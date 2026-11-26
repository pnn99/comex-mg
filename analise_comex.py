
"""Coleta, limpa, trata e visualiza exportações municipais de Minas Gerais."""

import argparse
import hashlib
import os
import re
import ssl
import time
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from tempfile import NamedTemporaryFile

import matplotlib.pyplot as plt
import pandas as pd
import requests


# ================= CONFIGURAÇÕES =================

ANO_INICIAL = 2015
UF = "MG"
PREFIXO_MUNICIPAL = "31"  # Prefixo dos municípios mineiros no catálogo.
TAMANHO_BLOCO = 150_000

PASTA = Path(__file__).resolve().parent
BRUTOS = PASTA / "dados" / "brutos"
TRATADOS = PASTA / "dados" / "tratados"
GRAFICOS = PASTA / "graficos"

API_MUNICIPAL = "https://api-comexstat.mdic.gov.br/cities"
CAMPOS_MENSAIS = {"year", "monthNumber", "metricKG", "metricFOB"}

COLUNAS = [
    "CO_ANO",
    "CO_MES",
    "SH4",
    "CO_PAIS",
    "SG_UF_MUN",
    "CO_MUN",
    "KG_LIQUIDO",
    "VL_FOB",
]


# ================= DOWNLOAD =================

def requisitar(metodo, url, **opcoes):
    """Usa a confiança padrão do Requests e respeita o PEM definido pelo usuário."""
    opcoes.setdefault("timeout", (30, 180))
    opcoes["headers"] = {"User-Agent": "COMEX-MG/1.0"}
    try:
        return requests.request(metodo, url, **opcoes)
    except requests.exceptions.SSLError as erro:
        if "CERTIFICATE_VERIFY_FAILED" not in str(erro):
            raise
        if os.getenv("REQUESTS_CA_BUNDLE") or os.getenv("CURL_CA_BUNDLE"):
            raise
        sistema = ssl.get_default_verify_paths().cafile
        if not sistema or Path(sistema).resolve() == Path(requests.certs.where()).resolve():
            raise
        print("Verificando a conexão com os certificados de confiança do sistema.")
        return requests.request(metodo, url, verify=sistema, **opcoes)


def consultar_api(metodo, url, **opcoes):
    for tentativa in range(3):
        with requisitar(metodo, url, **opcoes) as resposta:
            if metodo == "POST" or resposta.status_code != 429 or tentativa == 2:
                resposta.raise_for_status()
                resultado = resposta.json()
                break
            espera = resposta.headers.get("Retry-After", "")
            if espera and (not espera.isdigit() or int(espera) > 120):
                raise requests.HTTPError(f"Limite da API atingido. Retome após Retry-After: {espera}")
            segundos = int(espera) if espera else 30 * (tentativa + 1)
        print(f"Limite da API atingido. Nova tentativa em {segundos} s.")
        time.sleep(segundos)
    if not isinstance(resultado, dict) or resultado.get("success") is not True:
        raise ValueError(f"Resposta sem confirmação de sucesso em {url}")
    return resultado["data"]


def registros_api(dados, origem, campos):
    """Lê registros nomeados em lista direta, no campo list ou em listas agrupadas."""
    itens = dados.get("list") if isinstance(dados, dict) else dados
    if not isinstance(itens, list):
        raise ValueError(f"{origem}: esperava uma lista de registros em data ou data.list.")
    for item in itens:
        # Alguns catálogos incluem o idioma ao lado da lista de opções.
        if isinstance(item, str) and item in ("pt", "en", "es"):
            continue
        grupo = item if isinstance(item, list) else [item]
        for registro in grupo:
            if not isinstance(registro, dict) or not campos.issubset(registro):
                estrutura = list(registro) if isinstance(registro, dict) else type(registro).__name__
                raise ValueError(f"{origem}: registro com estrutura {estrutura}; "
                                 f"campos esperados: {sorted(campos)}.")
            yield registro


def limite_publicado():
    encerrado = date.today().replace(day=1) - timedelta(days=1)
    try:
        dados = consultar_api("GET", f"{API_MUNICIPAL}/dates/updated")
        publicado = date(int(dados["year"]), int(dados["monthNumber"]), 1)
        if publicado.year < ANO_INICIAL:
            raise ValueError(f"Data de cobertura inválida: {publicado}")
    except (OSError, ValueError, KeyError, TypeError) as erro:
        print(f"Publicação municipal não confirmada pela API ({erro}). "
              "O corte usará os meses disponíveis no CSV até o último mês encerrado.")
        return encerrado
    print(f"Último mês informado pela API municipal: {publicado:%m/%Y}")
    return min(encerrado, publicado)


def sha256(arquivo):
    resumo = hashlib.sha256()
    with arquivo.open("rb") as entrada:
        for bloco in iter(lambda: entrada.read(1024 * 1024), b""):
            resumo.update(bloco)
    return resumo.hexdigest()


@lru_cache(maxsize=1)
def filtro_mg():
    """Resolve o identificador estadual no mesmo catálogo usado por POST /cities."""
    origem = f"{API_MUNICIPAL}/filters/state"
    dados = consultar_api("GET", origem, params={"language": "pt"})
    ids = []
    for item in registros_api(dados, origem, {"id", "text"}):
        rotulo = str(item["text"]).upper()
        if re.search(r"\bMINAS GERAIS\b|\bMG\b", rotulo):
            ids.append(item["id"])
    if len(ids) != 1:
        raise ValueError(f"Catálogo estadual sem identificador único para Minas Gerais: {ids}.")
    return ids[0]


@lru_cache(maxsize=3)
def catalogo_api(campo):
    itens = consultar_api("GET", f"{API_MUNICIPAL}/filters/{campo}", params={"language": "pt"})
    nomes = {}
    for item in registros_api(itens, f"GET /cities/filters/{campo}", {"id", "text"}):
        codigo = str(item["id"])
        if campo == "city" and not codigo.startswith(PREFIXO_MUNICIPAL):
            continue
        nome = str(item["text"]).strip().casefold()
        # As tabelas podem exibir o código antes da descrição ou a UF após o nome.
        sem_codigo = re.sub(r"^\d+\s*[-–]\s*", "", nome)
        variantes = {nome, sem_codigo}
        if campo == "city":
            variantes.add(re.sub(r"\s*(?:[-/]\s*mg|\(mg\))$", "", sem_codigo).strip())
        for chave in variantes:
            nomes.setdefault(chave, set()).add(codigo)
    return nomes


def codigo_api(linha, campo, largura):
    chaves = [f"{campo}Code", f"{campo}Id", campo, f"{campo}Name"]
    if campo == "city":
        chaves.append("noMunMinsgUf")
    for chave in chaves:
        valor = str(linha.get(chave, "")).strip()
        if not valor:
            continue
        if not valor.isdecimal():
            nome = valor.casefold()
            if campo == "city":
                nome = re.sub(r"\s*(?:[-/]\s*mg|\(mg\))$", "", nome).strip()
            candidatos = catalogo_api(campo).get(nome, set())
            if len(candidatos) != 1:
                continue
            valor = next(iter(candidatos))
        if valor.isdecimal() and len(valor) <= largura:
            return valor.zfill(largura)
    raise ValueError(f"Código de {campo} ausente ou ambíguo no registro {linha!r}.")


def lote_atual(destino):
    """Resolve a revisão escolhida, preservando o primeiro CSV e cada versão recebida."""
    referencia = destino.parent / "versoes" / (destino.stem + ".sha256")
    if not referencia.exists():
        return destino
    digest = referencia.read_text().strip()
    if not re.fullmatch(r"[a-f0-9]{64}",digest):
        raise ValueError(f"Referência de versão inválida: {referencia}")
    revisao = referencia.parent / f"{destino.stem}_{digest}.csv"
    if destino.exists() and sha256(destino)==digest:
        return destino
    if not revisao.exists() or sha256(revisao)!=digest:
        raise ValueError(f"Lote com hash divergente: {revisao}")
    return revisao


def obter_arquivos(ano, ultimo_mes, atualizar=False):
    """Obtém um lote anual de MG com um único POST e mantém o mês de cada linha."""
    pasta = BRUTOS / "api_mg"
    destino = pasta / f"EXP_MG_{ano}_01-{ultimo_mes:02}.csv"
    if destino.is_file() and not atualizar:
        print(f"Lote anual encontrado: {destino.name}")
        return lote_atual(destino)

    # O filtro de municípios reforça o recorte fiscal no próprio pedido:
    # o serviço já devolveu "Estância - SE" em resposta ao filtro estadual isolado.
    municipios = sorted({codigo for ids in catalogo_api("city").values() for codigo in ids
                         if len(codigo) == 7 and codigo.isdecimal()})
    if not municipios:
        raise ValueError("Catálogo sem municípios de MG para a consulta anual.")
    consulta = {
        "flow": "export", "monthDetail": True,
        "period": {"from": f"{ano}-01", "to": f"{ano}-{ultimo_mes:02}"},
        "filters": [{"filter": "state", "values": [filtro_mg()]},
                    {"filter": "city", "values": municipios}],
        "details": ["city", "heading", "country"], "metrics": ["metricFOB", "metricKG"],
    }
    print(f"Consultando MG em um lote: 01/{ano} a {ultimo_mes:02}/{ano}.", flush=True)
    resposta = consultar_api("POST", API_MUNICIPAL, params={"language": "pt"}, json=consulta)
    permitidos = set(municipios)
    linhas = []
    for linha in registros_api(resposta, f"POST /cities ({ano})", CAMPOS_MENSAIS):
        mes = int(linha["monthNumber"])
        if int(linha["year"]) != ano or not 1 <= mes <= ultimo_mes:
            raise ValueError(f"Competência fora do lote de {ano}: {linha['year']}-{mes:02}.")
        rotulo = str(linha.get("noMunMinsgUf") or linha.get("city") or linha.get("cityName") or "")
        sigla = re.search(r"(?:[-/]|\()\s*([A-Za-z]{2})\)?$", rotulo.strip())
        if sigla and sigla[1].upper() != UF:
            raise ValueError(f"A API devolveu {rotulo} no lote de MG de {ano}. Lote rejeitado.")
        cidade = codigo_api(linha, "city", 7)
        if cidade not in permitidos:
            raise ValueError(f"Município fora do catálogo de MG no lote de {ano}: {cidade}.")
        linhas.append((ano, mes, codigo_api(linha, "heading", 4), codigo_api(linha, "country", 3),
                       UF, cidade, int(str(linha["metricKG"])), int(str(linha["metricFOB"]))))
    quadro = pd.DataFrame(linhas, columns=COLUNAS)
    if set(quadro["CO_MES"]) != set(range(1, ultimo_mes + 1)):
        raise ValueError(f"Cobertura mensal incompleta no lote da API de {ano}.")
    if quadro.duplicated(COLUNAS[:6]).any() or (quadro[["KG_LIQUIDO", "VL_FOB"]] < 0).any().any():
        raise ValueError(f"Chaves duplicadas ou medidas negativas no lote de {ano}.")

    # Quando há um bruto independente no projeto, reconcilia sem outra chamada HTTP.
    nacional = BRUTOS / f"EXP_{ano}_MUN.csv"
    if nacional.is_file():
        referencia = ler_e_tratar(nacional, ano, ultimo_mes)
        medidas = ["KG_LIQUIDO", "VL_FOB"]
        if not quadro.groupby("CO_MES")[medidas].sum().equals(referencia.groupby("CO_MES")[medidas].sum()):
            raise ValueError(f"Totais mensais do lote de {ano} divergem do bruto local {nacional.name}.")

    pasta.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=pasta, suffix=".part", delete=False) as tmp:
        temporario = Path(tmp.name)
    try:
        quadro.to_csv(temporario, sep=";", index=False)
        try:
            destino.hardlink_to(temporario)
            return destino
        except FileExistsError:
            pass
        digest = sha256(temporario)
        atual = lote_atual(destino)
        if sha256(atual) == digest:
            return atual
        historico = pasta / "versoes"
        historico.mkdir(exist_ok=True)
        revisao = historico / f"{destino.stem}_{digest}.csv"
        if sha256(destino)==digest:
            revisao = destino
        else:
            try:
                revisao.hardlink_to(temporario)
            except FileExistsError:
                if sha256(revisao)!=digest:
                    raise ValueError(f"Revisão local divergente: {revisao}")
        with NamedTemporaryFile(dir=historico,mode="w",delete=False) as ponteiro:
            ponteiro.write(digest)
        Path(ponteiro.name).replace(historico / (destino.stem+".sha256"))
        return revisao
    finally:
        temporario.unlink(missing_ok=True)


def ler_blocos(arquivos):
    tipos = {
        "SH4": "string",
        "CO_PAIS": "string",
        "CO_MUN": "string",
        "SG_UF_MUN": "string",
    }

    for caminho in arquivos:
        with pd.read_csv(caminho, sep=";", encoding="utf-8-sig", dtype=tipos,
                         chunksize=TAMANHO_BLOCO) as leitor:
            yield from leitor


def ler_e_tratar(arquivo, ano, ultimo_mes=12):
    """Lê o arquivo nacional ou os meses municipais e trata o recorte de MG."""
    partes = []
    arquivos = arquivo if isinstance(arquivo, list) else [arquivo]
    for bloco in ler_blocos(arquivos):

        # Conferir colunas
        faltantes = set(COLUNAS) - set(bloco.columns)

        if faltantes:
            raise ValueError(
                f"Colunas ausentes: {sorted(faltantes)}"
            )

        # Filtrar Minas Gerais
        filtro = (
            bloco["SG_UF_MUN"]
            .str.strip()
            .str.upper()
            .eq(UF)
        )

        dados_mg = bloco.loc[filtro, COLUNAS].copy()

        if dados_mg.empty:
            continue

        for coluna, largura in [("SH4",4),("CO_PAIS",3),("CO_MUN",7)]:
            codigo = dados_mg[coluna].str.strip()
            if not codigo.str.fullmatch(rf"[0-9]{{1,{largura}}}").fillna(False).all():
                raise ValueError(f"Código ausente ou inválido em {coluna} no ano {ano}.")
            dados_mg[coluna] = codigo.str.zfill(largura)
        for coluna in ["CO_ANO","CO_MES","KG_LIQUIDO","VL_FOB"]:
            valores = pd.to_numeric(dados_mg[coluna],errors="raise")
            if valores.isna().any() or not valores.ge(0).all() or not valores.mod(1).eq(0).all():
                raise ValueError(f"Medida ausente, negativa ou fracionária em {coluna}, ano {ano}.")
            dados_mg[coluna] = valores.astype("int64")
        if not dados_mg.CO_ANO.eq(ano).all() or not dados_mg.CO_MES.between(1,12).all():
            raise ValueError(f"Competência fora do arquivo de {ano}.")
        dados_mg = dados_mg[dados_mg.CO_MES.le(ultimo_mes)].copy()
        dados_mg["SG_UF_MUN"] = UF

        if not dados_mg.empty:
            partes.append(dados_mg)

    if not partes:
        raise ValueError(
            f"Nenhum registro encontrado para {UF} em {ano}."
        )

    dados = pd.concat(partes, ignore_index=True)

    chave = ["CO_ANO", "CO_MES", "CO_MUN", "SH4", "CO_PAIS"]
    if dados.duplicated(chave).any():
        raise ValueError(f"Chave municipal duplicada em {ano}: {chave}.")

    meses = set(dados["CO_MES"])
    faltantes = set(range(1, max(meses) + 1)) - meses
    if faltantes:
        raise ValueError(f"Meses ausentes para {UF} em {ano}: {sorted(faltantes)}")

    # Criar coluna de data
    dados["DATA"] = pd.to_datetime({
        "year": dados["CO_ANO"],
        "month": dados["CO_MES"],
        "day": 1,
    })

    return dados


# ================= VISUALIZAÇÃO =================

def visualizar(dados):
    """Gera gráficos das exportações de Minas Gerais."""

    GRAFICOS.mkdir(parents=True, exist_ok=True)
    periodo = f"{dados['DATA'].min():%m/%Y} a {dados['DATA'].max():%m/%Y}"

    # 1. Exportações mensais
    mensal = (
        dados.groupby("DATA")["VL_FOB"]
        .sum()
        .sort_index()
        / 1_000_000
    )

    ax = mensal.plot(
        figsize=(10, 5),
        marker="o",
        title=f"Exportações mensais de Minas Gerais ({periodo})",
    )

    ax.set_xlabel("Mês")
    ax.set_ylabel("Valor FOB (US$ milhões)")
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(
        GRAFICOS / "01_exportacoes_mensais.png",
        dpi=160,
    )
    plt.close()

    # 2. Dez produtos SH4 mais exportados
    produtos = (
        dados.groupby("SH4")["VL_FOB"]
        .sum()
        .nlargest(10)
        .sort_values()
        / 1_000_000
    )

    ax = produtos.plot(
        kind="barh",
        figsize=(10, 6),
        title=f"Dez produtos SH4 mais exportados por MG ({periodo})",
    )

    ax.set_xlabel("Valor FOB (US$ milhões)")
    ax.set_ylabel("Código SH4")

    plt.tight_layout()
    plt.savefig(
        GRAFICOS / "02_top10_produtos_sh4.png",
        dpi=160,
    )
    plt.close()

    # 3. EUA versus demais destinos
    destino = dados.copy()

    destino["GRUPO_PAIS"] = destino["CO_PAIS"].apply(
        lambda codigo: "EUA" if codigo == "249"
        else "Outros destinos"
    )

    evolucao = (
        destino.groupby(["DATA", "GRUPO_PAIS"])["VL_FOB"]
        .sum()
        .unstack(fill_value=0)
        .sort_index()
        / 1_000_000
    )

    ax = evolucao.plot(
        figsize=(10, 5),
        marker="o",
        title=f"Exportações de MG: EUA e demais destinos ({periodo})",
    )

    ax.set_xlabel("Mês")
    ax.set_ylabel("Valor FOB (US$ milhões)")
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(
        GRAFICOS / "03_eua_outros_destinos.png",
        dpi=160,
    )
    plt.close()

    print("Gráficos gerados com sucesso.")


# ================= EXECUÇÃO =================

def executar(desde_lotes=False):
    if desde_lotes:
        encerrado = date.today().replace(day=1) - timedelta(days=1)
        competencias = []
        for lote in (BRUTOS / "api_mg").glob("EXP_MG_*_01-*.csv"):
            m = re.fullmatch(r"EXP_MG_(\d{4})_01-(\d{2})\.csv",lote.name)
            if m:
                competencia = date(int(m[1]),int(m[2]),1)
                if competencia <= encerrado:
                    competencias.append(competencia)
        if not competencias:
            raise ValueError("Nenhum lote anual local elegível para reconstrução.")
        limite = max(competencias)
    else:
        limite = limite_publicado()
    print(f"Período solicitado: 01/{ANO_INICIAL} a {limite:%m/%Y}")
    TRATADOS.mkdir(parents=True, exist_ok=True)

    tabelas = []

    for ano in range(ANO_INICIAL, limite.year + 1):
        ano_final = ano == limite.year
        ultimo_mes = limite.month if ano_final else 12

        cache = BRUTOS / "api_mg" / f"EXP_MG_{ano}_01-{ultimo_mes:02}.csv"
        if desde_lotes:
            arquivo = lote_atual(cache)
            if not arquivo.is_file():
                raise ValueError(f"Lote obrigatório ausente: {arquivo}")
        else:
            try:
                arquivo = obter_arquivos(ano, ultimo_mes, atualizar=ano_final)
            except requests.RequestException as erro:
                arquivo = lote_atual(cache)
                if not arquivo.is_file():
                    arquivo = BRUTOS / f"EXP_{ano}_MUN.csv"
                if not arquivo.is_file():
                    raise
                print(f"Atualização indisponível. Verificando a cópia local. {erro}")

        # Leitura, limpeza e tratamento
        dados_ano = ler_e_tratar(arquivo, ano, ultimo_mes)
        if desde_lotes and dados_ano.CO_MES.max() != ultimo_mes:
            raise ValueError(f"Cobertura incompatível com o nome do lote de {ano}.")
        if not ano_final and dados_ano["CO_MES"].max() < 12:
            raise ValueError(f"A série de {ano} termina antes de dezembro.")
        if ano_final and dados_ano["CO_MES"].max() < ultimo_mes:
            print(f"Último mês disponível na base: {dados_ano['DATA'].max():%m/%Y}")

        tabelas.append(dados_ano)

        print(
            f"{ano}: {len(dados_ano):,} registros "
            f"de Minas Gerais carregados."
        )

    # Unificar os anos
    dados = pd.concat(
        tabelas,
        ignore_index=True,
    ).sort_values("DATA")

    # Salvar CSV tratado
    saida = TRATADOS / f"exportacoes_{UF.lower()}_atual.csv"
    with NamedTemporaryFile(dir=TRATADOS,suffix=".part",delete=False) as tmp:
        temporario = Path(tmp.name)
    try:
        dados.to_csv(temporario, sep=";", index=False, encoding="utf-8-sig")
        temporario.replace(saida)
    finally:
        temporario.unlink(missing_ok=True)
    print(f"Cobertura da base: {dados['DATA'].min():%m/%Y} a {dados['DATA'].max():%m/%Y}")

    # Gerar gráficos
    visualizar(dados)

    print(f"\nDados tratados salvos em: {saida}")
    print(f"Gráficos salvos em: {GRAFICOS}")

    print("\nPrévia dos dados:")
    print(dados.head().to_string(index=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    modos = parser.add_mutually_exclusive_group()
    modos.add_argument(
        "--baixar-anos", nargs="+", type=int, metavar="ANO",
        help="Baixa apenas os anos indicados, um por vez, sem gerar a análise.",
    )
    modos.add_argument(
        "--somente-graficos", action="store_true",
        help="Regera os três gráficos históricos a partir do consolidado local.",
    )
    modos.add_argument("--desde-lotes",action="store_true",help="Reconstrói o consolidado com os lotes municipais locais.")
    args = parser.parse_args()
    try:
        if args.somente_graficos:
            base = TRATADOS / f"exportacoes_{UF.lower()}_atual.csv"
            if not base.is_file():
                parser.error(f"Base tratada ausente: {base}. Execute a coleta ou use o CSV do repositório.")
            dados = pd.read_csv(base, sep=";", usecols=["DATA", "VL_FOB", "SH4", "CO_PAIS"],
                                parse_dates=["DATA"], dtype={"SH4": "string", "CO_PAIS": "string"})
            visualizar(dados)
        elif args.baixar_anos:
            limite = limite_publicado()
            if any(ano < ANO_INICIAL or ano > limite.year for ano in args.baixar_anos):
                parser.error(f"Informe anos entre {ANO_INICIAL} e {limite.year}.")
            for ano in sorted(set(args.baixar_anos)):
                ano_final = ano == limite.year
                obter_arquivos(ano, limite.month if ano_final else 12, atualizar=ano_final)
        else:
            executar(args.desde_lotes)
    except (requests.RequestException, ValueError, KeyError, RuntimeError) as erro:
        parser.exit(1, f"{erro}\n")

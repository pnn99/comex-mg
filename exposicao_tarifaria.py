"""Composição estadual e nacional prévia e limites da exposição municipal."""
import argparse
import os
import re
from collections import defaultdict
from functools import lru_cache
import unicodedata
from pathlib import Path
from tempfile import NamedTemporaryFile

import numpy as np
import pandas as pd
import requests

from analise_comex import consultar_api, registros_api, requisitar
from preparar_tarifas import ler_excecoes_2026, obter_lista
from regimes_comerciais import RAIZ, SECAO, calendario, salvar
from panorama_comercial import PAR, fluxos, ler_base, proporcao

NCM = RAIZ / "dados/brutos/ncm"
URL = "https://balanca.mdic.gov.br/balanca/bd/comexstat-bd/ncm/EXP_{}.csv"
CAFE = {"09011100","09011200","09012100","09012200","09019010","09019020"}
CAMPOS_NCM = ["CO_ANO","CO_MES","CO_NCM","CO_PAIS","SG_UF_NCM","VL_FOB","KG_LIQUIDO"]


def composicao_anual(arquivo, ano, *, lote_eua=False):
    partes, meses = [], set()
    chaves_api = set()
    for d in pd.read_csv(arquivo, sep=";", usecols=CAMPOS_NCM,
                         dtype={"CO_NCM":str,"CO_PAIS":str}, chunksize=150_000, encoding="latin1"):
        if (d.isna().any().any() or not d.CO_ANO.eq(ano).all() or not d.CO_MES.between(1,12).all()
                or not d.CO_NCM.str.fullmatch(r"\d{8}").all() or (d[["VL_FOB","KG_LIQUIDO"]]<0).any().any()):
            raise ValueError(f"Arquivo NCM inválido em {ano}.")
        if lote_eua:
            if not d.CO_PAIS.str.zfill(3).eq("249").all():
                raise ValueError(f"Lote da API de {ano} contém destino diferente dos EUA.")
            chaves = d[["CO_MES","CO_NCM","SG_UF_NCM"]]
            unicas = set(chaves.itertuples(index=False, name=None))
            if len(unicas) != len(d) or not chaves_api.isdisjoint(unicas):
                raise ValueError(f"Chave duplicada no lote da API de {ano}.")
            chaves_api.update(unicas)
        meses.update(d.CO_MES)
        d = d[d.CO_PAIS.str.zfill(3).eq("249")].copy()
        d["edicao"] = np.where((ano == 2022) & d.CO_MES.le(3), "SH2017", "SH2022")
        for area, t in [("BR",d),("MG",d[d.SG_UF_NCM.eq("MG")])]:
            partes.append(t.groupby(["edicao","CO_NCM"]).VL_FOB.sum().rename("fob_ncm").reset_index().assign(composicao=area))
    if meses != set(range(1,13)):
        raise ValueError(f"Cobertura nacional NCM incompleta em {ano}.")
    return pd.concat(partes).groupby(["edicao","CO_NCM","composicao"],as_index=False).fob_ncm.sum()


API_GERAL = "https://api-comexstat.mdic.gov.br/general"
METRICAS = ["VL_FOB", "KG_LIQUIDO"]
CODIGO_NCM = re.compile(r"([0-9]{7,8}|[0-9]{4}\.[0-9]{2}\.[0-9]{2})(?:\s*[-–—]\s*(.+))?", re.S)


class IdentificacaoNCMError(ValueError):
    """O retorno externo não permite identificar o produto com segurança."""


def nome_ncm(valor):
    return " ".join(unicodedata.normalize("NFC", valor).casefold().split())


@lru_cache(maxsize=1)
def catalogo_ncm():
    url = API_GERAL + "/filters/ncm"
    dados = consultar_api("GET", url, params={"language": "pt"})
    nomes = defaultdict(set)
    for item in registros_api(dados, url, {"id", "text"}):
        identificador = str(item["id"]).strip()
        texto = str(item["text"]).strip()
        if not re.fullmatch(r"[0-9]{7,8}", identificador) or not texto:
            raise IdentificacaoNCMError(f"Entrada inválida no catálogo NCM: {item!r}")
        codigo = identificador.zfill(8)
        prefixo = CODIGO_NCM.fullmatch(texto)
        if prefixo and prefixo[2]:
            if prefixo[1].replace(".", "").zfill(8) != codigo:
                raise IdentificacaoNCMError(f"Códigos conflitantes no catálogo NCM: {item!r}")
            texto = prefixo[2]
        nomes[nome_ncm(texto)].add(codigo)
    return nomes


def candidatos_ncm(item):
    rotulo = str(item.get("ncm") or item.get("ncmName") or "").strip()
    codigos = set()
    for campo in ("coNcm", "ncmCode", "ncmId", "CO_NCM", "ncm"):
        valor = item.get(campo)
        if valor is None or valor == "":
            continue
        codigo = CODIGO_NCM.fullmatch(str(valor).strip())
        if codigo:
            codigos.add(codigo[1].replace(".", "").zfill(8))
        elif campo != "ncm":
            raise IdentificacaoNCMError(f"Identificador inválido da API geral: {campo}={valor!r}")
    if len(codigos) > 1:
        raise IdentificacaoNCMError(f"Identificadores NCM conflitantes: {sorted(codigos)}")
    if codigos:
        return codigos
    candidatos = catalogo_ncm().get(nome_ncm(rotulo))
    if not candidatos:
        raise IdentificacaoNCMError(f"Descrição ausente do catálogo oficial de NCM: {rotulo!r}")
    return candidatos


def consultar_fluxos_ncm(ano, meses, detalhado, filtro_ncm=()):
    inicio, fim = meses
    filtros = [{"filter": "country", "values": [249]}]
    if filtro_ncm:
        filtros.append({"filter": "ncm", "values": sorted(filtro_ncm)})
    consulta = {
        "flow": "export", "period": {"from": f"{ano}-{inicio:02}", "to": f"{ano}-{fim:02}"},
        "monthDetail": True, "filters": filtros, "metrics": ["metricFOB", "metricKG"],
        "details": ["country", "state", "ncm"] if detalhado else ["country", "state"],
    }
    dados = consultar_api("POST", API_GERAL, params={"language": "pt"}, json=consulta)
    linhas = []
    for item in registros_api(dados, API_GERAL, {"year", "monthNumber", "metricFOB", "metricKG"}):
        pais = str(item.get("countryCode") or item.get("country") or "").strip().casefold()
        if pais not in {"249", "estados unidos", "estados unidos da américa", "249 - estados unidos"}:
            raise ValueError(f"Destino sem confirmação na API geral: {pais!r}")
        estado = str(item.get("state") or item.get("stateCode") or "").strip()
        if not estado:
            raise ValueError("UF ausente na resposta da API geral.")
        uf = "MG" if re.fullmatch(r"MG|31|Minas Gerais|(?:31|MG) - Minas Gerais|Minas Gerais [-–] MG",
                                  estado, re.I) else estado
        mes = int(item["monthNumber"])
        fob, kg = int(str(item["metricFOB"])), int(str(item["metricKG"]))
        if int(item["year"]) != ano or not inicio <= mes <= fim or min(fob, kg) < 0:
            raise ValueError("Totais de controle inválidos: competência ou fluxo fora da consulta.")
        ncm = ""
        if detalhado:
            candidatos = candidatos_ncm(item)
            if filtro_ncm:
                candidatos = candidatos.intersection(filtro_ncm)
                if len(candidatos) != 1:
                    raise IdentificacaoNCMError("A resposta não respeitou o filtro de códigos NCM.")
            # As tuplas preservam ambiguidades até a consulta filtrada.
            ncm = next(iter(candidatos)) if len(candidatos) == 1 else tuple(sorted(candidatos))
        linhas.append((ano, mes, ncm, "249", uf, fob, kg))
    return pd.DataFrame(linhas, columns=CAMPOS_NCM).astype({m: "int64" for m in METRICAS})


def totais_ncm(tabela):
    return tabela.groupby(["CO_MES", "SG_UF_NCM"])[METRICAS].sum().sort_index()


def desambiguar_ncm(detalhe, ano, meses):
    ambiguos = {grupo for grupo in detalhe.CO_NCM if isinstance(grupo, tuple)}
    if not ambiguos:
        return detalhe
    # Cada lote contém no máximo um candidato de cada descrição ambígua.
    codigos = set()
    lotes = defaultdict(set)
    for grupo in sorted(ambiguos):
        if codigos.intersection(grupo):
            raise IdentificacaoNCMError("Descrições ambíguas com conjuntos de NCM sobrepostos.")
        codigos.update(grupo)
        for posicao, codigo in enumerate(grupo):
            lotes[posicao].add(codigo)
    revisar = detalhe.CO_NCM.isin(codigos | ambiguos)
    novos = pd.concat([consultar_fluxos_ncm(ano, meses, True, lote) for lote in lotes.values()],
                      ignore_index=True)
    # Inclui códigos explícitos do grupo na conferência para evitar dupla contagem.
    for grupo in ambiguos:
        original = detalhe[detalhe.CO_NCM.isin({grupo, *grupo})]
        filtrado = novos[novos.CO_NCM.isin(grupo)]
        if not totais_ncm(original).equals(totais_ncm(filtrado)):
            raise ValueError(f"Totais de controle divergentes na desambiguação das NCM {grupo}.")
    return pd.concat([detalhe[~revisar], novos], ignore_index=True)


def lote_api_ncm(ano):
    """Obtém os fluxos para os EUA e reconcilia FOB e kg por mês e UF."""
    meses = (1, 12)
    referencia = consultar_fluxos_ncm(ano, meses, False)
    if (set(referencia.CO_MES) != set(range(1, 13)) or "MG" not in set(referencia.SG_UF_NCM)
            or referencia.SG_UF_NCM.nunique() < 2 or referencia.duplicated(CAMPOS_NCM[:5]).any()):
        raise ValueError(f"Cobertura, UF ou chave inconsistente no controle da API geral de {ano}.")
    detalhe = consultar_fluxos_ncm(ano, meses, True)
    controle = totais_ncm(referencia)
    # A API limita o número de linhas. Refaz apenas as competências divergentes.
    obtido, esperado = totais_ncm(detalhe).align(controle)
    divergentes = obtido.ne(esperado).any(axis=1)
    refazer = sorted(set(divergentes[divergentes].index.get_level_values("CO_MES")))
    partes = [detalhe[~detalhe.CO_MES.isin(refazer)]]
    for mes in refazer:
        print(f"Reconciliando lote NCM de {mes:02}/{ano} com o controle mensal.", flush=True)
        mensal = consultar_fluxos_ncm(ano, (mes, mes), True)
        if not totais_ncm(mensal).equals(controle.loc[[mes]]):
            raise ValueError(f"Totais de controle da API geral divergem em {mes:02}/{ano}.")
        partes.append(mensal)
    detalhe = desambiguar_ncm(pd.concat(partes, ignore_index=True), ano, meses)
    if detalhe.duplicated(CAMPOS_NCM[:5]).any() or not totais_ncm(detalhe).equals(controle):
        raise ValueError(f"Chave duplicada ou totais de controle da API geral divergentes em {ano}.")
    return detalhe.sort_values(CAMPOS_NCM[:5], ignore_index=True)


def composicoes(baixar):
    partes = []
    for ano in (2022,2023,2024):
        destino = NCM / f"EXP_{ano}.csv"
        api = NCM / f"API_EXP_EUA_{ano}.csv"
        if not destino.exists() and api.exists():
            destino = api
        if destino.exists():
            partes.append(composicao_anual(destino, ano, lote_eua=destino == api))
            continue
        if not baixar:
            return None
        NCM.mkdir(parents=True,exist_ok=True)
        with NamedTemporaryFile(dir=NCM, delete=False) as tmp:
            temporario = Path(tmp.name)
        try:
            try:
                with requisitar("GET", URL.format(ano),stream=True) as r:
                    r.raise_for_status()
                    with temporario.open("wb") as f:
                        for bloco in r.iter_content(1024*1024):
                            f.write(bloco)
            except requests.RequestException as erro:
                print(f"Arquivo nacional indisponível. Consultando a API geral para {ano}. {erro}", flush=True)
                try:
                    dados = lote_api_ncm(ano)
                except (requests.RequestException, IdentificacaoNCMError) as api_erro:
                    print(f"Aquisição NCM indisponível: {api_erro}",flush=True)
                    return None
                dados.to_csv(temporario,sep=";",index=False,encoding="latin1")
                destino = api
            partes.append(composicao_anual(temporario, ano, lote_eua=destino == api))
            os.link(temporario,destino)
            print(f"Lote NCM validado e salvo em {destino.name}.", flush=True)
        finally:
            temporario.unlink(missing_ok=True)
    t = pd.concat(partes).groupby(["composicao","edicao","CO_NCM"],as_index=False).fob_ncm.sum()
    t["SH4"] = t.CO_NCM.str[:4]
    t["SH6"] = t.CO_NCM.str[:6]
    return t


def listas():
    l = pd.read_csv(obter_lista(),sep=";",dtype=str)
    inicial = l[l.ato.eq("EO14323")]
    novas = l[l.ato.eq("EO14361")]
    extra = ler_excecoes_2026()
    # Subconjunto incondicional conferido nas versões dos três anexos recíprocos.
    minerais = {"26020000","26030000","26050000","26060000","26080000","26100000"}
    setembro = minerais | {"26040000","26090000"}
    res = {medida:(itens,itens) for medida,itens in [
        ("reciproca_inicial",minerais),("reciproca_setembro",setembro),("reciproca_agricola",setembro|CAFE)]}
    for medida, t in [("brasil_inicial", inicial), ("brasil_revisada", pd.concat([inicial,novas]))]:
        comuns = set(t.loc[t.tipo.eq("subposicao"),"HTS8"])
        # Dois textos oficiais divergem nesta linha. Mantém a subposição indeterminada.
        comuns -= {"31029000","31029001"}
        res[medida] = (comuns, set(t.HTS8))
    for nome, t in extra.groupby("medida"):
        res[nome] = (set(t.htsus), set(t.htsus))
    return res


def classificar(codigo, medida, regras, mesma_edicao=True):
    """Limites sob importação comercial ordinária. Código é SH4 ou SH6."""
    if not mesma_edicao:
        return 0., 1.
    comuns, todos = regras.get(medida, (set(),set()))
    if codigo.ljust(8,"0") in comuns or (codigo.startswith("0901") and CAFE <= comuns):
        return 0., 0.
    if medida in ("brasil_inicial","brasil_revisada") and codigo[:2] in {"07","08","09","10"}:
        if not any(c.startswith(codigo) for c in todos):
            return 1., 1.
    return 0., 1.


def limites_produto(produtos, comp, atos, regras):
    correspondencias, quadros = [], []
    for ato in atos[atos.aliquota.notna()].itertuples():
        base = pd.DataFrame({"SH4": sorted(produtos.SH4.unique())})
        base[["peso_min","peso_max"]] = [classificar(sh,ato.medida,regras) for sh in base.SH4]
        base["medida"] = ato.medida
        base["aliquota"] = ato.aliquota
        if comp is None:
            quadros.append(base.assign(composicao="limites_SH4",fob_composicao=np.nan))
            continue
        c = comp.copy()
        c[["min","max"]] = [classificar(sh,ato.medida,regras,versao=="SH2022")
                             for sh,versao in zip(c.SH6,c.edicao)]
        comuns, todos = regras.get(ato.medida,(set(),set()))
        por_sh6 = {}
        for codigo in sorted(todos):
            por_sh6.setdefault(codigo[:6],[]).append(codigo)
        c["htsus_candidatos"] = c.SH6.map({k:"|".join(v) for k,v in por_sh6.items()}).where(c.edicao.eq("SH2022"))
        correspondencias.append(c.assign(medida=ato.medida))
        c["usd_min"] = c.fob_ncm*c["min"]
        c["usd_max"] = c.fob_ncm*c["max"]
        for area, t in c.groupby("composicao"):
            soma = t.groupby("SH4")[["fob_ncm","usd_min","usd_max"]].sum()
            p = base.join(soma,on="SH4")
            for lim in ["min","max"]:
                p["peso_"+lim] = proporcao(p["usd_"+lim],p.fob_ncm).fillna(p["peso_"+lim])
            quadros.append(p[base.columns].assign(composicao=area,fob_composicao=p.fob_ncm))
    detalhe = pd.concat(correspondencias,ignore_index=True) if correspondencias else pd.DataFrame(
        columns=["CO_NCM","edicao","SH4","SH6","htsus_candidatos","medida","composicao","min","max","fob_ncm"])
    if comp is None:
        linhas = [(medida,c[:4],c[:6],c,c in comuns) for medida,(comuns,todos) in regras.items() for c in sorted(todos)]
        detalhe = pd.DataFrame(linhas,columns=["medida","SH4","SH6","htsus_candidatos","excecao_incondicional_listada"])
        detalhe["CO_NCM"] = pd.NA
        detalhe["situacao"] = "SH do anexo disponível; NCM comercial ausente"
    return pd.concat(quadros,ignore_index=True), detalhe


def municipais(produtos,pesos):
    linhas = []
    for (medida, area),p in pesos.groupby(["medida","composicao"]):
        t = produtos.merge(p,on="SH4",how="left",validate="many_to_one")
        if (t[["peso_min","peso_max"]].isna().any().any() or not t.peso_min.between(0,1).all()
                or not t.peso_max.between(0,1).all() or t.peso_min.gt(t.peso_max).any()):
            raise ValueError("Intervalo de exposição inválido.")
        for lim in ("min","max"):
            t["usd_"+lim] = t.eua*t["peso_"+lim]
        m = t.groupby("CO_MUN")[["total","eua","usd_min","usd_max"]].sum()
        m = m[m.total.gt(0)].copy()
        for lim in ("min","max"):
            for denom in ("eua","total"):
                coluna = "exposicao_"+denom+"_"+lim
                m[coluna] = proporcao(m["usd_"+lim],m[denom])
                m[coluna+"_ponderada"] = m[coluna]*p.aliquota.iloc[0]
        m["cobertura_fob_eua"] = proporcao(m.eua-m.usd_max+m.usd_min,m.eua)
        linhas.append(m.reset_index().assign(medida=medida,composicao=area))
    return pd.concat(linhas,ignore_index=True)


def executar(baixar=False):
    d = ler_base()
    produtos = fluxos(d[d.CO_ANO.between(2022,2024)],PAR).reset_index()
    produtos["total"] = produtos.eua + produtos.outros
    pesos, detalhe = limites_produto(produtos,composicoes(baixar),calendario(),listas())
    m = municipais(produtos,pesos)
    cobertura = m.groupby(["medida","composicao"])[["usd_min","usd_max","total","eua"]].sum().reset_index()
    cobertura["fracao_resolvida"] = proporcao(cobertura.eua-cobertura.usd_max+cobertura.usd_min,cobertura.eua)
    for t, nome in [(detalhe,"correspondencia_htsus_ncm"),(pesos,"exposicao_sh4_por_medida"),
                    (m,"exposicao_municipal_por_medida"),(cobertura,"cobertura_classificacao_tarifaria")]:
        salvar(t,nome,SECAO)
    print("Composição utilizada:", ", ".join(m.composicao.unique()))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baixar-ncm",action="store_true")
    executar(parser.parse_args().baixar_ncm)

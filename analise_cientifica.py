"""Indicadores municipais e cartografia da estrutura exportadora pré-choque."""
import argparse
import json
from pathlib import Path
from tempfile import NamedTemporaryFile

import matplotlib.pyplot as plt
from matplotlib.collections import PatchCollection
from matplotlib.colors import Normalize
from matplotlib.path import Path as Caminho
from matplotlib.patches import PathPatch, Patch
import numpy as np
import pandas as pd
import requests

RAIZ = Path(__file__).resolve().parent
BASE = RAIZ / "dados/tratados/exportacoes_mg_atual.csv"
MALHA = RAIZ / "dados/malhas/mg_municipios.geojson"
URL_MALHA = ("https://raw.githubusercontent.com/csmartins8/Mapas-de-Minas-Gerais/"
             "master/MG_municipios_simplificado.json")
SAIDA = RAIZ / "resultados/pre_choque"
MESES = pd.period_range("2022-01", "2024-12", freq="M")
METRICAS = ["hhi_produtos", "hhi_destinos", "participacao_eua", "cv_mensal"]
CHAVE = ["CO_MUN", "mes", "SH4", "CO_PAIS"]


def calcular_indicadores(dados):
    """Usa o FOB registrado na janela fixa, independentemente das linhas pós-2024."""
    pre = dados.loc[dados.CO_ANO.between(2022, 2024)].copy()
    if pre.empty or not pre.CO_MES.between(1, 12).all():
        raise ValueError("Janela pré-choque vazia ou mês inválido.")
    pre["mes"] = pd.to_datetime({"year": pre.CO_ANO, "month": pre.CO_MES, "day": 1}).dt.to_period("M")
    if set(pre.mes) != set(MESES):
        raise ValueError("A base de MG precisa cobrir todos os 36 meses de 2022 a 2024.")
    for campo, formato in [("CO_MUN", r"31[0-9]{5}"), ("SH4", r"[0-9]{4}"), ("CO_PAIS", r"[0-9]{3}")]:
        if not pre[campo].str.fullmatch(formato).fillna(False).all():
            raise ValueError(f"Código inválido em {campo}.")
    if not pre.SG_UF_MUN.eq("MG").fillna(False).all() or pre.duplicated(CHAVE).any():
        raise ValueError("UF inválida ou chave municipal duplicada.")
    if pre.VL_FOB.isna().any() or not np.isfinite(pre.VL_FOB).all() or (pre.VL_FOB < 0).any():
        raise ValueError("FOB inválido na janela pré-choque.")

    grupo = pre.groupby("CO_MUN")
    total = grupo.VL_FOB.sum()
    tabela = total[total > 0].rename("fob_pre_usd").to_frame()
    if tabela.empty:
        raise ValueError("Nenhum município com FOB positivo na janela.")
    pre = pre[pre.CO_MUN.isin(tabela.index)]
    mensal = pre.groupby(["CO_MUN", "mes"]).VL_FOB.sum().unstack().reindex(columns=MESES)
    tabela["meses_com_registro"] = mensal.notna().sum(axis=1)
    mensal = mensal.fillna(0)
    tabela["meses_ativos"] = mensal.gt(0).sum(axis=1)
    anual = pre.groupby(["CO_MUN", "CO_ANO"]).VL_FOB.sum().unstack(fill_value=0)
    tabela["anos_ativos"] = anual.gt(0).sum(axis=1)
    tabela["cv_mensal"] = mensal.std(axis=1, ddof=0) / mensal.mean(axis=1)
    eua = pre[pre.CO_PAIS == "249"].groupby("CO_MUN").VL_FOB.sum()
    tabela["fob_eua_pre_usd"] = eua.reindex(tabela.index, fill_value=0)
    tabela["participacao_eua"] = tabela.fob_eua_pre_usd / tabela.fob_pre_usd
    for campo, dimensao in [("SH4", "produtos"), ("CO_PAIS", "destinos")]:
        valores = pre.groupby(["CO_MUN", campo]).VL_FOB.sum()
        shares = valores.div(tabela.fob_pre_usd, level="CO_MUN")
        hhi = shares.pow(2).groupby(level="CO_MUN").sum()
        tabela[f"hhi_{dimensao}"] = hhi
        tabela[f"numero_efetivo_{dimensao}"] = 1 / hhi
        tabela[f"maior_participacao_{dimensao}"] = shares.groupby(level="CO_MUN").max()
    return tabela


def comparar_criterios(tabela):
    cenarios = {"minimo_1_mes": tabela.meses_ativos >= 1}
    cenarios.update({f"minimo_{n}_meses": tabela.meses_ativos >= n for n in (6, 12, 24, 36)})
    cenarios["positivo_nos_tres_anos"] = tabela.anos_ativos == 3
    cenarios["fob_a_partir_do_percentil_10"] = tabela.fob_pre_usd >= tabela.fob_pre_usd.quantile(.1)
    resumo = []
    for nome, mascara in cenarios.items():
        amostra = tabela.loc[mascara]
        linha = {"criterio": nome, "municipios": len(amostra),
                 "fracao_fob": amostra.fob_pre_usd.sum() / tabela.fob_pre_usd.sum(),
                 "mediana_fob_usd": amostra.fob_pre_usd.median()}
        linha.update(amostra[METRICAS].median().add_prefix("mediana_").to_dict())
        resumo.append(linha)
    return pd.DataFrame(resumo)


def ler_malha(arquivo):
    with arquivo.open(encoding="utf-8-sig") as f:
        features = json.load(f)["features"]
    geometrias = {}
    nomes = {}
    for feat in features:
        props = feat["properties"]
        codigo = str(props.get("CD_MUN") or props.get("id") or props.get("codarea"))
        if len(codigo) != 7 or not codigo.isdecimal() or not codigo.startswith("31") or codigo in geometrias:
            raise ValueError(f"Identificador cartográfico inválido ou duplicado: {codigo}")
        nomes[codigo] = props.get("NM_MUN") or props.get("name")
        geo = feat["geometry"]
        if geo["type"] not in ("Polygon", "MultiPolygon"):
            raise ValueError(f"Geometria inesperada para {codigo}.")
        poligonos = geo["coordinates"] if geo["type"] == "MultiPolygon" else [geo["coordinates"]]
        caminhos = []
        for poligono in poligonos:
            for i, anel in enumerate(poligono):
                xy = np.asarray(anel, dtype=float)[:, :2]
                if len(xy) < 4 or not np.array_equal(xy[0], xy[-1]) or not np.isfinite(xy).all():
                    raise ValueError(f"Anel inválido: {codigo}.")
                # Orienta exteriores e furos em sentidos opostos para o preenchimento.
                area = np.sum(xy[:-1, 0]*xy[1:, 1] - xy[1:, 0]*xy[:-1, 1])
                if (area > 0) != (i == 0):
                    xy = xy[::-1]
                caminhos.append(Caminho(xy, closed=True))
        geometrias[codigo] = PathPatch(Caminho.make_compound_path(*caminhos))
    if len(geometrias) != 853:
        raise ValueError(f"A malha precisa conter os 853 municípios de MG. Encontrados: {len(geometrias)}.")
    return geometrias, pd.Series(nomes, name="municipio")


def obter_malha(arquivo):
    if arquivo.is_file() or arquivo.resolve() != MALHA:
        return ler_malha(arquivo)

    print("Baixando a malha municipal de Minas Gerais.", flush=True)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    tmp = NamedTemporaryFile(dir=arquivo.parent, delete=False)
    temporario = Path(tmp.name)
    try:
        with tmp:
            with requests.get(URL_MALHA, timeout=(10, 90), stream=True) as resposta:
                resposta.raise_for_status()
                for bloco in resposta.iter_content(64 * 1024):
                    tmp.write(bloco)
        malha = ler_malha(temporario)
        temporario.replace(arquivo)
    finally:
        temporario.unlink(missing_ok=True)
    return malha


def desenhar_mapa(tabela, geometrias, destino, fonte):
    dados = tabela.reindex(geometrias.keys())
    cinza = "#dddddd"
    titulos = ["Concentração por produto", "Concentração por destino",
               "Participação dos EUA", "Volatilidade mensal"]
    escalas = ["HHI de produtos", "HHI de destinos", "% do FOB municipal", "Coeficiente de variação"]
    fig, eixos = plt.subplots(2, 2, figsize=(11, 10))
    fig.subplots_adjust(left=.05, right=.95, bottom=.15, top=.89, wspace=.15, hspace=.32)
    for ax, campo, titulo, escala in zip(eixos.flat, METRICAS, titulos, escalas):
        valores = dados[campo] * (100 if campo == "participacao_eua" else 1)
        vmax = {"participacao_eua": 100, "cv_mensal": max(1, np.ceil(tabela.cv_mensal.max()))}.get(campo, 1)
        cmap = plt.get_cmap("viridis").with_extremes(bad=cinza)
        colecao = PatchCollection(list(geometrias.values()), cmap=cmap, norm=Normalize(0, vmax),
                                  edgecolors="#ffffff", linewidths=.18)
        colecao.set_array(np.ma.masked_invalid(valores.to_numpy(dtype=float)))
        ax.add_collection(colecao)
        ax.autoscale_view()
        ax.set_aspect(1 / np.cos(np.deg2rad(18.5)))
        ax.axis("off")
        ax.set_title(titulo, loc="left", fontsize=13)
        barra = fig.colorbar(colecao, ax=ax, orientation="horizontal", fraction=.044, pad=.02, aspect=36)
        barra.set_label(escala)
    fig.suptitle("Estrutura exportadora dos municípios de Minas Gerais", fontsize=20, y=.97)
    fig.text(.5,.921,"Indicadores anteriores ao choque tarifário  |  Janeiro de 2022 a dezembro de 2024",
             ha="center", fontsize=11)
    fig.legend(handles=[Patch(facecolor=cinza, label="Sem FOB positivo registrado na janela")],
               loc="lower left", bbox_to_anchor=(.05,.065), frameon=False)
    fig.text(.06,.038,f"Exportações: Comex Stat / MDIC, domicílio fiscal.  Malha: {fonte}.", fontsize=8)
    fig.savefig(destino, dpi=190, facecolor="white")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=BASE)
    parser.add_argument("--malha", type=Path, default=MALHA, help="GeoJSON municipal de MG em graus (lon/lat).")
    parser.add_argument("--fonte-malha", help="Crédito cartográfico para a figura.")
    parser.add_argument("--saida", type=Path, default=SAIDA)
    args = parser.parse_args()
    if not args.base.is_file():
        parser.exit(1, f"Base ausente em {args.base}. Para gerar o consolidado, execute python analise_comex.py.\n")
    tipos = {c: "string" for c in ["CO_MUN", "CO_PAIS", "SH4", "SG_UF_MUN"]}
    colunas = [*tipos, "CO_ANO", "CO_MES", "VL_FOB"]
    dados = pd.read_csv(args.base, sep=";", usecols=colunas, dtype=tipos)
    tabela = calcular_indicadores(dados)
    try:
        geometrias, nomes = obter_malha(args.malha)
    except (OSError, ValueError, KeyError) as erro:
        parser.exit(1, f"Falha ao obter ou ler a malha municipal: {erro}\n")
    ausentes = tabela.index.difference(geometrias.keys())
    if len(ausentes):
        raise ValueError(f"Códigos Comex sem correspondência na malha: {ausentes.tolist()}")
    if nomes.notna().any():
        tabela.insert(0, "municipio", nomes.reindex(tabela.index))
    args.saida.mkdir(parents=True, exist_ok=True)
    fonte = args.fonte_malha or ("Mapas de Minas Gerais, versão simplificada"
                                 if args.malha.resolve() == MALHA else args.malha.name)
    desenhar_mapa(tabela, geometrias, args.saida / "mapa_indicadores_mg.png", fonte)
    tabela.to_csv(args.saida / "indicadores_municipais.csv", sep=";")
    comparar_criterios(tabela).to_csv(args.saida / "sensibilidade_inclusao.csv", sep=";", index=False)
    print(f"{len(tabela)} municípios com FOB positivo em 2022–2024. Resultados em {args.saida}")


if __name__ == "__main__":
    main()

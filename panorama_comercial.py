"""Panorama municipal do Comex MG e previsões estaduais de curto prazo."""
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from analise_cientifica import BASE, MALHA, RAIZ, calcular_indicadores, obter_malha
from analise_comex import sha256
from visualizar_panorama import gerar_visuais

SAIDA = RAIZ / "resultados/panorama"
PAR = ["CO_MUN", "SH4"]
MERCADOS = ["eua", "outros"]
FLUXOS = ["eua", "outros", "kg_eua", "kg_outros"]
HORIZONTE = 3


def ler_base():
    tipos = {c: "string" for c in ["CO_MUN", "SH4", "CO_PAIS", "SG_UF_MUN"]}
    df = pd.read_csv(BASE, sep=";", dtype=tipos, parse_dates=["DATA"])
    if df.isna().any().any() or not df.SG_UF_MUN.eq("MG").all():
        raise ValueError("Campos ausentes ou registros de outra UF.")
    df["mes"] = df.DATA.dt.to_period("M")
    if not (df.CO_ANO.eq(df.mes.dt.year) & df.CO_MES.eq(df.mes.dt.month)).all():
        raise ValueError("Ano e mês incompatíveis com DATA.")
    if df.duplicated(PAR + ["mes", "CO_PAIS"]).any() or (df[["VL_FOB","KG_LIQUIDO"]] < 0).any().any():
        raise ValueError("Chave duplicada ou fluxo negativo.")
    meses = pd.PeriodIndex(df.mes.unique()).sort_values()
    esperados = pd.period_range("2015-01", meses.max(), freq="M")
    if not meses.equals(esperados) or meses.max() < pd.Period("2026-07", "M"):
        raise ValueError("Cobertura mensal insuficiente para o panorama.")
    df["mercado"] = np.where(df.CO_PAIS.eq("249"), "eua", "outros")
    return df


def fluxos(dados, chaves):
    t = dados.groupby(chaves + ["mercado"])[["VL_FOB", "KG_LIQUIDO"]].sum().unstack(fill_value=0)
    res = pd.DataFrame(index=t.index)
    for destino in MERCADOS:
        res[destino] = t.get(("VL_FOB", destino), 0)
        res["kg_" + destino] = t.get(("KG_LIQUIDO", destino), 0)
    return res[FLUXOS]


def proporcao(numerador, denominador):
    return numerador.div(denominador.where(denominador > 0))


def razoes_produtos(t):
    t = t.copy()
    t["total"] = t.eua + t.outros
    t["fracao_eua"] = proporcao(t.eua, t.total)
    t["razao_eua_outros"] = proporcao(t.eua, t.outros)
    t["exclusivo_eua"] = t.eua.gt(0) & t.outros.eq(0)
    return t


def indicadores(pre, pares_pre):
    t = calcular_indicadores(pre)
    eua = pares_pre.eua.reset_index().sort_values(["CO_MUN","eua","SH4"], ascending=[True,False,True])
    maior = eua.drop_duplicates("CO_MUN").set_index("CO_MUN")
    t["sh4_principal_eua"] = maior.SH4.where(maior.eua.gt(0))
    t["vulnerabilidade_pct"] = 100 * maior.eua.reindex(t.index) / t.fob_pre_usd
    for minimo in (1, 12, 24):
        score = t.vulnerabilidade_pct.where(t.meses_ativos.ge(minimo))
        t[f"posicao_min_{minimo}m"] = score.rank(ascending=False, method="min").astype("Int64")
    return t


def comparar(pares, nome_a, nome_b):
    a, b = pares[nome_a].align(pares[nome_b], fill_value=0)
    t = a.add_suffix("_antes").join(b.add_suffix("_depois"))
    t["delta_eua"] = b.eua - a.eua
    t["delta_outros"] = b.outros - a.outros
    t["perda_eua_sh4"] = (-t.delta_eua).clip(lower=0)
    t["compensado_sh4"] = np.minimum(t.perda_eua_sh4, t.delta_outros.clip(lower=0))
    return t


def respostas_municipais(pares):
    t = pares.groupby(level="CO_MUN").sum()
    t["delta_total"] = t.delta_eua + t.delta_outros
    t["variacao_eua_pct"] = 100 * proporcao(t.delta_eua, t.eua_antes)
    t["variacao_total_pct"] = 100 * proporcao(t.delta_total, t.eua_antes + t.outros_antes)
    t["variacao_kg_eua_pct"] = 100 * proporcao(t.kg_eua_depois - t.kg_eua_antes, t.kg_eua_antes)
    t["compensacao_mesmo_sh4_pct"] = 100 * proporcao(t.compensado_sh4, t.perda_eua_sh4)
    return t


def associacoes(cidades):
    """Spearman e IC por reamostragem de municípios; uma linha por cidade na janela."""
    rng = np.random.default_rng(2026)
    linhas = []
    for corte in (1, 12, 24):
        selecionadas = cidades[cidades.meses_ativos.ge(corte)]
        for x, y in [("vulnerabilidade_pct", "variacao_eua_pct"),
                     ("vulnerabilidade_pct", "variacao_total_pct"),
                     ("numero_efetivo_destinos", "compensacao_mesmo_sh4_pct")]:
            amostra = selecionadas[[x, y, "fob_pre_usd"]].dropna()
            if len(amostra) < 3 or amostra.nunique().min() < 2:
                continue
            postos = amostra.rank()
            rho = postos[x].corr(postos[y])
            controle = np.column_stack([np.ones(len(postos)), postos.fob_pre_usd])
            xy = postos[[x,y]].to_numpy()
            residuais = xy - controle @ np.linalg.lstsq(controle, xy, rcond=None)[0]
            parcial = np.corrcoef(residuais.T)[0, 1]
            sorteio = rng.integers(len(amostra), size=(1000, len(amostra)))
            posto_x = pd.DataFrame(amostra[x].to_numpy()[sorteio]).rank(axis=1)
            posto_y = pd.DataFrame(amostra[y].to_numpy()[sorteio]).rank(axis=1)
            inferior, superior = posto_x.corrwith(posto_y, axis=1).quantile([.025, .975])
            linhas.append((corte, x, y, len(amostra), rho, inferior, superior, parcial))
    return pd.DataFrame(linhas, columns=["min_meses","indicador","desfecho","n","rho","ic025","ic975",
                                         "rho_parcial_porte"])


def fases_interanuais(mensal):
    """Faixas descritivas de meses completos, com comparação ao mesmo calendário."""
    periodos = [("2025-01","2025-03"), ("2025-04","2025-07"), ("2025-08","2025-10"),
                ("2025-11","2026-02"), ("2026-03","2026-06"), ("2026-07","2026-07"),
                ("2026-08", str(mensal.index.max()))]
    linhas = []
    for inicio, fim in periodos:
        meses = pd.period_range(inicio, fim, freq="M")
        if len(meses) == 0:
            continue
        for campo in FLUXOS + ["total"]:
            atual = mensal.loc[meses,campo].sum()
            anterior = mensal.loc[meses-12,campo].sum()
            linhas.append((inicio, fim, str(meses[0]-12), str(meses[-1]-12), campo, anterior, atual,
                           100*(atual/anterior-1) if anterior else np.nan))
    return pd.DataFrame(linhas, columns=["inicio","fim","base_inicio","base_fim","medida",
                                         "anterior","atual","variacao_pct"])


def projecoes(treino):
    """Cada linha de ciclos começa no mesmo mês do ano que a próxima previsão."""
    ciclos = treino[-36:].reshape(3, 12)
    sazonalidade = (ciclos / ciclos.mean(axis=1, keepdims=True)).mean(axis=0)
    nivel = (treino[-6:] / sazonalidade[-6:]).mean()
    return {"sazonal_12": treino[-12:][:HORIZONTE],
            "media_3": np.repeat(treino[-3:].mean(), HORIZONTE),
            "nivel_sazonal": nivel * sazonalidade[:HORIZONTE]}


def prever(series):
    historico = []
    for mercado in MERCADOS:
        y = series[mercado].to_numpy(dtype=float)
        for fim in range(36, len(y) - HORIZONTE + 1):
            origem = series.index[fim - 1]
            if origem < pd.Period("2018-12", "M"):
                continue
            for modelo, valores in projecoes(y[:fim]).items():
                for h, valor in enumerate(valores, 1):
                    historico.append((origem, origem+h, h, mercado, modelo, valor, y[fim+h-1]))
    erros = pd.DataFrame(historico, columns=["origem","alvo","h","mercado","modelo","previsto","observado"])
    corte = pd.Period("2024-12","M")
    # Evita origens cujos três alvos atravessam a separação entre seleção e teste.
    erros["etapa"] = np.select([erros.origem + HORIZONTE <= corte, erros.origem >= corte],
                               ["selecao","teste"], default="transicao")
    erros = erros[erros.etapa != "transicao"].copy()
    erros["erro_abs"] = (erros.observado - erros.previsto).abs()
    metricas = erros.groupby(["mercado","modelo","etapa"]).agg(
        mae_usd=("erro_abs","mean"), soma_erros=("erro_abs","sum"), soma_fob=("observado","sum"),
        origens=("origem","nunique")).reset_index()
    metricas["wape_pct"] = 100 * metricas.soma_erros / metricas.soma_fob
    escolhidos = metricas[metricas.etapa=="selecao"].sort_values("mae_usd").drop_duplicates("mercado")
    modelos = escolhidos.set_index("mercado").modelo.to_dict()
    teste = erros[(erros.etapa=="teste") & erros.modelo.eq(erros.mercado.map(modelos))].copy()
    # Mantém a covariação dos erros nos dois mercados para as faixas do total.
    soma = teste.groupby(["origem","alvo","h"])[["previsto","observado"]].sum().reset_index()
    soma["mercado"] = "total"
    residuos = pd.concat([teste,soma],ignore_index=True)
    residuos["erro_rel"] = residuos.observado / residuos.previsto - 1
    previsoes = {m: projecoes(series[m].to_numpy())[modelos[m]] for m in MERCADOS}
    previsoes["total"] = previsoes["eua"] + previsoes["outros"]
    linhas = []
    for m, valores in previsoes.items():
        for h, ponto in enumerate(valores, 1):
            amostra = residuos.loc[(residuos.mercado==m) & (residuos.h==h),"erro_rel"]
            q10,q90 = amostra.quantile([.10,.90])
            linhas.append((series.index[-1]+h,m,modelos.get(m,"soma"),ponto,
                           max(0,ponto*(1+q10)),ponto*(1+q90),len(amostra)))
    futuro = pd.DataFrame(linhas,columns=["mes","mercado","modelo","fob_usd","p10_usd","p90_usd","n_erros"])
    return futuro, metricas, erros


def figura(mensal, futuro):
    fig, axes = plt.subplots(2,2,figsize=(12,7),layout="constrained")
    for i, mercado in enumerate(MERCADOS):
        ax, zoom = axes[i]
        y = mensal[mercado]/1e6
        for painel, serie in [(ax,y),(zoom,y.iloc[-18:])]:
            painel.plot(serie.index.to_timestamp(),serie,color="#1b5273",label="Observado")
            painel.set_ylabel("US$ milhões")
            painel.grid(axis="y",alpha=.2)
        ax.plot(y.index.to_timestamp(),y.rolling(12).mean(),color="#c66b24",label="Média móvel de 12 meses")
        ax.axvline(pd.Timestamp("2025-08-01"),ls=":",color="#666")
        p = futuro[futuro.mercado==mercado]
        datas = p.mes.dt.to_timestamp()
        zoom.fill_between(datas,p.p10_usd/1e6,p.p90_usd/1e6,color="#edcfa2",label="Faixa empírica 10–90%")
        zoom.plot(datas,p.fob_usd/1e6,"o--",color="#a34d19",label="Previsão")
        zoom.tick_params(axis="x",rotation=30)
        ax.set_title("EUA" if mercado=="eua" else "Demais destinos",loc="left")
    axes[0,0].legend(fontsize=8)
    axes[0,1].legend(fontsize=8)
    fig.suptitle("Exportações de Minas Gerais por mercado de destino")
    fig.savefig(SAIDA/"historico_previsoes.png",dpi=170)
    plt.close(fig)


def main():
    df = ler_base()
    ultimo = df.mes.max()
    _, nomes = obter_malha(MALHA)
    if len(df.CO_MUN.unique()) != len(nomes.reindex(df.CO_MUN.unique()).dropna()):
        raise ValueError("Município sem correspondência nominal na malha.")
    pre = df[df.CO_ANO.between(2022,2024)]
    pp = fluxos(pre,PAR)
    perfil = indicadores(pre,pp)
    janelas = {"estrutura": ("2022-01","2024-12"), "antes_12": ("2024-08","2025-07"),
               "depois_12": ("2025-08","2026-07"), "base_inicial": ("2024-08","2024-12"),
               "choque_inicial": ("2025-08","2025-12")}
    for anos in [2,1,0]:
        fim = ultimo - 12*anos
        janelas[f"trimestre_t{anos}"] = (str(fim-2),str(fim))
    pares = {k:fluxos(df[df.mes.between(a,b)],PAR) for k,(a,b) in janelas.items()}
    comparacoes = {"anual":("antes_12","depois_12"),"inicial":("base_inicial","choque_inicial"),
                   "recente_interanual":("trimestre_t1","trimestre_t0"),
                   "recente_vs_dois_anos":("trimestre_t2","trimestre_t0")}
    SAIDA.mkdir(parents=True,exist_ok=True)

    def salvar(t,nome):
        t.to_csv(SAIDA/(nome+".csv"),sep=";",index=False)

    estaduais = []
    for janela, t in pares.items():
        linha = t.sum().to_dict()
        estaduais.append(dict(janela=janela,inicio=janelas[janela][0],fim=janelas[janela][1],**linha))
    salvar(pd.DataFrame(estaduais),"periodos_estaduais")
    por_periodo = pd.concat(pares,names=["janela"]).reset_index()
    produtos = razoes_produtos(por_periodo.groupby(["janela","SH4"])[FLUXOS].sum())
    salvar(produtos.reset_index(),"produtos_por_mercado")
    produtos_mun = razoes_produtos(por_periodo.set_index(["janela","CO_MUN","SH4"]))
    for m in MERCADOS:
        produtos_mun["fracao_municipal_no_sh4_"+m] = proporcao(produtos_mun[m],
                produtos_mun[m].groupby(level=["janela","SH4"]).transform("sum"))
    produtos_mun = produtos_mun.reset_index()
    produtos_mun["municipio"] = produtos_mun.CO_MUN.map(nomes)
    salvar(produtos_mun,"produtos_municipios")
    respostas = []
    for janela,(a,b) in comparacoes.items():
        t = comparar(pares,a,b)
        if janela == "anual":
            salvar(t.reset_index(),"compensacao_municipio_sh4_anual")
        mun = respostas_municipais(t)
        # Inclui também os exportadores estruturais ausentes em ambas as janelas.
        ausentes = perfil.index.difference(mun.index)
        if len(ausentes):
            vazio = t.iloc[:0].droplevel("SH4").reindex(ausentes,fill_value=0)
            mun = pd.concat([mun,respostas_municipais(vazio)])
        mun = mun.join(perfil)
        mun["municipio"] = nomes.reindex(mun.index)
        mun["comparacao"] = janela
        respostas.append(mun.reset_index())
    cidades = pd.concat(respostas,ignore_index=True)
    salvar(cidades,"municipios_vulnerabilidade_resposta")
    salvar(associacoes(cidades[cidades.comparacao=="anual"]), "associacoes_municipais")
    mensal = fluxos(df,["mes"])
    mensal["total"] = mensal.eua + mensal.outros
    salvar(fases_interanuais(mensal), "fases_interanuais")
    for m in MERCADOS:
        mensal[m+"_mm12"] = mensal[m].rolling(12).mean()
        mensal[m+"_interanual_pct"] = 100 * mensal[m].pct_change(12)
    salvar(mensal.reset_index(),"historico_mensal")
    historico = mensal[mensal.index.year<=2024]
    saz = historico[MERCADOS]/historico[MERCADOS].groupby(historico.index.year).transform("mean")
    salvar(saz.groupby(saz.index.month).mean().rename_axis("mes_calendario").reset_index(),"sazonalidade_2015_2024")
    futuro,metricas,erros = prever(mensal)
    salvar(futuro,"previsoes")
    salvar(metricas,"validacao_previsoes")
    salvar(erros,"erros_por_origem")
    figura(mensal,futuro)
    print(f"Caderno visual: {gerar_visuais(SAIDA)}")
    print(f"Fonte {BASE.name}, SHA-256 {sha256(BASE)}, {len(df)} registros, até {ultimo}. Saída: {SAIDA}")

if __name__ == "__main__":
    main()

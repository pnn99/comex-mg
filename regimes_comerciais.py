"""Calendário aduaneiro, comparações sazonais e recuperação municipal."""
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from panorama_comercial import FLUXOS, PAR, comparar, fluxos, ler_base, proporcao, respostas_municipais

RAIZ = Path(__file__).resolve().parent
SAIDA = RAIZ / "resultados/periodo_choque"
SECAO = RAIZ / "resultados/secao_4"
JANELAS = {
    "bimestre": ("2024-09", "2024-10", "2025-09", "2025-10"),
    "inicial": ("2024-08", "2024-12", "2025-08", "2025-12"),
    "anual": ("2024-08", "2025-07", "2025-08", "2026-07"),
}
FASES = [("2025-01","2025-03"), ("2025-04","2025-07"), ("2025-08","2025-10"),
         ("2025-11","2026-02"), ("2026-03","2026-06"), ("2026-07","2026-07"),
         ("2026-08","2026-10")]


def calendario():
    t = pd.read_csv(RAIZ / "docs/calendario_tarifario.csv", sep=";")
    if t.medida.duplicated().any() or (t.fim_exclusivo.dropna() <= t.inicio[t.fim_exclusivo.notna()]).any():
        raise ValueError("Versão duplicada ou vigência inválida.")
    return t


def salvar(t, nome, pasta=SAIDA):
    pasta.mkdir(parents=True, exist_ok=True)
    t.to_csv(pasta / (nome + ".csv"), sep=";", index=False)


def serie_mensal(d, atos):
    t = fluxos(d, ["mes"])
    t["total"] = t.eua + t.outros
    t["kg_total"] = t.kg_eua + t.kg_outros
    t["participacao_eua"] = proporcao(t.eua, t.total)
    for mercado in ["eua", "outros", "total"]:
        t["usd_kg_" + mercado] = proporcao(t[mercado], t["kg_" + mercado])
    for campo in FLUXOS + ["total", "kg_total"]:
        t[campo + "_interanual_pct"] = 100 * proporcao(t[campo] - t[campo].shift(12), t[campo].shift(12))
    dias = pd.date_range(t.index.min().start_time, t.index.max().end_time, freq="D")
    for ato in atos[atos.aliquota.notna()].itertuples():
        ativo = dias >= pd.Timestamp(ato.inicio)
        if pd.notna(ato.fim_exclusivo):
            ativo &= dias < pd.Timestamp(ato.fim_exclusivo)
        t["fracao_dias_" + ato.medida] = pd.Series(ativo, index=dias.to_period("M")).groupby(level=0).mean()
    fracoes = t.filter(like="fracao_dias_")
    t["transicao"] = (fracoes.gt(0) & fracoes.lt(1)).any(axis=1)
    t["regimes"] = fracoes.apply(lambda s: "|".join(s[s.gt(0)].index.str.removeprefix("fracao_dias_")), axis=1)
    fora = t.index > pd.Period("2026-10")
    t.loc[fora, fracoes.columns] = np.nan
    t.loc[fora, "regimes"] = "vigencia_pendente_de_revisao"
    t["transicao"] = t.transicao.astype("boolean").mask(fora)
    return t


def fases(t):
    linhas = []
    for inicio, fim in FASES:
        trecho = t.loc[inicio:fim]
        for criterio, atual in [("todos", trecho), ("completos", trecho[~trecho.transicao])]:
            if atual.empty:
                continue
            for medida in FLUXOS + ["total","kg_total"]:
                pre = t.loc[atual.index - 12, medida].sum()
                pos = atual[medida].sum()
                linhas.append(dict(inicio=inicio, fim=fim, criterio=criterio, meses="|".join(map(str, atual.index)),
                                   medida=medida, anterior=pre, atual=pos, variacao_pct=100*(pos/pre-1) if pre else np.nan))
    return pd.DataFrame(linhas)


def recuperacao(d):
    mensal = fluxos(d, ["CO_MUN", "mes"]).eua.unstack(fill_value=0)
    ref = mensal.loc[:, "2022-01":"2024-12"]
    if len(ref.columns) != 36:
        raise ValueError("Referência sazonal incompleta.")
    media = ref.T.groupby(ref.columns.month).mean().T
    trajetorias, resumo = [], []
    for mun, serie in mensal.loc[:, "2025-09":].iterrows():
        queda = retorno = None
        sequencia = 0
        referencias = 0
        for mes, valor in serie.items():
            base = media.loc[mun, mes.month]
            indice = valor / base if base > 0 else np.nan
            if mes <= pd.Period("2025-10") and base > 0:
                referencias += 1
                if queda is None and indice < 1:
                    queda = mes
            if queda is not None and mes > queda and retorno is None:
                sequencia = sequencia + 1 if indice >= 1 else 0
                if sequencia == 2:
                    retorno = mes
            trajetorias.append((mun, mes, valor, base, indice, valor-base))
        status = ("recuperado" if retorno else "censurado" if queda else
                  "sem_queda_inicial" if referencias == 2 else "referencia_inicial_insuficiente")
        resumo.append((mun, status, queda, retorno, (retorno.ordinal-queda.ordinal) if retorno else None,
                       (serie.index[-1].ordinal-queda.ordinal) if queda and retorno is None else None, serie.index[-1]))
    return (pd.DataFrame(trajetorias,columns=["CO_MUN","mes","eua","referencia","indice","distancia_usd"]),
            pd.DataFrame(resumo,columns=["CO_MUN","status","mes_queda","mes_confirmacao","meses_ate_recuperar",
                                        "meses_ate_censura","ultimo_mes"]))


def destinos(a, b):
    chaves = PAR + ["CO_PAIS"]
    def agregar(d):
        return d.loc[d.mercado.eq("outros")].groupby(chaves).VL_FOB.sum()
    t = pd.concat([agregar(a).rename("antes"), agregar(b).rename("depois")],axis=1).fillna(0)
    t = t[t.antes.gt(0) | t.depois.gt(0)].copy()
    t["delta"] = t.depois - t.antes
    t["movimento"] = np.select([t.antes.eq(0), t.depois.eq(0), t.delta.gt(0), t.delta.lt(0)],
                               ["entrada","saida","expansao","retracao"], default="estavel")
    return t.reset_index()


def valor_quantidade(precos):
    chaves = ["comparacao","SH4","CO_PAIS"]
    colunas = ["VL_FOB","KG_LIQUIDO"]
    t = precos.pivot(index=chaves,columns="epoca",values=colunas).fillna(0)
    v = pd.DataFrame(index=t.index)
    for etapa in ["antes","depois"]:
        for col in colunas:
            v[col+"_"+etapa] = t[col,etapa]
        v["usd_kg_"+etapa] = proporcao(t["VL_FOB",etapa],t["KG_LIQUIDO",etapa])
    for col in [*colunas,"usd_kg"]:
        v[col+"_variacao_pct"] = 100*proporcao(v[col+"_depois"]-v[col+"_antes"],v[col+"_antes"])
    v = v.reset_index()
    salvar(v,"variacoes_produto_destino")
    anual = v[v.comparacao.eq("anual")]
    fig, axes = plt.subplots(1,2,figsize=(12,6),layout="constrained")
    for ax,(rotulo,amostra) in zip(axes,[("EUA",anual[anual.CO_PAIS.eq("249")]),
                                         ("Outros destinos",anual[anual.CO_PAIS.ne("249")])]):
        topo = amostra.nlargest(5,"VL_FOB_antes").set_index(["SH4","CO_PAIS"])
        topo = topo[[c+"_variacao_pct" for c in [*colunas,"usd_kg"]]]
        topo.columns = ["FOB","Peso","FOB/kg"]
        topo.index = [f"{sh} · {pais}" for sh,pais in topo.index]
        topo.plot.barh(ax=ax,color=["#126782","#e59500","#57986c"])
        ax.axvline(0,color="#555",linewidth=.7)
        ax.set(title=rotulo,xlabel="Variação anual (%)",ylabel="SH4 · código do país")
        ax.invert_yaxis()
    fig.suptitle("Valor, peso e valor unitário dos principais fluxos por FOB na janela anterior")
    fig.savefig(SAIDA/"valor_quantidade_produto_destino.png",dpi=160)
    plt.close(fig)


def executar():
    atos = calendario()
    salvar(atos, "calendario_medidas_tarifarias", SECAO)
    d = ler_base()
    mensal = serie_mensal(d, atos)
    salvar(mensal.reset_index(), "serie_mensal_regimes")
    salvar(fases(mensal), "fases_interanuais")
    diaria = []
    for coluna in mensal.filter(like="fracao_dias_"):
        f = mensal[coluna]
        for mes in f[f.gt(0)].index:
            anterior = mensal.loc[mes-12, "eua"]
            diaria.append((mes,coluna.removeprefix("fracao_dias_"),f[mes],mensal.loc[mes,"eua"]*f[mes],anterior*f[mes]))
    salvar(pd.DataFrame(diaria, columns=["mes","medida","fracao_dias","fob_eua_rateado","fob_ano_anterior_rateado"]), "sensibilidade_dias")
    produtos, movimentos, municipios, agregados, precos = [], [], [], [], []
    for nome,(a,b,c,e) in JANELAS.items():
        pre, pos = d[d.mes.between(a,b)], d[d.mes.between(c,e)]
        pares = comparar({"a":fluxos(pre,PAR),"b":fluxos(pos,PAR)}, "a", "b")
        produto = pares.assign(razao_ganhos_perdas=proporcao(pares.ganho_outros_sh4,pares.perda_eua_sh4),
                               compensacao_pct=100*proporcao(pares.compensado_sh4,pares.perda_eua_sh4))
        produtos.append(produto.reset_index().assign(comparacao=nome))
        m = respostas_municipais(pares)
        municipios.append(m.reset_index().assign(comparacao=nome))
        movimentos.append(destinos(pre,pos).assign(comparacao=nome))
        perdas = m.delta_eua.lt(0)
        for campo in FLUXOS + ["total","kg_total"]:
            x, y = mensal.loc[a:b,campo].sum(), mensal.loc[c:e,campo].sum()
            agregados.append((nome,a,b,c,e,campo,x,y,y-x,100*(y/x-1) if x else np.nan,
                              perdas.sum(), m.eua_antes.gt(0).sum(), 100*perdas.sum()/m.eua_antes.gt(0).sum() if m.eua_antes.gt(0).any() else np.nan))
        for epoca, bloco in [("antes",pre),("depois",pos)]:
            v = bloco.groupby(["SH4","CO_PAIS"])[["VL_FOB","KG_LIQUIDO"]].sum().reset_index()
            precos.append(v.assign(comparacao=nome,epoca=epoca,usd_kg=proporcao(v.VL_FOB,v.KG_LIQUIDO)))
    for lista,nome in [(produtos,"compensacao_municipio_sh4"),(municipios,"resposta_municipal"),
                       (movimentos,"novos_destinos"),(precos,"valor_quantidade_produto_destino")]:
        salvar(pd.concat(lista,ignore_index=True),nome)
    salvar(pd.DataFrame(agregados,columns=["comparacao","inicio_base","fim_base","inicio_pos","fim_pos","medida",
           "anterior","atual","delta","variacao_pct","n_queda_liquida_eua","n_eua_base","pct_queda_liquida_eua"]), "comparacao_periodos")
    valor_quantidade(pd.concat(precos,ignore_index=True))
    trajetoria, resumo = recuperacao(d)
    salvar(trajetoria, "recuperacao_mensal")
    salvar(resumo, "recuperacao_municipal")
    contagens = resumo.status.value_counts()
    fig, ax = plt.subplots(figsize=(8,4),layout="constrained")
    contagens.rename(index={"recuperado":"Recuperação confirmada","censurado":"Censurado após queda",
        "sem_queda_inicial":"Sem queda inicial", "referencia_inicial_insuficiente":"Referência insuficiente"}).plot.barh(ax=ax)
    ax.set(xlabel="Municípios",title="Vendas aos EUA após a queda inicial de setembro–outubro de 2025")
    fig.savefig(SAIDA/"recuperacao.png",dpi=160)
    plt.close(fig)
    from analise_cientifica import MALHA, obter_malha
    from matplotlib.collections import PatchCollection
    geo, _ = obter_malha(MALHA)
    anual = pd.concat(municipios).query("comparacao == 'anual'").set_index("CO_MUN").compensacao_mesmo_sh4_pct
    fig, ax = plt.subplots(figsize=(9,6),layout="constrained")
    cmap = plt.get_cmap("viridis").with_extremes(bad="#dddddd")
    mapa = PatchCollection(list(geo.values()), cmap=cmap, edgecolors="white", linewidths=.2)
    mapa.set_array(np.ma.masked_invalid(anual.reindex(geo).to_numpy(dtype=float)))
    mapa.set_clim(0,100)
    ax.add_collection(mapa)
    ax.autoscale_view()
    ax.set_aspect(1/np.cos(np.deg2rad(18.5)))
    ax.axis("off")
    ax.set_title("Perda bruta aos EUA compensada no mesmo SH4 · janela anual")
    fig.colorbar(mapa,ax=ax,label="Percentual da perda compensada · cinza = sem perda bruta")
    fig.savefig(SAIDA/"mapa_compensacao.png",dpi=160)
    plt.close(fig)
    fig, eixos = plt.subplots(3,2,figsize=(12,8),layout="constrained",sharex=True)
    for ax, (campo, unidade, fator) in zip(eixos.flat,[("eua","EUA · US$ bilhões",1e9),
            ("outros","Outros destinos · US$ bilhões",1e9),("total","Total · US$ bilhões",1e9),
            ("participacao_eua","Participação EUA (%)",.01),("kg_total","Peso total · bilhões kg",1e9),
            ("usd_kg_total","Valor unitário total · US$/kg",1)]):
        ax.plot(mensal.index.to_timestamp(),mensal[campo]/fator)
        ax.set_title(unidade)
        ax.grid(alpha=.2)
    fig.savefig(SAIDA/"serie_historica_valor_quantidade.png",dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    executar()

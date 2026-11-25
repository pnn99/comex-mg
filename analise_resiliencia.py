"""Resultados da Seção 4. Associações municipais e exposição potencial por medida."""
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import numpy as np
import pandas as pd

from analise_cientifica import BASE, RAIZ
from analise_perfis import SAIDA as PERFIS, tabela_visual
from panorama_comercial import SAIDA as PANORAMA
from preparar_tarifas import obter_lista

SAIDA = RAIZ / "resultados/secao_4"
DESFECHOS = ["perdeu_eua_pct", "crescimento_simetrico_total_pct", "compensacao_mesmo_sh4_pct"]
CAMPOS = ["hhi_produtos", "hhi_destinos", "participacao_eua", "cv_mensal"]
CONTROLES = ["log_fob", "parcela_cafe", "parcela_minerio"]


def ler_csv(arquivo):
    return pd.read_csv(arquivo, sep=";", dtype={"CO_MUN": str, "SH4": str, "HTS8": str})


def classificar_tarifas(codigos, lista):
    if (lista.duplicated(["ato","tipo","HTS8"]).any() or not lista.HTS8.str.fullmatch(r"\d{8}").all()
            or not lista.HTS8.str[:4].eq(lista.SH4).all()):
        raise ValueError("Correspondência HTS8–SH4 inválida.")
    quadros = []
    for medida, ato in [("adicional_agosto","EO14323"), ("novas_excecoes_novembro","EO14361")]:
        itens = lista[lista.ato.eq(ato)]
        inteiros = set(itens.loc[itens.tipo.eq("subposicao") & itens.HTS8.str.endswith("0000"), "SH4"])
        if ato == "EO14361":
            cafe = {"09011100","09011200","09012100","09012200","09019010","09019020"}
            if not cafe.issubset(itens.loc[itens.tipo.eq("subposicao"), "HTS8"]):
                raise ValueError("A revisão do café diverge do anexo de novembro.")
            inteiros.add("0901")
        q = itens.groupby("SH4").size().reindex(codigos, fill_value=0).rename("itens_anexo").to_frame()
        inteiro = q.index.isin(inteiros)
        if ato == "EO14323":
            agro_sem_excecao = q.index.str[:2].isin(["07","08","09","10"]) & q.itens_anexo.eq(0)
            q["peso_min"] = agro_sem_excecao.astype(int)
            q["peso_max"] = (~inteiro).astype(int)
        else:
            q["peso_min"] = inteiro.astype(int)
            q["peso_max"] = q.itens_anexo.gt(0).astype(int)
        quadros.append(q.assign(medida=medida, ato=ato, vigencia=itens.vigencia.iloc[0]).reset_index())
    return pd.concat(quadros, ignore_index=True)


def exposicao(produtos, pesos):
    """Limites da parcela potencial da pauta mundial e cobertura do FOB aos EUA."""
    linhas = []
    for medida, q in pesos.groupby("medida"):
        p = produtos.merge(q, on="SH4", how="left", validate="many_to_one")
        if p[["peso_min","peso_max"]].isna().any().any():
            raise ValueError("Há produtos sem limites de exposição.")
        p["usd_min"] = p.eua * p.peso_min
        p["usd_max"] = p.eua * p.peso_max
        t = p.groupby("CO_MUN")[["eua","total","usd_min","usd_max"]].sum()
        t = t[t.total.gt(0)].copy()
        t["exposicao_min"] = t.usd_min / t.total
        t["exposicao_max"] = t.usd_max / t.total
        t["cobertura_fob_eua"] = 1 - (t.usd_max - t.usd_min) / t.eua.where(t.eua.gt(0))
        linhas.append(t.assign(medida=medida).reset_index())
    return pd.concat(linhas, ignore_index=True)


def regressao(dados, y, termos, **descricao):
    """MQO municipal com covariância HC3, IC normal assintótico de 95%."""
    t = dados[[y, *termos]].dropna()
    x = np.column_stack([np.ones(len(t)), t[termos]])
    nomes = ["constante", *termos]
    if len(t) <= len(nomes) or np.linalg.matrix_rank(x) != len(nomes):
        raise ValueError(f"Amostra insuficiente ou colinear em {y}, {descricao}.")
    inversa = np.linalg.pinv(x)
    beta = inversa @ t[y]
    erro = t[y] - x @ beta
    h = np.einsum("ij,ji->i", x, inversa)
    if np.any(h >= 1 - 1e-10):
        raise ValueError(f"Alavancagem unitária em {y}, {descricao}.")
    ajustada = inversa * (erro.to_numpy() / (1 - h))
    ep = np.sqrt((ajustada ** 2).sum(axis=1))
    return pd.DataFrame({"termo": nomes, "coef": beta, "ep_hc3": ep, "ic025": beta - 1.96 * ep,
                         "ic975": beta + 1.96 * ep, "n": len(t), "desfecho": y, **descricao})


def desfechos(d):
    d = d.copy()
    d["perdeu_eua_pct"] = (100 * d.delta_eua.lt(0)).where(d.eua_antes.gt(0))
    d["resistiu_eua_pct"] = 100 - d.perdeu_eua_pct
    soma = d.eua_antes + d.outros_antes + d.eua_depois + d.outros_depois
    d["crescimento_simetrico_total_pct"] = 200 * d.delta_total / soma.where(soma.gt(0))
    return d


def por_perfil(d):
    linhas = []
    for (janela, perfil), t in d.dropna(subset=["perfil"]).groupby(["comparacao","perfil"]):
        linhas.append(dict(comparacao=janela, perfil=perfil, municipios=len(t),
                          n_eua=t.variacao_eua_pct.count(), mediana_variacao_eua_pct=t.variacao_eua_pct.median(),
                          pct_com_queda_eua=t.perdeu_eua_pct.mean(), pct_com_resistencia=t.resistiu_eua_pct.mean(),
                          n_total=t.variacao_total_pct.count(), mediana_variacao_total_pct=t.variacao_total_pct.median(),
                          n_compensacao=t.compensacao_mesmo_sh4_pct.count(),
                          mediana_compensacao_pct=t.compensacao_mesmo_sh4_pct.median(),
                          perda_bruta_sh4_usd=t.perda_eua_sh4.sum(), compensado_sh4_usd=t.compensado_sh4.sum()))
    return pd.DataFrame(linhas)


def ajuste_tarifario(painel, exp):
    # Dois meses de calendário completos sob o marco inicial e anteriores à revisão de novembro.
    bruta = pd.read_csv(BASE, sep=";", usecols=["CO_ANO","CO_MES","CO_MUN","CO_PAIS","VL_FOB"],
                        dtype={"CO_MUN":str, "CO_PAIS":str})
    janela = bruta[bruta.CO_ANO.isin([2024,2025]) & bruta.CO_MES.isin([9,10]) & bruta.CO_PAIS.eq("249")]
    valores = janela.groupby(["CO_MUN","CO_ANO"]).VL_FOB.sum().unstack(fill_value=0)
    t = painel[painel.comparacao.eq("anual") & painel.meses_ativos.ge(12)].set_index("CO_MUN")
    t = t[["municipio", "perfil", *CAMPOS, *CONTROLES]]
    t = t.join(valores.rename(columns={2024:"base_bimestre",2025:"pos_bimestre"}))
    t = t.join(exp[exp.medida.eq("adicional_agosto")].set_index("CO_MUN")[["exposicao_min","exposicao_max","cobertura_fob_eua"]])
    t = t[t.base_bimestre.gt(0)].copy()
    t["perdeu_eua_pct"] = 100 * t.pos_bimestre.lt(t.base_bimestre)
    ajustes = []
    for limite in ["exposicao_min","exposicao_max"]:
        # Modelos de cenários separados. A faixa entre coeficientes não constitui um IC.
        termos = [limite, "hhi_produtos", "hhi_destinos", "log_fob", "parcela_cafe", "parcela_minerio"]
        ajustes.append(regressao(t, "perdeu_eua_pct", termos, modelo=limite,
                                 min_meses=12, comparacao="set_out_2025_vs_2024"))
    return ajustes, t.reset_index()


def main():
    perfis = ler_csv(PERFIS / "municipios.csv")
    prod = ler_csv(PANORAMA / "produtos_municipios.csv").query("janela == 'estrutura'").copy()
    if prod.duplicated(["CO_MUN","SH4"]).any():
        raise ValueError("Duplicação de município e produto na janela estrutural.")
    pesos = classificar_tarifas(pd.Index(sorted(prod.SH4.unique()), name="SH4"), ler_csv(obter_lista()))
    exp = exposicao(prod, pesos)
    prod["parcela_cafe"] = prod.total.where(prod.SH4.eq("0901"), 0)
    prod["parcela_minerio"] = prod.total.where(prod.SH4.eq("2601"), 0)
    composicao = prod.groupby("CO_MUN")[["total","parcela_cafe","parcela_minerio"]].sum()
    totals = composicao.total[composicao.total > 0].sort_index()
    pre = perfis.set_index("CO_MUN").sort_index()
    if not totals.index.equals(pre.index) or not np.array_equal(totals, pre.fob_pre_usd):
        raise ValueError("FOB municipal divergente entre perfis e panorama. Reexecute o orquestrador.")
    composicao = composicao[["parcela_cafe","parcela_minerio"]].div(composicao.total.where(composicao.total.gt(0)), axis=0)
    d = desfechos(ler_csv(PANORAMA / "municipios_vulnerabilidade_resposta.csv"))
    if d.duplicated(["CO_MUN","comparacao"]).any():
        raise ValueError("A resposta precisa ter uma linha por município e comparação.")
    anuais = d[d.comparacao.eq("anual") & d.fob_pre_usd.gt(0)].set_index("CO_MUN").sort_index()
    if not anuais.index.equals(pre.index) or not np.allclose(anuais[CAMPOS], pre[CAMPOS]):
        raise ValueError("Os indicadores do panorama diferem dos usados para classificar os perfis.")
    d = d.merge(perfis[["CO_MUN","perfil"]], on="CO_MUN", how="left", validate="many_to_one").join(composicao,on="CO_MUN")
    d["log_fob"] = np.log(d.fob_pre_usd)
    d["log2_destinos_efetivos"] = np.log2(d.numero_efetivo_destinos)
    comparacao = por_perfil(d)
    ajustes = []
    for janela in ["anual","inicial"]:
        for corte in (1,12,24):
            amostra = d[d.comparacao.eq(janela) & d.meses_ativos.ge(corte)]
            for y in DESFECHOS:
                termos = CAMPOS.copy()
                if y == "compensacao_mesmo_sh4_pct":
                    termos[1] = "log2_destinos_efetivos"
                ajustes.append(regressao(amostra, y, termos + CONTROLES,
                                         comparacao=janela, min_meses=corte, modelo="indicadores"))
        t = d[d.comparacao.eq(janela) & d.perfil.notna()].copy()
        # Contrastes ajustados frente ao primeiro perfil, com o mesmo controle de porte e composição.
        dummies = pd.get_dummies(t.perfil, prefix="perfil", drop_first=True, dtype=float)
        for y in DESFECHOS:
            ajustes.append(regressao(t.join(dummies), y, list(dummies.columns) + CONTROLES,
                                     comparacao=janela, min_meses=12, modelo="perfis"))
    tarifarios, bimestre = ajuste_tarifario(d, exp)
    reg = pd.concat(ajustes + tarifarios, ignore_index=True)
    pares = ler_csv(PANORAMA / "compensacao_municipio_sh4_anual.csv")
    if pares.duplicated(["CO_MUN","SH4"]).any():
        raise ValueError("Duplicação na tabela anual de compensação por produto e município.")
    medidas = ["delta_eua","delta_outros","perda_eua_sh4","compensado_sh4"]
    por_produto = pares.groupby("SH4")[medidas].sum().sort_values("perda_eua_sh4",ascending=False)
    por_produto["compensacao_pct"] = 100 * por_produto.compensado_sh4 / por_produto.perda_eua_sh4.where(por_produto.perda_eua_sh4.gt(0))
    anual_mg = d.loc[d.comparacao.eq("anual"), medidas].sum()
    if not por_produto[medidas].sum().eq(anual_mg).all():
        raise ValueError("Perdas e compensações por SH4 divergem dos totais municipais.")
    SAIDA.mkdir(exist_ok=True, parents=True)
    for nome, t in {"correspondencia_sh4":pesos, "exposicao_municipal":exp, "exposicao_resposta_bimestre":bimestre,
                    "resposta_por_perfil":comparacao, "regressoes_hc3":reg,
                    "compensacao_por_produto":por_produto.reset_index(), "resposta_municipal":d}.items():
        t.to_csv(SAIDA / f"{nome}.csv",sep=";",index=False)
    anual = comparacao[comparacao.comparacao.eq("anual")]
    tabela = anual[["perfil","n_eua","pct_com_queda_eua","mediana_variacao_total_pct","n_compensacao","mediana_compensacao_pct"]].copy()
    tabela.columns = ["Perfil","n EUA","Com queda (%)","Δ total (%)¹","n compensação","Compensação (%)¹"]
    fig = tabela_visual(tabela, "4.4 · Resposta comercial por perfil prévio",
                        "¹ Medianas municipais · Ago/2024–jul/2025 e ago/2025–jul/2026 · Compensação dentro do mesmo município e SH4.")
    fig.savefig(SAIDA / "resposta_por_perfil.png",dpi=180,bbox_inches="tight")
    with PdfPages(SAIDA / "resultados_discussao.pdf") as pdf:
        paineis = [("4.1 · Estrutura pré-choque", RAIZ / "resultados/pre_choque/mapa_indicadores_mg.png"),
                   ("4.1 · Distribuição dos indicadores", PANORAMA / "visuais/01b_estrutura_municipal.png"),
                   *[(f"4.2 · {titulo}", PERFIS / f"{nome}.png") for titulo, nome in
                     [("Correlações","correlacoes"),("Validação","comparacao_modelos"),("Caracterização","caracterizacao"),("Perfis municipais","mapa_perfis")]],
                   ("4.3 · Trajetória mensal", PANORAMA / "visuais/01_historico.png"),
                   ("4.3 · Resposta por período", PANORAMA / "visuais/02_fases.png"),
                   ("4.3 · Recuperação", PANORAMA / "visuais/02b_recuperacao.png"),
                   ("4.3 · Produtos e perdas", PANORAMA / "visuais/09_produtos_perdas.png")]
        for titulo, caminho in paineis:
            painel, ax = plt.subplots(figsize=(12,8), layout="constrained")
            ax.imshow(plt.imread(caminho))
            ax.axis("off")
            ax.set_title(titulo, loc="left", fontsize=12)
            pdf.savefig(painel, dpi=150)
            plt.close(painel)
            if titulo.startswith("4.1 · Distribuição"):
                cortes = ler_csv(RAIZ / "resultados/pre_choque/sensibilidade_inclusao.csv")
                cortes = cortes[cortes.criterio.str.startswith("minimo")].copy()
                cortes["min_meses"] = cortes.criterio.str.extract(r"(\d+)")[0].astype(int)
                cortes["pct_fob"] = 100 * cortes.fracao_fob
                quadro = cortes[["min_meses","municipios","pct_fob"]].copy()
                quadro.columns = ["Mínimo de meses ativos","Municípios","FOB preservado (%)"]
                pagina = tabela_visual(quadro, "4.1 · Sensibilidade da amostra municipal",
                                       "Comex Stat/MDIC · Denominador: FOB mundial de MG em 2022–2024.")
                pdf.savefig(pagina)
                plt.close(pagina)
        destaques = por_produto.head(8).copy()
        destaques[medidas] = destaques[medidas] / 1e6
        destaques = destaques.reset_index()
        destaques.columns = ["SH4","Δ EUA","Δ demais","Perda bruta EUA","Compensado","Compensação (%)"]
        pagina = tabela_visual(destaques, "4.3 · Perdas e compensação nos mesmos produtos",
                               "Oito maiores perdas brutas em US$ milhões. Ganhos e perdas pareados no mesmo município e SH4 antes da soma estadual.")
        pdf.savefig(pagina)
        plt.close(pagina)
        pdf.savefig(fig)
        plt.close(fig)
        # H1: um décimo de HHI. H3: diferença entre perfis relativamente a P1.
        base = reg[reg.min_meses.eq(12) & reg.comparacao.eq("anual")]
        concentracao = base[base.modelo.eq("indicadores") & base.termo.eq("hhi_produtos")].copy()
        concentracao[["coef","ic025","ic975"]] *= .1
        concentracao["contraste"] = "+0,10 HHI de produtos"
        perfis_ajustados = base[base.modelo.eq("perfis") & base.termo.eq("perfil_P3")].copy()
        perfis_ajustados["contraste"] = "P3 em relação a P1"
        efeitos = pd.concat([concentracao, perfis_ajustados], ignore_index=True)
        efeitos["desfecho"] = efeitos.desfecho.map(dict(zip(DESFECHOS,
            ["Queda aos EUA (p.p.)","Cresc. mundial (pontos)","Compensação (p.p.)"])))
        efeitos = efeitos[["contraste","desfecho","n","coef","ic025","ic975"]]
        efeitos.columns = ["Comparação","Desfecho","n","Estimativa","IC 95% inf.","IC 95% sup."]
        fig = tabela_visual(efeitos,"4.4 · Concentração e diferenças ajustadas entre perfis",
                            "Janela anual · Controles de porte e composição · Crescimento mundial simétrico · Intervalos assintóticos HC3.")
        pdf.savefig(fig)
        plt.close(fig)
        totais = exp.groupby("medida")[["usd_min","usd_max","total","eua"]].sum()
        exposicoes = pd.DataFrame({
            "Recorte": ["Adicional inicial","Novas exceções"],
            "Piso (%)": 100 * totais.usd_min / totais.total,
            "Teto (%)": 100 * totais.usd_max / totais.total,
            "FOB EUA resolvido (%)": 100 * (1 - (totais.usd_max-totais.usd_min) / totais.eua),
        })
        fig = tabela_visual(exposicoes, "4.4 · Alcance tarifário potencial sobre a pauta prévia",
                            "Piso e teto em % do FOB mundial de MG em 2022–2024. Cada linha mede um recorte próprio. Fontes: MDIC e anexos das EO 14323/14361.")
        pdf.savefig(fig)
        plt.close(fig)
        h2 = reg[(reg.modelo=="indicadores") & (reg.termo=="log2_destinos_efetivos")].copy()
        h2 = h2[["comparacao","min_meses","n","coef","ic025","ic975"]]
        h2.columns = ["Janela","Meses mínimos","n","Coeficiente","IC 95% inf.","IC 95% sup."]
        fig = tabela_visual(h2,"4.4 · Diversificação prévia e compensação posterior",
                            "Pontos percentuais de compensação por duplicação dos destinos efetivos, com controles. Intervalos assintóticos HC3.")
        pdf.savefig(fig)
        plt.close(fig)
    print(f"Seção 4. Caderno e tabelas em {SAIDA}")


if __name__ == "__main__":
    main()

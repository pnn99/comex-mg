"""Resultados da Seção 4. Associações municipais e exposição potencial por medida."""
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import numpy as np
import pandas as pd

from analise_cientifica import BASE, RAIZ
from analise_perfis import SAIDA as PERFIS, tabela_visual
from panorama_comercial import SAIDA as PANORAMA
from modelos_associacao import ajustar

SAIDA = RAIZ / "resultados/secao_4"
DESFECHOS = ["perdeu_eua_pct", "crescimento_simetrico_total_pct", "compensacao_mesmo_sh4_pct"]
CAMPOS = ["hhi_produtos", "hhi_destinos", "participacao_eua", "cv_mensal"]
CONTROLES = ["log_fob", "parcela_cafe", "parcela_minerio"]


def ler_csv(arquivo):
    return pd.read_csv(arquivo, sep=";", dtype={"CO_MUN": str, "SH4": str, "HTS8": str})


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
        linhas.append(dict(comparacao=janela, perfil=perfil, n_municipios_amostra=len(t),
                          n_eua=t.variacao_eua_pct.count(), mediana_variacao_eua_pct=t.variacao_eua_pct.median(),
                          pct_com_queda_eua=t.perdeu_eua_pct.mean(), pct_com_resistencia=t.resistiu_eua_pct.mean(),
                          n_total=t.variacao_total_pct.count(), mediana_variacao_total_pct=t.variacao_total_pct.median(),
                          n_compensacao_valida=t.compensacao_mesmo_sh4_pct.count(),
                          n_municipios_com_perda_eua=t.delta_eua.lt(0).sum(),
                          n_municipios_com_perda_bruta_sh4=t.perda_eua_sh4.gt(0).sum(),
                          n_municipios_com_ganho_outros=t.delta_outros.gt(0).sum(),
                          n_municipios_com_ganho_em_algum_sh4=t.ganho_outros_sh4.gt(0).sum(),
                          n_municipios_com_compensacao_positiva=t.compensado_sh4.gt(0).sum(),
                          percentual_municipios_com_compensacao=100*t.compensado_sh4.gt(0).mean(),
                          percentual_compensacao_entre_validos=(100*t.compensado_sh4.gt(0).sum() /
                              t.compensacao_mesmo_sh4_pct.count() if t.compensacao_mesmo_sh4_pct.count() else np.nan),
                          mediana_compensacao_pct=t.compensacao_mesmo_sh4_pct.median(),
                          perda_bruta_sh4_usd=t.perda_eua_sh4.sum(), compensado_sh4_usd=t.compensado_sh4.sum()))
    return pd.DataFrame(linhas)


def main():
    perfis = ler_csv(PERFIS / "municipios.csv")
    prod = ler_csv(PANORAMA / "produtos_municipios.csv").query("janela == 'estrutura'").copy()
    if prod.duplicated(["CO_MUN","SH4"]).any():
        raise ValueError("Duplicação de município e produto na janela estrutural.")
    exp = ler_csv(SAIDA / "exposicao_municipal_por_medida.csv")
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
    ajustes, diagnosticos = [], []

    def estimar(t, y, termos, **spec):
        familias = {"perdeu_eua_pct":["linear","logit"],
                    "compensacao_mesmo_sh4_pct":["linear","fracional"]}.get(y,["linear"])
        for familia in familias:
            coef, diag = ajustar(t, y, termos, familia, **spec)
            diagnosticos.append(diag)
            if not coef.empty:
                ajustes.append(coef)

    for janela in ["anual","inicial","bimestre"]:
        t = d[d.comparacao.eq(janela)].copy()
        for corte in (1,12,24):
            amostra = t[t.meses_ativos.ge(corte)]
            for y in DESFECHOS:
                termos = CAMPOS.copy()
                if y == "compensacao_mesmo_sh4_pct":
                    termos[1] = "log2_destinos_efetivos"
                estimar(amostra,y,termos+CONTROLES,comparacao=janela,min_meses=corte,modelo="indicadores")
            # Cenários do adicional inicial. Na janela anual representam exposição estrutural
            # ao regime de agosto associada a uma resposta que atravessa diversos regimes.
            for area, expos in exp[exp.medida.eq("brasil_inicial")].groupby("composicao"):
                amostra_exp = amostra.merge(expos,on="CO_MUN",how="left",validate="one_to_one")
                for limite in ["min","max"]:
                    campo = "exposicao_total_"+limite
                    for y in DESFECHOS:
                        estimar(amostra_exp,y,[campo,*CAMPOS,*CONTROLES],comparacao=janela,min_meses=corte,
                                modelo="tarifario_"+limite,composicao=area,medida="brasil_inicial")
                        # Especificação reduzida pré-definida para ambos os cenários.
                        reduzidos = [termo for termo in CAMPOS if termo != "participacao_eua"]
                        estimar(amostra_exp,y,[campo,*reduzidos,*CONTROLES],comparacao=janela,min_meses=corte,
                                modelo="tarifario_reduzido_"+limite,composicao=area,medida="brasil_inicial")
        grupos = t[t.perfil.notna()].copy()
        for perfil in ["P2","P3","P4","P5"]:
            grupos["perfil_"+perfil] = grupos.perfil.eq(perfil).astype(int)
        for y in DESFECHOS:
            estimar(grupos,y,["perfil_P2","perfil_P3","perfil_P4","perfil_P5",*CONTROLES],
                    comparacao=janela,min_meses=12,modelo="perfis")
    reg_todos = pd.concat(ajustes,ignore_index=True)
    reg = reg_todos[reg_todos.familia.eq("linear")]
    reg_todos[reg_todos.familia.eq("logit")].to_csv(SAIDA / "regressoes_logit.csv",sep=";",index=False)
    reg_todos[reg_todos.familia.eq("fracional")].to_csv(SAIDA / "regressoes_fracionais.csv",sep=";",index=False)
    pd.DataFrame(diagnosticos).to_csv(SAIDA / "diagnosticos_modelos.csv",sep=";",index=False)
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
    for nome, t in {
                    "resposta_por_perfil":comparacao, "regressoes_hc3":reg,
                    "compensacao_por_produto":por_produto.reset_index(), "resposta_municipal":d}.items():
        t.to_csv(SAIDA / f"{nome}.csv",sep=";",index=False)
    anual = comparacao[comparacao.comparacao.eq("anual")]
    tabela = anual[["perfil","n_eua","pct_com_queda_eua","mediana_variacao_total_pct","n_municipios_com_compensacao_positiva","mediana_compensacao_pct"]].copy()
    tabela.columns = ["Perfil","n EUA","Com queda (%)","Δ total (%)¹","Com compensação","Compensação (%)¹"]
    fig = tabela_visual(tabela, "4.4 · Resposta comercial por perfil prévio",
                        "¹ Medianas municipais · Ago/2024–jul/2025 e ago/2025–jul/2026 · Compensação dentro do mesmo município e SH4.")
    fig.savefig(SAIDA / "resposta_por_perfil.png",dpi=180,bbox_inches="tight")
    with PdfPages(SAIDA / "resultados_discussao.pdf") as pdf:
        paineis = [("4.1 · Estrutura pré-choque", RAIZ / "resultados/pre_choque/mapa_indicadores_mg.png"),
                   ("4.1 · Distribuição dos indicadores", PANORAMA / "visuais/01b_estrutura_municipal.png"),
                   *[(f"4.2 · {titulo}", PERFIS / f"{nome}.png") for titulo, nome in
                     [("Correlações","correlacoes"),("Validação","comparacao_modelos"),("Caracterização","caracterizacao"),("Perfis municipais","mapa_perfis")]],
                   ("4.3 · Trajetória mensal", PANORAMA / "visuais/01_historico.png"),
                   ("4.3 · FOB, peso e valor unitário", RAIZ / "resultados/periodo_choque/serie_historica_valor_quantidade.png"),
                   ("4.3 · Valor e quantidade por SH4 e destino", RAIZ / "resultados/periodo_choque/valor_quantidade_produto_destino.png"),
                   ("4.3 · Compensação por município", RAIZ / "resultados/periodo_choque/mapa_compensacao.png"),
                   ("4.3 · Resposta por período", PANORAMA / "visuais/02_fases.png"),
                   ("4.3 · Recuperação municipal após a queda inicial", RAIZ / "resultados/periodo_choque/recuperacao.png"),
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
        totais = exp.groupby(["medida","composicao"])[["usd_min","usd_max","total","eua"]].sum().reset_index()
        exposicoes = pd.DataFrame({
            "Medida": totais.medida, "Composição": totais.composicao,
            "Piso (%)": 100*totais.usd_min/totais.total, "Teto (%)": 100*totais.usd_max/totais.total,
            "FOB EUA resolvido (%)":100*(1-(totais.usd_max-totais.usd_min)/totais.eua)})
        fig = tabela_visual(exposicoes, "4.4 · Alcance tarifário potencial sobre a pauta prévia",
                            "FOB mundial de 2022–2024. As versões são avaliadas separadamente.")
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

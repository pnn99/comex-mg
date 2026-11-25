"""Seção 4.2. Perfis estruturais dos exportadores municipais de MG em 2022–2024."""
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.collections import PatchCollection
from matplotlib.patches import Patch
import numpy as np
import pandas as pd

from analise_cientifica import MALHA, METRICAS, SAIDA as PRE_CHOQUE, obter_malha
from analise_comex import sha256

ENTRADA = PRE_CHOQUE / "indicadores_municipais.csv"
SAIDA = PRE_CHOQUE.parent / "perfis_municipais"
CORTES = (1, 6, 12, 24, 36)
KS = range(2, 7)
SEMENTE = 2026
REPETICOES = 20
CORES = ["#226887", "#df8b32", "#41937b", "#87578c", "#a55744", "#537ab5"]
NOMES = ["HHI de produtos", "HHI de destinos", "Participação dos EUA", "CV mensal", "Meses ativos"]


def ler_indicadores():
    campos = ["CO_MUN", "municipio", "fob_pre_usd", "meses_ativos", *METRICAS]
    t = pd.read_csv(ENTRADA, sep=";", usecols=campos, dtype={"CO_MUN": str})
    t = t.set_index("CO_MUN").sort_index()
    numeros = t[["fob_pre_usd", "meses_ativos", *METRICAS]]
    if not (t.index.is_unique and t.index.str.fullmatch(r"31\d{5}").all() and np.isfinite(numeros).all().all()
            and t.fob_pre_usd.gt(0).all() and t.meses_ativos.isin(range(1, 37)).all()
            and t.cv_mensal.ge(0).all() and t[METRICAS[:3]].ge(0).all().all()
            and t[METRICAS[:3]].le(1 + 1e-12).all().all()):
        raise ValueError("Indicadores inválidos na base municipal pré-choque.")
    return t


def padronizar(x):
    escala = x.std(axis=0)
    return (x - x.mean(axis=0)) / np.where(escala > 0, escala, 1)


def quadrados(x, centros):
    return ((x[:, None, :] - centros[None, :, :]) ** 2).sum(axis=2)


def kmeans(x, k, rng):
    """Lloyd com oito inicializações k-means++ independentes."""
    melhor_custo = np.inf
    melhor = None
    for _ in range(8):
        centros = [x[rng.integers(len(x))]]
        proximidade = np.full(len(x), np.inf)
        while len(centros) < k:
            proximidade = np.minimum(proximidade, ((x - centros[-1]) ** 2).sum(axis=1))
            if proximidade.sum() == 0:
                raise ValueError(f"A amostra tem menos de {k} vetores distintos.")
            centros.append(x[rng.choice(len(x), p=proximidade / proximidade.sum())])
        centros = np.array(centros)
        anterior = None
        for _ in range(300):
            dist = quadrados(x, centros)
            grupos = dist.argmin(axis=1)
            if np.array_equal(grupos, anterior):
                custo = dist.min(axis=1).sum()
                if custo < melhor_custo:
                    melhor_custo, melhor = custo, grupos.copy()
                break
            contagens = np.bincount(grupos, minlength=k)
            if (contagens == 0).any():
                break  # descarta uma partida degenerada
            centros = np.stack([np.bincount(grupos, weights=v, minlength=k) / contagens for v in x.T], axis=1)
            anterior = grupos
    if melhor is None:
        raise ValueError(f"Nenhuma partida de K-Means convergiu com {k} grupos não vazios.")
    return melhor


def ward(x, ks):
    """Funde o par com menor aumento da soma de quadrados intragrupo."""
    centros = x.copy()
    pesos = np.ones(len(x), dtype=int)
    custos = quadrados(x, x) / 2
    np.fill_diagonal(custos, np.inf)
    grupos = np.arange(len(x))
    cortes = {}
    for restantes in range(len(x) - 1, min(ks) - 1, -1):
        i, j = np.unravel_index(np.argmin(custos), custos.shape)
        centros[i] = (pesos[i] * centros[i] + pesos[j] * centros[j]) / (pesos[i] + pesos[j])
        pesos[i] += pesos[j]
        pesos[j] = 0
        novos = ((centros - centros[i]) ** 2).sum(axis=1) * pesos * pesos[i] / (pesos + pesos[i])
        novos[pesos == 0] = np.inf
        novos[i] = np.inf
        custos[i, :] = custos[:, i] = novos
        custos[j, :] = custos[:, j] = np.inf
        grupos[grupos == j] = i
        if restantes in ks:
            cortes[restantes] = np.unique(grupos, return_inverse=True)[1]
    return cortes


def ari(a, b):
    """Índice de Rand ajustado, independente da numeração dos grupos."""
    a = np.unique(a, return_inverse=True)[1]
    b = np.unique(b, return_inverse=True)[1]
    colunas = b.max() + 1
    tabela = np.bincount(a * colunas + b, minlength=(a.max() + 1) * colunas).reshape(-1, colunas)

    def pares(n):
        return (n * (n - 1) / 2).sum()

    linhas, colunas = pares(tabela.sum(axis=1)), pares(tabela.sum(axis=0))
    esperado = linhas * colunas / pares(tabela.sum())
    maximo = (linhas + colunas) / 2
    return (pares(tabela) - esperado) / (maximo - esperado) if maximo != esperado else 1.0


def qualidade(x, dist, grupos):
    ids, contagens = np.unique(grupos, return_counts=True)
    medias = np.column_stack([dist[:, grupos == i].mean(axis=1) for i in ids])
    indices = np.arange(len(x))
    dentro = medias[indices, grupos] * contagens[grupos] / np.maximum(contagens[grupos] - 1, 1)
    medias[indices, grupos] = np.inf
    fora = medias.min(axis=1)
    sil = np.divide(fora - dentro, np.maximum(dentro, fora), out=np.zeros(len(x)), where=np.maximum(dentro, fora) > 0)
    sil[contagens[grupos] == 1] = 0
    centros = np.stack([x[grupos == i].mean(axis=0) for i in ids])
    raio = np.array([np.linalg.norm(x[grupos == i] - centros[i], axis=1).mean() for i in ids])
    separacao = np.sqrt(quadrados(centros, centros))
    np.fill_diagonal(separacao, np.inf)
    db = ((raio[:, None] + raio) / separacao).max(axis=1).mean()
    return sil.mean(), db, contagens.min()


def ajustar(x, semente):
    rng = np.random.default_rng(semente)
    modelos = {("Ward", k): v for k, v in ward(x, KS).items()}
    modelos.update({("K-Means", k): kmeans(x, k, rng) for k in KS})
    return modelos


def comparar_modelos(t):
    linhas, classificacoes = [], {}
    for corte in CORTES:
        amostra = t[t.meses_ativos >= corte]
        rng = np.random.default_rng(SEMENTE)
        subamostras = [np.sort(rng.choice(len(amostra), int(.8 * len(amostra)), replace=False))
                       for _ in range(REPETICOES)]
        for com_cv in (True, False):
            matriz = amostra[METRICAS if com_cv else METRICAS[:-1]].to_numpy()
            x = padronizar(matriz)
            modelos = ajustar(x, SEMENTE)
            estabilidade = {chave: [] for chave in modelos}
            for rodada, idx in enumerate(subamostras, 1):
                alternativos = ajustar(padronizar(matriz[idx]), SEMENTE + rodada)
                for chave, rotulos in alternativos.items():
                    estabilidade[chave].append(ari(modelos[chave][idx], rotulos))
            dist = np.sqrt(quadrados(x, x))
            for (metodo, k), grupos in modelos.items():
                sil, db, menor = qualidade(x, dist, grupos)
                p10, mediana, p90 = np.quantile(estabilidade[metodo, k], [.1, .5, .9])
                linhas.append((corte, com_cv, metodo, k, len(x), sil, db, menor, p10, mediana, p90))
                classificacoes[corte, com_cv, metodo, k] = pd.Series(grupos, index=amostra.index)
        print(f"Modelos avaliados com pelo menos {corte} meses ativos ({len(amostra)} municípios).", flush=True)
    colunas = ["min_meses", "com_cv", "metodo", "k", "municipios", "silhouette", "davies_bouldin",
               "menor_grupo", "ari_p10", "ari_mediana", "ari_p90"]
    return pd.DataFrame(linhas, columns=colunas), classificacoes


def selecionar(modelos):
    principal = modelos[(modelos.min_meses == 12) & modelos.com_cv].copy()
    aprovados = principal[principal.menor_grupo >= np.ceil(.05 * principal.municipios)]
    if aprovados.empty:
        raise ValueError("Nenhuma solução principal atingiu o tamanho exploratório mínimo.")
    postos = (aprovados.silhouette.rank(ascending=False) + aprovados.davies_bouldin.rank()
              + aprovados.ari_mediana.rank(ascending=False))
    principal["soma_postos"] = postos
    return principal.sort_values(["soma_postos", "k", "silhouette"], ascending=[True, True, False])


def sensibilidades(t, solucao, modelos):
    metodo, k = solucao.metodo, int(solucao.k)
    ref = modelos[12, True, metodo, k]
    linhas = []

    def comparar(corte, com_cv, algoritmo, extremos, rotulos):
        comuns = ref.index.intersection(rotulos.index)
        linhas.append((corte, com_cv, algoritmo, k, extremos, len(comuns), ari(ref.loc[comuns], rotulos.loc[comuns])))

    for (corte, com_cv, algoritmo, n), rotulos in modelos.items():
        if n == k:
            comparar(corte, com_cv, algoritmo, "originais", rotulos)
    matriz = t.loc[ref.index, METRICAS].to_numpy()
    limites = np.quantile(matriz, [.01, .99], axis=0)
    limitado = padronizar(np.clip(matriz, *limites))
    corte_extremos = (ward(limitado, [k])[k] if metodo == "Ward"
                      else kmeans(limitado, k, np.random.default_rng(SEMENTE)))
    comparar(12, True, metodo, "p01_p99", pd.Series(corte_extremos, index=ref.index))
    return pd.DataFrame(linhas, columns=["min_meses", "com_cv", "metodo", "k", "extremos", "municipios_comuns", "ari_referencia"])


def caracterizar(t, rotulos):
    amostra = t.loc[rotulos.index]
    # Identificadores estáveis para a apresentação, ordenados por HHI mediano de produtos.
    ordem = amostra.groupby(rotulos)[METRICAS].median().sort_values(METRICAS).index
    perfis = rotulos.map({grupo: f"P{i}" for i, grupo in enumerate(ordem, 1)}).rename("perfil")
    grupos = amostra.groupby(perfis)
    resumo = grupos[METRICAS + ["meses_ativos"]].median()
    resumo.insert(0, "municipios", grupos.size())
    resumo["fob_usd"] = grupos.fob_pre_usd.sum()
    resumo["pct_fob_amostra"] = 100 * resumo.fob_usd / amostra.fob_pre_usd.sum()
    x = pd.DataFrame(padronizar(amostra[METRICAS].to_numpy()), index=amostra.index)
    dist = ((x - x.groupby(perfis).transform("mean")) ** 2).sum(axis=1)
    resumo["municipio_proximo_centro"] = dist.groupby(perfis).idxmin().map(amostra.municipio)
    return perfis, resumo, grupos[METRICAS + ["meses_ativos"]].quantile([.25, .5, .75]).rename_axis(["perfil", "quantil"])


def mapa(perfis, t, geo):
    fig, ax = plt.subplots(figsize=(10, 7))
    paleta = dict(zip(sorted(perfis.unique()), CORES))
    cores = [paleta[perfis[c]] if c in perfis else "#aaaeb0" if c in t.index else "#e3e5e5" for c in geo]
    ax.add_collection(PatchCollection(list(geo.values()), facecolors=cores, edgecolors="white", linewidths=.25))
    ax.autoscale_view()
    ax.set_aspect(1 / np.cos(np.deg2rad(18.5)))
    ax.axis("off")
    legenda = [Patch(color=cor, label=f"{p} · {sum(perfis == p)} municípios") for p, cor in paleta.items()]
    legenda += [Patch(color="#aaaeb0", label=f"1–11 meses ativos · {len(t)-len(perfis)}"),
                Patch(color="#e3e5e5", label=f"Sem FOB positivo · {len(geo)-len(t)}")]
    fig.legend(handles=legenda, loc="center right", bbox_to_anchor=(.99,.49), frameon=False)
    fig.subplots_adjust(left=.025, right=.79, top=.88, bottom=.09)
    fig.suptitle("Perfis da estrutura exportadora municipal em Minas Gerais", fontsize=16)
    fig.text(.04,.045,"2022–2024 · Domicílio fiscal do exportador · Comex Stat/MDIC · Malha simplificada de Mapas de Minas Gerais", fontsize=9)
    return fig


def correlacoes(t):
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.8), layout="constrained")
    matrizes = []
    for ax, corte in zip(axes, [1, 12]):
        amostra = t[t.meses_ativos >= corte]
        rho = amostra[METRICAS + ["meses_ativos"]].rank().corr()
        matrizes.append(rho.assign(min_meses=corte).rename_axis("variavel").reset_index())
        ax.imshow(rho, cmap="RdBu", vmin=-1, vmax=1)
        ax.set_xticks(range(5), NOMES, rotation=30, ha="right", fontsize=8)
        ax.set_yticks(range(5), NOMES, fontsize=8)
        ax.set_title(f"Mínimo de {corte} mês(es) · n = {len(amostra)}")
        for (i,j), v in np.ndenumerate(rho.to_numpy()):
            ax.text(j, i, f"{v:.2f}".replace(".", ","), ha="center", va="center",
                    color="white" if abs(v) > .65 else "#15242e", fontsize=10)
    fig.suptitle("Correlações de Spearman · Comex Stat/MDIC · MG, 2022–2024", fontsize=15)
    return fig, pd.concat(matrizes, ignore_index=True)


def tabela_visual(dados, titulo, rodape):
    fig, ax = plt.subplots(figsize=(11, 6))
    ax.axis("off")
    fig.suptitle(titulo, y=.92, fontsize=17)
    valores = dados.map(lambda v: f"{v:.3f}".replace(".", ",") if isinstance(v, float) else str(v))
    tabela = ax.table(cellText=valores.to_numpy(), colLabels=valores.columns, cellLoc="center",
                      bbox=[0,.13,1,.77])
    for (linha, _), celula in tabela.get_celld().items():
        celula.set_facecolor("#245067" if linha == 0 else "#eaf1f3" if linha % 2 else "#fafafa")
        celula.set_edgecolor("white")
        if linha == 0:
            celula.set_text_props(color="white", weight="bold")
    fig.text(.065,.07,rodape,fontsize=9)
    return fig


def main():
    t = ler_indicadores()
    geo, _ = obter_malha(MALHA)
    if not t.index.isin(geo).all():
        raise ValueError("Há municípios dos indicadores sem correspondência cartográfica.")
    modelos, rotulos = comparar_modelos(t)
    principal = selecionar(modelos)
    escolha = principal.iloc[0]
    ref = rotulos[12, True, escolha.metodo, escolha.k]
    perfis, resumo, quartis = caracterizar(t, ref)
    sens = sensibilidades(t, escolha, rotulos)
    fig_corr, rho = correlacoes(t)
    SAIDA.mkdir(parents=True, exist_ok=True)
    for nome, quadro in {
        "correlacoes": rho, "modelos": modelos, "comparacao_principal": principal,
        "sensibilidade": sens, "municipios": t.join(perfis).reset_index(),
        "caracterizacao": resumo.reset_index(), "quartis": quartis.reset_index(),
    }.items():
        quadro.to_csv(SAIDA / f"{nome}.csv", sep=";", index=False)
    comp = principal[["metodo","k","silhouette","davies_bouldin","ari_mediana","menor_grupo"]].copy()
    comp.columns = ["Método","Grupos","Silhouette","Davies–Bouldin","ARI mediano","Menor grupo"]
    tab = resumo.reset_index()[["perfil","municipios",*METRICAS,"meses_ativos","pct_fob_amostra"]].copy()
    tab["participacao_eua"] *= 100
    tab.columns = ["Perfil","Municípios","HHI produto","HHI destino","EUA (%)","CV","Meses ativos","FOB (%)"]
    with PdfPages(SAIDA / "secao_4_2.pdf") as pdf:
        for nome, fig in [
            ("correlacoes", fig_corr),
            ("comparacao_modelos", tabela_visual(comp, "Comparação dos modelos na amostra de referência",
             f"Comex Stat/MDIC · 2022–2024 · n = {len(ref)} · 4 indicadores · ARI em 20 subamostras. Primeira linha: solução exploratória.")),
            ("caracterizacao", tabela_visual(tab, "Características dos perfis municipais",
             "Comex Stat/MDIC · 2022–2024 · Medianas municipais. FOB (%) representa a parcela do valor exportado pela amostra.")),
            ("mapa_perfis", mapa(perfis, t, geo)),
        ]:
            fig.savefig(SAIDA / f"{nome}.png", dpi=180, bbox_inches="tight")
            pdf.savefig(fig, bbox_inches="tight")
            plt.close(fig)
    print(f"Indicadores SHA-256 {sha256(ENTRADA)}. Referência: {escolha.metodo}, k={escolha.k}. Saída: {SAIDA}")


if __name__ == "__main__":
    main()

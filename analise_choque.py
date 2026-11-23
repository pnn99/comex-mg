from pathlib import Path
import hashlib, json

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.collections import PolyCollection
from matplotlib.colors import TwoSlopeNorm, SymLogNorm

# ----------------------------- CONFIGURAÇÃO -----------------------------
BASE = Path("dados/tratados/exportacoes_mg_atual.csv")
MALHA = Path("dados/malhas/mg_municipios.geojson")
SAIDA = Path("resultados/periodo_choque")
SAIDA.mkdir(parents=True, exist_ok=True)

EUA = "249"  # código do país no Comex Stat

# Janelas de comparação (12 meses antes e 12 meses depois do início da tarifa de 50%)
ANTES = ("2024-08-01", "2025-07-31")
DEPOIS = ("2025-08-01", "2026-07-31")

# Marcos tarifários (conferir datas e listas nas fontes oficiais antes de citar no artigo)
MARCOS = [
    ("2025-08-06", "6/ago/2025: tarifa de 50%"),
    ("2026-02-20", "20/fev/2026: ordens revogadas"),
    ("2026-07-22", "22/jul/2026: Seção 301 (25%)"),
]

MIN_FOB_MAPA = 1_000_000  # só colore no mapa municípios com pelo menos US$ 1 milhão aos EUA na janela "antes"
# --------------------------------------------------------------------------

plt.rcParams.update({"figure.dpi": 110, "savefig.dpi": 160, "axes.spines.top": False,
                     "axes.spines.right": False, "font.size": 10})
for caminho in (BASE, MALHA):
    assert caminho.is_file(), f"Arquivo não encontrado: {caminho.resolve()} (abra o notebook na raiz do projeto)"

def sha256(arquivo):
    h = hashlib.sha256()
    with open(arquivo, "rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()

df = pd.read_csv(BASE, sep=";", encoding="utf-8-sig",
                 dtype={"SH4": "string", "CO_PAIS": "string", "CO_MUN": "string"},
                 parse_dates=["DATA"])

print(f"Registros: {len(df):,}".replace(",", "."))
print(f"Cobertura: {df.DATA.min():%m/%Y} a {df.DATA.max():%m/%Y} ({df.DATA.nunique()} meses)")
print(f"FOB 2022-2024: US$ {df[(df.DATA>='2022-01-01')&(df.DATA<'2025-01-01')].VL_FOB.sum():,.0f}".replace(",", "."))
print("SHA-256 da base:", sha256(BASE))

df["eua"] = df["CO_PAIS"].eq(EUA)
a0, a1 = pd.Timestamp(ANTES[0]), pd.Timestamp(ANTES[1])
d0, d1 = pd.Timestamp(DEPOIS[0]), pd.Timestamp(DEPOIS[1])
assert df.DATA.max() >= d1, "A base não cobre a janela 'depois'."
antes = df[(df.DATA >= a0) & (df.DATA <= a1)]
depois = df[(df.DATA >= d0) & (df.DATA <= d1)]
print(f"Janela antes: {a0:%m/%Y}–{a1:%m/%Y} | depois: {d0:%m/%Y}–{d1:%m/%Y}")

NOMES_SH4 = {
    "0901": "Café", "2601": "Minérios de ferro e concentrados", "7201": "Ferro fundido bruto (gusa)",
    "7202": "Ferroligas", "7304": "Tubos sem costura de ferro ou aço", "7207": "Semiacabados de ferro/aço não ligado",
    "8411": "Turbinas a gás (turborreatores etc.)", "0202": "Carne bovina congelada",
    "8112": "Outros metais (nióbio, gálio, vanádio etc.)", "2804": "Hidrogênio, gases raros e outros não metais",
    "1701": "Açúcar de cana ou beterraba", "7108": "Ouro", "3105": "Adubos minerais ou químicos",
    "8503": "Partes de motores e geradores elétricos", "8481": "Torneiras e válvulas",
    "8407": "Motores de êmbolo", "8504": "Transformadores elétricos",
    "7103": "Pedras preciosas e semipreciosas (exceto diamantes)",
}
NOMES_PAISES = {
    "249": "Estados Unidos", "160": "China", "023": "Alemanha", "063": "Argentina", "069": "Austrália",
    "080": "Bahrein", "087": "Bélgica", "149": "Canadá", "361": "Índia", "386": "Itália", "399": "Japão",
    "455": "Malásia", "573": "Países Baixos", "628": "Reino Unido", "767": "Suíça", "827": "Turquia",
    "365": "Indonésia", "493": "México", "190": "Coreia do Sul", "271": "Finlândia",
}
nome_sh4 = lambda c: f"{c} {NOMES_SH4.get(c, '')}".strip()
nome_pais = lambda c: NOMES_PAISES.get(c, f"país {c}")

with open(MALHA, encoding="utf-8") as f:
    malha = json.load(f)
NOMES_MUN = {ft["properties"]["id"]: ft["properties"]["name"] for ft in malha["features"]}
nome_mun = lambda c: NOMES_MUN.get(c, c)
print(len(NOMES_MUN), "municípios na malha")

mensal = (df.assign(grupo=np.where(df.eua, "EUA", "Demais destinos"))
            .groupby(["DATA", "grupo"]).VL_FOB.sum().unstack(fill_value=0) / 1e6)
mensal["Total"] = mensal.sum(axis=1)
mensal["Participação EUA (%)"] = mensal["EUA"] / mensal["Total"] * 100
mensal.round(2).to_csv(SAIDA / "serie_mensal_eua_outros.csv", sep=";", decimal=",")

rec = mensal.loc["2022-01-01":]
fig, ax = plt.subplots(3, 1, figsize=(10, 8.5), sharex=True)
ax[0].plot(rec.index, rec["Demais destinos"], marker="o", ms=3, color="tab:blue")
ax[0].set_ylabel("Demais destinos\n(US$ milhões)")
ax[1].plot(rec.index, rec["EUA"], marker="o", ms=3, color="tab:orange")
ax[1].set_ylabel("Estados Unidos\n(US$ milhões)")
ax[2].plot(rec.index, rec["Participação EUA (%)"], color="tab:green", marker="o", ms=3)
ax[2].set_ylabel("Participação dos\nEUA no FOB (%)")
for x, rotulo in MARCOS:
    for a in ax:
        a.axvline(pd.Timestamp(x), color="gray", ls="--", lw=1)
    ymin, ymax = ax[0].get_ylim()
    ax[0].text(pd.Timestamp(x), ymin + 0.04 * (ymax - ymin), rotulo + " ", rotation=90, va="bottom", ha="right",
               fontsize=8, color="dimgray", bbox=dict(facecolor="white", alpha=0.8, edgecolor="none", pad=1.5))
for a in ax:
    a.grid(True, alpha=0.3)
ax[2].xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 7]))
ax[2].xaxis.set_major_formatter(mdates.DateFormatter("%m/%Y"))
fig.suptitle("Exportações mensais de Minas Gerais (FOB): demais destinos e Estados Unidos, 2022 a 2026")
fig.tight_layout()
fig.savefig(SAIDA / "fig_serie_mensal.png")
plt.close()

def total(d, so_eua=None):
    x = d if so_eua is None else d[d.eua == so_eua]
    return x.VL_FOB.sum() / 1e6

linhas = []
for nome, f in [("Total de MG", None), ("Estados Unidos", True), ("Demais destinos", False)]:
    a, d = total(antes, f), total(depois, f)
    linhas.append([nome, a, d, d - a, (d / a - 1) * 100])
pa, pd_ = total(antes, True) / total(antes) * 100, total(depois, True) / total(depois) * 100
linhas.append(["Participação dos EUA (%)", pa, pd_, pd_ - pa, np.nan])
resumo = pd.DataFrame(linhas, columns=["Medida", "Antes (US$ mi)", "Depois (US$ mi)", "Variação (US$ mi ou p.p.)", "Variação (%)"])
resumo.round(2).to_csv(SAIDA / "tabela_agregados.csv", sep=";", decimal=",", index=False)
print(resumo.round(2))

def variacao(chave):
    a = antes[antes.eua].groupby(chave).VL_FOB.sum()
    d = depois[depois.eua].groupby(chave).VL_FOB.sum()
    t = pd.concat([a, d], axis=1, keys=["antes", "depois"]).fillna(0)
    t["variacao"] = t.depois - t.antes
    t["variacao_pct"] = np.where(t.antes > 0, (t.depois / t.antes - 1) * 100, np.nan)
    t["part_antes_pct"] = t.antes / t.antes.sum() * 100
    return t

prod = variacao("SH4")
prod.insert(0, "produto", [nome_sh4(c) for c in prod.index])
prod_m = prod.copy()
for c in ["antes", "depois", "variacao"]:
    prod_m[c] = prod_m[c] / 1e6
prod_m.round(2).sort_values("variacao").to_csv(SAIDA / "produtos_sh4_eua.csv", sep=";", decimal=",")

quedas = prod_m.sort_values("variacao").head(10)
altas = prod_m.sort_values("variacao").tail(5)
mostra = pd.concat([quedas, altas.iloc[::-1]])
mostra = mostra.rename(columns={"antes": "Antes (US$ mi)", "depois": "Depois (US$ mi)", "variacao": "Variação (US$ mi)",
                                "variacao_pct": "Variação (%)", "part_antes_pct": "% do total aos EUA (antes)"})
print(mostra.round(1))

g = pd.concat([quedas, altas]).sort_values("variacao")
fig, ax = plt.subplots(figsize=(9, 6))
cores = ["tab:red" if v < 0 else "tab:blue" for v in g.variacao]
ax.barh(g.produto, g.variacao, color=cores)
ax.axvline(0, color="black", lw=0.8)
ax.set_xlabel("Variação do FOB para os EUA (US$ milhões)")
ax.set_title("Produtos (SH4) com maiores quedas e altas nas vendas aos EUA\n(12 meses depois menos 12 meses antes de ago/2025)", fontsize=10)
ax.grid(True, axis="x", alpha=0.3)
fig.tight_layout()
fig.savefig(SAIDA / "fig_produtos_sh4.png")
plt.close()

mun = variacao("CO_MUN")
mun.insert(0, "municipio", [nome_mun(c) for c in mun.index])
mun_m = mun.copy()
for c in ["antes", "depois", "variacao"]:
    mun_m[c] = mun_m[c] / 1e6
mun_m.round(2).sort_values("variacao").to_csv(SAIDA / "municipios_eua.csv", sep=";", decimal=",")

top_mun = mun_m.sort_values("variacao").head(15).rename(columns={
    "antes": "Antes (US$ mi)", "depois": "Depois (US$ mi)", "variacao": "Variação (US$ mi)",
    "variacao_pct": "Variação (%)", "part_antes_pct": "% do total aos EUA (antes)"})
print(top_mun.round(1))

g = mun_m.sort_values("variacao").head(15).iloc[::-1]
fig, ax = plt.subplots(figsize=(9, 5.5))
ax.barh(g.municipio, g.variacao, color="tab:red")
ax.set_xlabel("Variação do FOB para os EUA (US$ milhões)")
ax.set_title("Municípios com maiores quedas nas vendas aos EUA")
ax.grid(True, axis="x", alpha=0.3)
fig.tight_layout()
fig.savefig(SAIDA / "fig_municipios_queda.png")
plt.close()

def var_destino():
    a = antes.groupby("CO_PAIS").VL_FOB.sum()
    d = depois.groupby("CO_PAIS").VL_FOB.sum()
    t = pd.concat([a, d], axis=1, keys=["antes", "depois"]).fillna(0)
    t["variacao"] = t.depois - t.antes
    t["variacao_pct"] = np.where(t.antes > 0, (t.depois / t.antes - 1) * 100, np.nan)
    t.insert(0, "pais", [nome_pais(c) for c in t.index])
    for c in ["antes", "depois", "variacao"]:
        t[c] = t[c] / 1e6
    return t

dest = var_destino()
dest.round(2).sort_values("variacao").to_csv(SAIDA / "destinos.csv", sep=";", decimal=",")
g = pd.concat([dest.sort_values("variacao").head(8), dest.sort_values("variacao").tail(8)]).sort_values("variacao")
fig, ax = plt.subplots(figsize=(9, 6))
ax.barh(g.pais, g.variacao, color=["tab:red" if v < 0 else "tab:blue" for v in g.variacao])
ax.axvline(0, color="black", lw=0.8)
ax.set_xlabel("Variação do FOB (US$ milhões): 12 meses depois menos 12 meses antes")
ax.set_title("Destinos das exportações de MG: maiores perdas e ganhos")
ax.grid(True, axis="x", alpha=0.3)
fig.tight_layout()
fig.savefig(SAIDA / "fig_destinos.png")
plt.close()
print(dest.sort_values("variacao").head(8).round(1)); print(dest.sort_values("variacao").tail(8).iloc[::-1].round(1))

def aneis(feature):
    g = feature["geometry"]
    if g["type"] == "Polygon":
        return [np.array(g["coordinates"][0])]
    if g["type"] == "MultiPolygon":
        return [np.array(p[0]) for p in g["coordinates"]]
    return []

formas, codigos = [], []
for ft in malha["features"]:
    for anel in aneis(ft):
        formas.append(anel)
        codigos.append(ft["properties"]["id"])
codigos = pd.Series(codigos)

base_mapa = mun.reindex(codigos.unique())
validos = (base_mapa.antes >= MIN_FOB_MAPA)
pct = base_mapa.variacao_pct.where(validos).clip(-100, 100)
absol = (base_mapa.variacao / 1e6).where(validos)

fig, eixos = plt.subplots(1, 2, figsize=(12, 6))
paineis = [
    (pct, "Variação percentual (%)", TwoSlopeNorm(vmin=-100, vcenter=0, vmax=100)),
    (absol, "Variação absoluta (US$ milhões)",
     SymLogNorm(linthresh=1, vmin=-max(abs(absol.min()), abs(absol.max())), vmax=max(abs(absol.min()), abs(absol.max())))),
]
for ax, (serie, titulo, norm) in zip(eixos, paineis):
    cmap = plt.get_cmap("RdBu").copy()
    valores = codigos.map(serie)
    cores = [cmap(norm(v)) if pd.notna(v) else (0.88, 0.88, 0.88, 1) for v in valores]
    pc = PolyCollection(formas, facecolors=cores, edgecolors="white", linewidths=0.2)
    ax.add_collection(pc)
    xs = np.concatenate([f[:, 0] for f in formas]); ys = np.concatenate([f[:, 1] for f in formas])
    ax.set_xlim(xs.min(), xs.max()); ax.set_ylim(ys.min(), ys.max())
    ax.set_aspect("equal"); ax.axis("off"); ax.set_title(titulo)
    sm = plt.cm.ScalarMappable(norm=norm, cmap=cmap); sm.set_array([])
    cb = fig.colorbar(sm, ax=ax, shrink=0.65, orientation="horizontal", pad=0.02)
    if "absoluta" in titulo:
        lim = norm.vmax
        ticks = [t for t in [-100, -10, -1, 0, 1, 10, 100] if abs(t) <= lim]
        cb.set_ticks(ticks); cb.set_ticklabels([str(t) for t in ticks])
fig.suptitle("Variação das exportações aos EUA por município: 12 meses depois menos 12 meses antes de ago/2025\n"
             "(cinza: sem base de comparação suficiente)", fontsize=11)
fig.tight_layout(rect=(0, 0, 1, 0.93))
fig.savefig(SAIDA / "mapa_variacao_eua.png")
plt.close()
print(f"{int(validos.sum())} municípios coloridos de {len(validos)} na malha.")

resumo_txt = {
    "base_registros": int(len(df)),
    "base_cobertura": f"{df.DATA.min():%m/%Y} a {df.DATA.max():%m/%Y}",
    "base_sha256": sha256(BASE),
    "janela_antes": f"{a0:%m/%Y} a {a1:%m/%Y}",
    "janela_depois": f"{d0:%m/%Y} a {d1:%m/%Y}",
    "fob_total_antes_usd_mi": round(total(antes), 1),
    "fob_total_depois_usd_mi": round(total(depois), 1),
    "fob_eua_antes_usd_mi": round(total(antes, True), 1),
    "fob_eua_depois_usd_mi": round(total(depois, True), 1),
    "participacao_eua_antes_pct": round(pa, 2),
    "participacao_eua_depois_pct": round(pd_, 2),
    "municipios_com_vendas_eua_antes": int((mun.antes > 0).sum()),
    "municipios_com_queda_eua": int((mun.variacao < 0).sum()),
}
with open(SAIDA / "resumo_numeros.json", "w", encoding="utf-8") as f:
    json.dump(resumo_txt, f, ensure_ascii=False, indent=2)
print(resumo_txt)

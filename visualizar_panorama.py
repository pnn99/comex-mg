"""Figuras e tabelas do panorama do Comex MG, a partir dos CSVs da análise."""
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.collections import PatchCollection
from matplotlib.colors import Normalize, SymLogNorm
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter

from analise_cientifica import MALHA, obter_malha

PASTA = Path(__file__).resolve().parent / "resultados/panorama"
TINTA, AZUL, VERDE, COBRE, CINZA = "#18364a", "#286194", "#147a73", "#ac4c32", "#647887"
FILIGRANA = "#d9e2e6"
ANUAL = "Ago/2025–jul/2026 em relação a ago/2024–jul/2025"
MERCADOS = {"eua": "EUA", "outros": "Demais destinos", "total": "Total de MG"}
MODELOS = {"media_3": "Média de 3 meses", "nivel_sazonal": "Nível com sazonalidade",
           "sazonal_12": "Mesmo mês do ano anterior"}
MESES = "jan fev mar abr mai jun jul ago set out nov dez".split()
PRODUTOS = {"0901": "Café", "7201": "Ferro-gusa", "7304": "Tubos sem costura",
            "2601": "Minérios de ferro", "7202": "Ferroligas", "1201": "Soja",
            "7108": "Ouro", "8601": "Locomotivas elétricas", "4409": "Madeira perfilada",
            "0101": "Equinos vivos", "4415": "Embalagens de madeira", "8104": "Magnésio",
            "7207": "Semiacabados de ferro ou aço", "2804": "Hidrogênio e outros não metais",
            "8411": "Turborreatores e turbinas a gás", "2821": "Óxidos e hidróxidos de ferro"}


def num(x, casas=1, sinal=False):
    if pd.isna(x):
        return "—"
    return format(x, f"{'+' if sinal else ''},.{casas}f").translate(str.maketrans(",.-", ".,−"))


def data(m):
    p = pd.Period(m, freq="M")
    return f"{MESES[p.month-1]}/{p.year}"


def janela(a, b):
    return data(a) if a == b else f"{data(a)}–{data(b)}"


def produto(codigo):
    return f"{codigo}  {PRODUTOS.get(codigo, '')}".strip()


def pagina(titulo, sub):
    fig = plt.figure(figsize=(15.4, 8.7))
    fig.text(.053,.94,titulo, size=26, weight="bold", color=TINTA, va="top")
    fig.text(.055,.866,sub, size=12, color=CINZA, va="top")
    fig.add_artist(Line2D([.054,.952],[.819,.819], transform=fig.transFigure,color=FILIGRANA))
    return fig


def titulo_eixo(ax, titulo):
    ax.set_title(titulo, loc="left", color=TINTA, weight="bold", fontsize=12, pad=11)
    ax.tick_params(labelsize=9, colors=TINTA, length=0)
    ax.set_axisbelow(True)
    ax.spines[:].set_visible(False)


def tabela(fig, titulo, colunas, linhas, larguras=None, pos=(.538,.225,.412,.51), fonte=10):
    ax = fig.add_axes(pos)
    ax.axis("off")
    titulo_eixo(ax, titulo)
    t = ax.table(cellText=linhas, colLabels=colunas, colWidths=larguras,
                 loc="center", cellLoc="right", bbox=[0,0,1,1])
    t.auto_set_font_size(False)
    t.set_fontsize(fonte)
    for (r,c), cel in t.get_celld().items():
        cel.set_edgecolor("white")
        cel.set_linewidth(1)
        cel.PAD = .065
        cel.set_facecolor(TINTA if r==0 else ("#edf3f4" if r%2 else "#f7f9fa"))
        cel.set_text_props(color="white" if r==0 else TINTA,
                           ha="left" if c==0 else "right", weight="bold" if r==0 else "normal")
    return ax


def barras(fig, rotulos, valores, titulo, unidade, cor=None, pos=(.163,.235,.32,.48)):
    ax = fig.add_axes(pos)
    y = np.arange(len(rotulos))
    ax.barh(y, valores, height=.58, color=cor or [VERDE if v>=0 else COBRE for v in valores])
    ax.set_yticks(y,rotulos)
    ax.invert_yaxis()
    ax.axvline(0,color=CINZA,linewidth=.8)
    ax.grid(axis="x",color=FILIGRANA)
    ax.set_xlabel(unidade, fontsize=10)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: num(x,0)))
    titulo_eixo(ax,titulo)
    return ax


def notas(fig, texto):
    fig.text(.055,.108,texto,fontsize=10.5,color=TINTA,va="center",linespacing=1.5)


def historico(h, saz):
    fig = pagina("Trajetória e sazonalidade das exportações",
                 f"Minas Gerais • {janela(h.mes.iloc[0],h.mes.iloc[-1])} • Valores FOB correntes")
    for i,(campo,cor) in enumerate([("eua",AZUL),("outros",VERDE)]):
        ax = fig.add_axes([.09,.495-i*.27,.42,.175])
        datas = pd.to_datetime(h.mes)
        ax.plot(datas,h[campo]/1e6,color=cor,lw=1.1)
        ax.plot(datas,h[campo+"_mm12"]/1e6,color=TINTA,lw=1.8,label="Média móvel de 12 meses")
        ax.axvline(pd.Timestamp("2025-08-01"),ls=":",color=COBRE)
        ax.grid(axis="y",color=FILIGRANA)
        ax.xaxis.set_major_locator(mdates.YearLocator(2))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        titulo_eixo(ax,f"{MERCADOS[campo]}  ·  US$ milhões por mês")
        if not i:
            ax.legend(fontsize=8,loc="upper left")
    linhas = [[MESES[int(r.mes_calendario)-1],num(100*(r.eua-1),1,True),
               num(100*(r.outros-1),1,True)] for r in saz.itertuples()]
    tabela(fig,"Sazonalidade média em 2015–2024",["Mês","EUA (%)","Demais destinos (%)"],linhas)
    notas(fig,"A linha pontilhada marca agosto de 2025. A tabela compara cada mês à média mensal do próprio ano e depois calcula a média entre anos.")
    return fig


def fases(f, p):
    f = f.pivot(index=["inicio","fim"],columns="medida",values="variacao_pct")
    rotulos = [janela(a,b) for a,b in f.index]
    fig = pagina("Mudanças durante e após agosto de 2025","Cada período é comparado aos mesmos meses do ano anterior.")
    ax=fig.add_axes([.17,.23,.31,.49])
    y=np.arange(len(f))
    for campo,cor,offset,label in [("eua",AZUL,-.16,"FOB EUA"),("kg_eua",COBRE,.16,"Peso EUA")]:
        ax.barh(y+offset,f[campo],height=.28,color=cor,label=label)
    ax.set_yticks(y,rotulos)
    ax.invert_yaxis()
    ax.axvline(0,color=TINTA,lw=.8)
    ax.grid(axis="x",color=FILIGRANA)
    ax.set_xlabel("Variação interanual (%)")
    ax.legend(loc="lower center",bbox_to_anchor=(.5,1.0),ncol=2,fontsize=9)
    titulo_eixo(ax,"")
    linhas = [[label,*[num(r[c],1,True) for c in ["eua","kg_eua","outros","total"]]]
              for label,(_,r) in zip(rotulos,f.iterrows())]
    tabela(fig,"Variação interanual (%)",["Período","FOB\nEUA","Kg\nEUA","FOB\ndemais","FOB\ntotal"],
           linhas,[.37,.15,.14,.17,.17],fonte=9.8)
    v=p.loc["depois_12",["eua","outros"]]/p.loc["antes_12",["eua","outros"]]-1
    t=p.loc[["trimestre_t2","trimestre_t1","trimestre_t0"]]
    tri="  →  ".join(f"{data(r.fim)}: {num(r.eua/1e9,2)}" for r in t.itertuples())
    notas(fig,f"Nos 12 meses posteriores ao marco, o FOB variou {num(100*v.eua,1,True)}% nos EUA e {num(100*v.outros,1,True)}% nos demais destinos.\n"
          f"FOB aos EUA nos trimestres encerrados em cada data, em US$ bilhões: {tri}.")
    return fig


def dependencia(c):
    s=c[c.meses_ativos.ge(12)].nlargest(10,"vulnerabilidade_pct")
    n=c.meses_ativos.ge(12).sum()
    fig=pagina("Municípios com maior dependência concentrada",
               f"Dez maiores índices entre {n} municípios com pelo menos 12 meses ativos em 2022–2024")
    ax=barras(fig,s.municipio,s.variacao_eua_pct,"Resposta anual das vendas aos EUA","Variação do FOB (%)")
    ax.margins(x=.08)
    linhas=[[r.municipio,r.sh4_principal_eua,num(r.vulnerabilidade_pct,2),num(r.delta_eua/1e3,1,True)]
            for r in s.itertuples()]
    tabela(fig,"Dependência prévia e mudança em dólares",["Município","SH4","Índice (%)","Δ EUA\nUS$ mil"],
           linhas,[.40,.12,.21,.27])
    notas(fig,"Índice = FOB do maior SH4 vendido aos EUA / FOB mundial do município no triênio, em %.\n"
          f"{ANUAL}. No universo com FOB positivo, {c.vulnerabilidade_pct.eq(100).sum()} municípios empataram em 100%.")
    return fig


def estrutura(cidades):
    c = cidades[cidades.fob_pre_usd.gt(0)]
    fig = pagina("Como era a pauta dos municípios antes do choque?",
                 f"2022–2024 • {len(c)} municípios com FOB positivo • Cada município tem o mesmo peso")
    ax = fig.add_axes([.092, .25, .39, .46])
    for coluna, rotulo, cor in [("hhi_produtos", "Concentração por produto", AZUL),
                                 ("hhi_destinos", "Concentração por destino", VERDE),
                                 ("participacao_eua", "Participação dos EUA", COBRE)]:
        ax.ecdf(c[coluna], label=rotulo, color=cor, linewidth=2)
    ax.set_xlim(0, 1)
    ax.set_xlabel("Valor do indicador")
    ax.set_ylabel("Municípios com indicador até esse valor (%)")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda y, _: num(100 * y, 0)))
    ax.grid(color=FILIGRANA)
    ax.legend(fontsize=9, loc="lower right")
    titulo_eixo(ax, "Distribuição acumulada entre municípios")
    campos = [
        ("hhi_produtos", "HHI de produtos", 1), ("hhi_destinos", "HHI de destinos", 1),
        ("numero_efetivo_produtos", "Produtos efetivos", 1), ("numero_efetivo_destinos", "Destinos efetivos", 1),
        ("maior_participacao_produtos", "Maior produto (%)", 100),
        ("maior_participacao_destinos", "Maior destino (%)", 100),
        ("cv_mensal", "Volatilidade mensal (CV)", 1), ("participacao_eua", "Parcela para os EUA (%)", 100),
        ("vulnerabilidade_pct", "Maior SH4 para os EUA (%)", 1),
    ]
    linhas = [[rotulo, *[num(v, 2) for v in (c[coluna] * escala).quantile([.25, .5, .75])]]
              for coluna, rotulo, escala in campos]
    tabela(fig, "Quartis da distribuição municipal", ["Indicador", "P25", "Mediana", "P75"],
           linhas, [.49, .17, .18, .16])
    notas(fig, "HHI é a soma dos quadrados das participações no FOB. Um HHI igual a 1 indica concentração em um único SH4 ou destino.\n"
          "O número efetivo é o inverso do HHI. O CV divide o desvio-padrão do FOB mensal pela média nos 36 meses.")
    return fig


def recuperacao(p):
    trimestre = p.loc[["trimestre_t2", "trimestre_t1", "trimestre_t0"]]
    fig = pagina("Quanto da queda foi recuperado?",
                 "Mesmos três meses em três anos consecutivos • Vendas de Minas Gerais aos EUA")
    ax = fig.add_axes([.095, .25, .37, .45])
    x = np.arange(len(trimestre))
    for coluna, rotulo, cor in [("eua", "Valor FOB", AZUL), ("kg_eua", "Peso líquido", COBRE)]:
        indice = 100 * trimestre[coluna] / trimestre[coluna].iloc[0]
        ax.plot(x, indice, marker="o", color=cor, label=rotulo, linewidth=2.5)
    ax.axhline(100, color=CINZA, linestyle=":", linewidth=1)
    ax.set_xticks(x, [janela(a, b) for a, b in zip(trimestre.inicio, trimestre.fim)], fontsize=9)
    ax.set_ylabel("Índice · primeiro trimestre comparado = 100")
    ax.set_ylim(bottom=0)
    ax.grid(axis="y", color=FILIGRANA)
    ax.legend(loc="lower left")
    titulo_eixo(ax, "Receita e quantidade física")
    linhas = [[janela(r.inicio, r.fim), num(r.eua / 1e6, 1), num(r.kg_eua / 1e6, 1)]
              for r in trimestre.itertuples()]
    tabela(fig, "Vendas aos EUA em trimestres equivalentes", ["Trimestre", "US$ milhões", "Milhões de kg"],
           linhas, [.44, .28, .28], pos=(.53, .52, .42, .185))
    linhas = [[janela(r.inicio, r.fim), num(r.eua / 1e9, 2), num(r.outros / 1e9, 2),
               num((r.eua + r.outros) / 1e9, 2)] for r in p.loc[["antes_12", "depois_12"]].itertuples()]
    tabela(fig, "Balanço das janelas anuais em US$ bilhões", ["Período", "EUA", "Demais", "Total"],
           linhas, [.46, .18, .18, .18], pos=(.53, .235, .42, .16))
    variacao = 100 * (trimestre.iloc[-1][["eua", "kg_eua"]] / trimestre.iloc[0][["eua", "kg_eua"]] - 1)
    notas(fig, f"Entre os trimestres encerrados em {data(trimestre.fim.iloc[0])} e {data(trimestre.fim.iloc[-1])}, "
          f"a receita variou {num(variacao.eua, 2, True)}% e o peso líquido, {num(variacao.kg_eua, 2, True)}%.\n"
          "Mudanças nos preços e na composição dos produtos podem produzir trajetórias diferentes para o valor e o peso.")
    return fig


def perdas(c):
    s=c.nsmallest(8,"delta_eua")
    fig=pagina("Onde ocorreram as maiores perdas em dólares?",ANUAL+" • Seleção pela queda absoluta do FOB aos EUA")
    y=np.arange(len(s))
    ax=fig.add_axes([.153,.23,.32,.48])
    ax.barh(y-.16,s.delta_eua/1e6,height=.28,color=AZUL,label="Variação EUA")
    ax.barh(y+.16,s.delta_total/1e6,height=.28,color=VERDE,label="Variação total mundial")
    ax.set_yticks(y,s.municipio); ax.invert_yaxis()
    ax.axvline(0,color=TINTA,lw=.8); ax.grid(axis="x",color=FILIGRANA)
    ax.set_xlabel("Mudança no FOB (US$ milhões)")
    ax.legend(loc="lower center",bbox_to_anchor=(.5,1),ncol=2,fontsize=9)
    titulo_eixo(ax,"")
    linhas=[[r.municipio,num(r.delta_eua/1e6,2,True),num(r.variacao_eua_pct,1,True),
             num(r.vulnerabilidade_pct,1),num(r.compensacao_mesmo_sh4_pct,1)] for r in s.itertuples()]
    tabela(fig,"Perdas, índice prévio e compensação",["Município","Δ EUA\nUS$ mi","Δ EUA\n%","Índice\n%","Comp.\n%"],
           linhas,[.36,.19,.15,.14,.16])
    ativos=c[c.eua_antes.gt(0)]
    notas(fig,f"Dos {len(ativos)} municípios com FOB positivo aos EUA na janela anterior, {ativos.delta_eua.lt(0).sum()} registraram queda e "
          f"{ativos.eua_depois.eq(0).sum()} passaram a zero.\nCompensação considera ganhos em outros mercados dentro do mesmo município e SH4.")
    return fig


def mapas(c):
    geo,_=obter_malha(MALHA)
    s=c.set_index("CO_MUN").reindex(geo)
    fig=pagina("Dependência prévia e resposta no território","Município do domicílio fiscal do exportador • Minas Gerais")
    g=s.delta_eua.where(s.eua_antes.gt(0)|s.eua_depois.gt(0))/1e6
    lim=max(1,g.abs().max())
    paineis=[(s.vulnerabilidade_pct,"Dependência em 2022–2024","viridis",Normalize(0,100),
              "Parcela do FOB municipal (%)",[0,25,50,75,100]),
             (g,"Variação anual do FOB aos EUA","RdBu",SymLogNorm(linthresh=1,vmin=-lim,vmax=lim),
              "US$ milhões · escala simétrica logarítmica", [v for v in [-100,-10,-1,0,1,10,100] if abs(v)<=lim])]
    for i,(serie,titulo,cmap,norm,unidade,ticks) in enumerate(paineis):
        ax=fig.add_axes([.065+.46*i,.23,.405,.50])
        col=PatchCollection(list(geo.values()),cmap=plt.get_cmap(cmap).with_extremes(bad="#dddfe0"),
                            norm=norm,edgecolors="white",linewidths=.20)
        col.set_array(np.ma.masked_invalid(serie.to_numpy(dtype=float)))
        ax.add_collection(col); ax.autoscale_view(); ax.set_aspect(1/np.cos(np.deg2rad(18.5)))
        ax.axis("off")
        ax.set_title(f"{titulo}  ·  n = {serie.notna().sum()}",fontsize=13,weight="bold",color=TINTA)
        cb=fig.colorbar(col,ax=ax,orientation="horizontal",fraction=.045,pad=.016,aspect=30,ticks=ticks)
        cb.ax.set_xticklabels([num(v,0) for v in ticks]); cb.set_label(unidade,fontsize=10)
    notas(fig,"Cinza à esquerda indica ausência de FOB positivo no triênio. À direita, indica ausência de vendas positivas aos EUA nas duas janelas.\n"
          f"{ANUAL}. Malha municipal simplificada do projeto Mapas de Minas Gerais.")
    return fig


def associacao(assoc,c):
    rel={"compensacao_mesmo_sh4_pct":"Diversificação × compensação",
         "variacao_eua_pct":"Dependência × variação EUA","variacao_total_pct":"Dependência × variação total"}
    fig=pagina("Diversificação, compensação e desempenho municipal",
               f"Indicadores estruturais de 2022–2024 • {ANUAL}")
    s=assoc.sort_values(["desfecho","min_meses"])
    y=np.arange(len(s))
    ax=fig.add_axes([.215,.235,.255,.48])
    for j,r in enumerate(s.itertuples()):
        cor=VERDE if r.desfecho=="compensacao_mesmo_sh4_pct" else AZUL
        ax.plot([r.ic025,r.ic975],[j,j],lw=2,color=cor)
        ax.scatter(r.rho,j,s=35,color=cor)
    ax.set_yticks(y,[f"{rel[k]} · {v} m" for k,v in zip(s.desfecho,s.min_meses)],fontsize=9)
    ax.invert_yaxis(); ax.grid(axis="x",color=FILIGRANA); ax.axvline(0,color=CINZA,ls=":")
    ax.set_xlabel("Correlação de Spearman")
    titulo_eixo(ax,"Correlação e intervalo de 95%")
    linhas=[[rel[r.desfecho],str(r.min_meses),str(r.n),num(r.rho,2),num(r.rho_parcial_porte,2)] for r in s.itertuples()]
    tabela(fig,"Sensibilidade ao mínimo de meses ativos",["Relação","Meses","n","ρ bruto","ρ parcial¹"],
           linhas,[.50,.12,.09,.14,.15],fonte=9.4)
    perda=c.perda_eua_sh4.sum(); comp=c.compensado_sh4.sum()
    notas(fig,f"Compensação estadual no mesmo município e SH4: US$ {num(comp/1e6,1)} mi de US$ {num(perda/1e6,1)} mi em perdas brutas ({num(100*comp/perda)}%).\n"
          "¹ Correlação entre postos ajustada pelo FOB municipal prévio. Intervalos do coeficiente bruto por bootstrap de municípios. Associação exploratória.")
    return fig


def produto_mercado(prod,mun,por_dependencia):
    base=prod[prod.janela.eq("estrutura")].set_index("SH4")
    origem=mun[mun.janela.eq("estrutura")]
    if por_dependencia:
        s=base[base.total.ge(1e6)].nlargest(6,"fracao_eua")
        fig=pagina("Produtos mais dependentes das vendas aos EUA",
                   "Minas Gerais • 2022–2024 • Seis maiores participações entre os SH4 com FOB mundial de pelo menos US$ 1 milhão")
        ax=barras(fig,[produto(c) for c in s.index],100*s.fracao_eua,"Parcela destinada aos EUA",
                  "FOB aos EUA / FOB mundial (%)",cor=AZUL,pos=(.181,.235,.295,.48))
        ax.set_xlim(0,100)
        linhas=[]
        for c,r in s.iterrows():
            lider=origem[origem.SH4.eq(c)].nlargest(1,"eua").iloc[0]
            linhas.append([c,num(r.eua/1e6,2),num(r.razao_eua_outros,2),lider.municipio,
                           num(100*lider.fracao_municipal_no_sh4_eua)])
        tabela(fig,"Município líder no fluxo aos EUA",["SH4","FOB EUA\nUS$ mi","EUA /\ndemais","Município","Parcela¹\n%"],
               linhas,[.10,.18,.17,.37,.18])
        notas(fig,f"No triênio, {base.exclusivo_eua.sum()} SH4 tiveram vendas exclusivamente aos EUA, contando todos os volumes. O traço indica denominador zero.\n"
              "¹ Participação do município no FOB mineiro desse SH4 vendido aos EUA. A razão EUA/demais expressa dólares por dólar.")
    else:
        codigos=base.nlargest(3,"eua").index.union(base.nlargest(3,"outros").index,sort=False)
        s=base.loc[codigos]
        fig=pagina("Produtos de maior peso na receita exportadora",
                   "Minas Gerais • 2022–2024 • Três maiores posições SH4 por valor em cada mercado, reunidas sem duplicação")
        ax=fig.add_axes([.176,.24,.31,.47])
        y=np.arange(len(s))
        ax.barh(y-.16,s.eua/1e9,height=.28,color=AZUL,label="EUA")
        ax.barh(y+.16,s.outros/1e9,height=.28,color=VERDE,label="Demais destinos")
        ax.set_yticks(y,[produto(c) for c in s.index]); ax.invert_yaxis()
        ax.set_xlabel("FOB acumulado (US$ bilhões)"); ax.grid(axis="x",color=FILIGRANA)
        ax.legend(loc="lower center",bbox_to_anchor=(.5,1),ncol=2,fontsize=9)
        titulo_eixo(ax,"")
        linhas=[]
        for c,r in s.iterrows():
            t=origem[origem.SH4.eq(c)]
            linhas.append([c,num(r.eua/1e9,2),num(r.outros/1e9,2),num(100*r.fracao_eua,2),
                           t.nlargest(1,"eua").municipio.iloc[0],t.nlargest(1,"outros").municipio.iloc[0]])
        tabela(fig,"Receita e principal município por mercado",
               ["SH4","EUA\nUS$ bi","Demais\nUS$ bi","EUA\n%¹","Líder EUA","Líder demais"],
               linhas,[.08,.10,.11,.10,.24,.37],pos=(.505,.25,.45,.45),fonte=9)
        notas(fig,"¹ Participação dos EUA nas exportações mineiras do respectivo SH4. Os líderes municipais são definidos pelo FOB no mercado indicado.\n"
              "Um produto pode ter grande peso na receita estadual e uma parcela pequena destinada aos EUA.")
    return fig


def perdas_produto(pares,nomes,prod,p):
    maiores=pares.groupby("SH4").delta_eua.sum().nsmallest(5)
    fig=pagina("Quais produtos e municípios explicam as perdas aos EUA?",ANUAL+" • Cinco maiores quedas estaduais em dólares")
    barras(fig,[produto(c) for c in maiores.index],maiores/1e6,"Variação estadual por SH4","Mudança no FOB aos EUA (US$ milhões)",
           pos=(.185,.235,.295,.48))
    recente=prod.pivot(index="SH4",columns="janela",values="eua")
    linhas=[]
    for c in maiores.index:
        t=pares[pares.SH4.eq(c)].nsmallest(1,"delta_eua").iloc[0]
        linhas.append([c,nomes.loc[t.CO_MUN],num(t.delta_eua/1e6,1,True),
                       num(recente.loc[c,"trimestre_t1"]/1e6,1),num(recente.loc[c,"trimestre_t0"]/1e6,1)])
    tabela(fig,"Maior perda municipal e acompanhamento estadual",["SH4","Município","Δ local\nUS$ mi",
           "Tri. anterior¹\nUS$ mi","Tri. recente¹\nUS$ mi"],linhas,[.10,.30,.18,.21,.21],fonte=9.5)
    t1,t0=p.loc["trimestre_t1"],p.loc["trimestre_t0"]
    notas(fig,"O município indicado teve a maior queda absoluta aos EUA naquele SH4. Os valores trimestrais abrangem todo o estado.\n"
          f"¹ Trimestre anterior: {janela(t1.inicio,t1.fim)}. Trimestre recente: {janela(t0.inicio,t0.fim)}.")
    return fig


def previsao(h,f):
    fig=pagina("Previsões de curto prazo por mercado",
               f"Histórico até {data(h.mes.iloc[-1])} • Horizonte de três meses • FOB em US$ milhões")
    for i,(m,cor) in enumerate([("eua",AZUL),("outros",VERDE)]):
        ax=fig.add_axes([.09,.485-i*.27,.405,.17])
        passado=h.tail(12)
        ax.plot(pd.to_datetime(passado.mes),passado[m]/1e6,color=cor,lw=2)
        grupo=f[f.mercado.eq(m)]
        datas=pd.to_datetime(grupo.mes)
        ax.fill_between(datas,grupo.p10_usd/1e6,grupo.p90_usd/1e6,color="#e7cdaa")
        ax.plot(datas,grupo.fob_usd/1e6,"o--",ms=4,color=COBRE)
        ax.axvline(datas.iloc[0],color=CINZA,ls=":",lw=.8)
        ax.grid(axis="y",color=FILIGRANA)
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%y"))
        titulo_eixo(ax,MERCADOS[m]+"  ·  observado e projetado")
    linhas=[]
    for r in f.sort_values(["mes","mercado"]).itertuples():
        linhas.append([data(r.mes),MERCADOS[r.mercado],num(r.fob_usd/1e6,0),
                       num(r.p10_usd/1e6,0),num(r.p90_usd/1e6,0)])
    tabela(fig,"Previsão pontual e faixa empírica (US$ mi)",["Mês","Mercado","Previsão","P10","P90"],
           linhas,[.19,.30,.19,.16,.16],fonte=10)
    notas(fig,f"Linha contínua: dados observados. Linha tracejada: previsão. A faixa sombreada usa os percentis 10 e 90 dos erros relativos "
          f"em {int(f.n_erros.min())} origens por horizonte.\nA previsão total soma os mercados. Sua faixa incorpora a variação conjunta dos erros.")
    return fig


def modelos(t,f):
    sel=t[t.etapa.eq("selecao")].set_index(["mercado","modelo"])
    s=t[t.etapa.eq("teste")].sort_values(["mercado","mae_usd"])
    escolhidos=f.drop_duplicates("mercado").set_index("mercado").modelo
    fig=pagina("Quanto erraram os modelos de previsão?",
               f"Seleção em {int(sel.origens.iloc[0])} origens mensais até 2024 • Teste em {int(s.origens.iloc[0])} origens posteriores • Horizontes de um a três meses")
    for i,m in enumerate(["eua","outros"]):
        g=s[s.mercado.eq(m)]
        ax=barras(fig,[MODELOS[k] for k in g.modelo],g.mae_usd/1e6,MERCADOS[m],
                  "Erro absoluto médio (US$ milhões)" if i else "",
                  cor=[VERDE if k==escolhidos[m] else "#a7b9c5" for k in g.modelo],
                  pos=(.183,.49-i*.26,.302,.15))
        ax.set_xlim(0,s.mae_usd.max()/1e6*1.05)
    linhas=[[MERCADOS[r.mercado],MODELOS[r.modelo],num(sel.loc[(r.mercado,r.modelo),"mae_usd"]/1e6),
             num(r.mae_usd/1e6),num(r.wape_pct,2)] for r in s.itertuples()]
    tabela(fig,"Erro em seleção e teste",["Mercado","Método","Seleção\nUS$ mi","Teste\nUS$ mi","WAPE\nteste (%)"],
           linhas,[.21,.35,.14,.14,.16],pos=(.51,.225,.445,.51),fonte=9.4)
    notas(fig,"Em verde, o método escolhido pelo menor erro absoluto médio antes do teste. A referência sazonal repete o valor de um ano antes.\n"
          "WAPE = soma dos erros absolutos / soma dos valores observados, em %. As origens de previsão usam apenas o histórico disponível em cada data.")
    return fig


def gerar_visuais(pasta=PASTA):
    def ler(nome):
        return pd.read_csv(pasta/(nome+".csv"),sep=";",dtype={"CO_MUN":str,"SH4":str,"sh4_principal_eua":str})

    mensal=ler("historico_mensal")
    cidades=ler("municipios_vulnerabilidade_resposta").query("comparacao == 'anual'")
    periodos=ler("periodos_estaduais").set_index("janela")
    prod=ler("produtos_por_mercado")
    municipios_prod=ler("produtos_municipios")
    futuro=ler("previsoes")
    destino=pasta/"visuais"
    destino.mkdir(exist_ok=True)
    paginas=[
        ("01_historico",historico,(mensal,ler("sazonalidade_2015_2024"))),
        ("01b_estrutura_municipal",estrutura,(cidades,)),
        ("02_fases",fases,(ler("fases_interanuais"),periodos)),
        ("02b_recuperacao",recuperacao,(periodos,)),
        ("03_dependencia",dependencia,(cidades,)),
        ("04_perdas_municipais",perdas,(cidades,)),
        ("05_mapas",mapas,(cidades,)),
        ("06_compensacao_associacoes",associacao,(ler("associacoes_municipais"),cidades)),
        ("07_produtos_mercados",produto_mercado,(prod,municipios_prod,False)),
        ("08_produtos_dependencia",produto_mercado,(prod,municipios_prod,True)),
        ("09_produtos_perdas",perdas_produto,(ler("compensacao_municipio_sh4_anual"),
             cidades.set_index("CO_MUN").municipio,prod,periodos)),
        ("10_validacao",modelos,(ler("validacao_previsoes"),futuro)),
        ("11_previsoes",previsao,(mensal,futuro)),
    ]
    arquivo=destino/"panorama_visual.pdf"
    estilo={"font.family":"DejaVu Sans","axes.labelcolor":TINTA,"text.color":TINTA,
            "pdf.fonttype":42,"figure.facecolor":"white","savefig.facecolor":"white"}
    with plt.rc_context(estilo), PdfPages(arquivo,metadata={"Title":"Exportações municipais de Minas Gerais",
                                                          "Subject":"Panorama comercial · IFMG Campus Sabará"}) as pdf:
        for i,(nome,funcao,args) in enumerate(paginas,1):
            fig=funcao(*args)
            fig.text(.055,.036,"Fonte: Comex Stat / MDIC  ·  Exportações municipais de Minas Gerais  ·  IFMG Campus Sabará",
                     size=8.8,color=CINZA)
            fig.text(.95,.036,f"{i} / {len(paginas)}",ha="right",size=9,color=CINZA)
            fig.savefig(destino/(nome+".png"),dpi=160)
            pdf.savefig(fig)
            plt.close(fig)
    return arquivo


if __name__=="__main__":
    print(gerar_visuais())

"""Reconciliação final e relatório reproduzível da Seção 4."""
import argparse
import hashlib
import json
import zipfile
from pathlib import Path
from tempfile import NamedTemporaryFile

import numpy as np
import pandas as pd
import requests

from analise_cientifica import BASE, MALHA, obter_malha
from analise_comex import API_MUNICIPAL, COLUNAS, consultar_api, lote_atual, registros_api, requisitar, sha256
from exposicao_tarifaria import composicoes
from panorama_comercial import ler_base
from regimes_comerciais import JANELAS, RAIZ, SAIDA, SECAO, salvar


def ler(path):
    return pd.read_csv(path,sep=";",dtype={"CO_MUN":str,"SH4":str,"CO_PAIS":str})


def iguais(a,b,mensagem):
    if not np.allclose(a,b,rtol=1e-12,atol=1e-8,equal_nan=True):
        raise ValueError(mensagem)


def validar_catalogo(d, baixar):
    arq = RAIZ/"dados/brutos/PAIS.csv"
    api = arq.with_name("PAIS_api.csv")
    if not arq.exists() and api.exists():
        arq = api
    if baixar and not arq.exists():
        arq.parent.mkdir(parents=True,exist_ok=True)
        with NamedTemporaryFile(dir=arq.parent, delete=False) as f:
            tmp = Path(f.name)
        try:
            try:
                with requisitar("GET","https://balanca.mdic.gov.br/balanca/bd/tabelas/PAIS.csv") as r:
                    r.raise_for_status()
                    tmp.write_bytes(r.content)
            except requests.RequestException as erro:
                print("CSV de países indisponível. Consultando o catálogo da API municipal.",erro)
                url = API_MUNICIPAL + "/filters/country"
                itens = consultar_api("GET",url,params={"language":"pt"})
                tabela = pd.DataFrame([(str(l["id"]),l["text"]) for l in registros_api(itens,url,{"id","text"})],
                                      columns=["CO_PAIS","NO_PAIS"])
                tabela.to_csv(tmp,sep=";",index=False,encoding="latin1")
                arq = api
            cod = pd.read_csv(tmp,sep=";",encoding="latin1",usecols=["CO_PAIS","NO_PAIS"],dtype=str)
            if (cod.empty or cod.isna().any().any() or not cod.CO_PAIS.str.fullmatch(r"\d{1,3}").all()
                    or cod.CO_PAIS.str.zfill(3).duplicated().any()):
                raise ValueError("Catálogo de países inválido.")
            arq.hardlink_to(tmp)
        except requests.RequestException as erro:
            print("Catálogo de países indisponível:", erro)
        finally:
            tmp.unlink(missing_ok=True)
    codigos = sorted(d.CO_PAIS.unique())
    tabela = pd.DataFrame({"CO_PAIS":codigos})
    if arq.exists():
        cat = pd.read_csv(arq,sep=";",encoding="latin1",dtype=str)
        cat["CO_PAIS"] = cat.CO_PAIS.str.zfill(3)
        tabela = tabela.merge(cat[["CO_PAIS","NO_PAIS"]],on="CO_PAIS",how="left",validate="one_to_one")
        tabela["status"] = np.where(tabela.NO_PAIS.isna(),"sem_correspondencia","identificado")
    else:
        tabela["status"] = "sem_catalogo_local"
    salvar(tabela,"validacao_paises",SECAO)
    return tabela.status.value_counts().to_dict()


def validar_pesos_ncm(medidas):
    """Reconstitui os pesos publicados a partir do FOB de origem e das classificações."""
    origem = composicoes(False)
    pesos = ler(SECAO/"exposicao_sh4_por_medida.csv")
    areas = {"MG", "BR"} if origem is not None else {"limites_SH4"}
    cenarios = {(medida, area) for medida in medidas for area in areas}
    if set(zip(pesos.medida, pesos.composicao)) != cenarios:
        raise ValueError("Cenários de exposição incompatíveis com o calendário ou os lotes NCM.")
    if origem is None:
        return
    detalhe = pd.read_csv(SECAO/"correspondencia_htsus_ncm.csv", sep=";",
                          dtype={"CO_NCM": str, "SH4": str, "SH6": str})
    chaves = ["CO_NCM", "edicao", "composicao"]
    fonte = origem.set_index(chaves).fob_ncm.sort_index()
    if (not detalhe.SH4.eq(detalhe.CO_NCM.str[:4]).all()
            or not detalhe.SH6.eq(detalhe.CO_NCM.str[:6]).all()
            or set(detalhe.medida) != set(medidas)):
        raise ValueError("Correspondência NCM com edição, medida ou código SH incompatível.")
    for medida, linhas in detalhe.groupby("medida"):
        pd.testing.assert_series_equal(linhas.set_index(chaves).fob_ncm.sort_index(), fonte,
                                       check_dtype=False)
        if not (linhas["min"].between(0, 1) & linhas["max"].between(linhas["min"], 1)).all():
            raise ValueError(f"Limites NCM inválidos em {medida}.")
        linhas = linhas.assign(inferior=linhas.fob_ncm*linhas["min"],
                               superior=linhas.fob_ncm*linhas["max"])
        grupos = ["composicao", "SH4"]
        soma = linhas.groupby(grupos)[["fob_ncm","inferior","superior"]].sum()
        publicado = pesos[pesos.medida.eq(medida)].set_index(grupos)
        if not publicado.index.is_unique:
            raise ValueError(f"Peso SH4 duplicado em {medida}.")
        soma = soma.reindex(publicado.index)
        iguais(publicado.fob_composicao, soma.fob_ncm, f"FOB de composição divergente em {medida}.")
        cobertos = soma.fob_ncm.gt(0)
        for limite, coluna in [("peso_min","inferior"), ("peso_max","superior")]:
            esperado = soma.loc[cobertos,coluna] / soma.loc[cobertos,"fob_ncm"]
            iguais(publicado.loc[cobertos,limite], esperado, f"Peso comercial divergente em {medida}.")


def validar_perfis(perfis):
    from analise_perfis import METRICAS, REPETICOES, SEMENTE, ajustar
    t = perfis[perfis.meses_ativos.ge(12)].sort_values("CO_MUN")
    matriz = t[METRICAS].to_numpy()
    def z(m):
        return (m-m.mean(axis=0))/m.std(axis=0)
    def rand_ajustado(a,b):
        contingencia = pd.crosstab(a,b).to_numpy()
        def pares(n):
            return np.sum(n*(n-1)//2)
        lin, col = pares(contingencia.sum(axis=1)), pares(contingencia.sum(axis=0))
        esperado = lin*col/(len(a)*(len(a)-1)/2)
        return (pares(contingencia)-esperado)/((lin+col)/2-esperado)
    x = z(matriz)
    modelos = ajustar(x,SEMENTE)
    rng = np.random.default_rng(SEMENTE)
    chaves = [(metodo,k) for metodo in ["K-Means","Ward"] for k in [4,5]]
    estabilidade = {chave:[] for chave in chaves}
    for rodada in range(1,REPETICOES+1):
        idx = np.sort(rng.choice(len(x),int(.8*len(x)),replace=False))
        sub = ajustar(z(matriz[idx]),SEMENTE+rodada)
        for chave in chaves:
            estabilidade[chave].append(rand_ajustado(modelos[chave][idx],sub[chave]))
    referencia = ler(RAIZ/"resultados/perfis_municipais/comparacao_principal.csv").set_index(["metodo","k"])
    dist = np.linalg.norm(x[:,None]-x,axis=2)
    linhas = []
    try:
        from sklearn.cluster import AgglomerativeClustering, KMeans
    except ImportError:
        AgglomerativeClustering = KMeans = None
    for metodo,k in chaves:
        g = modelos[metodo,k]
        centros = np.array([x[g==i].mean(axis=0) for i in range(k)])
        if metodo=="K-Means":
            perto = np.linalg.norm(x[:,None]-centros,axis=2).argmin(axis=1)
            iguais(g,perto,"Partição K-Means fora do ponto fixo.")
        sil = []
        for i,grupo in enumerate(g):
            vizinhos = g==grupo
            vizinhos[i] = False
            a = dist[i,vizinhos].mean() if vizinhos.any() else 0
            b = min(dist[i,g==j].mean() for j in range(k) if j!=grupo)
            sil.append((b-a)/max(a,b) if vizinhos.any() and max(a,b)>0 else 0)
        raio = [np.linalg.norm(x[g==j]-centros[j],axis=1).mean() for j in range(k)]
        db = np.mean([max((raio[i]+raio[j])/np.linalg.norm(centros[i]-centros[j])
                          for j in range(k) if j!=i) for i in range(k)])
        resumo = [np.mean(sil),db,np.median(estabilidade[metodo,k]),np.bincount(g).min()]
        iguais(resumo,referencia.loc[(metodo,k),["silhouette","davies_bouldin","ari_mediana","menor_grupo"]].astype(float),
               "Divergência na validação independente de perfis.")
        externo = np.nan
        if KMeans is not None:
            if metodo=="K-Means":
                ajuste = KMeans(n_clusters=k,n_init=8,random_state=SEMENTE)
            else:
                ajuste = AgglomerativeClustering(n_clusters=k,linkage="ward")
            externo = rand_ajustado(g,ajuste.fit_predict(x))
        if metodo=="K-Means" and k==5:
            iguais(rand_ajustado(g,t.perfil),1,"Partição publicada diverge do ajuste.")
        linhas.append((metodo,k,*resumo,externo))
    salvar(pd.DataFrame(linhas,columns=["metodo","k","silhouette","davies_bouldin","ari_mediana",
                                        "menor_grupo","ari_sklearn_opcional"]),"validacao_independente",
           RAIZ/"resultados/perfis_municipais")


def relatar(auditoria):
    def numero(x, casas=2):
        return f"{x:,.{casas}f}".replace(",","_").replace(".",",").replace("_",".")
    quadros = [
        "# Seção 4 · Relatório da execução",
        f"A base reúne {numero(auditoria['registros'],0)} registros em {auditoria['meses']} meses, "
        f"de {auditoria['inicio']} a {auditoria['fim']}. A unidade geográfica é o domicílio fiscal do exportador.",
        "## 4.1 · Estrutura anterior às medidas",
        f"De 2022 a 2024, {auditoria['municipios_pre']} municípios exportaram US$ {numero(auditoria['fob_pre_usd'],0)}. "
        f"O corte de 12 meses positivos inclui {auditoria['municipios_perfis']} municípios.",
        "## 4.2 · Perfis estruturais"]
    grupos = ler(RAIZ/"resultados/perfis_municipais/caracterizacao.csv")
    cab = "| Perfil | Municípios | HHI produtos | HHI destinos | EUA (%) | CV |\n|---|---:|---:|---:|---:|---:|"
    quadros.append(cab+"\n"+"\n".join(f"| {r.perfil} | {r.municipios} | {numero(r.hhi_produtos)} | {numero(r.hhi_destinos)} | "
                                     f"{numero(100*r.participacao_eua)} | {numero(r.cv_mensal)} |" for r in grupos.itertuples()))
    modelos = ler(RAIZ/"resultados/perfis_municipais/validacao_independente.csv")
    for r in modelos[modelos.metodo.eq("K-Means")].itertuples():
        quadros.append(f"K-Means com {r.k} grupos obteve silhouette {numero(r.silhouette,3)}, "
                       f"Davies–Bouldin {numero(r.davies_bouldin,3)} e ARI mediano {numero(r.ari_mediana,3)}.")
    quadros.append("## 4.3 · Desempenho posterior")
    comparacoes = ler(SAIDA/"comparacao_periodos.csv")
    perdas = ler(SAIDA/"compensacao_municipio_sh4.csv")
    cab = "| Janela | FOB EUA (%) | Peso EUA (%) | FOB outros (%) | FOB total (%) | Perda compensada no mesmo SH4 (%) |\n|---|---:|---:|---:|---:|---:|"
    linhas = []
    for janela,d in comparacoes.groupby("comparacao"):
        t = perdas[perdas.comparacao.eq(janela)]
        medidas = d.set_index("medida").variacao_pct
        razao = 100*t.compensado_sh4.sum()/t.perda_eua_sh4.sum() if t.perda_eua_sh4.sum()>0 else np.nan
        linhas.append(f"| {janela} | "+" | ".join(numero(v) for v in [*medidas[["eua","kg_eua","outros","total"]],razao])+" |")
    quadros.append(cab+"\n"+"\n".join(linhas))
    r = auditoria["recuperacao"]
    quadros.append(f"Após a queda de setembro ou outubro de 2025 frente à média do mesmo mês em 2022–2024, "
                   f"{r.get('recuperado',0)} municípios alcançaram a referência por dois meses seguidos. "
                   f"Outros {r.get('censurado',0)} ficaram censurados até {auditoria['fim']}.")
    quadros.append("## 4.4 · Vulnerabilidade prévia e resposta observada")
    perfis = ler(SECAO/"resposta_por_perfil.csv").query("comparacao == 'anual'")
    quadros.append(f"Na janela anual, {perfis.n_municipios_com_compensacao_positiva.sum()} dos "
                   f"{perfis.n_compensacao_valida.sum()} municípios com perfil e perda bruta em algum SH4 "
                   "registraram compensação positiva. O denominador é a população em que o indicador está definido.")
    diag = ler(SECAO/"diagnosticos_modelos.csv")
    testes = diag.query("modelo == 'perfis' and familia == 'linear' and min_meses == 12")
    cab = "| Janela | Desfecho | n | Valor-p conjunto dos perfis |\n|---|---|---:|---:|"
    quadros.append(cab+"\n"+"\n".join(f"| {r.comparacao} | {r.desfecho} | {r.n} | {numero(r.p_conjunto_perfis,4)} |"
                                     for r in testes.itertuples()))
    reg = ler(SECAO/"regressoes_hc3.csv")
    for r in reg.query("comparacao == 'anual' and termo == 'log2_destinos_efetivos'").itertuples():
        quadros.append(f"No corte de atividade de {r.min_meses} mês(es), duplicar o número efetivo de destinos associou-se "
                       f"a {numero(r.coef)} p.p. de compensação (IC 95% {numero(r.ic025)} a {numero(r.ic975)}, n = {r.n}).")
    quadros.append("## Exposição e limites de interpretação")
    cobertura = ler(SECAO/"cobertura_classificacao_tarifaria.csv")
    linhas = ["| Composição | Pauta mundial (%) | Vendas aos EUA (%) |",
              "|---|---:|---:|"]
    for r in cobertura[cobertura.medida.eq("brasil_inicial")].itertuples():
        intervalos = [f"{numero(100*r.usd_min/den)} a {numero(100*r.usd_max/den)}"
                      if den > 0 else "indefinido" for den in (r.total, r.eua)]
        linhas.append(f"| {r.composicao} | {intervalos[0]} | {intervalos[1]} |")
    quadros.append("Parcela do FOB municipal de 2022–2024 potencialmente abrangida pelo adicional "
                   "inicial de 40% dos EUA sobre o Brasil. Os intervalos agregam os valores dos municípios mineiros.")
    quadros.append("\n".join(linhas))
    quadros.extend(["Os limites refletem a incerteza de classificação por mercadoria e operação. "
        "As composições MG e BR, quando disponíveis, aproximam a distribuição municipal das NCMs "
        "dentro de cada SH4. A base municipal observa o domicílio fiscal em Minas Gerais.",
        "Os testes dos perfis avaliam associação condicional ao porte exportador e às parcelas de café e minério. "
        "Os valores-p são nominais, exploratórios e sensíveis à janela. Preços, demanda, câmbio e sazonalidade "
        "também influem sobre as trajetórias municipais.",
        "## Reprodução e auditoria",
        "Execute python executar_analise.py --desde-lotes na raiz do projeto. O arquivo manifesto_fontes.csv contém os hashes "
        "dos insumos. auditoria.json registra a cobertura e a comparação com a base arquivada quando disponível. "
        "A documentação metodológica e os testes estão na raiz do repositório."])
    (SECAO/"relatorio_execucao.md").write_text("\n\n".join(quadros)+"\n",encoding="utf-8")


def executar(baixar=False):
    d = ler_base()
    _, nomes = obter_malha(MALHA)
    if (not d.CO_MUN.isin(nomes.index).all() or not d.SH4.str.fullmatch(r"\d{4}").all()
            or not d.CO_PAIS.str.fullmatch(r"\d{3}").all() or not d.DATA.dt.day.eq(1).all()):
        raise ValueError("Código geográfico, comercial ou data inválida.")
    paises = validar_catalogo(d,baixar)
    fontes = [BASE,MALHA,RAIZ/"docs/calendario_tarifario.csv",RAIZ/"docs/excecoes_2026.csv",
              RAIZ/"dados/tarifas/excecoes_brasil_2025.csv",*sorted((RAIZ/"dados/brutos/ncm").glob("*.csv"))]
    pais = RAIZ/"dados/brutos/PAIS.csv"
    for arq in (pais,pais.with_name("PAIS_api.csv")):
        if arq.exists():
            fontes.append(arq)
    reconciliados = []
    for ano, grupo in d.groupby("CO_ANO"):
        lote = RAIZ/f"dados/brutos/api_mg/EXP_MG_{ano}_01-{grupo.CO_MES.max():02}.csv"
        if lote.exists():
            lote = lote_atual(lote)
            bruto = ler(lote)
            chaves = COLUNAS[:6]
            a = bruto[COLUNAS].sort_values(chaves).reset_index(drop=True)
            b = grupo[COLUNAS].sort_values(chaves).reset_index(drop=True)
            pd.testing.assert_frame_equal(a,b,check_dtype=False)
            fontes.append(lote)
            reconciliados.append(int(ano))
    pre = ler(RAIZ/"resultados/pre_choque/indicadores_municipais.csv")
    perfis = ler(RAIZ/"resultados/perfis_municipais/municipios.csv")
    validar_perfis(perfis)
    mensal = ler(SAIDA/"serie_mensal_regimes.csv")
    iguais(mensal.total,d.groupby("mes").VL_FOB.sum(),"FOB estadual mensal divergente.")
    iguais(mensal.kg_total,d.groupby("mes").KG_LIQUIDO.sum(),"Peso estadual mensal divergente.")
    tri = d[d.CO_ANO.between(2022,2024)]
    iguais(tri.VL_FOB.sum(),pre.fob_pre_usd.sum(),"FOB estrutural divergente.")
    calendario = ler(SECAO/"calendario_medidas_tarifarias.csv")
    validar_pesos_ncm(calendario.loc[calendario.aliquota.notna(),"medida"])
    e = ler(SECAO/"exposicao_municipal_por_medida.csv")
    for _, g in e.groupby(["medida","composicao"]):
        iguais(g.total.sum(),tri.VL_FOB.sum(),"Denominador mundial divergente.")
        iguais(g.eua.sum(),tri.loc[tri.mercado.eq("eua"),"VL_FOB"].sum(),"Denominador EUA divergente.")
        if g.usd_min.gt(g.usd_max).any() or g.usd_max.gt(g.eua+1e-5).any():
            raise ValueError("FOB potencial incompatível com as vendas aos EUA.")
    r = ler(SAIDA/"resposta_municipal.csv")
    pares = ler(SAIDA/"compensacao_municipio_sh4.csv")
    por_perfil = ler(SECAO/"resposta_por_perfil.csv")
    for janela in JANELAS:
        p = pares[pares.comparacao.eq(janela)]
        if p.duplicated(["CO_MUN","SH4"]).any():
            raise ValueError("Pares município-SH4 duplicados.")
        soma = p.groupby("CO_MUN")[["compensado_sh4","perda_eua_sh4","ganho_outros_sh4"]].sum()
        m = r[r.comparacao.eq(janela)].set_index("CO_MUN")
        iguais(soma,m.loc[soma.index,soma.columns],"Soma da compensação diverge por município.")
        if janela in set(por_perfil.comparacao):
            g = m.join(perfis.set_index("CO_MUN").perfil).dropna(subset="perfil")
            q = por_perfil[por_perfil.comparacao.eq(janela)].set_index("perfil")
            positivos = g.compensado_sh4.gt(0).groupby(g.perfil).sum()
            iguais(positivos,q.loc[positivos.index,"n_municipios_com_compensacao_positiva"],"Contagem de compensação incorreta.")
    arquivos = [dict(arquivo=str(f.relative_to(RAIZ)),sha256=sha256(f),bytes=f.stat().st_size) for f in fontes]
    salvar(pd.DataFrame(arquivos),"manifesto_fontes",SECAO)
    zip_local = RAIZ/"analise_artigo.zip"
    auditoria = dict(registros=len(d),municipios=d.CO_MUN.nunique(),meses=d.mes.nunique(),
                     inicio=str(d.mes.min()),fim=str(d.mes.max()),anos_reconciliados=reconciliados,
                     paises=paises,fob_pre_usd=int(tri.VL_FOB.sum()),municipios_pre=len(pre),
                     municipios_perfis=int(perfis.perfil.notna().sum()),composicao=e.composicao.unique().tolist(),
                     versoes_tarifarias=int(calendario.aliquota.notna().sum()),
                     recuperacao=ler(SAIDA/"recuperacao_municipal.csv").status.value_counts().to_dict())
    pendencias = []
    if "limites_SH4" in auditoria["composicao"]:
        pendencias.append("Composição NCM 2022–2024 de MG e Brasil indisponível.")
    if set(paises) != {"identificado"}:
        pendencias.append("Correspondência com o catálogo oficial de países incompleta.")
    auditoria["pendencias_fontes"] = pendencias
    if zip_local.exists():
        with zipfile.ZipFile(zip_local) as z:
            anterior = hashlib.sha256(z.read(str(BASE.relative_to(RAIZ)))).hexdigest()
        auditoria["sha256_base_zip"] = anterior
        auditoria["mesma_base_arquivada"] = anterior==sha256(BASE)
    (SECAO/"auditoria.json").write_text(json.dumps(auditoria,ensure_ascii=False,indent=2)+"\n")
    relatar(auditoria)
    print(json.dumps(auditoria,ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baixar-catalogo",action="store_true")
    executar(parser.parse_args().baixar_catalogo)

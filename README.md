# Vulnerabilidade e resiliência comercial dos municípios mineiros

Pesquisa do IFMG, Campus Sabará. O estudo relaciona a estrutura exportadora de 2022–2024 à resposta posterior dos municípios nas exportações aos EUA e a outros destinos. Cada observação original agrega FOB e peso líquido por mês, município fiscal do exportador, SH4 e país. A extração de referência cobre janeiro de 2015 a outubro de 2026.

## Executar

Na raiz do repositório, prepare o ambiente. A referência usa Python 3.14.10. O Poppler fornece o comando pdftotext para a reconstrução da lista tarifária de 2025 a partir do PDF oficial.

~~~bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python executar_analise.py
~~~

A execução online consulta um lote municipal por ano, atualiza o último ano até o mês encerrado publicado, prepara os anexos e tenta obter os três CSVs nacionais por NCM. O catálogo de países e os arquivos por NCM vêm do MDIC. Para redes que utilizam uma autoridade certificadora institucional, Requests aceita um PEM confiável em REQUESTS_CA_BUNDLE. [Comex Stat — dados abertos e leiautes](https://www.gov.br/mdic/pt-br/assuntos/comercio-exterior/estatisticas/base-de-dados-bruta) · [Documentação da API](https://api-comexstat.mdic.gov.br/docs)

| Execução local | Insumos |
|---|---|
| `python executar_analise.py --desde-lotes` | Lotes desde 2015 em dados/brutos/api_mg/, malha em dados/malhas/mg_municipios.geojson e lista em dados/tarifas/excecoes_brasil_2025.csv. Reconstrói a base tratada e executa as análises. |
| `python executar_analise.py --usar-base-local` | Mesma malha e lista, mais dados/tratados/exportacoes_mg_atual.csv. Reutiliza esse consolidado. |

Nos dois modos offline, cada ano de 2022 a 2024 pode vir do CSV nacional `EXP_AAAA.csv` ou do lote validado `API_EXP_EUA_AAAA.csv`, em `dados/brutos/ncm/`. Com o triênio completo, o relatório apresenta os cenários MG e BR e os intervalos sobre a pauta mundial e sobre as vendas aos EUA. Se faltar um ano, a exposição recebe a identificação `limites_SH4`. O catálogo de países fica em `dados/brutos/PAIS.csv` ou `dados/brutos/PAIS_api.csv`. Os procedimentos de classificação, denominadores, datas e incertezas estão documentados. [Metodologia tarifária](docs/metodologia_tarifaria.md) · [Cronologia](docs/cronologia_tarifaria.md)

## Localizar os resultados

| Subseção | Scripts principais | Produtos locais |
|---|---|---|
| 4.1 · Estrutura municipal | analise_comex.py e analise_cientifica.py | A base detalhada fica em dados/tratados/exportacoes_mg_atual.csv. Indicadores, sete cortes de inclusão e mapa ficam em resultados/pre_choque/. Os gráficos gerais ficam em graficos/. |
| 4.2 · Perfis anteriores a 2025 | analise_perfis.py | resultados/perfis_municipais/ contém correlações, modelos, métricas, sensibilidades, caracterização, municípios e mapa. Referência K-Means com cinco grupos, mínimo de 12 meses ativos e quatro indicadores. |
| 4.3 · Resposta comercial | analise_choque.py, regimes_comerciais.py e panorama_comercial.py | resultados/periodo_choque/ contém séries, fases, resistência, compensação por município e SH4, movimentos por destino, quantidade, recuperação e mapas. O caderno de previsões fica em resultados/panorama/visuais/. |
| 4.4 · Associação | exposicao_tarifaria.py, modelos_associacao.py e analise_resiliencia.py | resultados/secao_4/ reúne exposição por medida, composição e denominador, resposta por perfil, coeficientes, diagnósticos e o caderno resultados_discussao.pdf. |

As comparações de setembro–outubro e agosto–dezembro comparam 2025 aos mesmos meses de 2024. A comparação anual confronta agosto/2024–julho/2025 com agosto/2025–julho/2026, atravessando diversos regimes. Os perfis são nominais. As previsões estaduais são exploratórias. Para a seção 4, use os arquivos por medida da versão atual. Em instalações anteriores podem existir arquivos históricos como exposicao_municipal.csv e correspondencia_sh4.csv. [Dicionário](docs/dicionario_dados.md) · [Decisões](docs/decisoes_metodologicas.md)

## Verificar

~~~bash
python -m unittest discover -s tests -v
python validar_resultados.py
~~~

A validação compara os lotes disponíveis com as linhas do consolidado, reconcilia FOB, kg e perdas entre as tabelas, verifica a malha e recalcula métricas dos perfis. Com scikit-learn instalado, inclui a comparação com os agrupamentos dessa biblioteca. A execução grava auditoria.json, manifesto_fontes.csv e relatorio_execucao.md em resultados/secao_4/. Os modelos singulares ou instáveis aparecem em diagnosticos_modelos.csv. Para comparar a transcrição de 2026 com os PDFs oficiais usando a rede, execute `python preparar_tarifas.py --verificar-anexos-2026`. [Validações e limitações](docs/validacoes.md)

Quando o CSV nacional está indisponível, a etapa 8 consulta a API geral para cada ano de 2022 a 2024. Descrições sem código são consultadas no catálogo oficial de NCM. Homônimos exigem consultas filtradas por código. A rotina confere o FOB e o peso por mês e UF antes de salvar o lote validado em `dados/brutos/ncm/API_EXP_EUA_AAAA.csv`, que também é reutilizado offline. Para os países, a alternativa é o catálogo municipal da API, salvo como PAIS_api.csv. Uma execução online que termina as análises com algum desses insumos pendente registra o motivo em auditoria.json e retorna código 2. Os modos offline podem concluir a reprodução dos limites parciais com os arquivos disponíveis.

Para testar a reprodução integral em duas execuções, use `COMEX_TESTE_INTEGRAL=1 python -m unittest discover -s tests -v` com os lotes locais. O teste constrói a base, as tabelas, os relatórios e as figuras em diretório temporário e compara seus hashes.

# Vulnerabilidade e resiliência comercial dos municípios mineiros

Projeto de pesquisa do IFMG, Campus Sabará. Investigamos como a concentração das exportações em produtos e destinos e a dependência do mercado dos Estados Unidos antes de 2025 se associam às perdas e à compensação comercial observadas nos municípios de Minas Gerais.

A versão auditada da base abrange **janeiro de 2015 a outubro de 2026**. A série histórica usa todos os meses disponíveis. Os indicadores estruturais municipais usam **janeiro de 2022 a dezembro de 2024**. A comparação anual confronta **agosto de 2024 a julho de 2025** com **agosto de 2025 a julho de 2026**. O panorama acompanha também o trimestre mais recente e projeta os três meses seguintes para as exportações estaduais. A localização corresponde ao domicílio fiscal do exportador.

## Reproduzir os resultados

Baixe ou clone o repositório e abra um terminal na pasta que contém este README. O ambiente de referência usa **Python 3.14.10**. No Linux, prepare o ambiente virtual e instale as versões de pandas, NumPy, Matplotlib e Requests registradas no [arquivo de dependências](requirements.txt).

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Com o ambiente preparado, execute a análise completa com **um comando**. A primeira execução precisa de internet para obter os dados e a malha municipal.

```bash
python executar_analise.py
```

Ao concluir, abra **`resultados/secao_4/resultados_discussao.pdf`** para percorrer as subseções 4.1 a 4.4. O caderno de previsões e panorama permanece em `resultados/panorama/visuais/panorama_visual.pdf`. O terminal mostra o progresso das seis etapas. Se uma delas falhar, a execução para nessa etapa e exibe o erro do script responsável.

| Etapa | Script acionado | Resultados |
|---|---|---|
| 1. Coleta e histórico | `analise_comex.py` | Consulta o Comex Stat em lotes anuais de MG, consolida os CSVs e gera os três gráficos históricos. |
| 2. Estrutura pré-choque | `analise_cientifica.py` | Obtém ou reutiliza a malha, calcula os indicadores, compara critérios de inclusão e gera o mapa municipal. |
| 3. Perfis municipais (4.2) | `analise_perfis.py` | Compara K-Means e Ward, avalia estabilidade e gera a caracterização e o mapa dos grupos. |
| 4. Período do choque | `analise_choque.py` | Compara as duas janelas anuais e gera tabelas e figuras por município, produto e destino. |
| 5. Panorama e previsões | `panorama_comercial.py` | Relaciona dependência, perdas e compensação, avalia previsões e chama `visualizar_panorama.py` para gerar o caderno e os PNGs. |
| 6. Resiliência e discussão (4.4) | `analise_resiliencia.py` | Cruza perfis, desfechos e listas oficiais, estima modelos com controles e monta o caderno da seção 4. |

Para repetir **todas as análises sem rede**, use o comando abaixo. Ele requer o consolidado em `dados/tratados/exportacoes_mg_atual.csv` e a malha em `dados/malhas/mg_municipios.geojson`. Os resultados refletem a cobertura dessa cópia local.

```bash
python executar_analise.py --usar-base-local
```

| Resultado gerado | Caminho local |
|---|---|
| Lotes de exportação por ano | `dados/brutos/api_mg/` |
| Série histórica consolidada | `dados/tratados/exportacoes_mg_atual.csv` |
| Três gráficos históricos | `graficos/` |
| Tabela por município | `resultados/pre_choque/indicadores_municipais.csv` |
| Comparação de sete critérios de inclusão | `resultados/pre_choque/sensibilidade_inclusao.csv` |
| Mapa dos quatro indicadores | `resultados/pre_choque/mapa_indicadores_mg.png` |
| Correlações, grupos, validação, sensibilidades e mapa | `resultados/perfis_municipais/` |
| Exposição potencial, regressões, comparações entre perfis e caderno da seção 4 | `resultados/secao_4/` |
| Comparação anual, séries e mapas do choque | `resultados/periodo_choque/` |
| Cruzamentos municipais, produtos, projeções e validação | `resultados/panorama/*.csv` |
| Caderno em PDF e figuras individuais em PNG | `resultados/panorama/visuais/` |

Na execução de referência, a tabela apresentou **446 municípios** e a coluna `fob_pre_usd` somou **US$ 110.032.285.301**. O mapa representou em cinza os 407 municípios sem FOB positivo na janela. Os CSVs usam ponto e vírgula como separador.

Depois da primeira execução, use `python analise_cientifica.py` para recalcular os indicadores a partir da base tratada e da malha local. O comando `python analise_comex.py --somente-graficos` regenera os três gráficos históricos usando o consolidado.

Para executar os testes da coleta, dos indicadores e do panorama, use o comando abaixo. As respostas da API nos testes são simuladas.

```bash
python -m unittest discover -s tests -v
```

## Dados e atualização

**Exportações.** A coleta gravou 610.971 registros na versão auditada de `dados/tratados/exportacoes_mg_atual.csv`. Cada linha reúne mês, município, posição SH4 e país de destino, com peso líquido em kg e valor FOB em dólares correntes. Os dados vêm do módulo municipal do Comex Stat, disponibilizado pelo MDIC. A auditoria identifica a versão utilizada por SHA-256 e apresenta as contagens por ano. [Dados abertos do MDIC](https://www.gov.br/mdic/pt-br/assuntos/comercio-exterior/estatisticas/base-de-dados-bruta) · [Manual da API](Manual.pdf) · [Auditoria da base](docs/validacoes.md)

**Malha municipal.** O script baixa o GeoJSON simplificado da fonte na primeira execução, valida os 853 códigos municipais e salva o arquivo em `dados/malhas/mg_municipios.geojson`. Nas execuções seguintes, reutiliza essa cópia e faz a junção ao CSV pelo código municipal de sete dígitos. A documentação da fonte consultada não explicita a licença de redistribuição nem o ano dos limites. [Arquivo da fonte](https://raw.githubusercontent.com/csmartins8/Mapas-de-Minas-Gerais/master/MG_municipios_simplificado.json) · [Proveniência e critérios de análise](docs/decisoes_metodologicas.md)

**Atualização.** Execute novamente `python analise_comex.py` com acesso à internet para atualizar a série. Ele consulta a API desde 2015, com um lote de dados por ano e filtro para Minas Gerais. Os lotes de anos completos são reutilizados. O fim da série respeita o último mês civil encerrado e a disponibilidade da fonte. Os lotes ficam em `dados/brutos/api_mg/`, pasta excluída do Git. A coleta atualiza o CSV consolidado e os gráficos históricos. Novas competências ou revisões do MDIC podem mudar os resultados em relação à versão auditada.


As fórmulas, a definição dos meses ativos e os procedimentos de validação estão na [metodologia da base e da coleta](docs/base_e_coleta.tex) e na [metodologia dos indicadores](docs/indicadores_vulnerabilidade.tex).

## Panorama do choque e acompanhamento

Depois de obter a base tratada, execute `python panorama_comercial.py` para cruzar a estrutura municipal de 2022–2024 com as perdas, comparar produtos e destinos e prever os próximos três meses de exportações estaduais. A rotina grava os CSVs em `resultados/panorama/` e gera o caderno de gráficos e tabelas em `resultados/panorama/visuais/panorama_visual.pdf`. Cada página também fica disponível como PNG na mesma pasta. O [panorama da pesquisa](docs/panorama_comercial.md) apresenta as janelas, o significado dos indicadores e a validação das previsões.

Para gerar novamente apenas as figuras e o PDF, usando os CSVs do panorama e a malha municipal já obtidos, execute `python visualizar_panorama.py`.


## Resultados e discussão do artigo

A [redação da seção 4](docs/resultados_discussao.tex) usa a extração com observações até outubro de 2026. Para incluí-la no artigo, use o pacote LaTeX `graphicx` e compile a partir da raiz do projeto. Os arquivos de redação registram a execução de referência. Com uma nova extração, confira os números publicados contra as tabelas regeneradas.

Para repetir a 4.2 com a tabela de indicadores já gerada, execute `python analise_perfis.py`. A classificação municipal está em `municipios.csv`, na pasta de perfis. A coluna vazia identifica exportadores fora do corte. `modelos.csv` compara 100 especificações; `comparacao_principal.csv` documenta a seleção e `sensibilidade.csv` compara classificações sobre os municípios comuns.

Para repetir a 4.4 com os resultados da 4.2 e do panorama disponíveis, execute `python analise_resiliencia.py`. Em `resultados/secao_4/`, `resposta_por_perfil.csv` informa as amostras de cada desfecho e `regressoes_hc3.csv` contém os coeficientes e intervalos. `resposta_municipal.csv` liga o código municipal e o perfil aos desfechos de cada janela. `compensacao_por_produto.csv` soma as perdas e os ganhos pareados dentro de cada município e SH4. As parcelas de exposição vão de 0 a 1. Consulte a [correspondência tarifária e suas limitações](dados/tarifas/README.md) e as [decisões metodológicas](docs/decisoes_metodologicas.md).

# Vulnerabilidade e resiliência comercial dos municípios mineiros

Projeto de pesquisa do IFMG, Campus Sabará. A etapa preliminar investiga quais municípios de Minas Gerais concentravam suas exportações em poucos produtos ou destinos, quanto dependiam do mercado dos Estados Unidos e quanto suas vendas mensais oscilavam antes das medidas tarifárias de 2025.

A versão auditada da base de exportações abrange **janeiro de 2015 a outubro de 2026**. Os gráficos históricos usam toda a série disponível na execução. O mapa e os indicadores municipais usam exclusivamente **janeiro de 2022 a dezembro de 2024**. A localização corresponde ao domicílio fiscal do exportador. A análise da resposta posterior às tarifas é uma etapa futura.

## Reproduzir os resultados

Baixe ou clone o repositório e abra um terminal na pasta que contém este README. O ambiente de referência usa **Python 3.14.10**. No Linux, prepare o ambiente virtual e instale as versões de pandas, NumPy, Matplotlib e Requests registradas no [arquivo de dependências](requirements.txt).

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Na primeira execução, conecte-se à internet e rode os comandos na ordem abaixo. O primeiro consulta o Comex Stat em lotes anuais de Minas Gerais, salva os CSVs, consolida a série e gera três gráficos históricos. Se a coleta terminar com sucesso, o segundo lê a base tratada, obtém a malha municipal e gera os indicadores e o mapa. Os scripts criam as pastas necessárias.

```bash
python analise_comex.py && python analise_cientifica.py
```

| Resultado gerado | Caminho local |
|---|---|
| Lotes de exportação por ano | `dados/brutos/api_mg/` |
| Série histórica consolidada | `dados/tratados/exportacoes_mg_atual.csv` |
| Três gráficos históricos | `graficos/` |
| Tabela por município | `resultados/pre_choque/indicadores_municipais.csv` |
| Comparação de sete critérios de inclusão | `resultados/pre_choque/sensibilidade_inclusao.csv` |
| Mapa dos quatro indicadores | `resultados/pre_choque/mapa_indicadores_mg.png` |

Na execução de referência, a tabela apresentou **446 municípios** e a coluna `fob_pre_usd` somou **US$ 110.032.285.301**. O mapa representou em cinza os 407 municípios sem FOB positivo na janela. Os CSVs usam ponto e vírgula como separador.

Depois da primeira execução, use `python analise_cientifica.py` para recalcular os indicadores a partir da base tratada e da malha local. O comando `python analise_comex.py --somente-graficos` regenera os três gráficos históricos usando o consolidado.

Para executar os testes da coleta e dos indicadores, use o comando abaixo. As respostas da API nos testes são simuladas.

```bash
python -m unittest discover -s tests -v
```

## Dados e atualização

**Exportações.** A coleta gravou 610.971 registros na versão auditada de `dados/tratados/exportacoes_mg_atual.csv`. Cada linha reúne mês, município, posição SH4 e país de destino, com peso líquido em kg e valor FOB em dólares correntes. Os dados vêm do módulo municipal do Comex Stat, disponibilizado pelo MDIC. A auditoria identifica a versão utilizada por SHA-256 e apresenta as contagens por ano. [Dados abertos do MDIC](https://www.gov.br/mdic/pt-br/assuntos/comercio-exterior/estatisticas/base-de-dados-bruta) · [Manual da API](Manual.pdf) · [Auditoria da base](docs/validacoes.md)

**Malha municipal.** O script baixa o GeoJSON simplificado da fonte na primeira execução, valida os 853 códigos municipais e salva o arquivo em `dados/malhas/mg_municipios.geojson`. Nas execuções seguintes, reutiliza essa cópia e faz a junção ao CSV pelo código municipal de sete dígitos. A documentação da fonte consultada não explicita a licença de redistribuição nem o ano dos limites. [Arquivo da fonte](https://raw.githubusercontent.com/csmartins8/Mapas-de-Minas-Gerais/master/MG_municipios_simplificado.json) · [Proveniência e critérios de análise](docs/decisoes_metodologicas.md)

**Atualização.** Execute novamente `python analise_comex.py` com acesso à internet para atualizar a série. Ele consulta a API desde 2015, com um lote de dados por ano e filtro para Minas Gerais. Os lotes de anos completos são reutilizados. O fim da série respeita o último mês civil encerrado e a disponibilidade da fonte. Os lotes ficam em `dados/brutos/api_mg/`, pasta excluída do Git. A coleta atualiza o CSV consolidado e os gráficos históricos. Novas competências ou revisões do MDIC podem mudar os resultados em relação à versão auditada.


As fórmulas, a definição dos meses ativos e os procedimentos de validação estão na [metodologia da base e da coleta](docs/base_e_coleta.tex) e na [metodologia dos indicadores](docs/indicadores_vulnerabilidade.tex).

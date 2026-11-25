"""Executa a análise completa das exportações municipais de Minas Gerais.

Instale as bibliotecas com python -m pip install -r requirements.txt.
A primeira execução precisa de internet e do programa pdftotext (Poppler).
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys


RAIZ = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--usar-base-local", action="store_true",
        help="Reutiliza o CSV tratado, a malha e a lista tarifária para executar a análise sem rede.",
    )
    args = parser.parse_args()

    coleta = ["analise_comex.py"]
    primeira_etapa = "Coleta anual, consolidação e gráficos históricos"
    if args.usar_base_local:
        for nome in ("dados/tratados/exportacoes_mg_atual.csv", "dados/malhas/mg_municipios.geojson",
                     "dados/tarifas/excecoes_brasil_2025.csv"):
            if not (RAIZ / nome).is_file():
                parser.error(f"Arquivo local ausente: {nome}. Execute sem --usar-base-local para obtê-lo.")
        coleta.append("--somente-graficos")
        primeira_etapa = "Gráficos históricos a partir da base local"
    else:
        print("Preparando a lista tarifária para a análise completa.", flush=True)
        preparo = subprocess.run([sys.executable, "-u", "preparar_tarifas.py"], cwd=RAIZ)
        if preparo.returncode:
            print("Falha na preparação da lista tarifária.", file=sys.stderr)
            return preparo.returncode if preparo.returncode > 0 else 128 - preparo.returncode

    etapas = [
        (primeira_etapa, coleta),
        ("Indicadores e mapa municipal pré-choque", ["analise_cientifica.py"]),
        ("Seção 4.2 · Identificação e validação dos perfis municipais", ["analise_perfis.py"]),
        ("Comparação do período do choque por município, produto e destino", ["analise_choque.py"]),
        ("Panorama, previsões e caderno de gráficos e tabelas", ["panorama_comercial.py"]),
        ("Seção 4.4 · Exposição tarifária, resiliência e síntese das quatro subseções", ["analise_resiliencia.py"]),
    ]
    ambiente = dict(os.environ, MPLBACKEND="Agg")
    for numero, (descricao, comando) in enumerate(etapas, 1):
        print(f"\n[{numero}/{len(etapas)}] {descricao}", flush=True)
        resultado = subprocess.run([sys.executable, "-u", *comando], cwd=RAIZ, env=ambiente)
        if resultado.returncode:
            print(f"Análise interrompida na etapa {numero} ({comando[0]}).", file=sys.stderr)
            return resultado.returncode if resultado.returncode > 0 else 128 - resultado.returncode

    print(f"\nAnálise completa. Seção 4 em {RAIZ / 'resultados/secao_4/resultados_discussao.pdf'}")
    print(f"Panorama e previsões em {RAIZ / 'resultados/panorama/visuais/panorama_visual.pdf'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

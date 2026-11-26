"""Executa a análise completa das exportações municipais de Minas Gerais.

Instale as bibliotecas com python -m pip install -r requirements.txt.
A primeira execução precisa de internet e do programa pdftotext (Poppler).
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


RAIZ = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modos = parser.add_mutually_exclusive_group()
    modos.add_argument(
        "--usar-base-local", action="store_true",
        help="Reutiliza o CSV tratado, a malha e a lista tarifária para executar a análise sem rede.",
    )
    modos.add_argument("--desde-lotes",action="store_true",help="Reprocessa também os lotes brutos locais, sem rede.")
    args = parser.parse_args()
    offline = args.usar_base_local or args.desde_lotes

    coleta = ["analise_comex.py"]
    primeira_etapa = "Coleta anual, consolidação e gráficos históricos"
    if offline:
        necessarios = ["dados/malhas/mg_municipios.geojson","dados/tarifas/excecoes_brasil_2025.csv"]
        if args.usar_base_local:
            necessarios.append("dados/tratados/exportacoes_mg_atual.csv")
        for nome in necessarios:
            if not (RAIZ / nome).is_file():
                parser.error(f"Arquivo local ausente: {nome}. Execute sem --usar-base-local para obtê-lo.")
        coleta.append("--desde-lotes" if args.desde_lotes else "--somente-graficos")
        primeira_etapa = "Reprocessamento dos lotes locais" if args.desde_lotes else "Gráficos históricos da base local"
    etapas = [
        (primeira_etapa, coleta),
        ("Verificação dos anexos e calendário tarifário", ["preparar_tarifas.py"]),
        ("Indicadores e mapa pré-choque", ["analise_cientifica.py"]),
        ("Perfis municipais e validação", ["analise_perfis.py"]),
        ("Evolução anual e mapas das perdas", ["analise_choque.py"]),
        ("Painel sazonal, compensação e recuperação", ["regimes_comerciais.py"]),
        ("Panorama e previsões", ["panorama_comercial.py"]),
        ("Exposição por versão da medida e composição", ["exposicao_tarifaria.py"] +
         ([] if offline else ["--baixar-ncm"])),
        ("Associações, robustez e caderno da Seção 4", ["analise_resiliencia.py"]),
        ("Reconciliação, hashes e relatório da execução", ["validar_resultados.py"] + ([] if offline else ["--baixar-catalogo"])),
    ]
    ambiente = dict(os.environ, MPLBACKEND="Agg", SOURCE_DATE_EPOCH="0")
    for numero, (descricao, comando) in enumerate(etapas, 1):
        print(f"\n[{numero}/{len(etapas)}] {descricao}", flush=True)
        resultado = subprocess.run([sys.executable, "-u", *comando], cwd=RAIZ, env=ambiente)
        if resultado.returncode:
            print(f"Análise interrompida na etapa {numero} ({comando[0]}).", file=sys.stderr)
            return resultado.returncode if resultado.returncode > 0 else 128 - resultado.returncode

    auditoria = json.loads((RAIZ/"resultados/secao_4/auditoria.json").read_text())
    pendencias = auditoria["pendencias_fontes"]
    if pendencias:
        print("Execução parcial quanto às fontes: " + " ".join(pendencias), flush=True)
    print(f"\nExecução encerrada. Consulte auditoria.json para cobertura e pendências. Seção 4 em {RAIZ / 'resultados/secao_4/resultados_discussao.pdf'}")
    print(f"Panorama e previsões em {RAIZ / 'resultados/panorama/visuais/panorama_visual.pdf'}")
    return 2 if pendencias and not offline else 0


if __name__ == "__main__":
    sys.exit(main())

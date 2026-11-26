"""Reconstitui o CSV tarifário local a partir dos anexos oficiais de 2025.

Na primeira execução, requer internet e pdftotext (Poppler).
"""
import hashlib
import html
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import NamedTemporaryFile

from analise_comex import requisitar

LISTA = Path(__file__).resolve().parent / "dados/tarifas/excecoes_brasil_2025.csv"
JULHO = "https://www.whitehouse.gov/presidential-actions/2025/07/addressing-threats-to-the-us/"
NOVEMBRO = "https://www.whitehouse.gov/wp-content/uploads/2025/11/2025NovemberBrazilTariff.ANNEXES.pdf"
SHA256_LISTA = "ea1532df264aa61257a4945b361825458b3261f959e934bacb32d27de957274b"
# Extração anterior do Federal Register: uma subposição difere no oitavo dígito.
# A classificação ao nível SH4 usada no projeto é idêntica nas duas versões.
SHA256_ANTERIOR = "3303bf65769052cfbfa3ccf4cb2e9fbc15c13ea7017fb5a3044835d5f6109e91"
HTS = r"\b\d{4}\.\d{2}\.\d{2}\b"


def reconstruir(julho, novembro):
    """Lê as subdivisões do Anexo II e confere a mesma versão usada na pesquisa."""
    julho = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", julho)).lower().split())
    novembro = " ".join(novembro.lower().split())
    geral = julho.split("(iii) as provided in heading 9903.01.81")[-1]
    regular, separador, aviacao = geral.partition("(iv) as provided in heading 9903.01.82")
    if not separador:
        raise ValueError("Subdivisão da aviação civil ausente no anexo de julho.")
    # Usa apenas códigos das tabelas, sem os cabeçalhos da medida no capítulo 99.
    regular = regular.partition("following provisions of the htsus:")[2]
    aviacao = aviacao.partition("special")[2].partition(":")[2].partition("(v)")[0]
    novembro = novembro.rpartition("the following provisions of the htsus in numerical order:")[2]
    adicionais, separador, especificos = novembro.partition("by inserting the following new subdivision")
    if not separador:
        raise ValueError("Subdivisão de usos específicos ausente no anexo de novembro.")
    registros = ["vigencia;ato;tipo;HTS8;SH4"]
    for data, ato, tipo, codigos in [
        ("2025-08-06", "EO14323", "subposicao", re.findall(HTS, regular)),
        ("2025-08-06", "EO14323", "aviacao_civil", re.findall(HTS, aviacao)),
        ("2025-11-13", "EO14361", "subposicao", re.findall(HTS, adicionais)),
        ("2025-11-13", "EO14361", "uso_especifico", re.findall(r"classifiable in subheading\s+(" + HTS + ")", especificos)),
    ]:
        for codigo in sorted(set(codigos)):
            hts = codigo.replace(".", "")
            registros.append(f"{data};{ato};{tipo};{hts};{hts[:4]}")
    conteudo = ("\n".join(registros) + "\n").encode("utf-8")
    if hashlib.sha256(conteudo).hexdigest() != SHA256_LISTA:
        raise ValueError("Os códigos extraídos divergem da versão auditada. Confira os dois anexos oficiais.")
    return conteudo


def obter_lista(destino=LISTA):
    if destino.is_file():
        # O Git e editores no Windows podem normalizar as quebras de linha.
        digest = hashlib.sha256(destino.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        if digest not in (SHA256_LISTA, SHA256_ANTERIOR):
            raise ValueError(f"CSV tarifário local divergente da versão auditada: {destino}")
        return destino
    conversor = shutil.which("pdftotext")
    if not conversor:
        raise RuntimeError("Instale o Poppler (pdftotext) para importar o anexo tarifário em PDF.")
    print("Obtendo os anexos tarifários de julho e novembro de 2025.", flush=True)
    with requisitar("GET", JULHO) as resposta:
        resposta.raise_for_status()
        julho = resposta.text
    with requisitar("GET", NOVEMBRO) as resposta:
        resposta.raise_for_status()
        texto = subprocess.run([conversor, "-layout", "-enc", "UTF-8", "-", "-"],
                               input=resposta.content, stdout=subprocess.PIPE, check=True).stdout
    conteudo = reconstruir(julho, texto.decode("utf-8"))
    destino.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=destino.parent, delete=False) as f:
        tmp = Path(f.name)
    try:
        tmp.write_bytes(conteudo)
        tmp.replace(destino)
    finally:
        tmp.unlink(missing_ok=True)
    return destino



# Recorte das tabelas incondicionais. Códigos estatísticos HTSUS de dez
# dígitos são conservados integralmente. Usos finais ficam indeterminados.
FONTES_2026 = {
    "secao122": ("https://www.whitehouse.gov/wp-content/uploads/2026/02/2026Section122.prc_.ANNEX1_.FINAL_.pdf",
                 r"\(ii\)\s+As provided in heading 9903\.03\.03", r"\(iii\)\s+As provided in heading 9903\.03\.04"),
    "secao301_brasil": ("https://content.govdelivery.com/attachments/USDHSCBP/2026/07/21/file_attachments/3721364/Section%20301%20HTS%20LIST07172026_508c.pdf",
                         r"9903\.05\.03\s*:", r"9903\.05\.04\s*:"),
    "secao301_trabalho": ("https://content.govdelivery.com/attachments/USDHSCBP/2026/07/23/file_attachments/3723786/Forced%20Labor%20HTS%20LIST.pdf",
                           r"9903\.05\.86\s*:", r"9903\.05\.87\s*:"),
}
RECORTE_2026 = LISTA.parents[2] / "docs/excecoes_2026.csv"
HASH_2026 = "6edc4a6a972053394332c4144710d91d55fac9b59e3f41a6079dc95909d5dcea"


def extrair_anexo_2026(texto, medida):
    _, inicio, fim = FONTES_2026[medida]
    trecho = re.search(inicio + r"(.*?)" + fim, texto, re.S | re.I)
    if trecho is None:
        raise ValueError(f"Tabela incondicional ausente em {medida}.")
    codigos = re.findall(r"(?<!\d)(\d{4}\.\d{2}\.(?:\d{4}|\d{2}))(?!\d)", trecho[1])
    resultado = {c.replace(".", "") for c in codigos if not c.startswith("99")}
    if not resultado:
        raise ValueError(f"Tabela tarifária vazia em {medida}.")
    return resultado


def ler_excecoes_2026(arquivo=RECORTE_2026):
    import pandas as pd
    if hashlib.sha256(arquivo.read_bytes().replace(b"\r\n", b"\n")).hexdigest() != HASH_2026:
        raise ValueError("SHA-256 divergente no recorte tarifário de 2026.")
    return pd.read_csv(arquivo, sep=";", dtype=str)


def verificar_anexos_2026():
    recorte = ler_excecoes_2026()
    for medida, (url, _, _) in FONTES_2026.items():
        with requisitar("GET", url) as resposta:
            resposta.raise_for_status()
            texto = subprocess.run(["pdftotext","-layout","-","-"], input=resposta.content,
                                   stdout=subprocess.PIPE, check=True).stdout.decode()
            codigos = extrair_anexo_2026(texto, medida)
            faltantes = set(recorte.loc[recorte.medida.eq(medida),"htsus"]) - codigos
            if faltantes:
                raise ValueError(f"{medida}: códigos transcritos divergentes: {sorted(faltantes)}")
            print(medida, "SHA-256 PDF", hashlib.sha256(resposta.content).hexdigest())


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verificar-anexos-2026", action="store_true")
    obter_lista()
    if parser.parse_args().verificar_anexos_2026:
        verificar_anexos_2026()
    ler_excecoes_2026()
    from regimes_comerciais import calendario, salvar, SECAO
    salvar(calendario(), "calendario_medidas_tarifarias", SECAO)

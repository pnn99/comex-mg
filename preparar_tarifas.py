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


if __name__ == "__main__":
    print(obter_lista())

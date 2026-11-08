"""Gera bases_embutidas/folha_rh_AAAA-MM.csv a partir do Caderno de RH da SEPLAG (PDF mensal, público em
https://www.rj.gov.br/gesperj/). Uso: python scripts/caderno_rh.py Caderno_de_RH-Mes2026.pdf 2026-03 URL_DO_PDF

Lê, por sigla do órgão: vínculos ativos, dispêndio do mês e remuneração média (tabelas 6 e 7) e os servidores
efetivos/concursados com idade e tempo de exercício médios (tabela 8). Órgão que não aparece na tabela 8 não tem
servidor efetivo lotado. Precisa do pdftotext (poppler)."""
import csv
import re
import subprocess
import sys
from pathlib import Path

NUM = r"[\d.]+"


def _num(texto):
    return float(texto.replace(".", "").replace(",", "."))


def ler(pdf):
    texto = subprocess.run(["pdftotext", "-layout", pdf, "-"], capture_output=True, text=True, check=True).stdout
    trecho = lambda ini, fim: texto[texto.index(ini):texto.index(fim, texto.index(ini))]
    orgaos = {}
    for tabela, adm, fim in (("Tabela 6 -", "direta", "Tabela 7 -"), ("Tabela 7 -", "indireta", "Tabela 8 -")):
        for m in re.finditer(rf"^\s*([A-ZÀ-Ú][A-ZÀ-Ú0-9 .\-]*?)\s+({NUM})\s+[\d,]+%\s+R\$\s*([\d.,]+)\s+R\$\s*([\d.,]+)",
                             trecho(tabela, fim), re.M):
            sigla = m.group(1).strip()
            if sigla in ("TOTAL", "ÓRGÃO"):
                continue
            orgaos[sigla] = {"sigla": sigla, "administracao": adm, "vinculos_ativos": int(_num(m.group(2))),
                             "dispendio_mes_mi": _num(m.group(3)), "remuneracao_media": _num(m.group(4))}
    efetivos = {}
    for m in re.finditer(rf"^\s*([A-ZÀ-Ú][A-ZÀ-Ú0-9 .\-]*?)\s+({NUM})\s+[\d,]+%\s+(\d+)\s+(\d+)\s*$",
                         trecho("Tabela 8 -", "Tabela 9 -"), re.M):
        efetivos[m.group(1).strip()] = (int(_num(m.group(2))), int(m.group(3)), int(m.group(4)))
    for sigla, o in orgaos.items():
        e = efetivos.get(sigla)
        o["efetivos"] = e[0] if e else 0
        o["efetivos_na_tabela_8"] = "sim" if e else "não"
        o["idade_media_efetivos"] = e[1] if e else ""
        o["tempo_exercicio_medio_efetivos"] = e[2] if e else ""
        o["nao_efetivos"] = max(o["vinculos_ativos"] - o["efetivos"], 0)
        o["pct_nao_efetivos"] = round(100 * o["nao_efetivos"] / o["vinculos_ativos"], 1) if o["vinculos_ativos"] else ""
    return list(orgaos.values())


if __name__ == "__main__":
    pdf, competencia, url = sys.argv[1], sys.argv[2], sys.argv[3]
    linhas = ler(pdf)
    saida = Path(__file__).resolve().parent.parent / "bases_embutidas" / f"folha_rh_{competencia}.csv"
    with open(saida, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["competencia", "url", *linhas[0].keys()])
        w.writeheader()
        for l in linhas:
            w.writerow({"competencia": competencia, "url": url, **l})
    print(f"{len(linhas)} órgãos em {saida}")

"""Lê o PDF do Plano de Governo 2027-2030 e grava os trechos com id (página e posição), eixo e tema. O PDF é em
duas colunas: a leitura é por blocos de texto (PyMuPDF), coluna da esquerda e depois a da direita, para que cada
compromisso saia inteiro. Compromissos são os itens de lista (•); o resto é texto de diagnóstico e apresentação.

Uso (uma vez):  pip install pymupdf
                python scripts/plano_governo.py PDG20272030.pdf bases_embutidas/plano_governo_2027_2030.json
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

# páginas de cada eixo, pelo sumário do plano
EIXOS = [(6, 15, "Eixo 1 – Rio Seguro"), (16, 26, "Eixo 2 – Rio que Cuida"), (27, 38, "Eixo 3 – Rio Próspero"),
         (39, 50, "Eixo 4 – Rio que Avança")]
RE_TEMA = re.compile(r"[A-ZÁÉÍÓÚÂÊÔÃÕÇ0-9 ,\-–]{4,60}")


def main(pdf, saida):
    import pymupdf
    doc = pymupdf.open(pdf)
    trechos = []
    for n in range(1, len(doc) + 1):
        eixo = next((e for a, b, e in EIXOS if a <= n <= b), "Abertura e considerações")
        tema = ""
        blocos = [b for b in doc[n - 1].get_text("blocks", sort=True) if b[4].strip()]
        blocos.sort(key=lambda b: (b[0] > doc[n - 1].rect.width / 2, b[1]))
        for k, b in enumerate(blocos, 1):
            texto = re.sub(r"(\w)- (\w)", r"\1\2", re.sub(r"\s+", " ", b[4])).strip()
            if texto.startswith("Plano do Rio Real"):
                continue
            if RE_TEMA.fullmatch(texto):
                tema = texto
                continue
            trechos.append({"id": f"P{n}.{k}", "pagina": n, "eixo": eixo, "tema": tema,
                            "tipo": "compromisso" if texto.startswith("•") else "texto", "texto": texto.lstrip("• ")})
    Path(saida).write_text(json.dumps({"fonte": Path(pdf).name, "titulo": "Plano do Rio Real 2027-2030",
                                       "trechos": trechos}, ensure_ascii=False, indent=0), encoding="utf-8")
    c = Counter((t["eixo"], t["tipo"]) for t in trechos)
    print(f"{len(trechos)} trechos; compromissos por eixo: "
          + "; ".join(f"{e}: {c[(e, 'compromisso')]}" for _, _, e in EIXOS))
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))

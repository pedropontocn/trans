"""Lê o Volume 2 da LOA (ou da PLOA) do Estado do Rio de Janeiro e grava, por unidade orçamentária, as ações do
"Demonstrativo da despesa por programa de trabalho": código completo (função.subfunção.programa.ação), descrição e
valor total. Confere, por unidade, a soma das ações contra o total declarado no próprio livro.

Uso (uma vez, quando sair uma LOA ou PLOA nova):
    python scripts/orcamento_loa.py LIVRO_LOA_2026_-_VOLUME_II.pdf bases_embutidas/loa_2026.json --exercicio 2026 --tipo LOA
    python scripts/orcamento_loa.py Volume_II_FINAL_Retificado.pdf bases_embutidas/ploa_2027.json --exercicio 2027 --tipo PLOA
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

RE_UO = re.compile(r"^UO:\s*(\d{5})\s*-\s*(.+)$", re.M)
RE_CODIGO = re.compile(r"^(\d{2}\.\d{3}\.\d{4}\.\d{4})\s+(.*)$")
RE_VALOR = re.compile(r"^(?:\d{1,3}(?:\.\d{3})*|-----)$")
RE_TOTAL = re.compile(r"^TOTAL (FISCAL|SEGURIDADE|DA SEGURIDADE SOCIAL|INVESTIMENTO)\S*\s+([\d.]+)", re.M)
COLUNAS = 7          # total + seis grupos de despesa


def _valores_no_fim(texto):
    """Separa a descrição dos sete valores do fim da linha (total e grupos de despesa)."""
    tokens = texto.split()
    k = len(tokens)
    while k > 0 and RE_VALOR.match(tokens[k - 1]) and len(tokens) - k < COLUNAS:
        k -= 1
    return " ".join(tokens[:k]), tokens[k:]


RE_ATRIBUICOES = re.compile(r"PRINCIPAIS ATRIBUIÇÕES\n(.*?)\n(?:LEGISLAÇÃO|ESTRUTURA|$)", re.S)


def ler_paginas(paginas):
    acoes, declarado, atribuicoes = [], Counter(), {}
    for n, texto in enumerate(paginas, 1):
        uo_a = RE_UO.search(texto)
        if uo_a and (m := RE_ATRIBUICOES.search(texto)) and uo_a.group(1) not in atribuicoes:
            atribuicoes[uo_a.group(1)] = {"texto": re.sub(r"\s+", " ", m.group(1)).strip(), "pagina": n}
        if "DEMONSTRATIVO DA DESPESA POR PROGRAMA" not in texto:
            continue
        uo = RE_UO.search(texto)
        if not uo:
            continue
        for m in RE_TOTAL.finditer(texto):
            declarado[uo.group(1)] += int(m.group(2).replace(".", ""))
        linhas = texto.splitlines()
        for k, linha in enumerate(linhas):
            m = RE_CODIGO.match(linha.strip())
            if not m:
                continue
            resto = m.group(2)
            desc, valores = _valores_no_fim(resto)
            extra = 1
            while len(valores) < COLUNAS and k + extra < len(linhas) and not linhas[k + extra].startswith(("ESFERA", "TOTAL")) \
                    and not RE_CODIGO.match(linhas[k + extra].strip()):
                resto += " " + linhas[k + extra].strip()      # valores ou descrição que quebraram na linha de baixo
                desc, valores = _valores_no_fim(resto)
                extra += 1
            if len(valores) != COLUNAS or valores[0] == "-----":
                continue
            prox = linhas[k + 1].strip() if k + 1 < len(linhas) else ""
            if prox and not prox.startswith(("ESFERA", "TOTAL")) and not re.match(r"^\d{2}[. ]", prox) \
                    and not any(RE_VALOR.match(t) for t in prox.split()):
                desc += " " + prox                             # descrição que continuou sozinha na linha de baixo
            cod = m.group(1)
            acoes.append({"uo": uo.group(1), "uo_nome": uo.group(2).strip(), "codigo": cod, "funcao": cod[:2],
                          "subfuncao": cod[3:6], "programa": cod[7:11], "acao": cod[12:], "descricao": desc.strip(),
                          "total": int(valores[0].replace(".", "")), "pagina": n})
    return acoes, declarado, atribuicoes


def main():
    p = argparse.ArgumentParser()
    p.add_argument("pdf"); p.add_argument("saida"); p.add_argument("--exercicio", required=True)
    p.add_argument("--tipo", choices=["LOA", "PLOA"], required=True)
    a = p.parse_args()
    import pdfplumber
    with pdfplumber.open(a.pdf) as pdf:
        paginas = [pg.extract_text() or "" for pg in pdf.pages]
    acoes, declarado, atribuicoes = ler_paginas(paginas)
    soma = Counter()
    for x in acoes:
        soma[x["uo"]] += x["total"]
    uos = {}
    for x in acoes:
        uos.setdefault(x["uo"], {"nome": x["uo_nome"], "total_declarado": declarado.get(x["uo"]),
                                 "soma_das_acoes": soma[x["uo"]], "confere": soma[x["uo"]] == declarado.get(x["uo"]),
                                 "atribuicoes": atribuicoes.get(x["uo"], {}).get("texto", ""),
                                 "pagina_atribuicoes": atribuicoes.get(x["uo"], {}).get("pagina")})
    divergentes = [u for u, d in uos.items() if not d["confere"]]
    saida = {"tipo": a.tipo, "exercicio": a.exercicio, "fonte": Path(a.pdf).name,
             "observacao": "Demonstrativo da despesa por programa de trabalho, recursos de todas as fontes, R$ 1,00.",
             "uos": uos, "acoes": acoes}
    Path(a.saida).write_text(json.dumps(saida, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"{a.tipo} {a.exercicio}: {len(acoes)} ações em {len(uos)} unidades; {len(uos) - len(divergentes)} conferem; "
          f"divergentes: {divergentes}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

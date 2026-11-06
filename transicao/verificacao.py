"""Verificação por código dos números do documento: cada valor, percentual e data precisa estar no material."""
import re
from bisect import bisect_left

from .modelo import _norm


_UNIDADES = {"mil": 1e3, "mi": 1e6, "milhao": 1e6, "milhoes": 1e6, "bi": 1e9, "bilhao": 1e9, "bilhoes": 1e9}


_RE_GRANDEZA = r"(\d[\d.,]*\d|\d)\s*(mil|mi|milh[aã]o|milh[oõ]es|bi|bilh[aã]o|bilh[oõ]es)?\b"


RE_DINHEIRO = re.compile(r"R\$\s*" + _RE_GRANDEZA, re.I)


RE_GRANDEZA_FONTE = re.compile(_RE_GRANDEZA, re.I)


RE_PERCENT = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")


RE_DATA = re.compile(r"\b\d{2}/\d{2}/\d{4}\b")


def _numero_br(txt):
    """'236.441.332,55' -> (236441332.55, 2); '236,4' -> (236.4, 1); '1.302' -> (1302, 0)."""
    txt = txt.strip(".,")
    if "," in txt:
        inteiro, dec = txt.rsplit(",", 1)
        return float(inteiro.replace(".", "") + "." + dec), len(dec)
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", txt):
        return float(txt.replace(".", "")), 0
    if "." in txt:
        inteiro, dec = txt.rsplit(".", 1)
        return float(inteiro.replace(".", "") + "." + dec), len(dec)
    return float(txt), 0


def _valores_fonte(base):
    valores = []
    for m in RE_GRANDEZA_FONTE.finditer(base):
        try:
            v, _ = _numero_br(m.group(1))
        except ValueError:
            continue
        valores.append(v * _UNIDADES.get(_norm(m.group(2) or ""), 1))
        if m.group(2):
            valores.append(v)
    return sorted(valores)


def _proximo(valor, ordenados, tol):
    i = bisect_left(ordenados, valor - tol)
    return i < len(ordenados) and ordenados[i] <= valor + tol


def verificar_numeros(memo, base):
    """Procura no texto-base cada valor em R$, percentual e data citado no memorando."""
    valores, percentuais = _valores_fonte(base), []
    for m in RE_PERCENT.finditer(base):
        try:
            percentuais.append(_numero_br(m.group(1))[0])
        except ValueError:
            pass
    percentuais.sort()
    achados = []

    def registrar(tipo, m, ok):
        declarado = re.match(r"\s*[(\[,;-]?\s*c[aá]lculo", memo[m.end():m.end() + 15], re.I)
        situacao = "conferido" if ok else ("cálculo declarado" if declarado else "não encontrado")
        ini, fim = max(0, m.start() - 50), min(len(memo), m.end() + 40)
        achados.append({"tipo": tipo, "valor": m.group(0).strip(), "situacao": situacao,
                         "contexto": re.sub(r"\s+", " ", memo[ini:fim]).strip()})

    for m in RE_DINHEIRO.finditer(memo):
        try:
            v, casas = _numero_br(m.group(1))
        except ValueError:
            continue
        unidade = _UNIDADES.get(_norm(m.group(2) or ""), 1)
        tol = 0.5 * 10 ** -casas * unidade + 0.01
        registrar("valor", m, _proximo(v * unidade, valores, tol))
    for m in RE_PERCENT.finditer(memo):
        try:
            v, casas = _numero_br(m.group(1))
        except ValueError:
            continue
        registrar("percentual", m, _proximo(v, percentuais, 0.5 * 10 ** -casas + 1e-9))
    for m in RE_DATA.finditer(memo):
        registrar("data", m, m.group(0) in base)
    return achados



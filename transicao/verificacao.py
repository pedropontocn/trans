"""Verificação por código: trechos citados, números, nível de evidência e confiança."""
import re
from bisect import bisect_left

from .modelo import _comparavel, _norm, _shingles, trecho_confere
from .pesquisa import TIPOS_FONTE, itens_incluidos, nivel_maximo


def verificar_evidencias(tm, base, dossie=None, relatorio=""):
    """Confere a fonte de cada argumento e ajusta o nível de evidência por regra explícita.

    - item do dossiê: o id precisa existir e o trecho precisa estar no item; o nível não passa do nível máximo do item;
    - autodeclaração: o trecho precisa estar no relatório; sem confirmação no dossiê, vale no máximo Nível 4;
    - cálculo: o dado de partida precisa estar no dossiê ou no relatório;
    - nível 1-2 sem fonte conferida cai para Nível 5. Normas vão para a revisão jurídica.
    """
    comp = _comparavel(base)
    base_sh = _shingles(comp.split())
    comp_rel = _comparavel(relatorio)
    rel_sh = _shingles(comp_rel.split())
    itens = {i["id"]: i for i in itens_incluidos(dossie)}
    textos_itens = {}
    for k, i in itens.items():
        texto_item = _comparavel(i["afirmacao"] + " " + i["trecho"])
        textos_itens[k] = (texto_item, _shingles(texto_item.split()))
    res = {"conferidas": [], "calculos": [], "rebaixadas": [], "normas": [], "limitadas": [], "autodeclaracoes": []}

    def nivel_de(item):
        try:
            return int(item.get("evidencia", 5))
        except (TypeError, ValueError):
            return 5

    def rebaixar(item, nivel, reg, motivo):
        item["evidencia_declarada"], item["evidencia"] = nivel, 5
        item["verificacao"] = reg["motivo"] = motivo
        res["rebaixadas"].append(reg)

    def limitar(item, nivel, teto, reg, motivo):
        if nivel < teto:
            item["evidencia_declarada"], item["evidencia"] = nivel, teto
            item["verificacao"] = reg["motivo"] = motivo
            res["limitadas"].append({**reg, "teto": teto})

    def checar(item, onde):
        if not isinstance(item, dict):
            return None
        fonte = item.get("fonte") if isinstance(item.get("fonte"), dict) else {}
        tipo = fonte.get("tipo", "nenhuma")
        nivel = nivel_de(item)
        reg = {"onde": onde, "nivel": nivel, "tipo": tipo, "referencia": str(fonte.get("referencia", "")),
               "trecho": str(fonte.get("trecho", ""))}
        if tipo == "norma":
            res["normas"].append(reg)
        elif tipo == "dossie":
            ref = re.sub(r"[^EO0-9]", "", reg["referencia"].upper())
            alvo = itens.get(ref)
            if alvo is None:
                rebaixar(item, nivel, reg, f"item {reg['referencia'] or '?'} não existe no dossiê")
            elif not trecho_confere(reg["trecho"], *textos_itens[ref]):
                rebaixar(item, nivel, reg, f"trecho não encontrado no item {ref} do dossiê")
            else:
                reg["referencia"] = ref
                res["conferidas"].append(reg)
                limitar(item, nivel, nivel_maximo(alvo), reg,
                        f"limitado ao nível máximo do item {ref} ({TIPOS_FONTE[alvo['tipo_fonte']].lower()}, "
                        f"{'conferido' if alvo['checagem'] == 'conferido' or alvo.get('conferido_pela_equipe') else 'não conferido'})")
        elif tipo in ("autodeclaracao", "relatorio"):
            if not trecho_confere(reg["trecho"], comp_rel, rel_sh):
                rebaixar(item, nivel, reg, "trecho não encontrado no relatório do órgão")
            else:
                res["autodeclaracoes"].append(reg)
                limitar(item, nivel, 4, reg, "autodeclaração do órgão sem confirmação no dossiê")
        elif tipo == "calculo":
            if trecho_confere(reg["trecho"], comp, base_sh):
                res["calculos"].append(reg)
                limitar(item, nivel, 2, reg, "cálculo vale no máximo nível 2")
            elif nivel <= 2:
                rebaixar(item, nivel, reg, "dado de partida do cálculo não encontrado no dossiê nem no relatório")
        elif nivel <= 2:
            rebaixar(item, nivel, reg, "nível 1-2 sem fonte de apoio")
        return item.get("evidencia", nivel)

    baseline = tm.get("baseline_reference")
    if isinstance(baseline, dict):
        for i, c in enumerate(baseline.get("consequencias") or [], 1):
            checar(c, f"Baseline, consequência {i}")
    for t in tm.get("trade_offs") or []:
        if not isinstance(t, dict):
            continue
        niveis = [checar(t.get(p), f"{t.get('id', '?')} · {rot}") for p, rot in (("polo_a", "Polo A"), ("polo_b", "Polo B"))]
        niveis = [n for n in niveis if isinstance(n, int)]
        # o trade-off não pode ter evidência mais forte que o seu polo mais bem apoiado
        try:
            declarado = int(t.get("nivel_evidencia", 5))
        except (TypeError, ValueError):
            declarado = 5
        if niveis and declarado < min(niveis):
            t["nivel_evidencia_declarado"], t["nivel_evidencia"] = declarado, min(niveis)
    return tm, res


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


RE_TITULO = re.compile(r"^#{1,4}\s+(.+)$", re.M)


def confianca_calculada(dossie, estab, ev):
    """Confiança da análise calculada por regras explícitas, em vez de declarada pelo modelo.
    dossie: o resumo de resumo_dossie()."""
    ordem = ["baixa", "média", "alta"]
    nivel, motivos = 2, []
    if dossie and dossie.get("itens"):
        c = dossie["conferidos"] / dossie["itens"]
        motivos.append(f"{dossie['conferidos']} de {dossie['itens']} itens do dossiê foram conferidos na fonte "
                       f"({dossie['oficiais']} de fonte oficial)")
        nivel = min(nivel, 0 if c < 0.4 else 1 if c < 0.7 else 2)
    else:
        motivos.append("sem dossiê de fontes independentes")
        nivel = 0
    total_ev = len(ev["conferidas"]) + len(ev["calculos"]) + len(ev["rebaixadas"]) + len(ev.get("autodeclaracoes", []))
    if total_ev:
        r = len(ev["rebaixadas"]) / total_ev
        motivos.append(f"{len(ev['rebaixadas'])} de {total_ev} fontes citadas não foram encontradas no dossiê ou no relatório"
                       if ev["rebaixadas"] else f"as {total_ev} fontes citadas foram encontradas no dossiê ou no relatório")
        nivel = min(nivel, 0 if r > 0.4 else 1 if r > 0.15 else 2)
        auto = len(ev.get("autodeclaracoes", []))
        if auto and auto / total_ev > 0.5:
            motivos.append(f"{auto} de {total_ev} fontes citadas são só a autodeclaração do órgão")
            nivel = min(nivel, 1)
    if not estab or estab.get("rodadas", 1) <= 1:
        motivos.append("a estabilidade entre rodadas não foi medida")
        nivel = min(nivel, 1)
    else:
        motivos.append(f"{estab['estaveis']} trade-off(s) se repetiram em pelo menos {estab['minimo_para_estavel']} "
                       f"de {estab['rodadas']} rodadas")
        if estab.get("previstas", 0) > estab["rodadas"]:
            motivos.append(f"as rodadas 1 e 2 chegaram aos mesmos trade-offs; as outras "
                           f"{estab['previstas'] - estab['rodadas']} das {estab['previstas']} previstas não foram necessárias")
        if estab["estaveis"] == 0:
            nivel = 0
    return {"nivel": ordem[nivel], "motivos": motivos}

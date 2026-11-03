import json
from collections import Counter
from litellm import completion
import os

# Usando duas versões do Gemini como validadores independentes
VALIDATORS = {
    "gemini_pro":   {"model": "gemini/gemini-3.1-pro-preview", "temperature": 0.1},
    "gemini_flash": {"model": "gemini/gemini-3.8-flash", "temperature": 0.1},
}

def fleiss_kappa(matrix):
    n_items = len(matrix)
    if n_items == 0: return 0.0
    n_raters = sum(matrix[0])
    if n_raters < 2: return 0.0

    P_items = []
    for row in matrix:
        total = sum(row)
        P = (sum(c * (c - 1) for c in row)) / (total * (total - 1)) if total > 1 else 0
        P_items.append(P)
    P_bar = sum(P_items) / n_items

    col_totals = [sum(row[j] for row in matrix) for j in range(len(matrix[0]))]
    grand_total = sum(col_totals)
    p_j = [c / grand_total for c in col_totals]
    P_e = sum(p * p for p in p_j)

    if P_e == 1.0: return 1.0
    return (P_bar - P_e) / (1 - P_e)

def extract_relevant_data(filepath):
    import re
    with open(filepath, encoding="utf-8") as f:
        conteudo = f.read()

    # Limpa blocos de markdown do Claude
    conteudo = re.sub(r'^```json\s*|\s*```$', '', conteudo.strip(), flags=re.MULTILINE)

    try:
        data = json.loads(conteudo)
    except json.JSONDecodeError:
        # Se falhar, tenta achar o JSON dentro do texto bruto
        match = re.search(r'\{.*\}', conteudo, re.DOTALL)
        data = json.loads(match.group(0)) if match else {}

    # O Claude colocou a Fase 4 dentro de uma chave. O validador precisa achar os trade-offs.
    if "fase_4_tension_map" in data:
        data = data["fase_4_tension_map"]

    return {
        "tension_map_id": data.get("tension_map_id", "N/A"),
        "scenario": data.get("scenario", "N/A"),
        "trade_offs": data.get("trade_offs", [])
    }

def rodar_validacao(tension_map_core):
    if not tension_map_core.get("trade_offs"):
        return {"erro": "Nenhum trade-off encontrado no JSON para validar."}

    print("   → Enviando para auditoria cruzada (Gemini Pro vs Gemini Flash)...")

    AUDIT_PROMPT = """Você é um auditor independente de políticas públicas.
    Abaixo está um Tension Map. Sua tarefa NÃO é elogiar. É apontar problemas com rigor.
    Responda APENAS com JSON válido.

    Para CADA trade-off, classifique em: "legitimo", "fraco", "contestado" ou "nao_ancorado".
    Formato: {{"avaliacao_por_trade_off": [{{"trade_off_id": "T1", "classificacao": "legitimo"}}]}}

    TENSION MAP: {tension_map}"""

    results = []
    for name, cfg in VALIDATORS.items():
        try:
            resp = completion(
                model=cfg["model"],
                temperature=cfg["temperature"],
                messages=[{"role": "user", "content": AUDIT_PROMPT.format(tension_map=json.dumps(tension_map_core, ensure_ascii=False))}],
                response_format={"type": "json_object"}
            )
            results.append({"validator": name, "ok": True, "data": json.loads(resp.choices[0].message.content)})
        except Exception as e:
            print(f"   ⚠️ Erro no {name}: {e}")
            results.append({"validator": name, "ok": False})

    ok_results = [r for r in results if r["ok"]]
    if len(ok_results) < 2:
        return {"erro": "Validação inconclusiva. Um dos modelos falhou."}

    categorias = ["legitimo", "fraco", "contestado", "nao_ancorado"]
    cat_index = {c: i for i, c in enumerate(categorias)}
    trade_ids = [t["trade_off_id"] for t in tension_map_core["trade_offs"]]

    matrix = []
    per_trade = {tid: {} for tid in trade_ids}

    for tid in trade_ids:
        row = [0] * len(categorias)
        for r in ok_results:
            for av in r["data"].get("avaliacao_por_trade_off", []):
                if av.get("trade_off_id") == tid:
                    cat = av.get("classificacao", "fraco")
                    if cat in cat_index:
                        row[cat_index[cat]] += 1
                        per_trade[tid][r["validator"]] = cat
        matrix.append(row)

    kappa = fleiss_kappa(matrix)

    return {
        "fleiss_kappa": round(kappa, 3),
        "kappa_interpretation": "ALTA" if kappa > 0.7 else "BAIXA" if kappa < 0.2 else "MODERADA",
        "avaliacao_por_trade_off": per_trade
    }

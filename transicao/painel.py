"""Painel estadual: as urgências de todas as secretarias, na mesma régua, em poucas páginas.

Quase tudo é calculado por código a partir dos riscos e vencimentos de cada secretaria (ranking, mapa de calor,
cronograma). O modelo entra uma vez, para apontar os temas que se repetem entre secretarias; o código confere que
as secretarias e os riscos citados existem.
"""
from collections import Counter, defaultdict
from datetime import date

from . import documentos
from .modelo import chamar_json
from .produtos import _ler_data, _mi, ordem_de_prioridade
from .riscos import CATEGORIAS

PROMPT_TEMAS = """Você lê os riscos da transição de várias secretarias do Estado do Rio de Janeiro, já ordenados por
prioridade, e aponta os TEMAS TRANSVERSAIS: problemas que se repetem em várias secretarias ou que dependem de uma
decisão central (Casa Civil, Fazenda, PGE, governador). Não recomende: descreva o tema, por que ele é transversal e o
que está em jogo. Use só o que está na lista; cite os riscos pelo código entre colchetes (ex.: "SECID:R2").
Português claro, frases de até 25 palavras. Não use: trade-off, persona, dossiê.

Responda SOMENTE com JSON, entre [INÍCIO DO JSON] e [FIM DO JSON]:
{"temas": [{"titulo": "até 8 palavras", "descricao": "2 ou 3 frases", "riscos": ["SECID:R2", "SES:R1"]}]}
Entre 3 e 6 temas, do mais amplo para o mais restrito."""


def _sigla(nome):
    partes = [p.strip() for p in nome.rsplit(" - ", 1)]
    return partes[-1] if len(partes) == 2 and partes[-1].isupper() else nome


def temas_transversais(modelo, riscos, uso):
    """Uma chamada: os temas que se repetem. Fica só o tema que cita riscos reais de pelo menos duas secretarias."""
    codigos = {f"{_sigla(r['orgao'])}:{r['id']}": r for r in riscos}
    linhas = [f"[{c}] {r['titulo']} — {r['categoria']} — prioridade {r['prioridade'].lower()} — {r['causa']} → "
              f"{r['consequencia']}" for c, r in list(codigos.items())[:300]]
    dados = chamar_json(modelo, [{"role": "system", "content": PROMPT_TEMAS},
                                 {"role": "user", "content": "RISCOS:\n" + "\n".join(linhas)}],
                        6000, etapa="painel estadual: temas transversais", uso_lista=uso) or {}
    temas = []
    for t in dados.get("temas") or []:
        if not isinstance(t, dict):
            continue
        citados = [c for c in (str(x).strip().strip("[]") for x in t.get("riscos") or []) if c in codigos]
        secretarias = sorted({_sigla(codigos[c]["orgao"]) for c in citados})
        if len(secretarias) >= 2 or (len(riscos) and len({r["orgao"] for r in riscos}) == 1 and citados):
            temas.append({"titulo": str(t.get("titulo") or "").strip(), "descricao": str(t.get("descricao") or "").strip(),
                          "secretarias": secretarias, "riscos": citados})
    return temas


def _mes(d):
    meses = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
    return f"{meses[d.month - 1]}/{d.year}"


def markdown_painel(riscos, situacoes, eventos, temas, data_corte, linhas=None):
    hoje = (_ler_data(data_corte) or (date.today(), False))[0] if data_corte else date.today()
    ordenados = sorted(riscos, key=lambda r: (-r["nota"], r.get("agir_ate") or date.max))
    secretarias = sorted({r["orgao"] for r in riscos})
    maximas = [r for r in riscos if r["prioridade"] == "Máxima"]
    contratos = [e for e in eventos if e.get("origem", "").startswith("Contratos") and 0 <= e["dias"] <= 90]
    md = ["## O essencial",
          f"- {len(maximas)} risco(s) de prioridade máxima e "
          f"{sum(r['prioridade'] == 'Alta' for r in riscos)} de prioridade alta em {len(secretarias)} secretaria(s).",
          f"- {sum(1 for r in riscos if r.get('agir_ate') and r['agir_ate'] <= hoje)} risco(s) já passaram da data para agir."]
    if contratos:
        md.append(f"- {len(contratos)} contrato(s) vencem em até 90 dias ({_mi(sum(e.get('valor') or 0 for e in contratos))}); "
                  f"{sum(e.get('essencial') for e in contratos)} são de serviço essencial.")
    if temas:
        md.append(f"- Temas que se repetem: " + "; ".join(t["titulo"] for t in temas[:4]) + ".")

    md += ["## As urgências do Estado",
           "| # | Secretaria | Risco | Categoria | Prioridade | Agir até | Base |", "|---|---|---|---|---|---|---|"]
    for k, r in enumerate(ordenados[:20], 1):
        agir = f"{r['agir_ate']:%d/%m/%Y}" if r.get("agir_ate") else "–"
        md.append(f"| {k} | {_sigla(r['orgao'])} | {r['id']}. {r['titulo']} | {r['categoria']} | {r['prioridade']} | "
                  f"{agir} | {r['firmeza']} |")

    if temas:
        md.append("## Temas que se repetem entre secretarias")
        for t in temas:
            md.append(f"### {t['titulo']}")
            md.append(t["descricao"])
            md.append(f"_Secretarias: {', '.join(t['secretarias'])}. Riscos: {', '.join(t['riscos'])}._")

    md += ["## Mapa de calor",
           "Riscos de prioridade máxima ou alta por secretaria e categoria (entre parênteses, os de prioridade máxima).",
           "| Secretaria | " + " | ".join(CATEGORIAS) + " | Total |", "|---|" + "---|" * (len(CATEGORIAS) + 1)]
    por_sec = defaultdict(Counter)
    for r in riscos:
        if r["prioridade"] in ("Máxima", "Alta"):
            por_sec[r["orgao"]][r["categoria"]] += 1
            if r["prioridade"] == "Máxima":
                por_sec[r["orgao"]][r["categoria"] + "*"] += 1
    for sec in sorted(secretarias, key=lambda s: (-sum(por_sec[s][c] for c in CATEGORIAS), s)):
        celulas = [(f"{por_sec[sec][c]}" + (f" ({por_sec[sec][c + '*']})" if por_sec[sec][c + "*"] else ""))
                   if por_sec[sec][c] else "–" for c in CATEGORIAS]
        md.append(f"| {_sigla(sec)} | " + " | ".join(celulas) + f" | {sum(por_sec[sec][c] for c in CATEGORIAS)} |")

    md.append("## Cronograma: quando agir")
    faixas = defaultdict(list)
    for r in ordenados:
        if r.get("agir_ate"):
            faixas["Já passou da data" if r["agir_ate"] <= hoje else _mes(r["agir_ate"])].append(r)
    chaves = (["Já passou da data"] if "Já passou da data" in faixas else []) + sorted(
        [k for k in faixas if k != "Já passou da data"],
        key=lambda k: min(r["agir_ate"] for r in faixas[k]))
    md += ["| Quando | Riscos | Os mais prioritários |", "|---|---|---|"]
    for k in chaves[:8]:
        destaque = "; ".join(f"{_sigla(r['orgao'])}: {r['titulo']}" for r in faixas[k][:3])
        md.append(f"| {k} | {len(faixas[k])} | {destaque} |")

    if contratos:
        md += ["## Contratos de maior prioridade que vencem em até 90 dias",
               "| Secretaria | Contrato | Valor | Agir até | Situação |", "|---|---|---|---|---|"]
        for e in sorted(contratos, key=ordem_de_prioridade)[:12]:
            md.append(f"| {_sigla(e['orgao'])} | {e['evento']}" + (" – serviço essencial" if e.get("essencial") else "")
                      + f" | {e.get('valor_texto') or '–'} | {e['agir_ate']:%d/%m/%Y} | {e.get('situacao_pncp') or e['criticidade']} |")

    if linhas:
        erros = [l for l in linhas if l.get("situacao") != "concluído"]
        if erros:
            md.append("## Secretarias não analisadas")
            md += [f"- {l['orgao']}: {l.get('observacao') or 'erro'}" for l in erros]
    md.append(f"_Consolida os riscos de {len(secretarias)} secretaria(s), com data de corte {data_corte}, com a mesma "
              "régua de prioridade (impacto × urgência) calculada por código. A base de contratos do Estado (SIGA) não "
              "traz contratos de gestão com OS, convênios nem concessões. Riscos com base \"informado pelo órgão\" ou "
              "\"sem comprovação\" dependem de confirmação. O detalhe e a base de cada risco estão no documento de "
              "cada secretaria. Gerado com apoio de IA, sem revisão da equipe; não recomenda decisões._")
    return "\n".join(md)


def painel_estadual(riscos, situacoes, eventos, cfg, linhas=None):
    """Devolve (Word do painel, uso de tokens)."""
    uso = []
    temas = temas_transversais(cfg["modelo"], riscos, uso) if len({r["orgao"] for r in riscos}) >= 2 else []
    md = markdown_painel(riscos, situacoes, eventos, temas, cfg["data_corte"], linhas)
    meta = {"orgao": cfg.get("orgao_emissor", ""), "unidade": cfg.get("unidade", ""), "para": cfg.get("para", ""),
            "assunto": "Painel estadual de urgências da transição", "tipo": "Painel estadual",
            "data": documentos._data_extenso(date.today()), "rodape_extra": "apoio de IA, processamento automático"}
    return documentos.gerar_docx(md, meta), uso

"""Painel estadual: todas as decisões com prazo antes da posse, nas primeiras 72 horas e nos primeiros 100 dias, e
todas as de repercussão política alta, de todas as secretarias, em ordem de prazo; e os serviços essenciais que podem
parar até o fim dos 100 dias (contratos que a secretaria informou, por código).

Quase tudo é calculado por código a partir dos riscos de cada secretaria (janela pela data-limite contada da posse,
prioridade, ordem). O modelo entra uma vez, para apontar os temas que se repetem entre secretarias; o código confere
que as secretarias e os riscos citados existem.
"""
from datetime import date

from . import documentos
from .modelo import chamar_json
from .produtos import _mi

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


SENS_ORDEM = {"Alta": 0, "Média": 1, "Baixa": 2}


def _linha_demanda(r):
    """Uma linha da tabela do painel: o ponto de decisão, o risco que o motiva, prazo, repercussão política
    (intensidade e quem reage), prioridade e base. Sem responsável: o painel não atribui quem faz."""
    agir = f"{r['agir_ate']:%d/%m/%Y}" if r.get("agir_ate") else "–"
    decisao = f"**{r.get('decisao') or r['titulo']}**" + (f" _({r['titulo']})_" if r.get("decisao") else "")
    rep = documentos._voto(r, "sensibilidade", r.get("sensibilidade"))
    if r.get("motivo_sensibilidade"):
        rep += f": {documentos._curto(r['motivo_sensibilidade'], 120)}"
    return (f"| {agir} | {_sigla(r['orgao'])} | {decisao} | {rep} | {r['prioridade']} | "
            f"{documentos.BASE_CURTA.get(r['firmeza'], r['firmeza'])} |")


CABECALHO = ["| Agir até | Secretaria | Ponto de decisão (risco) | Repercussão política | Prioridade | Base |",
             "|---|---|---|---|---|---|"]


def markdown_apagao(eventos, limite_lista=25):
    """Serviços essenciais que podem parar: contratos informados pela secretaria, de serviço essencial, que vencem até o fim
    dos 100 dias, por secretaria e janela (quantos e quanto), e a lista dos de prioridade máxima. Tudo por código."""
    from datetime import timedelta
    from .riscos import POSSE, horizonte
    limite = POSSE + timedelta(days=99)
    ess = [e for e in eventos or [] if e.get("tipo") == "Contrato" and e.get("essencial")
           and e["data"] <= limite and e["dias"] >= -30]
    if not ess:
        return []
    janelas = ["Antes da posse", "Primeiras 72 horas", "Primeiros 100 dias"]
    jan = lambda e: horizonte(e.get("agir_ate") or e["data"])
    total = sum(e.get("valor") or 0 for e in ess)
    md = [f"## Serviços essenciais que podem parar até {limite:%d/%m/%Y}",
          f"{len(ess)} contrato(s) de serviço essencial (saúde, alimentação, custódia, vigilância, combustível, sistemas "
          f"e outros) vencem até o fim dos 100 dias" + (f", somando {_mi(total)}" if total else "")
          + ", pelo que a secretaria informou. A janela é a da data-limite para agir (30 dias antes do fim). A lista "
          "completa, um a um, está no calendário (filtre Janela).",
          "| Secretaria | " + " | ".join(janelas) + " | Total |", "|---|" + "---|" * (len(janelas) + 1)]
    por_sec = {}
    for e in ess:
        por_sec.setdefault(_sigla(e["orgao"]), []).append(e)
    for sec, lista in sorted(por_sec.items(), key=lambda x: -sum(e.get("valor") or 0 for e in x[1])):
        celulas = []
        for j in janelas:
            da_janela = [e for e in lista if jan(e) == j]
            celulas.append(f"{len(da_janela)} ({_mi(sum(e.get('valor') or 0 for e in da_janela))})" if da_janela else "–")
        md.append(f"| {sec} | " + " | ".join(celulas) + f" | {len(lista)} ({_mi(sum(e.get('valor') or 0 for e in lista))}) |")
    maximas = sorted([e for e in ess if e.get("prioridade") == "Máxima"], key=lambda e: (e.get("agir_ate") or e["data"]))
    if maximas:
        md += [f"**Prioridade máxima ({len(maximas)})**" + (f", os {limite_lista} primeiros por data:" if len(maximas) > limite_lista else ":"),
               "| Agir até | Secretaria | Contrato e objeto | Fornecedor | Valor | Fim |", "|---|---|---|---|---|---|"]
        for e in maximas[:limite_lista]:
            agir = f"{e['agir_ate']:%d/%m/%Y}" if e.get("agir_ate") else "–"
            md.append(f"| {agir} | {_sigla(e['orgao'])} | {documentos._curto(e.get('contratacao') or e['evento'], 20)}: "
                      f"{documentos._curto(e.get('objeto'), 70)} | {documentos._curto(e.get('fornecedor'), 30)} | "
                      f"{e.get('valor_texto') or _mi(e.get('valor') or 0)} | {e['data']:%d/%m/%Y} |")
    return md


def markdown_painel(riscos, situacoes, eventos, temas, data_corte, linhas=None):
    """O painel estadual: todas as demandas que vencem antes da posse, nas primeiras 72 horas e nos primeiros 100 dias,
    e todas as de sensibilidade política alta, de todas as secretarias, na mesma régua. Montado por código."""
    from .riscos import POSSE, horizonte
    for r in riscos:
        r.setdefault("horizonte", horizonte(r.get("agir_ate")))
        r.setdefault("sensibilidade", "Baixa")
    ordem = lambda r: (r.get("agir_ate") or date.max, -r["nota"], SENS_ORDEM.get(r["sensibilidade"], 3))
    secretarias = sorted({r["orgao"] for r in riscos})
    janelas = [("Antes da posse", f"Até {POSSE - __import__('datetime').timedelta(days=1):%d/%m/%Y}: decisões da equipe de "
                "transição e da gestão atual que não podem esperar a posse."),
               ("Primeiras 72 horas", "De 01/01 a 03/01/2027: o que o governo eleito precisa decidir nos três primeiros dias."),
               ("Primeiros 100 dias", "Até 10/04/2027.")]
    por_janela = {h: sorted([r for r in riscos if r["horizonte"] == h], key=ordem) for h, _ in janelas}
    sensiveis_fora = sorted([r for r in riscos if r["sensibilidade"] == "Alta" and r["horizonte"] not in por_janela],
                            key=ordem)
    altas = [r for r in riscos if r["sensibilidade"] == "Alta"]

    md = ["## O essencial",
          (f"- {len(secretarias)} secretaria(s) analisada(s), {len(riscos)} decisão(ões) no total." if len(secretarias) > 1
           else f"- {len(riscos)} decisão(ões) no total."),
          f"- {len(por_janela['Antes da posse'])} com prazo antes da posse; {len(por_janela['Primeiras 72 horas'])} nas "
          f"primeiras 72 horas; {len(por_janela['Primeiros 100 dias'])} nos primeiros 100 dias.",
          f"- {len(altas)} de repercussão política alta"
          + (f" ({sum(r['horizonte'] in por_janela for r in altas)} delas com prazo até os 100 dias)" if altas else "") + "."]
    if temas:
        md.append("- Temas que se repetem entre secretarias: " + "; ".join(t["titulo"] for t in temas[:4]) + ".")
    md.append("_Cada tabela está em ordem de prazo (agir até); no mesmo dia, a prioridade (impacto × urgência, mesma "
              "régua para todas as secretarias). Repercussão política: a intensidade votada pelos seis agentes e quem "
              "reage._")

    for h, explicacao in janelas:
        md += [f"## {h}", explicacao]
        md += (CABECALHO + [_linha_demanda(r) for r in por_janela[h]]) if por_janela[h] else ["_Nenhuma decisão._"]
    if sensiveis_fora:
        md += ["## Repercussão política alta, com prazo depois dos 100 dias ou sem prazo"] + CABECALHO
        md += [_linha_demanda(r) for r in sensiveis_fora]

    md += markdown_apagao(eventos)

    if temas:
        md.append("## Temas que se repetem entre secretarias")
        for t in temas:
            md.append(f"**{t['titulo']}.** {t['descricao']} _({', '.join(t['secretarias'])}: {', '.join(t['riscos'])})_")

    if linhas:
        erros = [l for l in linhas if l.get("situacao") != "concluído"]
        if erros:
            md.append("## Secretarias não analisadas")
            md += [f"- {l['orgao']}: {l.get('observacao') or 'erro'}" for l in erros]
    md.append(f"_Data de corte {data_corte}; posse em {POSSE:%d/%m/%Y}. Prazos e prioridade calculados por código; a "
              "repercussão política é votada pelos seis agentes e só fica alta com quem reage dito. Os contratos que vencem, "
              "um a um, estão no calendário (Excel). O detalhe de cada demanda está no relatório de riscos da secretaria, "
              "e a base, no dossiê dela. Base \"órgão\" ou \"sem comprovação\" depende de confirmação. Gerado com apoio "
              "de IA, sem revisão da equipe; não recomenda decisões._")
    return "\n".join(md)


def painel_estadual(riscos, situacoes, eventos, cfg, linhas=None, orgao=None):
    """Devolve (Word do painel, uso de tokens). Com `orgao`, é o painel de uma secretaria só (sem temas
    transversais, sem chamada ao modelo)."""
    uso = []
    temas = temas_transversais(cfg["modelo"], riscos, uso) if len({r["orgao"] for r in riscos}) >= 2 else []
    md = markdown_painel(riscos, situacoes, eventos, temas, cfg["data_corte"], linhas)
    meta = {"orgao": cfg.get("orgao_emissor", ""), "unidade": cfg.get("unidade", ""), "para": cfg.get("para", ""),
            "assunto": f"Painel de urgências da transição – {orgao}" if orgao else "Painel estadual de urgências da transição",
            "tipo": "Painel de urgências" if orgao else "Painel estadual",
            "data": documentos._data_extenso(date.today()), "rodape_extra": "apoio de IA, processamento automático"}
    return documentos.gerar_docx(md, meta), uso


CAMPOS_PAINEL = ["id", "titulo", "decisao", "categoria", "agir_ate", "horizonte", "prazo_de_fato", "impacto",
                 "sensibilidade", "motivo_sensibilidade", "prioridade", "nota", "firmeza", "em_jogo", "em_curso", "fatos"]


def dados_do_painel(orgao, riscos, situacao, data_corte):
    """Os dados do painel de uma secretaria, para juntar depois no painel unificado: cada ponto de decisão com a
    janela, o prazo, a prioridade e a repercussão política votada, mais a situação da secretaria."""
    return {"orgao": orgao, "sigla": _sigla(orgao), "data_corte": data_corte, "situacao": situacao,
            "janelas": {j: sum(r.get("horizonte") == j for r in riscos) for j in
                        ("Antes da posse", "Primeiras 72 horas", "Primeiros 100 dias", "Depois dos 100 dias", "Sem prazo")},
            "pontos_de_decisao": [dict({c: r.get(c) for c in CAMPOS_PAINEL},
                                       votos={eixo: {"nivel": v.get("nivel"), "contagem": v.get("contagem")}
                                              for eixo, v in (r.get("votos") or {}).items()})
                                  for r in riscos]}

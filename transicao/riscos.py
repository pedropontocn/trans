"""Riscos e decisões urgentes: uma análise, a revisão por cinco agentes independentes e a consolidação.

1. A análise parte do diagnóstico (fatos F1, F2...), dos vencimentos prioritários (V1, V2...) e das contradições entre
   o órgão e as fontes, e devolve riscos, decisões em aberto e o que pedir à secretaria.
2. Cinco agentes, cada um com um viés de gestão, leem a análise em paralelo e independentes: apontam riscos que
   faltaram, riscos exagerados e o que temem e valorizam em cada opção das decisões.
3. Uma consolidação junta tudo. O código confere os fatos citados por cada risco, dá a firmeza da informação e calcula
   a prioridade com a mesma régua dos vencimentos (impacto × urgência).
"""
import json
import re
from datetime import date

from .modelo import _comparavel, _em_paralelo, _norm, _shingles, chamar_json, chamar_modelo, extrair_json, trecho_confere
from .produtos import IMPACTO_PONTOS, LIMITE_SIGA, _ler_data, ordem_de_prioridade
from .pesquisa import TIPOS_OFICIAIS, itens_incluidos

CATEGORIAS = ["Continuidade de serviço", "Fiscal e orçamentário", "Jurídico e controle", "Pessoas e capacidade",
              "Obras e projetos"]
POSSE = date(2027, 1, 1)

PAPEIS = [
    ("fiscal", "Fazenda e orçamento",
     "Olha caixa, restos a pagar, limite do art. 42 da LRF, PLOA 2027 e o custo de cada obrigação assumida agora."),
    ("controle", "Controle e jurídico (TCE-RJ, PGE, MPRJ)",
     "Olha legalidade, decisões de controle em vigor, aditivos acima de limites, emergenciais e responsabilização."),
    ("servico", "Área-fim e usuário do serviço",
     "Olha o que a população deixa de receber: serviço que para, obra que fica pela metade, quem é afetado e onde."),
    ("operacao", "Operação e servidores",
     "Olha a capacidade de executar: fiscais de contrato, sistemas, equipes, cargos que vagam na troca de governo."),
    ("governo", "Nova gestão: prioridades e articulação",
     "Olha as prioridades do governo eleito, a relação com a Alerj e com os municípios e os compromissos que "
     "amarram ou liberam a nova gestão."),
    ("contra", "Advogado do diabo",
     "Tenta derrubar cada risco: procura no material o que mostra que ele está errado, exagerado ou já resolvido."),
]
PAPEL_CONTRA = "Advogado do diabo"

LINGUAGEM = """LINGUAGEM: português claro, de gestão pública; frases de até 25 palavras. Não use: trade-off, persona,
baseline, dossiê, autodeclaração, nível de evidência. Não recomende: nada de "deve", "é preciso", "recomenda-se",
"o ideal é". Decisões são perguntas; opções têm o mesmo peso. Não invente números, datas ou nomes: use só o que está
no material, citando os ids (F1, V2, O3). Valores arredondados (R$ 2,49 bi, R$ 998 mi)."""

ESQUEMA_RISCO = ('{"titulo": "até 10 palavras", "categoria": "' + "|".join(CATEGORIAS) + '", '
                 '"causa": "...", "consequencia": "...", "em_jogo": "valor, serviço ou obra", '
                 '"prazo": "dd/mm/aaaa, antes da posse ou vazio", "impacto": "Alto|Médio|Baixo", "chance": "Alta|Média|Baixa", '
                 '"em_curso": "providência já publicada ou informada, ou vazio", "decisao": "a pergunta", '
                 '"quem_decide": "...", "fatos": ["F3", "V1"]}')

PROMPT_ANALISE = """Você é analista de riscos da Equipe de Transição do governo do Estado do Rio de Janeiro. A partir
do DIAGNÓSTICO da secretaria, dos VENCIMENTOS PRIORITÁRIOS e das CONTRADIÇÕES entre o que a secretaria informou e as
fontes, identifique os riscos da transição e as decisões urgentes. O leitor é o ponto focal da nova gestão: técnico,
com pouco tempo.

""" + LINGUAGEM + """

Entregue:
- "situacao": 4 ou 5 frases que resumem como a secretaria está hoje e o que mais pesa na transição.
- "riscos": 5 a 8 riscos. Cada risco liga uma causa a uma consequência concreta e cita os fatos que o sustentam
  ("fatos": ids F e V do material). Serviço essencial que pode parar pesa mais que obra de valor maior. Se o
  vencimento citado tem aditivo recente, registre em "em_curso".
- "decisoes": as 2 ou 3 decisões mais difíceis, que não se resolvem só cumprindo um prazo. Cada uma com 2 ou 3
  opções de mesmo peso ("nome" com verbo; "o_que_e" em uma frase), "o_que_falta_saber" e os riscos ligados ("riscos":
  ["R1"]).
- "pedir": até 6 documentos ou dados a pedir à secretaria, cada um dizendo a que risco ou decisão serve. Se houver
  CHECKLIST OBRIGATÓRIO com pontos NÃO PROCURADOS, eles entram aqui antes dos demais (cite o id, ex.: "C5").

Numere os riscos R1, R2... e as decisões Q1, Q2... Responda SOMENTE com JSON, entre [INÍCIO DO JSON] e [FIM DO JSON]:
{"situacao": ["..."], "riscos": [{"id": "R1", ...}], "decisoes": [{"id": "Q1", "pergunta": "...", "opcoes": [{"nome":
"...", "o_que_e": "..."}], "o_que_falta_saber": "...", "riscos": ["R1"]}], "pedir": [{"o_que": "...", "serve_a": "R1"}]}
Cada risco segue este formato: """ + ESQUEMA_RISCO

PROMPT_AGENTE = """Você revisa a análise de riscos da transição de uma secretaria do Estado do Rio de Janeiro com um
olhar específico. VOCÊ É: {papel}. {criterio}

Leia o material e a análise. Pelo seu olhar:
1. "faltando": até 3 riscos que a análise não viu e que o material sustenta (cite os ids em "fatos"). Não repita
   riscos que já estão na análise. Se não faltar nada, devolva lista vazia.
2. "exagerados": riscos da análise que o material não sustenta ou cujo impacto está superestimado, com o motivo.
3. "decisoes": para cada decisão (Q1, Q2...), o que você teme e o que você valoriza em cada opção, em uma frase cada.

""" + LINGUAGEM + """

Responda SOMENTE com JSON, entre [INÍCIO DO JSON] e [FIM DO JSON]:
{{"faltando": [{esquema}], "exagerados": [{{"risco": "R2", "motivo": "..."}}],
"decisoes": [{{"decisao": "Q1", "opcao": 1, "teme": "...", "valoriza": "..."}}]}}"""

PROMPT_CONTRA = """Você é o ADVOGADO DO DIABO na análise de riscos da transição de uma secretaria do Estado do Rio de
Janeiro. Seu trabalho é tentar DERRUBAR cada risco da análise: o que no material mostra que ele está errado, exagerado,
já resolvido (providência publicada, aditivo assinado, decisão cumprida) ou sem fato que o sustente. Seja duro e
específico; o que sobreviver a você é mais sólido. Não invente: cada contestação cita os ids do material.

Leia o material e a análise. Entregue:
1. "contestados": os riscos que você consegue derrubar ou enfraquecer, cada um com "risco" (id), "motivo" (uma ou duas
   frases, com os fatos) e "fatos" (ids do material que sustentam a contestação). Risco que você não consegue
   contestar com o material NÃO entra aqui.
2. "sustentados": os ids dos riscos que resistiram, em uma lista.
3. "decisoes": para cada decisão (Q1, Q2...), o que você teme em cada opção, em uma frase (o que pode dar errado).

""" + LINGUAGEM + """

Responda SOMENTE com JSON, entre [INÍCIO DO JSON] e [FIM DO JSON]:
{"contestados": [{"risco": "R2", "motivo": "...", "fatos": ["F4"]}], "sustentados": ["R1", "R3"],
"decisoes": [{"decisao": "Q1", "opcao": 1, "teme": "...", "valoriza": ""}]}"""

PROMPT_CONSOLIDACAO = """Você consolida a análise de riscos da transição de uma secretaria do Estado do Rio de Janeiro
com as revisões de agentes independentes, cada um com um olhar de gestão, e de um ADVOGADO DO DIABO, que tentou
derrubar cada risco.

- Inclua um risco apontado como faltando só se ele citar fatos do material; junte riscos repetidos.
- Ajuste ou retire um risco apontado como exagerado ou contestado só se o motivo se apoiar no material. Contestação
  sem fato não retira risco.
- Mantenha 5 a 8 riscos, numerados de novo (R1, R2...), e 2 ou 3 decisões (Q1, Q2...).
- Em cada risco, preencha "id_anterior": o id que ele tinha na ANÁLISE (ex.: "R3"); se veio de um agente como
  faltando, escreva "novo: " e o nome do agente (ex.: "novo: Fazenda e orçamento"). O sistema usa isso para registrar
  quem apontou e quem contestou cada risco.
- Em cada decisão, acrescente "visoes": para cada agente que opinou, o que ele teme e valoriza, sem dizer qual opção
  é melhor. Mantenha o peso igual entre as opções.

""" + LINGUAGEM + """

Responda SOMENTE com JSON, no mesmo formato da análise, entre [INÍCIO DO JSON] e [FIM DO JSON]. Em cada decisão, inclua
"visoes": [{"papel": "Fazenda e orçamento", "teme": "...", "valoriza": "..."}]. Cada risco segue este formato, mais
"id_anterior": """ + ESQUEMA_RISCO


# --- MATERIAL ------------------------------------------------------------------------------

def vencimentos_numerados(eventos, limite=15):
    """Os vencimentos de maior prioridade, com ids V1, V2... para os riscos citarem."""
    escolhidos = sorted([e for e in eventos or [] if e["dias"] >= -30], key=ordem_de_prioridade)[:limite]
    return {f"V{k}": e for k, e in enumerate(escolhidos, 1)}


def material(orgao, diag, vencimentos, txt_confronto="", data_corte="", txt_checklist=""):
    """O material da análise e dos agentes, em texto compacto e com ids."""
    linhas = [f"SECRETARIA: {orgao}" + (f" · data de corte {data_corte}" if data_corte else ""), "", "DIAGNÓSTICO:"]
    for sec in (diag or {}).get("secoes") or []:
        linhas.append(f"## {sec['titulo']}")
        linhas += [f"- [{i['id']}] {i['texto']} ({i['rotulo']})" for i in sec["itens"]]
        if sec.get("leitura"):
            linhas.append(f"Leitura: {sec['leitura']}")
        if sec.get("nao_se_sabe"):
            linhas.append("Não se sabe: " + "; ".join(sec["nao_se_sabe"]))
    if vencimentos:
        linhas += ["", "VENCIMENTOS PRIORITÁRIOS (prioridade calculada por código: impacto × urgência):"]
        for vid, e in vencimentos.items():
            marcas = [f"prioridade {e.get('prioridade', '?').lower()}", f"agir até {e['agir_ate']:%d/%m/%Y}"
                      if e.get("agir_ate") else ""]
            marcas += ["serviço essencial" if e.get("essencial") else "",
                       "sem tempo para nova licitação" if e.get("sem_tempo_licitar") else "", e.get("situacao_pncp", "")]
            linhas.append(f"- [{vid}] vence {e['data']:%d/%m/%Y}: {e['evento']}"
                          + (f" – {e['objeto'][:140]}" if e.get("objeto") else "")
                          + (f" – {e['valor_texto']}" if e.get("valor_texto") else "")
                          + f" ({'; '.join(m for m in marcas if m)}) [{e.get('origem', '')}]")
        if any(e.get("origem", "").startswith("Contratos") for e in vencimentos.values()):
            linhas.append(f"Limite da base: {LIMITE_SIGA}")
    if txt_confronto:
        linhas += ["", txt_confronto]
    if txt_checklist:
        linhas += ["", txt_checklist]
    return "\n".join(linhas)


# --- ANÁLISE, AGENTES E CONSOLIDAÇÃO ------------------------------------------------------------

def analisar(modelo, texto_material, uso):
    return chamar_json(modelo, [{"role": "system", "content": PROMPT_ANALISE},
                                {"role": "user", "content": texto_material}],
                       12000, etapa="análise de riscos", uso_lista=uso) or {}


def revisar_por_agentes(modelo, texto_material, analise, uso, modelos=None):
    """Os seis agentes (cinco olhares e o advogado do diabo), em paralelo e sem ver as respostas uns dos outros.
    modelos: um por agente (ver config.esquema_de_modelos); sem a lista, todos usam `modelo`."""
    pedido = texto_material + "\n\nANÁLISE A REVISAR:\n" + json.dumps(analise, ensure_ascii=False, indent=1)
    modelos = modelos or [modelo] * len(PAPEIS)

    def um(papel, modelo_agente):
        _, nome, criterio = papel
        sistema = PROMPT_CONTRA if nome == PAPEL_CONTRA else PROMPT_AGENTE.format(
            papel=nome, criterio=criterio, esquema=ESQUEMA_RISCO)
        mensagens = [{"role": "system", "content": sistema}, {"role": "user", "content": pedido}]
        try:
            r = chamar_json(modelo_agente, mensagens, 6000, etapa=f"agente: {nome}", uso_lista=uso)
            if not isinstance(r, dict):
                raise ValueError("resposta ilegível")
            return {"papel": nome, "modelo": modelo_agente, **r}
        except Exception as e:
            erro = f"{type(e).__name__}: {e}"[:200]
        if modelo_agente == modelo:
            return {"papel": nome, "modelo": modelo_agente, "erro": erro}
        # o modelo de outra família falhou (cota, instabilidade, saldo): o olhar não se perde, roda no principal, e
        # fica registrado que esta revisão não foi independente
        try:
            r = chamar_json(modelo, mensagens, 6000, etapa=f"agente: {nome} (substituto)", uso_lista=uso)
            if not isinstance(r, dict):
                raise ValueError("resposta ilegível")
            return {"papel": nome, "modelo": modelo, "modelo_previsto": modelo_agente, "substituto": True,
                    "erro_do_previsto": erro, **r}
        except Exception as e:
            return {"papel": nome, "modelo": modelo, "modelo_previsto": modelo_agente,
                    "erro": f"{erro}; substituto: {type(e).__name__}: {e}"[:300]}
    return _em_paralelo([lambda p=p, m=m: um(p, m) for p, m in zip(PAPEIS, modelos)])


def proveniencia(riscos_finais, revisoes, analise):
    """Para cada risco final, por código e a partir das revisões brutas: de onde veio (análise ou agente que apontou),
    quem fez objeção (exagerado ou contestado, com o motivo) e quantos agentes não objetaram. Usa o "id_anterior" que a
    consolidação registra; sem ele, só conta os agentes que responderam."""
    validas = [r for r in revisoes or [] if not r.get("erro")]
    ids_analise = {str(r.get("id") or "") for r in (analise or {}).get("riscos") or [] if isinstance(r, dict)}
    for risco in riscos_finais:
        anterior = str(risco.get("id_anterior") or "").strip()
        objecoes, origem = [], "análise"
        if anterior.lower().startswith("novo"):
            origem = "apontado por " + (anterior.split(":", 1)[1].strip() if ":" in anterior else "um agente")
        elif anterior and anterior not in ids_analise:
            anterior = ""
        for rev in validas:
            for e in rev.get("exagerados") or []:
                if isinstance(e, dict) and anterior and str(e.get("risco") or "").strip() == anterior:
                    objecoes.append({"papel": rev["papel"], "tipo": "exagerado", "motivo": str(e.get("motivo") or "").strip()})
            for c in rev.get("contestados") or []:
                if isinstance(c, dict) and anterior and str(c.get("risco") or "").strip() == anterior:
                    objecoes.append({"papel": rev["papel"], "tipo": "contestado", "motivo": str(c.get("motivo") or "").strip(),
                                     "fatos": [str(f) for f in c.get("fatos") or []]})
        risco["revisao"] = {"origem": origem, "objecoes": objecoes, "agentes": len(validas),
                            "sem_objecao": len(validas) - len({o["papel"] for o in objecoes}),
                            "contestado": any(o["tipo"] == "contestado" for o in objecoes)}
    return riscos_finais


def consolidar(modelo, texto_material, analise, revisoes, uso):
    validas = [r for r in revisoes if not r.get("erro")]
    if not validas:
        return analise
    pedido = (texto_material + "\n\nANÁLISE:\n" + json.dumps(analise, ensure_ascii=False, indent=1)
              + "\n\nREVISÕES DOS AGENTES:\n" + json.dumps(validas, ensure_ascii=False, indent=1))
    final = chamar_json(modelo, [{"role": "system", "content": PROMPT_CONSOLIDACAO},
                                 {"role": "user", "content": pedido}], 14000, etapa="consolidação dos riscos",
                        uso_lista=uso)
    return final if isinstance(final, dict) and final.get("riscos") else analise


# --- CONFERÊNCIA E PRIORIDADE (código) -------------------------------------------------------------

FIRMEZA = ["confirmado em fonte oficial", "dado do SIGA/PNCP", "fonte pública conferida", "só na imprensa",
           "fonte pública não conferida", "informado pelo órgão", "sem comprovação"]


def _firmeza_item(item):
    if item.get("conferido_pela_equipe"):
        return "dado do SIGA/PNCP"
    if item.get("checagem") == "conferido":
        return "confirmado em fonte oficial" if item.get("tipo_fonte") in TIPOS_OFICIAIS else "fonte pública conferida"
    return "só na imprensa" if item.get("tipo_fonte") == "imprensa" else "fonte pública não conferida"


def _urgencia(dias_agir):
    return 4 if dias_agir <= 0 else 3 if dias_agir <= 30 else 2 if dias_agir <= 90 else 1


def _rotulo_prioridade(nota):
    return "Máxima" if nota >= 9 else "Alta" if nota >= 6 else "Média" if nota >= 3 else "Baixa"


def conferir_e_ordenar(resultado, diag, vencimentos, dossie, data_corte=None):
    """Confere os fatos de cada risco, dá a firmeza (a melhor entre os fatos citados) e a prioridade:
    a dos vencimentos citados ou, sem eles, impacto × urgência pelo prazo. Risco sem fato conferido fica com
    firmeza "sem comprovação" e prioridade no máximo Média. Devolve a lista ordenada."""
    base_dia = (_ler_data(data_corte) or (date.today(), False))[0] if data_corte else date.today()
    fatos = {i["id"]: i["rotulo"] for s in (diag or {}).get("secoes") or [] for i in s["itens"]}
    dossie_ids = {i["id"]: i for i in itens_incluidos(dossie or {})}
    riscos = []
    for k, r in enumerate(resultado.get("riscos") or [], 1):
        if not isinstance(r, dict) or not str(r.get("titulo") or "").strip():
            continue
        citados = [str(f).strip() for f in r.get("fatos") or []]
        validos = [f for f in citados if f in fatos or f in vencimentos or f in dossie_ids]
        firmezas = [fatos[f] if f in fatos else
                    ("dado do SIGA/PNCP" if vencimentos[f].get("origem", "").startswith("Contratos") else
                     "informado pelo órgão" if vencimentos[f].get("origem", "").startswith("Informado") else
                     "fonte pública conferida") if f in vencimentos else _firmeza_item(dossie_ids[f]) for f in validos]
        firmeza = min(firmezas, key=lambda x: FIRMEZA.index(x) if x in FIRMEZA else 99) if firmezas else "sem comprovação"
        impacto = r.get("impacto") if r.get("impacto") in IMPACTO_PONTOS else "Médio"
        ligados = [vencimentos[f] for f in validos if f in vencimentos]
        if ligados:
            nota = max(e.get("prioridade_nota") or 0 for e in ligados)
            agir = min(e["agir_ate"] for e in ligados if e.get("agir_ate"))
        else:
            prazo = str(r.get("prazo") or "")
            lida = _ler_data(prazo)
            agir = lida[0] if lida else POSSE if "posse" in _norm(prazo) else None
            nota = IMPACTO_PONTOS[impacto] * (_urgencia((agir - base_dia).days) if agir else 1)
        if firmeza == "sem comprovação":
            nota = min(nota, 5)
        riscos.append({**{c: str(r.get(c) or "").strip() for c in ("titulo", "causa", "consequencia", "em_jogo", "prazo",
                                                                  "em_curso", "decisao", "quem_decide")},
                       "id_original": str(r.get("id") or f"R{k}"), "id_anterior": str(r.get("id_anterior") or "").strip(),
                       "categoria": r.get("categoria")
                       if r.get("categoria") in CATEGORIAS else "Continuidade de serviço",
                       "impacto": impacto, "chance": r.get("chance") if r.get("chance") in ("Alta", "Média", "Baixa")
                       else "Média", "fatos": validos, "fatos_invalidos": [f for f in citados if f not in validos],
                       "firmeza": firmeza, "agir_ate": agir, "nota": nota, "prioridade": _rotulo_prioridade(nota)})
    riscos.sort(key=lambda r: (-r["nota"], r["agir_ate"] or date.max))
    novo_id = {r["id_original"]: f"R{k}" for k, r in enumerate(riscos, 1)}
    for r in riscos:
        r["id"] = novo_id[r["id_original"]]
    decisoes = []
    for k, q in enumerate([q for q in resultado.get("decisoes") or [] if isinstance(q, dict)][:3], 1):
        opcoes = [o for o in q.get("opcoes") or [] if isinstance(o, dict) and str(o.get("nome") or "").strip()][:3]
        if len(opcoes) < 2:
            continue
        decisoes.append({"id": f"Q{k}", "pergunta": str(q.get("pergunta") or "").strip(), "opcoes": opcoes,
                         "o_que_falta_saber": str(q.get("o_que_falta_saber") or "").strip(),
                         "riscos": [novo_id[x] for x in q.get("riscos") or [] if x in novo_id],
                         "visoes": [v for v in q.get("visoes") or [] if isinstance(v, dict) and v.get("papel")][:6]})
    pedir = [{"o_que": str(p.get("o_que") or "").strip(),
              "serve_a": re.sub(r"\bR\d+\b", lambda m: novo_id.get(m.group(0), m.group(0)), str(p.get("serve_a") or ""))}
             for p in resultado.get("pedir") or [] if isinstance(p, dict) and str(p.get("o_que") or "").strip()][:6]
    situacao = [str(x).strip() for x in resultado.get("situacao") or [] if str(x).strip()][:5]
    return {"situacao": situacao, "riscos": riscos, "decisoes": decisoes, "pedir": pedir}


# --- NEUTRALIDADE E CONFIANÇA ----------------------------------------------------------------------

PROMPT_NEUTRALIDADE = """Você é um revisor de neutralidade. O documento abaixo deveria expor riscos e decisões para a
nova gestão SEM recomendar um caminho. Você não avalia se o conteúdo está certo; só se é neutro. Aponte trechos que
recomendam, prescrevem ou induzem uma opção ("é preciso", "o ideal é", "recomenda-se", "a melhor saída", adjetivos que
desqualificam uma opção) e diga se as opções de cada decisão têm o mesmo peso. Copie cada trecho LITERALMENTE, com até
25 palavras; o sistema confere se ele existe. Responda SOMENTE com JSON:
{"avaliacao_geral": "neutro|levemente_enviesado|enviesado", "recomendacoes_implicitas": [{"trecho": "...",
"por_que": "..."}], "decisoes_desequilibradas": [{"decisao": "...", "motivo": "..."}]}"""


def revisar_neutralidade(modelo, texto, uso_lista=None):
    """Revisão feita por um modelo diferente do que escreveu. Os trechos citados são conferidos no texto."""
    bruto, _, _ = chamar_modelo(modelo, [{"role": "system", "content": PROMPT_NEUTRALIDADE},
                                         {"role": "user", "content": texto}], 3000, etapa="revisão de neutralidade",
                                uso_lista=uso_lista)
    revisao = extrair_json(bruto)
    if not isinstance(revisao, dict):
        return {"erro": "o revisor não devolveu um resultado legível", "modelo": modelo}
    comp = _comparavel(texto)
    sh = _shingles(comp.split())
    achados = [{"trecho": str(r["trecho"]), "por_que": str(r.get("por_que", ""))}
               for r in revisao.get("recomendacoes_implicitas") or []
               if isinstance(r, dict) and trecho_confere(str(r.get("trecho", "")), comp, sh)]
    return {"modelo": modelo, "avaliacao_geral": revisao.get("avaliacao_geral", "?"),
            "recomendacoes_implicitas": achados,
            "decisoes_desequilibradas": [d for d in revisao.get("decisoes_desequilibradas") or [] if isinstance(d, dict)]}


def confianca(resumo_dossie, riscos, cobertura=None):
    """Confiança da análise por regras explícitas: conferência do dossiê, firmeza dos fatos que sustentam os riscos e
    cobertura do checklist obrigatório (ponto não procurado derruba a confiança: alta só sem nenhum em branco)."""
    nivel, motivos = 2, []
    if cobertura:
        em_branco = [c["id"] for c in cobertura if c["estado"] == "não procurado"]
        motivos.append(f"{len(cobertura) - len(em_branco)} de {len(cobertura)} pontos do checklist obrigatório procurados"
                       + (f" (não procurados: {', '.join(em_branco)})" if em_branco else ""))
        nivel = min(nivel, 0 if len(em_branco) > len(cobertura) / 2 else 1 if em_branco else 2)
    if resumo_dossie and resumo_dossie.get("itens"):
        c = resumo_dossie["conferidos"] / resumo_dossie["itens"]
        motivos.append(f"{resumo_dossie['conferidos']} de {resumo_dossie['itens']} fatos do dossiê conferidos na fonte "
                       "ou vindos do SIGA/PNCP")
        nivel = min(nivel, 0 if c < 0.4 else 1 if c < 0.7 else 2)
    else:
        motivos.append("sem dossiê de fontes independentes")
        nivel = 0
    if riscos:
        fracos = [r for r in riscos if r["firmeza"] in ("informado pelo órgão", "sem comprovação",
                                                        "fonte pública não conferida", "só na imprensa")]
        motivos.append(f"{len(riscos) - len(fracos)} de {len(riscos)} riscos apoiados em fonte oficial, conferida ou "
                       "no SIGA/PNCP")
        nivel = min(nivel, 0 if len(fracos) / len(riscos) > 0.6 else 1 if len(fracos) / len(riscos) > 0.3 else 2)
    return {"nivel": ["baixa", "média", "alta"][nivel], "motivos": motivos}

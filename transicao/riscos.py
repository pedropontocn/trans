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

from .modelo import (_comparavel, _em_paralelo, _norm, _shingles, chamar_json, chamar_modelo, em_lote, extrair_json,
                     mensagens_compartilhadas, trecho_confere)
from .produtos import IMPACTO_PONTOS, _ler_data, ordem_de_prioridade
from .pesquisa import TIPOS_OFICIAIS, itens_incluidos

CATEGORIAS = ["Continuidade de serviço", "Fiscal e orçamentário", "Jurídico e controle", "Pessoas e capacidade",
              "Obras e projetos"]
POSSE = date(2027, 1, 1)

HORIZONTES = ["Antes da posse", "Primeiras 72 horas", "Primeiros 100 dias", "Depois dos 100 dias", "Sem prazo"]


def horizonte(agir_ate, posse=POSSE):
    """Em que janela a decisão precisa estar tomada, pela data-limite para agir, contada da posse."""
    from datetime import timedelta
    if not agir_ate:
        return "Sem prazo"
    if agir_ate < posse:
        return "Antes da posse"
    if agir_ate <= posse + timedelta(days=2):
        return "Primeiras 72 horas"
    if agir_ate <= posse + timedelta(days=99):
        return "Primeiros 100 dias"
    return "Depois dos 100 dias"

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

LINGUAGEM = """LINGUAGEM: português claro, de gestão pública; frases completas de até 25 palavras. Não use: trade-off,
persona, baseline, dossiê, autodeclaração, nível de evidência.
TOM: o documento ANALISA; não aconselha. Descreva fatos, causas, consequências e o que está pendente. NÃO recomende,
NÃO sugira caminho nem opção, NÃO proponha providência, NÃO diga quem deve fazer, decidir ou ser responsável por algo.
Proibido: "deve", "deveria", "é preciso", "é necessário", "precisa ser", "recomenda-se", "sugere-se", "convém", "o
ideal", "cabe a", "é importante que", "a melhor saída", "quem decide".
Não invente números, datas ou nomes: use só o que está no material, citando os ids (F1, V2, O3). Valores arredondados
(R$ 2,49 bi, R$ 998 mi)."""

ESQUEMA_RISCO = ('{"titulo": "até 10 palavras", "categoria": "' + "|".join(CATEGORIAS) + '", '
                 '"causa": "...", "consequencia": "...", "em_jogo": "valor, serviço ou obra", '
                 '"prazo": "dd/mm/aaaa, antes da posse, nas primeiras 72 horas, nos primeiros 100 dias ou vazio", '
                 '"impacto": "Alto|Médio|Baixo", "chance": "Alta|Média|Baixa", '
                 '"sensibilidade_politica": "Alta|Média|Baixa", "motivo_sensibilidade": "o que a torna sensível, ou vazio", '
                 '"em_curso": "providência já publicada ou informada, ou vazio", '
                 '"decisao": "o ponto pendente de decisão, em frase afirmativa e neutra, sem listar caminhos", '
                 '"fatos": ["F3", "V1"]}')

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
- Em cada risco, "sensibilidade_politica": a repercussão política da decisão (toda decisão tem): Alta quando a
  reação vem no primeiro dia ou expõe o governador eleito (investigação de MP, TCE, CGE ou polícia; imprensa; serviço
  visível que para; conflito com Alerj, municípios, servidores ou grandes fornecedores; contrato alto sob suspeita);
  Média quando pode chegar lá; Baixa quando fica restrita à máquina. "motivo_sensibilidade" diz quem reage e como.
- Em cada risco, "prazo": a data em que a decisão precisa estar tomada. Sem data no material, diga se é "antes da
  posse", "nas primeiras 72 horas" (o que não pode esperar a primeira semana de governo) ou "nos primeiros 100 dias".
- "pedir": até 6 informações que faltam no material, em frase nominal (ex.: "Execução orçamentária por ação e
  fonte"), cada uma dizendo a que risco se liga. Se houver CHECKLIST OBRIGATÓRIO com temas SEM INFORMAÇÃO, eles entram
  aqui antes dos demais (cite o id, ex.: "C5").

Numere os riscos R1, R2... Responda SOMENTE com JSON, entre [INÍCIO DO JSON] e [FIM DO JSON]:
{"situacao": ["..."], "riscos": [{"id": "R1", ...}], "pedir": [{"o_que": "...", "serve_a": "R1"}]}
Cada risco segue este formato: """ + ESQUEMA_RISCO

PROMPT_AGENTE = """Você revisa a análise de riscos da transição de uma secretaria do Estado do Rio de Janeiro com um
olhar específico. VOCÊ É: {papel}. {criterio}

Leia o material e a análise. Pelo seu olhar:
1. "faltando": até 3 riscos que a análise não viu e que o material sustenta (cite os ids em "fatos"). Não repita
   riscos que já estão na análise. Se não faltar nada, devolva lista vazia.
2. "exagerados": riscos da análise que o material não sustenta ou cujo impacto está superestimado, com o motivo.

""" + LINGUAGEM + """

Responda SOMENTE com JSON, entre [INÍCIO DO JSON] e [FIM DO JSON]:
{{"faltando": [{esquema}], "exagerados": [{{"risco": "R2", "motivo": "..."}}]}}"""

PROMPT_CONTRA = """Você é o ADVOGADO DO DIABO na análise de riscos da transição de uma secretaria do Estado do Rio de
Janeiro. Seu trabalho é tentar DERRUBAR cada risco da análise: o que no material mostra que ele está errado, exagerado,
já resolvido (providência publicada, aditivo assinado, decisão cumprida) ou sem fato que o sustente. Seja duro e
específico; o que sobreviver a você é mais sólido. Não invente: cada contestação cita os ids do material.

Leia o material e a análise. Entregue:
1. "contestados": os riscos que você consegue derrubar ou enfraquecer, cada um com "risco" (id), "motivo" (uma ou duas
   frases, com os fatos) e "fatos" (ids do material que sustentam a contestação). Risco que você não consegue
   contestar com o material NÃO entra aqui.
2. "sustentados": os ids dos riscos que resistiram, em uma lista.

""" + LINGUAGEM + """

Responda SOMENTE com JSON, entre [INÍCIO DO JSON] e [FIM DO JSON]:
{"contestados": [{"risco": "R2", "motivo": "...", "fatos": ["F4"]}], "sustentados": ["R1", "R3"]}"""

PROMPT_CONSOLIDACAO = """Você consolida a análise de riscos da transição de uma secretaria do Estado do Rio de Janeiro
com as revisões de agentes independentes, cada um com um olhar de gestão, e de um ADVOGADO DO DIABO, que tentou
derrubar cada risco.

- Inclua um risco apontado como faltando só se ele citar fatos do material; junte riscos repetidos.
- Ajuste ou retire um risco apontado como exagerado ou contestado só se o motivo se apoiar no material. Contestação
  sem fato não retira risco.
- Mantenha 5 a 8 riscos, numerados de novo (R1, R2...).
- Em cada risco, preencha "id_anterior": o id que ele tinha na ANÁLISE (ex.: "R3"); se veio de um agente como
  faltando, escreva "novo: " e o nome do agente (ex.: "novo: Fazenda e orçamento").
- "respostas_as_revisoes": para CADA risco apontado como faltando, exagerado ou contestado, diga o que fez:
  {"agente": "...", "risco": "R2" ou o título do faltando, "decisao": "acatado|parcial|não acatado", "motivo": "uma
  frase, com os fatos"}. Nenhuma revisão fica sem resposta.
""" + LINGUAGEM + """

Responda SOMENTE com JSON, no mesmo formato da análise, entre [INÍCIO DO JSON] e [FIM DO JSON], mais a lista
"respostas_as_revisoes". Cada risco segue este formato, mais "id_anterior": """ + ESQUEMA_RISCO


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
                       "sem tempo para nova licitação" if e.get("sem_tempo_licitar") else ""]
            linhas.append(f"- [{vid}] vence {e['data']:%d/%m/%Y}: {e['evento']}"
                          + (f" – {e['objeto'][:140]}" if e.get("objeto") else "")
                          + (f" – {e['valor_texto']}" if e.get("valor_texto") else "")
                          + f" ({'; '.join(m for m in marcas if m)}) [{e.get('origem', '')}]")
    if txt_confronto:
        linhas += ["", txt_confronto]
    if txt_checklist:
        linhas += ["", txt_checklist]
    return "\n".join(linhas)


# --- ANÁLISE, AGENTES E CONSOLIDAÇÃO ------------------------------------------------------------

def analisar(modelo, texto_material, uso):
    return chamar_json(modelo, [{"role": "system", "content": PROMPT_ANALISE},
                                {"role": "user", "content": texto_material}],
                       24000, etapa="análise de riscos", uso_lista=uso, chave="riscos") or {}


def revisar_por_agentes(modelo, texto_material, analise, uso, modelos=None):
    """Os seis agentes (cinco olhares e o advogado do diabo), em paralelo e sem ver as respostas uns dos outros.
    modelos: um por agente (ver config.esquema_de_modelos); sem a lista, todos usam `modelo`."""
    pedido = texto_material + "\n\nANÁLISE A REVISAR:\n" + json.dumps(analise, ensure_ascii=False, indent=1)
    modelos = modelos or [modelo] * len(PAPEIS)

    def um(papel, modelo_agente):
        _, nome, criterio = papel
        sistema = PROMPT_CONTRA if nome == PAPEL_CONTRA else PROMPT_AGENTE.format(
            papel=nome, criterio=criterio, esquema=ESQUEMA_RISCO)
        mensagens = mensagens_compartilhadas(modelo_agente, sistema, pedido)
        try:
            r = chamar_json(modelo_agente, mensagens, 16000, etapa=f"agente: {nome}", uso_lista=uso)
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
            r = chamar_json(modelo, mensagens_compartilhadas(modelo, sistema, pedido), 16000,
                            etapa=f"agente: {nome} (substituto)", uso_lista=uso)
            if not isinstance(r, dict):
                raise ValueError("resposta ilegível")
            return {"papel": nome, "modelo": modelo, "modelo_previsto": modelo_agente, "substituto": True,
                    "erro_do_previsto": erro, **r}
        except Exception as e:
            return {"papel": nome, "modelo": modelo, "modelo_previsto": modelo_agente,
                    "erro": f"{erro}; substituto: {type(e).__name__}: {e}"[:300]}
    # fora do lote, o primeiro roda sozinho e grava o material no cache; os outros cinco o leem
    return _em_paralelo([lambda p=p, m=m: um(p, m) for p, m in zip(PAPEIS, modelos)], primeiro_sozinho=not em_lote())


def _palavras(texto):
    return {w for w in re.findall(r"[a-z0-9]{3,}", _norm(texto))
            if w not in {"com", "sem", "por", "para", "dos", "das", "que", "nao", "uma", "uns", "sob", "entre"}}


def _parecido(a, b):
    """Semelhança entre dois textos curtos (Jaccard das palavras): casa o risco final com o da análise ou com o faltando."""
    pa, pb = _palavras(a), _palavras(b)
    return len(pa & pb) / len(pa | pb) if pa and pb else 0.0


def _id_na_analise(risco, analise):
    """O id do risco na análise inicial: o id_anterior que a consolidação informou, se válido, senão o risco da análise
    com título mais parecido (pelo menos metade das palavras em comum)."""
    por_id = {str(r.get("id") or ""): r for r in (analise or {}).get("riscos") or [] if isinstance(r, dict)}
    anterior = str(risco.get("id_anterior") or "").strip()
    if anterior in por_id:
        return anterior
    if anterior.lower().startswith("novo"):
        return None
    melhor = max(((_parecido(risco.get("titulo", ""), r.get("titulo", "")), i) for i, r in por_id.items()), default=(0, None))
    return melhor[1] if melhor[0] >= 0.5 else None


def proveniencia(riscos_finais, revisoes, analise, consolidado=None):
    """Para cada risco final, por código e a partir das revisões brutas: de onde veio (análise ou agente que apontou),
    quem fez objeção (exagerado ou contestado, com o motivo e a resposta da consolidação) e quantos agentes não
    objetaram. Não depende do modelo: casa os riscos pelo id informado ou pelo título."""
    validas = [r for r in revisoes or [] if not r.get("erro")]
    respostas = [x for x in (consolidado or {}).get("respostas_as_revisoes") or [] if isinstance(x, dict)]
    for risco in riscos_finais:
        anterior = _id_na_analise(risco, analise)
        objecoes, origem = [], "análise"
        if not anterior:
            apontado = max(((_parecido(risco.get("titulo", ""), f.get("titulo", "")), rev["papel"])
                            for rev in validas for f in rev.get("faltando") or [] if isinstance(f, dict)), default=(0, ""))
            texto_anterior = str(risco.get("id_anterior") or "")
            if texto_anterior.lower().startswith("novo") and ":" in texto_anterior:
                origem = "apontado por " + texto_anterior.split(":", 1)[1].strip()
            elif apontado[0] >= 0.4:
                origem = "apontado por " + apontado[1]
        for rev in validas:
            for e in rev.get("exagerados") or []:
                if isinstance(e, dict) and anterior and str(e.get("risco") or "").strip() == anterior:
                    objecoes.append({"papel": rev["papel"], "tipo": "exagerado", "motivo": str(e.get("motivo") or "").strip()})
            for c in rev.get("contestados") or []:
                if isinstance(c, dict) and anterior and str(c.get("risco") or "").strip() == anterior:
                    objecoes.append({"papel": rev["papel"], "tipo": "contestado", "motivo": str(c.get("motivo") or "").strip(),
                                     "fatos": [str(f) for f in c.get("fatos") or []]})
        for o in objecoes:
            resposta = next((x for x in respostas if str(x.get("risco") or "").strip() == anterior
                             and _parecido(str(x.get("agente") or ""), o["papel"]) >= 0.5), None)
            if resposta:
                o["resposta"] = (str(resposta.get("decisao") or "").strip()
                                 + (f" ({resposta['motivo']})" if resposta.get("motivo") else ""))
            else:
                o["resposta"] = "sem resposta registrada"
        risco["revisao"] = {"origem": origem, "objecoes": objecoes, "agentes": len(validas),
                            "sem_objecao": len(validas) - len({o["papel"] for o in objecoes}),
                            "contestado": any(o["tipo"] == "contestado" for o in objecoes)}
    return riscos_finais


def visoes_por_codigo(decisoes_finais, analise, revisoes):
    """As visões de cada agente sobre cada decisão, montadas das revisões brutas (o que cada um disse que teme e
    valoriza em cada opção), em vez da paráfrase da consolidação. A decisão final casa com a da análise pela pergunta."""
    validas = [r for r in revisoes or [] if not r.get("erro")]
    da_analise = [q for q in (analise or {}).get("decisoes") or [] if isinstance(q, dict)]
    for q in decisoes_finais:
        nota, casada = max(((_parecido(q.get("pergunta", ""), a.get("pergunta", "")), a) for a in da_analise),
                           default=(0, None), key=lambda x: x[0])
        if not casada or nota < 0.4:
            continue
        id_analise = str(casada.get("id") or "")
        nomes = [o.get("nome", "") for o in q.get("opcoes") or []]
        visoes = []
        for rev in validas:
            minhas = [d for d in rev.get("decisoes") or []
                      if isinstance(d, dict) and str(d.get("decisao") or "").strip() == id_analise]

            def junta(campo):
                partes = []
                for d in sorted(minhas, key=lambda d: d.get("opcao") or 0):
                    texto = str(d.get(campo) or "").strip()
                    if texto:
                        k = int(d.get("opcao") or 0) - 1
                        nome = nomes[k] if 0 <= k < len(nomes) else f"Opção {k + 1}"
                        partes.append(f"**{nome}:** {texto}")
                return " ".join(partes)
            teme, valoriza = junta("teme"), junta("valoriza")
            if teme or valoriza:
                visoes.append({"papel": rev["papel"], "teme": teme, "valoriza": valoriza})
        if visoes:
            q["visoes"] = visoes
    return decisoes_finais


def consolidar(modelo, texto_material, analise, revisoes, uso):
    validas = [r for r in revisoes if not r.get("erro")]
    if not validas:
        return analise
    pedido = (texto_material + "\n\nANÁLISE:\n" + json.dumps(analise, ensure_ascii=False, indent=1)
              + "\n\nREVISÕES DOS AGENTES:\n" + json.dumps(validas, ensure_ascii=False, indent=1))
    final = chamar_json(modelo, [{"role": "system", "content": PROMPT_CONSOLIDACAO},
                                 {"role": "user", "content": pedido}], 32000, etapa="consolidação dos riscos",
                        uso_lista=uso, chave="riscos")
    return final if isinstance(final, dict) and final.get("riscos") else analise


# --- CONFERÊNCIA E PRIORIDADE (código) -------------------------------------------------------------

FIRMEZA = ["confirmado em fonte oficial", "fonte pública conferida", "só na imprensa",
           "fonte pública não conferida", "informado pelo órgão", "sem comprovação"]


def _firmeza_item(item):
    if item.get("checagem") == "conferido":
        return "confirmado em fonte oficial" if item.get("tipo_fonte") in TIPOS_OFICIAIS else "fonte pública conferida"
    return "só na imprensa" if item.get("tipo_fonte") == "imprensa" else "fonte pública não conferida"


def _urgencia(dias_agir):
    return 4 if dias_agir <= 0 else 3 if dias_agir <= 30 else 2 if dias_agir <= 90 else 1


def _rotulo_prioridade(nota):
    return "Máxima" if nota >= 9 else "Alta" if nota >= 6 else "Média" if nota >= 3 else "Baixa"


def _sensibilidade(r):
    """Repercussão política da decisão (campo "sensibilidade"). Alta só com o motivo dito; sem motivo, cai para Média."""
    nivel = str(r.get("sensibilidade_politica") or "").strip().capitalize()
    nivel = {"Media": "Média"}.get(nivel, nivel)
    motivo = str(r.get("motivo_sensibilidade") or "").strip()
    if nivel not in ("Alta", "Média", "Baixa"):
        nivel = "Média" if motivo else "Baixa"
    if nivel == "Alta" and not motivo:
        nivel = "Média"
    return {"sensibilidade": nivel, "motivo_sensibilidade": motivo}


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
                    ("informado pelo órgão" if vencimentos[f].get("origem", "").startswith("Informado") else
                     "fonte pública conferida") if f in vencimentos else _firmeza_item(dossie_ids[f]) for f in validos]
        firmeza = min(firmezas, key=lambda x: FIRMEZA.index(x) if x in FIRMEZA else 99) if firmezas else "sem comprovação"
        impacto = r.get("impacto") if r.get("impacto") in IMPACTO_PONTOS else "Médio"
        ligados = [vencimentos[f] for f in validos if f in vencimentos]
        if ligados:
            nota = max(e.get("prioridade_nota") or 0 for e in ligados)
            agir = min(e["agir_ate"] for e in ligados if e.get("agir_ate"))
            prazo_de_fato = True
        else:
            prazo = str(r.get("prazo") or "")
            lida = _ler_data(prazo)
            from datetime import timedelta
            texto = _norm(prazo)
            agir = (lida[0] if lida else POSSE - timedelta(days=1) if "posse" in texto
                    else POSSE + timedelta(days=2) if "72" in texto
                    else POSSE + timedelta(days=99) if "100 dias" in texto else None)
            prazo_de_fato = bool(lida) and firmeza != "sem comprovação"
            nota = IMPACTO_PONTOS[impacto] * (_urgencia((agir - base_dia).days) if agir else 1)
        if firmeza == "sem comprovação":
            nota = min(nota, 5)
        riscos.append({**{c: str(r.get(c) or "").strip() for c in ("titulo", "causa", "consequencia", "em_jogo", "prazo",
                                                                  "em_curso", "decisao")},
                       "id_original": str(r.get("id") or f"R{k}"), "id_anterior": str(r.get("id_anterior") or "").strip(),
                       "categoria": r.get("categoria")
                       if r.get("categoria") in CATEGORIAS else "Continuidade de serviço",
                       "impacto": impacto, "chance": r.get("chance") if r.get("chance") in ("Alta", "Média", "Baixa")
                       else "Média", "fatos": validos, "fatos_invalidos": [f for f in citados if f not in validos],
                       "firmeza": firmeza, "agir_ate": agir, "nota": nota, "prioridade": _rotulo_prioridade(nota),
                       "horizonte": horizonte(agir), "prazo_de_fato": prazo_de_fato, **_sensibilidade(r)})
    riscos.sort(key=lambda r: (-r["nota"], r["agir_ate"] or date.max))
    novo_id = {r["id_original"]: f"R{k}" for k, r in enumerate(riscos, 1)}
    for r in riscos:
        r["id"] = novo_id[r["id_original"]]
    pedir = [{"o_que": str(p.get("o_que") or "").strip(),
              "serve_a": re.sub(r"\bR\d+\b", lambda m: novo_id.get(m.group(0), m.group(0)), str(p.get("serve_a") or ""))}
             for p in resultado.get("pedir") or [] if isinstance(p, dict) and str(p.get("o_que") or "").strip()][:6]
    situacao = [str(x).strip() for x in resultado.get("situacao") or [] if str(x).strip()][:5]
    return {"situacao": situacao, "riscos": riscos, "decisoes": [], "pedir": pedir}


# --- VOTAÇÃO ITEM A ITEM ---------------------------------------------------------------------------
# Depois da consolidação, os seis agentes votam, em cada risco, os três eixos da decisão: impacto, janela (quando a
# decisão precisa estar tomada, contada da posse) e sensibilidade política. Cada voto traz a justificativa e os fatos.
# O código apura: impacto e sensibilidade por maioria (empate vai para o nível mais grave), janela pela data do
# documento quando há (fato prevalece sobre opinião) e, sem data, pelo voto (empate vai para a mais urgente). A
# divergência entre agentes fica registrada.

NIVEIS_IMPACTO = ["Baixo", "Médio", "Alto"]
NIVEIS_SENS = ["Baixa", "Média", "Alta"]
JANELAS_VOTO = ["Antes da posse", "Primeiras 72 horas", "Primeiros 100 dias", "Depois dos 100 dias"]

PROMPT_VOTO = """Você vota, item a item, os riscos da transição de uma secretaria do Estado do Rio de Janeiro, com um
olhar específico. VOCÊ É: {papel}. {criterio}

Para CADA risco da lista, dê três votos, cada um com uma justificativa de uma frase que cite os ids dos fatos:
- "impacto": Alto, Médio ou Baixo. O que acontece se nada for feito: serviço à população que para, dinheiro em jogo,
  responsabilização de gestores.
- "janela": quando a decisão precisa estar tomada: "Antes da posse", "Primeiras 72 horas", "Primeiros 100 dias" ou
  "Depois dos 100 dias". A posse é em 01/01/2027.
- "sensibilidade": a REPERCUSSÃO POLÍTICA da decisão, Alta, Média ou Baixa. Toda decisão tem repercussão; diga
  qual e com que força. Na justificativa, diga QUEM REAGE E COMO (imprensa, MP, TCE, CGE, polícia, Alerj, municípios,
  servidores, sindicatos, população atendida, fornecedores). Alta quando a reação vem no primeiro dia de governo ou
  expõe o governador eleito.
Vote pelo seu olhar, sem procurar consenso. Não invente fatos.

""" + LINGUAGEM + """

Responda SOMENTE com JSON, entre [INÍCIO DO JSON] e [FIM DO JSON], com um item por risco:
{{"votos": [{{"risco": "R1", "impacto": "Alto", "por_que_impacto": "...", "janela": "Primeiras 72 horas",
"por_que_janela": "...", "sensibilidade": "Alta", "por_que_sensibilidade": "...", "fatos": ["F3"]}}]}}"""


def votar_por_agentes(modelo, texto_material, resultado, uso, modelos=None):
    """Os seis agentes votam, em paralelo e sem ver uns aos outros, cada risco final nos três eixos."""
    lista = [{"id": r["id"], "titulo": r["titulo"], "causa": r["causa"], "consequencia": r["consequencia"],
              "em_jogo": r.get("em_jogo", ""), "em_curso": r.get("em_curso", ""), "decisao": r["decisao"],
              "agir_ate": f"{r['agir_ate']:%d/%m/%Y}" if r.get("agir_ate") and r.get("prazo_de_fato") else "",
              "fatos": r["fatos"]} for r in resultado.get("riscos") or []]
    if not lista:
        return []
    pedido = texto_material + "\n\nRISCOS A VOTAR:\n" + json.dumps(lista, ensure_ascii=False, indent=1)
    modelos = modelos or [modelo] * len(PAPEIS)

    def um(papel, modelo_agente):
        _, nome, criterio = papel
        instrucoes = PROMPT_VOTO.format(papel=nome, criterio=criterio)
        for m, substituto in ((modelo_agente, False), (modelo, True)):
            if substituto and m == modelo_agente:
                break
            try:
                r = chamar_json(m, mensagens_compartilhadas(m, instrucoes, pedido), 16000, etapa=f"votação: {nome}" + (" (substituto)" if substituto else ""),
                                uso_lista=uso, chave="votos")
                if isinstance(r, dict) and isinstance(r.get("votos"), list):
                    return {"papel": nome, "modelo": m, "substituto": substituto, "votos": r["votos"]}
            except Exception as e:
                erro = f"{type(e).__name__}: {e}"[:200]
                continue
            erro = "resposta ilegível"
        return {"papel": nome, "modelo": modelo_agente, "erro": erro}
    # fora do lote, o primeiro roda sozinho e grava o material no cache; os outros cinco o leem
    return _em_paralelo([lambda p=p, m=m: um(p, m) for p, m in zip(PAPEIS, modelos)], primeiro_sozinho=not em_lote())


def _normaliza(valor, niveis):
    v = _norm(str(valor or ""))
    for n in niveis:
        if _norm(n) == v or (len(v) > 3 and _norm(n).startswith(v[:5])):
            return n
    if "72" in v:
        return "Primeiras 72 horas" if "Primeiras 72 horas" in niveis else None
    if "100" in v:
        return ("Depois dos 100 dias" if "depois" in v else "Primeiros 100 dias") if "Primeiros 100 dias" in niveis else None
    if "posse" in v:
        return "Antes da posse" if "Antes da posse" in niveis else None
    return None


def _apura(votos, niveis, grave_primeiro):
    """Maioria simples; empate vai para o nível mais grave. Devolve (nível, quantos votaram nele, total, contagem)."""
    validos = [v for v in votos if v]
    if not validos:
        return None, 0, 0, {}
    contagem = {n: validos.count(n) for n in niveis if validos.count(n)}
    maior = max(contagem.values())
    empatados = [n for n in niveis if contagem.get(n) == maior]
    nivel = empatados[-1] if grave_primeiro else empatados[0]
    return nivel, maior, len(validos), contagem


def apurar_votos(resultado, votacoes, data_corte=None):
    """Aplica os votos aos riscos, recalcula a prioridade e reordena. Fica em cada risco "votos" com a apuração dos
    três eixos e as divergências, para o relatório e o painel."""
    from datetime import timedelta
    base_dia = (_ler_data(data_corte) or (date.today(), False))[0] if data_corte else date.today()
    validas = [v for v in votacoes or [] if not v.get("erro")]
    if not validas:
        return resultado
    por_risco = {}
    for v in validas:
        for voto in v.get("votos") or []:
            if isinstance(voto, dict):
                por_risco.setdefault(str(voto.get("risco") or "").strip(), []).append((v["papel"], voto))
    data_da_janela = {"Antes da posse": POSSE - timedelta(days=1), "Primeiras 72 horas": POSSE + timedelta(days=2),
                      "Primeiros 100 dias": POSSE + timedelta(days=99), "Depois dos 100 dias": POSSE + timedelta(days=180)}
    for r in resultado.get("riscos") or []:
        votos = por_risco.get(r["id"], [])
        if not votos:
            continue
        eixos = {}
        for eixo, niveis, grave, campo in (("impacto", NIVEIS_IMPACTO, True, "por_que_impacto"),
                                           ("janela", JANELAS_VOTO, False, "por_que_janela"),
                                           ("sensibilidade", NIVEIS_SENS, True, "por_que_sensibilidade")):
            lidos = [(papel, _normaliza(voto.get(eixo), niveis), str(voto.get(campo) or "").strip()) for papel, voto in votos]
            nivel, n, total, contagem = _apura([x[1] for x in lidos], niveis, grave)
            if not nivel:
                continue
            # divergência: alguém votou dois níveis longe do resultado, ou o resultado não teve maioria de 2/3
            longe = [x for x in lidos if x[1] and abs(niveis.index(x[1]) - niveis.index(nivel)) >= 2]
            fraca = n * 3 < total * 2
            minoria = [x for x in lidos if x[1] and x[1] != nivel]
            eixos[eixo] = {"nivel": nivel, "votos": n, "total": total, "contagem": contagem,
                           "divergencia": [{"papel": x[0], "voto": x[1], "por_que": x[2]} for x in (longe or (minoria if fraca else []))],
                           "justificativas": [{"papel": x[0], "voto": x[1], "por_que": x[2]} for x in lidos if x[1]]}
        r["votos"] = eixos
        if "impacto" in eixos:
            r["impacto"] = eixos["impacto"]["nivel"]
        if "sensibilidade" in eixos:
            r["sensibilidade"] = eixos["sensibilidade"]["nivel"]
            if r["sensibilidade"] == "Alta":
                motivos = [j["por_que"] for j in eixos["sensibilidade"]["justificativas"] if j["voto"] == "Alta" and j["por_que"]]
                r["motivo_sensibilidade"] = motivos[0] if motivos else r.get("motivo_sensibilidade", "")
        if "janela" in eixos and not r.get("prazo_de_fato"):
            r["agir_ate"] = data_da_janela[eixos["janela"]["nivel"]]
            r["horizonte"] = eixos["janela"]["nivel"]
            eixos["janela"]["prevaleceu"] = "voto"
        elif "janela" in eixos:
            eixos["janela"]["prevaleceu"] = "data do documento"
        # prioridade: a maior entre a do vencimento (código) e impacto votado × urgência; sem base, no máximo Média
        nota_votada = IMPACTO_PONTOS[r["impacto"]] * (_urgencia((r["agir_ate"] - base_dia).days) if r.get("agir_ate") else 1)
        r["nota"] = max(r["nota"], nota_votada) if r.get("prazo_de_fato") else nota_votada
        if r["firmeza"] == "sem comprovação":
            r["nota"] = min(r["nota"], 5)
        r["prioridade"] = _rotulo_prioridade(r["nota"])
    # reordena e renumera, levando os vínculos das decisões e do que pedir
    riscos = resultado["riscos"]
    riscos.sort(key=lambda r: (-r["nota"], r["agir_ate"] or date.max))
    novo = {r["id"]: f"R{k}" for k, r in enumerate(riscos, 1)}
    for r in riscos:
        r["id"] = novo[r["id"]]
    for q in resultado.get("decisoes") or []:
        q["riscos"] = [novo.get(x, x) for x in q.get("riscos") or []]
    for p in resultado.get("pedir") or []:
        p["serve_a"] = re.sub(r"\bR\d+\b", lambda m: novo.get(m.group(0), m.group(0)), p.get("serve_a") or "")
    return resultado


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
    cobertura do checklist (tema sem informação derruba a confiança: alta só sem nenhum em branco). Devolve também, em
    português, o que derrubou a nota ("por_que"), para a abertura do documento."""
    criterios = []                                   # (nível, motivo técnico, motivo em português)
    pontos = []                                      # cada critério em palavras simples, com a conta
    if cobertura:
        em_branco = [c for c in cobertura if c["estado"] == "não procurado"]
        nivel = 0 if len(em_branco) > len(cobertura) / 2 else 1 if em_branco else 2
        pontos.append(f"temas básicos com informação: {len(cobertura) - len(em_branco)} de {len(cobertura)}")
        criterios.append((nivel, f"{len(cobertura) - len(em_branco)} de {len(cobertura)} temas do checklist com informação"
                          + (f" (sem informação: {', '.join(c['id'] for c in em_branco)})" if em_branco else ""),
                          f"dos {len(cobertura)} temas básicos que toda secretaria precisa ter verificados, {len(em_branco)} "
                          f"ficaram sem informação ({', '.join(c.get('tema', c['id']).lower() for c in em_branco)})"))
    if resumo_dossie and resumo_dossie.get("itens"):
        c = resumo_dossie["conferidos"] / resumo_dossie["itens"]
        pontos.append(f"fatos das fontes públicas conferidos na fonte: {resumo_dossie['conferidos']} de "
                      f"{resumo_dossie['itens']}")
        criterios.append((0 if c < 0.4 else 1 if c < 0.7 else 2,
                          f"{resumo_dossie['conferidos']} de {resumo_dossie['itens']} fatos do dossiê conferidos na fonte",
                          f"só {resumo_dossie['conferidos']} dos {resumo_dossie['itens']} fatos do dossiê puderam ser "
                          "conferidos na fonte"))
    else:
        criterios.append((0, "sem dossiê de fontes independentes", "não houve dossiê de fontes independentes"))
        pontos.append("fatos das fontes públicas conferidos na fonte: não houve dossiê")
    if riscos:
        fracos = [r for r in riscos if r["firmeza"] in ("informado pelo órgão", "sem comprovação",
                                                        "fonte pública não conferida", "só na imprensa")]
        p = len(fracos) / len(riscos)
        pontos.append(f"riscos apoiados em fonte oficial ou conferida: {len(riscos) - len(fracos)} de {len(riscos)}")
        criterios.append((0 if p > 0.6 else 1 if p > 0.3 else 2,
                          f"{len(riscos) - len(fracos)} de {len(riscos)} riscos apoiados em fonte oficial ou conferida",
                          f"{len(fracos)} dos {len(riscos)} riscos se apoiam só no que a secretaria informou ou em fonte "
                          "que não pôde ser conferida"))
    nivel = min(c[0] for c in criterios)
    por_que = [c[2] for c in criterios if c[0] == nivel] if nivel < 2 else []
    return {"nivel": ["baixa", "média", "alta"][nivel], "motivos": [c[1] for c in criterios], "por_que": por_que,
            "pontos": pontos,
            "lacuna_checklist": any(m.startswith("dos ") for m in por_que)}

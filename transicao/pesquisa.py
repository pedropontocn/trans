"""Pesquisa: o dossiê de fontes públicas (Estado e órgão), com a conferência dos links e trechos por código."""
import json
import os
import re
import tempfile
from datetime import datetime
from copy import deepcopy

from .modelo import (_comparavel, _em_paralelo, _norm, _shingles, chamar_modelo, trecho_confere, chave_guardada, extrair_json, guardar_resposta,
                     resposta_guardada)


BLOCOS_ESTADO = {
    "situacao_fiscal": "Situação fiscal: receita e despesa por grupo, pessoal e previdência, dívida, restos a pagar, "
                       "receitas voláteis (royalties). Partir de PLOA/LOA, LDO, RREO e RGF, Siconfi e do parecer prévio "
                       "do TCE-RJ sobre as contas do governador.",
    "regime_divida": "Regime da dívida: termos do Propag, contrapartidas, o que mudou desde a saída do Regime de "
                     "Recuperação Fiscal. Partir do termo de adesão, do Relatório de Conclusão do RRF e da STN.",
    "previdencia": "Previdência: déficit, aportes do Tesouro, projeção atuarial. Partir do RioPrevidência e da "
                   "avaliação atuarial anual.",
    "calendario_legal": "Calendário legal: prazos de LOA, emendas e votações na Alerj, programação financeira "
                        "(LRF art. 8), limitação de empenho (LRF art. 9), fim de mandato (LRF art. 42).",
    "cenario_politico": "Cenário político: governo em exercício e governo eleito, composição e presidência da Alerj, "
                        "decisões do STF e de tribunais que afetam o Estado.",
    "compromissos_governo": "Compromissos do governo eleito: promessas e anúncios com data. São intenção declarada, "
                            "nunca fato documental.",
}


BLOCOS_ORGAO = {
    "mandato_estrutura": "Mandato e estrutura: competências legais, unidades, órgãos vinculados. Partir da lei e do "
                         "decreto de estrutura.",
    "orcamento_execucao": "Orçamento e execução: dotação, empenhado, liquidado e pago nos dois últimos anos, restos a "
                          "pagar. Partir da LOA por unidade orçamentária e do Portal da Transparência.",
    "pessoal": "Pessoal: efetivos, comissionados, cedidos, terceirizados, aposentadorias previstas.",
    "contratos_convenios": "Contratos e convênios: os maiores por valor, vencimentos próximos, os que sustentam "
                           "serviço direto. Partir do portal de compras, do Diário Oficial e das transferências federais.",
    "entregas_indicadores": "Entregas e indicadores: o que o órgão entrega e como isso é medido por fonte externa.",
    "controle_judicializacao": "Controle e judicialização: apontamentos do TCE-RJ e da CGE, ações do MPRJ, decisões "
                               "judiciais em vigor.",
    "riscos_continuidade": "Riscos de continuidade: sistemas críticos, contratos vencendo, prazos legais nos primeiros "
                           "100 dias de governo.",
}


BLOCOS = {**BLOCOS_ESTADO, **BLOCOS_ORGAO}


OPCOES_BLOCO = list(BLOCOS_ESTADO) + ["outro_estado"] + list(BLOCOS_ORGAO) + ["outro_orgao"]


TIPOS_FONTE = {"documento_oficial": "Documento oficial", "dado_oficial": "Dado oficial",
               "decisao_controle_judicial": "Decisão de controle ou judicial", "estudo": "Estudo",
               "imprensa": "Imprensa", "declaracao_politica": "Declaração política", "hipotese": "Hipótese"}


CONFIANCAS = ["alta", "media", "baixa"]


CHECAGENS = {"conferido": "conferido", "trecho_nao_encontrado": "trecho não encontrado",
             "inacessivel": "página inacessível", "sem_trecho": "sem trecho", "nao_conferido": "não conferido"}


PROMPT_PESQUISA = """Você é pesquisador da Equipe de Transição do governo do Estado do Rio de Janeiro. Monte a camada
"<<<CAMADA>>>" do dossiê que servirá de base factual para um mapa de tensões. Data de corte: <<<DATA>>>.
<<<ALVO>>>

Use a busca na web. Em cada bloco, procure primeiro documentos oficiais (Diário Oficial, Alerj, TCE-RJ, portais de
transparência, Tesouro Nacional, órgãos federais) e só depois imprensa.

BLOCOS (use exatamente estes nomes no campo "bloco"):
<<<BLOCOS>>>

Regras:
- Cada item é UMA afirmação verificável, com número, data ou fato concreto. Nada de opinião ou análise.
- "url": o endereço exato da página ou do documento onde a afirmação está. Não invente endereços: sem o endereço,
  não inclua o item.
- "trecho": cópia LITERAL de até 40 palavras dessa página, sem parafrasear. O sistema abre a página e confere.
- "data_fonte": data do documento (dd/mm/aaaa, mm/aaaa ou aaaa).
- "tipo_fonte": documento_oficial, dado_oficial, decisao_controle_judicial, estudo, imprensa, declaracao_politica
  ou hipotese. Promessa, anúncio ou plano de governo é declaracao_politica, nunca documento_oficial.
- "confianca": alta (fonte oficial que diz exatamente isso), media (fonte confiável, mas indireta ou desatualizada),
  baixa (imprensa sem documento ou dado provisório).
- Cite pessoas só pelo cargo público, quando for indispensável. Não inclua dados pessoais.
- Em "nao_encontrado", liste por bloco o que você procurou e não achou em fonte confiável. Isso é tão importante
  quanto o que achou: evita pedir ao decisor um dado que já é público, ou tratar como público o que não é.
- No máximo 6 itens por bloco.

Responda SOMENTE com JSON entre [INÍCIO DO JSON] e [FIM DO JSON]:
{"itens": [{"bloco": "...", "afirmacao": "...", "fonte": "documento e órgão emissor", "data_fonte": "...",
"url": "https://...", "trecho": "...", "tipo_fonte": "...", "confianca": "alta|media|baixa"}],
"nao_encontrado": [{"bloco": "...", "procurado": "..."}]}"""


LIMITE_PAGINA = 8_000_000


TEMPO_PAGINA = 12


TIPOS_OFICIAIS = {"documento_oficial", "dado_oficial", "decisao_controle_judicial"}


def _id_item(camada, n):
    return ("E" if camada == "estado" else "O") + str(n)


def normalizar_item(bruto, camada=None):
    """Põe um item do dossiê no formato do app. Devolve None se não tiver afirmação."""
    if not isinstance(bruto, dict):
        return None
    afirmacao = str(bruto.get("afirmacao") or "").strip()
    if not afirmacao:
        return None
    bloco = re.sub(r"[^a-z_]", "", _norm(bruto.get("bloco")).replace(" ", "_"))
    if camada is None:
        camada = bruto.get("camada") if bruto.get("camada") in ("estado", "orgao") else (
            "estado" if bloco in BLOCOS_ESTADO else "orgao")
    tipo = bruto.get("tipo_fonte") if bruto.get("tipo_fonte") in TIPOS_FONTE else "hipotese"
    confianca = _norm(bruto.get("confianca"))
    url = str(bruto.get("url") or "").strip()
    return {"id": str(bruto.get("id") or "").strip(), "camada": camada,
            "bloco": bloco if bloco in BLOCOS else ("outro_estado" if camada == "estado" else "outro_orgao"),
            "afirmacao": afirmacao, "fonte": str(bruto.get("fonte") or "").strip(),
            "data_fonte": str(bruto.get("data_fonte") or "").strip(),
            "url": url if re.match(r"^https?://", url) else "",
            "trecho": str(bruto.get("trecho") or "").strip(),
            "tipo_fonte": tipo, "confianca": confianca if confianca in CONFIANCAS else "baixa",
            "checagem": bruto.get("checagem") if bruto.get("checagem") in CHECAGENS else "nao_conferido",
            "conferido_pela_equipe": bool(bruto.get("conferido_pela_equipe")),
            "incluir": bruto.get("incluir", True) is not False}


def numerar_itens(itens, reservados=()):
    """Dá id aos itens que não têm (E1, E2... para o Estado; O1, O2... para o órgão), sem repetir ids.
    reservados: ids que já existiram (por exemplo, de linhas apagadas) e não podem ser reusados."""
    usados = {i["id"] for i in itens if re.fullmatch(r"[EO]\d+", i["id"] or "")} | set(reservados)
    contadores = {"estado": 0, "orgao": 0}
    vistos = set()
    for i in itens:
        if i["id"] in vistos or not re.fullmatch(r"[EO]\d+", i["id"] or "") or i["id"][0] != _id_item(i["camada"], 0)[0]:
            while True:
                contadores[i["camada"]] += 1
                novo = _id_item(i["camada"], contadores[i["camada"]])
                if novo not in usados:
                    break
            i["id"] = novo
            usados.add(novo)
        vistos.add(i["id"])
    return itens


def nivel_maximo(item):
    """O nível de evidência mais forte que um item do dossiê pode sustentar, por regra explícita."""
    conferido = item.get("checagem") == "conferido" or item.get("conferido_pela_equipe")
    tipo = item.get("tipo_fonte")
    if tipo in TIPOS_OFICIAIS:
        return 1 if conferido else 3
    if tipo == "estudo":
        return 2 if conferido else 3
    if tipo in ("imprensa", "declaracao_politica"):
        return 3
    return 4


def _html_para_texto(html):
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    import html as html_lib
    return re.sub(r"\s+", " ", html_lib.unescape(html))


def baixar_pagina(url):
    """Baixa a página e devolve o texto, ou None se não conseguir. PDF passa pelo MarkItDown."""
    import ipaddress
    import urllib.parse
    import urllib.request
    # Os links vêm da pesquisa: o painel não abre endereços locais ou de rede interna do servidor.
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    if not host or host == "localhost" or host.endswith((".local", ".internal")):
        return None
    try:
        if not ipaddress.ip_address(host).is_global:
            return None
    except ValueError:
        pass                                      # é um nome, não um IP
    try:
        pedido = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (PainelTransicao/2.0; conferencia de fontes)"})
        with urllib.request.urlopen(pedido, timeout=TEMPO_PAGINA) as resp:
            tipo = (resp.headers.get("Content-Type") or "").lower()
            dados = resp.read(LIMITE_PAGINA)
    except Exception:
        return None
    if "pdf" in tipo or dados[:5] == b"%PDF-":
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(dados)
                caminho = tmp.name
            try:
                from markitdown import MarkItDown
                return MarkItDown().convert(caminho).text_content
            finally:
                os.remove(caminho)
        except Exception:
            return None
    m = re.search(r"charset=([\w-]+)", tipo)
    try:
        texto = dados.decode(m.group(1) if m else "utf-8", errors="replace")
    except LookupError:
        texto = dados.decode("utf-8", errors="replace")
    return _html_para_texto(texto) if "html" in tipo or "<html" in texto[:2000].lower() else texto


def conferir_itens(itens):
    """Abre o link de cada item e procura o trecho citado. Feito por código; o modelo não participa."""
    urls = sorted({i["url"] for i in itens if i["url"] and i["trecho"]})
    paginas = dict(zip(urls, _em_paralelo([lambda u=u: baixar_pagina(u) for u in urls]))) if urls else {}
    bases = {}
    for i in itens:
        if not i["url"] or not i["trecho"]:
            i["checagem"] = "sem_trecho"
            continue
        texto = paginas.get(i["url"])
        if not texto:
            i["checagem"] = "inacessivel"
            continue
        if i["url"] not in bases:
            comp = _comparavel(texto)
            bases[i["url"]] = (comp, _shingles(comp.split()))
        i["checagem"] = "conferido" if trecho_confere(i["trecho"], *bases[i["url"]]) else "trecho_nao_encontrado"
    return itens


# A pesquisa é dividida em grupos pequenos de blocos, rodando em paralelo: cada chamada faz menos buscas e devolve
# um JSON menor. Isso reduz respostas cortadas e turnos pausados pela API (a Anthropic pausa turnos longos com busca
# e devolve "pause_turn", que o LiteLLM entrega como se a resposta tivesse terminado).
GRUPOS_PESQUISA = [
    ("estado", ["situacao_fiscal", "regime_divida", "previdencia"]),
    ("estado", ["calendario_legal", "cenario_politico", "compromissos_governo"]),
    ("orgao", ["mandato_estrutura", "orcamento_execucao", "pessoal"]),
    ("orgao", ["contratos_convenios", "entregas_indicadores"]),
    ("orgao", ["controle_judicializacao", "riscos_continuidade"]),
]


SEM_JSON = "a resposta não trouxe o JSON do dossiê"


PEDIDO_CONTINUACAO = ("Você parou antes de entregar o resultado. Entregue agora SOMENTE o JSON pedido, entre "
                      "[INÍCIO DO JSON] e [FIM DO JSON], com o que já encontrou. Faça novas buscas só se faltar um "
                      "bloco inteiro.")


def _itens_da_resposta(texto, camada, blocos):
    dados = extrair_json(texto)
    if not isinstance(dados, dict) or not isinstance(dados.get("itens"), list):
        return None, []
    itens = [x for x in (normalizar_item(b, camada) for b in dados["itens"]) if x]
    for i in itens:
        if i["bloco"] not in blocos:
            i["bloco"] = "outro_estado" if camada == "estado" else "outro_orgao"
    nao = [{"camada": camada, "bloco": str(n.get("bloco", "")), "procurado": str(n.get("procurado", "")).strip()}
           for n in (dados.get("nao_encontrado") or []) if isinstance(n, dict) and str(n.get("procurado", "")).strip()]
    return itens, nao


def pesquisar_grupo(modelo, camada, blocos, orgao, data_corte, foco=""):
    """Um grupo de blocos do dossiê, com busca na web. Nunca levanta exceção: devolve (itens, não encontrados, uso,
    diagnóstico), e o diagnóstico diz o que aconteceu (erro, resposta sem JSON, resposta cortada, continuação)."""
    descricoes = BLOCOS_ESTADO if camada == "estado" else BLOCOS_ORGAO
    alvo = ("Alvo: o Estado do Rio de Janeiro como um todo, no contexto da transição de governo."
            if camada == "estado" else f"Alvo: o órgão {orgao}, do Governo do Estado do Rio de Janeiro.")
    if foco:
        alvo += f"\nFoco indicado pela equipe (use para priorizar a busca, não como fato): {foco}"
    prompt = (PROMPT_PESQUISA.replace("<<<CAMADA>>>", "Estado" if camada == "estado" else "órgão")
              .replace("<<<DATA>>>", data_corte).replace("<<<ALVO>>>", alvo)
              .replace("<<<BLOCOS>>>", "\n".join(f"- {b}: {descricoes[b]}" for b in blocos)))
    uso, diag = [], {"camada": camada, "blocos": blocos, "erro": None, "motivo": None, "continuacao": False,
                     "itens": 0, "resposta": ""}
    mensagens = [{"role": "user", "content": prompt}]
    etapa = f"pesquisa · {camada} · {', '.join(blocos)}"
    try:
        texto, _, motivo = chamar_modelo(modelo, mensagens, 16000, etapa=etapa, uso_lista=uso, busca_web="medium")
        diag["motivo"] = motivo
        itens, nao = _itens_da_resposta(texto, camada, blocos)
        if itens is None:
            # sem JSON: turno pausado, resposta cortada ou o modelo só narrou a busca. Pede para terminar.
            diag["continuacao"] = True
            texto2, _, motivo2 = chamar_modelo(
                modelo, mensagens + [{"role": "assistant", "content": texto or "(sem texto)"},
                                     {"role": "user", "content": PEDIDO_CONTINUACAO}],
                16000, etapa=etapa + " (continuação)", uso_lista=uso, busca_web="low")
            diag["motivo"] = f"{motivo} → {motivo2}"
            texto = (texto or "") + "\n\n--- continuação ---\n\n" + (texto2 or "")
            itens, nao = _itens_da_resposta(texto2, camada, blocos)
        if itens is None:
            itens, nao = [], []
            diag["erro"] = SEM_JSON
        if diag["motivo"] and "length" in str(diag["motivo"]):
            nao.append({"camada": camada, "bloco": "", "procurado": f"resposta cortada em {', '.join(blocos)}; pode faltar item"})
        diag["itens"], diag["resposta"] = len(itens), (texto or "")[:3000]
        return itens, nao, uso, diag
    except Exception as e:
        diag["erro"] = f"{type(e).__name__}: {e}"[:600]
        return [], [], uso, diag


def montar_dossie(modelo, orgao, data_corte, foco="", reaproveitar=True, estado=None):
    """Pesquisa os grupos em paralelo, numera os itens e confere os links por código.

    estado: a camada do Estado já pesquisada (o que pesquisar_estado devolve). Ela é igual para todos os órgãos; com
    ela, só a camada do órgão é pesquisada, e os itens do Estado entram como estão, sem nova busca nem nova conferência.
    Se todos os grupos pesquisados falharem com erro, levanta RuntimeError com as mensagens."""
    grupos = [g for g in GRUPOS_PESQUISA if estado is None or g[0] == "orgao"]
    chave = chave_guardada("dossiê", modelo, PROMPT_PESQUISA, grupos, orgao, data_corte, foco,
                           (estado or {}).get("assinatura"))
    guardada = resposta_guardada(chave) if reaproveitar else None
    if guardada:
        dossie = deepcopy(guardada)
        dossie["reaproveitado"] = True
        return dossie
    resultados = _em_paralelo([lambda c=c, b=b: pesquisar_grupo(modelo, c, b, orgao, data_corte, foco) for c, b in grupos])
    itens, nao, uso, diagnostico = [], [], [], []
    for it, n, u, d in resultados:
        itens += it
        nao += n
        uso += u
        diagnostico.append(d)
    # todos os grupos deram erro na chamada (chave, modelo, parâmetro): não há dossiê a montar
    if not itens and all(d["erro"] and d["erro"] != SEM_JSON for d in diagnostico):
        raise RuntimeError("todas as buscas falharam: " + " | ".join(sorted({d["erro"] for d in diagnostico})))
    novos = conferir_itens(_unicos_ordenados(itens))
    if estado is not None:
        # itens do Estado já conferidos; perdem o id para a numeração ficar contínua neste dossiê
        itens = [dict(i, id="") for i in deepcopy(estado["itens"])] + [dict(i, id="") for i in novos]
        nao = deepcopy(estado["nao_encontrado"]) + nao
        diagnostico = [dict(d, compartilhado=True) for d in deepcopy(estado["diagnostico"])] + diagnostico
    else:
        itens = novos
    dossie = {"orgao": orgao, "data_corte": data_corte, "foco": foco, "modelo": modelo, "origem": "pesquisa",
              "gerado_em": datetime.now().isoformat(timespec="seconds"),
              "itens": numerar_itens(_unicos_ordenados(itens)), "nao_encontrado": nao, "uso": uso,
              "diagnostico": diagnostico, "reaproveitado": False, "estado_compartilhado": estado is not None}
    if dossie["itens"]:
        guardar_resposta(chave, deepcopy(dossie))
    return dossie


def _unicos_ordenados(itens):
    """Tira repetidos (mesmo link e mesma afirmação) e ordena: Estado antes do órgão e, dentro de cada camada, a ordem
    fixa dos blocos, para os ids não dependerem da ordem em que as respostas chegam."""
    vistos, unicos = set(), []
    for i in itens:
        chave_item = (i["url"], _comparavel(i["afirmacao"])[:120])
        if chave_item not in vistos:
            vistos.add(chave_item)
            unicos.append(i)
    ordem = {b: k for k, b in enumerate(OPCOES_BLOCO)}
    unicos.sort(key=lambda i: (i["camada"] != "estado", ordem.get(i["bloco"], len(ordem))))
    return unicos


def pesquisar_estado(modelo, data_corte, foco=""):
    """A camada do Estado, pesquisada uma vez para ser usada em vários órgãos (processamento em lote)."""
    grupos = [g for g in GRUPOS_PESQUISA if g[0] == "estado"]
    resultados = _em_paralelo([lambda b=b: pesquisar_grupo(modelo, "estado", b, "", data_corte, foco) for _, b in grupos])
    itens, nao, uso, diagnostico = [], [], [], []
    for it, n, u, d in resultados:
        itens += it
        nao += n
        uso += u
        diagnostico.append(d)
    if not itens and all(d["erro"] and d["erro"] != SEM_JSON for d in diagnostico):
        raise RuntimeError("todas as buscas falharam: " + " | ".join(sorted({d["erro"] for d in diagnostico})))
    itens = conferir_itens(numerar_itens(_unicos_ordenados(itens)))
    return {"itens": itens, "nao_encontrado": nao, "uso": uso, "diagnostico": diagnostico, "modelo": modelo,
            "data_corte": data_corte, "assinatura": chave_guardada("estado", modelo, data_corte, foco,
                                                                   datetime.now().isoformat(timespec="seconds"))}



def itens_incluidos(dossie):
    return [i for i in (dossie or {}).get("itens", []) if i.get("incluir", True)]


def linha_item(i):
    conferencia = "conferido pela equipe" if i.get("conferido_pela_equipe") else CHECAGENS.get(i["checagem"], i["checagem"])
    return (f"[{i['id']}] ({i['bloco']}) {i['afirmacao']} — fonte: {i['fonte'] or 'não informada'}"
            f"{', ' + i['data_fonte'] if i['data_fonte'] else ''}; {TIPOS_FONTE[i['tipo_fonte']].lower()}; "
            f"confiança {i['confianca']}; {conferencia}; nível máximo {nivel_maximo(i)}"
            + (f"; trecho: “{i['trecho']}”" if i["trecho"] else ""))


def texto_dossie(dossie):
    """O dossiê como texto, para os prompts e para a conferência dos números."""
    itens = itens_incluidos(dossie)
    if not itens:
        return ""
    partes = [f"DOSSIÊ — órgão: {dossie.get('orgao') or '—'}; data de corte: {dossie.get('data_corte') or '—'}"]
    for camada, titulo in (("estado", "ESTADO"), ("orgao", "ÓRGÃO")):
        linhas = [linha_item(i) for i in itens if i["camada"] == camada]
        if linhas:
            partes.append(f"{titulo}:\n" + "\n".join(linhas))
    nao = [n for n in dossie.get("nao_encontrado") or [] if n.get("procurado")]
    if nao:
        partes.append("PROCURADO E NÃO ENCONTRADO EM FONTE CONFIÁVEL:\n"
                      + "\n".join(f"- ({n.get('bloco') or '—'}) {n['procurado']}" for n in nao))
    return "\n\n".join(partes)


def material_referencia(dossie, relatorio):
    """O começo comum das mensagens do debate: dossiê e, se houver, a autodeclaração do órgão."""
    blocos = [f"<dossie>\n{texto_dossie(dossie)}\n</dossie>"]
    if relatorio:
        blocos.append(f"<relatorio>\nAUTODECLARAÇÃO DO ÓRGÃO (relatório de transição enviado pela pasta)\n\n{relatorio}\n</relatorio>")
    return "\n\n".join(blocos)


def resumo_dossie(dossie):
    itens = itens_incluidos(dossie)
    conferidos = [i for i in itens if i["checagem"] == "conferido" or i.get("conferido_pela_equipe")]
    oficiais = [i for i in itens if i["tipo_fonte"] in TIPOS_OFICIAIS]
    return {"itens": len(itens), "conferidos": len(conferidos), "oficiais": len(oficiais),
            "estado": sum(i["camada"] == "estado" for i in itens), "orgao": sum(i["camada"] == "orgao" for i in itens),
            "nao_encontrado": len([n for n in (dossie or {}).get("nao_encontrado") or [] if n.get("procurado")])}


def dossie_para_json(dossie):
    campos = ("orgao", "data_corte", "foco", "modelo", "origem", "gerado_em", "itens", "nao_encontrado", "diagnostico")
    return json.dumps({k: dossie.get(k) for k in campos}, ensure_ascii=False, indent=2)


# --- DOSSIÊ ENVIADO (montado fora do app, por exemplo no Perplexity) ------------------------------

RE_CAMPO = re.compile(r"^\s*(?:[-*•]\s*)?\**\s*(afirma[çc][ãa]o|tema|fonte|data(?: da fonte)?|link|url|"
                      r"trecho(?: literal)?|tipo(?: de fonte)?)\s*\**\s*:\s*\**\s*(.*)$", re.I)
RE_NAO_ENCONTRADO = re.compile(r"^\s*#*\s*\**\s*procurad[oa]s?\b.*n[ãa]o encontrad", re.I)
TEMAS = [  # palavras do tema → bloco do dossiê
    (r"fiscal|d[ée]ficit|receita|royalt", "situacao_fiscal"), (r"d[íi]vida|propag|recupera[çc][ãa]o fiscal", "regime_divida"),
    (r"previd", "previdencia"), (r"alerj|loa\b|ldo\b|calend[áa]rio legal", "calendario_legal"),
    (r"pol[íi]tic", "cenario_politico"), (r"compromisso|promessa|governo eleito", "compromissos_governo"),
    (r"miss[ãa]o|estrutura|compet[êe]ncia|mandato", "mandato_estrutura"),
    (r"or[çc]amento|execu[çc][ãa]o|empenh|dota[çc]", "orcamento_execucao"), (r"pessoal|servidor|cargo", "pessoal"),
    (r"contrato|conv[êe]nio|licita", "contratos_convenios"), (r"entrega|indicador|resultado", "entregas_indicadores"),
    (r"controle|tce|mp\b|mprj|judic|cge", "controle_judicializacao"),
    (r"risco|continuidade|prazo|vencimento", "riscos_continuidade"),
]
TIPOS = [(r"decis|controle|judicial", "decisao_controle_judicial"), (r"dado", "dado_oficial"),
         (r"documento|oficial|di[áa]rio|lei|decreto", "documento_oficial"), (r"estudo|pesquisa|acad", "estudo"),
         (r"imprensa|jornal|not[íi]cia|mat[ée]ria", "imprensa"), (r"declara|pol[íi]tic|promessa", "declaracao_politica")]


def _classificar(texto, regras, padrao):
    texto = _norm(texto)
    return next((valor for padrao_re, valor in regras if re.search(padrao_re, texto)), padrao)


def ler_dossie_enviado(texto):
    """Lê os fatos de um dossiê em texto (blocos com Afirmação, Tema, Fonte, Data, Link, Trecho literal e Tipo).
    Devolve (itens brutos, procurados e não encontrados). Cada novo "Afirmação:" abre um fato."""
    fatos, nao, atual, campo, na_lista = [], [], None, None, False
    for linha in (texto or "").splitlines():
        if RE_NAO_ENCONTRADO.search(linha):
            na_lista, atual, campo = True, None, None
            continue
        m = RE_CAMPO.match(linha)
        if na_lista and not m:
            item = re.sub(r"^\s*[-*•\d.)]+\s*", "", linha).strip(" *")
            if item and not item.startswith("#"):
                nao.append(item)
            continue
        if m:
            na_lista = False
            nome = _norm(m.group(1)).split()[0]
            nome = {"url": "link", "afirmacao": "afirmacao"}.get(nome, nome)
            valor = m.group(2).strip().strip("*").strip()
            if nome == "afirmacao":
                atual = {}
                fatos.append(atual)
            if atual is not None:
                atual[nome] = valor
                campo = nome
        elif atual is not None and campo in ("afirmacao", "trecho") and linha.strip() and not linha.lstrip().startswith("#"):
            atual[campo] += " " + linha.strip()          # texto que continuou na linha de baixo
        elif not linha.strip() or linha.lstrip().startswith("#"):
            campo = None
    itens = []
    for f in fatos:
        bloco = (_classificar(f.get("tema", ""), TEMAS, "") or _classificar(f.get("afirmacao", ""), TEMAS, "outro_orgao"))
        tipo = _classificar(f.get("tipo", ""), TIPOS, "hipotese")
        url = re.search(r"https?://[^\s)\]>\"']+", f.get("link", ""))
        itens.append({"bloco": bloco, "camada": "estado" if bloco in BLOCOS_ESTADO else "orgao",
                      "afirmacao": f.get("afirmacao", ""), "fonte": f.get("fonte", ""), "data_fonte": f.get("data", ""),
                      "url": url.group(0).rstrip(".,;") if url else "",
                      "trecho": f.get("trecho", "").strip().strip('"“”'),
                      "tipo_fonte": tipo,
                      "confianca": "alta" if tipo in ("documento_oficial", "dado_oficial", "decisao_controle_judicial")
                      else "media" if tipo in ("estudo", "imprensa") else "baixa"})
    return itens, nao


def dossie_enviado(texto, orgao, data_corte):
    """O dossiê a partir de um arquivo enviado pela equipe, no lugar da pesquisa do app. O código abre cada link e
    procura o trecho literal, como faz com a pesquisa; itens sem link ou sem trecho ficam como não conferidos."""
    brutos, nao = ler_dossie_enviado(texto)
    itens = [x for x in (normalizar_item(b) for b in brutos) if x]
    itens = numerar_itens(conferir_itens(_unicos_ordenados(itens)))
    return {"orgao": orgao, "data_corte": data_corte, "foco": "", "modelo": "dossiê enviado pela equipe",
            "origem": "arquivo", "gerado_em": datetime.now().isoformat(timespec="seconds"), "itens": itens,
            "nao_encontrado": [{"camada": "orgao", "bloco": "", "procurado": n} for n in nao], "uso": [],
            "diagnostico": [], "reaproveitado": False, "estado_compartilhado": False}

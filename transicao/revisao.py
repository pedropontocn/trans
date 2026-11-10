"""Revisão do texto final, antes de montar os documentos.

Três camadas, nesta ordem:
1. Código: acha as palavras de recomendação ("deve", "recomenda-se", "cabe a"...), a atribuição de responsável e o
   texto cortado no meio. É determinístico e não custa nada.
2. Modelo: reescreve cada campo do resultado (situação, riscos, informações que faltam) no tom de análise: descreve,
   não recomenda, não sugere caminho, não diz quem deve fazer. Recebe como pista o que o código e a revisão de
   neutralidade apontaram.
3. Código, de novo: só aceita a reescrita que preserva todos os números, datas e referências (F1, V2, O3, C5, R1) e
   que não traz palavra proibida. O que não passa fica como estava e vai para o registro de auditoria.
"""
import json
import re

from .modelo import chamar_json

# palavras e construções que recomendam, prescrevem ou atribuem responsável
PROIBIDAS = [
    r"\bdeve(?:m|ria|riam|rá|rão)?\b", r"\bé preciso\b", r"\bé necessári[oa]\b", r"\bfaz-se necessári[oa]\b",
    r"\brecomenda(?:-se|mos|do|da|ção|ções)?\b", r"\bsugere-se\b", r"\bsugerimos\b", r"\bsugest(?:ão|ões)\b",
    r"\bconvém\b", r"\bo ideal\b", r"\bidealmente\b", r"\bcabe (?:a|à|ao|aos|às)\b", r"\bcaberá\b",
    r"\bé importante que\b", r"\bé fundamental que\b", r"\bé essencial que\b", r"\bé recomendável\b",
    r"\bprecisa(?:m)? (?:ser|ter|fazer|decidir|definir|garantir|avaliar)\b", r"\bnecessita(?:m)?\b",
    r"\bresponsável (?:deve|por decidir|pela decisão)\b", r"\bquem decide\b", r"\ba melhor (?:saída|opção|alternativa)\b",
    r"\bvale a pena\b", r"\bproponho\b", r"\bpropõe-se\b",
]
RE_PROIBIDAS = re.compile("|".join(PROIBIDAS), re.I)
RE_NUMEROS = re.compile(r"\d+(?:[.,/]\d+)*")
RE_REFS = re.compile(r"\b[FVOCRQ]\d{1,3}\b")
RE_CORTE = re.compile(r"…|\.\.\.\s*$")
# repercussão política: reação que ainda não ocorreu não é fato; e o documento não diz quem fica exposto
RE_REACAO_AFIRMADA = re.compile(r"\b(reage|reagem|reagirá|reagirão|expõe|expõem|exporá|exporão)\b", re.I)
_EXPOE = (r"(?:pode[m]? expor|exp[õo]e[m]?|expor[áã]o?)\s+(?:diretamente\s+)?(?:o|a)\s+"
          r"(?:novo governo|governador eleito|nova gestão|governador)\b")
RE_EXPOE_ORACAO = re.compile(r",\s*[^,.;()]*?" + _EXPOE + r"[^.;(]*?(?=\s*[.;(]|$)", re.I)   # a oração, desde a vírgula
RE_EXPOE_GOVERNO = re.compile(_EXPOE + r"[^.;(]*?(?=\s*[.;(]|$)", re.I)
_CONDICIONAL = {"reage": "pode reagir", "reagem": "podem reagir", "reagirá": "pode reagir", "reagirão": "podem reagir",
                "expõe": "pode expor", "expõem": "podem expor", "exporá": "pode expor", "exporão": "podem expor"}


def condicional(texto):
    """A repercussão no condicional, por código: tira "expõe o governador/novo governo" e troca a reação afirmada
    ("reagem") pela possível ("podem reagir"). Não muda número, nome nem data."""
    texto = RE_EXPOE_ORACAO.sub("", str(texto or ""))
    texto = RE_EXPOE_GOVERNO.sub("pode gerar repercussão política", texto)   # sem vírgula antes: fica a frase

    def troca(m):
        novo = _CONDICIONAL[m.group(0).lower()]
        return novo.capitalize() if m.group(0)[0].isupper() else novo
    texto = RE_REACAO_AFIRMADA.sub(troca, texto)
    return re.sub(r"\s+([.,;])", r"\1", re.sub(r"\s{2,}", " ", texto)).strip(" ,;")


def alertas(texto):
    """O que o código acha num texto: recomendação, corte no meio e parêntese aberto."""
    texto = str(texto or "")
    achados = [f"recomendação: \"{m.group(0)}\"" for m in RE_PROIBIDAS.finditer(texto)]
    if RE_CORTE.search(texto):
        achados.append("texto cortado")
    if texto.count("(") != texto.count(")"):
        achados.append("parêntese sem fechar")
    return achados


def campos(resultado):
    """Os textos do resultado que vão para os documentos, cada um com uma chave estável."""
    saida = {}
    for k, s in enumerate(resultado.get("situacao") or []):
        saida[f"situacao.{k}"] = s
    for r in resultado.get("riscos") or []:
        for campo in ("titulo", "causa", "consequencia", "decisao", "motivo_sensibilidade", "em_curso"):
            if str(r.get(campo) or "").strip():
                saida[f"{r['id']}.{campo}"] = r[campo]
    for k, p in enumerate(resultado.get("pedir") or []):
        saida[f"pedir.{k}"] = p["o_que"]
    return saida


def _gravar(resultado, chave, texto):
    alvo, campo = chave.split(".", 1)
    if alvo == "situacao":
        resultado["situacao"][int(campo)] = texto
    elif alvo == "pedir":
        resultado["pedir"][int(campo)]["o_que"] = texto
    else:
        next(r for r in resultado["riscos"] if r["id"] == alvo)[campo] = texto


def _assinatura(texto):
    return sorted(RE_NUMEROS.findall(texto or "")), sorted(set(RE_REFS.findall(texto or "")))


def aceitar(antes, depois):
    """A reescrita vale? Devolve o motivo da recusa, ou "" se vale."""
    depois = str(depois or "").strip()
    if not depois:
        return "veio vazia"
    if _assinatura(antes) != _assinatura(depois):
        return "mudou número, data ou referência"
    if RE_PROIBIDAS.search(depois):
        return "manteve palavra de recomendação"
    if len(depois) > max(len(antes) * 1.25, len(antes) + 40):
        return "ficou bem mais longa"
    return ""


PROMPT_REVISAO = """Você revisa o TEXTO de um relatório de riscos da transição do governo do Estado do Rio de Janeiro.
Não muda o conteúdo: muda o tom e a forma. O relatório ANALISA; não aconselha.

Regras de tom (valem para todo campo):
- Descreva fatos, causas, consequências e o que está pendente. NÃO recomende, NÃO sugira caminho, NÃO proponha
  providência, NÃO diga quem deve fazer, decidir ou ser responsável por algo.
- Proibido: "deve", "deveria", "é preciso", "é necessário", "precisa ser", "recomenda-se", "sugere-se", "convém",
  "o ideal", "cabe a", "é importante que", "a melhor saída", "quem decide".
- Campo "decisao": o ponto que está pendente de decisão, em frase afirmativa e neutra, sem listar caminhos e sem
  pergunta (ex.: "Destino dos sete contratos de viaturas que terminam entre 14/11/2026 e 09/01/2027.").
- Campo "pedir": a informação que falta no material, em frase nominal (ex.: "Execução orçamentária por ação e fonte.").
- Campo "motivo_sensibilidade": a repercussão política, sempre no condicional ("pode gerar reação de famílias e da
  imprensa"). Não afirme reação que não ocorreu ("reagem") e tire "expõe o governador" ou "expõe o novo governo".
- Frases completas, de até 25 palavras. Nada cortado no meio, nada de reticências.

Regras de fidelidade (o sistema confere e recusa a reescrita que quebrar uma delas):
- Mantenha TODOS os números, datas, valores e referências (F1, V2, O3, C5, R1) exatamente como estão.
- Não acrescente fato, número, nome ou opinião.
- Não deixe o texto mais longo; se puder, mais curto.

Recebe um JSON {"chave": "texto"} e, em "pistas", o que já foi apontado. Devolva SÓ os campos que mudou, com a mesma
chave. Campo que já está bom não volta. Responda SOMENTE com JSON, entre [INÍCIO DO JSON] e [FIM DO JSON]:
{"textos": {"R1.decisao": "..."}}"""


def revisar_texto(modelo, resultado, uso, pistas=None):
    """Reescreve os campos do resultado no tom de análise, com as travas do código. Altera `resultado` e devolve o
    registro: o que mudou, o que foi recusado (e por quê) e os alertas que sobraram."""
    textos = campos(resultado)
    registro = {"modelo": modelo, "aceitos": [], "recusados": [], "alertas_antes": {}, "alertas_depois": {}}
    registro["alertas_antes"] = {k: a for k, t in textos.items() if (a := alertas(t))}
    if not textos:
        return registro
    pedido = json.dumps({"textos": textos, "pistas": {**{k: v for k, v in registro["alertas_antes"].items()},
                                                      "revisao_de_neutralidade": pistas or []}},
                        ensure_ascii=False, indent=0)
    try:
        dados = chamar_json(modelo, [{"role": "system", "content": PROMPT_REVISAO}, {"role": "user", "content": pedido}],
                            16000, etapa="revisão do texto", uso_lista=uso, chave="textos") or {}
    except Exception as e:                                      # sem a revisão, o texto segue como estava
        registro["erro"] = f"{type(e).__name__}: {e}"[:200]
        dados = {}
    novos = dados.get("textos") if isinstance(dados.get("textos"), dict) else {}
    for chave, depois in novos.items():
        if chave not in textos or not isinstance(depois, str) or depois.strip() == str(textos[chave]).strip():
            continue
        motivo = aceitar(textos[chave], depois)
        if motivo:
            registro["recusados"].append({"campo": chave, "antes": textos[chave], "proposta": depois, "motivo": motivo})
        else:
            _gravar(resultado, chave, depois.strip())
            registro["aceitos"].append({"campo": chave, "antes": textos[chave], "depois": depois.strip()})
    # a repercussão no condicional, por código, mesmo que a reescrita não tenha vindo ou tenha sido recusada
    registro["condicional"] = []
    for r in resultado.get("riscos") or []:
        antes = str(r.get("motivo_sensibilidade") or "")
        depois = condicional(antes)
        if depois != antes:
            r["motivo_sensibilidade"] = depois
            registro["condicional"].append({"campo": f"{r['id']}.motivo_sensibilidade", "antes": antes, "depois": depois})
    registro["alertas_depois"] = {k: a for k, t in campos(resultado).items() if (a := alertas(t))}
    return registro


def alertas_do_documento(md):
    """A última conferência, no documento pronto: as linhas com recomendação ou corte que ainda ficaram."""
    saida = []
    for linha in str(md or "").splitlines():
        a = [x for x in alertas(linha) if x != "parêntese sem fechar"]
        if a:
            saida.append({"trecho": linha.strip()[:200], "alertas": a})
    return saida

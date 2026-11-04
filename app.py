"""
Painel de Deliberação e Análise de Transição (Streamlit)

Instalação:
    pip install streamlit litellm "markitdown[all]" python-docx python-dotenv
Execução:
    streamlit run painel_deliberacao.py
A chave da API fica no arquivo .env, na mesma pasta:
    ANTHROPIC_API_KEY=...
"""
import hashlib
import io
import json
import os
import re
import tempfile
import unicodedata
from datetime import date

import docx
import streamlit as st
from docx.enum.text import WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from dotenv import load_dotenv
from litellm import completion
from markitdown import MarkItDown

load_dotenv()

# --- CONFIGURAÇÃO ---------------------------------------------------------

MODELOS = [
    "anthropic/claude-sonnet-5-5",
    "anthropic/claude-opus-5-5",
    "anthropic/claude-haiku-5-5",
    "anthropic/claude-sonnet-4-5-20250929",
]
LIMITE_CARACTERES = 150_000
CAMPOS = ["problema", "fatos", "personas", "lacunas"]
TIPOS_DIVERGENCIA = ["factual", "causal", "normativa", "distributiva", "temporal", "epistêmica"]
MARCA_JSON_INI, MARCA_JSON_FIM = "[INÍCIO DO JSON]", "[FIM DO JSON]"

# --- PROMPTS ---------------------------------------------------------------

METODOLOGIA = """
Você é um facilitador de deliberação multiagente para apoiar a transição de governo.
Você NÃO decide, NÃO recomenda e NÃO busca consenso. Seu trabalho é expor trade-offs,
revelar conflitos e mapear riscos para decisores humanos.

PROTOCOLO EM 5 FASES:
FASE 1 — PROPOSIÇÃO: cada persona propõe um plano.
FASE 2 — CRÍTICA CRUZADA: cada persona critica os planos das outras.
FASE 2.5 — REVISÃO: cada persona escolhe REVISAR, DEFENDER ou MANTER; abandona premissas se for convencida.
FASE 3 — AVALIAÇÃO INDEPENDENTE: nota cega de cada plano.
FASE 4 — TENSION MAP: deduplique argumentos por mecanismo causal (se três personas reclamam da mesma
coisa com palavras diferentes, é UM trade-off). No máximo 4 trade-offs reais.
FASE 5 — MEMORANDO EXECUTIVO: 2 páginas em português claro.

DIRETRIZES INVIOLÁVEIS:
1. Hierarquia de evidências:
   Nível 1 — fato documental (relatório, SIAFE, SEI);
   Nível 2 — cálculo sobre dados documentais ou norma legal expressa;
   Nível 3 — padrão recorrente ou precedente administrativo;
   Nível 4 — hipótese causal plausível, sem dado;
   Nível 5 — sem evidência / intuição.
2. Regra anti-alucinação: se não houver evidência, declare Nível 5. Nunca invente números, datas,
   nomes ou processos. Só use números que estejam nos fatos ou no relatório.
3. Classifique cada divergência como factual, causal, normativa, distributiva, temporal ou epistêmica.
4. Aplique as restrições legais brasileiras reais: LRF (inclusive art. 42 no fim de mandato),
   Lei 14.133/2021, poder de veto e de medida cautelar do TCE e do MP, estabilidade do servidor.
5. Nunca fabrique dissenso. Se houver convergência legítima, registre-a como convergência.
"""

PROMPT_ETAPA_1 = METODOLOGIA + f"""
NESTA ETAPA: execute internamente as Fases 1 a 4. Não mostre o histórico das Fases 1 a 3.
Registre o resultado chamando a ferramenta `registrar_tension_map` uma única vez.
Se não puder usar a ferramenta, devolva somente o JSON entre {MARCA_JSON_INI} e {MARCA_JSON_FIM}.

Regras de concisão (para caber no limite de tokens):
- no máximo 4 trade-offs;
- "descricao" com no máximo 2 frases; "mecanismo_causal" com 1 frase;
- argumentos de cada polo com no máximo 2 frases.
"""

PROMPT_ETAPA_2 = METODOLOGIA + """
NESTA ETAPA: escreva a Fase 5 a partir do cenário, dos fatos e do Tension Map fornecidos.
Não acrescente trade-offs, números ou fatos que não estejam nesses insumos. Não recomende um caminho:
apresente as opções, quem ganha e quem perde com cada uma e o que se sabe sobre cada argumento.

Tamanho: o memorando inteiro, com a matriz, deve caber em 2 páginas (no máximo 1.100 palavras).
Seja direto: frases curtas, sem repetir o que já está no Tension Map.

Entregue somente o Markdown abaixo, nesta ordem, sem texto antes ou depois:

# Memorando Executivo
## Em síntese
(3 a 5 tópicos com o que está em jogo)
## Os 3 principais trade-offs
(um ### por trade-off: o dilema, quem ganha e quem perde com cada polo, tipo de divergência e nível de evidência)
## Decisões que precisam ser tomadas nesta semana
(lista numerada; cada item diz o que precisa ser decidido e por quê agora, sem dizer qual opção escolher)
## Dados faltantes
(lista: o dado, quem pode fornecer e qual trade-off ele afeta)
## Custo de não decidir
(1 parágrafo, a partir do baseline)
## Matriz de Risco
| Risco | Probabilidade | Impacto | Ação mitigadora | Responsável |
|---|---|---|---|---|
(5 a 8 linhas; Probabilidade e Impacto só com Alta/Média/Baixa ou Alto/Médio/Baixo)
"""

PROMPT_EXTRATOR = """Leia o relatório de transição abaixo e extraia as informações no formato JSON.
Use só o que está no relatório; não invente números.

RELATÓRIO:
<<<RELATORIO>>>

Retorne APENAS o JSON, neste formato:
{
  "problema": "1 parágrafo com o maior dilema da secretaria.",
  "fatos": ["5 a 8 fatos ancoradores com números, orçamento, contratos e prazos, citando a seção do relatório"],
  "personas": [
    {"id": "baseline", "nome": "Status quo", "criterio": "o que acontece se nada for decidido"},
    {"id": "fazenda_planejamento", "nome": "...", "criterio": "foco em caixa"},
    {"id": "orgao_controle", "nome": "...", "criterio": "foco em legalidade/TCE"},
    {"id": "casa_civil", "nome": "...", "criterio": "foco em coordenação política"},
    {"id": "beneficiario_servico", "nome": "...", "criterio": "foco no cidadão na ponta"},
    {"id": "...", "nome": "persona técnica específica desta secretaria", "criterio": "..."},
    {"id": "...", "nome": "segunda persona técnica específica", "criterio": "..."}
  ],
  "lacunas": ["3 a 4 informações críticas que o relatório NÃO responde"]
}
As cinco primeiras personas são obrigatórias. As duas últimas você cria com base no relatório.
Descreva o critério de decisão de cada uma em uma frase.
Registre o resultado chamando a ferramenta `registrar_insumos`. Se não puder usar a ferramenta,
devolva somente o JSON acima, com exatamente estas chaves: problema, fatos, personas, lacunas."""

FERRAMENTA_EXTRACAO = {
    "type": "function",
    "function": {
        "name": "registrar_insumos",
        "description": "Registra os insumos da deliberação extraídos do relatório de transição.",
        "parameters": {
            "type": "object",
            "properties": {
                "problema": {"type": "string"},
                "fatos": {"type": "array", "items": {"type": "string"}},
                "personas": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}, "nome": {"type": "string"}, "criterio": {"type": "string"}},
                    "required": ["id", "nome", "criterio"]}},
                "lacunas": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["problema", "fatos", "personas", "lacunas"],
        },
    },
}

# Nomes alternativos que o modelo às vezes usa para cada campo
SINONIMOS = {
    "problema": ["problema", "problema_central", "dilema", "dilema_central", "cenario", "scenario", "problem"],
    "fatos": ["fatos", "fatos_ancoradores", "fatos_chave", "fatos_principais", "facts"],
    "personas": ["personas", "agentes", "personas_agentes", "agents"],
    "lacunas": ["lacunas", "lacunas_de_dados", "dados_faltantes", "informacoes_faltantes", "gaps"],
}

_NIVEL = {"type": "integer", "minimum": 1, "maximum": 5}
_POLO = {
    "type": "object",
    "properties": {
        "posicao": {"type": "string"},
        "defendido_por": {"type": "array", "items": {"type": "string"}},
        "argumento": {"type": "string"},
        "evidencia": _NIVEL,
    },
    "required": ["posicao", "defendido_por", "argumento", "evidencia"],
}
SCHEMA_TENSION_MAP = {
    "type": "object",
    "properties": {
        "tension_map_id": {"type": "string"},
        "scenario": {"type": "string"},
        "baseline_reference": {
            "type": "object",
            "properties": {
                "cenario": {"type": "string"},
                "consequencias": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"efeito": {"type": "string"}, "evidencia": _NIVEL},
                    "required": ["efeito", "evidencia"]}},
                "custo_de_esperar": {"type": "string"},
            },
            "required": ["cenario", "consequencias", "custo_de_esperar"],
        },
        "convergencias": {"type": "array", "items": {
            "type": "object",
            "properties": {"tema": {"type": "string"}, "personas": {"type": "array", "items": {"type": "string"}}, "evidencia": _NIVEL},
            "required": ["tema", "personas", "evidencia"]}},
        "trade_offs": {"type": "array", "maxItems": 4, "items": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "titulo": {"type": "string"},
                "descricao": {"type": "string"},
                "mecanismo_causal": {"type": "string"},
                "polo_a": _POLO,
                "polo_b": _POLO,
                "tipos_divergencia": {"type": "array", "items": {"type": "string", "enum": TIPOS_DIVERGENCIA}},
                "nivel_evidencia": _NIVEL,
                "quem_ganha": {"type": "string"},
                "quem_perde": {"type": "string"},
                "o_que_mudaria": {"type": "string"},
            },
            "required": ["id", "titulo", "descricao", "mecanismo_causal", "polo_a", "polo_b",
                         "tipos_divergencia", "nivel_evidencia", "quem_ganha", "quem_perde", "o_que_mudaria"]}},
        "unresolved_questions": {"type": "array", "items": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "questao": {"type": "string"},
                           "quem_responde": {"type": "string"}, "afeta": {"type": "array", "items": {"type": "string"}}},
            "required": ["id", "questao", "quem_responde", "afeta"]}},
        "confidence_assessment": {
            "type": "object",
            "properties": {"nivel_geral": {"type": "string", "enum": ["alta", "média", "baixa"]},
                           "justificativa": {"type": "string"},
                           "principais_limitacoes": {"type": "array", "items": {"type": "string"}}},
            "required": ["nivel_geral", "justificativa", "principais_limitacoes"]},
    },
    "required": ["tension_map_id", "scenario", "baseline_reference", "convergencias", "trade_offs",
                 "unresolved_questions", "confidence_assessment"],
}
FERRAMENTA_TENSION_MAP = {
    "type": "function",
    "function": {
        "name": "registrar_tension_map",
        "description": "Registra o Tension Map final da Fase 4.",
        "parameters": SCHEMA_TENSION_MAP,
    },
}

# --- FUNÇÕES AUXILIARES -----------------------------------------------------

def _norm(s):
    return unicodedata.normalize("NFD", str(s or "")).encode("ascii", "ignore").decode().lower().strip()


@st.cache_data(show_spinner=False)
def converter_arquivo(nome, conteudo):
    """Converte PDF, DOCX ou XLSX em Markdown. O cache evita reconverter o mesmo arquivo."""
    sufixo = "." + nome.rsplit(".", 1)[-1].lower()
    with tempfile.NamedTemporaryFile(delete=False, suffix=sufixo) as tmp:
        tmp.write(conteudo)
        caminho = tmp.name
    try:
        return MarkItDown().convert(caminho).text_content
    finally:
        os.remove(caminho)


def limpar_relatorio(texto):
    """Tira do relatório o que não serve à deliberação: instruções do modelo e dados pessoais."""
    avisos = []
    tamanho_original = len(texto)
    # Páginas de orientação do modelo de relatório (antes da seção 1)
    texto = re.sub(r"#+\s*\**ORIENTAÇÕES DE PREENCHIMENTO.*?(?=#+\s*\**1\.\s*APRESENTA)", "", texto, flags=re.S | re.I)
    # Quadros "Como preencher"
    texto = re.sub(r"\**Como preencher:?\**.*?(?:\n\s*\n|$)", "", texto, flags=re.S | re.I)
    # Seção 9 (pontos focais: nomes e contatos de servidores)
    texto, n9 = re.subn(r"#+\s*\**9\.\s*PONTOS FOCAIS.*", "", texto, flags=re.S | re.I)
    if n9:
        avisos.append("A seção 9 (pontos focais, com nomes e e-mails) não foi enviada ao modelo.")
    # E-mails que sobrarem em outras seções
    texto, n_email = re.subn(r"[\w.+-]+@[\w-]+\.[\w.-]+", "[e-mail omitido]", texto)
    if n_email:
        avisos.append(f"{n_email} endereço(s) de e-mail foram omitidos.")
    reduzido = tamanho_original - len(texto)
    if reduzido > 0:
        avisos.append(f"{reduzido:,} caracteres de instruções e dados pessoais foram removidos.".replace(",", "."))
    if len(texto) > LIMITE_CARACTERES:
        avisos.append(f"O relatório passou de {LIMITE_CARACTERES:,} caracteres e foi cortado no final.".replace(",", "."))
        texto = texto[:LIMITE_CARACTERES]
    return texto, avisos


def extrair_json(texto):
    """Lê o primeiro objeto JSON completo do texto. Procura entre os marcadores antes de tudo."""
    if not texto:
        return None
    ini, fim = texto.find(MARCA_JSON_INI), texto.find(MARCA_JSON_FIM)
    if ini != -1 and fim > ini:
        texto = texto[ini + len(MARCA_JSON_INI):fim]
    texto = re.sub(r"```(?:json)?", "", texto)
    decodificador = json.JSONDecoder()
    pos = texto.find("{")
    while pos != -1:
        try:
            obj, _ = decodificador.raw_decode(texto, pos)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
        pos = texto.find("{", pos + 1)
    return None


def chamar_modelo(modelo, mensagens, max_tokens, ferramenta=None):
    """Chama o modelo e devolve (texto, argumentos da ferramenta ou None, motivo de parada)."""
    extras = {}
    if ferramenta:
        # "auto" em vez de forçar a ferramenta: alguns modelos (ex.: Opus 5.5) não aceitam uso forçado.
        # Os prompts já mandam chamar a ferramenta e, se o modelo responder em texto, o JSON é lido do texto.
        extras = {"tools": [ferramenta], "tool_choice": "auto"}
    try:
        resp = completion(model=modelo, messages=mensagens, max_tokens=max_tokens, **extras)
    except Exception as e:
        # Sem o pacote "mcp", ou com um modelo que não aceita ferramentas, repete a chamada sem ferramenta;
        # os prompts já pedem o JSON em texto nesse caso.
        sem_suporte = isinstance(e, ImportError) or "UnsupportedParams" in type(e).__name__ or "tool" in str(e).lower()
        if not extras or not sem_suporte:
            raise
        resp = completion(model=modelo, messages=mensagens, max_tokens=max_tokens)
    escolha = resp.choices[0]
    msg = escolha.message
    argumentos = None
    for chamada in (getattr(msg, "tool_calls", None) or []):
        try:
            argumentos = json.loads(chamada.function.arguments)
            break
        except (json.JSONDecodeError, TypeError, AttributeError):
            continue
    return (msg.content or ""), argumentos, getattr(escolha, "finish_reason", None)


def como_texto(valor):
    """Converte o que o extrator devolve em texto legível para as caixas de edição."""
    if isinstance(valor, list):
        linhas = []
        for item in valor:
            if isinstance(item, dict):
                nome = item.get("nome") or item.get("id") or ""
                criterio = item.get("criterio") or item.get("descricao") or ""
                ident = f"[{item['id']}] " if item.get("id") and item.get("nome") else ""
                linhas.append(f"- {ident}{nome}: {criterio}".rstrip(": "))
            else:
                linhas.append(f"- {item}")
        return "\n".join(linhas)
    if isinstance(valor, dict):
        return json.dumps(valor, ensure_ascii=False, indent=2)
    return str(valor or "")


def mapear_campos(dados):
    """Encontra os quatro campos no JSON do extrator, aceitando nomes alternativos e um nível de aninhamento."""
    if not isinstance(dados, dict):
        return {}

    def chaves_normalizadas(d):
        return {re.sub(r"[^a-z0-9]+", "_", _norm(k)).strip("_"): v for k, v in d.items()}

    candidatos = [chaves_normalizadas(dados)]
    candidatos += [chaves_normalizadas(v) for v in dados.values() if isinstance(v, dict)]
    encontrados = {}
    for campo, nomes in SINONIMOS.items():
        for d in candidatos:
            valor = next((d[n] for n in nomes if d.get(n)), None)
            if valor:
                encontrados[campo] = valor
                break
    return encontrados


def processar_extracao(modelo, arquivo, manter_editados):
    """Lê o relatório, chama o extrator e preenche os campos. Devolve o status para a barra lateral."""
    status = {"tipo": "erro", "mensagem": "", "avisos": [], "bruto": ""}
    try:
        texto = converter_arquivo(arquivo.name, arquivo.getvalue())
    except Exception as e:
        status["mensagem"] = f"Não foi possível ler o arquivo: {e}"
        return status
    if not texto or len(texto.strip()) < 200:
        status["mensagem"] = ("Quase não há texto no arquivo. Se o PDF for digitalizado, use a versão com texto "
                              "selecionável ou o .docx original.")
        return status
    texto, status["avisos"] = limpar_relatorio(texto)
    try:
        bruto, argumentos, motivo = chamar_modelo(
            modelo, [{"role": "user", "content": PROMPT_EXTRATOR.replace("<<<RELATORIO>>>", texto)}],
            8000, ferramenta=FERRAMENTA_EXTRACAO)
    except Exception as e:
        status["mensagem"] = f"Erro na chamada ao modelo: {e}"
        return status
    status["bruto"] = json.dumps(argumentos, ensure_ascii=False, indent=2) if argumentos else bruto
    campos = mapear_campos(argumentos) or mapear_campos(extrair_json(bruto))
    if not campos:
        status["mensagem"] = ("O modelo respondeu, mas não encontrei os campos na resposta."
                              + (" A resposta foi cortada pelo limite de tokens." if motivo == "length" else "")
                              + " Veja a resposta bruta abaixo.")
        return status
    preenchidos, mantidos = [], []
    for campo in CAMPOS:
        if campo not in campos:
            continue
        if manter_editados and st.session_state.get(campo, "").strip():
            mantidos.append(campo)
            continue
        st.session_state[campo] = como_texto(campos[campo])
        preenchidos.append(campo)
    faltando = [c for c in CAMPOS if c not in campos]
    status["tipo"] = "aviso" if faltando else "ok"
    partes = [f"Preenchidos: {', '.join(preenchidos)}." if preenchidos else "Nenhum campo foi alterado."]
    if mantidos:
        partes.append(f"Mantidos como você editou: {', '.join(mantidos)}.")
    if faltando:
        partes.append(f"O modelo não devolveu: {', '.join(faltando)}. Preencha à mão ou extraia de novo.")
    status["mensagem"] = " ".join(partes)
    return status


def montar_cenario():
    s = st.session_state
    return (f"CENÁRIO / PROBLEMA CENTRAL:\n{s['problema']}\n\nFATOS ANCORADORES:\n{s['fatos']}\n\n"
            f"PERSONAS:\n{s['personas']}\n\nLACUNAS DE DADOS:\n{s['lacunas']}")


# --- WORD -----------------------------------------------------------------

AZUL = RGBColor(0x1B, 0x2A, 0x41)
ACENTO = RGBColor(0x3E, 0x6A, 0x9E)
CINZA = RGBColor(0x68, 0x72, 0x80)
TEXTO = RGBColor(0x26, 0x2C, 0x36)
NIVEIS = {3: ("F6DBD6", RGBColor(0xB0, 0x40, 0x34)), 2: ("F8ECCD", RGBColor(0xB0, 0x80, 0x16)), 1: ("DAECE1", RGBColor(0x3E, 0x80, 0x5C))}


def _nivel(txt):
    n = _norm(txt)
    if re.match(r"^(alt|high|critic)", n):
        return 3
    if re.match(r"^(med|moder)", n):
        return 2
    if re.match(r"^(baix|low)", n):
        return 1
    return None


def _sombrear(celula, cor):
    tcPr = celula._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), cor)
    tcPr.append(shd)


def _bordas_celula(celula, **lados):
    tcPr = celula._tc.get_or_add_tcPr()
    bordas = OxmlElement("w:tcBorders")
    for lado, (estilo, tamanho, cor) in lados.items():
        b = OxmlElement(f"w:{lado}")
        b.set(qn("w:val"), estilo)
        b.set(qn("w:sz"), str(tamanho))
        b.set(qn("w:color"), cor)
        bordas.append(b)
    tcPr.append(bordas)


def _linha_inferior(par, cor="D5DBE3", tamanho=4):
    pPr = par._p.get_or_add_pPr()
    pbdr = OxmlElement("w:pBdr")
    b = OxmlElement("w:bottom")
    b.set(qn("w:val"), "single")
    b.set(qn("w:sz"), str(tamanho))
    b.set(qn("w:space"), "4")
    b.set(qn("w:color"), cor)
    pbdr.append(b)
    pPr.append(pbdr)


def _campo(par, instrucao, tamanho, cor):
    """Insere um campo do Word (PAGE, NUMPAGES) que o próprio Word atualiza."""
    def _run_com(elemento):
        run = par.add_run()
        run.font.size, run.font.color.rgb = tamanho, cor
        run._r.append(elemento)
        return run

    inicio = OxmlElement("w:fldChar")
    inicio.set(qn("w:fldCharType"), "begin")
    _run_com(inicio)
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = f" {instrucao} "
    _run_com(instr)
    separador = OxmlElement("w:fldChar")
    separador.set(qn("w:fldCharType"), "separate")
    _run_com(separador)
    provisorio = par.add_run("1")
    provisorio.font.size, provisorio.font.color.rgb = tamanho, cor
    fim = OxmlElement("w:fldChar")
    fim.set(qn("w:fldCharType"), "end")
    _run_com(fim)


def _texto_inline(par, texto, tamanho=Pt(10.5), cor=TEXTO, negrito=False):
    texto = re.sub(r"`([^`]+)`", r"\1", texto)
    texto = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", texto)
    for pedaco in re.split(r"(\*\*[^*]+\*\*)", texto):
        if not pedaco:
            continue
        forte = pedaco.startswith("**") and pedaco.endswith("**")
        conteudo = pedaco[2:-2] if forte else re.sub(r"(?<![\w*])[*_]([^*_]+)[*_](?![\w*])", r"\1", pedaco)
        run = par.add_run(conteudo)
        run.bold = forte or negrito
        run.font.size, run.font.color.rgb = tamanho, cor


def _ler_markdown(md):
    """Divide o Markdown em blocos: título, parágrafo, lista e tabela."""
    blocos, paragrafo = [], []

    def fechar_paragrafo():
        if paragrafo:
            blocos.append(("p", " ".join(paragrafo)))
            paragrafo.clear()

    for linha in md.splitlines():
        s = linha.strip()
        if not s:
            fechar_paragrafo()
            continue
        if m := re.match(r"^(#{1,4})\s+(.*)", s):
            fechar_paragrafo()
            blocos.append(("h", len(m.group(1)), m.group(2).strip().strip("*")))
        elif s.startswith("|"):
            fechar_paragrafo()
            if re.match(r"^\|?\s*:?-{2,}", s):
                continue
            celulas = [c.strip() for c in s.strip("|").split("|")]
            if blocos and blocos[-1][0] == "table":
                blocos[-1][1].append(celulas)
            else:
                blocos.append(("table", [celulas]))
        elif m := re.match(r"^([-*•])\s+(.*)", s):
            fechar_paragrafo()
            if blocos and blocos[-1][0] == "ul":
                blocos[-1][1].append(m.group(2))
            else:
                blocos.append(("ul", [m.group(2)]))
        elif m := re.match(r"^(\d+)[.)]\s+(.*)", s):
            fechar_paragrafo()
            if blocos and blocos[-1][0] == "ol":
                blocos[-1][1].append(m.group(2))
            else:
                blocos.append(("ol", [m.group(2)]))
        else:
            paragrafo.append(s)
    fechar_paragrafo()
    return blocos


def _desenhar_blocos(alvo, blocos):
    """Desenha os blocos no documento ou dentro de uma célula de tabela."""
    for bloco in blocos:
        tipo = bloco[0]
        if tipo == "h":
            nivel, texto = bloco[1], bloco[2]
            par = alvo.add_paragraph()
            par.paragraph_format.space_before = Pt(14 if nivel <= 2 else 8)
            par.paragraph_format.space_after = Pt(5)
            par.paragraph_format.keep_with_next = True
            _texto_inline(par, texto, Pt(13 if nivel <= 2 else 11), AZUL, negrito=True)
            if nivel <= 2:
                _linha_inferior(par)
        elif tipo == "p":
            par = alvo.add_paragraph()
            par.paragraph_format.space_after = Pt(6)
            par.paragraph_format.line_spacing = 1.2
            _texto_inline(par, bloco[1])
        elif tipo in ("ul", "ol"):
            for i, item in enumerate(bloco[1], 1):
                par = alvo.add_paragraph()
                par.paragraph_format.left_indent = Cm(0.7)
                par.paragraph_format.first_line_indent = Cm(-0.5)
                par.paragraph_format.space_after = Pt(3)
                marcador = par.add_run(f"{i}.  " if tipo == "ol" else "•  ")
                marcador.bold = True
                marcador.font.size, marcador.font.color.rgb = Pt(10.5), ACENTO
                _texto_inline(par, item)
        elif tipo == "table":
            _desenhar_tabela(alvo, bloco[1])
            alvo.add_paragraph()


def _desenhar_tabela(alvo, linhas):
    ncol = max(len(l) for l in linhas)
    tabela = alvo.add_table(rows=len(linhas), cols=ncol)
    tabela.style = "Table Grid"
    cabecalho = [_norm(c) for c in linhas[0]]
    colunas_nivel = {i for i, c in enumerate(cabecalho) if any(k in c for k in ("probab", "impact", "nivel", "intens"))}
    for r, linha in enumerate(linhas):
        for c in range(ncol):
            celula = tabela.cell(r, c)
            texto = linha[c] if c < len(linha) else ""
            celula.text = ""
            par = celula.paragraphs[0]
            if r == 0:
                _sombrear(celula, "1B2A41")
                _texto_inline(par, texto.strip("*"), Pt(9), RGBColor(0xFF, 0xFF, 0xFF), negrito=True)
                continue
            nivel = _nivel(texto) if c in colunas_nivel else None
            if nivel:
                fundo, cor = NIVEIS[nivel]
                _sombrear(celula, fundo)
                _texto_inline(par, texto, Pt(9), cor, negrito=True)
            else:
                _texto_inline(par, texto, Pt(9))
    # larguras proporcionais ao tamanho médio do texto de cada coluna (17 cm úteis)
    medias = []
    for c in range(ncol):
        textos = [len(l[c]) if c < len(l) else 0 for l in linhas]
        cabecalho_len = len(linhas[0][c]) if c < len(linhas[0]) else 0
        medias.append(max(12, cabecalho_len + 2, min(60, sum(textos) / len(textos))))
    total = sum(medias)
    larguras = [Cm(17 * m / total) for m in medias]
    tabela.autofit = False
    for c, coluna in enumerate(tabela.columns):
        coluna.width = larguras[c]
    for linha in tabela.rows:
        for c, celula in enumerate(linha.cells):
            celula.width = larguras[c]
        # não quebra uma linha entre duas páginas
        trPr = linha._tr.get_or_add_trPr()
        nao_quebrar = OxmlElement("w:cantSplit")
        nao_quebrar.set(qn("w:val"), "true")
        trPr.append(nao_quebrar)
    # repete o cabeçalho quando a tabela passa de página
    cab = OxmlElement("w:tblHeader")
    cab.set(qn("w:val"), "true")
    tabela.rows[0]._tr.get_or_add_trPr().append(cab)


def gerar_docx(memorando_md, meta):
    doc = docx.Document()
    secao = doc.sections[0]
    secao.page_width, secao.page_height = Cm(21), Cm(29.7)
    secao.left_margin = secao.right_margin = secao.top_margin = secao.bottom_margin = Cm(2)
    normal = doc.styles["Normal"]
    normal.font.name, normal.font.size = "Arial", Pt(10.5)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "Arial")

    # Cabeçalho institucional
    if meta.get("orgao"):
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(0)
        _texto_inline(p, meta["orgao"], Pt(9.5), AZUL, negrito=True)
    if meta.get("unidade"):
        p = doc.add_paragraph()
        _texto_inline(p, meta["unidade"], Pt(9.5), CINZA)
    _linha_inferior(p, "3E6A9E", 12)
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after = Pt(2)
    run = p.add_run("MEMORANDO EXECUTIVO")
    run.bold, run.font.size, run.font.color.rgb = True, Pt(8.5), ACENTO
    p = doc.add_paragraph()
    _texto_inline(p, meta.get("assunto") or "Memorando executivo", Pt(17), AZUL, negrito=True)
    dados = [("PARA", meta.get("para")), ("DE", meta.get("unidade") or meta.get("orgao")), ("DATA", meta.get("data"))]
    for rotulo, valor in [d for d in dados if d[1]]:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(1)
        p.paragraph_format.tab_stops.add_tab_stop(Cm(2.2))
        r = p.add_run(rotulo + "\t")
        r.bold, r.font.size, r.font.color.rgb = True, Pt(8), CINZA
        _texto_inline(p, valor, Pt(10))
    _linha_inferior(p)

    # Corpo: "Em síntese" vai num quadro; o resto segue em ordem
    blocos = _ler_markdown(memorando_md)
    if blocos and blocos[0][0] == "h" and "memorando" in _norm(blocos[0][2]):
        blocos = blocos[1:]
    i = 0
    while i < len(blocos):
        b = blocos[i]
        if b[0] == "h" and b[1] <= 2 and "sintese" in _norm(b[2]):
            j = i + 1
            while j < len(blocos) and not (blocos[j][0] == "h" and blocos[j][1] <= 2):
                j += 1
            doc.add_paragraph().paragraph_format.space_after = Pt(2)
            quadro = doc.add_table(rows=1, cols=1)
            celula = quadro.cell(0, 0)
            _sombrear(celula, "F2F5F9")
            _bordas_celula(celula, left=("single", 24, "3E6A9E"), top=("nil", 0, "auto"), right=("nil", 0, "auto"), bottom=("nil", 0, "auto"))
            par = celula.paragraphs[0]
            r = par.add_run(b[2].upper())
            r.bold, r.font.size, r.font.color.rgb = True, Pt(8.5), ACENTO
            _desenhar_blocos(celula, blocos[i + 1:j])
            i = j
            continue
        _desenhar_blocos(doc, [b])
        i += 1

    # Rodapé com numeração de páginas
    rodape = secao.footer.paragraphs[0]
    rodape.paragraph_format.tab_stops.add_tab_stop(Cm(17), WD_TAB_ALIGNMENT.RIGHT)
    origem = " · ".join(x for x in [meta.get("orgao"), "Memorando executivo", meta.get("data")] if x)
    r = rodape.add_run(origem + "\tPágina ")
    r.font.size, r.font.color.rgb = Pt(8), CINZA
    _campo(rodape, "PAGE", Pt(8), CINZA)
    r = rodape.add_run(" de ")
    r.font.size, r.font.color.rgb = Pt(8), CINZA
    _campo(rodape, "NUMPAGES", Pt(8), CINZA)

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def _assunto_padrao():
    problema = st.session_state.get("problema", "").strip()
    primeira = re.split(r"(?<=[.;:])\s", problema)[0].rstrip(".;:") if problema else ""
    return (primeira[:107] + "…") if len(primeira) > 110 else (primeira or "Deliberação sobre a transição de governo")


def _data_extenso(d):
    meses = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
             "setembro", "outubro", "novembro", "dezembro"]
    return f"{d.day} de {meses[d.month - 1]} de {d.year}"


# --- ESTADO INICIAL ---------------------------------------------------------

st.set_page_config(page_title="Deliberação Multiagente", page_icon="🏛️", layout="wide")
for campo in CAMPOS:
    st.session_state.setdefault(campo, "")
st.session_state.setdefault("orgao", "Secretaria de Estado das Cidades (SECID)")
st.session_state.setdefault("unidade", "Assessoria do Gabinete")
st.session_state.setdefault("para", "")
st.session_state.setdefault("assunto", "")

st.title("🏛️ Painel de Deliberação e Análise de Transição")

# --- BARRA LATERAL ----------------------------------------------------------

with st.sidebar:
    st.header("0. Configuração de IA")
    modelo = st.selectbox("Modelo facilitador", MODELOS)
    modelo_manual = st.text_input("Outro modelo (opcional)", placeholder="ex.: anthropic/claude-opus-5-5",
                                  help="Se preenchido, substitui o modelo da lista. Use o nome no formato do LiteLLM.")
    modelo = modelo_manual.strip() or modelo

    st.markdown("---")
    st.header("1. Upload do relatório")
    arquivo = st.file_uploader("Relatório (PDF, DOCX ou XLSX)", type=["pdf", "docx", "xlsx"])
    manter = st.checkbox("Manter campos que já editei", value=False,
                         help="Marcado, a extração só preenche os campos que estiverem vazios.")
    extrair_de_novo = st.button("🔄 Extrair novamente", use_container_width=True, disabled=arquivo is None)

    # A extração roda sozinha quando um arquivo novo é carregado; o botão repete a extração
    if arquivo is not None:
        assinatura = hashlib.md5(arquivo.getvalue()).hexdigest()
        if extrair_de_novo or st.session_state.get("arquivo_extraido") != assinatura:
            with st.spinner("Lendo o relatório e preenchendo os campos..."):
                st.session_state["status_extracao"] = processar_extracao(modelo, arquivo, manter)
            st.session_state["arquivo_extraido"] = assinatura

    status = st.session_state.get("status_extracao")
    if status:
        {"ok": st.success, "aviso": st.warning, "erro": st.error}[status["tipo"]](status["mensagem"])
        for aviso in status["avisos"]:
            st.caption(f"ℹ️ {aviso}")
        if status["bruto"]:
            with st.expander("Ver resposta do extrator"):
                st.code(status["bruto"], language="json")

    st.markdown("---")
    st.header("2. Revisão e ajustes")
    st.text_area("Problema central", key="problema", height=100)
    st.text_area("Fatos ancoradores", key="fatos", height=150)
    st.text_area("Personas", key="personas", height=200)
    st.text_area("Lacunas de dados", key="lacunas", height=100)

    st.markdown("---")
    st.header("3. Cabeçalho do documento")
    st.text_input("Órgão", key="orgao")
    st.text_input("De (unidade)", key="unidade")
    st.text_input("Para", key="para", placeholder="ex.: Secretária Maria Gabriela Bessa")
    st.text_input("Assunto", key="assunto", placeholder="Em branco, usa o problema central")

    st.markdown("---")
    botao_gerar = st.button("🚀 Iniciar deliberação (2 etapas)", use_container_width=True, type="primary")

# --- DELIBERAÇÃO --------------------------------------------------------------

if botao_gerar:
    faltando = [nome for nome, chave in [("Problema central", "problema"), ("Fatos ancoradores", "fatos"), ("Personas", "personas")]
                if not st.session_state[chave].strip()]
    if faltando:
        st.warning(f"Preencha antes de iniciar: {', '.join(faltando)}.")
    else:
        cenario = montar_cenario()
        try:
            with st.spinner(f"Etapa 1/2: o conselho de agentes ({modelo}) está debatendo..."):
                texto1, args1, motivo1 = chamar_modelo(
                    modelo,
                    [{"role": "system", "content": PROMPT_ETAPA_1},
                     {"role": "user", "content": cenario + "\n\nExecute o protocolo e registre o Tension Map."}],
                    8192, ferramenta=FERRAMENTA_TENSION_MAP)
                tension_map = args1 or extrair_json(texto1)
            if tension_map is None:
                st.error("O modelo não devolveu um Tension Map válido."
                         + (" A resposta foi cortada pelo limite de tokens; reduza os fatos ou as personas." if motivo1 == "length" else ""))
                with st.expander("Ver resposta bruta (para depuração)"):
                    st.text(texto1)
                st.stop()

            with st.spinner("Etapa 2/2: redigindo o memorando executivo e a matriz de risco..."):
                mensagens2 = [{"role": "system", "content": PROMPT_ETAPA_2},
                              {"role": "user", "content": cenario + "\n\nTENSION MAP (Fase 4):\n"
                               + json.dumps(tension_map, ensure_ascii=False, indent=2)}]
                memorando, _, motivo2 = chamar_modelo(modelo, mensagens2, 16000)
                # Se ainda for cortado, pede para continuar de onde parou (até 2 vezes)
                for _ in range(2):
                    if motivo2 != "length":
                        break
                    continuacao, _, motivo2 = chamar_modelo(
                        modelo,
                        mensagens2 + [{"role": "assistant", "content": memorando},
                                      {"role": "user", "content": "Continue o memorando exatamente de onde parou, "
                                       "sem repetir nada do que já escreveu e sem comentários."}],
                        8000)
                    memorando = memorando.rstrip() + ("\n" if continuacao.lstrip().startswith(("|", "#", "-")) else " ") + continuacao.lstrip()
            st.session_state["resultado"] = {
                "tension_map": tension_map,
                "memorando": memorando.strip(),
                "memorando_cortado": motivo2 == "length",
                "modelo": modelo,
                "data": _data_extenso(date.today()),
                "assinatura_insumos": hashlib.md5(cenario.encode()).hexdigest(),
            }
        except Exception as e:
            st.error(f"❌ Erro na API: {e}")

# --- RESULTADO (fica na tela mesmo depois dos downloads) -----------------------

resultado = st.session_state.get("resultado")
if not resultado:
    st.info("Suba o relatório, revise os campos na barra lateral e clique em **Iniciar deliberação**. "
            "O Tension Map, o memorando e a matriz de risco aparecem aqui.")
else:
    tm, memo = resultado["tension_map"], resultado["memorando"]
    st.success(f"✅ Deliberação concluída em {resultado['data']} com {resultado['modelo']}.")
    if resultado.get("memorando_cortado"):
        st.warning("O memorando foi cortado pelo limite de tokens. Revise o final antes de usar.")
    if hashlib.md5(montar_cenario().encode()).hexdigest() != resultado.get("assinatura_insumos"):
        st.warning("Os campos da barra lateral mudaram depois desta deliberação. Rode de novo para atualizar.")

    meta = {
        "orgao": st.session_state["orgao"].strip(),
        "unidade": st.session_state["unidade"].strip(),
        "para": st.session_state["para"].strip(),
        "assunto": st.session_state["assunto"].strip() or _assunto_padrao(),
        "data": resultado["data"],
    }
    col1, col2, col3 = st.columns(3)
    with col1:
        st.download_button("⬇️ Memorando (.docx)", data=gerar_docx(memo, meta), file_name="memorando_transicao.docx",
                           mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                           use_container_width=True, type="primary")
    with col2:
        st.download_button("⬇️ Memorando (.md)", data=memo, file_name="memorando_transicao.md", use_container_width=True)
    with col3:
        st.download_button("⬇️ Tension Map (.json)", data=json.dumps(tm, ensure_ascii=False, indent=2),
                           file_name="tension_map.json", use_container_width=True)

    aba_memo, aba_mapa, aba_json = st.tabs(["📄 Memorando", "🧭 Tension Map", "{ } JSON"])
    with aba_memo:
        st.markdown(memo)
    with aba_mapa:
        base = tm.get("baseline_reference") or {}
        if isinstance(base, dict) and base:
            st.subheader("Baseline (status quo)")
            st.write(base.get("cenario", ""))
            for c in base.get("consequencias", []) or []:
                if isinstance(c, dict):
                    st.markdown(f"- {c.get('efeito', '')} *(evidência nível {c.get('evidencia', '?')})*")
            if base.get("custo_de_esperar"):
                st.caption(f"Custo de esperar: {base['custo_de_esperar']}")
        elif base:
            st.subheader("Baseline (status quo)")
            st.write(base)

        st.subheader("Trade-offs")
        for t in tm.get("trade_offs", []) or []:
            if not isinstance(t, dict):
                continue
            with st.container(border=True):
                st.markdown(f"**{t.get('id', '')} · {t.get('titulo', '')}**")
                tipos = ", ".join(t.get("tipos_divergencia", []) or [])
                st.caption(f"Divergência: {tipos or '—'} · Evidência nível {t.get('nivel_evidencia', '?')}")
                if t.get("descricao"):
                    st.write(t["descricao"])
                if t.get("mecanismo_causal"):
                    st.markdown(f"*Mecanismo:* {t['mecanismo_causal']}")
                a, b = st.columns(2)
                for coluna, chave, rotulo in [(a, "polo_a", "Polo A"), (b, "polo_b", "Polo B")]:
                    polo = t.get(chave) or {}
                    with coluna:
                        if isinstance(polo, dict):
                            st.markdown(f"**{rotulo}:** {polo.get('posicao', '')}")
                            st.caption(f"Defendido por: {', '.join(polo.get('defendido_por', []) or []) or '—'} · "
                                       f"evidência nível {polo.get('evidencia', '?')}")
                            st.write(polo.get("argumento", ""))
                        else:
                            st.markdown(f"**{rotulo}:** {polo}")
                if t.get("quem_ganha") or t.get("quem_perde"):
                    st.markdown(f"**Ganha:** {t.get('quem_ganha', '—')}  \n**Perde:** {t.get('quem_perde', '—')}")
                if t.get("o_que_mudaria"):
                    st.caption(f"O que mudaria o equilíbrio: {t['o_que_mudaria']}")

        conv = tm.get("convergencias") or []
        if conv:
            st.subheader("Convergências")
            for c in conv:
                if isinstance(c, dict):
                    st.markdown(f"- {c.get('tema', '')} ({', '.join(c.get('personas', []) or [])}; nível {c.get('evidencia', '?')})")

        perguntas = tm.get("unresolved_questions") or []
        if perguntas:
            st.subheader("Questões não resolvidas")
            for q in perguntas:
                if isinstance(q, dict):
                    st.markdown(f"- **{q.get('id', '')}** {q.get('questao', '')} — *{q.get('quem_responde', '')}*")
                else:
                    st.markdown(f"- {q}")

        conf = tm.get("confidence_assessment") or {}
        if isinstance(conf, dict) and conf:
            st.subheader("Confiança da análise")
            st.write(f"**{str(conf.get('nivel_geral', '')).capitalize()}** — {conf.get('justificativa', '')}")
            for lim in conf.get("principais_limitacoes", []) or []:
                st.markdown(f"- {lim}")
    with aba_json:
        st.json(tm)

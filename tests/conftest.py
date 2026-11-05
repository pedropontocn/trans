"""Infraestrutura dos testes.

Os testes NÃO chamam nenhuma API: o LiteLLM e o MarkItDown são trocados por versões falsas
antes de o app ser carregado. Por isso rodam de graça, no GitHub Actions ou no seu computador.
"""
import json
import re
import sys
import threading
import types
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

RAIZ = Path(__file__).resolve().parent.parent
APP = RAIZ / "app.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
RELATORIO = (FIXTURES / "relatorio_exemplo.md").read_text(encoding="utf-8")

# Dossiê de exemplo: o que a "pesquisa" devolve e as páginas que o código abre para conferir os trechos.
TRECHO_LICITACOES = "Quatro concorrências estão adiadas sine die, somando R$ 120.500.000,00"
PAGINAS = {
    "https://transparencia.exemplo.gov.br/licitacoes":
        "<html><body><script>var x=1;</script><p>Quatro concorrências estão adiadas sine die, somando "
        "R$ 120.500.000,00, segundo o painel de compras.</p></body></html>",
    "https://www.exemplo.rj.gov.br/loa-2027": "<html><p>A LOA 2027 prevê déficit nominal de R$ 13,98 bilhões.</p></html>",
    "https://www.alerj.exemplo/calendario": "<html><p>Emendas ao projeto de lei orçamentária de 5 a 11 de novembro.</p></html>",
    "https://tce.exemplo.gov.br/decisao-123": "<html><p>O Tribunal apontou atraso na prestação de contas de convênios "
                                               "da Secretaria de Exemplo.</p></html>",
    "https://jornal.exemplo/materia": "<html><p>Governo eleito promete reduzir o número de secretarias.</p></html>",
    "https://transparencia.exemplo.gov.br/loa-sex": "<html><p>LOA 2026 da Secretaria de Exemplo: R$ 412.000.000,00.</p></html>",
}
ITENS_ESTADO = [
    {"bloco": "situacao_fiscal", "afirmacao": "A LOA 2027 prevê déficit nominal de R$ 13,98 bilhões.",
     "fonte": "PLOA 2027", "data_fonte": "10/2026", "url": "https://www.exemplo.rj.gov.br/loa-2027",
     "trecho": "A LOA 2027 prevê déficit nominal de R$ 13,98 bilhões", "tipo_fonte": "documento_oficial", "confianca": "alta"},
    {"bloco": "calendario_legal", "afirmacao": "As emendas à LOA vão de 5 a 11 de novembro.", "fonte": "Alerj",
     "data_fonte": "11/2026", "url": "https://www.alerj.exemplo/calendario",
     "trecho": "Emendas ao projeto de lei orçamentária de 5 a 11 de novembro", "tipo_fonte": "documento_oficial",
     "confianca": "alta"},
    {"bloco": "compromissos_governo", "afirmacao": "O governo eleito promete reduzir o número de secretarias.",
     "fonte": "Jornal Exemplo", "data_fonte": "10/2026", "url": "https://jornal.exemplo/materia",
     "trecho": "Governo eleito promete reduzir o número de secretarias", "tipo_fonte": "declaracao_politica",
     "confianca": "media"},
]
ITENS_ORGAO = [
    {"bloco": "orcamento_execucao", "afirmacao": "A LOA 2026 da Secretaria é de R$ 412.000.000,00.", "fonte": "LOA 2026",
     "data_fonte": "2026", "url": "https://transparencia.exemplo.gov.br/loa-sex",
     "trecho": "LOA 2026 da Secretaria de Exemplo: R$ 412.000.000,00", "tipo_fonte": "documento_oficial", "confianca": "alta"},
    {"bloco": "pessoal", "afirmacao": "A Secretaria tem 1.200 servidores efetivos.", "fonte": "Portal da Transparência",
     "data_fonte": "2026", "url": "https://transparencia.exemplo.gov.br/licitacoes",
     "trecho": "A Secretaria tem 1.200 servidores efetivos", "tipo_fonte": "dado_oficial", "confianca": "media"},
    {"bloco": "contratos_convenios", "afirmacao": TRECHO_LICITACOES + ".", "fonte": "Painel de compras",
     "data_fonte": "10/2026", "url": "https://transparencia.exemplo.gov.br/licitacoes", "trecho": TRECHO_LICITACOES,
     "tipo_fonte": "dado_oficial", "confianca": "alta"},
    {"bloco": "controle_judicializacao", "afirmacao": "O TCE-RJ apontou atraso na prestação de contas de convênios da Secretaria.",
     "fonte": "TCE-RJ, decisão 123", "data_fonte": "09/2026", "url": "https://tce.exemplo.gov.br/decisao-123",
     "trecho": "O Tribunal apontou atraso na prestação de contas de convênios da Secretaria de Exemplo",
     "tipo_fonte": "decisao_controle_judicial", "confianca": "alta"},
    {"bloco": "riscos_continuidade", "afirmacao": "O contrato de manutenção do sistema de folha vence em janeiro.",
     "fonte": "Diário Oficial", "data_fonte": "08/2026", "url": "https://pagina-que-nao-abre.exemplo/do",
     "trecho": "contrato de manutenção do sistema de folha", "tipo_fonte": "documento_oficial", "confianca": "media"},
    {"bloco": "inventado", "afirmacao": "Item sem link.", "fonte": "?", "url": "", "trecho": "", "tipo_fonte": "estudo"},
]
GRUPOS = [["situacao_fiscal", "regime_divida", "previdencia"], ["calendario_legal", "cenario_politico", "compromissos_governo"],
          ["mandato_estrutura", "orcamento_execucao", "pessoal"], ["contratos_convenios", "entregas_indicadores"],
          ["controle_judicializacao", "riscos_continuidade"]]
NAO_ENCONTRADO = {"estado": [{"bloco": "previdencia", "procurado": "Aporte do Tesouro ao RioPrevidência em 2026"}],
                  "orgao": [{"bloco": "pessoal", "procurado": "Número de terceirizados nos contratos de custeio"}]}

# Fontes citadas nos Tension Maps dos testes: item do dossiê que existe, trecho inventado e sem fonte
FONTE_OK = {"tipo": "dossie", "referencia": "O3", "trecho": TRECHO_LICITACOES}
FONTE_FALSA = {"tipo": "dossie", "referencia": "O3",
               "trecho": "a Secretaria tem R$ 500 milhões livres em caixa para 2027"}
FONTE_AUTO = {"tipo": "autodeclaracao", "referencia": "3.2",
              "trecho": "Cinco obras estão com execução suspensa aguardando decisão da Casa Civil"}
SEM_FONTE = {"tipo": "nenhuma", "referencia": "", "trecho": ""}


def dossie_exemplo(funcoes):
    """O dossiê como o app o monta, com os links já conferidos pelas páginas falsas."""
    itens = [funcoes.normalizar_item(b, "estado") for b in ITENS_ESTADO]
    itens += [x for x in (funcoes.normalizar_item(b, "orgao") for b in ITENS_ORGAO) if x]
    return {"orgao": "Secretaria de Exemplo", "data_corte": "04/11/2026", "foco": "", "modelo": "m", "origem": "pesquisa",
            "itens": funcoes.conferir_itens(funcoes.numerar_itens(itens)),
            "nao_encontrado": [dict(n, camada=c) for c, ns in NAO_ENCONTRADO.items() for n in ns], "uso": []}


MEMORANDO = """# Memorando Executivo

## Em síntese
- Quatro licitações somam R$ 120,5 mi e estão adiadas.
- A LOA 2026 é de R$ 412 mi.

## Os 3 principais trade-offs
### T1. Licitações adiadas
Decidir cedo ou esperar. Diferença de R$ 13,3 mi (cálculo) entre LOA e empenhado.

## Decisões que precisam ser tomadas nesta semana
1. Definir o destino das licitações adiadas.

## Dados faltantes
- Dotação atualizada (orçamento).

## Custo de não decidir
O prazo das atas é de cerca de 85 dias; um valor inventado: R$ 999,9 mi.

## Matriz de Risco
| Risco | Probabilidade | Impacto | Ação mitigadora | Responsável |
|---|---|---|---|---|
| Perda de propostas | Alta | Médio | Atualizar preços | Licitações |
| Obrigações sem caixa | Média | Alto | Demonstrativo de restos a pagar | Finanças |
"""


def polo(evidencia, fonte):
    return {"posicao": "p", "defendido_por": ["P1"], "argumento": "a", "evidencia": evidencia, "fonte": fonte}


def trade_off(id_, titulo, evidencia=1, fonte=FONTE_OK, **extra):
    t = {"id": id_, "titulo": titulo, "descricao": "d", "mecanismo_causal": "m",
         "polo_a": polo(evidencia, fonte), "polo_b": polo(4, SEM_FONTE), "tipos_divergencia": ["temporal"],
         "nivel_evidencia": evidencia, "quem_ganha": "g", "quem_perde": "p", "o_que_mudaria": "o"}
    t.update(extra)
    return t


def tension_map(trade_offs, **sem):
    tm = {"tension_map_id": "tm", "scenario": "cenário",
          "baseline_reference": {"cenario": "nada muda",
                                 "consequencias": [{"efeito": "e", "evidencia": 1, "fonte": FONTE_OK}],
                                 "custo_de_esperar": "crescente"},
          "convergencias": [], "trade_offs": trade_offs, "unresolved_questions": [],
          "confidence_assessment": {"nivel_geral": "baixa", "justificativa": "j", "principais_limitacoes": []}}
    for chave in sem:
        tm.pop(chave, None)
    return tm


class LLMFalso:
    """Faz o papel do modelo. Cada teste ajusta as respostas que quer."""

    def __init__(self):
        self.chamadas = []
        self.trava = threading.Lock()
        self.insumos = {"problema": "Carteira de licitações travada na transição (O1, E1).",
                        "personas": [{"id": "baseline", "nome": "Status quo", "criterio": "nada muda"},
                                     {"id": "planejamento", "nome": "Pasta de Planejamento", "criterio": "resultado fiscal"},
                                     {"id": "controle", "nome": "Controle externo", "criterio": "legalidade"},
                                     {"id": "gradual", "nome": "Defensor da mudança gradual", "criterio": "continuidade"}],
                        "sem_voz": ["Trabalhadores terceirizados dos contratos de custeio"],
                        "lacunas": ["Aporte do Tesouro ao RioPrevidência"]}
        self.resposta_insumos_texto = None           # se definido, os insumos vêm em texto, sem ferramenta
        self.paginas = dict(PAGINAS)                 # o que a "web" devolve quando o código abre um link
        self.falhar_pesquisa = False
        self.grupos_sem_json = set()                 # primeiro bloco dos grupos cuja resposta para sem o JSON
        self.grupos_com_erro = set()                 # primeiro bloco dos grupos cuja chamada dá erro
        self.continuacao_sem_json = False            # a continuação também para sem o JSON
        self.dossie_arquivo = None                   # bytes de um dossiê .json para o upload opcional
        self.sem_relatorio = False
        self.calendario = {"eventos": [
            {"data": "23/10/2026", "tipo": "orcamento", "evento": "Corte do empenho informado", "objeto": "LOA 2026",
             "valor": "R$ 398.750.000,00", "consequencia": "", "decisao": "Conferir o empenhado",
             "origem": "relatorio", "item": "", "trecho": "Empenhado até 23/10/2026: R$ 398.750.000,00"},
            {"data": "31/12/2026", "tipo": "contrato", "evento": "Data trocada", "objeto": "x", "valor": "",
             "consequencia": "", "decisao": "", "origem": "relatorio", "item": "",
             "trecho": "Empenhado até 23/10/2026: R$ 398.750.000,00"},
            {"data": "15/12/2026", "tipo": "contrato", "evento": "Trecho inventado", "objeto": "Contrato 99/2026",
             "valor": "R$ 5 mi", "consequencia": "", "decisao": "", "origem": "relatorio", "item": "",
             "trecho": "o contrato 99/2026 vence em 15/12/2026"}]}
        self.confronto = {"divergencias": [
            {"item": "O4", "situacao": "nao_mencionado", "o_orgao_declara": "", "trecho_relatorio": "",
             "as_fontes_mostram": "O TCE-RJ apontou atraso na prestação de contas de convênios."},
            {"item": "O3", "situacao": "contradiz", "o_orgao_declara": "o motivo não foi informado",
             "trecho_relatorio": "O motivo do adiamento não foi informado", "as_fontes_mostram": "x"},
            {"item": "O99", "situacao": "contradiz", "trecho_relatorio": "x", "as_fontes_mostram": "item que não existe"},
            {"item": "O1", "situacao": "contradiz", "trecho_relatorio": "a Secretaria não tem orçamento", "as_fontes_mostram": "y"},
            {"item": "O3", "situacao": "nao_mencionado", "trecho_relatorio": "", "as_fontes_mostram": "licitações mencionadas"}]}
        self.rodadas = [tension_map([trade_off("T1", "Licitações"), trade_off("T2", "Atas")])]
        self.consolidacao = None
        self.memorando = MEMORANDO
        self.memorando_cortado_uma_vez = False
        self.recusar_ferramentas = None              # exceção para simular modelos/versões sem ferramenta
        self.neutralidade = {"avaliacao_geral": "levemente_enviesado",
                             "trade_offs": [{"id": "T1", "equilibrio": "pende_para_a", "motivo": "o polo A tem o dobro do espaço"}],
                             "recomendacoes_implicitas": [
                                 {"trecho": "Definir o destino das licitações adiadas", "por_que": "soa como ordem"},
                                 {"trecho": "é imprescindível retomar todas as obras imediatamente", "por_que": "inventado"}]}
        self.falhar_neutralidade = False
        self.texto_relatorio = RELATORIO           # o que o MarkItDown falso devolve
        self.registro_anterior = None              # bytes de um registro .json para o segundo upload
        self.pareamento = None                     # resposta do pareamento de trade-offs (None = pareia por id igual)
        self.personas_mudas = set()                # ids de personas que respondem sem JSON na Fase 1
        self.falhar_avaliador = False
        self.sintese = None                        # Tension Map da síntese do modo independente
        self._n_tm = 0

    def _resp(self, conteudo="", nome=None, args=None, motivo="stop", entrada=10000, saida=2000, buscas=None):
        chamadas = [NS(function=NS(name=nome, arguments=json.dumps(args)))] if nome else None
        uso = NS(prompt_tokens=entrada, completion_tokens=saida)
        if buscas is not None:
            uso.server_tool_use = NS(web_search_requests=buscas)
        return NS(choices=[NS(message=NS(content=conteudo, tool_calls=chamadas), finish_reason=motivo)], usage=uso)

    def __call__(self, model, messages, max_tokens, **kw):
        texto = lambda c: c if isinstance(c, str) else " ".join(p["text"] for p in c)
        ultimo = texto(messages[-1]["content"])
        sistema = texto(messages[0]["content"])
        # com o relatório em cache, as instruções da etapa vêm na primeira mensagem do usuário, depois do relatório
        contexto = sistema + " " + (texto(messages[1]["content"]) if len(messages) > 1 else "")
        nomes = [t["function"]["name"] for t in kw.get("tools") or []]
        nome = nomes[0] if nomes else None
        with self.trava:
            self.chamadas.append({"modelo": model, "ferramenta": nome, "ferramentas": nomes, "mensagens": messages, "kw": kw})
        if nome and self.recusar_ferramentas:
            raise self.recusar_ferramentas

        if "Monte a camada" in texto(messages[0]["content"]):
            pedido = texto(messages[0]["content"])
            grupo = re.findall(r"^- ([a-z_]+): ", pedido, re.M)
            if self.falhar_pesquisa or grupo[0] in self.grupos_com_erro:
                raise RuntimeError("busca indisponível")
            continuacao = ultimo.startswith("Você parou antes")
            if grupo[0] in self.grupos_sem_json and (not continuacao or self.continuacao_sem_json):
                return self._resp("Fiz as buscas e encontrei documentos relevantes.", buscas=5)   # turno pausado
            camada = "estado" if 'camada\n"Estado"' in pedido else "orgao"
            todos = ITENS_ESTADO if camada == "estado" else ITENS_ORGAO
            conhecidos = {b for g in GRUPOS for b in g}
            itens = [i for i in todos if i["bloco"] in grupo or (i["bloco"] not in conhecidos and grupo[0] == "mandato_estrutura")]
            nao = [n for n in NAO_ENCONTRADO[camada] if n["bloco"] in grupo]
            return self._resp("Pesquisei. [INÍCIO DO JSON]" + json.dumps({"itens": itens, "nao_encontrado": nao})
                              + "[FIM DO JSON]", entrada=30000, saida=3000, buscas=0 if continuacao else 4)
        if "Você prepara os insumos" in sistema:
            self.mensagem_insumos = ultimo
            if self.resposta_insumos_texto is not None or nome is None:
                return self._resp(self.resposta_insumos_texto or json.dumps(self.insumos))
            return self._resp(nome=nome, args=self.insumos, motivo="tool_calls")
        if "Você confronta o que um órgão declarou" in contexto:
            self.mensagem_confronto = ultimo
            return self._resp(json.dumps(self.confronto))
        if "Você monta o calendário de vencimentos críticos" in contexto:
            self.mensagem_calendario = ultimo
            return self._resp("[INÍCIO DO JSON]" + json.dumps(self.calendario) + "[FIM DO JSON]")
        if "Você participa de uma deliberação multiagente" in contexto:
            mais_curta = ultimo.startswith("Sua resposta passou do limite")
            if mais_curta:                      # o pedido de resposta mais curta vem depois da conversa original
                ultimo = texto(messages[1]["content"])
            pid = re.search(r"VOCÊ É: \[([^\]]+)\]", ultimo).group(1)
            if "FASE 1 — PROPOSIÇÃO" in ultimo:
                if pid in self.personas_mudas:
                    return self._resp("não sei responder")
                if pid in getattr(self, "personas_prolixas", set()) and not mais_curta:
                    return self._resp('[INÍCIO DO JSON]{"plano": "um plano enorme que não acaba', motivo="length",
                                      saida=6000)
                obj = {"plano": f"Plano de {pid}", "premissas": [f"premissa de {pid}"],
                       "argumentos": [{"afirmacao": "a", "evidencia": 1, "fonte": FONTE_OK}]}
            elif "FASE 2 — CRÍTICA" in ultimo:
                outros = list(json.loads(ultimo.split("PROPOSTAS DAS OUTRAS PERSONAS:\n")[1].split("\n\nFASE 2")[0]))
                obj = {"criticas": [{"alvo": o, "critica": f"{pid} critica {o}", "tipo_divergencia": "causal",
                                     "evidencia": 3, "fonte": SEM_FONTE} for o in outros[:2]]
                                   + [{"alvo": "inexistente", "critica": "x", "evidencia": 5}]}
            else:
                obj = {"decisao": "REVISAR" if pid.endswith("1") else "DEFENDER", "plano_final": f"Plano final de {pid}",
                       "premissas_abandonadas": [], "justificativa": "j"}
            return self._resp("[INÍCIO DO JSON]" + json.dumps(obj) + "[FIM DO JSON]", entrada=15000, saida=600)
        if "avaliador independente de políticas públicas" in sistema:
            # True: todo avaliador falha; "gemini": só os Gemini falham (fora do ar), e o Claude serve de reserva
            if self.falhar_avaliador is True or (self.falhar_avaliador == "gemini" and model.startswith("gemini/")):
                raise RuntimeError("GEMINI_API_KEY inválida" if self.falhar_avaliador is True else
                                   'litellm.ServiceUnavailableError: GeminiException - {"code": 503, "status": "UNAVAILABLE"}')
            planos = json.loads(ultimo.split("PLANOS:\n")[1])
            self.planos_vistos_pelo_avaliador = ultimo
            return self._resp(json.dumps({"avaliacoes": [{"plano": r, "notas": {"viabilidade_juridica": 3, "viabilidade_fiscal": 2,
                                                                                "impacto_para_a_populacao": 4, "ancoragem_em_evidencias": 3},
                                                          "comentario": f"fraco em {r}"} for r in planos]}))
        if "As Fases 1 a 3 JÁ ACONTECERAM" in contexto:
            self.historico_sintese = ultimo
            alvo = self.sintese or tension_map([trade_off("T1", "Licitações"), trade_off("T2", "Atas")])
            return self._resp(nome=nome, args=alvo, motivo="tool_calls") if nome else self._resp(json.dumps(alvo))
        if "Pareie os que tratam do mesmo dilema" in sistema:
            if self.pareamento is None:
                anteriores = json.loads(ultimo.split("ANTERIOR:\n")[1].split("\n\nATUAL:")[0])
                atuais = {t["id"] for t in json.loads(ultimo.split("ATUAL:\n")[1])}
                pares = {"pares": [{"anterior": t["id"], "atual": t["id"]} for t in anteriores if t["id"] in atuais]}
            else:
                pares = self.pareamento
            return self._resp(nome=nome, args=pares, motivo="tool_calls") if nome else self._resp(json.dumps(pares))
        if "revisor de neutralidade" in sistema:
            if self.falhar_neutralidade:
                raise RuntimeError("serviço indisponível")
            return self._resp(nome=nome, args=self.neutralidade, motivo="tool_calls") if nome else self._resp(json.dumps(self.neutralidade))
        if "Consolide-os" in sistema:
            alvo = self.consolidacao or self.rodadas[0]
            return self._resp(nome=nome, args=alvo, motivo="tool_calls") if nome else self._resp(json.dumps(alvo))
        if "Execute o protocolo" in ultimo or "não segue o formato" in ultimo:
            with self.trava:
                i = self._n_tm
                self._n_tm += 1
            alvo = self.rodadas[i % len(self.rodadas)]
            return self._resp(nome=nome, args=alvo, motivo="tool_calls") if nome else self._resp(
                "[INÍCIO DO JSON]" + json.dumps(alvo) + "[FIM DO JSON]")
        # memorando
        if self.memorando_cortado_uma_vez:
            if ultimo.startswith("Continue"):
                return self._resp(self.memorando[len(self.memorando) // 2:])
            return self._resp(self.memorando[:len(self.memorando) // 2], motivo="length")
        return self._resp(self.memorando)


class ArquivoFalso:
    name = "relatorio_exemplo.pdf"

    def __init__(self, texto=RELATORIO):
        self.texto = texto

    def getvalue(self):
        # o conteúdo muda quando o relatório muda, como num arquivo de verdade
        return b"%PDF falso " + self.texto.encode("utf-8")


class DossieFalso:
    name = "dossie.json"

    def __init__(self, dados):
        self.dados = dados

    def getvalue(self):
        return self.dados


class RegistroFalso:
    name = "registro_anterior.json"

    def __init__(self, dados):
        self.dados = dados

    def getvalue(self):
        return self.dados


@pytest.fixture
def llm(monkeypatch):
    """Instala o LiteLLM e o MarkItDown falsos e devolve o modelo falso para o teste configurar."""
    falso = LLMFalso()
    litellm = types.ModuleType("litellm")
    litellm.completion = falso
    markitdown = types.ModuleType("markitdown")

    class MarkItDown:
        def convert(self, caminho):
            return NS(text_content=falso.texto_relatorio)

    markitdown.MarkItDown = MarkItDown

    import urllib.error
    import urllib.request

    class Resposta:
        def __init__(self, texto):
            self.dados = texto.encode("utf-8")
            self.headers = {"Content-Type": "text/html; charset=utf-8"}

        def read(self, n=-1):
            return self.dados

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(pedido, timeout=None):
        url = getattr(pedido, "full_url", pedido)
        falso.paginas_abertas = getattr(falso, "paginas_abertas", []) + [url]
        if url not in falso.paginas:
            raise urllib.error.URLError("não encontrado")
        return Resposta(falso.paginas[url])

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setitem(sys.modules, "litellm", litellm)
    monkeypatch.setitem(sys.modules, "markitdown", markitdown)
    import streamlit
    streamlit.cache_resource.clear()     # respostas guardadas de um teste não vazam para o próximo
    streamlit.cache_data.clear()
    return falso


@pytest.fixture
def funcoes(llm):
    """As funções do app, sem a interface (tudo o que vem antes de '# --- ESTADO INICIAL')."""
    codigo = APP.read_text(encoding="utf-8").split("# --- ESTADO INICIAL")[0]
    ns = {"__file__": str(APP), "__name__": "app_funcoes"}
    exec(compile(codigo, str(APP), "exec"), ns)
    return NS(**{k: v for k, v in ns.items() if not k.startswith("__")})


@pytest.fixture
def app(llm, monkeypatch, tmp_path):
    """O app inteiro rodando no AppTest do Streamlit, com upload de um relatório falso."""
    import streamlit
    from streamlit.testing.v1 import AppTest

    def uploader(rotulo, *a, **k):
        if "dossiê" in rotulo.lower():
            return DossieFalso(llm.dossie_arquivo) if llm.dossie_arquivo else None
        if "anterior" in rotulo.lower():
            return RegistroFalso(llm.registro_anterior) if llm.registro_anterior else None
        if "relatórios resumidos" in rotulo.lower():
            return getattr(llm, "resumos_enviados", None)
        return None if llm.sem_relatorio else ArquivoFalso(llm.texto_relatorio)

    monkeypatch.setattr(streamlit, "file_uploader", uploader)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PAINEL_REGISTROS", str(tmp_path / "registros"))
    at = AppTest.from_file(str(APP), default_timeout=120)
    return at

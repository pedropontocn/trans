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

# Trechos que existem no relatório de exemplo e trechos inventados
FONTE_OK = {"tipo": "relatorio", "referencia": "3.1",
            "trecho": "Quatro concorrências estão adiadas sine die, somando R$ 120.500.000,00"}
FONTE_FALSA = {"tipo": "relatorio", "referencia": "1.2",
               "trecho": "a Secretaria tem R$ 500 milhões livres em caixa para 2027"}
SEM_FONTE = {"tipo": "nenhuma", "referencia": "", "trecho": ""}

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
        self.insumos = {"problema": "Carteira travada na transição.", "fatos": [FONTE_OK["trecho"]],
                        "personas": [{"id": "baseline", "nome": "Status quo", "criterio": "nada muda"}],
                        "lacunas": ["Dotação atualizada"]}
        self.resposta_extracao_texto = None          # se definido, a extração responde em texto, sem ferramenta
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

    def _resp(self, conteudo="", nome=None, args=None, motivo="stop", entrada=10000, saida=2000):
        chamadas = [NS(function=NS(name=nome, arguments=json.dumps(args)))] if nome else None
        return NS(choices=[NS(message=NS(content=conteudo, tool_calls=chamadas), finish_reason=motivo)],
                  usage=NS(prompt_tokens=entrada, completion_tokens=saida))

    def __call__(self, model, messages, max_tokens, **kw):
        nome = kw["tools"][0]["function"]["name"] if kw.get("tools") else None
        with self.trava:
            self.chamadas.append({"modelo": model, "ferramenta": nome, "mensagens": messages, "kw": kw})
        if nome and self.recusar_ferramentas:
            raise self.recusar_ferramentas
        ultimo = messages[-1]["content"]
        ultimo = ultimo if isinstance(ultimo, str) else " ".join(p["text"] for p in ultimo)
        sistema = messages[0]["content"]
        sistema = sistema if isinstance(sistema, str) else " ".join(p["text"] for p in sistema)

        if "Leia o relatório de transição" in ultimo or "Leia o relatório de transição" in sistema:
            if self.resposta_extracao_texto is not None or nome is None:
                return self._resp(self.resposta_extracao_texto or json.dumps(self.insumos))
            return self._resp(nome=nome, args=self.insumos, motivo="tool_calls")
        if "Você participa de uma deliberação multiagente" in sistema:
            pid = re.search(r"VOCÊ É: \[([^\]]+)\]", ultimo).group(1)
            if "FASE 1 — PROPOSIÇÃO" in ultimo:
                if pid in self.personas_mudas:
                    return self._resp("não sei responder")
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
            if self.falhar_avaliador:
                raise RuntimeError("GEMINI_API_KEY inválida")
            planos = json.loads(ultimo.split("PLANOS:\n")[1])
            self.planos_vistos_pelo_avaliador = ultimo
            return self._resp(json.dumps({"avaliacoes": [{"plano": r, "notas": {"viabilidade_juridica": 3, "viabilidade_fiscal": 2,
                                                                                "impacto_para_a_populacao": 4, "ancoragem_em_evidencias": 3},
                                                          "comentario": f"fraco em {r}"} for r in planos]}))
        if "As Fases 1 a 3 JÁ ACONTECERAM" in sistema:
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
    monkeypatch.setitem(sys.modules, "litellm", litellm)
    monkeypatch.setitem(sys.modules, "markitdown", markitdown)
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
        if "anterior" in rotulo.lower():
            return RegistroFalso(llm.registro_anterior) if llm.registro_anterior else None
        return ArquivoFalso(llm.texto_relatorio)

    monkeypatch.setattr(streamlit, "file_uploader", uploader)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PAINEL_REGISTROS", str(tmp_path / "registros"))
    at = AppTest.from_file(str(APP), default_timeout=120)
    return at

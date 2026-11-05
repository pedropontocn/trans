"""Testes do modo econômico do lote (Message Batches API), com uma Batch API falsa que responde pelo modelo falso."""
import csv
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import lote  # noqa: E402
import lote_api  # noqa: E402
from test_lote import DriveFalso  # noqa: E402

MOTIVO_ANTHROPIC = {"stop": "end_turn", "length": "max_tokens", "tool_calls": "tool_use"}
TAMANHO_BUSCA = {v: k for k, v in lote_api.MAX_BUSCAS.items()}


def _partes(conteudo):
    if isinstance(conteudo, str):
        return conteudo
    return [{"type": "text", "text": b["text"], **({"cache_control": b["cache_control"]} if b.get("cache_control") else {})}
            for b in conteudo]


class BatchFalso:
    """Imita client.messages.batches: cada pedido é respondido pelo modelo falso (formato do LiteLLM), convertido de
    volta para o formato da Anthropic. Assim o teste passa pelas duas conversões."""

    def __init__(self, llm, falhar=()):
        self.llm, self.falhar = llm, set(falhar)
        self.lotes, self.pedidos = {}, []

    def _responder(self, params):
        mensagens = ([{"role": "system", "content": _partes(params["system"])}] if params.get("system") else [])
        mensagens += [{"role": m["role"], "content": _partes(m["content"])} for m in params["messages"]]
        kw = {}
        funcoes = [t for t in params.get("tools", []) if "input_schema" in t]
        busca = [t for t in params.get("tools", []) if t.get("type", "").startswith("web_search")]
        if funcoes:
            kw["tools"] = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                             "parameters": t["input_schema"]}} for t in funcoes]
            kw["tool_choice"] = "auto"
        if busca:
            kw["web_search_options"] = {"search_context_size": TAMANHO_BUSCA[busca[0]["max_uses"]]}
        r = self.llm(model="anthropic/" + params["model"], messages=mensagens, max_tokens=params["max_tokens"], **kw)
        escolha = r.choices[0]
        blocos = [{"type": "text", "text": escolha.message.content}] if escolha.message.content else []
        for c in escolha.message.tool_calls or []:
            blocos.append({"type": "tool_use", "id": "t1", "name": c.function.name, "input": json.loads(c.function.arguments)})
        return {"content": blocos, "stop_reason": MOTIVO_ANTHROPIC.get(escolha.finish_reason, "end_turn"),
                "usage": {"input_tokens": r.usage.prompt_tokens, "output_tokens": r.usage.completion_tokens,
                          "server_tool_use": {"web_search_requests": 2 if busca else 0}}}

    def create(self, requests):
        lote_id = f"lote{len(self.lotes) + 1}"
        resultados = []
        for r in requests:
            self.pedidos.append(r)
            assert set(r) == {"custom_id", "params"} and len(r["custom_id"]) <= 64
            if any(f in json.dumps(r["params"], ensure_ascii=False) for f in self.falhar):
                resultados.append({"custom_id": r["custom_id"], "result": {
                    "type": "errored", "error": {"type": "error", "error": {"type": "invalid_request_error",
                                                                             "message": "pedido inválido"}}}})
            else:
                resultados.append({"custom_id": r["custom_id"],
                                   "result": {"type": "succeeded", "message": self._responder(r["params"])}})
        self.lotes[lote_id] = resultados
        return {"id": lote_id, "processing_status": "in_progress"}

    def retrieve(self, lote_id):
        return {"id": lote_id, "processing_status": "ended"}

    def results(self, lote_id):
        return iter(reversed(self.lotes[lote_id]))          # a ordem dos resultados não é garantida

    def cancel(self, lote_id):
        pass


def pedidos_do_lote(batches, lote_id):
    ids = {r["custom_id"] for r in batches.lotes[lote_id]}
    return [p for p in batches.pedidos if p["custom_id"] in ids]


def _cliente(llm, **kw):
    batches = BatchFalso(llm, **kw)
    return NS(messages=NS(batches=batches)), batches


def test_conversao_para_o_formato_da_anthropic():
    msgs = [{"role": "system", "content": [{"type": "text", "text": "SISTEMA"}]},
            {"role": "user", "content": [{"type": "text", "text": "<material>", "cache_control": {"type": "ephemeral"}},
                                         {"type": "text", "text": "pergunta"}]},
            {"role": "assistant", "content": ""},
            {"role": "user", "content": "continue"}]
    ferramenta = {"type": "function", "function": {"name": "registrar", "description": "d",
                                                   "parameters": {"type": "object", "properties": {"x": {"type": "string"}}}}}
    p = lote_api.para_anthropic("anthropic/claude-opus-5-5", msgs, 12000, tools=[ferramenta], tool_choice="auto",
                                web_search_options={"search_context_size": "low"})
    assert p["model"] == "claude-opus-5-5" and p["max_tokens"] == 12000
    assert p["system"] == [{"type": "text", "text": "SISTEMA"}]
    assert p["messages"][0]["content"][0] == {"type": "text", "text": "<material>", "cache_control": {"type": "ephemeral"}}
    assert p["messages"][1]["content"] == "(sem texto)"
    assert p["tools"] == [{"name": "registrar", "description": "d", "input_schema": ferramenta["function"]["parameters"]},
                          {"type": "web_search_20250305", "name": "web_search", "max_uses": 1}]
    assert p["tool_choice"] == {"type": "auto"}


def test_conversao_da_resposta():
    r = lote_api.de_anthropic({
        "content": [{"type": "server_tool_use", "name": "web_search"}, {"type": "text", "text": "a"},
                    {"type": "web_search_tool_result"}, {"type": "text", "text": "b"},
                    {"type": "tool_use", "name": "registrar", "input": {"x": 1}}],
        "stop_reason": "max_tokens",
        "usage": {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 1000,
                  "cache_creation_input_tokens": 10, "server_tool_use": {"web_search_requests": 3}}})
    assert r.choices[0].message.content == "ab" and r.choices[0].finish_reason == "length"
    assert json.loads(r.choices[0].message.tool_calls[0].function.arguments) == {"x": 1}
    assert r.usage.prompt_tokens == 1110 and r.usage.cache_read_input_tokens == 1000 and r.desconto_lote


def test_fila_junta_pedidos_e_devolve_erros(llm):
    cliente, batches = _cliente(llm, falhar={"ruim"})
    fila = lote_api.FilaBatch(cliente=cliente, quieto=0.3, intervalo=0.1, log=lambda *_: None)
    from concurrent.futures import ThreadPoolExecutor
    pedidos = [{"model": "claude-sonnet-5-5", "max_tokens": 10, "messages": [{"role": "user", "content": t}]}
               for t in ("bom 1", "bom 2", "ruim")]

    def pedir(p):
        try:
            return fila.pedir(p)
        except RuntimeError as e:
            return str(e)

    with ThreadPoolExecutor(3) as ex:
        respostas = list(ex.map(pedir, pedidos))
    fila.encerrar()
    assert len(batches.lotes) == 1 and len(batches.pedidos) == 3          # os três foram no mesmo lote
    assert isinstance(respostas[0], dict) and "pedido inválido" in respostas[2]


def test_prazo_esgotado_libera_quem_espera(llm):
    cliente, batches = _cliente(llm)
    batches.retrieve = lambda lote_id: {"id": lote_id, "processing_status": "in_progress"}   # nunca termina
    fila = lote_api.FilaBatch(cliente=cliente, quieto=0.1, intervalo=0.1, prazo=time.time() + 1.5, log=lambda *_: None)
    with pytest.raises(lote_api.PrazoEsgotado):
        fila.pedir({"model": "claude-sonnet-5-5", "max_tokens": 10, "messages": [{"role": "user", "content": "x"}]})
    fila.encerrar()


def test_sessao_separada_por_fio():
    import threading
    st = lote_api.StPorFio(NS(cache_data="decorador"))
    st.session_state["uso"] = [1]
    visto = {}
    t = threading.Thread(target=lambda: visto.update(outro=dict(st.session_state)))
    t.start()
    t.join()
    assert visto["outro"] == {} and st.session_state["uso"] == [1] and st.cache_data == "decorador"


def test_lote_economico_completo(tmp_path, llm):
    cliente, batches = _cliente(llm)
    app = lote.carregar_app()
    linhas = lote.principal(["--pasta", "raiz", "--orgaos", "SEFAZ,RIOPREV,SETUR", "--rodadas", "3", "--economico",
                             "--saida", str(tmp_path), "--data-corte", "04/11/2026"],
                            drive=DriveFalso(), app=app, cliente_batch=cliente)
    assert [(x["sigla"], x["situacao"]) for x in linhas] == [("SEFAZ", "concluído"), ("RIOPREV", "concluído"),
                                                             ("SETUR", "concluído")]
    # toda chamada ao modelo passou pela Batch API
    assert len(batches.pedidos) == len(llm.chamadas) > 0
    texto = lambda r: json.dumps(r["params"], ensure_ascii=False)
    # a pesquisa de órgãos diferentes vai no mesmo lote
    def orgaos_pesquisados(lote_id):
        return {n for r in pedidos_do_lote(batches, lote_id) if "Monte a camada" in texto(r)
                for n in ("Fazenda - SEFAZ", "RIOPREV", "Turismo - SETUR") if n in texto(r)}
    assert any(len(orgaos_pesquisados(lote_id)) >= 2 for lote_id in batches.lotes)
    # as rodadas 1 e 2 de um órgão vão juntas: dois pedidos idênticos de Tension Map no mesmo lote
    assert any(len(r) != len({texto(x) for x in r}) for r in
               ([x for x in pedidos_do_lote(batches, lote_id) if "Execute o protocolo" in texto(x)] for lote_id in batches.lotes))
    registro = json.loads((tmp_path / "sefaz" / "registro.json").read_text(encoding="utf-8"))
    assert registro["uso_tokens"] and all(u["lote_api"] for u in registro["uso_tokens"])
    with open(tmp_path / "resumo.csv", encoding="utf-8-sig") as f:
        resumo = list(csv.DictReader(f, delimiter=";"))
    assert [r["sigla"] for r in resumo] == ["SEFAZ", "RIOPREV", "SETUR"]          # ordem original, apesar do paralelo
    assert (tmp_path / "dossie_estado.json").exists()


def test_custo_com_desconto_do_lote(funcoes):
    u = {"modelo": "anthropic/claude-opus-5-5", "entrada": 1_000_000, "entrada_sem_cache": 1_000_000,
         "cache_leitura": 0, "cache_escrita": 0, "saida": 1_000_000, "buscas": 100}
    assert round(funcoes.custo_estimado([u])[0], 2) == 25.00              # 4 + 20 + 1 de buscas
    assert round(funcoes.custo_estimado([dict(u, lote_api=True)])[0], 2) == 13.00   # tokens pela metade; buscas iguais

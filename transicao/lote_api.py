"""Modo econômico do lote: as chamadas aos modelos da Anthropic vão pela Message Batches API, que cobra metade do preço
dos tokens. Em troca, cada resposta demora mais: a API processa os pedidos em fila (em geral, em minutos).

Como funciona: os órgãos rodam em paralelo, cada um no seu fio de execução. Cada chamada ao modelo entra numa fila e
espera (transicao.modelo.usar_completion troca a chamada do fio pela da fila). Quando a fila fica alguns segundos sem pedidos novos, ela é enviada como um lote
(batch). Assim, cada etapa de todos os órgãos (pesquisa, diagnóstico, agentes...) vai junta no mesmo lote.
A resposta volta no formato do LiteLLM, então o resto do código não precisa saber que está em modo econômico.

Modelos que não são da Anthropic (Gemini) continuam pela chamada normal.
"""
import itertools
import json
import threading
import time
from concurrent.futures import Future
from types import SimpleNamespace as NS

# Mesmo mapeamento do LiteLLM: search_context_size -> número máximo de buscas na chamada
MAX_BUSCAS = {"low": 1, "medium": 5, "high": 10}
FERRAMENTA_BUSCA = "web_search_20250305"
MOTIVOS = {"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length", "tool_use": "tool_calls",
           "pause_turn": "stop", "refusal": "content_filter"}


def e_anthropic(modelo):
    return modelo.startswith("anthropic/") or (modelo.startswith("claude") and "/" not in modelo)


# --- CONVERSÃO: formato do LiteLLM (OpenAI) <-> formato da Anthropic ------------------------------------------------

def _blocos(conteudo):
    """Conteúdo de mensagem do LiteLLM (texto ou lista de partes) em blocos da Anthropic, mantendo o cache_control."""
    if isinstance(conteudo, str):
        return [{"type": "text", "text": conteudo}]
    blocos = []
    for parte in conteudo or []:
        if isinstance(parte, dict) and parte.get("type", "text") == "text":
            bloco = {"type": "text", "text": parte.get("text", "")}
            if parte.get("cache_control"):
                bloco["cache_control"] = dict(parte["cache_control"])
            blocos.append(bloco)
    return blocos


def para_anthropic(model, messages, max_tokens, tools=None, tool_choice=None, web_search_options=None, **_):
    """Monta o corpo de um pedido da Messages API a partir dos argumentos que o app passa ao LiteLLM."""
    params = {"model": model.split("/", 1)[1] if "/" in model else model, "max_tokens": int(max_tokens)}
    sistema, mensagens = [], []
    for m in messages:
        if m["role"] == "system":
            sistema += _blocos(m["content"])
        else:
            conteudo = m["content"]
            if isinstance(conteudo, list):
                conteudo = _blocos(conteudo)
            elif not str(conteudo or "").strip():
                conteudo = "(sem texto)"           # a API não aceita mensagem vazia
            mensagens.append({"role": m["role"], "content": conteudo})
    if sistema:
        params["system"] = sistema
    params["messages"] = mensagens
    ferramentas = []
    for t in tools or []:
        f = t.get("function", t)
        ferramentas.append({"name": f["name"], "description": f.get("description", ""),
                            "input_schema": f.get("parameters") or {"type": "object", "properties": {}}})
    if web_search_options is not None:
        tamanho = (web_search_options or {}).get("search_context_size", "medium")
        ferramentas.append({"type": FERRAMENTA_BUSCA, "name": "web_search", "max_uses": MAX_BUSCAS.get(tamanho, 5)})
    if ferramentas:
        params["tools"] = ferramentas
    if tool_choice == "auto" and tools:
        params["tool_choice"] = {"type": "auto"}
    return params


def _dict(obj):
    if obj is None or isinstance(obj, (dict, list, str, int, float)):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return dict(vars(obj))


def de_anthropic(mensagem):
    """Resposta da Anthropic (objeto do SDK ou dicionário) no formato que o app lê do LiteLLM."""
    m = _dict(mensagem) or {}
    textos, chamadas = [], []
    for bloco in m.get("content") or []:
        bloco = _dict(bloco)
        if bloco.get("type") == "text":
            textos.append(bloco.get("text") or "")
        elif bloco.get("type") == "tool_use":
            chamadas.append(NS(function=NS(name=bloco.get("name"), arguments=json.dumps(bloco.get("input") or {}))))
    u = _dict(m.get("usage")) or {}
    leitura = int(u.get("cache_read_input_tokens") or 0)
    escrita = int(u.get("cache_creation_input_tokens") or 0)
    uso = NS(prompt_tokens=int(u.get("input_tokens") or 0) + leitura + escrita,
             completion_tokens=int(u.get("output_tokens") or 0),
             cache_read_input_tokens=leitura, cache_creation_input_tokens=escrita,
             cache_creation=_dict(u.get("cache_creation")) or {}, server_tool_use=_dict(u.get("server_tool_use")) or {})
    escolha = NS(message=NS(content="".join(textos), tool_calls=chamadas or None),
                 finish_reason=MOTIVOS.get(m.get("stop_reason"), m.get("stop_reason")))
    return NS(choices=[escolha], usage=uso, desconto_lote=True)


# --- FILA -----------------------------------------------------------------------------------------------------------

class PrazoEsgotado(RuntimeError):
    pass


class FilaBatch:
    """Junta os pedidos de vários fios de execução e os envia em lotes à Message Batches API.

    quieto: segundos sem pedido novo para enviar o que está na fila. intervalo: segundos entre consultas ao andamento.
    prazo: horário (time.time()) a partir do qual nada mais espera; os pedidos em aberto recebem PrazoEsgotado."""

    def __init__(self, cliente=None, quieto=20.0, intervalo=30.0, prazo=None, log=print, maximo=2000):
        if cliente is None:
            import anthropic
            cliente = anthropic.Anthropic()
        self.cliente, self.quieto, self.intervalo, self.prazo, self.log, self.maximo = \
            cliente, quieto, intervalo, prazo, log, maximo
        self.trava = threading.Lock()
        self.pendentes = {}                 # custom_id -> (params, Future)
        self.abertos = {}                   # id do lote -> {custom_id: Future}
        self.ultimo_pedido = time.time()
        self.contador = itertools.count(1)
        self.enviados = 0
        self._parar = threading.Event()
        self._fio = threading.Thread(target=self._laco, name="fila-batch", daemon=True)
        self._fio.start()

    # chamado pelos fios dos órgãos
    def pedir(self, params):
        futuro = Future()
        with self.trava:
            cid = f"p{next(self.contador)}"
            self.pendentes[cid] = (params, futuro)
            self.ultimo_pedido = time.time()
        return futuro.result()

    def completion(self, completion_original):
        """Uma função no lugar do `completion` do LiteLLM: Anthropic vai pela fila; o resto, pela chamada normal."""
        def chamar(model, messages, max_tokens, **kw):
            if not e_anthropic(model):
                return completion_original(model=model, messages=messages, max_tokens=max_tokens, **kw)
            return de_anthropic(self.pedir(para_anthropic(model, messages, max_tokens, **kw)))
        return chamar

    def encerrar(self):
        self._parar.set()
        self._fio.join(timeout=5)

    # fio da fila
    def _laco(self):
        ultima_consulta = 0.0
        while not self._parar.is_set():
            self._parar.wait(1.0)
            agora = time.time()
            if self.prazo and agora > self.prazo:
                self._esgotar()
                continue
            with self.trava:
                enviar = self.pendentes and (agora - self.ultimo_pedido >= self.quieto
                                             or len(self.pendentes) >= self.maximo)
                lote = dict(self.pendentes) if enviar else {}
                if enviar:
                    self.pendentes.clear()
            if lote:
                self._enviar(lote)
            if self.abertos and agora - ultima_consulta >= self.intervalo:
                ultima_consulta = agora
                self._consultar()

    def _enviar(self, lote):
        try:
            criado = self.cliente.messages.batches.create(
                requests=[{"custom_id": cid, "params": params} for cid, (params, _) in lote.items()])
        except Exception as e:
            for _, futuro in lote.values():
                futuro.set_exception(RuntimeError(f"não foi possível enviar o lote: {type(e).__name__}: {e}"))
            return
        self.enviados += 1
        self.abertos[_dict(criado)["id"]] = {cid: futuro for cid, (_, futuro) in lote.items()}
        self.log(f"    lote {self.enviados} enviado: {len(lote)} pedido(s)")

    def _consultar(self):
        for lote_id in list(self.abertos):
            try:
                estado = _dict(self.cliente.messages.batches.retrieve(lote_id))
            except Exception as e:
                self.log(f"    não foi possível consultar o lote ({type(e).__name__}); tento de novo")
                continue
            if estado.get("processing_status") != "ended":
                continue
            futuros = self.abertos.pop(lote_id)
            try:
                for item in self.cliente.messages.batches.results(lote_id):
                    item = _dict(item)
                    futuro = futuros.pop(item.get("custom_id"), None)
                    if futuro is None:
                        continue
                    resultado = _dict(item.get("result")) or {}
                    if resultado.get("type") == "succeeded":
                        futuro.set_result(resultado.get("message"))
                    else:
                        erro = _dict(resultado.get("error")) or {}
                        detalhe = _dict(erro.get("error")) or erro
                        futuro.set_exception(RuntimeError(
                            f"pedido do lote {resultado.get('type')}: {detalhe.get('message') or detalhe}"[:500]))
            except Exception as e:
                for futuro in futuros.values():
                    futuro.set_exception(RuntimeError(f"não foi possível ler o resultado do lote: {e}"))
                continue
            for futuro in futuros.values():
                futuro.set_exception(RuntimeError("o lote terminou sem resultado para este pedido"))

    def _esgotar(self):
        with self.trava:
            pendentes, self.pendentes = self.pendentes, {}
        for _, futuro in pendentes.values():
            if not futuro.done():
                futuro.set_exception(PrazoEsgotado("prazo da execução esgotado antes da resposta"))
        for lote_id, futuros in list(self.abertos.items()):
            try:
                self.cliente.messages.batches.cancel(lote_id)
            except Exception:
                pass
            for futuro in futuros.values():
                if not futuro.done():
                    futuro.set_exception(PrazoEsgotado("prazo da execução esgotado antes da resposta"))
            self.abertos.pop(lote_id, None)

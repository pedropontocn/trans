"""Testes do fluxo completo: um órgão, vários órgãos e o modo econômico (Batch API falsa). Nenhuma API é chamada."""
import csv
import io
import json
import time
import zipfile
from types import SimpleNamespace as NS

import pytest

from conftest import RELATORIO, tension_map, trade_off

CFG = {"modelo_pesquisa": "anthropic/claude-haiku-5-5", "modelo_auxiliar": "anthropic/claude-sonnet-5-5",
       "modelo": "anthropic/claude-opus-5-5", "n_rodadas": 3, "parar_cedo": True, "data_corte": "04/11/2026",
       "foco": "", "orgao_emissor": "Equipe de Transição", "unidade": "", "para": ""}

MOTIVO_ANTHROPIC = {"stop": "end_turn", "length": "max_tokens", "tool_calls": "tool_use"}


def _partes(conteudo):
    if isinstance(conteudo, str):
        return conteudo
    return [{"type": "text", "text": b["text"], **({"cache_control": b["cache_control"]} if b.get("cache_control") else {})}
            for b in conteudo]


class BatchFalso:
    """Imita client.messages.batches: cada pedido é respondido pelo modelo falso e convertido para o formato da
    Anthropic, para o teste passar pelas duas conversões."""

    def __init__(self, llm, falhar=()):
        self.llm, self.falhar = llm, set(falhar)
        self.lotes, self.pedidos = {}, []

    def _responder(self, params):
        from transicao import lote_api
        tamanho = {v: k for k, v in lote_api.MAX_BUSCAS.items()}
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
            kw["web_search_options"] = {"search_context_size": tamanho[busca[0]["max_uses"]]}
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


def _cliente(llm, **kw):
    batches = BatchFalso(llm, **kw)
    return NS(messages=NS(batches=batches)), batches


def _zip(arquivos):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for nome, dados in arquivos.items():
            z.writestr(nome, dados)
    return buffer.getvalue()


def _resumo(pasta):
    with open(pasta / "resumo.csv", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f, delimiter=";"))


# --- UM ÓRGÃO -------------------------------------------------------------------------------

def test_analise_de_um_orgao_gera_o_documento_unico(llm):
    import docx
    from transicao import analise
    r = analise.analisar_orgao("Secretaria de Exemplo", RELATORIO, CFG)
    textos = [p.text for p in docx.Document(io.BytesIO(r["documento"])).paragraphs]
    for titulo in ["Sobre este documento", "Diagnóstico do órgão", "Anexo 1 – Fontes consultadas",
                   "Anexo 2 – O debate em detalhe", "Anexo 3 – Como este documento foi feito"]:
        assert titulo in textos, titulo
    reg = r["registro"]
    assert reg["tension_map"]["trade_offs"] and reg["rodadas"] == 2           # as rodadas 1 e 2 concordaram
    assert r["eventos"] and all(e["data"] for e in r["eventos"])              # só as datas conferidas
    assert reg["verificacao"]["confianca"]["nivel"] in {"baixa", "média", "alta"}
    assert r["custo"] > 0 and reg["uso_tokens"]
    # sem personas independentes nem opções de organização
    assert not hasattr(llm, "mensagem_opcoes")


def test_custo_nao_conta_chamadas_duas_vezes(llm):
    from transicao import analise
    r = analise.analisar_orgao("Secretaria de Exemplo", RELATORIO, CFG)
    assert len(r["registro"]["uso_tokens"]) == len(llm.chamadas)


def test_sem_relatorio_analisa_so_com_o_dossie(llm):
    from transicao import analise
    r = analise.analisar_orgao("Secretaria de Exemplo", "", CFG)
    assert r["registro"]["tension_map"]["trade_offs"]
    assert not hasattr(llm, "mensagem_confronto")                          # nada a confrontar


def test_dossie_insuficiente_interrompe(llm):
    from transicao import analise
    llm.falhar_pesquisa = True
    with pytest.raises(Exception):
        analise.analisar_orgao("Secretaria de Exemplo", RELATORIO, CFG)


def test_etapa_complementar_com_erro_nao_derruba_a_analise(llm, monkeypatch):
    from transicao import analise, produtos

    def quebra(*a, **k):
        raise RuntimeError("fora do ar")
    monkeypatch.setattr(produtos, "extrair_calendario", quebra)
    r = analise.analisar_orgao("Secretaria de Exemplo", RELATORIO, CFG)
    assert r["eventos"] == [] and "fora do ar" in r["registro"]["verificacao"]["problemas"][0] or r["documento"]


def test_uma_rodada_so(llm):
    from transicao import analise
    r = analise.analisar_orgao("Secretaria de Exemplo", RELATORIO, dict(CFG, n_rodadas=1))
    assert r["registro"]["rodadas"] == 1 and r["registro"]["tension_map"].get("estabilidade") is None


def test_rodadas_divergentes_sao_consolidadas(llm):
    from transicao import analise
    llm.rodadas = [tension_map([trade_off("T1", "Licitações")]), tension_map([trade_off("T9", "Outro dilema")])]
    llm.pareamento = {"pares": []}
    r = analise.analisar_orgao("Secretaria de Exemplo", RELATORIO, CFG)
    assert r["registro"]["rodadas"] == 3


# --- ENVIO E VÁRIOS ÓRGÃOS ---------------------------------------------------------------------

def test_orgaos_do_envio_por_arquivo_e_por_pasta(llm):
    from transicao import entrada
    envio = [("resumos.zip", _zip({"resumos/SETUR - Turismo.docx": b"a", "resumos/SEFAZ.pdf": b"b",
                                   "resumos/~$SEFAZ.docx": b"x", "resumos/notas.txt": b"y"}))]
    orgaos = entrada.orgaos_do_envio(envio)
    assert len(orgaos) == 2 and all(o["arquivos"] for o in orgaos)
    texto, manifesto = orgaos[0]["ler"]()
    assert "# ARQUIVO:" in texto and manifesto["lidos"]
    brutos = [("Pasta-20261104T120000Z-001.zip",
               _zip({"Raiz/Secretaria de Turismo/oficio.pdf": b"a", "Raiz/Secretaria de Turismo/Anexos/x.pdf": b"b",
                     "Raiz/Secretaria de Fazenda/relatorio.docx": b"c"}))]
    nomes = [o["nome"] for o in entrada.orgaos_do_envio(brutos, cada_pasta=True)]
    assert nomes == ["Secretaria de Fazenda", "Secretaria de Turismo"]


def test_varios_orgaos_gravam_documentos_calendario_e_resumo(llm, tmp_path):
    from transicao import analise, entrada
    envio = [("resumos.zip", _zip({"SETUR - Turismo.docx": b"a", "SEFAZ - Fazenda.pdf": b"b"}))]
    linhas = analise.rodar_orgaos(entrada.orgaos_do_envio(envio), CFG, tmp_path, log=lambda *_: None)
    assert [l["situacao"] for l in linhas] == ["concluído", "concluído"]
    assert len(list((tmp_path / "documentos").glob("*.docx"))) == 2
    assert (tmp_path / "calendario_consolidado.xlsx").exists() and (tmp_path / "LEIA-ME.txt").exists()
    assert len(list((tmp_path / "auditoria").glob("*_arquivos_lidos.json"))) == 2
    assert [r["situacao"] for r in _resumo(tmp_path)] == ["concluído", "concluído"]
    # a pesquisa do Estado é feita uma vez só
    pedidos = [json.dumps(c["mensagens"][0]["content"], ensure_ascii=False) for c in llm.chamadas]
    estado = [p for p in pedidos if "Monte a camada" in p and 'camada\\n\\"Estado\\"' in p]
    assert estado and len(set(estado)) == len(estado)          # cada grupo do Estado pesquisado uma vez só
    with zipfile.ZipFile(io.BytesIO(analise.zipar(tmp_path))) as z:
        assert "calendario_consolidado.xlsx" in z.namelist() and "resumo.csv" in z.namelist()


def test_orgao_com_erro_nao_para_os_outros(llm, tmp_path):
    from transicao import analise
    orgaos = [{"nome": "Vazio", "ler": lambda: ("", {"lidos": []})}, {"nome": "Secretaria de Exemplo", "texto": RELATORIO}]
    linhas = analise.rodar_orgaos(orgaos, CFG, tmp_path, log=lambda *_: None)
    assert [l["situacao"] for l in linhas] == ["erro", "concluído"] and "nenhum arquivo" in linhas[0]["observacao"]


def test_modo_economico_passa_tudo_pela_batch_api(llm, tmp_path):
    from transicao import analise, debate
    cliente, batches = _cliente(llm)
    orgaos = [{"nome": n, "texto": RELATORIO} for n in ("Secretaria de Turismo", "Secretaria de Fazenda")]
    linhas = analise.rodar_orgaos(orgaos, CFG, tmp_path, economico=True, cliente_batch=cliente, log=lambda *_: None)
    assert [l["situacao"] for l in linhas] == ["concluído", "concluído"]
    assert len(batches.pedidos) == len(llm.chamadas) > 0                    # toda chamada foi pela Batch API
    registro = json.loads(next((tmp_path / "auditoria").glob("secretaria_de_turismo.json")).read_text(encoding="utf-8"))
    assert all(u.get("lote_api") for u in registro["uso_tokens"])
    texto = lambda r: json.dumps(r["params"], ensure_ascii=False)
    # as rodadas 1 e 2 vão juntas: dois pedidos idênticos de Tension Map no mesmo lote
    assert any(len(r) != len({texto(x) for x in r}) for r in (
        [p for p in batches.pedidos if p["custom_id"] in {x["custom_id"] for x in lote} and "Execute o protocolo" in texto(p)]
        for lote in batches.lotes.values()))
    assert debate.RODADAS_JUNTAS is False                                    # volta ao normal depois


def test_prazo_esgotado_libera_quem_espera(llm):
    from transicao import lote_api
    cliente, batches = _cliente(llm)
    batches.retrieve = lambda lote_id: {"id": lote_id, "processing_status": "in_progress"}   # nunca termina
    fila = lote_api.FilaBatch(cliente=cliente, quieto=0.1, intervalo=0.1, prazo=time.time() + 1.5, log=lambda *_: None)
    with pytest.raises(lote_api.PrazoEsgotado):
        fila.pedir({"model": "claude-sonnet-5-5", "max_tokens": 10, "messages": [{"role": "user", "content": "x"}]})
    fila.encerrar()


def test_conversao_para_o_formato_da_anthropic():
    from transicao import lote_api
    msgs = [{"role": "system", "content": [{"type": "text", "text": "SISTEMA"}]},
            {"role": "user", "content": [{"type": "text", "text": "<material>", "cache_control": {"type": "ephemeral"}},
                                         {"type": "text", "text": "pergunta"}]},
            {"role": "assistant", "content": ""},
            {"role": "user", "content": "continue"}]
    ferramenta = {"type": "function", "function": {"name": "registrar", "description": "d",
                                                   "parameters": {"type": "object", "properties": {"x": {"type": "string"}}}}}
    p = lote_api.para_anthropic("anthropic/claude-opus-5-5", msgs, 12000, tools=[ferramenta], tool_choice="auto",
                                web_search_options={"search_context_size": "low"})
    assert p["model"] == "claude-opus-5-5" and p["system"] == [{"type": "text", "text": "SISTEMA"}]
    assert p["messages"][1]["content"] == "(sem texto)" and p["tool_choice"] == {"type": "auto"}
    r = lote_api.de_anthropic({
        "content": [{"type": "text", "text": "a"}, {"type": "tool_use", "name": "registrar", "input": {"x": 1}}],
        "stop_reason": "max_tokens", "usage": {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 1000,
                                               "cache_creation_input_tokens": 10}})
    assert r.choices[0].finish_reason == "length" and r.usage.prompt_tokens == 1110 and r.desconto_lote


def test_custo_com_desconto_do_lote(funcoes):
    u = {"modelo": "anthropic/claude-opus-5-5", "entrada": 1_000_000, "entrada_sem_cache": 1_000_000,
         "cache_leitura": 0, "cache_escrita": 0, "saida": 1_000_000, "buscas": 100}
    assert round(funcoes.custo_estimado([u])[0], 2) == 25.00
    assert round(funcoes.custo_estimado([dict(u, lote_api=True)])[0], 2) == 13.00


# --- DOSSIÊ ENVIADO PELA EQUIPE ---------------------------------------------------------------------

DOSSIE_PERPLEXITY = """# Dossiê – Secretaria de Exemplo

### Fato
- **Afirmação:** A LOA 2026 da Secretaria é de R$ 412.000.000,00.
- **Tema:** Orçamento e execução
- **Fonte:** LOA 2026
- **Data da fonte:** 01/2026
- **Link:** [LOA 2026](https://transparencia.exemplo.gov.br/loa-sex)
- **Trecho literal:** "LOA 2026 da Secretaria de Exemplo:
  R$ 412.000.000,00"
- **Tipo:** documento oficial

### Fato
- Afirmação: Quatro concorrências estão adiadas, somando R$ 120,5 milhões.
- Tema: Contratos e convênios
- Fonte: Painel de compras
- Data: 10/2026
- Link: https://transparencia.exemplo.gov.br/licitacoes
- Trecho literal: Quatro concorrências estão adiadas sine die, somando R$ 120.500.000,00
- Tipo: dado oficial

### Fato
- Afirmação: O TCE-RJ apontou atraso na prestação de contas de convênios.
- Tema: Controle (TCE, MP) e judicialização
- Fonte: TCE-RJ
- Link: https://tce.exemplo.gov.br/decisao-123
- Trecho literal: frase que não está na página
- Tipo: decisão de controle

### Fato
- Afirmação: O governo eleito promete reduzir o número de secretarias.
- Tema: Compromissos do governo eleito
- Fonte: Jornal Exemplo
- Link: https://jornal.exemplo/materia
- Trecho literal: Governo eleito promete reduzir o número de secretarias
- Tipo: declaração política

### Fato
- Afirmação: A Secretaria tem 1.200 servidores efetivos.
- Tema: Pessoal
- Fonte: sem link
- Tipo: dado oficial

## Procurado e não encontrado
- Número de terceirizados nos contratos de custeio
- Organograma atualizado
"""


def test_dossie_enviado_e_lido_e_conferido(llm):
    from transicao import pesquisa
    d = pesquisa.dossie_enviado(DOSSIE_PERPLEXITY, "Secretaria de Exemplo", "04/11/2026")
    por_bloco = {i["bloco"]: i for i in d["itens"]}
    assert len(d["itens"]) == 5 and set(por_bloco) >= {"orcamento_execucao", "contratos_convenios",
                                                        "controle_judicializacao", "compromissos_governo", "pessoal"}
    assert por_bloco["orcamento_execucao"]["checagem"] == "conferido"          # trecho em duas linhas, link em Markdown
    assert por_bloco["contratos_convenios"]["checagem"] == "conferido"
    assert por_bloco["controle_judicializacao"]["checagem"] == "trecho_nao_encontrado"
    assert por_bloco["pessoal"]["checagem"] == "sem_trecho"
    assert por_bloco["compromissos_governo"]["camada"] == "estado"
    assert por_bloco["compromissos_governo"]["tipo_fonte"] == "declaracao_politica"
    assert por_bloco["controle_judicializacao"]["tipo_fonte"] == "decisao_controle_judicial"
    assert [n["procurado"] for n in d["nao_encontrado"]] == ["Número de terceirizados nos contratos de custeio",
                                                             "Organograma atualizado"]
    assert {i["id"][0] for i in d["itens"]} == {"E", "O"}


def test_dossies_casam_com_os_orgaos_pelo_nome(llm):
    from transicao import entrada
    orgaos = [{"nome": n} for n in ("Secretaria de Estado das Cidades - SECID", "SETUR - Turismo", "SEFAZ")]
    dossies = entrada.dossies_do_envio([("dossies.zip", _zip({
        "Dossiê - SECID.md": b"x", "Dossie Secretaria de Turismo.pdf": b"y", "Dossiê SEEDUC.docx": b"z",
        "~$lixo.docx": b"", "notas.xlsx": b""}))])
    sobrando = entrada.casar_dossies(orgaos, dossies)
    assert [o.get("dossie_arquivo") for o in orgaos] == ["Dossiê - SECID.md", "Dossie Secretaria de Turismo.pdf", None]
    assert [d["arquivo"] for d in sobrando] == ["Dossiê SEEDUC.docx"]
    assert orgaos[0]["ler_dossie"]() == "x"


def test_com_dossie_enviado_o_app_nao_pesquisa(llm, tmp_path):
    from transicao import analise
    orgaos = [{"nome": "Secretaria de Exemplo", "texto": RELATORIO, "ler_dossie": lambda: DOSSIE_PERPLEXITY}]
    linhas = analise.rodar_orgaos(orgaos, CFG, tmp_path, log=lambda *_: None)
    assert linhas[0]["situacao"] == "concluído" and linhas[0]["dossie"] == "enviado"
    assert not any("Monte a camada" in json.dumps(c["mensagens"], ensure_ascii=False) for c in llm.chamadas)
    assert _resumo(tmp_path)[0]["dossie"] == "enviado"


def test_dossie_fora_do_formato_avisa(llm, tmp_path):
    from transicao import analise
    orgaos = [{"nome": "Secretaria de Exemplo", "texto": RELATORIO, "ler_dossie": lambda: "Texto corrido sem fatos."}]
    linhas = analise.rodar_orgaos(orgaos, CFG, tmp_path, log=lambda *_: None)
    assert linhas[0]["situacao"] == "erro" and "formato" in linhas[0]["observacao"]

"""Testes do fluxo completo: um órgão, vários órgãos e o modo econômico (Batch API falsa). Nenhuma API é chamada."""
import csv
import io
import json
import time
import zipfile
from types import SimpleNamespace as NS

import pytest

from conftest import RELATORIO

CFG = {"modelo_pesquisa": "anthropic/claude-haiku-5-5", "modelo_auxiliar": "anthropic/claude-sonnet-5-5",
       "modelo": "anthropic/claude-opus-5-5", "data_corte": "04/11/2026",
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

def test_analise_de_uma_secretaria_gera_o_documento_curto(llm):
    import docx
    from transicao import analise
    r = analise.analisar_orgao("Secretaria de Exemplo", RELATORIO, CFG)
    # produto 2: o dossiê da secretaria, atualizado com o que ela informou
    textos = [p.text for p in docx.Document(io.BytesIO(r["dossie_docx"])).paragraphs]
    for titulo in ["Panorama", "Ficha rápida", "1. O que faz", "2. Como se organiza", "3. Programas e ações",
                   "4. Principais contratos", "5. Pessoal", "6. Orçamento", "7. Pendências com controle e justiça",
                   "8. Sistemas, convênios e parcerias", "Anexo – Fontes"]:
        assert titulo in textos, titulo
    # o organograma em árvore, em fonte fixa, só com as unidades conferidas
    assert "│   └── Subsecretaria de Obras (SUBOB) — vago" in textos and "│       └── Superintendência de Projetos" in textos
    assert "└── Vinculadas" in textos and "    └── EMOP" in textos
    assert not any("Inventada" in t for t in textos)
    # riscos, confronto e cobertura não ficam no dossiê: vão para o relatório de riscos e a auditoria
    for fora in ("Riscos por prioridade", "6. Cobertura do checklist obrigatório",
                 "5. O que a secretaria informou e o que as fontes mostram"):
        assert fora not in textos, fora
    assert not any(t.startswith(("Riscos por prioridade", "Sobre este documento", "Anexo 3")) for t in textos)
    # produto 3: o relatório de riscos, focado nas decisões urgentes, sem anexo
    riscos_txt = [p.text for p in docx.Document(io.BytesIO(r["riscos_docx"])).paragraphs]
    for titulo in ["Situação", "Decisões urgentes, em ordem de prazo", "Informações que faltam"]:
        assert titulo in riscos_txt, titulo
    assert not any(t.startswith(("1. Contratos", "Anexo")) for t in riscos_txt)
    # produto 5: a auditoria é só o registro JSON, com a versão legível dentro dele
    assert "auditoria_docx" not in r
    for titulo in ["Revisão dos agentes, risco a risco", "Todas as fontes do dossiê", "Anexo 3 – Como este documento foi feito"]:
        assert titulo in r["registro"]["auditoria_md"], titulo
    md = r["dossie_md"]
    assert md.index("## Panorama") < md.index("## 1. O que faz") < md.index("## 4. Principais contratos") < md.index("## Anexo")
    assert "| LOA 2026 | R$ 412 mi |" in md and "| Empenhado | R$ 398,75 mi |" in md and "Inventado" not in md
    assert "| Contrato 99/2026 |" in md and "Contrato 7/2025" not in md and "Contrato sem origem" not in md
    auditoria = r["registro"]["auditoria_md"]                   # o confronto e a cobertura ficam na auditoria
    assert "**As fontes mostram:**" in auditoria or "Não mencionado pela secretaria" in auditoria
    assert "Cobertura" in auditoria and "## Organograma completo" in auditoria
    assert "Anexo 3 – Como este documento foi feito" in r["registro"]["metodo_md"]       # o método fica na auditoria
    reg = r["registro"]
    assert len(reg["revisoes_dos_agentes"]) == 6 and r["agentes"] == 6                 # cinco olhares e o advogado do diabo
    assert sorted(llm.agentes_vistos) == sorted(p[1] for p in __import__("transicao.riscos", fromlist=["x"]).PAPEIS)
    assert "Fazenda e orçamento" in llm.pedido_consolidacao or "teme" in llm.pedido_consolidacao
    riscos = reg["riscos"]["riscos"]
    assert riscos[0]["titulo"] == "Licitações adiadas" and riscos[0]["firmeza"] != "sem comprovação"
    inventado = next(x for x in riscos if x["titulo"] == "Risco inventado")
    assert inventado["firmeza"] == "sem comprovação" and inventado["fatos_invalidos"] == ["F99"]
    assert inventado["prioridade"] in ("Média", "Baixa")                               # sem base, no máximo Média
    assert inventado["revisao"]["contestado"] and inventado["revisao"]["sem_objecao"] == 0     # 5 exageros + 1 contestação
    assert riscos[0]["revisao"] == {"origem": "análise", "objecoes": [], "agentes": 6, "sem_objecao": 6, "contestado": False}
    assert reg["modelos"]["neutralidade"] == CFG["modelo_auxiliar"] and len(reg["modelos"]["agentes"]) == 6
    # o olhar de cada agente fica no registro (visões montadas do que o agente disse, não da paráfrase)
    assert reg["riscos"]["decisoes"] == []                 # sem opções nem caminhos: o relatório não sugere
    assert "revisao_do_texto" in reg["verificacao"] and "Revisão de tom" in r["riscos_md"]
    # a revisão do texto reescreveu o ponto de decisão no tom de análise (sem listar caminhos)
    assert "Destino das licitações adiadas" in r["riscos_md"] and "Retomar ou cancelar" not in r["riscos_md"]
    assert reg["verificacao"]["revisao_do_texto"]["aceitos"][0]["campo"].endswith(".decisao")
    assert "Advogado do diabo contesta: o risco inventado não tem fato no material" in r["riscos_md"]
    assert "- Fazenda e orçamento vê exagero: sem base" in r["auditoria_md"]
    # votação item a item: seis votantes; o código apurou impacto, janela e repercussão de cada risco
    assert sorted(llm.votantes) == sorted(p[1] for p in __import__("transicao.riscos", fromlist=["x"]).PAPEIS)
    r1 = next(x for x in riscos if x["titulo"] == "Licitações adiadas")
    assert r1["votos"]["impacto"]["nivel"] == "Alto" and r1["votos"]["impacto"]["votos"] == 6
    assert r1["votos"]["sensibilidade"]["nivel"] == "Alta" and r1["votos"]["sensibilidade"]["votos"] == 5
    assert r1["votos"]["sensibilidade"]["divergencia"][0]["papel"] == "Fazenda e orçamento"   # votou Baixa: 2 níveis longe
    assert "Alta 5/6 ⚠" in r["riscos_md"] and "Divergência: Fazenda e orçamento vê sensibilidade baixa" in r["riscos_md"]
    assert reg["votacao_dos_agentes"] and len(reg["votacao_dos_agentes"]) == 6
    # a consolidação falsa não informa id_anterior: o casamento é pelo título
    assert all(x["revisao"]["agentes"] == 6 for x in riscos)
    assert "[F" in llm.material_riscos and "DIAGNÓSTICO:" in llm.material_riscos
    assert reg["verificacao"]["neutralidade"]["recomendacoes_implicitas"][0]["trecho"].startswith("Retomar")
    assert r["custo"] > 0 and r["riscos"][0]["orgao"] == "Secretaria de Exemplo"


def test_custo_nao_conta_chamadas_duas_vezes(llm):
    from transicao import analise
    r = analise.analisar_orgao("Secretaria de Exemplo", RELATORIO, CFG)
    assert len(r["registro"]["uso_tokens"]) == len(llm.chamadas)


def test_sem_relatorio_analisa_so_com_o_dossie(llm):
    from transicao import analise
    r = analise.analisar_orgao("Secretaria de Exemplo", "", CFG)
    assert r["registro"]["riscos"]["riscos"]
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
    assert r["eventos"] == [] and "fora do ar" in r["registro"]["verificacao"]["problemas"][0] or r["dossie_docx"]


def test_agente_fora_do_ar_nao_derruba_a_analise(llm):
    from transicao import analise
    llm.agentes_que_falham = {"Operação e servidores"}
    r = analise.analisar_orgao("Secretaria de Exemplo", RELATORIO, CFG)
    assert r["agentes"] == 5 and "5 agentes de IA" in r["riscos_md"]
    assert "sem resposta: Operação e servidores" in r["registro"]["metodo_md"]


def test_analise_sem_riscos_legiveis_para(llm):
    from transicao import analise
    llm.analise_riscos = {"situacao": [], "riscos": []}
    with pytest.raises(analise.ErroAnalise):
        analise.analisar_orgao("Secretaria de Exemplo", RELATORIO, CFG)


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
    assert len(list((tmp_path / "dossies").glob("*_dossie.docx"))) == 2
    assert len(list((tmp_path / "riscos").glob("*_riscos.docx"))) == 2
    assert not list((tmp_path / "auditoria").glob("*.docx"))                        # auditoria só em JSON
    assert len(list((tmp_path / "calendarios").glob("*_calendario.xlsx"))) == 2 and (tmp_path / "LEIA-ME.txt").exists()
    assert len(list((tmp_path / "paineis").glob("*_painel.json"))) == 2
    assert not (tmp_path / "calendario_consolidado.xlsx").exists() and not (tmp_path / "painel_estadual.docx").exists()
    assert len(list((tmp_path / "auditoria").glob("*_arquivos_lidos.json"))) == 2
    assert [r["situacao"] for r in _resumo(tmp_path)] == ["concluído", "concluído"]
    # a pesquisa do Estado é feita uma vez só
    pedidos = [json.dumps(c["mensagens"][0]["content"], ensure_ascii=False) for c in llm.chamadas]
    estado = [p for p in pedidos if "Monte a camada" in p and 'camada\\n\\"Estado\\"' in p]
    assert estado and len(set(estado)) == len(estado)          # cada grupo do Estado pesquisado uma vez só
    with zipfile.ZipFile(io.BytesIO(analise.zipar(tmp_path))) as z:
        assert any(n.startswith("calendarios/") for n in z.namelist()) and "resumo.csv" in z.namelist()
        assert any(n.startswith("paineis/") for n in z.namelist())


def test_orgao_com_erro_nao_para_os_outros(llm, tmp_path):
    from transicao import analise
    orgaos = [{"nome": "Vazio", "ler": lambda: ("", {"lidos": []})}, {"nome": "Secretaria de Exemplo", "texto": RELATORIO}]
    linhas = analise.rodar_orgaos(orgaos, CFG, tmp_path, log=lambda *_: None)
    assert [l["situacao"] for l in linhas] == ["erro", "concluído"] and "nenhum arquivo" in linhas[0]["observacao"]


def test_modo_economico_passa_tudo_pela_batch_api(llm, tmp_path):
    from transicao import analise
    cliente, batches = _cliente(llm)
    orgaos = [{"nome": n, "texto": RELATORIO} for n in ("Secretaria de Turismo", "Secretaria de Fazenda")]
    linhas = analise.rodar_orgaos(orgaos, CFG, tmp_path, economico=True, cliente_batch=cliente, log=lambda *_: None)
    assert [l["situacao"] for l in linhas] == ["concluído", "concluído"]
    assert len(batches.pedidos) == len(llm.chamadas) > 0                    # toda chamada foi pela Batch API
    registro = json.loads(next((tmp_path / "auditoria").glob("secretaria_de_turismo.json")).read_text(encoding="utf-8"))
    assert all(u.get("lote_api") for u in registro["uso_tokens"])
    texto = lambda r: json.dumps(r["params"], ensure_ascii=False)
    # os cinco agentes de uma secretaria vão no mesmo lote
    assert any(sum("Você revisa a análise de riscos" in texto(p) for p in batches.pedidos
                   if p["custom_id"] in {x["custom_id"] for x in lote}) >= 5 for lote in batches.lotes.values())
    assert analise.JUNTAS is False                                           # volta ao normal depois
    assert list((tmp_path / "paineis").glob("*_painel.json"))


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

CONSOLIDACAO = """# Consolidação estadual
| Sigla | Secretaria | Fim futuro |
|---|---|---|
| SEX | Secretaria de Estado de Exemplo | 3 |
"""
REDUZIDO = """# Dossiê reduzido — Secretaria de Exemplo (SEX)

## 3. Investimentos e contratos
| Indicador | Valor |
|---|---|
| Contratos com data de fim futura (SIGA/PNCP) | 3 contratos, R$ 30,0 mi |
| Vencem em até 30 dias | 1 contratos, R$ 10,0 mi |

## 4. Indicadores críticos
| Indicador | Valor | Meta | Status |
|---|---|---|---|
| Contratos sem fiscal/gestor designado | Não consta no SIGA | 0 | Solicitar à secretaria |

## 5. Alertas vermelhos
- 1 contrato(s) vencem em até 30 dias (R$ 10,0 mi).
- 2 contrato(s) com fornecedor em recuperação judicial.
- O TCE-RJ apontou atraso. [TCE](https://tce.exemplo.gov.br/decisao-123)
"""
PESQUISA = """# Pesquisa aprofundada — SEX

Gerada pela equipe.

### Alertas vermelhos
- **Licitações:** quatro concorrências estão adiadas, somando R$ 120.500.000,00. [Painel de compras](https://transparencia.exemplo.gov.br/licitacoes)
O Tribunal apontou atraso na prestação de contas de convênios da Secretaria. [TCE-RJ: decisão](https://tce.exemplo.gov.br/decisao-123)

### Contratos e serviços críticos
- A Secretaria tem 9.999 servidores em greve. [Jornal](https://jornal.exemplo/materia)
- **TCE-RJ:** nada encontrado nas fontes consultadas sobre decisões recentes. [Jornal](https://jornal.exemplo/materia)

### Lacunas da pesquisa
- Número de terceirizados nos contratos de custeio. [Jornal](https://jornal.exemplo/materia)

### Fontes consultadas
1. [Painel de compras](https://transparencia.exemplo.gov.br/licitacoes) — 2026-10-14
"""
CONTRATOS = ("\ufeffcontratacao;fornecedor;objeto;fim;dias_para_vencer;valor;valor_atualizado;flag_emerg;url_pncp;"
             "fonte_vigencia;a_pagar_liquidado\n"
             "2025000001;OBRAS ALFA LTDA;PAVIMENTAÇÃO DE VIAS;20/11/2026;14;10000000.0;10000000.0;False;"
             "https://pncp.gov.br/app/contratos/1;PNCP (1 termo(s)): https://pncp.gov.br/app/contratos/1;0.0\n"
             "2025000002;LIMPEZA BETA LTDA;LIMPEZA PREDIAL;15/03/2027;129;20000000.0;20000000.0;True;;SIGA;150000.0\n")


def _pacote():
    return [("Transicao_RJ_dossies.zip", _zip({
        "dossies/00_CONSOLIDACAO_ESTADUAL.md": CONSOLIDACAO, "dossies/SEX.md": REDUZIDO,
        "dossies_automaticos/pesquisas/SEX_pesquisa.md": PESQUISA,
        "dossies_automaticos/dados_vencimentos/SEX_vencimentos_180d.csv": CONTRATOS.encode("utf-8"),
        "dossies_automaticos/DOSSIE_SEX.md": "# completo", "dossies_automaticos/PAINEL_URGENCIAS.md": "x",
        "dossies_automaticos/vencimentos_180d_estado.csv": "x", "README.md": "x",
        "referencia/REVISAO_QUALIDADE.md": "x"}))]


def test_pacote_de_dossies_e_lido_por_sigla(llm):
    from transicao import entrada
    dossies = entrada.dossies_do_envio(_pacote())
    assert [d["orgao"] for d in dossies] == ["Secretaria de Estado de Exemplo - SEX"]
    assert sorted(dossies[0]["partes"]) == ["pesquisa"]          # planilha do SIGA e painel do SIGA/PNCP: ignorados
    orgaos = [{"nome": "SEX - Exemplo"}, {"nome": "Secretaria de Estado de Exemplo"}, {"nome": "SEFAZ"}]
    assert entrada.casar_dossies(orgaos, dossies) == []
    assert [bool(o.get("ler_dossie")) for o in orgaos] == [True, False, False]       # cada dossiê casa uma vez
    textos = orgaos[0]["ler_dossie"]()
    assert set(textos) == {"pesquisa"} and textos["pesquisa"].startswith("# Pesquisa")


def test_dossie_enviado_confere_links_e_numeros(llm):
    from transicao import pesquisa
    d = pesquisa.dossie_enviado({"pesquisa": PESQUISA, "dossie": REDUZIDO, "contratos": CONTRATOS},
                                "Secretaria de Estado de Exemplo - SEX", "06/11/2026")
    web = {i["url"].split("/")[-1]: i for i in d["itens"] if not i.get("conferido_pela_equipe")}
    assert web["licitacoes"]["checagem"] == "conferido" and web["licitacoes"]["conferencia"] == "numeros"
    assert web["licitacoes"]["afirmacao"].startswith("Licitações: quatro") and web["licitacoes"]["data_fonte"] == "14/10/2026"
    assert web["licitacoes"]["tipo_fonte"] == "documento_oficial"
    assert web["decisao-123"]["checagem"] == "sem_trecho"                         # parágrafo sem número: não conferido
    assert web["materia"]["checagem"] == "trecho_nao_encontrado"                  # o número não está na página
    # o painel do SIGA/PNCP e a planilha de vencimentos não entram, mesmo se vierem
    assert not any(i.get("conferido_pela_equipe") for i in d["itens"]) and "contratos" not in d
    assert not any("2025000001" in i["afirmacao"] or "Vencem em até 30 dias" in i["afirmacao"] for i in d["itens"])
    assert {n["procurado"][:12] for n in d["nao_encontrado"]} == {"TCE-RJ: nada", "Número de te"}


def test_com_dossie_enviado_o_app_nao_pesquisa_o_orgao(llm, tmp_path):
    import docx
    from transicao import analise
    partes = {"pesquisa": PESQUISA, "dossie": REDUZIDO, "contratos": CONTRATOS}
    orgaos = [{"nome": "Secretaria de Exemplo", "texto": RELATORIO, "ler_dossie": lambda: partes}]
    linhas = analise.rodar_orgaos(orgaos, CFG, tmp_path, log=lambda *_: None)
    assert linhas[0]["situacao"] == "concluído" and linhas[0]["dossie"] == "enviado"
    pedidos = [json.dumps(c["mensagens"][0]["content"], ensure_ascii=False) for c in llm.chamadas]
    assert not any("Monte a camada" in p and 'camada\\n\\"Estado\\"' not in p for p in pedidos)   # só o Estado
    texto = "\n".join(p.text for p in docx.Document(next((tmp_path / "dossies").glob("*_dossie.docx"))).paragraphs)
    assert "4. Principais contratos" in texto and "Cobertura do checklist obrigatório" not in texto
    import openpyxl
    calendarios = list((tmp_path / "calendarios").glob("*_calendario.xlsx"))
    celulas = [str(c.value) for f in calendarios for ws in openpyxl.load_workbook(f).worksheets
               for linha in ws.iter_rows() for c in linha]
    assert not any("2025000001" in v for v in celulas)            # contrato do SIGA/PNCP: fora por padrão
    registro = json.loads(next((tmp_path / "auditoria").glob("secretaria_de_exemplo.json")).read_text(encoding="utf-8"))
    fora = [i for i in registro["dossie"]["itens"] if i.get("fora_por")]
    assert fora and all(i["bloco"] == "contratos_convenios" for i in fora)
    material = " ".join(json.dumps(c["mensagens"], ensure_ascii=False) for c in llm.chamadas)
    assert "2025000001" not in material                            # nem chega ao modelo


def test_dossie_sem_fatos_avisa(llm, tmp_path):
    from transicao import analise
    orgaos = [{"nome": "Secretaria de Exemplo", "texto": RELATORIO, "ler_dossie": lambda: {"pesquisa": "Texto corrido."}}]
    linhas = analise.rodar_orgaos(orgaos, CFG, tmp_path, log=lambda *_: None)
    assert linhas[0]["situacao"] == "erro" and "dossiê insuficiente" in linhas[0]["observacao"]


def test_dados_do_painel_de_cada_secretaria(llm, tmp_path):
    from transicao import analise
    orgaos = [{"nome": n, "texto": RELATORIO} for n in ("Secretaria de Exemplo - SEX", "Secretaria de Ypsilon - SEY")]
    linhas = analise.rodar_orgaos(orgaos, CFG, tmp_path, log=lambda *_: None)
    assert [l["situacao"] for l in linhas] == ["concluído", "concluído"] and linhas[0]["riscos"] == 2
    assert sorted(p.name for p in (tmp_path / "paineis").iterdir()) == [
        "secretaria_de_exemplo_sex_painel.json", "secretaria_de_ypsilon_sey_painel.json"]
    dados = json.loads((tmp_path / "paineis" / "secretaria_de_exemplo_sex_painel.json").read_text(encoding="utf-8"))
    assert dados["sigla"] == "SEX" and len(dados["pontos_de_decisao"]) == 2 and sum(dados["janelas"].values()) == 2
    p1 = dados["pontos_de_decisao"][0]
    assert {"decisao", "horizonte", "agir_ate", "sensibilidade", "prioridade", "votos"} <= set(p1)
    assert "quem_decide" not in p1
    # a repercussão política vem da votação dos seis agentes: R1 teve 5 votos "Alta" (Fazenda votou Baixa)
    assert any(p["votos"]["sensibilidade"]["nivel"] == "Alta" and p["votos"]["sensibilidade"]["contagem"]["Alta"] == 5
               for p in dados["pontos_de_decisao"])
    assert not hasattr(llm, "pedido_temas") and "paineis/" in (tmp_path / "LEIA-ME.txt").read_text(encoding="utf-8")


def test_dossie_casado_pelo_conteudo_quando_o_nome_do_arquivo_nao_diz(llm):
    from transicao import entrada
    orgaos = entrada.orgaos_do_envio([("TRANSIÇÃO.docx", b"x")])        # o texto (falso) fala da "Secretaria de Exemplo (SEX)"
    dossies = entrada.dossies_do_envio(_pacote())
    sobrando = entrada.casar_dossies(orgaos, dossies)
    assert sobrando == [] and orgaos[0]["nome"] == "Secretaria de Estado de Exemplo - SEX"
    assert orgaos[0]["ler_dossie"]()["pesquisa"].startswith("# Pesquisa")
    outros = entrada.orgaos_do_envio([("TRANSIÇÃO.docx", b"x")])
    llm.texto_relatorio = "Relatório sem nome de secretaria."
    from transicao import entrada as e2
    e2.converter_arquivo.cache_clear()
    assert len(e2.casar_dossies(outros, e2.dossies_do_envio(_pacote()))) == 1      # sem pista: não liga


def test_planilha_excel_entra_como_documento_da_secretaria(llm):
    from transicao import entrada
    orgaos = entrada.orgaos_do_envio([("docs.zip", _zip({"SECID.docx": b"a", "SECID.xlsx": b"b", "SES.xls": b"c",
                                                         "notas.txt": b"d"}))])
    assert {o["nome"]: sorted(o["arquivos"]) for o in orgaos} == {"SECID": ["SECID.docx", "SECID.xlsx"], "SES": ["SES.xls"]}
    texto, manifesto = orgaos[0]["ler"]()
    assert texto.count("# ARQUIVO:") == 2 and len(manifesto["lidos"]) == 2


def test_rodar_de_novo_na_mesma_pasta_pula_os_prontos(llm, tmp_path):
    import docx
    from transicao import analise
    orgaos = [{"nome": n, "texto": RELATORIO} for n in ("Secretaria de Exemplo - SEX", "Secretaria de Ypsilon - SEY")]
    llm.texto_relatorio = RELATORIO
    linhas = analise.rodar_orgaos(orgaos, CFG, tmp_path, log=lambda *_: None)
    assert [l["situacao"] for l in linhas] == ["concluído", "concluído"]
    assert set(analise.prontos(tmp_path)) == {"Secretaria de Exemplo - SEX", "Secretaria de Ypsilon - SEY"}
    chamadas_antes = len(llm.chamadas)
    # simula a queda: o segundo órgão não terminou (sem resultado gravado) e o painel se perdeu
    (tmp_path / "auditoria" / "secretaria_de_ypsilon_sey_resultado.json").unlink()
    (tmp_path / "paineis" / "secretaria_de_exemplo_sex_painel.json").unlink()
    (tmp_path / "calendarios" / "secretaria_de_exemplo_sex_calendario.xlsx").unlink()
    registros = []
    linhas2 = analise.rodar_orgaos(orgaos, CFG, tmp_path, log=registros.append)
    assert [l["situacao"] for l in linhas2] == ["concluído", "concluído"]
    assert any("já estava pronto" in r and "SEX" in r for r in registros)
    pedidos_sex = [c for c in llm.chamadas[chamadas_antes:] if "Secretaria de Exemplo" in str(c["mensagens"])]
    assert not any("Você é analista de riscos" in str(c["mensagens"][0]["content"]) for c in pedidos_sex)
    # o painel e o calendário de quem estava pronto foram remontados por código, sem chamar o modelo
    dados = json.loads((tmp_path / "paineis" / "secretaria_de_exemplo_sex_painel.json").read_text(encoding="utf-8"))
    assert dados["sigla"] == "SEX" and dados["pontos_de_decisao"]
    import openpyxl
    for sigla in ("exemplo_sex", "ypsilon_sey"):
        planilha = openpyxl.load_workbook(tmp_path / "calendarios" / f"secretaria_de_{sigla}_calendario.xlsx")
        assert planilha.sheetnames[0] == "Prioridades"
    # sem retomar, refaz tudo; e um resultado de outra versão do app não é reaproveitado
    linhas3 = analise.rodar_orgaos(orgaos[:1], CFG, tmp_path, log=lambda *_: None, retomar=False)
    assert linhas3[0]["situacao"] == "concluído" and not any("já estava pronto" in r for r in registros[-1:])

    caminho = tmp_path / "auditoria" / "secretaria_de_exemplo_sex_resultado.json"
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    caminho.write_text(json.dumps(dict(dados, versao="0.0")), encoding="utf-8")
    assert analise.resultado_pronto(tmp_path, "secretaria_de_exemplo_sex") is None


def test_folha_da_seplag_entra_no_dossie_da_secretaria(llm):
    from transicao import analise
    r = analise.analisar_orgao("Secretaria de Estado das Cidades - SECID", RELATORIO, CFG)
    itens = [i for i in r["registro"]["dossie"]["itens"] if i["fonte"].startswith("Caderno de RH")]
    assert len(itens) == 2 and all(i["url"].startswith("https://www.rj.gov.br/gesperj/") for i in itens)
    assert "| 145 | 0 | 145 (100,0%) | R$ 1,17 mi |" in r["dossie_md"]
    c9 = next(c for c in r["registro"]["checklist"] if c["id"] == "C9")
    assert c9["estado"] == "encontrado"


def test_json_invalido_na_analise_e_pedido_de_novo_e_o_erro_diz_o_motivo(llm):
    from transicao import analise
    llm.analises_quebradas = 1                     # a primeira resposta vem quebrada; a segunda, certa
    r = analise.analisar_orgao("Secretaria de Exemplo", RELATORIO, CFG)
    assert r["riscos"] and any("pedindo só o JSON" in u["etapa"] for u in r["registro"]["uso_tokens"])
    llm.analises_quebradas = 2                     # as duas quebradas: o erro diz o motivo e mostra o começo
    import pytest
    with pytest.raises(analise.ErroAnalise) as erro:
        analise.analisar_orgao("Secretaria de Exemplo", RELATORIO, CFG)
    assert "motivo de parada: stop / stop" in str(erro.value) and "Pregão" in str(erro.value)


def test_antes_de_ler_abre_dossie_e_relatorio(llm):
    from transicao import analise
    manifesto = {"cortados": [{"arquivo": "Controle.xlsx", "caracteres": 93411, "usados": 60000}]}
    r = analise.analisar_orgao("Secretaria de Exemplo", RELATORIO, CFG, manifesto=manifesto)
    for md in (r["dossie_md"], r["riscos_md"]):
        assert md.startswith("## Antes de ler\n- **O que é:**")
        assert "**Confiança desta análise:" in md and "Controle.xlsx (60 de 93 mil caracteres lidos)" in md
    assert "sem revisão da equipe: confira antes de usar" not in r["riscos_md"].split("## Situação")[1]   # não repete no fim


def test_pesquisa_do_estado_e_reaproveitada_no_mesmo_dia(llm, tmp_path):
    from transicao import analise
    orgaos = [{"nome": "Secretaria de Exemplo - SEX", "texto": RELATORIO}]
    registros = []
    analise.rodar_orgaos(orgaos, CFG, tmp_path / "a", log=registros.append)
    pedidos_estado = lambda: sum('camada\n"Estado"' in c["mensagens"][0]["content"] for c in llm.chamadas)
    antes = pedidos_estado()
    assert antes > 0 and not any("reaproveitando" in x for x in registros)
    registros.clear()
    analise.rodar_orgaos(orgaos, CFG, tmp_path / "b", log=registros.append)
    assert pedidos_estado() == antes and any("reaproveitando a pesquisa de hoje" in x for x in registros)
    assert any("sem custo" in x for x in registros)


def test_painel_e_calendario_saem_mesmo_sem_data_nem_risco(llm, tmp_path):
    import docx
    import openpyxl
    from transicao import analise
    linha = {"orgao": "Secretaria de Exemplo", "situacao": "concluído", "riscos": 0}
    for sub in ("calendarios", "paineis"):
        (tmp_path / sub).mkdir(exist_ok=True)
    analise._gravar_painel_e_calendario(tmp_path, "sex", "Secretaria de Exemplo", [], ["s"], [], [],
                                        {"data_corte": "08/11/2026"}, linha)
    wb = openpyxl.load_workbook(tmp_path / "calendarios" / "sex_calendario.xlsx")
    assert wb["Calendário"].cell(2, 1).value.startswith("A secretaria não informou nenhuma data")
    dados = json.loads((tmp_path / "paineis" / "sex_painel.json").read_text(encoding="utf-8"))
    assert dados["pontos_de_decisao"] == [] and dados["janelas"]["Antes da posse"] == 0

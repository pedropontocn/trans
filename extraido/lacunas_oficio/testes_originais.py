"""Testes do diagnóstico e do ofício, como estavam no app 1.11. Não rodam no pytest do painel (ficam fora de tests/)."""

# --- de tests/test_funcoes.py ---

def test_dias_uteis_com_feriados(funcoes):
    from datetime import date
    assert funcoes._pascoa(2026) == date(2026, 4, 5)
    assert funcoes.somar_dias_uteis(date(2026, 11, 4), 5) == date(2026, 11, 11)
    assert funcoes.somar_dias_uteis(date(2026, 11, 18), 3) == date(2026, 11, 24)    # pula 20/11 e o fim de semana


def test_secretaria_e_cargo(funcoes):
    texto = "**GOVERNO DO ESTADO DO RIO DE JANEIRO**\n\nSecretaria de Estado das Cidades (SECID)\n"
    assert funcoes.secretaria_do_relatorio(texto) == "Secretaria de Estado das Cidades"
    assert funcoes.cargo_do_titular("Secretaria de Estado das Cidades", "Senhora") == "Secretária de Estado das Cidades"
    assert funcoes.cargo_do_titular("Secretaria de Estado das Cidades", "Senhor") == "Secretário de Estado das Cidades"


def test_pendencias_por_secao(funcoes):
    texto, _ = funcoes.limpar_relatorio(RELATORIO)
    secoes = [p["secao"][:3] for p in funcoes.pendencias_por_secao(texto)]
    assert {"1.2", "2.1", "3.2"} <= set(secoes)


BASE = "obra;municipio;situacao\nPonte do Rio Exemplo;Exemplópolis;em execução\n"


def test_diagnostico_confere_evidencias(funcoes, llm):
    texto, _ = funcoes.limpar_relatorio(RELATORIO)
    d = funcoes.diagnosticar("anthropic/claude-opus-5-5", texto, BASE, "cenário")
    itens = {i["item"]: i for i in d["itens"]}
    assert "Dotação (repetido)" not in itens                                   # pedido repetido sai
    assert itens["Dotação atualizada"]["verificado"] and itens["Dotação atualizada"]["onde"] == "relatório"
    assert itens["Ponte do Rio Exemplo"]["onde"] == "base de projetos"
    assert not itens["Obra inventada"]["verificado"] and not itens["Obra inventada"]["incluir"]
    assert not itens["Fonte das atas"]["incluir"]                              # acessória não entra por padrão
    assert d["itens"][0]["materialidade"] == "critica" and d["itens"][-1]["item"] == "Obra inventada"
    assert "<base_projetos>" in llm.mensagem_diagnostico and "1.2" in llm.mensagem_diagnostico


def test_oficio_em_word(funcoes):
    import io
    from datetime import date

    import docx
    itens = [{"secao": "1.2 Orçamento do exercício", "pedido": "Informar a dotação atualizada."},
             {"secao": "1.2 Orçamento do exercício", "pedido": "Informar os restos a pagar."},
             {"secao": "Base de projetos", "pedido": "Informar a situação da Ponte do Rio Exemplo."}]
    dados = {"secretaria": "Secretaria de Estado das Cidades", "titular": "", "tratamento": "Senhora", "numero": "12/2026",
             "referencia": "Relatório de transição.", "data_relatorio": "23/10/2026", "signatario": "", "cargo_signatario": "",
             "canal": "", "prazo_dias": 5, "data_oficio": date(2026, 11, 4)}
    conteudo, limite = funcoes.gerar_oficio_docx(dados, itens)
    texto = "\n".join(p.text for p in docx.Document(io.BytesIO(conteudo)).paragraphs)
    assert limite == date(2026, 11, 11)
    for trecho in ("Ofício nº 12/2026 – Equipe de Transição", "A Sua Excelência a Senhora", "[Nome do(a) titular]",
                   "Secretária de Estado das Cidades", "Senhora Secretária,", "5 (cinco) dias úteis, isto é, até 11/11/2026",
                   "2. Seção 1.2 Orçamento do exercício:", "a) Informar a dotação atualizada.", "b) Informar os restos a pagar.",
                   "3. Itens da base de projetos não mencionados no relatório:", "informado expressamente", "Atenciosamente,"):
        assert trecho in texto, trecho


def test_oficios_aplicaveis_e_referencia(funcoes):
    assert funcoes.oficios_aplicaveis("Secretaria de Estado das Cidades") == ["02", "06", "07", "08"]
    assert {"03", "04"} <= set(funcoes.oficios_aplicaveis("Secretaria de Estado de Fazenda"))
    assert "09" in funcoes.oficios_aplicaveis("Secretaria de Estado de Defesa Civil")
    ref = funcoes.referencia_oficios(["07", "02"], "23/10/2026")
    assert ref.startswith("Ofícios nº 02 e 07/2026 – Equipe de Transição, encaminhados pelo Ofício Circular SECC/CHEGAB nº 10/2026")
    assert ref.endswith("posicionadas em 23/10/2026.")


def test_diagnostico_confere_atendimento_aos_oficios(funcoes, llm):
    texto, _ = funcoes.limpar_relatorio(RELATORIO)
    d = funcoes.diagnosticar("anthropic/claude-opus-5-5", texto, "", "cenário", ["02", "06", "07", "08"])
    at = {a["item_id"]: a for a in d["atendimento"]}
    assert len(at) == 25
    assert at["02.2"]["situacao"] == "atendido" and at["02.2"]["evidencia"]
    assert at["02.3"]["situacao"] == "parcial" and "não foi encontrada" in at["02.3"]["alerta"]   # evidência falsa
    assert at["07.1"]["situacao"] == "nao_atendido" and not at["07.1"]["alerta"]
    assert at["06.4"]["situacao"] == "nao_atendido" and "concorrencia" in at["06.4"]["alerta"]   # o relatório fala de concorrências
    assert at["08.6"]["situacao"] == "nao_avaliado"
    itens = {i.get("item_id"): i for i in d["itens"] if i["tipo"] == "nao_atendido"}
    assert itens["07.1"]["materialidade"] == "critica" and itens["07.1"]["incluir"]
    assert not itens["06.4"]["incluir"]                                    # não reitera o que pode ter sido respondido
    assert d["itens"][0]["tipo"] == "nao_atendido"                         # reiterações primeiro


def test_oficio_reitera_pedidos_nao_atendidos(funcoes):
    import io
    from datetime import date

    import docx
    itens = [{"oficio": "07", "item_id": "07.1", "secao": "Ofício nº 07/2026",
              "pedido": "Informar as ações judiciais com potencial de bloqueio financeiro."},
             {"secao": "1.2 Orçamento do exercício", "pedido": "Informar a dotação atualizada."}]
    dados = {"secretaria": "Secretaria de Estado das Cidades", "tratamento": "Senhor", "prazo_dias": 5,
             "referencia": funcoes.referencia_oficios(["07"], "23/10/2026"), "data_relatorio": "23/10/2026",
             "data_oficio": date(2026, 11, 4)}
    conteudo, _ = funcoes.gerar_oficio_docx(dados, itens)
    texto = "\n".join(p.text for p in docx.Document(io.BytesIO(conteudo)).paragraphs)
    for trecho in ("Referência: Ofício nº 07/2026 – Equipe de Transição", "em resposta aos ofícios em referência",
                   "2. Reiteramos o solicitado no Ofício nº 07/2026 – Equipe de Transição (ações judiciais, auditorias e "
                   "órgãos de controle), em especial:", "a) Informar as ações judiciais com potencial de bloqueio financeiro.",
                   "3. Seção 1.2 Orçamento do exercício:"):
        assert trecho in texto, trecho


def test_prompt_pede_desdobramentos_com_lista_de_verificacao(funcoes):
    assert '"desdobramento"' in funcoes.PROMPT_DIAGNOSTICO
    assert "percentual de execução física e financeira" in funcoes.PROMPT_DIAGNOSTICO
    enum = funcoes.FERRAMENTA_DIAGNOSTICO["function"]["parameters"]["properties"]["lacunas"]["items"]["properties"]["tipo"]["enum"]
    assert "desdobramento" in enum and "nao_atendido" not in enum and "questao_debate" not in enum


def test_desdobramento_usa_o_fato_como_evidencia(funcoes, llm):
    llm.lacunas = [{"tipo": "desdobramento", "secao": "3.2 Obras suspensas", "item": "Dados das cinco obras suspensas",
                    "evidencia": "Cinco obras estão com execução suspensa aguardando decisão da Casa Civil",
                    "por_que_falta": "sem contrato e percentual executado não dá para avaliar o custo de esperar",
                    "materialidade": "critica", "pedido": "Informar, para cada uma das cinco obras suspensas, o contrato, a "
                    "contratada, o percentual executado e a data e o ato da suspensão."},
                   {"tipo": "nao_atendido", "secao": "x", "item": "tipo reservado ao código", "evidencia": "Cinco obras estão "
                    "com execução suspensa", "por_que_falta": "x", "materialidade": "relevante", "pedido": "Outro pedido."}]
    texto, _ = funcoes.limpar_relatorio(RELATORIO)
    d = funcoes.diagnosticar("anthropic/claude-opus-5-5", texto, "", "cenário", [])
    itens = {i["item"]: i for i in d["itens"]}
    obra = itens["Dados das cinco obras suspensas"]
    assert obra["tipo"] == "desdobramento" and obra["verificado"] and obra["incluir"]
    assert itens["tipo reservado ao código"]["tipo"] == "evasiva"       # o modelo não cria "pedido não atendido"


def test_pedidos_do_debate(funcoes, llm):
    tm = tension_map([trade_off("T1", "a")])
    tm["unresolved_questions"] = [{"id": "Q1", "questao": "Qual a dotação atualizada?", "quem_responde": "ASSPLO", "afeta": ["T1"]},
                                  {"id": "Q2", "questao": "Quando as obras foram suspensas?", "quem_responde": "SUBGFISO", "afeta": ["T2"]}]
    itens, _ = funcoes.pedidos_do_debate("anthropic/claude-sonnet-5-5", tm,
                                         ["Informar a dotação atualizada de 2026 por fonte de recurso."])
    assert [i["origem_id"] for i in itens] == ["Q1", "Q2"]              # Q99 inexistente e o repetido saem
    assert all(i["tipo"] == "questao_debate" and i["incluir"] for i in itens)
    assert itens[1]["unidade"] == "SUBGFISO" and "afeta T2" in itens[1]["por_que_falta"]
    assert "Informar a dotação atualizada" in llm.mensagem_pedidos_debate        # a lista de já pedidos vai ao modelo



# --- de tests/test_app.py ---

def _diagnosticar(at):
    next(b for b in at.button if "Diagnosticar" in b.label).click().run()
    assert not at.exception, at.exception
    return at.session_state["diagnostico"]


def test_diagnostico_com_base_e_oficio(app, llm):
    llm.base_projetos = "obra;municipio;situacao\nPonte do Rio Exemplo;Exemplópolis;em execução\n"
    at = app.run()
    d = _diagnosticar(at)
    assert d["com_base"] and any(i["onde"] == "base de projetos" for i in d["itens"])
    assert [m.value for m in at.metric][:1] == ["2"]                    # dotação + pedido 07.1 não atendido
    assert "07.1 (Ofício nº 07/2026)" in llm.mensagem_diagnostico          # itens dos ofícios vão para o modelo
    assert any("Minuta de ofício" in getattr(b, "proto", b).label for b in at.get("download_button"))


def test_lacuna_critica_segura_o_debate_ate_confirmar(app, llm):
    at = app.run()
    _diagnosticar(at)
    next(b for b in at.button if "deliber" in b.label.lower()).click().run()
    assert "resultado" not in at.session_state
    assert any("lacunas críticas sem resposta" in w.value for w in at.warning)
    # marcando "deliberar mesmo assim", o debate roda e recebe as lacunas como contexto
    next(c for c in at.checkbox if "mesmo assim" in c.label).check().run()
    at.slider[0].set_value(1).run()
    r = _deliberar(at)
    debate = next(c for c in llm.chamadas if c["ferramenta"] == "registrar_tension_map")
    assert "LACUNAS IDENTIFICADAS NO DIAGNÓSTICO PRÉVIO" in debate["mensagens"][1]["content"][-1]["text"]
    assert json.loads(r["registro_json"])["diagnostico_lacunas"]["itens"]


def test_questoes_do_debate_viram_pedidos_sem_travar_nova_deliberacao(app, llm):
    tm = tension_map([trade_off("T1", "Licitações")])
    tm["unresolved_questions"] = [{"id": "Q1", "questao": "Qual o motivo do adiamento?", "quem_responde": "Licitações", "afeta": ["T1"]}]
    llm.rodadas = [tm]
    at = app.run()
    at.slider[0].set_value(1).run()
    r = _deliberar(at)
    assert r["pedidos_do_debate"] == 2                                 # uma questão pode gerar mais de um pedido
    d = at.session_state["diagnostico"]
    assert d.get("so_debate") and {i["origem_id"] for i in d["itens"]} == {"Q1"}
    assert any("viraram pedidos ao órgão" in m.value for m in at.info)
    # rodar o diagnóstico depois mantém os pedidos do debate
    next(b for b in at.button if "Diagnosticar" in b.label).click().run()
    assert any(i["tipo"] == "questao_debate" for i in at.session_state["diagnostico"]["itens"])
    # e esses pedidos não travam uma nova deliberação (só as lacunas críticas do relatório travam)
    next(c for c in at.checkbox if "mesmo assim" in c.label).check().run()
    _deliberar(at)


def test_diagnostico_e_debate_compartilham_o_prefixo_do_cache(app, llm):
    at = app.run()
    _diagnosticar(at)
    next(c for c in at.checkbox if "mesmo assim" in c.label).check().run()
    _deliberar(at)
    diag = next(c for c in llm.chamadas if c["ferramenta"] == "registrar_diagnostico")
    debate = next(c for c in llm.chamadas if c["ferramenta"] == "registrar_tension_map")
    # mesmas ferramentas, mesmo sistema e mesmo bloco do relatório: o debate lê do cache o que o diagnóstico gravou
    assert diag["kw"]["tools"] == debate["kw"]["tools"]
    assert diag["mensagens"][0] == debate["mensagens"][0]
    assert diag["mensagens"][1]["content"][0] == debate["mensagens"][1]["content"][0]


def test_diagnostico_repetido_reaproveita_a_resposta(app, llm):
    at = app.run()
    _diagnosticar(at)
    d2 = _diagnosticar(at)
    assert [c["ferramenta"] for c in llm.chamadas].count("registrar_diagnostico") == 1
    assert d2["reaproveitado"] and d2["uso"] == [] and d2["itens"]
    assert any("reaproveitado" in c.value for c in at.caption)
    # "Refazer do zero" chama o modelo de novo
    next(b for b in at.button if "Refazer o diagnóstico" in b.label).click().run()
    assert not at.exception, at.exception
    assert [c["ferramenta"] for c in llm.chamadas].count("registrar_diagnostico") == 2
    assert not at.session_state["diagnostico"]["reaproveitado"]



"""Testes das funções do app, sem a interface."""
import json

from conftest import FONTE_FALSA, FONTE_OK, RELATORIO, SEM_FONTE, tension_map, trade_off


def test_limpeza_tira_orientacoes_e_dados_pessoais(funcoes):
    texto, avisos = funcoes.limpar_relatorio(RELATORIO)
    assert "ORIENTAÇÕES DE PREENCHIMENTO" not in texto
    assert "Como preencher" not in texto
    assert "fulano@exemplo.gov.br" not in texto
    assert "PONTOS FOCAIS" not in texto
    assert "Quatro concorrências" in texto
    assert any("seção 9" in a for a in avisos)


def test_extrair_json_ignora_lixo_e_respeita_marcadores(funcoes):
    assert funcoes.extrair_json('texto {"a": 1} depois {quebrado') == {"a": 1}
    assert funcoes.extrair_json('[INÍCIO DO JSON]{"b": 2}[FIM DO JSON] {"c": 3}') == {"b": 2}
    assert funcoes.extrair_json("sem json nenhum") is None


def test_mapear_campos_aceita_nomes_alternativos_e_aninhamento(funcoes):
    variante = {"Problema Central": "x", "Fatos Ancoradores": ["f"], "Personas": ["p"], "Lacunas de Dados": ["l"]}
    assert set(funcoes.mapear_campos(variante)) == {"problema", "fatos", "personas", "lacunas"}
    aninhado = {"dados": {"problema": "x", "fatos": ["f"], "personas": ["p"], "lacunas": ["l"]}}
    assert set(funcoes.mapear_campos(aninhado)) == {"problema", "fatos", "personas", "lacunas"}


def test_completude_conta_campos_pendentes(funcoes):
    texto, _ = funcoes.limpar_relatorio(RELATORIO)
    comp = funcoes.indice_completude(texto)
    pendentes = {s["secao"] for s in comp["secoes"] if s["pendencias"]}
    assert any(s.startswith("1.2") for s in pendentes)     # dotação a complementar
    assert any(s.startswith("2.1") for s in pendentes)     # agenda com datas em branco
    assert any(s["secao"].startswith("1.1") and s["pendencias"] == 0 for s in comp["secoes"])  # seção completa
    assert 0 < comp["indice"] < 1


def test_evidencia_sem_trecho_no_relatorio_e_rebaixada(funcoes):
    tm = tension_map([trade_off("T1", "ok", 1, FONTE_OK), trade_off("T2", "falsa", 1, FONTE_FALSA),
                      trade_off("T3", "sem fonte", 2, SEM_FONTE)])
    tm, ev = funcoes.verificar_evidencias(tm, RELATORIO)
    assert [r["onde"] for r in ev["rebaixadas"]] == ["T2 · Polo A", "T3 · Polo A"]
    assert tm["trade_offs"][1]["polo_a"]["evidencia"] == 5
    assert tm["trade_offs"][1]["polo_a"]["evidencia_declarada"] == 1
    # o trade-off não pode ter evidência mais forte que seu polo mais bem apoiado
    assert tm["trade_offs"][1]["nivel_evidencia"] == 4


def test_normas_vao_para_revisao_juridica(funcoes):
    norma = {"tipo": "norma", "referencia": "Lei 14.133/2021, art. 71", "trecho": ""}
    _, ev = funcoes.verificar_evidencias(tension_map([trade_off("T1", "x", 2, norma)]), RELATORIO)
    assert ev["normas"][0]["referencia"] == "Lei 14.133/2021, art. 71"
    assert not ev["rebaixadas"]


def test_numeros_do_memorando(funcoes):
    memo = ("Licitações somam R$ 120,5 mi (80%), LOA de R$ 412 mi, diferença de R$ 13,3 mi (cálculo). "
            "Valor inventado: R$ 999,9 mi. Data 23/10/2026 e data inventada 12/12/2026.")
    achados = {n["valor"]: n["situacao"] for n in funcoes.verificar_numeros(memo, RELATORIO)}
    assert achados["R$ 120,5 mi"] == "conferido"
    assert achados["R$ 412 mi"] == "conferido"
    assert achados["80%"] == "conferido"
    assert achados["R$ 13,3 mi"] == "cálculo declarado"
    assert achados["R$ 999,9 mi"] == "não encontrado"
    assert achados["23/10/2026"] == "conferido"
    assert achados["12/12/2026"] == "não encontrado"


def test_numero_br(funcoes):
    assert funcoes._numero_br("236.441.332,55") == (236441332.55, 2)
    assert funcoes._numero_br("236,4") == (236.4, 1)
    assert funcoes._numero_br("1.302") == (1302.0, 0)


def test_estabilidade_separa_estaveis_e_sinais_fracos(funcoes):
    r1 = tension_map([trade_off("T1", "a"), trade_off("T2", "b")])
    r2 = tension_map([trade_off("T1", "a'"), trade_off("T2", "c")])
    r3 = tension_map([trade_off("T1", "b'"), trade_off("T2", "a''")])
    cons = tension_map([trade_off("C1", "A", origens=["R1-T1", "R2-T1", "R3-T2"]),
                        trade_off("C2", "B", origens=["R1-T2", "R3-T1"]),
                        trade_off("C3", "C", origens=["R2-T2", "R9-T5"])])   # R9-T5 não existe
    tm = funcoes.aplicar_estabilidade(cons, [(1, r1), (2, r2), (3, r3)], 3)
    assert [(t["id"], t["estabilidade"]) for t in tm["trade_offs"]] == [("C1", "3/3"), ("C2", "2/3")]
    assert [(f["id"], f["estabilidade"]) for f in tm["sinais_fracos"]] == [("C3", "1/3")]


def test_estabilidade_sem_origens_nao_perde_a_analise(funcoes):
    r1 = tension_map([trade_off("T1", "a")])
    cons = tension_map([trade_off("C1", "A"), trade_off("C2", "B")])          # sem "origens"
    tm = funcoes.aplicar_estabilidade(cons, [(1, r1), (2, r1)], 2)
    assert [t["id"] for t in tm["trade_offs"]] == ["C1", "C2"]
    assert tm["estabilidade"] is None


def test_confianca_calculada(funcoes):
    vazio = {"conferidas": [1, 2, 3], "calculos": [], "rebaixadas": [], "normas": []}
    alta = funcoes.confianca_calculada({"indice": 0.9}, {"rodadas": 3, "estaveis": 3, "minimo_para_estavel": 2}, vazio)
    assert alta["nivel"] == "alta"
    assert funcoes.confianca_calculada({"indice": 0.3}, {"rodadas": 3, "estaveis": 3, "minimo_para_estavel": 2}, vazio)["nivel"] == "baixa"
    assert funcoes.confianca_calculada({"indice": 0.9}, None, vazio)["nivel"] == "média"   # estabilidade não medida


def test_validacao_aponta_campos_faltantes(funcoes):
    incompleto = tension_map([trade_off("T1", "a")], confidence_assessment=True)
    erros = funcoes.validar(incompleto, funcoes.SCHEMA_TENSION_MAP)
    assert any("confidence_assessment" in e for e in erros)
    assert funcoes.validar(tension_map([trade_off("T1", "a")]), funcoes.SCHEMA_TENSION_MAP) == []


def test_custo_considera_cache(funcoes):
    sem_cache = [{"modelo": "anthropic/claude-opus-5-5", "entrada": 1_000_000, "entrada_sem_cache": 1_000_000,
                  "cache_leitura": 0, "cache_escrita": 0, "saida": 0}]
    com_cache = [{"modelo": "anthropic/claude-opus-5-5", "entrada": 1_000_000, "entrada_sem_cache": 0,
                  "cache_leitura": 1_000_000, "cache_escrita": 0, "saida": 0}]
    assert round(funcoes.custo_estimado(sem_cache)[0], 2) == 4.00
    assert round(funcoes.custo_estimado(com_cache)[0], 2) == 0.20


def test_word_gerado_abre_e_tem_matriz(funcoes):
    import io

    import docx
    from conftest import MEMORANDO
    dados = funcoes.gerar_docx(MEMORANDO, {"orgao": "Secretaria de Exemplo", "unidade": "Gabinete", "para": "Secretária",
                                          "assunto": "Teste", "data": "4 de novembro de 2026"})
    documento = docx.Document(io.BytesIO(dados))
    tabelas = [t for t in documento.tables if t.rows and "Probabilidade" in [c.text for c in t.rows[0].cells]]
    assert len(tabelas) == 1 and len(tabelas[0].rows) == 3      # cabeçalho + 2 riscos numa tabela só
    assert "**" not in "\n".join(p.text for p in documento.paragraphs)


def test_secao_de_verificacao_do_word_inclui_neutralidade(funcoes):
    ev = {"conferidas": [], "calculos": [], "rebaixadas": [], "normas": []}
    neutralidade = {"modelo": "anthropic/claude-sonnet-5-5", "avaliacao_geral": "levemente_enviesado",
                    "desequilibrados": [{"id": "T2", "equilibrio": "pende_para_b"}],
                    "recomendacoes_implicitas": [{"trecho": "x", "por_que": "y"}]}
    md = funcoes.markdown_verificacao(ev, [], "abc", "anthropic/claude-opus-5-5", neutralidade=neutralidade)
    assert "Revisão de neutralidade" in md and "T2 (pende para B)" in md and "1 trecho(s)" in md


RELATORIO_NOVO = (RELATORIO
                  .replace("Dotação atualizada: \\[A complementar\\].", "Dotação atualizada: R$ 430.000.000,00.")
                  .replace("R$ 120.500.000,00", "R$ 98.000.000,00"))


def test_retrato_e_comparacao_do_relatorio(funcoes):
    antigo = funcoes.retrato_relatorio(funcoes.limpar_relatorio(RELATORIO)[0])
    novo = funcoes.retrato_relatorio(funcoes.limpar_relatorio(RELATORIO_NOVO)[0])
    c = funcoes.comparar_relatorios(antigo, novo)
    assert [p["secao"][:3] for p in c["preenchidas"]] == ["1.2"]
    mudou = {v["secao"][:3]: v for v in c["valores_mudaram"]}
    assert mudou["3.1"]["sairam"] == ["120.500.000,00"] and mudou["3.1"]["entraram"] == ["98.000.000,00"]
    assert "430.000.000,00" in mudou["1.2"]["entraram"]


def test_comparacao_de_riscos(funcoes):
    from conftest import MEMORANDO
    novo = (MEMORANDO.replace("| Perda de propostas | Alta | Médio |", "| Perda das propostas | Média | Médio |")
            .replace("| Obrigações sem caixa | Média | Alto | Demonstrativo de restos a pagar | Finanças |",
                     "| Questionamento do TCE | Alta | Alto | Parecer da PGE | Jurídico |"))
    r = funcoes.comparar_riscos(funcoes.extrair_matriz(MEMORANDO), funcoes.extrair_matriz(novo))
    assert r["mudaram"] == [{"risco": "Perda das propostas", "mudancas": ["probabilidade Alta → Média"]}]
    assert r["novos"] == ["Questionamento do TCE"] and r["sairam"] == ["Obrigações sem caixa"]


def test_pareamento_descarta_ids_inexistentes_e_repetidos(funcoes, llm):
    antigo = tension_map([trade_off("C1", "Licitações", estabilidade="2/3"), trade_off("C2", "Atas")])
    novo = tension_map([trade_off("T1", "Licitações adiadas", estabilidade="3/3"), trade_off("T2", "Obras")])
    llm.pareamento = {"pares": [{"anterior": "C1", "atual": "T1"}, {"anterior": "C2", "atual": "T1"},
                                {"anterior": "C9", "atual": "T2"}]}
    r = funcoes.comparar_trade_offs("anthropic/claude-sonnet-5-5", antigo, novo)
    assert [(m["anterior"], m["atual"]) for m in r["mantidos"]] == [("C1", "T1")]
    assert "estabilidade 2/3 → 3/3" in r["mantidos"][0]["mudancas"]
    assert [t["id"] for t in r["novos"]] == ["T2"] and [t["id"] for t in r["sairam"]] == ["C2"]


def test_ler_personas(funcoes):
    texto = ("- [fazenda] Fazenda: foco em caixa\n- [controle] Controle externo: legalidade\n"
             "3. Beneficiário\n- [fazenda] Outra fazenda: repetida\n\n")
    p = funcoes.ler_personas(texto)
    assert [x["id"] for x in p] == ["fazenda", "controle", "beneficiario", "fazenda_"]
    assert p[0]["criterio"] == "foco em caixa" and p[2]["nome"] == "Beneficiário"


def test_mesma_familia(funcoes):
    assert funcoes.mesma_familia("anthropic/claude-sonnet-5-5", "anthropic/claude-opus-5-5")
    assert not funcoes.mesma_familia("gemini/gemini-3.1-pro-preview", "anthropic/claude-sonnet-5-5")


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

"""Testes das funções do app, sem a interface."""
from conftest import MEMORANDO, FONTE_AUTO, FONTE_FALSA, FONTE_OK, RELATORIO, SEM_FONTE, dossie_exemplo, tension_map, trade_off


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
    variante = {"Problema Central": "x", "Personas": ["p"], "Lacunas de Dados": ["l"], "Grupos sem voz": ["g"]}
    assert set(funcoes.mapear_campos(variante)) == {"problema", "personas", "lacunas", "sem_voz"}
    aninhado = {"dados": {"problema": "x", "personas": ["p"], "lacunas": ["l"]}}
    assert set(funcoes.mapear_campos(aninhado)) == {"problema", "personas", "lacunas"}
    # fatos não são mais extraídos: vêm do dossiê
    assert "fatos" not in funcoes.mapear_campos({"fatos": ["f"], "problema": "x"})



def test_evidencias_conferidas_no_dossie_e_na_autodeclaracao(funcoes):
    dossie = dossie_exemplo(funcoes)
    item_inexistente = {"tipo": "dossie", "referencia": "O77", "trecho": "qualquer coisa escrita aqui mesmo"}
    pdf_nao_conferido = {"tipo": "dossie", "referencia": "O5", "trecho": "contrato de manutenção do sistema de folha"}
    tm = tension_map([trade_off("T1", "ok", 1, FONTE_OK), trade_off("T2", "falsa", 1, FONTE_FALSA),
                      trade_off("T3", "sem fonte", 2, SEM_FONTE), trade_off("T4", "autodeclaração", 1, FONTE_AUTO),
                      trade_off("T5", "item inexistente", 1, item_inexistente),
                      trade_off("T6", "não conferido", 1, pdf_nao_conferido)])
    tm, ev = funcoes.verificar_evidencias(tm, funcoes.texto_dossie(dossie), dossie, RELATORIO)
    t = {x["id"]: x for x in tm["trade_offs"]}
    assert [r["onde"] for r in ev["rebaixadas"]] == ["T2 · Polo A", "T3 · Polo A", "T5 · Polo A"]
    assert t["T1"]["polo_a"]["evidencia"] == 1                         # dado oficial conferido sustenta nível 1
    assert t["T2"]["polo_a"]["evidencia"] == 5 and t["T2"]["polo_a"]["evidencia_declarada"] == 1
    assert t["T2"]["nivel_evidencia"] == 4      # o trade-off não pode ser mais forte que seu polo mais bem apoiado
    # o que vem só do órgão vale no máximo nível 4
    assert t["T4"]["polo_a"]["evidencia"] == 4 and "autodeclaração" in t["T4"]["polo_a"]["verificacao"]
    assert [r["referencia"] for r in ev["autodeclaracoes"]] == ["3.2"]
    # item oficial cujo link não abriu: no máximo nível 3 até alguém conferir
    assert t["T6"]["polo_a"]["evidencia"] == 3 and "O5" in t["T6"]["polo_a"]["verificacao"]
    assert "não existe no dossiê" in ev["rebaixadas"][2]["motivo"]


def test_normas_vao_para_revisao_juridica(funcoes):
    norma = {"tipo": "norma", "referencia": "Lei 14.133/2021, art. 71", "trecho": ""}
    dossie = dossie_exemplo(funcoes)
    _, ev = funcoes.verificar_evidencias(tension_map([trade_off("T1", "x", 2, norma)]), RELATORIO, dossie, RELATORIO)
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
    vazio = {"conferidas": [1, 2, 3], "calculos": [], "rebaixadas": [], "normas": [], "autodeclaracoes": []}
    estavel = {"rodadas": 3, "estaveis": 3, "minimo_para_estavel": 2}
    bom = {"itens": 10, "conferidos": 9, "oficiais": 8}
    assert funcoes.confianca_calculada(bom, estavel, vazio)["nivel"] == "alta"
    assert funcoes.confianca_calculada(dict(bom, conferidos=3), estavel, vazio)["nivel"] == "baixa"   # dossiê mal conferido
    assert funcoes.confianca_calculada(None, estavel, vazio)["nivel"] == "baixa"                       # sem dossiê
    assert funcoes.confianca_calculada(bom, None, vazio)["nivel"] == "média"                           # estabilidade não medida
    so_orgao = dict(vazio, conferidas=[1], autodeclaracoes=[1, 2, 3])
    assert funcoes.confianca_calculada(bom, estavel, so_orgao)["nivel"] == "média"


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
    # busca na web da Anthropic: US$ 10 por mil buscas
    assert round(funcoes.custo_estimado([dict(com_cache[0], buscas=20)])[0], 2) == 0.40


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






def test_custo_da_escrita_de_cache_de_uma_hora(funcoes):
    base = {"modelo": "anthropic/claude-opus-5-5", "entrada": 1_000_000, "entrada_sem_cache": 0, "cache_leitura": 0,
            "cache_escrita": 1_000_000, "saida": 0}
    assert round(funcoes.custo_estimado([base])[0], 2) == 5.00                         # 5 minutos: 1,25x
    assert round(funcoes.custo_estimado([dict(base, cache_escrita_1h=1_000_000)])[0], 2) == 8.00   # 1 hora: 2x


def test_mensagens_sem_cache_para_outros_modelos(funcoes):
    msgs = funcoes.mensagens_com_cache("gemini/gemini-3.8-flash", "INSTRUÇÕES", "<dossie>\nx\n</dossie>", "pergunta")
    assert msgs[0] == {"role": "system", "content": "INSTRUÇÕES"}
    assert msgs[1]["content"].startswith("<dossie>") and msgs[1]["content"].endswith("pergunta")


def test_material_de_referencia_marca_o_relatorio_como_autodeclaracao(funcoes):
    dossie = dossie_exemplo(funcoes)
    m = funcoes.material_referencia(dossie, "texto do órgão")
    assert m.startswith("<dossie>") and "<relatorio>\nAUTODECLARAÇÃO DO ÓRGÃO" in m and m.endswith("</relatorio>")
    assert "<relatorio>" not in funcoes.material_referencia(dossie, "")
    texto = funcoes.texto_dossie(dossie)
    assert "[E1] (situacao_fiscal)" in texto and "nível máximo 1" in texto
    assert "PROCURADO E NÃO ENCONTRADO" in texto and "terceirizados" in texto


def test_concordancia_exige_todos_os_pares(funcoes, llm):
    tm1 = tension_map([trade_off("T1", "Licitações"), trade_off("T2", "Atas")])
    tm2 = tension_map([trade_off("T1", "Licitações adiadas"), trade_off("T2", "Obras")])
    assert funcoes.rodadas_concordam("anthropic/claude-sonnet-5-5", tm1, tm2, uso_lista=[])
    llm.pareamento = {"pares": [{"anterior": "T1", "atual": "T1"}, {"anterior": "T2", "atual": "T9"}]}
    assert not funcoes.rodadas_concordam("anthropic/claude-sonnet-5-5", tm1, tm2, uso_lista=[])
    llm.pareamento = {"pares": [{"anterior": "T1", "atual": "T1"}, {"anterior": "T1", "atual": "T2"}]}
    assert not funcoes.rodadas_concordam("anthropic/claude-sonnet-5-5", tm1, tm2, uso_lista=[])
    # número diferente de trade-offs: nem chama o modelo
    n = len(llm.chamadas)
    assert not funcoes.rodadas_concordam("anthropic/claude-sonnet-5-5", tm1, tension_map([trade_off("T1", "x")]), uso_lista=[])
    assert len(llm.chamadas) == n


# --- FUNDAMENTAÇÃO (DOSSIÊ) ---------------------------------------------------------

def test_itens_normalizados_e_numerados(funcoes):
    bruto = {"bloco": "Situação fiscal", "afirmacao": "x", "url": "javascript:alert(1)", "tipo_fonte": "opiniao",
             "confianca": "Alta"}
    i = funcoes.normalizar_item(bruto, "estado")
    assert i["url"] == "" and i["tipo_fonte"] == "hipotese" and i["confianca"] == "alta"
    assert i["bloco"] == "situacao_fiscal"
    assert funcoes.normalizar_item({"bloco": "pessoal"}, "orgao") is None            # sem afirmação
    assert funcoes.normalizar_item({"bloco": "nada", "afirmacao": "y"}, "orgao")["bloco"] == "outro_orgao"
    itens = [funcoes.normalizar_item({"afirmacao": a, "id": ident}, c)
             for a, ident, c in [("a", "E1", "estado"), ("b", "E1", "estado"), ("c", "", "orgao"), ("d", "E9", "orgao")]]
    assert [x["id"] for x in funcoes.numerar_itens(itens)] == ["E1", "E2", "O1", "O2"]


def test_nivel_maximo_por_tipo_de_fonte(funcoes):
    item = lambda tipo, chec="conferido", equipe=False: {"tipo_fonte": tipo, "checagem": chec, "conferido_pela_equipe": equipe}
    assert funcoes.nivel_maximo(item("documento_oficial")) == 1
    assert funcoes.nivel_maximo(item("documento_oficial", "inacessivel")) == 3
    assert funcoes.nivel_maximo(item("documento_oficial", "inacessivel", True)) == 1     # a equipe conferiu
    assert funcoes.nivel_maximo(item("estudo")) == 2
    assert funcoes.nivel_maximo(item("imprensa")) == 3
    assert funcoes.nivel_maximo(item("declaracao_politica")) == 3                        # promessa nunca é fato
    assert funcoes.nivel_maximo(item("hipotese")) == 4


def test_links_conferidos_por_codigo(funcoes, llm):
    d = dossie_exemplo(funcoes)
    chec = {i["id"]: i["checagem"] for i in d["itens"]}
    assert chec["O3"] == "conferido"                       # o script da página é ignorado e o trecho é achado
    assert chec["O2"] == "trecho_nao_encontrado"           # a página abre, mas não tem o trecho
    assert chec["O5"] == "inacessivel"
    assert chec["O6"] == "sem_trecho"
    # cada página é aberta uma vez só, mesmo citada por dois itens
    assert llm.paginas_abertas.count("https://transparencia.exemplo.gov.br/licitacoes") == 1
    r = funcoes.resumo_dossie(d)
    assert (r["itens"], r["estado"], r["orgao"], r["nao_encontrado"]) == (9, 3, 6, 2)
    assert r["conferidos"] == 6


def test_enderecos_internos_nao_sao_abertos(funcoes, llm):
    for url in ("http://localhost/x", "http://127.0.0.1/x", "http://169.254.169.254/latest", "http://10.0.0.5/a",
                "http://servidor.internal/a"):
        llm.paginas[url] = "<p>segredo</p>"
        assert funcoes.baixar_pagina(url) is None
    assert not any(u.startswith("http://") for u in getattr(llm, "paginas_abertas", []))     # nem chegou a abrir
    assert "Quatro concorrências" in funcoes.baixar_pagina("https://transparencia.exemplo.gov.br/licitacoes")


def test_html_vira_texto(funcoes):
    assert funcoes._html_para_texto("<p>a &amp; b</p><script>x()</script><style>p{}</style>").split() == ["a", "&", "b"]




def test_pesquisa_usa_busca_na_web_em_grupos(funcoes, llm):
    d = funcoes.montar_dossie("anthropic/claude-sonnet-5-5", "Secretaria de Exemplo", "04/11/2026", "licitações")
    pesquisas = [c for c in llm.chamadas if "Monte a camada" in str(c["mensagens"])]
    assert len(pesquisas) == 5 and all(c["kw"]["web_search_options"] == {"search_context_size": "medium"} for c in pesquisas)
    assert all("Foco indicado pela equipe" in str(c["mensagens"]) for c in pesquisas)
    assert sorted(i["id"] for i in d["itens"]) == ["E1", "E2", "E3", "O1", "O2", "O3", "O4", "O5", "O6"]
    assert sum(u["buscas"] for u in d["uso"]) == 20
    assert all(not x["erro"] and not x["continuacao"] for x in d["diagnostico"])
    assert len(d["nao_encontrado"]) == 2
    # mesma pesquisa de novo: reaproveitada, sem nova busca
    de_novo = funcoes.montar_dossie("anthropic/claude-sonnet-5-5", "Secretaria de Exemplo", "04/11/2026", "licitações")
    assert de_novo["reaproveitado"] and len([c for c in llm.chamadas if "Monte a camada" in str(c["mensagens"])]) == 5


def test_resposta_sem_json_pede_que_o_modelo_termine(funcoes, llm):
    llm.grupos_sem_json = {"situacao_fiscal", "contratos_convenios"}
    d = funcoes.montar_dossie("anthropic/claude-sonnet-5-5", "Secretaria de Exemplo", "04/11/2026")
    assert len(d["itens"]) == 9                                   # a continuação recuperou os itens
    continuacoes = [c for c in llm.chamadas if str(c["mensagens"][-1]["content"]).startswith("Você parou antes")]
    assert len(continuacoes) == 2
    assert continuacoes[0]["mensagens"][1] == {"role": "assistant", "content": "Fiz as buscas e encontrei documentos relevantes."}
    assert sum(x["continuacao"] for x in d["diagnostico"]) == 2 and not any(x["erro"] for x in d["diagnostico"])


def test_erro_em_parte_da_pesquisa_nao_derruba_o_resto(funcoes, llm):
    llm.grupos_com_erro = {"situacao_fiscal"}
    d = funcoes.montar_dossie("anthropic/claude-sonnet-5-5", "Secretaria de Exemplo", "04/11/2026")
    assert len(d["itens"]) == 8
    erro = next(x for x in d["diagnostico"] if x["erro"])
    assert erro["blocos"][0] == "situacao_fiscal" and "RuntimeError: busca indisponível" in erro["erro"]


def test_pesquisa_toda_com_erro_mostra_o_motivo(funcoes, llm):
    import pytest
    llm.falhar_pesquisa = True
    with pytest.raises(RuntimeError, match="todas as buscas falharam: RuntimeError: busca indisponível"):
        funcoes.montar_dossie("gemini/gemini-3.8-flash", "Secretaria de Exemplo", "04/11/2026")


def test_pesquisa_sem_json_nenhum_devolve_dossie_vazio_com_diagnostico(funcoes, llm):
    from conftest import GRUPOS
    llm.grupos_sem_json = {g[0] for g in GRUPOS}
    llm.continuacao_sem_json = True
    d = funcoes.montar_dossie("anthropic/claude-sonnet-5-5", "Secretaria de Exemplo", "04/11/2026")
    assert d["itens"] == [] and all(x["erro"] == funcoes.SEM_JSON for x in d["diagnostico"])
    assert all("Fiz as buscas" in x["resposta"] and x["continuacao"] for x in d["diagnostico"])


def test_insumos_saem_do_dossie_e_sem_baseline(funcoes, llm):
    campos, uso, _ = funcoes.preparar_insumos("anthropic/claude-sonnet-5-5", dossie_exemplo(funcoes), "foco x")
    assert "<dossie>" in llm.mensagem_insumos and "FOCO INDICADO PELA EQUIPE: foco x" in llm.mensagem_insumos
    assert "Cinco obras" not in llm.mensagem_insumos                              # o relatório do órgão não entra
    assert [p["id"] for p in campos["personas"]] == ["planejamento", "controle", "gradual"]
    assert campos["sem_voz"] == ["Trabalhadores terceirizados dos contratos de custeio"]


def test_confronto_descarta_o_que_nao_confere(funcoes, llm):
    texto_rel, _ = funcoes.limpar_relatorio(RELATORIO)
    c = funcoes.confrontar("anthropic/claude-sonnet-5-5", dossie_exemplo(funcoes), texto_rel)
    assert [(d["item"], d["situacao"]) for d in c["divergencias"]] == [("O4", "nao_mencionado"), ("O3", "contradiz")]
    assert c["descartadas"] == 3      # item inexistente, trecho que não está no relatório e item que o relatório menciona
    assert "<relatorio>" in llm.mensagem_confronto and "<dossie>" in llm.mensagem_confronto
    assert "sem atribuir intenção" in funcoes.texto_confronto(c)
    assert funcoes.confrontar("m", dossie_exemplo(funcoes), "")["divergencias"] == []


def test_quadro_sobre_o_documento(funcoes):
    quadro = funcoes.sobre_o_documento({"itens": 9, "conferidos": 6}, "04/11/2026", {"nivel": "média"})
    memo = funcoes.inserir_sobre_documento("# Memorando Executivo\n## Em síntese\n- x", quadro)
    linhas = memo.splitlines()
    assert linhas[0] == "# Memorando Executivo" and linhas[2] == "## Sobre este documento"
    assert "Apoio à decisão gerado com IA" in memo and "Não recomenda decisões" in memo and "média" in memo
    assert "sem revisão da equipe" in memo
    assert funcoes.inserir_sobre_documento("sem título", quadro).startswith("## Sobre este documento")


def test_dossie_com_estado_compartilhado(funcoes, llm):
    estado = funcoes.pesquisar_estado("anthropic/claude-sonnet-5-5", "04/11/2026")
    assert [i["id"] for i in estado["itens"]] == ["E1", "E2", "E3"]
    antes = len([c for c in llm.chamadas if "Monte a camada" in str(c["mensagens"])])
    assert antes == 2
    d = funcoes.montar_dossie("anthropic/claude-sonnet-5-5", "Secretaria de Exemplo", "04/11/2026", estado=estado)
    pesquisas = [str(c["mensagens"]) for c in llm.chamadas if "Monte a camada" in str(c["mensagens"])][antes:]
    assert len(pesquisas) == 3 and not any('camada\\n"Estado"' in p for p in pesquisas)   # só o órgão
    assert sorted(i["id"] for i in d["itens"]) == ["E1", "E2", "E3", "O1", "O2", "O3", "O4", "O5", "O6"]
    assert d["estado_compartilhado"] and sum(x.get("compartilhado", False) for x in d["diagnostico"]) == 2
    # o Estado não é conferido de novo nem cobrado de novo no dossiê do órgão
    assert llm.paginas_abertas.count("https://www.exemplo.rj.gov.br/loa-2027") == 1
    assert sum(u["buscas"] for u in d["uso"]) == 12


def test_memorando_sem_orgao_nem_unidade_no_cabecalho(funcoes):
    """Com os campos "Órgão" e "De (unidade)" vazios, o Word sai sem eles, sem erro."""
    from conftest import MEMORANDO
    import io
    import docx
    dados = funcoes.gerar_docx(MEMORANDO, {"orgao": "", "unidade": "", "para": "", "assunto": "Teste", "data": "5 de novembro de 2026"})
    assert "MEMORANDO EXECUTIVO" in "\n".join(p.text for p in docx.Document(io.BytesIO(dados)).paragraphs)


def test_conteudo_da_autodeclaracao_para_o_memorando(funcoes):
    rel = ("# ARQUIVO: relatorio.docx\n\n## 3. Contratos vigentes\n|Contrato|Obra|Valor|\n|-|-|-|\n"
           "|012/2025|Ponte do Rio|R$ 1.000.000,00|\n|013/2025|Escola|R$ 2.500.000,00|\n\n## 4. Pessoal\nTexto.")
    texto = funcoes.conteudo_autodeclaracao(rel)
    assert "relatorio.docx" in texto and "3. Contratos vigentes" in texto and "3 linha(s) com contratos" in texto
    assert "não enviou" in funcoes.conteudo_autodeclaracao("")


def test_memorando_recebe_o_que_o_orgao_enviou(funcoes):
    assert "Informado x confirmado" in funcoes.PROMPT_ETAPA_2 and "Declarado x confirmado" in funcoes.METODOLOGIA


def test_resumo_de_100_paginas_entra_inteiro(funcoes):
    """Um resumo de ~100 páginas (300 mil caracteres) entra inteiro; só o que passa de 400 mil é cortado, com aviso."""
    pagina = "## Contratos\n" + ("Contrato 012/2025, obra da Ponte do Rio, valor de R$ 1.000.000,00. " * 40) + "\n"
    resumo = pagina * 100 + "## Última seção\nRelação final de contratos."
    texto, avisos = funcoes.limpar_relatorio(resumo)
    assert len(resumo) > 250_000 and "Relação final de contratos." in texto
    assert not any("cortado" in a for a in avisos)
    grande, avisos = funcoes.limpar_relatorio(resumo * 2)
    assert len(grande) == funcoes.LIMITE_RELATORIO and any("passou do limite" in a for a in avisos)


def test_anexo_do_debate_montado_por_codigo(funcoes):
    tm = tension_map([trade_off("T1", "Licitações", estabilidade="2/2"), trade_off("T2", "Atas")])
    tm["trade_offs"][0]["polo_a"]["defendido_por"] = ["p1"]
    anexo = funcoes.anexo_debate(tm, "- [p1] Fazenda: equilíbrio fiscal\n- [p2] Prefeituras: obras")
    assert anexo.startswith("## Anexo 2 – O debate em detalhe")
    assert "### Licitações" in anexo and "Defendida por: Fazenda." in anexo
    assert "Natureza do desacordo" in anexo and "apareceu em 2/2 rodadas" in anexo
    assert "nível" in anexo and "Nível" not in anexo.split("Informação:")[0]


def test_memorando_novo_sem_jargao_no_prompt_e_titulo_no_word(funcoes):
    import io
    import docx
    p = funcoes.PROMPT_ETAPA_2
    assert "PONTO FOCAL" in p and "## Urgências" in p and "NÃO RECOMENDE" in p and "NÃO use estes termos" in p
    assert p.index("## Urgências") < p.index("## Decisões em aberto") < p.index("## Outros riscos")
    memo = ("# Carteira de obras da SECID depende de dados ainda não confirmados\n\n## O essencial\n- ponto\n\n"
            "## Decisões a tomar\n### Prorrogar já?\n- **Opção 1 – Prorrogar:** x.\n\n## Anexo 1 – O debate em detalhe\ntexto")
    doc = docx.Document(io.BytesIO(funcoes.gerar_docx(memo, {"orgao": "Equipe de Transição", "assunto": ""})))
    textos = [par.text for par in doc.paragraphs]
    assert "Carteira de obras da SECID depende de dados ainda não confirmados" in textos     # título vem do memorando
    assert "O ESSENCIAL" in "\n".join(c.text for t in doc.tables for c in t._cells)          # quadro de destaque
    assert any('w:br w:type="page"' in par._p.xml for par in doc.paragraphs)                 # anexo em página nova


def test_fontes_no_anexo_com_links_e_selos(funcoes):
    d = dossie_exemplo(funcoes)
    md = funcoes.markdown_dossie(d)
    assert md.startswith("# Dossiê – ") and "## Visão geral" in md and "## O órgão" in md
    assert "✔ conferido na fonte" in md and "⚠" in md
    confronto = {"divergencias": [{"item": d["itens"][-1]["id"], "situacao": "contradiz", "o_orgao_declara": "100 obras",
                                   "trecho_relatorio": "100 obras", "as_fontes_mostram": "80 obras"}]}
    anexo = funcoes.markdown_fontes(d, confronto)
    assert anexo.startswith("## Anexo 1 – Fontes consultadas") and "\n# " not in anexo   # títulos descem um nível
    assert "**As fontes mostram:** 80 obras" in anexo and "### Visão geral" in anexo


def test_calendario_so_com_datas_conferidas(funcoes, llm):
    from datetime import date
    rel, _ = funcoes.limpar_relatorio(RELATORIO)
    cal = funcoes.extrair_calendario("anthropic/claude-sonnet-5-5", dossie_exemplo(funcoes), rel, "Secretaria de Exemplo",
                                     "04/11/2026")
    assert [(e["data"], e["origem"], e["criticidade"]) for e in cal["eventos"]] == [
        (date(2026, 10, 23), "Informado pelo órgão", "Vencido")]
    assert cal["eventos"][0]["valor"] == 398750000.0
    motivos = {d["evento"]: d["motivo"] for d in cal["descartados"]}
    assert motivos == {"Data trocada": "a data não está no trecho citado",
                       "Trecho inventado": "trecho não encontrado no relatório"}


def test_formas_de_data_e_valores(funcoes):
    from datetime import date
    assert funcoes._ler_data("31/12/2026") == (date(2026, 12, 31), False)
    assert funcoes._ler_data("03/2027") == (date(2027, 3, 1), True)
    assert funcoes._ler_data("31/02/2026") is None
    assert funcoes._norm("31 de dezembro de 2026") in funcoes._formas_da_data(date(2026, 12, 31), False)
    assert funcoes._valor_em_reais("R$ 998,1 mi") == 998100000.0 and funcoes._valor_em_reais("R$ 1,2 bi") == 1.2e9
    assert funcoes.criticidade(10).startswith("Crítico") and funcoes.criticidade(60).startswith("Atenção")


def test_calendario_em_excel(funcoes):
    import io
    from datetime import date
    from openpyxl import load_workbook
    eventos = [{"data": date(2027, 3, 1), "so_mes": True, "dias": 117, "criticidade": "Acompanhar", "orgao": "SECID",
                "tipo": "Contrato", "evento": "Fim da locação de máquinas", "objeto": "Contrato 12/2025", "valor": 5e6,
                "valor_texto": "R$ 5 mi", "consequencia": "Fica sem máquinas", "decisao": "Prorrogar ou não",
                "origem": "Informado pelo órgão", "fonte": "relatório do órgão", "trecho": "vence em 03/2027"},
               {"data": date(2026, 11, 11), "so_mes": False, "dias": 6, "criticidade": "Crítico (até 30 dias)",
                "orgao": "Estado", "tipo": "Prazo legal", "evento": "Fim das emendas", "objeto": "LOA 2027", "valor": None,
                "valor_texto": "", "consequencia": "", "decisao": "", "origem": "Fonte pública (dossiê)",
                "fonte": "https://alerj.exemplo/emendas", "trecho": "até 11/11/2026"}]
    wb = load_workbook(io.BytesIO(funcoes.calendario_xlsx(eventos, [{"orgao": "SECID", "data": "x", "evento": "y",
                                                                     "motivo": "z"}])))
    ws = wb["Calendário"]
    assert ws["A2"].value.date() == date(2026, 11, 11) and ws["D3"].value == "SECID"     # ordenado por data
    assert ws["M2"].hyperlink.target == "https://alerj.exemplo/emendas" and ws.auto_filter.ref
    assert ws["A3"].number_format == "mm/yyyy" and set(wb.sheetnames) == {"Prioridades", "Calendário", "Como ler", "Descartados"}


def test_diagnostico_so_com_afirmacoes_conferidas(funcoes, llm):
    rel, _ = funcoes.limpar_relatorio(RELATORIO)
    d = dossie_exemplo(funcoes)
    assert d["itens"][[i["id"] for i in d["itens"]].index("O1")]["afirmacao"].startswith("A LOA 2026")
    diag = funcoes.extrair_diagnostico("anthropic/claude-sonnet-5-5", d, rel, "Secretaria de Exemplo")
    assert [s["titulo"] for s in diag["secoes"]] == ["Orçamento e execução"] and diag["descartados"] == 2
    rotulos = [i["rotulo"] for i in diag["secoes"][0]["itens"]]
    assert rotulos[1] == "informado pelo órgão" and rotulos[0].startswith(("confirmado", "fonte pública"))
    md = funcoes.markdown_diagnostico(diag)
    assert md.startswith("## Diagnóstico do órgão") and "### Orçamento e execução" in md
    assert "### O que não se sabe" in md and "40 subsecretarias" not in md


def test_documento_unico_do_orgao(funcoes, llm):
    import io
    import docx
    rel, _ = funcoes.limpar_relatorio(RELATORIO)
    d = dossie_exemplo(funcoes)
    diag = funcoes.extrair_diagnostico("m", d, rel, "Secretaria de Exemplo")
    eventos = funcoes.extrair_calendario("m", d, rel, "Secretaria de Exemplo", "04/11/2026")["eventos"]
    assert eventos
    texto = funcoes.documento_orgao(MEMORANDO, diag, eventos, d, None, "## Anexo 2 – O debate em detalhe\nx",
                                    "## Anexo 3 – Como este documento foi feito\ny")
    ordem = [texto.index(t) for t in ["# Memorando", "## Diagnóstico do órgão", "### Vencimentos prioritários",
                                      "## Anexo 1", "## Anexo 2", "## Anexo 3"]]
    assert ordem == sorted(ordem)
    dados = funcoes.gerar_docx(texto, {"orgao": "Equipe", "data": "6 de novembro de 2026"})
    textos = [p.text for p in docx.Document(io.BytesIO(dados)).paragraphs]
    assert "Diagnóstico do órgão" in textos and "Anexo 1 – Fontes consultadas" in textos

def test_resposta_cortada_e_repetida_com_mais_espaco(funcoes, llm):
    from types import SimpleNamespace as NS
    pedidos = []

    def completion(model, messages, max_tokens, **kw):
        pedidos.append(max_tokens)
        cortada = len(pedidos) == 1
        texto = '[INÍCIO DO JSON]{"eventos": [{"data": "01/12/2026"' if cortada else \
            '[INÍCIO DO JSON]{"eventos": []}[FIM DO JSON]'
        return NS(choices=[NS(message=NS(content=texto, tool_calls=None), finish_reason="length" if cortada else "stop")],
                  usage=NS(prompt_tokens=10, completion_tokens=10))
    funcoes.usar_completion(completion)
    try:
        assert funcoes.chamar_json("anthropic/claude-sonnet-5-5", [{"role": "user", "content": "x"}], 8000) == {"eventos": []}
    finally:
        funcoes.usar_completion(None)
    assert pedidos == [8000, 16000]


def test_pontos_de_urgencia_ordenados_por_prazo_e_valor(funcoes):
    from datetime import date
    def ev(dias, valor, nome):
        from datetime import timedelta
        return {"data": date(2026, 11, 6) + timedelta(days=dias), "dias": dias, "valor": valor, "evento": nome, "objeto": "",
                "valor_texto": f"R$ {valor}", "origem": "Contratos do Estado (SIGA/PNCP)"}
    eventos = [ev(60, 300e6, "grande e distante"), ev(10, 1e6, "pequeno e próximo"), ev(20, 50e6, "médio e próximo"),
               ev(200, 900e6, "fora da janela")]
    for e in eventos:
        e["tipo"] = "Contrato"
    funcoes.avaliar_riscos(eventos, "06/11/2026")
    d = dossie_exemplo(funcoes)
    texto = funcoes.pontos_de_urgencia(eventos, d, {"divergencias": [
        {"situacao": "contradiz", "o_orgao_declara": "100 obras", "as_fontes_mostram": "80 obras"}]})
    linhas = texto.splitlines()
    assert linhas[1].startswith("- 2 vencimento(s) em até 30 dias, somando R$ 51,0 mi")
    ordem = [l for l in linhas if "dias):" in l]
    assert ["médio" in ordem[0], "grande" in ordem[1], "pequeno" in ordem[2]] == [True, True, True]   # impacto × urgência
    assert "fora da janela" not in texto and "Controle/Judiciário" in texto and "80 obras" in texto
    assert funcoes.pontos_de_urgencia([], {"itens": []}) == ""


def test_regua_de_risco_igual_para_todos(funcoes):
    from datetime import date, timedelta
    corte = date(2026, 11, 6)
    def ev(dias, valor, objeto, termos=None, tipo="Contrato"):
        return {"data": corte + timedelta(days=dias), "dias": dias, "valor": valor, "evento": "Fim do contrato",
                "objeto": objeto, "tipo": tipo, "valor_texto": "", "origem": "Contratos do Estado (SIGA/PNCP)",
                "termos": termos if termos is not None else ""}
    eventos = funcoes.avaliar_riscos([
        ev(40, 300e6, "PAVIMENTAÇÃO DE VIAS"),                                     # obra grande
        ev(40, 2e6, "FORNECIMENTO DE ALIMENTAÇÃO PARA PRESOS"),                    # essencial pequeno
        ev(40, 2e6, "ALIMENTAÇÃO HOSPITALAR", "Termo Aditivo Termo 1 (2026-10-20)"),  # essencial com aditivo
        ev(200, 1e6, "MATERIAL DE ESCRITÓRIO"),
    ], "06/11/2026")
    obra, presos, hospital, escritorio = eventos
    assert presos["essencial"] and presos["impacto"] == "Alto" and presos["categoria"].startswith("Continuidade")
    assert obra["categoria"] == "Obra" and obra["impacto"] == "Alto"
    assert presos["agir_ate"] == corte + timedelta(days=10) and presos["sem_tempo_licitar"]
    assert presos["prioridade"] == "Máxima" and hospital["prioridade_nota"] < presos["prioridade_nota"]
    assert "aditivo publicado em 20/10/2026" in hospital["situacao_pncp"]
    assert escritorio["prioridade"] == "Baixa" and not escritorio["sem_tempo_licitar"]
    md = funcoes.markdown_vencimentos(eventos)
    assert md.index("ALIMENTAÇÃO PARA PRESOS") < md.index("ALIMENTAÇÃO HOSPITALAR") and "serviço essencial" in md
    assert "contratos de gestão com OS" in md
    import io
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(funcoes.calendario_xlsx([dict(e, orgao="SEX", criticidade="x", so_mes=False,
                                consequencia="", decisao="", fonte="", trecho="") for e in eventos])))
    assert wb.sheetnames[0] == "Prioridades" and wb["Prioridades"]["A2"].value == "Máxima"

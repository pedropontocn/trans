"""Testes das funções do app, sem a interface."""
from conftest import FONTE_AUTO, FONTE_FALSA, FONTE_OK, RELATORIO, SEM_FONTE, dossie_exemplo, tension_map, trade_off


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


def test_completude_conta_campos_pendentes(funcoes):
    texto, _ = funcoes.limpar_relatorio(RELATORIO)
    comp = funcoes.indice_completude(texto)
    pendentes = {s["secao"] for s in comp["secoes"] if s["pendencias"]}
    assert any(s.startswith("1.2") for s in pendentes)     # dotação a complementar
    assert any(s.startswith("2.1") for s in pendentes)     # agenda com datas em branco
    assert any(s["secao"].startswith("1.1") and s["pendencias"] == 0 for s in comp["secoes"])  # seção completa
    assert 0 < comp["indice"] < 1


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
    # a completude do relatório só é informada: o relatório é autodeclaração
    c = funcoes.confianca_calculada(bom, estavel, vazio, completude={"indice": 0.2})
    assert c["nivel"] == "alta" and any("20%" in m for m in c["motivos"])
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


def test_tabela_editada_volta_para_os_itens(funcoes):
    d = dossie_exemplo(funcoes)
    linhas = funcoes.itens_para_tabela(d["itens"])
    linhas[0]["Incluir"] = False                                                  # excluído do debate
    linhas[3]["Link"] = "https://outro.exemplo/pagina"                            # mudou o link: checagem refeita
    linhas[4]["Conferido pela equipe"] = True
    linhas.append({"Incluir": None, "ID": None, "Camada": "Órgão", "Bloco": "pessoal", "Afirmação": "Nova linha",
                   "Tipo": "Imprensa", "Confiança": float("nan")})                # linha nova, com vazios do editor
    linhas.append({"Afirmação": float("nan")})                                    # linha vazia: ignorada
    del linhas[5]                                                                 # linha apagada
    itens = funcoes.tabela_para_itens(linhas, d["itens"])
    assert len(itens) == 9 and not itens[0]["incluir"]
    assert itens[3]["checagem"] == "nao_conferido" and itens[1]["checagem"] == d["itens"][1]["checagem"]
    assert itens[4]["conferido_pela_equipe"]
    nova = itens[-1]
    assert nova["id"] == "O7" and nova["incluir"] and nova["tipo_fonte"] == "imprensa" and nova["confianca"] == "baixa"
    assert len({i["id"] for i in itens}) == len(itens)


def test_dossie_pronto_e_lido_e_reconferido(funcoes):
    d = dossie_exemplo(funcoes)
    for i in d["itens"]:
        i["checagem"] = "conferido"                                              # o arquivo diz que tudo foi conferido...
    lido = funcoes.ler_dossie_arquivo(funcoes.dossie_para_json(d).encode("utf-8"))
    assert lido["origem"] == "arquivo" and len(lido["itens"]) == 9
    assert {i["id"]: i["checagem"] for i in lido["itens"]}["O5"] == "inacessivel"  # ...mas o código confere de novo
    import pytest
    with pytest.raises(ValueError):
        funcoes.ler_dossie_arquivo(b'{"nada": 1}')
    with pytest.raises(ValueError):
        funcoes.ler_dossie_arquivo(b'{"itens": [{"bloco": "x"}]}')


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
    quadro = funcoes.sobre_o_documento({"itens": 9, "conferidos": 6}, "04/11/2026", {"nivel": "média"}, 4)
    memo = funcoes.inserir_sobre_documento("# Memorando Executivo\n## Em síntese\n- x", quadro)
    linhas = memo.splitlines()
    assert linhas[0] == "# Memorando Executivo" and linhas[2] == "## Sobre este documento"
    assert "4 papéis institucionais simulados" in memo and "não recomenda" in memo
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

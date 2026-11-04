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

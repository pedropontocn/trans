"""Testes do app inteiro, com a interface do Streamlit e o modelo falso."""
import json
from pathlib import Path

from conftest import FONTE_FALSA, tension_map, trade_off


def _deliberar(at):
    next(b for b in at.button if "deliber" in b.label.lower()).click().run()
    assert not at.exception, at.exception
    return at.session_state["resultado"]


def test_upload_preenche_os_campos_sozinho(app, llm):
    at = app.run()
    assert not at.exception, at.exception
    assert at.session_state["problema"] == "Carteira travada na transição."
    assert at.session_state["fatos"].startswith("- Quatro concorrências")
    assert any("Preenchidos" in m.value for m in at.success)
    extracoes = [c for c in llm.chamadas if c["ferramenta"] == "registrar_insumos"]
    assert len(extracoes) == 1 and extracoes[0]["modelo"].endswith("sonnet-5-5")   # modelo da extração
    at.run()                                                                       # nova execução: não extrai de novo
    assert len([c for c in llm.chamadas if c["ferramenta"] == "registrar_insumos"]) == 1


def test_extracao_em_texto_com_nomes_diferentes(app, llm):
    llm.resposta_extracao_texto = json.dumps({"Problema Central": "X", "Fatos Ancoradores": ["F"],
                                              "Personas": ["P"], "Lacunas de Dados": ["L"]})
    llm.recusar_ferramentas = ModuleNotFoundError("No module named 'mcp'")
    at = app.run()
    assert not at.exception, at.exception
    assert at.session_state["problema"] == "X" and at.session_state["lacunas"] == "- L"


def test_deliberacao_com_uma_rodada(app, llm):
    at = app.run()
    at.slider[0].set_value(1).run()
    r = _deliberar(at)
    assert r["n_rodadas"] == 1 and r["confianca"]["nivel"] in ("baixa", "média")
    assert [c["ferramenta"] for c in llm.chamadas].count("registrar_tension_map") == 1
    # o relatório vai para o debate, marcado para cache
    partes = next(c for c in llm.chamadas if c["ferramenta"] == "registrar_tension_map")["mensagens"][1]["content"]
    assert partes[0]["cache_control"] and "<relatorio>" in partes[0]["text"]
    assert "QUALIDADE DO RELATÓRIO" in partes[1]["text"]


def test_tres_rodadas_com_estabilidade(app, llm):
    llm.rodadas = [tension_map([trade_off("T1", "Licitações"), trade_off("T2", "Atas")]),
                   tension_map([trade_off("T1", "Licitações adiadas"), trade_off("T2", "Obras", 1, FONTE_FALSA)]),
                   tension_map([trade_off("T1", "Atas SRP"), trade_off("T2", "Licitações sine die")])]
    llm.consolidacao = tension_map([trade_off("C1", "Licitações", origens=["R1-T1", "R2-T1", "R3-T2"]),
                                    trade_off("C2", "Atas", origens=["R1-T2", "R3-T1"]),
                                    trade_off("C3", "Obras", 1, FONTE_FALSA, origens=["R2-T2"])])
    at = app.run()
    r = _deliberar(at)
    tm = r["tension_map"]
    assert [(t["id"], t["estabilidade"]) for t in tm["trade_offs"]] == [("C1", "3/3"), ("C2", "2/3")]
    assert [f["id"] for f in tm["sinais_fracos"]] == ["C3"]
    assert [c["ferramenta"] for c in llm.chamadas].count("registrar_tension_map") == 3
    assert [c["ferramenta"] for c in llm.chamadas].count("registrar_consolidacao") == 1


def test_resultado_continua_na_tela_depois_de_um_download(app, llm):
    at = app.run()
    _deliberar(at)
    at.run()                                   # o clique num download faz o Streamlit rodar de novo
    assert not at.exception, at.exception
    assert len(at.tabs) == 4 and any("Deliberação concluída" in m.value for m in at.success)


def test_verificacao_e_registro(app, llm, tmp_path):
    at = app.run()
    r = _deliberar(at)
    situacoes = {n["valor"]: n["situacao"] for n in r["numeros"]}
    assert situacoes["R$ 999,9 mi"] == "não encontrado"
    assert situacoes["R$ 13,3 mi"] == "cálculo declarado"
    registros = list((tmp_path / "registros").glob("*.json"))
    assert len(registros) == 1
    dados = json.loads(registros[0].read_text(encoding="utf-8"))
    assert {"versao_prompt", "modelo_debate", "insumos", "verificacao", "uso_tokens"} <= set(dados)


def test_tension_map_incompleto_pede_correcao(app, llm):
    completo = tension_map([trade_off("T1", "Licitações")])
    incompleto = tension_map([trade_off("T1", "Licitações")], confidence_assessment=True)
    llm.rodadas = [incompleto, completo]
    at = app.run()
    at.slider[0].set_value(1).run()
    r = _deliberar(at)
    assert r["problemas_formato"] == []
    assert "confidence_assessment" in r["tension_map"]


def test_memorando_cortado_e_continuado(app, llm):
    llm.memorando_cortado_uma_vez = True
    at = app.run()
    at.slider[0].set_value(1).run()
    r = _deliberar(at)
    assert not r["memorando_cortado"]
    assert r["memorando"].count("## Matriz de Risco") == 1 and r["memorando"].rstrip().endswith("| Finanças |")


def test_revisao_de_neutralidade_confere_trechos(app, llm):
    at = app.run()
    at.slider[0].set_value(1).run()
    r = _deliberar(at)
    n = r["neutralidade"]
    assert n["avaliacao_geral"] == "levemente_enviesado"
    assert [t["id"] for t in n["desequilibrados"]] == ["T1"]
    # o trecho que existe no memorando fica; o inventado é descartado
    assert [x["trecho"] for x in n["recomendacoes_implicitas"]] == ["Definir o destino das licitações adiadas"]
    assert n["trechos_descartados"] == 1
    # a revisão usa o modelo da extração, diferente do que escreveu o memorando
    revisao = next(c for c in llm.chamadas if c["ferramenta"] == "registrar_neutralidade")
    assert revisao["modelo"].endswith("sonnet-5-5")
    assert any(u["etapa"] == "revisão de neutralidade" for u in r["uso"])


def test_falha_na_neutralidade_nao_derruba_a_analise(app, llm):
    llm.falhar_neutralidade = True
    at = app.run()
    at.slider[0].set_value(1).run()
    r = _deliberar(at)
    assert "erro" in r["neutralidade"] and r["memorando"]


def test_registro_pode_ser_baixado(app, llm):
    at = app.run()
    at.slider[0].set_value(1).run()
    r = _deliberar(at)
    registro = json.loads(r["registro_json"])
    assert registro["id"] == r["registro_id"]
    assert {"insumos", "tension_map", "memorando", "verificacao", "uso_tokens"} <= set(registro)
    assert "neutralidade" in registro["verificacao"]
    botoes = [b for b in at.get("download_button")]
    assert any("Registro" in getattr(b, "proto", b).label for b in botoes)


def test_comparacao_com_analise_anterior(app, llm):
    from streamlit.testing.v1 import AppTest

    from test_funcoes import RELATORIO_NOVO
    at = app.run()
    at.slider[0].set_value(1).run()
    primeiro = _deliberar(at)
    assert "retrato_relatorio" in json.loads(primeiro["registro_json"])

    # segunda análise: relatório atualizado + registro da primeira
    llm.texto_relatorio = RELATORIO_NOVO
    llm.registro_anterior = primeiro["registro_json"].encode("utf-8")
    at2 = AppTest.from_file(app._script_path, default_timeout=120).run()
    assert not at2.exception, at2.exception
    at2.slider[0].set_value(1).run()
    r = _deliberar(at2)
    c = r["comparacao"]
    assert c["anterior_id"] == primeiro["registro_id"]
    assert [p["secao"][:3] for p in c["relatorio"]["preenchidas"]] == ["1.2"]
    assert len(c["trade_offs"]["mantidos"]) == 2
    assert [t.label for t in at2.tabs][-1] == "🔄 Comparação"
    assert "comparacao_com" in json.loads(r["registro_json"])


def test_registro_invalido_mostra_erro(app, llm):
    llm.registro_anterior = b'{"nada": 1}'
    at = app.run()
    assert not at.exception, at.exception
    assert any("não é um registro de análise válido" in e.value for e in at.error)


PERSONAS_4 = ("- [p1] Fazenda: foco em caixa\n- [p2] Controle externo: legalidade\n"
              "- [p3] Beneficiário: cidadão na ponta\n- [p4] Casa Civil: coordenação política")


def _modo_independente(at, personas=PERSONAS_4):
    at.radio[0].set_value("Personas independentes").run()
    at.session_state["personas"] = personas
    return at


def test_modo_independente_completo(app, llm):
    llm.sintese = tension_map([trade_off("T1", "Licitações"), trade_off("T2", "Atas")])
    llm.sintese["trade_offs"][1]["polo_b"]["defendido_por"] = ["p9"]            # persona que não existe
    at = _modo_independente(app.run())
    r = _deliberar(at)
    d = r["debate"]
    fases = [c for c in llm.chamadas if "Você participa" in str(c["mensagens"][0]["content"])]
    assert len(fases) == 12                                                  # 4 personas × 3 fases
    assert all(c["modelo"].endswith("sonnet-5-5") for c in fases)
    aval = next(c for c in llm.chamadas if c["modelo"].startswith("gemini/"))
    assert aval["modelo"] == "gemini/gemini-3.1-pro-preview"
    # avaliação cega: o avaliador não vê nomes nem ids das personas
    for nome in ("Fazenda", "Controle externo", "p1", "p2"):
        assert nome not in llm.planos_vistos_pelo_avaliador.split("PLANOS:")[1]
    assert "Plano final de [omitido]" in llm.planos_vistos_pelo_avaliador
    assert all(x["avaliacao_cega"] for x in d["personas"])
    # críticas a alvos inexistentes são descartadas; cada persona recebe críticas reais
    assert all(c["alvo"] in {"p1", "p2", "p3", "p4"} for x in d["personas"] for c in x["criticas_recebidas"])
    assert d["personas"][0]["revisao"]["decisao"] == "REVISAR"
    # a síntese recebe o histórico real e o código confere quem defendeu cada polo
    assert "Plano final de p2" in llm.historico_sintese
    assert any("p9" in prob for prob in r["problemas_formato"])
    assert r["tension_map"]["modo_debate"]["avaliador"] == "gemini/gemini-3.1-pro-preview"
    assert any("de outra família" in m for m in r["confianca"]["motivos"])
    assert [t.label for t in at.tabs][-1] == "🗣️ Debate"
    assert json.loads(r["registro_json"])["modo_debate"] == "personas independentes"


def test_persona_que_nao_responde_fica_de_fora(app, llm):
    llm.personas_mudas = {"p3"}
    at = _modo_independente(app.run())
    r = _deliberar(at)
    assert r["debate"]["ausentes"] == ["p3"]
    assert any("p3" in prob and "Fase 1" in prob for prob in r["problemas_formato"])


def test_falha_do_avaliador_limita_a_confianca(app, llm):
    llm.falhar_avaliador = True
    at = _modo_independente(app.run())
    r = _deliberar(at)
    assert "GEMINI_API_KEY" in r["debate"]["erro_avaliacao"]
    assert r["confianca"]["nivel"] in ("baixa", "média")
    assert any("avaliação cega falhou" in m for m in r["confianca"]["motivos"])


def test_modo_independente_exige_tres_personas(app, llm):
    at = _modo_independente(app.run(), personas="- [p1] Fazenda\n- [p2] Controle")
    next(b for b in at.button if "deliber" in b.label.lower()).click().run()
    assert not at.exception, at.exception
    assert any("pelo menos 3 personas" in e.value for e in at.error)


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
    assert "LACUNAS IDENTIFICADAS NO DIAGNÓSTICO PRÉVIO" in debate["mensagens"][1]["content"][1]["text"]
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

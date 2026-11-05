"""Testes do app inteiro, com a interface do Streamlit e o modelo falso."""
import json

from conftest import FONTE_FALSA, tension_map, trade_off


def _deliberar(at):
    next(b for b in at.button if "deliber" in b.label.lower()).click().run()
    assert not at.exception, at.exception
    return at.session_state["resultado"]


def _botao(at, texto):
    next(b for b in at.button if texto in b.label).click().run()
    assert not at.exception, at.exception
    return at


def _preparar(at, orgao="Secretaria de Exemplo"):
    """Pesquisa o dossiê e prepara os insumos, como a equipe faria antes de deliberar."""
    at.text_input(key="orgao_analisado").input(orgao).run()
    _botao(at, "Pesquisar e montar o dossiê")
    _botao(at, "Preparar insumos")
    return at


def test_relatorio_nao_preenche_os_campos(app, llm):
    at = app.run()
    assert not at.exception, at.exception
    assert at.session_state["problema"] == "" and at.session_state["personas"] == ""
    assert any("autodeclaração" in m.value for m in at.caption)
    assert any("não preenche os campos" in m.value for m in at.success)
    assert not llm.chamadas                                   # ler o relatório não chama o modelo


def test_pesquisa_monta_o_dossie_e_confere_os_links(app, llm):
    at = app.run()
    at.text_input(key="orgao_analisado").input("Secretaria de Exemplo").run()
    _botao(at, "Pesquisar e montar o dossiê")
    d = at.session_state["dossie"]
    assert d["orgao"] == "Secretaria de Exemplo" and len(d["itens"]) == 9
    assert {i["id"]: i["checagem"] for i in d["itens"]}["O5"] == "inacessivel"
    assert all(c["kw"].get("web_search_options") for c in llm.chamadas)
    assert any("Dossiê: 9 itens incluídos, 6 conferidos" in e.label for e in at.expander)
    assert [m.value for m in at.metric][:4] == ["9", "6", "7", "2"]


def test_falha_na_pesquisa_mostra_erro_e_aceita_dossie_pronto(app, llm):
    llm.falhar_pesquisa = True
    at = app.run()
    at.text_input(key="orgao_analisado").input("Secretaria de Exemplo").run()
    _botao(at, "Pesquisar e montar o dossiê")
    assert any("Não foi possível pesquisar" in e.value for e in at.error)
    assert "dossie" not in at.session_state


def test_dossie_pronto_carregado(app, llm):
    from conftest import ITENS_ESTADO, ITENS_ORGAO
    llm.dossie_arquivo = json.dumps({"orgao": "Secretaria de Exemplo", "itens": ITENS_ESTADO + ITENS_ORGAO}).encode("utf-8")
    at = app.run()
    assert not at.exception, at.exception
    d = at.session_state["dossie"]
    assert d["origem"] == "arquivo" and len(d["itens"]) == 9
    assert [c for c in llm.chamadas] == []                   # carregar o dossiê não chama o modelo
    llm.dossie_arquivo = b"isto nao e json"
    at2 = app.__class__.from_file(app._script_path, default_timeout=120).run()
    assert any("não é um dossiê válido" in e.value for e in at2.error)


def test_insumos_vem_do_dossie(app, llm):
    at = _preparar(app.run())
    assert at.session_state["problema"].startswith("Carteira de licitações")
    assert "[baseline]" not in at.session_state["personas"] and "[controle] Controle externo" in at.session_state["personas"]
    assert "terceirizados" in at.session_state["sem_voz"]
    assert "Cinco obras" not in llm.mensagem_insumos


def test_deliberar_exige_dossie(app, llm):
    at = app.run()
    at.session_state["problema"] = "x"
    at.session_state["personas"] = "- [a] A: b"
    next(b for b in at.button if "deliber" in b.label.lower()).click().run()
    assert "resultado" not in at.session_state
    assert any("Monte o dossiê antes de deliberar" in w.value for w in at.warning)


def test_deliberacao_com_uma_rodada(app, llm):
    at = _preparar(app.run())
    at.slider[0].set_value(1).run()
    r = _deliberar(at)
    assert r["n_rodadas"] == 1 and r["confianca"]["nivel"] in ("baixa", "média")
    assert [c["ferramenta"] for c in llm.chamadas].count("registrar_tension_map") == 1
    # o dossiê e a autodeclaração vão juntos para o debate, em cache de 1 hora, antes das instruções da etapa
    chamada = next(c for c in llm.chamadas if c["ferramenta"] == "registrar_tension_map")
    partes = chamada["mensagens"][1]["content"]
    assert partes[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert partes[0]["text"].startswith("<dossie>") and "<relatorio>\nAUTODECLARAÇÃO DO ÓRGÃO" in partes[0]["text"]
    assert "<instrucoes>" in partes[1]["text"] and partes[1]["cache_control"] == {"type": "ephemeral"}
    assert "QUALIDADE DO RELATÓRIO" in partes[2]["text"] and "DIVERGÊNCIAS ENTRE A AUTODECLARAÇÃO" in partes[2]["text"]
    assert "[O1]" not in partes[2]["text"].split("DIVERGÊNCIAS")[0]      # o dossiê não vai duas vezes
    assert chamada["ferramentas"] == ["registrar_tension_map"]
    # o confronto entra no resultado e no memorando; o memorando abre com o quadro de proveniência
    assert [d["item"] for d in r["confronto"]["divergencias"]] == ["O2", "O1"]
    assert r["memorando"].splitlines()[2] == "## Sobre este documento"
    memo_call = next(c for c in llm.chamadas if "NESTA ETAPA: escreva a Fase 5" in str(c["mensagens"][0]["content"]))
    assert "[O1]" in memo_call["mensagens"][1]["content"] and "DIVERGÊNCIAS" in memo_call["mensagens"][1]["content"]
    assert any("O que o órgão declarou" in s.value for s in at.subheader)


def test_deliberacao_sem_relatorio(app, llm):
    llm.sem_relatorio = True
    at = _preparar(app.run())
    at.slider[0].set_value(1).run()
    r = _deliberar(at)
    chamada = next(c for c in llm.chamadas if c["ferramenta"] == "registrar_tension_map")
    assert "<relatorio>" not in chamada["mensagens"][1]["content"][0]["text"]
    assert r["confronto"]["divergencias"] == [] and r["completude"] is None
    assert not any("Você confronta" in str(c["mensagens"][0]) for c in llm.chamadas)


def test_tres_rodadas_com_estabilidade(app, llm):
    llm.rodadas = [tension_map([trade_off("T1", "Licitações"), trade_off("T2", "Atas")]),
                   tension_map([trade_off("T1", "Licitações adiadas"), trade_off("T2", "Obras", 1, FONTE_FALSA)]),
                   tension_map([trade_off("T1", "Atas SRP"), trade_off("T2", "Licitações sine die")])]
    llm.consolidacao = tension_map([trade_off("C1", "Licitações", origens=["R1-T1", "R2-T1", "R3-T2"]),
                                    trade_off("C2", "Atas", origens=["R1-T2", "R3-T1"]),
                                    trade_off("C3", "Obras", 1, FONTE_FALSA, origens=["R2-T2"])])
    llm.pareamento = {"pares": [{"anterior": "T1", "atual": "T1"}]}     # rodadas 1 e 2 divergem: roda a 3ª
    at = _preparar(app.run())
    r = _deliberar(at)
    tm = r["tension_map"]
    assert [(t["id"], t["estabilidade"]) for t in tm["trade_offs"]] == [("C1", "3/3"), ("C2", "2/3")]
    assert [f["id"] for f in tm["sinais_fracos"]] == ["C3"]
    assert [c["ferramenta"] for c in llm.chamadas].count("registrar_tension_map") == 3
    assert [c["ferramenta"] for c in llm.chamadas].count("registrar_consolidacao") == 1
    assert r["n_rodadas"] == 3 and "previstas" not in tm["estabilidade"]


def test_para_na_segunda_rodada_quando_as_duas_concordam(app, llm):
    llm.rodadas = [tension_map([trade_off("T1", "Licitações"), trade_off("T2", "Atas")]),
                   tension_map([trade_off("T1", "Licitações adiadas"), trade_off("T2", "Atas SRP")])]
    llm.consolidacao = tension_map([trade_off("C1", "Licitações", origens=["R1-T1", "R2-T1"]),
                                    trade_off("C2", "Atas", origens=["R1-T2", "R2-T2"])])
    at = _preparar(app.run())
    r = _deliberar(at)
    tm = r["tension_map"]
    assert [c["ferramenta"] for c in llm.chamadas].count("registrar_tension_map") == 2
    assert r["n_rodadas"] == 2 and r["n_rodadas_previstas"] == 3
    assert [(t["id"], t["estabilidade"]) for t in tm["trade_offs"]] == [("C1", "2/2"), ("C2", "2/2")]
    assert tm["estabilidade"]["previstas"] == 3
    assert any("não foram necessárias" in m for m in r["confianca"]["motivos"])
    # a checagem usa o modelo barato da extração
    checagem = next(c for c in llm.chamadas if "Pareie" in c["mensagens"][0]["content"])
    assert checagem["modelo"].endswith("sonnet-5-5")


def test_sem_parada_antecipada_roda_todas(app, llm):
    at = _preparar(app.run())
    at.checkbox(key="parar_cedo").uncheck().run()
    r = _deliberar(at)
    assert [c["ferramenta"] for c in llm.chamadas].count("registrar_tension_map") == 3
    assert r["n_rodadas"] == 3 and not any("Pareie" in str(c["mensagens"][0]["content"]) for c in llm.chamadas)


def test_resultado_continua_na_tela_depois_de_um_download(app, llm):
    at = _preparar(app.run())
    _deliberar(at)
    at.run()                                   # o clique num download faz o Streamlit rodar de novo
    assert not at.exception, at.exception
    assert len(at.tabs) == 4 and any("Deliberação concluída" in m.value for m in at.success)


def test_verificacao_e_registro(app, llm, tmp_path):
    at = _preparar(app.run())
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
    at = _preparar(app.run())
    at.slider[0].set_value(1).run()
    r = _deliberar(at)
    assert r["problemas_formato"] == []
    assert "confidence_assessment" in r["tension_map"]


def test_memorando_cortado_e_continuado(app, llm):
    llm.memorando_cortado_uma_vez = True
    at = _preparar(app.run())
    at.slider[0].set_value(1).run()
    r = _deliberar(at)
    assert not r["memorando_cortado"]
    assert r["memorando"].count("## Matriz de Risco") == 1 and r["memorando"].rstrip().endswith("| Finanças |")


def test_revisao_de_neutralidade_confere_trechos(app, llm):
    at = _preparar(app.run())
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
    at = _preparar(app.run())
    at.slider[0].set_value(1).run()
    r = _deliberar(at)
    assert "erro" in r["neutralidade"] and r["memorando"]


def test_registro_pode_ser_baixado(app, llm):
    at = _preparar(app.run())
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
    at = _preparar(app.run())
    at.slider[0].set_value(1).run()
    primeiro = _deliberar(at)
    assert "retrato_relatorio" in json.loads(primeiro["registro_json"])

    # segunda análise: relatório atualizado + registro da primeira
    llm.texto_relatorio = RELATORIO_NOVO
    llm.registro_anterior = primeiro["registro_json"].encode("utf-8")
    at2 = _preparar(AppTest.from_file(app._script_path, default_timeout=120).run())
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
    at = _modo_independente(_preparar(app.run()))
    r = _deliberar(at)
    d = r["debate"]
    fases = [c for c in llm.chamadas if "Você participa" in str(c["mensagens"][1:2])]
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
    at = _modo_independente(_preparar(app.run()))
    r = _deliberar(at)
    assert r["debate"]["ausentes"] == ["p3"]
    assert any("p3" in prob and "Fase 1" in prob for prob in r["problemas_formato"])


def test_falha_do_avaliador_limita_a_confianca(app, llm):
    llm.falhar_avaliador = True
    at = _modo_independente(_preparar(app.run()))
    r = _deliberar(at)
    assert "GEMINI_API_KEY" in r["debate"]["erro_avaliacao"]
    assert r["confianca"]["nivel"] in ("baixa", "média")
    assert any("avaliação cega falhou" in m for m in r["confianca"]["motivos"])


def test_modo_independente_exige_tres_personas(app, llm):
    at = _modo_independente(_preparar(app.run()), personas="- [p1] Fazenda\n- [p2] Controle")
    next(b for b in at.button if "deliber" in b.label.lower()).click().run()
    assert not at.exception, at.exception
    assert any("pelo menos 3 personas" in e.value for e in at.error)


def test_dossie_reaproveitado_em_nova_sessao(app, llm):
    from streamlit.testing.v1 import AppTest
    _preparar(app.run())
    pesquisas = lambda: len([c for c in llm.chamadas if c["kw"].get("web_search_options")])
    assert pesquisas() == 2
    outra = AppTest.from_file(app._script_path, default_timeout=120).run()      # outra sessão, mesma pesquisa
    outra.text_input(key="orgao_analisado").input("Secretaria de Exemplo").run()
    _botao(outra, "Pesquisar e montar o dossiê")
    assert pesquisas() == 2 and outra.session_state["dossie"]["reaproveitado"]
    assert any("reaproveitado" in c.value for c in outra.caption)
    _botao(outra, "Pesquisar de novo do zero")
    assert pesquisas() == 4 and not outra.session_state["dossie"]["reaproveitado"]

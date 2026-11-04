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

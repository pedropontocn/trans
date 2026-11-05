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
    assert at.session_state["orgao_analisado"] == "exemplo"   # o nome sai do arquivo (sem "relatório")


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
    assert partes[0]["cache_control"] == {"type": "ephemeral"}
    assert partes[0]["text"].startswith("<dossie>") and "<relatorio>\nAUTODECLARAÇÃO DO ÓRGÃO" in partes[0]["text"]
    assert "<instrucoes>" in partes[1]["text"] and partes[1]["cache_control"] == {"type": "ephemeral"}
    assert "QUALIDADE DO RELATÓRIO" in partes[2]["text"] and "DIVERGÊNCIAS ENTRE A AUTODECLARAÇÃO" in partes[2]["text"]
    assert "[O1]" not in partes[2]["text"].split("DIVERGÊNCIAS")[0]      # o dossiê não vai duas vezes
    assert chamada["ferramentas"] == ["registrar_tension_map"]
    # o confronto entra no resultado e no memorando; o memorando abre com o quadro de proveniência
    assert [d["item"] for d in r["confronto"]["divergencias"]] == ["O4", "O3"]
    assert r["memorando"].splitlines()[2] == "## Sobre este documento"
    memo_call = next(c for c in llm.chamadas if "NESTA ETAPA: escreva o memorando para um ALTO GESTOR" in str(c["mensagens"][0]["content"]))
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
    # a consolidação é mecânica: vai com o modelo auxiliar (Sonnet), não com o do debate (Opus)
    consolidacao = next(c for c in llm.chamadas if c["ferramenta"] == "registrar_consolidacao")
    debate = next(c for c in llm.chamadas if c["ferramenta"] == "registrar_tension_map")
    assert consolidacao["modelo"].endswith("sonnet-5-5") and debate["modelo"].endswith("opus-5-5")
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
    assert aval["modelo"] == "gemini/gemini-3.8-flash"           # o Flash funciona na cota gratuita do Gemini
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
    assert r["tension_map"]["modo_debate"]["avaliador"] == "gemini/gemini-3.8-flash"
    assert any("de outra família" in m for m in r["confianca"]["motivos"])
    assert [t.label for t in at.tabs][-1] == "🗣️ Debate"
    assert json.loads(r["registro_json"])["modo_debate"] == "personas independentes"


def test_persona_cortada_responde_de_novo_mais_curta(app, llm):
    llm.personas_prolixas = {"p1", "p2"}
    at = _modo_independente(_preparar(app.run()))
    r = _deliberar(at)
    assert r["debate"]["ausentes"] == []                       # as duas voltaram com a resposta curta
    etapas = [u["etapa"] for u in r["uso"]]
    assert "fase 1 · p1 (mais curta)" in etapas and "fase 1 · p3 (mais curta)" not in etapas


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
    assert pesquisas() == 5
    outra = AppTest.from_file(app._script_path, default_timeout=120).run()      # outra sessão, mesma pesquisa
    outra.text_input(key="orgao_analisado").input("Secretaria de Exemplo").run()
    _botao(outra, "Pesquisar e montar o dossiê")
    assert pesquisas() == 5 and outra.session_state["dossie"]["reaproveitado"]
    assert any("reaproveitado" in c.value for c in outra.caption)
    _botao(outra, "Pesquisar de novo do zero")
    assert pesquisas() == 10 and not outra.session_state["dossie"]["reaproveitado"]


def test_dossie_vazio_mostra_o_diagnostico(app, llm):
    from conftest import GRUPOS
    llm.grupos_sem_json = {g[0] for g in GRUPOS}
    llm.continuacao_sem_json = True
    at = app.run()
    at.text_input(key="orgao_analisado").input("Secretaria de Exemplo").run()
    _botao(at, "Pesquisar e montar o dossiê")
    assert any("Diagnóstico da pesquisa" in w.value for w in at.warning)
    diag = next(e for e in at.expander if e.label.startswith("Diagnóstico da pesquisa"))
    assert "5 de 5 buscas com problema" in diag.label
    assert any("a resposta não trouxe o JSON do dossiê" in m.value for m in at.markdown)
    assert any("Fiz as buscas" in c.value for c in at.code)


def test_orgao_e_documentos_lidos_do_drive(app, llm, monkeypatch):
    import lote
    from test_lote import DriveFalso
    drive = DriveFalso()
    monkeypatch.setattr(lote, "Drive", lambda credenciais: drive)
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", '{"client_email": "conta@projeto.iam.gserviceaccount.com"}')
    monkeypatch.setenv("DRIVE_PASTA_ID", "raiz")
    llm.sem_relatorio = True
    at = app.run()
    assert not at.exception, at.exception
    seletor = at.selectbox(key="orgao_drive")
    # secretarias e vinculadas, na ordem do lote; a pasta que repete o nome não vira órgão
    assert seletor.options == ["—", "Secretaria de Fazenda - SEFAZ",
                               "↳ Fundo Único de Previdência Social do Estado - RIOPREV", "Secretaria de Turismo - SETUR"]
    seletor.set_value("Secretaria de Fazenda - SEFAZ").run()
    assert at.session_state["orgao_analisado"] == "Secretaria de Fazenda - SEFAZ"
    next(b for b in at.button if "Ler os documentos de SEFAZ" in b.label).click().run()
    assert not at.exception, at.exception
    assert at.session_state["fonte_relatorio"] == "drive" and at.session_state["texto_relatorio"]
    m = at.session_state["manifesto_drive"]
    lidos = {x["arquivo"] for x in m["lidos"]}
    assert "Relatorio_de_Transicao_SEFAZ.docx" in lidos and "SEFAZ/anexo.docx" in lidos
    assert "Planilha_dos_Cargos_e_Telefones.xlsx" not in drive.baixados          # dados pessoais: nem baixa
    assert not any("rioprev" in x for x in lidos)                               # vinculada tem análise própria
    at.run()                                                                    # nova execução: o texto do Drive fica
    assert at.session_state["texto_relatorio"]
    # trocar de órgão apaga os documentos do anterior e põe o vínculo no nome da pesquisa
    at.selectbox(key="orgao_drive").set_value("↳ Fundo Único de Previdência Social do Estado - RIOPREV").run()
    assert at.session_state["orgao_analisado"] == ("Fundo Único de Previdência Social do Estado - RIOPREV "
                                                   "(vinculado à Secretaria de Fazenda - SEFAZ)")
    assert "texto_relatorio" not in at.session_state


def test_sem_drive_configurado_o_app_segue(app, llm):
    at = app.run()
    assert not at.exception, at.exception
    assert not [s for s in at.selectbox if s.key == "orgao_drive"]
    assert any("conta de serviço nos Secrets" in c.value for c in at.caption)


def _zip_bytes(arquivos):
    import io
    import zipfile
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for nome, texto in arquivos.items():
            z.writestr(nome, texto)
    return buffer.getvalue()


class _Enviado:
    def __init__(self, nome, dados):
        self.name, self.dados = nome, dados

    def getvalue(self):
        return self.dados


def test_pasta_do_drive_enviada_em_zip(app, llm, monkeypatch):
    import streamlit
    # como o Drive entrega "Fazer download" da pasta: o primeiro nível é a própria pasta
    pacote = _zip_bytes({
        "Secretaria de Fazenda - SEFAZ/Relatorio_de_Transicao.docx": "relatório",
        "Secretaria de Fazenda - SEFAZ/Contatos_e_telefones.xlsx": "telefones",
        "Secretaria de Fazenda - SEFAZ/SEFAZ/anexo.pdf": "anexo",
        "Secretaria de Fazenda - SEFAZ/Junta Comercial do Estado do Rio de Janeiro - JUCERJA/jucerja.pdf": "jucerja",
        "Secretaria de Fazenda - SEFAZ/video.mp4": "x"})
    original = streamlit.file_uploader

    def uploader(rotulo, *a, **k):
        if "pasta baixada" in rotulo:
            return [_Enviado("Secretaria de Fazenda - SEFAZ-20261105T131500Z-001.zip", pacote)]
        return original(rotulo, *a, **k)

    monkeypatch.setattr(streamlit, "file_uploader", uploader)
    at = app.run()
    assert not at.exception, at.exception
    assert at.session_state["fonte_relatorio"] == "zip" and at.session_state["texto_relatorio"]
    assert at.session_state["orgao_analisado"] == "Secretaria de Fazenda - SEFAZ"
    m = at.session_state["manifesto_drive"]
    lidos = {x["arquivo"] for x in m["lidos"]}
    assert lidos == {"Relatorio_de_Transicao.docx", "SEFAZ/anexo.pdf"}
    motivos = {x["arquivo"]: x["motivo"] for x in m["pulados"]}
    assert "dados pessoais" in motivos["Contatos_e_telefones.xlsx"] and "formato" in motivos["video.mp4"]
    # a vinculada que veio dentro do zip pode ser escolhida à parte
    seletor = at.selectbox(key="orgao_zip")
    assert seletor.options == ["Secretaria de Fazenda - SEFAZ", "↳ Junta Comercial do Estado do Rio de Janeiro - JUCERJA"]
    seletor.set_value("↳ Junta Comercial do Estado do Rio de Janeiro - JUCERJA").run()
    assert not at.exception, at.exception
    assert {x["arquivo"] for x in at.session_state["manifesto_drive"]["lidos"]} == {"jucerja.pdf"}


def test_zip_sem_pasta_no_primeiro_nivel(funcoes, llm):
    pacote = funcoes.ZipComoDrive([("SETUR.zip", _zip_bytes({"relatorio.pdf": "a", "anexos/b.docx": "b"})),
                                      ("solto.docx", b"c")])
    orgaos = pacote.orgaos()
    assert [o["nome"] for o in orgaos] == ["SETUR"]           # o nome do arquivo vira a pasta principal
    nomes = {i["name"] for i in pacote.listar(orgaos[0]["pastas"][0]["id"])}
    assert nomes == {"relatorio.pdf", "anexos", "solto.docx"}


def test_segundo_orgao_reaproveita_a_pesquisa_do_estado(app, llm):
    at = app.run()
    at.text_input(key="orgao_analisado").input("Secretaria de Exemplo").run()
    _botao(at, "Pesquisar e montar o dossiê")
    buscas = lambda: [c for c in llm.chamadas if c["kw"].get("web_search_options")]
    assert len(buscas()) == 5                                  # 2 grupos do Estado + 3 do órgão
    primeiro = at.session_state["dossie"]
    assert not primeiro["estado_reaproveitado"]
    assert any(i["camada"] == "estado" for i in primeiro["itens"])
    at.text_input(key="orgao_analisado").input("Outra Secretaria").run()
    _botao(at, "Pesquisar e montar o dossiê")
    segundo = at.session_state["dossie"]
    assert len(buscas()) == 8                                  # só os 3 grupos do órgão
    assert segundo["estado_reaproveitado"] and segundo["orgao"] == "Outra Secretaria"
    assert any(i["camada"] == "estado" for i in segundo["itens"])
    assert len(segundo["uso"]) < len(primeiro["uso"])          # o custo do Estado não é cobrado de novo
    assert any("contexto do Estado veio de uma pesquisa anterior" in c.value for c in at.caption)


def test_nomes_dos_orgaos_pelos_arquivos(funcoes):
    n = funcoes.nome_do_orgao_pelo_arquivo
    assert n("Resumo - Secretaria de Fazenda - SEFAZ.docx") == "Secretaria de Fazenda - SEFAZ"
    assert n("Relatório resumido da SETUR.pdf") == "SETUR"
    assert n("SEDEC_resumo_final.docx") == "SEDEC resumo final"
    itens = funcoes.resumos_do_envio([("RESUMOS-20261105T140000Z-001.zip", _zip_bytes({
        "RESUMOS/Resumo - SEFAZ.docx": "a", "RESUMOS/~$Resumo - SEFAZ.docx": "lixo", "RESUMOS/SETUR.pdf": "b",
        "RESUMOS/planilha.xlsx": "c", "__MACOSX/RESUMOS/._SETUR.pdf": "d"})), ("SEDEC.docx", b"e")])
    assert [(i["orgao"], i["arquivo"]) for i in itens] == [("SEDEC", "SEDEC.docx"), ("SEFAZ", "Resumo - SEFAZ.docx"),
                                                          ("SETUR", "SETUR.pdf")]


def test_varios_orgaos_em_segundo_plano(app, llm):
    llm.sem_relatorio = True
    llm.resumos_enviados = [_Enviado("RESUMOS-20261105T140000Z-001.zip", _zip_bytes({
        "RESUMOS/Resumo - Secretaria de Fazenda - SEFAZ.docx": "resumo sefaz",
        "RESUMOS/Resumo - Secretaria de Turismo - SETUR.pdf": "resumo setur"}))]
    at = app.run()
    assert not at.exception, at.exception
    tabela = at.session_state["varios_itens"]
    assert [i["orgao"] for i in tabela] == ["Secretaria de Fazenda - SEFAZ", "Secretaria de Turismo - SETUR"]
    at.checkbox(key="varios_economico").uncheck().run()
    at.slider[0].set_value(1).run()
    next(b for b in at.button if "Analisar 2 órgão" in b.label).click().run()
    assert not at.exception, at.exception
    # espera o trabalho em segundo plano terminar
    import threading
    fio = next(t for t in threading.enumerate() if t.name == "analise-varios-orgaos")
    fio.join(timeout=120)
    at.run()
    assert not at.exception, at.exception
    assert any("Análise concluída" in s.value and "2 de 2" in s.value for s in at.success)
    assert any("Baixar os resultados" in b.label for b in at.get("download_button"))


def test_debate_sem_personas_suficientes_mostra_o_motivo(app, llm, monkeypatch):
    class ErroDeAutenticacao(Exception):
        pass

    original = llm.__class__.__call__

    def chamada(self, model, messages, max_tokens, **kw):
        if "Você participa de uma deliberação multiagente" in str(messages[1:2]):
            raise ErroDeAutenticacao("invalid x-api-key")
        return original(self, model, messages, max_tokens, **kw)

    monkeypatch.setattr(llm.__class__, "__call__", chamada)
    at = _modo_independente(_preparar(app.run()))
    next(b for b in at.button if "deliber" in b.label.lower()).click().run()
    erros = " ".join(e.value for e in at.error)
    assert "0 de 4 personas responderam" in erros and "ErroDeAutenticacao: invalid x-api-key" in erros


def test_limite_por_minuto_tenta_de_novo(funcoes, monkeypatch):
    monkeypatch.setattr(funcoes.time, "sleep", lambda s: None) if hasattr(funcoes, "time") else None
    tentativas = []

    def chamada():
        tentativas.append(1)
        if len(tentativas) < 3:
            raise RuntimeError("litellm.RateLimitError: AnthropicException - 429 rate_limit_error")
        return "ok"

    assert funcoes._com_novas_tentativas(chamada) == "ok" and len(tentativas) == 3
    with __import__("pytest").raises(ValueError):
        funcoes._com_novas_tentativas(lambda: (_ for _ in ()).throw(ValueError("invalid x-api-key")))


def test_gemini_fora_do_ar_usa_o_avaliador_reserva(app, llm, monkeypatch):
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda s: None)          # as novas tentativas no 503 não esperam no teste
    llm.falhar_avaliador = "gemini"
    at = _modo_independente(_preparar(app.run()))
    r = _deliberar(at)
    d = r["debate"]
    assert d["erro_avaliacao"] is None and d["avaliador"] == "anthropic/claude-sonnet-5-5"
    assert d["avaliador_escolhido"] == "gemini/gemini-3.8-flash"
    assert all(x["avaliacao_cega"] for x in d["personas"])
    # tentou de novo o Gemini antes de trocar (503 é passageiro) e tentou o outro Gemini antes do Claude
    gemini = [c["modelo"] for c in llm.chamadas if c["modelo"].startswith("gemini/")]
    assert gemini.count("gemini/gemini-3.8-flash") == 4 and "gemini/gemini-3.1-pro-preview" in gemini
    assert any("feita por anthropic/claude-sonnet-5-5" in p for p in r["problemas_formato"])
    assert any("mesma família" in m for m in r["confianca"]["motivos"])
    assert any("Pontos de atenção" in w.value for w in at.warning)

"""O dossiê no roteiro da Equipe de Transição: estrutura, funcionamento, sobreposições e gargalos, e os itens a) a g).
Os itens 3 (gargalos) e g (plano dos 100 dias) são o único ponto em que a IA avalia e propõe; o código confere cada um."""
import io

from test_analise import CFG, RELATORIO, TITULOS_DO_ROTEIRO

FATOS = [
    {"id": "F16", "origem": "item c", "texto": "A limpeza é prestada pela AGILE CORP por meio de Termos de Ajuste de Contas, com R$ 69.395.936,65 registrados."},
    {"id": "F24", "origem": "item b", "texto": "A Inspeção Escolar informa déficit de 638 professores inspetores, com 400 em atuação direta."},
    {"id": "F25", "origem": "item f", "texto": "Há contratos registrados sem gestor e fiscais designados."},
    {"id": "V3", "origem": "calendário", "texto": "Contrato SEEDUC nº 29/2021 – SENAI, R$18.660.817,34 (Fim da vigência, já vencido), em 26/10/2026"},
    {"id": "R1", "origem": "relatório de riscos", "texto": "Pregão de limpeza sem data. Prazo: 30/01/2027."}]


def _ler(llm, resposta, fatos=FATOS):
    from transicao import propostas
    llm.leitura_institucional = resposta
    uso = []
    return propostas.ler(CFG["modelo"], "SEEDUC", fatos, "10/11/2026", uso), uso


def test_gargalos_e_acoes_so_entram_presos_aos_fatos(llm):
    g = lambda **k: dict({"tipo": "entrave administrativo", "titulo": "Limpeza por termos de ajuste de contas",
                          "descricao": "A limpeza é prestada por Termos de Ajuste de Contas, com R$ 69.395.936,65 registrados.",
                          "fatos": ["F16"]}, **k)
    a = lambda **k: dict({"prazo": "30 dias", "acao": "Definir a continuidade do Contrato SEEDUC nº 29/2021",
                          "por_que": "O contrato com o SENAI, de R$18.660.817,34, venceu em 26/10/2026.", "fatos": ["V3"]}, **k)
    leitura, uso = _ler(llm, {"gargalos": [
        g(),
        g(titulo="Limpeza por termos de ajuste de contas"),                                         # repetido
        g(titulo="Déficit na inspeção", tipo="tipo inventado", descricao="Faltam 638 inspetores.", fatos=["F24", "F999"]),
        g(titulo="Passivo de R$ 2 bilhões", descricao="Há um passivo de R$ 2.000.000.000,00.", fatos=["F16"]),   # número fora
        g(titulo="Sem fato", descricao="Nada sustenta.", fatos=["F999"]),
        g(titulo="Fiscalização", descricao="Cabe ao subsecretário designar os fiscais.", fatos=["F25"])],    # diz quem
      "acoes": [
        a(),
        a(acao="Recompor o quadro da Inspeção Escolar", por_que="Há déficit de 638 professores inspetores.", fatos=["F24"],
          prazo="100 dias"),
        a(acao="Levar o pregão de limpeza à fase externa até 30/01/2027", por_que="O pregão está sem data.", fatos=["R1"],
          prazo="em até 100 dias"),
        a(acao="Contratar 900 inspetores", por_que="Há déficit de 638 professores inspetores.", fatos=["F24"]),   # 900 não está
        a(acao="Designar fiscais", por_que="A designação fica a cargo da Subsecretaria Executiva.", fatos=["F25"]),
        a(acao="", por_que="x", fatos=["F25"]),
        a(acao="Definir a continuidade do Contrato SEEDUC nº 29/2021"),                               # repetida
        a(acao="Rever o termo de ajuste de contas da limpeza", por_que="São R$ 69,39 milhões registrados.", fatos=["F16"])]})
    assert [(x["tipo"], x["titulo"]) for x in leitura["gargalos"]] == [
        ("entrave administrativo", "Limpeza por termos de ajuste de contas"), ("gargalo operacional", "Déficit na inspeção")]
    assert leitura["gargalos"][1]["fatos"] == ["F24"] and leitura["gargalos"][1]["origens"] == ["item b"]
    assert [(x["prazo"], x["acao"]) for x in leitura["acoes"]] == [
        ("30 dias", "Definir a continuidade do Contrato SEEDUC nº 29/2021"),
        ("30 dias", "Rever o termo de ajuste de contas da limpeza"),          # "69,39" é o começo de 69.395.936,65
        ("100 dias", "Recompor o quadro da Inspeção Escolar"),
        ("100 dias", "Levar o pregão de limpeza à fase externa até 30/01/2027")]
    motivos = [r["motivo"] for r in leitura["recusados"]]
    assert motivos == ["repetido", "número que não está nos fatos citados: 2, 200000000000", "não cita fato que exista",
                       "diz quem deve fazer", "número que não está nos fatos citados: 900", "diz quem deve fazer",
                       "campo em branco", "repetida"]
    assert uso[0]["etapa"] == "dossiê: gargalos institucionais e plano dos 100 dias" and uso[0]["modelo"] == CFG["modelo"]
    assert '"id": "V3"' in llm.pedido_leitura and '"de": "calendário"' in llm.pedido_leitura
    # no máximo quatro providências por prazo
    muitas = [a(acao=f"Providência número {k} sobre o contrato", por_que="O contrato venceu em 26/10/2026.") for k in "abcdef"]
    leitura, _ = _ler(llm, {"gargalos": [], "acoes": muitas})
    assert len(leitura["acoes"]) == 4 and leitura["recusados"][-1]["motivo"] == "acima do limite do prazo"
    # sem fatos, nenhuma chamada
    antes = len(llm.chamadas)
    vazio, _ = _ler(llm, {"gargalos": [g()], "acoes": [a()]}, fatos=[])
    assert vazio == {"gargalos": [], "acoes": [], "recusados": []} and len(llm.chamadas) == antes


def test_itens_3_e_g_no_documento(llm, funcoes):
    from transicao import documentos
    leitura, _ = _ler(llm, {"gargalos": [{"tipo": "fragmentação de responsabilidades", "titulo": "Contratos sem gestor e fiscais",
                                         "descricao": "Há contratos registrados sem gestor e fiscais designados.", "fatos": ["F25", "F16"]}],
                            "acoes": [{"prazo": "30 dias", "acao": "Definir a continuidade do Contrato SEEDUC nº 29/2021",
                                       "por_que": "O contrato venceu em 26/10/2026.", "fatos": ["V3"]},
                                      {"prazo": "100 dias", "acao": "Recompor o quadro da Inspeção Escolar",
                                       "por_que": "Há déficit de 638 professores inspetores", "fatos": ["F24", "R1"]}]})
    md = documentos.markdown_capitulos({"secoes": []}, leitura=leitura, com_riscos=True)
    titulos = [l for l in md.splitlines() if l.startswith("## ")]
    assert titulos == (TITULOS_DO_ROTEIRO[:2] + ["## 3. Sobreposições, fragmentações e gargalos institucionais"]
                       + TITULOS_DO_ROTEIRO[2:] + ["## g) Propostas de ações para os primeiros 100 dias"])
    for linha in [
        "_Leitura da análise (IA) a partir dos fatos deste dossiê; não é informação da secretaria.",
        "- **Fragmentação de responsabilidades: Contratos sem gestor e fiscais.** Há contratos registrados sem gestor e "
        "fiscais designados. _(base: itens c e f)_",
        "_Propostas da análise (IA), para discussão, a partir dos fatos deste dossiê, do calendário da secretaria e do "
        "relatório de riscos. Não indicam responsável e não substituem a avaliação da equipe._",
        "**Primeiros 30 dias**",
        "- **Definir a continuidade do Contrato SEEDUC nº 29/2021.** O contrato venceu em 26/10/2026. _(base: calendário)_",
        "**Até os 100 dias**",
        "- **Recompor o quadro da Inspeção Escolar.** Há déficit de 638 professores inspetores. _(base: item b; relatório de riscos)_"]:
        assert linha in md, linha
    assert "F25" not in md and "V3" not in md and "(R1)" not in md                    # sem códigos no texto
    # sem gargalo e sem ação: o documento diz; sem a leitura (não rodou), os dois itens não aparecem
    vazio = documentos.markdown_capitulos({"secoes": []}, leitura={"gargalos": [], "acoes": []})
    assert "não apontou sobreposição, fragmentação ou gargalo institucional" in vazio
    assert "não chegou a uma proposta de ação sustentada pelos fatos" in vazio
    sem = documentos.markdown_capitulos({"secoes": []})
    assert "## 3." not in sem and "## g)" not in sem
    # capítulo com dois blocos traz o rótulo de cada um; bloco sem nada não deixa rótulo solto
    it = lambda t: {"id": "F1", "texto": t, "rotulo": "informado pelo órgão", "url": "", "origem_item": ""}
    diag = {"secoes": [{"titulo": "O que faz", "itens": [it("Executa a política de educação.")], "leitura": "", "nao_se_sabe": []},
                       {"titulo": "Funcionamento das unidades", "leitura": "", "nao_se_sabe": [],
                        "itens": [it("A SUPCON gere os contratos e depende da SUPLIC para licitar.")]},
                       {"titulo": "Pendências com controle e justiça", "itens": [it("Há uma determinação do TCE-RJ.")],
                        "leitura": "", "nao_se_sabe": []},
                       {"titulo": "Sistemas, convênios e parcerias", "itens": [], "leitura": "", "nao_se_sabe": []},
                       {"titulo": "Dificuldades e problemas", "itens": [it("Faltam fiscais de contrato.")], "leitura": "", "nao_se_sabe": []}]}
    md = documentos.markdown_capitulos(diag, tce_md="- Multas e débitos no TCE-RJ: nenhuma condenação de 2024 para cá.")
    assert "**O que faz**\n- Executa a política de educação.\n\n**Como as unidades atuam**\n- A SUPCON gere os contratos" in md
    assert "**Auditorias, controle e justiça**\n- Há uma determinação do TCE-RJ." in md and "**Convênios, cooperação e sistemas**" not in md
    assert md.index("Há uma determinação do TCE-RJ.") < md.index("- Multas e débitos no TCE-RJ:") < md.index("## e) Programas")
    assert "## f) Principais dificuldades e problemas identificados\n- Faltam fiscais de contrato." in md
    assert "## b) Cargos e força de trabalho\n_O material lido não traz informação conferida sobre este item._" in md
    # os fatos da leitura trazem a origem pelo item do roteiro
    fatos = documentos.fatos_para_a_leitura(diag, None, {"riscos": [{"id": "R1", "titulo": "Pregão sem data (F3)", "causa": "x",
                                                                    "consequencia": "y", "decisao": "z", "prazo": "30/01/2027"}]})
    assert [(f["id"], f["origem"]) for f in fatos] == [("F1", "item 2"), ("F1", "item 2"), ("F1", "item d"), ("F1", "item f"),
                                                       ("R1", "relatório de riscos")]
    assert fatos[-1]["texto"] == "Pregão sem data. x. y. z. Prazo: 30/01/2027."


def test_rodada_do_dossie_no_roteiro(llm, tmp_path):
    import docx
    from transicao import analise
    llm.leitura_institucional = {
        "gargalos": [{"tipo": "gargalo operacional", "titulo": "Licitações adiadas", "fatos": ["F3"],
                      "descricao": "O órgão informa R$ 398,75 milhões empenhados até 23/10/2026."}],
        "acoes": [{"prazo": "30 dias", "acao": "Definir o destino das licitações adiadas", "fatos": ["R1", "V1"],
                   "por_que": "As concorrências estão adiadas e as obras não começam."},
                  {"prazo": "30 dias", "acao": "Definir a situação do Contrato 99/2026", "fatos": ["R1"],      # 99 não está no fato
                   "por_que": "O contrato vence antes da posse."}]}
    r = analise.analisar_orgao("Secretaria de Exemplo", RELATORIO, CFG)
    md = r["dossie_md"]
    titulos = [l for l in md.splitlines() if l.startswith("## ")]
    assert titulos == (["## Panorama"] + TITULOS_DO_ROTEIRO[:2] + ["## 3. Sobreposições, fragmentações e gargalos institucionais"]
                       + TITULOS_DO_ROTEIRO[2:] + ["## g) Propostas de ações para os primeiros 100 dias", "## Fontes"])
    assert "- **Gargalo operacional: Licitações adiadas.**" in md
    assert "- **Definir o destino das licitações adiadas.** As concorrências estão adiadas e as obras não começam." in md
    assert "Contrato 99/2026.** O contrato vence antes da posse" not in md
    assert r["registro"]["gargalos_e_cem_dias"]["recusados"][0]["motivo"] == "número que não está nos fatos citados: 99"
    assert "relatório de riscos)_" in md and ", do calendário da secretaria e do relatório de riscos. Não indicam responsável" in md
    assert "Descreve; só os itens 3 e g trazem leitura e proposta da análise." in md.split("\n")[0]
    assert "a leitura dos gargalos (item 3) e as propostas para os 100 dias (item g) são da análise" in md.rstrip().split("\n")[-1]
    assert r["registro"]["gargalos_e_cem_dias"]["acoes"][0]["fatos"] == ["R1", "V1"]
    assert any(u["etapa"] == "dossiê: gargalos institucionais e plano dos 100 dias" for u in r["registro"]["uso_tokens"])
    # os riscos da rodada entram como fatos da leitura; o relatório de riscos continua sem proposta
    assert '"de": "relatório de riscos"' in llm.pedido_leitura and '"de": "calendário"' in llm.pedido_leitura
    assert "Propostas da análise" not in r["riscos_md"] and "Primeiros 30 dias" not in r["riscos_md"]
    textos = [p.text for p in docx.Document(io.BytesIO(r["dossie_docx"])).paragraphs]
    assert "g) Propostas de ações para os primeiros 100 dias" in textos and "Fontes" in textos
    # só relatório de riscos: a leitura não roda
    antes = sum("Você apoia a Equipe de Transição de Governo" in str(c["mensagens"][0]["content"]) for c in llm.chamadas)
    r = analise.analisar_orgao("Secretaria de Exemplo", RELATORIO, dict(CFG, produtos=["riscos"]))
    assert sum("Você apoia a Equipe de Transição de Governo" in str(c["mensagens"][0]["content"]) for c in llm.chamadas) == antes
    assert r["registro"]["gargalos_e_cem_dias"] is None
    # a leitura fora do ar não derruba o dossiê: os itens 3 e g não aparecem, e o problema fica registrado
    llm.leitura_institucional = "isto não é um objeto"
    r = analise.analisar_orgao("Secretaria de Exemplo", RELATORIO, dict(CFG, produtos=["dossie"]))
    assert "## c) Contratos relevantes" in r["dossie_md"] and "## Panorama" in r["dossie_md"]


def test_linha_do_tce_no_item_de_auditorias(monkeypatch, tmp_path):
    from test_tce import DEBITOS, MULTAS
    from transicao import documentos, tce
    monkeypatch.delenv("TCE_DESLIGADO", raising=False)
    monkeypatch.setenv("PASTA_REGISTROS", str(tmp_path / "registros"))
    tce._MEMORIA.clear(); tce._FALHAS.clear()
    monkeypatch.setattr(tce, "_baixar_json", lambda caminho, params: MULTAS if params["tipo"] == "multa" else DEBITOS)
    linha = tce.linha_do_dossie(tce.cruzar("SEEDUC", "Processo 100144-5/2022.", "10/11/2026"))
    assert linha.startswith("- Multas e débitos no TCE-RJ: de 2024 para cá, 3 condenações em multa e 2 condenações em débito, em "
                            "3 processos do órgão e das vinculadas; 2 não aparecem no material enviado (100372-5/2019, "
                            "100500-2/2023). _(fonte oficial ✔: [TCE-RJ, dados abertos, consulta em ")
    assert "R$" not in linha
    sem = tce.linha_do_dossie(tce.cruzar("SETUR", "", "10/11/2026"))
    assert sem.startswith("- Multas e débitos no TCE-RJ: nenhuma condenação de 2024 para cá em processos do órgão")
    assert tce.linha_do_dossie(None) == ""
    tce._MEMORIA.clear()
    monkeypatch.setenv("PASTA_REGISTROS", str(tmp_path / "outra"))
    monkeypatch.setattr(tce, "_baixar_json", lambda caminho, params: (_ for _ in ()).throw(OSError("fora do ar")))
    assert tce.linha_do_dossie(tce.cruzar("SEEDUC", "", "10/11/2026")) == ""          # sem consulta, sem linha
    fontes = documentos.fontes_do_dossie({}, {}, tce_md=linha)
    assert "- [TCE-RJ, dados abertos (multas e débitos)](https://dados.tcerj.tc.br/api/v1/docs) · ✔ base oficial, lida por código" in fontes
    tce._MEMORIA.clear(); tce._FALHAS.clear()

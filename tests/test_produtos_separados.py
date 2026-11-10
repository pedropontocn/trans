"""Cada produto sozinho: a rodada só faz as etapas de que ele precisa e só grava o que foi pedido."""
import json

from test_analise import CFG, _zip

ENVIO = [("resumos.zip", _zip({"SETUR - Turismo.docx": b"a"}))]


def _etapas_chamadas(llm):
    from transicao import pesquisa, riscos
    textos = [json.dumps(c["mensagens"], ensure_ascii=False) for c in llm.chamadas]
    analise_de_riscos = riscos.PROMPT_ANALISE[:80]
    return {"riscos": any(json.dumps(analise_de_riscos, ensure_ascii=False)[1:-1] in t for t in textos),
            "pesquisa": any(json.dumps(pesquisa.PROMPT_PESQUISA[:80], ensure_ascii=False)[1:-1] in t for t in textos),
            "calendario": any("calend" in t.lower() for t in textos)}


def _arquivos(pasta):
    return sorted(str(p.relative_to(pasta)) for p in pasta.rglob("*") if p.is_file() and p.parent.name != "auditoria"
                  and p.name != "contexto_estado.json" and "registros" not in p.parts)


def test_so_calendario_e_barato_e_so_grava_o_calendario(llm, tmp_path):
    from transicao import analise, entrada
    linhas = analise.rodar_orgaos(entrada.orgaos_do_envio(ENVIO), dict(CFG, produtos=["calendario"]), tmp_path,
                                  log=lambda *_: None)
    assert linhas[0]["situacao"] == "concluído", linhas[0]
    feitas = _etapas_chamadas(llm)
    assert not feitas["riscos"] and not feitas["pesquisa"] and feitas["calendario"]
    assert _arquivos(tmp_path) == ["LEIA-ME.txt", "calendarios/setur_turismo_calendario.xlsx", "resumo.csv"]
    leia = (tmp_path / "LEIA-ME.txt").read_text(encoding="utf-8")
    assert "Produtos pedidos nesta rodada: Calendário." in leia and "riscos/" not in leia
    assert linhas[0]["dossie"] == "não usado" and linhas[0]["datas_calendario"] >= 1


def test_so_dossie_nao_roda_a_analise_de_riscos(llm, tmp_path):
    from transicao import analise, entrada
    linhas = analise.rodar_orgaos(entrada.orgaos_do_envio(ENVIO), dict(CFG, produtos=["dossie"]), tmp_path,
                                  log=lambda *_: None)
    assert linhas[0]["situacao"] == "concluído", linhas[0]["observacao"]
    assert not _etapas_chamadas(llm)["riscos"]
    assert _arquivos(tmp_path) == ["LEIA-ME.txt", "dossies/setur_turismo_dossie.docx", "resumo.csv"]
    registro = json.loads((tmp_path / "auditoria" / "setur_turismo.json").read_text(encoding="utf-8"))
    assert registro["produtos"] == ["dossie"] and registro["riscos"]["riscos"] == []
    assert "## Panorama" in registro["dossie_md"]


def test_so_painel_roda_os_riscos_mas_so_grava_o_painel(llm, tmp_path):
    from transicao import analise, entrada
    linhas = analise.rodar_orgaos(entrada.orgaos_do_envio(ENVIO), dict(CFG, produtos=["painel"]), tmp_path,
                                  log=lambda *_: None)
    assert linhas[0]["situacao"] == "concluído" and _etapas_chamadas(llm)["riscos"]
    assert _arquivos(tmp_path) == ["LEIA-ME.txt", "paineis/setur_turismo_painel.json", "resumo.csv"]


def test_retomada_nao_reaproveita_rodada_com_outros_produtos(llm, tmp_path):
    from transicao import analise, entrada
    orgaos = entrada.orgaos_do_envio(ENVIO)
    analise.rodar_orgaos(orgaos, dict(CFG, produtos=["calendario"]), tmp_path, log=lambda *_: None)
    assert analise.resultado_pronto(tmp_path, "setur_turismo", {"calendario"})
    assert analise.resultado_pronto(tmp_path, "setur_turismo", {"dossie", "calendario"}) is None
    mensagens = []
    analise.rodar_orgaos(orgaos, dict(CFG, produtos=["dossie", "calendario"]), tmp_path, log=mensagens.append)
    assert not any("já estava pronto" in m for m in mensagens)
    assert (tmp_path / "dossies" / "setur_turismo_dossie.docx").exists()


def test_varios_arquivos_da_mesma_secretaria_viram_uma_so(llm):
    from transicao import entrada
    envio = [("SEEDUC - apresentação.docx", b"a"), ("SEEDUC - ofício.pdf", b"b"), ("Educação - SEEDUC.xlsx", b"c"),
             ("SETUR - Turismo.docx", b"d"), ("SEI 123.pdf", b"e")]
    orgaos = {o["nome"]: o["arquivos"] for o in entrada.orgaos_do_envio(envio)}
    assert sorted(orgaos["SEEDUC"]) == sorted(["SEEDUC - apresentação.docx", "SEEDUC - ofício.pdf",
                                               "Educação - SEEDUC.xlsx"])
    assert "SETUR - Turismo" in orgaos and "SEI 123" in orgaos             # sozinho, o nome fica como estava
    seeduc = next(o for o in entrada.orgaos_do_envio(envio) if o["nome"] == "SEEDUC")
    texto, manifesto = seeduc["ler"]()
    assert texto.count("# ARQUIVO:") == 3 and len(manifesto["lidos"]) == 3


def test_planilha_grande_corta_por_aba_e_o_total_fica_no_limite(llm):
    # a planilha da SEEDUC tinha 12 milhões de caracteres: o corte no fim deixava só as primeiras abas
    from transicao import entrada
    grande = "## Escolas\n| Escola | Município |\n| --- | --- |\n" + "".join(
        f"| Escola {k} | Município {k % 92} |\n" for k in range(40000))
    abas = grande + "\n## Contratos\n| Nº | Objeto |\n| --- | --- |\n| 1 | Vigilância |\n" + \
        "\n## Programas\n| Programa | Situação |\n| --- | --- |\n" + "".join(f"| Programa {k} | ativo |\n" for k in range(9000))
    manifesto = {"lidos": [], "pulados": [], "erros": [], "cortados": []}
    textos = [("Relatório.pdf", "Relatório da secretaria. " * 4000), ("Modelo_Integrado.xlsx", abas)]
    texto = entrada.montar_material(textos, manifesto, 200_000)
    assert len(texto) <= 200_000
    assert "|1|Vigilância|" in texto and "|Programa 0|ativo|" in texto           # todas as abas entram
    assert "Relatório da secretaria." in texto
    corte = manifesto["cortados"][0]
    assert corte["arquivo"] == "Modelo_Integrado.xlsx"
    assert {a["aba"] for a in corte["abas_cortadas"]} == {"Escolas", "Programas"}  # a pequena entrou inteira
    assert texto.count("[… aba cortada para caber no limite:") == 2
    # cada corte é no fim de uma linha: nenhuma linha de tabela pela metade
    assert all(l.endswith("|") for l in texto.split("\n") if l.startswith("|"))


def test_arquivos_soltos_dividem_o_limite(llm, monkeypatch):
    # no envio de arquivos soltos, o último arquivo não some inteiro: cada um tem a sua parte
    from transicao import entrada
    monkeypatch.setattr(entrada, "LIMITE_CARACTERES", 50_000)
    llm.texto_relatorio = "Texto longo do relatório. " * 5000
    texto, manifesto = entrada.orgaos_do_envio([("SEEDUC - a.docx", b"a"), ("SEEDUC - b.docx", b"b")])[0]["ler"]()
    assert len(texto) <= 50_000 and texto.count("# ARQUIVO:") == 2
    assert manifesto["cortados"] and {l["arquivo"] for l in manifesto["lidos"]} == {"SEEDUC - a.docx", "SEEDUC - b.docx"}

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

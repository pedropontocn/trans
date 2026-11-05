"""Testes do processamento em lote, com um Drive falso que imita as pastas reais (cópias, vinculadas, zip do SEI)."""
import csv
import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import lote  # noqa: E402

PASTA = lote.PASTA_MIME


def _zip(arquivos):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for nome, texto in arquivos.items():
            z.writestr(nome, texto)
    return buffer.getvalue()


class DriveFalso:
    """Árvore: id -> lista de itens. Conteúdo dos arquivos: id -> bytes."""

    def __init__(self):
        self.arvore = {
            "raiz": [{"id": "sefaz", "name": "Secretaria de Fazenda - SEFAZ", "mimeType": PASTA},
                     {"id": "setur", "name": "Secretaria de Turismo - SETUR", "mimeType": PASTA},
                     {"id": "solto", "name": "leia-me.txt", "mimeType": "text/plain"}],
            "sefaz": [{"id": "f1", "name": "Relatorio_de_Transicao_SEFAZ.docx", "mimeType": "application/docx"},
                      {"id": "f2", "name": "Planilha_dos_Cargos_e_Telefones.xlsx", "mimeType": "application/xlsx"},
                      {"id": "f3", "name": "SEI_260001.zip", "mimeType": "application/x-zip-compressed"},
                      {"id": "f4", "name": "video.mp4", "mimeType": "video/mp4"},
                      {"id": "f5", "name": "Notas da equipe", "mimeType": "application/vnd.google-apps.document"},
                      {"id": "f6", "name": "enorme.pdf", "mimeType": "application/pdf", "size": "40000000"},
                      {"id": "copia", "name": "SEFAZ", "mimeType": PASTA},
                      {"id": "rioprev", "name": "Fundo Único de Previdência Social do Estado - RIOPREV", "mimeType": PASTA}],
            "copia": [{"id": "f7", "name": "anexo.docx", "mimeType": "application/docx"}],
            "rioprev": [{"id": "f8", "name": "rioprev.docx", "mimeType": "application/docx"},
                        {"id": "anexos_rp", "name": "Anexos", "mimeType": PASTA}],
            "anexos_rp": [{"id": "f9", "name": "atuarial.pdf", "mimeType": "application/pdf"}],
            "setur": [{"id": "copia_setur", "name": "Secretaria de Turismo", "mimeType": PASTA}],
            "copia_setur": [{"id": "f10", "name": "relatorio_setur.pdf", "mimeType": "application/pdf"}],
        }
        self.conteudo = {
            "f1": "Relatório da SEFAZ. Contato: (21) 2334-5678. PPA 2024-2027. CPF 123.456.789-09.".encode(),
            "f2": b"nomes e telefones",
            "f3": _zip({"despacho.pdf": "Despacho do processo SEI.", "foto.jpg": "x", "contatos.xlsx": "telefones"}),
            "f5": "Notas exportadas do Google Docs.".encode(),
            "f7": "Anexo da pasta copiada.".encode(),
            "f8": "Relatório do RIOPREV.".encode(),
            "f9": "Avaliação atuarial.".encode(),
            "f10": "Relatório da SETUR.".encode(),
        }
        self.baixados = []

    def listar(self, pasta_id):
        return self.arvore.get(pasta_id, [])

    def baixar(self, arquivo):
        self.baixados.append(arquivo["name"])
        return self.conteudo[arquivo["id"]]


def converter_texto(nome, dados):
    return dados.decode("utf-8")


def test_siglas_e_copias():
    assert lote.sigla("Secretaria de Fazenda - SEFAZ") == "SEFAZ"
    assert lote.sigla("Fundação de Previdência Complementar do Estado - RJPREV") == "RJPREV"
    assert lote.sigla("Secretaria de Defesa de Consumidor SEDCON") == "SEDCON"
    assert lote.e_copia_da_pasta("SEFAZ", "Secretaria de Fazenda - SEFAZ")
    assert lote.e_copia_da_pasta("Secretaria de Turismo", "Secretaria de Turismo - SETUR")
    assert lote.e_copia_da_pasta("Secretaria de Defesa de Consumidor SEDCON", "Secretaria de Estado de Defesa do Consumidor - SEDCON")
    assert not lote.e_copia_da_pasta("Junta Comercial do Estado do Rio de Janeiro - JUCERJA", "Secretaria de Fazenda - SEFAZ")
    assert not lote.e_copia_da_pasta("FUNDAÇÃO SAÚDE ", "Secretaria de Estado de Saúde - SES")


def test_planejamento_separa_vinculadas_e_junta_copias():
    orgaos = lote.planejar_orgaos(DriveFalso(), "raiz")
    resumo = [(o["sigla"], o["vinculada_a"], [p["id"] for p in o["pastas"]]) for o in orgaos]
    assert resumo == [("SEFAZ", "", ["sefaz", "copia"]),
                      ("RIOPREV", "Secretaria de Fazenda - SEFAZ", ["rioprev", "anexos_rp"]),
                      ("SETUR", "", ["setur", "copia_setur"])]
    assert [o["sigla"] for o in lote.filtrar_orgaos(orgaos, "setur, previdência")] == ["RIOPREV", "SETUR"]
    assert [o["sigla"] for o in lote.fatia(orgaos, 2, 2)] == ["RIOPREV"]


def test_documentos_lidos_com_filtros_de_formato_e_dados_pessoais():
    drive = DriveFalso()
    sefaz = lote.planejar_orgaos(drive, "raiz")[0]
    texto, m = lote.ler_documentos(drive, sefaz, converter_texto, 150_000)
    lidos = [x["arquivo"] for x in m["lidos"]]
    assert lidos[0] == "Relatorio_de_Transicao_SEFAZ.docx"            # relatórios primeiro
    assert set(lidos) == {"Relatorio_de_Transicao_SEFAZ.docx", "SEI_260001.zip/despacho.pdf", "Notas da equipe",
                          "SEFAZ/anexo.docx"}
    pulados = {x["arquivo"]: x["motivo"] for x in m["pulados"]}
    assert "dados pessoais" in pulados["Planilha_dos_Cargos_e_Telefones.xlsx"]
    assert "dados pessoais" in pulados["SEI_260001.zip/contatos.xlsx"]
    assert "formato" in pulados["video.mp4"] and "30 MB" in pulados["enorme.pdf"]
    assert "Planilha_dos_Cargos_e_Telefones.xlsx" not in drive.baixados and "enorme.pdf" not in drive.baixados
    # dados pessoais apagados do texto; anos e valores ficam
    assert "2334-5678" not in texto and "123.456.789-09" not in texto and "PPA 2024-2027" in texto
    assert "# ARQUIVO: SEI_260001.zip/despacho.pdf" in texto


def test_textos_longos_sao_cortados_dentro_do_limite():
    drive = DriveFalso()
    drive.conteudo["f1"] = ("relatório " * 5000).encode()
    sefaz = lote.planejar_orgaos(drive, "raiz")[0]
    texto, m = lote.ler_documentos(drive, sefaz, converter_texto, 10_000)
    assert [c["arquivo"] for c in m["cortados"]] == ["Relatorio_de_Transicao_SEFAZ.docx"]
    assert len(texto) < 12_000 and "cortado para caber no limite" in texto


def test_apenas_listar_nao_chama_modelo(tmp_path, llm):
    linhas = lote.principal(["--pasta", "raiz", "--apenas-listar", "--saida", str(tmp_path)], drive=DriveFalso(), app={})
    assert [(x["sigla"], x["arquivos"], x["pulados_por_dados_pessoais"]) for x in linhas] == [
        ("SEFAZ", 7, 1), ("RIOPREV", 2, 0), ("SETUR", 1, 0)]
    assert not llm.chamadas
    assert json.loads((tmp_path / "orgaos.json").read_text(encoding="utf-8"))[0]["orgao"] == "Secretaria de Fazenda - SEFAZ"


def test_lote_completo_sem_parar(tmp_path, llm):
    app = lote.carregar_app()
    linhas = lote.principal(["--pasta", "raiz", "--orgaos", "SEFAZ,RIOPREV", "--rodadas", "1", "--saida", str(tmp_path),
                             "--data-corte", "04/11/2026"], drive=DriveFalso(), app=app)
    assert [(x["sigla"], x["situacao"]) for x in linhas] == [("SEFAZ", "concluído"), ("RIOPREV", "concluído")]
    pasta = tmp_path / "sefaz"
    for arquivo in ("memorando.docx", "memorando.md", "tension_map.json", "dossie.json", "dossie.docx", "registro.json", "arquivos_lidos.json"):
        assert (pasta / arquivo).exists(), arquivo
    registro = json.loads((pasta / "registro.json").read_text(encoding="utf-8"))
    assert registro["origem"] == "lote" and registro["dossie_revisado"] is False
    memo = (pasta / "memorando.md").read_text(encoding="utf-8")
    assert "sem revisão da equipe" in memo
    # o órgão vinculado é pesquisado com o nome da secretaria-mãe
    pesquisas = [str(c["mensagens"]) for c in llm.chamadas if "Monte a camada" in str(c["mensagens"])]
    assert any("RIOPREV (vinculado à Secretaria de Fazenda - SEFAZ)" in p for p in pesquisas)
    # a camada do Estado é pesquisada uma vez só (2 grupos) e entra no dossiê dos dois órgãos
    assert sum('camada\\n"Estado"' in p for p in pesquisas) == 2 and len(pesquisas) == 2 + 2 * 3
    dossie = json.loads((pasta / "dossie.json").read_text(encoding="utf-8"))
    assert [i["id"] for i in dossie["itens"]][:3] == ["E1", "E2", "E3"]
    assert (tmp_path / "dossie_estado.json").exists()
    # padrão do lote: Sonnet no debate
    assert registro["modelo_debate"].endswith("sonnet-5-5")
    with open(tmp_path / "resumo.csv", encoding="utf-8-sig") as f:
        resumo = list(csv.DictReader(f, delimiter=";"))
    assert [r["sigla"] for r in resumo] == ["SEFAZ", "RIOPREV"] and all(float(r["custo_usd"]) > 0 for r in resumo)
    resumo_md = (tmp_path / "resumo.md").read_text(encoding="utf-8")
    assert "2 de 2 órgãos concluídos" in resumo_md and "da pesquisa do Estado, feita uma vez" in resumo_md
    assert "usada em todos os órgãos." in resumo_md


def test_falha_num_orgao_nao_para_o_lote(tmp_path, llm):
    from conftest import GRUPOS
    drive = DriveFalso()
    app = lote.carregar_app()
    llm.grupos_sem_json = {g[0] for g in GRUPOS}
    llm.continuacao_sem_json = True                    # o dossiê da SEFAZ sai vazio...
    original = app["montar_dossie"]

    def montar_dossie(modelo, nome, *a, **k):          # ...e a pesquisa da SETUR quebra no meio do caminho
        if "Turismo" in nome:
            raise RuntimeError("403 sem acesso")
        return original(modelo, nome, *a, **k)
    app["montar_dossie"] = montar_dossie
    linhas = lote.principal(["--pasta", "raiz", "--orgaos", "SEFAZ,SETUR", "--rodadas", "1", "--saida", str(tmp_path)],
                            drive=drive, app=app)
    assert [x["situacao"] for x in linhas] == ["dossiê insuficiente", "erro"]
    assert "403 sem acesso" in linhas[1]["observacao"] and (tmp_path / "setur" / "erro.txt").exists()
    assert (tmp_path / "sefaz" / "dossie.json").exists()                     # o diagnóstico da pesquisa fica salvo


def test_sem_credenciais_explica_o_que_falta(monkeypatch):
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_JSON", raising=False)
    with pytest.raises(SystemExit, match="GOOGLE_SERVICE_ACCOUNT_JSON"):
        lote.principal(["--pasta", "raiz"])


def test_subpasta_generica_nao_vira_orgao():
    assert lote.parece_orgao("Junta Comercial do Estado do Rio de Janeiro - JUCERJA")
    assert lote.parece_orgao("FUNDAÇÃO SAÚDE ") and lote.parece_orgao("DETRAN")
    for nome in ("Anexos", "ANEXOS", "Resposta Ofício 7", "Planilhas", "2026"):
        assert not lote.parece_orgao(nome)
    drive = DriveFalso()
    drive.arvore["setur"].append({"id": "anexos_setur", "name": "Anexos", "mimeType": PASTA})
    drive.arvore["anexos_setur"] = [{"id": "f11", "name": "anexo_setur.pdf", "mimeType": "application/pdf"}]
    setur = next(o for o in lote.planejar_orgaos(drive, "raiz") if o["sigla"] == "SETUR")
    assert "Anexos" in [p["name"] for p in setur["pastas"]]


def test_pastas_reais_do_drive():
    """Subpastas reais da pasta DOCUMENTOS RECEBIDOS (nov/2026)."""
    junta = lambda sub, mae: lote.e_copia_da_pasta(sub, mae) or not lote.parece_orgao(sub)
    sedec = "Secretaria de Estado de Defesa Civil - SEDEC"
    assert junta("SETD", "Secretaria de Estado de Transformação Digital - SEDT")          # sigla com letras trocadas
    assert junta("OFÍCIO PADRÃO 03", sedec) and junta("OFÍCIO 9 - EL NIÑO", sedec)
    assert junta("SEDEC - OFÍCIOS 02/06/07/08/09", sedec)
    assert not junta("TURISRIO", "Secretaria de Turismo - SETUR")
    assert not junta("DETRAN", "Secretaria da Casa Civil - SECC")
    assert not junta("Instituto Vital Brasil - IVB", "Secretaria de Estado de Saúde - SES")


def test_planilha_compactada_sem_perder_valores():
    md = ("## Obras\n| OBRA | Unnamed: 1 | VALOR | STATUS |\n|---|---|---|---|\n"
          "| Ponte do Rio   | nan | 1.000,00 | Paralisada |\n| nan | nan | nan | nan |\n| Escola | NaN | 2.500,00 | NaN |\n\nTexto  com   espaços")
    c = lote.compactar_tabelas(md)
    assert c == ("## Obras\n|OBRA|VALOR|STATUS|\n|-|-|-|\n|Ponte do Rio|1.000,00|Paralisada|\n|Escola|2.500,00||\n\n"
                 "Texto com espaços")


def test_trecho_repetido_entre_arquivos_entra_uma_vez():
    comum = "Este parágrafo longo aparece no relatório e também no anexo, palavra por palavra, sem nenhuma mudança."
    manifesto = {}
    saida = lote.remover_repetidos([("relatorio.docx", f"Início.\n\n{comum}"), ("anexo.docx", f"{comum}\n\nSó do anexo.")],
                                   manifesto)
    assert saida[1] == ("anexo.docx", "Só do anexo.") and comum in saida[0][1]
    assert manifesto["repetidos"] == [{"arquivo": "anexo.docx", "caracteres": len(comum)}]


def test_limite_dividido_sem_desperdicio():
    assert lote.dividir_limite([5000, 3000], 150000) == [5000, 3000]                 # tudo cabe
    assert lote.dividir_limite([20000, 129330, 341439], 150000) == [20000, 65000, 65000]   # a sobra vai aos maiores
    assert lote.dividir_limite([111361, 129330, 341439], 150000) == [75000, 37500, 37500]  # relatório com peso 2
    assert sum(lote.dividir_limite([90000, 90000, 90000], 150000)) <= 150000


def test_secao_9_nao_apaga_os_arquivos_seguintes(funcoes):
    texto = ("# ARQUIVO: relatorio.docx\n\n## 8. RISCOS\nRisco A\n\n## 9. PONTOS FOCAIS\nFulano, fulano@rj.gov.br\n\n"
             "# ARQUIVO: base.xlsx\n\n|OBRA|\n|-|\n|Ponte|")
    limpo, avisos = funcoes.limpar_relatorio(texto)
    assert "Risco A" in limpo and "Fulano" not in limpo and "|Ponte|" in limpo and "# ARQUIVO: base.xlsx" in limpo

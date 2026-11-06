"""A tela, rodando no AppTest do Streamlit com o modelo falso: subir, escolher, analisar e baixar."""
import io
import time
import zipfile

import pytest

from conftest import RAIZ, RELATORIO


@pytest.fixture(autouse=True)
def pasta_de_registros(tmp_path, monkeypatch):
    """Cada teste grava as análises numa pasta temporária, não em registros/ do repositório."""
    monkeypatch.setenv("PASTA_REGISTROS", str(tmp_path / "registros"))
    return tmp_path / "registros"


class Envio:
    def __init__(self, nome, dados):
        self.name, self.dados = nome, dados

    def getvalue(self):
        return self.dados


def _zip(arquivos):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for nome, dados in arquivos.items():
            z.writestr(nome, dados)
    return buffer.getvalue()


def test_fluxo_unico_da_tela(llm, monkeypatch, pasta_de_registros):
    import streamlit
    from streamlit.testing.v1 import AppTest
    llm.texto_relatorio = RELATORIO
    envio = [Envio("resumos.zip", _zip({"SETUR - Turismo.docx": b"a", "SEFAZ - Fazenda.pdf": b"b"}))]
    dossies = [Envio("Dossiê SETUR.md", b"### Fato\n- Afirmacao: x\n"),
               Envio("Dossiê SECID.md", b"# SECID")]                 # sem documento enviado: entra desmarcada
    monkeypatch.setattr(streamlit, "file_uploader", lambda rotulo, *a, **k: dossies if "Dossiê" in rotulo else envio)
    at = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=60)
    at.run()
    assert not at.exception
    economico = next(c for c in at.checkbox if "econômico" in c.label)
    economico.uncheck().run()                       # sem a Batch API, o teste usa o modelo falso direto
    botao = next(b for b in at.button if b.label.startswith("▶️ Analisar 2"))
    botao.click().run()
    for _ in range(120):
        at.run()
        if any(getattr(d, "label", "").startswith("⬇️") for d in at.get("download_button")):
            break
        time.sleep(0.5)
    assert any("Pronto" in s.value for s in at.success), [e.value for e in at.error]
    assert any(getattr(d, "label", "").startswith("⬇️") for d in at.get("download_button"))
    pastas = list(pasta_de_registros.glob("analise_*"))
    assert len(pastas) == 1 and (pastas[0] / "resultados.zip").exists() and (pastas[0] / "entrada.json").exists()
    import json
    escolhas = json.loads((pastas[0] / "entrada.json").read_text(encoding="utf-8"))["escolhas"]
    assert sorted(e["nome"] for e in escolhas) == ["SEFAZ - Fazenda", "SETUR - Turismo"]
    with zipfile.ZipFile(io.BytesIO((pastas[0] / "resultados.zip").read_bytes())) as z:
        assert not any(n.startswith("entrada") for n in z.namelist()) and "resumo.csv" in z.namelist()


def test_so_com_dossies_a_tabela_ja_vem_marcada(llm, monkeypatch):
    import streamlit
    from streamlit.testing.v1 import AppTest
    streamlit.cache_resource.clear()                  # sem a análise do teste anterior na memória do app
    dossies = [Envio("Dossiê SECID.md", b"# SECID"), Envio("Dossiê SES.md", b"# SES")]
    monkeypatch.setattr(streamlit, "file_uploader", lambda rotulo, *a, **k: dossies if "Dossiê" in rotulo else [])
    at = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=60)
    at.run()
    assert not at.exception
    assert any(b.label.startswith("▶️ Analisar 2") for b in at.button)


def test_com_senha_a_tela_pede_a_senha_antes(llm, monkeypatch):
    import streamlit
    from streamlit.testing.v1 import AppTest
    streamlit.cache_resource.clear()
    monkeypatch.setenv("APP_SENHA", "segredo")
    monkeypatch.setattr(streamlit, "file_uploader", lambda *a, **k: [])
    at = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=60)
    at.run()
    assert not at.exception and not at.selectbox            # nada da tela antes da senha
    at.text_input[0].input("errada")
    at.button[0].click().run()
    assert any("incorreta" in e.value for e in at.error) and not at.selectbox
    at.text_input[0].input("segredo")
    at.button[0].click().run()
    assert not at.exception and at.selectbox


def test_depois_de_um_reinicio_a_tela_oferece_retomar(llm, monkeypatch, pasta_de_registros):
    import streamlit
    from streamlit.testing.v1 import AppTest
    streamlit.cache_resource.clear()
    llm.texto_relatorio = RELATORIO
    envio = [Envio("resumos.zip", _zip({"SETUR - Turismo.docx": b"a", "SEFAZ - Fazenda.pdf": b"b"}))]
    monkeypatch.setattr(streamlit, "file_uploader", lambda rotulo, *a, **k: [] if "Dossiê" in rotulo else envio)
    at = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=60)
    at.run()
    next(c for c in at.checkbox if "econômico" in c.label).uncheck().run()
    next(b for b in at.button if b.label.startswith("▶️ Analisar 2")).click().run()
    for _ in range(120):
        at.run()
        if any(getattr(d, "label", "").startswith("⬇️") for d in at.get("download_button")):
            break
        time.sleep(0.5)
    pasta = next(pasta_de_registros.glob("analise_*"))
    # simula a queda no meio: o app reinicia (memória zerada), o .zip final não existe e a SEFAZ não terminou
    streamlit.cache_resource.clear()
    (pasta / "resultados.zip").unlink()
    (pasta / "auditoria" / "sefaz_fazenda_resultado.json").unlink()
    chamadas_antes = len(llm.chamadas)
    at = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=60)
    at.run()
    assert not at.exception
    assert any("interrompida" in w.value and "1 de 2" in w.value for w in at.warning)
    next(b for b in at.button if b.label.startswith("▶️ Retomar")).click().run()
    for _ in range(120):
        at.run()
        if any(getattr(d, "label", "").startswith("⬇️") for d in at.get("download_button")):
            break
        time.sleep(0.5)
    assert any("Pronto" in s.value and "2 de 2" in s.value for s in at.success), [e.value for e in at.error]
    assert any("retomada: 1 já estavam prontas" in i.value for i in at.info) or True
    assert (pasta / "resultados.zip").exists()
    # só a SEFAZ foi analisada de novo
    novas = [c for c in llm.chamadas[chamadas_antes:] if "Você é analista de riscos" in str(c["mensagens"][0]["content"])]
    assert len(novas) == 1 and "SEFAZ" in str(novas[0]["mensagens"][1]["content"])

"""A tela, rodando no AppTest do Streamlit com o modelo falso: subir, escolher, analisar e baixar."""
import io
import time
import zipfile

from conftest import RAIZ, RELATORIO


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


def test_fluxo_unico_da_tela(llm, monkeypatch):
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

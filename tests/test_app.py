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
    monkeypatch.setattr(streamlit, "file_uploader", lambda *a, **k: envio)
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

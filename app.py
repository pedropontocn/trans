"""Análise da Transição: uma tela só. Sobe o .zip, escolhe os órgãos, processa e baixa os resultados.

Execução local:
    pip install -r requirements.txt
    streamlit run app.py
A chave da API fica no arquivo .env (ANTHROPIC_API_KEY=...) ou nos Secrets do Streamlit.
"""
import csv
import hashlib
import tempfile
import threading
import zipfile
from datetime import date, datetime
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from transicao import VERSAO, analise, entrada
from transicao.config import MODELOS

load_dotenv()

# custo por órgão, em US$, com Haiku na pesquisa, Sonnet no auxiliar e Opus no debate (medido em testes reais)
CUSTO_POR_ORGAO = {True: (1.0, 1.6), False: (2.0, 3.2)}


@st.cache_resource(show_spinner=False)
def _trabalhos():
    """A análise roda num fio à parte e fica na memória do app (todas as abas veem) até ele reiniciar."""
    return {}


def trabalho_atual():
    t = _trabalhos()
    return t[max(t)] if t else None


def iniciar(orgaos, cfg, economico):
    atual = trabalho_atual()
    if atual and atual["situacao"] == "rodando":
        raise RuntimeError("já há uma análise em andamento")
    trabalho = {"id": datetime.now().strftime("%Y%m%d%H%M%S%f"), "situacao": "rodando", "inicio": datetime.now(),
                "fim": None, "log": [], "total": len(orgaos), "economico": economico, "zip": None, "erro": None,
                "saida": Path(tempfile.mkdtemp(prefix="analise_"))}
    _trabalhos()[trabalho["id"]] = trabalho
    threading.Thread(target=_executar, args=(trabalho, orgaos, dict(cfg), economico), daemon=True).start()


def _executar(trabalho, orgaos, cfg, economico):
    log = lambda linha: trabalho["log"].append(f"{datetime.now():%H:%M:%S} {linha}") if len(trabalho["log"]) < 5000 else None
    try:
        analise.rodar_orgaos(orgaos, cfg, trabalho["saida"], economico=economico, log=log)
        trabalho["zip"] = analise.zipar(trabalho["saida"])
        trabalho["situacao"] = "concluído"
    except Exception as e:
        trabalho["erro"] = f"{type(e).__name__}: {e}"[:500]
        trabalho["situacao"] = "erro"
    finally:
        trabalho["fim"] = datetime.now()


def linhas(trabalho):
    caminho = Path(trabalho["saida"]) / "resumo.csv"
    try:
        with open(caminho, encoding="utf-8-sig") as f:
            return list(csv.DictReader(f, delimiter=";"))
    except (OSError, csv.Error):
        return []


# --- TELA ------------------------------------------------------------------------------------

st.set_page_config(page_title="Análise da Transição", page_icon="🏛️", layout="wide")
st.title("🏛️ Análise da Transição")
st.caption("Para cada órgão, um documento Word com as decisões a tomar, o diagnóstico, os próximos vencimentos e, "
           "nos anexos, as fontes, o debate e a verificação; e um calendário consolidado em Excel. "
           "Expõe escolhas para quem decide: não recomenda.")

with st.sidebar:
    st.header("Modelos")
    modelo_pesquisa = st.selectbox("Pesquisa em fontes públicas", MODELOS, index=MODELOS.index("anthropic/claude-haiku-5-5"),
                                   help="Busca na web e monta o dossiê. A Anthropic cobra US$ 10 por mil buscas, além dos tokens.")
    modelo_auxiliar = st.selectbox("Auxiliar", MODELOS, index=MODELOS.index("anthropic/claude-sonnet-5-5"),
                                   help="Insumos, confronto com o relatório, calendário, diagnóstico, consolidação e revisão "
                                        "de neutralidade.")
    modelo_debate = st.selectbox("Debate e memorando", MODELOS, index=MODELOS.index("anthropic/claude-opus-5-5"))
    n_rodadas = st.slider("Rodadas do debate", 1, 5, 3,
                          help="Cada rodada refaz o debate do zero; só ganham destaque os dilemas que se repetem.")
    parar_cedo = n_rodadas >= 3 and st.checkbox("Parar na 2ª rodada se as duas concordarem", value=True)
    economico = st.checkbox("Modo econômico (Batch API)", value=True,
                            help="Metade do preço dos tokens. Cada etapa espera a fila da Anthropic: o total leva de "
                                 "uma a algumas horas, com todos os órgãos em paralelo.")
    st.header("Análise")
    data_corte = st.date_input("Data de corte", value=date.today(), format="DD/MM/YYYY")
    foco = st.text_input("Foco (opcional)", placeholder="ex.: contratos que vencem até março")
    with st.expander("Cabeçalho do documento"):
        orgao_emissor = st.text_input("Órgão", value="Equipe de Transição")
        unidade = st.text_input("De (unidade)", value="")
        para = st.text_input("Para", value="")
    st.caption(f"Versão {VERSAO}")

trabalho = trabalho_atual()


@st.fragment(run_every=15)
def andamento():
    t = trabalho_atual()
    if not t:
        return
    feitas = linhas(t)
    minutos = ((t["fim"] or datetime.now()) - t["inicio"]).total_seconds() / 60
    if t["situacao"] == "rodando":
        st.info(f"⏳ Analisando {t['total']} órgão(s)" + (" no modo econômico" if t["economico"] else "")
                + f": {len(feitas)} pronto(s), {minutos:.0f} min até agora. Pode fechar a página: a análise continua. "
                  "Não reinicie o app nem faça merge no GitHub até terminar.")
        st.progress(len(feitas) / max(t["total"], 1))
    elif t["situacao"] == "concluído":
        ok = sum(l.get("situacao") == "concluído" for l in feitas)
        custo = sum(float(l.get("custo_usd") or 0) for l in feitas)
        st.success(f"✅ Pronto em {minutos:.0f} min: {ok} de {t['total']} órgão(s). "
                   f"Custo estimado: US$ {custo:.2f}".replace(".", ",") + " (mais a pesquisa do Estado; ver LEIA-ME).")
    else:
        st.error(f"A análise parou: {t['erro']}")
    if feitas:
        st.dataframe([{"Órgão": l["orgao"], "Situação": l["situacao"], "Itens do dossiê": l["itens_dossie"],
                       "Dilemas": l["trade_offs"], "Datas": l["datas_calendario"], "Confiança": l["confianca"],
                       "US$": l["custo_usd"], "Observação": l["observacao"]} for l in feitas],
                     hide_index=True, width="stretch")
    with st.expander("Registro do andamento"):
        st.code("\n".join(t["log"][-200:]) or "(começando)", language=None)
    if t["situacao"] != "rodando" and st.session_state.get("visto") != t["id"]:
        st.session_state["visto"] = t["id"]
        st.rerun(scope="app")                     # mostra o botão de download, que fica fora deste trecho


if trabalho:
    andamento()
    if trabalho["situacao"] != "rodando":
        if trabalho.get("zip"):
            st.download_button("⬇️ Baixar os resultados (.zip)", trabalho["zip"], type="primary", width="stretch",
                               file_name=f"transicao_{trabalho['inicio']:%Y-%m-%d_%H%M}.zip", mime="application/zip")
        st.button("Começar outra análise", on_click=lambda: _trabalhos().pop(trabalho["id"], None))

if not trabalho or trabalho["situacao"] != "rodando":
    if not trabalho:
        enviados = st.file_uploader("Arquivos dos órgãos (.zip, Word ou PDF)", type=["zip", "docx", "pdf"],
                                    accept_multiple_files=True)
        modo = st.radio("Como os arquivos estão organizados?",
                        ["Cada arquivo é o resumo de um órgão", "Cada pasta é um órgão (documentos brutos)"],
                        horizontal=True,
                        help="Resumos: o nome do órgão vem do nome do arquivo. Documentos brutos: suba o .zip da pasta "
                             "que tem uma subpasta por órgão; o app lê os Word, PDF e planilhas de cada uma.")
        if enviados:
            cada_pasta = modo.startswith("Cada pasta")
            assinatura = hashlib.md5(b"".join(a.name.encode() + a.getvalue() for a in enviados)
                                     + str(cada_pasta).encode()).hexdigest()
            if st.session_state.get("lidos") != assinatura:
                try:
                    st.session_state["orgaos"] = entrada.orgaos_do_envio([(a.name, a.getvalue()) for a in enviados],
                                                                         cada_pasta)
                except zipfile.BadZipFile as e:
                    st.session_state["orgaos"] = []
                    st.error(f"Não foi possível abrir o .zip: {e}")
                st.session_state["lidos"] = assinatura
                st.session_state.pop("tabela", None)
            orgaos = st.session_state.get("orgaos") or []
            if not orgaos:
                st.warning("Não achei nenhum órgão no envio. Confira se escolheu a organização certa acima.")
            else:
                tabela = st.data_editor(
                    [{"analisar": True, "orgao": o["nome"], "arquivos": ", ".join(o["arquivos"])[:200]} for o in orgaos],
                    key="tabela", hide_index=True, width="stretch", disabled=["arquivos"],
                    column_config={"analisar": st.column_config.CheckboxColumn("Analisar"),
                                   "orgao": st.column_config.TextColumn("Órgão (corrija se precisar)"),
                                   "arquivos": st.column_config.TextColumn("Arquivos ou pastas")})
                registros = tabela.to_dict("records") if hasattr(tabela, "to_dict") else list(tabela)
                escolhidos = [dict(o, nome=str(r["orgao"]).strip() or o["nome"])
                              for o, r in zip(orgaos, registros) if r.get("analisar")]
                faixa = CUSTO_POR_ORGAO[economico]
                st.caption(f"Estimativa: US$ {faixa[0] * len(escolhidos):.0f} a {faixa[1] * len(escolhidos):.0f} para "
                           f"{len(escolhidos)} órgão(s). O valor real sai no resumo. Não envie documentos sigilosos.")
                if st.button(f"▶️ Analisar {len(escolhidos)} órgão(s)", type="primary", width="stretch",
                             disabled=not escolhidos):
                    cfg = {"modelo_pesquisa": modelo_pesquisa, "modelo_auxiliar": modelo_auxiliar, "modelo": modelo_debate,
                           "n_rodadas": n_rodadas, "parar_cedo": parar_cedo, "data_corte": data_corte.strftime("%d/%m/%Y"),
                           "foco": foco.strip(), "orgao_emissor": orgao_emissor, "unidade": unidade, "para": para}
                    try:
                        iniciar(escolhidos, cfg, economico)
                        st.rerun()
                    except RuntimeError as e:
                        st.error(str(e))

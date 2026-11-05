"""Processamento em lote: lê no Google Drive a pasta de cada secretaria (e de cada órgão vinculado), baixa os
documentos, monta o dossiê de fontes independentes e gera o mapa de tensões e o memorando de cada órgão, sem parar.

Uso:
    python lote.py --pasta ID_DA_PASTA_DOCUMENTOS_RECEBIDOS [--orgaos "SES,SEFAZ"] [--saida resultados]
    python lote.py --pasta ID --apenas-listar          # mostra o que seria processado, sem chamar nenhum modelo

Variáveis de ambiente:
    GOOGLE_SERVICE_ACCOUNT_JSON   conteúdo do arquivo JSON da conta de serviço com acesso de leitura à pasta
    ANTHROPIC_API_KEY             chave da Anthropic
    GEMINI_API_KEY                chave do Gemini (se algum modelo escolhido for Gemini)

Reaproveita as funções do app.py: a pesquisa, a conferência de links, a deliberação e a verificação são as mesmas
do painel. A diferença é que aqui ninguém revisa o dossiê e os insumos antes do debate, e o memorando diz isso.
Os logs não mostram o conteúdo dos documentos: só nomes de pastas, contagens e erros.
"""
import argparse
import csv
import io
import json
import os
import re
import sys
import threading
import time
import unicodedata
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
PASTA_MIME = "application/vnd.google-apps.folder"
EXPORTAR = {  # arquivos nativos do Google são exportados para um formato que o MarkItDown lê
    "application/vnd.google-apps.document": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
    "application/vnd.google-apps.spreadsheet": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
    "application/vnd.google-apps.presentation": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx"),
}
EXTENSOES = {".pdf", ".docx", ".xlsx", ".xls", ".pptx", ".csv", ".txt", ".md", ".html", ".htm"}
LIMITE_ARQUIVO = 30_000_000
# Arquivos que costumam ter só dados pessoais (contatos, telefones, CPF): não vão para a API do modelo.
RE_ARQUIVO_PESSOAL = re.compile(r"telefone|contato|ponto[s]?[ _-]*foca|cpf|dados[ _-]*pessoais|curr[ií]culo|agenda[ _-]*de[ _-]*contatos", re.I)
RE_CPF = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")
# Telefone só com DDD entre parênteses, celular de 5+4 dígitos ou precedido de "tel", "fone", "celular":
# assim "PPA 2024-2027" e valores numéricos não são apagados.
RE_TELEFONE = re.compile(r"\(\d{2}\)\s?9?\d{4}[\s.-]?\d{4}(?!\d)|(?<!\d)9\d{4}-\d{4}(?!\d)"
                         r"|(?i:\b(?:tel(?:efone)?|fone|cel(?:ular)?|whats(?:app)?)\.?:?\s*)(?:\d{2}\s?)?9?\d{4}[\s.-]?\d{4}(?!\d)")
PRIORIDADE_NOME = re.compile(r"relat|transi|resumo|situa|diagn", re.I)


def _norm(s):
    return unicodedata.normalize("NFD", str(s or "")).encode("ascii", "ignore").decode().lower().strip()


OUVINTES_LOG = []          # funções que também recebem cada linha do log (o app mostra o andamento na tela)


def log(msg):
    linha = f"[{datetime.now():%H:%M:%S}] {msg}"
    print(linha, flush=True)
    for ouvinte in list(OUVINTES_LOG):
        try:
            ouvinte(linha)
        except Exception:
            pass


# --- APP ---------------------------------------------------------------------------

def carregar_app():
    """As funções do app.py, sem a interface (tudo antes de '# --- ESTADO INICIAL'), como nos testes."""
    caminho = RAIZ / "app.py"
    codigo = caminho.read_text(encoding="utf-8").split("# --- ESTADO INICIAL")[0]
    ns = {"__file__": str(caminho), "__name__": "app_lote"}
    exec(compile(codigo, str(caminho), "exec"), ns)
    return ns


# --- DRIVE -------------------------------------------------------------------------

class Drive:
    """Acesso de leitura ao Google Drive com uma conta de serviço."""

    def __init__(self, credenciais_json):
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        info = json.loads(credenciais_json)
        cred = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/drive.readonly"])
        self.servico = build("drive", "v3", credentials=cred, cache_discovery=False)
        self.email = info.get("client_email", "")

    def listar(self, pasta_id):
        itens, token = [], None
        while True:
            resp = self.servico.files().list(
                q=f"'{pasta_id}' in parents and trashed = false", pageSize=200, pageToken=token,
                fields="nextPageToken, files(id, name, mimeType, size)",
                supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
            itens += resp.get("files", [])
            token = resp.get("nextPageToken")
            if not token:
                return itens

    def nome(self, pasta_id):
        return self.servico.files().get(fileId=pasta_id, fields="name", supportsAllDrives=True).execute()["name"]

    def baixar(self, arquivo):
        from googleapiclient.http import MediaIoBaseDownload
        if arquivo["mimeType"] in EXPORTAR:
            pedido = self.servico.files().export_media(fileId=arquivo["id"], mimeType=EXPORTAR[arquivo["mimeType"]][0])
        else:
            pedido = self.servico.files().get_media(fileId=arquivo["id"], supportsAllDrives=True)
        buffer = io.BytesIO()
        baixador = MediaIoBaseDownload(buffer, pedido)
        feito = False
        while not feito:
            _, feito = baixador.next_chunk()
        return buffer.getvalue()


# --- QUAIS ÓRGÃOS PROCESSAR ------------------------------------------------------------

def sigla(nome):
    m = re.search(r"[-–]\s*([A-Z][A-Z0-9]{1,14})\s*$", nome.strip())
    if m:
        return m.group(1)
    m = re.search(r"\b([A-Z][A-Z0-9]{2,14})\b\s*$", nome.strip())
    return m.group(1) if m else ""


def e_copia_da_pasta(sub, mae):
    """Subpasta que repete a pasta-mãe ("SEFAZ" dentro de "Secretaria de Fazenda - SEFAZ") não é órgão vinculado."""
    s_mae, n_sub, n_mae = sigla(mae), _norm(sub), _norm(mae)
    if s_mae and re.search(r"\b" + re.escape(s_mae.lower()) + r"\b", n_sub):
        return True
    # sigla digitada com letras trocadas ("SETD" dentro de "... - SEDT")
    if s_mae and len(n_sub) == len(s_mae) and sorted(n_sub) == sorted(s_mae.lower()):
        return True
    base_mae = _norm(re.sub(r"\s*[-–]\s*[A-Z0-9]+\s*$", "", mae))
    return bool(n_sub) and (n_sub in n_mae or base_mae in n_sub)


RE_ENTIDADE = re.compile(r"^(funda[cç][aã]o|instituto|companhia|cia\.?|departamento|junta|fundo|empresa|ag[eê]ncia|"
                         r"autarquia|centro|superintend[eê]ncia|loteria|imprensa|universidade|fundacao|rio\s?prev|"
                         r"secretaria|comiss[aã]o|conselho|procuradoria|defensoria|detran|ceperj|cedae|emop)", re.I)
RE_PASTA_GENERICA = re.compile(r"anexo|resposta|of[ií]cio|documento|relat[oó]rio|planilha|arquivo|processo|\bsei\b|"
                               r"outros|diversos|complement|pasta|dados|c[oó]pia|vers[aã]o|enviado|recebido", re.I)


def parece_orgao(nome):
    """Subpasta que tem cara de órgão (nome de entidade ou sigla). "Anexos" ou "Resposta ao Ofício 5" não têm:
    são juntadas à pasta-mãe, em vez de virar um órgão vinculado."""
    nome = nome.strip()
    if RE_ENTIDADE.search(nome):
        return True
    if RE_PASTA_GENERICA.search(nome):
        return False
    return bool(sigla(nome))


def planejar_orgaos(drive, pasta_raiz):
    """Cada pasta da raiz é uma secretaria. Dentro dela, subpastas que repetem o nome são juntadas à secretaria;
    as demais são órgãos vinculados, com análise própria. Devolve a lista de órgãos com as pastas de cada um."""
    orgaos = []

    def juntar(pasta, nome_dono, pastas, vinculadas, profundidade=0):
        for item in drive.listar(pasta["id"]):
            if item["mimeType"] != PASTA_MIME:
                continue
            if profundidade < 4 and (e_copia_da_pasta(item["name"], nome_dono) or not parece_orgao(item["name"])):
                pastas.append(item)
                juntar(item, nome_dono, pastas, vinculadas, profundidade + 1)
            else:
                vinculadas.append(item)

    for secretaria in sorted((i for i in drive.listar(pasta_raiz) if i["mimeType"] == PASTA_MIME), key=lambda i: i["name"]):
        pastas, vinculadas = [secretaria], []
        juntar(secretaria, secretaria["name"], pastas, vinculadas)
        orgaos.append({"nome": secretaria["name"].strip(), "sigla": sigla(secretaria["name"]), "vinculada_a": "",
                       "pastas": pastas})
        for v in sorted(vinculadas, key=lambda i: i["name"]):
            pastas_v, sub_v = [v], []
            juntar(v, v["name"], pastas_v, sub_v)
            pastas_v += sub_v            # dentro de um vinculado, tudo é do vinculado
            orgaos.append({"nome": v["name"].strip(), "sigla": sigla(v["name"]), "vinculada_a": secretaria["name"].strip(),
                           "pastas": pastas_v})
    return orgaos


def filtrar_orgaos(orgaos, filtro):
    if not filtro:
        return orgaos
    termos = [_norm(t) for t in filtro.split(",") if t.strip()]
    return [o for o in orgaos if any(t == _norm(o["sigla"]) or t in _norm(o["nome"]) for t in termos)]


def fatia(orgaos, parte, total):
    """Divide os órgãos entre execuções paralelas (parte de 1 a total)."""
    return [o for k, o in enumerate(orgaos) if k % total == parte - 1]


# --- DOCUMENTOS ----------------------------------------------------------------------

def _extensao(nome, mime):
    if mime in EXPORTAR:
        return EXPORTAR[mime][1]
    return Path(nome).suffix.lower()


def limpar_dados_pessoais(texto):
    texto = RE_CPF.sub("[CPF omitido]", texto)
    return RE_TELEFONE.sub("[telefone omitido]", texto)


def ler_documentos(drive, orgao, converter, limite_total):
    """Baixa e converte os arquivos das pastas do órgão. Devolve (texto, manifesto). O manifesto diz o que foi lido,
    pulado (formato, tamanho ou dados pessoais), cortado para caber no limite e o que deu erro."""
    manifesto = {"lidos": [], "pulados": [], "erros": [], "cortados": []}
    textos = []

    def converter_bytes(nome, dados, origem):
        try:
            texto = converter(nome, dados) or ""
        except Exception as e:
            manifesto["erros"].append({"arquivo": origem, "erro": f"{type(e).__name__}: {e}"[:300]})
            return
        if texto.strip():
            textos.append((origem, limpar_dados_pessoais(texto)))
        else:
            manifesto["pulados"].append({"arquivo": origem, "motivo": "sem texto (PDF digitalizado?)"})

    for pasta in orgao["pastas"]:
        for arq in drive.listar(pasta["id"]):
            if arq["mimeType"] == PASTA_MIME:
                continue
            nome, ext = arq["name"], _extensao(arq["name"], arq["mimeType"])
            origem = nome if pasta is orgao["pastas"][0] else f"{pasta['name']}/{nome}"
            if RE_ARQUIVO_PESSOAL.search(nome):
                manifesto["pulados"].append({"arquivo": origem, "motivo": "nome indica dados pessoais"})
                continue
            if ext not in EXTENSOES and ext != ".zip":
                manifesto["pulados"].append({"arquivo": origem, "motivo": f"formato não lido ({ext or arq['mimeType']})"})
                continue
            if int(arq.get("size") or 0) > LIMITE_ARQUIVO:
                manifesto["pulados"].append({"arquivo": origem, "motivo": "maior que 30 MB"})
                continue
            try:
                dados = drive.baixar(arq)
            except Exception as e:
                manifesto["erros"].append({"arquivo": origem, "erro": f"download: {type(e).__name__}: {e}"[:300]})
                continue
            if ext != ".zip":
                converter_bytes(nome if Path(nome).suffix else nome + ext, dados, origem)
                continue
            try:
                with zipfile.ZipFile(io.BytesIO(dados)) as z:
                    for info in z.infolist():
                        interno = f"{origem}/{info.filename}"
                        ext_i = Path(info.filename).suffix.lower()
                        if info.is_dir():
                            continue
                        if RE_ARQUIVO_PESSOAL.search(info.filename):
                            manifesto["pulados"].append({"arquivo": interno, "motivo": "nome indica dados pessoais"})
                        elif ext_i not in EXTENSOES or info.file_size > LIMITE_ARQUIVO:
                            manifesto["pulados"].append({"arquivo": interno, "motivo": "formato ou tamanho não lido"})
                        else:
                            converter_bytes(Path(info.filename).name, z.read(info), interno)
            except zipfile.BadZipFile:
                manifesto["erros"].append({"arquivo": origem, "erro": "zip corrompido"})

    # Antes de cortar, tira o que ocupa espaço sem trazer informação: células vazias de planilha e trechos repetidos
    # entre arquivos. Depois divide o limite: relatórios e resumos primeiro, e quem precisa de menos que a sua parte
    # deixa a sobra para os outros.
    textos.sort(key=lambda t: (not PRIORIDADE_NOME.search(t[0]), t[0]))
    textos = [(origem, compactar_tabelas(texto)) for origem, texto in textos]
    textos = remover_repetidos(textos, manifesto)
    cotas = dividir_limite([len(t) for _, t in textos], limite_total)
    partes = []
    for (origem, texto), cota in zip(textos, cotas):
        if len(texto) > cota:
            manifesto["cortados"].append({"arquivo": origem, "caracteres": len(texto), "usados": cota})
            texto = texto[:cota] + "\n\n[… cortado para caber no limite]"
        manifesto["lidos"].append({"arquivo": origem, "caracteres": len(texto)})
        partes.append(f"# ARQUIVO: {origem}\n\n{texto}")
    return "\n\n".join(partes), manifesto


RE_CELULA_VAZIA = re.compile(r"^(nan|none|null|nat|unnamed: ?\d+|-+|:?-+:?)$", re.I)


def compactar_tabelas(texto):
    """Tabelas em Markdown (planilhas e tabelas de Word convertidas) sem o que não é informação: células vazias,
    "NaN", cabeçalhos "Unnamed: 3", colunas e linhas inteiramente vazias e espaços de alinhamento.
    Nenhum valor é perdido."""
    linhas, saida, bloco = texto.split("\n"), [], []

    def fechar():
        if not bloco:
            return
        celulas = [[c.strip() for c in l.strip().strip("|").split("|")] for l in bloco]
        separador = [all(re.fullmatch(r":?-+:?", c) for c in linha if c) and any(linha) for linha in celulas]
        dados = [linha for linha, sep in zip(celulas, separador) if not sep]
        largura = max((len(l) for l in dados), default=0)
        dados = [l + [""] * (largura - len(l)) for l in dados]
        vazio = lambda c: not c or bool(RE_CELULA_VAZIA.match(c))
        manter = [j for j in range(largura) if any(not vazio(l[j]) for l in dados)]
        limpas = []
        for l in dados:
            valores = ["" if vazio(l[j]) else l[j] for j in manter]
            if any(valores):
                limpas.append("|" + "|".join(valores) + "|")
        if len(limpas) > 1:
            limpas.insert(1, "|" + "|".join("-" for _ in manter) + "|")
        saida.extend(limpas)
        bloco.clear()

    for linha in linhas:
        if linha.lstrip().startswith("|"):
            bloco.append(linha)
        else:
            fechar()
            saida.append(re.sub(r"[ \t]{2,}", " ", linha))
    fechar()
    return re.sub(r"\n{3,}", "\n\n", "\n".join(saida))


def remover_repetidos(textos, manifesto):
    """Tira de cada arquivo os parágrafos longos que já apareceram num arquivo anterior (ex.: o mesmo texto no
    relatório e num anexo). Fica registrado no manifesto quanto foi tirado de cada arquivo."""
    vistos, saida = set(), []
    for origem, texto in textos:
        manter, removidos = [], 0
        for paragrafo in re.split(r"\n\s*\n", texto):
            chave = re.sub(r"\W+", " ", _norm(paragrafo)).strip()
            if len(chave) >= 80 and chave in vistos:
                removidos += len(paragrafo)
                continue
            if len(chave) >= 80:
                vistos.add(chave)
            manter.append(paragrafo)
        if removidos:
            manifesto.setdefault("repetidos", []).append({"arquivo": origem, "caracteres": removidos})
        saida.append((origem, "\n\n".join(manter)))
    return saida


def dividir_limite(tamanhos, limite, minimo=2000):
    """Divide o limite entre os arquivos: quem precisa de menos que a parte igual fica com o que precisa, e a sobra
    é dividida entre os maiores. Os primeiros da lista (relatórios) recebem o dobro do peso."""
    pesos = [2 if k == 0 else 1 for k in range(len(tamanhos))]
    cotas, pendentes, restante = [0] * len(tamanhos), set(range(len(tamanhos))), limite
    while pendentes:
        peso_total = sum(pesos[i] for i in pendentes)
        parte = {i: restante * pesos[i] // peso_total for i in pendentes}
        cabem = {i for i in pendentes if tamanhos[i] <= parte[i]}
        if not cabem:
            for i in pendentes:
                cotas[i] = max(minimo, parte[i])
            break
        for i in cabem:
            cotas[i] = tamanhos[i]
            restante -= tamanhos[i]
        pendentes -= cabem
    return cotas


# --- UMA ANÁLISE -------------------------------------------------------------------

def slug(texto):
    return re.sub(r"[^a-z0-9]+", "_", _norm(texto)).strip("_")[:60] or "orgao"


def processar_orgao(app, drive, orgao, cfg, saida):
    """Documentos → dossiê → insumos → deliberação → arquivos de saída. Devolve a linha do resumo."""
    inicio = time.time()
    pasta = saida / slug(orgao["sigla"] or orgao["nome"])
    pasta.mkdir(parents=True, exist_ok=True)
    linha = {"orgao": orgao["nome"], "sigla": orgao["sigla"], "vinculada_a": orgao["vinculada_a"], "situacao": "erro",
             "arquivos_lidos": 0, "arquivos_pulados": 0, "itens_dossie": 0, "conferidos": 0, "trade_offs": 0,
             "confianca": "", "custo_usd": 0.0, "minutos": 0.0, "observacao": ""}
    app["st"].session_state.clear()
    try:
        if orgao.get("documentos") is not None:          # texto já lido (ex.: relatório resumido enviado no app)
            texto, manifesto = orgao["documentos"]
        else:
            texto, manifesto = ler_documentos(drive, orgao, app["converter_arquivo"], app["LIMITE_CARACTERES"])
        (pasta / "arquivos_lidos.json").write_text(json.dumps(manifesto, ensure_ascii=False, indent=2), encoding="utf-8")
        linha["arquivos_lidos"], linha["arquivos_pulados"] = len(manifesto["lidos"]), len(manifesto["pulados"])
        relatorio, _ = app["limpar_relatorio"](texto) if texto else ("", [])
        log(f"  documentos: {len(manifesto['lidos'])} lidos, {len(manifesto['pulados'])} pulados, "
            f"{len(manifesto['erros'])} com erro, {len(manifesto['cortados'])} cortados")

        nome_pesquisa = orgao["nome"] + (f" (vinculado à {orgao['vinculada_a']})" if orgao["vinculada_a"] else "")
        dossie = app["montar_dossie"](cfg["modelo_pesquisa"], nome_pesquisa, cfg["data_corte"], cfg.get("foco", ""),
                                      estado=cfg.get("estado"))
        (pasta / "dossie.json").write_text(app["dossie_para_json"](dossie), encoding="utf-8")
        resumo = app["resumo_dossie"](dossie)
        linha["itens_dossie"], linha["conferidos"] = resumo["itens"], resumo["conferidos"]
        custo_pesquisa, _ = app["custo_estimado"](dossie.get("uso") or [])
        linha["custo_usd"] = round(custo_pesquisa, 3)
        log(f"  dossiê: {resumo['itens']} itens, {resumo['conferidos']} conferidos na fonte")
        if resumo["itens"] < app["MIN_ITENS_DOSSIE"]:
            erros = sorted({d["erro"] for d in dossie.get("diagnostico") or [] if d.get("erro")})
            linha["situacao"] = "dossiê insuficiente"
            linha["observacao"] = "; ".join(erros)[:300] or f"menos de {app['MIN_ITENS_DOSSIE']} itens"
            return linha

        campos, uso_insumos, _ = app["preparar_insumos"](cfg["modelo_auxiliar"], dossie, cfg.get("foco", ""))
        insumos = {c: app["como_texto"](campos.get(c, "")) for c in ("problema", "personas", "lacunas", "sem_voz")}
        if not insumos["problema"].strip() or not insumos["personas"].strip():
            linha["situacao"] = "insumos incompletos"
            return linha
        completude = app["indice_completude"](relatorio) if relatorio else None
        resultado = app["deliberar"](
            insumos, dossie, relatorio, completude,
            {**cfg, "uso_preparo": uso_insumos,
             "arquivo_nome": orgao.get("descricao_documentos") or f"{len(manifesto['lidos'])} arquivos do Drive",
             "origem": "lote", "dossie_revisado": False},
            progresso=lambda t: log(f"  {t}"))
        tm, memo = resultado["tension_map"], resultado["memorando"]
        verificacao = app["markdown_verificacao"](
            resultado["evidencias"], resultado["numeros"], resultado["registro_id"], resultado["modelo"],
            resultado["confianca"], resultado["completude"], tm, resultado["neutralidade"],
            resultado["resumo_dossie"], resultado["confronto"])
        meta = {"orgao": cfg["orgao_emissor"], "unidade": cfg["unidade"], "para": cfg.get("para", ""),
                "assunto": f"Mapa de tensões — {orgao['nome']}", "data": resultado["data"],
                "rodape_extra": f"apoio de IA, processamento automático, reg. {resultado['registro_id']}"}
        (pasta / "memorando.docx").write_bytes(app["gerar_docx"](memo + "\n\n" + verificacao, meta))
        (pasta / "memorando.md").write_text(memo, encoding="utf-8")
        (pasta / "tension_map.json").write_text(json.dumps(tm, ensure_ascii=False, indent=2), encoding="utf-8")
        (pasta / "registro.json").write_text(resultado["registro_json"], encoding="utf-8")
        linha.update(situacao="concluído", trade_offs=len(tm.get("trade_offs") or []),
                     confianca=resultado["confianca"]["nivel"],
                     custo_usd=round(resultado["custo"] + resultado["custo_extracao"], 3),
                     observacao="; ".join(resultado.get("problemas_formato") or [])[:300])
        return linha
    except Exception as e:
        linha["observacao"] = f"{type(e).__name__}: {e}"[:300]
        (pasta / "erro.txt").write_text(linha["observacao"], encoding="utf-8")
        return linha
    finally:
        linha["minutos"] = round((time.time() - inicio) / 60, 1)


def _reais(valor):
    return f"{valor:.2f}".replace(".", ",")


def gravar_resumo(saida, linhas, custo_estado=0.0):
    campos = list(linhas[0]) if linhas else ["orgao"]
    with open(saida / "resumo.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=campos, delimiter=";")
        w.writeheader()
        w.writerows(linhas)
    concluidos = [x for x in linhas if x["situacao"] == "concluído"]
    texto = [f"# Processamento em lote — {datetime.now():%d/%m/%Y %H:%M}", "",
             f"{len(concluidos)} de {len(linhas)} órgãos concluídos. Custo estimado: US$ "
             f"{_reais(sum(x['custo_usd'] for x in linhas) + custo_estado)}, dos quais US$ {_reais(custo_estado)} da "
             "pesquisa do Estado, feita uma vez e usada em todos os órgãos.", "",
             "Os memorandos foram gerados sem revisão humana do dossiê e dos insumos e dizem isso no quadro "
             "\"Sobre este documento\". Revise antes de circular.", "",
             "| Órgão | Situação | Arquivos lidos | Itens do dossiê (conferidos) | Trade-offs | Confiança | Observação |",
             "|---|---|---|---|---|---|---|"]
    for x in linhas:
        texto.append(f"| {x['orgao']} | {x['situacao']} | {x['arquivos_lidos']} | {x['itens_dossie']} ({x['conferidos']}) | "
                     f"{x['trade_offs']} | {x['confianca'] or '—'} | {x['observacao'] or ''} |")
    (saida / "resumo.md").write_text("\n".join(texto) + "\n", encoding="utf-8")


# --- PRINCIPAL -----------------------------------------------------------------------

def principal(argv=None, drive=None, app=None, cliente_batch=None):
    p = argparse.ArgumentParser(description="Mapa de tensões em lote a partir das pastas do Google Drive.")
    p.add_argument("--pasta", required=True, help="ID da pasta DOCUMENTOS RECEBIDOS no Drive")
    p.add_argument("--orgaos", default="", help="só estes órgãos: siglas ou partes do nome, separadas por vírgula")
    p.add_argument("--saida", default="resultados")
    p.add_argument("--parte", type=int, default=1, help="esta execução processa a parte N de --partes")
    p.add_argument("--partes", type=int, default=1)
    p.add_argument("--apenas-listar", action="store_true", help="lista os órgãos e arquivos, sem chamar modelos")
    p.add_argument("--modelo-pesquisa", default="anthropic/claude-sonnet-5-5")
    p.add_argument("--modelo-auxiliar", default="anthropic/claude-sonnet-5-5")
    p.add_argument("--modelo", default="anthropic/claude-sonnet-5-5", help="modelo do debate e do memorando")
    p.add_argument("--rodadas", type=int, default=2)
    p.add_argument("--data-corte", default=date.today().strftime("%d/%m/%Y"))
    p.add_argument("--foco", default="")
    p.add_argument("--orgao-emissor", default="Equipe de Transição de Governo")
    p.add_argument("--unidade", default="Equipe de Transição")
    p.add_argument("--para", default="")
    p.add_argument("--economico", action="store_true",
                   help="manda as chamadas da Anthropic pela Message Batches API: metade do preço, respostas mais lentas")
    p.add_argument("--prazo-minutos", type=float, default=320,
                   help="no modo econômico, quanto esperar no total; o que não terminar sai como erro")
    p.add_argument("--paralelos", type=int, default=40, help="no modo econômico, órgãos processados ao mesmo tempo")
    a = p.parse_args(argv)

    if drive is None:
        credenciais = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
        if not credenciais.strip():
            sys.exit("Falta GOOGLE_SERVICE_ACCOUNT_JSON (o conteúdo do JSON da conta de serviço).")
        drive = Drive(credenciais)
        log(f"Conta de serviço: {drive.email}")
    try:
        orgaos = planejar_orgaos(drive, a.pasta)
    except Exception as e:
        sys.exit(f"Não foi possível ler a pasta {a.pasta}: {e}. Confira se ela foi compartilhada com a conta de serviço.")
    orgaos = fatia(filtrar_orgaos(orgaos, a.orgaos), a.parte, a.partes)
    log(f"{len(orgaos)} órgão(s) nesta execução (parte {a.parte} de {a.partes}).")
    saida = Path(a.saida)
    saida.mkdir(parents=True, exist_ok=True)

    if a.apenas_listar:
        linhas = []
        for o in orgaos:
            arquivos = [f for pasta in o["pastas"] for f in drive.listar(pasta["id"]) if f["mimeType"] != PASTA_MIME]
            linhas.append({"orgao": o["nome"], "sigla": o["sigla"], "vinculada_a": o["vinculada_a"],
                           "pastas": len(o["pastas"]), "arquivos": len(arquivos),
                           "pulados_por_dados_pessoais": sum(bool(RE_ARQUIVO_PESSOAL.search(f["name"])) for f in arquivos)})
            log(f"{o['nome']}{' (vinculado a ' + o['vinculada_a'] + ')' if o['vinculada_a'] else ''}: "
                f"{len(o['pastas'])} pasta(s), {len(arquivos)} arquivo(s)")
        (saida / "orgaos.json").write_text(json.dumps(linhas, ensure_ascii=False, indent=2), encoding="utf-8")
        return linhas

    app = app or carregar_app()
    cfg = {"modelo_pesquisa": a.modelo_pesquisa, "modelo_auxiliar": a.modelo_auxiliar, "modelo": a.modelo,
           "n_rodadas": a.rodadas, "parar_cedo": a.rodadas >= 3, "modo_independente": False,
           "data_corte": a.data_corte, "foco": a.foco, "orgao_emissor": a.orgao_emissor, "unidade": a.unidade,
           "para": a.para}
    return rodar_orgaos(app, drive, orgaos, cfg, saida, economico=a.economico, cliente_batch=cliente_batch,
                        paralelos=a.paralelos, prazo_minutos=a.prazo_minutos)


def rodar_orgaos(app, drive, orgaos, cfg, saida, economico=False, cliente_batch=None, paralelos=40, prazo_minutos=320):
    """Analisa os órgãos e grava os arquivos de cada um em `saida`. Usado pelo lote no GitHub e pelo app.
    No modo econômico, os órgãos rodam em paralelo e as chamadas à Anthropic vão pela Batch API."""
    import lote_api
    saida = Path(saida)
    saida.mkdir(parents=True, exist_ok=True)
    app["st"] = lote_api.StPorFio(app["st"] if not isinstance(app["st"], lote_api.StPorFio) else app["st"]._st)
    fila = None
    if economico:
        # Todos os órgãos rodam em paralelo; cada chamada à Anthropic entra numa fila que vai à Batch API em lotes.
        fila = lote_api.FilaBatch(cliente=cliente_batch, prazo=time.time() + prazo_minutos * 60, log=log,
                                  **({"quieto": 0.2, "intervalo": 0.2} if cliente_batch is not None else {}))
        app["completion"] = fila.completion(app["completion"])
        app["RODADAS_JUNTAS"] = True
        log(f"Modo econômico: chamadas da Anthropic pela Batch API (metade do preço), até {paralelos} órgãos ao "
            f"mesmo tempo, prazo de {prazo_minutos:.0f} min.")
    # A camada do Estado (situação fiscal, dívida, previdência, calendário, cenário político) é a mesma para todos os
    # órgãos: é pesquisada uma vez e reaproveitada. Se falhar, cada órgão pesquisa a sua.
    custo_estado = 0.0
    if orgaos:
        log("Pesquisando a camada do Estado (uma vez para todos os órgãos)...")
        try:
            estado = app["pesquisar_estado"](cfg["modelo_pesquisa"], cfg["data_corte"], cfg["foco"])
            custo_estado = round(app["custo_estimado"](estado["uso"])[0], 3)
            (saida / "dossie_estado.json").write_text(json.dumps(
                {k: estado[k] for k in ("itens", "nao_encontrado", "diagnostico", "modelo", "data_corte")},
                ensure_ascii=False, indent=2), encoding="utf-8")
            log(f"  Estado: {len(estado['itens'])} itens (US$ {custo_estado:.2f})")
            cfg["estado"] = estado if estado["itens"] else None
            if not estado["itens"]:
                log("  a camada do Estado veio vazia; cada órgão vai pesquisar a sua")
        except Exception as e:
            log(f"  a pesquisa do Estado falhou ({type(e).__name__}: {e}); cada órgão vai pesquisar a sua")
            cfg["estado"] = None
    linhas = []
    if fila is None:
        for k, o in enumerate(orgaos, 1):
            log(f"[{k}/{len(orgaos)}] {o['nome']}" + (f" (vinculado a {o['vinculada_a']})" if o["vinculada_a"] else ""))
            linha = processar_orgao(app, drive, o, cfg, saida)
            linhas.append(linha)
            log(f"  → {linha['situacao']}" + (f": {linha['observacao']}" if linha["observacao"] else "")
                + f" ({linha['minutos']} min, US$ {linha['custo_usd']:.2f})")
            gravar_resumo(saida, linhas, custo_estado)   # grava a cada órgão: se a execução cair, o que já foi feito fica
        return linhas

    # modo econômico: os órgãos em paralelo; o resumo é regravado a cada órgão concluído, na ordem original
    prontas, trava = {}, threading.Lock()

    def um(k, o):
        log(f"[{k}/{len(orgaos)}] {o['nome']}: começando")
        linha = processar_orgao(app, drive, o, cfg, saida)
        with trava:
            prontas[k] = linha
            gravar_resumo(saida, [prontas[i] for i in sorted(prontas)], custo_estado)
        log(f"[{k}/{len(orgaos)}] {o['nome']} → {linha['situacao']}"
            + (f": {linha['observacao']}" if linha["observacao"] else "")
            + f" ({linha['minutos']} min, US$ {linha['custo_usd']:.2f})")
        return linha

    try:
        with ThreadPoolExecutor(max_workers=max(1, min(paralelos, len(orgaos) or 1))) as ex:
            linhas = list(ex.map(lambda par: um(*par), enumerate(orgaos, 1)))
    finally:
        fila.encerrar()
    log(f"Modo econômico: {fila.enviados} lote(s) enviados à Batch API.")
    return linhas


if __name__ == "__main__":
    principal()

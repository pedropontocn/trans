"""Entrada: leitura dos arquivos enviados (resumos ou pastas de documentos), limpeza e regras de pastas."""
import io
import os
import tempfile
import re
import zipfile
from functools import lru_cache
from pathlib import Path

from . import imagens
from .config import LIMITE_CARACTERES, LIMITE_RELATORIO
from .modelo import _norm


@lru_cache(maxsize=64)
def converter_arquivo(nome, conteudo):
    """Converte PDF, DOCX ou XLSX em Markdown. O cache evita reconverter o mesmo arquivo."""
    sufixo = "." + nome.rsplit(".", 1)[-1].lower()
    with tempfile.NamedTemporaryFile(delete=False, suffix=sufixo) as tmp:
        tmp.write(conteudo)
        caminho = tmp.name
    try:
        from markitdown import MarkItDown      # importado na hora: os testes trocam o módulo por um falso
        return MarkItDown().convert(caminho).text_content
    finally:
        os.remove(caminho)


def limpar_relatorio(texto, limite=None):
    """Tira do relatório o que não serve à deliberação: instruções do modelo, dados pessoais e o espaço vazio das
    tabelas. Corta no final o que passar do limite (LIMITE_RELATORIO), avisando."""
    limite = limite or LIMITE_RELATORIO
    avisos = []
    tamanho_original = len(texto)
    texto = compactar_tabelas(texto)        # células vazias e alinhamento: nenhum valor se perde
    # Páginas de orientação do modelo de relatório (antes da seção 1)
    texto = re.sub(r"#+\s*\**ORIENTAÇÕES DE PREENCHIMENTO.*?(?=#+\s*\**1\.\s*APRESENTA)", "", texto, flags=re.S | re.I)
    # Quadros "Como preencher"
    texto = re.sub(r"\**Como preencher:?\**.*?(?:\n\s*\n|$)", "", texto, flags=re.S | re.I)
    # Seção 9 (pontos focais: nomes e contatos de servidores)
    # (só até o próximo arquivo, quando vários documentos do órgão vêm juntos)
    texto, n9 = re.subn(r"#+\s*\**9\.\s*PONTOS FOCAIS.*?(?=^# ARQUIVO: |\Z)", "", texto, flags=re.S | re.I | re.M)
    if n9:
        avisos.append("A seção 9 (pontos focais, com nomes e e-mails) não foi enviada ao modelo.")
    # E-mails que sobrarem em outras seções
    texto, n_email = re.subn(r"[\w.+-]+@[\w-]+\.[\w.-]+", "[e-mail omitido]", texto)
    if n_email:
        avisos.append(f"{n_email} endereço(s) de e-mail foram omitidos.")
    reduzido = tamanho_original - len(texto)
    if reduzido > 0:
        avisos.append(f"{reduzido:,} caracteres de instruções, dados pessoais e espaço vazio de tabelas foram "
                      "removidos.".replace(",", "."))
    if len(texto) > limite:
        avisos.append(f"⚠️ O relatório tem {len(texto):,} caracteres e passou do limite de {limite:,}: o final "
                      f"(cerca de {(len(texto) - limite) * 100 // len(texto)}%) foi cortado e não entra na análise."
                      .replace(",", "."))
        texto = texto[:limite]
    return texto, avisos


RE_SUFIXO_ZIP_DRIVE = re.compile(r"-\d{8}T\d{6}Z(?:-\d+)?-\d{3}$")


def nome_do_orgao_pelo_arquivo(nome):
    base = RE_SUFIXO_ZIP_DRIVE.sub("", Path(nome).stem)
    base = re.sub(r"[_]+", " ", base).strip()
    base = re.sub(r"^(relat[oó]rio\s+resumido|resumo|relat[oó]rio)\s*[-–:]*\s*(d[aeo]s?\s+)?", "", base, flags=re.I).strip()
    return re.sub(r"\s{2,}", " ", base) or Path(nome).stem


EXTENSOES_RESUMO = (".docx", ".pdf", ".xlsx", ".xls", ".pptx", *sorted(imagens.EXTENSOES_IMAGEM))


PASTA_MIME = "application/vnd.google-apps.folder"


EXPORTAR = {  # arquivos nativos do Google são exportados para um formato que o MarkItDown lê
    "application/vnd.google-apps.document": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
    "application/vnd.google-apps.spreadsheet": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
    "application/vnd.google-apps.presentation": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx"),
}


EXTENSOES = {".pdf", ".docx", ".xlsx", ".xls", ".pptx", ".csv", ".txt", ".md", ".html", ".htm",
             *imagens.EXTENSOES_IMAGEM}


def texto_do_arquivo(converter, nome, dados, origem, manifesto):
    """O texto de um arquivo: o digitado (MarkItDown) mais a transcrição do que está em imagem (páginas digitalizadas,
    slides, prints, fotos), quando a rodada liga a transcrição. Devolve "" se não houver texto; erro vai ao manifesto."""
    texto = ""
    if Path(nome).suffix.lower() not in imagens.EXTENSOES_IMAGEM:
        try:
            texto = converter(nome, dados) or ""
        except Exception as e:
            manifesto["erros"].append({"arquivo": origem, "erro": f"{type(e).__name__}: {e}"[:300]})
            if Path(nome).suffix.lower() != ".pdf":
                return ""
    transcrito = imagens.transcrever_arquivo(nome, dados, origem)
    if transcrito:
        manifesto.setdefault("com_imagem_transcrita", []).append(origem)
    return (texto.rstrip() + transcrito) if transcrito else texto


def _motivo_sem_texto(nome):
    if Path(nome).suffix.lower() in imagens.EXTENSOES_IMAGEM | {".pdf", ".pptx", ".docx"} and not imagens.ativa():
        return "sem texto digitado; está em imagem e a leitura de imagens está desligada"
    return "sem texto legível (nem digitado, nem em imagem)"


LIMITE_ARQUIVO = 30_000_000


PRIORIDADE_NOME = re.compile(r"relat|transi|resumo|situa|diagn", re.I)


# Arquivos que costumam ter só dados pessoais (contatos, telefones, CPF): não vão para a API do modelo.
RE_ARQUIVO_PESSOAL = re.compile(r"telefone|contato|ponto[s]?[ _-]*foca|cpf|dados[ _-]*pessoais|curr[ií]culo|agenda[ _-]*de[ _-]*contatos", re.I)


RE_CPF = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")


# Telefone só com DDD entre parênteses, celular de 5+4 dígitos ou precedido de "tel", "fone", "celular":
# assim "PPA 2024-2027" e valores numéricos não são apagados.
RE_TELEFONE = re.compile(r"\(\d{2}\)\s?9?\d{4}[\s.-]?\d{4}(?!\d)|(?<!\d)9\d{4}-\d{4}(?!\d)"
                         r"|(?i:\b(?:tel(?:efone)?|fone|cel(?:ular)?|whats(?:app)?)\.?:?\s*)(?:\d{2}\s?)?9?\d{4}[\s.-]?\d{4}(?!\d)")


def limpar_dados_pessoais(texto):
    texto = RE_CPF.sub("[CPF omitido]", texto)
    return RE_TELEFONE.sub("[telefone omitido]", texto)


def siglas_conhecidas():
    """As siglas das secretarias (bases_embutidas/siglas_2026.json) e os apelidos da folha."""
    import json
    from .folha import APELIDOS, PASTA_BASES
    try:
        tabela = json.loads((Path(os.getenv("PASTA_BASES") or PASTA_BASES) / "siglas_2026.json")
                            .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set(APELIDOS)
    return set(tabela.get("unidades", {})) | set(tabela.get("sucessoras", {})) | set(APELIDOS)


def sigla_conhecida(nome):
    """A sigla de secretaria no começo ou no fim do nome ("SEEDUC - apresentação", "Educação - SEEDUC"), se for uma
    das conhecidas; senão ""."""
    conhecidas = siglas_conhecidas()
    for candidata in (re.match(r"\s*([A-Z][A-Z0-9]{1,14})\b", nome or ""), sigla(nome or "")):
        valor = candidata.group(1) if hasattr(candidata, "group") else candidata
        if valor and valor in conhecidas:
            return valor
    return ""


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


def _extensao(nome, mime):
    if mime in EXPORTAR:
        return EXPORTAR[mime][1]
    return Path(nome).suffix.lower()


def _guardar_secao3(manifesto, origem, nome, dados):
    """Se o arquivo for um Relatório de Transição (modelo v2) em PDF, guarda no manifesto, lidas por código, as
    fichas da seção 3 e o quadro 4.1: são a base do caderno executivo. Não interfere na leitura do texto."""
    if not str(nome).lower().endswith(".pdf"):
        return
    from .secao3 import ler_relatorio_pdf
    lido = ler_relatorio_pdf(origem, dados)
    if lido["fichas"]:
        manifesto.setdefault("secao3", []).append(dict(lido, arquivo=origem))


def ler_documentos(drive, orgao, converter, limite_total):
    """Baixa e converte os arquivos das pastas do órgão. Devolve (texto, manifesto). O manifesto diz o que foi lido,
    pulado (formato, tamanho ou dados pessoais), cortado para caber no limite e o que deu erro."""
    manifesto = {"lidos": [], "pulados": [], "erros": [], "cortados": []}
    textos = []

    def converter_bytes(nome, dados, origem):
        n_erros = len(manifesto["erros"])
        texto = texto_do_arquivo(converter, nome, dados, origem, manifesto)
        if texto.strip():
            del manifesto["erros"][n_erros:]          # o PDF que o conversor não leu, mas a transcrição leu
            textos.append((origem, limpar_dados_pessoais(texto)))
            _guardar_secao3(manifesto, origem, nome, dados)
        elif len(manifesto["erros"]) == n_erros:
            manifesto["pulados"].append({"arquivo": origem, "motivo": _motivo_sem_texto(nome)})

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

    textos.sort(key=lambda t: (not PRIORIDADE_NOME.search(t[0]), t[0]))
    return montar_material(textos, manifesto, limite_total), manifesto


RE_ABA = re.compile(r"(?m)^(?=## )")
EXTENSOES_PLANILHA = (".xlsx", ".xls", ".csv")


def cortar(origem, texto, cota):
    """Corta um arquivo na sua cota. Planilha corta por aba: cada aba recebe uma parte (a pequena entra inteira),
    para nenhuma ficar de fora porque as primeiras eram grandes; o corte é sempre no fim de uma linha. Devolve o
    texto e, para planilha, as abas cortadas."""
    abas = [a for a in RE_ABA.split(texto) if a.strip()]
    if not origem.lower().endswith(EXTENSOES_PLANILHA) or len(abas) < 2:
        return texto[:cota].rsplit("\n", 1)[0] + "\n\n[… cortado para caber no limite]", []
    marca = "\n[… aba cortada para caber no limite: {usados:,} de {total:,} caracteres]\n"
    folga = len(marca) + 40
    cotas = dividir_limite([len(a) for a in abas], max(cota - folga * len(abas), 2000 * len(abas)), pesos_iguais=True)
    saida, cortadas = [], []
    for aba, q in zip(abas, cotas):
        if len(aba) <= q:
            saida.append(aba)
            continue
        pedaco = aba[:q].rsplit("\n", 1)[0]
        nome = aba.split("\n", 1)[0].removeprefix("## ").strip()
        cortadas.append({"aba": nome, "caracteres": len(aba), "usados": len(pedaco)})
        saida.append(pedaco + marca.format(usados=len(pedaco), total=len(aba)).replace(",", "."))
    return "".join(saida), cortadas


def montar_material(textos, manifesto, limite_total):
    """Junta os arquivos de uma secretaria no limite. Antes de cortar, tira o que ocupa espaço sem trazer
    informação: células vazias de planilha e trechos repetidos entre arquivos. Depois divide o limite: o primeiro
    (relatório ou resumo) com peso dobrado, e quem precisa de menos que a sua parte deixa a sobra para os outros.
    O cabeçalho de cada arquivo e as marcas de corte entram na conta, para o total ficar dentro do limite."""
    textos = [(origem, compactar_tabelas(texto)) for origem, texto in textos]
    textos = remover_repetidos(textos, manifesto)
    cabecalhos = sum(len(f"# ARQUIVO: {o}\n\n") + 2 for o, _ in textos)
    cotas = dividir_limite([len(t) for _, t in textos], max(limite_total - cabecalhos - 200 * len(textos), 0))
    partes = []
    for (origem, texto), cota in zip(textos, cotas):
        if len(texto) > cota:
            original = len(texto)
            texto, abas = cortar(origem, texto, cota)
            manifesto["cortados"].append({"arquivo": origem, "caracteres": original, "usados": len(texto),
                                          **({"abas_cortadas": abas} if abas else {})})
        manifesto["lidos"].append({"arquivo": origem, "caracteres": len(texto)})
        partes.append(f"# ARQUIVO: {origem}\n\n{texto}")
    return "\n\n".join(partes)


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


def dividir_limite(tamanhos, limite, minimo=2000, pesos_iguais=False):
    """Divide o limite entre os arquivos: quem precisa de menos que a parte igual fica com o que precisa, e a sobra
    é dividida entre os maiores. O primeiro da lista (relatório) recebe o dobro do peso, salvo `pesos_iguais`."""
    pesos = [2 if k == 0 and not pesos_iguais else 1 for k in range(len(tamanhos))]
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


def slug(texto):
    return re.sub(r"[^a-z0-9]+", "_", _norm(texto)).strip("_")[:60] or "orgao"


class ZipComoDrive:
    """Faz um ou mais .zip (a pasta baixada do Drive) se comportarem como a pasta no Drive, para usar as mesmas regras
    do lote: subpasta que repete o nome da secretaria é juntada a ela; as demais são órgãos vinculados."""
    RAIZ = "__raiz__"

    def __init__(self, arquivos):
        """arquivos: lista de (nome, bytes). Os .zip são abertos; os demais entram na pasta principal."""
        self.pasta_mime = PASTA_MIME
        self.filhos = {self.RAIZ: {}}
        self.origem = {}                              # id do arquivo -> (bytes do zip ou do arquivo, nome interno)
        soltos, topo_padrao = [], None
        for nome, conteudo in arquivos:
            if not nome.lower().endswith(".zip"):
                soltos.append((nome, conteudo))
                continue
            topo = RE_SUFIXO_ZIP_DRIVE.sub("", Path(nome).stem).strip() or "Pasta enviada"
            with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
                infos = [i for i in z.infolist() if not i.is_dir()]
            caminhos = [[p for p in i.filename.replace("\\", "/").split("/") if p] for i in infos]
            # o zip do Drive costuma trazer a pasta como primeiro nível; se não trouxer, usa o nome do arquivo
            tem_topo = bool(caminhos) and all(len(c) > 1 for c in caminhos) and len({c[0] for c in caminhos}) == 1
            for info, partes in zip(infos, caminhos):
                partes = partes if tem_topo else [topo] + partes
                topo_padrao = topo_padrao or partes[0]
                self._incluir(partes, info.file_size, (conteudo, info.filename))
        for nome, conteudo in soltos:
            self._incluir([topo_padrao or "Arquivos enviados", nome], len(conteudo), (conteudo, None))

    def _incluir(self, partes, tamanho, origem):
        pai = self.RAIZ
        for pasta in partes[:-1]:
            pid = pai + "/" + pasta
            self.filhos[pai].setdefault(pasta, {"id": pid, "name": pasta, "mimeType": self.pasta_mime})
            self.filhos.setdefault(pid, {})
            pai = pid
        fid = pai + "/" + partes[-1]
        self.filhos[pai][partes[-1]] = {"id": fid, "name": partes[-1], "mimeType": "application/octet-stream",
                                        "size": str(tamanho)}
        self.origem[fid] = origem

    def listar(self, pasta_id):
        return list(self.filhos.get(pasta_id, {}).values())

    def baixar(self, arquivo):
        conteudo, interno = self.origem[arquivo["id"]]
        if interno is None:
            return conteudo
        with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
            return z.read(interno)

    def orgaos(self):
        return planejar_orgaos(self, self.RAIZ)


def resumos_do_envio(arquivos):
    """Lista (arquivo, órgão sugerido, bytes) dos relatórios resumidos: os Word e PDF de dentro dos .zip e os enviados
    soltos. Ignora pastas, arquivos temporários do Word e outros formatos."""
    itens = []
    for nome, conteudo in arquivos:
        if nome.lower().endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
                for info in z.infolist():
                    interno = Path(info.filename.replace("\\", "/"))
                    if (info.is_dir() or interno.name.startswith(("~$", "._")) or "__MACOSX" in interno.parts
                            or interno.suffix.lower() not in EXTENSOES_RESUMO):
                        continue
                    itens.append({"arquivo": interno.name, "orgao": nome_do_orgao_pelo_arquivo(interno.name),
                                  "conteudo": z.read(info)})
        elif nome.lower().endswith(EXTENSOES_RESUMO):
            itens.append({"arquivo": nome, "orgao": nome_do_orgao_pelo_arquivo(nome), "conteudo": conteudo})
    return sorted(itens, key=lambda i: i["orgao"].lower())


def orgaos_do_envio(arquivos, cada_pasta=False):
    """Os órgãos de um envio. arquivos: lista de (nome, bytes).
    - cada_pasta=False: cada Word, PDF ou Excel (solto ou dentro do .zip) é o resumo de um órgão; o nome vem do arquivo, e
      arquivos com o mesmo órgão são juntados.
    - cada_pasta=True: o .zip traz os documentos brutos, uma pasta por órgão (subpastas com cara de órgão viram
      órgãos vinculados).
    Devolve [{"nome", "arquivos", "ler"}], em que ler() devolve (texto, manifesto)."""
    if cada_pasta:
        drive = ZipComoDrive(arquivos)
        raiz = drive.RAIZ
        while True:            # o zip da pasta-mãe traz uma pasta só, com as pastas dos órgãos dentro: desce até elas
            itens = drive.listar(raiz)
            dentro = drive.listar(itens[0]["id"]) if len(itens) == 1 else []
            if (dentro and itens[0]["mimeType"] == PASTA_MIME
                    and all(i["mimeType"] == PASTA_MIME and parece_orgao(i["name"]) for i in dentro)):
                raiz = itens[0]["id"]
            else:
                break
        return [{"nome": o["nome"], "arquivos": [p["name"] for p in o["pastas"]],
                 "ler": lambda o=o: ler_documentos(drive, o, converter_arquivo, LIMITE_CARACTERES)}
                for o in planejar_orgaos(drive, raiz)]
    grupos = {}
    for r in resumos_do_envio(arquivos):
        grupos.setdefault(r["orgao"], []).append(r)
    # vários arquivos da mesma secretaria ("SEEDUC - apresentação.pptx", "SEEDUC - ofício.pdf"): uma secretaria só,
    # pela sigla conhecida no começo ou no fim do nome
    por_sigla = {}
    for nome in list(grupos):
        s = sigla_conhecida(nome)
        if s:
            por_sigla.setdefault(s, []).append(nome)
    for s, nomes in por_sigla.items():
        if len(nomes) > 1:
            grupos[s] = [r for n in nomes for r in grupos.pop(n)]

    def ler(itens):
        textos, manifesto = [], {"lidos": [], "pulados": [], "erros": [], "cortados": []}
        for r in itens:
            n_erros = len(manifesto["erros"])
            texto = texto_do_arquivo(converter_arquivo, r["arquivo"], r["conteudo"], r["arquivo"], manifesto)
            if texto.strip():
                del manifesto["erros"][n_erros:]
                textos.append((r["arquivo"], texto))
                _guardar_secao3(manifesto, r["arquivo"], r["arquivo"], r["conteudo"])
            elif len(manifesto["erros"]) == n_erros:
                manifesto["pulados"].append({"arquivo": r["arquivo"], "motivo": _motivo_sem_texto(r["arquivo"])})
        # vários arquivos: o mesmo limite dividido entre eles (sem isso, o corte no fim levaria o último inteiro)
        return montar_material(textos, manifesto, LIMITE_CARACTERES), manifesto

    def previa(itens):
        r = itens[0]
        return (converter_arquivo(r["arquivo"], r["conteudo"]) or "")[:4000]

    return [{"nome": nome, "arquivos": [r["arquivo"] for r in itens], "ler": lambda itens=itens: ler(itens),
             "previa": lambda itens=itens: previa(itens)} for nome, itens in grupos.items()]


# --- DOSSIÊS ENVIADOS ----------------------------------------------------------------------------

EXTENSOES_DOSSIE = (".docx", ".pdf", ".md", ".txt")
PALAVRAS_GENERICAS = {"secretaria", "estado", "de", "do", "da", "dos", "das", "e", "rj", "rio", "janeiro", "dossie",
                      "perplexity", "orgao", "sobre", "para", "transicao", "final", "v1", "v2"}


def _palavras(nome):
    return {p for p in re.findall(r"[a-z0-9]+", _norm(nome)) if p not in PALAVRAS_GENERICAS and len(p) > 1}


def _parecidos(a, b):
    """Nota de 0 a 1 de quanto dois nomes de órgão se referem ao mesmo órgão (sigla igual vale 1)."""
    sa, sb = sigla(a).lower(), sigla(b).lower()
    pa, pb = _palavras(a), _palavras(b)
    if sa and (sa == sb or sa in pb) or sb and sb in pa:
        return 1.0
    if not pa or not pb:
        return 0.0
    if pa <= pb or pb <= pa:
        return 0.9
    return len(pa & pb) / len(pa | pb)


RE_PARTE_DOSSIE = [  # o pacote de dossiês da equipe: por sigla, só a pesquisa com citações. A planilha de
    # vencimentos e os dossiês com o painel do SIGA/PNCP são ignorados: as bases de contratos são defasadas.
    ("pesquisa", re.compile(r"^([A-Z][A-Z0-9]{1,14})_pesquisa\.(md|txt)$")),
]
IGNORAR_DOSSIE = re.compile(r"^(00_|README|PAINEL|unidades_|vencimentos_180d_estado|AUTONOMOS|DOSSIE_AUTONOMOS)", re.I)
# as partes do pacote que trazem o SIGA/PNCP (planilha de vencimentos, dossiê reduzido com o painel, dossiê completo)
IGNORAR_SIGA = re.compile(r"(_vencimentos_180d\.csv|^[A-Z][A-Z0-9]{1,14}\.(md|txt)|^DOSSIE_[A-Z][A-Z0-9]{1,14}\.(md|txt))$")


def dossies_do_envio(arquivos):
    """Os dossiês enviados, um por órgão. Reconhece o pacote da equipe (por sigla, só SIGLA_pesquisa.md; SIGLA.md e
    SIGLA_vencimentos_180d.csv trazem o SIGA/PNCP e são ignorados; os nomes por extenso vêm de 00_CONSOLIDACAO) e, fora dele, aceita um
    arquivo por órgão (Word, PDF ou Markdown, com o nome do órgão no nome do arquivo).
    Devolve [{"orgao", "arquivos", "partes"}], em que partes traz os bytes de "pesquisa"."""
    grupos, nomes, soltos = {}, {}, []

    def incluir(caminho, conteudo):
        nome = Path(caminho).name
        if nome.startswith(("~$", "._")) or "__MACOSX" in caminho or "/referencia/" in "/" + caminho:
            return
        if nome.startswith("00_CONSOLIDACAO"):
            texto = conteudo.decode("utf-8", errors="replace")
            nomes.update({s: n.strip() for s, n in re.findall(r"^\|\s*([A-Z][A-Z0-9]{1,14})\s*\|\s*([^|]+?)\s*\|", texto, re.M)})
            return
        if IGNORAR_DOSSIE.search(nome) or IGNORAR_SIGA.search(nome):
            return
        for parte, padrao in RE_PARTE_DOSSIE:
            m = padrao.match(nome)
            if m:
                grupo = grupos.setdefault(m.group(1), {"arquivos": [], "partes": {}})
                grupo["arquivos"].append(nome)
                grupo["partes"][parte] = conteudo
                return
        if Path(nome).suffix.lower() in EXTENSOES_DOSSIE:
            soltos.append((nome, conteudo))

    for nome, conteudo in arquivos:
        if nome.lower().endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
                for info in z.infolist():
                    if not info.is_dir():
                        incluir(info.filename.replace("\\", "/"), z.read(info))
        else:
            incluir(nome, conteudo)
    itens = [{"orgao": f"{nomes[s]} - {s}" if s in nomes else s, "arquivos": g["arquivos"], "partes": g["partes"]}
             for s, g in sorted(grupos.items()) if "pesquisa" in g["partes"]]
    for nome, conteudo in soltos:
        base = re.sub(r"(?i)\bdossi[eê]\b\s*[-–:]*\s*(d[aeo]s?\s+)?", " ", Path(nome).stem)
        itens.append({"orgao": nome_do_orgao_pelo_arquivo(base.strip() + ".x"), "arquivos": [nome],
                      "partes": {"arquivo": (nome, conteudo)}})
    return itens


PASTA_DOSSIES_EMBUTIDOS = Path(__file__).resolve().parent.parent / "dossies_embutidos"


def dossies_embutidos(pasta=None):
    """O pacote de dossiês que vem com o app (pasta dossies_embutidos/, ou PASTA_DOSSIES): os .zip e arquivos soltos
    que estiverem lá, lidos como um envio. Devolve (dossiês, data do pacote), com a data tirada do nome do arquivo
    (dd-mm-aaaa) quando houver."""
    pasta = Path(pasta or os.getenv("PASTA_DOSSIES") or PASTA_DOSSIES_EMBUTIDOS)
    if not pasta.is_dir():
        return [], ""
    arquivos = [(str(c.relative_to(pasta)), c.read_bytes()) for c in sorted(pasta.rglob("*"))
                if c.is_file() and not c.name.startswith((".", "LEIA-ME", "README"))]
    if not arquivos:
        return [], ""
    datas = re.findall(r"(\d{2})-(\d{2})-(\d{4})", " ".join(n for n, _ in arquivos))
    data = max((f"{d}/{m}/{a}" for d, m, a in datas), key=lambda x: x[6:] + x[3:5] + x[:2]) if datas else ""
    dossies = dossies_do_envio(arquivos)
    for d in dossies:
        d["embutido"] = True
    return dossies, data


def juntar_dossies(embutidos, enviados):
    """Os dossiês disponíveis, por secretaria (pela sigla, quando há): o enviado na tela vale sobre o embutido da
    mesma secretaria, e herda o nome por extenso se vier só com a sigla."""
    chave = lambda d: sigla(d["orgao"]) or (d["orgao"] if re.fullmatch(r"[A-Z][A-Z0-9]{1,14}", d["orgao"]) else _norm(d["orgao"]))
    por_chave = {chave(d): d for d in embutidos}
    for d in enviados:
        k = chave(d)
        if k in por_chave and " - " in por_chave[k]["orgao"] and " - " not in d["orgao"]:
            d = dict(d, orgao=por_chave[k]["orgao"])
        por_chave[k] = d
    return list(por_chave.values())


def _texto_dossie(d):
    """O texto do dossiê: a pesquisa (com citações)."""
    textos = {}
    for parte, valor in d["partes"].items():
        if parte == "arquivo":
            nome, conteudo = valor
            textos["pesquisa"] = (conteudo.decode("utf-8", errors="replace") if nome.lower().endswith((".md", ".txt"))
                                  else converter_arquivo(nome, conteudo) or "")
        elif parte == "pesquisa":
            textos[parte] = valor.decode("utf-8-sig", errors="replace")
    return textos


def casar_dossies(orgaos, dossies):
    """Liga cada órgão ao seu dossiê pelo nome (sigla ou palavras do nome). Devolve os dossiês que não acharam órgão.
    O órgão ligado ganha "dossie_arquivo" e "ler_dossie" (devolve os textos do dossiê)."""
    livres = list(dossies)

    def ligar(o, d):
        livres.remove(d)
        o["dossie_arquivo"] = ", ".join(d["arquivos"])
        o["dossie_rotulo"] = d["orgao"]
        o["ler_dossie"] = lambda d=d: _texto_dossie(d)

    for o in orgaos:
        o.pop("ler_dossie", None)
        o.pop("dossie_arquivo", None)
        notas = sorted(((_parecidos(o["nome"], d["orgao"]), i) for i, d in enumerate(livres)), reverse=True)
        if notas and notas[0][0] >= 0.5:
            ligar(o, livres[notas[0][1]])
    # O nome do arquivo não disse de qual secretaria é ("TRANSIÇÃO.docx"): procura no começo do documento a sigla
    # ou o nome de um dossiê que sobrou. Só liga se exatamente um dossiê aparecer.
    for o in orgaos:
        if o.get("ler_dossie") or not o.get("previa") or not livres:
            continue
        try:
            inicio = _norm(o["previa"]() or "")
        except Exception:
            continue
        achados = [d for d in livres if _aparece(d["orgao"], inicio)]
        if len(achados) == 1:
            ligar(o, achados[0])
            o["nome"] = achados[0]["orgao"]
    return livres


def _aparece(nome_dossie, texto_norm):
    """A sigla (palavra inteira) ou o nome por extenso do dossiê está no texto?"""
    sig = sigla(nome_dossie) or (nome_dossie if re.fullmatch(r"[A-Z][A-Z0-9]{1,14}", nome_dossie) else "")
    extenso = _norm(nome_dossie.rsplit(" - ", 1)[0])
    return bool((sig and re.search(rf"\b{re.escape(sig.lower())}\b", texto_norm))
                or (len(extenso) > 12 and extenso in texto_norm))


def orgaos_so_com_dossie(dossies):
    """Secretarias que têm dossiê, mas nenhum documento enviado: analisadas só com o dossiê."""
    return [{"nome": d["orgao"], "arquivos": [], "texto": "", "so_dossie": True,
             "dossie_arquivo": ", ".join(d["arquivos"]), "dossie_rotulo": d["orgao"],
             "ler_dossie": lambda d=d: _texto_dossie(d)} for d in dossies]


def ler_dossie_de(dossie):
    """A função que lê os textos de um dossiê escolhido à mão na tabela."""
    return lambda: _texto_dossie(dossie)

"""Cruzamento com os dados abertos do TCE-RJ (https://dados.tcerj.tc.br/api/v1/docs): as multas e os débitos que o
Tribunal aplicou em processos da secretaria e das vinculadas, comparados com o que ela enviou. Tudo por código;
nenhum modelo é chamado.

Só entra o que é DECISÃO DO PRÓPRIO TRIBUNAL (multas e débitos, com processo, sessão e número da condenação). Os
outros conjuntos do portal (obras paralisadas, contratos, convênios, dotação) são declarados pelos órgãos e não
verificados pelo TCE: ficam de fora. A API não filtra por órgão: o app baixa o conjunto inteiro, uma vez por dia.

O cruzamento diz, de cada processo com condenação, se o número aparece no material da secretaria. O que o TCE tem e
ela não citou vai para a pauta de investigação.

VALORES NÃO ENTRAM NO RELATÓRIO. A base não diz a unidade de "ValorPenalidade" (R$ ou UFIR-RJ; o TCE-RJ costuma fixar
multa em UFIR-RJ) e repete a mesma condenação em uma linha por responsável ("258/2024-2", "258/2024-3"...), de modo
que somar as linhas multiplicaria o débito. O app conta condenações (pelo número, sem o sufixo do responsável) e
processos; o valor fica, como publicado, só no registro de auditoria.

O nome de cada órgão no TCE é próprio ("SEC EST INFRA E OBRAS PÚBLICAS", "EMOP-EMPRESA DE OBRAS PUBLICAS DO ERJ").
As secretarias vêm da tabela conferida em bases_embutidas/siglas_2026.json ("tce"); as vinculadas, do nome na LOA,
casado por código. Os nomes usados ficam no relatório, para conferência.
"""
import json
import os
import re
import threading
import time
import unicodedata
from datetime import date, datetime
from pathlib import Path

BASE = "https://dados.tcerj.tc.br/api/v1/"
DOCUMENTACAO = "https://dados.tcerj.tc.br/api/v1/docs"
CONJUNTOS = {"multas": ("penalidades_ressarcimento_estado", {"tipo": "multa"}),
             "debitos": ("penalidades_ressarcimento_estado", {"tipo": "debito"})}
ORIGEM = "decisão do TCE-RJ"
FONTE = "TCE-RJ, dados abertos (multas e débitos)"
RECENTES_ANOS = 3                 # "recentes": do ano de corte e dos dois anteriores
ESPERA_APOS_FALHA = 600           # segundos sem tentar de novo depois de uma falha de acesso
_TRAVA = threading.Lock()
_MEMORIA, _FALHAS = {}, {}


def ligado():
    return os.getenv("TCE_DESLIGADO", "") not in ("1", "true", "sim")


# --- download ------------------------------------------------------------------------------------------------------

def _baixar_json(caminho, params):
    """Uma chamada à API. Separada para os testes trocarem; levanta erro se a resposta não for JSON."""
    import urllib.parse
    import urllib.request
    url = BASE + caminho + ("?" + urllib.parse.urlencode(params) if params else "")
    pedido = urllib.request.Request(url, headers={"User-Agent": "analise-da-transicao/1.0", "Accept": "application/json"})
    ultimo = None
    for _ in range(2):
        try:
            with urllib.request.urlopen(pedido, timeout=45) as resposta:
                return json.loads(resposta.read().decode("utf-8-sig"))      # a resposta pode vir com BOM
        except Exception as e:                      # rede instável: tenta de novo antes de desistir
            ultimo = e
    raise ultimo


def conjunto(nome):
    """As linhas de um conjunto, baixadas uma vez por dia (memória e disco). Devolve (linhas, erro). Uma falha de
    acesso não é guardada como resultado do dia: depois de alguns minutos o app tenta de novo."""
    caminho, params = CONJUNTOS[nome]
    hoje = date.today().isoformat()
    marca = (nome, hoje)
    with _TRAVA:                                    # as secretarias rodam em paralelo: um download só
        if marca in _MEMORIA:
            return _MEMORIA[marca]
        if marca in _FALHAS and time.monotonic() - _FALHAS[marca][0] < ESPERA_APOS_FALHA:
            return [], _FALHAS[marca][1]
        pasta = Path(os.getenv("PASTA_REGISTROS") or "registros") / "tce"
        arquivo = pasta / f"{hoje}_{nome}.json"
        try:
            if arquivo.exists():
                _MEMORIA[marca] = (json.loads(arquivo.read_text(encoding="utf-8")), "")
                return _MEMORIA[marca]
        except (OSError, ValueError):
            pass
        try:
            resposta = _baixar_json(caminho, params)
            if not isinstance(resposta, list):
                raise ValueError("a resposta do TCE-RJ não veio como lista")
            linhas = [x for x in resposta if isinstance(x, dict)]
        except Exception as e:
            erro = f"{type(e).__name__}: {e}"[:200]
            _FALHAS[marca] = (time.monotonic(), erro)
            return [], erro
        try:
            pasta.mkdir(parents=True, exist_ok=True)
            arquivo.write_text(json.dumps(linhas, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
        _MEMORIA[marca] = (linhas, "")
        return _MEMORIA[marca]


# --- nomes dos órgãos ------------------------------------------------------------------------------------------------

ABREVIACOES = {"sec": "secretaria", "est": "estado", "estadual": "estado", "desenv": "desenvolvimento",
               "des": "desenvolvimento", "econ": "economico", "ind": "industria", "com": "comercio", "serv": "servico",
               "reg": "regional", "infra": "infraestrutura", "fund": "fundacao", "fundac": "fundacao",
               "instit": "instituto", "inst": "instituto", "depart": "departamento", "dep": "departamento",
               "cia": "companhia", "emp": "empresa", "assist": "assistencia", "tecn": "tecnica", "ext": "extensao",
               "transp": "transporte", "gab": "gabinete", "esp": "especial", "univ": "universidade", "ag": "agencia",
               "superint": "superintendencia", "pesq": "pesquisa", "adm": "administracao", "publ": "publica"}
VAZIAS = {"de", "do", "da", "dos", "das", "e", "rj", "erj", "rio", "janeiro", "estado", "em", "liq", "para", "a", "o",
          "extinta", "geral"}
TIPOS = ("secretaria", "fundacao", "instituto", "departamento", "companhia", "empresa", "fundo", "agencia",
         "universidade", "superintendencia", "centro", "junta", "loteria", "conselho")


def _sem_acento(texto):
    return unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode().lower()


RE_SIGLA_NA_FRENTE = re.compile(r"^\s*[A-Za-zÀ-ú/.]{2,14}\s*-\s*(?=\S)")


def _palavras(nome):
    nome = RE_SIGLA_NA_FRENTE.sub("", str(nome or ""), count=1)      # "EMOP-EMPRESA DE OBRAS..." → sem a sigla
    saida = []
    for p in re.findall(r"[a-z0-9]+", _sem_acento(nome)):
        p = ABREVIACOES.get(p, p)
        if len(p) > 4 and p.endswith("s") and not p.endswith("ss"):
            p = p[:-1]                              # transportes = transporte
        if p not in VAZIAS:
            saida.append(p)
    return saida


def _igual(a, b):
    """Mesma palavra, aceitando a cortada do lado do TCE ("EDUCATIV" = "educativa")."""
    return a == b or (min(len(a), len(b)) >= 5 and (a.startswith(b) or b.startswith(a)))


def _tipo(palavras):
    return next((p for p in palavras if p in TIPOS), "")


def mesmo_orgao(nome_tce, nome_loa):
    """O nome do TCE é o do órgão da LOA? Mesmo tipo (secretaria, fundação, empresa...) e as mesmas palavras do nome,
    aceitando sigla na frente ("EMOP-EMPRESA DE OBRAS PUBLICAS DO ERJ") e nome abreviado do lado do TCE."""
    a, b = _palavras(nome_loa), _palavras(nome_tce)
    if _tipo(a) != _tipo(b):
        return False
    na, nb = {p for p in a if p not in TIPOS}, {p for p in b if p not in TIPOS}
    comuns_a = {p for p in na if any(_igual(p, q) for q in nb)}
    comuns_b = {q for q in nb if any(_igual(p, q) for p in na)}
    if not comuns_a:
        return False
    uniao = len(na) + len(nb) - min(len(comuns_a), len(comuns_b))
    if min(len(comuns_a), len(comuns_b)) / uniao >= 0.6:
        return True
    # o nome do TCE é a versão curta do nome da LOA (ou o contrário): todas as palavras do menor estão no maior
    if len(na) <= len(nb):
        return comuns_a == na and len(na) >= 2 and len(na) / len(nb) >= 0.5
    return comuns_b == nb and len(nb) >= 2 and len(nb) / len(na) >= 0.5


def _tabelas():
    """As tabelas conferidas de bases_embutidas/siglas_2026.json: "tce", "tce_vinculadas" e "tce_a_confirmar"."""
    from .folha import PASTA_BASES
    try:
        dados = json.loads((Path(os.getenv("PASTA_BASES") or PASTA_BASES) / "siglas_2026.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        dados = {}
    return {c: dados.get(c) or {} for c in ("tce", "tce_vinculadas", "tce_a_confirmar")}


def alvos_da_secretaria(sigla):
    """Como achar a secretaria e as vinculadas nos nomes do TCE: os nomes conferidos da tabela (secretaria e
    antecessoras), os nomes das unidades na LOA e, para a entidade que o TCE abrevia demais, a tabela de vinculadas
    (nome do TCE → unidade orçamentária). "a_confirmar" são os nomes antigos que podem ser antecessoras."""
    from . import caderno
    from .folha import APELIDOS
    sigla = (sigla or "").strip().upper()
    tabelas = _tabelas()
    siglas = {sigla, APELIDOS.get(sigla, sigla)}
    conferidos = next((tabelas["tce"][s] for s in (sigla, APELIDOS.get(sigla, "")) if tabelas["tce"].get(s)), [])
    nomes_loa, uos = [], []
    try:
        loa, _ = caderno.orcamento()
        uos, _ = caderno.unidades_da_secretaria(sigla, loa, sigla, sigla)
        nomes_loa = [loa["uos"][u]["nome"] for u in uos if loa["uos"][u].get("nome")]
    except Exception:
        pass
    return {"sigla": sigla, "conferidos": conferidos, "loa": nomes_loa,
            "vinculadas": [_sem_acento(n) for n, uo in tabelas["tce_vinculadas"].items() if uo in uos],
            "a_confirmar": [n for n, quem in tabelas["tce_a_confirmar"].items() if siglas & set(quem)]}


def da_secretaria(nome_tce, alvos):
    """"secretaria", "antecessora (extinta)", "vinculada" ou "" para um nome de unidade do TCE."""
    nome = str(nome_tce or "").strip()
    if not nome:
        return ""
    chave = _sem_acento(nome)
    for conferido in alvos["conferidos"]:
        if _sem_acento(conferido) == chave:
            return "antecessora (extinta)" if "extinta" in chave else "secretaria"
    if chave in alvos.get("vinculadas", ()):
        return "vinculada"
    if any(_sem_acento(n) == chave for n in alvos.get("a_confirmar", ())):
        return ""                                   # nome antigo sem ligação confirmada: não entra (ver cruzar)
    if alvos["sigla"] and re.match(rf"\s*{re.escape(alvos['sigla'].lower())}\s*[-–]", chave):     # "SIGLA - NOME"
        return "secretaria"
    for loa in alvos["loa"]:
        if mesmo_orgao(nome, loa):
            # a secretaria só casa pelo nome se a tabela conferida não tiver nada para ela
            if _tipo(_palavras(loa)) == "secretaria":
                if alvos["conferidos"]:
                    continue
                return "antecessora (extinta)" if "extinta" in chave else "secretaria"
            return "vinculada"
    return ""


# --- citado pela secretaria? ---------------------------------------------------------------------------------------

def _digitos(texto):
    return re.sub(r"\D", "", str(texto or ""))


class Material:
    """O material da secretaria preparado para a busca do número do processo: só os dígitos."""

    def __init__(self, texto):
        self.digitos = _digitos(texto)

    def cita(self, processo):
        """O processo do TCE ("100002-7/2020") aparece no material? Compara só os dígitos, para valer com qualquer
        pontuação; número curto demais não conta."""
        p = _digitos(processo)
        return "processo" if len(p) >= 9 and p in self.digitos else ""


# --- o cruzamento ----------------------------------------------------------------------------------------------------

def _data(valor):
    valor = str(valor or "").strip()
    for formato in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(valor[:10], formato).date()
        except ValueError:
            continue
    return None


def _numero(valor):
    if isinstance(valor, (int, float)):
        return float(valor)
    valor = str(valor or "").strip()
    if not valor:
        return None
    try:
        return float(valor.replace(".", "").replace(",", ".")) if "," in valor else float(valor)
    except ValueError:
        return None


def _n(quantos, um, muitos):
    return f"{quantos} {um if quantos == 1 else muitos}"


def _condenacoes(lista, tipo=None):
    """Quantas condenações há na lista: o TCE publica uma linha por responsável ("258/2024-2", "258/2024-3"...); a
    condenação é o número sem o sufixo, dentro do processo."""
    return len({(p["tipo"], p["processo"], p["condenacao_base"]) for p in lista if tipo in (None, p["tipo"])})


def cruzar(sigla, texto_material, data_corte=None):
    """O cruzamento de uma secretaria: as multas e os débitos do TCE-RJ em processos dela, das vinculadas e das
    antecessoras extintas, cada um com "citado" (se o processo aparece no material). Devolve também os nomes do TCE
    usados, o resumo e os erros de acesso. Nunca levanta erro: sem acesso, a lista vem vazia e o erro fica dito."""
    corte = _data(data_corte) or date.today()
    alvos = alvos_da_secretaria(sigla)
    material = Material(texto_material)
    saida = {"sigla": alvos["sigla"], "consultado_em": date.today().isoformat(), "fonte": DOCUMENTACAO,
             "origem": ORIGEM, "unidades": {}, "erros": [], "penalidades": [], "resumo": {}, "a_confirmar": {}}
    desde = corte.year - RECENTES_ANOS + 1
    antigos = {_sem_acento(n): n for n in alvos["a_confirmar"]}
    if not (alvos["conferidos"] or alvos["loa"]):
        saida["erros"].append("a secretaria não foi achada na tabela de nomes do TCE-RJ nem na LOA")
        return saida
    for tipo, rotulo in (("multas", "multa"), ("debitos", "débito")):
        linhas, erro = conjunto(tipo)
        if erro:
            saida["erros"].append(f"{tipo}: {erro}")
        for k, l in enumerate(linhas):
            if str(l.get("TipoEnte") or "ESTADUAL").upper() != "ESTADUAL":
                continue
            papel = da_secretaria(l.get("NomeOrgao"), alvos)
            processo = str(l.get("Processo") or "").strip()
            antigo = antigos.get(_sem_acento(str(l.get("NomeOrgao") or "").strip()))
            if antigo and processo and isinstance(l.get("AnoCondenacao"), int) and l["AnoCondenacao"] >= desde:
                saida["a_confirmar"].setdefault(antigo, [])       # nome antigo, possível antecessora: fora da contagem
                if processo not in saida["a_confirmar"][antigo]:
                    saida["a_confirmar"][antigo].append(processo)
            if not papel or not processo:
                continue
            unidade, condenacao = str(l.get("NomeOrgao")).strip(), str(l.get("Condenacao") or "").strip()
            saida["unidades"].setdefault(unidade, papel)
            saida["penalidades"].append({
                "unidade": unidade, "papel": papel, "tipo": rotulo, "processo": processo, "condenacao": condenacao,
                "condenacao_base": condenacao.rsplit("-", 1)[0].strip() or f"linha {k}",
                "ano": l.get("AnoCondenacao") if isinstance(l.get("AnoCondenacao"), int) else None,
                "valor_publicado": _numero(l.get("ValorPenalidade")),       # unidade não informada: só na auditoria
                "natureza": str(l.get("GrupoNatureza") or "").strip(),
                "sessao": _data(l.get("DataSessao")), "citado": material.cita(processo)})
    pen = saida["penalidades"]
    pen.sort(key=lambda p: (-(p["ano"] or 0), p["processo"], p["tipo"], p["condenacao"]))
    recentes = [p for p in pen if (p["ano"] or 0) >= desde]
    saida["resumo"] = {
        "desde": desde, "condenacoes": _condenacoes(pen), "processos": len({p["processo"] for p in pen}),
        "multas": _condenacoes(pen, "multa"), "debitos": _condenacoes(pen, "débito"),
        "recentes": _condenacoes(recentes), "processos_recentes": len({p["processo"] for p in recentes}),
        "multas_recentes": _condenacoes(recentes, "multa"), "debitos_recentes": _condenacoes(recentes, "débito"),
        "processos_citados": len({p["processo"] for p in pen if p["citado"]}),
        "processos_recentes_nao_citados": len({p["processo"] for p in recentes if not p["citado"]})}
    return saida


def _contagem(multas, debitos):
    partes = ([_n(multas, "condenação em multa", "condenações em multa")] if multas else []) + \
             ([_n(debitos, "condenação em débito", "condenações em débito")] if debitos else [])
    return " e ".join(partes)


def _por_processo(cruzamento):
    """Os processos com condenação recente, cada um com as suas linhas: primeiro os que a secretaria não citou, depois
    os com débito, depois pela sessão mais recente."""
    desde = cruzamento["resumo"]["desde"]
    grupos = {}
    for p in cruzamento["penalidades"]:
        if (p["ano"] or 0) >= desde:
            grupos.setdefault(p["processo"], []).append(p)
    ultima = lambda lista: max((p["sessao"] for p in lista if p["sessao"]), default=date.min)
    return sorted(grupos.items(), key=lambda x: (bool(x[1][0]["citado"]), -_condenacoes(x[1], "débito"),
                                                 -ultima(x[1]).toordinal(), x[0]))


def _consulta(cruzamento):
    return f"{date.fromisoformat(cruzamento['consultado_em']):%d/%m/%Y}"


def fatos(cruzamento):
    """O cruzamento como fatos para a análise de riscos (ids T1, T2...), todos decisão do Tribunal: quantas
    condenações recentes, quantos processos a secretaria não citou e os processos com débito. Sem valor (ver o
    cabeçalho do módulo). Sem condenação recente, nenhum fato."""
    r = (cruzamento or {}).get("resumo") or {}
    if not r.get("recentes"):
        return []
    base = {"rotulo": "confirmado em fonte oficial", "url": DOCUMENTACAO, "fonte": FONTE}
    processos = _por_processo(cruzamento)
    textos = [f"De {r['desde']} para cá, os dados abertos do TCE-RJ registram "
              f"{_contagem(r['multas_recentes'], r['debitos_recentes'])}, em "
              f"{_n(r['processos_recentes'], 'processo', 'processos')} do órgão e das vinculadas (consulta em "
              f"{_consulta(cruzamento)})."]
    fora = [numero for numero, lista in processos if not lista[0]["citado"]]
    if fora:
        textos.append((f"O processo TCE-RJ {fora[0]} não aparece" if len(fora) == 1 else
                       f"{len(fora)} desses processos do TCE-RJ não aparecem") + " no material enviado pela secretaria"
                      + ("" if len(fora) == 1 else f": {', '.join(fora[:6])}{' e outros' if len(fora) > 6 else ''}") + ".")
    for numero, lista in [x for x in processos if _condenacoes(x[1], "débito")][:3]:
        sessoes = sorted({p["sessao"] for p in lista if p["sessao"]})
        textos.append(f"Processo TCE-RJ {numero} ({lista[0]['unidade']}): "
                      f"{_contagem(_condenacoes(lista, 'multa'), _condenacoes(lista, 'débito'))}"
                      + (f", sessão de {sessoes[-1]:%d/%m/%Y}" if sessoes else "")
                      + (f", em {lista[0]['natureza'].lower()}" if lista[0]["natureza"] else "") + "."
                      + ("" if lista[0]["citado"] else " O processo não aparece no material da secretaria."))
    return [dict(base, id=f"T{k}", texto=t) for k, t in enumerate(textos, 1)]


def para_a_pauta(cruzamento):
    """O que o TCE decidiu e a secretaria não citou, como item da pauta de investigação."""
    r = (cruzamento or {}).get("resumo") or {}
    if not r.get("processos_recentes_nao_citados"):
        return []
    fora = [numero for numero, lista in _por_processo(cruzamento) if not lista[0]["citado"]]
    quais = f"{', '.join(fora[:4])}{' e outros' if len(fora) > 4 else ''}"
    return [{"o_que": (f"Situação do processo do TCE-RJ {quais}, com multa ou débito de {r['desde']} para cá, que não "
                       "aparece no material" if len(fora) == 1 else
                       f"Situação de {len(fora)} processos do TCE-RJ com multa ou débito de {r['desde']} para cá que não "
                       f"aparecem no material ({quais})"),
             "para_que": "Dizer se há determinação do Tribunal ainda a cumprir, recurso pendente ou valor a ressarcir "
                         "que passa para a nova gestão.",
             "onde": "TCE-RJ (consulta de processos) e o controle interno da secretaria", "serve_a": "",
             "apontado_por": ["Cruzamento com o TCE-RJ"]}]


def _fora_da_contagem(cruzamento):
    """As linhas sobre nomes antigos de secretaria que podem ser antecessoras e ainda não têm ligação confirmada."""
    desde = (cruzamento.get("resumo") or {}).get("desde")
    return [f"- **Nome antigo, fora da contagem:** a base traz {_n(len(processos), 'processo', 'processos')} com "
            f"condenação de {desde} para cá em nome de \"{nome}\", que pode ser antecessora desta secretaria. A ligação "
            f"não está confirmada; por isso não {'entra' if len(processos) == 1 else 'entram'} acima: "
            f"{', '.join(sorted(processos)[:8])}{' e outros' if len(processos) > 8 else ''}."
            for nome, processos in (cruzamento.get("a_confirmar") or {}).items() if processos]


def markdown(cruzamento, limite=12):
    """A seção do relatório de riscos: o resumo e os processos com condenação recente, com a marca de citado ou não."""
    if not cruzamento:
        return ""
    r = cruzamento.get("resumo") or {}
    md = ["## Cruzamento com o TCE-RJ: multas e débitos"]
    if cruzamento.get("erros") and not cruzamento.get("penalidades"):
        return "\n".join(md + ["_O cruzamento com os dados abertos do TCE-RJ não foi feito nesta rodada: "
                               + "; ".join(cruzamento["erros"])[:200] + "._"])
    if not r.get("condenacoes"):
        return "\n".join(md + ["_Nenhuma multa ou débito em processos do órgão nos dados abertos do TCE-RJ, consultados "
                               f"em {_consulta(cruzamento)}. Só entram decisões do próprio Tribunal._"]
                         + _fora_da_contagem(cruzamento))
    md.append(f"_Decisões do próprio Tribunal, dos dados abertos do TCE-RJ consultados em {_consulta(cruzamento)}. \"No "
              "material\" diz se o número do processo aparece no que a secretaria enviou. Os valores não entram: a base "
              "não informa a unidade (R$ ou UFIR-RJ) e repete a mesma condenação para cada responsável._")
    if r["recentes"]:
        nao = r["processos_recentes_nao_citados"]
        md.append(f"- **De {r['desde']} para cá:** {_contagem(r['multas_recentes'], r['debitos_recentes'])}, em "
                  f"{_n(r['processos_recentes'], 'processo', 'processos')}; "
                  + ("todos aparecem no material." if not nao else
                     f"{_n(nao, 'não aparece', 'não aparecem')} no material."))
    else:
        md.append(f"- **De {r['desde']} para cá:** nenhuma condenação.")
    md.append(f"- **Ao todo na base:** {_contagem(r['multas'], r['debitos'])}, em "
              f"{_n(r['processos'], 'processo', 'processos')}.")
    md.append("- **Unidades consideradas (como o TCE as nomeia):** "
              + "; ".join(f"{n} ({p})" for n, p in cruzamento.get("unidades", {}).items()) + ".")
    md += _fora_da_contagem(cruzamento)
    if cruzamento.get("erros"):
        md.append("- **Contagem incompleta:** parte da base não pôde ser consultada nesta rodada ("
                  + "; ".join(cruzamento["erros"])[:200] + ").")
    linhas = _por_processo(cruzamento)
    if linhas:
        md += ["| Processo | Unidade | Última sessão | Multas | Débitos | Natureza | No material |", "|---|---|---|---|---|---|---|"]
        for numero, lista in linhas[:limite]:
            sessoes = sorted({p["sessao"] for p in lista if p["sessao"]})
            md.append(f"| {numero} | {lista[0]['unidade']} | {f'{sessoes[-1]:%d/%m/%Y}' if sessoes else '–'} | "
                      f"{_condenacoes(lista, 'multa') or '–'} | {_condenacoes(lista, 'débito') or '–'} | "
                      f"{lista[0]['natureza'].capitalize() or '–'} | {'sim' if lista[0]['citado'] else 'não'} |")
        if len(linhas) > limite:
            md.append(f"_Mais {_n(len(linhas) - limite, 'processo', 'processos')} no arquivo de auditoria._")
    return "\n".join(md)

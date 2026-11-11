"""Infraestrutura dos testes.

Os testes NÃO chamam nenhuma API: o LiteLLM e o MarkItDown são trocados por versões falsas
antes de o app ser carregado. Por isso rodam de graça, no GitHub Actions ou no seu computador.
"""
import json
import re
import sys
import threading
import types
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

RAIZ = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
RELATORIO = (FIXTURES / "relatorio_exemplo.md").read_text(encoding="utf-8")

# Dossiê de exemplo: o que a "pesquisa" devolve e as páginas que o código abre para conferir os trechos.
TRECHO_LICITACOES = "Quatro concorrências estão adiadas sine die, somando R$ 120.500.000,00"
PAGINAS = {
    "https://transparencia.exemplo.gov.br/licitacoes":
        "<html><body><script>var x=1;</script><p>Quatro concorrências estão adiadas sine die, somando "
        "R$ 120.500.000,00, segundo o painel de compras.</p></body></html>",
    "https://www.exemplo.rj.gov.br/loa-2027": "<html><p>A LOA 2027 prevê déficit nominal de R$ 13,98 bilhões.</p></html>",
    "https://www.alerj.exemplo/calendario": "<html><p>Emendas ao projeto de lei orçamentária de 5 a 11 de novembro.</p></html>",
    "https://tce.exemplo.gov.br/decisao-123": "<html><p>O Tribunal apontou atraso na prestação de contas de convênios "
                                               "da Secretaria de Exemplo.</p></html>",
    "https://jornal.exemplo/materia": "<html><p>Governo eleito promete reduzir o número de secretarias.</p></html>",
    "https://transparencia.exemplo.gov.br/loa-sex": "<html><p>LOA 2026 da Secretaria de Exemplo: R$ 412.000.000,00.</p></html>",
}
ITENS_ESTADO = [
    {"bloco": "situacao_fiscal", "afirmacao": "A LOA 2027 prevê déficit nominal de R$ 13,98 bilhões.",
     "fonte": "PLOA 2027", "data_fonte": "10/2026", "url": "https://www.exemplo.rj.gov.br/loa-2027",
     "trecho": "A LOA 2027 prevê déficit nominal de R$ 13,98 bilhões", "tipo_fonte": "documento_oficial", "confianca": "alta"},
    {"bloco": "calendario_legal", "afirmacao": "As emendas à LOA vão de 5 a 11 de novembro.", "fonte": "Alerj",
     "data_fonte": "11/2026", "url": "https://www.alerj.exemplo/calendario",
     "trecho": "Emendas ao projeto de lei orçamentária de 5 a 11 de novembro", "tipo_fonte": "documento_oficial",
     "confianca": "alta"},
    {"bloco": "compromissos_governo", "afirmacao": "O governo eleito promete reduzir o número de secretarias.",
     "fonte": "Jornal Exemplo", "data_fonte": "10/2026", "url": "https://jornal.exemplo/materia",
     "trecho": "Governo eleito promete reduzir o número de secretarias", "tipo_fonte": "declaracao_politica",
     "confianca": "media"},
]
ITENS_ORGAO = [
    {"bloco": "orcamento_execucao", "afirmacao": "A LOA 2026 da Secretaria é de R$ 412.000.000,00.", "fonte": "LOA 2026",
     "data_fonte": "2026", "url": "https://transparencia.exemplo.gov.br/loa-sex",
     "trecho": "LOA 2026 da Secretaria de Exemplo: R$ 412.000.000,00", "tipo_fonte": "documento_oficial", "confianca": "alta"},
    {"bloco": "pessoal", "afirmacao": "A Secretaria tem 1.200 servidores efetivos.", "fonte": "Portal da Transparência",
     "data_fonte": "2026", "url": "https://transparencia.exemplo.gov.br/licitacoes",
     "trecho": "A Secretaria tem 1.200 servidores efetivos", "tipo_fonte": "dado_oficial", "confianca": "media"},
    {"bloco": "contratos_convenios", "afirmacao": TRECHO_LICITACOES + ".", "fonte": "Painel de compras",
     "data_fonte": "10/2026", "url": "https://transparencia.exemplo.gov.br/licitacoes", "trecho": TRECHO_LICITACOES,
     "tipo_fonte": "dado_oficial", "confianca": "alta"},
    {"bloco": "controle_judicializacao", "afirmacao": "O TCE-RJ apontou atraso na prestação de contas de convênios da Secretaria.",
     "fonte": "TCE-RJ, decisão 123", "data_fonte": "09/2026", "url": "https://tce.exemplo.gov.br/decisao-123",
     "trecho": "O Tribunal apontou atraso na prestação de contas de convênios da Secretaria de Exemplo",
     "tipo_fonte": "decisao_controle_judicial", "confianca": "alta"},
    {"bloco": "riscos_continuidade", "afirmacao": "O contrato de manutenção do sistema de folha vence em janeiro.",
     "fonte": "Diário Oficial", "data_fonte": "08/2026", "url": "https://pagina-que-nao-abre.exemplo/do",
     "trecho": "contrato de manutenção do sistema de folha", "tipo_fonte": "documento_oficial", "confianca": "media"},
    {"bloco": "inventado", "afirmacao": "Item sem link.", "fonte": "?", "url": "", "trecho": "", "tipo_fonte": "estudo"},
]
GRUPOS = [["situacao_fiscal", "regime_divida", "previdencia"], ["calendario_legal", "cenario_politico", "compromissos_governo"],
          ["mandato_estrutura", "orcamento_execucao", "pessoal"], ["contratos_convenios", "entregas_indicadores"],
          ["controle_judicializacao", "riscos_continuidade"]]
NAO_ENCONTRADO = {"estado": [{"bloco": "previdencia", "procurado": "Aporte do Tesouro ao RioPrevidência em 2026"}],
                  "orgao": [{"bloco": "pessoal", "procurado": "Número de terceirizados nos contratos de custeio"}]}

def dossie_exemplo(funcoes):
    """O dossiê como o app o monta, com os links já conferidos pelas páginas falsas."""
    itens = [funcoes.normalizar_item(b, "estado") for b in ITENS_ESTADO]
    itens += [x for x in (funcoes.normalizar_item(b, "orgao") for b in ITENS_ORGAO) if x]
    return {"orgao": "Secretaria de Exemplo", "data_corte": "04/11/2026", "foco": "", "modelo": "m", "origem": "pesquisa",
            "itens": funcoes.conferir_itens(funcoes.numerar_itens(itens)),
            "nao_encontrado": [dict(n, camada=c) for c, ns in NAO_ENCONTRADO.items() for n in ns], "uso": []}


MEMORANDO = """# Memorando Executivo

## Em síntese
- Quatro licitações somam R$ 120,5 mi e estão adiadas.
- A LOA 2026 é de R$ 412 mi.

## Os 3 principais trade-offs
### T1. Licitações adiadas
Decidir cedo ou esperar. Diferença de R$ 13,3 mi (cálculo) entre LOA e empenhado.

## Decisões que precisam ser tomadas nesta semana
1. Definir o destino das licitações adiadas.

## Dados faltantes
- Dotação atualizada (orçamento).

## Custo de não decidir
O prazo das atas é de cerca de 85 dias; um valor inventado: R$ 999,9 mi.

## Matriz de Risco
| Risco | Probabilidade | Impacto | Ação mitigadora | Responsável |
|---|---|---|---|---|
| Perda de propostas | Alta | Médio | Atualizar preços | Licitações |
| Obrigações sem caixa | Média | Alto | Demonstrativo de restos a pagar | Finanças |
"""


class LLMFalso:
    """Faz o papel do modelo. Cada teste ajusta as respostas que quer."""

    def __init__(self):
        self.chamadas = []
        self.trava = threading.Lock()
        self.paginas = dict(PAGINAS)                 # o que a "web" devolve quando o código abre um link
        self.falhar_pesquisa = False
        self.grupos_sem_json = set()                 # primeiro bloco dos grupos cuja resposta para sem o JSON
        self.grupos_com_erro = set()                 # primeiro bloco dos grupos cuja chamada dá erro
        self.continuacao_sem_json = False            # a continuação também para sem o JSON
        self.sem_relatorio = False
        self.diagnostico_orgao = {"secoes": [
            {"titulo": "Orçamento e execução", "itens": [
                {"texto": "A LOA 2026 da Secretaria é de R$ 412 milhões.", "origem": "dossie", "item": "O1", "trecho": ""},
                {"texto": "O órgão informa R$ 398,75 milhões empenhados até 23/10/2026.", "origem": "relatorio",
                 "item": "", "trecho": "Empenhado até 23/10/2026: R$ 398.750.000,00"},
                {"texto": "A Secretaria tem 40 subsecretarias.", "origem": "relatorio", "item": "",
                 "trecho": "a Secretaria tem 40 subsecretarias"}]},
            {"titulo": "Como se organiza", "itens": [
                {"texto": "Item que não existe.", "origem": "dossie", "item": "O999", "trecho": ""},
                {"texto": "O TCE-RJ apontou atraso na prestação de contas de convênios.", "origem": "dossie",
                 "item": "O4", "trecho": ""}],
             "leitura": "A secretaria tem pendências de controle.", "nao_se_sabe": ["Organograma atualizado"]}],
            "panorama": ["A Secretaria de Exemplo cuida de obras e tem 40 subsecretarias."],
            "organograma": [
                {"unidade": "Gabinete do Secretário", "sigla": "GAB", "subordinada_a": "", "titular": "",
                 "origem": "relatorio", "trecho": "Empenhado até 23/10/2026: R$ 398.750.000,00"},
                {"unidade": "Subsecretaria de Obras", "sigla": "SUBOB", "subordinada_a": "Gabinete do Secretário",
                 "titular": "vago", "origem": "relatorio", "trecho": "Empenhado até 23/10/2026: R$ 398.750.000,00"},
                {"unidade": "Superintendência de Projetos", "sigla": "", "subordinada_a": "Subsecretaria de Obras",
                 "titular": "", "origem": "relatorio", "trecho": "Empenhado até 23/10/2026: R$ 398.750.000,00"},
                {"unidade": "Subsecretaria Inventada", "subordinada_a": "Gabinete do Secretário",
                 "origem": "relatorio", "trecho": "frase que não existe no relatório"},
                {"unidade": "EMOP", "sigla": "EMOP", "subordinada_a": "", "vinculada": True, "origem": "dossie",
                 "item": "O1"}],
            "indicadores": [
                {"nome": "LOA 2026", "valor": "R$ 412 mi", "origem": "dossie", "item": "O1", "trecho": ""},
                {"nome": "Empenhado", "valor": "R$ 398,75 mi", "origem": "relatorio", "item": "",
                 "trecho": "Empenhado até 23/10/2026: R$ 398.750.000,00"},
                {"nome": "Inventado", "valor": "R$ 1 bi", "origem": "relatorio", "item": "", "trecho": "frase que não existe"}]}
        self.cruzamento_plano = {"compromissos": []}      # dossiê: cruzamento com o plano de governo
        self.leitura_institucional = {"gargalos": [], "acoes": []}   # dossiê: gargalos e plano dos 100 dias
        self.contratos_criticos = {"contratos": [
            {"contrato": "Contrato 99/2026", "objeto": "Manutenção predial", "contratado": "Empresa X", "valor": "R$ 398.750.000,00",
             "vigencia": "15/12/2026", "motivos": ["vence em breve", "valor alto"], "observacao": "Vence antes da posse.",
             "origem": "relatorio", "item": "", "trecho": "Empenhado até 23/10/2026: R$ 398.750.000,00"},
            {"contrato": "Contrato 7/2025", "objeto": "Obra", "contratado": "Y", "valor": "R$ 777 mi", "vigencia": "",
             "motivos": ["paralisado"], "observacao": "valor inventado", "origem": "relatorio", "item": "",
             "trecho": "Empenhado até 23/10/2026: R$ 398.750.000,00"},
            {"contrato": "Contrato sem origem", "objeto": "x", "contratado": "Z", "valor": "", "vigencia": "",
             "motivos": ["emergencial"], "observacao": "", "origem": "dossie", "item": "O999", "trecho": ""},
            {"contrato": "Licitações adiadas", "objeto": "Quatro concorrências", "contratado": "", "valor": "R$ 120.500.000,00",
             "vigencia": "", "motivos": ["passivo jurídico", "motivo inválido"], "observacao": "", "origem": "dossie",
             "item": "O3", "trecho": ""}]}
        self.calendario = {"eventos": [
            {"data": "23/10/2026", "tipo": "orcamento", "evento": "Corte do empenho informado", "objeto": "LOA 2026",
             "valor": "R$ 398.750.000,00", "consequencia": "", "decisao": "Conferir o empenhado",
             "origem": "relatorio", "item": "", "trecho": "Empenhado até 23/10/2026: R$ 398.750.000,00"},
            {"data": "31/12/2026", "tipo": "contrato", "evento": "Data trocada", "objeto": "x", "valor": "",
             "consequencia": "", "decisao": "", "origem": "relatorio", "item": "",
             "trecho": "Empenhado até 23/10/2026: R$ 398.750.000,00"},
            {"data": "15/12/2026", "tipo": "contrato", "evento": "Trecho inventado", "objeto": "Contrato 99/2026",
             "valor": "R$ 5 mi", "consequencia": "", "decisao": "", "origem": "relatorio", "item": "",
             "trecho": "o contrato 99/2026 vence em 15/12/2026"}]}
        self.confronto = {"divergencias": [
            {"item": "O4", "situacao": "nao_mencionado", "o_orgao_declara": "", "trecho_relatorio": "",
             "as_fontes_mostram": "O TCE-RJ apontou atraso na prestação de contas de convênios."},
            {"item": "O3", "situacao": "contradiz", "o_orgao_declara": "o motivo não foi informado",
             "trecho_relatorio": "O motivo do adiamento não foi informado", "as_fontes_mostram": "x"},
            {"item": "O99", "situacao": "contradiz", "trecho_relatorio": "x", "as_fontes_mostram": "item que não existe"},
            {"item": "O1", "situacao": "contradiz", "trecho_relatorio": "a Secretaria não tem orçamento", "as_fontes_mostram": "y"},
            {"item": "O3", "situacao": "nao_mencionado", "trecho_relatorio": "", "as_fontes_mostram": "licitações mencionadas"}]}
        self.analise_riscos = {
            "situacao": ["A secretaria tem R$ 412 milhões de LOA.", "Há licitações adiadas."],
            "riscos": [
                {"id": "R1", "titulo": "Licitações adiadas", "categoria": "Obras e projetos", "causa": "concorrências adiadas",
                 "consequencia": "obras não começam", "em_jogo": "R$ 120,5 mi", "prazo": "antes da posse",
                 "impacto": "Alto", "chance": "Alta", "em_curso": "", "decisao": "Retomar ou cancelar?",
                 "quem_decide": "Secretaria", "fatos": ["F1", "O3"]},
                {"id": "R2", "titulo": "Risco inventado", "categoria": "Fiscal e orçamentário", "causa": "x",
                 "consequencia": "y", "impacto": "Alto", "chance": "Baixa", "prazo": "", "decisao": "?", "fatos": ["F99"]}],
            "decisoes": [{"id": "Q1", "pergunta": "Retomar as licitações agora ou esperar?", "opcoes": [
                {"nome": "Retomar", "o_que_e": "publicar de novo"}, {"nome": "Esperar", "o_que_e": "deixar à nova gestão"}],
                "o_que_falta_saber": "preços atualizados", "riscos": ["R1"]}],
            "pedir": [{"o_que": "Lista de contratos vigentes com datas de término", "serve_a": "R1",
                       "para_que": "Dizer quais serviços ficam sem cobertura.", "onde": "SIGA"}]}
        self.revisao_agente = {"faltando": [], "exagerados": [{"risco": "R2", "motivo": "sem base"}],
                               "decisoes": [{"decisao": "Q1", "opcao": 1, "teme": "custo", "valoriza": "rapidez"}],
                               "faltam": [{"o_que": "Lista dos contratos vigentes, com as datas de término",
                                           "para_que": "Medir o alcance.", "onde": "SIGA", "serve_a": "R1"}]}
        self.faltam_do_contra = [{"o_que": "Parecer da PGE sobre a retomada das licitações", "serve_a": "R1",
                                  "para_que": "Confirmaria ou derrubaria o risco.", "onde": "SEI"}]
        self.conferencia_final = {"riscos": []}    # a conferência final das afirmações: nada a corrigir
        self.pontos_criticos = {"pontos": []}      # os pontos críticos que o modelo acha no material
        self.agentes_que_falham = set()
        self.consolidacao_riscos = None            # None: a consolidação devolve a análise com as visões
        self.temas = {"temas": [{"titulo": "Contratos vencendo", "descricao": "Vários contratos vencem.",
                                 "riscos": ["SEX:R1", "SEY:R1"]}, {"titulo": "Tema de uma só", "descricao": "x",
                                                                    "riscos": ["SEX:R1"]}]}
        self.neutralidade = {"avaliacao_geral": "levemente_enviesado",
                             "decisoes_desequilibradas": [],
                             "trade_offs": [{"id": "T1", "equilibrio": "pende_para_a", "motivo": "o polo A tem o dobro do espaço"}],
                             "recomendacoes_implicitas": [
                                 {"trecho": "Retomar ou cancelar", "por_que": "lista caminhos"},
                                 {"trecho": "é imprescindível retomar todas as obras imediatamente", "por_que": "inventado"}]}
        self.falhar_neutralidade = False
        self.caderno_ligacao = None               # None: liga toda ficha à ação 4489 e a 2ª ficha ao R1
        self.caderno_plano = {"vinculos": [
            {"secao": "3.1.1", "trecho_id": "P33.9", "citacao": "Criação do Calendário Estadual de Turismo"},
            {"secao": "3.1.2", "trecho_id": "P33.9", "citacao": "citação que não está no plano"}]}
        self.fichas_ruins = {}                    # seção → ficha que não passa nas travas
        self.caderno_material = {"programas": []}  # programas achados no material, quando não há relatório v2
        self.fichas_refeitas = 0
        self.revisao_texto = {"textos": {"R1.decisao": "Destino das licitações adiadas."}}
        self.modelos_que_falham = set()           # modelos (nomes) que respondem como fora do ar
        self.analises_quebradas = 0               # quantas respostas da análise de riscos vêm com JSON inválido
        self.checklist = {"respostas": [
            {"id": "C3", "resposta": "LOA 2026 de R$ 412 milhões.", "itens": ["O1"], "trechos": []},
            {"id": "C5", "resposta": "O TCE-RJ apontou atraso na prestação de contas de convênios.", "itens": ["O4"]}]}
        self.texto_relatorio = RELATORIO           # o que o MarkItDown falso devolve
        self.transcricao = "| Obra | Valor |\n|---|---|\n| Ponte do Rio | R$ 1.234.567,89 |"  # o que vem da imagem
        self.imagens_vistas = []

    def _resp(self, conteudo="", nome=None, args=None, motivo="stop", entrada=10000, saida=2000, buscas=None):
        chamadas = [NS(function=NS(name=nome, arguments=json.dumps(args)))] if nome else None
        uso = NS(prompt_tokens=entrada, completion_tokens=saida)
        if buscas is not None:
            uso.server_tool_use = NS(web_search_requests=buscas)
        return NS(choices=[NS(message=NS(content=conteudo, tool_calls=chamadas), finish_reason=motivo)], usage=uso)

    def __call__(self, model, messages, max_tokens, **kw):
        if model in self.modelos_que_falham:
            raise RuntimeError(f"{model} fora do ar")
        texto = lambda c: c if isinstance(c, str) else " ".join(p.get("text", "") for p in c)
        ultimo = texto(messages[-1]["content"])
        sistema = texto(messages[0]["content"])
        if "Você transcreve imagens de documentos" in sistema:
            with self.trava:
                self.chamadas.append({"modelo": model, "ferramenta": None, "ferramentas": [], "mensagens": messages,
                                      "kw": kw})
            imagem = next(p for p in messages[-1]["content"] if p.get("type") == "image_url")
            self.imagens_vistas.append(imagem["image_url"]["url"])
            return self._resp(self.transcricao, entrada=1600, saida=300)
        # com o relatório em cache, as instruções da etapa vêm na primeira mensagem do usuário, depois do relatório
        contexto = sistema + " " + (texto(messages[1]["content"]) if len(messages) > 1 else "")
        nomes = [t["function"]["name"] for t in kw.get("tools") or []]
        nome = nomes[0] if nomes else None
        with self.trava:
            self.chamadas.append({"modelo": model, "ferramenta": nome, "ferramentas": nomes, "mensagens": messages, "kw": kw})

        if "Você liga as fichas de programas" in sistema:
            pedido = json.loads(ultimo)
            return self._resp("[INÍCIO DO JSON]" + json.dumps(self.caderno_ligacao or {"fichas": [
                {"secao": f["secao"], "acoes": ["10010:23.695.0452.4489"], "riscos": ["R1"] if k == 1 else [],
                 "motivo": "teste"} for k, f in enumerate(pedido["fichas"])]}) + "[FIM DO JSON]")
        if "Você lê o material que uma secretaria" in sistema:
            return self._resp("[INÍCIO DO JSON]" + json.dumps(self.caderno_material) + "[FIM DO JSON]")
        if "Você indica, para cada programa" in sistema:
            return self._resp("[INÍCIO DO JSON]" + json.dumps(self.caderno_plano) + "[FIM DO JSON]")
        if "Você redige uma ficha do Caderno Executivo" in sistema:
            if "não passou na conferência" in ultimo:
                self.fichas_refeitas += 1
            pedido = json.loads(texto(messages[1]["content"]))
            sec = pedido["programa"].split()[0]
            tr = pedido["trechos"]
            if sec in self.fichas_ruins:
                return self._resp("[INÍCIO DO JSON]" + json.dumps(self.fichas_ruins[sec]) + "[FIM DO JSON]")

            def campo(c):
                k = f"{sec}:{c}"
                return {"valor": tr[k].split(": ", 1)[1], "fontes": [k]} if k in tr else \
                    {"valor": "Não informado pela secretaria", "fontes": []}
            ficha = {"programa": {"valor": pedido["programa"][len(sec) + 1:], "fontes": [f"{sec}:titulo"]},
                     "orgao_executor": campo("responsavel"), "objetivo": campo("objetivo"),
                     "base_legal": {"valor": "Não informado pela secretaria", "fontes": []},
                     "publico_cobertura": campo("publico"),
                     "orcamento": {"liquidado": {"valor": "", "data_base": "", "fontes": []},
                                   "fonte_recurso": {"valor": "", "fontes": []}},
                     "instrumentos": [], "execucao_fisica": campo("metas"), "situacao": campo("situacao"),
                     "proximos_marcos": [{"data": "15/01/2027", "descricao": "Encontro com o trade",
                                          "fontes": [f"{sec}:proximas"]}] if f"{sec}:proximas" in tr else [],
                     "pendencias_riscos": campo("pontos_criticos"), "responsavel_tecnico": campo("responsavel"),
                     "lacunas": [], "conflitos": []}
            return self._resp("[INÍCIO DO JSON]" + json.dumps(ficha) + "[FIM DO JSON]")
        if "Monte a camada" in texto(messages[0]["content"]):
            pedido = texto(messages[0]["content"])
            grupo = re.findall(r"^- ([a-z_]+): ", pedido, re.M)
            if self.falhar_pesquisa or grupo[0] in self.grupos_com_erro:
                raise RuntimeError("busca indisponível")
            continuacao = ultimo.startswith("Você parou antes")
            if grupo[0] in self.grupos_sem_json and (not continuacao or self.continuacao_sem_json):
                return self._resp("Fiz as buscas e encontrei documentos relevantes.", buscas=5)   # turno pausado
            camada = "estado" if 'camada\n"Estado"' in pedido else "orgao"
            todos = ITENS_ESTADO if camada == "estado" else ITENS_ORGAO
            conhecidos = {b for g in GRUPOS for b in g}
            itens = [i for i in todos if i["bloco"] in grupo or (i["bloco"] not in conhecidos and grupo[0] == "mandato_estrutura")]
            nao = [n for n in NAO_ENCONTRADO[camada] if n["bloco"] in grupo]
            return self._resp("Pesquisei. [INÍCIO DO JSON]" + json.dumps({"itens": itens, "nao_encontrado": nao})
                              + "[FIM DO JSON]", entrada=30000, saida=3000, buscas=0 if continuacao else 4)
        if "Você apoia a Equipe de Transição de Governo" in sistema:
            self.pedido_leitura = ultimo
            return self._resp("[INÍCIO DO JSON]" + json.dumps(self.leitura_institucional) + "[FIM DO JSON]")
        if "Você cruza o Plano de Governo" in sistema:
            self.pedido_plano = ultimo
            return self._resp("[INÍCIO DO JSON]" + json.dumps(self.cruzamento_plano) + "[FIM DO JSON]")
        if "lista os PONTOS CRÍTICOS" in contexto:
            self.pedido_pontos = contexto
            return self._resp("[INÍCIO DO JSON]" + json.dumps(self.pontos_criticos) + "[FIM DO JSON]")
        if "Você confronta o que um órgão declarou" in contexto:
            self.mensagem_confronto = ultimo
            return self._resp(json.dumps(self.confronto))
        if "Você escreve o DOSSIÊ de uma secretaria" in contexto:
            self.mensagem_diagnostico_orgao = ultimo
            return self._resp("[INÍCIO DO JSON]" + json.dumps(self.diagnostico_orgao) + "[FIM DO JSON]")
        if "Você lista os PRINCIPAIS CONTRATOS" in contexto:
            self.mensagem_contratos = ultimo
            return self._resp("[INÍCIO DO JSON]" + json.dumps(self.contratos_criticos) + "[FIM DO JSON]")
        if "Você responde ao CHECKLIST obrigatório" in contexto:
            self.mensagem_checklist = ultimo
            return self._resp("[INÍCIO DO JSON]" + json.dumps(self.checklist) + "[FIM DO JSON]")
        if "Você monta o calendário de vencimentos críticos" in contexto:
            self.mensagem_calendario = ultimo
            return self._resp("[INÍCIO DO JSON]" + json.dumps(self.calendario) + "[FIM DO JSON]")
        if "Você é analista de riscos" in sistema:
            if self.analises_quebradas > 0:                       # simula JSON inválido (aspas sem escape)
                self.analises_quebradas -= 1
                # o defeito no meio faz o leitor achar só um risco solto, sem a lista "riscos"
                return self._resp('[INÍCIO DO JSON]{"situacao": ["O "Pregão" 002/2024"], "riscos": [{"id": "R1", '
                                  '"titulo": "Solto", "fatos": []}, ]}[FIM DO JSON]')
            if "não é um JSON válido" not in ultimo:
                self.material_riscos = ultimo
            return self._resp("[INÍCIO DO JSON]" + json.dumps(self.analise_riscos) + "[FIM DO JSON]")
        if "Você vota, item a item" in contexto:
            papel = re.search(r"VOCÊ É: ([^.]+)\.", contexto).group(1)
            with self.trava:
                self.votantes = getattr(self, "votantes", []) + [papel]
            if papel in self.agentes_que_falham:
                raise RuntimeError("agente fora do ar")
            ids = re.findall(r'"id": "(R\d+)"', ultimo)
            votos = [{"risco": i, "impacto": "Alto" if i == "R1" else "Médio", "por_que_impacto": "serviço para (F1)",
                      "janela": "Primeiras 72 horas", "por_que_janela": "vence na posse",
                      "sensibilidade": ("Alta" if i == "R1" and not papel.startswith("Fazenda") else
                                        "Baixa" if i == "R1" else "Média"),
                      "por_que_sensibilidade": "TCE apontou (F4)" if i == "R1" else "gestão interna",
                      "fatos": ["F1"]} for i in ids]
            return self._resp("[INÍCIO DO JSON]" + json.dumps({"votos": votos}) + "[FIM DO JSON]")
        if "Você é o ADVOGADO DO DIABO" in contexto:
            with self.trava:
                self.agentes_vistos = getattr(self, "agentes_vistos", []) + ["Advogado do diabo"]
            if "Advogado do diabo" in self.agentes_que_falham:
                raise RuntimeError("agente fora do ar")
            return self._resp("[INÍCIO DO JSON]" + json.dumps({
                "contestados": [{"risco": "R2", "motivo": "o risco inventado não tem fato no material", "fatos": ["F1"]}],
                "sustentados": ["R1"], "faltam": self.faltam_do_contra,
                "decisoes": [{"decisao": "Q1", "opcao": 1, "teme": "licitar sem caixa", "valoriza": ""}]}) + "[FIM DO JSON]")
        if "Você revisa a análise de riscos" in contexto:
            papel = re.search(r"VOCÊ É: ([^.]+)\.", contexto).group(1)
            with self.trava:
                self.agentes_vistos = getattr(self, "agentes_vistos", []) + [papel]
            if papel in self.agentes_que_falham:
                raise RuntimeError("agente fora do ar")
            return self._resp("[INÍCIO DO JSON]" + json.dumps(self.revisao_agente) + "[FIM DO JSON]")
        if "Você confere, risco a risco" in sistema:
            self.pedido_conferencia = ultimo
            return self._resp("[INÍCIO DO JSON]" + json.dumps(self.conferencia_final) + "[FIM DO JSON]")
        if "Você consolida a análise de riscos" in sistema:
            self.pedido_consolidacao = ultimo
            final = self.consolidacao_riscos or dict(
                self.analise_riscos,
                riscos=[dict(r) for r in self.analise_riscos["riscos"]],          # sem id_anterior: casa pelo título
                decisoes=[dict(q, visoes=[{"papel": "Fazenda e orçamento", "teme": "custo", "valoriza": "rapidez"}])
                          for q in self.analise_riscos["decisoes"]])
            return self._resp("[INÍCIO DO JSON]" + json.dumps(final) + "[FIM DO JSON]")
        if "TEMAS TRANSVERSAIS" in sistema:
            self.pedido_temas = ultimo
            return self._resp("[INÍCIO DO JSON]" + json.dumps(self.temas) + "[FIM DO JSON]")
        if "Você revisa o TEXTO de um relatório" in sistema:
            if self.revisao_texto is None:
                return self._resp("sem JSON")
            return self._resp("[INÍCIO DO JSON]" + json.dumps(self.revisao_texto) + "[FIM DO JSON]")
        if "revisor de neutralidade" in sistema:
            if self.falhar_neutralidade:
                raise RuntimeError("serviço indisponível")
            return self._resp(nome=nome, args=self.neutralidade, motivo="tool_calls") if nome else self._resp(json.dumps(self.neutralidade))
        return self._resp("ok")


class ArquivoFalso:
    name = "relatorio_exemplo.pdf"

    def __init__(self, texto=RELATORIO):
        self.texto = texto

    def getvalue(self):
        # o conteúdo muda quando o relatório muda, como num arquivo de verdade
        return b"%PDF falso " + self.texto.encode("utf-8")


@pytest.fixture
def llm(monkeypatch):
    """Instala o LiteLLM e o MarkItDown falsos e devolve o modelo falso para o teste configurar."""
    falso = LLMFalso()
    litellm = types.ModuleType("litellm")
    litellm.completion = falso
    markitdown = types.ModuleType("markitdown")

    class MarkItDown:
        def convert(self, caminho):
            return NS(text_content=falso.texto_relatorio)

    markitdown.MarkItDown = MarkItDown

    import urllib.error
    import urllib.request

    class Resposta:
        def __init__(self, texto):
            self.dados = texto.encode("utf-8")
            self.headers = {"Content-Type": "text/html; charset=utf-8"}

        def read(self, n=-1):
            return self.dados

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(pedido, timeout=None):
        url = getattr(pedido, "full_url", pedido)
        falso.paginas_abertas = getattr(falso, "paginas_abertas", []) + [url]
        if url not in falso.paginas:
            raise urllib.error.URLError("não encontrado")
        return Resposta(falso.paginas[url])

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setitem(sys.modules, "litellm", litellm)
    monkeypatch.setitem(sys.modules, "markitdown", markitdown)
    if str(RAIZ) not in sys.path:
        sys.path.insert(0, str(RAIZ))
    from transicao import analise, entrada, modelo, pesquisa
    # páginas pelo urlopen falso acima e nomes resolvidos sem DNS (os testes não acessam a rede)
    falso.dns = {}
    monkeypatch.setattr(pesquisa, "_abrir", lambda pedido, timeout=None: urllib.request.urlopen(pedido, timeout=timeout))
    monkeypatch.setattr(pesquisa, "_resolver", lambda host: falso.dns.get(host, {"200.144.0.10"}))
    modelo._GUARDADOS.clear()            # respostas guardadas de um teste não vazam para o próximo
    entrada.converter_arquivo.cache_clear()
    modelo.usar_completion(None)
    analise.JUNTAS = False
    return falso


MODULOS = ["config", "modelo", "entrada", "folha", "pesquisa", "verificacao", "confronto", "produtos", "checklist", "riscos", "documentos",
           "revisao", "painel", "secao3", "caderno", "analise"]


@pytest.fixture(autouse=True)
def _registros_temporarios(tmp_path, monkeypatch):
    """Nada de teste grava em registros/ do repositório (inclusive a pesquisa do Estado guardada do dia)."""
    monkeypatch.setenv("PASTA_REGISTROS", str(tmp_path / "registros"))
    monkeypatch.setenv("ESTADO_EMBUTIDO", "0")       # os testes exercitam a pesquisa; o embutido tem teste próprio
    monkeypatch.setenv("TCE_DESLIGADO", "1")         # sem rede nos testes; o cruzamento com o TCE-RJ tem teste próprio


@pytest.fixture
def funcoes(llm):
    """Todas as funções do pacote transicao num só lugar (os nomes não se repetem entre os módulos)."""
    import importlib
    nomes = {}
    for m in MODULOS:
        mod = importlib.import_module(f"transicao.{m}")
        nomes.update({k: v for k, v in vars(mod).items() if not k.startswith("__")})
    return NS(**nomes)

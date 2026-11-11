# Análise da Transição

Aplicação em Streamlit que apoia a equipe de transição do governo do Estado do Rio de Janeiro. Para cada secretaria,
ela monta um diagnóstico a partir do dossiê de fontes públicas e dos documentos enviados, identifica riscos e decisões
urgentes, submete a análise a cinco agentes independentes com olhares de gestão diferentes e entrega um documento
curto, um calendário e os dados do painel. **Não decide, não recomenda, não sugere caminho nem responsável**:
analisa riscos e pontos de decisão, com as fontes conferidas por código.

## O que sai

Na barra lateral, escolha os produtos: juntos ou separados. Cada um roda só as etapas de que precisa:

| Produto marcado | O que roda |
|---|---|
| Calendário | só a extração das datas que a secretaria informou (rápido e barato) |
| Caderno executivo | a leitura do material, a LOA, a PLOA, o plano e as datas; usa os riscos só se o relatório de riscos ou o painel também estiverem marcados |
| Dossiê | o dossiê de fontes e as extrações (diagnóstico, checklist, confronto, contratos), sem a análise de riscos |
| Relatório de riscos ou Painel | o caminho completo, com a análise de riscos revisada e votada pelos seis agentes |

Os modelos (Claude Opus 5.5 em todas as etapas) e o cabeçalho dos documentos (Equipe de Transição) são fixos.

Um `.zip` com os produtos pedidos:

| Arquivo | O que é |
|---|---|
| `paineis/<sigla>_painel.json` | **1. Dados do painel, por secretaria:** os pontos de decisão com janela (antes da posse, 72 horas, 100 dias, depois), prazo, prioridade e repercussão política votada pelos seis agentes, na mesma régua para todas; prontos para o painel unificado. O painel em Word por secretaria saiu: repetia a tabela do relatório de riscos |
| `dossies/<secretaria>_dossie.docx` | **2. Dossiê: como a secretaria funciona hoje**: abertura curta, em duas notas (o que é e como ler a origem de cada informação, com o material lido em parte); panorama e ficha rápida; 1. O que faz; 2. Como se organiza (organograma em árvore e as unidades orçamentárias do órgão); 3. Programas e ações; 4. Principais contratos (tabela com os nomes por inteiro e, depois, o que destaca cada um); 5. Pessoal (Caderno de RH); 6. Orçamento (por código, das leis embutidas: LOA 2026 e PLOA 2027 de cada unidade orçamentária, com a variação, quanto é gestão administrativa e quanto é finalístico e as maiores ações de cada unidade; depois, a execução informada); 7. Pendências com controle e justiça; 8. Sistemas, convênios e parcerias; 9. Plano de governo 2027–2030 (os compromissos que tratam da área da secretaria e, para cada um, o que os fatos do material e o orçamento trazem hoje; a IA classifica e o código confere que o compromisso e a citação estão no plano e que o fato e a ação apontados existem); anexo só com as fontes que o corpo usa. O que a secretaria informou vem sem marca; o resto traz "fonte oficial ✔". Notícia conferida na página só entra no capítulo 7, com a marca "imprensa ✔". O código tira do "não se sabe" o que as bases embutidas trazem (PLOA, LOA, ato de criação, folha), não repete na ficha o número que já vem de base oficial e, quando as categorias de pessoal listadas pela secretaria não fecham com o Caderno de RH, mostra as duas contas. Descritivo: os riscos ficam no relatório de riscos; o confronto e a cobertura dos temas, na auditoria |
| `riscos/<secretaria>_riscos.docx` | **3. Relatório de riscos**, direto ao ponto e sem anexo: abertura em três linhas (o que é, confiança, como ler); os riscos **agrupados pela janela de decisão** (prazo vencido, antes da posse, primeiras 72 horas, primeiros 100 dias, depois), em ordem de prazo dentro de cada janela. Cada risco diz **do que se trata**: o que é (instrumento, número, a outra parte), o valor, em que pé está e, escritos por código, os contratos e prazos do calendário da secretaria que ele cita (data, objeto, valor); depois o problema, a consequência, o ponto de decisão, o prazo, o processo, a repercussão possível, o ponto contestado e as fontes por extenso. Além de contratos que vencem, cobre programas em fase crítica, concessões e PPPs, decisões pendentes em tribunal, acordos com órgãos de controle, recursos federais com marco, obras, eventos, pessoal e atos pendentes. Depois, o **cruzamento com o TCE-RJ** (multas e débitos em processos da secretaria e das vinculadas, com a marca de citado ou não no material) e a **pauta de investigação**: até 15 informações que faltam, com para que servem, onde procurar, o risco a que servem e quem apontou (a análise, cada um dos seis agentes, o checklist obrigatório ou o cruzamento com o TCE-RJ). A janela vem da data do documento (prazo já passado aparece como vencido); sem data, do voto dos agentes, e o texto diz. Contestação já acatada e corrigida não aparece: só o que continua em disputa, com a resposta. Tom de análise: sem recomendação, sem caminho sugerido, sem responsável, repercussão sempre no condicional |
| `auditoria/<secretaria>.json` | **5. Auditoria**: o registro completo de cada análise: dossiê e conferências, análise inicial, revisões e votos dos seis agentes, consolidação, objeções risco a risco, método, descartes, custo |
| `calendarios/<sigla>_calendario.xlsx` | **4. Calendário, por secretaria:** os vencimentos com filtro em todas as colunas; as três primeiras são para filtrar: secretaria (sigla), janela (antes da posse, 72 horas, 100 dias, depois) e mês. A aba Prioridades vem primeiro. Só as datas que a secretaria informou |
| `cadernos/<sigla>_caderno.docx` e `_quadro.csv` | **Caderno executivo** (opcional): o que a secretaria entrega, para quem, com quanto e em que pé está. Página-resumo; quadro-síntese por ação orçamentária (LOA 2026 e PLOA 2027), com os programas sob cada ação e o total conferido com o finalístico da LOA; uma ficha por programa (14 campos, cada valor com a fonte); notas de fonte e lacunas. Fonte: a seção 3 do Relatório de Transição (modelo v2) em PDF, lida por código; sem ele, os programas achados no material enviado, com cada campo copiado e conferido no arquivo; sem programas, só o orçamento. Seleção por código: riscos e painel, Plano de Governo, ações por orçamento até 80% do finalístico, teto de 12 fichas (editáveis na tela) |
| `resumo.csv` | Situação, números e custo de cada secretaria |

## Como usar

1. Suba os arquivos: os documentos soltos ou num `.zip` (Word, PDF, Excel, PowerPoint ou imagens; a sigla da
   secretaria no começo ou no fim do nome junta os arquivos dela numa secretaria só) ou o `.zip` da pasta com uma
   subpasta de documentos brutos por órgão. O que está em imagem (página digitalizada, slide salvo como figura, print
   de tabela, foto de documento) é transcrito pelo modelo e entra no material, se "Ler o que está em imagem" estiver
   marcado.
2. O **pacote de dossiês das secretarias** montado pela equipe já vem embutido no app (`dossies_embutidos/`, pacote de
   06/11/2026, 31 secretarias) e é usado sozinho: por sigla, o app pega `SIGLA_pesquisa.md` (pesquisa web com
   citações `[título](link)`); os nomes por extenso vêm de `00_CONSOLIDACAO_ESTADUAL.md`. As bases de contratos do
   SIGA e do PNCP (painel `SIGLA.md` e planilha `SIGLA_vencimentos_180d.csv`) não são usadas: trazem datas
   defasadas e foram tiradas do pacote; se vierem num pacote novo, são ignoradas. Para atualizar,
   troque o `.zip` da pasta (ou suba um pacote mais novo na tela: vale sobre o embutido para as secretarias que
   cobrir). Também aceita um arquivo por secretaria (Word, PDF ou Markdown) com fatos citados.
   A **folha de pessoal** de cada órgão (Caderno de RH da SEPLAG, `bases_embutidas/`) também entra sozinha, como
   dado oficial: vínculos ativos, folha do mês, efetivos e não efetivos (a parte da equipe que pode sair na troca
   de governo).
   Para quem tiver dossiê, o app não pesquisa a web sobre o órgão:
   - cada fato da pesquisa tem o link aberto pelo código, e os números da afirmação precisam estar na página;
   - contratos e calendário saem só do que a secretaria informou; fatos de contrato da pesquisa ficam no registro
     de auditoria, marcados, fora da análise.
   O contexto do Estado continua pesquisado pelo app, uma vez para todos.
3. Confira a tabela de órgãos (dá para corrigir nomes e desmarcar; a coluna Dossiê mostra qual arquivo casou).
4. Clique em **Analisar**. A análise roda em segundo plano; pode fechar a página.
5. Baixe o `.zip`.

Na barra lateral: modelos (inclusive um modelo por agente revisor, de provedores diferentes), modo econômico (Batch
API, metade do preço, mais lento), data de corte, foco e cabeçalho do documento.

**Se o app reiniciar no meio** (merge no GitHub, queda), a tela oferece **retomar**: cada secretaria concluída fica
gravada em `registros/` (fora do Git) e só o que faltou é analisado de novo. Um reinício durante a análise ainda
custa tempo: evite fazer merge com análise em andamento.
**Não envie documentos sigilosos** (licitações em curso, processos sob sigilo): o texto vai para a API da Anthropic
(e dos outros provedores, se escolher modelos deles para os agentes).

## Como rodar

```bash
pip install -r requirements.txt
streamlit run app.py
```

A chave fica num arquivo `.env` (fora do Git) ou nos Secrets do Streamlit Cloud: `ANTHROPIC_API_KEY=...`

**Defina também uma senha de acesso**, no mesmo lugar: `APP_SENHA=...`. A análise em andamento e o `.zip` ficam na
memória do app e valem para todas as abas; sem senha, quem tiver o link vê o andamento e baixa os documentos.

## Como funciona cada secretaria

1. **Dossiê.** O pacote de dossiês da equipe (ou, sem ele, a pesquisa do app). Links abertos e números conferidos por
   código. Contratos: só o que a secretaria informou.
   Por padrão, todas as etapas usam o modelo mais forte (Opus): qualidade primeiro; o modo econômico (Batch API)
   só muda o tempo, não o modelo.
2. **Dossiê (diagnóstico).** Responde "como essa secretaria funciona hoje?", em oito blocos fixos: o que faz; como
   se organiza (com o organograma, cada unidade conferida na origem e desenhada em árvore pelo código); programas e
   ações; contratos (só o que a secretaria informou); pessoal; orçamento e execução; pendências com controle e
   justiça; sistemas, convênios e parcerias. Mais o panorama e os números da ficha rápida. Primeiro o que a
   secretaria enviou; só sem isso, os documentos oficiais dos dossiês de base (a imprensa fica para os riscos e a
   contraprova). Cada afirmação cita o dossiê ou um trecho literal do
   relatório; o que não confere é retirado. Os fatos que pesam na transição entram sem juízo e servem à análise de
   riscos.
3. **Checklist obrigatório.** Dez temas básicos que toda secretaria precisa ter verificados (contratos a vencer, emergenciais,
   execução, restos a pagar, TCE-RJ, judicialização, convênios federais, obras, pessoal, sistemas críticos). Cada um
   sai com estado conferido por código: **encontrado** (com os fatos), **procurado e não encontrado** (a pesquisa
   registrou a busca, ou o órgão informou que não há) ou **sem informação**. O que ficou em branco aparece na primeira
   página do documento, entra no que pedir à secretaria e derruba a confiança: alta só sem nenhum ponto em branco.
   A pesquisa do app recebe os pontos como obrigatórios e registra os que não achou.
4. **Vencimentos.** Régua de risco por código: serviço essencial, impacto, data-limite para agir, tempo para nova
   licitação e prioridade (impacto × urgência).
5. **Análise de riscos.** Antes dela, o funil é alargado: (a) os **pontos críticos** que a secretaria informou (até
   20), de todos os tipos de questão urgente e não só contratos (concessão ou PPP em andamento, decisão pendente em
   tribunal, acordo com órgão de controle, auditoria em curso, recurso federal com marco, programa em fase crítica,
   obra, evento, contingência sazonal, pessoal, ato pendente, obrigação fiscal), cada um com o trecho literal
   conferido por código no material; (b) as **multas e débitos do TCE-RJ** (ver abaixo). A análise recebe os fatos
   com id (diagnóstico F, vencimentos V, dossiê O, pontos críticos P, TCE-RJ T) e, depois deles, **o material inteiro
   da secretaria**. Propõe de 5 a 10 riscos (causa → consequência), cada um identificado (o que é, valor, em que pé
   está, marco, processo), o ponto de decisão (descrito, sem caminhos) e as informações que faltam. Tudo que o risco
   afirma tem de estar num fato com id; o que só está no material completo vem como trecho literal, que o código
   confere e transforma em fato (o que não confere cai e fica no registro). Agentes e consolidação trabalham com os
   fatos com id.

   **Cruzamento com o TCE-RJ.** Por código, sem modelo, a partir dos dados abertos do Tribunal
   (https://dados.tcerj.tc.br/api/v1/docs), baixados uma vez por dia. Só entram **decisões do próprio Tribunal**:
   multas e débitos, com processo, sessão e número da condenação. Os outros conjuntos do portal (obras paralisadas,
   contratos, convênios, dotação) são declarados pelos órgãos e ficam de fora. O app acha a secretaria, as antecessoras
   extintas e as vinculadas pelo nome que o TCE usa (tabela conferida em `bases_embutidas/siglas_2026.json` e nomes da
   LOA) e diz, de cada processo, se o número aparece no material enviado. O que o TCE tem e a secretaria não citou
   abre a pauta de investigação. Nome antigo de secretaria entra pela tabela de antecessoras confirmadas pela
   equipe (a antiga com duas sucessoras aparece nas duas, com o nome antigo); sem confirmação, não entra na contagem
   e o relatório diz que ficou de fora, com os processos. **Valores não entram**: a base não informa a unidade (R$ ou UFIR-RJ) e repete a mesma
   condenação em uma linha por responsável; o app conta condenações e processos, e o valor fica, como publicado, só no
   registro de auditoria. Sem acesso ao portal, o relatório diz que o cruzamento não foi feito. `TCE_DESLIGADO=1` nos
   Secrets desliga.
6. **Seis agentes independentes** revisam a análise sem ver uns aos outros: Fazenda e orçamento; controle e jurídico;
   área-fim e usuário do serviço; operação e servidores; nova gestão (prioridades e articulação); e o **advogado do
   diabo**, que tenta derrubar cada risco com o material. Apontam riscos que faltaram, riscos exagerados ou
   contestados, e cada um aponta, pelo seu olhar, as informações que faltam para fechar os riscos (a pauta de
   investigação). O código registra, para cada risco final, quem apontou e quem fez objeção, e, para cada informação
   que falta, quem a apontou. No relatório só aparece a objeção que continua em disputa depois da consolidação.
   Depois da votação, uma **conferência final** lê cada risco ao lado do texto dos fatos que ele cita: o que não tem
   apoio é corrigido (a correção só entra sem número novo e sem palavra de recomendação) ou fica marcado "a confirmar".

   **Esquema de modelos.** Quem produz não confere, e quem confere não é da mesma família de quem produziu. Com as
   chaves de outras famílias nos Secrets (`OPENAI_API_KEY`, `GEMINI_API_KEY`, `DEEPSEEK_API_KEY`, qualquer
   combinação), os agentes se repartem: o advogado do diabo e o controle jurídico vão para fora primeiro, e a
   Anthropic, que escreveu a análise, nunca tem maioria (com uma família de fora, 3 a 3; com duas, fica com um
   agente). A revisão de neutralidade vai para outra família. Sem nenhuma chave, tudo roda na Anthropic e a barra
   lateral avisa. A lista de modelos na barra lateral vale sobre o esquema. O modelo de cada família pode ser
   trocado nos Secrets (`GEMINI_MODELO = "gemini/gemini-3.8-flash"` fica na cota gratuita do Google, por exemplo).
7. **Consolidação e conferência.** Uma consolidação junta as revisões; o código confere os fatos citados por cada
   risco, dá a firmeza da informação e calcula a prioridade. Um segundo modelo revisa a neutralidade.
8. **Votação item a item.** Depois da consolidação, os seis agentes votam, em cada risco, sem ver uns aos outros:
   **impacto** (alto, médio, baixo), **janela** (antes da posse, primeiras 72 horas, primeiros 100 dias, depois) e
   **repercussão política** (alta, média, baixa, dizendo quem reage e como). O código apura: maioria, com empate indo
   para o nível mais grave (janela: o mais urgente); data que está no documento prevalece sobre o voto de janela; a
   divergência entre agentes fica registrada e aparece no relatório.
9. **Revisão do texto.** Antes de montar os documentos: a revisão de neutralidade (outro modelo) aponta trechos que
   recomendam; a revisão do texto (IA) reescreve cada campo no tom de análise; o código só aceita a reescrita que
   mantém todos os números, datas e referências e não traz palavra de recomendação ("deve", "é preciso", "cabe
   a"...). O que sobrar fica marcado na auditoria e no resumo.
10. **Documento.** Montado por código, sempre na mesma estrutura, sem cortar frase no meio.

## Código

```
app.py                 a tela (só interface)
transicao/
  config.py            modelos, preços e limites
  modelo.py            chamada aos modelos, cache, validação, custo
  entrada.py           leitura dos arquivos enviados (resumos ou pastas)
  pesquisa.py          dossiê e conferência dos links
  confronto.py         confronto entre o que a secretaria informou e as fontes
  riscos.py            análise de riscos, cinco agentes, consolidação, prioridade e neutralidade
  painel.py            painel estadual
  produtos.py          calendário, régua de risco dos vencimentos e diagnóstico
  checklist.py         checklist obrigatório: o estado de cada ponto (encontrado, procurado, não procurado)
  verificacao.py       conferência dos números do documento
  documentos.py        Word e Excel
  lote_api.py          modo econômico (Batch API)
  analise.py           o fluxo de um órgão e de vários; retomada do disco
tests/                 testes com um modelo falso: não chamam nenhuma API
```

Testes: `pip install -r requirements-dev.txt && pytest -q tests`

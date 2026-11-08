# Análise da Transição

Aplicação em Streamlit que apoia a equipe de transição do governo do Estado do Rio de Janeiro. Para cada secretaria,
ela monta um diagnóstico a partir do dossiê de fontes públicas e dos documentos enviados, identifica riscos e decisões
urgentes, submete a análise a cinco agentes independentes com olhares de gestão diferentes e entrega um documento
curto. No fim, um painel estadual consolida as urgências. **Não decide e não recomenda**: expõe riscos e escolhas, com
as fontes conferidas por código.

## O que sai

Um `.zip` com:

| Arquivo | O que é |
|---|---|
| `painel_estadual.docx` | **1. Painel estadual:** todas as decisões de todas as secretarias com prazo antes da posse, nas primeiras 72 horas e nos primeiros 100 dias, e todas as de repercussão política alta. Em ordem de prazo; cada linha com a decisão a tomar, quem decide, a repercussão política votada pelos seis agentes (e quem reage), a prioridade e a base |
| `dossies/<secretaria>_dossie.docx` | **2. Dossiê da secretaria, atualizado com o que ela informou**: em resumo (situação, números-chave, lacunas); 1. Contratos (tabela dos contratos críticos); 2. Pessoal; 3. Passivos jurídicos e de controle; 4. Orçamento, obras e estrutura; 5. O que a secretaria informou e o que as fontes mostram; 6. Cobertura do checklist; anexo de fontes citadas e prazos que não são contratos |
| `riscos/<secretaria>_riscos.docx` | **3. Relatório de riscos**, até 3 páginas e sem anexo: situação; as decisões urgentes em ordem de prazo, com janela, impacto e repercussão política votados item a item pelos seis agentes (contagem dos votos e divergências), prioridade e base; decisões em aberto com opções de mesmo peso; o que pedir à secretaria |
| `auditoria/<secretaria>.json` | **5. Auditoria**: o registro completo de cada análise: dossiê e conferências, análise inicial, revisões e votos dos seis agentes, consolidação, objeções risco a risco, método, descartes, custo |
| `calendario_consolidado.xlsx` | **4. Calendário:** os vencimentos de todas as secretarias, com filtro em todas as colunas; as três primeiras são para filtrar: secretaria (sigla), janela (antes da posse, 72 horas, 100 dias, depois) e mês. A aba Prioridades vem primeiro |
| `resumo.csv` | Situação, números e custo de cada secretaria |

## Como usar

1. Suba os arquivos: o `.zip` com os documentos (Word, PDF ou Excel; o nome ou a sigla da secretaria no nome do arquivo; arquivos com o mesmo nome são juntados) ou o
   `.zip` da pasta com uma subpasta de documentos brutos por órgão.
2. O **pacote de dossiês das secretarias** montado pela equipe já vem embutido no app (`dossies_embutidos/`, pacote de
   06/11/2026, 31 secretarias) e é usado sozinho: por sigla, o app pega `SIGLA_pesquisa.md` (pesquisa web com
   citações `[título](link)`), `SIGLA.md` (painel de contratos do SIGA/PNCP) e `SIGLA_vencimentos_180d.csv`
   (contratos que vencem em 180 dias); os nomes por extenso vêm de `00_CONSOLIDACAO_ESTADUAL.md`. Para atualizar,
   troque o `.zip` da pasta (ou suba um pacote mais novo na tela: vale sobre o embutido para as secretarias que
   cobrir). Também aceita um arquivo por secretaria (Word, PDF ou Markdown) com fatos citados.
   A **folha de pessoal** de cada órgão (Caderno de RH da SEPLAG, `bases_embutidas/`) também entra sozinha, como
   dado oficial: vínculos ativos, folha do mês, efetivos e não efetivos (a parte da equipe que pode sair na troca
   de governo).
   Para quem tiver dossiê, o app não pesquisa a web sobre o órgão:
   - cada fato da pesquisa tem o link aberto pelo código, e os números da afirmação precisam estar na página;
   - os números do SIGA/PNCP entram como dado oficial conferido pela equipe;
   - os vencimentos da planilha vão direto para o calendário, sem passar pelo modelo.
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
   código; contratos do SIGA/PNCP entram como dado oficial.
   Por padrão, todas as etapas usam o modelo mais forte (Opus): qualidade primeiro; o modo econômico (Batch API)
   só muda o tempo, não o modelo.
2. **Diagnóstico.** Seis blocos fixos, na ordem do que mais pesa na transição: contratos (valores altos, objetos
   questionáveis, vigência acabando, paralisados, passivo); pessoal (tamanho e custo da folha, folha inchada, cargos
   que vagam, risco de apagão de equipe); passivos jurídicos e de controle; orçamento e execução; obras e entregas;
   estrutura e dirigentes. Mais os números-chave do resumo executivo e a **tabela de contratos críticos** (da
   planilha do SIGA/PNCP, por código, e os apontados no material). Cada afirmação, número e contrato cita o dossiê
   ou um trecho literal do relatório da secretaria; o que não confere é retirado.
3. **Checklist obrigatório.** Dez pontos que toda secretaria precisa responder (contratos a vencer, emergenciais,
   execução, restos a pagar, TCE-RJ, judicialização, convênios federais, obras, pessoal, sistemas críticos). Cada um
   sai com estado conferido por código: **encontrado** (com os fatos), **procurado e não encontrado** (a pesquisa
   registrou a busca, ou o órgão informou que não há) ou **não procurado**. O que ficou em branco aparece na primeira
   página do documento, entra no que pedir à secretaria e derruba a confiança: alta só sem nenhum ponto em branco.
   A pesquisa do app recebe os pontos como obrigatórios e registra os que não achou.
4. **Vencimentos.** Régua de risco por código: serviço essencial, impacto, data-limite para agir, tempo para nova
   licitação, aditivo recente no PNCP e prioridade (impacto × urgência).
5. **Análise de riscos.** Uma análise lê o diagnóstico e os vencimentos e propõe riscos (causa → consequência),
   decisões em aberto e o que pedir à secretaria.
6. **Seis agentes independentes** revisam a análise sem ver uns aos outros: Fazenda e orçamento; controle e jurídico;
   área-fim e usuário do serviço; operação e servidores; nova gestão (prioridades e articulação); e o **advogado do
   diabo**, que tenta derrubar cada risco com o material. Apontam riscos que faltaram, riscos exagerados ou
   contestados e o que temem e valorizam em cada opção. O código registra, para cada risco final, quem apontou e
   quem fez objeção ("5 de 6 agentes sem objeção; advogado do diabo contesta: ..."), e isso aparece no documento.

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
9. **Documento e painel.** O documento é montado por código, sempre na mesma estrutura. O painel estadual junta os
   riscos de todas as secretarias; o modelo só aponta os temas que se repetem.

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

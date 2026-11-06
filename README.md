# Análise da Transição

Aplicação em Streamlit que apoia a equipe de transição do governo do Estado do Rio de Janeiro. Para cada órgão, ela
pesquisa fontes públicas, confronta o que o órgão informou, simula um debate entre papéis institucionais e escreve
um documento para quem decide. **Não decide e não recomenda**: expõe as escolhas, com as fontes conferidas por código.

## O que sai

Um `.zip` com:

| Arquivo | O que é |
|---|---|
| `documentos/<órgão>.docx` | **Um Word por órgão**: as decisões a tomar (memorando executivo), o diagnóstico do órgão com os próximos vencimentos e, nos anexos, as fontes consultadas, o debate em detalhe e como o documento foi feito |
| `calendario_consolidado.xlsx` | As datas críticas de todos os órgãos numa planilha, só com datas conferidas na fonte |
| `resumo.csv` | Situação, números e custo de cada órgão |
| `auditoria/` | O registro completo de cada análise e os arquivos lidos, para conferência técnica |

## Como usar

1. Suba os arquivos: o `.zip` com os resumos (um Word ou PDF por órgão, o nome do órgão no nome do arquivo) ou o
   `.zip` da pasta com uma subpasta de documentos brutos por órgão.
2. Opcional: suba o **pacote de dossiês das secretarias** (.zip) montado pela equipe. Por sigla, o app usa
   `SIGLA_pesquisa.md` (pesquisa web com citações `[título](link)`), `SIGLA.md` (painel de contratos do SIGA/PNCP) e
   `SIGLA_vencimentos_180d.csv` (contratos que vencem em 180 dias); os nomes por extenso vêm de
   `00_CONSOLIDACAO_ESTADUAL.md`. Também aceita um arquivo por secretaria (Word, PDF ou Markdown) com fatos citados.
   Para quem tiver dossiê, o app não pesquisa a web sobre o órgão:
   - cada fato da pesquisa tem o link aberto pelo código, e os números da afirmação precisam estar na página;
   - os números do SIGA/PNCP entram como dado oficial conferido pela equipe;
   - os vencimentos da planilha vão direto para o calendário, sem passar pelo modelo.
   O contexto do Estado continua pesquisado pelo app, uma vez para todos.
3. Confira a tabela de órgãos (dá para corrigir nomes e desmarcar; a coluna Dossiê mostra qual arquivo casou).
4. Clique em **Analisar**. A análise roda em segundo plano; pode fechar a página.
5. Baixe o `.zip`.

Na barra lateral: modelos, rodadas do debate, modo econômico (Batch API, metade do preço, mais lento), data de corte,
foco e cabeçalho do documento.

**Não reinicie o app nem faça merge no GitHub com uma análise em andamento**: o Streamlit reinicia e a análise se perde.
**Não envie documentos sigilosos** (licitações em curso, processos sob sigilo): o texto vai para a API da Anthropic.

## Como rodar

```bash
pip install -r requirements.txt
streamlit run app.py
```

A chave fica num arquivo `.env` (fora do Git) ou nos Secrets do Streamlit Cloud: `ANTHROPIC_API_KEY=...`

## Como funciona cada órgão

1. **Dossiê.** Se a equipe enviou o dossiê do órgão, ele é usado no lugar da pesquisa. Senão, o modelo de pesquisa busca na web, em grupos paralelos, o contexto do Estado (pesquisado uma vez para
   todos) e o do órgão. O código abre cada link e procura o trecho citado; o tipo de fonte e a conferência limitam o
   nível de evidência de cada item. Sem itens suficientes, o órgão não é analisado.
2. **Insumos.** Problema central, papéis do debate, grupos sem voz e lacunas, montados só a partir do dossiê.
3. **Confronto, calendário e diagnóstico.** O relatório do órgão entra como autodeclaração: é comparado com o dossiê,
   e o código descarta o que não confere. Datas e afirmações do diagnóstico só ficam se o trecho citado estiver na fonte.
4. **Debate.** Até 5 rodadas independentes (padrão 3, parando na 2ª se as duas concordarem). Só ganham destaque os
   dilemas que se repetem; uma consolidação junta as rodadas.
5. **Verificação por código.** Fontes, níveis de evidência, números do memorando e confiança da análise são
   conferidos ou calculados pelo código; um segundo modelo revisa a neutralidade.
6. **Documento.** Memorando em linguagem direta, diagnóstico, vencimentos e anexos num só Word.

## Código

```
app.py                 a tela (só interface)
transicao/
  config.py            modelos, preços e limites
  modelo.py            chamada aos modelos, cache, validação, custo
  entrada.py           leitura dos arquivos enviados (resumos ou pastas)
  pesquisa.py          dossiê e conferência dos links
  debate.py            prompts, insumos, confronto, rodadas e neutralidade
  produtos.py          calendário e diagnóstico
  verificacao.py       evidências, números e confiança
  documentos.py        Word e Excel
  lote_api.py          modo econômico (Batch API)
  analise.py           o fluxo de um órgão e de vários
tests/                 testes com um modelo falso: não chamam nenhuma API
```

Testes: `pip install -r requirements-dev.txt && pytest -q tests`

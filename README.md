# Painel do Mapa de Tensões da Transição

Aplicação em Streamlit que apoia a transição de governo do Estado do Rio de Janeiro. Para cada órgão, um conselho de
papéis institucionais simulado por modelos de linguagem expõe trade-offs, conflitos e riscos. O painel **não decide
e não recomenda**: entrega um mapa de tensões (Tension Map), um memorando executivo com matriz de risco e uma
verificação automática do que foi citado.

A partir da versão 2.0, o painel faz uma coisa só: o mapa de tensões. A base factual é um **dossiê de fontes
independentes** sobre o Estado e o órgão. O relatório que o órgão envia entra como **autodeclaração**: é confrontado
com o dossiê e não preenche nenhum campo do debate. O diagnóstico de lacunas e a minuta de ofício saíram do painel
(veja "Código retirado", abaixo).

## Como rodar

```bash
pip install -r requirements.txt
streamlit run app.py
```

As chaves das APIs ficam num arquivo `.env` na raiz do projeto, que **não** vai para o GitHub (está no `.gitignore`).
No Streamlit Cloud, ficam nos Secrets:

```
ANTHROPIC_API_KEY=...
GEMINI_API_KEY=...
```

## Como funciona uma análise

1. **Pesquisa (dossiê).** Você informa o órgão, um foco opcional e a data de corte. O modelo da pesquisa busca na web,
   em duas camadas em paralelo:
   - **Estado:** situação fiscal, regime da dívida (Propag), previdência, calendário legal (LOA, emendas, LRF),
     cenário político e compromissos do governo eleito;
   - **Órgão:** mandato e estrutura, orçamento e execução, pessoal, contratos e convênios, entregas e indicadores,
     controle e judicialização, riscos de continuidade.

   Cada item traz afirmação, fonte, data, link, trecho literal, tipo de fonte (documento oficial, dado oficial,
   decisão de controle ou judicial, estudo, imprensa, declaração política, hipótese) e confiança. Promessa de governo
   é sempre declaração política, nunca fato. O dossiê também registra o que foi **procurado e não encontrado**.
2. **Conferência por código.** O painel abre cada link e procura o trecho citado: conferido, trecho não encontrado,
   página inacessível ou sem trecho. O tipo de fonte e a conferência definem o **nível máximo** de evidência que o
   item sustenta (fonte oficial conferida: nível 1; estudo conferido: 2; imprensa, declaração ou item não conferido:
   3; hipótese: 4).
3. **Revisão do dossiê.** O dossiê aparece numa tabela editável: dá para corrigir, excluir, acrescentar linhas e
   marcar "Conferido pela equipe" quando alguém confirmar a fonte (por exemplo, um PDF que o código não abriu). Dá
   também para baixar o dossiê em JSON e carregar um dossiê pronto, montado fora do painel; os links são conferidos
   de novo.
4. **Insumos.** O modelo auxiliar monta, **só a partir do dossiê**, o problema central, as personas (papéis, nunca
   nomes de pessoas, incluindo quem pode vetar, quem paga, quem sofre os efeitos e quem defende o status quo ou a
   mudança gradual), os grupos afetados sem voz no debate e as lacunas. Tudo é editável.
5. **Relatório do órgão (opcional).** Antes do debate, o modelo auxiliar confronta o relatório com o dossiê. O código
   descarta o que não confere. Ficam dois tipos de divergência: o órgão declara algo diferente das fontes, ou não
   menciona um assunto que as fontes trazem. O painel não atribui intenção.
6. **Debate (Fases 1 a 4).** O modelo do debate roda o protocolo em 1 a 5 rodadas independentes (padrão: 3) ou no
   modo de personas independentes. O dossiê e a autodeclaração vão no começo da mensagem, em cache. Com mais de uma
   rodada, só entram no memorando os trade-offs que aparecem na maioria das rodadas; os demais ficam como sinais fracos.
7. **Memorando (Fase 5).** Abre com o quadro "Sobre este documento", escrito por código: material gerado com IA a
   partir de papéis simulados, tamanho e conferência do dossiê, data de corte e confiança calculada. Depois: síntese,
   os três principais trade-offs (com o critério de escolha), perguntas que o decisor precisa responder e quem tem
   competência hoje, o que o órgão declarou e o que as fontes mostram, dados que faltam, custo de não decidir, custo
   de decidir errado e matriz de risco. Sai em Word com cabeçalho institucional.
8. **Verificação, feita por código e não pelo modelo:**
   - fonte de item do dossiê: o id precisa existir e o trecho precisa estar no item; o nível não passa do nível
     máximo do item;
   - fonte da autodeclaração: o trecho precisa estar no relatório; sem confirmação no dossiê, vale no máximo nível 4;
   - cálculo: o dado de partida precisa estar no dossiê ou no relatório; vale no máximo nível 2;
   - fonte não encontrada derruba o argumento para nível 5;
   - valores em R$, percentuais e datas do memorando são conferidos no dossiê e no relatório;
   - citações de lei vão para uma lista de revisão da assessoria jurídica; dúvidas jurídicas que a norma responde
     saem do mapa e aparecem à parte, para a PGE;
   - a confiança da análise é calculada a partir da conferência do dossiê, das fontes rebaixadas, do peso da
     autodeclaração e da estabilidade; a completude do relatório é só informada;
   - um modelo diferente do que escreveu o memorando revisa a **neutralidade**.
9. **Registro.** Cada análise é gravada em `registros/`, com modelos, versão do prompt, dossiê, confronto, insumos,
   verificação, tokens, buscas e custo. Use o botão **Registro (.json)** para baixar e guardar a trilha de cada análise.

## Regras do método

- O dossiê é a única base factual. Nenhum argumento passa do nível máximo do item que o sustenta.
- O relatório do órgão nunca é a única base de um polo.
- Simetria: o baseline registra o custo de esperar e o risco de agir errado; caso histórico contra a inércia pede um
  caso em que agir da forma proposta deu errado.
- Personas são papéis institucionais, nunca pessoas reais.
- Nunca fabricar dissenso: convergência legítima é registrada como convergência.

## Modo "Personas independentes"

No modo rápido, um único modelo simula todas as personas numa chamada, e as rodadas medem se ele é consistente.
No modo **Personas independentes**, o debate acontece de verdade:

1. **Fase 1:** cada persona propõe o seu plano numa chamada própria.
2. **Fase 2:** cada persona recebe os planos das outras e os critica.
3. **Fase 2.5:** cada persona recebe as críticas que sofreu e decide revisar, defender ou manter o plano.
4. **Fase 3:** um modelo de outra família (Gemini, por padrão) dá notas aos planos finais sem saber quem os
   propôs, com o dossiê à mão para julgar a ancoragem. O código embaralha os planos e retira deles os nomes e ids das
   personas.
5. **Fase 4:** o modelo do debate extrai o Tension Map do histórico real. O código confere se cada polo foi
   defendido por uma persona que de fato participou.

O histórico completo aparece na aba **Debate** e vai para o registro. Personas que não respondem ficam de fora,
com aviso; com menos de 3, o debate não acontece. Os modelos Gemini usam a `GEMINI_API_KEY` dos Secrets.

Com o Sonnet 5.5 nas personas e o Opus 5.5 na síntese e no memorando, o debate custa cerca de US$ 0,60, sem a
pesquisa. O custo exibido no painel não inclui o Gemini, que ainda não tem preço cadastrado (aparece marcado com *).

## Comparar com uma análise anterior

Suba na barra lateral o **registro (.json) de uma análise anterior**. O painel compara os trade-offs (pareados pelo
mecanismo causal por um modelo barato e conferidos por código), a matriz de risco, a confiança e, se houver relatório
do órgão nas duas análises, as seções do relatório e os valores em R$ que mudaram.

## Economia de tokens

- **Material em cache uma vez só.** As rodadas do debate e a síntese do modo independente usam o mesmo começo de
  mensagem (prompt de sistema comum, mesma ferramenta, o dossiê e o relatório). O material é gravado em cache por
  1 hora e as demais chamadas o leem por 5% do preço.
- **Parada antecipada das rodadas.** Com 3 ou mais rodadas, o painel roda as rodadas 1 e 2 e confere se chegaram aos
  mesmos trade-offs; se chegaram, as demais não rodam. Dá para desligar na barra lateral.
- **Pesquisa reaproveitada.** A mesma pesquisa (modelo, órgão, data de corte e foco) não é refeita enquanto o app não
  reinicia.

## Custo aproximado

- **Pesquisa:** cinco chamadas em paralelo, uma por grupo de blocos, com até 5 buscas cada. Se uma resposta parar
  antes do JSON (turno pausado pela API ou resposta cortada), o painel pede que o modelo termine; o motivo de cada
  chamada aparece em "Diagnóstico da pesquisa", no painel do dossiê. Com o Sonnet 5.5, a Anthropic cobra US$ 10 por mil
  buscas além dos tokens; o painel soma as buscas no custo. Uma pesquisa repetida com os mesmos insumos é
  reaproveitada sem nova busca enquanto o app não reinicia ("Pesquisar de novo do zero" força uma nova).
- **Debate e memorando:** com o Opus 5.5 no debate e 3 rodadas, cerca de US$ 0,50 a 0,60. O dossiê fica em cache por
  1 hora e as rodadas o leem por 5% do preço.

O valor real de cada análise aparece no painel e no registro.

## Testes

Os testes **não chamam nenhuma API**: o modelo é substituído por uma versão falsa, e o relatório usado é fictício
(`tests/fixtures/relatorio_exemplo.md`). Rodam de graça, no computador ou no GitHub Actions.

```bash
pip install -r requirements-dev.txt
pytest -q tests
```

O GitHub Actions roda os testes a cada push na `main` e a cada pull request (`.github/workflows/testes.yml`).

## Estrutura

| Arquivo | O que é |
|---|---|
| `app.py` | O painel (Streamlit) |
| `tests/` | Testes automáticos e relatório fictício |
| `requirements.txt` | Dependências para rodar o painel |
| `requirements-dev.txt` | Dependências para rodar os testes |
| `orquestrador.py`, `validador.py`, `prompts.py` | Versão anterior, em linha de comando, com auditoria cruzada por modelos Gemini. Não é usada pelo `app.py`. |
| `lote.py` | Processamento em lote a partir do Google Drive (usa as funções do `app.py`). |
| `.github/workflows/lote.yml` | Workflow manual que roda o `lote.py` em paralelo e entrega o zip criptografado. |
| `requirements-lote.txt` | Dependências extras do lote (acesso ao Google Drive). |
| `extraido/lacunas_oficio/` | Diagnóstico de lacunas e minuta de ofício, retirados do painel na versão 2.0. Ponto de partida da ferramenta própria de triagem; não é usado pelo `app.py`. |

## Processamento em lote a partir do Drive

O `lote.py` lê a pasta DOCUMENTOS RECEBIDOS no Google Drive e roda, sem parar, a análise de cada secretaria e de cada
órgão vinculado: baixa os documentos, monta o dossiê, prepara os insumos, delibera e gera o memorando. Usa as mesmas
funções do painel. Roda no GitHub Actions, disparado à mão, e entrega um zip criptografado.

**Como as pastas são lidas**
- Cada pasta da raiz é uma secretaria. Subpasta que repete o nome ou a sigla da secretaria (ex.: "SEFAZ" dentro de
  "Secretaria de Fazenda - SEFAZ") é juntada a ela. As demais subpastas são órgãos vinculados, com análise própria.
- Lê PDF, Word, Excel, PowerPoint, CSV, texto, arquivos do Google Docs/Planilhas/Apresentações e o que estiver dentro
  de zips (como os exportados do SEI). Pula outros formatos e arquivos acima de 30 MB.
- **Dados pessoais:** arquivos cujo nome indica contatos, telefones, CPF ou pontos focais não são baixados. Nos demais,
  CPFs e telefones são apagados do texto antes de ir para a API. E-mails são apagados como no painel.
- Os textos são juntados num limite de 150 mil caracteres por órgão, com relatórios e resumos primeiro. O que for
  cortado fica registrado em `arquivos_lidos.json`.
- **Sem revisão humana:** o dossiê e os insumos não passam pela equipe antes do debate. O quadro "Sobre este
  documento" diz isso em cada memorando. Revise antes de circular.

**O que sai, por órgão:** `memorando.docx`, `memorando.md`, `tension_map.json`, `dossie.json` (com o diagnóstico da
pesquisa), `registro.json` e `arquivos_lidos.json`. Na raiz, `resumo.md` e `resumo.csv` com situação, itens do dossiê,
confiança e custo de cada órgão. Uma falha num órgão não para os outros.

**Configuração (uma vez)**
1. No [Google Cloud Console](https://console.cloud.google.com/), crie um projeto (ou use um existente) e ative a
   **Google Drive API**.
2. Em **IAM e administrador > Contas de serviço**, crie uma conta de serviço (não precisa de papel). Em **Chaves >
   Adicionar chave > JSON**, baixe o arquivo. Guarde-o com cuidado: ele dá acesso ao que for compartilhado com a conta.
3. O dono da pasta DOCUMENTOS RECEBIDOS compartilha a pasta com o e-mail da conta de serviço
   (`...@...iam.gserviceaccount.com`) como **Leitor**. As subpastas herdam o acesso.
4. No GitHub, em **Settings > Secrets and variables > Actions**, crie os segredos:
   `GOOGLE_SERVICE_ACCOUNT_JSON` (o conteúdo do arquivo JSON), `DRIVE_PASTA_ID` (o ID da pasta, o trecho do link depois
   de `/folders/`), `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` (se usar Gemini) e `RESULTADOS_SENHA` (a senha do zip).

**Como rodar**
1. Em **Actions > Processamento em lote (Drive) > Run workflow**, rode primeiro com "Só listar" marcado. O zip traz
   `orgaos.json` com os órgãos e o número de arquivos de cada um, sem gastar nada com modelos.
2. Rode de novo com "Só listar" desmarcado. Para testar, preencha "Só estes órgãos" com uma ou duas siglas.
3. Ao final, baixe o artefato **resultados** e abra com a senha. O zip usa criptografia AES: no Windows, abra com o
   7-Zip ou o WinRAR (o Explorador de Arquivos não abre).

**Custo.** A camada do Estado (situação fiscal, dívida, previdência, calendário e cenário político) é igual para todos
os órgãos: é pesquisada uma vez por execução e reaproveitada, e o resumo mostra esse custo à parte. Cada órgão pesquisa
só a própria camada. O padrão do lote é Sonnet no debate e no memorando, com 2 rodadas: estimativa de US$ 0,40 a 0,70
por órgão. Com Opus e 3 rodadas, a estimativa sobe para US$ 0,80 a 1,20. Com 4 partes em paralelo, cerca de 40 órgãos
levam de 1h a 1h30. O custo real de cada órgão sai no `resumo.csv`.

**Atenção: o repositório é público.** Logs e artefatos do GitHub Actions de um repositório público podem ser vistos
por qualquer pessoa com conta no GitHub. Por isso o zip sai criptografado e os logs mostram só nomes de órgãos,
contagens e erros. O mais seguro é tornar o repositório privado (o Streamlit Community Cloud funciona com repositórios
privados).

## Código retirado

O diagnóstico de lacunas, a conferência dos ofícios já enviados, os pedidos gerados das questões do debate e a minuta
de ofício saíram do painel na versão 2.0. O código e os testes estão em `extraido/lacunas_oficio/`, como estavam na
versão 1.11, para servir de base à ferramenta própria de triagem de relatórios. Eles dependem de funções que
continuam no `app.py` (lista no topo de `lacunas_oficio.py`).

## Cuidados

- Não envie ao painel propostas de licitação em andamento, processos sigilosos ou dados pessoais além do necessário.
  O texto vai para a API do provedor do modelo.
- O painel abre os links do dossiê para conferi-los. Endereços locais e de rede interna não são abertos.
- Use papéis nas personas, nunca nomes de pessoas: o debate atribui posições simuladas a quem estiver nelas.
- O memorando é gerado com apoio de IA e diz isso no rodapé e na seção de verificação. Ele não substitui a revisão
  técnica e jurídica.

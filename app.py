import streamlit as st
import json
import re
import os
import tempfile
from dotenv import load_dotenv
from litellm import completion
from markitdown import MarkItDown # NOVA BIBLIOTECA
SYSTEM_PROMPT = """
Você é um facilitador de deliberação multiagente. Seu objetivo é produzir um TENSION MAP (mapa de tensões) e um MEMORANDO EXECUTIVO para apoiar decisores humanos. Você NÃO decide e NÃO busca consenso. Você amplia a inteligência expondo trade-offs.

PROTOCOLO OBRIGATÓRIO DE EXECUÇÃO EM 5 FASES:
FASE 1 — PROPOSIÇÃO: Cada persona propõe um plano (JSON).
FASE 2 — CRÍTICA CRUZADA: Cada persona critica os planos das outras (Regra Adversarial).
FASE 2.5 — REVISÃO: Cada persona escolhe REVISAR (abandonando premissas), DEFENDER ou MANTER.
FASE 3 — AVALIAÇÃO INDEPENDENTE: Nota cega (forte/moderado/fraco/rejeitar).
FASE 4 — TENSION MAP: Agrupar argumentos por mecanismo causal (deduplicação). Produzir o JSON final com trade_offs (mínimo 3), evidence_level (1 a 5) e unresolved_questions.
FASE 5 — MEMORANDO EXECUTIVO: 2 páginas em português claro. Top 3 trade-offs, quem ganha/perde, decisões da semana, dados faltantes, custo de não decidir.

DIRETRIZES INVIOLÁVEIS:
1. Use a hierarquia de evidências: Nível 1 (Fato documental) a Nível 5 (Sem evidência).
2. Classifique as divergências: factual, causal, normativa, distributiva, temporal ou epistêmica.
3. Aplique as restrições legais brasileiras (estabilidade do servidor, Lei 14.133/21, patrimonialismo, TCE/MPRJ).
4. NUNCA fabrique dissenso. Se houver convergência legítima, registre-a.
5. ENTREGUE APENAS UM BLOCO JSON VÁLIDO E O MEMORANDO EM TEXTO PURO. Não use formatação markdown ao redor do JSON.

Formato de Saída Obrigatório:
[INÍCIO DO JSON]
{
  "tension_map_id": "...",
  "scenario": "...",
  "baseline_reference": "...",
  "trade_offs": [...],
  "unresolved_questions": [...],
  "confidence_assessment": {...}
}
[FIM DO JSON]

[INÍCIO DO MEMORANDO]
(Texto do memorando aqui)
[FIM DO MEMORANDO]
"""

load_dotenv()


def extrair_json_limpo(texto):
    # Remove blocos de código markdown (```json ... ```)
    texto_limpo = re.sub(r'```(?:json)?', '', texto)
    # Encontra o primeiro '{' e o último '}'
    inicio = texto_limpo.find('{')
    fim = texto_limpo.rfind('}')
    if inicio != -1 and fim != -1:
        texto_limpo = texto_limpo[inicio:fim+1]
    try:
        return json.loads(texto_limpo)
    except json.JSONDecodeError as e:
        print("Erro ao decodificar JSON. Texto recebido:", texto_limpo[:200])
        return None


st.set_page_config(page_title="Deliberação Multiagente", page_icon="🏛️", layout="wide")

st.title("🏛️ Painel de Deliberação e Análise de Transição")


def _como_texto(valor):
    # O modelo às vezes devolve listas em vez de texto; st.text_area exige string
    if isinstance(valor, list):
        return "\n".join(
            json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)
            for v in valor
        )
    if isinstance(valor, dict):
        return json.dumps(valor, ensure_ascii=False, indent=2)
    return str(valor or "")


with st.sidebar:
    st.header("1. Upload do Relatório")
    # Aceita PDF, Word e Excel
    uploaded_file = st.file_uploader("Suba o relatório (PDF, DOCX ou XLSX)", type=["pdf", "docx", "xlsx"])

    if st.button("🔍 Extrair Dados do Relatório"):
        if uploaded_file is not None:
            with st.spinner("Lendo tabelas e estruturando os dados (Markdown)..."):

                # 1. Salva o arquivo temporariamente para o MarkItDown ler
                with tempfile.NamedTemporaryFile(delete=False, suffix=f".{uploaded_file.name.split('.')[-1]}") as tmp:
                    tmp.write(uploaded_file.getvalue())
                    tmp_path = tmp.name

                # 2. Converte para Markdown (as tabelas viram texto estruturado!)
                md = MarkItDown()
                try:
                    result = md.convert(tmp_path)
                    texto_relatorio = result.text_content
                except Exception as e:
                    st.error(f"Erro ao ler o arquivo: {e}")
                    st.stop()
                finally:
                    os.remove(tmp_path) # Limpa o arquivo temporário

                # 3. Manda o Markdown para o Claude extrair as informações
                # Limite aumentado para 60.000 caracteres, pois Markdown é denso
                prompt_extrator = f"""Leia o relatório de transição abaixo (que está em formato Markdown, com tabelas preservadas) e extraia as informações EXATAS no formato JSON.

                Relatório:
                {texto_relatorio[:60000]}

                Retorne APENAS o JSON:
                {{
                  "problema": "Resuma em 1 parágrafo o maior dilema ou conflito estratégico da secretaria.",
                  "fatos": "Liste de 5 a 8 fatos ancoradores cruciais. Se houver tabelas de contratos ou obras, extraia os nomes das empresas, valores e saldos exatos.",
                  "personas": "Crie 5 a 6 personas com critérios de decisão conflitantes baseados nos atores citados.",
                  "lacunas": "Liste de 3 a 4 informações críticas que o relatório NÃO responde."
                }}"""

                try:
                    resp_extrator = completion(
                        model="anthropic/claude-sonnet-5-5",
                        messages=[{"role": "user", "content": prompt_extrator}],
                    )

                    # Usa a nova função de limpeza
                    texto_bruto = resp_extrator.choices[0].message.content
                    dados = extrair_json_limpo(texto_bruto)

                    if dados is None:
                        st.error("O modelo não retornou um JSON válido.")
                        # Mostra a resposta na tela: com o iniciar.bat (pythonw) não há console para o print
                        with st.expander("Ver resposta bruta do extrator"):
                            st.text(texto_bruto)
                        st.stop()
                    st.session_state['problema'] = _como_texto(dados.get('problema', ''))
                    st.session_state['fatos'] = _como_texto(dados.get('fatos', ''))
                    st.session_state['personas'] = _como_texto(dados.get('personas', ''))
                    st.session_state['lacunas'] = _como_texto(dados.get('lacunas', ''))
                    st.success("Relatório e tabelas lidos com sucesso!")
                except Exception as e:
                    st.error(f"Erro na extração: {e}")
        else:
            st.warning("Faça o upload do arquivo primeiro.")

    st.markdown("---")
    st.header("2. Revisão e Ajustes")
    problema = st.text_area("Problema Central", value=st.session_state.get('problema', ''), height=100)
    fatos = st.text_area("Fatos Ancoradores", value=st.session_state.get('fatos', ''), height=150)
    personas = st.text_area("Personas", value=st.session_state.get('personas', ''), height=150)
    lacunas = st.text_area("Lacunas de Dados", value=st.session_state.get('lacunas', ''), height=100)

    st.markdown("---")
    modelo = st.selectbox("Modelo Facilitador", ["anthropic/claude-sonnet-4-6", "anthropic/claude-sonnet-4-20250514"])
    botao_gerar = st.button("🚀 Iniciar Deliberação (2 Etapas)", use_container_width=True)


def extrair_json(texto):
    # 1º: bloco entre as tags (evita pegar os JSONs intermediários das Fases 1-3)
    match = re.search(r'\[INÍCIO DO JSON\]\s*(.*?)\s*\[FIM DO JSON\]', texto, re.DOTALL)
    if match:
        bloco = re.sub(r'^```(?:json)?\s*|\s*```$', '', match.group(1).strip())
        try: return json.loads(bloco)
        except: pass
    # 2º: fallback para o maior objeto JSON do texto
    match = re.search(r'\{.*\}', texto, re.DOTALL)
    if match:
        try: return json.loads(match.group(0))
        except: pass
    return None


def prompt_somente_fases_1_a_4(prompt):
    # Remove o bloco da Fase 5 (até "REGRAS:") e a menção ao memorando na entrega
    prompt = re.sub(
        r"FASE 5 —.*?(?=\nREGRAS:)",
        "PARE NA FASE 4. Gere APENAS o JSON do Tension Map, não escreva o memorando agora.\n",
        prompt,
        flags=re.DOTALL,
    )
    return prompt.replace(", seguido do memorando entre [INÍCIO DO MEMORANDO] e [FIM DO MEMORANDO]", "")


if botao_gerar:
    if not problema or not fatos:
        st.warning("Por favor, preencha os dados antes de iniciar.")
    else:
               # --- ETAPA 1: GERAR O TENSION MAP (JSON) ---
        with st.spinner("Etapa 1/2: O conselho de agentes está debatendo e gerando o Tension Map..."):
            
            # A MÁGICA ACONTECE AQUI: Dizemos para ele não imprimir as Fases 1 a 3 no JSON final
            instrucao_compacta = """
            Execute internamente as Fases 1 a 3 (Proposição, Crítica, Revisão e Avaliação).
            
            MAS NÃO RETORNE O HISTÓRICO DAS FASES 1 A 3 NO JSON. Retorne APENAS o Tension Map da Fase 4, com os trade-offs já deduplicados e sintetizados.
            
            O JSON deve ter o formato estrito:
            {
              "tension_map_id": "RJ_SECID_2027",
              "scenario": "...",
              "baseline_reference": "...",
              "trade_offs": [ ... no máximo 6 trade-offs detalhados ... ],
              "unresolved_questions": [ ... no máximo 4 ... ],
              "confidence_assessment": { ... }
            }
            """
            
            prompt_fase_1_a_4 = SYSTEM_PROMPT + "\n\n" + instrucao_compacta
            
            # Aumentamos o limite de tokens de saída para garantir que caiba
            user_prompt_1 = f"CENÁRIO: {problema}\nFATOS: {fatos}\nPERSONAS: {personas}\nLACUNAS: {lacunas}\n\nExecute o protocolo e retorne APENAS o JSON final entre [INÍCIO DO JSON] e [FIM DO JSON]."
            
            try:
                # MUDANÇA IMPORTANTE: Use um modelo com limite de token maior (Sonnet 3.5)
                resp_1 = completion(
                    model="anthropic/claude-3-5-sonnet-20241022",
                    messages=[{"role": "system", "content": prompt_fase_1_a_4}, {"role": "user", "content": user_prompt_1}],
                    max_tokens=8000, # Aumentado para caber o JSON inteiro
                )
                texto_json = resp_1.choices[0].message.content
                tension_map = extrair_json_limpo(texto_json)
                
                if tension_map is None:
                    st.error("Falha ao gerar o JSON. O modelo gerou um texto muito longo. Tente novamente.")
                    st.stop()

                # --- ETAPA 2: GERAR MEMORANDO E MATRIZ DE RISCO ---
                with st.spinner("Etapa 2/2: Redigindo Memorando Executivo e Matriz de Risco..."):
                    prompt_memo = f"""
                    Com base no seguinte Tension Map, escreva o Memorando Executivo e a Matriz de Risco para o Secretário.

                    TENSION MAP: {json.dumps(tension_map, ensure_ascii=False)}

                    Entregue o texto em Markdown com a seguinte estrutura:
                    # Memorando Executivo
                    (Texto direto, 2 páginas)

                    # Matriz de Risco de Ação
                    | Risco Identificado | Probabilidade (Alta/Média/Baixa) | Impacto (Alto/Médio/Baixo) | Ação Mitigadora Proposta | Responsável Sugerido |
                    |---|---|---|---|---|
                    (Preencha a tabela com os riscos do mapa)
                    """

                    resp_2 = completion(
                        model=modelo,
                        messages=[{"role": "user", "content": prompt_memo}],
                        max_tokens=8000
                    )
                    memorando = resp_2.choices[0].message.content

                st.success("✅ Deliberação concluída com sucesso!")

                st.header("📄 Memorando e Matriz de Risco")
                st.markdown(memorando)

                col1, col2 = st.columns(2)
                with col1:
                    st.download_button("⬇️ Baixar Memorando (.md)", data=memorando, file_name="memorando_transicao.md")
                with col2:
                    st.download_button("⬇️ Baixar Dados (.json)", data=json.dumps(tension_map, ensure_ascii=False, indent=2), file_name="tension_map.json")

                with st.expander("Ver Dados Estruturados (JSON)"):
                    st.json(tension_map)

            except Exception as e:
                st.error(f"❌ Erro na API: {e}")

import streamlit as st
import json
import re
import os
import tempfile
import io
import docx
from docx.shared import Pt
from dotenv import load_dotenv
from litellm import completion
from markitdown import MarkItDown

# --- PROMPT DO SISTEMA ---
SYSTEM_PROMPT = """
Você é um facilitador de deliberação multiagente. Seu objetivo é produzir um TENSION MAP (mapa de tensões) e um MEMORANDO EXECUTIVO para apoiar decisores humanos. Você NÃO decide e NÃO busca consenso. Você amplia a inteligência expondo trade-offs.

PROTOCOLO OBRIGATÓRIO DE EXECUÇÃO EM 5 FASES:
FASE 1 — PROPOSIÇÃO: Cada persona propõe um plano.
FASE 2 — CRÍTICA CRUZADA: Cada persona critica os planos das outras.
FASE 2.5 — REVISÃO: Cada persona escolhe REVISAR, DEFENDER ou MANTER.
FASE 3 — AVALIAÇÃO INDEPENDENTE: Nota cega.
FASE 4 — TENSION MAP: Produzir o JSON final com os trade-offs deduplicados.
FASE 5 — MEMORANDO EXECUTIVO: 2 páginas em português claro. Top 3 trade-offs, quem ganha/perde, decisões da semana, dados faltantes, custo de não decidir.

DIRETRIZES INVIOLÁVEIS:
1. Use a hierarquia de evidências: Nível 1 (Fato documental) a Nível 5 (Sem evidência).
2. Classifique as divergências: factual, causal, normativa, distributiva, temporal ou epistêmica.
3. Aplique as restrições legais brasileiras.
4. NUNCA fabrique dissenso. Se houver convergência legítima, registre-a.
5. ENTREGUE APENAS UM BLOCO JSON VÁLIDO E O MEMORANDO EM TEXTO PURO.

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

st.set_page_config(page_title="Deliberação Multiagente", page_icon="🏛️", layout="wide")
st.title("🏛️ Painel de Deliberação e Análise de Transição")

# --- FUNÇÕES AUXILIARES ---
def extrair_json_limpo(texto):
    texto_limpo = re.sub(r'```(?:json)?', '', texto)
    inicio = texto_limpo.find('{')
    fim = texto_limpo.rfind('}')
    if inicio != -1 and fim != -1:
        texto_limpo = texto_limpo[inicio:fim+1]
    try:
        return json.loads(texto_limpo)
    except json.JSONDecodeError:
        return None

def _como_texto(valor):
    if isinstance(valor, list):
        return "\n".join(json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v) for v in valor)
    if isinstance(valor, dict):
        return json.dumps(valor, ensure_ascii=False, indent=2)
    return str(valor or "")

def gerar_docx(texto_markdown):
    doc = docx.Document()
    style = doc.styles['Normal']
    font = style.font
    font.name = 'Arial'
    font.size = Pt(11)
    
    linhas = texto_markdown.split('\n')
    for linha in linhas:
        linha = linha.strip()
        if not linha:
            continue
        if linha.startswith('# '):
            doc.add_heading(linha.replace('# ', ''), level=1)
        elif linha.startswith('## '):
            doc.add_heading(linha.replace('## ', ''), level=2)
        elif linha.startswith('### '):
            doc.add_heading(linha.replace('### ', ''), level=3)
        elif linha.startswith('|'):
            if '---' in linha:
                continue
            colunas = [c.strip() for c in linha.split('|') if c.strip()]
            if colunas:
                tabela = doc.add_table(rows=1, cols=len(colunas))
                tabela.style = 'Table Grid'
                hdr_cells = tabela.rows[0].cells
                for i, col in enumerate(colunas):
                    hdr_cells[i].text = col
        else:
            doc.add_paragraph(linha)
            
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer

# --- BARRA LATERAL ---
with st.sidebar:
    st.header("0. Configuração de IA")
    modelo = st.selectbox("Modelo Facilitador", [
        "anthropic/claude-3-5-sonnet-20241022", 
        "anthropic/claude-3-opus-20240229"
    ])
    
    st.markdown("---")
    st.header("1. Upload do Relatório")
    uploaded_file = st.file_uploader("Suba o relatório (PDF, DOCX ou XLSX)", type=["pdf", "docx", "xlsx"])

    if st.button("🔍 Extrair Dados do Relatório"):
        if uploaded_file is not None:
            with st.spinner("Lendo tabelas e estruturando os dados (Markdown)..."):
                
                with tempfile.NamedTemporaryFile(delete=False, suffix=f".{uploaded_file.name.split('.')[-1]}") as tmp:
                    tmp.write(uploaded_file.getvalue())
                    tmp_path = tmp.name

                md = MarkItDown()
                try:
                    result = md.convert(tmp_path)
                    texto_relatorio = result.text_content
                except Exception as e:
                    st.error(f"Erro ao ler o arquivo: {e}")
                    st.stop()
                finally:
                    os.remove(tmp_path) 

                # CORREÇÃO AQUI: FORÇANDO O MODELO HÍBRIDO DE PERSONAS
                prompt_extrator = f"""Leia o relatório de transição abaixo e extraia as informações EXATAS no formato JSON.
                Relatório: {texto_relatorio[:60000]}

                Retorne APENAS o JSON:
                {{
                  "problema": "Resuma em 1 parágrafo o maior dilema da secretaria.",
                  "fatos": "Liste de 5 a 8 fatos ancoradores cruciais (números, orçamento, contratos vencendo).",
                  "personas": "OBRIGATÓRIO: Use o Modelo Híbrido. Inclua SEMPRE estes 5 agentes fixos: 1. fazenda_planejamento (foco em caixa), 2. orgao_controle (foco em legalidade/TCE), 3. casa_civil (foco em coordenação política), 4. beneficiario_servico (foco no cidadão na ponta), 5. baseline (status quo). Depois, crie mais 2 personas técnicas específicas desta secretaria com base no relatório (ex: diretor_tecnico, sindicato). Descreva o critério de decisão de cada uma.",
                  "lacunas": "Liste de 3 a 4 informações críticas que o relatório NÃO responde."
                }}"""

                try:
                    resp_extrator = completion(
                        model=modelo,
                        messages=[{"role": "user", "content": prompt_extrator}],
                        max_tokens=4000
                    )

                    texto_bruto = resp_extrator.choices[0].message.content
                    dados = extrair_json_limpo(texto_bruto)

                    if dados is None:
                        st.error("O modelo não retornou um JSON válido.")
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
    personas = st.text_area("Personas", value=st.session_state.get('personas', ''), height=200)
    lacunas = st.text_area("Lacunas de Dados", value=st.session_state.get('lacunas', ''), height=100)

    st.markdown("---")
    botao_gerar = st.button("🚀 Iniciar Deliberação (2 Etapas)", use_container_width=True)

# --- LÓGICA PRINCIPAL ---
if botao_gerar:
    if not problema or not fatos:
        st.warning("Por favor, preencha os dados antes de iniciar.")
    else:
        with st.spinner(f"Etapa 1/2: O conselho de agentes ({modelo}) está debatendo..."):
            
            instrucao_compacta = """
            Execute internamente as Fases 1 a 3 (Proposição, Crítica, Revisão e Avaliação).
            MAS NÃO RETORNE O HISTÓRICO DAS FASES 1 A 3 NO JSON. Retorne APENAS o Tension Map da Fase 4.
            
            REGRA DE OURO DE CONCISÃO: 
            - Crie no máximo 4 trade-offs.
            - No campo "descricao" de cada trade-off, use no máximo 2 frases.
            - No campo "mecanismo_causal", use no máximo 1 frase.
            - Seja direto e cirúrgico. O objetivo é caber no limite de tokens.
            """
            
            prompt_fase_1_a_4 = SYSTEM_PROMPT + "\n\n" + instrucao_compacta
            user_prompt_1 = f"CENÁRIO: {problema}\nFATOS: {fatos}\nPERSONAS: {personas}\nLACUNAS: {lacunas}\n\nExecute o protocolo e retorne APENAS o JSON final."
            
            try:
                resp_1 = completion(
                    model=modelo,
                    messages=[
                        {"role": "system", "content": prompt_fase_1_a_4}, 
                        {"role": "user", "content": user_prompt_1}
                    ],
                    max_tokens=8192,
                )
                texto_json = resp_1.choices[0].message.content
                tension_map = extrair_json_limpo(texto_json)
                
                if tension_map is None:
                    st.error("Falha ao gerar o JSON. O modelo gerou um texto muito longo ou inválido.")
                    with st.expander("Ver resposta bruta (para debug)"):
                        st.text(texto_json)
                    st.stop()

                with st.spinner("Etapa 2/2: Redigindo Memorando Executivo e Matriz de Risco..."):
                    prompt_memo = f"""
                    Com base no Tension Map abaixo, escreva o Memorando Executivo e a Matriz de Risco.
                    TENSION MAP: {json.dumps(tension_map, ensure_ascii=False)}
                    
                    Entregue em Markdown:
                    # Memorando Executivo
                    # Matriz de Risco de Ação (Tabela com Colunas: Risco, Probabilidade, Impacto, Ação, Responsável)
                    """

                    resp_2 = completion(
                        model=modelo,
                        messages=[{"role": "user", "content": prompt_memo}],
                        max_tokens=4000
                    )
                    memorando = resp_2.choices[0].message.content

                st.success("✅ Deliberação concluída com sucesso!")

                st.header("📄 Memorando e Matriz de Risco")
                st.markdown(memorando)

                col1, col2, col3 = st.columns(3)
                with col1:
                    st.download_button("⬇️ Baixar Dados (.json)", data=json.dumps(tension_map, ensure_ascii=False, indent=2), file_name="tension_map.json")
                with col2:
                    st.download_button("⬇️ Baixar Texto (.md)", data=memorando, file_name="memorando_transicao.md")
                with col3:
                    arquivo_word = gerar_docx(memorando)
                    st.download_button(
                        label="⬇️ Baixar Relatório (.docx)",
                        data=arquivo_word,
                        file_name="relatorio_transicao.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    )

                with st.expander("Ver Dados Estruturados (JSON)"):
                    st.json(tension_map)

            except Exception as e:
                st.error(f"❌ Erro na API: {e}")

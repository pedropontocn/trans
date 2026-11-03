"""Orquestrador: cenário -> Claude Opus (deliberação) -> Tension Map + Memorando -> validação.

Uso:
    python src/orquestrador.py [caminho_cenario]
"""
import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from litellm import completion

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
load_dotenv(ROOT / ".env")

from prompts import SYSTEM_PROMPT  # noqa: E402
import validador  # noqa: E402

SAIDA_TM = ROOT / "output_tension_map.json"
SAIDA_MEMO = ROOT / "output_memorando.md"
SAIDA_VALIDACAO = ROOT / "output_validacao.json"
SAIDA_BRUTA = ROOT / "output_resposta_bruta.txt"


def _entre_tags(texto: str, inicio: str, fim: str) -> str | None:
    m = re.search(re.escape(inicio) + r"(.*?)" + re.escape(fim), texto, re.DOTALL)
    return m.group(1).strip() if m else None


def extrair_tension_map(texto: str) -> dict:
    bloco = _entre_tags(texto, "[INÍCIO DO JSON]", "[FIM DO JSON]")
    if bloco is None:
        raise ValueError("Tags [INÍCIO DO JSON]/[FIM DO JSON] não encontradas na resposta.")
    bloco = re.sub(r"^```(?:json)?\s*|\s*```$", "", bloco.strip())
    try:
        return json.loads(bloco)
    except json.JSONDecodeError:
        # fallback: maior objeto JSON dentro do bloco
        m = re.search(r"\{.*\}", bloco, re.DOTALL)
        if not m:
            raise
        return json.loads(m.group(0))


def extrair_memorando(texto: str) -> str:
    memo = _entre_tags(texto, "[INÍCIO DO MEMORANDO]", "[FIM DO MEMORANDO]")
    if memo is None:
        # tolera ausência da tag final (resposta truncada)
        m = re.search(re.escape("[INÍCIO DO MEMORANDO]") + r"(.*)", texto, re.DOTALL)
        if not m:
            raise ValueError("Tag [INÍCIO DO MEMORANDO] não encontrada na resposta.")
        memo = m.group(1).strip()
    return memo


def main(caminho_cenario: Path) -> None:
    cenario = json.loads(caminho_cenario.read_text(encoding="utf-8"))
    user_prompt = (
        "Execute a deliberação para o cenário abaixo.\n\n"
        + json.dumps(cenario, ensure_ascii=False, indent=2)
    )

    # 2. Chama o Claude (Fases 1 a 5)
    print("2. Acionando o Conselho de Agentes (Claude Opus 5.5)...")
    try:
        resp = completion(
            model="anthropic/claude-opus-5-5", # Nome oficial confirmado
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=16000, # OBRIGATÓRIO AUMENTAR: Opus 5.5 usa os tokens para pensar também
            # temperature=0.7, # REMOVIDO: Opus 5.5 rejeita este parâmetro (Erro 400)
        )

        texto_gerado = resp.choices[0].message.content

        # Verifica se a API cortou a resposta por falta de espaço
        if resp.choices[0].finish_reason == "length":
            print("⚠️ AVISO: O modelo atingiu o limite de tokens e a resposta pode estar cortada.")

    except Exception as e:
        print(f"❌ Erro ao chamar o Claude: {e}")
        return

    texto = texto_gerado
    SAIDA_BRUTA.write_text(texto, encoding="utf-8")

    tension_map = extrair_tension_map(texto)
    SAIDA_TM.write_text(json.dumps(tension_map, ensure_ascii=False, indent=2), encoding="utf-8")

    # Usa o extrator do validador (desembrulha "fase_4_tension_map" se o Claude aninhar)
    core = validador.extract_relevant_data(SAIDA_TM)
    for i, to in enumerate(core["trade_offs"], start=1):
        if isinstance(to, dict):
            to.setdefault("trade_off_id", f"T{i}")
    n = len(core["trade_offs"])
    if n < 3:
        print(f"[aviso] Tension Map tem {n} trade-offs (mínimo esperado: 3).", file=sys.stderr)
    print(f"Tension Map salvo em {SAIDA_TM}")

    SAIDA_MEMO.write_text(extrair_memorando(texto), encoding="utf-8")
    print(f"Memorando salvo em {SAIDA_MEMO}")

    validacao = validador.rodar_validacao(core)
    SAIDA_VALIDACAO.write_text(json.dumps(validacao, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Validação salva em {SAIDA_VALIDACAO}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "input" / "cenario.json")

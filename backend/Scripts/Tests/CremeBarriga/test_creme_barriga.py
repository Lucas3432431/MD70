"""
Mock de copywriting — 5 variações de estilo via generate_from_reference_image.

Cena: mulher búlgara (30–40 anos) aplicando creme na barriga.
Formato: 4:5
Referência: https://i.pinimg.com/736x/75/a2/97/75a29748d062e7d03e7e1aaf97e5e487.jpg

Chama generate_from_reference_image diretamente (mesmo caminho do _execute_asset_variation_mode),
sem passar pelos gates de validation do fluxo de chat.

Uso:
    cd App/mvp/services/backend
    python -m Scripts.Tests.CremeBarriga.test_creme_barriga
    python -m Scripts.Tests.CremeBarriga.test_creme_barriga --env-file .env.wsl
"""

import sys, os, json, argparse, time
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(BACKEND_DIR))

_parser = argparse.ArgumentParser(add_help=False)
_parser.add_argument("--env-file", default=str(BACKEND_DIR / ".env.wsl"))
_args, _ = _parser.parse_known_args()
os.environ["ENV_FILE"] = _args.env_file

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

REFERENCE_IMG = (
    "https://i.pinimg.com/736x/75/a2/97/75a29748d062e7d03e7e1aaf97e5e487.jpg"
)
ASPECT_RATIO = "4:5"
WHAT_TO_VALIDATE = "estilo visual e ângulo — 5 variações criativas"
SEP = "=" * 70
SEP2 = "-" * 70

# ── 5 Variações de estilo ─────────────────────────────────────────────────────
#
# Cada variação usa testing_var.type = "custom" com descrição criativa completa.
# O _TESTING_VAR_BASE["custom"] injeta:
#   "Generate a professional ad creative variation based on this reference image.
#    Validation objective: {what_to_validate}.
#    Specific creative direction for this variation: {description}.
#    Result must be photorealistic, print-quality, professional advertising standard."
#
# Personagem base: mulher búlgara 30-40 anos, pele clara warm beige, aplicando creme na barriga.

VARIATIONS = [
    # ── V1: Studio Beauty ─────────────────────────────────────────────────────
    {
        "label": "V1_Studio_Beauty",
        "style": "Studio beauty — minimalist white, close-up torso, diffused beauty light",
        "testing_var": {
            "type": "custom",
            "description": (
                "STYLE: Clean beauty studio photography. "
                "Bulgarian woman, 30–40 years old, light warm beige skin, dewy texture. "
                "White crop top slightly raised — belly exposed. Both hands applying cream in circular motion. "
                "ANGLE: CloseUpShot — torso and belly fill the frame from collar to hips. "
                "SETTING: Pure white/cream seamless background studio. "
                "LIGHTING: Large softbox from front-left 45°, warm fill right. "
                "Even diffused light — no harsh shadows. Catches dewy skin luminosity. "
                "MOOD: Serene luxury — self-care as sacred ritual. "
                "Premium beauty campaign quality. No text. No graphics."
            ),
        },
    },
    # ── V2: Window Intimate ───────────────────────────────────────────────────
    {
        "label": "V2_Window_Intimate",
        "style": "Window light — interior morning, plants in background, warm natural glow",
        "testing_var": {
            "type": "custom",
            "description": (
                "STYLE: Intimate morning home photography. "
                "Bulgarian woman, 30–40 years old, fair skin, dewy. "
                "Off-white linen bralette and high-waist underwear. Belly exposed. "
                "ANGLE: CloseUpShot — torso close-up, window light flooding from left side. "
                "SETTING: Home interior with large window. Background: monstera plant and warm neutral wall in soft focus. "
                "LIGHTING: Soft natural window daylight from left — directional, warm. "
                "Gentle shadow on right side for depth. "
                "MOOD: Warm private morning ritual — beauty in real life, unperformed. "
                "No text. No graphics."
            ),
        },
    },
    # ── V3: Editorial Outdoor ─────────────────────────────────────────────────
    {
        "label": "V3_Editorial_Outdoor",
        "style": "Golden hour outdoors — terrace, garden bokeh, direct eye contact",
        "testing_var": {
            "type": "custom",
            "description": (
                "STYLE: Editorial outdoor photography — summer campaign. "
                "Bulgarian woman, 30–40 years old, fair sun-touched skin, natural glow. "
                "White bandeau bikini top and linen shorts. Belly exposed. "
                "ANGLE: EyeLevelShot — subject at eye level, direct confident gaze into camera. "
                "SETTING: Sunlit garden terrace. Blurred green bokeh background. "
                "LIGHTING: Golden hour sunlight from side-right — warm, directional, low angle. "
                "Strong rim light on shoulder. Rich golden skin glow. "
                "MOOD: Free and confident — outdoor beauty, sun-kissed self-care. "
                "No text. No graphics."
            ),
        },
    },
    # ── V4: UGC Authentic ─────────────────────────────────────────────────────
    {
        "label": "V4_UGC_Authentic",
        "style": "UGC self-filmed — handheld candid, outdoor balcony, real person energy",
        "testing_var": {
            "type": "custom",
            "description": (
                "STYLE: UGC (User Generated Content) self-filmed. "
                "Bulgarian woman, 30–40 years old, fair skin, natural look. "
                "Casual oversized t-shirt pulled up — belly naturally exposed. "
                "ANGLE: UGC style — handheld close shot, slightly above, off-center. "
                "Imperfect, authentic framing. One hand holds or gestures toward camera; "
                "other hand on belly with cream. Natural expression — slight smile or casual look. "
                "SETTING: Outdoor balcony or backyard. Soft natural ambient light. "
                "LIGHTING: Natural ambient outdoor light — no professional setup. Authentic UGC feel. "
                "MOOD: Raw relatability — real person, real routine, genuine and unposed. "
                "No text. No graphics."
            ),
        },
    },
    # ── V5: B&W Editorial ─────────────────────────────────────────────────────
    {
        "label": "V5_BlackWhite_Editorial",
        "style": "Black & white editorial — high contrast, dramatic directional light",
        "testing_var": {
            "type": "custom",
            "description": (
                "STYLE: Black and white editorial photography. Full monochromatic treatment — no color. "
                "Bulgarian woman, 30–40 years old, applying cream to belly. "
                "ANGLE: HighAngleShot — camera above looking down at her. "
                "Subject's torso and hands visible; cream being applied in circular motion. "
                "SETTING: Clean neutral setting, outdoor or studio — reads as pure tones in B&W. "
                "LIGHTING: Dramatic single directional light from side — strong shadows reveal "
                "skin texture, micro-details of hands and belly. "
                "High contrast tonal range — deep blacks, bright highlights. "
                "MOOD: Fashion editorial — timeless, dramatic, skin-texture as sculpture. "
                "No text. No graphics."
            ),
        },
    },
]

# ── Infrastructure ────────────────────────────────────────────────────────────


def get_session():
    db_path = BACKEND_DIR / "Data" / "Database" / "MD70.db"
    engine = create_engine(f"sqlite:///{db_path}")

    @event.listens_for(engine, "connect")
    def _fk_off(conn, _):
        conn.execute("PRAGMA foreign_keys = OFF")

    return sessionmaker(bind=engine)()


def get_user_id(session) -> str:
    row = session.execute(text("SELECT user_id FROM users LIMIT 1")).fetchone()
    if not row:
        raise RuntimeError("Nenhum usuário no DB")
    return row[0]


class LiveDB:
    def __init__(self, session):
        self._session = session

    def get_session(self):
        return self._session


# ── Runner ────────────────────────────────────────────────────────────────────


def run():
    print(f"\n{SEP}")
    print("  MOCK COPYWRITING — Mulher Búlgara + Creme na Barriga — 5 Variações 4:5")
    print(SEP)
    print(f"  Referência : {REFERENCE_IMG}")
    print(f"  Formato    : {ASPECT_RATIO}")
    print(f"  Variações  : {len(VARIATIONS)}")
    print()

    session = get_session()
    user_id = get_user_id(session)
    db = LiveDB(session)

    from App.Features.Tools.Tools.Assets import generate_from_reference_image

    print(f"Iniciando geração ({len(VARIATIONS)} imagens via Vertex AI / Gemini)...")
    print()

    t_total_start = time.time()

    result = generate_from_reference_image(
        reference_image=REFERENCE_IMG,
        variations=VARIATIONS,
        what_to_validate=WHAT_TO_VALIDATE,
        aspect_ratio=ASPECT_RATIO,
        chat_id=None,
        user_id=user_id,
        db_manager=db,
    )

    elapsed_total = time.time() - t_total_start

    # ── Resultado ─────────────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("  RESULTADO FINAL")
    print(SEP)

    generated = result.get("generated_assets", [])
    ok_count = sum(1 for a in generated if a.get("success"))

    print(f"  {ok_count}/{len(VARIATIONS)} imagens geradas com sucesso")
    print(f"  Tempo total: {elapsed_total:.1f}s\n")

    for a in generated:
        idx = a.get("index", "?")
        label = (
            VARIATIONS[idx]["label"]
            if isinstance(idx, int) and idx < len(VARIATIONS)
            else f"asset_{idx}"
        )
        icon = "[OK]" if a.get("success") else "[FAIL]"
        print(f"  {icon}  {label}")
        url = a.get("asset_url", "")
        if url:
            print(f"         {url}")
        elif a.get("error"):
            print(f"         Erro: {a['error']}")

    if not result.get("success") and not generated:
        print(f"\n  [FAIL] {result.get('error', 'erro desconhecido')}")

    # Salvar resultado
    output_file = OUTPUT_DIR / f"result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    output_file.write_text(
        json.dumps(
            {
                "reference_img": REFERENCE_IMG,
                "aspect_ratio": ASPECT_RATIO,
                "total_ok": ok_count,
                "total": len(VARIATIONS),
                "elapsed_seconds": round(elapsed_total, 1),
                "generated": generated,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    print(f"\n  Resultado salvo: {output_file}")

    session.close()


if __name__ == "__main__":
    run()

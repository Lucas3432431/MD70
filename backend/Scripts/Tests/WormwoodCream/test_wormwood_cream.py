"""
Gera 3 variações de imagem para South Moon Wormwood Fat Burning Cream.

Estilos: UGC · Lifestyle · Studio
Referência: foto do produto (WhatsApp Image 2026-06-03 at 16.51.13.jpeg)

Uso:
    cd App/mvp/services/backend
    python -m Scripts.Tests.WormwoodCream.test_wormwood_cream
    python -m Scripts.Tests.WormwoodCream.test_wormwood_cream --env-file .env.wsl
    python -m Scripts.Tests.WormwoodCream.test_wormwood_cream --style ugc
    python -m Scripts.Tests.WormwoodCream.test_wormwood_cream --style lifestyle
    python -m Scripts.Tests.WormwoodCream.test_wormwood_cream --style studio
"""

import sys, os, json, argparse, time
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(BACKEND_DIR))

_parser = argparse.ArgumentParser(add_help=False)
_parser.add_argument("--env-file", default=str(BACKEND_DIR / ".env"))
_parser.add_argument(
    "--style", choices=["ugc", "lifestyle", "studio", "all"], default="all"
)
_args, _ = _parser.parse_known_args()
os.environ["ENV_FILE"] = _args.env_file

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

DOCS_DIR = Path(__file__).parent / "documents"
OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

REFERENCE_IMG = str(
    Path.home() / "Downloads" / "WhatsApp Image 2026-06-03 at 16.51.13.jpeg"
)
ASPECT_RATIO = "4:5"
WHAT_TO_VALIDATE = "estilo visual — UGC, lifestyle e studio para creme emagrecedor"
SEP = "=" * 70

# ── Carregar documentos JSON ──────────────────────────────────────────────────


def load_doc(style: str) -> dict:
    path = DOCS_DIR / f"{style}.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def doc_to_variation(doc: dict) -> dict:
    asset = doc["assets"][0]
    prompt = asset["prompt"]
    return {
        "label": f"{doc['style'].upper()}_v1",
        "style": f"{doc['style']} — {doc.get('hook', '')}",
        "testing_var": {
            "type": "custom",
            "description": prompt["description"],
        },
    }


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
    styles = ["ugc", "lifestyle", "studio"] if _args.style == "all" else [_args.style]

    docs = {s: load_doc(s) for s in styles}
    variations = [doc_to_variation(docs[s]) for s in styles]

    print(f"\n{SEP}")
    print("  SOUTH MOON WORMWOOD FAT BURNING CREAM — Geração de Imagens")
    print(SEP)
    print(f"  Referência : {REFERENCE_IMG}")
    print(f"  Formato    : {ASPECT_RATIO}")
    print(f"  Estilos    : {', '.join(styles)}")
    print()

    if not Path(REFERENCE_IMG).exists():
        print(f"[ERRO] Imagem de referência não encontrada: {REFERENCE_IMG}")
        print(
            "       Mova o arquivo para ~/Downloads/ com o nome exato e tente novamente."
        )
        sys.exit(1)

    session = get_session()
    user_id = get_user_id(session)
    db = LiveDB(session)

    from App.Features.Tools.Tools.Assets import generate_from_reference_image

    print(f"Iniciando geração ({len(variations)} imagens via Vertex AI / Gemini)...")
    print()

    t_start = time.time()

    result = generate_from_reference_image(
        reference_image=REFERENCE_IMG,
        variations=variations,
        what_to_validate=WHAT_TO_VALIDATE,
        aspect_ratio=ASPECT_RATIO,
        chat_id=None,
        user_id=user_id,
        db_manager=db,
    )

    elapsed = time.time() - t_start

    print(f"\n{SEP}")
    print("  RESULTADO")
    print(SEP)

    generated = result.get("generated_assets", [])
    ok = sum(1 for a in generated if a.get("success"))
    print(f"  {ok}/{len(variations)} imagens geradas  ({elapsed:.1f}s)\n")

    for a in generated:
        idx = a.get("index", "?")
        label = (
            variations[idx]["label"]
            if isinstance(idx, int) and idx < len(variations)
            else f"asset_{idx}"
        )
        icon = "[OK]" if a.get("success") else "[FAIL]"
        print(f"  {icon}  {label}")
        if a.get("asset_url"):
            print(f"         {a['asset_url']}")
        elif a.get("error"):
            print(f"         Erro: {a['error']}")

    output_file = OUTPUT_DIR / f"result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    output_file.write_text(
        json.dumps(
            {
                "product": "South Moon Wormwood Fat Burning Cream",
                "styles": styles,
                "reference_img": REFERENCE_IMG,
                "aspect_ratio": ASPECT_RATIO,
                "total_ok": ok,
                "total": len(variations),
                "elapsed_seconds": round(elapsed, 1),
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

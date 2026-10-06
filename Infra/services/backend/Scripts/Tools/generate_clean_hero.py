"""
Gera hero image limpa (fundo branco, sem texto, sem watermark) para Apple LP.

Uso:
    python Scripts/Tools/generate_clean_hero.py --image PATH --out DIR [--num N]
"""

import sys
import os
import argparse
from pathlib import Path
from datetime import datetime

_BACKEND_DIR = Path(__file__).parent.parent.parent.absolute()
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

CLEAN_HERO_PROMPT = (
    "Based on this reference image, generate a new clean product/lifestyle photograph. "
    "KEEP EXACTLY: the floating 3D app icons (chart, hashtag, graph, plus, grid) with their "
    "glowing green-gold metallic finish, the hand holding/surrounding them, the same pose and "
    "composition, soft studio lighting, photorealistic quality. "
    "CHANGE: pure white background (replace any dark gradient or colored background with solid white), "
    "remove ALL text, remove ALL watermarks, remove ALL brand names, remove ALL labels, "
    "remove any UI overlays or button elements. "
    "The result must be a clean, text-free, watermark-free product photo with white background, "
    "Apple-style minimal aesthetic, suitable as a hero image."
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True, help="Caminho da imagem fonte")
    parser.add_argument(
        "--out",
        default=str(Path.home() / "Downloads" / "HeroOutput"),
        help="Diretório de saída",
    )
    parser.add_argument("--num", type=int, default=1, help="Número de variações")
    args = parser.parse_args()

    from App.Features.Tools.Tools.Assets import run_model_logic

    img_path = Path(args.image)
    if not img_path.exists():
        print(f"[ERRO] Arquivo não encontrado: {img_path}")
        sys.exit(1)

    output_dir = Path(args.out)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    for i in range(args.num):
        print(f"\n=== Gerando variação {i + 1}/{args.num} ===")
        result = run_model_logic(
            prompt=CLEAN_HERO_PROMPT,
            extra_args={"image_input": [str(img_path)]},
            return_binary=True,
        )
        if result.get("success"):
            out_filename = f"{img_path.stem}__clean_v{i + 1}__{timestamp}.jpg"
            out_path = output_dir / out_filename
            out_path.write_bytes(result["content"])
            print(f"[OK] Salvo: {out_path}")
        else:
            print(f"[ERRO] {result.get('error', result)}")


if __name__ == "__main__":
    main()

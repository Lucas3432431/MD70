"""
Step 2 do fluxo Notion — substitui os rostinhos do personagem Notion
pelo estilo ilustrado de referencia (NotionBase.png).

Uso:
    python Scripts/Tools/notion_face_replace.py \
      --image <output_step1.jpg> \
      --ref   <NotionBase.png> \
      --out   <pasta_saida>
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

PROMPT = (
    "Image 1 is the CHARACTER FACE REFERENCE. Image 2 is the AD to modify. "
    "TASK: In the AD (image 2), find the illustrated character face and replace it with "
    "an exact pixel-faithful copy of the face from image 1. "
    "Reproduce ONLY what is visible in image 1 — do NOT add, invent or change any element: "
    "no glasses if not in image 1, no eyebrows if not in image 1, no extra details. "
    "Copy only what exists in the reference face and nothing more. "
    "The replaced face must be the same size as the original character in the AD. "
    "NO border, NO outline circle, NO container, NO shadow around the character — "
    "it must sit directly on the background with no frame. "
    "OUTPUT: reproduce the full AD (image 2) layout at exact same dimensions and aspect ratio, "
    "with only the character face swapped. "
    "Do NOT change any text, colors, buttons, logo, checklist, or layout."
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--image", required=True, help="Output do step 1 (imagem com copy MD70)"
    )
    parser.add_argument(
        "--ref", required=True, help="Imagem de referencia de estilo do rosto"
    )
    parser.add_argument(
        "--out",
        default=str(Path.home() / "Downloads" / "MD70" / "Output" / "Notion"),
    )
    args = parser.parse_args()

    from App.Features.Tools.Tools.Assets import run_model_logic

    img = Path(args.image)
    ref = Path(args.ref)
    for p in [img, ref]:
        if not p.exists():
            print(f"[ERRO] Arquivo nao encontrado: {p}")
            sys.exit(1)

    output_dir = Path(args.out)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    print(f"Gerando face-replace: {img.name} + ref {ref.name} ...")
    from PIL import Image as PILImage
    from math import gcd

    with PILImage.open(str(img)) as im:
        w, h = im.size
        g = gcd(w, h)
        aspect = f"{w//g}:{h//g}"
    print(f"Aspect ratio detectado: {aspect} ({w}x{h})")

    # ref primeiro para dar prioridade ao estilo do rosto
    result = run_model_logic(
        prompt=PROMPT,
        extra_args={"image_input": [str(ref), str(img)], "aspect_ratio": aspect},
        return_binary=True,
    )

    if result.get("success"):
        out_path = output_dir / f"{img.stem}__face_replace__{timestamp}.jpg"
        out_path.write_bytes(result["content"])
        print(f"[OK] Salvo: {out_path}")
    else:
        print(f"[ERRO] {result.get('error', result)}")


if __name__ == "__main__":
    main()

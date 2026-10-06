#!/usr/bin/env python3
"""
Converte todos os .png e .jpg/.jpeg para .webp em um diretório.

Uso (dentro do container ou com python3):
  python3 convert_to_webp.py [--keep] [diretório]

  --keep   mantém os originais após conversão (padrão: remove)
  dir      caminho alvo (padrão: /app/../frontend/public)

Exemplos:
  python3 convert_to_webp.py
  python3 convert_to_webp.py --keep
  python3 convert_to_webp.py /app/static/media
"""

import argparse
import sys
from pathlib import Path
from PIL import Image

EXTENSIONS = {".png", ".jpg", ".jpeg"}
QUALITY = 85


def convert(src: Path, keep: bool) -> tuple[int, int] | None:
    dst = src.with_suffix(".webp")
    if dst.exists():
        print(f"  ⟳ já existe, pulando: {dst.name}")
        return None

    size_before = src.stat().st_size
    img = Image.open(src)

    # Preservar transparência para PNG; JPEG não tem alpha
    if src.suffix.lower() == ".png" and img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
    else:
        img = img.convert("RGB")

    img.save(dst, "WEBP", quality=QUALITY, method=6)
    size_after = dst.stat().st_size
    saved = size_before - size_after

    print(
        f"  ✔ {src.name} → {dst.name} | "
        f"{size_before // 1024}KB → {size_after // 1024}KB "
        f"(economia: {saved // 1024}KB)"
    )

    if not keep:
        src.unlink()

    return size_before, size_after


def main():
    parser = argparse.ArgumentParser(description="Converte imagens para WebP")
    parser.add_argument("directory", nargs="?", help="Diretório alvo")
    parser.add_argument("--keep", action="store_true", help="Manter originais")
    args = parser.parse_args()

    if args.directory:
        target = Path(args.directory)
    else:
        # Padrão: public/ do frontend, relativo ao repositório
        target = Path(__file__).resolve().parents[4] / "services/frontend/public"

    if not target.exists():
        print(f"✖ Diretório não encontrado: {target}", file=sys.stderr)
        sys.exit(1)

    print(f"▶ Diretório : {target}")
    print(f"▶ Qualidade : {QUALITY}")
    print(f"▶ Originais : {'mantidos' if args.keep else 'removidos após conversão'}")
    print()

    converted, skipped = 0, 0
    total_before, total_after = 0, 0

    for src in sorted(target.rglob("*")):
        if src.suffix.lower() not in EXTENSIONS:
            continue
        result = convert(src, args.keep)
        if result is None:
            skipped += 1
        else:
            before, after = result
            total_before += before
            total_after += after
            converted += 1

    print()
    print("─" * 42)
    print(f"  Convertidos : {converted}")
    print(f"  Pulados     : {skipped} (já eram .webp)")
    if converted:
        saved = total_before - total_after
        print(f"  Antes       : {total_before // 1024} KB")
        print(f"  Depois      : {total_after // 1024} KB")
        print(f"  Economia    : {saved // 1024} KB ({100 * saved // total_before}%)")
    if not args.keep and converted:
        print(f"  Originais   : removidos")
    print("─" * 42)


if __name__ == "__main__":
    main()

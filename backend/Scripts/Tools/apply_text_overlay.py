"""
Aplica overlay de texto sobre imagem clean com layout fixo.
Garante que duas variações de título tenham layout idêntico.

Uso:
    python apply_text_overlay.py --image PATH --title "Texto" --subtitle "Texto" --cta "Texto" --out DIR --label nome
"""

import argparse
import os
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("[ERRO] Instale Pillow: pip install Pillow")
    sys.exit(1)

# ── Layout constants (fração da largura/altura da imagem) ────────────────────
BLOCK_LEFT_MARGIN = 0.04  # margem esquerda do bloco
BLOCK_TOP_MARGIN = 0.30  # início vertical do bloco
BLOCK_WIDTH_FRAC = 0.54  # largura do bloco em relação à imagem
BLOCK_PADDING_X = 0.035  # padding horizontal interno
BLOCK_PADDING_Y = 0.025  # padding vertical interno
BLOCK_RADIUS = 18  # border-radius em px

TITLE_SIZE_FRAC = 0.052  # tamanho do título (fração da altura)
SUBTITLE_SIZE_FRAC = 0.028  # tamanho do subtítulo
CTA_SIZE_FRAC = 0.026  # tamanho do CTA

TITLE_COLOR = "#FFFFFF"
SUBTITLE_COLOR = "#E8E8E8"
CTA_BG_COLOR = "#FFFFFF"
CTA_TEXT_COLOR = "#1A1A2E"
BLOCK_BG_COLOR = (26, 26, 46, 220)  # dark navy, alpha 220/255

GAP_TITLE_SUB = 0.018  # gap entre título e subtítulo (fração altura)
GAP_SUB_CTA = 0.030  # gap entre subtítulo e CTA
CTA_PADDING_X = 28
CTA_PADDING_Y = 14
CTA_RADIUS = 10


def _load_font(size: int):
    """Tenta carregar uma fonte do sistema. Fallback para default."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Arial.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _load_font_regular(size: int):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _wrap_text(text: str, font, max_width: int, draw: ImageDraw.ImageDraw) -> list:
    """Quebra texto em linhas para caber em max_width."""
    words = text.split()
    lines = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _text_block_height(draw, title, subtitle, cta, fonts, max_text_w, img_h) -> int:
    """Calcula altura total do bloco de texto."""
    f_title, f_sub, f_cta = fonts
    pad_y = int(img_h * BLOCK_PADDING_Y)
    gap_ts = int(img_h * GAP_TITLE_SUB)
    gap_sc = int(img_h * GAP_SUB_CTA)

    title_lines = _wrap_text(title, f_title, max_text_w, draw)
    sub_lines = _wrap_text(subtitle, f_sub, max_text_w, draw)

    def line_h(font, lines):
        if not lines:
            return 0
        bbox = draw.textbbox((0, 0), lines[0], font=font)
        return (bbox[3] - bbox[1]) * len(lines) + (len(lines) - 1) * 4

    title_h = line_h(f_title, title_lines)
    sub_h = line_h(f_sub, sub_lines)
    cta_bbox = draw.textbbox((0, 0), cta, font=f_cta)
    cta_h = cta_bbox[3] - cta_bbox[1] + CTA_PADDING_Y * 2

    total = pad_y + title_h + gap_ts + sub_h + gap_sc + cta_h + pad_y
    return total


def _rounded_rect(draw, xy, radius, fill):
    x0, y0, x1, y1 = xy
    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=fill)


def apply_overlay(
    image_path: str, title: str, subtitle: str, cta: str, output_path: str
) -> None:
    img = Image.open(image_path).convert("RGBA")
    W, H = img.size

    title_size = max(24, int(H * TITLE_SIZE_FRAC))
    sub_size = max(14, int(H * SUBTITLE_SIZE_FRAC))
    cta_size = max(13, int(H * CTA_SIZE_FRAC))

    f_title = _load_font(title_size)
    f_sub = _load_font_regular(sub_size)
    f_cta = _load_font(cta_size)
    fonts = (f_title, f_sub, f_cta)

    block_w = int(W * BLOCK_WIDTH_FRAC)
    pad_x = int(W * BLOCK_PADDING_X)
    pad_y = int(H * BLOCK_PADDING_Y)
    max_text_w = block_w - pad_x * 2

    # Medir altura do bloco
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    block_h = _text_block_height(probe, title, subtitle, cta, fonts, max_text_w, H)

    bx0 = int(W * BLOCK_LEFT_MARGIN)
    by0 = int(H * BLOCK_TOP_MARGIN)
    bx1 = bx0 + block_w
    by1 = by0 + block_h

    # Overlay layer
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    _rounded_rect(draw, (bx0, by0, bx1, by1), BLOCK_RADIUS, BLOCK_BG_COLOR)

    # Desenhar texto
    cx = bx0 + pad_x
    cy = by0 + pad_y

    # Título
    title_lines = _wrap_text(title, f_title, max_text_w, draw)
    for line in title_lines:
        draw.text((cx, cy), line, font=f_title, fill=TITLE_COLOR)
        bbox = draw.textbbox((cx, cy), line, font=f_title)
        cy += (bbox[3] - bbox[1]) + 4
    cy += int(H * GAP_TITLE_SUB)

    # Subtítulo
    sub_lines = _wrap_text(subtitle, f_sub, max_text_w, draw)
    for line in sub_lines:
        draw.text((cx, cy), line, font=f_sub, fill=SUBTITLE_COLOR)
        bbox = draw.textbbox((cx, cy), line, font=f_sub)
        cy += (bbox[3] - bbox[1]) + 4
    cy += int(H * GAP_SUB_CTA)

    # CTA button
    cta_bbox = draw.textbbox((0, 0), cta, font=f_cta)
    cta_w = cta_bbox[2] - cta_bbox[0] + CTA_PADDING_X * 2
    cta_h_btn = cta_bbox[3] - cta_bbox[1] + CTA_PADDING_Y * 2
    _rounded_rect(draw, (cx, cy, cx + cta_w, cy + cta_h_btn), CTA_RADIUS, CTA_BG_COLOR)
    draw.text(
        (cx + CTA_PADDING_X, cy + CTA_PADDING_Y), cta, font=f_cta, fill=CTA_TEXT_COLOR
    )

    # Compor
    result = Image.alpha_composite(img, overlay).convert("RGB")
    result.save(output_path, "JPEG", quality=95)
    print(f"[OK] Salvo em: {output_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--subtitle", required=True)
    parser.add_argument("--cta", default="Ver como funciona")
    parser.add_argument("--out", required=True)
    parser.add_argument("--label", required=True)
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(args.image).stem
    out_path = str(out_dir / f"{stem}__{args.label}.jpg")

    apply_overlay(args.image, args.title, args.subtitle, args.cta, out_path)


if __name__ == "__main__":
    main()

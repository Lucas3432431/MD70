"""
Gera variações de imagens de templates usando Gemini via Vertex AI.

Uso:
    python generate_template_variations.py [--image PATH] [--variations N] [--hrp auto|true|false] [--num N] [--out DIR]
    python generate_template_variations.py --image PATH --mode brand-replace --hook "Hook" --sub "Sub" --cta "CTA" --variations N --out DIR
    python generate_template_variations.py --image PATH --mode color --variations N --out DIR

    --image      : caminho direto para uma imagem (substitui a lista padrão de templates)
    --variations : número de variações a gerar (alias de --num)
    --hrp        : 'auto' (detecta pelo nome), 'true' (todas com pessoa), 'false' (todas sem pessoa)
    --num        : número de variações por imagem (default: 5 para hrp=true, 1 para hrp=false)
    --out        : diretório de saída (default: ~/Downloads/Templates/Variations/)
    --mode       : ethnic | structural | brand-replace | color
                   ethnic       → substitui pessoa por variação étnica (usa --hrp true)
                   structural   → variação estrutural sutil (cor, luz, prop)
                   brand-replace→ preserva composição, substitui marca/copy por MD70 PT-BR
                   color        → variações de paleta de cores, preserva tudo mais
    --hook       : (brand-replace) headline principal em PT-BR
    --sub        : (brand-replace) subtítulo em PT-BR
    --cta        : (brand-replace) call-to-action em PT-BR
    --ratios     : aspect ratios a gerar, separados por vírgula (default: "9:16,1:1")
                   ex: --ratios "1:1"  ou  --ratios "9:16,1:1,16:9"
"""

import sys
import os
import argparse
from pathlib import Path
from datetime import datetime

# ── Resolver sys.path para importar o app ────────────────────────────────────
_BACKEND_DIR = Path(__file__).parent.parent.parent.absolute()
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# ── Templates ────────────────────────────────────────────────────────────────
TEMPLATES_DIR = Path.home() / "Downloads" / "Templates"

TEMPLATES = [
    {"file": TEMPLATES_DIR / "AcessorioShoot.jpg", "hrp": False},
    {"file": TEMPLATES_DIR / "AcessoriosTemplate2.jpg", "hrp": False},
    {"file": TEMPLATES_DIR / "AcessoriosTemplate3.jpg", "hrp": False},
    {"file": TEMPLATES_DIR / "FashionTemplate.jpg", "hrp": True},
    {"file": TEMPLATES_DIR / "FashionTemplate2.jpg", "hrp": True},
    {"file": TEMPLATES_DIR / "FashionTemplate3.jpg", "hrp": True},
]

# ── Prompts base ──────────────────────────────────────────────────────────────

HRP_ETHNIC_VARIATIONS = [
    (
        "Parda brasileira — pele morena clara a média, tom quente com subtom dourado-acobreado, "
        "cabelo castanho escuro a preto com volume natural e cachos suaves ou lisos, "
        "olhos castanho-escuros, lábios cheios com subtom rosado-terroso, "
        "nariz de base levemente mais larga, sobrancelhas escuras e expressivas"
    ),
    (
        "Mulher ruiva de pele muito clara — pele porcelana quase translúcida com sardas delicadas espalhadas "
        "pelo nariz e maçãs do rosto, cabelo ruivo-cobre intenso ou vermelho-cenoura com brilho dourado natural, "
        "olhos verdes ou âmbar com cílios ruivos, lábios rosados naturais, "
        "sobrancelhas de tom cobre-louro fino mas definidas"
    ),
    (
        "Melanismo intenso — pele negra profunda de tom azul-ébano com alto brilho natural, "
        "poros mínimos e acabamento acetinado, cabelo black power volumoso ou trança nagô estilizada, "
        "olhos negros com íris quase invisível de tão escura, lábios escuros com subtom roxo-violeta, "
        "sobrancelhas pretas densas e definidas, traços marcados de grande impacto visual"
    ),
    (
        "Albinismo — pele creme-marfim uniforme sem manchas, cabelo branco-platinado liso ou ondulado "
        "com brilho sedoso, olhos cinza-avelã ou âmbar claro com irís delicada, "
        "sobrancelhas branco-louro quase imperceptíveis mas presentes, "
        "lábios rosa-pálido natural, aparência etérea de grande beleza"
    ),
    (
        "Asiática — pele bege-marfim uniforme com subtom neutro a rosado, "
        "cabelo preto liso de alto brilho com caimento perfeito, "
        "olhos amendoados castanho-escuros ou pretos com pálpebra superior leve, "
        "nariz pequeno com ponta arredondada, lábios rosados e proporcionais, "
        "sobrancelhas pretas retas e bem definidas"
    ),
]

HRP_TRUE_BASE = (
    "Generate a professional photorealistic variation of this image. "
    "PRESERVE EXACTLY — do NOT change under any circumstances: camera angle, focal distance, "
    "depth of field, framing and composition, lighting setup (direction, intensity, shadows, "
    "highlights, catchlights), specular reflections on skin and surfaces, background environment "
    "and all props, clothing style and color palette, overall mood and color grading, "
    "image quality and resolution, skin pore texture level, oiliness/moisture quality, "
    "subtle asymmetry that makes the model look human and real. "
    "\n\nREPLACE ONLY the model/person, applying this ethnic variation: {ethnicity}. "
    "\n\nCRITICAL rules for the replacement: "
    "— Same apparent age as the original model (if original looks 30, new model must look 30) "
    "— Same pose: body posture, hand position, head tilt, gaze direction, all identical "
    "— Same facial expression and micro-expression: smile intensity, eye openness, jaw tension "
    "— Same skin texture quality: pore visibility, moisture sheen, micro-highlight distribution "
    "— Same specular catchlights in the eyes "
    "— Natural human asymmetry preserved — perfect symmetry is forbidden "
    "— Nail color and lip color should harmonize naturally with the new skin tone "
    "— The result must look like an editorial fashion photograph with extreme photographic realism "
    "— Do NOT make the model look like a painting, render or illustration under any circumstance"
)

HRP_FALSE_BASE = (
    "Generate a professional variation of this image. "
    "PRESERVE EXACTLY — do NOT change: composition, layout, lighting, color palette, "
    "all graphic elements, typography, product positioning, background style, "
    "mood and visual identity. "
    "Apply a fresh creative variation: adjust ONE of the following while keeping everything else identical — "
    "background color tone (shift slightly warmer or cooler), prop styling (substitute one prop for a similar one), "
    "or light direction (shift key light 15–30 degrees). "
    "No people involved. Result must be photorealistic, print-quality, professional advertising standard."
)

REFORMAT_BASE = (
    "Redesign this advertising image for the target aspect ratio as if it had been created "
    "natively for that format from scratch. "
    "\n\nPRESERVE EXACTLY — do NOT change under any circumstances: every word of text and its "
    "font style, all brand identity elements, the person/subject, product, color palette, "
    "lighting mood, and overall visual style. "
    "PRESERVE ALL overlays, cards, and background treatments exactly — if the original has a "
    "white semi-transparent card or frosted-glass layer behind the text, reproduce it with the "
    "same shape, opacity, color, border-radius, and shadow; do NOT remove or simplify it. "
    "\n\nCOMPOSITION REDESIGN rules — this is NOT a simple crop or scale: "
    "— Redistribute and reposition all elements (text blocks, person, product, decorative "
    "elements) to fill the new format naturally and with strong visual hierarchy "
    "— Text size relative to the image frame must be EQUAL TO OR LARGER than in the original — "
    "never smaller; headlines must remain dominant and highly legible "
    "— The person/subject must occupy the same or greater visual weight in the new format "
    "— Tighten vertical spacing between elements to fit the shorter format; do NOT leave dead "
    "space where elements used to be "
    "— Background should fill seamlessly; extend or crop edges as needed but keep the "
    "background style identical "
    "— The final image must have the same visual impact and commercial energy as the original: "
    "same punch, same legibility, same hierarchy — adapted to the new canvas "
    "\n\nSTRICT RULES — violations are forbidden: "
    "— NEVER mirror, flip, or reverse the composition — every element must stay on the exact "
    "same side (left or right) as in the original; if the person is on the right, keep on right "
    "— Do NOT invent, add, or duplicate any element not present in the original — no extra dots, "
    "icons, badges, overlays, or UI elements; element count must match the original exactly "
    "\n\nResult must be photorealistic, professional advertising standard, print-quality. "
    "The viewer should not realize this is a reformatted version — it must look purpose-built "
    "for this aspect ratio."
)

BRAND_REPLACE_BASE = (
    "Generate a professional advertising image based on this reference. "
    "PRESERVE EXACTLY — do NOT change under any circumstances: the overall composition and layout, "
    "3D objects and their shapes, lighting direction and intensity, depth and perspective, "
    "background style and environment, visual hierarchy and spacing, "
    "overall color palette and mood, image quality and resolution. "
    "\n\nREPLACE all visible text and brand identifiers with MD70 brand content: "
    '— Main headline (Hook): "{hook}" '
    '— Sub-headline: "{sub}" '
    '— Call-to-action button or text: "{cta}" '
    "— Brand name anywhere: MD70 "
    "\n\nCLEAN BACKGROUND — the final image must have a clean background with no residual text: "
    "— Remove any small secondary text elements that are not the hook, sub-headline, or CTA "
    "— Remove any subtle background text overlays or semi-transparent text layers "
    "— Fill cleaned areas seamlessly to match the surrounding background — no ghosting, no blank patches "
    "— The only visible text in the final image must be the hook, sub-headline, and CTA provided above "
    "\n\nTYPOGRAPHY rules: "
    "— Match the original font weight, size hierarchy, and text placement exactly "
    "— Use clean, modern sans-serif typography consistent with the original style "
    "— All text must be in Brazilian Portuguese exactly as provided above — do not translate or alter "
    "— Ensure all text is perfectly legible, crisp, and anti-aliased "
    "\n\nResult must be photorealistic, professional advertising standard, print-quality. "
    "No creative liberties beyond the specified text replacement and watermark removal."
)

COLOR_DIRECTIONS = [
    # ── MD70 brand (índices 0–1, use --num 1 ou --num 2 para isolar) ──
    "clean white (#ffffff) background with vivid orange (#f97316) as dominant CTA and brand accent, "
    "cyan-600 (#0891b2) for trust and secondary elements, dark gray (#111827) body text — "
    "MD70 brand identity: direct, results-driven, zero friction",
    "deep off-black (#0f172a) background with vivid orange (#f97316) glow on key CTA elements, "
    "cyan-600 (#0891b2) highlights on secondary elements, pure white text — "
    "MD70 dark: premium contrast, high-energy, e-commerce urgency",
    # ── Genéricos ──────────────────────────────────────────────────────────
    "deep midnight blue (#0a0f2e) background with electric cyan (#00d4ff) and violet (#8b5cf6) neon accents — dark cyberpunk premium feel",
    "rich obsidian (#0d0d0d) background with emerald green (#10b981) and gold (#f59e0b) accents — luxury fintech feel",
    "deep navy (#0f172a) background with hot pink (#ec4899) and electric purple (#a855f7) neon accents — bold digital agency feel",
    "warm charcoal (#1a1a2e) background with vivid orange (#f97316) and coral (#fb7185) accents — energetic growth feel",
    "pure white (#ffffff) background with deep blue (#1e40af) and subtle silver (#94a3b8) accents — clean Apple-style premium feel",
]

COLOR_BASE = (
    "Generate a professional color palette variation of this advertising image. "
    "PRESERVE EXACTLY — do NOT change under any circumstances: composition and layout, "
    "3D object shapes and positions, all visible text content and typography (font, size, weight, placement), "
    "lighting structure (key light direction, shadow placement), image quality and resolution, "
    "all graphic elements and their spatial relationships. "
    "\n\nAPPLY this specific color direction across the entire image: {color_direction}. "
    "\n\nCOLOR APPLICATION rules: "
    "— Replace the dominant background color with the new palette "
    "— Shift all glow, neon, and accent colors to match the new palette "
    "— Adjust material and surface colors of 3D objects to harmonize with the new palette "
    "— Keep relative contrast ratios so all text and elements remain visible and legible "
    "— Lighting color temperature should shift to match the new palette mood "
    "— The result must feel like a different colorway of the exact same design "
    "\n\nResult must be professional advertising quality, photorealistic, print-ready."
)

# brand-replace-color: faz brand-replace E color shift em um único passo
BRAND_REPLACE_COLOR_BASE = (
    "Generate a professional advertising image based on this reference. "
    "\n\nSTEP 1 — CLEAN: Remove everything that is not part of the core visual composition: "
    "— Remove ALL original brand names, logos, icons, and visual marks — every single one "
    "— Remove ALL original text: headlines, subtitles, body copy, CTAs, captions, small print "
    "— Remove any small secondary text elements, background text overlays, semi-transparent text layers "
    "— Remove any URL, domain, social handle, photographer credit, or attribution "
    "— Fill every cleaned area seamlessly to match the surrounding background — zero ghosting, zero blank patches "
    "\n\nSTEP 2 — ADD MD70 content in place of everything removed: "
    '— Main headline: "{hook}" '
    '— Sub-headline: "{sub}" '
    '— Call-to-action: "{cta}" '
    "— Brand name: MD70 "
    "— All text must be in Brazilian Portuguese exactly as written above "
    "— Match the original font weight and size hierarchy — place text in the same positions as the originals "
    "— Text must be perfectly legible, crisp, and anti-aliased "
    "\n\nSTEP 3 — APPLY color palette: {color_direction}. "
    "— Replace dominant background color with the new palette "
    "— Shift all glow, neon, and accent colors to match "
    "— Adjust 3D object surface colors to harmonize "
    "— Preserve all contrast ratios so text and elements remain visible "
    "— Lighting color temperature shifts to match the palette mood "
    "\n\nPRESERVE EXACTLY throughout all steps: overall composition and layout, "
    "3D object shapes and positions, lighting structure, depth and perspective, "
    "visual hierarchy, image quality and resolution. "
    "\n\nResult must be photorealistic, professional advertising standard, print-quality."
)


DEFAULT_RATIOS = [("9:16", "9x16"), ("1:1", "1x1")]


def parse_ratios(ratios_str: str) -> list:
    result = []
    for r in ratios_str.split(","):
        r = r.strip()
        if r:
            label = r.replace(":", "x")
            result.append((r, label))
    return result or DEFAULT_RATIOS


def generate_variations(
    templates: list,
    num_variations: int,
    output_dir: Path,
    hrp_override: str = "auto",
    mode: str = "auto",
    hook: str = "",
    sub: str = "",
    cta: str = "",
    ratios: list = None,
    prompts_file: str = None,
):
    import json as _json
    from App.Features.Tools.Tools.Assets import run_model_logic

    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    active_ratios = ratios if ratios else DEFAULT_RATIOS

    # Carregar prompts customizados para modo "custom"
    custom_prompts_global: list = []
    if prompts_file:
        with open(prompts_file, encoding="utf-8") as _pf:
            custom_prompts_global = _json.load(_pf)
    # Injetar nos templates quando modo custom
    if mode == "custom" or (mode == "auto" and custom_prompts_global):
        for t in templates:
            if not t.get("custom_prompts"):
                t["custom_prompts"] = custom_prompts_global

    total_ok = 0
    total_fail = 0

    for template in templates:
        img_path = Path(template["file"])
        hrp = template["hrp"]

        if hrp_override == "true":
            hrp = True
        elif hrp_override == "false":
            hrp = False

        if not img_path.exists():
            print(f"[SKIP] Arquivo não encontrado: {img_path}")
            continue

        # Resolver modo efetivo
        effective_mode = mode
        if effective_mode == "auto":
            effective_mode = "ethnic" if hrp else "structural"

        print(f"\n{'='*60}")
        print(f"Processando: {img_path.name}  (mode={effective_mode})")
        print(f"{'='*60}")

        # Montar lista de variações conforme modo
        custom_prompts = template.get("custom_prompts", [])
        if effective_mode == "ethnic":
            pool = HRP_ETHNIC_VARIATIONS
            n = min(num_variations or 5, len(pool))
            variations = [(i, pool[i]) for i in range(n)]
        elif effective_mode in ("color", "brand-replace-color"):
            n = min(num_variations or len(COLOR_DIRECTIONS), len(COLOR_DIRECTIONS))
            variations = [(i, COLOR_DIRECTIONS[i]) for i in range(n)]
        elif effective_mode == "reformat":
            variations = [(0, None)]
        elif effective_mode == "custom":
            variations = [(i, p) for i, p in enumerate(custom_prompts)]
        else:
            n = num_variations or 1
            variations = [(i, None) for i in range(n)]

        for var_idx, payload in variations:
            if effective_mode == "ethnic":
                prompt = HRP_TRUE_BASE.format(ethnicity=payload)
                label = f"ethnic_v{var_idx + 1}"
            elif effective_mode == "color":
                prompt = COLOR_BASE.format(color_direction=payload)
                label = f"color_v{var_idx + 1}"
            elif effective_mode == "brand-replace":
                if not hook:
                    print("  [ERRO] --mode brand-replace requer --hook, --sub e --cta")
                    total_fail += 1
                    break
                prompt = BRAND_REPLACE_BASE.format(hook=hook, sub=sub, cta=cta)
                label = f"brand_v{var_idx + 1}"
            elif effective_mode == "brand-replace-color":
                if not hook:
                    print(
                        "  [ERRO] --mode brand-replace-color requer --hook, --sub e --cta"
                    )
                    total_fail += 1
                    break
                prompt = BRAND_REPLACE_COLOR_BASE.format(
                    hook=hook, sub=sub, cta=cta, color_direction=payload
                )
                label = f"brc_v{var_idx + 1}"
            elif effective_mode == "reformat":
                prompt = REFORMAT_BASE
                label = "reformat"
            elif effective_mode == "custom":
                entry = payload if isinstance(payload, dict) else {"prompt": payload}
                prompt = entry.get("prompt", "")
                label = entry.get("label", f"custom_v{var_idx + 1}")
                if not prompt:
                    print(f"  [SKIP] Variação {var_idx + 1} sem prompt definido")
                    total_fail += 1
                    continue
            else:
                prompt = HRP_FALSE_BASE
                label = f"structural_v{var_idx + 1}"

            print(f"  [{var_idx + 1}/{len(variations)}] Gerando variação '{label}'...")

            for aspect_ratio, ratio_label in active_ratios:
                print(f"    → aspect_ratio={aspect_ratio}")
                result = run_model_logic(
                    prompt=prompt,
                    extra_args={
                        "image_input": [str(img_path)],
                        "aspect_ratio": aspect_ratio,
                    },
                    return_binary=True,
                )

                if result.get("success"):
                    stem = img_path.stem
                    out_filename = f"{stem}__{label}__{ratio_label}__{timestamp}.jpg"
                    out_path = output_dir / out_filename
                    out_path.write_bytes(result["content"])
                    print(f"    [OK] Salvo em: {out_path}")
                    total_ok += 1
                else:
                    print(
                        f"    [ERRO] {aspect_ratio}: {result.get('error', 'Falha desconhecida')}"
                    )
                    total_fail += 1

    print(f"\n{'='*60}")
    print(f"Concluído: {total_ok} geradas, {total_fail} falhas")
    print(f"Saída: {output_dir}")
    print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(
        description="Gera variações de templates de imagem via Gemini Vertex AI"
    )
    parser.add_argument(
        "--image",
        type=str,
        default=None,
        help="Caminho direto para uma imagem (substitui a lista padrão de templates)",
    )
    parser.add_argument(
        "--variations",
        type=int,
        default=None,
        dest="num",
        help="Número de variações a gerar (alias de --num)",
    )
    parser.add_argument(
        "--hrp",
        choices=["auto", "true", "false"],
        default="auto",
        help="Has Realistic Person: auto=detecta pelo nome, true=todas, false=nenhuma",
    )
    parser.add_argument(
        "--num",
        type=int,
        default=None,
        help="Número de variações por imagem (default: 5 para ethnic, 5 para color, 1 para structural/brand-replace)",
    )
    parser.add_argument(
        "--out",
        type=str,
        default=str(Path.home() / "Downloads" / "Templates" / "Variations"),
        help="Diretório de saída",
    )
    parser.add_argument(
        "--only",
        type=str,
        default=None,
        help="Processar apenas um template específico (nome parcial, ex: Fashion)",
    )
    parser.add_argument(
        "--mode",
        choices=[
            "auto",
            "ethnic",
            "structural",
            "brand-replace",
            "color",
            "brand-replace-color",
            "reformat",
            "custom",
        ],
        default="auto",
        help=(
            "Modo de geração: "
            "ethnic=variação étnica de pessoa, "
            "structural=variação sutil de estrutura, "
            "brand-replace=substituir marca/copy por MD70 PT-BR, "
            "color=variações de paleta (preserva texto existente), "
            "brand-replace-color=substitui marca/copy E aplica nova paleta em um passo só, "
            "reformat=adapta imagem existente para novos aspect ratios sem mudanças criativas"
        ),
    )
    parser.add_argument(
        "--hook",
        type=str,
        default="",
        help="(brand-replace) Headline principal em PT-BR",
    )
    parser.add_argument(
        "--sub",
        type=str,
        default="",
        help="(brand-replace) Subtítulo em PT-BR",
    )
    parser.add_argument(
        "--cta",
        type=str,
        default="",
        help="(brand-replace) Call-to-action em PT-BR",
    )
    parser.add_argument(
        "--ratios",
        type=str,
        default="9:16,1:1",
        help="Aspect ratios a gerar, separados por vírgula (default: '9:16,1:1'). Ex: '1:1' ou '9:16,1:1,16:9'",
    )
    parser.add_argument(
        "--prompts-file",
        type=str,
        default=None,
        dest="prompts_file",
        help=(
            "JSON com lista de variações para --mode custom. "
            'Cada item pode ser uma string (prompt) ou objeto {"label": "v2", "prompt": "..."}.'
        ),
    )
    args = parser.parse_args()

    if args.image:
        img_path = Path(args.image)
        if not img_path.exists():
            print(f"[ERRO] Arquivo não encontrado: {img_path}")
            sys.exit(1)
        name_lower = img_path.name.lower()
        hrp_auto = any(k in name_lower for k in ("fashion", "person", "model", "hrp"))
        templates = [{"file": img_path, "hrp": hrp_auto}]
    else:
        templates = TEMPLATES
        if args.only:
            templates = [
                t for t in templates if args.only.lower() in str(t["file"]).lower()
            ]
            if not templates:
                print(f"Nenhum template encontrado com '{args.only}'")
                sys.exit(1)

    output_dir = Path(args.out)
    generate_variations(
        templates,
        args.num,
        output_dir,
        hrp_override=args.hrp,
        mode=args.mode,
        hook=args.hook,
        sub=args.sub,
        cta=args.cta,
        ratios=parse_ratios(args.ratios),
        prompts_file=args.prompts_file,
    )


if __name__ == "__main__":
    main()

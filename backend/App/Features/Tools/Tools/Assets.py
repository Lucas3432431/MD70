import os
import json
import argparse
import requests
import time
import sys
import base64
from datetime import datetime
from pathlib import Path
from PIL import Image
from io import BytesIO
from typing import Optional, Dict, Any
from threading import Thread, Lock
from concurrent.futures import ThreadPoolExecutor, as_completed
from google.oauth2 import service_account
from google.auth.transport.requests import Request
from App.Core.Logs import debug, error
from App.Core.Settings.Settings import get_google_cloud_config, get_openai_api_key

# ============================================================================
# CONSTANTES GLOBAIS
# ============================================================================

# ── Limites e timeouts ───────────────────────────────────────────────────────
COPY_MAX_BATCH_ASSETS = 4  # limite máximo de assets por batch (Vertex AI quota)
BATCH_MAX_WORKERS = 3  # workers paralelos no ThreadPoolExecutor
REQUEST_TIMEOUT = 240  # timeout da chamada Vertex AI (segundos)
IMAGE_DOWNLOAD_TIMEOUT = 15  # timeout de download de imagens de referência (segundos)
TOKEN_TTL_SECONDS = 3500  # TTL do access token GCP (segundos; < 3600 para margem)
IMAGE_LOAD_MAX_RETRIES = 3  # tentativas para carregar imagem de referência
IMAGE_LOAD_RETRY_DELAY = 2  # delay entre tentativas de load (segundos)
RETRY_429_DELAYS = [5, 15, 30, 60] + [60] * 15  # escalonamento de retry em 429

# ── Vertex AI / GCP ──────────────────────────────────────────────────────────
VERTEX_AI_DEFAULT_LOCATION = "us-central1"
VERTEX_AI_MODEL = "gemini-3.1-flash-image"
VERTEX_AI_ENDPOINT_TEMPLATE = (
    "https://aiplatform.googleapis.com/v1/projects/{project_id}"
    "/locations/global/publishers/google/models/{model}:generateContent"
)
GCP_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
CREDITS_PROVIDER = "google-vertex"

# ── Prefixos de log ──────────────────────────────────────────────────────────
LOG_GEMINI = "[GEMINI]"
LOG_IMAGEN = "[IMAGEN]"
LOG_GEN_DOC = "[GEN-DOC]"
LOG_BATCH = "[BATCH]"
LOG_ASSETS_DEBUG = "[ASSETS-DEBUG]"

# ── Labels do assembler de prompt ────────────────────────────────────────────
PROMPT_LABEL_SCENE_SUBJECT = "Scene subject"
PROMPT_LABEL_PERSON = "Person"
PROMPT_LABEL_PEOPLE = "People"
PROMPT_MODEL_AGE = "age"
PROMPT_MODEL_SKIN = "skin color"
PROMPT_MODEL_STYLE = "wearing"
PROMPT_MODEL_MOISTURE = "skin moisture"
PROMPT_LABEL_CAMERA_ANGLE = "Camera angle"
PROMPT_LABEL_POSE = "Pose"
PROMPT_LABEL_COMP_GRID = "Composition grid"
PROMPT_LABEL_SETTING = "Setting"
PROMPT_LABEL_ENV_ELEMENTS = "Environment elements"
PROMPT_LABEL_OBJ_FOCUSED = "in sharp focus"
PROMPT_LABEL_OBJ_BLURRED = "softly out of focus"
PROMPT_LABEL_COLORS = "Colors"
PROMPT_LABEL_BG_TYPE = "Background style"
PROMPT_LABEL_SAT_CONTRAST = "Saturation/contrast"
PROMPT_LABEL_HARMONY = "Color harmony"
PROMPT_LABEL_LIGHTING = "Lighting"
PROMPT_LABEL_EMOTION = "Emotion & style"
PROMPT_LABEL_NEGATIVE = "NEGATIVE"
PROMPT_NEGATIVE_ADDITIONALLY = "Additionally"

# ── Mapeamento descritivo de moisture (para injeção no prompt de texto) ───────
MOISTURE_DESC: dict[str, str] = {
    "natural_glow": "light natural skin oiliness — subtle satin luminance, no excess shine",
    "dewy": "dewy luminous skin — visibly hydrated and radiant",
    "wet": "wet skin — high-gloss surface with visible moisture",
}

# ── Directivas de tipo de fundo ───────────────────────────────────────────────
BG_TYPE_DIRECTIVE: dict[str, str] = {
    "color": "Pure color background — clean neutral tone, zero environmental distractions",
    "outside": "Outdoor setting — strong natural presence of plants, open sky, water or landscape",
    "window": (
        "Interior with natural light from window — intense daylight flooding the space. "
        "The background must feel alive and visually layered: "
        "include at least one indoor plant (monstera, fiddle-leaf fig, palm, potted plant on shelf or floor) "
        "adding organic green contrast to the neutral walls. "
        "Introduce blue or cool-toned accents through framed artwork, abstract prints, architectural panels, "
        "or decorative objects on shelving — creating chromatic depth between warm neutrals, cool blue and living green. "
        "Add ambient lighting fixtures (sconces, LED strips, or pendant lights) casting warm directional glow. "
        "Avoid bare plain walls — every surface visible in frame must contribute to visual richness and contrast."
    ),
    "black_white": "Full black and white photographic treatment — monochromatic tonal range, no color",
    "product_closeup": "Product close-up — shallow depth of field with subject in sharp focus, background fully blurred or dark studio",
}

# ── Directivas de enquadramento ───────────────────────────────────────────────
FRAMING_DIRECTIVE: dict[str, str] = {
    "HyperCloseUpShot": (
        "Hyper close-up — extreme macro of ONE single specific point of the main subject. "
        "Do NOT frame the whole subject — choose and frame only ONE isolated micro-detail: "
        "eye, mouth, lips, nose, ear, eyelashes, bracelet, necklace, ring, watch face, "
        "collar, fingernail, fabric texture, or any single element. "
        "The chosen detail fills 100% of the frame. Zero full-body or full-face context visible."
    ),
    "CloseUpShot": (
        "Close-up — main subject fills minimum 90% of the frame from edge to edge. "
        "Head and upper chest (or product) dominate the composition with no dead space or background gaps. "
        "Subject commands the entire frame."
    ),
    "HighAngleShot": (
        "High angle — camera positioned above the subject looking downward. "
        "Range: from slightly above eye-level to near-overhead. "
        "Subject is seen from above, creating depth and scale contrast with the environment below."
    ),
    "LowAngleShot": (
        "Low angle — camera positioned below the subject looking upward. "
        "Range: from partially below eye-level to completely floor-level (camera at foot/ground level). "
        "Subject towers over the viewer, projecting dominance and presence."
    ),
    "MidBodyShot": (
        "Mid-body shot — subject framed from waist to head. "
        "Upper body and face visible, lower body cut off at waist or hip level."
    ),
    "EyeLevelShot": (
        "Eye-level — camera at exact eye height of the subject. "
        "Neutral, direct, frontal perspective. Creates intimacy and equality between viewer and subject."
    ),
    "POVShot": (
        "First-person POV — camera assumes the subject's perspective. "
        "Viewer sees exactly what the subject sees. Hands may be partially visible in lower frame. "
        "Fully immersive experiential composition."
    ),
    "OverheadDroneShot": (
        "Overhead/drone — camera directly above shooting straight down (90 degree nadir). "
        "Subject seen flat from above. Geometric, top-down architectural composition."
    ),
    "DetailShot": (
        "Detail shot — tight crop on a specific fragment of the subject or product, "
        "including some surrounding context. Reveals texture, material, craftsmanship "
        "or a meaningful element of the subject."
    ),
    "UGC": (
        "UGC (User Generated Content) style — handheld self-shot or casual close-up, completely unposed. "
        "Appears as if the user grabbed their phone and filmed themselves using, applying, or wearing the product "
        "in real life. Framing is tight and intimate: face and product together, slightly off-center, imperfect "
        "angles welcome. Natural ambient lighting (window light, room lamp) — no professional setup, no studio "
        "backdrop, no model posing. Genuine reaction or live demonstration — raw, relatable authenticity."
    ),
    "Studio": (
        "Studio — controlled studio setting: clean professional background, intentional lighting setup. "
        "Subject and product are the sole focus of the frame. No environmental distractions."
    ),
}

# ── Studio HRP directives by product category ───────────────────────────────
STUDIO_HRP_CATEGORY_DIRECTIVE: dict[str, str] = {
    "cosmetics": (
        "STUDIO SUBJECT FOCUS: Hyper close-up on the model's face — camera pressed tight against the face. "
        "The cosmetic product is visible in its application area (lips, eyes, skin, cheeks). "
        "Face fills 80–100% of the frame. No full-body visible. Skin texture and product result are the hero."
    ),
    "accessories": (
        "STUDIO SUBJECT FOCUS: Hyper close-up of the model actively wearing the accessory — "
        "wrist, neck, ear, or hand in the foreground with the accessory as the hero element. "
        "Product fills 60–80% of frame; the relevant body part provides natural context only."
    ),
    "clothing": (
        "STUDIO SUBJECT FOCUS: Full-body confident fashion pose — strong editorial stance, purposeful attitude. "
        "Man or woman presenting the garment with intention. Fashion editorial energy: straight posture, "
        "defined lines, camera at mid-body or eye level. The garment must read clearly from shoulder to hem."
    ),
}

# ── Directivas auto-injetadas ────────────────────────────────────────────────
SKIN_AUTO_INJECT = (
    "Skin: hyper-realistic skin with visible pores, natural asymmetry, "
    "micro-highlight catchlights and shadow micro-variations across the face"
)
MODEL_ATTRACTION_INJECT = (
    "Facial beauty standard: models must have conventionally attractive facial features — "
    "symmetrical face, clean skin, well-defined features. Age-accurate: a 40-year-old must look 40 "
    "but with the best standard facial appearance for that age."
)
GLOBAL_QUALITY_INJECT = (
    "Image quality directive: render with high color saturation and strong tonal contrast — "
    "rich, vivid colors that command attention, deep shadows and bright highlights creating clear visual separation. "
    "No flat, desaturated or washed-out tones. Every element in frame must pop with visual presence. "
    "Shot quality equivalent to a high-end commercial photography campaign."
)
NEGATIVE_BASE = (
    "Do NOT include any text, typography, words, captions, labels, subtitles, "
    "headlines, CTA buttons, arrows, icons, logos, watermarks, borders, frames, "
    "UI elements, interface mockups, graphic overlays, or any design elements "
    "superimposed on the scene. Pure photographic composition only — "
    "the image must be clean for external text and graphic injection."
)
BRAND_IDENTITY_INJECT = (
    "BRAND IDENTITY REQUIRED: The product must appear with its original label, packaging, "
    "and visual branding fully intact and legible. All text, logos, color blocks, and graphic "
    "elements printed on the product label or packaging must be rendered accurately and clearly "
    "in the final image. Do NOT alter, blur, stylize, or omit any product labeling or brand markings."
)
REFERENCE_FIDELITY_INJECT = (
    "REFERENCE IMAGE FIDELITY — MANDATORY: Maintain 100% visual fidelity to the reference image. "
    "Do NOT add, remove, replace, or modify any product element, detail, label, packaging, shape, "
    "color, texture, or visual component present in the reference image — unless you have been "
    "explicitly instructed to do so in this prompt. Apply only the specific adjustment requested. "
    "Every other visual aspect must be reproduced exactly as it appears in the reference image. "
    "This rule applies regardless of image type, scene, or style."
)

# ── Asset filename ────────────────────────────────────────────────────────────
ASSET_FILENAME_PREFIX = "asset_gemini"
ASSET_FILENAME_EXT = ".jpg"
ASSET_DL_FILENAME_PREFIX = "asset"

# ── Mensagens de erro ────────────────────────────────────────────────────────
ERR_NO_DB = "Database manager not configured"
ERR_NO_GCP_PROJECT = "GOOGLE_CLOUD_PROJECT não configurado em .env"
ERR_NO_GCP_CREDS = "GOOGLE_CREDENTIALS_PRIVATE_KEY não definida no .env"
ERR_TOKEN_FAILED = "Erro ao obter token Vertex AI: {}"
ERR_429_PERSISTENT = (
    "Vertex AI 429 persistente após {} tentativas — "
    "feature core offline. Verifique quotas no GCP."
)
ERR_EMPTY_RESPONSE = "Resposta vazia da API"
ERR_NO_CANDIDATES_KEY = "Chave 'candidates' não encontrada na resposta"
ERR_NO_IMAGES_GENERATED = "Nenhuma imagem foi gerada (candidates vazio)"
ERR_UNRECOGNIZED_FORMAT = "Formato de resposta não reconhecido"
ERR_NO_IMAGE_IN_RESPONSE = "Não conseguiu extrair imagem da resposta Gemini"
ERR_BATCH_EMPTY = "requests_list vazio"
ERR_NO_ASSETS = "Document has no assets to generate"
ERR_DOC_NOT_FOUND = "Copywriting document {} not found"
ERR_INSUFFICIENT_CREDITS = (
    "Créditos insuficientes: necessário {:.6f}, disponível {:.6f}"
)
ERR_PROMPT_EMPTY = "prompt vazio"
ERR_UNKNOWN_GENERATION = "Erro desconhecido"
ERR_GENERATION_FAILED = "Generation failed"

# ── SQL ───────────────────────────────────────────────────────────────────────
SQL_SELECT_COPYWRITING_DOC = """
    SELECT content FROM documents
    WHERE document_id = :document_id
    AND tool_type IN ('copywriting', 'catalog', 'social_media')
"""
SQL_UPDATE_DOCUMENT_CONTENT = """
    UPDATE documents SET content = :content, updated_at = CURRENT_TIMESTAMP
    WHERE document_id = :document_id
"""

# ── Mensagens human_mode ─────────────────────────────────────────────────────
HM_BATCH_HEADER = "🚀 GEMINI 3 Pro Image com Vertex AI + Múltiplas Referências"
HM_LOADING_STATUS = "Gerando imagem com referências"


def assemble_asset_prompt(
    prompt_data: dict, should_keep_brand_identity: bool = True
) -> str:
    """
    Assembles a final text prompt string from a structured prompt object.
    Injects skin directives automatically when has_realistic_people=True.
    Injects brand identity directive when should_keep_brand_identity=True.
    """
    if isinstance(prompt_data, str):
        return prompt_data

    parts = []

    description = prompt_data.get("description", "")
    if description:
        parts.append(description)

    # subject_context + models (people specs)
    if prompt_data.get("has_realistic_people"):
        subject_context = prompt_data.get("subject_context", "")
        if subject_context:
            parts.append(f"{PROMPT_LABEL_SCENE_SUBJECT}: {subject_context}")

        models = prompt_data.get("models", [])
        if models:
            model_descs = []
            for i, m in enumerate(models):
                m_parts = []
                if m.get("sex"):
                    m_parts.append(m["sex"])
                if m.get("age"):
                    m_parts.append(f"{PROMPT_MODEL_AGE} {m['age']}")
                if m.get("skin_color"):
                    m_parts.append(f"{PROMPT_MODEL_SKIN}: {m['skin_color']}")
                if m.get("style"):
                    m_parts.append(f"{PROMPT_MODEL_STYLE}: {m['style']}")
                if m.get("skin_texture_moisture"):
                    moisture_key = m["skin_texture_moisture"]
                    moisture_text = MOISTURE_DESC.get(moisture_key, moisture_key)
                    m_parts.append(f"{PROMPT_MODEL_MOISTURE}: {moisture_text}")
                if m_parts:
                    model_descs.append(
                        f"{PROMPT_LABEL_PERSON} {i + 1}: {', '.join(m_parts)}"
                    )
            if model_descs:
                parts.append(f"{PROMPT_LABEL_PEOPLE} — " + "; ".join(model_descs))

        pose = prompt_data.get("pose", "")
        if pose:
            parts.append(f"{PROMPT_LABEL_POSE}: {pose}")

    comp = prompt_data.get("composition", {})
    angle = comp.get("angle", "")
    grid = comp.get("grid", "")
    if angle or grid:
        comp_parts = []
        if angle:
            angle_desc = FRAMING_DIRECTIVE.get(angle, angle)
            if angle == "HyperCloseUpShot":
                main_object = comp.get("main_object", "")
                if main_object:
                    angle_desc = angle_desc + f" Focus exclusively on: {main_object}."
            comp_parts.append(f"{PROMPT_LABEL_CAMERA_ANGLE}: {angle_desc}")
        if grid:
            comp_parts.append(f"{PROMPT_LABEL_COMP_GRID}: {grid}")
        parts.append(". ".join(comp_parts))

        # Studio + HRP: inject category-specific subject focus directive
        if angle == "Studio" and prompt_data.get("has_realistic_people"):
            product_category = comp.get("product_category", "").lower()
            _studio_directive = STUDIO_HRP_CATEGORY_DIRECTIVE.get(product_category)
            if _studio_directive:
                parts.append(_studio_directive)

    env = prompt_data.get("environment", {})
    place = env.get("place", "")
    objects = env.get("objects", "")
    if place:
        parts.append(f"{PROMPT_LABEL_SETTING}: {place}")
    if objects:
        if isinstance(objects, list):
            obj_parts = []
            for obj in objects:
                if isinstance(obj, dict):
                    item = obj.get("item", "")
                    if item:
                        focus = obj.get("focus")
                        if focus is True:
                            obj_parts.append(f"{item} ({PROMPT_LABEL_OBJ_FOCUSED})")
                        elif focus is False:
                            obj_parts.append(f"{item} ({PROMPT_LABEL_OBJ_BLURRED})")
                        else:
                            obj_parts.append(item)
                elif isinstance(obj, str):
                    obj_parts.append(obj)
            if obj_parts:
                parts.append(f"{PROMPT_LABEL_ENV_ELEMENTS}: {', '.join(obj_parts)}")
        else:
            parts.append(f"{PROMPT_LABEL_ENV_ELEMENTS}: {objects}")

    colors = prompt_data.get("colors", {})
    color_parts = []

    # bg_type injetado como directiva antes das cores
    bg_data = colors.get("background", {})
    bg_type = bg_data.get("bg_type", "") if isinstance(bg_data, dict) else ""
    if bg_type and bg_type in BG_TYPE_DIRECTIVE:
        parts.append(f"{PROMPT_LABEL_BG_TYPE}: {BG_TYPE_DIRECTIVE[bg_type]}")

    for role in ["background", "subject", "accent"]:
        role_data = colors.get(role, {})
        if isinstance(role_data, dict) and role_data.get("hex"):
            hex_str = ", ".join(role_data["hex"])
            detail = role_data.get("detail", "")
            if detail:
                color_parts.append(f"{role}: {hex_str} — {detail}")
            else:
                color_parts.append(f"{role}: {hex_str}")
    sat_contrast = colors.get("saturation_contrast", "")
    harmony = colors.get("harmony", "")
    if sat_contrast:
        color_parts.append(f"{PROMPT_LABEL_SAT_CONTRAST}: {sat_contrast}")
    if harmony:
        color_parts.append(f"{PROMPT_LABEL_HARMONY}: {harmony}")
    if color_parts:
        parts.append(f"{PROMPT_LABEL_COLORS} — " + "; ".join(color_parts))

    illumination = prompt_data.get("illumination", "")
    if illumination:
        parts.append(f"{PROMPT_LABEL_LIGHTING}: {illumination}")

    emotion_style = prompt_data.get("emotion_style", "")
    if emotion_style:
        parts.append(f"{PROMPT_LABEL_EMOTION}: {emotion_style}")

    # Auto-inject skin + attraction directives when people are present
    if prompt_data.get("has_realistic_people"):
        parts.append(SKIN_AUTO_INJECT)
        parts.append(MODEL_ATTRACTION_INJECT)

    # Brand identity — inject when should_keep_brand_identity=True
    if should_keep_brand_identity:
        parts.append(BRAND_IDENTITY_INJECT)

    # Global quality — sempre injetado independente do tipo de imagem
    parts.append(GLOBAL_QUALITY_INJECT)

    # Negative — base sempre injetado + campo adicional do agente
    negative_extra = prompt_data.get("negative_prompt", "")
    negative_full = (
        f"{NEGATIVE_BASE} {PROMPT_NEGATIVE_ADDITIONALLY}: {negative_extra}"
        if negative_extra
        else NEGATIVE_BASE
    )
    parts.append(f"{PROMPT_LABEL_NEGATIVE} — {negative_full}")

    return ". ".join(parts)


# ============================================================================
# 1. Configurações de Ambiente
script_dir = os.path.dirname(os.path.abspath(__file__))

# Variável global para armazenar o token de acesso
_access_token = None
_token_expiry = None


def get_vertex_ai_token():
    """
    Obtém token de acesso para Vertex AI REST API usando as credenciais do .env.
    """
    global _access_token, _token_expiry

    if _access_token and _token_expiry and time.time() < _token_expiry:
        return _access_token

    try:
        gcp_config = get_google_cloud_config()
        credentials_info = gcp_config.get("credentials_info", {})
        if not credentials_info.get("private_key"):
            raise ValueError(ERR_NO_GCP_CREDS)

        credentials = service_account.Credentials.from_service_account_info(
            credentials_info, scopes=GCP_SCOPES
        )
        credentials.refresh(Request())
        _access_token = credentials.token
        _token_expiry = time.time() + TOKEN_TTL_SECONDS
        debug(f"{LOG_IMAGEN} Token Vertex AI obtido com sucesso")
        return _access_token
    except Exception as e:
        raise ValueError(ERR_TOKEN_FAILED.format(e))


def loading_animation(start_time, status="Processando"):
    chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    idx = 0
    while True:
        elapsed = time.time() - start_time
        sys.stdout.write(f"\r{chars[idx % len(chars)]} {status}... [{elapsed:.1f}s]")
        sys.stdout.flush()
        idx += 1
        yield
        time.sleep(0.1)


def get_image_dimensions(image_input):
    """
    Detecta dimensões de uma imagem.

    Returns:
        tuple (width, height) ou None se falhar
    """
    try:
        if str(image_input).startswith(("http://", "https://")):
            res = requests.get(image_input, timeout=IMAGE_DOWNLOAD_TIMEOUT)
            img = Image.open(BytesIO(res.content))
            return img.size
        elif os.path.exists(image_input):
            img = Image.open(image_input)
            return img.size
    except Exception:
        pass
    return None


def calculate_aspect_ratio(width, height):
    """Calcula razão de aspecto (width:height mantendo proporção)"""
    from math import gcd

    g = gcd(width, height)
    return (width // g, height // g)


def resolve_image_input(image_input, chat_id=None, user_id=None):
    """
    Resolve image input - pode ser URL, caminho local, attachment ID ou asset UUID.
    Retorna conteúdo binário e dimensões.

    Args:
        image_input: URL, caminho local, attachment ID ou asset UUID
        chat_id: ID da conversa (para resolver attachment IDs)
        user_id: ID do usuário (para resolver attachment IDs)

    Returns:
        Dicionário com dados de imagem e dimensões
    """
    try:
        dimensions = None
        image_bytes = None

        # Se é data URI (base64), decodificar diretamente
        if str(image_input).startswith("data:"):
            import base64 as _b64

            try:
                _, encoded = str(image_input).split(",", 1)
                image_bytes = _b64.b64decode(encoded)
                return {"bytes": image_bytes, "dimensions": None}
            except Exception:
                return None

        # Se é URL, baixa e converte para bytes
        if str(image_input).startswith(("http://", "https://")):
            dimensions = get_image_dimensions(image_input)
            res = requests.get(image_input, timeout=IMAGE_DOWNLOAD_TIMEOUT)
            image_bytes = res.content
            return {"bytes": image_bytes, "dimensions": dimensions}

        # Se é arquivo local, lê conteúdo
        if os.path.exists(image_input):
            dimensions = get_image_dimensions(image_input)
            with open(image_input, "rb") as f:
                image_bytes = f.read()
            return {"bytes": image_bytes, "dimensions": dimensions}

        # Se parece ser UUID de asset gerado — fallback caso agente passe UUID em vez de URL
        if (
            "-" in str(image_input)
            and len(str(image_input)) == 36
            and chat_id
            and user_id
        ):
            try:
                from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager as _DBM
                from App.Core.Utils.TempTokenStore import generate as _gen_token
                from App.Core.Settings.Settings import load_config as _load_cfg

                asset_row = _DBM.fetch_one(
                    """SELECT storage_path FROM assets
                       WHERE asset_id = :id AND chat_id = :cid AND user_id = :uid LIMIT 1""",
                    {"id": image_input, "cid": chat_id, "uid": user_id},
                )
                if asset_row:
                    _cfg = _load_cfg()
                    _pub = _cfg.get("public_url", "").rstrip("/")
                    if _pub:
                        _token = _gen_token(attachment_id=image_input, user_id=user_id)
                        _asset_url = f"{_pub}/api/chat/{chat_id}/attachment/{image_input}/view?token={_token}"
                        res = requests.get(_asset_url, timeout=IMAGE_DOWNLOAD_TIMEOUT)
                        return {
                            "bytes": res.content,
                            "dimensions": get_image_dimensions(_asset_url),
                        }
            except Exception as _e:
                print(f"{LOG_ASSETS_DEBUG} Erro ao buscar asset UUID: {_e}")

        # Fallback: FileHandler (outros tipos de ID)
        if chat_id and user_id:
            try:
                from App.Core.Services.Common.FileHandler import FileHandler

                handler = FileHandler()
                resolved_url = handler.get_file_url(image_input, chat_id, user_id)
                if resolved_url:
                    dimensions = get_image_dimensions(resolved_url)
                    res = requests.get(resolved_url, timeout=IMAGE_DOWNLOAD_TIMEOUT)
                    image_bytes = res.content
                    return {"bytes": image_bytes, "dimensions": dimensions}
            except Exception:
                pass

        # Se chegou aqui e parece ser URL, tenta baixar
        if str(image_input).startswith(("http://", "https://")):
            try:
                res = requests.get(image_input, timeout=IMAGE_DOWNLOAD_TIMEOUT)
                image_bytes = res.content
                dimensions = get_image_dimensions(image_input)
                return {"bytes": image_bytes, "dimensions": dimensions}
            except Exception as e:
                print(
                    f"{LOG_ASSETS_DEBUG} Erro ao baixar URL '{image_input[:80]}...': {type(e).__name__}: {e}"
                )
                debug(f"{LOG_ASSETS_DEBUG} Erro ao baixar URL: {e}")
                pass

        print(
            f"{LOG_ASSETS_DEBUG} resolve_image_input retornando None para: {image_input[:80]}..."
        )
        debug(f"{LOG_ASSETS_DEBUG} resolve_image_input retornando None")
        return None
    except Exception as e:
        print(f"[ERRO] Falha ao resolver imagem: {e}")
        return None


def download_file(url, filename=None, return_binary=False):
    """
    Baixa arquivo da URL.
    """
    if not url or not str(url).startswith("http"):
        return None

    if not filename:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{ASSET_DL_FILENAME_PREFIX}_{timestamp}{ASSET_FILENAME_EXT}"

    if return_binary:
        res = requests.get(url, timeout=IMAGE_DOWNLOAD_TIMEOUT)
        return filename, res.content
    else:
        full_path = os.path.join(script_dir, filename)
        res = requests.get(url, timeout=IMAGE_DOWNLOAD_TIMEOUT)
        with open(full_path, "wb") as f:
            f.write(res.content)
        return full_path


def _run_openai_fallback(
    prompt: str, return_binary: bool = False
) -> Optional[Dict[str, Any]]:
    """
    Fallback para geração de imagem usando OpenAI DALL-E 3 via REST API.
    Utilizado quando o Gemini 3 Pro (Vertex AI) falha ou está indisponível.
    """
    try:
        api_key = get_openai_api_key()
        if not api_key:
            debug("[OPENAI-FALLBACK] API key não encontrada")
            return None

        debug(f"[OPENAI-FALLBACK] Iniciando geração DALL-E 3: {prompt[:100]}...")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        # DALL-E 3 HD é o modelo mais potente da OpenAI para imagem
        payload = {
            "model": "dall-e-3",
            "prompt": prompt,
            "size": "1024x1024",
            "quality": "hd",
            "n": 1,
        }

        response = requests.post(
            "https://api.openai.com/v1/images/generations",
            headers=headers,
            json=payload,
            timeout=120,
        )

        if response.status_code != 200:
            error(
                f"[OPENAI-FALLBACK] Erro API OpenAI ({response.status_code}): {response.text}"
            )
            return None

        data = response.json()
        if "data" in data and len(data["data"]) > 0:
            image_url = data["data"][0]["url"]
            debug(f"[OPENAI-FALLBACK] Imagem gerada com sucesso: {image_url[:100]}...")

            # Baixar imagem
            img_res = requests.get(image_url, timeout=IMAGE_DOWNLOAD_TIMEOUT)
            if img_res.status_code == 200:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"asset_openai_{timestamp}.jpg"

                if return_binary:
                    return {
                        "success": True,
                        "filename": filename,
                        "content": img_res.content,
                        "url": None,
                        "provider": "openai",
                    }
                else:
                    full_path = os.path.join(script_dir, filename)
                    with open(full_path, "wb") as f:
                        f.write(img_res.content)
                    return {
                        "success": True,
                        "path": full_path,
                        "url": None,
                        "provider": "openai",
                    }

        return None
    except Exception as e:
        error(f"[OPENAI-FALLBACK] Erro crítico: {e}")
        return None


def run_model_logic(
    prompt,
    extra_args=None,
    human_mode=False,
    api_key=None,
    return_binary=False,
    chat_id=None,
    user_id=None,
    image_input=None,
    isolated_message_id: str = None,
):
    """
    Executa geração de imagem com Gemini 3 Pro Image via Vertex AI REST API com múltiplas referências.

    Args:
        prompt: Descrição do que gerar
        extra_args: Argumentos extras contendo:
                    - image_input: array de caminhos/URLs de imagens de entrada ["img1", "img2", ...]
                    - aspect_ratio: proporção da imagem
                    - width, height: dimensões (opcionais)
        human_mode: Se True, mostra mensagens
        api_key: Ignorado (usa Vertex AI credentials)
        return_binary: Se True, retorna conteúdo binário
        chat_id: ID da conversa (para resolver attachment IDs)
        user_id: ID do usuário (para resolver attachment IDs)
        image_input: Argumentos diretos para image_input (pode ser string ou array)

    Returns:
        Dicionário com resultado da geração
    """
    # Carregar config do Settings.py
    gcp_config = get_google_cloud_config()
    project_id = gcp_config.get("project_id")
    location = gcp_config.get("location", VERTEX_AI_DEFAULT_LOCATION)

    if not project_id:
        return {"success": False, "error": ERR_NO_GCP_PROJECT}

    # Obter token de acesso
    try:
        access_token = get_vertex_ai_token()
    except Exception as e:
        return {"success": False, "error": str(e)}

    # Configurações
    images_loaded = []
    aspect_ratio = None

    # Extrair aspect_ratio de extra_args se fornecido
    if extra_args and "aspect_ratio" in extra_args:
        aspect_ratio = extra_args["aspect_ratio"]
        print(f"{LOG_GEMINI} aspect_ratio extraído de extra_args: {aspect_ratio}")
        debug(f"{LOG_GEMINI} aspect_ratio extraído de extra_args: {aspect_ratio}")
    else:
        print(f"{LOG_GEMINI} Nenhum aspect_ratio fornecido")
        debug(f"{LOG_GEMINI} Nenhum aspect_ratio fornecido")

    # Log
    print(f"{LOG_GEMINI} extra_args recebido: {extra_args}")
    print(f"{LOG_GEMINI} image_input (arg direto): {image_input}")
    debug(f"{LOG_GEMINI} extra_args recebido: {extra_args}")
    debug(f"{LOG_GEMINI} image_input (arg direto): {image_input}")

    # Prioridade: image_input direto > extra_args["image_input"]
    final_image_input = image_input or (extra_args and extra_args.get("image_input"))

    print(f"{LOG_GEMINI} final_image_input: {final_image_input}")
    debug(f"{LOG_GEMINI} final_image_input: {final_image_input}")

    if final_image_input:
        image_input_array = final_image_input
        print(
            f"{LOG_GEMINI} image_input_array type: {type(image_input_array)}, value: {image_input_array}"
        )
        debug(
            f"{LOG_GEMINI} image_input_array type: {type(image_input_array)}, value: {image_input_array}"
        )

        # Garantir que seja lista
        if not isinstance(image_input_array, list):
            image_input_array = [image_input_array]
            print(f"{LOG_GEMINI} Convertido para lista: {image_input_array}")
            debug(f"{LOG_GEMINI} Convertido para lista: {image_input_array}")

        print(f"{LOG_GEMINI} Total de imagens a processar: {len(image_input_array)}")
        debug(f"{LOG_GEMINI} Total de imagens a processar: {len(image_input_array)}")

        max_retries = IMAGE_LOAD_MAX_RETRIES
        retry_delay = IMAGE_LOAD_RETRY_DELAY

        for idx, image_path in enumerate(image_input_array):
            print(f"{LOG_GEMINI} [#{idx+1}] Processando: {image_path}")
            debug(f"{LOG_GEMINI} [#{idx+1}] Processando: {image_path}")

            # Se é URL HTTP/HTTPS, usar file_uri diretamente (Gemini faz download)
            if isinstance(image_path, str) and image_path.startswith(
                ("http://", "https://")
            ):
                print(
                    f"{LOG_GEMINI} [#{idx+1}] URL HTTP detectada - usando file_uri direto"
                )
                debug(
                    f"{LOG_GEMINI} [#{idx+1}] URL HTTP detectada - usando file_uri direto"
                )
                images_loaded.append({"type": "url", "url": image_path})
                continue

            # Se é data URI (base64), decodificar e usar como bytes
            if isinstance(image_path, str) and image_path.startswith("data:"):
                import base64 as _b64

                try:
                    _, _enc = image_path.split(",", 1)
                    _img_bytes = _b64.b64decode(_enc)
                    images_loaded.append({"bytes": _img_bytes, "dimensions": None})
                    debug(
                        f"{LOG_GEMINI} [#{idx+1}] Data URI decodificada - {len(_img_bytes)} bytes"
                    )
                    continue
                except Exception as _de:
                    debug(
                        f"{LOG_GEMINI} [#{idx+1}] Falha ao decodificar data URI: {_de}"
                    )

            # Para outros tipos (caminhos locais, attachment IDs), fazer download
            img_data = None
            last_error = None

            # Retry loop
            for retry in range(max_retries):
                try:
                    img_data = resolve_image_input(image_path, chat_id, user_id)
                    if img_data:
                        images_loaded.append(img_data)
                        print(
                            f"{LOG_GEMINI} [#{idx+1}] CARREGADA - bytes: {len(img_data.get('bytes', b''))}"
                        )
                        debug(
                            f"{LOG_GEMINI} [#{idx+1}] CARREGADA - bytes: {len(img_data.get('bytes', b''))}"
                        )
                        break  # Sucesso, sair do retry loop
                    else:
                        last_error = f"resolve_image_input retornou None"
                        if retry < max_retries - 1:
                            print(
                                f"{LOG_GEMINI} [#{idx+1}] Retry {retry+1}/{max_retries-1}: {last_error}"
                            )
                            debug(
                                f"{LOG_GEMINI} [#{idx+1}] Retry {retry+1}/{max_retries-1}: {last_error}"
                            )
                            time.sleep(retry_delay)
                except Exception as e:
                    last_error = str(e)
                    if retry < max_retries - 1:
                        print(
                            f"{LOG_GEMINI} [#{idx+1}] Retry {retry+1}/{max_retries-1}: {last_error}"
                        )
                        debug(
                            f"{LOG_GEMINI} [#{idx+1}] Retry {retry+1}/{max_retries-1}: {last_error}"
                        )
                        time.sleep(retry_delay)

            # Se falhou após todos os retries
            if not img_data:
                error_msg = f"Falha ao carregar imagem #{idx+1} após {max_retries} tentativas: {image_path} ({last_error})"
                print(f"{LOG_GEMINI} {error_msg}")
                debug(f"{LOG_GEMINI} {error_msg}")
                # Cancelar se alguma imagem falhar
                return {"success": False, "error": error_msg}
    else:
        print(f"{LOG_GEMINI} Nenhuma image_input fornecida em extra_args")
        debug(f"{LOG_GEMINI} Nenhuma image_input fornecida em extra_args")

    if human_mode:
        print(f"\n{HM_BATCH_HEADER}")
        print(f"Reference images: {len(images_loaded)}")
        if aspect_ratio:
            print(f"Aspect ratio: {aspect_ratio}")

    start_time = time.time()

    try:
        debug(f"{LOG_GEMINI} Iniciando geração via Vertex AI REST API")
        debug(f"{LOG_GEMINI} Project: {project_id}, Location: {location}")
        debug(f"{LOG_GEMINI} Images loaded: {len(images_loaded)}")
        debug(f"{LOG_GEMINI} Prompt (primeiros 100 chars): {prompt[:100]}")

        if human_mode:
            anim = loading_animation(start_time, status=HM_LOADING_STATUS)

        # Construir request para Vertex AI REST API
        # Modelo: gemini-3.1-flash-image (global-only, suporte a múltiplas imagens + text rendering)

        endpoint = VERTEX_AI_ENDPOINT_TEMPLATE.format(
            project_id=project_id, model=VERTEX_AI_MODEL
        )

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        # Construir parts array com imagens e texto
        parts = []

        # Adicionar imagens como fileData
        if images_loaded and len(images_loaded) > 0:
            debug(
                f"{LOG_GEMINI} Adicionando {len(images_loaded)} imagem(ns) de referência"
            )
            for idx, img_data in enumerate(images_loaded):
                try:
                    # Verificar se é URL ou bytes
                    if img_data.get("type") == "url":
                        # URL - enviar como file_uri (Gemini faz o download)
                        print(
                            f"{LOG_GEMINI} [#{idx+1}] Enviando URL como file_uri: {img_data['url']}"
                        )
                        debug(
                            f"{LOG_GEMINI} [#{idx+1}] Enviando URL como file_uri: {img_data['url']}"
                        )
                        parts.append(
                            {
                                "file_data": {
                                    "mime_type": "image/jpeg",  # Gemini detecta automaticamente, mas precisa ser não-vazio
                                    "file_uri": img_data["url"],
                                }
                            }
                        )
                    else:
                        # Bytes - enviar como inline_data
                        # Detectar MIME type (simplificado - assume JPEG/PNG)
                        img_bytes = img_data["bytes"]
                        if img_bytes.startswith(b"\x89PNG"):
                            mime_type = "image/png"
                        elif img_bytes.startswith(b"\xff\xd8\xff"):
                            mime_type = "image/jpeg"
                        else:
                            mime_type = "image/jpeg"  # fallback

                        img_base64 = base64.b64encode(img_bytes).decode("utf-8")
                        parts.append(
                            {
                                "inline_data": {
                                    "mime_type": mime_type,
                                    "data": img_base64,
                                }
                            }
                        )
                        debug(
                            f"{LOG_GEMINI} [#{idx+1}] Imagem adicionada (MIME: {mime_type}, bytes: {len(img_bytes)})"
                        )
                except Exception as e:
                    debug(f"{LOG_GEMINI} [#{idx+1}] ERRO ao processar imagem: {e}")
                    continue

        # Adicionar prompt como texto
        # Injetar fidelidade visual quando há imagem(ns) de referência, independente do tipo
        if images_loaded:
            prompt = prompt + "\n\n" + REFERENCE_FIDELITY_INJECT
        parts.append({"text": prompt})

        # Construir contents
        contents = [{"role": "user", "parts": parts}]

        # Construir generation_config
        generation_config = {"response_modalities": ["TEXT", "IMAGE"]}

        # Adicionar image_config com aspect_ratio se fornecido (SEM defaults)
        if aspect_ratio:
            generation_config["image_config"] = {"aspect_ratio": aspect_ratio}
            print(f"{LOG_GEMINI} image_config adicionado: aspect_ratio={aspect_ratio}")
            debug(f"{LOG_GEMINI} image_config adicionado: aspect_ratio={aspect_ratio}")

        # Construir body completo
        request_body = {"contents": contents, "generation_config": generation_config}

        debug(f"{LOG_GEMINI} Enviando request para: {endpoint}")
        debug(f"{LOG_GEMINI} Request body keys: {list(request_body.keys())}")
        debug(f"{LOG_GEMINI} Parts count: {len(parts)}")

        # Fazer requisição com retry escalável em 429
        # Delays: 5s, 15s, 30s, 60s, depois 60s × 15 loops (total máx ~19min de espera)
        # Se esgotar todos os retries → exception crítica (feature offline > 2h não tolerada)
        _retry_delays = RETRY_429_DELAYS
        _attempt = 0
        while True:
            response = requests.post(
                endpoint, json=request_body, headers=headers, timeout=REQUEST_TIMEOUT
            )
            debug(f"{LOG_GEMINI} Response status: {response.status_code}")

            if response.status_code == 429:
                if _attempt >= len(_retry_delays):
                    raise Exception(ERR_429_PERSISTENT.format(_attempt + 1))
                _delay = _retry_delays[_attempt]
                debug(
                    f"{LOG_GEMINI} 429 rate limit — aguardando {_delay}s (retry {_attempt + 1}/{len(_retry_delays)})"
                )
                time.sleep(_delay)
                _attempt += 1
                continue

            if response.status_code != 200:
                error_text = response.text
                debug(f"{LOG_GEMINI} Error response: {error_text}")
                raise Exception(
                    f"Vertex AI API retornou {response.status_code}: {error_text[:200]}"
                )

            break  # 200 OK

        response_data = response.json()
        debug(
            f"{LOG_GEMINI} Response keys: {list(response_data.keys()) if isinstance(response_data, dict) else 'not dict'}"
        )
        debug(f"{LOG_GEMINI} Response sample: {str(response_data)[:500]}")

        if human_mode:
            print("\n")

        # Processar resposta
        # Resposta do Gemini contém "candidates"
        if not response_data:
            debug(f"{LOG_GEMINI} Response vazia!")
            raise Exception(ERR_EMPTY_RESPONSE)

        if "candidates" not in response_data:
            debug(f"{LOG_GEMINI} Chaves na resposta: {list(response_data.keys())}")
            raise Exception(ERR_NO_CANDIDATES_KEY)

        if len(response_data["candidates"]) == 0:
            raise Exception(ERR_NO_IMAGES_GENERATED)

        candidate = response_data["candidates"][0]
        debug(
            f"{LOG_GEMINI} Candidate keys: {list(candidate.keys()) if isinstance(candidate, dict) else 'not dict'}"
        )

        if "content" not in candidate or "parts" not in candidate["content"]:
            raise Exception(ERR_UNRECOGNIZED_FORMAT)

        # Procurar por parte com imagem
        image_bytes = None
        parts = candidate["content"]["parts"]
        debug(f"{LOG_GEMINI} Total de parts na resposta: {len(parts)}")
        for idx, part in enumerate(parts):
            debug(f"{LOG_GEMINI} Part #{idx} keys: {list(part.keys())}")
            # Response uses camelCase inlineData, not snake_case
            if "inlineData" in part:
                img_data = part["inlineData"]
                if "data" in img_data:
                    image_bytes = base64.b64decode(img_data["data"])
                    debug(
                        f"{LOG_GEMINI} Imagem extraída da resposta (bytes: {len(image_bytes)})"
                    )
                    break

        if not image_bytes:
            debug(
                f"{LOG_GEMINI} Resposta completa (primeiros 1000 chars): {str(response_data)[:1000]}"
            )
            raise Exception(ERR_NO_IMAGE_IN_RESPONSE)

        # Retornar resultado
        if return_binary:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{ASSET_FILENAME_PREFIX}_{timestamp}{ASSET_FILENAME_EXT}"

            if human_mode:
                print(f"SUCESSO | {filename} ({len(image_bytes)} bytes)")

            return {
                "success": True,
                "filename": filename,
                "content": image_bytes,
                "url": None,
            }
        else:
            # Salvar no disco
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{ASSET_FILENAME_PREFIX}_{timestamp}{ASSET_FILENAME_EXT}"
            full_path = os.path.join(script_dir, filename)

            with open(full_path, "wb") as f:
                f.write(image_bytes)

            if human_mode:
                print(f"SUCESSO | {full_path}")

            return {"success": True, "path": full_path, "url": None}

    except Exception as e:
        if human_mode:
            print(f"FALHOU GEMINI | {e}")
        error_msg = str(e)
        debug(f"{LOG_GEMINI} ERRO GEMINI: {error_msg}")

        # Tentar Fallback OpenAI (DALL-E 3)
        fallback_res = _run_openai_fallback(prompt, return_binary=return_binary)
        if fallback_res:
            if human_mode:
                print(f"SUCESSO FALLBACK OPENAI")
            return fallback_res

        return {"success": False, "error": error_msg}


def run_model_logic_batch(requests_list, human_mode=False, chat_id=None, user_id=None):
    """
    Executa multiplas geracoes de imagem em paralelo via Vertex AI.
    Otimizado para economizar requisicoes: dispara todos os requests de uma vez e faz polling paralelo.

    Args:
        requests_list: Lista de dicts com:
            {
                "index": 0,
                "prompt": "Descricao...",
                "extra_args": {"aspect_ratio": "9:16", "image_input": [...]},
                "human_mode": False (override local)
            }
        human_mode: Se True, mostra progresso
        chat_id: ID da conversa (para resolver attachment IDs)
        user_id: ID do usuario (para resolver attachment IDs)

    Returns:
        Dicionario com:
        {
            "success": bool,
            "total": int,
            "completed": int,
            "results": [
                {
                    "index": 0,
                    "success": True/False,
                    "url": "https://...",
                    "error": "..." (se falhou)
                }
            ]
        }
    """
    if not requests_list or len(requests_list) == 0:
        return {"success": False, "error": ERR_BATCH_EMPTY}

    debug(f"{LOG_BATCH} Iniciando batch com {len(requests_list)} requisicoes")

    # Lock para thread-safe results
    results_lock = Lock()
    results = {}

    def process_single_request(req_item):
        """Processa um unico request de forma thread-safe"""
        try:
            idx = req_item.get("index")
            prompt = req_item.get("prompt", "")
            extra_args = req_item.get("extra_args", {})
            req_human_mode = req_item.get("human_mode", human_mode)

            if not prompt:
                return {"index": idx, "success": False, "error": ERR_PROMPT_EMPTY}

            if req_human_mode:
                print(f"[BATCH #{idx}] Iniciando geracao...")
                debug(f"[BATCH #{idx}] Geracao iniciada")

            # Chamar run_model_logic (ja existente)
            result = run_model_logic(
                prompt=prompt,
                extra_args=extra_args,
                human_mode=req_human_mode,
                return_binary=False,
                chat_id=chat_id,
                user_id=user_id,
            )

            # Formatar resultado
            if result.get("success"):
                return {
                    "index": idx,
                    "success": True,
                    "url": result.get("url"),
                    "path": result.get("path"),
                }
            else:
                return {
                    "index": idx,
                    "success": False,
                    "error": result.get("error", ERR_UNKNOWN_GENERATION),
                }

        except Exception as e:
            error(f"{LOG_BATCH} Erro ao processar request {req_item.get('index')}: {e}")
            return {"index": req_item.get("index"), "success": False, "error": str(e)}

    # Executar requisicoes em paralelo com ThreadPoolExecutor
    # Max 3 workers simultaneos para nao sobrecarregar (quota do Vertex AI)
    max_workers = min(BATCH_MAX_WORKERS, len(requests_list))

    if human_mode:
        print(
            f"{LOG_BATCH} Disparando {len(requests_list)} requisicoes com {max_workers} workers paralelos"
        )
        debug(
            f"{LOG_BATCH} Disparando {len(requests_list)} requisicoes com {max_workers} workers paralelos"
        )

    completed_count = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submeter todos os jobs
        future_to_idx = {
            executor.submit(process_single_request, req): req.get("index")
            for req in requests_list
        }

        # Processar conforme completam (nao em ordem)
        for future in as_completed(future_to_idx):
            try:
                result = future.result()
                idx = result.get("index")

                with results_lock:
                    results[idx] = result

                completed_count += 1
                status = "OK" if result.get("success") else "ERRO"
                if human_mode:
                    print(
                        f"{LOG_BATCH} Completado {completed_count}/{len(requests_list)} - #{idx}: {status}"
                    )
                    debug(
                        f"{LOG_BATCH} Completado {completed_count}/{len(requests_list)} - #{idx}: {status}"
                    )

            except Exception as e:
                idx = future_to_idx[future]
                error_msg = str(e)
                with results_lock:
                    results[idx] = {"index": idx, "success": False, "error": error_msg}
                completed_count += 1
                error(f"{LOG_BATCH} Erro ao aguardar future #{idx}: {error_msg}")

    # Ordenar resultados por index
    ordered_results = [results[i] for i in range(len(requests_list)) if i in results]

    # Contar sucessos
    successes = sum(1 for r in ordered_results if r.get("success"))

    if human_mode:
        print(f"{LOG_BATCH} CONCLUSAO: {successes}/{len(requests_list)} sucessos")
        debug(f"{LOG_BATCH} CONCLUSAO: {successes}/{len(requests_list)} sucessos")

    return {
        "success": successes == len(requests_list),
        "total": len(requests_list),
        "completed": successes,
        "results": ordered_results,
    }


def generate_from_document(
    document_id: str,
    db_manager,
    chat_id: str = None,
    user_id: str = None,
    human_mode: bool = False,
    isolated_message_id: str = None,
):
    """
    Gera assets para um documento copywriting com validação de créditos.

    Args:
        document_id: UUID do documento copywriting
        db_manager: DatabaseManager instance
        chat_id: ID da conversa (opcional, para resolução de attachments)
        user_id: ID do usuário (obrigatório para validação de créditos)
        human_mode: Se True, mostra progresso

    Returns:
        Dict com:
        {
            "success": bool,
            "generated_assets": [{index, success, asset_url/error}],
            "credits_consumed": float,
            "credits_remaining": float,
            "message": str,
            "error": str (se houver)
        }
    """
    try:
        from App.Features.Credits.CreditsManager import CreditsManager
        from sqlalchemy import text

        if not db_manager:
            return {
                "success": False,
                "error": ERR_NO_DB,
                "generated_assets": [],
                "credits_consumed": 0.0,
                "credits_remaining": 0.0,
            }

        # Abrir sessão e buscar documento
        session = db_manager.get_session()
        try:
            verify_query = text(SQL_SELECT_COPYWRITING_DOC)
            verify_result = session.execute(
                verify_query, {"document_id": document_id}
            ).first()

            if not verify_result:
                return {
                    "success": False,
                    "error": ERR_DOC_NOT_FOUND.format(document_id),
                    "generated_assets": [],
                    "credits_consumed": 0.0,
                    "credits_remaining": 0.0,
                }

            copy_data = json.loads(verify_result[0]) if verify_result[0] else {}
            assets = copy_data.get("assets", [])

            if len(assets) == 0:
                return {
                    "success": False,
                    "error": ERR_NO_ASSETS,
                    "generated_assets": [],
                    "credits_consumed": 0.0,
                    "credits_remaining": 0.0,
                }

            # FILTRAR ASSETS PENDENTES (status != "done")
            pending_assets = []
            for idx, asset_data in enumerate(assets):
                if asset_data.get("status") == "done":
                    debug(
                        f"{LOG_GEN_DOC} Asset {idx} já gerado (status=done), ignorando"
                    )
                    continue
                if not asset_data.get("prompt"):
                    debug(f"{LOG_GEN_DOC} Asset {idx} sem prompt, ignorando")
                    continue
                pending_assets.append(idx)

            # Limitar a COPY_MAX_BATCH_ASSETS
            if len(pending_assets) > COPY_MAX_BATCH_ASSETS:
                debug(
                    f"{LOG_GEN_DOC} {len(pending_assets)} assets, limitando a {COPY_MAX_BATCH_ASSETS}"
                )
                pending_assets = pending_assets[:COPY_MAX_BATCH_ASSETS]

            if len(pending_assets) == 0:
                all_done = all(a.get("status") == "done" for a in assets)
                empty_prompts = [
                    i
                    for i, a in enumerate(assets)
                    if not a.get("prompt") and a.get("status") != "done"
                ]
                if all_done:
                    msg = "Todos os assets já foram gerados (status=done)."
                elif empty_prompts:
                    msg = (
                        f"Assets {empty_prompts} têm prompt vazio — não é possível gerar sem prompt. "
                        "Use update() para preencher o campo 'prompt' em cada asset ou recrie o documento copywriting "
                        "com os campos variation_N contendo o prompt estruturado."
                    )
                else:
                    msg = "No pending assets to generate"
                return {
                    "success": True if all_done else False,
                    "generated_assets": [],
                    "credits_consumed": 0.0,
                    "credits_remaining": 0.0,
                    "message": msg,
                }

            # PRE-CHECK CRÉDITOS
            if user_id:
                (
                    has_credits,
                    cost_centavos,
                    available,
                ) = CreditsManager.check_and_consume_for_batch_assets(
                    user_id,
                    num_assets=len(pending_assets),
                    isolated_chat_id=chat_id,
                    isolated_message_id=isolated_message_id,
                )
                if not has_credits:
                    cost_credits = CreditsManager.centavos_to_credits(cost_centavos)
                    return {
                        "success": False,
                        "error": ERR_INSUFFICIENT_CREDITS.format(
                            cost_credits, float(available)
                        ),
                        "generated_assets": [],
                        "credits_consumed": 0.0,
                        "credits_remaining": float(available),
                    }

            # ── Helper: construir extra_args para um asset ───────────────────
            def _build_extra_args(asset_data):
                _raw_doc_ratio = copy_data.get("aspect_ratio")
                _doc_ratio_default = (
                    _raw_doc_ratio[0]
                    if isinstance(_raw_doc_ratio, list) and _raw_doc_ratio
                    else str(_raw_doc_ratio)
                    if _raw_doc_ratio
                    else "9:16"
                )
                extra = {"aspect_ratio": asset_data.get("format") or _doc_ratio_default}
                ref_imgs = asset_data.get("reference_imgs") or []
                if ref_imgs:
                    extra["image_input"] = ref_imgs
                return extra

            import uuid as _uuid
            from App.Core.Crunch.Storage.StorageManager import (
                StorageManager as _StorageManager,
            )

            # Um variation_id por asset — cada geração é independente (um formato por vez)
            variation_ids = {idx: str(_uuid.uuid4()) for idx in pending_assets}

            # Pre-fetch client_id via users
            from sqlalchemy import text as _text

            _client_id = None
            if user_id:
                _client_row = session.execute(
                    _text("SELECT client_id FROM users WHERE user_id = :uid"),
                    {"uid": user_id},
                ).first()
                _client_id = str(_client_row[0]) if _client_row else None

            generated_assets = []
            successes = 0

            for idx in pending_assets:
                asset_data = assets[idx]
                _should_keep_brand = copy_data.get("should_keep_brand_identity", True)
                assembled_prompt = assemble_asset_prompt(
                    asset_data.get("prompt", ""),
                    should_keep_brand_identity=_should_keep_brand,
                )
                extra_args = _build_extra_args(asset_data)

                debug(
                    f"{LOG_GEN_DOC} Gerando asset idx={idx} format={asset_data.get('format')}"
                )

                result = run_model_logic(
                    prompt=assembled_prompt,
                    extra_args=extra_args,
                    human_mode=human_mode,
                    return_binary=True,
                    chat_id=chat_id,
                    user_id=user_id,
                )

                if result.get("success"):
                    _ext = Path(result.get("filename", "asset.jpg")).suffix or ".jpg"
                    _asset_filename = f"{str(_uuid.uuid4())}{_ext}"

                    _saved_path = _StorageManager.save_file(
                        client_id=_client_id,
                        chat_uuid=chat_id,
                        folder_type="assets",
                        filename=_asset_filename,
                        content=result["content"],
                        is_binary=True,
                        user_id=user_id,
                    )
                    if _saved_path:
                        asset_url = _saved_path
                    else:
                        _fallback_path = os.path.join(script_dir, _asset_filename)
                        with open(_fallback_path, "wb") as _ff:
                            _ff.write(result["content"])
                        asset_url = _fallback_path
                        debug(
                            f"{LOG_GEN_DOC} StorageManager falhou, salvo em fallback: {_asset_filename}"
                        )

                    copy_data["assets"][idx]["asset_url"] = asset_url
                    copy_data["assets"][idx]["status"] = "done"

                    _raw_doc_ratio = copy_data.get("aspect_ratio", "9:16")
                    _doc_ratio_str = (
                        _raw_doc_ratio[0]
                        if isinstance(_raw_doc_ratio, list) and _raw_doc_ratio
                        else str(_raw_doc_ratio)
                    )
                    asset_format = (
                        copy_data["assets"][idx].get("format") or _doc_ratio_str
                    )

                    generated_assets.append(
                        {
                            "asset_id": _asset_filename,
                            "variation_id": variation_ids[idx],
                            "ratio": asset_format,
                            "caption": copy_data.get("caption", ""),
                        }
                    )
                    successes += 1

                    try:
                        from App.Core.Crunch.TablesSQL.Models import Asset as _Asset

                        _new_asset = _Asset(
                            asset_id=_asset_filename,
                            type="img",
                            content_name=copy_data.get(
                                "title", f"copy_{document_id[:8]}_{idx}"
                            ),
                            user_id=user_id,
                            client_id=_client_id,
                            chat_id=chat_id,
                            storage_path=asset_url,
                            storage_env="local",
                            caption=copy_data.get("caption", ""),
                            ratio=asset_format,
                            title=f"{copy_data.get('title', '')} — {asset_format}",
                            variation_id=variation_ids[idx],
                        )
                        session.add(_new_asset)
                        session.flush()
                        debug(
                            f"{LOG_GEN_DOC} Asset salvo na tabela assets: {_asset_filename}"
                        )
                    except Exception as _ae:
                        debug(f"{LOG_GEN_DOC} Erro ao salvar asset na tabela: {_ae}")
                else:
                    generated_assets.append(
                        {
                            "asset_id": None,
                            "variation_id": variation_ids[idx],
                            "error": result.get("error", ERR_GENERATION_FAILED),
                        }
                    )

            # Mark document done if every asset is now generated
            all_done = all(
                a.get("status") == "done" for a in copy_data.get("assets", [])
            )
            if all_done:
                copy_data["status"] = "done"

            # ATUALIZAR DB
            updated_content = json.dumps(copy_data, ensure_ascii=False)
            update_query = text(SQL_UPDATE_DOCUMENT_CONTENT)
            session.execute(
                update_query, {"content": updated_content, "document_id": document_id}
            )
            session.commit()

            # CONSUMIR CRÉDITOS APENAS DOS GERADOS COM SUCESSO
            credits_consumed = 0.0
            remaining_credits = 0.0

            if user_id and successes > 0:
                cost_centavos = CreditsManager.calculate_batch_asset_cost(
                    successes, provider=CREDITS_PROVIDER
                )
                cost_credits = CreditsManager.centavos_to_credits(cost_centavos)

                # Extrair apenas os IDs dos assets gerados com sucesso
                asset_ids = [
                    a["asset_id"] for a in generated_assets if a.get("asset_id")
                ]

                (
                    consume_ok,
                    remaining_credits,
                ) = CreditsManager.check_and_consume_for_batch_assets(
                    user_id,
                    num_successes=successes,
                    provider=CREDITS_PROVIDER,
                    asset_ids=asset_ids,
                    isolated_chat_id=chat_id,
                    isolated_message_id=isolated_message_id,
                )
                if consume_ok:
                    credits_consumed = cost_credits
                    debug(
                        f"{LOG_GEN_DOC} Créditos consumidos: {credits_consumed:.6f}, restante: {remaining_credits:.6f}"
                    )
                else:
                    debug(
                        f"{LOG_GEN_DOC} Falha ao consumir créditos para {successes} assets"
                    )
                    _, remaining_credits = CreditsManager.check_credits(user_id)
            elif user_id:
                _, remaining_credits = CreditsManager.check_credits(user_id)

            return {
                "success": successes > 0,
                "generated_assets": generated_assets,
                "credits_consumed": credits_consumed,
                "credits_remaining": remaining_credits,
                "message": f"Generated {successes}/{len(pending_assets)} assets",
            }

        finally:
            session.close()

    except Exception as e:
        error(f"{LOG_GEN_DOC} Erro ao gerar assets: {e}")
        import traceback

        debug(f"{LOG_GEN_DOC} Traceback: {traceback.format_exc()}")
        return {
            "success": False,
            "error": str(e),
            "generated_assets": [],
            "credits_consumed": 0.0,
            "credits_remaining": 0.0,
        }


# ── Variações étnicas HRP=True ───────────────────────────────────────────────
# Sequência rotativa: cada geração usa uma variação diferente
_HRP_ETHNIC_VARIATIONS = [
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

# Prompts base por dimensão de variação (testing_var system)
_TESTING_VAR_BASE = {
    "style": (
        "Generate a professional ad creative variation based on this reference image. "
        "Validation objective: {what_to_validate}. "
        "VISUAL STYLE to apply in this variation: {description}. "
        "Preserve the core product and message intent. "
        "Fully adapt the visual style, environment and art direction to match the specified style. "
        "Result must be photorealistic, print-quality, professional advertising standard."
    ),
    "camera_angle": (
        "Generate a professional ad creative variation based on this reference image. "
        "Validation objective: {what_to_validate}. "
        "CAMERA ANGLE for this variation: {description}. "
        "Keep the same product, subject, lighting style and background theme. "
        "Only change the camera position, angle and framing. "
        "Result must be photorealistic, print-quality, professional advertising standard."
    ),
    "emotion": (
        "Generate a professional ad creative variation based on this reference image. "
        "Validation objective: {what_to_validate}. "
        "EMOTION/EXPRESSION for this variation: {description}. "
        "Keep the same setting, lighting, composition and all visual elements. "
        "Only change the subject's facial expression and body language to convey the target emotion. "
        "Result must be photorealistic, print-quality, professional advertising standard."
    ),
    "pose": (
        "Generate a professional ad creative variation based on this reference image. "
        "Validation objective: {what_to_validate}. "
        "POSE for this variation: {description}. "
        "Keep the same setting, style, model appearance and lighting. "
        "Only change the body posture, hand position and pose as specified. "
        "Result must be photorealistic, print-quality, professional advertising standard."
    ),
    "ethnicity": (
        "Generate a professional photorealistic variation of this image. "
        "Validation objective: {what_to_validate}. "
        "REPLACE ONLY the model/person ethnicity/cultural look: {description}. "
        "PRESERVE EXACTLY — do NOT change: camera angle, focal distance, depth of field, "
        "framing, composition, lighting setup, background, clothing style, color palette, "
        "pose, facial expression, mood, image quality. "
        "Same apparent age as the original model. Natural human asymmetry preserved. "
        "Result must look like an editorial fashion photograph with extreme photographic realism."
    ),
    "gender": (
        "Generate a professional photorealistic variation of this image. "
        "Validation objective: {what_to_validate}. "
        "REPLACE the model with a {description} version. "
        "PRESERVE EXACTLY — do NOT change: camera angle, lighting, background, "
        "clothing style adapted to the new gender, pose, expression, composition and mood. "
        "Result must be photorealistic, print-quality, professional advertising standard."
    ),
    "color": (
        "Generate a professional ad creative variation based on this reference image. "
        "Validation objective: {what_to_validate}. "
        "COLOR PALETTE for this variation: {description}. "
        "Preserve the composition, layout, subject and all structural elements. "
        "Only shift the color palette, tones and color grading as specified. "
        "Result must be photorealistic, print-quality, professional advertising standard."
    ),
    "lighting": (
        "Generate a professional ad creative variation based on this reference image. "
        "Validation objective: {what_to_validate}. "
        "LIGHTING SETUP for this variation: {description}. "
        "Preserve the composition, subject, background and all non-lighting elements. "
        "Only change the light direction, intensity, quality and shadows as specified. "
        "Result must be photorealistic, print-quality, professional advertising standard."
    ),
    "background": (
        "Generate a professional ad creative variation based on this reference image. "
        "Validation objective: {what_to_validate}. "
        "BACKGROUND for this variation: {description}. "
        "Preserve the foreground elements, product, subject and composition exactly. "
        "Only replace the background environment as specified. "
        "Result must be photorealistic, print-quality, professional advertising standard."
    ),
    "custom": (
        "Generate a professional ad creative variation based on this reference image. "
        "Validation objective: {what_to_validate}. "
        "Specific creative direction for this variation: {description}. "
        "Result must be photorealistic, print-quality, professional advertising standard."
    ),
}


def generate_from_reference_image(
    reference_image: str,
    variations: list = None,
    what_to_validate: str = "",
    prompt_extra: str = "",
    num_variations: int = None,
    chat_id: str = None,
    user_id: str = None,
    db_manager=None,
    aspect_ratio: str = "",
    isolated_message_id: str = None,
    asset_id_override: str = None,
) -> dict:
    """
    Geração de variações a partir de imagem de referência (attachment, template ou URL).

    Args:
        reference_image: URL da imagem já resolvida
        variations: [{label, style, testing_var: {type, description}}] por variação
        what_to_validate: dimensão sendo testada ("estilo inicial", "ângulo", "cor"...)
        prompt_extra: orientações adicionais
        num_variations: fallback se `variations` não fornecido
        chat_id, user_id, db_manager: contexto de execução

    Returns:
        {success, generated_assets, credits_consumed, credits_remaining, message/error}
    """
    import uuid as _uuid
    from App.Core.Crunch.Storage.StorageManager import StorageManager as _StorageManager

    try:
        from App.Features.Credits.CreditsManager import CreditsManager

        # A imagem já deve vir resolvida (URL ou data URI) do Core.py
        # Se ainda não for URL nem data URI, tentar resolver
        resolved = reference_image
        if not resolved or (
            not resolved.startswith("http") and not resolved.startswith("data:")
        ):
            resolved = resolve_image_input(
                reference_image, chat_id=chat_id, user_id=user_id
            )
            # resolve_image_input pode retornar dict {"bytes": ..., "dimensions": ...}
            # run_model_logic não consegue reprocessar um dict — converter para data URI
            if isinstance(resolved, dict) and resolved.get("bytes"):
                import base64 as _b64

                _b = resolved["bytes"]
                _mime = "image/jpeg"
                if _b[:8] == b"\x89PNG\r\n\x1a\n":
                    _mime = "image/png"
                elif _b[:4] == b"RIFF" and _b[8:12] == b"WEBP":
                    _mime = "image/webp"
                resolved = f"data:{_mime};base64,{_b64.b64encode(_b).decode()}"
        if not resolved:
            return {
                "success": False,
                "error": "Imagem de referência não encontrada. Verifique o ID do template ou attachment e tente novamente.",
                "hint": f"reference_image='{reference_image}' não pôde ser resolvido. Use attachment_id, template_id (ex: 'insp-8') ou URL direta.",
                "generated_assets": [],
                "credits_consumed": 0.0,
                "credits_remaining": 0.0,
            }

        # Montar lista de variações a executar
        if variations:
            # Cada item tem {label, style, testing_var: {type, description}}
            variations_to_run = list(enumerate(variations))
            _n = len(variations_to_run)
        else:
            # Fallback: num_variations variações sem estilo específico
            _n = num_variations or 1
            variations_to_run = [(i, None) for i in range(_n)]

        # Checar créditos antes de gerar (não consome ainda)
        _num_variations = len(variations_to_run)
        _credits_consumed = 0.0
        _credits_remaining = 0.0
        if user_id:
            (
                has_credits,
                cost_centavos,
                available,
            ) = CreditsManager.check_and_consume_for_batch_assets(
                user_id,
                num_assets=_num_variations,
                isolated_chat_id=chat_id,
                isolated_message_id=isolated_message_id,
            )
            if not has_credits:
                cost_credits = CreditsManager.centavos_to_credits(cost_centavos)
                return {
                    "success": False,
                    "error": f"Créditos insuficientes. Necessário: {cost_credits:.2f} créditos, disponível: {float(available):.2f}.",
                    "generated_assets": [],
                    "credits_consumed": 0.0,
                    "credits_remaining": float(available),
                }

        # Buscar client_id
        _client_id = None
        if user_id and db_manager:
            from sqlalchemy import text as _text

            _s = db_manager.get_session()
            try:
                _row = _s.execute(
                    _text("SELECT client_id FROM users WHERE user_id = :uid"),
                    {"uid": user_id},
                ).first()
                _client_id = str(_row[0]) if _row else None
            finally:
                _s.close()

        # Gerar variações
        variation_id = str(
            _uuid.uuid4()
        )  # mesmo variation_id para todas as variações deste batch
        generated_assets = []
        successes = 0

        for var_idx, var_item in variations_to_run:
            # Extrair testing_var do item (se existir)
            if isinstance(var_item, dict):
                _testing_var = var_item.get("testing_var") or {}
                _var_type = _testing_var.get("type", "custom")
                _var_desc = _testing_var.get("description", var_item.get("style", ""))

                # Ethnicity sem descrição: usar pool rotativo de etnias
                if _var_type == "ethnicity" and not _var_desc:
                    _pool = _HRP_ETHNIC_VARIATIONS
                    _var_desc = _pool[var_idx % len(_pool)]

                _prompt_template = _TESTING_VAR_BASE.get(
                    _var_type, _TESTING_VAR_BASE["custom"]
                )
                base_prompt = _prompt_template.format(
                    what_to_validate=what_to_validate or _var_type,
                    description=_var_desc,
                )
            else:
                # Fallback genérico sem testing_var
                base_prompt = _TESTING_VAR_BASE["custom"].format(
                    what_to_validate=what_to_validate or "creative variation",
                    description="Apply a fresh creative variation while preserving the core product and message.",
                )
                _var_type = "custom"
                _var_desc = ""

            final_prompt = base_prompt
            if prompt_extra:
                final_prompt += (
                    f"\n\nAdditional instructions from the user: {prompt_extra}"
                )

            extra_args = {"image_input": [resolved]}
            if aspect_ratio:
                extra_args["aspect_ratio"] = aspect_ratio

            result = run_model_logic(
                prompt=final_prompt,
                extra_args=extra_args,
                return_binary=True,
                chat_id=chat_id,
                user_id=user_id,
            )

            if result.get("success"):
                _ext = Path(result.get("filename", "asset.jpg")).suffix or ".jpg"
                _asset_filename = (
                    asset_id_override
                    if asset_id_override
                    else f"{str(_uuid.uuid4())}{_ext}"
                )

                _saved_path = _StorageManager.save_file(
                    client_id=_client_id,
                    chat_uuid=chat_id,
                    folder_type="assets",
                    filename=_asset_filename,
                    content=result["content"],
                    is_binary=True,
                    user_id=user_id,
                )
                asset_url = _saved_path or _asset_filename

                # Salvar na tabela assets
                if db_manager:
                    try:
                        from App.Core.Crunch.TablesSQL.Models import Asset as _Asset
                        from sqlalchemy.orm import Session as _Session

                        _sa = db_manager.get_session()
                        try:
                            _label_name = (
                                var_item.get("label", f"v{var_idx + 1}")
                                if isinstance(var_item, dict)
                                else f"v{var_idx + 1}"
                            )
                            _label = (
                                f"var-{_var_type}-{_label_name}"
                                if isinstance(var_item, dict)
                                else f"var-v{var_idx + 1}"
                            )
                            _new_asset = _Asset(
                                asset_id=_asset_filename,
                                type="img",
                                content_name=_label,
                                user_id=user_id,
                                client_id=_client_id,
                                chat_id=chat_id,
                                storage_path=asset_url,
                                storage_env="local",
                                variation_id=variation_id,
                                ratio=aspect_ratio or "9:16",
                            )
                            _sa.add(_new_asset)
                            _sa.commit()
                        finally:
                            _sa.close()
                    except Exception as _ae:
                        debug(f"[ASSET_REF] Erro ao salvar na tabela assets: {_ae}")

                generated_assets.append(
                    {
                        "asset_id": _asset_filename,
                        "variation_id": variation_id,
                        "variation_index": var_idx + 1,
                        "testing_var_type": _var_type,
                        "testing_var_description": _var_desc,
                        "label": (
                            _label_name
                            if isinstance(var_item, dict)
                            else f"v{var_idx + 1}"
                        ),
                        "ratio": aspect_ratio or "9:16",
                    }
                )
                successes += 1
            else:
                generated_assets.append(
                    {
                        "asset_id": None,
                        "variation_id": variation_id,
                        "variation_index": var_idx + 1,
                        "error": result.get("error", "Generation failed"),
                    }
                )

        # Consumir créditos apenas pelas imagens geradas com sucesso
        if user_id and successes > 0:
            # Extrair apenas os IDs dos assets gerados com sucesso
            asset_ids = [a["asset_id"] for a in generated_assets if a.get("asset_id")]

            consume_ok, remaining = CreditsManager.check_and_consume_for_batch_assets(
                user_id,
                num_successes=successes,
                provider=CREDITS_PROVIDER,
                asset_ids=asset_ids,
                isolated_chat_id=chat_id,
                isolated_message_id=isolated_message_id,
            )
            if consume_ok:
                cost_centavos = CreditsManager.calculate_batch_asset_cost(successes)
                _credits_consumed = float(
                    CreditsManager.centavos_to_credits(cost_centavos)
                )
                _credits_remaining = float(remaining)
            else:
                _, _credits_remaining = CreditsManager.check_credits(user_id)
        elif user_id:
            _, _credits_remaining = CreditsManager.check_credits(user_id)

        return {
            "success": successes > 0,
            "generated_assets": generated_assets,
            "credits_consumed": _credits_consumed,
            "credits_remaining": _credits_remaining,
            "message": f"Generated {successes}/{len(variations_to_run)} variations — what_to_validate='{what_to_validate}'",
        }

    except Exception as e:
        error(f"[ASSET_REF] Erro: {e}")
        import traceback

        debug(f"[ASSET_REF] Traceback: {traceback.format_exc()}")
        return {
            "success": False,
            "error": str(e),
            "generated_assets": [],
            "credits_consumed": 0.0,
            "credits_remaining": 0.0,
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", type=str, required=True)
    parser.add_argument("--reference", type=str, default=None)
    parser.add_argument("--logo", type=str, default=None)
    parser.add_argument("--human", type=str, default="false")
    args, unknown = parser.parse_known_args()

    # Preparar imagens de entrada como dicionário com roles
    images = {}
    if args.reference:
        images["reference"] = args.reference
    if args.logo:
        images["logo"] = args.logo

    extra_params = {}
    for i in range(0, len(unknown), 2):
        key = unknown[i].lstrip("-")
        if i + 1 < len(unknown):
            val = unknown[i + 1]
            if val.startswith("[") or val.startswith("{"):
                try:
                    val = json.loads(val)
                except json.JSONDecodeError:
                    pass
            elif "," in val:
                val = [item.strip() for item in val.split(",")]
            elif val.lower() == "true":
                val = True
            elif val.lower() == "false":
                val = False
            elif val.isdigit():
                val = int(val)
            extra_params[key] = val

    run_model_logic(
        args.prompt,
        images=images or None,
        extra_args=extra_params,
        human_mode=args.human.lower() == "true",
    )


if __name__ == "__main__":
    main()

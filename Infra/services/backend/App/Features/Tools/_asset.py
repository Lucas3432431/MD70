"""
_asset.py — Mixin extraído de Core.py.
Core.py importa este módulo e herda AssetMixin.
NÃO edite a assinatura da classe — use Core.py como entry point.
"""

# ruff: noqa
# type: ignore
from __future__ import annotations
from typing import TYPE_CHECKING, Dict, Any, Optional

if TYPE_CHECKING:
    pass  # evita imports circulares em type checking

"""
Core.py - Simple tool execution handler
Processa tool calls de print, task, agent e web-search
"""

import json
import asyncio
import hashlib
import re
import time as _time
import uuid as uuid_lib
from uuid import UUID
import base64
import tempfile
import requests
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime
from App.Core.Logs import debug, error
from .AgentHandler import AgentHandler
from App.Features.Tools.Tools.Scraping import ScrapingScrawlingTool
from App.Features.Tools.Tools.Assets import run_model_logic as assets_run_model_logic
from App.Features.Tools.Tools.Graphs import execute_graph_visualization
from App.Core.Crunch.Storage.StorageManager import StorageManager
from App.Core.Crunch.Storage.MediaCompressor import MediaCompressor
from App.Core.Settings.Settings import load_config, get_public_url, is_public_url_online
import anthropic
import openai
from google import genai
from .Mcp.MCPClientManager import mcp_manager
from App.Features.Tools.Tools.Edit import (
    read_file_with_encoding,
    process_escape_sequences,
    normalize_line_endings,
    find_block_match,
)
from App.Core.Crunch.TablesSQL.Models import User, GeneratedContent
from App.Core.Types import (
    AssetType,
    AssetContentType,
    ASSET_TYPE_TO_CONTENT_TYPE,
    ASSET_CONTENT_TYPE_TO_EXTENSION,
)

# ============================================================================
# GLOBAL STRINGS & CONSTANTS (Isolated from Logic)
# ============================================================================

# Configuration
LOOKUP_HISTORY_LIMIT = 20
DEFAULT_POST_STATUS = "toDo"
TIMEOUT_API = 60

# Tool Names
TOOL_PRINT = "print"
TOOL_TASK = "task"
TOOL_AGENT = "agent"
TOOL_WEB_SEARCH = "web-search"
TOOL_DOCUMENT = "document"
TOOL_UPDATE = "update"
TOOL_DELETE = "delete"
TOOL_LOOKUP = "lookup"
TOOL_QUIZ = "quiz"
TOOL_MESSAGE = "message"
TOOL_GRAPH = "create_graph_visualization"

# Entity Types
TYPE_DOCUMENT = "document"
TYPE_SCHEDULE = "schedule"
TYPE_TASK = "task"
TYPE_ASSET = "asset"
TYPE_CLIENT = "client"

# Validation Lists
VALID_CONTENT_TYPES = [
    "branding",
    "conversion",
    "awareness",
    "educational",
    "cart_recovery",
]
UPDATE_VALID_TYPES = ["document", "schedule", "task", "asset"]
DELETE_VALID_TYPES = ["document", "schedule", "task"]
DOCUMENT_VALID_TYPES = [
    "business_canvas",
    "brand_communication",
    "copywriting",
    "product",
]

# Copywriting Constants
COPY_POST_TYPE_VALUES = [
    "topo_de_funil",
    "meio_de_funil",
    "fundo_de_funil",
    "recuperacao_de_carrinho",
    "branding",
    "anuncio",
]
COPY_POST_TYPE_VALUES_PRODUCT = [
    "branding",
    "anuncio",
    "recuperacao_de_carrinho",
]  # produto fsico/digital
COPY_POST_TYPE_VALUES_SERVICE = [
    "topo_de_funil",
    "meio_de_funil",
    "fundo_de_funil",
    "recuperacao_de_carrinho",
    "branding",
]
COPY_VARIATION_CATEGORIES = ["Criativo", "Gatilhos", "Comunicao", "Outro"]
COPY_ASSET_TYPES = ["img"]
COPY_ASPECT_RATIOS = ["9:16", "16:9", "1:1", "4:5"]
COPY_FRAMEWORK_VALUES = ["SLAP", "ACC", "4CS", "PAS", "AIDA", "FAB"]
COPY_CHANNELS = [
    "instagram",
    "facebook",
    "linkedin",
    "x",
    "google",
    "youtube",
    "tiktok",
    "pinterest",
]
COPY_CHANNEL_VALID_FORMATS = {
    "instagram": ["1:1", "4:5", "9:16"],  # feed 1:1/4:5 + reels/stories 9:16
    "facebook": ["1:1", "4:5", "16:9"],
    "linkedin": ["1:1", "4:5", "16:9"],
    "x": ["1:1", "16:9"],
    "google": ["1:1", "16:9"],
    "youtube": ["16:9", "9:16"],
    "tiktok": ["9:16"],
    "pinterest": ["4:5", "1:1"],
}
COPY_ASSET_ANGLE_VALUES = [
    "OverheadDroneShot",
    "DetailShot",
    "CloseUpShot",
    "HyperCloseUpShot",
    "HighAngleShot",
    "LowAngleShot",
    "MidBodyShot",
    "EyeLevelShot",
    "POVShot",
    "UGC",
    "Studio",
]
COPY_ASSET_ANGLE_VALUES_PRODUCT = [
    "CloseUpShot",
    "DetailShot",
    "HyperCloseUpShot",
]  # non-HRP: close-up obrigatrio
COPY_ASSET_ANGLE_VALUES_CLOSEUP = [
    "CloseUpShot",
    "HyperCloseUpShot",
]  # bg limpo (window/color) exige enquadramento fechado
COPY_ASSET_MOISTURE_VALUES = [
    "natural_glow",
    "dewy",
    "wet",
]  # mnimo = leve oleosidade natural
COPY_ASSET_BG_TYPE_VALUES = [
    "color",
    "outside",
    "window",
    "black_white",
    "product_closeup",
]
COPY_ASSET_BG_TYPE_VALUES_PRODUCT = [
    "window",
    "color",
    "product_closeup",
]  # non-HRP: sem outside/black_white

# Document Validation Strings (for web-search prerequisites)
# Estrutura: { "concept": [list of variations] } - precisa encontrar UMA variao de CADA conceito
BUSINESS_CANVAS_REQUIRED_SEARCH_CONCEPTS = {
    "market_sizing_tam": ["TAM", "Total Addressable Market", "mercado total"],
    "market_sizing_sam": [
        "SAM",
        "Serviceable Addressable Market",
        "mercado enderecvel",
    ],
    "market_sizing_som": ["SOM", "Serviceable Obtainable Market", "mercado obtenvel"],
    "barriers": ["barriers to entry", "barreiras de entrada", "barreira de entrada"],
    "market_age": [
        "market age",
        "idade do mercado",
        "maturidade do mercado",
        "anos no mercado",
    ],
    "budget": ["budget", "oramento", "investimento", "custo"],
}

# Para compatibilidade com cdigo antigo que usa lista simples
BUSINESS_CANVAS_REQUIRED_SEARCH_STRINGS = [
    "TAM",
    "SAM",
    "SOM",
    "barriers to entry",
    "market age",
    "budget",
]

BRAND_COMMUNICATION_REQUIRED_SEARCH_STRINGS = [
    "top",
    "mid",
    "bottom",
    "funnel",
    "branding",
]
BRAND_COMMUNICATION_REQUIRED_SEARCH_CONCEPTS = {
    "top_funnel": ["top of funnel", "topo de funil", "topo do funil", "topo"],
    "mid_funnel": [
        "mid funnel",
        "middle of funnel",
        "meio de funil",
        "meio do funil",
        "meio",
    ],
    "bottom_funnel": [
        "bottom of funnel",
        "fundo de funil",
        "fundo do funil",
        "bottom",
        "fundo",
    ],
    "branding": ["branding"],
}

# Strings PROIBIDAS no Quiz (devem vir do web-search, no do quiz)
# Inclui variaes em portugus para detectar quando usurio traz informaes do quiz
BUSINESS_CANVAS_PROHIBITED_IN_QUIZ = [
    # Ingls (originals)
    "TAM",
    "SAM",
    "SOM",
    "barriers to entry",
    "market age",
    "budget",
    "Total Addressable Market",
    "Serviceable Addressable Market",
    "Serviceable Obtainable Market",
    # Portugus (variaes)
    "mercado total",
    "mercado enderecvel",
    "mercado obtenvel",
    "mercado obtvel",
    "barreiras de entrada",
    "barreira de entrada",
    "idade do mercado",
    "maturidade do mercado",
    "anos no mercado",
    "tempo de mercado",
    "oramento",
    "investimento necessrio",
    "capital investido",
    "investimento inicial",
]
# Nota: "tam"/"sam"/"som" removidos  substring muito curta gera falsos positivos
# em palavras portuguesas como "plataforma", "tambm", "automatizar", etc.
# A verificao case-insensitive de "TAM"/"SAM"/"SOM" como palavras isoladas  feita via word boundary.

# Tpicos OBRIGATRIOS no Quiz (validao por tpico com variaes pt/en)
BUSINESS_CANVAS_REQUIRED_TOPICS_IN_QUIZ = [
    {
        "topic": "value_proposition",
        "pt": ["proposta de valor", "proposio de valor", "proposicao de valor"],
        "en": ["value proposition", "proposition"],
    },
    {
        "topic": "pain_solution",
        "pt": ["dor", "soluo", "dor e soluo", "solucao", "dor e solucao"],
        "en": ["pain", "solution", "pain and solution"],
    },
    {
        "topic": "firmography",
        "pt": ["firmografia", "demografia", "demographia"],
        "en": ["demographic", "firmographic", "firmography"],
    },
    {"topic": "awareness", "pt": ["consciencia"], "en": ["awareness"]},
]

BRAND_COMMUNICATION_REQUIRED_TOPICS_IN_QUIZ = [
    {
        "topic": "color",
        "pt": ["cor", "cores", "paleta de cores"],
        "en": ["color", "colors", "color palette"],
    },
    {
        "topic": "tone",
        "pt": ["tom", "tom de comunicao", "tom de comunicacao"],
        "en": ["tone", "tone of communication", "tone of voice"],
    },
]

BRAND_COMMUNICATION_PROHIBITED_IN_QUIZ = [
    # Ingls (originals)
    "top",
    "mid",
    "bottom",
    "funnel",
    "branding",
    "top of funnel",
    "middle of funnel",
    "bottom of funnel",
    "sales funnel",
    "archetype",
    "hero",
    "shadow",
    "sage",
    "innocent",
    "everyman",
    "lover",
    "creator",
    "caregiver",
    "ruler",
    "magician",
    "mentor",
    # Portugus (variaes)
    "topo do funil",
    "meio do funil",
    "fundo do funil",
    "funil de vendas",
    "topo de funil",
    "meio de funil",
    "fundo de funil",
    "arqutipo",
    "arquetipo",
    "heri",
    "heroi",
    "sombra",
    "sbio",
    "sabio",
    "inocente",
    "homem comum",
    "amante",
    "criador",
    "cuidador",
    "governante",
    "mago",
    "mentor",
    "awareness",
    "considerao",
    "converso",
    "conscincia",
    "consideracao",
    "conversao",
]

# Framework-specific required fields for copywriting
COPY_FRAMEWORK_FIELDS = {
    "SLAP": {
        "name": "Stop, Look, Act, Purchase",
        "required_fields": [
            "stop_hook",
            "look_proposition",
            "act_urgency",
            "purchase_cta",
        ],
    },
    "ACC": {
        "name": "Awareness  Comprehension  Conversion",
        "required_fields": [
            "awareness_problem",
            "comprehension_explanation",
            "conversion_solution",
        ],
    },
    "4CS": {
        "name": "Clear, Concise, Compelling, Credible",
        "required_fields": [
            "clear_message",
            "concise_copy",
            "compelling_angle",
            "credible_proof",
        ],
    },
    "PAS": {
        "name": "Problem, Agitate, Solution",
        "required_fields": ["problem", "agitate", "solution"],
    },
    "AIDA": {
        "name": "Attention, Interest, Desire, Action",
        "required_fields": ["attention", "interest", "desire", "action"],
    },
    "FAB": {
        "name": "Features, Advantages, Benefits",
        "required_fields": ["features", "advantages", "benefits"],
    },
}

# SQL Queries
SQL_SELECT_DOCUMENT = (
    "SELECT document_id, title, content FROM documents WHERE document_id = :id"
)
SQL_DELETE_DOCUMENT = "DELETE FROM documents WHERE document_id = :document_id"
SQL_SELECT_DOC_SIMPLE = (
    "SELECT document_id, title FROM documents WHERE document_id = :document_id"
)

# Error Messages
ERR_DB_NOT_CONFIGURED = "Database manager no configurado"
ERR_MISSING_REQUIRED_FIELDS = "Campos obrigatrios faltando: {}"
ERR_INVALID_TYPE = "Tipo invlido '{}'. Use: {}"
ERR_ITEM_NOT_FOUND = "{} com ID {} no encontrado"
ERR_EXTERNAL_TOOL = "[EXTERNAL_TOOL] Erro em {}: {}"
ERR_MESSAGE_REQUIRED = "A primeira tool deve ser 'message' OU 'chain-of-thought' para contextualizar antes de usar outras tools."  # kept for reference
ERR_PREREQUISITES_TEMPLATE = "Para usar esta tool, execute primeiro:\n{steps}"

# Log Prefixes
LOG_PREFIX_EXTERNAL = "[EXTERNAL_TOOL]"
LOG_PREFIX_UPDATE = "[UPDATE]"
LOG_PREFIX_DELETE = "[DELETE]"
LOG_PREFIX_TASK = "[TASK]"
LOG_PREFIX_TOOL = "[TOOL]"

# ============================================================================

# ---------------------------------------------------------------------------
# Public-URL reachability probe (cached 60 s) + attachment base64 fallback
# ---------------------------------------------------------------------------
_url_probe: dict = {"ok": None, "at": 0.0}
_URL_PROBE_TTL = 60  # seconds


def _is_public_url_reachable(public_url: str) -> bool:
    """Returns True if public_url/api/health responds < 500 (cached 60 s)."""
    global _url_probe
    now = _time.time()
    if _url_probe["ok"] is not None and now - _url_probe["at"] < _URL_PROBE_TTL:
        return bool(_url_probe["ok"])
    try:
        import httpx as _httpx

        _target = f"{public_url}/api/health"
        resp = _httpx.head(
            _target,
            headers={"User-Agent": "MD70-probe/1.0"},
            timeout=3,
            follow_redirects=False,
        )
        ok = resp.status_code < 500
    except Exception:
        ok = False
    _url_probe = {"ok": ok, "at": now}
    if not ok:
        error(
            f"[RESOLVE_IMAGE] public_url inacessível ({public_url}) — fallback base64 ativado"
        )
    return ok


def _attachment_as_base64(attachment_id: str, user_id: str) -> str:
    """Reads attachment from local storage and returns data URI string, or ''."""
    try:
        from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
        from sqlalchemy import text as _text
        import base64 as _b64

        session = DatabaseManager.get_session()
        try:
            row = session.execute(
                _text(
                    "SELECT storage_path FROM attachments "
                    "WHERE attachment_id = :aid AND user_id = :uid AND deleted_at IS NULL LIMIT 1"
                ),
                {"aid": attachment_id, "uid": user_id},
            ).fetchone()
        finally:
            session.close()

        if not row:
            return ""

        file_path = StorageManager.LOCAL_STORAGE_BASE / row[0]
        if not file_path.exists():
            return ""

        ext = file_path.suffix.lower()
        mime_map = {
            ".webp": "image/webp",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".pdf": "application/pdf",
        }
        mime = mime_map.get(ext, "image/webp")
        data = _b64.b64encode(file_path.read_bytes()).decode()
        return f"data:{mime};base64,{data}"
    except Exception as e:
        debug(f"[RESOLVE_IMAGE] _attachment_as_base64 falhou: {e}")
        return ""


def _asset_as_base64(asset_id_prefix: str, user_id: str) -> str:
    """Reads generated asset from local storage and returns data URI, or ''.
    Accepts UUID with or without extension; queries with LIKE to handle both."""
    try:
        from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
        from App.Core.Crunch.Storage.StorageManager import StorageManager
        import base64 as _b64

        session = DatabaseManager.get_session()
        try:
            from sqlalchemy import text as _text

            row = session.execute(
                _text(
                    "SELECT storage_path FROM assets "
                    "WHERE (asset_id = :aid OR asset_id LIKE :aid_prefix) "
                    "AND user_id = :uid LIMIT 1"
                ),
                {
                    "aid": asset_id_prefix,
                    "aid_prefix": f"{asset_id_prefix}.%",
                    "uid": user_id,
                },
            ).fetchone()
        finally:
            session.close()

        if not row:
            return ""

        storage_path = row[0]
        base = StorageManager.LOCAL_STORAGE_BASE
        file_path = (
            base / storage_path
            if not str(storage_path).startswith("/")
            else Path(storage_path)
        )
        if not file_path.exists():
            return ""

        ext = file_path.suffix.lower()
        mime_map = {
            ".webp": "image/webp",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
        }
        mime = mime_map.get(ext, "image/jpeg")
        data = _b64.b64encode(file_path.read_bytes()).decode()
        return f"data:{mime};base64,{data}"
    except Exception as e:
        debug(f"[RESOLVE_IMAGE] _asset_as_base64 falhou: {e}")
        return ""


def _call_vision_with_fallback(image_data_uri: str, prompt: str) -> Optional[str]:
    """
    Chama visão com OpenAI gpt-4o e fallback para Claude.
    Aceita data URI (base64) ou URL http/https.
    Standalone — usável fora de Core/AssetMixin.
    """
    # --- OpenAI GPT-4o ---
    try:
        from App.Core.Settings.Settings import get_openai_api_key

        api_key = get_openai_api_key()
        if api_key:
            payload = {
                "model": "gpt-4o",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": image_data_uri}},
                        ],
                    }
                ],
            }
            resp = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=60,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("choices"):
                    return data["choices"][0]["message"]["content"]
            else:
                debug(
                    f"[VISION-STANDALONE] OpenAI erro {resp.status_code}: {resp.text[:200]}"
                )
    except Exception as e:
        debug(f"[VISION-STANDALONE] OpenAI falhou: {e}")

    # --- Fallback: Claude via Anthropic SDK ---
    try:
        from App.Core.Settings.Settings import get_anthropic_api_key

        api_key = get_anthropic_api_key()
        if not api_key:
            return None

        # Montar content block de imagem para Claude
        if image_data_uri.startswith("data:"):
            header, b64data = image_data_uri.split(",", 1)
            media_type = header.split(";")[0].replace("data:", "")
            image_block = {
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": b64data},
            }
        else:
            image_block = {
                "type": "image",
                "source": {"type": "url", "url": image_data_uri},
            }

        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=8192,
            messages=[
                {
                    "role": "user",
                    "content": [image_block, {"type": "text", "text": prompt}],
                }
            ],
        )
        if msg.content:
            return msg.content[0].text
    except Exception as e:
        debug(f"[VISION-STANDALONE] Claude fallback falhou: {e}")

    return None


class AssetMixin:
    def _compress_base64_image_for_vision(self, image_data_uri: str) -> Optional[str]:
        """
        Comprime imagem base64 usando MediaCompressor.
        Reduz para 512x384px e converte para WebP.

        Args:
            image_data_uri: Data URI com base64 (data:image/...;base64,...)

        Returns:
            Data URI comprimida ou None se falhar
        """
        if not image_data_uri or not image_data_uri.startswith("data:"):
            return image_data_uri  # Retorna URL como est

        try:
            # Extrair informaes do data URI
            parts = image_data_uri.split(",", 1)
            if len(parts) != 2:
                return image_data_uri

            header = parts[0]  # data:image/png;base64
            data = parts[1]

            # Extrair tipo MIME
            mime_type = "image/png"
            if "image/jpeg" in header:
                mime_type = "image/jpeg"
            elif "image/webp" in header:
                mime_type = "image/webp"
            elif "image/gif" in header:
                mime_type = "image/gif"
            elif "image/png" in header:
                mime_type = "image/png"

            # Decodificar base64
            image_bytes = base64.b64decode(data)

            # Criar arquivo temporrio
            with tempfile.NamedTemporaryFile(suffix=".tmp", delete=False) as tmp_file:
                tmp_path = Path(tmp_file.name)
                tmp_file.write(image_bytes)

            try:
                debug(f"[VISION] Comprimindo imagem ({len(image_bytes)} bytes)...")

                # Comprimir usando MediaCompressor
                compressed_path = MediaCompressor.resize_for_ai(
                    tmp_path, max_width=512, max_height=384, quality=40
                )

                if not compressed_path or not compressed_path.exists():
                    debug("[VISION] Falha ao comprimir, usando original")
                    return image_data_uri

                # Ler arquivo comprimido
                with open(compressed_path, "rb") as f:
                    compressed_bytes = f.read()

                # Converter de volta para base64
                compressed_base64 = base64.b64encode(compressed_bytes).decode("utf-8")
                compressed_data_uri = f"data:image/webp;base64,{compressed_base64}"

                reduction = (
                    (len(image_bytes) - len(compressed_bytes)) / len(image_bytes) * 100
                )
                debug(
                    f"[VISION] Compresso concluda: {reduction:.1f}% reduo ({len(image_bytes)}B  {len(compressed_bytes)}B)"
                )

                return compressed_data_uri

            finally:
                # Limpar arquivos temporrios
                try:
                    if tmp_path.exists():
                        tmp_path.unlink()
                    if compressed_path and compressed_path.exists():
                        compressed_path.unlink()
                except Exception as e:
                    debug(f"[VISION] Erro ao limpar temporrios: {e}")

        except Exception as e:
            debug(f"[VISION] Erro ao comprimir imagem: {e}")
            return image_data_uri  # Retorna original se falhar

    def _resolve_uuid_to_media_url(
        self, uuid_str: str, user_id: str, chat_id: str
    ) -> Optional[str]:
        """
        Converte UUID de attachment ou generated_content para URL temporria.

        Args:
            uuid_str: UUID do attachment ou generated_content
            user_id: ID do usurio
            chat_id: ID do chat

        Returns:
            URL temporria ou None se no encontrar
        """
        try:
            from App.Core.Utils.TempTokenStore import build_file_url
            from App.Core.Crunch.Storage.StorageManager import StorageManager
            from pathlib import Path as _Path

            # Tentar buscar como attachment
            attachment = self.db_manager.fetch_one(
                "SELECT storage_path, storage_env FROM attachments "
                "WHERE attachment_id = :uuid AND user_id = :user_id AND deleted_at IS NULL LIMIT 1",
                {"uuid": uuid_str, "user_id": user_id},
            )
            if attachment:
                sp = attachment.get("storage_path") or ""
                if attachment.get("storage_env") == "local":
                    fp = str(StorageManager.LOCAL_STORAGE_BASE / _Path(sp))
                else:
                    fp = sp
                url = build_file_url(fp)
                debug(
                    f"[RESOLVE-UUID] URL pública gerada para attachment: {uuid_str[:8]}..."
                )
                return url

            # Tentar buscar como asset
            asset = self.db_manager.fetch_one(
                "SELECT storage_path, storage_env FROM assets "
                "WHERE (id = :uuid OR asset_id = :uuid OR asset_id LIKE :prefix) "
                "AND user_id = :user_id LIMIT 1",
                {"uuid": uuid_str, "prefix": f"{uuid_str}.%", "user_id": user_id},
            )
            if asset:
                sp = asset.get("storage_path") or ""
                if asset.get("storage_env", "local") == "local":
                    fp = str(StorageManager.LOCAL_STORAGE_BASE / _Path(sp))
                else:
                    fp = sp
                url = build_file_url(fp)
                debug(
                    f"[RESOLVE-UUID] URL pública gerada para asset: {uuid_str[:8]}..."
                )
                return url

            debug(f"[RESOLVE-UUID] UUID não encontrado: {uuid_str[:8]}...")
            return None

        except Exception as e:
            error(f"[RESOLVE-UUID] Erro ao resolver UUID para URL: {e}")
            return None

    def _gen_img_fallback_dalle3(
        self, prompt: str, asset_name: str
    ) -> Optional[Dict[str, Any]]:
        """
        Fallback para asset(type="image"): usa OpenAI DALL-E 3 quando Replicate falha.

        Args:
            prompt: Descrio da imagem a gerar
            asset_name: Nome do asset para salvar

        Returns:
            Dict com {"success": True, "content": bytes, "filename": str} ou None se falhar
        """
        try:
            from App.Core.Settings.Settings import load_llm_config

            llm_config = load_llm_config()
            openai_config = llm_config.get("providers", {}).get("openai", {})
            keys = openai_config.get("keys", [])
            openai_api_key = keys[0].get("key", "").strip() if keys else ""

            if not openai_api_key:
                debug("[GEN-IMG-FALLBACK] API key do OpenAI no configurada")
                return None

            debug(f"[GEN-IMG-FALLBACK] Gerando imagem com DALL-E 3: {prompt[:50]}...")

            client = openai.OpenAI(api_key=openai_api_key)

            response = client.images.generate(
                model="dall-e-3",
                prompt=prompt,
                size="1024x1024",
                quality="standard",
                n=1,
            )

            if response.data and len(response.data) > 0:
                image_url = response.data[0].url

                # Baixar a imagem
                img_response = requests.get(image_url, timeout=30)

                if img_response.status_code == 200:
                    filename = f"{asset_name}.jpg"
                    debug("[GEN-IMG-FALLBACK] DALL-E 3 concludo com sucesso")
                    return {
                        "success": True,
                        "content": img_response.content,
                        "filename": filename,
                    }

            return None

        except Exception as e:
            error(f"[GEN-IMG-FALLBACK] Erro ao usar DALL-E 3: {e}")
            return None

    def _gen_film_fallback_google_veo(
        self, prompt: str, asset_name: str
    ) -> Optional[Dict[str, Any]]:
        """
        Fallback para asset(type="video"): usa Google VEO 3.1 quando Replicate falha.

        Args:
            prompt: Descrio do vdeo a gerar
            asset_name: Nome do asset para salvar

        Returns:
            Dict com {"success": True, "content": bytes, "filename": str} ou None se falhar
        """
        try:
            config = load_config()
            google_api_key = config.get("google_api_key", "")

            if not google_api_key:
                debug("[GEN-FILM-FALLBACK] API key do Google no configurada")
                return None

            debug(
                f"[GEN-FILM-FALLBACK] Gerando vdeo com Google VEO 3.1: {prompt[:50]}..."
            )

            client = genai.Client(api_key=google_api_key)

            # VEO 3.1 via Google Generative AI
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=f"Generate a video from this prompt (return as base64 MP4 if possible): {prompt}",
            )

            if response.text:
                # Google pode retornar em diferentes formatos
                # Aqui esperamos um valor de vdeo ou URL
                debug("[GEN-FILM-FALLBACK] Google VEO 3.1 respondeu")

                # Se for uma URL, baixar
                if response.text.startswith("http"):
                    video_response = requests.get(response.text, timeout=60)
                    if video_response.status_code == 200:
                        filename = f"{asset_name}.mp4"
                        return {
                            "success": True,
                            "content": video_response.content,
                            "filename": filename,
                        }

            return None

        except Exception as e:
            error(f"[GEN-FILM-FALLBACK] Erro ao usar Google VEO 3.1: {e}")
            return None

    def _select_model(self, media_type: str) -> str:
        """
        Seleciona automaticamente o modelo principal para o media_type via Replicate.json.
        Retorna o primeiro modelo listado para o media_type (que  o modelo padro).

        Args:
            media_type: Tipo de mdia ('image', 'video', 'vision')

        Returns:
            ID do modelo (ex: 'nano-banana', 'veo-3.1', 'gpt-4o-vision')
        """
        try:
            from pathlib import Path

            replicate_path = Path(__file__).parent / "Tools" / "Replicate.json"
            with open(replicate_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            models = [
                m for m in data.get("models", []) if m.get("media_type") == media_type
            ]
            if models:
                selected = models[0]["id"]
                debug(
                    f"[MEDIAAI] Modelo automtico selecionado para {media_type}: {selected}"
                )
                return selected
        except Exception as e:
            debug(f"[MEDIAAI] Erro ao carregar modelo para {media_type}: {e}")

        # Fallbacks hardcoded se Replicate.json no carregar
        defaults = {
            "image": "nano-banana",
            "video": "veo-3.1",
            "vision": "gpt-4o-vision",
        }
        fallback = defaults.get(media_type, "nano-banana")
        debug(f"[MEDIAAI] Usando fallback de modelo para {media_type}: {fallback}")
        return fallback

    def _validate_and_clean_url(self, url: str, timeout: int = 3) -> tuple[bool, str]:
        """
        Valida se uma URL  acessvel antes de enviar ao Replicate.

        Args:
            url: URL a validar (reference_image)
            timeout: Timeout em segundos

        Returns:
            (is_valid: bool, message: str)
        """
        if not url or url.startswith("data:"):
            # Data URIs e strings vazias so vlidas (no precisam validao)
            return True, "Data URI ou vazio"

        try:
            # Fazer HEAD request para validar URL
            response = requests.head(url, timeout=timeout, allow_redirects=True)
            if response.status_code < 400:
                debug(
                    f"[ASSET] URL validada: {url[:60]}... (status {response.status_code})"
                )
                return True, f"URL acessvel (status {response.status_code})"
            else:
                debug(
                    f"[ASSET] URL retornou status {response.status_code}: {url[:60]}..."
                )
                return False, f"URL retornou status {response.status_code}"
        except requests.exceptions.Timeout:
            debug(f"[ASSET] URL timeout (>{timeout}s): {url[:60]}...")
            return False, f"URL timeout (>{timeout}s)"
        except requests.exceptions.ConnectionError as e:
            debug(f"[ASSET] URL invlida/inacessvel: {url[:60]}... ({str(e)[:50]}...)")
            return False, "URL invlida ou inacessvel"
        except Exception as e:
            debug(f"[ASSET] Erro ao validar URL: {str(e)[:100]}")
            return False, f"Erro ao validar: {type(e).__name__}"

    def _build_extra_params(
        self,
        media_type: str,
        model: str,
        image_input: str,
        aspect_ratio: str,
        duration: int,
        first_frame_image: str,
        last_frame_image: str,
        temperature: float,
    ) -> Dict[str, Any]:
        """
        Mapeia parmetros genricos (image_input, aspect_ratio, etc) para os campos especficos do modelo.

        Cada modelo Replicate espera seus prprios nomes de parmetros. Essa funo centraliza
        o mapeamento para que a IA sempre use names genricos.

        Args:
            media_type: 'image', 'video' ou 'vision'
            model: ID do modelo
            image_input: Imagem/referncia genrica (convertida para o campo correto do modelo)
            aspect_ratio: Proporo para imagens
            duration: Durao para vdeos (segundos)
            first_frame_image: Primeiro frame (optional, para vdeos)
            last_frame_image: ltimo frame (optional, para futuros modelos)
            temperature: Temperatura para vision

        Returns:
            Dict com extra_params no formato esperado pelo modelo
        """
        extra = {}

        if media_type == "image":
            # Modelos image (nano-banana, seedream) usam "image_input"
            if image_input:
                extra["image_input"] = [image_input]
            if aspect_ratio:
                extra["aspect_ratio"] = aspect_ratio

        elif media_type == "video":
            if model == "veo-3.1":
                # veo-3.1 usa "reference_images" (array)
                if image_input:
                    extra["reference_images"] = [image_input]
                if duration:
                    extra["duration"] = duration
            elif model == "minimax-video-01":
                # minimax usa "subject_reference" (string) e opcionalmente "first_frame_image"
                if image_input:
                    extra["subject_reference"] = image_input
                if first_frame_image:
                    extra["first_frame_image"] = first_frame_image
                if duration:
                    extra["duration"] = duration

            # last_frame_image: ser ignorado se o modelo no suportar, mas deixamos passar
            if last_frame_image:
                extra["last_frame_image"] = last_frame_image

        elif media_type == "vision":
            # Vision usa "image_input" como ARRAY (compatvel com Replicate API)
            if image_input:
                extra["image_input"] = [image_input]  #  Replicate espera array
            if temperature is not None:
                extra["temperature"] = temperature

        return extra

    def _resolve_image_input_to_url(
        self, image_input: str, chat_id: str = "", user_id: str = ""
    ) -> str:
        """
        Converte IDs de attachment ou asset para URLs temporrias.
        Se for URL http ou data URI, retorna como est.
        Se for attachment ID (sufixo _attach), gera URL temporria.
        Se for UUID de asset gerado naquele chat, busca e gera URL temporria.

        Args:
            image_input: URL, data URI, attachment ID ou asset UUID do chat
            chat_id: ID do chat (necessrio para gerar URL temporria)
            user_id: ID do usurio (necessrio para gerar URL temporria)

        Returns:
            URL completa ou o input original se no conseguir converter
        """
        if not image_input:
            return image_input

        # Se for URL http ou https, retornar como est
        if image_input.startswith("http://") or image_input.startswith("https://"):
            debug(f"[RESOLVE_IMAGE] URL http detectada: {image_input[:60]}...")
            return image_input

        # Se for data URI (base64), retornar como est
        if image_input.startswith("data:"):
            debug(f"[RESOLVE_IMAGE] Data URI detectada")
            return image_input

        # Se for attachment ID (começa com "attach_")
        if image_input.startswith("attach_"):
            debug(f"[RESOLVE_IMAGE] Attachment ID detectado: {image_input}")
            if chat_id and user_id:
                if is_public_url_online():
                    try:
                        from App.Core.Utils.TempTokenStore import build_file_url
                        from App.Core.Crunch.Storage.StorageManager import (
                            StorageManager,
                        )
                        from pathlib import Path as _Path
                        from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager

                        row = DatabaseManager.fetch_one(
                            "SELECT storage_path, storage_env FROM attachments "
                            "WHERE attachment_id = :aid AND user_id = :uid AND deleted_at IS NULL LIMIT 1",
                            {"aid": image_input, "uid": user_id},
                        )
                        if row:
                            sp = row.get("storage_path") or ""
                            fp = (
                                str(StorageManager.LOCAL_STORAGE_BASE / _Path(sp))
                                if row.get("storage_env") == "local"
                                else sp
                            )
                            url = build_file_url(fp)
                            debug(f"[RESOLVE_IMAGE] URL pública gerada para attachment")
                            return url
                    except Exception as e:
                        debug(
                            f"[RESOLVE_IMAGE] Erro ao gerar URL pública para attachment: {e}"
                        )
                # public_url offline ou erro: usar base64
                b64 = _attachment_as_base64(image_input, user_id)
                if b64:
                    debug(f"[RESOLVE_IMAGE] base64 ativo para attachment {image_input}")
                    return b64

        # Se for UUID de asset gerado (UUID sem extensão, 36 chars)
        # DB armazena asset_id com extensão (ex: "uuid.jpg"), por isso usamos LIKE
        if "-" in image_input and len(image_input) == 36 and chat_id and user_id:
            debug(f"[RESOLVE_IMAGE] UUID de asset detectado: {image_input}")
            try:
                query = """
                    SELECT asset_id, storage_path, storage_env
                    FROM assets
                    WHERE (asset_id = :asset_id OR asset_id LIKE :asset_id_prefix)
                      AND chat_id = :chat_id AND user_id = :user_id
                    LIMIT 1
                """
                result = self.db_manager.fetch_one(
                    query,
                    {
                        "asset_id": image_input,
                        "asset_id_prefix": f"{image_input}.%",
                        "chat_id": chat_id,
                        "user_id": user_id,
                    },
                )

                if result:
                    debug(
                        f"[RESOLVE_IMAGE] Asset encontrado no chat (asset_id={result.get('asset_id')})"
                    )
                    if is_public_url_online():
                        try:
                            from App.Core.Utils.TempTokenStore import build_file_url
                            from pathlib import Path as _Path

                            sp = result.get("storage_path") or ""
                            if result.get("storage_env", "local") == "local":
                                fp = str(StorageManager.LOCAL_STORAGE_BASE / _Path(sp))
                            else:
                                fp = sp
                            url = build_file_url(fp)
                            debug(
                                f"[RESOLVE_IMAGE] URL pública gerada para asset {image_input}"
                            )
                            return url
                        except Exception as e:
                            debug(
                                f"[RESOLVE_IMAGE] Erro ao gerar URL pública para asset: {e}"
                            )
                    # public_url offline ou erro: usar base64
                    b64 = _asset_as_base64(image_input, user_id)
                    if b64:
                        debug(f"[RESOLVE_IMAGE] base64 gerado para asset {image_input}")
                        return b64
                else:
                    debug(
                        f"[RESOLVE_IMAGE] Asset não encontrado no chat: {image_input}"
                    )
            except Exception as e:
                debug(f"[RESOLVE_IMAGE] Erro ao buscar asset: {e}")

        # Se não conseguir converter, retorna como está
        debug(f"[RESOLVE_IMAGE] Input retornado sem conversão: {image_input[:40]}...")
        return image_input

    def _vision_openai_gpt4o(
        self, prompt: str, params: Dict[str, Any]
    ) -> Optional[str]:
        """Anlise de imagem via OpenAI GPT-4o REST API."""
        try:
            from App.Core.Settings.Settings import get_openai_api_key

            api_key = get_openai_api_key()
            if not api_key:
                error("[VISION-OPENAI] OpenAI API Key no encontrada")
                return None

            image_input = params.get("image") or params.get("image_input")
            if not image_input:
                return None

            # Payload formatado para GPT-4o Vision
            payload = {
                "model": "gpt-4o",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": image_input}},
                        ],
                    }
                ],
            }

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            }

            debug(f"[VISION-OPENAI] Chamando GPT-4o para imagem: {image_input[:60]}...")
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=60,
            )

            if response.status_code != 200:
                error(
                    f"[VISION-OPENAI] Erro API OpenAI ({response.status_code}): {response.text}"
                )
                return None

            data = response.json()
            if "choices" in data and len(data["choices"]) > 0:
                return data["choices"][0]["message"]["content"]

            return None
        except Exception as e:
            error(f"[VISION-OPENAI] Erro: {e}")
            return None

    def _vision_fallback_to_claude(
        self, prompt: str, params: Dict[str, Any]
    ) -> Optional[str]:
        """Fallback para Claude 3.5 Sonnet via REST API."""
        try:
            from App.Core.Settings.Settings import get_anthropic_api_key

            api_key = get_anthropic_api_key()
            if not api_key:
                return None

            image_input = params.get("image") or params.get("image_input")
            debug(
                "[VISION-FALLBACK] Claude fallback ignorado (exige base64/SDK complexo)"
            )
            return None
        except:
            return None

    def _execute_vision(self, args: Dict[str, Any]) -> str:
        """
        Executa tool 'vision' para anlise de imagens usando OpenAI GPT-4o.
        """
        # ========== VALIDAO DE ESTRUTURA PADRO ==========
        prompt = args.get("prompt", "").strip()
        _raw_image_input = args.get("image_input", "")
        # LLM às vezes passa lista; pegar o primeiro elemento
        if isinstance(_raw_image_input, list):
            _raw_image_input = _raw_image_input[0] if _raw_image_input else ""
        image_input = str(_raw_image_input).strip()

        if not prompt or not image_input:
            return json.dumps(
                {
                    "success": False,
                    "error": 'Estrutura invlida para vision(). OBRIGATRIO: vision(prompt="...", image_input="...")',
                    "tool": "vision",
                },
                ensure_ascii=False,
            )

        # Validar image_input: deve ser URL direta de imagem, attachment_id (attach_*), data URI ou asset UUID.ext
        import re as _re

        _UUID_IMG_RE = _re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.(jpg|jpeg|png|webp|gif|fav|ico|avif|bmp|tiff)$",
            _re.IGNORECASE,
        )
        _PHOTO_EXTS = (
            ".jpg",
            ".jpeg",
            ".png",
            ".webp",
            ".gif",
            ".fav",
            ".ico",
            ".avif",
            ".bmp",
            ".tiff",
        )
        _is_http_url = image_input.startswith("http://") or image_input.startswith(
            "https://"
        )
        _is_data_uri = image_input.startswith("data:")
        if not _is_http_url and not _is_data_uri:
            return json.dumps(
                {
                    "success": False,
                    "error": (
                        f"vision() requer URL pública ou data URI — recebeu: '{image_input[:80]}'. "
                        "Use generate_temporary_public_url para converter attachment_id ou asset_id em URL pública antes de chamar vision()."
                    ),
                    "tool": "vision",
                    "hint": (
                        "generate_temporary_public_url(attachment_id='attach_XXXX') → URL pública\n"
                        "generate_temporary_public_url(filename='imagem.png') → URL pública\n"
                        "Então: vision(image_input='<url_retornada>')"
                    ),
                },
                ensure_ascii=False,
            )

        image_url = image_input

        # Chamar visão com fallback (OpenAI → Claude)
        analysis = _call_vision_with_fallback(image_url, prompt)

        if analysis:
            return json.dumps(
                {
                    "success": True,
                    "content": analysis,
                    "type": "vision",
                    "model": "gpt-4o",
                },
                ensure_ascii=False,
            )
        else:
            return json.dumps(
                {
                    "success": False,
                    "error": "Vision falhou em todos os provedores",
                    "tool": "vision",
                },
                ensure_ascii=False,
            )

    def _execute_asset_direct(self, args: Dict[str, Any]) -> str:
        """Geração direta de imagem com type + prompt (sem document_id). Usado pelo art-generator."""
        asset_type = (args.get("type") or "image").strip().lower()
        prompt = (args.get("prompt") or "").strip()
        aspect_ratio = (args.get("aspect_ratio") or "4:5").strip()
        generated_content_id = (
            args.get("generated_content_id") or str(uuid_lib.uuid4())
        ).strip()

        # Imagem de referência — pode ser attach_ID, URL ou lista
        raw_image_input = args.get("image_input") or args.get("reference_image") or ""
        if isinstance(raw_image_input, list):
            raw_image_input = raw_image_input[0] if raw_image_input else ""
        image_input_resolved = None
        if raw_image_input:
            image_input_resolved = self._resolve_image_input_to_url(
                raw_image_input,
                chat_id=self.current_chat_id or "",
                user_id=self.current_user_id or "",
            )

        if not prompt:
            return json.dumps(
                {"success": False, "error": "prompt é obrigatório"}, ensure_ascii=False
            )

        from App.Core.Settings.Settings import load_llm_config

        llm_config = load_llm_config()
        google_keys = llm_config.get("providers", {}).get("google", {}).get("keys", [])
        gemini_api_key = google_keys[0].get("key", "") if google_keys else ""

        debug(
            f"[ASSET-DIRECT] Gerando {asset_type} | aspect_ratio={aspect_ratio} | image_ref={bool(image_input_resolved)} | prompt={prompt[:80]}..."
        )

        result = assets_run_model_logic(
            prompt,
            extra_args={"aspect_ratio": aspect_ratio},
            human_mode=False,
            api_key=gemini_api_key,
            return_binary=True,
            chat_id=self.current_chat_id,
            user_id=self.current_user_id,
            image_input=image_input_resolved,
        )

        if not (isinstance(result, dict) and result.get("success")):
            err = (
                result.get("error", "Falha na geração")
                if isinstance(result, dict)
                else "Resultado inesperado"
            )
            debug(f"[ASSET-DIRECT] Falha: {err}")
            return json.dumps({"success": False, "error": err}, ensure_ascii=False)

        # Salvar arquivo
        content_type = ASSET_TYPE_TO_CONTENT_TYPE.get(
            asset_type, AssetContentType.IMAGE.value
        )
        file_ext = ASSET_CONTENT_TYPE_TO_EXTENSION.get(content_type, ".jpg")
        filename = f"art-{str(uuid_lib.uuid4())[:8]}{file_ext}"
        storage_path = ""

        if self.current_user_id and self.current_chat_id and "content" in result:
            try:
                session = self.db_manager.get_session()
                try:
                    user = (
                        session.query(User)
                        .filter(User.user_id == self.current_user_id)
                        .first()
                    )
                    client_id = user.client_id if user else None
                finally:
                    session.close()

                StorageManager.save_file(
                    client_id=client_id,
                    user_id=self.current_user_id,
                    chat_uuid=self.current_chat_id,
                    folder_type="assets",
                    filename=filename,
                    content=result["content"],
                    is_binary=True,
                )
                storage_path = f"client_{client_id}/user_{self.current_user_id}/chat_{self.current_chat_id}/assets/{filename}"

                # Registrar em generated_content
                try:
                    content_uuid = UUID(generated_content_id)
                except Exception:
                    content_uuid = UUID(str(uuid_lib.uuid4()))

                session2 = self.db_manager.get_session()
                try:
                    gc = GeneratedContent(
                        asset_id=str(content_uuid),
                        type=content_type,
                        content_name=filename,
                        user_id=self.current_user_id,
                        client_id=client_id,
                        chat_id=self.current_chat_id,
                        storage_path=storage_path,
                        storage_env="local",
                        version=1,
                    )
                    session2.add(gc)
                    session2.commit()
                    debug(
                        f"[ASSET-DIRECT] Registrado em generated_content: {content_uuid}"
                    )
                except Exception as e:
                    session2.rollback()
                    debug(f"[ASSET-DIRECT] Erro ao registrar: {e}")
                finally:
                    session2.close()

            except Exception as e:
                debug(f"[ASSET-DIRECT] Erro ao salvar: {e}")

        return json.dumps(
            {
                "success": True,
                "tool": "asset",
                "type": asset_type,
                "asset_id": generated_content_id,
                "content_id": generated_content_id,
                "filename": filename,
                "storage_path": storage_path,
            },
            ensure_ascii=False,
        )

    def _execute_asset(self, args: Dict[str, Any]) -> str:
        """
        Executa tool 'asset' para gerar assets (imagens ou vdeos) a partir de documentos copywriting.

        ASSET OBRIGATORIAMENTE VINCULADO A COPYWRITING:
        - document_id  OBRIGATRIO
        - type, prompt e outras informaes so extradas do documento copywriting
        - No aceita outros tipos de documentos

        Args:
            args: Dict com:
                - document_id: ID do documento copywriting - OBRIGATRIO
                - prompt: Descrio adicional (opcional, sobrescreve a do documento se fornecido)
                - help: Se true, retorna documentao das ferramentas
                - context: Se true, retorna histrico de execues anteriores

        Returns:
            JSON com resultado ou mensagem de erro
        """
        help_mode = args.get("help", False)

        # ========== VALIDAO: document_id ou document_ids  OBRIGATRIO ==========
        doc_id = args.get("document_id", "").strip()
        doc_ids = args.get("document_ids", [])

        # Converter para lista se document_id foi fornecido
        if doc_id and not doc_ids:
            doc_ids = [doc_id]

        if not doc_ids or len(doc_ids) == 0:
            # Geração direta: type + prompt fornecidos sem document_id (ex: art-generator)
            _direct_type = (args.get("type") or "").strip()
            _direct_prompt = (args.get("prompt") or "").strip()
            if _direct_type and _direct_prompt:
                return self._execute_asset_direct(args)
            return json.dumps(
                {
                    "success": False,
                    "error": "Informe qual copywriting deve ser utilizada para executar a gerao do ativo",
                    "tool": "asset",
                    "hint": "1. Crie documentos copywriting: document(type='copywriting', title='...', data={...})\n2. Use asset(document_id='<uuid-retornado>') ou asset(document_ids=['<uuid1>', '<uuid2>', ...])",
                },
                ensure_ascii=False,
            )

        # ========== VALIDAO: Todos os document_ids devem ser copywriting ==========
        all_results = {
            "success": True,
            "total_documents": len(doc_ids),
            "processed": [],
            "errors": [],
        }

        for doc_id in doc_ids:
            is_valid, error_msg, doc_data = self._validate_copywriting_document_id(
                doc_id
            )
            if not is_valid:
                all_results["errors"].append(
                    {"document_id": doc_id, "error": error_msg}
                )
                all_results["success"] = False
                continue

            # Se todos os assets j foram gerados, no chamar Assets.py
            if doc_data.get("status") == "done":
                debug(
                    f"[ASSET] Documento {doc_id} j finalizado (status=done), pulando gerao"
                )
                all_results["processed"].append(
                    {
                        "document_id": doc_id,
                        "result": {
                            "success": True,
                            "message": "All assets already generated",
                            "generated_assets": [],
                            "credits_consumed": 0.0,
                            "credits_remaining": 0.0,
                            "status": "done",
                        },
                    }
                )
                continue

            # ========== EXTRAIR DADOS DO DOCUMENTO COPYWRITING ==========
            media_type = doc_data.get("media_type", "image").lower()

            # Roteamento: se variation.count > 0 → modo variação
            _variation_data = doc_data.get("variation") or {}
            _variation_count = int(_variation_data.get("count", 0))
            if _variation_count > 0:
                debug(
                    f"[ASSET] Documento {doc_id} tem variation.count={_variation_count}, roteando para _execute_asset_variation_mode"
                )
                result = self._execute_asset_variation_mode(
                    doc_id,
                    doc_data,
                    _variation_data,
                    isolated_message_id=self.current_isolated_message_id,
                )
                all_results["processed"].append(
                    {"document_id": doc_id, "result": result}
                )
                continue

            # Redirecionar para gerao batch de copywriting
            debug(
                f"[ASSET] Gerando assets a partir de copywriting document_id={doc_id}, media_type={media_type}"
            )
            result = self._generate_all_copy_assets(doc_id)

            all_results["processed"].append({"document_id": doc_id, "result": result})

        # ── RESET GATE: Se houver sucesso em algum documento, resetar gate de SkillCopywriting ──
        any_success = any(
            (p.get("result") or {}).get("success") is True
            for p in all_results["processed"]
        )
        if any_success and self.db_manager and self.current_chat_id:
            try:
                self.db_manager.save_isolated_message(
                    chat_id=self.current_chat_id,
                    role="system",
                    content="[FLOW_CANCELLED] Assets generated successfully. SkillCopywriting cycle completed.",
                    user_id=self.current_user_id,
                )
                debug(
                    "[ASSET] Copywriting gate reset successfully via [FLOW_CANCELLED]"
                )
            except Exception as _re:
                debug(f"[ASSET] Failed to reset gate: {_re}")

        return json.dumps(all_results, ensure_ascii=False)

        # ========== VALIDAO: ID  obrigatrio para outros asset types ==========
        if (
            asset_type not in [AssetType.VISION.value, "brand_communication"]
            and not asset_id
        ):
            return json.dumps(
                {
                    "success": False,
                    "error": f"Campo 'id'  OBRIGATRIO para type={asset_type}. Este deve ser um post_id retornado por calendar(plan=[...]). Exemplo: id=\"P001_awareness_001\"",
                    "tool": "asset",
                    "hint": "Use calendar(plan=[{day: 'dd/mm/aaaa', content: 'nome'}, ...]) para gerar os IDs das postagens",
                },
                ensure_ascii=False,
            )

        # ========== wait=true  ignorado no Core.py ==========
        # O MessageProcessor usa wait para quebrar o loop
        # Core.py sempre executa a tool completamente e retorna o resultado real

        # Novos parmetros genricos (sem seleo de modelo)
        # Aceitar tanto 'image_input' (vision) quanto 'reference_image' (asset)
        image_input = args.get("image_input") or args.get("reference_image", "")
        print(f"[ASSET-DEBUG] image_input extrado de args: {image_input}")
        debug(f"[ASSET-DEBUG] image_input extrado de args: {image_input}")

        aspect_ratio = args.get("aspect_ratio", "")
        duration = args.get("duration")  # int
        first_frame_image = args.get("first_frame_image", "")
        last_frame_image = args.get("last_frame_image", "")
        temperature = args.get("temperature")  # float
        # Aceitar tanto 'post_id' quanto 'id' do schedule (id da postagem no calendrio - OPCIONAL)
        post_id = (args.get("post_id") or args.get("id", "")).strip()
        # Title para identificao do asset (opcional)
        title = args.get("title", "").strip()
        # Caption para SEO/LLM (opcional)
        caption = args.get(
            "caption"
        )  # dict com header_seo, direct_answer, deep_content
        if caption and isinstance(caption, dict):
            caption_json = json.dumps(caption, ensure_ascii=False)
        else:
            caption_json = None

        # Backward compatibility: se enviar extra_params como antes, merge com os novos params
        extra_params = args.get("extra_params", {})

        # ========== NOVOS PARMETROS PARA BRAND_COMMUNICATION ==========
        # Parmetros para atualizar documento brand_communication automaticamente
        brand_field = args.get("brand_field", "").strip()  # ex: "exclusive_avatar.url"
        document_id = args.get(
            "document_id", ""
        ).strip()  # ID do documento brand_communication

        # Se agent enviar help=true, listar assets ou carregar documentao
        if help_mode is True:
            # Se for apenas help=true sem asset_type, listar assets
            if not asset_type:
                return self._get_assets_list()

            # Tentar carregar help especfico da ferramenta (asset, vision)
            if asset_type in [AssetType.IMAGE.value, AssetType.VIDEO.value]:
                help_data = self._get_tool_help("asset")
            elif asset_type == AssetType.VISION.value:
                help_data = self._get_tool_help("vision")
            else:
                help_data = self._get_tool_help("asset")  # Fallback
            return json.dumps(help_data, ensure_ascii=False)

        # Se enviar sem parametros vlidos, mostrar help com aviso
        if not asset_type and not prompt:
            help_data = self._get_tool_help("asset")
            help_data[
                "warning"
            ] = "Parmetros obrigatrios faltando: type (image|video) e prompt"
            return json.dumps(help_data, ensure_ascii=False)

        # Validaes para gerao - se algo faltar, mostrar help com success=false
        error_msg = None
        if not asset_type:
            error_msg = (
                "Tipo de asset  obrigatrio (image, video, vision, brand_communication)"
            )
        elif not prompt:
            error_msg = "Prompt  obrigatrio"
        elif asset_type not in [
            AssetType.IMAGE.value,
            AssetType.VIDEO.value,
            AssetType.VISION.value,
            "brand_communication",
        ]:
            error_msg = f"Tipo de asset invlido: {asset_type}. Use: {AssetType.IMAGE.value}, {AssetType.VIDEO.value}, {AssetType.VISION.value} ou brand_communication"
        elif (
            asset_type
            in [AssetType.IMAGE.value, AssetType.VIDEO.value, "brand_communication"]
            and not asset_name
        ):
            # name  OBRIGATRIO para asset (para nomear o arquivo)
            error_msg = "Nome do asset  obrigatrio para gerao (name='nomeDaMidia')"
        elif asset_type == AssetType.VIDEO.value and not image_input:
            # image_input  OBRIGATRIO apenas para video
            error_msg = "reference_image  obrigatrio para vdeo (URL, data URI ou filename da referncia visual)"
        elif asset_type == AssetType.VISION.value and not image_input:
            error_msg = "image_input  obrigatrio para anlise de imagem"
        elif asset_type == "brand_communication":
            # Validaes especficas para brand_communication
            # Exigir que lookup(file="SkillPromptEngineering.md") tenha sido chamado
            if not self._check_prompt_engineering_in_chat():
                error_msg = "Consulte SkillPromptEngineering antes de gerar brand_communication assets: lookup(file='SkillPromptEngineering.md')"
            elif not brand_field:
                error_msg = "brand_field  obrigatrio para brand_communication (ex: 'exclusive_avatar.url', 'moodboard.url')"
            elif not document_id:
                error_msg = "document_id  obrigatrio para brand_communication (ID do documento para atualizar)"
        # image_input  OPCIONAL para image (pode gerar sem referncia)
        # post_id  OPCIONAL - permite gerar mdia sem vincular a schedule

        if error_msg:
            debug(f"[ASSET] Parmetro invlido detectado: {error_msg}")
            help_data = self._get_tool_help("asset")
            help_data["error_log"] = error_msg
            return json.dumps(help_data, ensure_ascii=False)

        # ========== BRAND_COMMUNICATION: Tratar como image generation ==========
        # brand_communication usa o mesmo fluxo de gerao que image, mas com documento update adicional
        asset_type_for_generation = asset_type
        if asset_type == "brand_communication":
            asset_type_for_generation = AssetType.IMAGE.value
            # Gerar nome determinstico baseado no brand_field para permitir sobrescrita
            # Exemplo: "exclusive_avatar.url" -> "exclusive_avatar"
            if brand_field:
                field_name = brand_field.split(".")[
                    0
                ]  # Extrair primeira parte (exclusive_avatar)
                asset_name = (
                    field_name  # Sobrescrever asset_name com nome determinstico
                )
                debug(
                    f"[ASSET] Nome determinstico para brand_communication: {asset_name} (baseado em {brand_field})"
                )
            debug(f"[ASSET] brand_communication detectado, usando gerao de image")

        # Seleo automtica de modelo baseada em asset_type
        model = self._select_model(asset_type_for_generation)

        # Construir extra_params com mapeamento automtico de image_input para campo especfico do modelo
        extra_params = self._build_extra_params(
            media_type=asset_type_for_generation,
            model=model,
            image_input=image_input,
            aspect_ratio=aspect_ratio,
            duration=duration,
            first_frame_image=first_frame_image,
            last_frame_image=last_frame_image,
            temperature=temperature,
        )

        # Adicionar user_id e chat_id aos extra_params para resoluo de UUIDs
        if extra_params:
            extra_params["user_id"] = self.current_user_id
            extra_params["chat_id"] = self.current_chat_id

        # Garantir que image_input est em extra_params se foi resolvido
        if image_input and asset_type == AssetType.IMAGE.value:
            if not extra_params:
                extra_params = {}
            extra_params["image_input"] = (
                [image_input] if isinstance(image_input, str) else image_input
            )
            print(
                f"[ASSET-DEBUG] Adicionado image_input a extra_params: {image_input[:60]}..."
            )
            debug(f"[ASSET-DEBUG] Adicionado image_input a extra_params")

        try:
            debug(
                f"[ASSET] Gerando {asset_type} com modelo {model} (automtico): {prompt[:50]}..."
            )

            # Para vision models: comprimir imagem antes de enviar
            if (
                asset_type == AssetType.VISION.value
                and extra_params
                and "image_input" in extra_params
            ):
                image_input_array = extra_params.get("image_input", [])
                if isinstance(image_input_array, list) and len(image_input_array) > 0:
                    original_image = image_input_array[0]
                    if original_image.startswith("data:"):
                        compressed_image = self._compress_base64_image_for_vision(
                            original_image
                        )
                        if compressed_image:
                            extra_params["image_input"] = [compressed_image]
                            debug("[MEDIAAI] Imagem comprimida para vision")

            # Processar image_input/images/reference_images/first_frame_image/subject_reference: converter nome do arquivo para data URI
            if extra_params and self.db_manager:
                processed_params = extra_params.copy()
                image_fields = [
                    "image_input",
                    "images",
                    "init_image",
                    "reference_images",
                    "first_frame_image",
                    "subject_reference",
                ]

                for field in image_fields:
                    if field in processed_params:
                        value = processed_params[field]

                        # Converter para lista se for string nico
                        filenames = (
                            value
                            if isinstance(value, list)
                            else [value]
                            if isinstance(value, str)
                            else []
                        )

                        if filenames:
                            try:
                                data_uris = []
                                db_session = self.db_manager.get_session()

                                for filename in filenames:
                                    if not filename:
                                        continue

                                    # Se  URL, usar direto sem fazer query
                                    if isinstance(
                                        filename, str
                                    ) and filename.startswith("http"):
                                        data_uris.append(filename)
                                        debug(
                                            f"[MEDIAAI] {field}  URL, usando direto: {filename[:60]}..."
                                        )
                                        continue

                                    # Consultar attachments pelo attachment_id (apenas arquivos locais)
                                    from sqlalchemy import text

                                    query = text(
                                        """
                                        SELECT storage_path FROM attachments
                                        WHERE attachment_id = :attachment_id AND user_id = :user_id AND deleted_at IS NULL
                                        LIMIT 1
                                    """
                                    )
                                    result = db_session.execute(
                                        query,
                                        {
                                            "attachment_id": filename,
                                            "user_id": self.current_user_id,
                                        },
                                    ).fetchone()

                                    if result:
                                        storage_path = result[0]
                                        # Ler arquivo e converter para data URI
                                        from pathlib import Path
                                        import base64

                                        base_path = StorageManager.LOCAL_STORAGE_BASE
                                        file_path = base_path / storage_path

                                        if file_path.exists():
                                            # Detectar tipo MIME baseado em extenso
                                            ext = file_path.suffix.lower()
                                            mime_types = {
                                                ".webp": "image/webp",
                                                ".jpg": "image/jpeg",
                                                ".jpeg": "image/jpeg",
                                                ".png": "image/png",
                                                ".gif": "image/gif",
                                            }
                                            mime_type = mime_types.get(
                                                ext, "image/webp"
                                            )

                                            # Ler arquivo e converter para base64
                                            with open(file_path, "rb") as f:
                                                image_data = base64.b64encode(
                                                    f.read()
                                                ).decode("utf-8")

                                            # Converter para data URI com prefixo
                                            data_uri = (
                                                f"data:{mime_type};base64,{image_data}"
                                            )
                                            data_uris.append(data_uri)

                                            rel_path = StorageManager.get_relative_path(
                                                file_path
                                            )
                                            debug(
                                                f"[MEDIAAI] Convertido {field}: {filename} ({rel_path})  data URI ({len(image_data)} chars)"
                                            )
                                        else:
                                            rel_path = StorageManager.get_relative_path(
                                                file_path
                                            )
                                            debug(
                                                f"[MEDIAAI] Arquivo no encontrado no storage: {rel_path}"
                                            )

                                    else:
                                        debug(
                                            f"[MEDIAAI] Arquivo no encontrado na tabela attachments: {filename}"
                                        )

                                if data_uris:
                                    processed_params[field] = data_uris

                                db_session.close()
                            except Exception as e:
                                debug(f"[MEDIAAI] Erro ao processar {field}: {e}")
                                import traceback

                                debug(f"[MEDIAAI] Traceback: {traceback.format_exc()}")

                extra_params = processed_params

            # ========== VALIDAR URLs ANTES de enviar ao Replicate (apenas para video/vision, no para image) ==========
            if extra_params and asset_type != AssetType.IMAGE.value:
                # Validar reference_image ou image_input se enviados (apenas para Replicate)
                url_fields = ["reference_images", "image_input"]
                for field in url_fields:
                    if field in extra_params:
                        urls = extra_params[field]
                        if isinstance(urls, list) and len(urls) > 0:
                            url_to_check = urls[0] if isinstance(urls[0], str) else None
                            if url_to_check and url_to_check.startswith("http"):
                                is_valid, message = self._validate_and_clean_url(
                                    url_to_check
                                )
                                if not is_valid:
                                    debug(
                                        f"[ASSET] URL invlida detectada ({message}), removendo {field} dos parmetros"
                                    )
                                    extra_params.pop(field, None)
                                    # Se era image_input obrigatrio para video, tentar sem
                                    if (
                                        field == "image_input"
                                        and asset_type == AssetType.VIDEO.value
                                    ):
                                        debug(
                                            f"[ASSET] Video sem reference_image - ser enviado ao Replicate"
                                        )

            # Obter API keys da configurao (confidential-llm.json)
            from App.Core.Settings.Settings import load_llm_config

            llm_config = load_llm_config()
            replicate_keys = (
                llm_config.get("providers", {}).get("replicate", {}).get("keys", [])
            )
            replicate_api_key = (
                replicate_keys[0].get("key", "") if replicate_keys else ""
            )
            google_keys = (
                llm_config.get("providers", {}).get("google", {}).get("keys", [])
            )
            gemini_api_key = google_keys[0].get("key", "") if google_keys else ""

            # ===== ROTEADOR CONDICIONAL: Assets.py para imagens, Replicate para video/vision =====
            debug(
                f"[ASSET]  ROTEADOR: asset_type='{asset_type}' (tipo: {type(asset_type).__name__}), asset_type_for_generation='{asset_type_for_generation}'"
            )
            debug(
                f"[ASSET]  Comparao: '{asset_type_for_generation}' == '{AssetType.IMAGE.value}'? {asset_type_for_generation == AssetType.IMAGE.value}"
            )
            if asset_type_for_generation == AssetType.IMAGE.value:
                # Para imagens: usar Gemini 3 Pro Image via Assets.py (Gemini API)
                debug(
                    f"[ASSET]  IMAGE DETECTED - roteando para Assets.py com Gemini 3 Pro Image"
                )

                # image_input pode ser:
                # - string nica: "url" ou "attach_xxx" -> converte para ["url"] ou resolve para URL
                # - array: ["url1", "attach_xxx", ...] -> mantm e resolve attachment_ids
                # - reference_image (legacy): string ou array -> tambm suportado
                image_input_list = []
                if extra_params and "image_input" in extra_params:
                    img_input = extra_params["image_input"]
                    if isinstance(img_input, list):
                        image_input_list = img_input
                    elif isinstance(img_input, str):
                        image_input_list = [img_input]
                    debug(f"[ASSET] {len(image_input_list)} imagem(ns) via image_input")
                elif extra_params and "reference_image" in extra_params:
                    # Legacy support: reference_image -> convertendo para image_input
                    img_input = extra_params["reference_image"]
                    if isinstance(img_input, list):
                        image_input_list = img_input
                    elif isinstance(img_input, str):
                        image_input_list = [img_input]
                    debug(
                        f"[ASSET] {len(image_input_list)} imagem(ns) via reference_image (legacy)"
                    )

                # Passar imagens como estão — agente deve usar generate_temporary_public_url antes
                resolved_image_urls = [img for img in image_input_list if img]
                debug(f"[ASSET] image_input_list: {resolved_image_urls}")

                debug(
                    f"[ASSET] Resultado final resolved_image_urls: {resolved_image_urls}"
                )

                # Extrair dimenses e aspect_ratio para Assets (SEM defaults hardcoded)
                assets_params = {}
                if extra_params and "width" in extra_params:
                    assets_params["width"] = extra_params["width"]
                if extra_params and "height" in extra_params:
                    assets_params["height"] = extra_params["height"]
                if extra_params and "aspect_ratio" in extra_params:
                    assets_params["aspect_ratio"] = extra_params["aspect_ratio"]
                    debug(
                        f"[ASSET] aspect_ratio adicionado: {extra_params['aspect_ratio']}"
                    )

                # Passar image_input como array de mltiplas imagens (com URLs resolvidas)
                print(f"[ASSET-DEBUG] resolved_image_urls final: {resolved_image_urls}")
                if resolved_image_urls:
                    assets_params["image_input"] = resolved_image_urls
                    print(
                        f"[ASSET-DEBUG] Adicionado assets_params['image_input']: {resolved_image_urls}"
                    )
                    debug(
                        f"[ASSET] {len(resolved_image_urls)} URL(s) de imagem passada(s) para Assets.py"
                    )
                else:
                    print(f"[ASSET-DEBUG] resolved_image_urls vazio!")

                result = assets_run_model_logic(
                    prompt,
                    extra_args=assets_params if assets_params else None,
                    human_mode=False,
                    api_key=gemini_api_key,
                    return_binary=True,
                    chat_id=self.current_chat_id,
                    user_id=self.current_user_id,
                    image_input=resolved_image_urls if resolved_image_urls else None,
                )
                debug(f"[ASSET] Usando Assets.py para gerao de imagem")
            else:
                # Para vdeo e viso: usar Replicate
                debug(
                    f"[ASSET]  NON-IMAGE TYPE - roteando para Replicate com asset_type={asset_type}"
                )
                result = replicate_run_model_logic(
                    model,
                    prompt,
                    human_mode=False,
                    extra_args=extra_params,
                    target_type=asset_type,
                    api_key=replicate_api_key,
                    return_binary=True,
                )

            # Logging detalhado do resultado da Replicate API
            debug(f"[MEDIAAI] Replicate result type: {type(result)}")
            if isinstance(result, dict):
                debug(f"[MEDIAAI] Replicate result keys: {list(result.keys())}")
                debug(f"[MEDIAAI] Replicate success: {result.get('success')}")
                if not result.get("success"):
                    debug(f"[MEDIAAI] Replicate error: {result.get('error')}")
                    debug(
                        f"[MEDIAAI] Replicate full response: {json.dumps(result, ensure_ascii=False, default=str)}"
                    )
            else:
                debug(f"[MEDIAAI] Replicate result (non-dict): {result}")

            if isinstance(result, dict) and result.get("success"):
                # Vision models retornam anlise de texto, no arquivos
                if asset_type == AssetType.VISION.value:
                    # Replicate.py retorna com chave "content" para vision models
                    analysis_text = result.get("content")

                    return json.dumps(
                        {
                            "success": True,
                            "content": analysis_text or "Anlise no disponvel",
                        },
                        ensure_ascii=False,
                    )

                # Image/Video models geram arquivos
                else:
                    # Mapear asset_type para tipo do Asset (antes de usar)
                    content_type = ASSET_TYPE_TO_CONTENT_TYPE.get(
                        asset_type, AssetContentType.IMAGE.value
                    )

                    # Usar o nome proposto pela IA, no o nome do modelo
                    # Adicionar extenso apropriada
                    file_extension = ASSET_CONTENT_TYPE_TO_EXTENSION.get(
                        content_type, ".jpg"
                    )
                    filename = f"{asset_name}{file_extension}"
                    used_model = model

                    # Salvar mdia no StorageManager (assets)
                    content_uuid = None  # Definir aqui para acessar na response
                    if (
                        self.current_user_id
                        and self.current_chat_id
                        and "content" in result
                    ):
                        session = None
                        try:
                            # Obter client_id do usurio
                            session = self.db_manager.get_session()
                            user = (
                                session.query(User)
                                .filter(User.user_id == self.current_user_id)
                                .first()
                            )
                            client_id = user.client_id if user else None
                            debug(
                                f"[ASSET] Obtido client_id={client_id} para user_id={self.current_user_id}, user={user}"
                            )

                            # ========== BRAND_COMMUNICATION: Salvar em client_{client_id}/assets/ ==========
                            if asset_type == "brand_communication":
                                # Salvar direto em client_{client_id}/assets/ (compartilhado)
                                assets_folder = StorageManager.get_client_assets_folder(
                                    client_id
                                )
                                file_path = assets_folder / filename
                                file_path.parent.mkdir(parents=True, exist_ok=True)
                                with open(file_path, "wb") as f:
                                    f.write(result["content"])
                                storage_path = f"client_{client_id}/assets/{filename}"
                                debug(
                                    f"[ASSET] Brand Communication asset salvo: {storage_path}"
                                )
                            else:
                                # Salvar em client_{client_id}/user_{user_id}/chat_{chat_uuid}/assets/
                                StorageManager.save_file(
                                    client_id=client_id,
                                    user_id=self.current_user_id,
                                    chat_uuid=self.current_chat_id,
                                    folder_type="assets",
                                    filename=filename,
                                    content=result["content"],
                                    is_binary=True,
                                )
                                storage_path = f"client_{client_id}/user_{self.current_user_id}/chat_{self.current_chat_id}/assets/{filename}"
                                debug(
                                    f"[ASSET] {asset_type.capitalize()} salvo no Storage: {filename}"
                                )

                            # Registrar no banco de dados como asset
                            # Salvar em generated_content table
                            try:
                                # Usar generated_content_id injetado pelo MessageProcessor ou gerar novo
                                if generated_content_id:
                                    try:
                                        # Converter string com ou sem hfens para UUID
                                        content_uuid = UUID(generated_content_id)
                                    except:
                                        content_uuid = UUID(str(uuid_lib.uuid4()))
                                else:
                                    content_uuid = UUID(str(uuid_lib.uuid4()))

                                # Criar registro em generated_content
                                # Caption e title so opcionais - se no fornecidos, criar asset com aviso
                                final_caption = caption_json
                                final_title = title if title else None
                                caption_warning = None
                                title_warning = None
                                if not final_caption:
                                    caption_warning = " Caption no fornecida. Use update(type='asset', id='asset_id', field='caption', value={...}) para adicionar depois"
                                    debug(f"[ASSET] {caption_warning}")
                                if not final_title:
                                    title_warning = " Title no fornecido. Use update(type='asset', id='asset_id', field='title', value='...') para adicionar depois"
                                    debug(f"[ASSET] {title_warning}")

                                generated_content = GeneratedContent(
                                    asset_id=str(content_uuid),
                                    type=content_type,
                                    content_name=filename,
                                    user_id=self.current_user_id,
                                    client_id=client_id,
                                    chat_id=self.current_chat_id,
                                    storage_path=storage_path,
                                    storage_env="local",
                                    title=final_title,
                                    caption=final_caption,
                                    version=1,
                                )
                                session.add(generated_content)
                                session.commit()
                                debug(
                                    f"[ASSET] Asset registrado em generated_content: {generated_content.asset_id} (caption={'sim' if final_caption else 'no'})"
                                )

                                #  Registrar evento de lifecycle
                                try:
                                    from App.Features.Tracking.LifecycleTracker import (
                                        LifecycleTracker,
                                    )

                                    LifecycleTracker.track(
                                        user_id=self.current_user_id,
                                        event_type="asset_created",
                                        chat_id=self.current_chat_id,
                                        metadata={
                                            "asset_id": str(content_uuid),
                                            "asset_type": content_type,
                                        },
                                    )
                                except Exception as lifecycle_error:
                                    error(
                                        f"[LIFECYCLE] Erro ao registrar asset_created: {lifecycle_error}"
                                    )

                            except Exception as e:
                                debug(f"[MEDIAAI] Erro ao registrar asset: {e}")
                                session.rollback()

                        except Exception as e:
                            debug(f"[MEDIAAI] Erro ao salvar no Storage: {e}")
                            # Continua mesmo se salvar falhar
                        finally:
                            if session:
                                session.close()

                    # NOTA: Sincronizao ser feita pelo MultiWorkerPool quando salvar output em isolated_messages
                    # No sincronizar aqui para evitar mensagens duplicadas

                    # Preparar resposta
                    response = {
                        "success": True,
                        "tool": "asset",
                        "type": asset_type,
                        "model": used_model,
                        "name": asset_name,
                        "prompt": prompt,
                        "filename": filename,
                        "post_id": post_id,
                        "asset_id": str(content_uuid) if content_uuid else None,
                        "message": f"{asset_type.capitalize()} gerado e vinculado ao post {post_id}",
                        "status": "saved_to_db_and_storage",
                    }

                    # ========== BRAND_COMMUNICATION: Atualizar documento com URL relativa ==========
                    if (
                        asset_type == "brand_communication"
                        and content_uuid
                        and document_id
                    ):
                        try:
                            # Gerar URL relativa para brand_communication (client_{id}/assets/filename)
                            relative_url = (
                                self._convert_brand_communication_to_relative_url(
                                    filename=filename, client_id=client_id
                                )
                            )

                            # Atualizar documento com URL relativa
                            self._update_brand_communication_document(
                                document_id=document_id,
                                brand_field=brand_field,
                                relative_url=relative_url,
                            )

                            # Converter para URL completa para resposta (usando proxy)
                            complete_url = self._convert_relative_to_complete_url(
                                relative_url
                            )

                            # Adicionar campos  resposta
                            response["document_updated"] = True
                            response["field_updated"] = brand_field
                            response[
                                "relative_url"
                            ] = complete_url  # Resposta com URL completa (proxy)
                            response[
                                "message"
                            ] = f"Asset gerado e documento brand_communication atualizado: {brand_field}"

                        except Exception as e:
                            debug(
                                f"[ASSET] Erro ao atualizar documento brand_communication: {e}"
                            )
                            response["document_update_error"] = str(e)
                            response["document_updated"] = False

                    # Adicionar avisos se caption ou title no foram fornecidos
                    if caption_warning:
                        response["caption_warning"] = caption_warning
                    if title_warning:
                        response["title_warning"] = title_warning

                    return json.dumps(response, ensure_ascii=False)
            else:
                error_msg = (
                    result.get("error", f"Falha ao gerar {asset_type}")
                    if isinstance(result, dict)
                    else str(result)
                )

                # FALLBACK: Se asset generation falhou (apenas para image/video)
                if asset_type in ["image", "video"]:
                    debug(
                        f"[ASSET] {asset_type.capitalize()} falhou ({error_msg}), tentando fallback..."
                    )
                    # Aqui voc poderia adicionar lgica de fallback se necessrio
                    # Por agora, apenas retornar erro

                # Se for vision, este erro vem do wrapper _execute_vision
                if asset_type == "vision":
                    debug(
                        f"[VISION] Vision falhou no Replicate ({error_msg}), tentando fallback Claude..."
                    )
                    fallback_analysis = self._vision_fallback_to_claude(
                        prompt, extra_params
                    )

                    if fallback_analysis:
                        original_tool_name = "vision"

                        return json.dumps(
                            {
                                "success": True,
                                "tool": original_tool_name,
                                "type": asset_type,
                                "model": "claude-3-5-sonnet (fallback)",
                                "prompt": prompt,
                                "analysis": fallback_analysis,
                                "message": "Anlise de imagem concluda com sucesso (usando Claude como fallback)",
                                "used_model": "claude-fallback",
                                "replicate_error": error_msg,
                            },
                            ensure_ascii=False,
                        )
                    else:
                        return json.dumps(
                            {
                                "success": False,
                                "error": f"Vision falhou no Replicate e no fallback Claude: {error_msg}",
                                "tool": "vision",
                                "replicate_error": error_msg,
                            },
                            ensure_ascii=False,
                        )

                # RETRY: Se asset image falhou com erro de URL invlida/inacessvel, reenviar SEM reference_image
                # (Nota: URLs j so validadas ANTES do envio ao Replicate, este  um fallback extra)
                elif (
                    asset_type == AssetType.IMAGE.value
                    and image_input
                    and any(
                        err in error_msg
                        for err in [
                            "403",
                            "404",
                            "Forbidden",
                            "NameResolutionError",
                            "ConnectionError",
                            "HTTPSConnection",
                            "Connection refused",
                            "Failed to resolve",
                        ]
                    )
                ):
                    debug(
                        f"[ASSET] Image falhou por URL inacessvel ({error_msg}), reenviando SEM reference_image..."
                    )

                    # Retry com Assets (sem imagens de entrada)
                    assets_params_retry = {}
                    if extra_params and "width" in extra_params:
                        assets_params_retry["width"] = extra_params["width"]
                    if extra_params and "height" in extra_params:
                        assets_params_retry["height"] = extra_params["height"]

                    retry_result = assets_run_model_logic(
                        prompt,
                        images=None,  # Reenviar SEM imagens
                        extra_args=assets_params_retry if assets_params_retry else None,
                        human_mode=False,
                        api_key=gemini_api_key,
                        return_binary=True,
                        chat_id=self.current_chat_id,
                        user_id=self.current_user_id,
                    )

                    debug(f"[MEDIAAI] Retry result type: {type(retry_result)}")
                    if isinstance(retry_result, dict):
                        debug(
                            f"[MEDIAAI] Retry result keys: {list(retry_result.keys())}"
                        )
                        debug(f"[MEDIAAI] Retry success: {retry_result.get('success')}")

                    if isinstance(retry_result, dict) and retry_result.get("success"):
                        debug(f"[ASSET]  Retry SEM reference_image funcionou!")
                        result = retry_result  # Usar resultado do retry - vai processar normalmente abaixo
                    else:
                        # Se retry falhar, continuar com fallback DALL-E 3
                        debug(
                            f"[ASSET] Retry SEM reference_image falhou tambm, usando fallback DALL-E 3..."
                        )
                        fallback_result = self._gen_img_fallback_dalle3(
                            prompt, asset_name
                        )

                        if fallback_result and fallback_result.get("success"):
                            result = fallback_result
                        else:
                            error_msg = f"Asset falhou no Replicate ({error_msg}), falhou SEM reference_image, e DALL-E 3 tambm falhou"
                            result = {"success": False, "error": error_msg}

                # FALLBACK: Se asset image falhou no Replicate (e NO houve retry), tentar DALL-E 3
                elif asset_type == AssetType.IMAGE.value and not (
                    image_input
                    and any(
                        err in error_msg
                        for err in [
                            "403",
                            "404",
                            "Forbidden",
                            "NameResolutionError",
                            "ConnectionError",
                            "HTTPSConnection",
                            "Connection refused",
                            "Failed to resolve",
                        ]
                    )
                ):
                    debug(
                        f"[ASSET] Image falhou no Replicate ({error_msg}), tentando fallback DALL-E 3..."
                    )
                    fallback_result = self._gen_img_fallback_dalle3(prompt, asset_name)

                    if fallback_result and fallback_result.get("success"):
                        filename = fallback_result.get("filename")
                        content = fallback_result.get("content")

                        # Obter client_id PRIMEIRO (antes de salvar no storage)
                        client_id = None
                        session = None
                        try:
                            session = self.db_manager.get_session()
                            user = (
                                session.query(User)
                                .filter(User.user_id == self.current_user_id)
                                .first()
                            )
                            client_id = user.client_id if user else None
                        except Exception as e:
                            debug(
                                f"[MEDIAAI] Erro ao obter client_id para fallback: {e}"
                            )
                        finally:
                            if session:
                                session.close()

                        # Salvar no Storage
                        try:
                            if self.current_user_id and self.current_chat_id:
                                StorageManager.save_file(
                                    client_id=client_id,
                                    user_id=self.current_user_id,
                                    chat_uuid=self.current_chat_id,
                                    folder_type="assets",
                                    filename=filename,
                                    content=content,
                                    is_binary=True,
                                )
                                debug(
                                    f"[MEDIAAI] Imagem do fallback DALL-E 3 salva no Storage: {filename}"
                                )

                                # Registrar em generated_content
                                session = None
                                try:
                                    content_uuid = uuid_lib.uuid4()
                                    storage_path = f"client_{client_id}/user_{self.current_user_id}/chat_{self.current_chat_id}/assets/{filename}"

                                    session = self.db_manager.get_session()

                                    # Salvar em assets table
                                    generated_content = GeneratedContent(
                                        asset_id=str(content_uuid),
                                        type="img",
                                        content_name=filename,
                                        user_id=self.current_user_id,
                                        client_id=client_id,
                                        chat_id=self.current_chat_id,
                                        storage_path=storage_path,
                                        storage_env="local",
                                        caption=None,
                                        version=1,
                                    )
                                    session.add(generated_content)
                                    session.commit()
                                    debug(
                                        f"[ASSET] Asset fallback DALL-E 3 registrado em generated_content: {content_uuid}"
                                    )

                                    #  Registrar evento de lifecycle
                                    try:
                                        from App.Features.Tracking.LifecycleTracker import (
                                            LifecycleTracker,
                                        )

                                        LifecycleTracker.track(
                                            user_id=self.current_user_id,
                                            event_type="asset_created",
                                            chat_id=self.current_chat_id,
                                            metadata={
                                                "asset_id": str(content_uuid),
                                                "asset_type": AssetType.IMAGE.value,
                                            },
                                        )
                                    except Exception as lifecycle_error:
                                        error(
                                            f"[LIFECYCLE] Erro ao registrar asset_created (fallback DALL-E): {lifecycle_error}"
                                        )

                                except Exception as e:
                                    debug(
                                        f"[ASSET] Erro ao registrar imagem fallback: {e}"
                                    )
                                    if session:
                                        session.rollback()
                                finally:
                                    if session:
                                        session.close()
                        except Exception as e:
                            debug(f"[ASSET] Erro ao salvar imagem fallback: {e}")

                        return json.dumps(
                            {
                                "success": True,
                                "tool": "asset",
                                "type": asset_type,
                                "model": "dall-e-3",
                                "name": asset_name,
                                "prompt": prompt,
                                "filename": filename,
                                "post_id": post_id,
                                "asset_id": str(content_uuid) if content_uuid else None,
                                "message": f"{asset_type.capitalize()} gerado e vinculado ao post {post_id}",
                                "status": "saved_to_db_and_storage",
                                "fallback_error_report": f"Gerao no Vertex falhou ({error_msg}), reenviado com DALL-E 3 com sucesso",
                            },
                            ensure_ascii=False,
                        )
                    else:
                        return json.dumps(
                            {
                                "success": False,
                                "error": f"Asset falhou no Replicate e no fallback DALL-E 3: {error_msg}",
                                "tool": "asset",
                                "replicate_error": error_msg,
                            },
                            ensure_ascii=False,
                        )

                # FALLBACK: Se asset video falhou no Replicate, tentar Google VEO 3.1
                elif asset_type == AssetType.VIDEO.value:
                    debug(
                        f"[ASSET] Video falhou no Replicate ({error_msg}), tentando fallback Google VEO 3.1..."
                    )
                    fallback_result = self._gen_film_fallback_google_veo(
                        prompt, asset_name
                    )

                    if fallback_result and fallback_result.get("success"):
                        filename = fallback_result.get("filename")
                        content = fallback_result.get("content")

                        # Obter client_id PRIMEIRO (antes de salvar no storage)
                        client_id = None
                        session = None
                        try:
                            session = self.db_manager.get_session()
                            user = (
                                session.query(User)
                                .filter(User.user_id == self.current_user_id)
                                .first()
                            )
                            client_id = user.client_id if user else None
                        except Exception as e:
                            debug(
                                f"[ASSET] Erro ao obter client_id para fallback vdeo: {e}"
                            )
                        finally:
                            if session:
                                session.close()

                        # Salvar no Storage
                        try:
                            if self.current_user_id and self.current_chat_id:
                                StorageManager.save_file(
                                    client_id=client_id,
                                    user_id=self.current_user_id,
                                    chat_uuid=self.current_chat_id,
                                    folder_type="assets",
                                    filename=filename,
                                    content=content,
                                    is_binary=True,
                                )
                                debug(
                                    f"[ASSET] Vdeo do fallback Google VEO 3.1 salvo no Storage: {filename}"
                                )

                                # Registrar no DB
                                session = None
                                try:
                                    content_uuid = uuid_lib.uuid4()
                                    storage_path = f"client_{client_id}/user_{self.current_user_id}/chat_{self.current_chat_id}/assets/{filename}"

                                    session = self.db_manager.get_session()

                                    # Salvar em assets table
                                    generated_content = GeneratedContent(
                                        asset_id=str(content_uuid),
                                        type="film",
                                        content_name=filename,
                                        user_id=self.current_user_id,
                                        client_id=client_id,
                                        chat_id=self.current_chat_id,
                                        storage_path=storage_path,
                                        storage_env="local",
                                        caption=None,
                                        version=1,
                                    )
                                    session.add(generated_content)
                                    session.commit()
                                    debug(
                                        f"[ASSET] Vdeo fallback Google VEO registrado em generated_content: {content_uuid}"
                                    )

                                    #  Registrar evento de lifecycle
                                    try:
                                        from App.Features.Tracking.LifecycleTracker import (
                                            LifecycleTracker,
                                        )

                                        LifecycleTracker.track(
                                            user_id=self.current_user_id,
                                            event_type="asset_created",
                                            chat_id=self.current_chat_id,
                                            metadata={
                                                "asset_id": str(content_uuid),
                                                "asset_type": AssetType.VIDEO.value,
                                            },
                                        )
                                    except Exception as lifecycle_error:
                                        error(
                                            f"[LIFECYCLE] Erro ao registrar asset_created (fallback VEO): {lifecycle_error}"
                                        )

                                except Exception as e:
                                    debug(
                                        f"[ASSET] Erro ao registrar vdeo fallback: {e}"
                                    )
                                    if session:
                                        session.rollback()
                                finally:
                                    if session:
                                        session.close()
                        except Exception as e:
                            debug(f"[ASSET] Erro ao salvar vdeo fallback: {e}")

                        return json.dumps(
                            {
                                "success": True,
                                "tool": "asset",
                                "type": asset_type,
                                "model": "google-veo-3.1 (fallback)",
                                "name": asset_name,
                                "prompt": prompt,
                                "filename": filename,
                                "message": "Asset gerado com sucesso (usando Google VEO 3.1 como fallback)",
                                "used_model": "google-veo-fallback",
                                "replicate_error": error_msg,
                                "status": "saved_to_db_and_storage",
                            },
                            ensure_ascii=False,
                        )
                    else:
                        return json.dumps(
                            {
                                "success": False,
                                "error": f"Asset falhou no Replicate e no fallback Google VEO 3.1: {error_msg}",
                                "tool": "asset",
                                "replicate_error": error_msg,
                            },
                            ensure_ascii=False,
                        )

                return json.dumps(
                    {"success": False, "error": error_msg, "tool": "asset"},
                    ensure_ascii=False,
                )

        except Exception as e:
            error(f"[ASSET] Erro ao gerar asset: {e}")
            return json.dumps({"success": False, "error": str(e), "tool": "asset"})

    def _execute_asset_variation_mode(
        self,
        doc_id: str,
        doc_data: dict,
        variation_data: dict,
        isolated_message_id: Optional[str] = None,
    ) -> dict:
        """
        Gera variações a partir de uma imagem de referência definida no documento copywriting.
        """
        from App.Features.Tools.Tools.Assets import generate_from_reference_image

        reference_image = variation_data.get("reference_image", "")
        what_to_validate = variation_data.get("what_to_validate", "")
        category = variation_data.get("category", "")
        count = int(variation_data.get("count", 1))
        # Obter aspect_ratio (prioridade: valor do documento copywriting)
        _raw_doc_ratio = doc_data.get("aspect_ratio")
        if isinstance(_raw_doc_ratio, list) and _raw_doc_ratio:
            _aspect_ratio = _raw_doc_ratio[0]
        elif _raw_doc_ratio:
            _aspect_ratio = str(_raw_doc_ratio)
        else:
            _aspect_ratio = "9:16"  # Fallback final

        # ... (rest of the method logic should remain but we only saw until line 2480)

        # Mapear categoria do quiz para tipo de testing_var
        _CAT_TO_TYPE = {
            "Estilos": "style",
            "Ambientes": "background",
            "Emoções": "emotion",
            "Paletas": "color",
            "Etnias/Gêneros": "ethnicity",
            "Ângulos": "camera_angle",
            "Criativo": "custom",
        }
        _var_type_from_cat = _CAT_TO_TYPE.get(category, "custom")

        # Construir variations_list a partir de variation_1, variation_2, ... em doc_data
        variations_list = []
        for _vi in range(1, count + 1):
            _vobj = doc_data.get(f"variation_{_vi}", {})
            if not isinstance(_vobj, dict) or not _vobj:
                continue
            if category == "Criativo":
                # Criativo usa prompt completo da variação como description
                _desc = (
                    _vobj.get("description")
                    or _vobj.get("prompt")
                    or _vobj.get("style", "")
                )
                if isinstance(_desc, dict):
                    _desc = " ".join(str(v) for v in _desc.values() if v)
            else:
                _desc = _vobj.get("description") or _vobj.get("style", "")
            variations_list.append(
                {
                    "label": _vobj.get("label", f"v{_vi}"),
                    "style": _vobj.get("style", ""),
                    "testing_var": {"type": _var_type_from_cat, "description": _desc},
                }
            )

        if not reference_image:
            return {
                "success": False,
                "error": "variation.reference_image é obrigatório para geração de variações. Informe attachment_id, template_id ou URL da imagem de referência.",
            }

        _is_attachment = reference_image.startswith("attach_")
        _is_url = reference_image.startswith("http://") or reference_image.startswith(
            "https://"
        )

        # Gate 1: attachment → vision obrigatório antes de gerar
        if _is_attachment and self.db_manager and self.current_chat_id:
            try:
                from App.Core.Crunch.TablesSQL.Models import IsolatedMessage as _IMv

                _sv = self.db_manager.get_session()
                try:
                    _vision_called = (
                        _sv.query(_IMv)
                        .filter(
                            _IMv.isolated_chat_id == self.current_chat_id,
                            _IMv.tool_called == "vision",
                            _IMv.tool_call_type == "output",
                            _IMv.content.ilike("%success%"),
                        )
                        .first()
                    )
                finally:
                    _sv.close()
                if not _vision_called:
                    return {
                        "success": False,
                        "error": "A imagem de referência é um attachment — execute vision() para analisar a imagem antes de gerar as variações.",
                        "correction_required": [
                            {
                                "step": 1,
                                "call": {
                                    "tool": "vision",
                                    "prompt": "Descreva em detalhes esta imagem: cores dominantes, estilo visual, composição, elementos, iluminação, emoção transmitida.",
                                    "image_input": reference_image,
                                },
                            }
                        ],
                    }
            except Exception as _ve:
                debug(f"[ASSET_VAR] Erro ao verificar gate vision: {_ve}")

        # Gate 2: URL → fetch + visual-analysis obrigatórios antes de gerar
        # DESATIVADO: skill gate já garante o fluxo de confirmação da imagem
        if False and _is_url and self.db_manager and self.current_chat_id:
            try:
                from App.Core.Crunch.TablesSQL.Models import IsolatedMessage as _IMws

                _sws = self.db_manager.get_session()
                try:
                    _has_fetch = (
                        _sws.query(_IMws)
                        .filter(
                            _IMws.isolated_chat_id == self.current_chat_id,
                            _IMws.tool_called.in_(["web-search", "web_search"]),
                            _IMws.tool_call_type == "output",
                            _IMws.content.ilike('%"type": "fetch"%'),
                        )
                        .first()
                    )
                    _has_visual = (
                        _sws.query(_IMws)
                        .filter(
                            _IMws.isolated_chat_id == self.current_chat_id,
                            _IMws.tool_called.in_(["web-search", "web_search"]),
                            _IMws.tool_call_type == "output",
                            _IMws.content.ilike('%"type": "visual-analysis"%'),
                        )
                        .first()
                    )
                finally:
                    _sws.close()
                _missing_ws = []
                if not _has_fetch:
                    _missing_ws.append("web-search(fetch='<url_imagem_ou_produto>')")
                if not _has_visual:
                    _missing_ws.append(
                        "web-search(visual-analysis='<url_imagem_ou_produto>')"
                    )
                if _missing_ws:
                    return {
                        "success": False,
                        "error": f"A imagem de referência é uma URL — execute antes de gerar: {' e '.join(_missing_ws)}.",
                        "correction_required": [
                            {"step": i + 1, "call": c}
                            for i, c in enumerate(
                                [
                                    {"tool": "web-search", "fetch": reference_image},
                                    {
                                        "tool": "web-search",
                                        "visual-analysis": reference_image,
                                    },
                                ]
                            )
                            if (c.get("fetch") and not _has_fetch)
                            or (c.get("visual-analysis") and not _has_visual)
                        ],
                    }
            except Exception as _wse:
                debug(f"[ASSET_VAR] Erro ao verificar gate web-search: {_wse}")

        # Gate 3: URL → quiz image_selection obrigatório para confirmar imagem base
        # DESATIVADO: skill gate já garante o fluxo de confirmação da imagem
        # (attachment não precisa: o usuário já curou a imagem ao fazer o upload)
        if False and _is_url and self.db_manager and self.current_chat_id:
            try:
                from App.Core.Crunch.TablesSQL.Models import IsolatedMessage as _IMqs

                _sqs = self.db_manager.get_session()
                try:
                    _img_quiz_input = (
                        _sqs.query(_IMqs)
                        .filter(
                            _IMqs.isolated_chat_id == self.current_chat_id,
                            _IMqs.tool_called == "quiz",
                            _IMqs.tool_call_type == "input",
                            _IMqs.content.ilike("%image_selection%"),
                        )
                        .order_by(_IMqs.id.desc())
                        .first()
                    )
                    _img_quiz_answered = False
                    if _img_quiz_input:
                        _img_quiz_output = (
                            _sqs.query(_IMqs)
                            .filter(
                                _IMqs.isolated_chat_id == self.current_chat_id,
                                _IMqs.tool_called == "quiz",
                                _IMqs.tool_call_type == "output",
                                _IMqs.id > _img_quiz_input.id,
                            )
                            .first()
                        )
                        _img_quiz_answered = _img_quiz_output is not None
                finally:
                    _sqs.close()
                if not _img_quiz_answered:
                    return {
                        "success": False,
                        "error": "Execute um quiz de confirmação da imagem base antes de gerar as variações.",
                        "hint": "Liste as URLs de imagens (.jpg/.png/.webp) encontradas no web-search como opções de um quiz com type='image_selection', para o usuário confirmar a imagem de referência.",
                        "correction_required": [
                            {
                                "step": 1,
                                "call": {
                                    "tool": "quiz",
                                    "items": [
                                        {
                                            "question": "Confirme a imagem de referência para as variações:",
                                            "type": "image_selection",
                                            "attachment": True,
                                            "options": [
                                                "<url1.jpg>",
                                                "<url2.png>",
                                                "...liste as URLs encontradas no web-search",
                                            ],
                                        }
                                    ],
                                },
                            }
                        ],
                    }
            except Exception as _qse:
                debug(
                    f"[ASSET_VAR] Erro ao verificar gate image_selection quiz: {_qse}"
                )

        if not reference_image:
            return {
                "success": False,
                "error": "reference_image é obrigatória. Use generate_temporary_public_url para obter uma URL pública e passe-a aqui.",
            }

        debug(
            f"[ASSET_VAR] Gerando {count} variações — what_to_validate='{what_to_validate}', reference_image={reference_image[:60]}"
        )

        result = generate_from_reference_image(
            reference_image=reference_image,
            variations=variations_list or None,
            what_to_validate=what_to_validate,
            num_variations=count,
            chat_id=self.current_chat_id,
            user_id=self.current_user_id,
            db_manager=self.db_manager,
            aspect_ratio=_aspect_ratio,
            isolated_message_id=isolated_message_id,
        )

        # Se todos os erros são de URL inacessível pelo Vertex, sugerir base64
        _url_error_phrases = (
            "Cannot fetch content from the provided URL",
            "ensure the URL is valid and accessible",
            "robots.txt",
        )
        _assets = result.get("generated_assets", [])
        if _assets and all(
            not a.get("asset_id")
            and any(p in (a.get("error") or "") for p in _url_error_phrases)
            for a in _assets
        ):
            return {
                "success": False,
                "error": (
                    "O Vertex AI não consegue acessar a URL da imagem de referência "
                    "(URL temporária/privada não é alcançável externamente)."
                ),
                "hint": (
                    "Use generate_temporary_public_url para obter a URL do arquivo, "
                    "depois leia o arquivo localmente com terminal(command='base64 <caminho_do_arquivo>') "
                    "e passe o resultado como data URI: "
                    "reference_image='data:image/jpeg;base64,<conteúdo_base64>'"
                ),
                "correction_required": [
                    {
                        "step": 1,
                        "call": {
                            "tool": "terminal",
                            "command": "base64 <caminho_local_da_imagem>",
                        },
                    },
                    {
                        "step": 2,
                        "call": {
                            "tool": "asset",
                            "reference_image": "data:image/jpeg;base64,<output_do_step_1>",
                        },
                    },
                ],
            }

        return result

    def _generate_all_copy_assets(self, document_id: str) -> Dict[str, Any]:
        """
        Dispara gerao automtica de assets de um documento copywriting.
        Delega para Assets.py que gerencia crditos e batch.

        Args:
            document_id: UUID do documento copywriting

        Returns:
            Dict com {success, generated_assets: [...], credits_consumed, credits_remaining, message}
        """
        try:
            from App.Features.Tools.Tools.Assets import generate_from_document

            result = generate_from_document(
                document_id=document_id,
                db_manager=self.db_manager,
                chat_id=self.current_chat_id,
                user_id=self.current_user_id,
                human_mode=False,
                isolated_message_id=self.current_isolated_message_id,
            )

            return result

        except ImportError:
            error(f"[GENERATE] Assets.generate_from_document nao disponivel")
            return {
                "success": False,
                "error": "Batch generation not available",
                "generated_assets": [],
                "credits_consumed": 0.0,
                "credits_remaining": 0.0,
            }
        except Exception as e:
            error(f"[GENERATE] Erro ao gerar assets: {e}")
            return {
                "success": False,
                "error": str(e),
                "generated_assets": [],
                "credits_consumed": 0.0,
                "credits_remaining": 0.0,
            }

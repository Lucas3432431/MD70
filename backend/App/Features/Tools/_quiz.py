"""
_quiz.py — Mixin extraído de Core.py.
Core.py importa este módulo e herda QuizMixin.
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
from App.Core.Settings.Settings import load_config, get_public_url
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


class QuizMixin:
    def _check_quiz_in_chat_history(self) -> bool:
        """
        Verifica se h execuo de quiz tool nas ltimas mensagens do chat.
        """
        if not self.db_manager or not self.current_chat_id:
            return False

        try:
            session = self.db_manager.get_session()
            try:
                blob = self._get_tool_messages_blob(session, "quiz")
                return bool(blob.strip())
            finally:
                session.close()
        except Exception as e:
            debug(f"[VALIDATE] Erro ao verificar quiz history: {e}")
            return False

    def _check_quiz_in_chat_history_10(self) -> bool:
        """
        Verifica se h execuo de quiz tool nas ltimas mensagens do chat.
        """
        if not self.db_manager or not self.current_chat_id:
            return False

        try:
            session = self.db_manager.get_session()
            try:
                blob = self._get_tool_messages_blob(session, "quiz")
                return bool(blob.strip())
            finally:
                session.close()
        except Exception as e:
            debug(f"[VALIDATE] Erro ao verificar quiz history 10: {e}")
            return False

    def _check_product_url_quiz_answered(self) -> bool:
        """Verifica se o quiz de URL do produto (ProductURL) j foi respondido no chat."""
        if not self.db_manager or not self.current_chat_id:
            return False
        try:
            session = self.db_manager.get_session()
            try:
                blob = self._get_tool_messages_blob(session, "quiz", call_type="output")
                return (
                    "producturl"
                    in blob.replace("-", "").replace("_", "").replace(" ", "")
                    or "http" in blob
                )
            finally:
                session.close()
        except Exception as e:
            debug(f"[VALIDATE] Erro ao verificar product URL quiz: {e}")
            return False

    def _check_strings_in_quiz(self, prohibited_strings: list) -> dict:
        """
        Verifica se as strings PROIBIDAS esto NO QUIZ MAIS RECENTE.
        Checa apenas o ltimo output de quiz  se o agente refez o quiz corretamente,
        quizzes anteriores com strings proibidas no devem bloquear.
        """
        if not self.db_manager or not self.current_chat_id:
            return {"found_in_quiz": False, "strings_found": []}

        try:
            session = self.db_manager.get_session()
            try:
                from App.Core.Crunch.TablesSQL.Models import (
                    IsolatedMessage,
                    IsolatedChat,
                )

                # Buscar apenas o INPUT do quiz mais recente (o que o agente perguntou)
                # No checamos o output (respostas do usurio)  o agente no controla isso
                def _get_latest_quiz_input(chat_id):
                    msg = (
                        session.query(IsolatedMessage)
                        .filter(
                            IsolatedMessage.isolated_chat_id == chat_id,
                            IsolatedMessage.tool_called == "quiz",
                            IsolatedMessage.tool_call_type == "input",
                        )
                        .order_by(IsolatedMessage.created_at.desc())
                        .first()
                    )
                    return msg

                msg = _get_latest_quiz_input(self.current_chat_id)
                if not msg:
                    isolated_chat = (
                        session.query(IsolatedChat)
                        .filter(IsolatedChat.chat_id == self.current_chat_id)
                        .first()
                    )
                    if isolated_chat:
                        msg = _get_latest_quiz_input(str(isolated_chat.id))

                if not msg or not msg.content:
                    return {"found_in_quiz": False, "strings_found": []}

                blob = msg.content.lower()

                def _matches(s: str, text: str) -> bool:
                    sl = s.lower()
                    if len(sl) <= 4:
                        return bool(re.search(r"\b" + re.escape(sl) + r"\b", text))
                    return sl in text

                strings_found = [s for s in prohibited_strings if _matches(s, blob)]
                return {
                    "found_in_quiz": bool(strings_found),
                    "strings_found": strings_found,
                }
            finally:
                session.close()
        except Exception as e:
            debug(f"[VALIDATE] Erro ao verificar strings no quiz: {e}")
            return {"found_in_quiz": False, "strings_found": []}

    def _check_required_topics_in_quiz(self, required_topics: list) -> dict:
        """
        Verifica se os tpicos OBRIGATRIOS esto presentes NO BLOB CONCATENADO de todos os quizzes.
        Cada tpico pode ter variaes em portugus (pt) e ingls (en).
        Basta encontrar UMA variao do tpico para consider-lo presente.

        Args:
            required_topics: Lista de dicionrios com formato:
                [{"topic": "color", "pt": ["cor", "cores"], "en": ["color"]}, ...]
        """
        import unicodedata

        def _normalize(s: str) -> str:
            return (
                unicodedata.normalize("NFKD", s)
                .encode("ascii", "ignore")
                .decode("ascii")
            )

        if not self.db_manager or not self.current_chat_id:
            missing = [t["topic"] for t in required_topics]
            return {"found_all": False, "missing_topics": missing, "found_topics": []}

        try:
            session = self.db_manager.get_session()
            try:
                blob = self._get_tool_messages_blob(session, "quiz", call_type="input")
                if not blob.strip():
                    missing = [t["topic"] for t in required_topics]
                    return {
                        "found_all": False,
                        "missing_topics": missing,
                        "found_topics": [],
                    }

                blob_normalized = _normalize(blob)

                found_topics = []
                missing_topics = []

                for topic_dict in required_topics:
                    topic_name = topic_dict["topic"]
                    all_variants = topic_dict.get("pt", []) + topic_dict.get("en", [])

                    if any(
                        _normalize(v.lower()) in blob_normalized for v in all_variants
                    ):
                        found_topics.append(topic_name)
                        debug(
                            f"[VALIDATE] Quiz topic '{topic_name}' encontrado no blob concatenado"
                        )
                    else:
                        missing_topics.append(topic_name)

                found_all = len(missing_topics) == 0
                debug(
                    f"[VALIDATE] Quiz check: found_all={found_all}, found={len(found_topics)}, missing={len(missing_topics)}"
                )

                return {
                    "found_all": found_all,
                    "missing_topics": missing_topics,
                    "found_topics": found_topics,
                }

            finally:
                session.close()
        except Exception as e:
            debug(f"[VALIDATE] Erro ao verificar tpicos obrigatrios no quiz: {e}")
            import traceback

            debug(f"[VALIDATE] Traceback: {traceback.format_exc()}")
            missing = [t["topic"] for t in required_topics]
            return {"found_all": False, "missing_topics": missing, "found_topics": []}

    def _get_quiz_user_answers_blob(self) -> str:
        """Returns concatenated lowercase blob of all quiz OUTPUT messages (user's answers)."""
        if not self.db_manager or not self.current_chat_id:
            return ""
        try:
            session = self.db_manager.get_session()
            try:
                return self._get_tool_messages_blob(session, "quiz", call_type="output")
            finally:
                session.close()
        except Exception:
            return ""

    def _get_last_quiz_answers(self, domain: str = "") -> list:
        """Returns final_answers list from the most recent quiz output message."""
        if not self.db_manager or not self.current_chat_id:
            return []
        try:
            from App.Core.Crunch.TablesSQL.Models import IsolatedMessage, IsolatedChat

            session = self.db_manager.get_session()
            try:

                def _query(chat_id):
                    return (
                        session.query(IsolatedMessage)
                        .filter(
                            IsolatedMessage.isolated_chat_id == chat_id,
                            IsolatedMessage.tool_called == "quiz",
                            IsolatedMessage.tool_call_type == "output",
                        )
                        .order_by(IsolatedMessage.created_at.desc())
                        .limit(self.LOOKUP_HISTORY_LIMIT)
                        .all()
                    )

                messages = _query(self.current_chat_id)
                if not messages:
                    isolated_chat = (
                        session.query(IsolatedChat)
                        .filter(IsolatedChat.chat_id == self.current_chat_id)
                        .first()
                    )
                    if isolated_chat:
                        messages = _query(str(isolated_chat.id))

                for msg in messages:
                    try:
                        data = json.loads(msg.content or "{}")
                        answers = data.get("final_answers", [])
                        if answers:
                            return answers
                    except (json.JSONDecodeError, AttributeError):
                        continue
            finally:
                session.close()
        except Exception as e:
            debug(f"[VALIDATE] Erro em _get_last_quiz_answers: {e}")
        return []

    def _parse_quiz_answers_by_type(self, quiz_output_content: str) -> dict:
        """
        Parses a quiz output JSON and returns {type: answer} mapping.
        Quiz outputs use "final_answers" with {question, answer}  no type field.
        Correlates by parsing the "raw" field (original quiz input with types).
        """
        try:
            _d = json.loads(quiz_output_content or "{}")
            _final_answers = _d.get("final_answers", [])
            _raw = _d.get("raw", "")
            if not _final_answers:
                return {}
            # Build questionanswer map
            _q_to_ans = {
                fa.get("question", ""): fa.get("answer", "") for fa in _final_answers
            }
            # Parse raw to get questiontype map
            _q_to_type = {}
            if _raw and "Args: " in _raw:
                try:
                    _args = json.loads(_raw.split("Args: ", 1)[1])
                    for qi in _args.get("quiz", []):
                        _q_to_type[qi.get("question", "")] = qi.get("type", "").lower()
                except Exception:
                    pass
            # Build typeanswer
            result = {}
            for q, ans in _q_to_ans.items():
                t = _q_to_type.get(q, "")
                if t:
                    result[t] = ans
            return result
        except Exception:
            return {}

    def _get_quiz_post_category(self) -> str:
        """Returns the user's answer to the post_category quiz question, or ''."""
        if not self.db_manager or not self.current_chat_id:
            return ""
        try:
            from App.Core.Crunch.TablesSQL.Models import IsolatedMessage as _IM

            _s = self.db_manager.get_session()
            try:
                rows = (
                    _s.query(_IM)
                    .filter(
                        _IM.isolated_chat_id == self.current_chat_id,
                        _IM.tool_called == "quiz",
                        _IM.tool_call_type == "output",
                    )
                    .order_by(_IM.id.desc())
                    .limit(20)
                    .all()
                )
                for row in rows:
                    answers = self._parse_quiz_answers_by_type(row.content or "{}")
                    if "post_category" in answers:
                        return answers["post_category"]
            finally:
                _s.close()
        except Exception:
            pass
        return ""

    def _get_quiz_selected_product_id(self) -> str:
        """Returns the document_id for the product selected in the product_selection quiz question."""
        if not self.db_manager or not self.current_chat_id:
            return ""
        try:
            from App.Core.Crunch.TablesSQL.Models import IsolatedMessage as _IM

            _s = self.db_manager.get_session()
            try:
                rows = (
                    _s.query(_IM)
                    .filter(
                        _IM.isolated_chat_id == self.current_chat_id,
                        _IM.tool_called == "quiz",
                        _IM.tool_call_type == "output",
                    )
                    .order_by(_IM.id.desc())
                    .limit(20)
                    .all()
                )
                for row in rows:
                    answers = self._parse_quiz_answers_by_type(row.content or "{}")
                    selected_title = answers.get("product_selection", "")
                    if not selected_title or selected_title.lower() in (
                        "no se aplica",
                        "nao se aplica",
                        ".",
                    ):
                        continue
                    _prod_docs = self._get_product_docs_list()
                    for pdoc in _prod_docs:
                        if pdoc["title"].lower() == selected_title.lower():
                            return pdoc["document_id"]
                    # Fallback: answer is already a document_id
                    if len(selected_title) == 36 and selected_title.count("-") == 4:
                        return selected_title
            finally:
                _s.close()
        except Exception:
            pass
        return ""

    def _check_copywriting_quiz_in_chat(self) -> bool:
        """
        Verifica se h quiz de copywriting no histrico do chat.
        O quiz deve conter perguntas sobre quantidade de assets e o que validar.
        """
        if not self.db_manager or not self.current_chat_id:
            return False
        try:
            session = self.db_manager.get_session()
            try:
                blob = self._get_tool_messages_blob(session, "quiz").lower()
                if not blob:
                    return False
                keywords = [
                    "asset",
                    "headline",
                    "ngulo",
                    "angulo",
                    "ângulo",
                    "estilo",
                    "quantos",
                    "how many",
                    "ia decide",
                    "formato",
                    "format",
                    "4:5",
                    "9:16",
                    "1:1",
                    "feed",
                    "story",
                    "reels",
                    "shorts",
                    "canal",
                    "channel",
                    "instagram",
                    "facebook",
                    "linkedin",
                    "youtube",
                    "tiktok",
                    "branding",
                    "topo de funil",
                    "fundo de funil",
                    "meio de funil",
                    # Variações / A/B testing
                    "variacao",
                    "variação",
                    "variation",
                    "testing_var",
                    "what_to_validate",
                    "referencia",
                    "referência",
                    "attachment",
                    "template",
                    "ugc",
                    "studio",
                    "lifestyle",
                    "ambiente",
                    "background",
                    "emocao",
                    "emoção",
                    "emotion",
                    "pose",
                    "etnia",
                    "ethnicity",
                    "genero",
                    "gênero",
                    "gender",
                    "iluminacao",
                    "iluminação",
                    "lighting",
                    "cor ",
                    "color",
                    "camera",
                    "câmera",
                ]
                return any(k in blob for k in keywords)
            finally:
                session.close()
        except Exception as e:
            debug(f"[VALIDATE] Erro ao verificar quiz copywriting: {e}")
            return False

    def _execute_quiz(self, args: Dict[str, Any]) -> str:
        """
        Executa tool 'quiz' para criar perguntas estruturadas com opes (BLOQUEANTE/ASSNCRONO).

        Suporta uma ou mltiplas perguntas via array 'quiz'.
        Retorna status "waiting" para interromper o looping da IA e aguardar o usurio.

        Args:
            args: Dict com:
                - quiz: List de Dicts com {question, options, type} (obrigatrio)

        Returns:
            JSON com status "waiting" e quiz_call_id, ou erro de validao
        """
        quiz_items = args.get("quiz", [])

        if not quiz_items or not isinstance(quiz_items, list):
            return json.dumps(
                {
                    "success": False,
                    "error": "'quiz' deve ser uma lista de perguntas estruturadas",
                    "tool": "quiz",
                    "hint": "Formato: quiz(quiz=[{question: '...', options: [...], type: '...'}])",
                },
                ensure_ascii=False,
            )

        #  GATE: bloquear quiz duplicado de URL  s se o quiz anterior j foi respondido (tem output)
        # Se o ltimo quiz input no tem output ainda (aguardando resposta), permite chamar de novo
        try:
            if self.db_manager and self.current_chat_id:
                _new_types = {
                    item.get("type", "").lower()
                    for item in quiz_items
                    if isinstance(item, dict)
                }
                if _new_types & {"url"} and self._check_product_url_quiz_answered():
                    # Verificar se o ltimo quiz input tem output correspondente
                    from App.Core.Crunch.TablesSQL.Models import IsolatedMessage as _IMq

                    _sq = self.db_manager.get_session()
                    try:
                        _last_quiz_input = (
                            _sq.query(_IMq)
                            .filter(
                                _IMq.isolated_chat_id == self.current_chat_id,
                                _IMq.tool_called == "quiz",
                                _IMq.tool_call_type == "input",
                            )
                            .order_by(_IMq.id.desc())
                            .first()
                        )
                        _last_quiz_output = (
                            _sq.query(_IMq)
                            .filter(
                                _IMq.isolated_chat_id == self.current_chat_id,
                                _IMq.tool_called == "quiz",
                                _IMq.tool_call_type == "output",
                                ~_IMq.content.ilike('%"success": false%'),
                            )
                            .order_by(_IMq.id.desc())
                            .first()
                        )
                        # Bloquear apenas se o ltimo input j tem output (foi respondido)
                        _has_unanswered = _last_quiz_input and (
                            _last_quiz_output is None
                            or _last_quiz_output.id < _last_quiz_input.id
                        )
                        # Verificar se um ciclo completo (document→asset) ocorreu após o último quiz
                        # Se sim, o agente está livre para iniciar um novo fluxo
                        _cycle_complete_after_quiz = False
                        if not _has_unanswered and _last_quiz_output:
                            _asset_after_quiz = (
                                _sq.query(_IMq)
                                .filter(
                                    _IMq.isolated_chat_id == self.current_chat_id,
                                    _IMq.tool_called == "asset",
                                    _IMq.tool_call_type == "output",
                                    _IMq.id > _last_quiz_output.id,
                                )
                                .first()
                            )
                            _cycle_complete_after_quiz = bool(_asset_after_quiz)
                    finally:
                        _sq.close()
                    if not _has_unanswered and not _cycle_complete_after_quiz:
                        return json.dumps(
                            {
                                "success": False,
                                "error": "O quiz de URL do produto j foi respondido. Use os dados do quiz anterior para continuar.",
                                "tool": "quiz",
                                "hint": "No repita o quiz de URL. Prossiga com a pesquisa usando a URL j fornecida pelo usurio.",
                            },
                            ensure_ascii=False,
                        )
        except Exception as _dq:
            debug(f"[QUIZ] Erro ao verificar quiz duplicado: {_dq}")

        #  GATE: quiz no setup de business_canvas ou brand_communication exige web-search antes
        # EXCETO: quiz de variação (attachment=true) OU quando SkillCopywriting já foi carregada
        # (nesse caso o user está no fluxo de copywriting/variação, não no setup)
        _is_variation_quiz = any(
            item.get("attachment") for item in quiz_items if isinstance(item, dict)
        )
        _copywriting_active = self._check_copywriting_lookup_in_chat()
        if not _is_variation_quiz and not _copywriting_active:
            #  GATE DESATIVADO: quiz no setup de business_canvas ou brand_communication exige web-search antes
            pass
            # try:
            #     canvas_done = self._user_has_business_canvas()
            #     brand_done = self._user_has_brand_communication()
            #     in_setup = not canvas_done or (canvas_done and not brand_done)
            #     if in_setup and self.db_manager and self.current_chat_id:
            #         session = self.db_manager.get_session()
            #         try:
            #             web_blob = self._get_tool_messages_blob(
            #                 session, TOOL_WEB_SEARCH
            #             )
            #             has_web_search = bool(web_blob and web_blob.strip())
            #         finally:
            #             session.close()
            #         if not has_web_search:
            #             phase = (
            #                 "business_canvas"
            #                 if not canvas_done
            #                 else "brand_communication"
            #             )
            #             return json.dumps(
            #                 {
            #                     "success": False,
            #                     "error": f"Faa ao menos uma pesquisa com web-search sobre o cliente antes de iniciar o quiz de {phase}.",
            #                     "tool": "quiz",
            #                     "hint": "Use web-search(fetch/query) para pesquisar o site, redes sociais ou concorrentes do cliente primeiro.",
            #                 },
            #                 ensure_ascii=False,
            #             )
            # except Exception as _qe:
            #     debug(f"[QUIZ] Erro ao verificar gate de web-search: {_qe}")

        #  GATE: bloquear qualquer quiz aps Etapa 2 respondida (channels ou asset_quantity respondidos)
        if self.db_manager and self.current_chat_id:
            try:
                from App.Core.Crunch.TablesSQL.Models import IsolatedMessage as _IMq2

                _q2s = self.db_manager.get_session()
                try:
                    _etapa2_done = (
                        _q2s.query(_IMq2)
                        .filter(
                            _IMq2.isolated_chat_id == self.current_chat_id,
                            _IMq2.tool_called == "quiz",
                            _IMq2.tool_call_type == "output",
                            _IMq2.content.ilike("%asset_quantity%"),
                        )
                        .first()
                    )
                    if _etapa2_done:
                        return json.dumps(
                            {
                                "success": False,
                                "error": "Quiz bloqueado: os dois quizzes j foram respondidos. Prossiga com task() e document(type='copywriting').",
                                "tool": "quiz",
                                "hint": "No adicione mais perguntas. Use as respostas j coletadas para montar o copywriting.",
                            },
                            ensure_ascii=False,
                        )
                finally:
                    _q2s.close()
            except Exception as _q2e:
                debug(f"[QUIZ] Erro ao verificar gate ps-Etapa 2: {_q2e}")

        #  GATE: quiz de Etapa 1 exige context(type='documents') para o agente conhecer os produtos
        _etapa1_quiz_types = {"post_category", "product_selection"}
        _is_etapa1_quiz = any(
            item.get("type", "").lower() in _etapa1_quiz_types for item in quiz_items
        )
        if _is_etapa1_quiz and self.db_manager and self.current_chat_id:
            try:
                from App.Core.Crunch.TablesSQL.Models import IsolatedMessage as _IMq1

                _q1s = self.db_manager.get_session()
                try:
                    _skill_copy_loaded = (
                        _q1s.query(_IMq1)
                        .filter(
                            _IMq1.isolated_chat_id == self.current_chat_id,
                            _IMq1.tool_called == "lookup",
                            _IMq1.tool_call_type == "output",
                            _IMq1.content.ilike("%SkillCopywriting.md%"),
                        )
                        .first()
                    )
                    if _skill_copy_loaded:
                        # 1. Verificar se Etapa 1 j foi respondida
                        _quiz_etapa1_answered = (
                            _q1s.query(_IMq1)
                            .filter(
                                _IMq1.isolated_chat_id == self.current_chat_id,
                                _IMq1.tool_called == "quiz",
                                _IMq1.tool_call_type == "output",
                                _IMq1.content.ilike("%post_category%"),
                                _IMq1.id > _skill_copy_loaded.id,
                            )
                            .first()
                        )
                        if _quiz_etapa1_answered:
                            return json.dumps(
                                {
                                    "success": False,
                                    "error": "Quiz Etapa 1 j foi respondido. Prossiga para a Etapa 2 ou leitura de documentos.",
                                    "tool": "quiz",
                                    "hint": "No repita perguntas de categoria ou produto. Use as respostas j fornecidas para seguir o fluxo.",
                                },
                                ensure_ascii=False,
                            )

                        # 2. Verificar se consultou context(type='documents') antes
                        _has_ctx_docs = (
                            _q1s.query(_IMq1)
                            .filter(
                                _IMq1.isolated_chat_id == self.current_chat_id,
                                _IMq1.tool_called == "context",
                                _IMq1.tool_call_type == "output",
                                _IMq1.content.ilike("%documents%"),
                                _IMq1.id > _skill_copy_loaded.id,
                            )
                            .first()
                        )
                        if not _has_ctx_docs:
                            return json.dumps(
                                {
                                    "success": False,
                                    "error": "Ao bloqueada: Execute primeiro context(type='documents') para listar os produtos disponveis.",
                                    "tool": "quiz",
                                    "hint": (
                                        "Voc no pode iniciar o quiz sem saber quais produtos o usurio possui.\n"
                                        "1. Execute context(type='documents') agora.\n"
                                        "2. Use os nomes dos produtos retornados para preencher as 'options' da pergunta de seleo de produto no Quiz Etapa 1."
                                    ),
                                    "correction_required": [
                                        {
                                            "step": 1,
                                            "call": {
                                                "tool": "context",
                                                "type": "documents",
                                            },
                                        }
                                    ],
                                },
                                ensure_ascii=False,
                            )
                finally:
                    _q1s.close()
            except Exception as _q1e:
                debug(f"[QUIZ] Erro ao verificar gate de context docs Etapa 1: {_q1e}")

        #  GATE: quiz de Etapa 2 exige context(type='document') de brand_communication aps Etapa 1
        _etapa2_quiz_types = {
            "post_type",
            "validation_focus",
            "asset_quantity",
            "channels",
        }
        _is_etapa2_quiz = any(
            item.get("type", "").lower() in _etapa2_quiz_types for item in quiz_items
        )
        if _is_etapa2_quiz and self.db_manager and self.current_chat_id:
            try:
                from App.Core.Crunch.TablesSQL.Models import IsolatedMessage as _IMqg

                _qgs = self.db_manager.get_session()
                try:
                    # Busca quiz output de Etapa 1 (post_category respondido)
                    _etapa1_answered = (
                        _qgs.query(_IMqg)
                        .filter(
                            _IMqg.isolated_chat_id == self.current_chat_id,
                            _IMqg.tool_called == "quiz",
                            _IMqg.tool_call_type == "output",
                            _IMqg.content.ilike("%post_category%"),
                        )
                        .first()
                    )
                    _ctx_brand_after_etapa1 = None
                    if _etapa1_answered:
                        _ctx_brand_after_etapa1 = (
                            _qgs.query(_IMqg)
                            .filter(
                                _IMqg.isolated_chat_id == self.current_chat_id,
                                _IMqg.tool_called == "context",
                                _IMqg.tool_call_type == "output",
                                _IMqg.content.ilike("%brand_communication%"),
                                _IMqg.id > _etapa1_answered.id,
                            )
                            .first()
                        )
                finally:
                    _qgs.close()
                if not _ctx_brand_after_etapa1:
                    return json.dumps(
                        {
                            "success": False,
                            "error": "Leia os documentos do cliente antes do quiz de Etapa 2.",
                            "tool": "quiz",
                            "hint": (
                                "Aps responder o quiz de Etapa 1, execute:\n"
                                "1. context(type='documents')  listar documentos\n"
                                "2. context(type='document', document_id='<brand_communication_id>')  ler brand_communication\n"
                                "3. Para Branding: ler business_canvas | Para Anncio/Funil: ler product"
                            ),
                        },
                        ensure_ascii=False,
                    )
            except Exception as _qge:
                debug(f"[QUIZ] Erro ao verificar gate de context docs Etapa 2: {_qge}")

        #  GATE: em fluxo de variação com URL, o único quiz permitido após web-search é a confirmação de imagem (image_selection)
        _IR_QUESTION = "Extrai algumas imagens do seu produto, qual imagem você prefere usar como referência?"
        if self.db_manager and self.current_chat_id:
            try:
                from App.Core.Crunch.TablesSQL.Models import IsolatedMessage as _IMir

                _sir = self.db_manager.get_session()
                try:
                    _in_variation = self._check_variation_quiz_answered_in_chat()
                    if _in_variation:
                        _ir_input = (
                            _sir.query(_IMir)
                            .filter(
                                _IMir.isolated_chat_id == self.current_chat_id,
                                _IMir.tool_called == "quiz",
                                _IMir.tool_call_type == "input",
                                _IMir.content.ilike("%image_selection%"),
                            )
                            .order_by(_IMir.id.desc())
                            .first()
                        )
                        _ir_answered = False
                        if _ir_input:
                            _ir_out = (
                                _sir.query(_IMir)
                                .filter(
                                    _IMir.isolated_chat_id == self.current_chat_id,
                                    _IMir.tool_called == "quiz",
                                    _IMir.tool_call_type == "output",
                                    _IMir.id > _ir_input.id,
                                    ~_IMir.content.ilike('%"success": false%'),
                                )
                                .first()
                            )
                            _ir_answered = _ir_out is not None
                        _has_fetch = (
                            _sir.query(_IMir)
                            .filter(
                                _IMir.isolated_chat_id == self.current_chat_id,
                                _IMir.tool_called.in_(["web-search", "web_search"]),
                                _IMir.tool_call_type == "output",
                                _IMir.content.ilike('%"type": "fetch"%'),
                            )
                            .first()
                        )
                        _has_visual = (
                            _sir.query(_IMir)
                            .filter(
                                _IMir.isolated_chat_id == self.current_chat_id,
                                _IMir.tool_called.in_(["web-search", "web_search"]),
                                _IMir.tool_call_type == "output",
                                _IMir.content.ilike('%"type": "visual-analysis"%'),
                            )
                            .first()
                        )
                        # Bloquear repetição: image_selection já respondido
                        if _ir_answered:
                            _q_types_new = {
                                item.get("type", "").lower()
                                for item in quiz_items
                                if isinstance(item, dict)
                            }
                            if "image_selection" in _q_types_new:
                                return json.dumps(
                                    {
                                        "success": False,
                                        "error": "O quiz de confirmação de imagem já foi respondido. Use a imagem selecionada e prossiga com document(type='copywriting').",
                                        "tool": "quiz",
                                        "hint": "Não repita o quiz de imagem. Use variation.reference_image com a URL já confirmada pelo usuário.",
                                    },
                                    ensure_ascii=False,
                                )

                        if _has_fetch and _has_visual and not _ir_answered:
                            _q_types = {
                                item.get("type", "").lower()
                                for item in quiz_items
                                if isinstance(item, dict)
                            }
                            _q_texts = [
                                item.get("question", "").strip()
                                for item in quiz_items
                                if isinstance(item, dict)
                            ]
                            _is_valid_ir = (
                                len(quiz_items) == 1 and "image_selection" in _q_types
                            )
                            if not _is_valid_ir:
                                return json.dumps(
                                    {
                                        "success": False,
                                        "error": "Neste ponto do fluxo de variação, o único quiz permitido é a confirmação da imagem de referência.",
                                        "tool": "quiz",
                                        "hint": f"Execute exatamente: quiz([{{question: '{_IR_QUESTION}', type: 'image_selection', options: ['<url1.jpg>', ...]}}])",
                                        "correction_required": [
                                            {
                                                "step": 1,
                                                "call": {
                                                    "tool": "quiz",
                                                    "quiz": [
                                                        {
                                                            "question": _IR_QUESTION,
                                                            "type": "image_selection",
                                                            "options": [
                                                                "<url1.jpg>",
                                                                "<url2.png>",
                                                                "...liste as URLs de imagem encontradas no web-search",
                                                            ],
                                                        }
                                                    ],
                                                },
                                            }
                                        ],
                                    },
                                    ensure_ascii=False,
                                )
                finally:
                    _sir.close()
            except Exception as _ire:
                debug(f"[QUIZ] Erro ao verificar gate image_selection: {_ire}")

        # GATE: Quiz de variação — validação completa (attachment + completude)
        _VAR_CATEGORY_OPTS = {
            "Estilos",
            "Ambientes",
            "Emoções",
            "Paletas",
            "Etnias/Gêneros",
            "Ângulos",
        }
        _is_variation_quiz = any(
            "varia" in item.get("question", "").lower()
            or bool(_VAR_CATEGORY_OPTS.intersection(set(item.get("options", []))))
            for item in quiz_items
        )
        _quiz_has_attachment = any(
            item.get("attachment") is True for item in quiz_items
        )
        _quiz_has_category = any(
            bool(_VAR_CATEGORY_OPTS.intersection(set(item.get("options", []))))
            for item in quiz_items
        )
        _quiz_has_count = any(
            any("A/B" in str(o) for o in item.get("options", []))
            for item in quiz_items
            if not item.get("attachment")
        )
        _quiz_has_style_field = any(
            item.get("type", "").lower() in ("text", "url", "open")
            and not item.get("attachment")
            for item in quiz_items
        ) or any(
            # Aceita múltipla escolha com opção única de skip (ex: "Deixar a critério do agente")
            item.get("type", "").lower()
            in ("multiple_choice", "múltipla escolha", "text", "url", "open")
            and not item.get("attachment")
            and not bool(_VAR_CATEGORY_OPTS.intersection(set(item.get("options", []))))
            and not any("A/B" in str(o) for o in item.get("options", []))
            and not any(
                any(
                    kw in str(o).lower()
                    for kw in {"9:16", "1:1", "4:5", "16:9", "feed", "story"}
                )
                for o in item.get("options", [])
            )
            and len(item.get("options", [])) <= 2
            and "critério" in " ".join(str(o) for o in item.get("options", []))
            for item in quiz_items
        )
        _FORMAT_KEYWORDS = {
            "9:16",
            "1:1",
            "4:5",
            "16:9",
            "feed",
            "story",
            "stories",
            "reels",
            "shorts",
        }
        _quiz_has_format = any(
            not item.get("attachment")
            and any(
                any(kw in str(o).lower() for kw in _FORMAT_KEYWORDS)
                for o in item.get("options", [])
            )
            for item in quiz_items
        )

        # Bloquear quiz parcial: tem attachment mas faltam perguntas de variação, e contexto é de variação
        # Cancel ativo desativa ambos os gates de variação para não forçar o agente a completar um fluxo cancelado
        _var_gate_cancelled = bool(
            self.db_manager
            and self.current_chat_id
            and self._check_flow_cancelled_in_chat(self.current_chat_id)
        )
        if (
            not _var_gate_cancelled
            and _quiz_has_attachment
            and not _is_variation_quiz
            and self.db_manager
            and self.current_chat_id
        ):
            try:
                from App.Core.Crunch.TablesSQL.Models import IsolatedMessage as _IMva

                _vas = self.db_manager.get_session()
                try:
                    _var_user_msg = (
                        _vas.query(_IMva)
                        .filter(
                            _IMva.isolated_chat_id == self.current_chat_id,
                            _IMva.role == "user",
                            _IMva.content.ilike("%varia%"),
                        )
                        .order_by(_IMva.id.desc())
                        .first()
                    )
                finally:
                    _vas.close()
                if _var_user_msg:
                    return json.dumps(
                        {
                            "success": False,
                            "error": (
                                "Quiz de variação incompleto: envie TODAS as 5 perguntas em uma única chamada quiz(). "
                                "Nunca divida o quiz de variação em múltiplas chamadas."
                            ),
                            "tool": "quiz",
                            "required_questions": [
                                "1. Imagem de referência [type: 'url', attachment: true] — PRIMEIRA",
                                "2. Categoria [type: 'multiple_choice', options: ['Estilos','Ambientes','Emoções','Paletas','Etnias/Gêneros','Ângulos']]",
                                "3. Quantidade [type: 'multiple_choice', options: com 'A/B' (2/3/5/10)]",
                                "4. Descrição de estilo [type: 'text' ou 'url', campo aberto]",
                                "5. Formato [type: 'multiple_choice', options: ex. ['1:1', '4:5', '9:16', '16:9']]",
                            ],
                        },
                        ensure_ascii=False,
                    )
            except Exception as _vae:
                debug(
                    f"[QUIZ] Erro ao verificar contexto de variação para quiz parcial: {_vae}"
                )

        if _is_variation_quiz and not _var_gate_cancelled:
            _has_attachment_item = _quiz_has_attachment
            _first_is_attachment = (
                quiz_items[0].get("attachment") is True if quiz_items else False
            )
            if not _has_attachment_item:
                return json.dumps(
                    {
                        "success": False,
                        "error": "Quiz de variação inválido: a pergunta de imagem de referência deve ter 'attachment: true'.",
                        "tool": "quiz",
                        "hint": (
                            "A pergunta de imagem de referência deve ser a PRIMEIRA e ter 'attachment: true'. "
                            "Exemplo: {question: 'Qual a imagem de referência?', type: 'url', options: [], attachment: true}"
                        ),
                    },
                    ensure_ascii=False,
                )
            if not _first_is_attachment:
                return json.dumps(
                    {
                        "success": False,
                        "error": "Quiz de variação inválido: a pergunta de imagem de referência (attachment: true) deve ser a PRIMEIRA pergunta do quiz.",
                        "tool": "quiz",
                        "hint": "Reordene o quiz para que a pergunta com 'attachment: true' seja o item 0 (primeiro).",
                    },
                    ensure_ascii=False,
                )
            # Completude: todas as 5 perguntas obrigatórias
            _missing_var = []
            if not _quiz_has_category:
                _missing_var.append(
                    "categoria [options: Estilos/Ambientes/Emoções/Paletas/Etnias/Gêneros/Ângulos]"
                )
            if not _quiz_has_count:
                _missing_var.append(
                    "quantidade [options com 'A/B': 2/3/5/10 variações]"
                )
            if not _quiz_has_style_field:
                _missing_var.append(
                    "descrição de estilo [type: 'text' ou 'url', campo aberto, sem attachment]"
                )
            if not _quiz_has_format:
                _missing_var.append(
                    "formato [type: 'multiple_choice', options: ex. ['1:1', '4:5', '9:16', '16:9']]"
                )
            if _missing_var:
                return json.dumps(
                    {
                        "success": False,
                        "error": f"Quiz de variação incompleto. Faltam: {'; '.join(_missing_var)}.",
                        "tool": "quiz",
                        "hint": (
                            "Envie TODAS as 5 perguntas em uma única chamada quiz(). "
                            "Veja o exemplo completo na seção 'Quiz de Variação' do SkillCopywriting.md."
                        ),
                    },
                    ensure_ascii=False,
                )

        # Validaes de cada item
        validation_errors = []
        for i, item in enumerate(quiz_items):
            q = item.get("question", "").strip()
            opts = item.get("options", [])
            t = item.get("type", "").strip()

            if not q:
                validation_errors.append(f"Item {i}: 'question'  obrigatrio")
            _open_types = {"text", "url", "open"}
            if t.lower() in _open_types:
                # Campo aberto: options deve ser lista vazia ou ausente.
                # Exceções permitidas:
                #   1. attachment=true → pode ter options como atalho (ex: ["Nenhum"])
                #   2. options são atalhos de texto puro (sem URLs) → sugestões de skip (ex: ["Deixar a critério do agente"])
                _has_attachment_flag = item.get("attachment") is True
                _is_skip_options = (
                    isinstance(opts, list)
                    and len(opts) > 0
                    and all(
                        isinstance(o, str) and len(o) < 80 and "://" not in o
                        for o in opts
                    )
                )
                if (
                    isinstance(opts, list)
                    and len(opts) > 0
                    and not _has_attachment_flag
                    and not _is_skip_options
                ):
                    validation_errors.append(
                        f"Item {i}: type='{t}'  campo aberto  no use 'options'"
                    )
            elif t.lower() == "channels":
                # Opes obrigatrias dependem do public_target do produto selecionado.
                # Para cada pblico, mostrar: bundle recomendado + canais adicionais exclusivos do outro pblico
                # (no o bundle inteiro  apenas os canais que NO esto no bundle recomendado)
                _prod_sel_id = self._get_quiz_selected_product_id()
                _prod_sel = (
                    self._get_product_doc_by_id(_prod_sel_id) if _prod_sel_id else {}
                )
                _pub_target = _prod_sel.get("public_target", "").lower()
                _req_channels = []
                if _pub_target in ("b2b", "smb", "b2g"):
                    # B2B: bundle B2B obrigatrio + Instagram como adicional (Google j est no bundle B2B)
                    _req_channels.append("linkedin, x e google")
                    _req_channels.append(
                        "instagram"
                    )  # adicional  no "instagram e google" pois google j est
                elif _pub_target == "b2c":
                    # B2C: bundle B2C obrigatrio + LinkedIn e X como adicionais (Google j est no bundle B2C)
                    _req_channels.append("instagram e google")
                    _req_channels.append("linkedin")  # adicional
                    _req_channels.append(
                        " x "
                    )  # adicional (espaos para evitar match parcial)
                else:
                    # Pblico desconhecido: ambos os bundles
                    _req_channels.append("instagram e google")
                    _req_channels.append("linkedin, x e google")
                _req_channels += ["facebook", "youtube", "tiktok", "pinterest"]
                opts_blob = (
                    " ".join(o.lower() for o in opts) if isinstance(opts, list) else ""
                )
                missing_ch = [ch for ch in _req_channels if ch not in opts_blob]
                if missing_ch:
                    validation_errors.append(
                        f"Item {i}: quiz de channels incompleto. Faltam: {missing_ch}. "
                        f"Para pblico '{_pub_target or 'no definido'}', inclua: {_req_channels}."
                    )
            elif t.lower() == "product_selection":
                # Opes devem ser EXATAMENTE os ttulos dos product docs + "No se aplica"
                _prod_docs = self._get_product_docs_list()
                if not _prod_docs:
                    validation_errors.append(
                        f"Item {i}: nenhum documento product encontrado. "
                        "Crie document(type='product') antes de iniciar o copywriting."
                    )
                elif not isinstance(opts, list) or len(opts) < 1:
                    validation_errors.append(
                        f"Item {i}: 'options' deve listar pelo menos 1 produto disponvel"
                    )
                else:
                    _valid_titles = {pd["title"].lower() for pd in _prod_docs}
                    _valid_titles.add("no se aplica")
                    _invalid_opts = [o for o in opts if o.lower() not in _valid_titles]
                    if _invalid_opts:
                        _real_titles = [pd["title"] for pd in _prod_docs]
                        validation_errors.append(
                            f"Item {i}: opes de product_selection invlidas: {_invalid_opts}. "
                            f"Use exatamente os ttulos dos documentos product: {_real_titles} "
                            f"+ 'No se aplica' para Branding."
                        )
            elif t.lower() == "post_type":
                # Valida opes de post_type conforme product_type do produto selecionado
                _prod_sel_id2 = self._get_quiz_selected_product_id()
                _prod_sel2 = (
                    self._get_product_doc_by_id(_prod_sel_id2) if _prod_sel_id2 else {}
                )
                _ptype2 = _prod_sel2.get("product_type", "").lower()
                _post_cat2 = self._get_quiz_post_category().lower()
                if _post_cat2 in ("branding",):
                    pass  # categoria branding j conhecida, sem validao extra de post_type
                elif _ptype2 == "product":
                    _allowed_pt = {
                        "anncio",
                        "anuncio",
                        "recuperao de carrinho",
                        "recuperacao de carrinho",
                    }
                    invalid_opts = [
                        o
                        for o in (opts or [])
                        if o.lower() not in _allowed_pt and "agente" not in o.lower()
                    ]
                    if invalid_opts:
                        validation_errors.append(
                            f"Item {i}: produto fsico/digital s suporta Anncio e Recuperao de Carrinho. "
                            f"Opes invlidas: {invalid_opts}"
                        )
                # service/desconhecido: aceitar todos os valores
                if not isinstance(opts, list) or len(opts) < 2:
                    validation_errors.append(
                        f"Item {i}: 'options' deve ter pelo menos 2 opes"
                    )
            elif t.lower() == "asset_quantity":
                # Opes fixas de quantidade  valores exatos obrigatrios
                _allowed_qty = {"1", "2", "5", "10"}
                _opts_normalized = [str(o).split(" ")[0].strip() for o in (opts or [])]
                _invalid_qty = [o for o in _opts_normalized if o not in _allowed_qty]
                if _invalid_qty or not isinstance(opts, list) or len(opts) < 2:
                    validation_errors.append(
                        f"Item {i}: opes de asset_quantity devem ser exatamente: "
                        "'1 (nica)', '2 (A/B validaes simples)', '5 (A/B intermedirio)', '10 (A/B explorao)'. "
                        f"Recebido: {opts}"
                    )
            elif t.lower() == "validation_focus":
                # Apenas 4 opes permitidas  sem "Outro" no quiz
                _allowed_focus = {
                    "criativo (imagem que melhor performa)",
                    "gatilhos (validao social, urgncia, escassez...)",
                    "comunicao (hook, corpo ou cta)",
                    "deixar o agente decidir",
                }
                _opts_lower = [o.lower() for o in (opts or [])]
                _invalid_focus = [o for o in _opts_lower if o not in _allowed_focus]
                if _invalid_focus:
                    validation_errors.append(
                        f"Item {i}: validation_focus s aceita estas opes: "
                        "'Criativo (Imagem que melhor performa)', "
                        "'Gatilhos (Validao social, urgncia, escassez...)', "
                        "'Comunicao (Hook, Corpo ou CTA)', "
                        "'Deixar o Agente decidir'. "
                        f"Opes invlidas: {_invalid_focus}"
                    )
                if not isinstance(opts, list) or len(opts) < 2:
                    validation_errors.append(
                        f"Item {i}: 'options' deve ter pelo menos 2 opes"
                    )
            elif t.lower() == "image_selection":
                # image_selection: mínimo 1 opção, todas devem ser URLs válidas
                if not isinstance(opts, list) or len(opts) < 1:
                    validation_errors.append(
                        f"Item {i}: 'options' deve ter pelo menos 1 URL de imagem"
                    )
                else:
                    _invalid_urls = [
                        o
                        for o in opts
                        if not isinstance(o, str)
                        or not (o.startswith("http://") or o.startswith("https://"))
                    ]
                    if _invalid_urls:
                        validation_errors.append(
                            f"Item {i}: todas as options de image_selection devem ser URLs válidas (http:// ou https://). Inválidas: {_invalid_urls}"
                        )
            else:
                if not isinstance(opts, list) or len(opts) < 2 or len(opts) > 10:
                    validation_errors.append(
                        f"Item {i}: 'options' deve ter entre 2 e 10 opes"
                    )
            if not t:
                validation_errors.append(f"Item {i}: 'type'  obrigatrio")

        if validation_errors:
            debug(f"[QUIZ] Validao falhou: {validation_errors}")
            return json.dumps(
                {
                    "success": False,
                    "error": "Validao de quiz falhou",
                    "tool": "quiz",
                    "errors": validation_errors,
                },
                ensure_ascii=False,
            )

        #  GATE: verificar strings proibidas no contedo do quiz antes de criar
        try:
            quiz_blob = json.dumps(quiz_items, ensure_ascii=False).lower()

            def _quiz_matches(s: str) -> bool:
                sl = s.lower()
                if len(sl) <= 4:
                    return bool(re.search(r"\b" + re.escape(sl) + r"\b", quiz_blob))
                return sl in quiz_blob

            canvas_done = self._user_has_business_canvas()
            brand_done = self._user_has_brand_communication()

            if not canvas_done:
                prohibited_found = [
                    s for s in BUSINESS_CANVAS_PROHIBITED_IN_QUIZ if _quiz_matches(s)
                ]
                if prohibited_found:
                    found_str = ", ".join(prohibited_found)
                    return json.dumps(
                        {
                            "success": False,
                            "error": f"Refaa o quiz sem conter: {found_str}. Esses dados devem vir do web-search, no do quiz.",
                            "tool": "quiz",
                        },
                        ensure_ascii=False,
                    )

            elif canvas_done and not brand_done:
                prohibited_found = [
                    s
                    for s in BRAND_COMMUNICATION_PROHIBITED_IN_QUIZ
                    if _quiz_matches(s)
                ]
                if prohibited_found:
                    found_str = ", ".join(prohibited_found)
                    return json.dumps(
                        {
                            "success": False,
                            "error": f"Refaa o quiz sem conter: {found_str}. O quiz de brand_communication deve focar apenas em COR e TOM.",
                            "tool": "quiz",
                        },
                        ensure_ascii=False,
                    )

                #  GATE: opes de questes de cor devem conter nomes/hex de cores reais
                _COLOR_KEYWORDS_TYPE = ["cor", "cores", "paleta", "color", "palette"]
                _COLOR_NAMES_PT_EN = [
                    "azul",
                    "vermelho",
                    "verde",
                    "amarelo",
                    "laranja",
                    "roxo",
                    "rosa",
                    "branco",
                    "preto",
                    "cinza",
                    "marrom",
                    "bege",
                    "dourado",
                    "prata",
                    "turquesa",
                    "violeta",
                    "coral",
                    "salmo",
                    "navy",
                    "teal",
                    "lils",
                    "blue",
                    "red",
                    "green",
                    "yellow",
                    "orange",
                    "purple",
                    "pink",
                    "white",
                    "black",
                    "gray",
                    "grey",
                    "brown",
                    "gold",
                    "silver",
                ]
                _HEX_RE = re.compile(r"#[0-9a-fA-F]{3,6}")
                for _i, _item in enumerate(quiz_items):
                    _item_type = _item.get("type", "").lower()
                    if not any(_kw in _item_type for _kw in _COLOR_KEYWORDS_TYPE):
                        continue
                    _opts = _item.get("options", [])
                    _opts_with_color = [
                        _o
                        for _o in _opts
                        if _HEX_RE.search(_o)
                        or any(_cn in _o.lower() for _cn in _COLOR_NAMES_PT_EN)
                    ]
                    if len(_opts_with_color) < 1:
                        return json.dumps(
                            {
                                "success": False,
                                "error": f"Quiz de cor rejeitado: a questo {_i} deve ter pelo menos uma opo contendo as cores (nomes ou #hex) que voc identificou como corretas para a marca.",
                                "tool": "quiz",
                                "hint": "Uma das opes deve ser a paleta que voc acredita ser correta, com os nomes ou hex das cores. Ex: 'Azul Escuro (#1E3A8A), Azul Claro (#60A5FA), Branco (#FFFFFF)  paleta identificada no logo'. As demais opes podem ser alternativas ou 'Outra combinao'.",
                                "example": "options: ['Azul Escuro (#1E3A8A), Azul Claro (#60A5FA), Branco (#FFFFFF)  paleta do logo', 'Prefiro outras cores', 'Deixar a IA decidir']",
                            },
                            ensure_ascii=False,
                        )
        except Exception as _pe:
            debug(f"[QUIZ] Erro ao verificar strings proibidas: {_pe}")

        try:
            debug(f"[QUIZ] Criando quiz com {len(quiz_items)} pergunta(s)")

            # Gerar UUID nico para essa requisio de quiz
            quiz_call_id = str(uuid_lib.uuid4())
            attachment = bool(args.get("attachment", False))

            is_user_browser_auth = bool(args.get("is_user_browser_auth", False))
            plan = args.get("plan", None)
            if not is_user_browser_auth:
                try:
                    _has_lookup = self._check_user_browsing_lookup_in_chat()
                    if _has_lookup and len(quiz_items) == 1:
                        _opts = quiz_items[0].get("options", [])
                        if list(_opts) == ["Sim", "Não"]:
                            is_user_browser_auth = True
                except Exception:
                    pass

            if is_user_browser_auth and not plan:
                return json.dumps(
                    {
                        "success": False,
                        "error": "quiz de autorização do browser requer o campo 'plan' com o planejamento das ações que serão executadas.",
                        "tool": "quiz",
                        "hint": "Inclua plan='1. Abrir X\\n2. Clicar em Y\\n3. Extrair Z' na chamada do quiz.",
                    },
                    ensure_ascii=False,
                )

            # Retorna status "waiting" para que o MessageProcessor interrompa o loop
            # O job permanece aberto aguardando a rota /quiz_answer ser chamada
            response_data = {
                "success": True,
                "status": "waiting",
                "tool": "quiz",
                "quiz_call_id": quiz_call_id,
                "quiz": quiz_items,
                "attachment": attachment,
                "is_user_browser_auth": is_user_browser_auth,
                "plan": plan,
                "message": f"Quiz criado com {len(quiz_items)} pergunta(s). Aguardando resposta do usurio...",
            }

            debug(f"[QUIZ] Requisio criada com ID: {quiz_call_id}")
            return json.dumps(response_data, ensure_ascii=False)

        except Exception as e:
            error(f"[QUIZ] Erro ao executar quiz: {e}")
            return json.dumps(
                {"success": False, "error": str(e), "tool": "quiz"}, ensure_ascii=False
            )

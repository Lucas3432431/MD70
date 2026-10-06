"""
_validators.py — Mixin extraído de Core.py.
Core.py importa este módulo e herda ValidatorsMixin.
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


class ValidatorsMixin:
    def _get_tool_messages_blob(
        self, session, tool_called: str, call_type: str = None
    ) -> str:
        """
        Returns a single lowercase string concatenating content of messages
        with the given tool_called within the last LOOKUP_HISTORY_LIMIT messages.

        Args:
            call_type: "input", "output" ou None (ambos). Validaes devem usar "input"
                       para checar apenas o que o agente enviou, no respostas do usurio.
        """
        from App.Core.Crunch.TablesSQL.Models import IsolatedMessage, IsolatedChat

        def _query(chat_id):
            q = session.query(IsolatedMessage).filter(
                IsolatedMessage.isolated_chat_id == chat_id,
                IsolatedMessage.tool_called == tool_called,
            )
            if call_type:
                q = q.filter(IsolatedMessage.tool_call_type == call_type)
            return (
                q.order_by(IsolatedMessage.created_at.desc())
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

        return " ".join((msg.content or "") for msg in messages).lower()

    def _check_prompt_engineering_in_chat(self) -> bool:
        """
        Verifica se h lookup(file="SkillPromptEngineering.md") nas ltimas mensagens do chat.
        """
        if not self.db_manager or not self.current_chat_id:
            return False

        try:
            session = self.db_manager.get_session()
            try:
                blob = self._get_tool_messages_blob(session, "lookup")
                if not blob.strip():
                    return False

                return "skillpromptengineering" in blob
            finally:
                session.close()
        except Exception as e:
            debug(f"[VALIDATE] Erro ao verificar isolated_messages history: {e}")
            return False

    def _check_flow_cancelled_in_chat(self, chat_id: str, since_id: int = 0) -> bool:
        """Verifica se existe uma mensagem de cancelamento [FLOW_CANCELLED] no chat desde o lookup."""
        if not self.db_manager:
            return False
        try:
            from App.Core.Crunch.TablesSQL.Models import IsolatedMessage

            session = self.db_manager.get_session()
            try:
                # Buscar a mensagem de cancelamento mais recente para este chat
                query = (
                    session.query(IsolatedMessage)
                    .filter(
                        IsolatedMessage.isolated_chat_id == chat_id,
                        IsolatedMessage.role == "system",
                        IsolatedMessage.content.ilike("%[FLOW_CANCELLED]%"),
                    )
                    .order_by(IsolatedMessage.id.desc())
                )

                last_cancel = query.first()
                if not last_cancel:
                    return False

                # Se since_id for fornecido, o cancelamento só é válido se for APÓS o lookup
                if since_id > 0:
                    return last_cancel.id > since_id

                return True
            finally:
                session.close()
        except Exception as e:
            debug(f"[VALIDATE] Erro ao verificar cancelamento: {e}")
            return False

    def _check_copywriting_lookup_in_chat(self) -> bool:
        """Verifica se foi feito lookup(file="SkillCopywriting.md") com sucesso no chat e não foi cancelado."""
        if not self.db_manager or not self.current_chat_id:
            return False
        try:
            from App.Core.Crunch.TablesSQL.Models import IsolatedMessage, IsolatedChat

            session = self.db_manager.get_session()
            try:

                def _q(chat_id):
                    return (
                        session.query(IsolatedMessage)
                        .filter(
                            IsolatedMessage.isolated_chat_id == chat_id,
                            IsolatedMessage.tool_called == "lookup",
                            IsolatedMessage.tool_call_type == "output",
                            IsolatedMessage.content.ilike(
                                '%"file": "SkillCopywriting.md"%'
                            ),
                            ~IsolatedMessage.content.ilike("%blocked_files%"),
                        )
                        .order_by(IsolatedMessage.id.desc())
                        .first()
                    )

                msg = _q(self.current_chat_id)
                if not msg:
                    ic = (
                        session.query(IsolatedChat)
                        .filter(IsolatedChat.chat_id == self.current_chat_id)
                        .first()
                    )
                    if ic:
                        msg = _q(ic.id)

                if msg:
                    # Verificar se houve um cancelamento APÓS este lookup
                    if self._check_flow_cancelled_in_chat(
                        msg.isolated_chat_id, since_id=msg.id
                    ):
                        return False
                    return True

                return False
            finally:
                session.close()
        except Exception as e:
            debug(f"[VALIDATE] Erro ao verificar copywriting lookup: {e}")
            return False

    def _check_variation_quiz_answered_in_chat(self) -> bool:
        """Retorna True se um quiz de variação (attachment=true) foi respondido neste chat."""
        if not self.db_manager or not self.current_chat_id:
            return False
        try:
            from App.Core.Crunch.TablesSQL.Models import IsolatedMessage, IsolatedChat

            session = self.db_manager.get_session()
            try:

                def _q(chat_id):
                    # Busca TODOS os inputs de variação (attachment:true), do mais recente ao mais antigo
                    _var_inputs = (
                        session.query(IsolatedMessage)
                        .filter(
                            IsolatedMessage.isolated_chat_id == chat_id,
                            IsolatedMessage.tool_called == "quiz",
                            IsolatedMessage.tool_call_type == "input",
                            IsolatedMessage.content.ilike('%"attachment": true%'),
                        )
                        .order_by(IsolatedMessage.id.desc())
                        .all()
                    )
                    if not _var_inputs:
                        _var_inputs = (
                            session.query(IsolatedMessage)
                            .filter(
                                IsolatedMessage.isolated_chat_id == chat_id,
                                IsolatedMessage.tool_called == "quiz",
                                IsolatedMessage.tool_call_type == "input",
                                IsolatedMessage.content.ilike('%"attachment":true%'),
                            )
                            .order_by(IsolatedMessage.id.desc())
                            .all()
                        )
                    if not _var_inputs:
                        return False
                    # Retorna True se QUALQUER input tem output válido após ele
                    for _var_input in _var_inputs:
                        _var_output = (
                            session.query(IsolatedMessage)
                            .filter(
                                IsolatedMessage.isolated_chat_id == chat_id,
                                IsolatedMessage.tool_called == "quiz",
                                IsolatedMessage.tool_call_type == "output",
                                IsolatedMessage.id > _var_input.id,
                                ~IsolatedMessage.content.ilike('%"success": false%'),
                            )
                            .first()
                        )
                        if _var_output is not None:
                            return True
                    return False

                result = _q(self.current_chat_id)
                if not result:
                    ic = (
                        session.query(IsolatedChat)
                        .filter(IsolatedChat.chat_id == self.current_chat_id)
                        .first()
                    )
                    if ic:
                        result = _q(str(ic.id))
                return result
            finally:
                session.close()
        except Exception as e:
            debug(f"[VALIDATE] Erro ao verificar variation quiz: {e}")
            return False

    def _check_caption_lookup_in_chat(self) -> bool:
        """
        Verifica se h lookup de SkillCaption.md no chat (file= ou files=[]).
        """
        if not self.db_manager or not self.current_chat_id:
            return False
        try:
            session = self.db_manager.get_session()
            try:
                blob = self._get_tool_messages_blob(session, "lookup")
                return "skillcaption" in blob
            finally:
                session.close()
        except Exception as e:
            debug(f"[VALIDATE] Erro ao verificar caption lookup: {e}")
            return False

    def _check_competitor_analysis_lookup_in_chat(self) -> bool:
        """Verifica se foi feito lookup(file="SkillCompetitorAnalysis.md") com sucesso no chat."""
        if not self.db_manager or not self.current_chat_id:
            return False
        try:
            from App.Core.Crunch.TablesSQL.Models import IsolatedMessage, IsolatedChat

            session = self.db_manager.get_session()
            try:

                def _q(chat_id):
                    return (
                        session.query(IsolatedMessage)
                        .filter(
                            IsolatedMessage.isolated_chat_id == chat_id,
                            IsolatedMessage.tool_called == "lookup",
                            IsolatedMessage.tool_call_type == "output",
                            IsolatedMessage.content.ilike(
                                '%"file": "SkillCompetitorAnalysis.md"%'
                            ),
                            ~IsolatedMessage.content.ilike("%blocked_files%"),
                        )
                        .first()
                    )

                msg = _q(self.current_chat_id)
                if not msg:
                    ic = (
                        session.query(IsolatedChat)
                        .filter(IsolatedChat.chat_id == self.current_chat_id)
                        .first()
                    )
                    if ic:
                        msg = _q(str(ic.id))
                if msg:
                    if self._check_flow_cancelled_in_chat(
                        msg.isolated_chat_id, since_id=msg.id
                    ):
                        return False
                    return True
                return False
            finally:
                session.close()
        except Exception as e:
            debug(f"[VALIDATE] Erro ao verificar competitor analysis lookup: {e}")
            return False

    def _check_user_browsing_lookup_in_chat(self) -> bool:
        """Verifica se foi feito lookup(file="SkillUserBrowsing.md") ou help(name="user_browser") com sucesso no chat."""
        if not self.db_manager or not self.current_chat_id:
            return False
        try:
            from App.Core.Crunch.TablesSQL.Models import IsolatedChat, IsolatedMessage
            from sqlalchemy import or_, and_

            session = self.db_manager.get_session()
            try:

                def _q(chat_id):
                    return (
                        session.query(IsolatedMessage)
                        .filter(
                            IsolatedMessage.isolated_chat_id == chat_id,
                            IsolatedMessage.tool_call_type == "output",
                            or_(
                                and_(
                                    IsolatedMessage.tool_called == "lookup",
                                    IsolatedMessage.content.ilike(
                                        '%"file": "SkillUserBrowsing.md"%'
                                    ),
                                    ~IsolatedMessage.content.ilike("%blocked_files%"),
                                ),
                                and_(
                                    IsolatedMessage.tool_called == "help",
                                    IsolatedMessage.content.ilike(
                                        '%"name": "user_browser"%'
                                    ),
                                    IsolatedMessage.content.ilike('%"success": true%'),
                                ),
                            ),
                        )
                        .order_by(IsolatedMessage.id.desc())
                        .first()
                    )

                msg = _q(self.current_chat_id)
                if not msg:
                    ic = (
                        session.query(IsolatedChat)
                        .filter(IsolatedChat.chat_id == self.current_chat_id)
                        .first()
                    )
                    if ic:
                        msg = _q(str(ic.id))
                if msg:
                    if self._check_flow_cancelled_in_chat(
                        msg.isolated_chat_id, since_id=msg.id
                    ):
                        return False
                    return True
                return False
            finally:
                session.close()
        except Exception as e:
            debug(f"[VALIDATE] Erro ao verificar user browsing lookup: {e}")
            return False

    def _check_terminal_lookup_in_chat(self) -> bool:
        """Verifica se foi feito lookup(file="SkillTerminal.md") com sucesso no chat."""
        if not self.db_manager or not self.current_chat_id:
            return False
        try:
            from App.Core.Crunch.TablesSQL.Models import IsolatedChat, IsolatedMessage

            session = self.db_manager.get_session()
            try:

                def _q(chat_id):
                    return (
                        session.query(IsolatedMessage)
                        .filter(
                            IsolatedMessage.isolated_chat_id == chat_id,
                            IsolatedMessage.tool_called == "lookup",
                            IsolatedMessage.tool_call_type == "output",
                            IsolatedMessage.content.ilike(
                                '%"file": "SkillTerminal.md"%'
                            ),
                            ~IsolatedMessage.content.ilike("%blocked_files%"),
                        )
                        .order_by(IsolatedMessage.id.desc())
                        .first()
                    )

                msg = _q(self.current_chat_id)
                if not msg:
                    ic = (
                        session.query(IsolatedChat)
                        .filter(IsolatedChat.chat_id == self.current_chat_id)
                        .first()
                    )
                    if ic:
                        msg = _q(str(ic.id))
                if msg:
                    if self._check_flow_cancelled_in_chat(
                        msg.isolated_chat_id, since_id=msg.id
                    ):
                        return False
                    return True
                return False
            finally:
                session.close()
        except Exception as e:
            debug(f"[VALIDATE] Erro ao verificar terminal lookup: {e}")
            return False

    def _check_html_lookup_in_chat(self) -> bool:
        """Verifica se foi feito lookup(file="SkillDashboard.md") com sucesso no chat."""
        if not self.db_manager or not self.current_chat_id:
            return False
        try:
            from App.Core.Crunch.TablesSQL.Models import IsolatedChat, IsolatedMessage

            session = self.db_manager.get_session()
            try:

                def _q(chat_id):
                    return (
                        session.query(IsolatedMessage)
                        .filter(
                            IsolatedMessage.isolated_chat_id == chat_id,
                            IsolatedMessage.tool_called == "lookup",
                            IsolatedMessage.tool_call_type == "output",
                            IsolatedMessage.content.ilike(
                                '%"file": "SkillDashboard.md"%'
                            ),
                            ~IsolatedMessage.content.ilike("%blocked_files%"),
                        )
                        .order_by(IsolatedMessage.id.desc())
                        .first()
                    )

                msg = _q(self.current_chat_id)
                if not msg:
                    ic = (
                        session.query(IsolatedChat)
                        .filter(IsolatedChat.chat_id == self.current_chat_id)
                        .first()
                    )
                    if ic:
                        msg = _q(str(ic.id))
                if msg:
                    if self._check_flow_cancelled_in_chat(
                        msg.isolated_chat_id, since_id=msg.id
                    ):
                        return False
                    return True
                return False
            finally:
                session.close()
        except Exception as e:
            debug(f"[VALIDATE] Erro ao verificar html lookup: {e}")
            return False

    def _check_browser_auth_quiz_sim(self) -> bool:
        """
        Retorna True se o quiz de autorização de browser foi respondido com "Sim" neste chat.
        Retorna False se não houve quiz ou se a resposta foi "Não".
        """
        if not self.db_manager or not self.current_chat_id:
            return False
        try:
            from App.Core.Crunch.TablesSQL.Models import IsolatedChat, IsolatedMessage

            session = self.db_manager.get_session()
            try:

                def _q(chat_id):
                    return (
                        session.query(IsolatedMessage)
                        .filter(
                            IsolatedMessage.isolated_chat_id == chat_id,
                            IsolatedMessage.tool_called == "quiz",
                            IsolatedMessage.tool_call_type == "output",
                            IsolatedMessage.content.ilike("%is_user_browser_auth%"),
                        )
                        .order_by(IsolatedMessage.id.desc())
                        .first()
                    )

                msg = _q(self.current_chat_id)
                if not msg:
                    ic = (
                        session.query(IsolatedChat)
                        .filter(IsolatedChat.chat_id == self.current_chat_id)
                        .first()
                    )
                    if ic:
                        msg = _q(str(ic.id))
                if not msg:
                    return False
                try:
                    # Formato atual: {"success": true, "raw": "Tool: quiz\nArgs: {...}", "final_answers": [...]}
                    outer = json.loads(msg.content or "{}")
                    final_answers = outer.get("final_answers", [])

                    # Extrai is_user_browser_auth do campo "raw" (Args da call original)
                    raw_str = outer.get("raw", "")
                    args_data = {}
                    if "Args: " in raw_str:
                        try:
                            args_data = json.loads(raw_str.split("Args: ", 1)[1])
                        except (json.JSONDecodeError, ValueError):
                            pass

                    if not args_data.get("is_user_browser_auth"):
                        return False

                    for answer_entry in final_answers:
                        ans = str(answer_entry.get("answer", "")).strip().lower()
                        if ans.startswith("sim"):
                            return True
                        if (
                            ans.startswith("não")
                            or ans.startswith("nao")
                            or ans.startswith("no")
                        ):
                            return False
                except (json.JSONDecodeError, AttributeError):
                    pass
                return False
            finally:
                session.close()
        except Exception as e:
            debug(f"[VALIDATE] Erro ao verificar browser auth quiz: {e}")
            return False

    def _check_lookup_in_chat(self) -> bool:
        """
        Verifica se qualquer lookup foi executado no chat atual.
        """
        if not self.db_manager or not self.current_chat_id:
            return False

        try:
            session = self.db_manager.get_session()
            try:
                blob = self._get_tool_messages_blob(session, "lookup")
                return bool(blob.strip())
            finally:
                session.close()
        except Exception as e:
            debug(f"[VALIDATE] Erro ao verificar lookup: {e}")
            return False

    def _check_brand_lookup_in_chat(self) -> bool:
        """
        Verifica se foi feito lookup(file="SkillBrandIdentity.md") com sucesso no chat.
        Consulta diretamente: tool_called == 'lookup' E content contm 'SkillBrandIdentity' (sem blocked_files).
        """
        if not self.db_manager or not self.current_chat_id:
            return False

        try:
            from App.Core.Crunch.TablesSQL.Models import IsolatedMessage, IsolatedChat

            session = self.db_manager.get_session()
            try:

                def _query(chat_id):
                    return (
                        session.query(IsolatedMessage)
                        .filter(
                            IsolatedMessage.isolated_chat_id == chat_id,
                            IsolatedMessage.tool_called == "lookup",
                            IsolatedMessage.tool_call_type == "output",
                            IsolatedMessage.content.ilike(
                                '%"file": "SkillBrandIdentity.md"%'
                            ),
                            ~IsolatedMessage.content.ilike("%blocked_files%"),
                        )
                        .first()
                    )

                msg = _query(self.current_chat_id)
                if not msg:
                    isolated_chat = (
                        session.query(IsolatedChat)
                        .filter(IsolatedChat.chat_id == self.current_chat_id)
                        .first()
                    )
                    if isolated_chat:
                        msg = _query(str(isolated_chat.id))
                if msg:
                    if self._check_flow_cancelled_in_chat(
                        msg.isolated_chat_id, since_id=msg.id
                    ):
                        return False
                    return True
                return False
            finally:
                session.close()
        except Exception as e:
            debug(f"[VALIDATE] Erro ao verificar brand lookup: {e}")
            return False

    def _check_canvas_lookup_in_chat(self) -> bool:
        """
        Verifica se foi feito lookup(file="SkillBusinessCanvas.md") com sucesso no chat.
        Consulta diretamente: tool_called == 'lookup' E content contm 'SkillBusinessCanvas' (sem blocked_files).
        """
        if not self.db_manager or not self.current_chat_id:
            return False

        try:
            from App.Core.Crunch.TablesSQL.Models import IsolatedMessage, IsolatedChat

            session = self.db_manager.get_session()
            try:

                def _query(chat_id):
                    return (
                        session.query(IsolatedMessage)
                        .filter(
                            IsolatedMessage.isolated_chat_id == chat_id,
                            IsolatedMessage.tool_called == "lookup",
                            IsolatedMessage.tool_call_type == "output",
                            IsolatedMessage.content.ilike(
                                '%"file": "SkillBusinessCanvas.md"%'
                            ),
                            ~IsolatedMessage.content.ilike("%blocked_files%"),
                        )
                        .first()
                    )

                msg = _query(self.current_chat_id)
                if not msg:
                    isolated_chat = (
                        session.query(IsolatedChat)
                        .filter(IsolatedChat.chat_id == self.current_chat_id)
                        .first()
                    )
                    if isolated_chat:
                        msg = _query(str(isolated_chat.id))
                if msg:
                    if self._check_flow_cancelled_in_chat(
                        msg.isolated_chat_id, since_id=msg.id
                    ):
                        return False
                    return True
                return False
            finally:
                session.close()
        except Exception as e:
            debug(f"[VALIDATE] Erro ao verificar canvas lookup: {e}")
            return False

    def _check_product_lookup_in_chat(self) -> bool:
        """Verifica se foi feito lookup(file="SkillProduct.md") com sucesso no chat."""
        if not self.db_manager or not self.current_chat_id:
            return False
        try:
            from App.Core.Crunch.TablesSQL.Models import IsolatedMessage, IsolatedChat

            session = self.db_manager.get_session()
            try:

                def _q(chat_id):
                    return (
                        session.query(IsolatedMessage)
                        .filter(
                            IsolatedMessage.isolated_chat_id == chat_id,
                            IsolatedMessage.tool_called == "lookup",
                            IsolatedMessage.tool_call_type == "output",
                            # Usar aspas duplas para evitar falso positivo: SkillCopywriting.md
                            # menciona 'SkillProduct.md' no seu texto, mas o campo JSON "file"
                            # só terá "SkillProduct.md" com aspas duplas quando for o arquivo real
                            IsolatedMessage.content.ilike(
                                '%"file": "SkillProduct.md"%'
                            ),
                            ~IsolatedMessage.content.ilike("%blocked_files%"),
                        )
                        .first()
                    )

                msg = _q(self.current_chat_id)
                if not msg:
                    ic = (
                        session.query(IsolatedChat)
                        .filter(IsolatedChat.chat_id == self.current_chat_id)
                        .first()
                    )
                    if ic:
                        msg = _q(str(ic.id))
                if msg:
                    if self._check_flow_cancelled_in_chat(
                        msg.isolated_chat_id, since_id=msg.id
                    ):
                        return False
                    return True
                return False
            finally:
                session.close()
        except Exception as e:
            debug(f"[VALIDATE] Erro ao verificar product lookup: {e}")
            return False

    def _check_social_media_lookup_in_chat(self) -> bool:
        """Verifica se foi feito lookup(file="SkillSocialMedia.md") com sucesso no chat."""
        if not self.db_manager or not self.current_chat_id:
            return False
        try:
            from App.Core.Crunch.TablesSQL.Models import IsolatedMessage, IsolatedChat

            session = self.db_manager.get_session()
            try:

                def _q(chat_id):
                    return (
                        session.query(IsolatedMessage)
                        .filter(
                            IsolatedMessage.isolated_chat_id == chat_id,
                            IsolatedMessage.tool_called == "lookup",
                            IsolatedMessage.tool_call_type == "output",
                            IsolatedMessage.content.ilike(
                                '%"file": "SkillSocialMedia.md"%'
                            ),
                            ~IsolatedMessage.content.ilike("%blocked_files%"),
                        )
                        .order_by(IsolatedMessage.id.desc())
                        .first()
                    )

                msg = _q(self.current_chat_id)
                if not msg:
                    ic = (
                        session.query(IsolatedChat)
                        .filter(IsolatedChat.chat_id == self.current_chat_id)
                        .first()
                    )
                    if ic:
                        msg = _q(str(ic.id))
                if msg:
                    if self._check_flow_cancelled_in_chat(
                        msg.isolated_chat_id, since_id=msg.id
                    ):
                        return False
                    return True
                return False
            finally:
                session.close()
        except Exception as e:
            debug(f"[VALIDATE] Erro ao verificar social media lookup: {e}")
            return False

    def _check_catalog_lookup_in_chat(self) -> bool:
        """Verifica se foi feito lookup(file="SkillCatalog.md") com sucesso no chat."""
        if not self.db_manager or not self.current_chat_id:
            return False
        try:
            from App.Core.Crunch.TablesSQL.Models import IsolatedMessage, IsolatedChat

            session = self.db_manager.get_session()
            try:

                def _q(chat_id):
                    return (
                        session.query(IsolatedMessage)
                        .filter(
                            IsolatedMessage.isolated_chat_id == chat_id,
                            IsolatedMessage.tool_called == "lookup",
                            IsolatedMessage.tool_call_type == "output",
                            IsolatedMessage.content.ilike(
                                '%"file": "SkillCatalog.md"%'
                            ),
                            ~IsolatedMessage.content.ilike("%blocked_files%"),
                        )
                        .order_by(IsolatedMessage.id.desc())
                        .first()
                    )

                msg = _q(self.current_chat_id)
                if not msg:
                    ic = (
                        session.query(IsolatedChat)
                        .filter(IsolatedChat.chat_id == self.current_chat_id)
                        .first()
                    )
                    if ic:
                        msg = _q(str(ic.id))
                if msg:
                    if self._check_flow_cancelled_in_chat(
                        msg.isolated_chat_id, since_id=msg.id
                    ):
                        return False
                    return True
                return False
            finally:
                session.close()
        except Exception as e:
            debug(f"[VALIDATE] Erro ao verificar catalog lookup: {e}")
            return False

    def _check_self_knowledge_lookup_in_chat(self) -> bool:
        """Verifica se foi feito lookup(file="SkillSelfKnowledge.md") com sucesso no chat."""
        if not self.db_manager or not self.current_chat_id:
            return False
        try:
            from App.Core.Crunch.TablesSQL.Models import IsolatedMessage, IsolatedChat

            session = self.db_manager.get_session()
            try:

                def _q(chat_id):
                    return (
                        session.query(IsolatedMessage)
                        .filter(
                            IsolatedMessage.isolated_chat_id == chat_id,
                            IsolatedMessage.tool_called == "lookup",
                            IsolatedMessage.tool_call_type == "output",
                            IsolatedMessage.content.ilike(
                                '%"file": "SkillSelfKnowledge.md"%'
                            ),
                            ~IsolatedMessage.content.ilike("%blocked_files%"),
                        )
                        .order_by(IsolatedMessage.id.desc())
                        .first()
                    )

                msg = _q(self.current_chat_id)
                if not msg:
                    ic = (
                        session.query(IsolatedChat)
                        .filter(IsolatedChat.chat_id == self.current_chat_id)
                        .first()
                    )
                    if ic:
                        msg = _q(str(ic.id))
                if msg:
                    if self._check_flow_cancelled_in_chat(
                        msg.isolated_chat_id, since_id=msg.id
                    ):
                        return False
                    return True
                return False
            finally:
                session.close()
        except Exception as e:
            debug(f"[VALIDATE] Erro ao verificar self knowledge lookup: {e}")
            return False

    def _check_tool_help_in_chat(self, tool_name: str) -> bool:
        """Verifica se foi chamado help(name="{tool_name}") com sucesso no chat."""
        if not self.db_manager or not self.current_chat_id:
            return False
        try:
            from App.Core.Crunch.TablesSQL.Models import IsolatedChat, IsolatedMessage

            session = self.db_manager.get_session()
            try:

                def _q(chat_id):
                    return (
                        session.query(IsolatedMessage)
                        .filter(
                            IsolatedMessage.isolated_chat_id == chat_id,
                            IsolatedMessage.tool_called == "help",
                            IsolatedMessage.tool_call_type == "output",
                            IsolatedMessage.content.ilike(f'%"name": "{tool_name}"%'),
                            IsolatedMessage.content.ilike('%"success": true%'),
                        )
                        .order_by(IsolatedMessage.id.desc())
                        .first()
                    )

                msg = _q(self.current_chat_id)
                if not msg:
                    ic = (
                        session.query(IsolatedChat)
                        .filter(IsolatedChat.chat_id == self.current_chat_id)
                        .first()
                    )
                    if ic:
                        msg = _q(str(ic.id))
                if msg:
                    if self._check_flow_cancelled_in_chat(
                        msg.isolated_chat_id, since_id=msg.id
                    ):
                        return False
                    return True
                return False
            finally:
                session.close()
        except Exception as e:
            debug(f"[VALIDATE] Erro ao verificar tool help para '{tool_name}': {e}")
            return False

    def _user_has_business_canvas(self) -> bool:
        """True se o user atual tem pelo menos um documento business_canvas ou o fluxo foi cancelado."""
        if not self.db_manager or not self.current_user_id:
            return True
        if self.current_chat_id and self._check_flow_cancelled_in_chat(
            self.current_chat_id
        ):
            return True
        _, doc_status = self._check_required_documents_exist()
        return doc_status.get("business_canvas", False)

    def _user_has_brand_communication(self) -> bool:
        """True se o user atual tem pelo menos um documento brand_communication ou o fluxo foi cancelado."""
        if not self.db_manager or not self.current_user_id:
            return True
        if self.current_chat_id and self._check_flow_cancelled_in_chat(
            self.current_chat_id
        ):
            return True
        _, doc_status = self._check_required_documents_exist()
        return doc_status.get("brand_communication", False)

    def _user_has_product(self) -> bool:
        """True se o user atual tem pelo menos um documento product ou o fluxo foi cancelado."""
        if not self.db_manager or not self.current_user_id:
            return True
        if self.current_chat_id and self._check_flow_cancelled_in_chat(
            self.current_chat_id
        ):
            return True
        _, doc_status = self._check_required_documents_exist(
            ["business_canvas", "brand_communication", "product"]
        )
        return doc_status.get("product", False)

    def _get_product_docs_list(self) -> list:
        """Returns [{document_id, title, public_target, product_type}] for current user's product docs."""
        if not self.db_manager or not self.current_user_id:
            return []
        try:
            from App.Core.Crunch.TablesSQL.Models import Document as _Doc

            _s = self.db_manager.get_session()
            try:
                rows = (
                    _s.query(_Doc)
                    .filter(
                        _Doc.user_id == self.current_user_id,
                        _Doc.tool_type == "product",
                    )
                    .order_by(_Doc.id.desc())
                    .all()
                )
                result = []
                for r in rows:
                    try:
                        _c = (
                            json.loads(r.content)
                            if isinstance(r.content, str)
                            else (r.content or {})
                        )
                    except Exception:
                        _c = {}
                    result.append(
                        {
                            "document_id": r.document_id,
                            "title": r.title or _c.get("title", r.document_id[:8]),
                            "public_target": _c.get("public_target", ""),
                            "product_type": _c.get("product_type", ""),
                        }
                    )
                return result
            finally:
                _s.close()
        except Exception:
            return []

    def _get_product_doc_by_id(self, document_id: str) -> dict:
        """Returns {document_id, title, public_target, product_type} for a specific product doc."""
        if not self.db_manager or not document_id:
            return {}
        try:
            from App.Core.Crunch.TablesSQL.Models import Document as _Doc

            _s = self.db_manager.get_session()
            try:
                r = (
                    _s.query(_Doc)
                    .filter(
                        _Doc.document_id == document_id,
                        _Doc.user_id == self.current_user_id,
                        _Doc.tool_type == "product",
                    )
                    .first()
                )
                if not r:
                    return {}
                try:
                    _c = (
                        json.loads(r.content)
                        if isinstance(r.content, str)
                        else (r.content or {})
                    )
                except Exception:
                    _c = {}
                return {
                    "document_id": r.document_id,
                    "title": r.title or _c.get("title", document_id[:8]),
                    "public_target": _c.get("public_target", ""),
                    "product_type": _c.get("product_type", ""),
                }
            finally:
                _s.close()
        except Exception:
            return {}

    def _get_pending_copywriting_document_from_db(self) -> str | None:
        """
        Retorna o document_id do último copywriting salvo com sucesso que ainda não teve asset gerado.
        Consulta o DB diretamente — não depende de _pending_document_id em memória.
        Retorna None se não há documento pendente.
        """
        if not self.db_manager or not self.current_chat_id:
            return None
        try:
            import json as _json
            from App.Core.Crunch.TablesSQL.Models import (
                IsolatedMessage as _IM,
                IsolatedChat as _IC,
            )

            session = self.db_manager.get_session()
            try:

                def _check(chat_id: str) -> str | None:
                    # Último document copywriting com sucesso
                    _last_doc = (
                        session.query(_IM)
                        .filter(
                            _IM.isolated_chat_id == chat_id,
                            _IM.tool_called == "document",
                            _IM.tool_call_type == "output",
                            _IM.content.ilike('%"type": "copywriting"%'),
                            _IM.content.ilike('%"success": true%'),
                        )
                        .order_by(_IM.id.desc())
                        .first()
                    )
                    if not _last_doc:
                        return None
                    # Verificar se já houve asset gerado após esse documento
                    _asset_after = (
                        session.query(_IM)
                        .filter(
                            _IM.isolated_chat_id == chat_id,
                            _IM.tool_called == "asset",
                            _IM.tool_call_type == "output",
                            _IM.id > _last_doc.id,
                        )
                        .first()
                    )
                    if _asset_after:
                        return None
                    # Extrair document_id do conteúdo
                    try:
                        _content = (
                            _json.loads(_last_doc.content)
                            if isinstance(_last_doc.content, str)
                            else (_last_doc.content or {})
                        )
                        return _content.get("id") or _content.get("document_id")
                    except Exception:
                        return None

                result = _check(self.current_chat_id)
                if result is None:
                    ic = (
                        session.query(_IC)
                        .filter(_IC.chat_id == self.current_chat_id)
                        .first()
                    )
                    if ic:
                        result = _check(str(ic.id))
                return result
            finally:
                session.close()
        except Exception as e:
            from App.Core.Logs import debug

            debug(f"[VALIDATE] Erro ao verificar pending copywriting doc: {e}")
            return None

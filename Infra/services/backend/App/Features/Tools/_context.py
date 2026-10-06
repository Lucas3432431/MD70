"""
_context.py — Mixin extraído de Core.py.
Core.py importa este módulo e herda ContextMixin.
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


class ContextMixin:
    def _get_client_id_from_user(self, user_id: Any) -> Optional[str]:
        """Busca o client_id associado a um user_id via DatabaseManager."""
        if not user_id or not self.db_manager:
            return None

        try:
            return self.db_manager.execute_transaction(
                lambda session: self.db_manager.get_client_id_by_user_id(
                    session, user_id
                )
            )
        except Exception as e:
            debug(f"[_get_client_id_from_user] Erro via db_manager: {e}")
            return None

    @staticmethod
    def _get_last_visual_analysis(self) -> dict | None:
        """Returns the parsed JSON of the most recent web-search visual-analysis output, or None."""
        if not self.db_manager or not self.current_chat_id:
            return None
        try:
            from App.Core.Crunch.TablesSQL.Models import IsolatedMessage, IsolatedChat

            session = self.db_manager.get_session()
            try:

                def _query(chat_id):
                    return (
                        session.query(IsolatedMessage)
                        .filter(
                            IsolatedMessage.isolated_chat_id == chat_id,
                            IsolatedMessage.tool_called == TOOL_WEB_SEARCH,
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
                        if data.get("type") == "visual-analysis" and data.get(
                            "design_analysis"
                        ):
                            return data
                    except (json.JSONDecodeError, AttributeError):
                        continue
            finally:
                session.close()
        except Exception as e:
            debug(f"[VALIDATE] Erro em _get_last_visual_analysis: {e}")
        return None

    def _check_context_calendar_in_chat_history(self) -> bool:
        """
        Verifica se h execuo de context(type="calendar") nas ltimas mensagens do chat.
        Obrigatrio para bloquear schedule() at que seja chamado.

        Returns:
            True se encontrou context(type="calendar"), False caso contrrio
        """
        if not self.db_manager or not self.current_chat_id:
            return False

        try:
            session = self.db_manager.get_session()
            try:
                from App.Core.Crunch.TablesSQL.Models import IsolatedMessage

                # Buscar ltimas mensagens
                messages = (
                    session.query(IsolatedMessage)
                    .filter(IsolatedMessage.isolated_chat_id == self.current_chat_id)
                    .order_by(IsolatedMessage.created_at.desc())
                    .limit(self.LOOKUP_HISTORY_LIMIT)
                    .all()
                )

                search_terms = [
                    "type: calendar",
                    '"type": "calendar"',
                    'context(type="calendar")',
                    "context(type='calendar')",
                    "execute context(",
                    '"tool_called": "context"',
                ]

                for msg in messages:
                    content = (msg.content or "").lower()
                    tool_called = (msg.tool_called or "").lower()

                    # 1. Verificar pelo campo estruturado tool_called = context
                    if tool_called == "context":
                        # Verificar se menciona "calendar" no contedo
                        if "calendar" in content:
                            return True

                    # 2. Verificar pelo contedo da mensagem
                    for term in search_terms:
                        if term.lower() in content:
                            return True

                return False

            finally:
                session.close()
        except Exception as e:
            debug(f"[VALIDATE] Erro ao verificar context calendar history: {e}")
            return False

    def _execute_context(self, args: Dict[str, Any]) -> str:
        """
        Executa tool 'context' para obter instrues de steps ou help.
        Suporta 2 modos:
        - help=true: Retorna documentao de todas as ferramentas e etapas disponveis
        - step="1" ou step="PESQUISA_DO_ANUNCIANTE": Retorna instrues especficas

        Args:
            args: Dict com:
                - help: Boolean True ou string "true" para obter ajuda geral
                - step: Identificador do step (nmero, range ou nome)

        Returns:
            JSON com instrues ou error
        """
        debug(f"[_EXECUTE_CONTEXT] INICIANDO - args: {args}")
        # Verificar se est pedindo help (aceita bool True ou string "true")
        help_raw = args.get("help", False)
        help_mode = help_raw is True or (
            isinstance(help_raw, str) and help_raw.lower() == "true"
        )
        debug(
            f"[_EXECUTE_CONTEXT] help_raw={help_raw} (type={type(help_raw).__name__}), help_mode={help_mode}"
        )

        # Novo: type parameter para obter contexto especfico de uma entidade
        context_type = args.get("type", "").strip().lower() if not help_mode else ""
        step_query = (
            args.get("step", "").strip() if not help_mode and not context_type else ""
        )
        rag_context = (
            args.get("context", "").strip()
            if not help_mode and context_type == "rag"
            else ""
        )

        if not help_mode and not step_query and not context_type:
            return json.dumps(
                {
                    "success": False,
                    "error": "Informe step='nmero/nome' ou help=true ou type='steps'|'rag'|'instructions'|'document'|'task'|'media'|'calendar'",
                    "tool": "context",
                },
                ensure_ascii=False,
            )

        # NOVO: Se type foi fornecido, retornar contexto especfico dessa entidade
        if context_type:
            if context_type == "steps":
                # Retornar todas as etapas e sua ordem lgica, ou uma etapa especfica se step foi fornecido
                return self._execute_context_steps(step_query)
            elif context_type == "rag":
                # Retornar orientaes estratgicas do RAG.json, ou orientao especfica se context foi fornecido
                return self._execute_context_rag(rag_context)
            elif context_type == "calendar":
                return self._execute_context_calendar()
            elif context_type == "instructions":
                # Retornar contedo de HELP.md (instrues de ferramentas)
                try:
                    from pathlib import Path

                    core_dir = Path(__file__).parent.parent
                    help_file = core_dir / "Agents" / "Agents" / "HELP.md"

                    if help_file.exists():
                        with open(help_file, "r", encoding="utf-8") as f:
                            help_content = f.read()
                        return json.dumps(
                            {
                                "success": True,
                                "tool": "context",
                                "type": "instructions",
                                "help": help_content,
                            },
                            ensure_ascii=False,
                        )
                    else:
                        return json.dumps(
                            {
                                "success": False,
                                "error": f"HELP.md no encontrado em {help_file}",
                                "tool": "context",
                            },
                            ensure_ascii=False,
                        )
                except Exception as e:
                    return json.dumps(
                        {
                            "success": False,
                            "error": f"Erro ao ler HELP.md: {str(e)}",
                            "tool": "context",
                        },
                        ensure_ascii=False,
                    )
            elif context_type in ("document", "documents"):
                # Suporta leitura de documento especfico por ID:
                # context(type='document', document='<uuid>') ou document_id
                _doc_id_arg = (
                    args.get("document", "").strip()
                    if isinstance(args.get("document"), str)
                    else ""
                )
                if not _doc_id_arg:
                    _doc_id_arg = args.get("document_id", "").strip()
                if not _doc_id_arg:
                    _doc_obj = args.get("document", {})
                    if isinstance(_doc_obj, dict):
                        _doc_id_arg = _doc_obj.get("document_id", "").strip()

                #  GATE: SkillCopywriting ativa  proibir consulta de documentos ESPECFICOS antes do quiz Etapa 1
                # Permitimos listagem (seja type='documents' ou 'document' SEM ID)
                _is_listing = not _doc_id_arg

                if self.db_manager and self.current_chat_id and self.current_user_id:
                    try:
                        from App.Core.Crunch.TablesSQL.Models import (
                            IsolatedMessage as _IMgd,
                        )

                        _gds = self.db_manager.get_session()
                        try:
                            # 1. Localizar SkillCopywriting (apenas sucessos)
                            _skill_copy_loaded = (
                                _gds.query(_IMgd)
                                .filter(
                                    _IMgd.isolated_chat_id == self.current_chat_id,
                                    _IMgd.tool_called == "lookup",
                                    _IMgd.tool_call_type == "output",
                                    _IMgd.content.ilike("%SkillCopywriting.md%"),
                                    _IMgd.content.ilike('%"success": true%'),
                                )
                                .order_by(_IMgd.id.desc())
                                .first()
                            )

                            if _skill_copy_loaded:
                                # 2. Verificar se Quiz Etapa 1 foi respondido (apenas sucessos)
                                _quiz_etapa1_answered = (
                                    _gds.query(_IMgd)
                                    .filter(
                                        _IMgd.isolated_chat_id == self.current_chat_id,
                                        _IMgd.tool_called == "quiz",
                                        _IMgd.tool_call_type == "output",
                                        _IMgd.content.ilike("%post_category%"),
                                        _IMgd.content.ilike('%"success": true%'),
                                        _IMgd.id > _skill_copy_loaded.id,
                                    )
                                    .first()
                                )

                                if not _is_listing:
                                    # GATE LEITURA ESPECFICA
                                    if not _quiz_etapa1_answered:
                                        return json.dumps(
                                            {
                                                "success": False,
                                                "error": "Ao bloqueada: Voc deve executar primeiro context(type='documents') para listar os produtos e depois o Quiz Etapa 1.",
                                                "tool": "context",
                                                "hint": "O acesso ao contedo detalhado s  liberado aps a Etapa 1 do Quiz.",
                                            },
                                            ensure_ascii=False,
                                        )

                                    # 1. Parsear resposta do quiz para saber categoria e produto
                                    try:
                                        _quiz_data = json.loads(
                                            _quiz_etapa1_answered.content
                                        )
                                        _answers = _quiz_data.get("final_answers", [])
                                        _category = ""
                                        _sel_product = ""
                                        for _a in _answers:
                                            _q_text = _a.get("question", "").lower()
                                            if "categoria" in _q_text:
                                                _category = _a.get("answer", "").lower()
                                            if "produto" in _q_text:
                                                _sel_product = _a.get("answer", "")

                                        _is_branding = "branding" in _category
                                    except Exception as _qpe:
                                        debug(
                                            f"[CONTEXT] Erro ao parsear quiz para gate: {_qpe}"
                                        )
                                        _is_branding = False
                                        _sel_product = ""

                                    # 2. Obter metadados do documento solicitado
                                    from sqlalchemy import text as _txt

                                    _doc_meta = _gds.execute(
                                        _txt(
                                            "SELECT tool_type, title FROM documents WHERE document_id = :did"
                                        ),
                                        {"did": _doc_id_arg},
                                    ).fetchone()

                                    if not _doc_meta:
                                        return json.dumps(
                                            {
                                                "success": False,
                                                "error": "Documento no encontrado.",
                                                "tool": "context",
                                            },
                                            ensure_ascii=False,
                                        )

                                    _req_type = _doc_meta[0]
                                    _req_title = _doc_meta[1]

                                    # 3. Validar se o documento  permitido para esta categoria
                                    if _req_type == "brand_communication":
                                        pass  # Sempre permitido
                                    elif _is_branding:
                                        if _req_type == "business_canvas":
                                            pass  # Permitido para branding
                                        else:
                                            return json.dumps(
                                                {
                                                    "success": False,
                                                    "error": "Acesso negado: Campanhas de Branding exigem Brand Communication e Business Canvas.",
                                                    "hint": "No tente ler documentos de 'product' em branding. Use o Business Canvas.",
                                                    "tool": "context",
                                                },
                                                ensure_ascii=False,
                                            )
                                    else:  # Anncio / Funil
                                        if _req_type == "product":
                                            if _req_title != _sel_product:
                                                return json.dumps(
                                                    {
                                                        "success": False,
                                                        "error": f"Acesso negado: Voc deve ler o produto selecionado no Quiz ('{_sel_product}').",
                                                        "hint": f"O ID solicitado no corresponde ao produto '{_sel_product}' escolhido pelo usurio.",
                                                        "tool": "context",
                                                    },
                                                    ensure_ascii=False,
                                                )
                                        elif _req_type == "business_canvas":
                                            return json.dumps(
                                                {
                                                    "success": False,
                                                    "error": "Acesso negado: Campanhas de Anncio/Funil utilizam Brand Communication e Product (no o Business Canvas).",
                                                    "hint": f"Leia o Brand Communication e o produto '{_sel_product}'.",
                                                    "tool": "context",
                                                },
                                                ensure_ascii=False,
                                            )
                                        else:
                                            # Outros tipos (copywriting, etc) bloqueados nesta fase
                                            return json.dumps(
                                                {
                                                    "success": False,
                                                    "error": f"Acesso negado: Tipo '{_req_type}' no permitido nesta etapa.",
                                                    "tool": "context",
                                                },
                                                ensure_ascii=False,
                                            )

                                    # 4. Limite de 2 leituras bem-sucedidas (apenas sucessos)
                                    _reads_count = (
                                        _gds.query(_IMgd)
                                        .filter(
                                            _IMgd.isolated_chat_id
                                            == self.current_chat_id,
                                            _IMgd.tool_called == "context",
                                            _IMgd.tool_call_type == "output",
                                            _IMgd.content.ilike('%"success": true%'),
                                            (
                                                _IMgd.content.ilike("%document_id%")
                                                | _IMgd.content.ilike('%"document": "%')
                                            ),
                                            _IMgd.id > _quiz_etapa1_answered.id,
                                        )
                                        .count()
                                    )

                                    if _reads_count >= 2:
                                        _h = (
                                            "Voc j leu o Brand Communication e o Business Canvas."
                                            if _is_branding
                                            else f"Voc j leu o Brand Communication e o produto '{_sel_product}'."
                                        )
                                        return json.dumps(
                                            {
                                                "success": False,
                                                "error": "Limite de leitura atingido (2 documentos especficos por ciclo).",
                                                "tool": "context",
                                                "hint": _h,
                                            },
                                            ensure_ascii=False,
                                        )
                                else:
                                    # GATE LISTAGEM BRUTA (apenas sucessos)
                                    _list_count = (
                                        _gds.query(_IMgd)
                                        .filter(
                                            _IMgd.isolated_chat_id
                                            == self.current_chat_id,
                                            _IMgd.tool_called == "context",
                                            _IMgd.tool_call_type == "output",
                                            _IMgd.content.ilike('%"success": true%'),
                                            _IMgd.content.ilike('%"type": "document%'),
                                            ~_IMgd.content.ilike("%document_id%"),
                                            ~_IMgd.content.ilike('%"document": "%'),
                                            _IMgd.id > _skill_copy_loaded.id,
                                        )
                                        .count()
                                    )
                                    if _list_count >= 1:
                                        return json.dumps(
                                            {
                                                "success": False,
                                                "error": "context(type='documents') j foi executado para a skill atual.",
                                                "hint": "Reutilize a lista j carregada para o Quiz Etapa 1.",
                                                "tool": "context",
                                            },
                                            ensure_ascii=False,
                                        )
                        finally:
                            _gds.close()
                    except Exception as _gdge:
                        debug(f"[CONTEXT] Erro ao verificar gates de context: {_gdge}")

                if _doc_id_arg:
                    return self._get_document_by_id(_doc_id_arg)

                return self._get_documents_list()
            elif context_type == "calendar":
                return self._get_calendar_context()
            elif context_type in ["task", "tasks"]:
                # Retornar lista de tasks do chat atual com task_id e step_id
                if not self.db_manager or not self.current_chat_id:
                    return json.dumps(
                        {
                            "success": False,
                            "error": "Contexto no disponvel",
                            "tool": "context",
                        },
                        ensure_ascii=False,
                    )
                try:
                    from App.Core.Crunch.TablesSQL.Models import Task as _TM

                    _ts = self.db_manager.get_session()
                    try:
                        _rows = (
                            _ts.query(_TM)
                            .filter(
                                _TM.chat_id == self.current_chat_id,
                                _TM.user_id == self.current_user_id,
                            )
                            .order_by(_TM.task_id, _TM.id)
                            .all()
                        )
                    finally:
                        _ts.close()
                    _tasks_map: dict = {}
                    for r in _rows:
                        if r.task_id not in _tasks_map:
                            _tasks_map[r.task_id] = {
                                "task_id": r.task_id,
                                "task_name": r.task_name,
                                "steps": [],
                            }
                        _tasks_map[r.task_id]["steps"].append(
                            {
                                "step_id": r.step_id,
                                "step_name": r.step_name,
                                "status": r.status,
                            }
                        )
                    _tasks_list = list(_tasks_map.values())
                    return json.dumps(
                        {
                            "success": True,
                            "tool": "context",
                            "type": "tasks",
                            "tasks": _tasks_list,
                            "total": len(_tasks_list),
                        },
                        ensure_ascii=False,
                    )
                except Exception as _te:
                    return json.dumps(
                        {
                            "success": False,
                            "error": f"Erro ao consultar tasks: {_te}",
                            "tool": "context",
                        },
                        ensure_ascii=False,
                    )
            elif context_type == "media":
                return json.dumps(
                    {
                        "success": True,
                        "tool": "context",
                        "type": "media",
                        "message": "Contexto de mdia (imagens, vdeos) gerada em context(type='media')",
                        "note": "Media no tem contexto persistente - use asset(type='image' ou type='video')",
                    },
                    ensure_ascii=False,
                )
            else:
                return json.dumps(
                    {
                        "success": False,
                        "error": f"Type '{context_type}' no reconhecido. Use: instructions, document, calendar, task, media",
                        "tool": "context",
                    },
                    ensure_ascii=False,
                )

        try:
            #  COMENTADO: Carregamento automtico de STEPS.json desabilitado
            # Esse bloco tentava carregar STEPS.json mesmo quando no era necessrio
            # Ser habilitado APENAS quando type="steps" ou step=... for especificado

            # # Carrega o arquivo CONTEXT.json (path relativo ao Core.py)
            # # Core.py: App/Features/Tools/Core.py
            # # CONTEXT.json: App/Features/Agents/Agents/Context.json
            # # Diferena: 2 nveis para cima (Core -> Tools -> Features), depois 2 para baixo (Agents -> Agents)
            # from pathlib import Path
            # core_dir = Path(__file__).parent.parent  # Features directory
            # context_file = core_dir / "Agents" / "Agents" / "STEPS.json"
            #
            # debug(f"[_EXECUTE_CONTEXT] help_mode={help_mode}, vai carregar CONTEXT.json")
            # debug(f"[_EXECUTE_CONTEXT] Tentando abrir arquivo em: {context_file}")
            # debug(f"[_EXECUTE_CONTEXT] Arquivo existe? {context_file.exists()}")
            #
            # with open(context_file, 'r', encoding='utf-8') as f:
            #     debug(f"[_EXECUTE_CONTEXT] STEPS.json aberto, comeando parse JSON...")
            #     context_data = json.load(f)
            #     debug(f"[_EXECUTE_CONTEXT] JSON parsed com sucesso")
            #
            # steps = context_data.get("steps", [])
            # debug(f"[_EXECUTE_CONTEXT] STEPS.json carregado, steps={len(steps)}")

            steps = []  # Definir como vazio para que lgica abaixo continue funcionando

            # MODO HELP: help=true retorna ajuda sobre como usar a ferramenta context
            if help_mode:
                debug(
                    "[_EXECUTE_CONTEXT] Modo HELP detectado, retornando documentao da ferramenta context"
                )
                help_content = """# Ferramenta: context - Recuperar Contexto

## Descrio
Ferramenta para recuperar informaes contextuais e documentao. As informaes de ferramentas (tools_instructions), informaes do cliente (user_info) e data/hora atual (current_date) J ESTO INJETADAS NO SYSTEM PROMPT no incio de cada conversa.

## Uso

### Recuperar Etapas do Workflow
#### Listar todas as etapas em ordem lgica:
context(type="steps")
- Retorna: Lista de todas as etapas com ordem sequencial de execuo

#### Obter instrues de um step especfico:
context(type="steps", step="NOME_DO_STEP")
- Exemplo: context(type="steps", step="PESQUISA_DO_ANUNCIANTE")
- Retorna: Instrues detalhadas, pr-requisitos e objetivo do step

### Recuperar Orientaes Estratgicas (RAG)
#### Listar todas as orientaes disponveis:
context(type="rag")
- Retorna: Lista de todas as sees de orientao estratgica com trigadores de ativao

#### Obter orientao especfica:
context(type="rag", context="TTULO_DA_ORIENTAO")
- Exemplo: context(type="rag", context="ANLISE DE MERCADOS ENDEREVEIS (TAM)")
- Retorna: Instrues detalhadas sobre a orientao estratgica

### Recuperar Documentos Salvos
context(type="document")
- Retorna: Lista de todos os documentos salvos com IDs (para editar depois com update)

### Recuperar Informaes do Cliente
context(type="client")
- Retorna: Lista de dados persistentes do cliente (briefing, ICPs, estratgias, etc) com IDs

### Recuperar Tasks/Etapas
context(type="task")
- Retorna: Contexto atual das tarefas em execuo

### Recuperar Mdia
context(type="media")
- Retorna: Informaes sobre mdia gerada (imagens, vdeos)

### Obter Ajuda sobre context
context(help=true)
- Retorna: Esta documentao

##  IMPORTANTE
- tools_instructions, user_info e current_date J VM no system prompt!
- NO PRECISA executar context() no incio da conversa para obt-las
- Use context(type="...") apenas para RECUPERAR IDs ou CONFIRMAR informaes
- context() NO sincroniza para main chat - respostas ficam apenas no agent (isoladas)

## Parmetros
- type (opcional): "steps" | "rag" | "document" | "client" | "task" | "media"
- step (opcional, com type="steps"): Nome ou nmero do step especfico
- context (opcional, com type="rag"): Ttulo da orientao estratgica especfica
- help (opcional): Se true, retorna esta documentao

## Quando usar
 context(type="steps") para conhecer ordem de etapas do workflow
 context(type="steps", step="...") para obter instrues de um step especfico
 context(type="rag") para conhecer orientaes estratgicas disponveis
 context(type="rag", context="...") para obter orientao estratgica especfica
 Recuperar IDs de documentos/clientes para editar com update()
 Confirmar/revisar informaes persistentes do cliente
 Ver status de tasks em andamento
 NO precisa executar para obter tools_instructions, user_info ou data"""

                debug(f"[CONTEXT] Documentao da ferramenta context preparada")
                result = json.dumps(
                    {"success": True, "tool": "context", "help": help_content},
                    ensure_ascii=False,
                )
                debug(f"[CONTEXT] Retornando JSON com {len(result)} chars")
                return result

            if not steps:
                return json.dumps(
                    {
                        "success": False,
                        "error": "Nenhum step encontrado no STEPS.json",
                        "tool": "context",
                    }
                )

            matched_steps = []

            # Detectar tipo de query
            if "-" in step_query:
                # Range query: "1-5"
                try:
                    parts = step_query.split("-")
                    start = int(parts[0].strip())
                    end = int(parts[1].strip())
                    matched_steps = [
                        s for s in steps if start <= s.get("number", 0) <= end
                    ]
                except (ValueError, IndexError):
                    return json.dumps(
                        {
                            "success": False,
                            "error": f"Range invlido: '{step_query}'. Use formato: '1-5'",
                            "tool": "context",
                        }
                    )
            elif step_query.isdigit():
                # Single number query: "1"
                step_num = int(step_query)
                matched_steps = [s for s in steps if s.get("number") == step_num]
            else:
                # Name query: "PESQUISA_DO_ANUNCIANTE"
                matched_steps = [
                    s for s in steps if s.get("name", "").upper() == step_query.upper()
                ]

            if not matched_steps:
                return json.dumps(
                    {
                        "success": False,
                        "error": f"Nenhum step encontrado para: '{step_query}'",
                        "tool": "context",
                    }
                )

            debug(
                f"[CONTEXT] Retornando {len(matched_steps)} step(s) para query: {step_query}"
            )

            # Construir resposta com instrues dos steps
            instructions = []
            for step in matched_steps:
                instructions.append(
                    {
                        "number": step.get("number"),
                        "name": step.get("name"),
                        "filename": step.get("filename"),
                        "objective": step.get("objective"),
                        "instructions": step.get("instructions"),
                    }
                )

            return json.dumps(
                {
                    "success": True,
                    "tool": "context",
                    "query": step_query,
                    "steps_found": len(matched_steps),
                    "instructions": instructions,
                },
                ensure_ascii=False,
            )

        except FileNotFoundError:
            error(f"[CONTEXT] Arquivo STEPS.json no encontrado")
            return json.dumps(
                {
                    "success": False,
                    "error": "Arquivo STEPS.json no encontrado",
                    "tool": "context",
                },
                ensure_ascii=False,
            )
        except Exception as e:
            error(f"[CONTEXT] Erro ao processar context: {e}")
            import traceback

            error(f"[CONTEXT] Traceback: {traceback.format_exc()}")
            result = json.dumps(
                {"success": False, "error": str(e), "tool": "context"},
                ensure_ascii=False,
            )
            # Safeguard: sempre retorna string, nunca None
            return result if isinstance(result, str) else str(result)

    def _execute_context_steps(self, step_query: str = "") -> str:
        """
        Retorna informaes sobre etapas (steps) de workflow.
        Se step_query vazio, retorna lista de todas as etapas.
        Se step_query fornecido, retorna detalhes de um step especfico.

        Args:
            step_query: Nome ou nmero do step (opcional)

        Returns:
            JSON com steps e ordem lgica
        """
        try:
            from pathlib import Path

            core_dir = Path(__file__).parent.parent
            steps_file = core_dir / "Agents" / "Agents" / "STEPS.json"

            if not steps_file.exists():
                return json.dumps(
                    {
                        "success": False,
                        "error": f"STEPS.json no encontrado em {steps_file}",
                        "tool": "context",
                    },
                    ensure_ascii=False,
                )

            with open(steps_file, "r", encoding="utf-8") as f:
                steps_data = json.load(f)

            steps = steps_data.get("steps", [])

            # Se step_query vazio, retornar lista de todas as etapas com ordem lgica
            if not step_query:
                steps_summary = []
                for idx, step in enumerate(steps, 1):
                    steps_summary.append(
                        {
                            "order": idx,
                            "name": step.get("name"),
                            "filename": step.get("filename"),
                            "objective": step.get("objective"),
                            "prerequisites": step.get("prerequisites", []),
                        }
                    )

                return json.dumps(
                    {
                        "success": True,
                        "tool": "context",
                        "type": "steps",
                        "total_steps": len(steps),
                        "steps_order": "Execuo sequencial de 1 at o final",
                        "steps": steps_summary,
                        "note": "Use context(type='steps', step='NOME_DO_STEP') para ver instrues detalhadas de um step especfico",
                    },
                    ensure_ascii=False,
                )

            # Se step_query fornecido, retornar detalhes do step especfico
            matched_steps = [
                s for s in steps if s.get("name", "").upper() == step_query.upper()
            ]

            if not matched_steps:
                # Tentar por nmero
                try:
                    step_num = int(step_query)
                    matched_steps = (
                        [steps[step_num - 1]] if 0 < step_num <= len(steps) else []
                    )
                except (ValueError, IndexError):
                    pass

            if not matched_steps:
                return json.dumps(
                    {
                        "success": False,
                        "error": f"Step '{step_query}' no encontrado em STEPS.json",
                        "tool": "context",
                    },
                    ensure_ascii=False,
                )

            step = matched_steps[0]
            step_idx = steps.index(step) + 1

            return json.dumps(
                {
                    "success": True,
                    "tool": "context",
                    "type": "steps",
                    "step_order": step_idx,
                    "total_steps": len(steps),
                    "step_details": {
                        "name": step.get("name"),
                        "filename": step.get("filename"),
                        "objective": step.get("objective"),
                        "prerequisites": step.get("prerequisites", []),
                        "conditional": step.get("conditional"),
                        "instructions": step.get("instructions"),
                    },
                },
                ensure_ascii=False,
            )

        except Exception as e:
            error(f"[_EXECUTE_CONTEXT_STEPS] Erro: {e}")
            return json.dumps(
                {
                    "success": False,
                    "error": f"Erro ao obter contexto de steps: {str(e)}",
                    "tool": "context",
                },
                ensure_ascii=False,
            )

    def _execute_context_rag(self, rag_context: str = "") -> str:
        """
        Retorna informaes sobre orientaes estratgicas (RAG).
        Se rag_context vazio, retorna lista de todas as orientaes.
        Se rag_context fornecido, retorna detalhes de uma orientao especfica.

        Args:
            rag_context: Ttulo ou seo da orientao (opcional)

        Returns:
            JSON com orientaes estratgicas
        """
        try:
            from pathlib import Path

            core_dir = Path(__file__).parent.parent
            rag_file = core_dir / "Agents" / "Agents" / "RAG.json"

            if not rag_file.exists():
                return json.dumps(
                    {
                        "success": False,
                        "error": f"RAG.json no encontrado em {rag_file}",
                        "tool": "context",
                    },
                    ensure_ascii=False,
                )

            with open(rag_file, "r", encoding="utf-8") as f:
                rag_data = json.load(f)

            strategic = rag_data.get("strategic_guidance", {})
            sections = strategic.get("sections", {})

            # Se rag_context vazio, retornar lista de todas as orientaes
            if not rag_context:
                sections_list = []
                for key, section in sections.items():
                    sections_list.append(
                        {
                            "id": key,
                            "title": section.get("title"),
                            "description": section.get("description"),
                        }
                    )

                return json.dumps(
                    {
                        "success": True,
                        "tool": "context",
                        "type": "rag",
                        "name": strategic.get("name"),
                        "description": strategic.get("description"),
                        "activation_triggers": strategic.get("activation_triggers", []),
                        "total_sections": len(sections_list),
                        "sections": sections_list,
                        "note": "Use context(type='rag', context='TTULO_DA_SEO') para ver orientao detalhada de uma seo especfica",
                    },
                    ensure_ascii=False,
                )

            # Se rag_context fornecido, retornar detalhes da orientao especfica
            matched_section = None
            matched_key = None

            for key, section in sections.items():
                title = section.get("title", "").upper()
                if title == rag_context.upper():
                    matched_section = section
                    matched_key = key
                    break
                # Tambm tentar por ID
                if key.upper() == rag_context.upper():
                    matched_section = section
                    matched_key = key
                    break

            if not matched_section:
                return json.dumps(
                    {
                        "success": False,
                        "error": f"Orientao '{rag_context}' no encontrada em RAG.json",
                        "available_sections": [
                            s.get("title") for s in sections.values()
                        ],
                        "tool": "context",
                    },
                    ensure_ascii=False,
                )

            return json.dumps(
                {
                    "success": True,
                    "tool": "context",
                    "type": "rag",
                    "section_id": matched_key,
                    "section_details": matched_section,
                },
                ensure_ascii=False,
            )

        except Exception as e:
            error(f"[_EXECUTE_CONTEXT_RAG] Erro: {e}")
            return json.dumps(
                {
                    "success": False,
                    "error": f"Erro ao obter contexto de RAG: {str(e)}",
                    "tool": "context",
                },
                ensure_ascii=False,
            )

    def _execute_client(self, args: Dict[str, Any]) -> str:
        """
        Executa tool 'client' para gerenciar informaes do cliente que persistem entre conversas.

        Args:
            args: Dict com:
                - document: Nome do documento (ex: 'Briefing_ACME', 'ICPs_ACME')
                - content: Contedo do documento
                - help: Boolean True para retornar instrues de uso da tool

        Returns:
            JSON com resultado da operao
        """
        help_mode = args.get("help", False)

        # MODO HELP: retornar instrues de uso da tool
        if help_mode is True:
            return self._get_tool_instructions("client")

        document_name = args.get("document", "").strip()
        content = args.get("content", "").strip()

        if not document_name:
            return json.dumps(
                {
                    "success": False,
                    "error": "document  obrigatrio (ex: 'Briefing_ACME', 'ICPs_ACME')",
                    "tool": "client",
                }
            )

        if not content:
            return json.dumps(
                {"success": False, "error": "content  obrigatrio", "tool": "client"}
            )

        if not self.current_user_id:
            return json.dumps(
                {
                    "success": False,
                    "error": "Contexto de cliente no disponvel",
                    "tool": "client",
                }
            )

        try:
            # Salvar no banco de dados
            session = self.db_manager.get_session()
            try:
                # Calcular hash e tamanho
                content_bytes = content.encode("utf-8")
                file_hash = hashlib.sha256(content_bytes).hexdigest()
                file_size = len(content_bytes)

                # Gerar ID nico
                file_id = str(uuid_lib.uuid4())

                # Extrair short_description (primeiras 100 chars do contedo)
                short_description = content[:100].replace("\n", " ").strip()
                if len(content) > 100:
                    short_description += "..."

                # Caminho de armazenamento (client-specific)
                storage_path = (
                    f"client_{self.current_user_id}/client_info/{document_name}.md"
                )

                # Obter client_id do usurio
                user = (
                    session.query(User)
                    .filter(User.user_id == self.current_user_id)
                    .first()
                )
                client_id = user.client_id if user else None

                # Salvar em Document model em vez de deprecated files table
                try:
                    document = Document(
                        document_id=file_id,
                        chat_id=self.current_chat_id,
                        user_id=self.current_user_id,
                        title=document_name,
                        content=content,
                        extension="md",
                        tool_type="client",
                    )
                    session.add(document)
                    session.commit()
                    debug(
                        f"[CLIENT] Documento do cliente salvo: {document_name} ({file_id})"
                    )
                    return json.dumps(
                        {
                            "success": True,
                            "tool": "client",
                            "id": file_id,
                            "document": document_name,
                            "short_description": short_description,
                            "status": "saved_to_db",
                            "message": f"Informao '{document_name}' salva e disponvel globalmente",
                        },
                        ensure_ascii=False,
                    )
                except Exception as db_err:
                    session.rollback()
                    debug(f"[CLIENT] Erro ao salvar documento: {db_err}")
                    return json.dumps(
                        {
                            "success": False,
                            "error": f"Falha ao salvar: {str(db_err)}",
                            "tool": "client",
                        }
                    )

            finally:
                session.close()

        except Exception as e:
            error(f"[CLIENT] Erro ao salvar informao do cliente: {e}")
            return json.dumps({"success": False, "error": str(e), "tool": "client"})

    def _get_client_documents_list(self) -> str:
        """
        Lista documentos obrigatrios do cliente: business_canvas e brand_communication.
        Se no existir, retorna instrues para criar imediatamente.

        Returns:
            JSON com lista de documentos e instrues
        """
        if not self.current_user_id or not self.db_manager:
            debug(
                f"[CLIENT-HELP] Contexto incompleto: client_id={self.current_user_id}, db_manager={bool(self.db_manager)}"
            )
            return json.dumps(
                {
                    "success": True,
                    "tool": "client",
                    "documents": {},
                    "message": "Contexto incompleto para listar documentos",
                },
                ensure_ascii=False,
            )

        session = None
        try:
            session = self.db_manager.get_session()
            from sqlalchemy import text

            # Buscar business_canvas, brand_communication da tabela documents
            # E schedules (calendar) da tabela calendar
            query = text(
                """
                SELECT document_id, title, tool_type, content, created_at
                FROM documents
                WHERE user_id = :user_id AND tool_type IN ('business_canvas', 'brand_communication')
                ORDER BY tool_type ASC, created_at DESC
            """
            )

            results = session.execute(
                query, {"user_id": self.current_user_id}
            ).fetchall()
            debug(
                f"[CLIENT-HELP] {len(results) if results else 0} documentos do cliente encontrados"
            )

            documents = {}
            found_types = set()

            for row in results:
                doc_id, title, doc_type, content, created_at = row
                found_types.add(doc_type)

                # Parse content se for JSON
                try:
                    parsed_content = (
                        json.loads(content)
                        if isinstance(content, str) and content.startswith("{")
                        else content
                    )
                except:
                    parsed_content = content

                documents[doc_type] = {
                    "document_id": doc_id,
                    "title": title,
                    "type": doc_type,
                    "content": parsed_content,
                    "created_at": str(created_at) if created_at else None,
                }

            # Buscar schedules (calendar) do cliente - GLOBAL para todos os chats
            try:
                schedule_query = text(
                    """
                    SELECT COUNT(*) as total_posts, MIN(post_date) as start_date, MAX(post_date) as end_date
                    FROM calendar
                    WHERE user_id = :user_id
                """
                )
                schedule_result = session.execute(
                    schedule_query, {"user_id": self.current_user_id}
                ).fetchone()

                if schedule_result and schedule_result[0] > 0:
                    found_types.add("calendar")
                    documents["calendar"] = {
                        "type": "calendar",
                        "title": "Calendar de Posts",
                        "status": "created",
                        "total_posts": schedule_result[0],
                        "period": f"{schedule_result[1]} a {schedule_result[2]}",
                        "description": "Todos os posts agendados para o cliente (global)",
                    }
            except Exception as e:
                debug(f"[CLIENT-HELP] Erro ao buscar calendar: {e}")

            # Verificar documentos faltando e carregar instrues do SIGNIN.json
            missing_types = {
                "business_canvas",
                "brand_communication",
                "calendar",
            } - found_types
            signin_instructions = {}

            if missing_types:
                try:
                    signin_path = (
                        Path(__file__).parent.parent / "Agents" / "SIGNIN.json"
                    )
                    if signin_path.exists():
                        with open(signin_path, "r", encoding="utf-8") as f:
                            signin_data = json.load(f)
                            for doc_type in missing_types:
                                if doc_type in signin_data:
                                    documents[doc_type] = {
                                        "document_id": None,
                                        "title": f"[NO CRIADO] {doc_type}",
                                        "type": doc_type,
                                        "status": "not_found",
                                        "instruction": signin_data[doc_type][
                                            "instructions"
                                        ],
                                        "example_fields": signin_data[doc_type][
                                            "example_fields"
                                        ],
                                        "action_required": f"Criar imediatamente: document(type='{doc_type}', title='...', data={{...}})",
                                    }
                except Exception as e:
                    debug(f"[CLIENT-HELP] Erro ao carregar SIGNIN.json: {e}")

            result_json = json.dumps(
                {
                    "success": True,
                    "tool": "client",
                    "total": len(documents),
                    "created": len(found_types),
                    "missing": list(missing_types),
                    "documents": documents,
                    "message": (
                        f"{len(found_types)} documentos criados, {len(missing_types)} documentos faltando - CRIE IMEDIATAMENTE!"
                        if missing_types
                        else f"Total de {len(documents)} documentos do cliente"
                    ),
                },
                ensure_ascii=False,
            )
            debug(f"[CLIENT-HELP] Retornando JSON com {len(documents)} documentos")
            return result_json

        except Exception as e:
            debug(f"[CLIENT-HELP] Erro ao listar documentos: {e}")
            return json.dumps(
                {
                    "success": True,
                    "tool": "client",
                    "documents": {},
                    "message": "Erro ao listar documentos do cliente",
                },
                ensure_ascii=False,
            )
        finally:
            if session:
                try:
                    session.close()
                except:
                    pass

    def _get_assets_list(self) -> str:
        """
        Lista todos os assets (imagens/vdeos) gerados.

        Returns:
            JSON com lista de assets
        """
        if not self.current_user_id or not self.db_manager:
            return json.dumps(
                {
                    "success": True,
                    "tool": "vision",
                    "assets": {},
                    "message": "Nenhum asset gerado ainda",
                },
                ensure_ascii=False,
            )

        try:
            session = self.db_manager.get_session()
            try:
                from sqlalchemy import text

                # Buscar todos os assets (imagens/vdeos)
                query = text(
                    """
                    SELECT file_name, file_size, created_at, storage_path
                    FROM files
                    WHERE user_id = :user_id AND file_category = 'asset' AND deleted_at IS NULL
                    ORDER BY created_at DESC
                """
                )

                results = session.execute(
                    query, {"user_id": self.current_user_id}
                ).fetchall()

                assets = {}
                for row in results:
                    assets[row[0]] = {
                        "name": row[0],
                        "size": row[1],
                        "created_at": str(row[2]) if row[2] else None,
                        "path": row[3],
                    }

                return json.dumps(
                    {
                        "success": True,
                        "tool": "vision",
                        "total": len(assets),
                        "assets": assets,
                        "message": f"Total de {len(assets)} asset(s) gerado(s)",
                    },
                    ensure_ascii=False,
                )

            finally:
                session.close()

        except Exception as e:
            debug(f"[VISION-HELP] Erro ao listar assets: {e}")
            return json.dumps({"success": False, "tool": "vision", "error": str(e)})

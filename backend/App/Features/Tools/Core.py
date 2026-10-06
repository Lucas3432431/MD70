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
from App.Features.Tools.Tools.RagQuery import execute_rag_query
from App.Features.Tools.Tools.Schedule import execute_schedule
from App.Features.Tools.Tools.Skill import execute_skill
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
from App.Core.Utils.TemporaryScreenshotStore import generate as generate_temp_screenshot
from App.Features.Tools._asset import _call_vision_with_fallback
from App.Core.Types import (
    AssetType,
    AssetContentType,
    ASSET_TYPE_TO_CONTENT_TYPE,
    ASSET_CONTENT_TYPE_TO_EXTENSION,
)

# ============================================================================
# MCP AUTH ERROR HELPER
# ============================================================================

_MCP_AUTH_KEYWORDS = [
    "session has expired",
    "error validating access token",
    "oauthexception",
    "invalid token",
    "token has expired",
    "token expired",
    "unauthorized",
    "access token expired",
]


def _mark_token_invalid_if_auth_error(
    err_msg: str, tool_name: str, client_id: str, db_manager
) -> None:
    """Se o erro de MCP indica token expirado, marca token_valid=False no DB."""
    if not any(kw in err_msg.lower() for kw in _MCP_AUTH_KEYWORDS):
        return
    try:
        from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager as _DBMgr

        parts = tool_name.split("__")
        provider = parts[1] if len(parts) >= 2 else ""
        if not provider or not client_id:
            return
        session = db_manager.get_session()
        _DBMgr.mark_integration_token_invalid(session, client_id, provider)
        session.close()
        debug(f"[TOOL] Token inválido detectado — provider={provider} marcado no DB")
    except Exception as _e:
        debug(f"[TOOL] Erro ao marcar token inválido: {_e}")


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
TOOL_FILE = "file"
TOOL_SCHEDULE = "schedule"
TOOL_CANCEL = "cancel"
TOOL_TERMINAL = "terminal"
TOOL_HELP = "help"

# Tools folder config
TOOLS_DIR = Path(__file__).parent.parent / "Agents" / "Agents" / ".Agent" / "Tools"
TOOLS_CONFIG_FILE = "TOOLS.json"

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
    "social_media",  # SkillSocialMedia — conteudo organico para redes sociais
    "catalog",  # SkillCatalog — imagens de catalogo para site/plataforma
    "self_knowledge",  # SkillSelfKnowledge — autoconhecimento estrategico da marca
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


# Mixins — cada arquivo contém um domínio de tools
from ._document import DocumentMixin
from ._document_update import DocumentUpdateMixin
from ._document_validators import DocumentValidatorsMixin
from ._asset import AssetMixin
from ._quiz import QuizMixin
from ._web_search import WebSearchMixin
from ._schedule import ScheduleMixin
from ._context import ContextMixin
from ._task import TaskMixin
from ._validators import ValidatorsMixin
from ._sandbox import SandboxMixin
from ._gate_engine import GateEngineMixin
from ._autonomy_gate import AutonomyGateMixin


class Core(
    DocumentMixin,
    DocumentUpdateMixin,
    DocumentValidatorsMixin,
    AssetMixin,
    QuizMixin,
    WebSearchMixin,
    ScheduleMixin,
    ContextMixin,
    TaskMixin,
    ValidatorsMixin,
    SandboxMixin,
    GateEngineMixin,
    AutonomyGateMixin,
):
    """Facilita execuo de tools para agents."""

    def __init__(
        self,
        message_processor=None,
        chat_manager=None,
        agents_manager=None,
        db_manager=None,
    ):
        self.message_processor = message_processor
        self.chat_manager = chat_manager
        self.agents_manager = agents_manager
        self.db_manager = db_manager
        # Rastrear tasks criadas com status pending para permitir atualizao posterior
        self.pending_tasks = (
            {}
        )  # {(task_name, step_context): status} - step_context  o nmero do step (1, 2, 3, ...)
        # Contexto do chat atual para salvar tasks.json
        self.current_chat_id = None
        self.current_user_id = None
        # Rastrear se message ou chain-of-thought foi chamado (um dos dois obrigatrio antes de outras tools)
        self.message_used = False
        self.chain_of_thought_used = False
        # ID do último documento copywriting salvo que ainda não teve assets gerados
        self._pending_document_id: str | None = None
        self._pending_document_partial: bool = False

        # Configuraes de histrico para validaes
        self.LOOKUP_HISTORY_LIMIT = LOOKUP_HISTORY_LIMIT

        # Configuraes de tipos vlidos
        self.DOCUMENT_VALID_TYPES = DOCUMENT_VALID_TYPES
        self.UPDATE_VALID_TYPES = UPDATE_VALID_TYPES
        self.DELETE_VALID_TYPES = DELETE_VALID_TYPES
        self.VALID_CONTENT_TYPES = VALID_CONTENT_TYPES

        # Configuraes de copywriting
        self.COPY_POST_TYPE_VALUES = COPY_POST_TYPE_VALUES
        self.COPY_ASSET_TYPES = COPY_ASSET_TYPES
        self.COPY_ASPECT_RATIOS = COPY_ASPECT_RATIOS
        self.COPY_FRAMEWORK_VALUES = COPY_FRAMEWORK_VALUES
        self.COPY_FRAMEWORK_FIELDS = COPY_FRAMEWORK_FIELDS
        self.COPY_CHANNELS = COPY_CHANNELS
        self.COPY_CHANNEL_VALID_FORMATS = COPY_CHANNEL_VALID_FORMATS
        self.COPY_ASSET_ANGLE_VALUES = COPY_ASSET_ANGLE_VALUES
        self.COPY_ASSET_ANGLE_VALUES_PRODUCT = COPY_ASSET_ANGLE_VALUES_PRODUCT
        self.COPY_ASSET_ANGLE_VALUES_CLOSEUP = COPY_ASSET_ANGLE_VALUES_CLOSEUP
        self.COPY_ASSET_MOISTURE_VALUES = COPY_ASSET_MOISTURE_VALUES
        self.COPY_ASSET_BG_TYPE_VALUES = COPY_ASSET_BG_TYPE_VALUES
        self.COPY_ASSET_BG_TYPE_VALUES_PRODUCT = COPY_ASSET_BG_TYPE_VALUES_PRODUCT

        # CRITICAL: Validate Tools configuration file exists
        self._validate_tools_config()

    def _execute_external_tool_pattern(
        tool_name: str, execute_func, args: Dict[str, Any]
    ) -> str:
        """
        PADRO GENRICO para ferramentas externas (vision, asset, web-search).

         IMPORTANTE - Este mtodo NO controla wait/enqueue:
        - Comportamento  determinado pelo MessageProcessor baseado em is_inline
        - Esta funo SEMPRE executa completamente e retorna resultado real
        - O parmetro 'wait'  IGNORADO aqui (MessageProcessor usa para quebrar loop)

        FLUXO CONTROLADO PELO MESSAGEPROCESSOR:
        - is_inline=false + wait=true    MessageProcessor enfileira tool + quebra loop LLM
        - is_inline=false + wait=false   MessageProcessor continua processando
        - is_inline=true                 Sempre executa inline, resultado imediato

        Args:
            tool_name: Nome da ferramenta ('vision', 'asset', 'web-search')
            execute_func: Funo que executa a ferramenta (e.g., self._do_vision_execution)
            args: Dicionrio de argumentos da ferramenta

        Returns:
            JSON com resultado real da execuo (sucesso ou erro)
        """
        try:
            # Remover 'wait' dos args -  ignorado aqui
            if "wait" in args:
                del args["wait"]

            # Executar a ferramenta completamente
            result = execute_func(args)
            return result
        except Exception as e:
            error(f"[EXTERNAL_TOOL] Erro em {tool_name}: {e}")
            return json.dumps({"success": False, "error": str(e), "tool": tool_name})

    def get_available_tools(self, agent_id: Optional[str] = None) -> list:
        """
        Carrega as ferramentas disponveis de TOOLS.json e converte para formato OpenAI.
        Filtra baseado no agent_id se fornecido.

        Args:
            agent_id: ID do agent (ex: 'orchestrator-global'). Se None, retorna todas.

        Returns:
            Lista de ferramentas em formato OpenAI function
        """
        try:
            from pathlib import Path

            tools_json_path = Path(__file__).parent / "Tools" / "TOOLS.json"

            if not tools_json_path.exists():
                debug(
                    f"[get_available_tools] TOOLS.json no encontrado em {tools_json_path}, retornando lista vazia"
                )
                return []

            with open(tools_json_path, "r", encoding="utf-8") as f:
                tools_config = json.load(f)

            # Obter ferramentas permitidas para este agent
            allowed_tools = []
            agent_mcp_enabled = True  # default: inject MCP tools
            if agent_id and agent_id in tools_config.get("agent_tools", {}):
                agent_cfg = tools_config["agent_tools"][agent_id]
                allowed_tools = agent_cfg.get("allowed_tools", [])
                agent_mcp_enabled = agent_cfg.get("mcp_enabled", True)
                debug(
                    f"[get_available_tools] Agent {agent_id}: {len(allowed_tools)} tools permitidas, mcp_enabled={agent_mcp_enabled}"
                )
            else:
                # Se agent_id no encontrado, usar todas as ferramentas
                all_tool_names = list(tools_config.get("tool_definitions", {}).keys())
                debug(
                    f"[get_available_tools] Agent {agent_id} no encontrado, retornando {len(all_tool_names)} tools"
                )
                allowed_tools = all_tool_names

            # Converter para formato OpenAI
            tool_definitions = tools_config.get("tool_definitions", {})
            openai_tools = []

            for tool_name in allowed_tools:
                if tool_name not in tool_definitions:
                    debug(
                        f"[get_available_tools] Tool '{tool_name}' na allowed_tools mas NO encontrada em tool_definitions"
                    )
                    continue

                tool_info = tool_definitions[tool_name]
                openai_tool = {
                    "name": tool_name,
                    "description": tool_info.get("description", ""),
                    "parameters": {"type": "object", "properties": {}, "required": []},
                }

                # Se houver parameters no TOOLS.json, us-los
                if "parameters" in tool_info:
                    openai_tool["parameters"] = tool_info["parameters"]
                    debug(
                        f"[get_available_tools] Tool '{tool_name}': parameters carregados de TOOLS.json"
                    )
                else:
                    debug(
                        f"[get_available_tools] Tool '{tool_name}': SEM parameters em TOOLS.json"
                    )

                openai_tools.append(openai_tool)

            # INJETAR TOOLS DO MCP (Isolado por cliente, filtrado por connections do chat)
            # get_event_loop() lança RuntimeError em Python 3.13 dentro de threads worker.
            # Usar get_running_loop() + RuntimeError fallback para asyncio.run().
            try:
                if not agent_mcp_enabled:
                    debug(
                        f"[get_available_tools] MCP desabilitado para agente {agent_id}, pulando injeção"
                    )
                else:
                    client_id = self._get_client_id_from_user(self.current_user_id)
                    if client_id:
                        try:
                            loop = asyncio.get_running_loop()
                            import nest_asyncio

                            nest_asyncio.apply()
                            mcp_tools = loop.run_until_complete(
                                mcp_manager.get_all_tools(client_id)
                            )
                        except RuntimeError:
                            mcp_tools = asyncio.run(
                                mcp_manager.get_all_tools(client_id)
                            )

                        # Filtrar MCP tools pelo campo connections do chat atual
                        # (evita que o LLM veja tools de integrações não autorizadas)
                        _allowed_providers = None
                        if self.current_chat_id:
                            try:
                                import json as _jconn
                                from App.Core.Crunch.TablesSQL.DBManager import (
                                    DatabaseManager as _DBConn,
                                )

                                _crow = _DBConn.fetch_one(
                                    "SELECT connections FROM chats WHERE chat_id = :cid",
                                    {"cid": self.current_chat_id},
                                )
                                if _crow and _crow.get("connections") is not None:
                                    _allowed_providers = set(
                                        _jconn.loads(_crow["connections"])
                                    )
                            except Exception as _ce:
                                debug(
                                    f"[get_available_tools] Erro ao ler connections: {_ce}"
                                )

                        if _allowed_providers is not None:
                            before = len(mcp_tools)
                            mcp_tools = [
                                t
                                for t in mcp_tools
                                if (
                                    lambda n: n.split("__")[1]
                                    if n.startswith("mcp__") and len(n.split("__")) >= 2
                                    else ""
                                )(t["name"])
                                in _allowed_providers
                            ]
                            debug(
                                f"[get_available_tools] MCP filtrado por connections: {before} → {len(mcp_tools)} tools (permitidos: {_allowed_providers})"
                            )

                        openai_tools.extend(mcp_tools)
                        debug(
                            f"[get_available_tools] Injetadas {len(mcp_tools)} ferramentas do MCP para cliente {client_id}"
                        )
                    else:
                        debug(
                            "[get_available_tools] MCP ignorado: nenhum client_id identificado."
                        )
            except Exception as mcp_err:
                error(
                    f"[get_available_tools] Erro ao buscar ferramentas MCP: {mcp_err}"
                )

            debug(
                f"[get_available_tools] Retornando {len(openai_tools)} ferramentas para {agent_id}: {[t['name'] for t in openai_tools]}"
            )
            return openai_tools

        except Exception as e:
            import traceback

            error(f"[get_available_tools] Erro ao carregar ferramentas: {e}")
            error(f"[get_available_tools] Traceback: {traceback.format_exc()}")
            return []

    def is_inline_tool(self, tool_name: str) -> bool:
        """
        Verifica se uma tool deve ser executada inline (imediatamente) ou enfileirada.
        L o campo is_inline_tool do TOOLS.json.

        Args:
            tool_name: Nome da tool

        Returns:
            True se  inline, False se  external
        """
        if tool_name.startswith("mcp__"):
            return True

        try:
            from pathlib import Path

            tools_json_path = Path(__file__).parent / "Tools" / "TOOLS.json"

            if not tools_json_path.exists():
                return False

            with open(tools_json_path, "r", encoding="utf-8") as f:
                tools_config = json.load(f)

            tool_definitions = tools_config.get("tool_definitions", {})
            if tool_name not in tool_definitions:
                return False

            return tool_definitions[tool_name].get("is_inline_tool", False)

        except Exception as e:
            debug(
                f"[is_inline_tool] Erro ao verificar is_inline_tool para '{tool_name}': {e}"
            )
            return False

    def get_all_tool_instructions(self) -> Dict[str, Any]:
        """
        Retorna instrues consolidadas de TODAS as ferramentas disponveis.
        Usado na injeo de contexto consolidado no incio do chat.

        Returns:
            Dict com {tool_name: {description, usage, is_inline_tool}}
        """
        try:
            from pathlib import Path

            tools_json_path = Path(__file__).parent / "Tools" / "TOOLS.json"

            if not tools_json_path.exists():
                return {"success": False, "error": "TOOLS.json no encontrado"}

            with open(tools_json_path, "r", encoding="utf-8") as f:
                tools_config = json.load(f)

            tool_definitions = tools_config.get("tool_definitions", {})
            consolidated = {"success": True, "tools": {}}

            for tool_name, tool_info in tool_definitions.items():
                consolidated["tools"][tool_name] = {
                    "description": tool_info.get("description", ""),
                    "usage": tool_info.get("usage", ""),
                    "is_inline_tool": tool_info.get("is_inline_tool", False),
                }

            return consolidated

        except Exception as e:
            debug(
                f"[get_all_tool_instructions] Erro ao obter instrues consolidadas: {e}"
            )
            return {"success": False, "error": str(e)}

    def _get_tool_instructions(self, tool_name: str) -> str:
        """
        Retorna as instrues de uso de uma ferramenta (descrio + usage do TOOLS.json).
        Usado quando help=true  chamado em uma tool.

        Args:
            tool_name: Nome da tool

        Returns:
            JSON com instrues da ferramenta
        """
        try:
            from pathlib import Path

            tools_json_path = Path(__file__).parent / "Tools" / "TOOLS.json"

            if not tools_json_path.exists():
                return json.dumps(
                    {"success": False, "error": "TOOLS.json no encontrado"}
                )

            with open(tools_json_path, "r", encoding="utf-8") as f:
                tools_config = json.load(f)

            tool_definitions = tools_config.get("tool_definitions", {})
            if tool_name not in tool_definitions:
                return json.dumps(
                    {"success": False, "error": f"Tool '{tool_name}' no encontrada"}
                )

            tool_info = tool_definitions[tool_name]
            return json.dumps(
                {
                    "success": True,
                    "tool": tool_name,
                    "description": tool_info.get("description", ""),
                    "usage": tool_info.get("usage", ""),
                    "is_inline_tool": tool_info.get("is_inline_tool", False),
                },
                ensure_ascii=False,
            )

        except Exception as e:
            debug(
                f"[_get_tool_instructions] Erro ao obter instrues para '{tool_name}': {e}"
            )
            return json.dumps({"success": False, "error": str(e)})

    def execute_tool(
        self,
        tool_name: str,
        arguments: str,
        agent_id: Optional[str] = None,
        chat_id: Optional[str] = None,
        user_id: Optional[int] = None,
        job_id: Optional[str] = None,
        isolated_message_id: Optional[str] = None,
    ) -> str:
        """
        Executa uma tool (status, chain-of-thought, task, etc).

        Args:
            tool_name: Nome da tool ("status", "chain-of-thought", "task", "web-search", etc)
            arguments: JSON string com argumentos
            agent_id: ID do agent que chamou a tool
            chat_id: ID do chat (para sincronizao de sub-agents)
            user_id: ID do usurio (para sincronizao de sub-agents)
            job_id: ID do job de processamento (para PollingReactor)
            isolated_message_id: ID da mensagem isolada (input do usuário)

        Returns:
            String formatada para retornar  LLM
        """
        try:
            tool_name = tool_name.lower().strip()
            original_tool_name = tool_name
            # Normalizar: converter hfens em underscores para flexibilidade
            tool_name = tool_name.replace("-", "_")
            try:
                args = json.loads(arguments) if arguments else {}
            except json.JSONDecodeError as _initial_parse_err:
                # Tentativa 1: sanitizar newlines/tabs literais gerados pelo LLM
                try:
                    import re as _re_core

                    _sanitized = _re_core.sub(r"(?<!\\)\n", r"\\n", arguments)
                    _sanitized = _re_core.sub(r"(?<!\\)\r", r"\\r", _sanitized)
                    _sanitized = _re_core.sub(r"(?<!\\)\t", r"\\t", _sanitized)
                    args = json.loads(_sanitized)
                except json.JSONDecodeError:
                    # Tentativa 2: json_repair
                    try:
                        from json_repair import repair_json as _repair_json

                        _repaired_str = _repair_json(arguments)
                        args = json.loads(_repaired_str) if _repaired_str else {}
                        args["__json_repaired__"] = True
                    except Exception:
                        raise _initial_parse_err

            # Guardar contexto do chat para salvar arquivos
            self.current_chat_id = chat_id
            self.current_user_id = user_id
            self.current_job_id = job_id
            self.current_isolated_message_id = isolated_message_id

            debug(
                f"[TOOL] Executando {tool_name} com contexto: user_id={user_id}, chat_id={chat_id}, job_id={job_id}, isolated_message_id={isolated_message_id}"
            )
            debug(f"[TOOL] Executando {tool_name} com args: {args}")

            # AUTONOMY GATE — verifica nível de autonomia do trigger antes de executar
            _autonomy_block = self._check_trigger_autonomy_gate(tool_name, args)
            if _autonomy_block is not None:
                return _autonomy_block

            # MCP TOOL DELEGATION
            if original_tool_name.startswith("mcp__"):
                # Gate check: MCP tools devem respeitar o gate da skill ativa
                _mcp_gate = self._evaluate_gate(
                    original_tool_name, args, agent_id=agent_id
                )
                if _mcp_gate is not None:
                    return _mcp_gate

                # Verificar se o provider está habilitado neste chat
                if self.current_chat_id:
                    try:
                        import json as _json_check
                        from App.Core.Crunch.TablesSQL.DBManager import (
                            DatabaseManager as _DBCheck,
                        )

                        _chat_row = _DBCheck().fetch_one(
                            "SELECT connections FROM chats WHERE chat_id = :cid",
                            {"cid": self.current_chat_id},
                        )
                        if _chat_row and _chat_row.get("connections"):
                            _allowed = _json_check.loads(_chat_row["connections"])
                            _parts = original_tool_name.split("__")
                            _provider = _parts[1] if len(_parts) >= 2 else ""
                            if _provider and _provider not in _allowed:
                                return f"Integração '{_provider}' não está ativa neste chat."
                    except Exception as _conn_err:
                        debug(f"[TOOL] Erro ao verificar connections: {_conn_err}")

                debug(f"[TOOL] Delegando execução para MCP: {original_tool_name}")
                try:
                    _mcp_client_id = self._get_client_id_from_user(self.current_user_id)
                    try:
                        loop = asyncio.get_running_loop()
                        import nest_asyncio

                        nest_asyncio.apply()
                        mcp_result = loop.run_until_complete(
                            mcp_manager.call_tool(
                                _mcp_client_id,
                                original_tool_name,
                                args,
                                chat_id=self.current_chat_id or "",
                                user_id=str(self.current_user_id or ""),
                            )
                        )
                    except RuntimeError:
                        mcp_result = asyncio.run(
                            mcp_manager.call_tool(
                                _mcp_client_id,
                                original_tool_name,
                                args,
                                chat_id=self.current_chat_id or "",
                                user_id=str(self.current_user_id or ""),
                            )
                        )

                    if mcp_result.get("success"):
                        return mcp_result.get("content", "Sucesso (sem conteúdo)")
                    else:
                        _err_msg = mcp_result.get("error", "")
                        _mark_token_invalid_if_auth_error(
                            _err_msg,
                            original_tool_name,
                            _mcp_client_id,
                            self.db_manager,
                        )
                        return f"Erro ao executar ferramenta MCP: {_err_msg}"
                except Exception as mcp_exec_err:
                    error(f"[TOOL] Erro na delegacao MCP: {mcp_exec_err}")
                    _mark_token_invalid_if_auth_error(
                        str(mcp_exec_err),
                        original_tool_name,
                        _mcp_client_id,
                        self.db_manager,
                    )
                    return f"Erro crítico na integração MCP: {str(mcp_exec_err)}"

            # Verificar se est solicitando contexto (histrico) de execues anteriores
            if args.get("context") == True and tool_name in [
                "web_search",
                "gen_img",
                "gen_film",
                "vision",
                "document",
            ]:
                return self._get_tool_execution_history(tool_name, chat_id)

            # GATES SEQUENCIAIS L0-L2 COMENTADOS:
            # Removida exigência de canvas→brand→product em sequência.
            # Cada skill/flow exige apenas os documentos que realmente precisa.
            # O CopyDoc Gate (em _validate_copywriting_document) garante os prereqs corretos.

            # ── Gate: bloquear lookup redundante da SkillCopywriting durante ciclo ativo ──
            # Verifica via DB para ser resiliente a múltiplas instâncias de Core.
            if tool_name == "lookup" and agent_id != "debug-agent":
                _file_arg = str(args.get("file", "") or args.get("files", "")).lower()
                if "skillcopywriting" in _file_arg or "skill_copywriting" in _file_arg:
                    if (
                        self._check_copywriting_lookup_in_chat()
                        and self._check_variation_quiz_answered_in_chat()
                    ):
                        _pending_db = self._get_pending_copywriting_document_from_db()
                        if _pending_db:
                            return json.dumps(
                                {
                                    "success": False,
                                    "error": f"SkillCopywriting.md já está ativa. O documento '{_pending_db}' foi salvo e aguarda geração de assets. Não recarregue a skill — execute imediatamente: asset(document_id='{_pending_db}')",
                                    "correction_required": [
                                        {
                                            "step": 1,
                                            "call": {
                                                "tool": "asset",
                                                "document_id": _pending_db,
                                            },
                                        }
                                    ],
                                },
                                ensure_ascii=False,
                            )
                        elif self._check_variation_quiz_answered_in_chat():
                            return json.dumps(
                                {
                                    "success": False,
                                    "error": "SkillCopywriting.md já está ativa e o ciclo de criação está em andamento. Não recarregue a skill — prossiga com o próximo passo do fluxo (document → asset).",
                                    "correction_required": [
                                        {"step": 1, "call": {"tool": "document"}}
                                    ],
                                },
                                ensure_ascii=False,
                            )
            # ─────────────────────────────────────────────────────────────────────────────

            _ALWAYS_ALLOWED = {
                "message",
                "chain_of_thought",
                "tools",
                "lookup",
                "context",
                "calendar",
            }
            # L0 COMENTADO: sem canvas → bloqueia tudo
            # L1 COMENTADO: sem brand → bloqueia tudo
            # L2 COMENTADO: sem product → bloqueia tudo

            _is_brand_analysis_chat = bool(
                self.current_chat_id
                and str(self.current_chat_id).startswith("brand_analysis_")
            )
            if (
                tool_name not in _ALWAYS_ALLOWED
                and agent_id != "debug-agent"
                and not _is_brand_analysis_chat
            ):
                if (
                    tool_name != "quiz"
                    and tool_name != "user_browser"
                    and self._check_tool_help_in_chat("user_browser")
                    and not self._check_browser_auth_quiz_sim()
                ):
                    return json.dumps(
                        {
                            "success": False,
                            "error": "help(user_browser) foi carregado. Apresente o planejamento e execute o quiz com is_user_browser_auth=True e options=['Sim', 'Não'] antes de usar qualquer outra ferramenta.",
                            "correction_required": [
                                {
                                    "step": 1,
                                    "call": {
                                        "tool": "quiz",
                                        "is_user_browser_auth": True,
                                        "plan": "<liste as ações que serão executadas>",
                                    },
                                }
                            ],
                        },
                        ensure_ascii=False,
                    )

                # ── Gate user_browser: exige help(name="user_browser") + quiz ────
                if tool_name == "user_browser":
                    if not self._check_tool_help_in_chat("user_browser"):
                        return json.dumps(
                            {
                                "success": False,
                                "error": "A ferramenta user_browser exige help(name='user_browser') antes de usar.",
                                "correction_required": [
                                    {
                                        "step": 1,
                                        "call": {
                                            "tool": "help",
                                            "name": "user_browser",
                                        },
                                    }
                                ],
                            },
                            ensure_ascii=False,
                        )
                    if not self._check_browser_auth_quiz_sim():
                        return json.dumps(
                            {
                                "success": False,
                                "error": "user_browser bloqueado: execute o quiz com is_user_browser_auth=True, options=['Sim', 'Não'] e campo plan antes de controlar o browser.",
                                "correction_required": [
                                    {
                                        "step": 1,
                                        "call": {
                                            "tool": "quiz",
                                            "is_user_browser_auth": True,
                                            "plan": "<liste as ações que serão executadas>",
                                        },
                                    }
                                ],
                            },
                            ensure_ascii=False,
                        )

                # ── Gate terminal: exige help(name="terminal") ───────────────────
                if tool_name == "terminal":
                    if not self._check_tool_help_in_chat("terminal"):
                        return json.dumps(
                            {
                                "success": False,
                                "error": "A ferramenta terminal exige help(name='terminal') antes de usar.",
                                "correction_required": [
                                    {
                                        "step": 1,
                                        "call": {"tool": "help", "name": "terminal"},
                                    }
                                ],
                            },
                            ensure_ascii=False,
                        )

            # ── Gate engine JSON (skills com GATES/*.json) ───────────────────
            # GATES DE SKILLS DESATIVADOS TEMPORARIAMENTE
            _skip_skill_gates = True
            # Avaliado antes dos gates hardcoded de copywriting.
            # Retorna erro se a skill JSON está ativa e o tool não é permitido no step atual.
            _json_gate_result = self._evaluate_gate(tool_name, args, agent_id=agent_id)
            if _json_gate_result is not None and not _skip_skill_gates:
                return _json_gate_result
            # ──────────────────────────────────────────────────────────────────

            # GATE SEQUENCIAL COPYWRITING: após lookup SkillCopywriting, a única sequência permitida é:
            #   quiz → vision (attachment) OU web-search (URL)
            #       → [URL: quiz image_selection → vision]
            #       → document copywriting → asset
            # Antes do quiz inicial, apenas tools utilitárias são liberadas.
            # Quando SkillCopywriting.json existe, o gate JSON (acima) substitui este hardcoded.
            _copy_json_active = any(
                c.get("lookup_file") == "SkillCopywriting.md"
                for c in self._gate_all_configs()
            )
            _COPY_GATE_EXEMPT = {
                "message",
                "chain_of_thought",
                "quiz",
                "asset",
                "update",
                "delete",
                "cancel",
                "task",
                "schedule",
                "client",
            }
            if (
                not _skip_skill_gates
                and tool_name not in _COPY_GATE_EXEMPT
                and agent_id != "debug-agent"
                and not _copy_json_active
            ):
                # Se SkillCompetitorAnalysis está ativa, este gate não se aplica
                _competitor_active = self._check_competitor_analysis_lookup_in_chat()
                if not _competitor_active and self._check_copywriting_lookup_in_chat():
                    _quiz_done = self._check_variation_quiz_answered_in_chat()
                    if not _quiz_done:
                        return json.dumps(
                            {
                                "success": False,
                                "error": "Após o lookup de SkillCopywriting.md, o primeiro passo obrigatório é o quiz de variação (5 perguntas juntas: imagem de referência, formato, categoria, quantidade, estilo).",
                                "tool": original_tool_name,
                                "correction_required": [
                                    {"step": 1, "call": {"tool": "quiz"}}
                                ],
                            },
                            ensure_ascii=False,
                        )

            # GATE DE FLUXO DE VARIAÇÃO: em cada etapa, só o próximo passo obrigatório é permitido
            # Whitelist: tools sempre liberadas independente do estado
            _VARIATION_WHITELIST = {
                "message",
                "chain_of_thought",
                "cancel",
                "task",
                "schedule",
                "client",
            }
            if (
                not _skip_skill_gates
                and tool_name not in _VARIATION_WHITELIST
                and agent_id != "debug-agent"
                and not _copy_json_active
            ):
                _in_variation = self._check_variation_quiz_answered_in_chat()
                # Desativar gate se o último ciclo foi completado (asset executado) e
                # nenhum novo quiz de variação foi iniciado desde então
                if _in_variation and self.db_manager and self.current_chat_id:
                    try:
                        from App.Core.Crunch.TablesSQL.Models import (
                            IsolatedMessage as _IMcyc,
                        )

                        _scyc = self.db_manager.get_session()
                        try:
                            _last_asset_cyc = (
                                _scyc.query(_IMcyc)
                                .filter(
                                    _IMcyc.isolated_chat_id == self.current_chat_id,
                                    _IMcyc.tool_called == "asset",
                                    _IMcyc.tool_call_type == "output",
                                )
                                .order_by(_IMcyc.id.desc())
                                .first()
                            )
                            if _last_asset_cyc:
                                _new_var_quiz = (
                                    _scyc.query(_IMcyc)
                                    .filter(
                                        _IMcyc.isolated_chat_id == self.current_chat_id,
                                        _IMcyc.tool_called == "quiz",
                                        _IMcyc.tool_call_type == "output",
                                        _IMcyc.id > _last_asset_cyc.id,
                                    )
                                    .first()
                                )
                                if not _new_var_quiz:
                                    _in_variation = False
                        finally:
                            _scyc.close()
                    except Exception:
                        pass
                if _in_variation:
                    try:
                        from App.Core.Crunch.TablesSQL.Models import (
                            IsolatedMessage as _IMgf,
                        )

                        _sgf = (
                            self.db_manager.get_session() if self.db_manager else None
                        )
                        if _sgf:
                            try:
                                _has_fetch_gf = (
                                    _sgf.query(_IMgf)
                                    .filter(
                                        _IMgf.isolated_chat_id == self.current_chat_id,
                                        _IMgf.tool_called.in_(
                                            ["web-search", "web_search"]
                                        ),
                                        _IMgf.tool_call_type == "output",
                                        _IMgf.content.ilike('%"type": "fetch"%'),
                                    )
                                    .first()
                                )
                                _has_visual_gf = (
                                    _sgf.query(_IMgf)
                                    .filter(
                                        _IMgf.isolated_chat_id == self.current_chat_id,
                                        _IMgf.tool_called.in_(
                                            ["web-search", "web_search"]
                                        ),
                                        _IMgf.tool_call_type == "output",
                                        _IMgf.content.ilike(
                                            '%"type": "visual-analysis"%'
                                        ),
                                    )
                                    .first()
                                )
                                # Quando fetch+visual-analysis são chamados juntos,
                                # o output só retorna "type": "visual-analysis".
                                # Considera fetch como feito SE: há output visual-analysis E
                                # o input correspondente continha também "fetch".
                                if _has_visual_gf and not _has_fetch_gf:
                                    _visual_input = (
                                        _sgf.query(_IMgf)
                                        .filter(
                                            _IMgf.isolated_chat_id
                                            == self.current_chat_id,
                                            _IMgf.tool_called.in_(
                                                ["web-search", "web_search"]
                                            ),
                                            _IMgf.tool_call_type == "input",
                                            _IMgf.id < _has_visual_gf.id,
                                            _IMgf.content.ilike('%"fetch"%'),
                                            _IMgf.content.ilike('%"visual-analysis"%'),
                                        )
                                        .order_by(_IMgf.id.desc())
                                        .first()
                                    )
                                    if _visual_input:
                                        _has_fetch_gf = _visual_input

                                # Fluxo de attachment: vision bem-sucedido substitui fetch+visual-analysis.
                                # image_selection também é desnecessário (imagem já foi enviada).
                                _is_attachment_flow = False
                                _attach_quiz = None
                                _quiz_answer_is_attachment = False
                                if not (_has_fetch_gf and _has_visual_gf):
                                    _attach_quiz = (
                                        _sgf.query(_IMgf)
                                        .filter(
                                            _IMgf.isolated_chat_id
                                            == self.current_chat_id,
                                            _IMgf.tool_called == "quiz",
                                            _IMgf.tool_call_type == "input",
                                            _IMgf.content.ilike('%"attachment": true%'),
                                        )
                                        .order_by(_IMgf.id.asc())
                                        .first()
                                    )
                                    if not _attach_quiz:
                                        _attach_quiz = (
                                            _sgf.query(_IMgf)
                                            .filter(
                                                _IMgf.isolated_chat_id
                                                == self.current_chat_id,
                                                _IMgf.tool_called == "quiz",
                                                _IMgf.tool_call_type == "input",
                                                _IMgf.content.ilike(
                                                    '%"attachment":true%'
                                                ),
                                            )
                                            .order_by(_IMgf.id.asc())
                                            .first()
                                        )
                                    if _attach_quiz:
                                        _vision_after_attach = (
                                            _sgf.query(_IMgf)
                                            .filter(
                                                _IMgf.isolated_chat_id
                                                == self.current_chat_id,
                                                _IMgf.tool_called == "vision",
                                                _IMgf.tool_call_type == "output",
                                                _IMgf.id > _attach_quiz.id,
                                            )
                                            .first()
                                        )
                                        if _vision_after_attach:
                                            _is_attachment_flow = True
                                            _has_fetch_gf = _vision_after_attach
                                            _has_visual_gf = _vision_after_attach

                                # Verificar se a RESPOSTA do quiz de variação foi um attach_id real.
                                # O quiz sempre tem attachment:true, mas o usuário pode digitar URL.
                                # Discriminador: output do quiz contém "attach_" → upload real.
                                _no_reference_flow = False
                                if _attach_quiz and not _is_attachment_flow:
                                    _var_quiz_out = (
                                        _sgf.query(_IMgf)
                                        .filter(
                                            _IMgf.isolated_chat_id
                                            == self.current_chat_id,
                                            _IMgf.tool_called == "quiz",
                                            _IMgf.tool_call_type == "output",
                                            _IMgf.id > _attach_quiz.id,
                                            ~_IMgf.content.ilike('%"success": false%'),
                                        )
                                        .first()
                                    )
                                    if (
                                        _var_quiz_out
                                        and '"attach_' in _var_quiz_out.content
                                    ):
                                        _quiz_answer_is_attachment = True
                                    elif _var_quiz_out:
                                        # Q1=Nenhum → sem imagem de referência, bypass das etapas de análise
                                        try:
                                            import json as _jgf

                                            _qd_gf = _jgf.loads(_var_quiz_out.content)
                                            _fa_gf = _qd_gf.get("final_answers", [])
                                            if _fa_gf and isinstance(_fa_gf[0], dict):
                                                _ans0 = (
                                                    str(_fa_gf[0].get("answer", ""))
                                                    .strip()
                                                    .lower()
                                                )
                                                if _ans0 in ("nenhum", "none", ""):
                                                    _no_reference_flow = True
                                        except Exception:
                                            pass

                                _ir_input_gf = (
                                    _sgf.query(_IMgf)
                                    .filter(
                                        _IMgf.isolated_chat_id == self.current_chat_id,
                                        _IMgf.tool_called == "quiz",
                                        _IMgf.tool_call_type == "input",
                                        _IMgf.content.ilike("%image_selection%"),
                                    )
                                    .order_by(_IMgf.id.desc())
                                    .first()
                                )
                                # Attachment: image_selection não é necessário (imagem já confirmada via vision)
                                _ir_answered_gf = _is_attachment_flow
                                if not _ir_answered_gf and _ir_input_gf:
                                    _ir_out_gf = (
                                        _sgf.query(_IMgf)
                                        .filter(
                                            _IMgf.isolated_chat_id
                                            == self.current_chat_id,
                                            _IMgf.tool_called == "quiz",
                                            _IMgf.tool_call_type == "output",
                                            _IMgf.id > _ir_input_gf.id,
                                            ~_IMgf.content.ilike('%"success": false%'),
                                        )
                                        .first()
                                    )
                                    _ir_answered_gf = _ir_out_gf is not None

                                # URL flow: vision obrigatório após image_selection, antes do document
                                _vision_post_confirmation = None
                                if (
                                    _ir_answered_gf
                                    and not _is_attachment_flow
                                    and _ir_input_gf
                                ):
                                    _vision_post_confirmation = (
                                        _sgf.query(_IMgf)
                                        .filter(
                                            _IMgf.isolated_chat_id
                                            == self.current_chat_id,
                                            _IMgf.tool_called == "vision",
                                            _IMgf.tool_call_type == "output",
                                            _IMgf.id > _ir_input_gf.id,
                                        )
                                        .first()
                                    )
                            finally:
                                _sgf.close()

                            # Etapa 1: vision (attachment) ou web-search (URL) — apenas UM é permitido
                            if not _no_reference_flow and not (
                                _has_fetch_gf and _has_visual_gf
                            ):
                                if (
                                    _quiz_answer_is_attachment
                                    and not _is_attachment_flow
                                ):
                                    # Attachment real (upload): resposta do quiz contém attach_id → só vision
                                    if tool_name not in {"vision"}:
                                        return json.dumps(
                                            {
                                                "success": False,
                                                "error": "Fluxo attachment: execute vision(image_input='<attach_id>') com o attach_id retornado pelo quiz.",
                                                "tool": original_tool_name,
                                                "correction_required": [
                                                    {
                                                        "step": 1,
                                                        "call": {
                                                            "tool": "vision",
                                                            "image_input": "<attach_id>",
                                                        },
                                                    }
                                                ],
                                            },
                                            ensure_ascii=False,
                                        )
                                else:
                                    # URL: só web-search é permitido
                                    if tool_name not in {"web_search"}:
                                        return json.dumps(
                                            {
                                                "success": False,
                                                "error": "Fluxo URL: execute web-search(fetch='<url_produto>', visual-analysis='<url_produto>') antes de continuar.",
                                                "tool": original_tool_name,
                                                "correction_required": [
                                                    {
                                                        "step": 1,
                                                        "call": {
                                                            "tool": "web-search",
                                                            "fetch": "<url_do_produto>",
                                                            "visual-analysis": "<url_do_produto>",
                                                            "wait": True,
                                                        },
                                                    }
                                                ],
                                            },
                                            ensure_ascii=False,
                                        )

                            # Etapa 2: URL flow — quiz image_selection obrigatório
                            elif not _no_reference_flow and not _ir_answered_gf:
                                if tool_name not in {"quiz"}:
                                    return json.dumps(
                                        {
                                            "success": False,
                                            "error": "Após o web-search, execute o quiz de seleção da imagem de referência antes de continuar.",
                                            "tool": original_tool_name,
                                            "hint": "Execute: quiz([{question: 'Extrai algumas imagens do seu produto, qual imagem você prefere usar como referência?', type: 'image_selection', options: ['<url1.jpg>', ...]}])",
                                            "correction_required": [
                                                {
                                                    "step": 1,
                                                    "call": {
                                                        "tool": "quiz",
                                                        "quiz": [
                                                            {
                                                                "question": "Extrai algumas imagens do seu produto, qual imagem você prefere usar como referência?",
                                                                "type": "image_selection",
                                                                "options": [
                                                                    "<url1.jpg>"
                                                                ],
                                                            }
                                                        ],
                                                    },
                                                }
                                            ],
                                        },
                                        ensure_ascii=False,
                                    )

                            # Etapa 3: URL flow — vision na imagem confirmada antes do document
                            elif (
                                not _no_reference_flow
                                and not _is_attachment_flow
                                and not _vision_post_confirmation
                            ):
                                if tool_name not in {"vision"}:
                                    return json.dumps(
                                        {
                                            "success": False,
                                            "error": "Após confirmar a imagem, execute vision(image_input='<url_imagem_selecionada>') para análise antes de criar o documento.",
                                            "tool": original_tool_name,
                                            "correction_required": [
                                                {
                                                    "step": 1,
                                                    "call": {
                                                        "tool": "vision",
                                                        "image_input": "<url_imagem_selecionada>",
                                                    },
                                                }
                                            ],
                                        },
                                        ensure_ascii=False,
                                    )
                            # Etapa 4: sequência completa — document copywriting e asset permitidos
                    except Exception as _gfe:
                        debug(
                            f"[GATE_VARIATION] Erro ao verificar gate de fluxo: {_gfe}"
                        )

            # ── Gate: documento copywriting salvo aguardando asset() ────────
            # Usa DB como fonte de verdade — resiliente a múltiplas instâncias de Core.
            # _pending_document_id em memória serve apenas como cache de escrita rápida.
            _pdid_partial = getattr(self, "_pending_document_partial", False)
            _pdid = getattr(self, "_pending_document_id", None)
            if not _pdid or not _pdid_partial:
                # Fallback: consultar DB para garantir que não perdemos o estado entre instâncias
                _db_pending = self._get_pending_copywriting_document_from_db()
                if _db_pending and not _pdid:
                    _pdid = _db_pending
                    _pdid_partial = False
            if (
                not _skip_skill_gates
                and _pdid
                and tool_name not in ("asset", "message", "chain_of_thought")
            ):
                # Documento parcial: permitir apenas document (para completar variações faltantes)
                if _pdid_partial and tool_name == "document":
                    pass  # deixar passar — agente está completando o documento parcial
                else:
                    if _pdid_partial:
                        return json.dumps(
                            {
                                "success": False,
                                "error": (
                                    f"DOCUMENTO PARCIAL: '{_pdid}' ainda tem variações faltantes. "
                                    f"Complete-o com: document(document_id='{_pdid}', data={{variation_N: {{...}}}})"
                                ),
                                "correction_required": [
                                    {
                                        "step": 1,
                                        "call": {
                                            "tool": "document",
                                            "document_id": _pdid,
                                        },
                                    }
                                ],
                                "hint": "Não chame outra tool antes de completar as variações do documento parcial.",
                            },
                            ensure_ascii=False,
                        )
                    else:
                        return json.dumps(
                            {
                                "success": False,
                                "error": (
                                    f"AÇÃO OBRIGATÓRIA: O documento copywriting '{_pdid}' foi salvo mas os assets ainda não foram gerados. "
                                    f"Execute AGORA: asset(document_id='{_pdid}')"
                                ),
                                "correction_required": [
                                    {
                                        "step": 1,
                                        "call": {"tool": "asset", "document_id": _pdid},
                                    }
                                ],
                                "hint": "Não chame outra tool antes de gerar os assets do documento salvo.",
                            },
                            ensure_ascii=False,
                        )
            # ────────────────────────────────────────────────────────────────

            if tool_name == "message":
                return self._execute_message(args)

            elif tool_name == "generate_temporary_public_url":
                from App.Features.Tools.Tools.GeneratePublicUrl import (
                    execute as _gen_url,
                )

                return _gen_url(args, self.current_chat_id, self.current_user_id)

            elif tool_name == "encode_base64":
                from App.Features.Tools.Tools.EncodeBase64 import execute as _enc_b64

                return _enc_b64(args, self.current_chat_id, self.current_user_id)

            elif tool_name == "write_file":
                from App.Features.Tools.Tools.WriteFile import execute as _write_file

                _client_id = self._get_client_id_from_user(self.current_user_id)
                return _write_file(
                    args, self.current_chat_id, self.current_user_id, _client_id
                )

            elif tool_name == "rag_query":
                return execute_rag_query(args, self.current_user_id or "")

            elif tool_name == "schedule":
                return execute_schedule(args, self.current_user_id or "")

            elif tool_name == "skill":
                return execute_skill(args, self.current_user_id or "")

            elif tool_name == "cancel":
                return self._execute_cancel(args)

            elif tool_name == "escalate":
                return self._execute_escalate(args)

            elif tool_name == "send":
                from App.Features.Tools._send import execute as _send_tool

                return _send_tool(args, chat_id=self.current_chat_id)

            elif tool_name == "telegram_send":
                # Alias legado → delega para send com channel explícito
                from App.Features.Tools._send import execute as _send_tool

                legacy_args = {
                    "channel": {"provider": "telegram"},
                    "message": {"text": args.get("message", "")},
                }
                return _send_tool(legacy_args, chat_id=self.current_chat_id)

            elif tool_name == "lookup":
                return self._execute_lookup(args)

            elif tool_name == "help":
                return self._execute_tool_help(args)

            elif tool_name == "chain_of_thought":
                return self._execute_chain_of_thought(args)

            if tool_name == "task":
                return self._execute_task(args)

            elif tool_name == "steps":
                return self._execute_steps(args)

            # COMENTADO: Tool "agent" para chamar agents especializados
            # elif tool_name == "agent":
            #     return self._execute_agent(args, agent_id, chat_id, client_id)

            elif tool_name == "web_search":
                from App.Core.Cache.RedisCache import cache_get, cache_set, url_hash

                # Não cachear quando há insta (dados sociais mudam com frequência)
                _ws_skip_cache = bool(
                    args.get("insta")
                    or any(
                        s.get("insta")
                        for s in (args.get("searches") or [])
                        if isinstance(s, dict)
                    )
                )
                _ws_key = None
                if not _ws_skip_cache:
                    _ws_norm = {k: v for k, v in args.items() if k != "wait"}
                    _ws_key = f"ws:{url_hash(json.dumps(_ws_norm, sort_keys=True))}"
                    _ws_cached = cache_get(_ws_key)
                    if _ws_cached is not None:
                        return json.dumps(_ws_cached, ensure_ascii=False)
                _ws_result_str = self._execute_web_search(args)
                if _ws_key:
                    try:
                        _ws_parsed = json.loads(_ws_result_str)
                        if _ws_parsed.get("success"):
                            cache_set(_ws_key, _ws_parsed, 86400)  # 24h
                    except Exception:
                        pass
                return _ws_result_str

            elif tool_name == "asset":
                # RESTRIO: Apenas orchestrator-global pode usar asset
                if agent_id != "orchestrator-global":
                    return json.dumps(
                        {
                            "success": False,
                            "error": f"ACESSO NEGADO: Apenas o orchestrator-global pode usar a ferramenta '{tool_name}'.",
                            "tool": tool_name,
                        }
                    )
                # Limpar pendência ao chamar asset
                self._pending_document_id = None
                self._pending_document_partial = False
                return self._execute_asset(args)

            elif tool_name == "vision":
                # RESTRIO: Apenas orchestrator-global pode usar vision
                if agent_id != "orchestrator-global":
                    return json.dumps(
                        {
                            "success": False,
                            "error": f"ACESSO NEGADO: Apenas o orchestrator-global pode usar a ferramenta '{tool_name}'.",
                            "tool": tool_name,
                        }
                    )
                return self._execute_vision(args)

            elif tool_name == "document":
                # RESTRIO: Apenas orchestrator-global pode usar document
                if agent_id != "orchestrator-global":
                    return json.dumps(
                        {
                            "success": False,
                            "error": "ACESSO NEGADO: Apenas o orchestrator-global pode usar a ferramenta 'document'.",
                            "tool": "document",
                        }
                    )
                return self._execute_document(args)

            elif tool_name == "context":
                # RESTRIO: Apenas orchestrator-global pode usar context
                if agent_id != "orchestrator-global":
                    return json.dumps(
                        {
                            "success": False,
                            "error": "ACESSO NEGADO: Apenas o orchestrator-global pode usar a ferramenta 'context'.",
                            "tool": "context",
                        }
                    )
                try:
                    debug(f"[TOOL] Chamando _execute_context com args: {args}")
                    result = self._execute_context(args)
                    debug(f"[TOOL] _execute_context retornou tipo: {type(result)}")
                    if result is None:
                        debug(f"[TOOL] AVISO: _execute_context retornou None!")
                        return json.dumps(
                            {
                                "success": False,
                                "error": "_execute_context retornou None (bug interno)",
                                "tool": "context",
                            },
                            ensure_ascii=False,
                        )
                    debug(
                        f"[TOOL] _execute_context retornou string com {len(result)} chars"
                    )
                    return result
                except Exception as e:
                    error(f"[TOOL] Erro ao chamar _execute_context: {e}")
                    import traceback

                    error(f"[TOOL] Traceback: {traceback.format_exc()}")
                    return json.dumps(
                        {
                            "success": False,
                            "error": f"Erro ao executar context: {str(e)}",
                            "tool": "context",
                        },
                        ensure_ascii=False,
                    )

            elif tool_name == "client":
                # RESTRIO: Apenas orchestrator-global pode usar client
                if agent_id != "orchestrator-global":
                    return json.dumps(
                        {
                            "success": False,
                            "error": "ACESSO NEGADO: Apenas o orchestrator-global pode usar a ferramenta 'client'.",
                            "tool": "client",
                        }
                    )
                return self._execute_client(args)

            elif tool_name == "quiz":
                # RESTRIO: Apenas orchestrator-global pode usar quiz
                if agent_id != "orchestrator-global":
                    return json.dumps(
                        {
                            "success": False,
                            "error": "ACESSO NEGADO: Apenas o orchestrator-global pode usar a ferramenta 'quiz'.",
                            "tool": "quiz",
                        }
                    )
                return self._execute_quiz(args)

            elif tool_name == "schedule":
                # RESTRIO: Apenas orchestrator-global pode usar schedule
                if agent_id != "orchestrator-global":
                    return json.dumps(
                        {
                            "success": False,
                            "error": "ACESSO NEGADO: Apenas o orchestrator-global pode usar a ferramenta 'schedule'.",
                            "tool": "schedule",
                        },
                        ensure_ascii=False,
                    )
                return self._execute_schedule(args)

            elif tool_name == "delete":
                # RESTRIO: Apenas orchestrator-global pode usar delete
                if agent_id != "orchestrator-global":
                    return json.dumps(
                        {
                            "success": False,
                            "error": "ACESSO NEGADO: Apenas o orchestrator-global pode usar a ferramenta 'delete'.",
                            "tool": "delete",
                        },
                        ensure_ascii=False,
                    )
                return self._execute_delete(args)

            elif tool_name == "update":
                return json.dumps(
                    {
                        "success": False,
                        "error": "A ferramenta 'update' no est disponvel.",
                        "tool": "update",
                        "hint": "Para atualizar status de steps use context(type='tasks') para ver os IDs e o sistema marca automaticamente via document() e asset().",
                    },
                    ensure_ascii=False,
                )

            elif tool_name == "brand":
                from App.Features.Tools._brand_tool import execute_brand

                _brand_client_id = self._get_client_id_from_user(self.current_user_id)
                return execute_brand(
                    args, self.current_chat_id, self.current_user_id, _brand_client_id
                )

            elif tool_name == "terminal":
                # ── Gate: help(name="terminal") obrigatório ───────────────────────
                # brand_analysis chats têm acesso direto ao terminal sem gate
                _is_brand_ctx = bool(
                    self.current_chat_id
                    and str(self.current_chat_id).startswith("brand_analysis_")
                )
                if agent_id != "debug-agent" and not _is_brand_ctx:
                    if not self._check_tool_help_in_chat("terminal"):
                        return json.dumps(
                            {
                                "success": False,
                                "error": "A ferramenta terminal exige help(name='terminal') antes de usar.",
                                "correction_required": [
                                    {
                                        "step": 1,
                                        "call": {"tool": "help", "name": "terminal"},
                                    }
                                ],
                            },
                            ensure_ascii=False,
                        )
                return self._execute_terminal(args)

            elif tool_name in ("pdv_menu", "pdv_stock", "pdv_orders", "pdv_settings", "pdv_promotions", "pdv_payments"):
                _pdv_action = (args.get("action") or "").strip()
                _pdv_is_read = _pdv_action.startswith("list") or _pdv_action.startswith("get")
                if not _pdv_is_read:
                    return self._create_tool_approval_pending(tool_name, args)
                _pdv_client_id = self._get_client_id_from_user(self.current_user_id) or ""
                if tool_name == "pdv_menu":
                    from App.Features.Tools.Tools.Pdv import execute_pdv_menu
                    return execute_pdv_menu(args, _pdv_client_id)
                elif tool_name == "pdv_stock":
                    from App.Features.Tools.Tools.Pdv import execute_pdv_stock
                    return execute_pdv_stock(args, _pdv_client_id)
                elif tool_name == "pdv_orders":
                    from App.Features.Tools.Tools.Pdv import execute_pdv_orders
                    return execute_pdv_orders(args, _pdv_client_id)
                elif tool_name == "pdv_settings":
                    from App.Features.Tools.Tools.Pdv import execute_pdv_settings
                    return execute_pdv_settings(args, _pdv_client_id)
                elif tool_name == "pdv_promotions":
                    from App.Features.Tools.Tools.Pdv import execute_pdv_promotions
                    return execute_pdv_promotions(args, _pdv_client_id)
                elif tool_name == "pdv_payments":
                    from App.Features.Tools.Tools.Pdv import execute_pdv_payments
                    return execute_pdv_payments(args, _pdv_client_id)

            elif tool_name in ("md70_projetos", "md70_compras", "md70_crm", "md70_financeiro"):
                _admin_action = (args.get("action") or "").strip()
                _admin_is_read = _admin_action.startswith("list") or _admin_action.startswith("get")
                if not _admin_is_read and not bypass_approval:
                    return self._create_tool_approval_pending(tool_name, args)
                if tool_name == "md70_projetos":
                    from App.Features.Tools.Tools.Admin import execute_md70_projetos
                    _admin_result = execute_md70_projetos(args)
                elif tool_name == "md70_compras":
                    from App.Features.Tools.Tools.Admin import execute_md70_compras
                    _admin_result = execute_md70_compras(args)
                elif tool_name == "md70_crm":
                    from App.Features.Tools.Tools.Admin import execute_md70_crm
                    _admin_result = execute_md70_crm(args)
                else:
                    from App.Features.Tools.Tools.Admin import execute_md70_financeiro
                    _admin_result = execute_md70_financeiro(args)
                return _admin_result

            else:
                # Ferramentas desconhecidas no so aceitas
                return self._get_available_tools_list(original_tool_name)

        except json.JSONDecodeError as _jde:
            _hint = str(_jde)
            return json.dumps(
                {
                    "success": False,
                    "error": "Corrija os campos e valores da tool",
                    "hint": f"JSON invlido: {_hint}. Verifique aspas simples, vrgulas finais e estrutura dos objetos.",
                }
            )
        except Exception as e:
            error(f"[TOOL] Erro ao executar {tool_name}: {e}")
            return json.dumps({"success": False, "error": str(e)})

    def _get_tool_execution_history(
        self, tool_name: str, chat_id: Optional[str]
    ) -> str:
        """
        Retorna histrico de todas as execues anteriores de uma tool especfica.
        Filtra por: type=tool_call, primeiros 50 chars contm "Tool: tool_name" ou "tool": "tool_name"
        Exclui: help=true e context=true
        """
        try:
            if not chat_id or not self.db_manager:
                return json.dumps(
                    {
                        "success": False,
                        "tool": tool_name,
                        "error": "Chat ID ou database manager no disponvel",
                        "executions": [],
                    },
                    ensure_ascii=False,
                )

            if hasattr(self.db_manager, "get_session"):
                session = self.db_manager.get_session()
            else:
                session = self.db_manager()

            try:
                from App.Core.Crunch.TablesSQL.Models import (
                    IsolatedChat,
                    IsolatedMessage,
                )

                # Buscar mensagens diretamente usando chat_id (UUID STRING)
                messages = (
                    session.query(IsolatedMessage)
                    .filter(
                        IsolatedMessage.isolated_chat_id == chat_id,
                        IsolatedMessage.type == "tool_call",
                    )
                    .order_by(IsolatedMessage.created_at)
                    .all()
                )

                # Step 1: Find all INPUT UUIDs for this tool (role=assistant, matching tool name pattern)
                # Pattern: "Tool: web-search\nArgs: {...}" - starts with exact pattern
                input_uuids = set()
                for msg in messages:
                    if msg.role != "assistant":
                        continue

                    # Check if message starts with "Tool: {tool_name}\n"
                    expected_start = f"Tool: {tool_name}\n"
                    if not msg.content.startswith(expected_start):
                        continue

                    # Exclude help and context calls
                    if (
                        "help=true" in msg.content
                        or "context=true" in msg.content
                        or "context=True" in msg.content
                    ):
                        continue

                    input_uuids.add(msg.uuid)

                # Step 2: For each input UUID, build execution record with INPUT and OUTPUT
                executions = {}
                uuid_counts = {}

                for uuid in input_uuids:
                    executions[uuid] = {
                        "uuid": uuid,
                        "tool": tool_name,
                        "input": None,
                        "output": None,
                        "status": "processing",
                    }
                    uuid_counts[uuid] = 0

                # Step 3: Find all messages with these UUIDs (both INPUT and OUTPUT)
                for msg in messages:
                    if msg.uuid not in input_uuids:
                        continue

                    uuid_counts[msg.uuid] += 1

                    # INPUT = role assistant
                    if msg.role == "assistant":
                        input_text = msg.content
                        # Remove "Status:  Processando..." e "ToolCallId:..."
                        if "\nStatus: " in input_text:
                            input_text = input_text.split("\nStatus: ")[0]
                        if "\nToolCallId:" in input_text:
                            input_text = input_text.split("\nToolCallId:")[0]
                        executions[msg.uuid]["input"] = input_text

                    # OUTPUT = role user
                    elif msg.role == "user":
                        executions[msg.uuid]["output"] = msg.content
                        # Extract status from output
                        if (
                            '"success": true' in msg.content
                            or '"success":true' in msg.content
                        ):
                            executions[msg.uuid]["status"] = "success"
                        elif (
                            '"success": false' in msg.content
                            or '"success":false' in msg.content
                        ):
                            executions[msg.uuid]["status"] = "error"

                # Step 4: Set final status based on UUID count
                for uuid, count in uuid_counts.items():
                    if uuid in executions:
                        if count == 1:
                            # Only INPUT, not finalized yet
                            executions[uuid]["status"] = "processing"
                        elif count >= 2:
                            # INPUT + OUTPUT, finalized
                            # If status wasn't already set to success/error, mark as finalizado
                            if executions[uuid]["status"] == "processing":
                                executions[uuid]["status"] = "finalizado"

                return json.dumps(
                    {
                        "success": True,
                        "tool": tool_name,
                        "total_executions": len(executions),
                        "executions": list(executions.values()),
                    },
                    ensure_ascii=False,
                )

            finally:
                session.close()

        except Exception as e:
            error(f"[TOOL-HISTORY] Erro ao recuperar histrico de {tool_name}: {e}")
            return json.dumps(
                {
                    "success": False,
                    "tool": tool_name,
                    "error": str(e),
                    "executions": [],
                },
                ensure_ascii=False,
            )

    def _execute_graph_design(self, args: Dict[str, Any]) -> str:
        """
        Executa graph_design: create (ack inline), lookup (consulta dados), update (mescla layers).
        Auth: asset e composition sempre verificados contra current_chat_id + current_user_id.
        """
        action = args.get("action", "create")

        # ── CREATE ──────────────────────────────────────────────────────────────
        if action == "create":
            composition_id = args.get("composition_id", "")
            asset_id = args.get("asset_id", "")
            if not composition_id or not asset_id:
                return json.dumps(
                    {
                        "success": False,
                        "error": "graph_design create requer composition_id e asset_id.",
                        "tool": "graph_design",
                    },
                    ensure_ascii=False,
                )
            return json.dumps(
                {
                    "success": True,
                    "action": "create",
                    "composition_id": composition_id,
                    "asset_id": asset_id,
                    "title": args.get("title", "Design"),
                    "aspect_ratio": args.get("aspect_ratio", "1:1"),
                    "composition": args.get("composition", {}),
                    "message": "Composição enviada ao frontend para renderização e persistência.",
                },
                ensure_ascii=False,
            )

        # ── LOOKUP ──────────────────────────────────────────────────────────────
        if action == "lookup":
            resource = args.get("resource", "composition")

            if resource == "fonts":
                try:
                    import json as _json

                    _ds_path = (
                        Path(__file__).parent
                        / "../../../../frontend/src/_shared/core/config/designSystem.json"
                    )
                    _ds = _json.loads(_ds_path.read_text(encoding="utf-8"))
                    fonts = _ds.get("fonts", [])
                except Exception:
                    fonts = []
                return json.dumps(
                    {
                        "success": True,
                        "action": "lookup",
                        "resource": "fonts",
                        "data": {"fonts": fonts},
                    },
                    ensure_ascii=False,
                )

            if resource == "brand":
                client_id = self._get_client_id_from_user(self.current_user_id)
                if not client_id:
                    return json.dumps(
                        {
                            "success": False,
                            "error": "Não foi possível resolver client_id para brand lookup.",
                            "tool": "graph_design",
                        },
                        ensure_ascii=False,
                    )
                try:
                    from App.Core.Crunch.TablesSQL.Models import Brand

                    session = self.db_manager.get_session()
                    try:
                        brand = (
                            session.query(Brand)
                            .filter(Brand.client_id == client_id)
                            .first()
                        )
                        title = brand.title if brand else None
                        data = brand.data if brand else {}
                    finally:
                        session.close()
                    return json.dumps(
                        {
                            "success": True,
                            "action": "lookup",
                            "resource": "brand",
                            "title": title,
                            "data": data or {},
                        },
                        ensure_ascii=False,
                    )
                except Exception as e:
                    return json.dumps(
                        {
                            "success": False,
                            "error": f"Erro ao buscar brand: {e}",
                            "tool": "graph_design",
                        },
                        ensure_ascii=False,
                    )

            if resource == "composition":
                asset_id = args.get("asset_id", "")
                composition_id = (
                    asset_id.rsplit(".", 1)[0] if "." in asset_id else asset_id
                )
                if not composition_id or not self.current_chat_id:
                    return json.dumps(
                        {
                            "success": False,
                            "error": "graph_design lookup composition requer asset_id.",
                            "tool": "graph_design",
                        },
                        ensure_ascii=False,
                    )
                try:
                    from App.Core.Crunch.TablesSQL.Models import CreativeComposition
                    from sqlalchemy import text as _t

                    session = self.db_manager.get_session()
                    try:
                        # Verify chat ownership before returning composition data
                        owner_check = session.execute(
                            _t(
                                "SELECT 1 FROM chats WHERE chat_id = :c AND user_id = :u"
                            ),
                            {"c": self.current_chat_id, "u": self.current_user_id},
                        ).first()
                        if not owner_check:
                            return json.dumps(
                                {
                                    "success": False,
                                    "error": "Acesso negado: chat não pertence ao usuário.",
                                    "tool": "graph_design",
                                },
                                ensure_ascii=False,
                            )
                        creative = (
                            session.query(CreativeComposition)
                            .filter(
                                CreativeComposition.composition_id == composition_id,
                                CreativeComposition.chat_id == self.current_chat_id,
                            )
                            .first()
                        )
                    finally:
                        session.close()
                    if not creative:
                        return json.dumps(
                            {
                                "success": False,
                                "error": f"Composição '{composition_id}' não encontrada neste chat.",
                                "tool": "graph_design",
                            },
                            ensure_ascii=False,
                        )
                    return json.dumps(
                        {
                            "success": True,
                            "action": "lookup",
                            "resource": "composition",
                            "data": {
                                "composition_id": creative.composition_id,
                                "title": creative.title,
                                "version": creative.version,
                                "state": creative.state,
                            },
                        },
                        ensure_ascii=False,
                    )
                except Exception as e:
                    return json.dumps(
                        {
                            "success": False,
                            "error": f"Erro ao buscar composição: {e}",
                            "tool": "graph_design",
                        },
                        ensure_ascii=False,
                    )

            return json.dumps(
                {
                    "success": False,
                    "error": f"resource inválido: '{resource}'. Use composition, fonts ou brand.",
                    "tool": "graph_design",
                },
                ensure_ascii=False,
            )

        # ── UPDATE ──────────────────────────────────────────────────────────────
        if action == "update":
            asset_id = args.get("asset_id", "")
            layers_update = args.get("layers", {})
            composition_id = asset_id.rsplit(".", 1)[0] if "." in asset_id else asset_id
            if not composition_id or not layers_update:
                return json.dumps(
                    {
                        "success": False,
                        "error": "graph_design update requer asset_id e layers.",
                        "tool": "graph_design",
                    },
                    ensure_ascii=False,
                )
            try:
                from App.Core.Crunch.TablesSQL.Models import CreativeComposition
                from sqlalchemy import text as _t

                session = self.db_manager.get_session()
                try:
                    owner_check = session.execute(
                        _t("SELECT 1 FROM chats WHERE chat_id = :c AND user_id = :u"),
                        {"c": self.current_chat_id, "u": self.current_user_id},
                    ).first()
                    if not owner_check:
                        return json.dumps(
                            {
                                "success": False,
                                "error": "Acesso negado: chat não pertence ao usuário.",
                                "tool": "graph_design",
                            },
                            ensure_ascii=False,
                        )
                    creative = (
                        session.query(CreativeComposition)
                        .filter(
                            CreativeComposition.composition_id == composition_id,
                            CreativeComposition.chat_id == self.current_chat_id,
                        )
                        .first()
                    )
                    if not creative:
                        session.close()
                        return json.dumps(
                            {
                                "success": False,
                                "error": f"Composição '{composition_id}' não encontrada.",
                                "tool": "graph_design",
                            },
                            ensure_ascii=False,
                        )
                    # Merge layers by ID
                    state = creative.state or {}
                    existing_layers = state.get("layers", {})
                    existing_layers.update(layers_update)
                    state["layers"] = existing_layers
                    creative.state = state
                    creative.version = (creative.version or 1) + 1
                    session.commit()
                    updated_ids = list(layers_update.keys())
                finally:
                    session.close()
                return json.dumps(
                    {
                        "success": True,
                        "action": "update",
                        "composition_id": composition_id,
                        "updated_layer_ids": updated_ids,
                        "new_version": creative.version,
                        "message": f"{len(updated_ids)} layer(s) atualizado(s). Usuário verá as mudanças ao abrir o editor.",
                    },
                    ensure_ascii=False,
                )
            except Exception as e:
                return json.dumps(
                    {
                        "success": False,
                        "error": f"Erro ao atualizar composição: {e}",
                        "tool": "graph_design",
                    },
                    ensure_ascii=False,
                )

        return json.dumps(
            {
                "success": False,
                "error": f"action inválida: '{action}'. Use create, lookup ou update.",
                "tool": "graph_design",
            },
            ensure_ascii=False,
        )

    def _get_available_tools_list(self, tool_name_requested: str) -> str:
        """
        Retorna lista de todas as tools disponveis carregadas de TOOLS.json quando tool inexistente for chamada.

        Args:
            tool_name_requested: Nome da tool que foi solicitada e no existe

        Returns:
            JSON com erro + lista completa de tools disponveis carregada de TOOLS.json
        """
        try:
            # Carregar TOOLS.json
            import os

            tools_json_path = os.path.join(
                os.path.dirname(__file__), "Tools", "TOOLS.json"
            )

            if not os.path.exists(tools_json_path):
                return json.dumps(
                    {
                        "success": False,
                        "error": f"Tool '{tool_name_requested}' no existe",
                        "message": "Arquivo TOOLS.json no encontrado para listar tools disponveis",
                    },
                    ensure_ascii=False,
                )

            with open(tools_json_path, "r", encoding="utf-8") as f:
                tools_config = json.load(f)

            # Extrair tool_definitions
            tool_definitions = tools_config.get("tool_definitions", {})

            # Formatar resposta com ferramentas disponveis
            tools_list = {}
            for tool_name, tool_info in tool_definitions.items():
                tools_list[tool_name] = {
                    "description": tool_info.get("description", "Sem descrio"),
                    "usage": tool_info.get("usage", ""),
                }

            return json.dumps(
                {
                    "success": False,
                    "error": f"Tool '{tool_name_requested}' no existe",
                    "available_tools": len(tools_list),
                    "tools": tools_list,
                    "hint": "Use uma das tools acima. Adapte hfens para underscores em chamadas (ex: chain-of-thought  chain_of_thought)",
                },
                ensure_ascii=False,
            )

        except Exception as e:
            error(f"[TOOLS] Erro ao carregar TOOLS.json: {e}")
            return json.dumps(
                {
                    "success": False,
                    "error": f"Tool '{tool_name_requested}' no existe",
                    "message": f"Erro ao listar tools disponveis: {str(e)}",
                },
                ensure_ascii=False,
            )

    def _execute_message(self, args: Dict[str, Any]) -> str:
        """
        Executa tool message (comunicao com usurio).
        Retorna apenas o valor da mensagem quando bem-sucedida.
        Use para falar COM o usurio (saudao, feedback, resultados), no para raciocnio.
        """
        message = args.get("message", "")
        if not message:
            return json.dumps({"success": False, "error": "message obrigatrio"})

        debug(f"[MESSAGE] {message}")
        self.message_used = True
        return message

    def _execute_cancel(self, args: Dict[str, Any]) -> str:
        """
        Lógica para tool cancel() - Quebra os gates de fluxo atuais.
        Persiste uma mensagem de sistema para invalidar os validadores de gate.
        """
        should_cancel = args.get("cancel", False)
        reason = args.get("reason", "Usuário solicitou cancelamento")
        escalate = args.get("escalate_to_human", False)
        escalation_reason = args.get(
            "reason", "Agente não conseguiu completar a tarefa"
        )

        if escalate:
            # Marcar execução como 'escalated' nas tabelas de trigger/scheduled
            if self.current_chat_id:
                try:
                    from App.Core.Crunch.TablesSQL.DBManager import (
                        DatabaseManager as _DBM,
                    )

                    _db = _DBM()
                    _db.execute_query(
                        "UPDATE trigger_executions SET status='escalated', result_summary=:summary, finished_at=:now WHERE chat_id=:cid",
                        {
                            "summary": f"Escalado: {escalation_reason}",
                            "now": datetime.now().isoformat(),
                            "cid": self.current_chat_id,
                        },
                    )
                    _db.execute_query(
                        "UPDATE task_executions SET status='escalated', result_summary=:summary, finished_at=:now WHERE chat_id=:cid",
                        {
                            "summary": f"Escalado: {escalation_reason}",
                            "now": datetime.now().isoformat(),
                            "cid": self.current_chat_id,
                        },
                    )
                except Exception as e:
                    error(f"[ESCALATE] Erro ao atualizar status: {e}")
            return json.dumps(
                {
                    "success": True,
                    "escalated": True,
                    "reason": escalation_reason,
                    "message": "Tarefa escalada para revisão humana. O painel irá notificar a equipe.",
                },
                ensure_ascii=False,
            )

        if not should_cancel:
            return json.dumps(
                {
                    "success": False,
                    "error": "Parâmetro 'cancel' deve ser true para efetivar a ação.",
                },
                ensure_ascii=False,
            )

        debug(f"[CANCEL] Fluxo cancelado. Motivo: {reason}")

        # Persistir mensagem de cancelamento no banco de dados para invalidar gates
        if self.db_manager and self.current_chat_id:
            try:
                from App.Core.Crunch.TablesSQL.Models import IsolatedMessage

                session = self.db_manager.get_session()
                try:
                    import uuid

                    new_msg = IsolatedMessage(
                        isolated_chat_id=self.current_chat_id,  # Usar o UUID diretamente
                        isolated_message_id=str(uuid.uuid4()),
                        role="system",
                        content=f"[FLOW_CANCELLED] Motivo: {reason}",
                        agent_id="system",
                        agent="System",
                        created_at=datetime.now(),
                    )
                    session.add(new_msg)
                    session.commit()
                    debug(
                        f"[CANCEL] Mensagem de sistema [FLOW_CANCELLED] salva no chat {self.current_chat_id}"
                    )
                finally:
                    session.close()
            except Exception as e:
                error(f"[CANCEL] Erro ao salvar mensagem de cancelamento: {e}")

        return json.dumps(
            {
                "success": True,
                "cancelled": True,
                "reason": reason,
                "message": "Fluxo cancelado. PARE imediatamente — não execute mais ferramentas deste fluxo nem continue o quiz/document/asset. Responda ao usuário diretamente sobre o que ele pediu e aguarde novas instruções.",
            },
            ensure_ascii=False,
        )

    def _execute_escalate(self, args: Dict[str, Any]) -> str:
        """Escala a conversa para revisão humana, opcionalmente enviando mensagem ao usuário."""
        reason = args.get("reason", "Conversa escalada para atendimento humano.")
        user_message = args.get("user_message", "")

        # Atualizar status para pending_review (exibido no painel com botões aprovar/rejeitar)
        if self.current_chat_id:
            try:
                from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager as _DBM

                _db = _DBM()
                _db.execute_query(
                    "UPDATE trigger_executions SET status='pending_review', result_summary=:summary, finished_at=:now WHERE chat_id=:cid",
                    {
                        "summary": f"Escalado para humano: {reason}",
                        "now": datetime.now().isoformat(),
                        "cid": self.current_chat_id,
                    },
                )
            except Exception as e:
                error(f"[ESCALATE] Erro ao atualizar status: {e}")

            # Enviar mensagem ao usuário externo se fornecida
            if user_message:
                try:
                    from App.Features.Tools._send import execute as _send_tool

                    _send_tool({"message": user_message}, chat_id=self.current_chat_id)
                except Exception as e:
                    error(f"[ESCALATE] Erro ao enviar mensagem ao usuário: {e}")

        return json.dumps(
            {
                "success": True,
                "escalated": True,
                "reason": reason,
                "message": "Conversa marcada para atendimento humano. PARE — não envie mais mensagens automáticas nesta conversa.",
            },
            ensure_ascii=False,
        )

    def _execute_lookup(self, args: Dict[str, Any]) -> str:
        """
        Executa tool lookup (consultar documentao de apoio).
        Aceita file="X.md" (single) ou files=["X.md","Y.md"] (mltiplos).
        Retorna contedo de arquivos da pasta .Agent.

        Segurana: Valida que o arquivo est dentro da pasta .Agent (bloqueia path traversal).
        """
        import os

        # Suporte a files (array) e file (string)
        files_arg = args.get("files")
        file_arg = args.get("file", "").strip()

        if files_arg and isinstance(files_arg, list):
            file_names = [
                f.strip() for f in files_arg if isinstance(f, str) and f.strip()
            ]
        elif file_arg:
            file_names = [file_arg]
        else:
            file_names = []

        if not file_names:
            return json.dumps(
                {
                    "success": False,
                    "error": "file ou files obrigatrio",
                    "tool": "lookup",
                },
                ensure_ascii=False,
            )

        if len(file_names) > 1:
            return json.dumps(
                {
                    "success": False,
                    "error": "Lookup de mltiplas skills em uma nica chamada no  permitido. Chame uma skill por vez.",
                    "tool": "lookup",
                    "hint": "Use lookup(file='SkillX.md')  uma chamada por skill.",
                },
                ensure_ascii=False,
            )

        # GATES L0-L2 COMENTADOS: lookup de skills é livre, sem exigir canvas/brand/product previamente.
        # O gate de documentos obrigatórios é aplicado apenas no momento de criar o documento copywriting
        # (ver CopyDoc Gate em _execute_document) e na geração de assets (_execute_asset).

        # 4. Bloquear re-lookup de SkillCopywriting até o documento copywriting ser criado
        if (
            "SkillCopywriting.md" in file_names
            and self.db_manager
            and self.current_chat_id
            and self.current_user_id
        ):
            try:
                from App.Core.Crunch.TablesSQL.Models import (
                    IsolatedMessage as _IMrl,
                    Document as _DocRl,
                )

                _rls = self.db_manager.get_session()
                try:
                    _prev_copy_lookup = (
                        _rls.query(_IMrl)
                        .filter(
                            _IMrl.isolated_chat_id == self.current_chat_id,
                            _IMrl.tool_called == "lookup",
                            _IMrl.tool_call_type == "output",
                            _IMrl.content.ilike("%SkillCopywriting.md%"),
                            ~_IMrl.content.ilike("%blocked_files%"),
                        )
                        .first()
                    )
                    if _prev_copy_lookup:
                        _copy_doc_created = (
                            _rls.query(_DocRl)
                            .filter(
                                _DocRl.chat_id == self.current_chat_id,
                                _DocRl.user_id == self.current_user_id,
                                _DocRl.tool_type == "copywriting",
                            )
                            .first()
                        )
                        if not _copy_doc_created:
                            return json.dumps(
                                {
                                    "success": False,
                                    "error": "Finalize o Copywriting antes de recarregar a skill.",
                                    "tool": "lookup",
                                    "blocked_files": ["SkillCopywriting.md"],
                                    "hint": "SkillCopywriting j foi carregada. Conclua o fluxo com document(type='copywriting', data={...}) antes de recarregar.",
                                },
                                ensure_ascii=False,
                            )
                finally:
                    _rls.close()
            except Exception as _rle:
                debug(f"[LOOKUP] Erro ao verificar re-lookup SkillCopywriting: {_rle}")

        agent_folder = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "Agents", "Agents", ".Agent")
        )
        agent_folder_abs = os.path.abspath(agent_folder)

        def _read_one(fname: str) -> dict:
            # Bloquear path traversal
            if ".." in fname or "/" in fname or "\\" in fname:
                return {
                    "file": fname,
                    "success": False,
                    "error": f"Arquivo '{fname}' no permitido.",
                }
            fp = os.path.normpath(os.path.join(agent_folder_abs, fname))
            if not fp.startswith(agent_folder_abs):
                return {
                    "file": fname,
                    "success": False,
                    "error": "Acesso negado. Arquivo fora da pasta permitida.",
                }
            if not os.path.exists(fp):
                debug(f"[LOOKUP] Arquivo no encontrado: {fp}")
                return {
                    "file": fname,
                    "success": False,
                    "error": f"Arquivo '{fname}' no encontrado",
                }
            if not os.path.isfile(fp):
                return {
                    "file": fname,
                    "success": False,
                    "error": f"'{fname}' no  um arquivo vlido",
                }
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    content = f.read()
                debug(
                    f"[LOOKUP] Arquivo consultado: {fname} ({len(content)} caracteres)"
                )
                return {"file": fname, "success": True, "content": content}
            except Exception as e:
                error(f"[LOOKUP] Erro ao ler arquivo {fname}: {e}")
                return {"file": fname, "success": False, "error": str(e)}

        results_list = [_read_one(fn) for fn in file_names]

        # Single file  manter formato original para compatibilidade
        if len(results_list) == 1:
            r = results_list[0]
            if r["success"]:
                return json.dumps(
                    {
                        "success": True,
                        "tool": "lookup",
                        "file": r["file"],
                        "content": r["content"],
                    },
                    ensure_ascii=False,
                )
            else:
                return json.dumps(
                    {"success": False, "tool": "lookup", "error": r["error"]},
                    ensure_ascii=False,
                )

        # Multiple files  retornar array JSON
        all_ok = all(r["success"] for r in results_list)
        return json.dumps(
            {"success": all_ok, "tool": "lookup", "files": results_list},
            ensure_ascii=False,
        )

    def _execute_tool_help(self, args: Dict[str, Any]) -> str:
        """Carrega instruções de uma tool a partir de TOOLS.json + Tools/Tool*.md."""
        import os

        tool_name = args.get("name", "").strip()
        if not tool_name:
            return json.dumps(
                {
                    "success": False,
                    "tool": "help",
                    "error": "Parâmetro 'name' obrigatório.",
                },
                ensure_ascii=False,
            )

        tools_dir = TOOLS_DIR
        config_path = tools_dir / TOOLS_CONFIG_FILE

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                tools_config = json.load(f)
        except Exception as e:
            return json.dumps(
                {
                    "success": False,
                    "tool": "help",
                    "error": f"Erro ao ler TOOLS.json: {e}",
                },
                ensure_ascii=False,
            )

        entry = tools_config.get(tool_name)
        if not entry:
            available = list(tools_config.keys())
            return json.dumps(
                {
                    "success": False,
                    "tool": "help",
                    "error": f"Tool '{tool_name}' não encontrada em TOOLS.json.",
                    "available": available,
                },
                ensure_ascii=False,
            )

        instructions_file = entry.get("instructions", "")
        instructions_path = tools_dir / instructions_file

        # Bloquear path traversal
        instructions_path_abs = os.path.abspath(str(instructions_path))
        tools_dir_abs = os.path.abspath(str(tools_dir))
        if not instructions_path_abs.startswith(tools_dir_abs):
            return json.dumps(
                {"success": False, "tool": "help", "error": "Acesso negado."},
                ensure_ascii=False,
            )

        if not instructions_path.exists():
            return json.dumps(
                {
                    "success": False,
                    "tool": "help",
                    "error": f"Arquivo de instruções '{instructions_file}' não encontrado.",
                },
                ensure_ascii=False,
            )

        try:
            content = instructions_path.read_text(encoding="utf-8")
            debug(
                f"[HELP] Instruções carregadas para tool '{tool_name}' ({len(content)} chars)"
            )
            return json.dumps(
                {
                    "success": True,
                    "tool": "help",
                    "name": tool_name,
                    "instructions": content,
                },
                ensure_ascii=False,
            )
        except Exception as e:
            return json.dumps(
                {"success": False, "tool": "help", "error": str(e)},
                ensure_ascii=False,
            )

    def _register_file_in_db(
        self,
        filename: str,
        content: str,
        file_category: str = "document",
        message_id: Optional[str] = None,
        short_description: Optional[str] = None,
    ) -> str:
        """
        Registra arquivo na tabela 'files' do banco de dados.

        Args:
            filename: Nome do arquivo
            content: Contedo do arquivo (para calcular hash e size)
            file_category: 'document', 'asset', 'upload', 'attachment'
            message_id: ID da mensagem (opcional)
            short_description: Descrio curta do arquivo (primeiras 100 chars)

        Returns:
            ID do arquivo (file_id) ou None se falhar
        """
        if not self.db_manager or not self.current_user_id or not self.current_chat_id:
            debug(f"[FILE-DB] Contexto incompleto para registrar arquivo: {filename}")
            return None

        try:
            # Calcular hash e tamanho
            content_bytes = (
                content.encode("utf-8") if isinstance(content, str) else content
            )
            file_hash = hashlib.sha256(content_bytes).hexdigest()
            file_size = len(content_bytes)

            # Determinar tipo de arquivo
            file_type = "text/markdown" if filename.endswith(".md") else "text/plain"

            # Gerar ID nico
            file_id = str(uuid_lib.uuid4())

            # Gerar short_description se no fornecido
            if not short_description:
                short_description = content[:100].replace("\n", " ").strip()
                if len(content) > 100:
                    short_description += "..."

            # Caminho de armazenamento
            storage_path = f"client_{self.current_user_id}/chat_{self.current_chat_id}/documents/{filename}"

            # DEPRECADO: files table foi removida. Esta funo no salva mais nada.
            # Se precisar salvar documentos, use o model Document ao invs.
            debug(
                f"[FILE-DB] register_file_to_db() deprecado - files table removida ({filename})"
            )
            return None

        except Exception as e:
            debug(f"[FILE-DB] Erro ao registrar arquivo: {e}")
            return None

    def _execute_agent(
        self,
        args: Dict[str, Any],
        caller_agent_id: Optional[str],
        chat_id: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> str:
        """Executa tool agent."""
        target_agent_id = args.get("agent_id")
        message = args.get("message")

        if not target_agent_id or not message:
            return json.dumps(
                {"success": False, "error": "agent_id e message obrigatrios"}
            )

        try:
            handler = AgentHandler(
                message_processor=self.message_processor,
                chat_manager=self.chat_manager,
                agents_manager=self.agents_manager,
                db_manager=self.db_manager,
            )

            result = handler.handle_agent_call(
                target_agent_id=target_agent_id,
                message=message,
                caller_agent_id=caller_agent_id,
                chat_id=chat_id,
                user_id=user_id,
            )

            return json.dumps(result)

        except Exception as e:
            error(f"[AGENT_TOOL] Erro ao chamar agent {target_agent_id}: {e}")
            return json.dumps({"success": False, "error": str(e)})

    def _get_tool_help(self, tool_name: str) -> Dict[str, Any]:
        """Carrega documentao de help para uma tool do CONTEXT.json

        Args:
            tool_name: Nome da tool (print, task, context, web-search, document, mediaai, wait)

        Returns:
            Dict com "success", "instructions", "errors" da tool
        """
        try:
            from pathlib import Path

            core_dir = Path(__file__).parent.parent.parent.parent
            context_file = core_dir / "Data" / "Agents" / "CONTEXT.json"

            with open(context_file, "r", encoding="utf-8") as f:
                context_data = json.load(f)

            steps = context_data.get("steps", [])
            help_entry = next(
                (s for s in steps if s.get("number") == f"help-{tool_name}"), None
            )

            if help_entry:
                return {
                    "success": True,
                    "tool": tool_name,
                    "instructions": help_entry.get("instructions", ""),
                    "objective": help_entry.get("objective", ""),
                }
            else:
                return {
                    "success": False,
                    "error": f"Documentao de '{tool_name}' no encontrada",
                }
        except Exception as e:
            debug(f"[HELP] Erro ao carregar help para {tool_name}: {e}")
            return {"success": False, "error": f"Erro ao carregar documentao: {str(e)}"}

    def _execute_chain_of_thought(self, args: Dict[str, Any]) -> str:
        """
        Executa tool 'chain-of-thought' para registrar raciocnio/pensamento em steps estruturados.

        Args:
            args: Dict com:
                - steps: Array de strings - cada elemento  um passo/descoberta/anlise (obrigatrio)
                  Exemplo: ["Analisei 12 competidores", "8 focam em preo", "Concluso: oportunidade em mid-premium"]

        Returns:
            JSON com status de sucesso e steps estruturados
        """
        steps_input = args.get("steps", [])

        # Validar que  array/lista
        if not isinstance(steps_input, list):
            return json.dumps(
                {
                    "success": False,
                    "error": "'steps' deve ser um array de strings",
                    "tool": "chain-of-thought",
                    "hint": 'Use: chain-of-thought(steps=["passo 1", "passo 2", "concluso"])',
                },
                ensure_ascii=False,
            )

        # Limpar e validar cada step
        steps = []
        for step in steps_input:
            if isinstance(step, str):
                cleaned = step.strip()
                if cleaned:
                    steps.append(cleaned)

        if not steps:
            return json.dumps(
                {
                    "success": False,
                    "error": "Nenhum step vlido encontrado no array",
                    "tool": "chain-of-thought",
                    "hint": "Certifique-se de que cada elemento  uma string no-vazia",
                },
                ensure_ascii=False,
            )

        try:
            self.chain_of_thought_used = True
            # Log de cada step
            for i, step in enumerate(steps, 1):
                debug(f"[CHAIN-OF-THOUGHT] Step {i}/{len(steps)}: {step[:100]}...")

            return json.dumps(
                {
                    "success": True,
                    "tool": "chain-of-thought",
                    "total_steps": len(steps),
                    "steps": steps,
                    "message": f"Raciocnio registrado com {len(steps)} step(s) - auditvel e estruturado",
                },
                ensure_ascii=False,
            )

        except Exception as e:
            error(f"[CHAIN-OF-THOUGHT] Erro ao executar: {e}")
            return json.dumps(
                {"success": False, "error": str(e), "tool": "chain-of-thought"},
                ensure_ascii=False,
            )

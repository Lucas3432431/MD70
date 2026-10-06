"""
_web_search.py — Mixin extraído de Core.py.
Core.py importa este módulo e herda WebSearchMixin.
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


class WebSearchMixin:
    def _execute_web_search(self, args: Dict[str, Any]) -> str:
        """
        Executa tool 'web-search' para extrair contedo de URLs ou pesquisar no Google.

         PADRO GENRICO PARA EXTERNAL TOOLS:
        - Esta funo SEMPRE executa completamente e retorna resultado real
        - O parmetro 'wait'  IGNORADO aqui
        - O MessageProcessor controla o comportamento via is_inline:
          * is_inline=false + wait=true  MessageProcessor enfileira + quebra loop
          * is_inline=false + wait=false  MessageProcessor continua processando
          * is_inline=true  sempre executa inline, resultado imediato
        - Este padro  compartilhado com _execute_vision() e _execute_asset()

        SUPORTA MLTIPLAS PESQUISAS:
        - Parmetro 'searches': Array de pesquisas a executar em paralelo
          Exemplo: searches=[{"query": "python async"}, {"fetch": "https://example.com"}, {"visual-analysis": "https://github.com"}]
        - Scraping.py processa todas e retorna resultado nico com todos os resultados

        Args:
            args: Dict com:
            - searches: Lista de pesquisas (mltiplas pesquisas em paralelo):
                * fetch: URL para obter contedo
                * query: Termo para pesquisar no Google
                * visual-analysis: URL para anlise visual (fetch + screenshot)
            - query: Termo para pesquisar no Google
            - fetch: URL para extrair contedo
            - visual-analysis: URL para anlise visual
            - insta: URL ou @usuario do Instagram
            - selector: CSS selector opcional para extrair seo especfica
            - screenshot: Se true, retorna screenshot da pgina + design_system
            - wait: Ignorado - MessageProcessor controla (mantido para compatibilidade)

        Returns:
            JSON com contedo em markdown ou erro
        """
        # Import no topo da funo para evitar problemas de escopo
        from App.Features.Tools.Tools.Scraping.crawler import ScrapingScrawlingTool
        import platform

        # Configurar event loop para Windows (necessrio para Playwright)
        if platform.system() == "Windows":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

        # SpecificSourceResearch bypasses marketing gates — prospecting context
        #  visual-analysis e insta exigem business_canvas criado previamente
        # Sem business_canvas, a chamada inteira  bloqueada com erro detalhado
        searches_arg = args.get("searches", [])
        blocked_visual_items: list = []
        has_visual = (
            args.get("visual-analysis")
            or args.get("insta")
            or any(
                s.get("visual-analysis") or s.get("insta")
                for s in searches_arg
                if isinstance(s, dict)
            )
        )
        if has_visual:
            #  GATE DESATIVADO: VERIFICAR SE DOCUMENTOS REQUERIDOS EXISTEM
            pass
            # _, doc_status = self._check_required_documents_exist()
            # #  Bloquear visual-analysis no fluxo de Product (SkillProduct lookup feito, produto ainda no criado)
            # if (
            #     doc_status.get("business_canvas", False)
            #     and self._check_product_lookup_in_chat()
            #     and not self._user_has_product()
            # ):
            #     return json.dumps(
            #         {
            #             "success": False,
            #             "tool": "web-search",
            #             "error": "visual-analysis no  permitido no fluxo de criao do produto.",
            #             "hint": "Use apenas fetch (pgina do produto) e query (busca de avaliaes) durante a pesquisa de produto. visual-analysis  para Brand Communication.",
            #             "allowed_now": ["fetch", "query"],
            #             "correction_required": [
            #                 "REMOVA visual-analysis desta chamada",
            #                 "Use web-search(fetch='<url>') para capturar dados do produto",
            #             ],
            #         },
            #         ensure_ascii=False,
            #     )
            _visual_bypass = self._check_variation_quiz_answered_in_chat()
            # if not doc_status.get("business_canvas", False) and not _visual_bypass:
            if False:  # GATE DESATIVADO
                # Identificar quais itens foram bloqueados para informar o modelo
                blocked_items_desc = []
                if args.get("visual-analysis"):
                    blocked_items_desc.append(
                        f"visual-analysis: {args['visual-analysis']}"
                    )
                if args.get("insta"):
                    blocked_items_desc.append(f"insta: {args['insta']}")
                for s in searches_arg:
                    if isinstance(s, dict):
                        if s.get("visual-analysis"):
                            blocked_items_desc.append(
                                f"visual-analysis: {s['visual-analysis']}"
                            )
                        elif s.get("insta"):
                            blocked_items_desc.append(f"insta: {s['insta']}")
                return json.dumps(
                    {
                        "success": False,
                        "tool": "web-search",
                        "error": "Antes de realizar anlises visuais, faa o setup do Business Canvas.",
                        "blocked_items": blocked_items_desc,
                        "allowed_now": ["fetch", "query"],
                        "requires_first": "document(type='business_canvas')",
                        "correction_required": [
                            "REMOVA os itens 'visual-analysis'/'insta' desta chamada",
                            "Use apenas 'fetch' ou 'query' por enquanto",
                            f"Itens bloqueados: {', '.join(blocked_items_desc)}",
                            "DEPOIS de criar business_canvas: visual-analysis e insta estaro disponveis",
                        ],
                    },
                    ensure_ascii=False,
                )

        #  GATE: fluxo de variação exige web-search com AMBOS fetch e visual-analysis
        # Se o agente chamar com apenas um dos dois, bloqueia e instrui a incluir ambos
        if (
            self._check_variation_quiz_answered_in_chat()
            and self.db_manager
            and self.current_chat_id
        ):
            try:
                from App.Core.Crunch.TablesSQL.Models import IsolatedMessage as _IMvw

                _svw = self.db_manager.get_session()
                try:
                    _already_fetch = (
                        _svw.query(_IMvw)
                        .filter(
                            _IMvw.isolated_chat_id == self.current_chat_id,
                            _IMvw.tool_called.in_(["web-search", "web_search"]),
                            _IMvw.tool_call_type == "output",
                            _IMvw.content.ilike('%"type": "fetch"%'),
                        )
                        .first()
                    )
                    _already_visual = (
                        _svw.query(_IMvw)
                        .filter(
                            _IMvw.isolated_chat_id == self.current_chat_id,
                            _IMvw.tool_called.in_(["web-search", "web_search"]),
                            _IMvw.tool_call_type == "output",
                            _IMvw.content.ilike('%"type": "visual-analysis"%'),
                        )
                        .first()
                    )
                    # Chamada combinada: output só retorna visual-analysis, mas fetch também foi feito
                    if _already_visual and not _already_fetch:
                        _vis_input = (
                            _svw.query(_IMvw)
                            .filter(
                                _IMvw.isolated_chat_id == self.current_chat_id,
                                _IMvw.tool_called.in_(["web-search", "web_search"]),
                                _IMvw.tool_call_type == "input",
                                _IMvw.id < _already_visual.id,
                                _IMvw.content.ilike('%"fetch"%'),
                                _IMvw.content.ilike('%"visual-analysis"%'),
                            )
                            .order_by(_IMvw.id.desc())
                            .first()
                        )
                        if _vis_input:
                            _already_fetch = _vis_input
                finally:
                    _svw.close()

                # Só valida se ainda falta pelo menos um dos dois
                if not (_already_fetch and _already_visual):
                    _this_has_fetch = bool(
                        args.get("fetch")
                        or any(
                            s.get("fetch") for s in searches_arg if isinstance(s, dict)
                        )
                    )
                    _this_has_visual = bool(
                        args.get("visual-analysis")
                        or any(
                            s.get("visual-analysis")
                            for s in searches_arg
                            if isinstance(s, dict)
                        )
                    )
                    _missing_now = []
                    if not _already_fetch and not _this_has_fetch:
                        _missing_now.append("fetch")
                    if not _already_visual and not _this_has_visual:
                        _missing_now.append("visual-analysis")
                    if _missing_now:
                        _ref_url = (
                            args.get("fetch")
                            or args.get("visual-analysis")
                            or "<url_do_produto>"
                        )
                        return json.dumps(
                            {
                                "success": False,
                                "tool": "web-search",
                                "error": f"No fluxo de variação, web-search deve incluir fetch E visual-analysis. Faltando: {', '.join(_missing_now)}.",
                                "hint": "Inclua ambos na mesma chamada: web-search(fetch='<url>', visual-analysis='<url>')",
                                "correction_required": [
                                    {
                                        "step": 1,
                                        "call": {
                                            "tool": "web-search",
                                            "fetch": _ref_url,
                                            "visual-analysis": _ref_url,
                                            "wait": True,
                                        },
                                    }
                                ],
                            },
                            ensure_ascii=False,
                        )
            except Exception as _vwe:
                debug(
                    f"[WEB-SEARCH] Erro ao verificar gate variação fetch+visual: {_vwe}"
                )

        #  GATE: aps lookup SkillProduct.md e sem produto criado  exige quiz de URL antes de qualquer pesquisa
        if (
            self._check_product_lookup_in_chat()
            and not self._user_has_product()
            and not self._check_product_url_quiz_answered()
        ):
            return json.dumps(
                {
                    "success": False,
                    "tool": "web-search",
                    "error": "Execute o quiz de URL do produto antes de pesquisar",
                    "hint": "Use quiz(domain='ProductURL', questions=[{'question': 'Informe a URL do produto ou de um concorrente para eu pesquisar', 'type': 'url', 'options': []}]). NUNCA use type='mltipla escolha' para esta pergunta.",
                    "correction_required": [
                        {"step": 1, "call": {"tool": "quiz", "domain": "ProductURL"}}
                    ],
                },
                ensure_ascii=False,
            )

        # ========== GATE: SkillCompetitorAnalysis exige canvas+brand setados e consultados ==========
        if (
            self._check_competitor_analysis_lookup_in_chat()
            and agent_id != "debug-agent"
        ):
            _has_canvas_ca = self._user_has_business_canvas()
            _has_brand_ca = self._user_has_brand_communication()
            if not _has_canvas_ca or not _has_brand_ca:
                _missing_ca = []
                if not _has_canvas_ca:
                    _missing_ca.append("business_canvas")
                if not _has_brand_ca:
                    _missing_ca.append("brand_communication")
                return json.dumps(
                    {
                        "success": False,
                        "tool": "web-search",
                        "error": f"SkillCompetitorAnalysis exige {' e '.join(_missing_ca)} criados antes de pesquisar concorrentes.",
                        "correction_required": [
                            {
                                "step": 1,
                                "call": {
                                    "tool": "lookup",
                                    "file": "SkillBusinessCanvas.md",
                                },
                            },
                            {
                                "step": 2,
                                "call": {
                                    "tool": "lookup",
                                    "file": "SkillBrandIdentity.md",
                                },
                            },
                        ],
                    },
                    ensure_ascii=False,
                )
            # Documentos existem — verificar se foram consultados nesta sessão
            try:
                from App.Core.Crunch.TablesSQL.Models import (
                    IsolatedMessage as _IMca,
                    Document as _DocModelCa,
                )

                _sca = self.db_manager.get_session()
                try:
                    _ctx_ca = (
                        _sca.query(_IMca)
                        .filter(
                            _IMca.isolated_chat_id == self.current_chat_id,
                            _IMca.tool_called == "context",
                            _IMca.tool_call_type == "output",
                        )
                        .all()
                    )
                    _ctx_blob_ca = " ".join(c.content for c in _ctx_ca).lower()
                    _missing_ctx = []
                    _required_ctx = []
                    if "business_canvas" not in _ctx_blob_ca:
                        _canvas_doc_ca = (
                            _sca.query(_DocModelCa)
                            .filter(
                                _DocModelCa.user_id == self.current_user_id,
                                _DocModelCa.tool_type == "business_canvas",
                            )
                            .order_by(_DocModelCa.created_at.desc())
                            .first()
                        )
                        _canvas_id_ca = (
                            _canvas_doc_ca.document_id
                            if _canvas_doc_ca
                            else "<business_canvas_id>"
                        )
                        _missing_ctx.append("business_canvas")
                        _required_ctx.append(
                            f"context(type='document', document_id='{_canvas_id_ca}')"
                        )
                    if "brand_communication" not in _ctx_blob_ca:
                        _brand_doc_ca = (
                            _sca.query(_DocModelCa)
                            .filter(
                                _DocModelCa.user_id == self.current_user_id,
                                _DocModelCa.tool_type == "brand_communication",
                            )
                            .order_by(_DocModelCa.created_at.desc())
                            .first()
                        )
                        _brand_id_ca = (
                            _brand_doc_ca.document_id
                            if _brand_doc_ca
                            else "<brand_communication_id>"
                        )
                        _missing_ctx.append("brand_communication")
                        _required_ctx.append(
                            f"context(type='document', document_id='{_brand_id_ca}')"
                        )
                    if _missing_ctx:
                        return json.dumps(
                            {
                                "success": False,
                                "tool": "web-search",
                                "error": f"Execute context() de {' e '.join(_missing_ctx)} antes de iniciar análise de concorrentes.",
                                "correction_required": [
                                    {"step": i + 1, "call": c}
                                    for i, c in enumerate(_required_ctx)
                                ],
                            },
                            ensure_ascii=False,
                        )
                finally:
                    _sca.close()
            except Exception as _eca:
                debug(
                    f"[WEB-SEARCH] Erro ao verificar gate SkillCompetitorAnalysis: {_eca}"
                )

        # ========== Suporte a mltiplas pesquisas ==========
        # Scraping.py recebe mltiplas pesquisas e processa todas juntas
        # Retorna resultado nico com todos os resultados
        searches = args.get("searches", [])

        if searches and isinstance(searches, list) and len(searches) > 0:
            debug(f"[WEB-SEARCH] Mltiplas pesquisas detectadas: {len(searches)} itens")

            # Validar cada pesquisa
            validated_searches = []
            for i, search_item in enumerate(searches):
                if isinstance(search_item, dict):
                    if (
                        search_item.get("fetch")
                        or search_item.get("query")
                        or search_item.get("visual-analysis")
                    ):
                        validated_searches.append(search_item)
                    else:
                        debug(
                            f"[WEB-SEARCH] Item {i} invlido: sem 'fetch', 'query' ou 'visual-analysis'"
                        )

            if not validated_searches:
                return json.dumps(
                    {
                        "success": False,
                        "error": "Nenhuma pesquisa vlida fornecida em 'searches'",
                        "tool": "web-search",
                    },
                    ensure_ascii=False,
                )

            # ========== EXECUTAR MLTIPLAS PESQUISAS EM PARALELO ==========
            # Scraping.py.execute_multiple processa todas as pesquisas em paralelo
            # e retorna resultado consolidado quando todas terminarem
            try:
                from App.Features.Tools.Tools.Scraping.crawler import (
                    ScrapingScrawlingTool,
                )

                scraper = ScrapingScrawlingTool()

                debug(
                    f"[WEB-SEARCH] Iniciando execuo de {len(validated_searches)} pesquisas em paralelo via Scraping.execute_multiple"
                )

                # Verificar se h event loop ativo
                try:
                    loop = asyncio.get_running_loop()
                    debug(f"[WEB-SEARCH] Event loop j est rodando, usando threadsafe")
                    result = asyncio.run_coroutine_threadsafe(
                        scraper.execute_multiple(
                            searches=validated_searches,
                            debug=False,
                            proxy=scraper.get_proxy(),
                        ),
                        loop,
                    ).result(timeout=300)
                except RuntimeError:
                    debug(f"[WEB-SEARCH] Sem event loop, usando asyncio.run")
                    result = asyncio.run(
                        scraper.execute_multiple(
                            searches=validated_searches,
                            debug=False,
                            proxy=scraper.get_proxy(),
                        )
                    )

                if result.get("status") == "success":
                    return json.dumps(
                        {
                            "success": True,
                            "tool": "web-search",
                            "type": "multiple_searches",
                            "total": result.get("total", 0),
                            "success_count": result.get("success_count", 0),
                            "results": result.get("results", []),
                        },
                        ensure_ascii=False,
                    )
                else:
                    return json.dumps(
                        {
                            "success": False,
                            "error": result.get(
                                "message", "Erro ao processar mltiplas pesquisas"
                            ),
                            "tool": "web-search",
                        },
                        ensure_ascii=False,
                    )
            except Exception as e:
                error(f"[WEB-SEARCH] Erro ao processar mltiplas pesquisas: {e}")
                return json.dumps(
                    {
                        "success": False,
                        "error": f"Erro ao processar mltiplas pesquisas: {str(e)}",
                        "tool": "web-search",
                    },
                    ensure_ascii=False,
                )

        # ========== Modo singular (URL, search term ou Instagram) ==========
        # Suportar novos parmetros: fetch, query, visual-analysis
        url = args.get("fetch", "").strip()
        query = args.get("query", "").strip()
        visual_analysis = args.get("visual-analysis", "").strip()
        insta = args.get("insta", "").strip()
        selector = args.get("selector")

        # Se ambos fetch e visual-analysis fornecidos: executar em paralelo para retornar os dois resultados
        if url and visual_analysis:
            combined_searches = [{"fetch": url}, {"visual-analysis": visual_analysis}]
            try:
                from App.Features.Tools.Tools.Scraping.crawler import (
                    ScrapingScrawlingTool as _Crawler,
                )

                _scraper = _Crawler()
                try:
                    _loop = asyncio.get_running_loop()
                    _result = asyncio.run_coroutine_threadsafe(
                        _scraper.execute_multiple(
                            searches=combined_searches,
                            debug=False,
                            proxy=_scraper.get_proxy(),
                        ),
                        _loop,
                    ).result(timeout=300)
                except RuntimeError:
                    _result = asyncio.run(
                        _scraper.execute_multiple(
                            searches=combined_searches,
                            debug=False,
                            proxy=_scraper.get_proxy(),
                        )
                    )
                if _result.get("status") == "success":
                    return json.dumps(
                        {
                            "success": True,
                            "tool": "web-search",
                            "type": "multiple_searches",
                            "total": _result.get("total", 0),
                            "success_count": _result.get("success_count", 0),
                            "results": _result.get("results", []),
                        },
                        ensure_ascii=False,
                    )
                else:
                    return json.dumps(
                        {
                            "success": False,
                            "error": _result.get(
                                "message", "Erro ao processar fetch+visual-analysis"
                            ),
                            "tool": "web-search",
                        },
                        ensure_ascii=False,
                    )
            except Exception as _e:
                error(f"[WEB-SEARCH] Erro ao processar fetch+visual-analysis: {_e}")
                return json.dumps(
                    {
                        "success": False,
                        "error": f"Erro ao processar fetch+visual-analysis: {str(_e)}",
                        "tool": "web-search",
                    },
                    ensure_ascii=False,
                )

        # visual-analysis implica screenshot=True e  tratado como URL
        if visual_analysis:
            url = visual_analysis
            screenshot = True
        else:
            screenshot = args.get("screenshot", False)

        # ========== wait=true  ignorado aqui ==========
        # O MessageProcessor controla o wait/enqueue baseado no parmetro
        # Core.py sempre executa a busca e retorna o resultado real

        # Validar que pelo menos um parmetro foi fornecido
        if not url and not query and not insta:
            return json.dumps(
                {
                    "success": False,
                    "error": "Parmetro obrigatrio: fetch (URL), query (termo), visual-analysis (URL) ou insta",
                    "tool": "web-search",
                }
            )

        # ========== INSTAGRAM PROFILE ANALYSIS ==========
        if insta and not query and not url:
            return json.dumps(
                {
                    "success": False,
                    "error": "Análise de perfil Instagram foi removida. Use --url com a URL do perfil para scraping via browser service.",
                    "tool": "web-search",
                },
                ensure_ascii=False,
            )

        # Se query, fazer web-search dos resultados do Google
        if query and not url and not insta:
            try:
                debug(f"[WEB-SEARCH] Pesquisa Google: {query}")

                # Usar Google search como URL
                google_search_url = (
                    f"https://www.google.com/search?q={query.replace(' ', '+')}"
                )
                debug(f"[WEB-SEARCH] URL formatada: {google_search_url}")

                tool = ScrapingScrawlingTool()
                debug(f"[WEB-SEARCH] Iniciando execute com is_google_search=True")

                # Verificar se h event loop ativo
                try:
                    loop = asyncio.get_running_loop()
                    debug(f"[WEB-SEARCH] Event loop j est rodando, usando gather")
                    result = asyncio.run_coroutine_threadsafe(
                        tool.execute(
                            google_search_url,
                            is_google_search=True,
                            extract_colors=False,
                        ),
                        loop,
                    ).result(timeout=60)
                except RuntimeError:
                    # Sem event loop, usar asyncio.run normalmente
                    debug(f"[WEB-SEARCH] Sem event loop, usando asyncio.run")
                    result = asyncio.run(
                        tool.execute(
                            google_search_url,
                            is_google_search=True,
                            extract_colors=False,
                        )
                    )

                debug(
                    f"[WEB-SEARCH] Resultado recebido: status={result.get('status')}, tipo={type(result)}"
                )

                if result.get("status") == "success":
                    content_len = len(result.get("content", ""))
                    debug(
                        f"[WEB-SEARCH] Pesquisa bem-sucedida: {content_len} chars extrados"
                    )
                    response_data = {
                        "success": True,
                        "tool": "web-search",
                        "query": query,
                        "type": "query",
                        "content": result.get("content", ""),
                    }
                    return json.dumps(response_data, ensure_ascii=False)
                else:
                    error_msg = result.get(
                        "message", "Erro desconhecido ao processar pesquisa"
                    )
                    error(
                        f"[WEB-SEARCH] Erro ao fazer web-search: {error_msg}. Resultado completo: {json.dumps(result, ensure_ascii=False)}"
                    )
                    return json.dumps(
                        {
                            "success": False,
                            "error": f"Erro ao fazer web-search: {error_msg}",
                            "tool": "web-search",
                        },
                        ensure_ascii=False,
                    )

            except Exception as e:
                import traceback

                error(f"[WEB-SEARCH] Erro ao processar busca: {str(e)}")
                error(f"[WEB-SEARCH] Traceback: {traceback.format_exc()}")
                return json.dumps(
                    {
                        "success": False,
                        "error": f"Erro ao processar busca: {str(e)}",
                        "tool": "web-search",
                    },
                    ensure_ascii=False,
                )

        # Se URL, fazer web-search
        try:
            debug(
                f"[WEB-SEARCH] Iniciando web-search: {url}"
                + (f" (selector: {selector})" if selector else "")
                + (f" (screenshot: true)" if screenshot else "")
            )

            tool = ScrapingScrawlingTool()

            # Se screenshot=true, executar anlise de design completa
            if screenshot:
                debug(f"[WEB-SEARCH] Modo screenshot: anlise de design system")

                # Verificar se h event loop ativo
                try:
                    loop = asyncio.get_running_loop()
                    debug(f"[WEB-SEARCH] Event loop j est rodando, usando threadsafe")
                    result = asyncio.run_coroutine_threadsafe(
                        tool.execute(
                            url, selector, extract_colors=True, vision_only=True
                        ),
                        loop,
                    ).result(timeout=120)
                except RuntimeError:
                    debug(f"[WEB-SEARCH] Sem event loop, usando asyncio.run")
                    result = asyncio.run(
                        tool.execute(
                            url, selector, extract_colors=True, vision_only=True
                        )
                    )

                if result["status"] == "success":
                    debug(f"[WEB-SEARCH-SCREENSHOT] Anlise bem-sucedida")
                    response_data = {
                        "success": True,
                        "tool": "web-search",
                        "type": "visual-analysis",
                        "url": url,
                        "content": result.get("content"),
                        "design_analysis": result.get("design_analysis"),
                    }
                    return json.dumps(response_data, ensure_ascii=False)
                else:
                    error(
                        f"[WEB-SEARCH-SCREENSHOT] Erro na anlise: {result.get('message')}"
                    )
                    return json.dumps(
                        {
                            "success": False,
                            "error": result.get(
                                "message", "Erro ao capturar screenshot"
                            ),
                            "tool": "web-search",
                            "url": url,
                        },
                        ensure_ascii=False,
                    )
            else:
                # Modo normal: scraping de contedo
                # Verificar se h event loop ativo
                try:
                    loop = asyncio.get_running_loop()
                    debug(f"[WEB-SEARCH] Event loop j est rodando, usando threadsafe")
                    result = asyncio.run_coroutine_threadsafe(
                        tool.execute(url, selector, extract_colors=True), loop
                    ).result(timeout=60)
                except RuntimeError:
                    debug(f"[WEB-SEARCH] Sem event loop, usando asyncio.run")
                    result = asyncio.run(
                        tool.execute(url, selector, extract_colors=True)
                    )

                if result["status"] == "success":
                    debug(
                        f"[WEB-SEARCH] Scraping bem-sucedido: {len(result['content'])} chars extrados"
                    )
                    response_data = {
                        "success": True,
                        "tool": "web-search",
                        "type": "fetch",
                        "url": url,
                        "content": result["content"],
                        "favicon_url": result.get("favicon_url"),
                    }
                    if selector:
                        response_data["selector"] = selector

                    # REMOVIDO: Anlise de vision agora  feita como tool call separada
                    # IA deve chamar vision() se quiser analisar a favicon ou imagens da pgina

                    return json.dumps(response_data, ensure_ascii=False)
                else:
                    return json.dumps(
                        {
                            "success": False,
                            "error": result.get(
                                "message", "Erro desconhecido ao fazer web-search"
                            ),
                            "tool": "web-search",
                            "url": url,
                        }
                    )

        except Exception as e:
            error(f"[WEB-SEARCH] Erro ao fazer web-search de {url}: {e}")
            return json.dumps(
                {"success": False, "error": str(e), "tool": "web-search", "url": url}
            )

    def _check_web_search_visual_analysis(self) -> bool:
        """
        Verifica se h execuo de web-search com visual-analysis nas ltimas mensagens do chat.
        """
        if not self.db_manager or not self.current_chat_id:
            return False

        try:
            session = self.db_manager.get_session()
            try:
                blob = self._get_tool_messages_blob(session, TOOL_WEB_SEARCH)
                return bool(blob) and (
                    "visual-analysis" in blob or "visual_analysis" in blob
                )
            finally:
                session.close()
        except Exception as e:
            debug(f"[VALIDATE] Erro ao verificar web-search visual-analysis: {e}")
            return False

    def _check_web_search_with_specific_strings(
        self, required_strings: list, search_type: str = None
    ) -> dict:
        """
        Verifica se o blob concatenado de todos os web-searches contm todas as strings obrigatrias.

        Args:
            required_strings: Lista de strings que devem estar presentes
            search_type: Se informado, o blob tambm deve conter este tipo (ex: "visual-analysis")
        """
        if not self.db_manager or not self.current_chat_id:
            return {"found": False, "missing_strings": required_strings}

        try:
            session = self.db_manager.get_session()
            try:
                blob = self._get_tool_messages_blob(session, TOOL_WEB_SEARCH)
                if not blob.strip():
                    return {"found": False, "missing_strings": required_strings}

                if search_type and search_type.lower() not in blob:
                    return {"found": False, "missing_strings": required_strings}

                found_strings = {s for s in required_strings if s.lower() in blob}
                missing = [s for s in required_strings if s not in found_strings]

                if not missing:
                    debug(
                        f"[VALIDATE] Todas as strings encontradas no blob de web-searches: {found_strings}"
                    )
                    return {"found": True, "missing_strings": []}

                debug(f"[VALIDATE] Strings faltantes: {missing}")
                return {"found": False, "missing_strings": missing}
            finally:
                session.close()
        except Exception as e:
            debug(
                f"[VALIDATE] Erro ao verificar web-search com strings especficas: {e}"
            )
            return {"found": False, "missing_strings": required_strings}

    def _check_web_search_with_concepts(
        self, required_concepts: dict, search_type: str = None
    ) -> dict:
        """
        Verifica se o blob concatenado de todos os web-searches contm uma variao de cada conceito.

        Args:
            required_concepts: Dict { "concept_name": [list of variations] }
            search_type: Se informado, o blob tambm deve conter este tipo
        """
        if not self.db_manager or not self.current_chat_id:
            return {
                "found": False,
                "missing_concepts": list(required_concepts.keys()),
                "found_concepts": {},
            }

        try:
            session = self.db_manager.get_session()
            try:
                blob = self._get_tool_messages_blob(session, TOOL_WEB_SEARCH)
                if not blob.strip():
                    return {
                        "found": False,
                        "missing_concepts": list(required_concepts.keys()),
                        "found_concepts": {},
                    }

                if search_type and search_type.lower() not in blob:
                    return {
                        "found": False,
                        "missing_concepts": list(required_concepts.keys()),
                        "found_concepts": {},
                    }

                found_concepts = {}
                for concept_name, variations in required_concepts.items():
                    for variation in variations:
                        if variation.lower() in blob:
                            found_concepts[concept_name] = variation
                            debug(
                                f"[VALIDATE] Conceito '{concept_name}' encontrado via '{variation}'"
                            )
                            break

                missing_concepts = [
                    c for c in required_concepts.keys() if c not in found_concepts
                ]

                if not missing_concepts:
                    debug(
                        f"[VALIDATE] Todos os conceitos encontrados: {found_concepts}"
                    )
                    return {
                        "found": True,
                        "missing_concepts": [],
                        "found_concepts": found_concepts,
                    }

                debug(f"[VALIDATE] Conceitos faltantes: {missing_concepts}")
                return {
                    "found": False,
                    "missing_concepts": missing_concepts,
                    "found_concepts": found_concepts,
                }
            finally:
                session.close()
        except Exception as e:
            debug(f"[VALIDATE] Erro ao verificar web-search com conceitos: {e}")
            return {
                "found": False,
                "missing_concepts": list(required_concepts.keys()),
                "found_concepts": {},
            }

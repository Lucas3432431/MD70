"""
_document.py — Mixin extraído de Core.py.
Core.py importa este módulo e herda DocumentMixin.
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
    "social_media",
    "catalog",
    "self_knowledge",
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


class DocumentMixin:
    def _convert_brand_communication_to_relative_url(
        self, filename: str, client_id: int
    ) -> str:
        """
        Gera URL relativa para brand_communication assets.
        Salva em client_{client_id}/assets/filename

        Exemplo:
        - Input: "avatar.png", client_id=123
        - Output: "client_123/assets/avatar.png"

        Args:
            filename: Nome do arquivo (ex: "avatar.png")
            client_id: ID do cliente

        Returns:
            URL relativa (ex: "client_123/assets/avatar.png")
        """
        relative_url = f"client_{client_id}/assets/{filename}"
        debug(f"[ASSET] URL relativa brand_communication gerada: {relative_url}")
        return relative_url

    def _convert_relative_to_complete_url(self, relative_url: str) -> str:
        """
        Converte URL relativa para URL completa usando PUBLIC_URL do .env.

        Exemplo:
        - Input: "client_123/assets/avatar.png"
        - Output: "https://transpenetrable-supernormally-donnie.ngrok-free.dev/assets/proxy/client_123/assets/avatar.png"

        Args:
            relative_url: URL relativa (ex: "client_123/assets/avatar.png")

        Returns:
            URL completa usando PUBLIC_URL
        """
        public_url = get_public_url()
        # Usar rota de proxy /assets/proxy/ para servir arquivos do storage
        complete_url = f"{public_url}/assets/proxy/{relative_url}"
        return complete_url

    def _set_nested_field(
        self, obj: Dict[str, Any], field_path: str, value: Any
    ) -> None:
        """
        Atualiza campo aninhado em dicionrio usando notao de ponto.

        Exemplo:
            obj = {"exclusive_avatar": {"url": None}}
            _set_nested_field(obj, "exclusive_avatar.url", "assets/2026/03/30/avatar.png")
            # Resultado: obj["exclusive_avatar"]["url"] = "assets/..."

        Args:
            obj: Dicionrio a atualizar
            field_path: Caminho do campo separado por ponto (ex: "a.b.c")
            value: Valor a atribuir

        Raises:
            KeyError se campo intermedirio no existe e no pode ser criado
        """
        parts = field_path.split(".")
        current = obj

        # Navegar at penltimo campo
        for part in parts[:-1]:
            if part not in current:
                # Criar estrutura se no existir
                current[part] = {}
            current = current[part]

        # Atualizar ltimo campo
        final_key = parts[-1]
        current[final_key] = value
        debug(f"[ASSET] Campo aninhado atualizado: {field_path} = {value}")

    def _update_brand_communication_document(
        self, document_id: str, brand_field: str, relative_url: str
    ) -> None:
        """
        Atualiza campo aninhado em documento brand_communication.

        Suporta notao de ponto: "exclusive_avatar.url", "brand_archetype.url", etc.

        Args:
            document_id: ID do documento
            brand_field: Caminho do campo (ex: "exclusive_avatar.url")
            relative_url: URL relativa a atribuir

        Raises:
            Exception se documento no encontrado ou erro ao salvar
        """
        if not self.db_manager or not self.current_user_id:
            raise Exception("Contexto de banco de dados no disponvel")

        session = self.db_manager.get_session()
        try:
            from sqlalchemy import text

            # 1. Buscar documento
            query_select = text(
                """
                SELECT content FROM documents
                WHERE document_id = :document_id
                AND user_id = :user_id
                AND tool_type = 'brand_communication'
            """
            )

            result = session.execute(
                query_select,
                {"document_id": document_id, "user_id": self.current_user_id},
            ).first()

            if not result:
                raise Exception(
                    f"Documento brand_communication no encontrado: {document_id}"
                )

            # 2. Parsear contedo JSON
            content_json = json.loads(result[0])

            # 3. Atualizar campo aninhado
            self._set_nested_field(content_json, brand_field, relative_url)

            # 4. Salvar documento
            updated_content = json.dumps(content_json, ensure_ascii=False)

            query_update = text(
                """
                UPDATE documents
                SET content = :content, updated_at = CURRENT_TIMESTAMP
                WHERE document_id = :document_id
            """
            )

            session.execute(
                query_update, {"content": updated_content, "document_id": document_id}
            )

            session.commit()
            debug(
                f"[ASSET] Documento brand_communication atualizado: {document_id}  {brand_field} = {relative_url}"
            )

        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    def _execute_document(self, args: Dict[str, Any]) -> str:
        """
        Executa tool 'document' para salvar documentos com contedo na tabela documents.

        Args:
            args: Dict com:
                - type: Tipo de documento - OBRIGATRIO (business_canvas | brand_communication | goal)
                - title: Nome descritivo do documento - OBRIGATRIO
                - data: JSON estruturado (OBRIGATRIO se type=business_canvas)
                - content: Contedo markdown (OBRIGATRIO se typebusiness_canvas)
                - help: Boolean True para retornar instrues de uso da tool

        Returns:
            JSON com resultado da operao
        """
        help_mode = args.get("help", False)

        # MODO HELP: retornar instrues de uso da tool
        if help_mode is True:
            return self._get_tool_instructions("document")

        doc_type = args.get("type", "").strip().lower()
        title = args.get("title", "").strip()
        data = args.get("data")  # JSON object
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (json.JSONDecodeError, ValueError):
                data = None
        if data is not None and not isinstance(data, dict):
            return json.dumps(
                {
                    "success": False,
                    "error": "O campo 'data' deve ser um objeto JSON válido (não string ou lista).",
                    "tool": "document",
                },
                ensure_ascii=False,
            )
        content = args.get("content", "").strip()

        # Validar tipo de documento (OBRIGATRIO)
        if not doc_type:
            return json.dumps(
                {
                    "success": False,
                    "error": "Informe o tipo do documento",
                    "hint": f"Campo 'type'  obrigatrio. Valores aceitos: {', '.join(self.DOCUMENT_VALID_TYPES)}",
                    "tool": "document",
                }
            )

        if doc_type not in self.DOCUMENT_VALID_TYPES:
            return json.dumps(
                {
                    "success": False,
                    "error": f"Tipo de documento '{doc_type}' invlido",
                    "hint": f"Valores aceitos: {', '.join(self.DOCUMENT_VALID_TYPES)}",
                    "tool": "document",
                }
            )

        # Validar title (OBRIGATRIO)
        if not title:
            return json.dumps(
                {"success": False, "error": "title  obrigatrio", "tool": "document"}
            )

        #  VALIDAR PRIMEIRO (antes de salvar no banco)
        warnings_list = []
        valid_data = {}
        _step_id_to_complete = None  # set by copywriting path to auto-complete step
        _missing_vars: list = []  # set by copywriting path for partial save

        #  GATE GLOBAL: apenas o document do ltimo lookup  permitido
        _LOOKUP_DOC_MAP = {
            "SkillBusinessCanvas.md": "business_canvas",
            "SkillBrandIdentity.md": "brand_communication",
            "SkillProduct.md": "product",
            "SkillCopywriting.md": "copywriting",
            "SkillSocialMedia.md": "social_media",
            "SkillCatalog.md": "catalog",
            "SkillSelfKnowledge.md": "self_knowledge",
        }
        _DOC_SKILL_MAP = {v: k for k, v in _LOOKUP_DOC_MAP.items()}
        _last_lookup_check = [
            ("SkillCopywriting.md", self._check_copywriting_lookup_in_chat),
            ("SkillProduct.md", self._check_product_lookup_in_chat),
            ("SkillBrandIdentity.md", self._check_brand_lookup_in_chat),
            ("SkillBusinessCanvas.md", self._check_canvas_lookup_in_chat),
            ("SkillSocialMedia.md", self._check_social_media_lookup_in_chat),
            ("SkillCatalog.md", self._check_catalog_lookup_in_chat),
            ("SkillSelfKnowledge.md", self._check_self_knowledge_lookup_in_chat),
        ]
        _expected_skill = None
        for _skill_file, _check_fn in _last_lookup_check:
            if _check_fn():
                _expected_skill = _skill_file
                break

        if _expected_skill:
            _expected_doc = _LOOKUP_DOC_MAP[_expected_skill]
            if doc_type != _expected_doc:
                return json.dumps(
                    {
                        "success": False,
                        "error": f"Use document(type='{_expected_doc}')  o ltimo lookup foi {_expected_skill}",
                        "hint": f"Cada skill habilita apenas seu document correspondente. lookup({_expected_skill})  document(type='{_expected_doc}')",
                        "tool": "document",
                        "type": doc_type,
                        "status": "rejected",
                    },
                    ensure_ascii=False,
                )

        if doc_type == "business_canvas":
            missing_steps = []

            #  BLOQUEAR se lookup no foi feito  obrigatrio antes de quiz ou web-search
            if not self._check_lookup_in_chat():
                return json.dumps(
                    {
                        "success": False,
                        "error": "Faa o lookup de SkillBusinessCanvas.md antes de continuar",
                        "hint": "Sequncia obrigatria: lookup(SkillBusinessCanvas.md)  web-search(cliente)  quiz(BusinessCanvas)  document(business_canvas)",
                        "tool": "document",
                        "type": doc_type,
                        "title": title,
                        "status": "rejected",
                    },
                    ensure_ascii=False,
                )

            # SEMPRE exigir quiz
            if not self._check_quiz_in_chat_history():
                missing_steps.append("quiz(skill='BusinessCanvas')")

            #  BLOQUEAR se as strings esto NO QUIZ (devem estar no web-search, no no quiz)
            strings_in_quiz = self._check_strings_in_quiz(
                BUSINESS_CANVAS_PROHIBITED_IN_QUIZ
            )
            if strings_in_quiz["found_in_quiz"]:
                prohibited_found = ", ".join(strings_in_quiz["strings_found"])
                return json.dumps(
                    {
                        "success": False,
                        "error": "Refaa o quiz sem incluir dados quantitativos de mercado",
                        "hint": f"Dados encontrados no quiz que devem vir do web-search: {prohibited_found}. Repita o quiz com informaes qualitativas (proposta de valor, dor, firmografia, conscincia). Use web-search para TAM/SAM/SOM/barreiras/oramento.",
                        "tool": "document",
                        "type": doc_type,
                        "title": title,
                        "status": "rejected",
                    },
                    ensure_ascii=False,
                )

            #  VERIFICAR se o quiz contm informaes OBRIGATRIAS
            quiz_validation = self._check_required_topics_in_quiz(
                BUSINESS_CANVAS_REQUIRED_TOPICS_IN_QUIZ
            )
            missing_t = quiz_validation.get("missing_topics", [])
            found_t = quiz_validation.get("found_topics", [])

            # SEMPRE exigir web-search TOOL com conceitos especficos
            search_validation = self._check_web_search_with_concepts(
                required_concepts=BUSINESS_CANVAS_REQUIRED_SEARCH_CONCEPTS
            )
            missing_concepts = search_validation.get("missing_concepts", [])

            # Consolidar TUDO antes de retornar
            if not quiz_validation["found_all"] or not search_validation["found"]:
                _friendly_names = {
                    "value_proposition": "Proposta de Valor",
                    "pain_solution": "Dor/Soluo",
                    "firmography": "Firmografia/Demografia do ICP",
                    "awareness": "Nvel de Conscincia",
                }
                _concept_explanations = {
                    "market_sizing_tam": "TAM (Mercado Total)",
                    "market_sizing_sam": "SAM (Mercado Enderevel)",
                    "market_sizing_som": "SOM (Mercado Obtvel)",
                    "barriers": "Barreiras de entrada",
                    "market_age": "Idade do mercado",
                    "budget": "Oramento/Investimento",
                }
                _topic_instructions = {
                    "value_proposition": "- 'proposta de valor' ou 'value proposition'",
                    "pain_solution": "- 'dor' ou 'pain' E 'solucao' ou 'solution'",
                    "firmography": "- 'firmografia' ou 'firmographic'",
                    "awareness": "- 'consciencia' ou 'awareness'",
                }

                error_parts = []
                correction_required = []

                if missing_t:
                    friendly_missing = [_friendly_names.get(t, t) for t in missing_t]
                    error_parts.append(f"quiz de {', '.join(friendly_missing)}")
                    correction_required.append(
                        f"quiz(skill='BusinessCanvas') com tpicos faltantes: {', '.join(friendly_missing)}"
                    )
                    correction_required += [
                        _topic_instructions[t]
                        for t in missing_t
                        if t in _topic_instructions
                    ]
                    if found_t:
                        correction_required.append(
                            f"NO repita: {', '.join(found_t)} (j respondidos)"
                        )

                found_concepts = search_validation.get("found_concepts", {})

                # Derivar keywords de validao direto das constantes existentes
                _concept_kw = {
                    c: " ou ".join(f"'{v}'" for v in variants)
                    for c, variants in BUSINESS_CANVAS_REQUIRED_SEARCH_CONCEPTS.items()
                }
                _topic_kw = {
                    t["topic"]: " ou ".join(
                        f"'{v}'" for v in t.get("pt", []) + t.get("en", [])
                    )
                    for t in BUSINESS_CANVAS_REQUIRED_TOPICS_IN_QUIZ
                }

                if missing_concepts:
                    explained = [
                        _concept_explanations.get(c, c) for c in missing_concepts
                    ]
                    error_parts.append(f"pesquisa de {', '.join(explained)}")
                    for c in missing_concepts:
                        correction_required.append(
                            f"web-search '{_concept_explanations.get(c, c)}': inclua uma das strings {_concept_kw.get(c, c)} na query ou resultado"
                        )

                if found_concepts:
                    correction_required.append(
                        f"J validados no web-search (NO refaa): {', '.join(_concept_explanations.get(c, c) for c in found_concepts)}"
                    )

                _what_missing = []
                if missing_t:
                    _what_missing.append("quiz")
                if missing_concepts:
                    _what_missing.append("pesquisa de mercado")
                error_msg = f"Complete {'o ' if len(_what_missing) == 1 else 'o '}{' e a '.join(_what_missing)} obrigatrio{'s' if len(_what_missing) > 1 else ''} do Business Canvas"

                hint_parts = []
                if missing_t:
                    kw_hints = [
                        f"{_friendly_names.get(t, t)}: {_topic_kw.get(t, t)}"
                        for t in missing_t
                    ]
                    hint_parts.append(
                        f"Quiz faltando  inclua uma das keywords na pergunta: {' | '.join(kw_hints)}"
                    )
                if missing_concepts:
                    kw_hints = [
                        f"{_concept_explanations.get(c, c)}: {_concept_kw.get(c, c)}"
                        for c in missing_concepts
                    ]
                    hint_parts.append(
                        f"Web-search faltando  inclua uma das keywords na query: {' | '.join(kw_hints)}"
                    )
                if found_concepts:
                    hint_parts.append(
                        f"J OK no web-search: {', '.join(_concept_explanations.get(c, c) for c in found_concepts)}"
                    )
                if found_t:
                    hint_parts.append(f"J OK no quiz: {', '.join(found_t)}")

                return json.dumps(
                    {
                        "success": False,
                        "error": error_msg,
                        "hint": " || ".join(hint_parts),
                        "tool": "document",
                        "type": doc_type,
                        "title": title,
                        "status": "rejected",
                        "found_search": list(found_concepts.keys()),
                        "found_quiz": found_t,
                        "correction_required": correction_required,
                    },
                    ensure_ascii=False,
                )

            if not data:
                return json.dumps(
                    {
                        "success": False,
                        "error": "Fornea o campo 'data' com o contedo estruturado do Business Canvas.",
                        "tool": "document",
                    }
                )

            # Validar estrutura do business_canvas
            try:
                validation_result = self._validate_business_canvas_json(data)
            except (AttributeError, TypeError) as _val_err:
                _problem_fields = []
                for _f, _t in [
                    ("lifecycle_crm", dict),
                    ("lifecycle_value", dict),
                    ("pains_gains", dict),
                    ("market_sizing", (dict, list)),
                ]:
                    if _f in data and not isinstance(
                        data[_f], _t if isinstance(_t, type) else _t
                    ):
                        _problem_fields.append(
                            f"'{_f}' (recebeu {type(data[_f]).__name__}, deve ser objeto)"
                        )
                if "icp" in data and isinstance(data["icp"], list):
                    for _i, _icp in enumerate(
                        data["icp"] if isinstance(data["icp"], list) else []
                    ):
                        if isinstance(_icp, dict):
                            for _sub in ("firmografia", "demographics"):
                                if _sub in _icp and not isinstance(_icp[_sub], dict):
                                    _problem_fields.append(
                                        f"'icp[{_i}].{_sub}' (recebeu {type(_icp[_sub]).__name__}, deve ser objeto)"
                                    )
                elif "icp" in data and not isinstance(data["icp"], list):
                    _problem_fields.append(
                        f"'icp' (recebeu {type(data['icp']).__name__}, deve ser array)"
                    )
                _bad_hint = (
                    f"Campo(s) com tipo invlido: {', '.join(_problem_fields)}"
                    if _problem_fields
                    else f"Erro interno de tipo: {_val_err}"
                )
                return json.dumps(
                    {
                        "success": False,
                        "tool": "document",
                        "type": doc_type,
                        "title": title,
                        "status": "rejected",
                        "error": "Ajuste as informacoes necessarias no Business Canvas",
                        "message": "Ajuste as informacoes necessarias no Business Canvas",
                        "hint": f'{_bad_hint}. Todos os campos aninhados devem ser objetos JSON {{ }}, no strings. Exemplo correto: lifecycle_crm: {{"acquisition": "...", ...}}',
                    },
                    ensure_ascii=False,
                )
            warnings_list = validation_result.get("warnings", [])
            valid_data = validation_result.get("data", {})

            #  REJEITAR se h warnings (validao falhou)
            if warnings_list:
                correction_instructions = []
                for warning in warnings_list:
                    if "missing: lifecycle_crm" in warning:
                        correction_instructions.append(
                            "LIFECYCLE_CRM OBRIGATRIO: Adicione lifecycle_crm com os 9 campos: acquisition, qualification, conversion, onboarding, activation, retention, expansion, indication, churn"
                        )
                    elif "lifecycle_crm faltando campos" in warning:
                        correction_instructions.append(
                            f"LIFECYCLE_CRM INCOMPLETO: {warning}"
                        )
                    elif "missing: lifecycle_value" in warning:
                        correction_instructions.append(
                            "LIFECYCLE_VALUE OBRIGATRIO: Adicione lifecycle_value com: aha_moment, value_moment, habit, advocacy"
                        )
                    elif "lifecycle_value faltando campos" in warning:
                        correction_instructions.append(
                            f"LIFECYCLE_VALUE INCOMPLETO: {warning}"
                        )
                    elif "missing: icp" in warning:
                        correction_instructions.append(
                            'ICP OBRIGATRIO: Adicione icp como array com pelo menos 1 subgrupo  [{"title": "Nome do subgrupo", "firmografia": {...}} ]'
                        )
                    elif "icp[" in warning and "firmografia" in warning:
                        correction_instructions.append(
                            f"ICP FIRMOGRAFIA FALTANDO: {warning}  Adicione annual_revenue, sector, employees, digital_maturity, technology"
                        )
                    elif "icp[" in warning and "demographics" in warning:
                        correction_instructions.append(
                            f"ICP DEMOGRAPHICS FALTANDO: {warning}  Adicione age_range, gender, location, social_class, consumption_habits, values"
                        )
                    elif "icp[" in warning and "title" in warning:
                        correction_instructions.append(
                            "ICP.TITLE OBRIGATRIO: Cada subgrupo de ICP deve ter um ttulo (ex: 'Fundadores SMB')"
                        )
                    elif "motivator" in warning:
                        correction_instructions.append(
                            'ICP.MOTIVATOR OBRIGATRIO: Adicione motivator em demographics/firmografia de cada ICP: {"type": "pain" ou "ambition", "explanation": "motivo curto"}'
                        )
                    elif "consciousness_level invlido" in warning:
                        correction_instructions.append(
                            "CONSCIOUSNESS_LEVEL INVLIDO: Use string ou array de 1-2 nveis sequenciais adjacentes: 'Inconsciente', 'Consciente do Problema', 'Consciente da Soluo', 'Consciente do Produto', 'Totalmente Consciente'"
                        )
                    elif "pains_gains.pain" in warning:
                        correction_instructions.append(
                            'PAINS_GAINS.PAIN INVLIDO: Use string direta OU objeto {"psychological_effect": "...", "perceived_impact": "..."}'
                        )
                    elif (
                        "missing: market_sizing" in warning
                        or "market_sizing.tam" in warning
                    ):
                        correction_instructions.append(
                            "MARKET_SIZING.TAM INVALIDO: Deve ser numero inteiro (ex: 5000000000)"
                        )
                    elif "market_sizing.sam" in warning:
                        correction_instructions.append(
                            "MARKET_SIZING.SAM INVALIDO: Deve ser numero inteiro"
                        )
                    elif "market_sizing.som" in warning:
                        correction_instructions.append(
                            "MARKET_SIZING.SOM INVALIDO: Deve ser numero inteiro"
                        )
                    elif "invalid:" in warning:
                        field = (
                            warning.split("invalid:")[-1].strip().split("(")[0].strip()
                        )
                        correction_instructions.append(f"{field.upper()} INVALIDO")
                    else:
                        correction_instructions.append(str(warning))

                friendly_error = "Ajuste as informacoes necessarias no Business Canvas"
                return json.dumps(
                    {
                        "success": False,
                        "tool": "document",
                        "type": doc_type,
                        "title": title,
                        "status": "rejected",
                        "error": friendly_error,
                        "correction_required": correction_instructions,
                        "message": friendly_error,
                        "hint": f"DETALHES TCNICOS: {'; '.join(correction_instructions)}",
                    },
                    ensure_ascii=False,
                )

            # Converter data validada para JSON string
            content = json.dumps(valid_data, ensure_ascii=False)

        elif doc_type == "brand_communication":
            #  VERIFICAR PR-REQUISITOS - DESATIVADO
            pass
            #  BLOQUEAR se business_canvas no existe  pr-requisito obrigatrio
            # _, doc_status = self._check_required_documents_exist()
            # if not doc_status.get("business_canvas", False):
            #     return json.dumps(
            #         {
            #             "success": False,
            #             "error": "Finalize o Business Canvas para iniciar a Identidade de Marca.",
            #             "tool": "document",
            #             "type": doc_type,
            #             "title": title,
            #             "status": "rejected",
            #             "message": "Business Canvas no encontrado.",
            #         },
            #         ensure_ascii=False,
            #     )

            #  BLOQUEAR se lookup de brand_communication no foi feito
            if not self._check_brand_lookup_in_chat():
                return json.dumps(
                    {
                        "success": False,
                        "error": "Execute o lookup de SkillBrandIdentity.md para prosseguir.",
                        "tool": "document",
                        "type": doc_type,
                        "title": title,
                        "status": "rejected",
                        "message": "Lookup de SkillBrandIdentity.md pendente.",
                    },
                    ensure_ascii=False,
                )

            # Verificar quiz de URL do site (usurio deve ter informado URL)
            if not self._check_product_url_quiz_answered():
                return json.dumps(
                    {
                        "success": False,
                        "error": "Execute o quiz de URL do site antes de criar o Brand Communication.",
                        "tool": "document",
                        "type": doc_type,
                        "title": title,
                        "status": "rejected",
                        "hint": "quiz(quiz=[{'question': 'Informe a URL do site da empresa para anlise visual', 'type': 'url', 'options': []}])",
                    },
                    ensure_ascii=False,
                )

            # Verificar visual-analysis do site
            if not self._check_web_search_visual_analysis():
                return json.dumps(
                    {
                        "success": False,
                        "error": "Execute web-search(visual-analysis='<url_do_quiz>') antes de criar o Brand Communication.",
                        "tool": "document",
                        "type": doc_type,
                        "title": title,
                        "status": "rejected",
                        "hint": "web-search(visual-analysis='<url_respondida_no_quiz>', wait=true)",
                    },
                    ensure_ascii=False,
                )

            # Verificar quiz para Brand Communication
            quiz_validation = self._check_required_topics_in_quiz(
                BRAND_COMMUNICATION_REQUIRED_TOPICS_IN_QUIZ
            )

            if not quiz_validation["found_all"]:
                brand_error = "Ajuste as informacoes necessarias no Brand Communication"

                return json.dumps(
                    {
                        "success": False,
                        "error": brand_error,
                        "tool": "document",
                        "type": doc_type,
                        "title": title,
                        "status": "rejected",
                        "message": brand_error,
                        "hint": f"Quiz pendente: {', '.join(quiz_validation['missing_topics'])} (use keywords 'cor'/'cores' e 'tom'/'comunicacao')",
                    },
                    ensure_ascii=False,
                )

            #  VALIDAO DE CORES (Visual Analysis vs Quiz)
            # 1. Obter cores da anlise visual
            visual_analysis = self._get_last_visual_analysis()
            if visual_analysis:
                analysis_colors = visual_analysis.get("design_analysis", {}).get(
                    "colors", []
                )
                analysis_hexes = [
                    c.get("hex", "").lower() for c in analysis_colors if c.get("hex")
                ]

                # 2. Obter cores confirmadas pelo usurio no quiz
                quiz_answers = self._get_last_quiz_answers("BrandCommunication")
                user_color_answer = ""
                for qa in quiz_answers:
                    q_text = qa.get("question", "").lower()
                    if "cor" in q_text or "cores" in q_text:
                        user_color_answer = qa.get("answer", "").lower()
                        break

                # 3. Validar se as cores do documento (data) esto alinhadas
                if data:
                    doc_colors = data.get("color_palette", {}).get("colors", [])
                    doc_hexes = [
                        c.get("hex", "").lower() for c in doc_colors if c.get("hex")
                    ]

                    if doc_hexes:
                        # Verificar se as cores do doc esto presentes na resposta do user ou na anlise
                        # (Lgica: as cores do doc devem ser subconjunto ou match das confirmadas)
                        for d_hex in doc_hexes:
                            # Se no est no hex da anlise e o user no mencionou algo parecido na resposta
                            is_in_analysis = any(
                                d_hex in a_hex or a_hex in d_hex
                                for a_hex in analysis_hexes
                            )
                            is_in_answer = d_hex in user_color_answer or any(
                                word in user_color_answer
                                for word in [
                                    "azul",
                                    "verde",
                                    "vermelho",
                                    "preto",
                                    "branco",
                                ]
                                if word in d_hex
                            )

                            if not is_in_analysis and not is_in_answer:
                                return json.dumps(
                                    {
                                        "success": False,
                                        "error": "Ajuste as cores da Identidade de Marca",
                                        "tool": "document",
                                        "type": doc_type,
                                        "message": "Cores no confirmadas pelo usurio no quiz ou anlise visual.",
                                        "hint": f"A cor {d_hex} no foi detectada na anlise visual ({', '.join(analysis_hexes)}) nem confirmada no seu quiz. Use as cores reais do site do cliente confirmadas no final_answers do quiz.",
                                    },
                                    ensure_ascii=False,
                                )

            if not data:
                return json.dumps(
                    {
                        "success": False,
                        "error": "Fornea o campo 'data' com o contedo estruturado do Brand Communication.",
                        "tool": "document",
                    }
                )

            # Validar estrutura do brand_communication
            try:
                validation_result = self._validate_brand_communication_json(data)
            except (AttributeError, TypeError) as _val_err:
                _bc_fields = [
                    ("brand_archetype", dict),
                    ("color_palette", dict),
                    ("font", dict),
                    ("tone_of_voice", dict),
                    ("moodboard", dict),
                    ("exclusive_avatar", dict),
                    ("communication_style", dict),
                ]
                _bad = [
                    f"'{f}' deve ser objeto {{}}  recebeu {type(data[f]).__name__}"
                    for f, t in _bc_fields
                    if f in data and not isinstance(data[f], t)
                ]
                _bad_hint = (
                    f"Campo(s) com tipo errado: {', '.join(_bad)}"
                    if _bad
                    else str(_val_err)
                )
                return json.dumps(
                    {
                        "success": False,
                        "tool": "document",
                        "type": doc_type,
                        "title": title,
                        "status": "rejected",
                        "error": "Corrija os campos do Brand Communication antes de reenviar.",
                        "correction_required": [
                            f'Envie {f.upper()} como objeto JSON {{ }}, no como string. Exemplo: {f}: {{"...": "..."}}'
                            for f, t in _bc_fields
                            if f in data and not isinstance(data[f], t)
                        ]
                        or [f"Erro de tipo interno: {_bad_hint}"],
                        "message": "Corrija os campos do Brand Communication antes de reenviar.",
                        "hint": f"{_bad_hint}. Todos os campos aninhados devem ser objetos JSON {{ }}, no strings.",
                    },
                    ensure_ascii=False,
                )
            warnings_list = validation_result.get("warnings", [])
            valid_data = validation_result.get("data", {})

            #  REJEITAR se h warnings (validao falhou)
            if warnings_list:
                _valid_archetypes = [
                    "fluxo_de_energia",
                    "ludico",
                    "raiz",
                    "instinto_de_possessao",
                    "guerreiro",
                    "socializacao",
                    "cenas_do_cotidiano",
                    "formalizacao",
                    "racional",
                    "grande_meta",
                    "autoestima",
                    "rebelde",
                    "o_intimo",
                    "i_am_a_star",
                    "equilibrio_estetico",
                    "exaltacao_dos_sentidos",
                    "jogo_do_poder",
                    "busca_inconsciente",
                    "idealismo",
                    "expansao",
                    "expressao",
                    "lider_visionario",
                    "tribo_global",
                    "sentimento_cosmico",
                    "sensibilidade",
                ]
                _FIELD_EXAMPLES = {
                    "favicon": '"favicon": "https://exemplo.com/logo.png"',
                    "brand_archetype": '"brand_archetype": {"archetype": "guerreiro", "slogan": "Conquiste sem limites", "unicity": 80}',
                    "brand_archetype.archetype": f'"archetype": "<um dos {len(_valid_archetypes)} valores vlidos, ex: guerreiro, rebelde, racional>"',
                    "brand_archetype.slogan": '"slogan": "Frase curta e impactante da marca"',
                    "brand_archetype.unicity": '"unicity": 75  (nmero de 0 a 100)',
                    "color_palette": '"color_palette": {"colors": [{"hex": "#1E3A8A", "name": "Azul Profundo", "feeling": {"name": "Confiana", "value": 85}}, ...]}}',
                    "color_palette.colors": '"colors": [{"hex": "#1E3A8A", "name": "Azul", "feeling": {"name": "Confiana", "value": 85}}, {"hex": "#60A5FA", ...}, {"hex": "#FFFFFF", ...}]',
                    "color_palette  nenhuma": "Certifique-se de que os 'name' das cores na paleta contenham as mesmas palavras que o cliente usou na resposta do quiz (ex: se o quiz disse 'azul', use name: 'Azul Escuro')",
                    "font": '"font": {"primary": "Inter", "secondary": "Playfair Display", "body": "Roboto"}',
                    "tone_of_voice": '"tone_of_voice": {"primary": "Autoritativo", "secondary": "Acessvel", "forbidden": ["infantil", "agressivo"]}',
                    "communication_style": '"communication_style": {"formality": "semiformal", "pronouns": "voc", "sentence_length": "curtas e diretas"}',
                }
                _errors = [
                    w for w in warnings_list if "invalid:" in w or "nenhuma" in w
                ]
                _missing = [w for w in warnings_list if "missing:" in w]
                _ok_fields = [
                    f
                    for f in [
                        "favicon",
                        "brand_archetype",
                        "color_palette",
                        "font",
                        "tone_of_voice",
                        "communication_style",
                    ]
                    if f in valid_data
                ]

                hint_parts = []
                if _ok_fields:
                    hint_parts.append(f"Campos OK (no altere): {', '.join(_ok_fields)}")
                if _missing:
                    missing_details = []
                    for w in _missing:
                        field = w.split("missing:")[-1].strip().split("(")[0].strip()
                        ex = next(
                            (
                                v
                                for k, v in _FIELD_EXAMPLES.items()
                                if field.startswith(k)
                                or k.startswith(field.split(".")[0])
                            ),
                            None,
                        )
                        missing_details.append(
                            f"  - {field}: AUSENTE  adicione ex: {ex}"
                            if ex
                            else f"  - {field}: AUSENTE"
                        )
                    hint_parts.append("Campos faltando:\n" + "\n".join(missing_details))
                if _errors:
                    error_details = []
                    for w in _errors:
                        field = (
                            w.split("invalid:")[-1].strip().split("(")[0].strip()
                            if "invalid:" in w
                            else "color_palette"
                        )
                        reason = w.split("(")[-1].rstrip(")") if "(" in w else w
                        ex = next(
                            (
                                v
                                for k, v in _FIELD_EXAMPLES.items()
                                if field.startswith(k) or k in field
                            ),
                            None,
                        )
                        error_details.append(
                            f"  - {field}: INVLIDO  {reason}"
                            + (f"  correto: {ex}" if ex else "")
                        )
                    hint_parts.append("Campos com erro:\n" + "\n".join(error_details))

                return json.dumps(
                    {
                        "success": False,
                        "tool": "document",
                        "type": doc_type,
                        "title": title,
                        "status": "rejected",
                        "error": "Ajuste as informacoes necessarias no Brand Communication",
                        "correction_required": [w for w in warnings_list],
                        "message": "Ajuste as informacoes necessarias no Brand Communication",
                        "hint": "\n\n".join(hint_parts),
                    },
                    ensure_ascii=False,
                )

            # Converter data validada para JSON string
            content = json.dumps(valid_data, ensure_ascii=False)

        elif doc_type == "product":
            #  GATE DESATIVADO: business_canvas pr-requisito para product
            pass
            # _, doc_status = self._check_required_documents_exist()
            # if not doc_status.get("business_canvas", False):
            #     return json.dumps(
            #         {
            #             "success": False,
            #             "error": "Finalize o Business Canvas antes de criar o produto",
            #             "hint": "O documento business_canvas  pr-requisito para product.",
            #             "tool": "document",
            #             "type": doc_type,
            #             "title": title,
            #             "status": "rejected",
            #         },
            #         ensure_ascii=False,
            #     )

            #  GATE: lookup de SkillProduct.md obrigatrio
            if not self._check_product_lookup_in_chat():
                return json.dumps(
                    {
                        "success": False,
                        "error": "Faa o lookup de SkillProduct.md antes de criar o produto",
                        "hint": "Execute lookup(file='SkillProduct.md') para carregar a skill.",
                        "tool": "document",
                        "type": doc_type,
                        "title": title,
                        "status": "rejected",
                    },
                    ensure_ascii=False,
                )

            #  GATE: web-search obrigatrio (pesquisa da pgina/avaliaes do produto)
            if self.db_manager and self.current_chat_id:
                try:
                    _ws_session = self.db_manager.get_session()
                    try:
                        _ws_blob = self._get_tool_messages_blob(
                            _ws_session, TOOL_WEB_SEARCH
                        )
                        _has_ws = bool(_ws_blob and _ws_blob.strip())
                    finally:
                        _ws_session.close()
                except Exception:
                    _has_ws = False
                if not _has_ws:
                    return json.dumps(
                        {
                            "success": False,
                            "error": "Pesquise a pgina do produto antes de criar o documento",
                            "hint": "Use web-search(fetch='<url_produto>') para extrair descrio, preo e avaliaes reais do produto.",
                            "tool": "document",
                            "type": doc_type,
                            "title": title,
                            "status": "rejected",
                        },
                        ensure_ascii=False,
                    )

            #  GATE: quiz obrigatrio para confirmar dados qualitativos
            if not self._check_quiz_in_chat_history():
                return json.dumps(
                    {
                        "success": False,
                        "error": "Execute o quiz do produto antes de criar o documento",
                        "hint": "O quiz deve confirmar: ICP do produto, conscincia, dor e proposta de valor.",
                        "tool": "document",
                        "type": doc_type,
                        "title": title,
                        "status": "rejected",
                    },
                    ensure_ascii=False,
                )

            if not data:
                return json.dumps(
                    {
                        "success": False,
                        "error": "Fornea o campo 'data' com os dados do produto",
                        "hint": 'Campos obrigatrios: product_page_url, price ({"value": 199.90, "currency": "BRL"}), value_proposition, pain, solution, site_description, consciousness_level, icp (com firmografia/demographics e motivator), reviews e feedbacks (extrados de web-search)',
                        "tool": "document",
                    }
                )

            validation_result = self._validate_product_json(data)
            warnings_list = validation_result.get("warnings", [])
            valid_data = validation_result.get("data", {})

            if warnings_list:
                correction_instructions = []
                for warning in warnings_list:
                    if "missing:" in warning:
                        field = warning.split("missing:")[-1].strip()
                        correction_instructions.append(f"{field.upper()} OBRIGATRIO")
                    elif "invalid:" in warning:
                        field = (
                            warning.split("invalid:")[-1].strip().split("(")[0].strip()
                        )
                        correction_instructions.append(
                            f"{field.upper()} INVLIDO  {warning.split('(')[-1].rstrip(')')}"
                        )
                    else:
                        correction_instructions.append(warning)
                return json.dumps(
                    {
                        "success": False,
                        "error": "Ajuste as informacoes necessarias no Product",
                        "hint": f"{len(warnings_list)} campo(s) com problema: {'; '.join(correction_instructions)}",
                        "tool": "document",
                        "type": doc_type,
                        "title": title,
                        "status": "rejected",
                        "correction_required": correction_instructions,
                    },
                    ensure_ascii=False,
                )

            content = json.dumps(valid_data, ensure_ascii=False)

        elif doc_type == "copywriting":
            # Variação: bypass — não exige documentos de setup (canvas/brand/product)
            _is_variation_flow = (
                int((data.get("variation") or {}).get("count", 0)) > 0
                or self._check_variation_quiz_answered_in_chat()
            )

            # Gate: variação → exige quiz image_selection respondido antes de salvar doc
            # Exceção: fluxo de attachment (vision já confirmou a imagem, image_selection desnecessário)
            # (a checagem de web-search é feita pelo gate central em execute_tool)
            _IR_QUESTION_DOC = "Extrai algumas imagens do seu produto, qual imagem você prefere usar como referência?"
            if _is_variation_flow and self.db_manager and self.current_chat_id:
                try:
                    from App.Core.Crunch.TablesSQL.Models import (
                        IsolatedMessage as _IMdoc,
                    )

                    _sdoc = self.db_manager.get_session()
                    try:
                        # Detectar fluxo de attachment: quiz com attachment=true + vision executado
                        _attach_quiz_doc = (
                            _sdoc.query(_IMdoc)
                            .filter(
                                _IMdoc.isolated_chat_id == self.current_chat_id,
                                _IMdoc.tool_called == "quiz",
                                _IMdoc.tool_call_type == "input",
                                _IMdoc.content.ilike('%"attachment": true%'),
                            )
                            .order_by(_IMdoc.id.asc())
                            .first()
                        )
                        if not _attach_quiz_doc:
                            _attach_quiz_doc = (
                                _sdoc.query(_IMdoc)
                                .filter(
                                    _IMdoc.isolated_chat_id == self.current_chat_id,
                                    _IMdoc.tool_called == "quiz",
                                    _IMdoc.tool_call_type == "input",
                                    _IMdoc.content.ilike('%"attachment":true%'),
                                )
                                .order_by(_IMdoc.id.asc())
                                .first()
                            )
                        _is_attachment_doc = False
                        if _attach_quiz_doc:
                            _vision_doc = (
                                _sdoc.query(_IMdoc)
                                .filter(
                                    _IMdoc.isolated_chat_id == self.current_chat_id,
                                    _IMdoc.tool_called == "vision",
                                    _IMdoc.tool_call_type == "output",
                                    _IMdoc.id > _attach_quiz_doc.id,
                                )
                                .first()
                            )
                            _is_attachment_doc = _vision_doc is not None

                        _img_quiz_input = (
                            _sdoc.query(_IMdoc)
                            .filter(
                                _IMdoc.isolated_chat_id == self.current_chat_id,
                                _IMdoc.tool_called == "quiz",
                                _IMdoc.tool_call_type == "input",
                                _IMdoc.content.ilike("%image_selection%"),
                            )
                            .order_by(_IMdoc.id.desc())
                            .first()
                        )
                        _img_quiz_answered = (
                            _is_attachment_doc  # attachment dispensa image_selection
                        )
                        if not _img_quiz_answered and _img_quiz_input:
                            _img_quiz_out = (
                                _sdoc.query(_IMdoc)
                                .filter(
                                    _IMdoc.isolated_chat_id == self.current_chat_id,
                                    _IMdoc.tool_called == "quiz",
                                    _IMdoc.tool_call_type == "output",
                                    _IMdoc.id > _img_quiz_input.id,
                                    ~_IMdoc.content.ilike('%"success": false%'),
                                )
                                .first()
                            )
                            _img_quiz_answered = _img_quiz_out is not None
                    finally:
                        _sdoc.close()

                    if not _img_quiz_answered:
                        return json.dumps(
                            {
                                "success": False,
                                "error": "Execute o quiz de confirmação da imagem antes de salvar o documento de variação.",
                                "hint": f"Execute: quiz([{{question: '{_IR_QUESTION_DOC}', type: 'image_selection', options: ['<url1.jpg>', ...]}}])",
                                "tool": "document",
                                "correction_required": [
                                    {
                                        "step": 1,
                                        "call": {
                                            "tool": "quiz",
                                            "quiz": [
                                                {
                                                    "question": _IR_QUESTION_DOC,
                                                    "type": "image_selection",
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
                            },
                            ensure_ascii=False,
                        )
                except Exception as _dge:
                    debug(f"[DOCUMENT] Erro ao verificar gate image_selection: {_dge}")

            if not _is_variation_flow:
                #  GATE DESATIVADO: VERIFICAR SE DOCUMENTOS REQUERIDOS EXISTEM (business_canvas + brand_communication + product)
                pass
                # has_required_docs, doc_status = self._check_required_documents_exist(
                #     required_types=["business_canvas", "brand_communication", "product"]
                # )
                # if not has_required_docs:
                #     missing_docs = [
                #         t
                #         for t in ["business_canvas", "brand_communication", "product"]
                #         if not doc_status.get(t)
                #     ]
                #     return json.dumps(
                #         {
                #             "success": False,
                #             "error": f"Crie {', '.join(missing_docs)} antes de criar o copywriting",
                #             "hint": "O copywriting exige business_canvas, brand_communication e product criados primeiro.",
                #             "tool": "document",
                #             "type": doc_type,
                #             "title": title,
                #             "status": "rejected",
                #         },
                #         ensure_ascii=False,
                #     )

            #  VERIFICAR LOOKUPS OBRIGATRIOS: SkillCopywriting apenas (Caption foi integrado)
            missing_lookups = []
            if not self._check_copywriting_lookup_in_chat():
                missing_lookups.append("SkillCopywriting.md")

            if missing_lookups:
                return json.dumps(
                    {
                        "success": False,
                        "error": "Faa o lookup de SkillCopywriting.md antes de criar o copywriting",
                        "hint": "Execute lookup(file='SkillCopywriting.md') para carregar a skill.",
                        "tool": "document",
                        "type": doc_type,
                        "title": title,
                        "status": "rejected",
                    },
                    ensure_ascii=False,
                )

            #  VERIFICAR QUIZ DE COPYWRITING
            if not self._check_copywriting_quiz_in_chat():
                return json.dumps(
                    {
                        "success": False,
                        "error": "Execute o quiz de Copywriting antes de criar o documento",
                        "hint": "O quiz deve conter: (a) quantos assets o usurio quer e (b) o que deseja validar  headline, ngulos, cores, estilos ou deixar para a IA decidir.",
                        "tool": "document",
                        "type": doc_type,
                        "title": title,
                        "status": "rejected",
                    },
                    ensure_ascii=False,
                )

            if not data:
                return json.dumps(
                    {
                        "success": False,
                        "error": "data (JSON estruturado)  obrigatrio para copywriting",
                        "tool": "document",
                    }
                )

            # Validar estrutura do copywriting
            validation_result = self._validate_copy_json(data)
            warnings_list = validation_result.get("warnings", [])
            valid_data = validation_result.get("data", {})
            gate_error = validation_result.get("error")
            _missing_vars = validation_result.get("missing_variations", [])

            #  REJEITAR se gate de contexto bloqueou (brand_communication / product no consultados)
            if gate_error and not warnings_list:
                return json.dumps(
                    {
                        "success": False,
                        "error": "Consulte os documentos obrigatrios antes de criar o copywriting.",
                        "tool": "document",
                        "type": doc_type,
                        "title": title,
                        "status": "rejected",
                        "hint": gate_error,
                    },
                    ensure_ascii=False,
                )

            #  REJEITAR se h warnings (validao falhou)
            if warnings_list:
                correction_instructions = []
                field_examples = {
                    "is_paid_ad": "true ou false",
                    "aspect_ratio": "9:16, 16:9, 1:1, ou 4:5",
                    "framework": "SLAP, ACC, 4CS, PAS, AIDA ou FAB",
                    # Narrative & StoryBrand (sempre obrigatrios)
                    "hypothesy": "Hiptese do copywriting (string)",
                    "problem": "Problema especfico do ICP (string)",
                    "solution": "Como sua soluo resolve (string)",
                    "transformation": "Antes  Depois (string)",
                    "hook_pain_awareness": "Ato 1: Gancho + Dor (string) - Exemplo: 'Voc acorda cansado mesmo dormindo 8h?'",
                    "empathy": "Ato 2: Empatia (string) - Exemplo: 'Eu sei como , j passei por isso'",
                    "autority": "Ato 3: Autoridade (string) - Exemplo: 'Depois de analisar 300+ pacientes...'",
                    "solution_contious": "Ato 4: Soluo (string) - Exemplo: 'A resposta  regular seu cortisol'",
                    "product_contious": "Ato 5: Produto (string) - Exemplo: 'Criamos o X: Magnsio + Ashwagandha + D3'",
                    "offer_concious": "Ato 6: Oferta (string) - Exemplo: 'Hoje 30% OFF. Apenas 48h'",
                    # Framework-specific fields
                    "stop_hook": "[SLAP] Hook para parar: 'Voc acorda cansado mesmo dormindo bem?'",
                    "look_proposition": "[SLAP] Proposio: 'Magnsio + Ashwagandha regulam cortisol em 7 dias'",
                    "act_urgency": "[SLAP] Urgncia: 'Apenas 48h com 30% OFF'",
                    "purchase_cta": "[SLAP] CTA: 'Compre agora no link da bio'",
                    "awareness_problem": "[ACC] Problema: 'Fadiga constante no  normal'",
                    "comprehension_explanation": "[ACC] Explicao: 'Inflamao silenciosa causa cansao'",
                    "conversion_solution": "[ACC] Soluo: 'Cortisol Balance resolve em 7 dias'",
                    "clear_message": "[4CS] Mensagem clara: sem jargo, direto",
                    "concise_copy": "[4CS] Conciso: mxima informao, mnimas palavras",
                    "compelling_angle": "[4CS] Compelling: gera desejo, no apenas informa",
                    "credible_proof": "[4CS] Prova: dados, estudos, depoimentos reais",
                    "agitate": "[PAS] Agitar: aprofundar a dor do problema",
                    "caption": "Caption do post (string - pode ser simples ou JSON estruturado)",
                    "assets": "Array com mnimo 1 asset: [{asset_type: 'img', prompt: {description: '...', has_realistic_people: false, composition: {angle: 'EyeLevelShot', grid: 'Centralized'}, environment: {place: '...', objects: [...]}, colors: {background: {hex: ['#FFF'], bg_type: 'studio'}, subject: {hex: ['#000']}, accent: {hex: ['#FFF']}, saturation_contrast: '...', harmony: 'Complementary'}, illumination: '...', emotion_style: '...'}}]",
                    "attention": "[AIDA] Ateno: captura interesse em 2-3 segundos",
                    "interest": "[AIDA] Interesse: mantm engajamento",
                    "desire": "[AIDA] Desejo: cria vontade de comprar",
                    "action": "[AIDA] Ao: CTA claro e direto",
                    "features": "[FAB] Features: caractersticas do produto",
                    "advantages": "[FAB] Vantagens: por que  melhor que concorrentes",
                    "benefits": "[FAB] Benefcios: ganho real do cliente",
                }

                for warning in warnings_list:
                    if "missing: document_id" in warning:
                        correction_instructions.append(
                            "DOCUMENT_ID OBRIGATRIO: Informe o document_id do produto (no obrigatrio apenas para branding). Use context(type='documents') para obter o ID correto."
                        )
                    elif "missing: task_id" in warning or "missing: step_id" in warning:
                        # Agora  opcional, mas se o agente tentar e falhar, damos o hint
                        correction_instructions.append(
                            f"VNCULO COM TASK: {warning}. Use context(type='tasks') para obter os IDs ou remova task_id/step_id para salvar sem vnculo."
                        )
                    elif "missing: is_paid_ad" in warning:
                        correction_instructions.append(
                            "IS_PAID_AD OBRIGATRIO: Informe se  anncio pago (true ou false)."
                        )
                    elif "missing: channels" in warning:
                        correction_instructions.append(
                            f"CHANNELS OBRIGATRIO: Informe uma lista de canais (ex: ['instagram', 'facebook']). Opes: {', '.join(self.COPY_CHANNELS)}"
                        )
                    elif "missing: framework" in warning:
                        correction_instructions.append(
                            f"FRAMEWORK OBRIGATRIO: Escolha uma estratgia: {', '.join(self.COPY_FRAMEWORK_VALUES)}"
                        )
                    elif "missing: archetype" in warning:
                        correction_instructions.append(
                            "ARCHETYPE OBRIGATRIO: Use o arqutipo definido no documento brand_communication."
                        )
                    elif "missing: moodboard" in warning:
                        correction_instructions.append(
                            "MOODBOARD OBRIGATRIO: Use o moodboard definido no documento brand_communication."
                        )
                    elif "missing: caption" in warning:
                        correction_instructions.append(
                            "CAPTION OBRIGATRIO: Adicione a legenda do post."
                        )
                    elif "missing: assets" in warning and "].prompt (" in warning:
                        # prompt em si no  objeto ( string ou ausente)
                        correction_instructions.append(
                            "PROMPT DO ASSET INVLIDO: O campo 'prompt' deve ser um OBJETO JSON, NO uma string. "
                            'Estrutura obrigatria: {"description": "...", "has_realistic_people": false, '
                            '"composition": {"angle": "EyeLevelShot", "grid": "Centralized"}, '
                            '"environment": {"place": "...", "objects": ["..."]}, '
                            '"colors": {"background": {"hex": ["#FFF"], "bg_type": "studio"}, '
                            '"subject": {"hex": ["#000"]}, "accent": {"hex": ["#FFF"]}, '
                            '"saturation_contrast": "...", "harmony": "Complementary"}, '
                            '"illumination": "...", "emotion_style": "..."}'
                        )
                    elif "missing: assets" in warning and "].prompt." in warning:
                        # sub-campo do prompt ausente  passa o warning bruto para o agente
                        correction_instructions.append(str(warning))
                    elif "missing: assets" in warning:
                        correction_instructions.append(
                            "ASSETS OBRIGATRIO: Adicione pelo menos 1 asset com asset_type='img' e prompt como OBJETO estruturado (no string)."
                        )
                    elif "invalid:" in warning:
                        field = (
                            warning.split("invalid:")[-1].strip().split("(")[0].strip()
                        )
                        detail = (
                            warning.split("(")[-1].rstrip(")")
                            if "(" in warning
                            else warning
                        )
                        correction_instructions.append(
                            f"{field.upper()} INVLIDO  {detail}"
                        )
                    else:
                        correction_instructions.append(str(warning))

                return json.dumps(
                    {
                        "success": False,
                        "error": "Ajuste as informacoes necessarias no Copywriting",
                        "hint": f"{len(warnings_list)} campo(s) com problema: {'; '.join(correction_instructions)}",
                        "tool": "document",
                        "type": doc_type,
                        "title": title,
                        "status": "rejected",
                        "correction_required": correction_instructions,
                    },
                    ensure_ascii=False,
                )

            # Atribuir format e source_idx em cada asset (sempre um único formato por geração)
            _already_variation_expanded = bool(
                valid_data.get("variation", {}).get("count", 0)
            )
            _formats = valid_data.get("aspect_ratio", [])
            if isinstance(_formats, str):
                _formats = [_formats]
            _base_assets = valid_data.get("assets", [])
            if not _already_variation_expanded and _formats and _base_assets:
                for _src_idx, _asset in enumerate(_base_assets):
                    _asset["format"] = _formats[0]
                    _asset["source_idx"] = _src_idx

            # Guardar step_id para auto-completar aps save
            _step_id_to_complete = valid_data.get("step_id")

            # Converter data validada para JSON string
            content = json.dumps(valid_data, ensure_ascii=False)

        elif doc_type == "social_media":
            if not data:
                return json.dumps(
                    {
                        "success": False,
                        "error": "data e obrigatorio para social_media",
                        "tool": "document",
                    }
                )
            _valid_formats = ["story", "carrossel", "photo"]
            if data.get("format") not in _valid_formats:
                return json.dumps(
                    {
                        "success": False,
                        "error": f"format deve ser um de: {', '.join(_valid_formats)}",
                        "hint": "story=9:16 | carrossel=4:5 | photo=1:1 ou 4:5",
                        "tool": "document",
                    }
                )
            if not data.get("channels"):
                return json.dumps(
                    {
                        "success": False,
                        "error": "channels e obrigatorio",
                        "tool": "document",
                    }
                )
            if not data.get("assets"):
                return json.dumps(
                    {
                        "success": False,
                        "error": "assets e obrigatorio (minimo 1)",
                        "tool": "document",
                    }
                )
            valid_data = data
            content = json.dumps(valid_data, ensure_ascii=False)

        elif doc_type == "catalog":
            if not data:
                return json.dumps(
                    {
                        "success": False,
                        "error": "data é obrigatório para catalog",
                        "tool": "document",
                    }
                )

            # Validate using the same structured format as copywriting
            catalog_validation = self._validate_catalog_json(data)
            catalog_warnings = catalog_validation.get("warnings", [])
            valid_data = catalog_validation.get("data", {})
            catalog_error = catalog_validation.get("error")

            if catalog_warnings:
                _correction = []
                for w in catalog_warnings:
                    if "product_category" in w:
                        _correction.append(
                            "PRODUCT_CATEGORY OBRIGATÓRIO: clothing, cosmetics, accessories, real_estate, automotive, pet ou retail."
                        )
                    elif "aspect_ratio" in w:
                        _correction.append(
                            "ASPECT_RATIO OBRIGATÓRIO: '9:16', '16:9', '1:1' ou '4:5'."
                        )
                    elif "assets" in w and ".prompt." in w:
                        _correction.append(str(w))
                    elif "assets" in w:
                        _correction.append(
                            "ASSETS OBRIGATÓRIO: array com pelo menos 1 asset com asset_type='img' e prompt estruturado (description, composition, environment, colors, illumination, emotion_style)."
                        )
                    else:
                        _correction.append(str(w))

                return json.dumps(
                    {
                        "success": False,
                        "error": "Ajuste os campos do catalog antes de salvar",
                        "hint": f"{len(catalog_warnings)} campo(s) com problema: {'; '.join(_correction)}",
                        "tool": "document",
                        "type": doc_type,
                        "title": title,
                        "status": "rejected",
                        "correction_required": _correction,
                    },
                    ensure_ascii=False,
                )

            # Assign format and source_idx to each asset
            _formats = valid_data.get("aspect_ratio", [])
            if isinstance(_formats, str):
                _formats = [_formats]
            _base_assets = valid_data.get("assets", [])
            if _formats and _base_assets:
                for _src_idx, _asset in enumerate(_base_assets):
                    _asset["format"] = _formats[0]
                    _asset["source_idx"] = _src_idx

            content = json.dumps(valid_data, ensure_ascii=False)

        elif doc_type == "self_knowledge":
            if not data:
                return json.dumps(
                    {
                        "success": False,
                        "error": "data e obrigatorio para self_knowledge",
                        "tool": "document",
                    }
                )
            if not data.get("brand_name"):
                return json.dumps(
                    {
                        "success": False,
                        "error": "brand_name e obrigatorio",
                        "tool": "document",
                    }
                )
            if not data.get("brand_story"):
                return json.dumps(
                    {
                        "success": False,
                        "error": "brand_story e obrigatorio",
                        "tool": "document",
                    }
                )
            valid_data = data
            content = json.dumps(valid_data, ensure_ascii=False)

        else:
            # Para outros tipos, content  obrigatrio
            if not content:
                return json.dumps(
                    {
                        "success": False,
                        "error": f"content  obrigatrio para type '{doc_type}'",
                        "tool": "document",
                    }
                )

        try:
            # Validar contexto
            if (
                not self.current_user_id
                or not self.current_chat_id
                or not self.db_manager
            ):
                return json.dumps(
                    {
                        "success": False,
                        "error": "Contexto de chat ou banco de dados no disponvel",
                        "tool": "document",
                    }
                )

            # Todos os tipos salvam com current_chat_id
            # A reutilizao de business_canvas e visual_communication entre chats
            #  feita na LEITURA (/get/chat/:chat_id filtra por user_id para tipos globais)
            chat_id = self.current_chat_id

            # MODO MERGE: completar documento parcial já salvo
            _merge_document_id = args.get("document_id", "").strip() if args else ""
            if _merge_document_id:
                # Carregar documento existente do banco
                try:
                    _merge_session = self.db_manager.get_session()
                    try:
                        from sqlalchemy import text as _mtext

                        _merge_row = _merge_session.execute(
                            _mtext(
                                "SELECT content FROM documents WHERE document_id = :did AND user_id = :uid AND tool_type = 'copywriting'"
                            ),
                            {"did": _merge_document_id, "uid": self.current_user_id},
                        ).fetchone()
                    finally:
                        _merge_session.close()
                except Exception as _me:
                    _merge_row = None

                if _merge_row:
                    try:
                        _existing = json.loads(_merge_row[0])
                    except Exception:
                        _existing = {}
                    # Merge: sobrepor apenas os variation_N novos
                    _var_total = _existing.get("variation", {}).get("count", 0)
                    for _mvi in range(1, _var_total + 1):
                        _mvk = f"variation_{_mvi}"
                        if _mvk in valid_data:
                            _existing[_mvk] = valid_data[_mvk]
                    # Re-calcular missing_variations após merge
                    _missing_vars = [
                        _mvi
                        for _mvi in range(1, _var_total + 1)
                        if not _existing.get(f"variation_{_mvi}")
                    ]
                    # Atualizar valid_data com o merged
                    valid_data = _existing
                    # UPDATE no banco
                    _upd_session = self.db_manager.get_session()
                    try:
                        from sqlalchemy import text as _utext

                        _upd_session.execute(
                            _utext(
                                "UPDATE documents SET content = :content, updated_at = CURRENT_TIMESTAMP WHERE document_id = :did"
                            ),
                            {
                                "content": json.dumps(valid_data, ensure_ascii=False),
                                "did": _merge_document_id,
                            },
                        )
                        _upd_session.commit()
                    finally:
                        _upd_session.close()

                    document_id = _merge_document_id  # reusar o mesmo ID
                    # Pular INSERT abaixo
                    _skip_insert = True
                else:
                    _skip_insert = False
            else:
                _skip_insert = False

            # Gerar ID nico para o documento
            if not _skip_insert:
                document_id = str(uuid_lib.uuid4())

            session = self.db_manager.get_session() if not _skip_insert else None
            try:
                if not _skip_insert:
                    from sqlalchemy import text

                    # Obter client_id do usurio
                    user = (
                        session.query(User)
                        .filter(User.user_id == self.current_user_id)
                        .first()
                    )
                    client_id = user.client_id if user else None

                    # Salvar documento diretamente na tabela documents
                    insert_query = text(
                        """
                        INSERT INTO documents (document_id, chat_id, user_id, client_id, title, content, extension, tool_type, created_at, updated_at)
                        VALUES (:document_id, :chat_id, :user_id, :client_id, :title, :content, :extension, :tool_type, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """
                    )

                    # Extenso baseada no tipo de documento
                    extension = (
                        "json"
                        if doc_type
                        in [
                            "business_canvas",
                            "brand_communication",
                            "copywriting",
                            "product",
                        ]
                        else "md"
                    )

                    session.execute(
                        insert_query,
                        {
                            "document_id": document_id,
                            "chat_id": chat_id,
                            "user_id": self.current_user_id,
                            "client_id": client_id,
                            "title": title,
                            "content": content,
                            "extension": extension,
                            "tool_type": doc_type,
                        },
                    )

                    session.flush()
                    session.commit()
                    debug(
                        f"[DOCUMENT] Documento ({doc_type}) salvo: {title} ({len(content)} chars) - ID: {document_id}"
                    )

                    #  Registrar evento de lifecycle (apenas canvas e brand  copywriting  intermedirio)
                    try:
                        if doc_type in ("business_canvas", "brand_communication"):
                            from App.Features.Tracking.LifecycleTracker import (
                                LifecycleTracker,
                            )

                            event = (
                                "business_canvas_created"
                                if doc_type == "business_canvas"
                                else "brand_identity_created"
                            )
                            LifecycleTracker.track(
                                user_id=self.current_user_id,
                                event_type=event,
                                chat_id=self.current_chat_id,
                                metadata={"document_id": document_id},
                            )
                    except Exception as lifecycle_error:
                        error(
                            f"[LIFECYCLE] Erro ao registrar {doc_type}: {lifecycle_error}"
                        )

                    # Sincronizar brand_communication → tabela brands (por cliente)
                    if doc_type == "brand_communication" and client_id:
                        try:
                            from App.Core.Crunch.TablesSQL.Models import Brand
                            from datetime import datetime as _brand_dt

                            _existing_brand = (
                                session.query(Brand)
                                .filter(Brand.client_id == client_id)
                                .first()
                            )
                            if _existing_brand:
                                _existing_brand.data = valid_data
                                _existing_brand.chat_id = self.current_chat_id
                                _existing_brand.version = (
                                    _existing_brand.version or 0
                                ) + 1
                                _existing_brand.updated_at = _brand_dt.utcnow()
                            else:
                                _new_brand = Brand(
                                    client_id=client_id,
                                    chat_id=self.current_chat_id,
                                    data=valid_data,
                                    version=1,
                                )
                                session.add(_new_brand)
                            session.commit()
                            debug(
                                f"[Brand] brand_communication sincronizado para client {client_id}"
                            )
                        except Exception as _brand_err:
                            warning(f"[Brand] Falha ao sincronizar brand: {_brand_err}")

                    # Auto-marcar step como concludo (copywriting vincula step_id)
                    if _step_id_to_complete:
                        try:
                            from App.Core.Crunch.TablesSQL.Models import (
                                Task as _TaskModelSave,
                            )
                            from datetime import datetime as _dt

                            _step = (
                                session.query(_TaskModelSave)
                                .filter(_TaskModelSave.step_id == _step_id_to_complete)
                                .first()
                            )
                            if _step:
                                _step.status = "success"
                                _step.completed_at = _dt.utcnow()
                                session.commit()
                                debug(
                                    f"[DOCUMENT] Step {_step_id_to_complete} marcado como success"
                                )
                        except Exception as _step_err:
                            error(
                                f"[DOCUMENTO] Erro ao marcar step como done: {_step_err}"
                            )

                # Documento salvo com sucesso
                response = {
                    "success": True,
                    "tool": "document",
                    "type": doc_type,
                    "id": document_id,
                    "title": title,
                    "status": "saved",
                }

                if doc_type == "copywriting":
                    if _missing_vars:
                        # Documento parcial — não acionar gate de asset ainda
                        self._pending_document_id = document_id
                        self._pending_document_partial = True
                        _first_missing = f"variation_{_missing_vars[0]}"
                        _missing_labels = ", ".join(
                            f"variation_{v}" for v in _missing_vars
                        )
                        response["success"] = False
                        response["status"] = "partial"
                        response["missing_variations"] = _missing_vars
                        response["next_action"] = {
                            "tool": "document",
                            "document_id": document_id,
                            "hint": f"Continue from {_first_missing} using the same document_id",
                        }
                        response["message"] = (
                            f"Accepted content (Continue from {_first_missing} using document_id '{document_id}'): "
                            f"document(document_id='{document_id}', data={{'{_first_missing}': {{...}}}})"
                        )
                        response[
                            "warning"
                        ] = f"Variações faltantes: {_missing_labels}. Complete-as antes de gerar os assets."
                    else:
                        # Documento completo
                        self._pending_document_id = document_id
                        self._pending_document_partial = False
                        response["next_action"] = {
                            "OBRIGATÓRIO": f"CHAME IMEDIATAMENTE asset(document_id='{document_id}') para gerar os assets.",
                            "tool": "asset",
                            "document_id": document_id,
                            "warning": "NÃO execute outra tool antes de chamar asset(). O documento foi salvo mas os assets ainda não foram gerados.",
                        }

                return json.dumps(response, ensure_ascii=False)

            finally:
                if session:
                    session.close()

        except Exception as e:
            error(f"[DOCUMENT] Erro ao salvar documento ({doc_type}) {title}: {e}")
            return json.dumps({"success": False, "error": str(e), "tool": "document"})

    def _check_required_documents_exist(
        self, required_types: list = None
    ) -> tuple[bool, dict]:
        """
        Verifica se os documentos required_types existem para o usurio atual.
        Default: business_canvas + brand_communication.
        """
        if required_types is None:
            required_types = ["brand_communication", "business_canvas"]

        if not self.db_manager or not self.current_user_id:
            return False, {}

        try:
            session = self.db_manager.get_session()
            try:
                from sqlalchemy import text

                placeholders = ", ".join(f"'{t}'" for t in required_types)
                query = text(
                    f"""
                    SELECT tool_type, COUNT(*) as count
                    FROM documents
                    WHERE user_id = :user_id
                    AND tool_type IN ({placeholders})
                    GROUP BY tool_type
                """
                )
                results = session.execute(
                    query, {"user_id": self.current_user_id}
                ).fetchall()

                doc_info = {t: False for t in required_types}
                for row in results:
                    doc_info[row[0]] = row[1] > 0

                has_all = all(doc_info.values())
                return has_all, doc_info

            finally:
                session.close()
        except Exception as e:
            debug(f"[VALIDATE] Erro ao verificar documentos requeridos: {e}")
            return False, {}

    def _get_documents_list(self) -> str:
        """
        Lista todos os documentos salvos na tabela documents.

        Returns:
            JSON com lista de documentos
        """
        if not self.current_user_id or not self.current_chat_id or not self.db_manager:
            return json.dumps(
                {
                    "success": True,
                    "tool": "document",
                    "documents": {},
                    "message": "Nenhum documento salvo ainda",
                },
                ensure_ascii=False,
            )

        try:
            session = self.db_manager.get_session()
            try:
                from sqlalchemy import text

                # Buscar todos os documentos deste chat
                query = text(
                    """
                    SELECT document_id, title, LENGTH(content) as content_size, created_at
                    FROM documents
                    WHERE user_id = :user_id AND chat_id = :chat_id
                    ORDER BY created_at DESC
                """
                )

                results = session.execute(
                    query,
                    {"user_id": self.current_user_id, "chat_id": self.current_chat_id},
                ).fetchall()

                documents = {}
                for row in results:
                    doc_id, title, size, created_at = row
                    documents[title] = {
                        "id": doc_id,
                        "name": title,
                        "size": size,
                        "created_at": str(created_at) if created_at else None,
                    }

                return json.dumps(
                    {
                        "success": True,
                        "tool": "document",
                        "total": len(documents),
                        "documents": documents,
                        "message": f"Total de {len(documents)} documento(s) salvo(s)",
                    },
                    ensure_ascii=False,
                )

            finally:
                session.close()

        except Exception as e:
            debug(f"[DOCUMENT-HELP] Erro ao listar documentos: {e}")
            return json.dumps({"success": False, "tool": "document", "error": str(e)})

    def _get_document_by_id(self, document_id: str) -> str:
        """Retorna o contedo completo de um documento especfico pelo ID."""
        if not self.current_user_id or not self.db_manager:
            return json.dumps(
                {"success": False, "error": "Contexto no disponvel", "tool": "context"},
                ensure_ascii=False,
            )
        try:
            from sqlalchemy import text as _text

            _sess = self.db_manager.get_session()
            try:
                _row = _sess.execute(
                    _text(
                        "SELECT document_id, title, content, tool_type, created_at "
                        "FROM documents WHERE document_id = :did AND user_id = :uid"
                    ),
                    {"did": document_id, "uid": self.current_user_id},
                ).fetchone()
            finally:
                _sess.close()
            if not _row:
                return json.dumps(
                    {
                        "success": False,
                        "error": f"Documento '{document_id}' no encontrado.",
                        "hint": "Use context(type='documents') para listar os IDs disponveis.",
                        "tool": "context",
                    },
                    ensure_ascii=False,
                )
            doc_id, title, content, tool_type, created_at = _row
            try:
                content_parsed = json.loads(content) if content else {}
            except Exception:
                content_parsed = content
            return json.dumps(
                {
                    "success": True,
                    "tool": "context",
                    "type": "document",
                    "document_id": doc_id,
                    "title": title,
                    "document_type": tool_type,
                    "created_at": str(created_at) if created_at else None,
                    "content": content_parsed,
                },
                ensure_ascii=False,
            )
        except Exception as e:
            return json.dumps(
                {"success": False, "error": str(e), "tool": "context"},
                ensure_ascii=False,
            )

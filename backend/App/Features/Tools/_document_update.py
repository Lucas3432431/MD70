"""
_document_update.py — Mixin extraído de Core.py.
Core.py importa este módulo e herda DocumentUpdateMixin.
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


class DocumentUpdateMixin:
    def _execute_update(self, args: Dict[str, Any]) -> str:
        """
        Executa tool 'update' para editar contedo de documentos, calendrios, clientes e tarefas.

        Args:
            args: Dict com:
                - type: 'document' | 'calendar' | 'client' | 'task' (obrigatrio)
                - id: UUID do item a editar (obrigatrio)

                Para 'document' e 'client':
                  - old_content: contedo anterior (obrigatrio - para saber onde inserir)
                  - new_content: novo contedo (obrigatrio)

                Para 'calendar':
                  - action: 'reschedule' | 'remove' (obrigatrio)
                  - new_date: dd/mm/aaaa (obrigatrio se action='reschedule')

                Para 'task':
                  - step_name: Nome exato do step (obrigatrio)
                  - field: Campo a atualizar: 'status', 'step_name', 'step_context', 'task_name', etc. (obrigatrio)
                  - value: Novo valor para o campo (obrigatrio se field != 'delete')
                  - Para delete: field='delete'

        Returns:
            JSON com status de sucesso e informaes da edio
        """
        try:
            update_type = args.get("type", "").strip().lower()
            item_id = args.get("id", "").strip()

            # Validar campos obrigatrios bsicos
            if not update_type or not item_id:
                return json.dumps(
                    {
                        "success": False,
                        "tool": "update",
                        "error": "Campos obrigatrios faltando: type e id",
                    },
                    ensure_ascii=False,
                )

            # Validar tipo
            if update_type not in self.UPDATE_VALID_TYPES:
                return json.dumps(
                    {
                        "success": False,
                        "tool": "update",
                        "error": f"Tipo invlido '{update_type}'. Use: {', '.join(self.UPDATE_VALID_TYPES)}",
                    },
                    ensure_ascii=False,
                )

            # ============================================================================
            # DOCUMENT: Editar contedo do documento (markdown) ou campos JSON (business_canvas)
            # ============================================================================
            if update_type == "document":
                doc_type = args.get("doc_type", "").strip().lower()
                updates_list = args.get("updates", [])

                # NOVO: Business Canvas - field-by-field updates
                if doc_type == "business_canvas" and updates_list:
                    if not isinstance(updates_list, list) or len(updates_list) == 0:
                        return json.dumps(
                            {
                                "success": False,
                                "tool": "update",
                                "type": "document",
                                "doc_type": "business_canvas",
                                "error": "updates must be a non-empty array of {field: ..., value: ...}",
                            },
                            ensure_ascii=False,
                        )

                    debug(
                        f"[UPDATE] Atualizando business_canvas: {item_id} com {len(updates_list)} campos"
                    )

                    try:
                        if not self.db_manager:
                            return json.dumps(
                                {
                                    "success": False,
                                    "tool": "update",
                                    "type": "document",
                                    "doc_type": "business_canvas",
                                    "error": "Database manager not configured",
                                },
                                ensure_ascii=False,
                            )

                        session = self.db_manager.get_session()
                        try:
                            from sqlalchemy import text

                            # Buscar documento business_canvas
                            query = text(
                                """
                                SELECT document_id, title, content FROM documents
                                WHERE document_id = :document_id AND tool_type = 'business_canvas'
                            """
                            )
                            result = session.execute(
                                query, {"document_id": item_id}
                            ).first()

                            if not result:
                                return json.dumps(
                                    {
                                        "success": False,
                                        "tool": "update",
                                        "type": "document",
                                        "doc_type": "business_canvas",
                                        "error": f"Business canvas with ID {item_id} not found",
                                    },
                                    ensure_ascii=False,
                                )

                            document_id, title, content = result

                            # Parse current JSON
                            try:
                                current_data = json.loads(content) if content else {}
                            except json.JSONDecodeError:
                                current_data = {}

                            # Apply updates
                            updated_data = current_data.copy()
                            updated_fields = []

                            for update_item in updates_list:
                                if not isinstance(update_item, dict):
                                    continue

                                field_path = update_item.get("field", "").strip()
                                value = update_item.get("value")

                                if not field_path:
                                    continue

                                # Support nested fields like "pocket.total_budget_r"
                                parts = field_path.split(".")
                                current = updated_data

                                # Navigate to parent
                                for part in parts[:-1]:
                                    if part not in current:
                                        current[part] = {}
                                    current = current[part]

                                # Set final value
                                current[parts[-1]] = value
                                updated_fields.append(field_path)

                            # Validate merged data
                            validation_result = self._validate_business_canvas_json(
                                updated_data
                            )
                            warnings = validation_result.get("warnings", [])
                            valid_data = validation_result.get("data", {})

                            #  CRTICO: Se h ANY warnings aps update, REJEITAR
                            if warnings:
                                correction_instructions = []
                                for warning in warnings:
                                    if "missing: firmografia" in warning:
                                        correction_instructions.append(
                                            ' FIRMOGRAFIA FALTANDO: Adicione {"annual_revenue": 1000000, "sector": "...", "employees": 10, "digital_maturity": "Intermediria", "technology": "..."}'
                                        )
                                    elif "market_sizing.tam" in warning:
                                        correction_instructions.append(
                                            " MARKET_SIZING.TAM INVLIDO: Deve ser nmero inteiro (ex: 50000000000)"
                                        )
                                    elif "market_sizing.sam" in warning:
                                        correction_instructions.append(
                                            " MARKET_SIZING.SAM INVLIDO: Deve ser nmero inteiro (ex: 3000000000)"
                                        )
                                    elif "market_sizing.som" in warning:
                                        correction_instructions.append(
                                            " MARKET_SIZING.SOM INVLIDO: Deve ser nmero inteiro (ex: 60000000)"
                                        )
                                    elif "product_pricing" in warning:
                                        correction_instructions.append(
                                            ' POCKET.PRODUCT_PRICING INVLIDO: Deve ser ["valor", "percentual%"] ex: ["5000", "10%"]'
                                        )
                                    else:
                                        correction_instructions.append(f" {warning}")

                                return json.dumps(
                                    {
                                        "success": False,
                                        "tool": "update",
                                        "type": "document",
                                        "doc_type": "business_canvas",
                                        "id": item_id,
                                        "title": title,
                                        "status": "rejected_incomplete",
                                        "errors": warnings,
                                        "attempted_fields": updated_fields,
                                        "correction_required": [
                                            " UPDATE REJEITADO - Campos invlidos ou faltando.",
                                            "",
                                            " CORRIJA IMEDIATAMENTE:",
                                            *correction_instructions,
                                            "",
                                            " Tente novamente com os campos COMPLETOS e VLIDOS.",
                                        ],
                                        "message": f"Update rejeitado: {len(warnings)} campo(s) invlido(s). Corrija os campos e reenvia.",
                                    },
                                    ensure_ascii=False,
                                )

                            updated_content = json.dumps(valid_data, ensure_ascii=False)

                            # Update in database (s se passou na validao)
                            update_query = text(
                                """
                                UPDATE documents SET content = :content, updated_at = CURRENT_TIMESTAMP
                                WHERE document_id = :document_id
                            """
                            )
                            session.execute(
                                update_query,
                                {
                                    "content": updated_content,
                                    "document_id": document_id,
                                },
                            )
                            session.commit()

                            debug(
                                f"[UPDATE] Business canvas updated: {title} - {len(updated_fields)} fields"
                            )

                            response = {
                                "success": True,
                                "tool": "update",
                                "type": "document",
                                "doc_type": "business_canvas",
                                "id": item_id,
                                "title": title,
                                "updated_fields": updated_fields,
                                "message": f"{len(updated_fields)} field(s) updated successfully",
                            }

                            return json.dumps(response, ensure_ascii=False)

                        finally:
                            session.close()

                    except Exception as e:
                        error(f"[UPDATE] Error updating business_canvas: {e}")
                        return json.dumps(
                            {
                                "success": False,
                                "tool": "update",
                                "type": "document",
                                "doc_type": "business_canvas",
                                "error": str(e),
                            },
                            ensure_ascii=False,
                        )

                # Brand Communication - field-by-field updates
                elif doc_type == "brand_communication" and updates_list:
                    if not isinstance(updates_list, list) or len(updates_list) == 0:
                        return json.dumps(
                            {
                                "success": False,
                                "tool": "update",
                                "type": "document",
                                "doc_type": "brand_communication",
                                "error": "updates must be a non-empty array of {field: ..., value: ...}",
                            },
                            ensure_ascii=False,
                        )

                    debug(
                        f"[UPDATE] Atualizando brand_communication: {item_id} com {len(updates_list)} campos"
                    )

                    try:
                        if not self.db_manager:
                            return json.dumps(
                                {
                                    "success": False,
                                    "tool": "update",
                                    "type": "document",
                                    "doc_type": "brand_communication",
                                    "error": "Database manager not configured",
                                },
                                ensure_ascii=False,
                            )

                        session = self.db_manager.get_session()
                        try:
                            from sqlalchemy import text

                            # Buscar documento brand_communication
                            query = text(
                                """
                                SELECT document_id, title, content FROM documents
                                WHERE document_id = :document_id AND tool_type = 'brand_communication'
                            """
                            )
                            result = session.execute(
                                query, {"document_id": item_id}
                            ).first()

                            if not result:
                                return json.dumps(
                                    {
                                        "success": False,
                                        "tool": "update",
                                        "type": "document",
                                        "doc_type": "brand_communication",
                                        "error": f"Brand communication with ID {item_id} not found",
                                    },
                                    ensure_ascii=False,
                                )

                            document_id, title, content = result

                            # Parse current JSON
                            try:
                                current_data = json.loads(content) if content else {}
                            except json.JSONDecodeError:
                                current_data = {}

                            # Apply updates
                            updated_data = current_data.copy()
                            updated_fields = []

                            for update_item in updates_list:
                                if not isinstance(update_item, dict):
                                    continue

                                field_path = update_item.get("field", "").strip()
                                value = update_item.get("value")

                                if not field_path:
                                    continue

                                # Support nested fields like "brand_archetype.archetype"
                                parts = field_path.split(".")
                                current = updated_data

                                # Navigate to parent
                                for part in parts[:-1]:
                                    if part not in current:
                                        current[part] = {}
                                    current = current[part]

                                # Set final value
                                current[parts[-1]] = value
                                updated_fields.append(field_path)

                            # Validate merged data
                            validation_result = self._validate_brand_communication_json(
                                updated_data
                            )
                            warnings = validation_result.get("warnings", [])
                            valid_data = validation_result.get("data", {})

                            #  CRTICO: Se h ANY warnings aps update, REJEITAR
                            if warnings:
                                return json.dumps(
                                    {
                                        "success": False,
                                        "tool": "update",
                                        "type": "document",
                                        "doc_type": "brand_communication",
                                        "id": item_id,
                                        "title": title,
                                        "status": "rejected_incomplete",
                                        "errors": warnings,
                                        "attempted_fields": updated_fields,
                                        "correction_required": [
                                            " UPDATE REJEITADO - Campos invlidos ou faltando.",
                                            "",
                                            " CORRIJA IMEDIATAMENTE os seguintes campos:",
                                            *[f" {w}" for w in warnings],
                                            "",
                                            " Tente novamente com os campos COMPLETOS e VLIDOS.",
                                        ],
                                        "message": f"Update rejeitado: {len(warnings)} campo(s) invlido(s). Corrija e reenvia.",
                                    },
                                    ensure_ascii=False,
                                )

                            updated_content = json.dumps(valid_data, ensure_ascii=False)

                            # Update in database (s se passou na validao)
                            update_query = text(
                                """
                                UPDATE documents SET content = :content, updated_at = CURRENT_TIMESTAMP
                                WHERE document_id = :document_id
                            """
                            )
                            session.execute(
                                update_query,
                                {
                                    "content": updated_content,
                                    "document_id": document_id,
                                },
                            )
                            session.commit()

                            debug(
                                f"[UPDATE] Brand communication updated: {title} - {len(updated_fields)} fields"
                            )

                            response = {
                                "success": True,
                                "tool": "update",
                                "type": "document",
                                "doc_type": "brand_communication",
                                "id": item_id,
                                "title": title,
                                "updated_fields": updated_fields,
                                "message": f"{len(updated_fields)} field(s) updated successfully",
                            }

                            return json.dumps(response, ensure_ascii=False)

                        finally:
                            session.close()

                    except Exception as e:
                        error(f"[UPDATE] Error updating brand_communication: {e}")
                        return json.dumps(
                            {
                                "success": False,
                                "tool": "update",
                                "type": "document",
                                "doc_type": "brand_communication",
                                "error": str(e),
                            },
                            ensure_ascii=False,
                        )

                # Copywriting - field-by-field updates with asset generation trigger
                elif doc_type == "copywriting" and updates_list:
                    if not isinstance(updates_list, list) or len(updates_list) == 0:
                        return json.dumps(
                            {
                                "success": False,
                                "tool": "update",
                                "type": "document",
                                "doc_type": "copywriting",
                                "error": "updates must be a non-empty array of {field: ..., value: ...}",
                            },
                            ensure_ascii=False,
                        )

                    debug(
                        f"[UPDATE] Atualizando copywriting: {item_id} com {len(updates_list)} campos"
                    )

                    try:
                        if not self.db_manager:
                            return json.dumps(
                                {
                                    "success": False,
                                    "tool": "update",
                                    "type": "document",
                                    "doc_type": "copywriting",
                                    "error": "Database manager not configured",
                                },
                                ensure_ascii=False,
                            )

                        session = self.db_manager.get_session()
                        try:
                            from sqlalchemy import text

                            # Buscar documento copywriting
                            query = text(
                                """
                                SELECT document_id, title, content FROM documents
                                WHERE document_id = :document_id AND tool_type = 'copywriting'
                            """
                            )
                            result = session.execute(
                                query, {"document_id": item_id}
                            ).first()

                            if not result:
                                return json.dumps(
                                    {
                                        "success": False,
                                        "tool": "update",
                                        "type": "document",
                                        "doc_type": "copywriting",
                                        "error": f"Copywriting with ID {item_id} not found",
                                    },
                                    ensure_ascii=False,
                                )

                            document_id, title, content = result

                            # Parse current JSON
                            try:
                                current_data = json.loads(content) if content else {}
                            except json.JSONDecodeError:
                                current_data = {}

                            # Apply updates
                            updated_data = current_data.copy()
                            updated_fields = []

                            for update_item in updates_list:
                                if not isinstance(update_item, dict):
                                    continue

                                field_path = update_item.get("field", "").strip()
                                value = update_item.get("value")

                                if not field_path:
                                    continue

                                # Support nested fields like "assets[0].asset_status"
                                parts = field_path.split(".")
                                current = updated_data

                                # Navigate to parent
                                for part in parts[:-1]:
                                    if "[" in part and "]" in part:
                                        # Handle array indices like "assets[0]"
                                        key = part[: part.index("[")]
                                        idx_str = part[
                                            part.index("[") + 1 : part.index("]")
                                        ]
                                        if key not in current:
                                            current[key] = []
                                        idx = int(idx_str)
                                        if idx >= len(current[key]):
                                            current[key].append({})
                                        current = current[key][idx]
                                    else:
                                        if part not in current:
                                            current[part] = {}
                                        current = current[part]

                                # Set final value
                                final_key = parts[-1]
                                if "[" in final_key and "]" in final_key:
                                    key = final_key[: final_key.index("[")]
                                    idx_str = final_key[
                                        final_key.index("[") + 1 : final_key.index("]")
                                    ]
                                    if key not in current:
                                        current[key] = []
                                    idx = int(idx_str)
                                    if idx >= len(current[key]):
                                        current[key].append({})
                                    current[key][idx] = value
                                else:
                                    current[final_key] = value

                                updated_fields.append(field_path)

                            # Validate merged data
                            validation_result = self._validate_copy_json(updated_data)
                            warnings = validation_result.get("warnings", [])
                            valid_data = validation_result.get("data", {})

                            #  CRTICO: Se h ANY warnings aps update, REJEITAR
                            if warnings:
                                # Mapear avisos para mensagens instructivas
                                field_examples = {
                                    "is_paid_ad": "true ou false",
                                    "aspect_ratio": "9:16, 16:9, 1:1, ou 4:5",
                                    "framework": "SLAP, ACC, 4CS, PAS, AIDA ou FAB",
                                    # Narrative & StoryBrand
                                    "hypothesy": "Hiptese do copywriting",
                                    "problem": "Problema especfico",
                                    "solution": "Como resolve",
                                    "transformation": "Antes  Depois",
                                    "hook_pain_awareness": "Ato 1 do StoryBrand (gancho + dor)",
                                    "empathy": "Ato 2 do StoryBrand (empatia)",
                                    "autority": "Ato 3 do StoryBrand (autoridade)",
                                    "solution_contious": "Ato 4 do StoryBrand (soluo)",
                                    "product_contious": "Ato 5 do StoryBrand (produto)",
                                    "offer_concious": "Ato 6 do StoryBrand (oferta)",
                                    # Framework-specific
                                    "stop_hook": "[SLAP] Hook para parar",
                                    "look_proposition": "[SLAP] Proposio atrativa",
                                    "act_urgency": "[SLAP] Urgncia para agir",
                                    "purchase_cta": "[SLAP] CTA de compra",
                                    "awareness_problem": "[ACC] Problema de awareness",
                                    "comprehension_explanation": "[ACC] Explicao da soluo",
                                    "conversion_solution": "[ACC] Soluo de converso",
                                    "clear_message": "[4CS] Mensagem clara",
                                    "concise_copy": "[4CS] Copy conciso",
                                    "compelling_angle": "[4CS] ngulo compelling",
                                    "credible_proof": "[4CS] Prova de credibilidade",
                                    "agitate": "[PAS] Agitar/aprofundar dor",
                                    "attention": "[AIDA] Capturar ateno",
                                    "interest": "[AIDA] Gerar interesse",
                                    "desire": "[AIDA] Criar desejo",
                                    "action": "[AIDA] CTA claro",
                                    "features": "[FAB] Caractersticas",
                                    "advantages": "[FAB] Vantagens",
                                    "benefits": "[FAB] Benefcios",
                                    "caption": "String simples ou JSON estruturado",
                                    "assets": "Array com mnimo 1 asset. ATENO: 'prompt' deve ser OBJETO JSON (no string): {description, has_realistic_people, composition: {angle, grid}, environment: {place, objects}, colors: {background, subject, accent, saturation_contrast, harmony}, illumination, emotion_style}",
                                }

                                correction_list = []
                                for w in warnings:
                                    if "invalid:" in w:
                                        # Extrai os valores vlidos diretamente do warning
                                        _inv_field = (
                                            w.split("invalid:")[-1]
                                            .strip()
                                            .split("(")[0]
                                            .strip()
                                        )
                                        _inv_detail = (
                                            w.split("(")[-1].rstrip(")")
                                            if "(" in w
                                            else w
                                        )
                                        correction_list.append(
                                            f" {_inv_field.upper()} INVLIDO  {_inv_detail}"
                                        )
                                    else:
                                        for field, example in field_examples.items():
                                            if field in w:
                                                correction_list.append(
                                                    f" {field.upper()}: {example}"
                                                )
                                                break
                                        else:
                                            correction_list.append(f" {w}")

                                return json.dumps(
                                    {
                                        "success": False,
                                        "tool": "update",
                                        "type": "document",
                                        "doc_type": "copywriting",
                                        "id": item_id,
                                        "title": title,
                                        "status": "rejected_incomplete",
                                        "errors": warnings,
                                        "attempted_fields": updated_fields,
                                        "correction_required": correction_list,
                                        "guidance": f"Revise os {len(warnings)} campo(s) abaixo e reenvia o UPDATE com os valores CORRETOS.",
                                        "message": f"Update rejeitado: {len(warnings)} erro(s). Corrija e tente novamente.",
                                    },
                                    ensure_ascii=False,
                                )

                            updated_content = json.dumps(valid_data, ensure_ascii=False)

                            # Update in database (s se passou na validao)
                            update_query = text(
                                """
                                UPDATE documents SET content = :content, updated_at = CURRENT_TIMESTAMP
                                WHERE document_id = :document_id
                            """
                            )
                            session.execute(
                                update_query,
                                {
                                    "content": updated_content,
                                    "document_id": document_id,
                                },
                            )
                            session.commit()

                            debug(
                                f"[UPDATE] Copywriting updated: {title} - {len(updated_fields)} fields"
                            )

                            response = {
                                "success": True,
                                "tool": "update",
                                "type": "document",
                                "doc_type": "copywriting",
                                "id": item_id,
                                "title": title,
                                "updated_fields": updated_fields,
                                "message": f"{len(updated_fields)} field(s) updated successfully",
                            }

                            return json.dumps(response, ensure_ascii=False)

                        finally:
                            session.close()

                    except Exception as e:
                        error(f"[UPDATE] Error updating copywriting: {e}")
                        return json.dumps(
                            {
                                "success": False,
                                "tool": "update",
                                "type": "document",
                                "doc_type": "copywriting",
                                "error": str(e),
                            },
                            ensure_ascii=False,
                        )

                # LEGACY: Markdown documents - old_content/new_content replacement
                old_content = args.get("old_content", "")
                new_content = args.get("new_content", "").strip()

                # Validar campos obrigatrios para document (markdown)
                if not old_content or not new_content:
                    return json.dumps(
                        {
                            "success": False,
                            "tool": "update",
                            "type": "document",
                            "error": "Required fields for markdown document: old_content and new_content",
                        },
                        ensure_ascii=False,
                    )

                debug(f"[UPDATE] Atualizando documento: {item_id}")

                try:
                    # Buscar documento no banco de dados
                    if not self.db_manager:
                        return json.dumps(
                            {
                                "success": False,
                                "tool": "update",
                                "type": "document",
                                "error": "Database manager no configurado",
                            },
                            ensure_ascii=False,
                        )

                    session = self.db_manager.get_session()
                    try:
                        from sqlalchemy import text

                        # Procurar pelo documento com este ID na tabela documents
                        query = text(
                            """
                            SELECT document_id, title, content FROM documents WHERE document_id = :document_id
                        """
                        )
                        result = session.execute(
                            query, {"document_id": item_id}
                        ).first()

                        if not result:
                            return json.dumps(
                                {
                                    "success": False,
                                    "tool": "update",
                                    "type": "document",
                                    "error": f"Documento com ID {item_id} no encontrado",
                                },
                                ensure_ascii=False,
                            )

                        document_id, title, file_content = result

                        # Processar sequncias de escape
                        old_content_processed = process_escape_sequences(old_content)
                        new_content_processed = process_escape_sequences(new_content)

                        # Normalizar quebras de linha
                        file_content_normalized = (
                            normalize_line_endings(file_content) if file_content else ""
                        )

                        # Dividir em linhas para busca
                        file_lines = (
                            file_content_normalized.split("\n")
                            if file_content_normalized
                            else []
                        )
                        old_lines = old_content_processed.split("\n")

                        # Encontrar o bloco
                        match_result = find_block_match(file_lines, old_lines)

                        if not match_result.get("found"):
                            return json.dumps(
                                {
                                    "success": False,
                                    "tool": "update",
                                    "type": "document",
                                    "error": f"Contedo a ser editado no encontrado no documento",
                                    "hint": "Verifique se o texto corresponde exatamente ao arquivo (espaos, indentao, quebras de linha)",
                                },
                                ensure_ascii=False,
                            )

                        if not match_result.get("unique"):
                            return json.dumps(
                                {
                                    "success": False,
                                    "tool": "update",
                                    "type": "document",
                                    "error": f"Mltiplas ocorrncias do contedo encontradas ({match_result.get('count')})",
                                    "hint": "Expanda o bloco com mais contexto para torn-lo nico",
                                },
                                ensure_ascii=False,
                            )

                        # Substituir o contedo
                        start_line = match_result["start_line"]
                        end_line = match_result["end_line"]

                        new_lines = (
                            file_lines[:start_line]
                            + new_content_processed.split("\n")
                            + file_lines[end_line + 1 :]
                        )

                        updated_content = "\n".join(new_lines)

                        # Atualizar documento no banco de dados
                        update_query = text(
                            """
                            UPDATE documents SET content = :content, updated_at = CURRENT_TIMESTAMP
                            WHERE document_id = :document_id
                        """
                        )
                        session.execute(
                            update_query,
                            {"content": updated_content, "document_id": document_id},
                        )
                        session.commit()

                        debug(
                            f"[UPDATE] Documento atualizado: {title} (linhas {start_line + 1}-{end_line + 1})"
                        )

                        return json.dumps(
                            {
                                "success": True,
                                "tool": "update",
                                "type": "document",
                                "id": item_id,
                                "filename": title,
                                "lines_modified": end_line - start_line + 1,
                                "message": f"Documento atualizado com sucesso",
                                "updated_fields": ["content"],
                            },
                            ensure_ascii=False,
                        )

                    finally:
                        session.close()

                except Exception as e:
                    error(f"[UPDATE] Erro ao editar documento: {e}")
                    return json.dumps(
                        {
                            "success": False,
                            "tool": "update",
                            "type": "document",
                            "error": str(e),
                        },
                        ensure_ascii=False,
                    )

            # ============================================================================
            # CALENDAR: Reschedule (PATCH post_date) ou remover post
            # ============================================================================
            elif update_type == "calendar":
                new_date = args.get("new_date", "").strip()

                # Se new_date fornecido: PATCH (reschedule)
                # Seno: DELETE (remover)

                if new_date:
                    # PATCH: Reschedule
                    # Aceita dd/mm/aaaa ou dd.mm.aaaa
                    if not re.match(r"^\d{2}[./]\d{2}[./]\d{4}$", new_date):
                        return json.dumps(
                            {
                                "success": False,
                                "tool": "update",
                                "type": "calendar",
                                "error": f"Formato de data invlido '{new_date}'. Use: dd/mm/aaaa ou dd.mm.aaaa",
                            },
                            ensure_ascii=False,
                        )

                    # Converter dd.mm.aaaa para dd/mm/aaaa se necessrio
                    new_date = new_date.replace(".", "/")
                    action = "reschedule"
                else:
                    # DELETE: Remove
                    action = "remove"

                debug(f"[UPDATE] {action.upper()} post de calendrio: {item_id}")

                try:
                    if not self.db_manager:
                        return json.dumps(
                            {
                                "success": False,
                                "tool": "update",
                                "type": "calendar",
                                "error": "Database manager no configurado",
                            },
                            ensure_ascii=False,
                        )

                    session = self.db_manager.get_session()
                    try:
                        from App.Core.Crunch.TablesSQL.Models import Calendar
                        from datetime import datetime as dt

                        # Buscar post no banco de dados (filtrado por user_id para segurana)
                        calendar_post = (
                            session.query(Calendar)
                            .filter(
                                Calendar.post_id == item_id,
                                Calendar.user_id == self.current_user_id,
                            )
                            .first()
                        )

                        if not calendar_post:
                            return json.dumps(
                                {
                                    "success": False,
                                    "tool": "update",
                                    "type": "calendar",
                                    "error": f"Post com ID {item_id} no encontrado",
                                },
                                ensure_ascii=False,
                            )

                        # Processar a ao
                        if action == "reschedule":
                            old_date = calendar_post.post_date.strftime("%d.%m.%Y")
                            # Parse new_date (dd/mm/aaaa format)
                            new_date_obj = dt.strptime(
                                new_date.replace(".", "/"), "%d/%m/%Y"
                            ).date()
                            calendar_post.post_date = new_date_obj
                            session.commit()

                            debug(
                                f"[UPDATE] Post reagendado: {item_id} de {old_date} para {new_date}"
                            )

                            return json.dumps(
                                {
                                    "success": True,
                                    "tool": "update",
                                    "type": "calendar",
                                    "action": "reschedule",
                                    "id": item_id,
                                    "old_date": old_date,
                                    "new_date": new_date,
                                    "message": f"Post reagendado de {old_date} para {new_date}",
                                },
                                ensure_ascii=False,
                            )

                        else:  # action == 'remove'
                            post_description = (
                                calendar_post.short_description or "sem descrio"
                            )
                            session.delete(calendar_post)
                            session.commit()

                            debug(
                                f"[UPDATE] Post removido: {item_id} ({post_description})"
                            )

                            return json.dumps(
                                {
                                    "success": True,
                                    "tool": "update",
                                    "type": "calendar",
                                    "action": "remove",
                                    "id": item_id,
                                    "removed_post": post_description,
                                    "message": f"Post removido com sucesso",
                                },
                                ensure_ascii=False,
                            )

                    finally:
                        session.close()

                except Exception as e:
                    error(f"[UPDATE] Erro ao atualizar calendrio: {e}")
                    import traceback

                    error(f"[UPDATE] Traceback: {traceback.format_exc()}")
                    return json.dumps(
                        {
                            "success": False,
                            "tool": "update",
                            "type": "calendar",
                            "error": str(e),
                        },
                        ensure_ascii=False,
                    )

            # ============================================================================
            # CLIENT: Editar informaes do cliente
            # ============================================================================
            elif update_type == "client":
                old_content = args.get("old_content", "")
                new_content = args.get("new_content", "").strip()

                # Validar campos obrigatrios para client
                if not old_content or not new_content:
                    return json.dumps(
                        {
                            "success": False,
                            "tool": "update",
                            "type": "client",
                            "error": "Campos obrigatrios para client: old_content e new_content",
                        },
                        ensure_ascii=False,
                    )

                debug(f"[UPDATE] Atualizando cliente: {item_id}")

                try:
                    # Buscar arquivo do cliente no banco de dados
                    if not self.db_manager:
                        return json.dumps(
                            {
                                "success": False,
                                "tool": "update",
                                "type": "client",
                                "error": "Database manager no configurado",
                            },
                            ensure_ascii=False,
                        )

                    session = self.db_manager.get_session()
                    try:
                        from App.Core.Crunch.TablesSQL.Models import FileRecord

                        # Procurar pelo arquivo com este ID
                        file_record = (
                            session.query(FileRecord)
                            .filter(
                                FileRecord.file_id == item_id,
                                FileRecord.file_category == "client_info",
                            )
                            .first()
                        )

                        if not file_record:
                            return json.dumps(
                                {
                                    "success": False,
                                    "tool": "update",
                                    "type": "client",
                                    "error": f"Documento do cliente com ID {item_id} no encontrado",
                                },
                                ensure_ascii=False,
                            )

                        filename = file_record.file_name
                        # Extrair nome do documento sem extenso
                        document_name = filename.replace(".md", "").replace(".txt", "")

                    finally:
                        session.close()

                    # Construir caminho do arquivo cliente
                    # Cliente files: client_{user_id}/client_info/{document_name}.md
                    client_base = (
                        StorageManager.LOCAL_STORAGE_BASE
                        / f"client_{self.current_user_id}"
                        / "client_info"
                    )
                    file_path = client_base / filename

                    if not file_path.exists():
                        return json.dumps(
                            {
                                "success": False,
                                "tool": "update",
                                "type": "client",
                                "error": f"Arquivo do cliente no encontrado: {filename}",
                            },
                            ensure_ascii=False,
                        )

                    # Ler arquivo com tratamento de encoding
                    file_content, encoding = read_file_with_encoding(file_path)

                    # Processar sequncias de escape
                    old_content_processed = process_escape_sequences(old_content)
                    new_content_processed = process_escape_sequences(new_content)

                    # Normalizar quebras de linha
                    file_content_normalized = normalize_line_endings(file_content)

                    # Dividir em linhas para busca
                    file_lines = file_content_normalized.split("\n")
                    old_lines = old_content_processed.split("\n")

                    # Encontrar o bloco
                    match_result = find_block_match(file_lines, old_lines)

                    if not match_result.get("found"):
                        return json.dumps(
                            {
                                "success": False,
                                "tool": "update",
                                "type": "client",
                                "error": f"Contedo a ser editado no encontrado no documento do cliente",
                                "hint": "Verifique se o texto corresponde exatamente ao arquivo (espaos, indentao, quebras de linha)",
                            },
                            ensure_ascii=False,
                        )

                    if not match_result.get("unique"):
                        return json.dumps(
                            {
                                "success": False,
                                "tool": "update",
                                "type": "client",
                                "error": f"Mltiplas ocorrncias do contedo encontradas ({match_result.get('count')})",
                                "hint": "Expanda o bloco com mais contexto para torn-lo nico",
                            },
                            ensure_ascii=False,
                        )

                    # Substituir o contedo
                    start_line = match_result["start_line"]
                    end_line = match_result["end_line"]

                    new_lines = (
                        file_lines[:start_line]
                        + new_content_processed.split("\n")
                        + file_lines[end_line + 1 :]
                    )

                    updated_content = "\n".join(new_lines)

                    # Salvar arquivo
                    try:
                        file_path.write_text(updated_content, encoding="utf-8")
                    except:
                        file_path.write_text(
                            updated_content, encoding="cp1252", errors="replace"
                        )

                    debug(
                        f"[UPDATE] Cliente atualizado: {filename} (linhas {start_line + 1}-{end_line + 1})"
                    )

                    return json.dumps(
                        {
                            "success": True,
                            "tool": "update",
                            "type": "client",
                            "id": item_id,
                            "filename": filename,
                            "lines_modified": end_line - start_line + 1,
                            "message": f"Documento do cliente atualizado com sucesso",
                            "updated_fields": ["info"],
                        },
                        ensure_ascii=False,
                    )

                except Exception as e:
                    error(f"[UPDATE] Erro ao editar cliente: {e}")
                    return json.dumps(
                        {
                            "success": False,
                            "tool": "update",
                            "type": "client",
                            "error": str(e),
                        },
                        ensure_ascii=False,
                    )

            # ============================================================================
            # TASK: PATCH field ou DELETE task (com linked-list support)
            # ============================================================================
            elif update_type == "task":
                step_name = args.get("step_name", "").strip()
                field = args.get("field", "").strip()
                value = args.get("value", "").strip()

                # Validar campos obrigatrios para task
                if not step_name or not field:
                    return json.dumps(
                        {
                            "success": False,
                            "tool": "update",
                            "type": "task",
                            "error": "Campos obrigatrios para task: step_name e field",
                        },
                        ensure_ascii=False,
                    )

                # Se field for "delete": DELETE task (remove)
                # Seno: PATCH (atualizar campo especfico)

                if field.lower() == "delete":
                    # DELETE: Remover task
                    action = "remove"
                else:
                    # PATCH: Atualizar campo especfico
                    action = "update"
                    if not value:
                        return json.dumps(
                            {
                                "success": False,
                                "tool": "update",
                                "type": "task",
                                "error": "Campo 'value'  obrigatrio quando atualizando um field",
                            },
                            ensure_ascii=False,
                        )

                debug(
                    f"[UPDATE] {action.upper()} task: {item_id} (step: {step_name}, field: {field})"
                )

                try:
                    if not self.db_manager:
                        return json.dumps(
                            {
                                "success": False,
                                "tool": "update",
                                "type": "task",
                                "error": "Database manager no configurado",
                            },
                            ensure_ascii=False,
                        )

                    session = self.db_manager.get_session()
                    try:
                        from App.Core.Crunch.TablesSQL.Models import Task

                        # Procurar pela task com este UUID (task_id retornado do backend)
                        # E verificar que o step_name coincide
                        task = (
                            session.query(Task)
                            .filter(
                                Task.task_id == item_id,
                                Task.step_name == step_name,
                                Task.chat_id == self.current_chat_id,
                            )
                            .first()
                        )

                        if not task:
                            return json.dumps(
                                {
                                    "success": False,
                                    "tool": "update",
                                    "type": "task",
                                    "error": f"Task com ID {item_id} e step '{step_name}' no encontrada",
                                },
                                ensure_ascii=False,
                            )

                        task_name = task.task_name
                        previous_id = task.previous_step_id
                        next_id = task.next_step_id

                        if action == "update":
                            # PATCH: Atualizar campo especfico
                            valid_statuses = [
                                "pending",
                                "in_progress",
                                "success",
                                "failed",
                                "finished",
                            ]
                            old_value = getattr(task, field, None)

                            # Validar e atualizar o campo
                            if field == "status":
                                if value not in valid_statuses:
                                    return json.dumps(
                                        {
                                            "success": False,
                                            "tool": "update",
                                            "type": "task",
                                            "error": f"Status invlido '{value}'. Use: {', '.join(valid_statuses)}",
                                        },
                                        ensure_ascii=False,
                                    )
                                task.status = value
                            elif hasattr(task, field):
                                setattr(task, field, value)
                            else:
                                return json.dumps(
                                    {
                                        "success": False,
                                        "tool": "update",
                                        "type": "task",
                                        "error": f"Campo '{field}' no existe em Task. Use: 'status', 'step_name', 'step_context', 'task_name', etc.",
                                    },
                                    ensure_ascii=False,
                                )

                            session.commit()

                            debug(
                                f"[UPDATE] Task field: {task_name}/{step_name} - {field}: '{old_value}'  '{value}'"
                            )

                            # Se marcado como sucesso, retornar contexto da prxima task
                            next_task_context = {}
                            next_step = None
                            if field == "status" and value in ["success", "finished"]:
                                # Buscar prximo step pelo step_context (nome)
                                if task.step_context and isinstance(
                                    task.step_context, str
                                ):
                                    next_task_context = self._get_next_step_context(
                                        task.step_context
                                    )
                                    if next_task_context:
                                        next_step = next_task_context.get(
                                            "step_context"
                                        )

                            return json.dumps(
                                {
                                    "success": True,
                                    "tool": "update",
                                    "type": "task",
                                    "task_id": item_id,
                                    "step_name": step_name,
                                    "field_updated": field,
                                    "old_value": str(old_value),
                                    "new_value": str(value),
                                    "message": f"Campo '{field}' atualizado com sucesso",
                                    "next_step": next_step,
                                    "next_task_context": (
                                        next_task_context if next_task_context else None
                                    ),
                                    "is_final_step": (
                                        len(next_task_context) == 0
                                        if field == "status"
                                        and value in ["success", "finished"]
                                        else None
                                    ),
                                },
                                ensure_ascii=False,
                            )

                        else:
                            # DELETE: Remover task e atualizar linked-list
                            # Conectar previous_step -> next_step
                            if previous_id:
                                prev_task = (
                                    session.query(Task)
                                    .filter(Task.task_id == previous_id)
                                    .first()
                                )
                                if prev_task:
                                    prev_task.next_step_id = next_id

                            if next_id:
                                next_task = (
                                    session.query(Task)
                                    .filter(Task.task_id == next_id)
                                    .first()
                                )
                                if next_task:
                                    next_task.previous_step_id = previous_id

                            # Remover a task
                            session.delete(task)
                            session.commit()

                            debug(
                                f"[UPDATE] Task removida: {task_name}/{step_name} (linked-list atualizado)"
                            )

                            return json.dumps(
                                {
                                    "success": True,
                                    "tool": "update",
                                    "type": "task",
                                    "task_id": item_id,
                                    "step_name": step_name,
                                    "message": f"Task removida com sucesso (sequncia mantida)",
                                },
                                ensure_ascii=False,
                            )

                    finally:
                        session.close()

                except Exception as e:
                    error(f"[UPDATE] Erro ao editar task: {e}")
                    return json.dumps(
                        {
                            "success": False,
                            "tool": "update",
                            "type": "task",
                            "error": str(e),
                        },
                        ensure_ascii=False,
                    )

            # ============================================================================
            # ASSET: Editar propriedades do asset (caption, version, etc)
            # ============================================================================
            elif update_type == "asset":
                field = args.get("field", "").strip()
                value = args.get("value")

                # Validar campos obrigatrios para asset
                if not field:
                    return json.dumps(
                        {
                            "success": False,
                            "tool": "update",
                            "type": "asset",
                            "error": "Campo obrigatrio faltando: field",
                        },
                        ensure_ascii=False,
                    )

                if value is None:
                    return json.dumps(
                        {
                            "success": False,
                            "tool": "update",
                            "type": "asset",
                            "error": "Campo obrigatrio faltando: value",
                        },
                        ensure_ascii=False,
                    )

                debug(f"[UPDATE] Atualizando asset: {item_id}, field: {field}")

                try:
                    if not self.db_manager:
                        return json.dumps(
                            {
                                "success": False,
                                "tool": "update",
                                "type": "asset",
                                "error": "Database manager no configurado",
                            },
                            ensure_ascii=False,
                        )

                    session = self.db_manager.get_session()
                    try:
                        from App.Core.Crunch.TablesSQL.Models import GeneratedContent

                        # Buscar asset no banco de dados
                        asset = (
                            session.query(GeneratedContent)
                            .filter(GeneratedContent.asset_id == item_id)
                            .first()
                        )

                        if not asset:
                            return json.dumps(
                                {
                                    "success": False,
                                    "tool": "update",
                                    "type": "asset",
                                    "error": f"Asset com ID {item_id} no encontrado",
                                },
                                ensure_ascii=False,
                            )

                        old_value = getattr(asset, field, None)

                        # Validar e atualizar o campo
                        if field == "caption":
                            # Caption pode ser dict ou string JSON
                            if isinstance(value, dict):
                                value = json.dumps(value, ensure_ascii=False)
                            elif isinstance(value, str):
                                # Tentar validar como JSON
                                try:
                                    json.loads(value)
                                except json.JSONDecodeError:
                                    return json.dumps(
                                        {
                                            "success": False,
                                            "tool": "update",
                                            "type": "asset",
                                            "error": "Campo 'caption' deve ser JSON vlido ou dict",
                                        },
                                        ensure_ascii=False,
                                    )
                            asset.caption = value
                        elif field == "version":
                            # Version deve ser nmero
                            try:
                                asset.version = int(value)
                            except (ValueError, TypeError):
                                return json.dumps(
                                    {
                                        "success": False,
                                        "tool": "update",
                                        "type": "asset",
                                        "error": f"Campo 'version' deve ser um nmero, recebido: {value}",
                                    },
                                    ensure_ascii=False,
                                )
                        elif field == "title":
                            # Title deve ser string
                            asset.title = str(value) if value else None
                        elif hasattr(asset, field):
                            setattr(asset, field, value)
                        else:
                            return json.dumps(
                                {
                                    "success": False,
                                    "tool": "update",
                                    "type": "asset",
                                    "error": f"Campo '{field}' no existe em Asset. Use: 'title', 'caption', 'version', etc.",
                                },
                                ensure_ascii=False,
                            )

                        session.commit()

                        debug(
                            f"[UPDATE] Asset atualizado: {item_id} - {field}: '{old_value}'  '{value}'"
                        )

                        return json.dumps(
                            {
                                "success": True,
                                "tool": "update",
                                "type": "asset",
                                "generated_content_id": item_id,
                                "field_updated": field,
                                "old_value": str(old_value),
                                "new_value": str(value),
                                "message": f"Campo '{field}' do asset atualizado com sucesso",
                            },
                            ensure_ascii=False,
                        )

                    finally:
                        session.close()

                except Exception as e:
                    error(f"[UPDATE] Erro ao editar asset: {e}")
                    return json.dumps(
                        {
                            "success": False,
                            "tool": "update",
                            "type": "asset",
                            "error": str(e),
                        },
                        ensure_ascii=False,
                    )

        except Exception as e:
            error(f"[UPDATE] Erro ao executar: {e}")
            return json.dumps(
                {"success": False, "error": str(e), "tool": "update"},
                ensure_ascii=False,
            )

    def _execute_delete(self, args: Dict[str, Any]) -> str:
        """
        Executa tool 'delete' para remover entidades (tasks, documents, posts agendados).

        Args:
            args: Dict com:
                - type: 'document' | 'schedule' | 'task' (obrigatrio)
                - id: UUID do item a deletar (obrigatrio)
                - step_name: Nome exato do step (OBRIGATRIO apenas para task)

        Returns:
            JSON com status de sucesso e informaes da remoo
        """
        try:
            delete_type = args.get("type", "").strip().lower()
            item_id = args.get("id", "").strip()

            # Validar campos obrigatrios bsicos
            if not delete_type or not item_id:
                return json.dumps(
                    {
                        "success": False,
                        "tool": "delete",
                        "error": "Campos obrigatrios faltando: type e id",
                    },
                    ensure_ascii=False,
                )

            # Validar tipo
            if delete_type not in self.DELETE_VALID_TYPES:
                return json.dumps(
                    {
                        "success": False,
                        "tool": "delete",
                        "error": f"Tipo invlido '{delete_type}'. Use: {', '.join(self.DELETE_VALID_TYPES)}",
                    },
                    ensure_ascii=False,
                )

            # ============================================================================
            # DOCUMENT: Deletar documento
            # ============================================================================
            if delete_type == "document":
                debug(f"[DELETE] Deletando documento: {item_id}")

                try:
                    if not self.db_manager:
                        return json.dumps(
                            {
                                "success": False,
                                "tool": "delete",
                                "type": "document",
                                "error": "Database manager no configurado",
                            },
                            ensure_ascii=False,
                        )

                    session = self.db_manager.get_session()
                    try:
                        from sqlalchemy import text

                        # Buscar documento
                        query = text(
                            """
                            SELECT document_id, title FROM documents WHERE document_id = :document_id
                        """
                        )
                        result = session.execute(
                            query, {"document_id": item_id}
                        ).first()

                        if not result:
                            return json.dumps(
                                {
                                    "success": False,
                                    "tool": "delete",
                                    "type": "document",
                                    "error": f"Documento com ID {item_id} no encontrado",
                                },
                                ensure_ascii=False,
                            )

                        document_id, title = result

                        # Deletar documento
                        delete_query = text(
                            """
                            DELETE FROM documents WHERE document_id = :document_id
                        """
                        )
                        session.execute(delete_query, {"document_id": document_id})
                        session.commit()

                        debug(f"[DELETE] Documento deletado: {title} ({document_id})")

                        return json.dumps(
                            {
                                "success": True,
                                "tool": "delete",
                                "type": "document",
                                "id": item_id,
                                "filename": title,
                                "message": f"Documento removido com sucesso",
                            },
                            ensure_ascii=False,
                        )

                    finally:
                        session.close()

                except Exception as e:
                    error(f"[DELETE] Erro ao deletar documento: {e}")
                    return json.dumps(
                        {
                            "success": False,
                            "tool": "delete",
                            "type": "document",
                            "error": str(e),
                        },
                        ensure_ascii=False,
                    )

            # ============================================================================
            # SCHEDULE: Deletar post agendado
            # ============================================================================
            elif delete_type == "schedule":
                debug(f"[DELETE] Deletando post agendado: {item_id}")

                try:
                    if not self.db_manager:
                        return json.dumps(
                            {
                                "success": False,
                                "tool": "delete",
                                "type": "schedule",
                                "error": "Database manager no configurado",
                            },
                            ensure_ascii=False,
                        )

                    session = self.db_manager.get_session()
                    try:
                        from App.Core.Crunch.TablesSQL.Models import Calendar

                        # Buscar post na tabela Calendar
                        calendar_post = (
                            session.query(Calendar)
                            .filter(
                                Calendar.post_id == item_id,
                                Calendar.user_id == self.current_user_id,
                            )
                            .first()
                        )

                        if not calendar_post:
                            return json.dumps(
                                {
                                    "success": False,
                                    "tool": "delete",
                                    "type": "schedule",
                                    "error": f"Post com ID {item_id} no encontrado",
                                },
                                ensure_ascii=False,
                            )

                        post_description = (
                            calendar_post.short_description or "sem descrio"
                        )
                        post_date = (
                            calendar_post.post_date.strftime("%d.%m.%Y")
                            if calendar_post.post_date
                            else "sem data"
                        )

                        # Deletar post
                        session.delete(calendar_post)
                        session.commit()

                        debug(
                            f"[DELETE] Post agendado deletado: {item_id} ({post_date})"
                        )

                        return json.dumps(
                            {
                                "success": True,
                                "tool": "delete",
                                "type": "schedule",
                                "id": item_id,
                                "post_date": post_date,
                                "post_description": post_description,
                                "message": f"Post agendado removido com sucesso",
                            },
                            ensure_ascii=False,
                        )

                    finally:
                        session.close()

                except Exception as e:
                    error(f"[DELETE] Erro ao deletar post agendado: {e}")
                    return json.dumps(
                        {
                            "success": False,
                            "tool": "delete",
                            "type": "schedule",
                            "error": str(e),
                        },
                        ensure_ascii=False,
                    )

            # ============================================================================
            # TASK: Deletar task e atualizar linked-list
            # ============================================================================
            elif delete_type == "task":
                step_name = args.get("step_name", "").strip()

                # Validar step_name obrigatrio para task
                if not step_name:
                    return json.dumps(
                        {
                            "success": False,
                            "tool": "delete",
                            "type": "task",
                            "error": "Campo 'step_name'  obrigatrio para deletar task",
                        },
                        ensure_ascii=False,
                    )

                debug(f"[DELETE] Deletando task: {item_id} (step: {step_name})")

                try:
                    if not self.db_manager:
                        return json.dumps(
                            {
                                "success": False,
                                "tool": "delete",
                                "type": "task",
                                "error": "Database manager no configurado",
                            },
                            ensure_ascii=False,
                        )

                    session = self.db_manager.get_session()
                    try:
                        from App.Core.Crunch.TablesSQL.Models import Task

                        # Procurar pela task
                        task = (
                            session.query(Task)
                            .filter(
                                Task.task_id == item_id,
                                Task.step_name == step_name,
                                Task.chat_id == self.current_chat_id,
                            )
                            .first()
                        )

                        if not task:
                            return json.dumps(
                                {
                                    "success": False,
                                    "tool": "delete",
                                    "type": "task",
                                    "error": f"Task com ID {item_id} e step '{step_name}' no encontrada",
                                },
                                ensure_ascii=False,
                            )

                        task_name = task.task_name
                        previous_id = task.previous_step_id
                        next_id = task.next_step_id

                        # Atualizar linked-list
                        if previous_id:
                            prev_task = (
                                session.query(Task)
                                .filter(Task.task_id == previous_id)
                                .first()
                            )
                            if prev_task:
                                prev_task.next_step_id = next_id

                        if next_id:
                            next_task = (
                                session.query(Task)
                                .filter(Task.task_id == next_id)
                                .first()
                            )
                            if next_task:
                                next_task.previous_step_id = previous_id

                        # Deletar task
                        session.delete(task)
                        session.commit()

                        debug(
                            f"[DELETE] Task removida: {task_name}/{step_name} (linked-list atualizado)"
                        )

                        return json.dumps(
                            {
                                "success": True,
                                "tool": "delete",
                                "type": "task",
                                "task_id": item_id,
                                "step_name": step_name,
                                "message": f"Task removida com sucesso (sequncia mantida)",
                            },
                            ensure_ascii=False,
                        )

                    finally:
                        session.close()

                except Exception as e:
                    error(f"[DELETE] Erro ao deletar task: {e}")
                    return json.dumps(
                        {
                            "success": False,
                            "tool": "delete",
                            "type": "task",
                            "error": str(e),
                        },
                        ensure_ascii=False,
                    )

        except Exception as e:
            error(f"[DELETE] Erro ao executar: {e}")
            return json.dumps(
                {"success": False, "error": str(e), "tool": "delete"},
                ensure_ascii=False,
            )

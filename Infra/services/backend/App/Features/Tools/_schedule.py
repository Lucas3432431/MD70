"""
_schedule.py — Mixin extraído de Core.py.
Core.py importa este módulo e herda ScheduleMixin.
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


class ScheduleMixin:
    def _execute_schedule(self, args: Dict[str, Any]) -> str:
        """
        Executa tool 'schedule' para agendar postagens e gerenciar calendrio de campanhas.

         PADRO GENRICO - Suporta MLTIPLOS agendamentos em uma nica requisio:
        - Parmetro 'schedules': Array de agendamentos a executar
          Exemplo: schedules=[
            {name: "CAMPANHA_1", posts: [...]},
            {name: "CAMPANHA_2", posts: [...]}
          ]
        - Cada agendamento  processado independentemente
        - Retorna resultado consolidado com todos os agendamentos criados

        Actions:
        - calendar="now" ou day="today": Retorna data/hora atual
        - plan=[...]: Cria calendrio simplificado com UUIDs (retorna imediatamente)
        - schedules=[...]: Cria mltiplos agendamentos em paralelo
        - "schedule": Programa posts com post_ids automticos (modo singular)
        - "status": Retorna status de progresso

        Args:
            args: Dict com action/plan/schedules + parmetros especficos

        Returns:
            JSON com data/calendrio/status
        """
        #  VERIFICAR SE DOCUMENTOS REQUERIDOS EXISTEM (exceto para calendar e plan)
        calendar = args.get("calendar", "").strip()
        day = args.get("day", "").strip()
        plan = args.get("plan", [])
        schedules = args.get("schedules", [])
        action = args.get("action", "").strip().lower()

        #  BLOQUEAR EXECUES VAZIAS
        if not schedules and not plan and not calendar and not day and not action:
            return json.dumps(
                {
                    "success": False,
                    "error": "Nenhum agendamento ou comando fornecido.",
                    "tool": "schedule",
                    "status": "rejected",
                    "message": "Voc precisa fornecer os dados da campanha no parmetro 'schedules' para agendar posts.",
                    "hint": "Passe um array em 'schedules' com 'name' e 'posts'.",
                },
                ensure_ascii=False,
            )

        # Se est tentando criar schedules (no apenas consultar calendar/plan)
        if schedules and isinstance(schedules, list) and len(schedules) > 0:
            #  VALIDAO OBRIGATRIA: context(type="calendar") deve ter sido chamado antes
            if not self._check_context_calendar_in_chat_history():
                return json.dumps(
                    {
                        "success": False,
                        "error": "context(type='calendar')  obrigatrio antes de agendar postagens",
                        "tool": "schedule",
                        "status": "rejected",
                        "message": "Voc deve chamar context(type='calendar') ANTES de agendar postagens. Isso valida as datas e contexto do calendrio.",
                        "hint": "Exemplo: context(type='calendar')",
                    },
                    ensure_ascii=False,
                )

            # has_required_docs, doc_status = self._check_required_documents_exist()
            # if not has_required_docs:
            #     missing_docs = []
            #     if not doc_status.get("business_canvas"):
            #         missing_docs.append("business_canvas")
            #     if not doc_status.get("brand_communication"):
            #         missing_docs.append("brand_communication")

            #     return json.dumps(
            #         {
            #             "success": False,
            #             "error": f"Crie os documentos {', '.join(missing_docs)} antes de agendar postagens",
            #             "tool": "schedule",
            #             "status": "rejected",
            #             "message": f"Faltam documentos pr-requisitos: {', '.join(missing_docs)}. Crie business_canvas e brand_communication primeiro.",
            #         },
            #         ensure_ascii=False,
            #     )

        # ========== MODO MLTIPLOS AGENDAMENTOS: schedule(schedules=[...]) ==========
        schedules = args.get("schedules", [])
        if schedules and isinstance(schedules, list) and len(schedules) > 0:
            debug(
                f"[SCHEDULE] Mltiplos agendamentos detectados: {len(schedules)} campanhas"
            )

            # Validar cada agendamento
            validated_schedules = []

            for i, schedule_item in enumerate(schedules):
                if isinstance(schedule_item, dict):
                    name = schedule_item.get("name", "").strip()
                    posts = schedule_item.get("posts", [])

                    if not name:
                        debug(f"[SCHEDULE] Item {i} invlido: sem 'name' vlido")
                        continue

                    if not isinstance(posts, list) or len(posts) == 0:
                        debug(
                            f"[SCHEDULE] Item {i} invlido: 'posts' deve ser array no-vazio"
                        )
                        continue

                    # Validar cada post
                    valid_posts = True
                    for post_idx, post in enumerate(posts):
                        if not isinstance(post, dict):
                            debug(
                                f"[SCHEDULE] Post {post_idx} em agendamento {i} no  dicionrio"
                            )
                            valid_posts = False
                            break

                        # Validar content_type
                        content_type = post.get("content_type", "").strip().lower()
                        if (
                            not content_type
                            or content_type not in self.VALID_CONTENT_TYPES
                        ):
                            debug(
                                f"[SCHEDULE] Post {post_idx} em agendamento {i} invlido: content_type deve ser um de {self.VALID_CONTENT_TYPES}"
                            )
                            valid_posts = False
                            break

                        # Validar short_description
                        short_description = post.get("short_description", "").strip()
                        if not short_description:
                            debug(
                                f"[SCHEDULE] Post {post_idx} em agendamento {i} invlido: short_description  obrigatrio"
                            )
                            valid_posts = False
                            break

                    if valid_posts:
                        validated_schedules.append(schedule_item)
                else:
                    debug(f"[SCHEDULE] Item {i} no  um dicionrio")

            if not validated_schedules:
                return json.dumps(
                    {
                        "success": False,
                        "error": f"Nenhum agendamento vlido fornecido em 'schedules'. Cada agendamento deve ter: 'name' (string), 'posts' (array). Cada post deve ter: 'content_type' ({', '.join(self.VALID_CONTENT_TYPES)}), 'short_description' (string)",
                        "tool": "schedule",
                    },
                    ensure_ascii=False,
                )

            # ========== EXECUTAR MLTIPLOS AGENDAMENTOS ==========
            results = []
            total_posts = 0
            successful_schedules = 0

            try:
                for schedule_item in validated_schedules:
                    try:
                        name = schedule_item.get("name", "").strip()
                        posts = schedule_item.get("posts", [])

                        debug(
                            f"[SCHEDULE] Processando agendamento: {name} com {len(posts)} posts"
                        )

                        #  Bloquear datas duplicadas
                        post_dates = [p.get("date", "") for p in posts if p.get("date")]
                        conflicts = self._find_conflicting_schedule_dates(post_dates)
                        if conflicts:
                            results.append(
                                {
                                    "campaign_name": name,
                                    "success": False,
                                    "error": f"Datas j agendadas para este usurio: {', '.join(conflicts)}. Escolha outros dias.",
                                    "conflicting_dates": conflicts,
                                }
                            )
                            continue

                        # Programar este agendamento
                        calendar_data = self._schedule_calendar_posts(name, posts)

                        if not calendar_data.get("success"):
                            results.append(
                                {
                                    "campaign_name": name,
                                    "success": False,
                                    "error": calendar_data.get(
                                        "error", "Erro desconhecido"
                                    ),
                                }
                            )
                            continue

                        # Salvar posts no banco de dados
                        try:
                            saved_count, saved_post_ids = self._save_calendar_to_db(
                                name, calendar_data["campaign"]["posts"]
                            )
                            debug(
                                f"[SCHEDULE] {saved_count} posts salvos no DB para campanha: {name}"
                            )
                            debug(f"[SCHEDULE] Post IDs retornados: {saved_post_ids}")

                            results.append(
                                {
                                    "campaign_name": name,
                                    "success": True,
                                    "posts_created": saved_count,
                                    "post_ids": saved_post_ids,
                                    "args": schedule_item,
                                }
                            )
                            successful_schedules += 1
                            total_posts += saved_count

                        except Exception as save_err:
                            error(
                                f"[SCHEDULE] Erro ao salvar calendrio para {name}: {save_err}"
                            )
                            results.append(
                                {
                                    "campaign_name": name,
                                    "success": False,
                                    "error": f"Erro ao salvar: {str(save_err)}",
                                }
                            )

                    except Exception as e:
                        error(f"[SCHEDULE] Erro ao processar agendamento: {e}")
                        results.append(
                            {
                                "campaign_name": schedule_item.get(
                                    "name", "DESCONHECIDO"
                                ),
                                "success": False,
                                "error": str(e),
                            }
                        )

                debug(
                    f"[SCHEDULE] Mltiplos agendamentos concludos: {successful_schedules}/{len(validated_schedules)} com sucesso"
                )

                return json.dumps(
                    {
                        "success": True,
                        "tool": "schedule",
                        "type": "multiple_schedules",
                        "total_schedules": len(validated_schedules),
                        "successful_schedules": successful_schedules,
                        "total_posts": total_posts,
                        "results": results,
                        "hint": "Use context(type='calendar') para visualizar calendrio completo",
                    },
                    ensure_ascii=False,
                )

            except Exception as e:
                error(f"[SCHEDULE] Erro ao processar mltiplos agendamentos: {e}")
                return json.dumps(
                    {
                        "success": False,
                        "error": f"Erro ao processar mltiplos agendamentos: {str(e)}",
                        "tool": "schedule",
                    },
                    ensure_ascii=False,
                )

        # ========== MODO SIMPLIFICADO: calendar(plan=[...]) ==========
        plan = args.get("plan", [])
        if plan and isinstance(plan, list) and len(plan) > 0:
            #  VALIDAO OBRIGATRIA: context(type="calendar") deve ter sido chamado antes
            if not self._check_context_calendar_in_chat_history():
                return json.dumps(
                    {
                        "success": False,
                        "error": "context(type='calendar')  obrigatrio antes de planejar postagens",
                        "tool": "schedule",
                        "status": "rejected",
                        "message": "Voc deve chamar context(type='calendar') ANTES de planejar postagens.",
                        "hint": "Exemplo: context(type='calendar')",
                    },
                    ensure_ascii=False,
                )

            try:
                import uuid as uuid_lib

                posts_with_ids = []

                for item in plan:
                    if (
                        isinstance(item, dict)
                        and "day" in item
                        and "short_description" in item
                    ):
                        post_id = str(uuid_lib.uuid4())
                        posts_with_ids.append(
                            {
                                "day": item["day"],
                                "short_description": item["short_description"],
                                "id": post_id,
                            }
                        )

                if posts_with_ids:
                    debug(
                        f"[CALENDAR] Plano simplificado criado: {len(posts_with_ids)} postagens"
                    )

                    #  Bloquear datas duplicadas
                    plan_days = [p["day"] for p in posts_with_ids]
                    plan_conflicts = self._find_conflicting_schedule_dates(plan_days)
                    if plan_conflicts:
                        return json.dumps(
                            {
                                "success": False,
                                "error": f"Datas j agendadas para este usurio: {', '.join(plan_conflicts)}. Escolha outros dias.",
                                "tool": "schedule",
                                "conflicting_dates": plan_conflicts,
                            },
                            ensure_ascii=False,
                        )

                    # Salvar posts no banco de dados
                    saved_count = 0
                    saved_ids = []
                    try:
                        saved_count, saved_ids = self._save_calendar_to_db(
                            "Plano Simplificado", posts_with_ids
                        )
                        debug(f"[CALENDAR] {saved_count} posts salvos no DB")
                    except Exception as e:
                        error(f"[CALENDAR] Erro ao salvar calendrio no DB: {e}")

                    return json.dumps(
                        {
                            "success": True,
                            "tool": "calendar",
                            "type": "plan",
                            "posts_planned": saved_count,
                            "post_ids": saved_ids,
                            "args": {"plan": plan},
                            "message": f"{saved_count} postagens planejadas com sucesso",
                            "hint": "Use context(type='calendar') para visualizar calendrio completo",
                        },
                        ensure_ascii=False,
                    )
            except Exception as e:
                error(f"[CALENDAR] Erro ao processar plano: {e}")
                return json.dumps(
                    {
                        "success": False,
                        "error": f"Erro ao processar plano: {str(e)}",
                        "tool": "calendar",
                    },
                    ensure_ascii=False,
                )

        action = (
            args.get("action", "").lower()
            if "action" in args
            else (args.get("calendar", "") or args.get("day", "")).lower()
        )

        # ========== ACTION: TODAY ou day="today" ou calendar="now" ==========
        if action in ["today", "now"]:
            today = datetime.now()
            # Formato: dd.mm.aaaa
            date_str = today.strftime("%d.%m.%Y")
            # Dia da semana em portugus
            days_pt = [
                "segunda",
                "tera",
                "quarta",
                "quinta",
                "sexta",
                "sbado",
                "domingo",
            ]
            day_name = days_pt[today.weekday()]

            return json.dumps(
                {
                    "success": True,
                    "tool": "calendar",
                    "action": "today",
                    "date": date_str,
                    "day_of_week": day_name,
                    "timestamp": today.isoformat(),
                },
                ensure_ascii=False,
            )

        # ========== ACTION: SCHEDULE ==========
        elif action == "schedule":
            name = args.get("name", "").strip()
            posts = args.get("posts", [])

            if not name:
                return json.dumps(
                    {
                        "success": False,
                        "error": "Para 'schedule': name  obrigatrio (nome da campanha)",
                        "tool": "calendar",
                    },
                    ensure_ascii=False,
                )

            if not isinstance(posts, list) or len(posts) < 1:
                return json.dumps(
                    {
                        "success": False,
                        "error": "Para 'schedule': posts  obrigatrio e deve ter pelo menos 1 item. Exemplo: posts=[{date: '05.03.2025', platform: 'instagram', stage: 'awareness', content_type: 'image', copy: 'Mensagem'}]",
                        "tool": "calendar",
                    },
                    ensure_ascii=False,
                )

            #  VALIDAO OBRIGATRIA: context(type="calendar") deve ter sido chamado antes
            if not self._check_context_calendar_in_chat_history():
                return json.dumps(
                    {
                        "success": False,
                        "error": "context(type='calendar')  obrigatrio antes de agendar postagens",
                        "tool": "schedule",
                        "status": "rejected",
                        "message": "Voc deve chamar context(type='calendar') ANTES de agendar postagens. Isso valida as datas e contexto do calendrio.",
                        "hint": "Exemplo: context(type='calendar')",
                    },
                    ensure_ascii=False,
                )

            #  Bloquear datas duplicadas
            post_dates = [p.get("date", "") for p in posts if p.get("date")]
            conflicts = self._find_conflicting_schedule_dates(post_dates)
            if conflicts:
                return json.dumps(
                    {
                        "success": False,
                        "error": f"Datas j agendadas para este usurio: {', '.join(conflicts)}. Escolha outros dias.",
                        "tool": "schedule",
                        "conflicting_dates": conflicts,
                    },
                    ensure_ascii=False,
                )

            # Programar calendrio com posts da IA
            calendar_data = self._schedule_calendar_posts(name, posts)

            if not calendar_data.get("success"):
                return json.dumps(calendar_data, ensure_ascii=False)

            # Salvar posts no banco de dados
            saved_count = 0
            post_ids = []
            try:
                saved_count, post_ids = self._save_calendar_to_db(
                    name, calendar_data["campaign"]["posts"]
                )
                debug(
                    f"[CALENDAR] {saved_count} posts salvos no DB para campanha: {name}"
                )
                debug(f"[CALENDAR] Post IDs retornados: {post_ids}")

            except Exception as e:
                error(f"[CALENDAR] Erro ao salvar calendrio no DB: {e}")
                return json.dumps(
                    {
                        "success": False,
                        "tool": "calendar",
                        "error": f"Erro ao salvar calendrio: {str(e)}",
                    },
                    ensure_ascii=False,
                )

            response = {
                "success": True,
                "tool": "schedule",
                "campaign_name": name,
                "posts_created": saved_count,
                "post_ids": post_ids,
                "args": {"name": name, "posts": posts},
                "message": f"{saved_count} posts agendados com sucesso",
                "hint": "Use context(type='calendar') para visualizar calendrio completo",
            }

            return json.dumps(response, ensure_ascii=False)

        # ========== ACTION: STATUS ==========
        elif action == "status":
            name = args.get("name", "").strip()

            if not name:
                return json.dumps(
                    {
                        "success": False,
                        "error": "Para 'status': name  obrigatrio",
                        "tool": "schedule",
                    },
                    ensure_ascii=False,
                )

            # Buscar status da campanha do banco de dados
            try:
                if not self.db_manager or not self.current_user_id:
                    return json.dumps(
                        {
                            "success": False,
                            "error": "Contexto de banco de dados no configurado",
                            "tool": "schedule",
                        },
                        ensure_ascii=False,
                    )

                session = self.db_manager.get_session()
                try:
                    from sqlalchemy import text

                    # Buscar posts da campanha
                    query = text(
                        """
                        SELECT id, post_id
                        FROM calendar
                        WHERE campaign_name = :campaign_name
                        AND user_id = :user_id
                        ORDER BY post_date ASC
                    """
                    )

                    results = session.execute(
                        query, {"campaign_name": name, "user_id": self.current_user_id}
                    ).fetchall()

                    if not results:
                        return json.dumps(
                            {
                                "success": True,
                                "tool": "schedule",
                                "action": "status",
                                "campaign_name": name,
                                "posts_with_assets": 0,
                                "total_posts": 0,
                                "completion_percentage": 0,
                                "pending_assets": 0,
                                "message": "Nenhum post programado ainda",
                                "post_ids": [],
                            },
                            ensure_ascii=False,
                        )

                    total_posts = len(results)
                    posts_with_assets = sum(1 for r in results if r[2] and r[2] > 0)
                    pending_assets = sum(1 for r in results if not r[2] or r[2] == 0)
                    post_ids = [r[1] for r in results if r[1]]

                    completion_percentage = (
                        int((posts_with_assets / total_posts * 100))
                        if total_posts > 0
                        else 0
                    )

                    return json.dumps(
                        {
                            "success": True,
                            "tool": "schedule",
                            "action": "status",
                            "campaign_name": name,
                            "posts_with_assets": posts_with_assets,
                            "total_posts": total_posts,
                            "completion_percentage": completion_percentage,
                            "pending_assets": pending_assets,
                            "post_ids": post_ids,
                            "message": f"{posts_with_assets}/{total_posts} posts com assets ({completion_percentage}% completo)",
                        },
                        ensure_ascii=False,
                    )

                finally:
                    session.close()

            except Exception as e:
                error(f"[SCHEDULE] Erro ao buscar status: {e}")
                return json.dumps(
                    {
                        "success": False,
                        "error": f"Erro ao buscar status: {str(e)}",
                        "tool": "schedule",
                    },
                    ensure_ascii=False,
                )

        else:
            return json.dumps(
                {
                    "success": False,
                    "error": "Action  obrigatrio. Use: 'today', 'schedule' ou 'status'",
                    "tool": "calendar",
                },
                ensure_ascii=False,
            )

    def _save_calendar_to_db(self, campaign_name: str, posts: list) -> tuple:
        """
        Salva posts de calendrio na tabela calendar do banco de dados.

        Args:
            campaign_name: Nome da campanha
            posts: Lista de posts com estrutura de _schedule_calendar_posts

        Returns:
            Tupla (saved_count, post_ids) onde:
            - saved_count: Nmero de posts salvos
            - post_ids: Lista com IDs dos posts salvos
        """
        debug(
            f"[CALENDAR-DB] Iniciando _save_calendar_to_db: campaign={campaign_name}, posts_count={len(posts)}"
        )
        debug(
            f"[CALENDAR-DB] Contexto: db_manager={bool(self.db_manager)}, user_id={self.current_user_id}, chat_id={self.current_chat_id}"
        )

        if not self.db_manager or not self.current_user_id or not self.current_chat_id:
            debug(f"[CALENDAR-DB] ERRO: Contexto incompleto!")
            raise Exception("Contexto do banco de dados no configurado")

        session = self.db_manager.get_session()
        saved_count = 0
        saved_post_ids = []

        try:
            from App.Core.Crunch.TablesSQL.Models import Calendar, User
            from datetime import datetime as dt

            # current_user_id  STRING (UUID) - fonte da verdade
            user_id_str = self.current_user_id
            debug(f"[CALENDAR-DB] Usando user_id (source of truth): {user_id_str}")

            for post in posts:
                try:
                    # Parsear data (dd.mm.aaaa ou dd/mm/aaaa -> date)
                    # Aceita tanto "date" (modo completo) quanto "day" (modo simplificado)
                    date_str = post.get("date") or post.get("day", "")
                    if date_str:
                        try:
                            date_str_normalized = date_str.replace(".", "/")
                            post_date = dt.strptime(
                                date_str_normalized, "%d/%m/%Y"
                            ).date()
                        except Exception as parse_err:
                            debug(
                                f"[CALENDAR-DB] Erro ao parsear data '{date_str}': {parse_err}, usando data atual"
                            )
                            post_date = dt.now().date()
                    else:
                        post_date = dt.now().date()

                    # Usar ID do post se existir, seno gerar novo UUID
                    post_id = post.get("id", str(uuid_lib.uuid4()))

                    # Extrair short_description
                    # Prioridade: short_description (modo simplificado) -> copy (modo completo)
                    short_description = post.get("short_description", "")
                    if not short_description:
                        copy = post.get("copy", "")
                        short_description = copy[:100].replace("\n", " ").strip()
                        if len(copy) > 100:
                            short_description += "..."

                    # Extrair content_type
                    content_type = post.get("content_type", "")

                    debug(
                        f"[CALENDAR-DB] Salvando post: id={post_id}, date={post_date}, desc={short_description[:50]}, content_type={content_type}"
                    )

                    # Criar registro de calendrio
                    calendar_record = Calendar(
                        post_id=post_id,
                        chat_id=self.current_chat_id,
                        user_id=user_id_str,
                        campaign_name=campaign_name,
                        post_date=post_date,
                        short_description=short_description,
                        content_type=content_type,
                        full_content=json.dumps(post, ensure_ascii=False),
                        status="toDo",
                    )

                    session.add(calendar_record)
                    saved_count += 1
                    saved_post_ids.append(post_id)
                    debug(f"[CALENDAR-DB] Post adicionado  sesso: {post_id}")

                except Exception as e:
                    debug(f"[CALENDAR-DB] Erro ao salvar post: {e}")
                    import traceback

                    debug(f"[CALENDAR-DB] Traceback: {traceback.format_exc()}")
                    continue

            debug(
                f"[CALENDAR-DB] Commitando {saved_count} posts para campanha: {campaign_name}"
            )
            session.commit()
            debug(f"[CALENDAR-DB] Post IDs salvos: {saved_post_ids}")
            debug(
                f"[CALENDAR-DB]  {saved_count} posts salvos com sucesso para campanha: {campaign_name}"
            )

        finally:
            session.close()

        return saved_count, saved_post_ids

    def _find_conflicting_schedule_dates(self, date_strings: list) -> list:
        """Retorna datas que j existem no calendrio do usurio atual."""
        if not self.db_manager or not self.current_user_id:
            return []
        try:
            from datetime import datetime as dt
            from App.Core.Crunch.TablesSQL.Models import Calendar

            session = self.db_manager.get_session()
            try:
                existing_rows = (
                    session.query(Calendar.post_date)
                    .filter(Calendar.user_id == self.current_user_id)
                    .all()
                )
                existing_dates = {str(row[0]) for row in existing_rows}
                conflicts = []
                for date_str in date_strings:
                    try:
                        normalized = str(date_str).replace(".", "/")
                        parsed = dt.strptime(normalized, "%d/%m/%Y").date()
                        if str(parsed) in existing_dates:
                            conflicts.append(date_str)
                    except Exception:
                        pass
                return conflicts
            finally:
                session.close()
        except Exception as e:
            debug(f"[SCHEDULE] Erro ao verificar datas duplicadas: {e}")
            return []

    def _schedule_calendar_posts(
        self, campaign_name: str, posts_input: list
    ) -> Dict[str, Any]:
        """
        Cria estrutura de calendrio a partir de posts programados pela IA.

        Cada post da IA deve ter: date (dd.mm.aaaa), platform, stage, content_type, copy, e opcionalmente type.

        Gera post_ids sequenciais (P001, P002, ..., Pnnn) baseado na ordem.

        Args:
            campaign_name: Nome da campanha
            posts_input: Array de posts da IA com {date, platform, stage, content_type, copy, type?, ...}

        Returns:
            Dict com success, campaign (contendo posts com post_ids, datas parseadas, etc.)
        """
        try:
            days_pt = [
                "segunda",
                "tera",
                "quarta",
                "quinta",
                "sexta",
                "sbado",
                "domingo",
            ]
            posts = []
            dates_parsed = []

            # Processar cada post da IA
            for idx, post_input in enumerate(posts_input, 1):
                # Extrair dados
                date_str = post_input.get("date", "").strip()
                platform = post_input.get("platform", "").lower()
                stage = post_input.get("stage", "").lower()
                content_type = post_input.get("content_type", "").lower()
                copy = post_input.get("copy", "")
                post_type = post_input.get(
                    "type", self._infer_type(platform, content_type)
                )
                theme = post_input.get("theme", "")

                # Validar campos obrigatrios
                if not date_str:
                    return {
                        "success": False,
                        "error": f"Post {idx}: 'date'  obrigatrio (formato: dd.mm.aaaa)",
                    }
                if not platform:
                    return {
                        "success": False,
                        "error": f"Post {idx}: 'platform'  obrigatrio (instagram, tiktok, facebook, etc)",
                    }
                if not stage:
                    return {
                        "success": False,
                        "error": f"Post {idx}: 'stage'  obrigatrio (awareness, consideration, conversion, remarketing)",
                    }
                if not content_type:
                    return {
                        "success": False,
                        "error": f"Post {idx}: 'content_type'  obrigatrio (image ou video)",
                    }

                # Parsear data (dd.mm.aaaa -> datetime)
                try:
                    post_date = datetime.strptime(date_str, "%d.%m.%Y")
                    dates_parsed.append(post_date)
                except ValueError:
                    return {
                        "success": False,
                        "error": f"Post {idx}: data invlida '{date_str}'. Use formato dd.mm.aaaa (ex: 05.03.2025)",
                    }

                # Gerar post_id: P{NNN}_{stage}_{numero_no_stage}
                # Ex: P001_awareness_001, P002_awareness_002, P003_consideration_001
                stage_count = sum(1 for p in posts if p.get("stage") == stage) + 1
                post_id = f"P{str(idx).zfill(3)}_{stage}_{str(stage_count).zfill(3)}"

                # Montar estrutura do post
                day_name = days_pt[post_date.weekday()]
                day_number = idx  # Ordenao sequencial

                post = {
                    "post_id": post_id,
                    "date": date_str,
                    "day_of_week": day_name,
                    "day_number": day_number,
                    "platform": platform,
                    "type": post_type,
                    "stage": stage,
                    "theme": theme,
                    "copy": copy,
                    "content_type": content_type,
                    "required_assets": {
                        "images": 1 if content_type == "image" else 0,
                        "videos": 1 if content_type == "video" else 0,
                    },
                    "assets": {"images": [], "videos": []},
                    "status": "pending_assets",
                }
                posts.append(post)

            # Calcular datas de incio e fim
            if not dates_parsed:
                return {"success": False, "error": "Nenhum post vlido fornecido"}

            start_date_str = min(dates_parsed).strftime("%d.%m.%Y")
            end_date_str = max(dates_parsed).strftime("%d.%m.%Y")
            duration_days = (max(dates_parsed) - min(dates_parsed)).days

            # Extrair plataformas nicas
            platforms = list(set([p.get("platform") for p in posts]))

            # Criar estrutura final
            return {
                "success": True,
                "campaign": {
                    "name": campaign_name,
                    "created_at": datetime.now().isoformat(),
                    "start_date": start_date_str,
                    "end_date": end_date_str,
                    "duration_days": duration_days,
                    "total_posts": len(posts),
                    "platforms": platforms,
                    "posts": posts,
                },
            }

        except Exception as e:
            error(f"[CALENDAR] Erro ao programar posts: {e}")
            return {"success": False, "error": f"Erro ao programar posts: {str(e)}"}

    def _infer_type(self, platform: str, content_type: str) -> str:
        """Infere o tipo de post baseado na plataforma e content_type."""
        platform_lower = platform.lower()
        content_type_lower = content_type.lower()

        if platform_lower == "instagram":
            return "reel" if content_type_lower == "video" else "carousel"
        elif platform_lower == "tiktok":
            return "video"
        elif platform_lower == "facebook":
            return "post"
        else:
            return "story" if content_type_lower == "image" else "video"

    def _generate_calendar_data(
        self, campaign_name: str, template: str
    ) -> Dict[str, Any]:
        """
        Gera estrutura de calendrio baseado no template.
        """
        today = datetime.now()
        posts = []

        # Estrutura base: 11 posts para campanha de 28 dias
        posts_config = [
            {
                "post_id": "P001_awareness_001",
                "day_offset": 0,
                "platform": "instagram",
                "type": "story",
                "stage": "awareness",
                "theme": "Apresentao da marca",
                "copy": f"Conhea {campaign_name}",
                "content_type": "image",
            },
            {
                "post_id": "P002_awareness_002",
                "day_offset": 2,
                "platform": "tiktok",
                "type": "video",
                "stage": "awareness",
                "theme": "Storytelling",
                "copy": f"A histria de {campaign_name}",
                "content_type": "video",
            },
            {
                "post_id": "P003_awareness_003",
                "day_offset": 5,
                "platform": "instagram",
                "type": "carousel",
                "stage": "awareness",
                "theme": "Identidade visual",
                "copy": f"Conhea nossa identidade",
                "content_type": "image",
            },
            {
                "post_id": "P004_consideration_001",
                "day_offset": 10,
                "platform": "facebook",
                "type": "post",
                "stage": "consideration",
                "theme": "Prova social",
                "copy": "Clientes satisfeitos",
                "content_type": "image",
            },
            {
                "post_id": "P005_consideration_002",
                "day_offset": 14,
                "platform": "instagram",
                "type": "reel",
                "stage": "consideration",
                "theme": "Tutorial/Educativo",
                "copy": "Como funciona",
                "content_type": "video",
            },
            {
                "post_id": "P006_consideration_003",
                "day_offset": 18,
                "platform": "tiktok",
                "type": "video",
                "stage": "consideration",
                "theme": "Comparao vs concorrentes",
                "copy": "Por que somos diferentes",
                "content_type": "video",
            },
            {
                "post_id": "P007_conversion_001",
                "day_offset": 22,
                "platform": "instagram",
                "type": "story",
                "stage": "conversion",
                "theme": "Urgncia/Escassez",
                "copy": "ltima chance!",
                "content_type": "image",
            },
            {
                "post_id": "P008_conversion_002",
                "day_offset": 24,
                "platform": "facebook",
                "type": "post",
                "stage": "conversion",
                "theme": "Oferta especial",
                "copy": "Desconto limitado",
                "content_type": "image",
            },
            {
                "post_id": "P009_conversion_003",
                "day_offset": 26,
                "platform": "tiktok",
                "type": "video",
                "stage": "conversion",
                "theme": "CTA direto",
                "copy": "Compre agora",
                "content_type": "video",
            },
            {
                "post_id": "P010_remarketing_001",
                "day_offset": 27,
                "platform": "instagram",
                "type": "ad",
                "stage": "remarketing",
                "theme": "Recuperao de carrinho",
                "copy": "Voc deixou algo para trs",
                "content_type": "image",
            },
            {
                "post_id": "P011_remarketing_002",
                "day_offset": 28,
                "platform": "facebook",
                "type": "ad",
                "stage": "remarketing",
                "theme": "Segunda chance",
                "copy": "Volte e complete sua compra",
                "content_type": "image",
            },
        ]

        # Preencher com datas
        days_pt = ["segunda", "tera", "quarta", "quinta", "sexta", "sbado", "domingo"]

        for config in posts_config:
            post_date = datetime.fromtimestamp(
                today.timestamp() + config["day_offset"] * 86400
            )
            date_str = post_date.strftime("%d.%m.%Y")
            day_name = days_pt[post_date.weekday()]

            post = {
                "post_id": config["post_id"],
                "date": date_str,
                "day_of_week": day_name,
                "day_number": config["day_offset"] + 1,
                "platform": config["platform"],
                "type": config["type"],
                "stage": config["stage"],
                "theme": config["theme"],
                "copy": config["copy"],
                "content_type": config["content_type"],
                "required_assets": {
                    "images": 1 if config["content_type"] == "image" else 0,
                    "videos": 1 if config["content_type"] == "video" else 0,
                },
                "assets": {"images": [], "videos": []},
                "status": "pending_assets",
            }
            posts.append(post)

        start_date = today.strftime("%d.%m.%Y")
        end_date = datetime.fromtimestamp(today.timestamp() + 28 * 86400).strftime(
            "%d.%m.%Y"
        )

        return {
            "success": True,
            "campaign": {
                "name": campaign_name,
                "created_at": today.isoformat(),
                "start_date": start_date,
                "end_date": end_date,
                "duration_days": 28,
                "total_posts": len(posts_config),
                "platforms": ["instagram", "facebook", "tiktok"],
                "posts": posts,
            },
        }

    def _summarize_calendar_posts(self, posts: list) -> Dict[str, Any]:
        """Retorna resumo dos posts por stage."""
        summary = {
            "awareness": 0,
            "consideration": 0,
            "conversion": 0,
            "remarketing": 0,
        }

        for post in posts:
            stage = post.get("stage", "")
            if stage in summary:
                summary[stage] += 1

        return summary

    def _save_calendar_json(
        self, campaign_name: str, calendar_data: Dict[str, Any]
    ) -> None:
        """Salva calendrio em arquivo JSON."""
        try:
            from pathlib import Path

            storage_path = Path(StorageManager.LOCAL_STORAGE_BASE) / "calendarios"
            storage_path.mkdir(parents=True, exist_ok=True)

            filename = f"CalendarioPostagens_{campaign_name.replace(' ', '_')}.json"
            filepath = storage_path / filename

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump({"campaign": calendar_data}, f, ensure_ascii=False, indent=2)

            debug(f"[CALENDAR] Calendrio salvo em: {filepath}")
        except Exception as e:
            debug(f"[CALENDAR] Erro ao salvar calendrio: {e}")

    def _execute_context_calendar(self) -> str:
        """
        Retorna informaes sobre o calendrio de postagens do usurio.
        Busca todos os agendamentos registrados no banco de dados.

        Returns:
            JSON com o calendrio do usurio.
        """
        if not self.db_manager or not self.current_user_id:
            return json.dumps(
                {
                    "success": False,
                    "error": "Contexto do banco de dados ou usurio no configurado.",
                    "tool": "context",
                },
                ensure_ascii=False,
            )

        session = self.db_manager.get_session()
        try:
            from App.Core.Crunch.TablesSQL.Models import Calendar

            # Buscar posts futuros e passados recentes (ex: ltimos 30 dias at o futuro)
            posts = (
                session.query(Calendar)
                .filter(Calendar.user_id == self.current_user_id)
                .order_by(Calendar.post_date.asc())
                .all()
            )

            if not posts:
                return json.dumps(
                    {
                        "success": True,
                        "tool": "context",
                        "type": "calendar",
                        "message": "Voc ainda no possui nenhum post agendado no calendrio.",
                        "total_posts": 0,
                        "calendar": [],
                    },
                    ensure_ascii=False,
                )

            calendar_data = []
            for post in posts:
                calendar_data.append(
                    {
                        "id": post.post_id,
                        "campaign_name": post.campaign_name,
                        "date": (
                            post.post_date.strftime("%d/%m/%Y")
                            if post.post_date
                            else ""
                        ),
                        "platform": post.platform,
                        "content_type": post.content_type,
                        "short_description": post.short_description,
                        "status": "with_asset" if post.asset_id else "pending_asset",
                    }
                )

            return json.dumps(
                {
                    "success": True,
                    "tool": "context",
                    "type": "calendar",
                    "message": f"Voc possui {len(calendar_data)} post(s) no calendrio.",
                    "total_posts": len(calendar_data),
                    "calendar": calendar_data,
                },
                ensure_ascii=False,
            )

        except Exception as e:
            error(f"[_EXECUTE_CONTEXT_CALENDAR] Erro: {e}")
            return json.dumps(
                {
                    "success": False,
                    "error": f"Erro ao obter calendrio: {str(e)}",
                    "tool": "context",
                },
                ensure_ascii=False,
            )
        finally:
            session.close()

    def _get_calendar_context(self) -> str:
        """
        Retorna contexto do calendrio: data de hoje + agendamentos j existentes do user.

        Returns:
            JSON com:
            - today: data/hora atual (timestamp ISO)
            - total_schedules: quantidade de agendamentos
            - schedules: lista de agendamentos com campaign_name, short_description, status, post_date, created_at
        """
        if not self.current_user_id or not self.db_manager:
            return json.dumps(
                {
                    "success": True,
                    "tool": "context",
                    "type": "calendar",
                    "today": datetime.now().isoformat(),
                    "total_schedules": 0,
                    "schedules": [],
                    "message": "Nenhum agendamento ainda",
                },
                ensure_ascii=False,
            )

        try:
            session = self.db_manager.get_session()
            try:
                from sqlalchemy import text

                # Buscar todos os agendamentos deste user (STRING user_id)
                query = text(
                    """
                    SELECT
                        id,
                        post_id,
                        campaign_name,
                        short_description,
                        status,
                        post_date,
                        created_at
                    FROM calendar
                    WHERE user_id = :user_id
                    ORDER BY post_date ASC, created_at DESC
                """
                )

                results = session.execute(
                    query, {"user_id": self.current_user_id}
                ).fetchall()

                schedules = []
                for row in results:
                    (
                        schedule_id,
                        post_id,
                        campaign_name,
                        short_description,
                        status,
                        post_date,
                        created_at,
                    ) = row
                    schedules.append(
                        {
                            "id": schedule_id,
                            "post_id": post_id,
                            "campaign_name": campaign_name or "Sem campanha",
                            "short_description": short_description or "Sem descrio",
                            "status": status,
                            "post_date": str(post_date) if post_date else None,
                            "created_at": str(created_at) if created_at else None,
                        }
                    )

                return json.dumps(
                    {
                        "success": True,
                        "tool": "context",
                        "type": "calendar",
                        "today": datetime.now().isoformat(),
                        "total_schedules": len(schedules),
                        "schedules": schedules,
                        "message": f"Total de {len(schedules)} agendamento(s) no calendrio",
                    },
                    ensure_ascii=False,
                )

            finally:
                session.close()

        except Exception as e:
            debug(f"[CALENDAR-CONTEXT] Erro ao listar agendamentos: {e}")
            return json.dumps(
                {
                    "success": False,
                    "tool": "context",
                    "type": "calendar",
                    "error": str(e),
                },
                ensure_ascii=False,
            )

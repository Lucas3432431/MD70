"""
_task.py — Mixin extraído de Core.py.
Core.py importa este módulo e herda TaskMixin.
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


class TaskMixin:
    def _build_tasks_json(self) -> Dict[str, Any]:
        """
        Constri JSON com todas as tasks, steps e status atuais (para compatibility)

        Returns:
            Dict com estrutura de tasks
        """
        tasks_by_name = {}

        for (task_name, step_context), status in self.pending_tasks.items():
            if task_name not in tasks_by_name:
                tasks_by_name[task_name] = {"name": task_name, "steps": []}
            tasks_by_name[task_name]["steps"].append(
                {"step": step_name, "status": status}
            )

        return {
            "success": True,
            "total_tasks": len(tasks_by_name),
            "tasks": list(tasks_by_name.values()),
        }

    def _save_tasks_to_db(self, task_id_group: str) -> Dict[tuple, str]:
        """
        Salva tasks no banco de dados (tabela tasks)

        Args:
            task_id_group: UUID do grupo de tasks (mesmo para todos os steps)

        Returns:
            Dict mapeando (task_name, step_context) -> step_id (UUID do step)
        """
        step_id_map = {}

        if not self.db_manager or not self.current_user_id or not self.current_chat_id:
            debug("[TASK-DB] Contexto incompleto para salvar tasks")
            return step_id_map

        try:
            session = self.db_manager.get_session()
            saved_count = 0

            for (task_name, step_context), task_data in self.pending_tasks.items():
                step_id = str(uuid_lib.uuid4())  # UUID nico para cada step
                step_name = (
                    task_data.get("step_name", "")
                    if isinstance(task_data, dict)
                    else str(task_data)
                )
                status = (
                    task_data.get("status", "pending")
                    if isinstance(task_data, dict)
                    else task_data
                )

                success = self.db_manager.save_task(
                    session=session,
                    task_id=task_id_group,
                    step_id=step_id,
                    chat_id=self.current_chat_id,
                    user_id=self.current_user_id,
                    task_name=task_name,
                    step_name=step_name,
                    step_context=str(step_context),
                    status=status,
                )
                if success:
                    saved_count += 1
                    step_id_map[(task_name, step_context)] = step_id

            debug(
                f"[TASK-DB] {saved_count} tasks salvas para chat {self.current_chat_id}"
            )
            return step_id_map

        except Exception as e:
            debug(f"[TASK-DB] Erro ao salvar tasks no DB: {e}")
            return step_id_map

    def _save_tasks_json(self, task_id_group: str) -> Dict[tuple, str]:
        """
        Salva tasks no DB (principal)

        Args:
            task_id_group: UUID do grupo de tasks

        Returns:
            Dict mapeando (task_name, step_context) -> step_id
        """
        if not self.current_user_id or not self.current_chat_id:
            debug("[TASK] Contexto de chat no disponvel para salvar tasks")
            return {}

        # Salvar no DB (principal)
        return self._save_tasks_to_db(task_id_group)

    def _get_next_step_context(self, step_name: str) -> Dict[str, Any]:
        """
        Carrega o contexto do prximo step baseado no step_name atual.
        Procura pelo step por name, encontra seu nmero, e retorna o contexto do prximo.

        Args:
            step_name: Nome do step atual (ex: "pesquisa_anunciante")

        Returns:
            Dict com contexto do prximo step ou vazio se for o ltimo
        """
        try:
            from pathlib import Path

            core_dir = Path(__file__).parent.parent.parent.parent
            steps_file = core_dir / "Data" / "Agents" / "STEPS.json"

            with open(steps_file, "r", encoding="utf-8") as f:
                context_data = json.load(f)

            steps = context_data.get("steps", [])

            # Encontrar o nmero do step atual
            current_number = None
            for step in steps:
                if (
                    isinstance(step.get("name"), str)
                    and step.get("name").lower() == step_name.lower()
                ):
                    current_number = step.get("number")
                    break

            if current_number is None:
                return {}

            # Encontrar o prximo step (number = current_number + 1)
            next_number = current_number + 1
            for step in steps:
                if step.get("number") == next_number:
                    return {
                        "step_context": step.get("name", ""),
                        "step_name": step.get("name", ""),
                        "objective": step.get("objective", ""),
                        "instructions": step.get("instructions", ""),
                        "prerequisites": step.get("prerequisites", []),
                    }
        except Exception as e:
            debug(f"[TASK] Erro ao carregar prximo step aps {step_name}: {e}")

        return {}

    def _load_task_context_for_step(self, step_name: str) -> Dict[str, Any]:
        """
        Carrega o contexto (instrues, objetivo, prerequisitos) para um step especfico.
        Usado para retornar contexto automtico ao criar/completar tasks.
        Agora usa a mesma funcionalidade de context(type='steps', step='NOME') para consistncia.

        Args:
            step_name: Nome do step (ex: "PESQUISA_ANUNCIANTE", "PESQUISA_MERCADO", ...)

        Returns:
            Dict com {objective, instructions, prerequisites, name} ou vazio se no encontrar
        """
        try:
            # Usar a mesma funo de context para obter instrues de step
            context_result = self._execute_context_steps(step_name)
            result_data = json.loads(context_result)

            if result_data.get("success") and result_data.get("step_details"):
                step_details = result_data["step_details"]
                return {
                    "step_context": step_name,
                    "step_name": step_details.get("name", ""),
                    "objective": step_details.get("objective", ""),
                    "instructions": step_details.get("instructions", ""),
                    "prerequisites": step_details.get("prerequisites", []),
                }
        except Exception as e:
            debug(f"[TASK] Erro ao carregar contexto do step {step_name}: {e}")

        return {}

    def _execute_task(self, args: Dict[str, Any]) -> str:
        """
        Executa tool 'task' para CRIAR APENAS tarefas.
        """
        #  GATE: bloquear task() se SkillCopywriting estiver ativa (obsoleto)
        if self._check_copywriting_lookup_in_chat():
            return json.dumps(
                {
                    "success": False,
                    "error": "A ferramenta task()  obsoleta para o fluxo de copywriting.",
                    "tool": "task",
                    "hint": "No  mais necessrio declarar tasks. Prossiga diretamente para web-search() ou document(type='copywriting').",
                },
                ensure_ascii=False,
            )

        name = args.get("name", "").strip()

        # Validar name
        if not name:
            return json.dumps(
                {
                    "success": False,
                    "error": "Name  obrigatrio (nome do grupo de tasks)",
                    "tool": "task",
                },
                ensure_ascii=False,
            )

        # ========== CRIAR TASKS ==========
        # Sempre cria (no h ao explcita)
        steps_array = args.get("steps", [])
        if not isinstance(steps_array, list) or len(steps_array) < 1:
            return json.dumps(
                {
                    "success": False,
                    "error": "Steps  obrigatrio e deve ter pelo menos 1 item",
                    "tool": "task",
                },
                ensure_ascii=False,
            )

        #  Validar step names: no podem citar canais nem formatos de mdia
        _STEP_BLOCKED_CHANNELS = COPY_CHANNELS  # instagram, facebook, linkedin, x, google, youtube, tiktok, pinterest
        _STEP_BLOCKED_FORMATS = COPY_ASPECT_RATIOS  # 9:16, 16:9, 1:1, 4:5
        _step_violations = []
        for _si, _sitem in enumerate(steps_array):
            _sname = str(_sitem.get("step", "")).lower()
            _bad_ch = [c for c in _STEP_BLOCKED_CHANNELS if c in _sname]
            _bad_fmt = [f for f in _STEP_BLOCKED_FORMATS if f in _sname]
            if _bad_ch or _bad_fmt:
                _step_violations.append(
                    f"Step {_si + 1}: remova {', '.join(_bad_ch + _bad_fmt)}  steps descrevem a narrativa/ngulo do post, no canal ou formato"
                )
        if _step_violations:
            return json.dumps(
                {
                    "success": False,
                    "error": "Corrija os nomes dos steps antes de criar as tasks.",
                    "hint": f"{len(_step_violations)} step(s) com problema: {'; '.join(_step_violations)}",
                    "tool": "task",
                    "correction_required": _step_violations,
                },
                ensure_ascii=False,
            )

        #  Validar formato dos steps: apenas "Variao N: {categoria} - {ttulo}" + "Produzir criativos"
        _VARIATION_RE = re.compile(r"^variao\s+\d+\s*:", re.IGNORECASE)
        _GERACAO_STEP = "produzir criativos"
        _step_format_errors = []
        _has_geracao = False
        for _si, _sitem in enumerate(steps_array):
            _sname = str(_sitem.get("step", "")).strip()
            _sname_lower = _sname.lower()
            if _sname_lower == _GERACAO_STEP:
                _has_geracao = True
                continue
            if not _VARIATION_RE.match(_sname_lower):
                _step_format_errors.append(
                    f"Step {_si + 1} invlido: '{_sname}'. "
                    "Use o formato: 'Variao N: {categoria} - {ttulo}' "
                    "(ex: 'Variao 1: Criativo - Produto sobre fundo branco')"
                )
        if not _has_geracao:
            _step_format_errors.append(
                "Falta o step obrigatrio 'Produzir criativos' (deve ser o ltimo step)."
            )
        if _step_format_errors:
            return json.dumps(
                {
                    "success": False,
                    "error": "Formato de steps invlido.",
                    "hint": f"Corrija: {'; '.join(_step_format_errors)}",
                    "tool": "task",
                    "correction_required": _step_format_errors,
                },
                ensure_ascii=False,
            )

        #  Bloquear criao de novas tasks enquanto h tasks pendentes/in_progress no chat
        if self.db_manager and self.current_chat_id and self.current_user_id:
            try:
                from App.Core.Crunch.TablesSQL.Models import Task as _TM_check

                _ts_check = self.db_manager.get_session()
                try:
                    _open_steps = (
                        _ts_check.query(_TM_check)
                        .filter(
                            _TM_check.chat_id == self.current_chat_id,
                            _TM_check.user_id == self.current_user_id,
                            _TM_check.status.in_(["pending", "in_progress"]),
                        )
                        .all()
                    )
                finally:
                    _ts_check.close()
                if _open_steps:
                    _open_names = list({s.step_name for s in _open_steps})[:3]
                    return json.dumps(
                        {
                            "success": False,
                            "error": "Conclua as tasks em aberto antes de criar novas.",
                            "hint": f"{len(_open_steps)} step(s) ainda pendentes: {', '.join(_open_names)}{'...' if len(_open_steps) > 3 else ''}. Use context(type='tasks') para ver os IDs.",
                            "tool": "task",
                        },
                        ensure_ascii=False,
                    )
            except Exception as _oe:
                debug(f"[TASK] Erro ao verificar tasks em aberto: {_oe}")

        # Processar cada step
        results = []
        for step_item in steps_array:
            step_name = step_item.get("step", "").strip()
            status = step_item.get("status", "pending")

            if not step_name:
                continue

            results.append({"step": step_name, "status": status})

        if not results:
            return json.dumps(
                {
                    "success": False,
                    "error": "Nenhum step vlido foi fornecido",
                    "tool": "task",
                },
                ensure_ascii=False,
            )

        # Gerar UUID do grupo de tasks
        task_id_group = str(uuid_lib.uuid4())

        # Salvar apenas os steps dessa chamada no banco de dados
        if self.db_manager and self.current_chat_id and self.current_user_id:
            session = None
            try:
                session = self.db_manager.get_session()
                for step_item in results:
                    step_id = str(uuid_lib.uuid4())
                    step_item["step_id"] = step_id  # guardar para retornar na resposta
                    step_context = step_item.get("step_context", "PENDING")

                    self.db_manager.save_task(
                        session=session,
                        task_id=task_id_group,
                        step_id=step_id,
                        chat_id=self.current_chat_id,
                        user_id=self.current_user_id,
                        task_name=name,
                        step_name=step_item["step"],
                        step_context=step_context,
                        status=step_item["status"],
                    )
                debug(
                    f"[TASK] {len(results)} steps salvos no BD para task {task_id_group}"
                )
            except Exception as e:
                debug(f"[TASK] Erro ao salvar tasks no BD: {e}")
            finally:
                if session:
                    session.close()

        return json.dumps(
            {
                "success": True,
                "tool": "task",
                "task_id": task_id_group,
                "task_name": name,
                "tasks_created": len(results),
                "steps": results,
            },
            ensure_ascii=False,
        )

    def _check_tasks_after_quiz(self) -> bool:
        """Retorna True se tasks foi executado aps o ltimo quiz no chat."""
        if not self.db_manager or not self.current_chat_id:
            return False
        try:
            from App.Core.Crunch.TablesSQL.Models import IsolatedMessage, IsolatedChat

            session = self.db_manager.get_session()
            try:

                def _check(chat_id):
                    last_quiz = (
                        session.query(IsolatedMessage)
                        .filter(
                            IsolatedMessage.isolated_chat_id == chat_id,
                            IsolatedMessage.tool_called == "quiz",
                            IsolatedMessage.tool_call_type == "output",
                        )
                        .order_by(
                            IsolatedMessage.created_at.desc(), IsolatedMessage.id.desc()
                        )
                        .first()
                    )
                    if not last_quiz:
                        return False
                    tasks_after = (
                        session.query(IsolatedMessage)
                        .filter(
                            IsolatedMessage.isolated_chat_id == chat_id,
                            IsolatedMessage.tool_called == "task",
                            IsolatedMessage.tool_call_type == "input",
                            IsolatedMessage.id > last_quiz.id,
                        )
                        .first()
                    )
                    return tasks_after is not None

                result = _check(self.current_chat_id)
                if not result:
                    ic = (
                        session.query(IsolatedChat)
                        .filter(IsolatedChat.chat_id == self.current_chat_id)
                        .first()
                    )
                    if ic:
                        result = _check(str(ic.id))
                return result
            finally:
                session.close()
        except Exception as e:
            debug(f"[VALIDATE] Erro ao verificar tasks aps quiz: {e}")
            return False

    def _check_copywriting_tasks_in_chat(self) -> bool:
        """
        Verifica se h tasks criadas no chat atual (postagens propostas).
        """
        if not self.db_manager or not self.current_chat_id:
            return False
        try:
            session = self.db_manager.get_session()
            try:
                from App.Core.Crunch.TablesSQL.Models import IsolatedMessage

                task_msg = (
                    session.query(IsolatedMessage)
                    .filter(
                        IsolatedMessage.isolated_chat_id == self.current_chat_id,
                        IsolatedMessage.tool_called == "task",
                    )
                    .first()
                )
                if task_msg:
                    return True
                # fallback: verificar chat pai se existir
                from App.Core.Crunch.TablesSQL.Models import IsolatedChat

                chat = (
                    session.query(IsolatedChat)
                    .filter(IsolatedChat.chat_id == self.current_chat_id)
                    .first()
                )
                if chat and chat.parent_chat_id:
                    task_msg = (
                        session.query(IsolatedMessage)
                        .filter(
                            IsolatedMessage.isolated_chat_id == chat.parent_chat_id,
                            IsolatedMessage.tool_called == "task",
                        )
                        .first()
                    )
                    return bool(task_msg)
                return False
            finally:
                session.close()
        except Exception as e:
            debug(f"[VALIDATE] Erro ao verificar tasks copywriting: {e}")
            return False

    def _execute_steps(self, args: Dict[str, Any]) -> str:
        """
        Executa tool 'steps' — registra passos de uma tarefa sem interromper o loop do agente.
        Com pause=True, pausa o loop aguardando input do usuário.
        """
        name = args.get("name", "Tarefa").strip() or "Tarefa"
        steps_array = args.get("steps", [])
        pause = args.get("pause", False)

        if not isinstance(steps_array, list) or len(steps_array) < 1:
            return json.dumps(
                {
                    "success": False,
                    "error": "steps é obrigatório e deve ter pelo menos 1 item",
                    "tool": "steps",
                },
                ensure_ascii=False,
            )

        # Normalizar: aceita string simples ou objeto {step, status}
        results = []
        for item in steps_array:
            if isinstance(item, str):
                results.append({"step": item.strip(), "status": "pending"})
            elif isinstance(item, dict):
                step_name = str(item.get("step", "")).strip()
                if step_name:
                    results.append(
                        {"step": step_name, "status": item.get("status", "pending")}
                    )

        if not results:
            return json.dumps(
                {
                    "success": False,
                    "error": "Nenhum step válido fornecido",
                    "tool": "steps",
                },
                ensure_ascii=False,
            )

        # Salvar no banco de dados
        task_id_group = str(uuid_lib.uuid4())
        if self.db_manager and self.current_chat_id and self.current_user_id:
            session = None
            try:
                session = self.db_manager.get_session()
                for step_item in results:
                    step_id = str(uuid_lib.uuid4())
                    step_item["step_id"] = step_id
                    self.db_manager.save_task(
                        session=session,
                        task_id=task_id_group,
                        step_id=step_id,
                        chat_id=self.current_chat_id,
                        user_id=self.current_user_id,
                        task_name=name,
                        step_name=step_item["step"],
                        step_context="PENDING",
                        status=step_item["status"],
                    )
                debug(f"[STEPS] {len(results)} steps salvos para task {task_id_group}")
            except Exception as e:
                debug(f"[STEPS] Erro ao salvar no BD: {e}")
            finally:
                if session:
                    session.close()

        response = {
            "success": True,
            "tool": "steps",
            "task_id": task_id_group,
            "task_name": name,
            "steps_created": len(results),
            "steps": [{"step": s["step"], "status": s["status"]} for s in results],
            "message": f"Plano registrado: {len(results)} passo(s). Continue executando os passos em sequência.",
        }

        if pause:
            # Pausar o loop — frontend renderiza o plano e aguarda próxima mensagem do usuário
            response["status"] = "waiting"
            response["pending_tool_approval"] = True
            response[
                "message"
            ] = f"Plano registrado com {len(results)} passo(s). Aguardando confirmação para continuar."

        return json.dumps(response, ensure_ascii=False)

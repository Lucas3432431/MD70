"""
_document_validators.py — Mixin extraído de Core.py.
Core.py importa este módulo e herda DocumentValidatorsMixin.
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


class DocumentValidatorsMixin:
    def _validate_range_or_value(self, value: Any) -> bool:
        """
        Valida se value  integer simples ou array de 2 integers (range).

        Exemplos vlidos:
        - 50000 (integer simples)
        - 500000000 (integer simples)
        - [50000, 75000] (range)
        - [500000000, 600000000] (range)

        Returns:
            True se vlido, False caso contrrio
        """
        # Integer simples
        if isinstance(value, int) and value > 0:
            return True

        # Range de 2 integers
        if isinstance(value, list) and len(value) == 2:
            return (
                isinstance(value[0], int)
                and isinstance(value[1], int)
                and value[0] > 0
                and value[1] > 0
                and value[0] < value[1]
            )

        return False

    def _validate_business_canvas_json(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Valida estrutura do JSON do business_canvas com suporte a validao parcial.
        Aceita campos presentes e valida apenas eles, reportando warnings sobre campos faltantes/invlidos.

        Returns:
            Dict com:
            - 'valid': True se h ALGUM campo vlido, False se tudo est invlido
            - 'data': Os campos que passaram na validao
            - 'warnings': Lista de avisos sobre campos faltantes ou invlidos
            - 'error': None se h algo vlido, string descritiva se tudo invlido
        """
        warnings = []
        valid_data = {}

        # Validar favicon (SEMPRE OBRIGATRIO)
        if "favicon" in data and data.get("favicon", "").strip():
            valid_data["favicon"] = data.get("favicon").strip()
        else:
            warnings.append("missing: favicon (SEMPRE OBRIGATRIO)")

        # Validar public_target se presente
        if "public_target" in data:
            public_target = data.get("public_target", "").lower()
            if public_target in ["b2c", "b2b", "smb", "b2g"]:
                valid_data["public_target"] = public_target
            else:
                warnings.append(
                    f"public_target invlido: '{public_target}' (deve ser b2c, b2b, smb ou b2g)"
                )
        else:
            warnings.append("missing: public_target")

        # Validar consciousness_level  aceita 1 ou 2 nveis sequenciais
        if "consciousness_level" in data:
            LEVELS = [
                "Inconsciente",
                "Consciente do Problema",
                "Consciente da Soluo",
                "Consciente do Produto",
                "Totalmente Consciente",
            ]
            _LEVEL_NORM = {
                "inconsciente": "Inconsciente",
                "consciente do problema": "Consciente do Problema",
                "consciente da solucao": "Consciente da Soluo",
                "consciente da soluo": "Consciente da Soluo",
                "consciente do produto": "Consciente do Produto",
                "totalmente consciente": "Totalmente Consciente",
            }
            consciousness = data.get("consciousness_level")
            if isinstance(consciousness, str):
                consciousness = [
                    _LEVEL_NORM.get(consciousness.strip().lower(), consciousness)
                ]
            elif isinstance(consciousness, list):
                consciousness = [
                    _LEVEL_NORM.get(c.strip().lower(), c) if isinstance(c, str) else c
                    for c in consciousness
                ]
            if isinstance(consciousness, list) and 1 <= len(consciousness) <= 2:
                invalid = [c for c in consciousness if c not in LEVELS]
                if invalid:
                    warnings.append(
                        f"consciousness_level invlido: {invalid}. Use apenas: {', '.join(LEVELS)}"
                    )
                elif len(consciousness) == 2:
                    idx0 = LEVELS.index(consciousness[0])
                    idx1 = LEVELS.index(consciousness[1])
                    if idx1 != idx0 + 1:
                        warnings.append(
                            f"consciousness_level: os 2 nveis devem ser sequenciais adjacentes (ex: ['Consciente do Problema', 'Consciente da Soluo'])"
                        )
                    else:
                        valid_data["consciousness_level"] = consciousness
                else:
                    valid_data["consciousness_level"] = consciousness
            else:
                warnings.append(
                    f"consciousness_level invlido: deve ser string ou array de 1-2 nveis sequenciais. Nveis: {', '.join(LEVELS)}"
                )
        else:
            warnings.append("missing: consciousness_level")

        # Validar Lifecycle Operacional CRM (OBRIGATRIO)
        if "lifecycle_crm" in data:
            crm = data.get("lifecycle_crm", {})
            crm_fields = [
                "acquisition",
                "qualification",
                "conversion",
                "onboarding",
                "activation",
                "retention",
                "expansion",
                "indication",
                "churn",
            ]
            valid_crm = {}
            missing_crm = []
            for field in crm_fields:
                if field in crm and crm[field]:
                    valid_crm[field] = crm[field]
                else:
                    missing_crm.append(field)
            if missing_crm:
                warnings.append(
                    f"lifecycle_crm faltando campos: {', '.join(missing_crm)}"
                )
            if valid_crm:
                valid_data["lifecycle_crm"] = valid_crm
        else:
            warnings.append(
                "missing: lifecycle_crm (OBRIGATRIO  Lifecycle Operacional CRM)"
            )

        # Validar Lifecycle de Valor Percebido (OBRIGATRIO)
        if "lifecycle_value" in data:
            lv = data.get("lifecycle_value", {})
            lv_fields = ["aha_moment", "value_moment", "habit", "advocacy"]
            valid_lv = {}
            missing_lv = []
            for field in lv_fields:
                if field in lv and lv[field]:
                    valid_lv[field] = lv[field]
                else:
                    missing_lv.append(field)
            if missing_lv:
                warnings.append(
                    f"lifecycle_value faltando campos: {', '.join(missing_lv)}"
                )
            if valid_lv:
                valid_data["lifecycle_value"] = valid_lv
        else:
            warnings.append(
                "missing: lifecycle_value (OBRIGATRIO  Lifecycle de Valor Percebido)"
            )

        # Validar Pains/Gains se presente
        if "pains_gains" in data:
            valid_data["pains_gains"] = data.get("pains_gains")

        # Validar Market Sizing se presente
        if "market_sizing" in data:
            valid_data["market_sizing"] = data.get("market_sizing")

        # Validar GTM Strategy se presente
        if "gtm_strategy" in data:
            valid_data["gtm_strategy"] = data.get("gtm_strategy")

        # Validar Competitors se presente
        if "competitors" in data:
            valid_data["competitors"] = data.get("competitors")

        # Validar ICP  array de subgrupos, cada um com ttulo e perfil demogrfico/firmogrfico
        public_target = valid_data.get(
            "public_target", data.get("public_target", "").lower()
        )
        if "icp" in data:
            icp_list = data.get("icp", [])
            if not isinstance(icp_list, list) or len(icp_list) == 0:
                warnings.append("invalid: icp (deve ser array no-vazio de subgrupos)")
            else:
                valid_icps = []
                for idx, icp_entry in enumerate(icp_list):
                    if not isinstance(icp_entry, dict):
                        warnings.append(f"invalid: icp[{idx}] (deve ser objeto)")
                        continue
                    valid_icp = {}
                    label = icp_entry.get("title", f"ICP {idx+1}")
                    if icp_entry.get("title", "").strip():
                        valid_icp["title"] = icp_entry["title"].strip()
                    else:
                        warnings.append(f"missing: icp[{idx}].title")

                    def _validate_motivator(
                        profile: dict, path: str
                    ) -> tuple[dict, list]:
                        mot = profile.get("motivator")
                        mot_warnings = []
                        mot_valid = {}
                        if isinstance(mot, dict):
                            mot_type = mot.get("type", "")
                            mot_exp = str(mot.get("explanation", "")).strip()
                            if mot_type in ["pain", "ambition"] and mot_exp:
                                mot_valid["motivator"] = mot
                            else:
                                mot_warnings.append(
                                    f"invalid: {path}.motivator (type deve ser 'pain'|'ambition' com explanation)"
                                )
                        else:
                            mot_warnings.append(
                                f'missing: {path}.motivator ({{"type": "pain"|"ambition", "explanation": "..."}})'
                            )
                        return mot_valid, mot_warnings

                    if public_target == "b2c":
                        if "demographics" in icp_entry:
                            if not isinstance(icp_entry["demographics"], dict):
                                warnings.append(
                                    f"invalid: icp[{idx}].demographics (recebeu {type(icp_entry['demographics']).__name__}, deve ser objeto {{}})"
                                )
                            else:
                                demo_fields = [
                                    "age_range",
                                    "gender",
                                    "location",
                                    "social_class",
                                    "consumption_habits",
                                    "values",
                                ]
                                valid_demo = {}
                                missing_demo = []
                                for field in demo_fields:
                                    if icp_entry["demographics"].get(field):
                                        valid_demo[field] = icp_entry["demographics"][
                                            field
                                        ]
                                    else:
                                        missing_demo.append(field)
                                if missing_demo:
                                    warnings.append(
                                        f"Demographics ({label}) faltando: {', '.join(missing_demo)}"
                                    )
                                mot_valid, mot_warns = _validate_motivator(
                                    icp_entry["demographics"],
                                    f"icp[{idx}].demographics",
                                )
                                warnings.extend(mot_warns)
                                valid_demo.update(mot_valid)
                                if valid_demo:
                                    valid_icp["demographics"] = valid_demo
                        else:
                            warnings.append(
                                f"missing: icp[{idx}].demographics (OBRIGATRIO para B2C)"
                            )
                    elif public_target in ["b2b", "smb", "b2g"]:
                        if "firmografia" in icp_entry:
                            if not isinstance(icp_entry["firmografia"], dict):
                                warnings.append(
                                    f"invalid: icp[{idx}].firmografia (recebeu {type(icp_entry['firmografia']).__name__}, deve ser objeto {{}})"
                                )
                            else:
                                firm_fields = [
                                    "annual_revenue",
                                    "sector",
                                    "employees",
                                    "digital_maturity",
                                    "technology",
                                ]
                                valid_firm = {}
                                missing_firm = []
                                for field in firm_fields:
                                    if icp_entry["firmografia"].get(field):
                                        valid_firm[field] = icp_entry["firmografia"][
                                            field
                                        ]
                                    else:
                                        missing_firm.append(field)
                                if missing_firm:
                                    warnings.append(
                                        f"Firmografia ({label}) faltando: {', '.join(missing_firm)}"
                                    )
                                mot_valid, mot_warns = _validate_motivator(
                                    icp_entry["firmografia"], f"icp[{idx}].firmografia"
                                )
                                warnings.extend(mot_warns)
                                valid_firm.update(mot_valid)
                                if valid_firm:
                                    valid_icp["firmografia"] = valid_firm
                        else:
                            warnings.append(
                                f"missing: icp[{idx}].firmografia (OBRIGATRIO para {public_target.upper()})"
                            )
                    if valid_icp:
                        valid_icps.append(valid_icp)
                if valid_icps:
                    valid_data["icp"] = valid_icps
        else:
            warnings.append(
                "missing: icp (OBRIGATRIO  array de subgrupos com ttulo e perfil demogrfico/firmogrfico)"
            )

        # Validar Pains & Gains
        # pain = efeito psicolgico + impacto percebido (baseado no ICP), no mecnica de problema
        if "pains_gains" in data:
            pains_gains = data.get("pains_gains", {})
            valid_pains_gains = {}

            if "pain" in pains_gains:
                pain = pains_gains["pain"]
                if isinstance(pain, dict):
                    if (
                        pain.get("psychological_effect", "").strip()
                        and pain.get("perceived_impact", "").strip()
                    ):
                        valid_pains_gains["pain"] = pain
                    else:
                        warnings.append(
                            "invalid: pains_gains.pain (objeto deve ter 'psychological_effect' e 'perceived_impact' no-vazios)"
                        )
                elif isinstance(pain, str) and pain.strip():
                    valid_pains_gains["pain"] = pain
                else:
                    warnings.append(
                        "invalid: pains_gains.pain (deve ser string ou {psychological_effect, perceived_impact})"
                    )
            else:
                warnings.append("missing: pains_gains.pain")

            if "gain" in pains_gains and pains_gains["gain"]:
                valid_pains_gains["gain"] = pains_gains["gain"]
            else:
                warnings.append("missing: pains_gains.gain")

            if valid_pains_gains:
                valid_data["pains_gains"] = valid_pains_gains
        else:
            warnings.append("missing: pains_gains")

        # Validar obs se presente (anlise de implicaes de posicionamento)
        if "obs" in data:
            obs = data.get("obs")
            if isinstance(obs, str) and obs.strip():
                valid_data["obs"] = obs.strip()
            elif isinstance(obs, dict) and obs:
                valid_data["obs"] = obs

        # Validar Market Sizing se presente
        if "market_sizing" in data:
            market_sizing = data.get("market_sizing", {})
            valid_sizing = {}
            sizing_fields = ["tam", "sam", "som"]

            for field in sizing_fields:
                if field in market_sizing:
                    if self._validate_range_or_value(market_sizing.get(field)):
                        valid_sizing[field] = market_sizing[field]
                    else:
                        warnings.append(
                            f"invalid: market_sizing.{field} (deve ser integer ou range [min, max])"
                        )
                else:
                    warnings.append(f"missing: market_sizing.{field}")

            if valid_sizing:
                valid_data["market_sizing"] = valid_sizing
        else:
            warnings.append("missing: market_sizing")

        # Validar Viability se presente
        if "viability" in data:
            viability = data.get("viability", {})
            valid_viability = {}
            viability_fields = [
                "customer_bargaining_power",
                "threat_new_entrants",
                "rivalry",
            ]

            for field in viability_fields:
                if field in viability:
                    try:
                        val = int(viability.get(field))
                        if 1 <= val <= 10:
                            valid_viability[field] = val
                        else:
                            warnings.append(
                                f"invalid: viability.{field} (deve estar entre 1-10, recebido: {val})"
                            )
                    except (ValueError, TypeError):
                        warnings.append(
                            f"invalid: viability.{field} (deve ser numrico 1-10)"
                        )
                else:
                    warnings.append(f"missing: viability.{field}")

            if valid_viability:
                valid_data["viability"] = valid_viability
        else:
            warnings.append("missing: viability")

        # Validar GTM Strategy (SEMPRE OBRIGATRIO)
        if "gtm_strategy" in data:
            gtm_strategy = data.get("gtm_strategy", {})
            valid_gtm = {}
            gtm_fields = [
                "value_proposition",
                "customer_relationship",
                "channels",
                "revenue_streams",
            ]

            for field in gtm_fields:
                if field in gtm_strategy:
                    value = gtm_strategy.get(field)
                    # Validar que no est vazio
                    if (
                        field == "channels"
                        and isinstance(value, list)
                        and len(value) > 0
                    ):
                        valid_gtm[field] = value
                    elif (
                        field == "revenue_streams"
                        and isinstance(value, list)
                        and len(value) > 0
                    ):
                        valid_gtm[field] = value
                    elif (
                        field in ["value_proposition", "customer_relationship"]
                        and isinstance(value, str)
                        and value.strip()
                    ):
                        valid_gtm[field] = value
                    else:
                        warnings.append(
                            f"invalid: gtm_strategy.{field} (deve ser string no-vazio ou lista no-vazia)"
                        )
                else:
                    warnings.append(f"missing: gtm_strategy.{field} (OBRIGATRIO)")

            if valid_gtm:
                valid_data["gtm_strategy"] = valid_gtm
        else:
            warnings.append("missing: gtm_strategy (SEMPRE OBRIGATRIO)")

        # Validar Competitors se presente
        if "competitors" in data:
            competitors = data.get("competitors", [])
            valid_competitors = []

            if isinstance(competitors, list):
                for comp in competitors:
                    if not isinstance(comp, dict):
                        continue

                    valid_comp = {}

                    # name (obrigatrio para cada competidor)
                    if "name" in comp and comp.get("name", "").strip():
                        valid_comp["name"] = comp["name"].strip()
                    else:
                        warnings.append("invalid: competitors[].name (obrigatrio)")
                        continue

                    # favicon_url (opcional)
                    if "favicon_url" in comp and comp.get("favicon_url"):
                        valid_comp["favicon_url"] = comp["favicon_url"]

                    # presence (opcional)
                    if "presence" in comp:
                        presence = comp.get("presence", {})
                        valid_presence = {}

                        if "channels" in presence and isinstance(
                            presence.get("channels"), list
                        ):
                            valid_presence["channels"] = presence["channels"]

                        if valid_presence:
                            valid_comp["presence"] = valid_presence

                    # followers (opcional, inteiro)
                    if "followers" in comp:
                        try:
                            valid_comp["followers"] = int(comp["followers"])
                        except (ValueError, TypeError):
                            warnings.append(
                                f"invalid: competitors[{comp.get('name')}].followers (deve ser nmero)"
                            )

                    # ratings (opcional, array com source, volume, rating)
                    if "ratings" in comp and isinstance(comp.get("ratings"), list):
                        valid_ratings = []
                        for rating_obj in comp["ratings"]:
                            if not isinstance(rating_obj, dict):
                                continue

                            valid_rating = {}

                            # source (obrigatrio em cada rating)
                            if (
                                "source" in rating_obj
                                and rating_obj.get("source", "").strip()
                            ):
                                valid_rating["source"] = rating_obj["source"].strip()
                            else:
                                warnings.append(
                                    f"invalid: competitors[{comp.get('name')}].ratings[].source (obrigatrio)"
                                )
                                continue

                            # volume (opcional, inteiro)
                            if "volume" in rating_obj:
                                try:
                                    valid_rating["volume"] = int(rating_obj["volume"])
                                except (ValueError, TypeError):
                                    warnings.append(
                                        f"invalid: competitors[{comp.get('name')}].ratings[{rating_obj.get('source')}].volume (deve ser nmero)"
                                    )

                            # rating (opcional, float 0-10)
                            if "rating" in rating_obj:
                                try:
                                    rating_val = float(rating_obj["rating"])
                                    if 0 <= rating_val <= 10:
                                        valid_rating["rating"] = rating_val
                                    else:
                                        warnings.append(
                                            f"invalid: competitors[{comp.get('name')}].ratings[{rating_obj.get('source')}].rating (deve estar entre 0-10)"
                                        )
                                except (ValueError, TypeError):
                                    warnings.append(
                                        f"invalid: competitors[{comp.get('name')}].ratings[{rating_obj.get('source')}].rating (deve ser nmero 0-10)"
                                    )

                            if valid_rating:
                                valid_ratings.append(valid_rating)

                        if valid_ratings:
                            valid_comp["ratings"] = valid_ratings

                    if valid_comp:
                        valid_competitors.append(valid_comp)

            if valid_competitors:
                valid_data["competitors"] = valid_competitors
            elif competitors:
                warnings.append("competitors: nenhum competidor vlido fornecido")
        else:
            warnings.append("missing: competitors")

        # Se h algum campo vlido, retornar sucesso com avisos
        if valid_data:
            return {
                "valid": True,
                "data": valid_data,
                "warnings": warnings,
                "error": None,
            }
        else:
            # Se nenhum campo  vlido
            return {
                "valid": False,
                "data": {},
                "warnings": warnings,
                "error": "Nenhum campo vlido foi fornecido no business_canvas",
            }

    def _validate_brand_communication_json(
        self, data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Valida estrutura do JSON do brand_communication com suporte a validao parcial.
        Aceita campos presentes e valida apenas eles, reportando warnings sobre campos faltantes/invlidos.

        Returns:
            Dict com:
            - 'valid': True se h ALGUM campo vlido, False se tudo est invlido
            - 'data': Os campos que passaram na validao
            - 'warnings': Lista de avisos sobre campos faltantes ou invlidos
            - 'error': None se h algo vlido, string descritiva se tudo invlido
        """
        warnings = []
        valid_data = {}

        # Lista vlida de arqutipos
        valid_archetypes = [
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

        # Validar favicon (SEMPRE OBRIGATRIO)
        if "favicon" in data and data.get("favicon", "").strip():
            valid_data["favicon"] = data.get("favicon").strip()
        else:
            warnings.append("missing: favicon (SEMPRE OBRIGATRIO)")

        # Validar brand_archetype se presente
        if "brand_archetype" in data:
            archetype_data = data.get("brand_archetype", {})
            valid_archetype = {}

            # archetype (obrigatrio)
            if (
                "archetype" in archetype_data
                and archetype_data.get("archetype", "").strip()
            ):
                arch = archetype_data["archetype"].strip().lower()
                if arch in valid_archetypes:
                    valid_archetype["archetype"] = arch
                else:
                    warnings.append(
                        f"invalid: brand_archetype.archetype (deve ser um dos: {', '.join(valid_archetypes[:5])}...)"
                    )
            else:
                warnings.append("missing: brand_archetype.archetype (obrigatrio)")

            # slogan (obrigatrio)
            if "slogan" in archetype_data and archetype_data.get("slogan", "").strip():
                valid_archetype["slogan"] = archetype_data["slogan"].strip()
            else:
                warnings.append("missing: brand_archetype.slogan (obrigatrio)")

            # unicity (obrigatrio, 0-100)
            if "unicity" in archetype_data:
                try:
                    unicity = int(archetype_data["unicity"])
                    if 0 <= unicity <= 100:
                        valid_archetype["unicity"] = unicity
                    else:
                        warnings.append(
                            "invalid: brand_archetype.unicity (deve estar entre 0-100)"
                        )
                except (ValueError, TypeError):
                    warnings.append(
                        "invalid: brand_archetype.unicity (deve ser nmero 0-100)"
                    )
            else:
                warnings.append("missing: brand_archetype.unicity")

            # url (opcional - preenchido pela IA aps asset)
            if "url" in archetype_data and archetype_data.get("url", "").strip():
                valid_archetype["url"] = archetype_data["url"].strip()

            if valid_archetype:
                valid_data["brand_archetype"] = valid_archetype
        else:
            warnings.append("missing: brand_archetype")

        # Validar color_palette se presente
        if "color_palette" in data:
            color_data = data.get("color_palette", {})
            valid_colors = {}

            if "colors" in color_data and isinstance(color_data.get("colors"), list):
                colors = color_data["colors"]
                if len(colors) == 3:
                    valid_color_list = []
                    for idx, color in enumerate(colors):
                        valid_color = {}

                        # Validar hex code (obrigatrio)
                        if isinstance(color, dict) and "hex" in color:
                            hex_code = str(color["hex"]).strip()
                            if hex_code.startswith("#") and len(hex_code) == 7:
                                valid_color["hex"] = hex_code
                            else:
                                warnings.append(
                                    f"invalid: color_palette.colors[{idx}].hex (formato invlido, ex: #FF5733)"
                                )
                        elif isinstance(color, str):
                            # Aceitar string como backward compatibility
                            hex_code = color.strip()
                            if hex_code.startswith("#") and len(hex_code) == 7:
                                valid_color["hex"] = hex_code
                            else:
                                warnings.append(
                                    f"invalid: color_palette.colors[{idx}] (formato hex invlido)"
                                )
                        else:
                            warnings.append(
                                f"invalid: color_palette.colors[{idx}] (deve ser string hex ou objeto com hex e feeling)"
                            )

                        # Validar color name (opcional)
                        if (
                            isinstance(color, dict)
                            and "name" in color
                            and color.get("name", "").strip()
                        ):
                            valid_color["name"] = color["name"].strip()

                        # Validar feeling (obrigatrio se dict, opcional se string legacy)
                        if isinstance(color, dict) and "feeling" in color:
                            feeling = color["feeling"]
                            if isinstance(feeling, dict):
                                valid_feeling = {}
                                if (
                                    "name" in feeling
                                    and feeling.get("name", "").strip()
                                ):
                                    valid_feeling["name"] = feeling["name"].strip()
                                else:
                                    warnings.append(
                                        f"invalid: color_palette.colors[{idx}].feeling.name (obrigatrio)"
                                    )

                                if "value" in feeling:
                                    try:
                                        val = int(feeling["value"])
                                        if 1 <= val <= 100:
                                            valid_feeling["value"] = val
                                        else:
                                            warnings.append(
                                                f"invalid: color_palette.colors[{idx}].feeling.value (deve estar entre 1-100)"
                                            )
                                    except (ValueError, TypeError):
                                        warnings.append(
                                            f"invalid: color_palette.colors[{idx}].feeling.value (deve ser nmero 1-100)"
                                        )
                                else:
                                    warnings.append(
                                        f"missing: color_palette.colors[{idx}].feeling.value"
                                    )

                                if valid_feeling:
                                    valid_color["feeling"] = valid_feeling
                            else:
                                warnings.append(
                                    f"invalid: color_palette.colors[{idx}].feeling (deve ser objeto com name e value)"
                                )
                        elif isinstance(color, dict):
                            warnings.append(
                                f"missing: color_palette.colors[{idx}].feeling"
                            )

                        if valid_color.get("hex"):
                            valid_color_list.append(valid_color)

                    if len(valid_color_list) == 3:
                        valid_colors["colors"] = valid_color_list
                    else:
                        warnings.append(
                            f"invalid: color_palette.colors (precisa de 3 cores vlidas, obteve {len(valid_color_list)})"
                        )
                else:
                    warnings.append(
                        "invalid: color_palette.colors (deve ter exatamente 3 cores)"
                    )
            else:
                warnings.append(
                    "missing: color_palette.colors (deve ser array com 3 cores)"
                )

            if valid_colors:
                valid_data["color_palette"] = valid_colors

                # Verificar consistncia entre nomes das cores e resposta do user no quiz de cor
                color_names_text = " ".join(
                    c.get("name", "")
                    for c in valid_colors.get("colors", [])
                    if isinstance(c, dict) and c.get("name")
                ).lower()
                if color_names_text.strip():
                    quiz_blob = self._get_quiz_user_answers_blob()
                    if quiz_blob.strip():
                        palette_words = set(re.findall(r"\w{3,}", color_names_text))
                        quiz_words = set(re.findall(r"\w{3,}", quiz_blob))
                        if not (palette_words & quiz_words):
                            warnings.append(
                                "invalid: color_palette  nenhuma cor da paleta corresponde s preferncias informadas pelo cliente no quiz. "
                                "Escolha cores alinhadas com o que o cliente descreveu."
                            )
        else:
            warnings.append("missing: color_palette")

        # Validar font se presente
        if "font" in data:
            font_data = data.get("font", {})
            valid_font = {}

            if "primary" in font_data and font_data.get("primary", "").strip():
                valid_font["primary"] = font_data["primary"].strip()
            else:
                warnings.append("missing: font.primary")

            if "secondary" in font_data and font_data.get("secondary", "").strip():
                valid_font["secondary"] = font_data["secondary"].strip()

            if valid_font:
                valid_data["font"] = valid_font
        else:
            warnings.append("missing: font")

        # Validar voice_tone se presente
        if "voice_tone" in data:
            tone_data = data.get("voice_tone", {})
            valid_tone = {}

            for field in ["seriousness", "exclusivity", "tradition"]:
                if field in tone_data:
                    try:
                        val = int(tone_data[field])
                        if 1 <= val <= 10:
                            valid_tone[field] = val
                        else:
                            warnings.append(
                                f"invalid: voice_tone.{field} (deve estar entre 1-10)"
                            )
                    except (ValueError, TypeError):
                        warnings.append(
                            f"invalid: voice_tone.{field} (deve ser nmero 1-10)"
                        )
                else:
                    warnings.append(f"missing: voice_tone.{field}")

            if valid_tone:
                valid_data["voice_tone"] = valid_tone
        else:
            warnings.append("missing: voice_tone")

        # Validar target_pulse se presente
        if "target_pulse" in data:
            pulse_data = data.get("target_pulse", {})
            valid_pulse = {}

            for field in ["provocation", "warmth", "precision", "energy", "mystery"]:
                if field in pulse_data:
                    try:
                        val = int(pulse_data[field])
                        if 1 <= val <= 5:
                            valid_pulse[field] = val
                        else:
                            warnings.append(
                                f"invalid: target_pulse.{field} (deve estar entre 1-5)"
                            )
                    except (ValueError, TypeError):
                        warnings.append(
                            f"invalid: target_pulse.{field} (deve ser nmero 1-5)"
                        )
                else:
                    warnings.append(f"missing: target_pulse.{field}")

            if valid_pulse:
                valid_data["target_pulse"] = valid_pulse
        else:
            warnings.append("missing: target_pulse")

        # Validar moodboard se presente
        if "moodboard" in data:
            mood_data = data.get("moodboard", {})
            valid_mood = {}

            if "description" in mood_data and mood_data.get("description", "").strip():
                valid_mood["description"] = mood_data["description"].strip()
            else:
                warnings.append("invalid: moodboard.description (obrigatrio)")

            # url (opcional - preenchido pela IA aps asset)
            if "url" in mood_data and mood_data.get("url", "").strip():
                valid_mood["url"] = mood_data["url"].strip()

            if valid_mood:
                valid_data["moodboard"] = valid_mood
        else:
            warnings.append("missing: moodboard")

        # Validar brand_matrix se presente
        if "brand_matrix" in data:
            matrix_data = data.get("brand_matrix", {})
            if "dimensions" in matrix_data and isinstance(
                matrix_data.get("dimensions"), list
            ):
                dimensions = matrix_data["dimensions"]
                if len(dimensions) > 0:
                    valid_dims = []
                    for dim in dimensions:
                        if (
                            isinstance(dim, dict)
                            and dim.get("is", "").strip()
                            and dim.get("is_not", "").strip()
                        ):
                            valid_dims.append(
                                {
                                    "is": dim["is"].strip(),
                                    "is_not": dim["is_not"].strip(),
                                }
                            )
                        else:
                            warnings.append(
                                "invalid: brand_matrix.dimensions[] (cada item deve ter 'is' e 'is_not' no-vazios)"
                            )
                    if valid_dims:
                        valid_data["brand_matrix"] = {"dimensions": valid_dims}
                else:
                    warnings.append(
                        "invalid: brand_matrix.dimensions (deve ter pelo menos 1 objeto {is, is_not})"
                    )
            else:
                warnings.append(
                    "missing: brand_matrix.dimensions (deve ser array de {is, is_not})"
                )
        else:
            warnings.append("missing: brand_matrix")

        # Validar exclusive_avatar (SEMPRE OBRIGATRIO - preenchido pela IA aps asset)
        if "exclusive_avatar" in data:
            avatar_data = data.get("exclusive_avatar", {})
            if "url" in avatar_data and avatar_data.get("url", "").strip():
                valid_data["exclusive_avatar"] = {"url": avatar_data["url"].strip()}
            else:
                warnings.append("invalid: exclusive_avatar.url (obrigatrio)")
        else:
            warnings.append(
                "missing: exclusive_avatar (SEMPRE OBRIGATRIO - usar asset primeiro)"
            )

        # Validar models (inspiraes de empresas com comunicao parecida)
        if "models" in data:
            models_data = data.get("models", {})
            valid_models = {}

            if "inspirations" in models_data and isinstance(
                models_data.get("inspirations"), list
            ):
                inspirations = models_data["inspirations"]
                valid_inspirations = []

                for idx, inspiration in enumerate(inspirations):
                    if isinstance(inspiration, dict):
                        valid_inspiration = {}

                        # brand_name (obrigatrio)
                        if (
                            "brand_name" in inspiration
                            and inspiration.get("brand_name", "").strip()
                        ):
                            valid_inspiration["brand_name"] = inspiration[
                                "brand_name"
                            ].strip()
                        else:
                            warnings.append(
                                f"invalid: models.inspirations[{idx}].brand_name (obrigatrio)"
                            )

                        # favicon_url (obrigatrio)
                        if (
                            "favicon_url" in inspiration
                            and inspiration.get("favicon_url", "").strip()
                        ):
                            valid_inspiration["favicon_url"] = inspiration[
                                "favicon_url"
                            ].strip()
                        else:
                            warnings.append(
                                f"invalid: models.inspirations[{idx}].favicon_url (obrigatrio)"
                            )

                        if valid_inspiration.get(
                            "brand_name"
                        ) and valid_inspiration.get("favicon_url"):
                            valid_inspirations.append(valid_inspiration)

                if valid_inspirations:
                    valid_models["inspirations"] = valid_inspirations
                    valid_data["models"] = valid_models
            else:
                warnings.append(
                    "missing: models.inspirations (deve ser array de {brand_name, favicon_url})"
                )
        else:
            warnings.append("missing: models")

        # Validar theme_ideas se presente (OPCIONAL)
        if "theme_ideas" in data:
            theme_data = data.get("theme_ideas", {})
            valid_theme = {}

            # Validar cada subcampo (branding_ideas, top_funnel_ideas, mid_funnel_ideas, low_funnel_ideas)
            idea_fields = [
                "branding_ideas",
                "top_funnel_ideas",
                "mid_funnel_ideas",
                "low_funnel_ideas",
            ]
            for field in idea_fields:
                if field in theme_data:
                    ideas = theme_data.get(field)
                    if isinstance(ideas, list):
                        # Filtrar strings vazias e normalizar
                        valid_ideas = [
                            str(idea).strip() for idea in ideas if str(idea).strip()
                        ]
                        if valid_ideas:
                            valid_theme[field] = valid_ideas
                    else:
                        warnings.append(
                            f"invalid: theme_ideas.{field} (deve ser array de strings)"
                        )
                else:
                    # Campo opcional, no gera warning se ausente
                    pass

            if valid_theme:
                valid_data["theme_ideas"] = valid_theme

        # Se h algum campo vlido, retornar sucesso com avisos
        if valid_data:
            return {
                "valid": True,
                "data": valid_data,
                "warnings": warnings,
                "error": None,
            }
        else:
            return {
                "valid": False,
                "data": {},
                "warnings": warnings,
                "error": "Nenhum campo vlido foi fornecido no brand_communication",
            }

    def _validate_copywriting_document_id(
        self, document_id: str
    ) -> tuple[bool, str, dict]:
        """
        Valida se um document_id  realmente de um documento copywriting.
        Rejeita qualquer outro tipo de documento.
        Retorna os dados do documento para reutilizao.

        Args:
            document_id: ID do documento a validar

        Returns:
            Tuple (is_valid: bool, error_message: str, document_data: dict)
            - is_valid: True se  um document copywriting vlido
            - error_message: Mensagem de erro se invlido (vazio se vlido)
            - document_data: Dict com contedo do documento se vlido
        """
        if not document_id:
            return False, "document_id  obrigatrio", {}

        if not self.db_manager or not self.current_user_id:
            return False, "Contexto de banco de dados no configurado", {}

        try:
            session = self.db_manager.get_session()
            try:
                from sqlalchemy import text

                # Buscar documento especfico
                query = text(
                    """
                    SELECT tool_type, content
                    FROM documents
                    WHERE document_id = :document_id
                    AND user_id = :user_id
                """
                )
                result = session.execute(
                    query, {"document_id": document_id, "user_id": self.current_user_id}
                ).first()

                if not result:
                    return False, f"Documento com ID '{document_id}' no encontrado", {}

                tool_type = result[0]
                content = result[1]

                _ASSET_SUPPORTED_TYPES = {"copywriting", "catalog", "social_media"}
                if tool_type not in _ASSET_SUPPORTED_TYPES:
                    return (
                        False,
                        f"asset() aceita document_id de documentos do tipo copywriting, catalog ou social_media. Você forneceu '{tool_type}'.",
                        {},
                    )

                # Parsear contedo JSON
                try:
                    doc_data = (
                        json.loads(content) if isinstance(content, str) else content
                    )
                except:
                    doc_data = {}

                return True, "", doc_data

            finally:
                session.close()
        except Exception as e:
            debug(f"[ASSET] Erro ao validar document_id: {e}")
            return False, f"Erro ao validar documento: {str(e)}", {}

    def _validate_catalog_json(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Valida estrutura do JSON do catálogo.
        Usa o mesmo formato de assets do copywriting (structured prompt objects).
        Campos específicos de catalog: product_category, inspiration.
        Não exige: document_id, channels, framework, archetype, moodboard.
        """
        warnings = []
        valid_data = {}

        # product_category (required, enum)
        _valid_categories = [
            "clothing",
            "cosmetics",
            "accessories",
            "real_estate",
            "automotive",
            "pet",
            "retail",
        ]
        cat = str(data.get("product_category", "")).strip().lower()
        if cat in _valid_categories:
            valid_data["product_category"] = cat
        else:
            warnings.append(
                f"missing: product_category (OBRIGATÓRIO — deve ser um de: {', '.join(_valid_categories)})"
            )

        # aspect_ratio (required, same as copywriting — single format per generation)
        _valid_ratios = {"9:16", "16:9", "1:1", "4:5"}
        if "aspect_ratio" in data:
            _ar_raw = data["aspect_ratio"]
            if isinstance(_ar_raw, list):
                _filtered = [r for r in _ar_raw if str(r).strip() in _valid_ratios]
                if len(_filtered) > 1:
                    warnings.append(
                        "invalid: aspect_ratio — apenas UM formato por geração. "
                        f"Recebido: {_ar_raw}. Envie somente '9:16', '16:9', '1:1' ou '4:5'."
                    )
                elif _filtered:
                    valid_data["aspect_ratio"] = [_filtered[0]]
                else:
                    warnings.append(
                        f"invalid: aspect_ratio '{_ar_raw}' — válidos: '9:16', '16:9', '1:1', '4:5'."
                    )
            else:
                _ar_str = str(_ar_raw).strip()
                if _ar_str in _valid_ratios:
                    valid_data["aspect_ratio"] = [_ar_str]
                else:
                    warnings.append(
                        f"invalid: aspect_ratio '{_ar_raw}' — válidos: '9:16', '16:9', '1:1', '4:5'."
                    )
        else:
            warnings.append(
                "missing: aspect_ratio (OBRIGATÓRIO — envie UM formato: '9:16', '16:9', '1:1' ou '4:5')"
            )

        # should_keep_brand_identity (optional boolean)
        if "should_keep_brand_identity" in data:
            try:
                valid_data["should_keep_brand_identity"] = bool(
                    data["should_keep_brand_identity"]
                )
            except (ValueError, TypeError):
                warnings.append(
                    "invalid: should_keep_brand_identity (deve ser boolean true ou false)"
                )

        # inspiration (optional — list of {url, description} com análise visual da referência)
        _insp_raw = data.get("inspiration")
        if _insp_raw is not None:
            if isinstance(_insp_raw, list):
                valid_insp = []
                for insp in _insp_raw:
                    if isinstance(insp, dict):
                        _url = str(insp.get("url", "")).strip()
                        _desc = str(insp.get("description", "")).strip()
                        if _url:
                            valid_insp.append({"url": _url, "description": _desc})
                    elif isinstance(insp, str) and insp.strip():
                        valid_insp.append({"url": insp.strip(), "description": ""})
                if valid_insp:
                    valid_data["inspiration"] = valid_insp
            elif isinstance(_insp_raw, str) and _insp_raw.strip():
                valid_data["inspiration"] = [
                    {"url": _insp_raw.strip(), "description": ""}
                ]

        # caption (optional string)
        if "caption" in data and str(data.get("caption", "")).strip():
            valid_data["caption"] = str(data["caption"]).strip()

        # assets (required, same structured prompt format as copywriting)
        if "assets" in data and isinstance(data.get("assets"), list):
            assets = data["assets"]
            if len(assets) > 0:
                valid_assets = []
                for idx, asset in enumerate(assets):
                    if not isinstance(asset, dict):
                        warnings.append(f"invalid: assets[{idx}] (deve ser objeto)")
                        continue

                    valid_asset = {}
                    prompt_warnings = []

                    # asset_type
                    if "asset_type" in asset:
                        asset_type = asset.get("asset_type", "").strip()
                        if asset_type in self.COPY_ASSET_TYPES:
                            valid_asset["asset_type"] = asset_type
                        else:
                            warnings.append(
                                f"invalid: assets[{idx}].asset_type (deve ser um de: {', '.join(self.COPY_ASSET_TYPES)})"
                            )
                    else:
                        warnings.append(
                            f"missing: assets[{idx}].asset_type (OBRIGATÓRIO)"
                        )
                        continue

                    # format (optional per asset)
                    if "format" in asset and str(asset.get("format", "")).strip():
                        _fmt = str(asset["format"]).strip()
                        if _fmt in self.COPY_ASPECT_RATIOS:
                            valid_asset["format"] = _fmt
                        else:
                            warnings.append(
                                f"invalid: assets[{idx}].format (deve ser um de: {', '.join(self.COPY_ASPECT_RATIOS)})"
                            )

                    # prompt (structured object, required)
                    if "prompt" not in asset or not isinstance(
                        asset.get("prompt"), dict
                    ):
                        warnings.append(
                            f"missing: assets[{idx}].prompt (OBRIGATÓRIO - objeto estruturado com: "
                            "description, composition, environment, colors, illumination, emotion_style)"
                        )
                        continue

                    raw_prompt = asset["prompt"]
                    valid_prompt = {}

                    # has_realistic_people
                    if "has_realistic_people" in raw_prompt:
                        try:
                            valid_prompt["has_realistic_people"] = bool(
                                raw_prompt["has_realistic_people"]
                            )
                        except (ValueError, TypeError):
                            prompt_warnings.append(
                                f"invalid: assets[{idx}].prompt.has_realistic_people (deve ser boolean)"
                            )
                    else:
                        prompt_warnings.append(
                            f"missing: assets[{idx}].prompt.has_realistic_people (OBRIGATÓRIO)"
                        )

                    has_people = valid_prompt.get("has_realistic_people", False)

                    # subject_context (optional)
                    if (
                        "subject_context" in raw_prompt
                        and str(raw_prompt.get("subject_context", "")).strip()
                    ):
                        valid_prompt["subject_context"] = str(
                            raw_prompt["subject_context"]
                        ).strip()

                    # models (required when has_realistic_people=True)
                    if "models" in raw_prompt and isinstance(
                        raw_prompt.get("models"), list
                    ):
                        valid_models = []
                        for mi, model in enumerate(raw_prompt["models"]):
                            if not isinstance(model, dict):
                                prompt_warnings.append(
                                    f"invalid: assets[{idx}].prompt.models[{mi}] (deve ser objeto)"
                                )
                                continue
                            valid_model = {}
                            for mf in ["sex", "age", "skin_color", "style"]:
                                if mf in model and str(model.get(mf, "")).strip():
                                    valid_model[mf] = str(model[mf]).strip()
                                else:
                                    prompt_warnings.append(
                                        f"missing: assets[{idx}].prompt.models[{mi}].{mf} (OBRIGATÓRIO)"
                                    )
                            if "skin_texture_moisture" in model:
                                moisture = model["skin_texture_moisture"]
                                if moisture in self.COPY_ASSET_MOISTURE_VALUES:
                                    valid_model["skin_texture_moisture"] = moisture
                                else:
                                    prompt_warnings.append(
                                        f"invalid: assets[{idx}].prompt.models[{mi}].skin_texture_moisture "
                                        f"(deve ser um de: {', '.join(self.COPY_ASSET_MOISTURE_VALUES)})"
                                    )
                            else:
                                prompt_warnings.append(
                                    f"missing: assets[{idx}].prompt.models[{mi}].skin_texture_moisture (OBRIGATÓRIO)"
                                )
                            if valid_model:
                                valid_models.append(valid_model)
                        if valid_models:
                            valid_prompt["models"] = valid_models
                    elif has_people:
                        prompt_warnings.append(
                            f"missing: assets[{idx}].prompt.models (OBRIGATÓRIO quando has_realistic_people=true)"
                        )

                    # pose (required when has_realistic_people=True)
                    if "pose" in raw_prompt and str(raw_prompt.get("pose", "")).strip():
                        valid_prompt["pose"] = str(raw_prompt["pose"]).strip()
                    elif has_people:
                        prompt_warnings.append(
                            f"missing: assets[{idx}].prompt.pose (OBRIGATÓRIO quando has_realistic_people=true)"
                        )

                    # description
                    if (
                        "description" in raw_prompt
                        and str(raw_prompt.get("description", "")).strip()
                    ):
                        valid_prompt["description"] = str(
                            raw_prompt["description"]
                        ).strip()
                    else:
                        prompt_warnings.append(
                            f"missing: assets[{idx}].prompt.description (OBRIGATÓRIO)"
                        )

                    # composition
                    if "composition" in raw_prompt and isinstance(
                        raw_prompt["composition"], dict
                    ):
                        comp = raw_prompt["composition"]
                        valid_comp = {}
                        _raw_colors = (
                            raw_prompt.get("colors", {})
                            if isinstance(raw_prompt.get("colors"), dict)
                            else {}
                        )
                        _raw_bg = (
                            _raw_colors.get("background", {})
                            if isinstance(_raw_colors, dict)
                            else {}
                        )
                        _bg_type = (
                            _raw_bg.get("bg_type", "")
                            if isinstance(_raw_bg, dict)
                            else ""
                        )
                        if not has_people:
                            allowed_angles = self.COPY_ASSET_ANGLE_VALUES_PRODUCT
                        elif _bg_type in ("window", "color"):
                            allowed_angles = self.COPY_ASSET_ANGLE_VALUES_CLOSEUP
                        else:
                            allowed_angles = self.COPY_ASSET_ANGLE_VALUES
                        if "angle" in comp and comp["angle"] in allowed_angles:
                            valid_comp["angle"] = comp["angle"]
                            if comp["angle"] == "UGC" and not has_people:
                                prompt_warnings.append(
                                    f"invalid: assets[{idx}].prompt.composition.angle — UGC requer has_realistic_people=true"
                                )
                        else:
                            prompt_warnings.append(
                                f"invalid: assets[{idx}].prompt.composition.angle (deve ser um de: {', '.join(allowed_angles)})"
                            )
                        if valid_comp.get("angle") == "HyperCloseUpShot":
                            if (
                                "main_object" in comp
                                and str(comp.get("main_object", "")).strip()
                            ):
                                valid_comp["main_object"] = str(
                                    comp["main_object"]
                                ).strip()
                            else:
                                prompt_warnings.append(
                                    f"missing: assets[{idx}].prompt.composition.main_object (OBRIGATÓRIO quando angle=HyperCloseUpShot)"
                                )
                        if "grid" in comp and str(comp.get("grid", "")).strip():
                            valid_comp["grid"] = str(comp["grid"]).strip()
                        else:
                            prompt_warnings.append(
                                f"missing: assets[{idx}].prompt.composition.grid (OBRIGATÓRIO)"
                            )
                        if valid_comp:
                            valid_prompt["composition"] = valid_comp
                    else:
                        prompt_warnings.append(
                            f"missing: assets[{idx}].prompt.composition (OBRIGATÓRIO - objeto com angle e grid)"
                        )

                    # environment
                    if "environment" in raw_prompt and isinstance(
                        raw_prompt["environment"], dict
                    ):
                        env = raw_prompt["environment"]
                        valid_env = {}
                        if "place" in env and str(env.get("place", "")).strip():
                            valid_env["place"] = str(env["place"]).strip()
                        else:
                            prompt_warnings.append(
                                f"missing: assets[{idx}].prompt.environment.place (OBRIGATÓRIO)"
                            )
                        if "objects" in env:
                            raw_objs = env["objects"]
                            if isinstance(raw_objs, str) and raw_objs.strip():
                                valid_env["objects"] = raw_objs.strip()
                            elif isinstance(raw_objs, list) and len(raw_objs) > 0:
                                valid_obj_list = []
                                for obj in raw_objs:
                                    if (
                                        isinstance(obj, dict)
                                        and str(obj.get("item", "")).strip()
                                    ):
                                        obj_entry = {"item": str(obj["item"]).strip()}
                                        if "focus" in obj:
                                            obj_entry["focus"] = bool(obj["focus"])
                                        valid_obj_list.append(obj_entry)
                                    elif isinstance(obj, str) and obj.strip():
                                        valid_obj_list.append({"item": obj.strip()})
                                if valid_obj_list:
                                    valid_env["objects"] = valid_obj_list
                                else:
                                    prompt_warnings.append(
                                        f"missing: assets[{idx}].prompt.environment.objects (OBRIGATÓRIO)"
                                    )
                            else:
                                prompt_warnings.append(
                                    f"missing: assets[{idx}].prompt.environment.objects (OBRIGATÓRIO)"
                                )
                        else:
                            prompt_warnings.append(
                                f"missing: assets[{idx}].prompt.environment.objects (OBRIGATÓRIO)"
                            )
                        if valid_env:
                            valid_prompt["environment"] = valid_env
                    else:
                        prompt_warnings.append(
                            f"missing: assets[{idx}].prompt.environment (OBRIGATÓRIO - objeto com place e objects)"
                        )

                    # colors
                    if "colors" in raw_prompt and isinstance(
                        raw_prompt["colors"], dict
                    ):
                        colors = raw_prompt["colors"]
                        valid_colors = {}
                        allowed_bg_types = (
                            self.COPY_ASSET_BG_TYPE_VALUES_PRODUCT
                            if not has_people
                            else self.COPY_ASSET_BG_TYPE_VALUES
                        )
                        for role in ["background", "subject", "accent"]:
                            if role in colors and isinstance(colors[role], dict):
                                role_data = colors[role]
                                if (
                                    "hex" in role_data
                                    and isinstance(role_data["hex"], list)
                                    and len(role_data["hex"]) > 0
                                ):
                                    valid_role = {
                                        "hex": [str(h) for h in role_data["hex"]]
                                    }
                                    if (
                                        "detail" in role_data
                                        and str(role_data.get("detail", "")).strip()
                                    ):
                                        valid_role["detail"] = str(
                                            role_data["detail"]
                                        ).strip()
                                    if role == "background":
                                        bg_type = role_data.get("bg_type", "")
                                        if bg_type in allowed_bg_types:
                                            valid_role["bg_type"] = bg_type
                                        else:
                                            prompt_warnings.append(
                                                f"invalid: assets[{idx}].prompt.colors.background.bg_type "
                                                f"(deve ser um de: {', '.join(allowed_bg_types)})"
                                            )
                                    valid_colors[role] = valid_role
                        for color_field in ["saturation_contrast", "harmony"]:
                            if (
                                color_field in colors
                                and str(colors.get(color_field, "")).strip()
                            ):
                                valid_colors[color_field] = str(
                                    colors[color_field]
                                ).strip()
                            else:
                                prompt_warnings.append(
                                    f"missing: assets[{idx}].prompt.colors.{color_field} (OBRIGATÓRIO)"
                                )
                        if valid_colors:
                            valid_prompt["colors"] = valid_colors
                    else:
                        prompt_warnings.append(
                            f"missing: assets[{idx}].prompt.colors (OBRIGATÓRIO - objeto com background, subject, accent, saturation_contrast, harmony)"
                        )

                    # illumination
                    if (
                        "illumination" in raw_prompt
                        and str(raw_prompt.get("illumination", "")).strip()
                    ):
                        valid_prompt["illumination"] = str(
                            raw_prompt["illumination"]
                        ).strip()
                    else:
                        prompt_warnings.append(
                            f"missing: assets[{idx}].prompt.illumination (OBRIGATÓRIO)"
                        )

                    # emotion_style
                    if (
                        "emotion_style" in raw_prompt
                        and str(raw_prompt.get("emotion_style", "")).strip()
                    ):
                        valid_prompt["emotion_style"] = str(
                            raw_prompt["emotion_style"]
                        ).strip()
                    else:
                        prompt_warnings.append(
                            f"missing: assets[{idx}].prompt.emotion_style (OBRIGATÓRIO)"
                        )

                    # negative_prompt (optional)
                    if (
                        "negative_prompt" in raw_prompt
                        and str(raw_prompt.get("negative_prompt", "")).strip()
                    ):
                        valid_prompt["negative_prompt"] = str(
                            raw_prompt["negative_prompt"]
                        ).strip()

                    warnings.extend(prompt_warnings)

                    # Block asset if critical prompt fields are missing
                    _critical = [
                        "description",
                        "composition",
                        "environment",
                        "colors",
                        "illumination",
                        "emotion_style",
                    ]
                    if any(f not in valid_prompt for f in _critical):
                        continue
                    if (
                        valid_prompt.get("has_realistic_people")
                        and "models" not in valid_prompt
                    ):
                        continue
                    if (
                        valid_prompt.get("has_realistic_people")
                        and "pose" not in valid_prompt
                    ):
                        continue
                    if valid_prompt.get("composition", {}).get(
                        "angle"
                    ) == "HyperCloseUpShot" and "main_object" not in valid_prompt.get(
                        "composition", {}
                    ):
                        continue

                    valid_asset["prompt"] = valid_prompt

                    # reference_imgs (optional list)
                    if "reference_imgs" in asset and isinstance(
                        asset.get("reference_imgs"), list
                    ):
                        ref_imgs = asset["reference_imgs"]
                        if len(ref_imgs) > 0:
                            valid_asset["reference_imgs"] = [
                                str(img) for img in ref_imgs
                            ]

                    valid_asset["status"] = (
                        "done" if asset.get("status") == "done" else "toDo"
                    )

                    if (
                        valid_asset.get("asset_type")
                        and valid_asset.get("prompt") is not None
                    ):
                        valid_assets.append(valid_asset)

                if valid_assets:
                    valid_data["assets"] = valid_assets
                else:
                    warnings.append("invalid: assets (nenhum asset válido fornecido)")
            else:
                warnings.append("missing: assets (deve conter pelo menos 1 asset)")
        else:
            warnings.append("missing: assets (OBRIGATÓRIO — array com mínimo 1 item)")

        has_valid = bool(
            valid_data.get("product_category") and valid_data.get("assets")
        )
        return {
            "valid": has_valid,
            "data": valid_data,
            "warnings": warnings,
            "error": None
            if has_valid
            else "Campos obrigatórios ausentes ou inválidos no catalog",
        }

    def _validate_copy_json(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Valida estrutura do JSON do copywriting com suporte a validao parcial.
        Aceita campos presentes e valida apenas eles, reportando warnings sobre campos faltantes/invlidos.

        Returns:
            Dict com:
            - 'valid': True se h ALGUM campo vlido, False se tudo est invlido
            - 'data': Os campos que passaram na validao
            - 'warnings': Lista de avisos sobre campos faltantes ou invlidos
            - 'error': None se h algo vlido, string descritiva se tudo invlido
        """
        warnings = []
        valid_data = {}
        _product_type = ""  # preenchido na validao de document_id; usado nos assets

        #  GATE: documentos obrigatrios devem ter sido consultados antes do copywriting
        _copy_doc_id_for_gate = str(data.get("document_id", "")).strip()

        # Variações: bypass do gate de documentos — copywriting de variação não exige
        # consulta prévia de brand/canvas/product (já está no doc de referência)
        _is_variation_doc = (
            int((data.get("variation") or {}).get("count", 0)) > 0
            or self._check_variation_quiz_answered_in_chat()
        )

        if not _is_variation_doc and self.db_manager and self.current_chat_id:
            try:
                from App.Core.Crunch.TablesSQL.Models import (
                    IsolatedMessage as _IMcg,
                    Document as _DocModel,
                )

                _gc = self.db_manager.get_session()
                try:
                    _ctx_outputs = (
                        _gc.query(_IMcg)
                        .filter(
                            _IMcg.isolated_chat_id == self.current_chat_id,
                            _IMcg.tool_called == "context",
                            _IMcg.tool_call_type == "output",
                            _IMcg.content.ilike('%"type": "document%'),
                        )
                        .all()
                    )
                    _ctx_blob = " ".join(c.content for c in _ctx_outputs).lower()
                    _missing_reads = []
                    _required_calls = []  # chamadas exatas que o agente precisa fazer

                    # # GATE brand_communication — desativado temporariamente
                    # if "brand_communication" not in _ctx_blob:
                    #     _bc_doc = (
                    #         _gc.query(_DocModel)
                    #         .filter(
                    #             _DocModel.user_id == self.current_user_id,
                    #             _DocModel.tool_type == "brand_communication",
                    #         )
                    #         .order_by(_DocModel.created_at.desc())
                    #         .first()
                    #     )
                    #     _bc_id = (
                    #         _bc_doc.document_id
                    #         if _bc_doc
                    #         else "<brand_communication_id>"
                    #     )
                    #     _missing_reads.append("brand_communication")
                    #     _required_calls.append(
                    #         f"context(type='document', document_id='{_bc_id}')   brand_communication"
                    #     )

                    # # GATE branding (business_canvas) — desativado temporariamente
                    # if _gate_is_branding:
                    #     if "business_canvas" not in _ctx_blob:
                    #         _canvas_doc = (
                    #             _gc.query(_DocModel)
                    #             .filter(
                    #                 _DocModel.user_id == self.current_user_id,
                    #                 _DocModel.tool_type == "business_canvas",
                    #             )
                    #             .order_by(_DocModel.created_at.desc())
                    #             .first()
                    #         )
                    #         _canvas_id = (
                    #             _canvas_doc.document_id
                    #             if _canvas_doc
                    #             else "<business_canvas_id>"
                    #         )
                    #         _missing_reads.append("business_canvas")
                    #         _required_calls.append(
                    #             f"context(type='document', document_id='{_canvas_id}')   business_canvas"
                    #         )

                    # # GATE product (anúncio/funil) — desativado temporariamente
                    # else:
                    #     if _copy_doc_id_for_gate:
                    #         if _copy_doc_id_for_gate.lower() not in _ctx_blob:
                    #             _missing_reads.append("product")
                    #             _required_calls.append(
                    #                 f"context(type='document', document_id='{_copy_doc_id_for_gate}')   product"
                    #             )
                    #     else:
                    #         if 'document_type": "product' not in _ctx_blob:
                    #             _prod_doc = (
                    #                 _gc.query(_DocModel)
                    #                 .filter(
                    #                     _DocModel.user_id == self.current_user_id,
                    #                     _DocModel.tool_type == "product",
                    #                 )
                    #                 .order_by(_DocModel.created_at.desc())
                    #                 .first()
                    #             )
                    #             _prod_id = (
                    #                 _prod_doc.document_id
                    #                 if _prod_doc
                    #                 else "<product_id>"
                    #             )
                    #             _missing_reads.append("product")
                    #             _required_calls.append(
                    #                 f"context(type='document', document_id='{_prod_id}')   product (inclua document_id no copywriting)"
                    #             )

                    if _missing_reads:
                        _calls_str = " | ".join(_required_calls)
                        return {
                            "valid": False,
                            "data": {},
                            "warnings": [],
                            "error": (
                                f"Documentos obrigatrios no consultados: {_missing_reads}. "
                                f"Execute AGORA (antes de tentar document(type='copywriting') novamente): {_calls_str}"
                            ),
                            "hint": _calls_str,
                        }
                finally:
                    _gc.close()
            except Exception as _cge:
                debug(f"[COPY_VALIDATE] Erro ao verificar gate de contexto: {_cge}")

        if _is_variation_doc:
            # Variação: exige variation.reference_image (URL ou attachment_id) em vez de document_id
            _ref_img = str(
                (data.get("variation") or {}).get("reference_image", "")
            ).strip()
            if _ref_img:
                valid_data.setdefault("variation", {})["reference_image"] = _ref_img
            else:
                warnings.append(
                    "missing: variation.reference_image (OBRIGATÓRIO para variações — informe a URL da imagem "
                    "confirmada no quiz de imagem, ou o attachment_id enviado pelo usuário)"
                )
        else:
            # Fluxo padrão: exige document_id vinculado ao produto
            doc_id_raw = data.get("document_id", "")
            if isinstance(doc_id_raw, str) and doc_id_raw.strip():
                doc_id = doc_id_raw.strip()
                try:
                    from App.Core.Crunch.TablesSQL.Models import Document

                    session_temp = self.db_manager.get_session()
                    try:
                        doc_row = (
                            session_temp.query(Document)
                            .filter(
                                Document.document_id == doc_id,
                                Document.user_id == self.current_user_id,
                                Document.tool_type == "product",
                            )
                            .first()
                        )
                        if doc_row:
                            valid_data["document_id"] = doc_id
                            try:
                                _pc = (
                                    json.loads(doc_row.content)
                                    if isinstance(doc_row.content, str)
                                    else (doc_row.content or {})
                                )
                                _product_type = (
                                    str(_pc.get("product_type", "")).lower().strip()
                                )
                            except Exception:
                                _product_type = ""
                        else:
                            warnings.append(
                                f"invalid: document_id ('{doc_id}' no  um documento product vlido deste usurio). "
                                "Use context(type='documents') para obter o document_id correto."
                            )
                    finally:
                        session_temp.close()
                except Exception as e:
                    warnings.append(f"invalid: document_id (Erro ao validar: {str(e)})")
            else:
                warnings.append(
                    "missing: document_id (OBRIGATRIO  informe o document_id do produto. "
                    "Use context(type='documents') para recuper-lo.)"
                )

        # Optional: task_id + step_id (para marcar step como concludo automaticamente)
        _task_id_raw = str(data.get("task_id", "")).strip()
        _step_id_raw = str(data.get("step_id", "")).strip()
        if _task_id_raw and _step_id_raw:
            try:
                from App.Core.Crunch.TablesSQL.Models import Task as _TaskModel

                _sess = self.db_manager.get_session()
                try:
                    _step_row = (
                        _sess.query(_TaskModel)
                        .filter(
                            _TaskModel.step_id == _step_id_raw,
                            _TaskModel.user_id == self.current_user_id,
                            _TaskModel.task_id == _task_id_raw,
                        )
                        .first()
                    )
                    if _step_row:
                        valid_data["task_id"] = _task_id_raw
                        valid_data["step_id"] = _step_id_raw
                    else:
                        warnings.append(
                            f"invalid: step_id ('{_step_id_raw}' no encontrado ou no pertence a este usurio/task). "
                            "Se quiser vincular a uma task, use context(type='tasks') para ver os IDs corretos. "
                            "Caso contrrio, remova task_id e step_id para salvar sem vnculo."
                        )
                finally:
                    _sess.close()
            except Exception as e:
                warnings.append(f"invalid: task_id/step_id (erro ao validar: {str(e)})")
        elif _task_id_raw or _step_id_raw:
            # Se forneceu um mas no o outro
            if not _task_id_raw:
                warnings.append(
                    "missing: task_id (Para vincular a uma task, ambos task_id e step_id so necessrios. Use context(type='tasks') ou remova ambos.)"
                )
            if not _step_id_raw:
                warnings.append(
                    "missing: step_id (Para vincular a uma task, ambos task_id e step_id so necessrios. Use context(type='tasks') ou remova ambos.)"
                )

        # Required: is_paid_ad (boolean) — opcional para variações
        if "is_paid_ad" in data:
            try:
                valid_data["is_paid_ad"] = bool(data.get("is_paid_ad"))
            except (ValueError, TypeError):
                warnings.append("invalid: is_paid_ad (deve ser boolean True ou False)")
        elif not _is_variation_doc:
            warnings.append("missing: is_paid_ad (SEMPRE OBRIGATRIO)")

        # Required: should_keep_brand_identity (boolean)
        if "should_keep_brand_identity" in data:
            try:
                valid_data["should_keep_brand_identity"] = bool(
                    data["should_keep_brand_identity"]
                )
            except (ValueError, TypeError):
                warnings.append(
                    "invalid: should_keep_brand_identity (deve ser boolean true ou false)"
                )
        else:
            warnings.append(
                "missing: should_keep_brand_identity (OBRIGATÓRIO — "
                "true=manter rótulo/embalagem/identidade visual da marca legível e fiel na imagem final; "
                "false=estilo livre, sem exigência de rótulo visível)"
            )

        # Required: channels (lista de canais — aceita nomes individuais ou agrupados do quiz)
        # aspect_ratio NÃO é derivado de channels — deve ser enviado explicitamente pelo agente
        # Mapa de opes agrupadas  canais individuais
        _CHANNEL_BUNDLES = {
            "b2c": ["instagram", "google"],
            "b2b": ["linkedin", "x", "google"],
            "instagram e google": ["instagram", "google"],
            "linkedin, x e google": ["linkedin", "x", "google"],
            "instagram, facebook e tiktok": ["instagram", "facebook", "tiktok"],
            "linkedin e x": ["linkedin", "x"],
        }
        if "channels" in data:
            raw_ch = data.get("channels", [])
            if isinstance(raw_ch, str):
                raw_ch = [raw_ch]
            if isinstance(raw_ch, list) and raw_ch:
                # Expandir opes agrupadas
                expanded_ch = []
                for c in raw_ch:
                    cl = str(c).lower().strip()
                    # Verificar se  bundle (parcial match)
                    bundle_match = next(
                        (v for k, v in _CHANNEL_BUNDLES.items() if k in cl), None
                    )
                    if bundle_match:
                        expanded_ch.extend(bundle_match)
                    else:
                        expanded_ch.append(cl)
                # Deduplicate preserving order
                seen = set()
                expanded_ch = [c for c in expanded_ch if not (c in seen or seen.add(c))]
                valid_channels = [c for c in expanded_ch if c in self.COPY_CHANNELS]
                invalid_channels = [
                    c for c in expanded_ch if c not in self.COPY_CHANNELS
                ]
                if invalid_channels:
                    warnings.append(
                        f"invalid: channels (canais invlidos: {', '.join(invalid_channels)}; use: {', '.join(self.COPY_CHANNELS)})"
                    )
                if valid_channels:
                    valid_data["channels"] = valid_channels
                else:
                    warnings.append(
                        f"missing: channels (nenhum canal vlido; use: {', '.join(self.COPY_CHANNELS)})"
                    )
            else:
                warnings.append(
                    f"missing: channels (deve ser lista de canais; use: {', '.join(self.COPY_CHANNELS)})"
                )
        elif not _is_variation_doc:
            warnings.append(
                f"missing: channels (OBRIGATRIO  ex: ['instagram', 'facebook']; opes: {', '.join(self.COPY_CHANNELS)})"
            )

        # aspect_ratio: campo obrigatório — deve ser enviado explicitamente pelo agente
        # com o valor exato escolhido pelo usuário no quiz. Não é derivado de channels.
        # Apenas UM formato por geração é permitido.
        _valid_ratios = {"9:16", "16:9", "1:1", "4:5"}
        if "aspect_ratio" in data:
            _ar_raw = data["aspect_ratio"]
            if isinstance(_ar_raw, list):
                _filtered = [r for r in _ar_raw if str(r).strip() in _valid_ratios]
                if len(_filtered) > 1:
                    warnings.append(
                        f"invalid: aspect_ratio — apenas UM formato por geração é permitido. "
                        f"Recebido: {_ar_raw}. Envie somente o valor escolhido pelo usuário: "
                        f"'9:16', '16:9', '1:1' ou '4:5'."
                    )
                elif _filtered:
                    valid_data["aspect_ratio"] = [_filtered[0]]
                else:
                    warnings.append(
                        f"invalid: aspect_ratio '{_ar_raw}' — valores válidos: '9:16', '16:9', '1:1', '4:5'."
                    )
            else:
                _ar_str = str(_ar_raw).strip()
                if _ar_str in _valid_ratios:
                    valid_data["aspect_ratio"] = [_ar_str]
                else:
                    warnings.append(
                        f"invalid: aspect_ratio '{_ar_raw}' — valores válidos: '9:16', '16:9', '1:1', '4:5'."
                    )
        else:
            warnings.append(
                "missing: aspect_ratio (OBRIGATÓRIO — envie UM formato: '9:16', '16:9', '1:1' ou '4:5', "
                "usando a resposta exata do usuário no quiz)"
            )

        # Required: framework (enum - copywriting strategy)
        framework_chosen = None
        if "framework" in data:
            framework = data.get("framework", "").strip().upper()
            if framework in self.COPY_FRAMEWORK_VALUES:
                valid_data["framework"] = framework
                framework_chosen = framework
            else:
                warnings.append(
                    f"invalid: framework (deve ser um de: {', '.join(self.COPY_FRAMEWORK_VALUES)})"
                )
        elif not _is_variation_doc:
            warnings.append(
                "missing: framework (SEMPRE OBRIGATRIO - escolha uma estratgia: SLAP, ACC, 4Cs, PAS, AIDA ou FAB)"
            )

        # Framework-specific required fields validation
        if framework_chosen and framework_chosen in self.COPY_FRAMEWORK_FIELDS:
            framework_config = self.COPY_FRAMEWORK_FIELDS[framework_chosen]
            required_fields = framework_config.get("required_fields", [])
            framework_name = framework_config.get("name", framework_chosen)

            for field in required_fields:
                if field in data and data.get(field, "").strip():
                    valid_data[field] = data[field].strip()
                else:
                    warnings.append(
                        f"missing: {field} (OBRIGATRIO para framework {framework_name})"
                    )

        # Narrative fields (optional - apenas hypothesy  inspirador)
        optional_narrative_fields = [
            "hypothesy",
            "problem",
            "solution",
            "transformation",
        ]
        for field in optional_narrative_fields:
            if field in data and data.get(field, "").strip():
                valid_data[field] = data[field].strip()

        # StoryBrand 6 acts (optional - framework-specific)
        acts_fields = [
            "hook_pain_awareness",
            "empathy",
            "autority",
            "solution_contious",
            "product_contious",
            "offer_concious",
        ]
        for field in acts_fields:
            if field in data and data.get(field, "").strip():
                valid_data[field] = data[field].strip()

        # archetype (obrigatório — variações podem definir direto; demais devem vir do brand_communication)
        if "archetype" in data and str(data.get("archetype", "")).strip():
            valid_data["archetype"] = str(data["archetype"]).strip()
        elif not _is_variation_doc:
            warnings.append(
                "missing: archetype (OBRIGATRIO  use o arqutipo definido no brand_communication)"
            )

        # moodboard (obrigatório — variações podem definir direto; demais devem vir do brand_communication)
        if "moodboard" in data and str(data.get("moodboard", "")).strip():
            valid_data["moodboard"] = str(data["moodboard"]).strip()
        elif not _is_variation_doc:
            warnings.append(
                "missing: moodboard (OBRIGATRIO  use o moodboard definido no brand_communication)"
            )

        # Caption (plain string, required)
        if "caption" in data and data.get("caption", "").strip():
            valid_data["caption"] = data["caption"].strip()
        else:
            warnings.append(
                "missing: caption (SEMPRE OBRIGATRIO - pode ser string simples ou JSON estruturado)"
            )

        # Assets array (required, min 1)
        if "assets" in data and isinstance(data.get("assets"), list):
            assets = data["assets"]
            if len(assets) > 0:
                valid_assets = []

                for idx, asset in enumerate(assets):
                    if not isinstance(asset, dict):
                        warnings.append(f"invalid: assets[{idx}] (deve ser objeto)")
                        continue

                    valid_asset = {}

                    # asset_type (enum)
                    if "asset_type" in asset:
                        asset_type = asset.get("asset_type", "").strip()
                        if asset_type in self.COPY_ASSET_TYPES:
                            valid_asset["asset_type"] = asset_type
                        else:
                            warnings.append(
                                f"invalid: assets[{idx}].asset_type (deve ser um de: {', '.join(self.COPY_ASSET_TYPES)})"
                            )
                    else:
                        warnings.append(
                            f"missing: assets[{idx}].asset_type (OBRIGATRIO)"
                        )
                        continue

                    # format (opcional - sobrescreve aspect_ratio global do documento)
                    if "format" in asset and str(asset.get("format", "")).strip():
                        _fmt = str(asset["format"]).strip()
                        if _fmt in self.COPY_ASPECT_RATIOS:
                            valid_asset["format"] = _fmt
                        else:
                            warnings.append(
                                f"invalid: assets[{idx}].format (deve ser um de: {', '.join(self.COPY_ASPECT_RATIOS)})"
                            )

                    # Em modo variation, o prompt vem de variation_N.prompt — não validar estrutura aqui
                    if _is_variation_doc:
                        valid_asset["status"] = "toDo"
                        valid_assets.append(valid_asset)
                        continue

                    # prompt (objeto estruturado, obrigatrio)
                    if "prompt" not in asset or not isinstance(
                        asset.get("prompt"), dict
                    ):
                        warnings.append(
                            f"missing: assets[{idx}].prompt (OBRIGATRIO - deve ser objeto estruturado com campos: description, composition, environment, colors, illumination, emotion_style)"
                        )
                        continue

                    raw_prompt = asset["prompt"]
                    valid_prompt = {}
                    prompt_warnings = []

                    # has_realistic_people (boolean, obrigatrio)
                    if "has_realistic_people" in raw_prompt:
                        try:
                            valid_prompt["has_realistic_people"] = bool(
                                raw_prompt["has_realistic_people"]
                            )
                        except (ValueError, TypeError):
                            prompt_warnings.append(
                                f"invalid: assets[{idx}].prompt.has_realistic_people (deve ser boolean)"
                            )
                    else:
                        prompt_warnings.append(
                            f"missing: assets[{idx}].prompt.has_realistic_people (OBRIGATRIO)"
                        )

                    has_people = valid_prompt.get("has_realistic_people", False)

                    # Servios exigem pessoas reais  produto sem forma fsica no pode ser mostrado sozinho
                    if not has_people and _product_type == "service":
                        prompt_warnings.append(
                            f"invalid: assets[{idx}].prompt.has_realistic_people  produto do tipo 'service' exige "
                            "pessoas reais nos assets (has_realistic_people=true). Servios precisam de representao "
                            "humana; use modelos que personifiquem o resultado/benefcio."
                        )

                    # subject_context (string, opcional - contexto relacional/social da cena)
                    if (
                        "subject_context" in raw_prompt
                        and str(raw_prompt.get("subject_context", "")).strip()
                    ):
                        valid_prompt["subject_context"] = str(
                            raw_prompt["subject_context"]
                        ).strip()

                    # models (array de specs por modelo, obrigatrio se has_realistic_people=True)
                    # Cada modelo: sex, age, skin_color, style, skin_texture_moisture
                    if "models" in raw_prompt and isinstance(
                        raw_prompt.get("models"), list
                    ):
                        valid_models = []
                        for mi, model in enumerate(raw_prompt["models"]):
                            if not isinstance(model, dict):
                                prompt_warnings.append(
                                    f"invalid: assets[{idx}].prompt.models[{mi}] (deve ser objeto)"
                                )
                                continue
                            valid_model = {}
                            for mf in ["sex", "age", "skin_color", "style"]:
                                if mf in model and str(model.get(mf, "")).strip():
                                    valid_model[mf] = str(model[mf]).strip()
                                else:
                                    prompt_warnings.append(
                                        f"missing: assets[{idx}].prompt.models[{mi}].{mf} (OBRIGATRIO)"
                                    )
                            # skin_texture_moisture dentro de cada modelo
                            if "skin_texture_moisture" in model:
                                moisture = model["skin_texture_moisture"]
                                if moisture in self.COPY_ASSET_MOISTURE_VALUES:
                                    valid_model["skin_texture_moisture"] = moisture
                                else:
                                    prompt_warnings.append(
                                        f"invalid: assets[{idx}].prompt.models[{mi}].skin_texture_moisture (deve ser um de: {', '.join(self.COPY_ASSET_MOISTURE_VALUES)})"
                                    )
                            else:
                                prompt_warnings.append(
                                    f"missing: assets[{idx}].prompt.models[{mi}].skin_texture_moisture (OBRIGATRIO)"
                                )
                            if valid_model:
                                valid_models.append(valid_model)
                        if valid_models:
                            valid_prompt["models"] = valid_models
                    elif has_people:
                        prompt_warnings.append(
                            f"missing: assets[{idx}].prompt.models (OBRIGATRIO quando has_realistic_people=true  array com sex, age, skin_color, style, skin_texture_moisture de cada modelo)"
                        )

                    # pose (string, obrigatrio quando has_realistic_people=True)
                    if "pose" in raw_prompt and str(raw_prompt.get("pose", "")).strip():
                        valid_prompt["pose"] = str(raw_prompt["pose"]).strip()
                    elif has_people:
                        prompt_warnings.append(
                            f"missing: assets[{idx}].prompt.pose (OBRIGATRIO quando has_realistic_people=true  descreva a pose fisica do modelo: postura, posicao do corpo, membros, expressao corporal)"
                        )

                    # description (string, obrigatrio)
                    if (
                        "description" in raw_prompt
                        and str(raw_prompt.get("description", "")).strip()
                    ):
                        valid_prompt["description"] = str(
                            raw_prompt["description"]
                        ).strip()
                    else:
                        prompt_warnings.append(
                            f"missing: assets[{idx}].prompt.description (OBRIGATRIO)"
                        )

                    # composition (objeto com angle e grid, obrigatrio)
                    if "composition" in raw_prompt and isinstance(
                        raw_prompt["composition"], dict
                    ):
                        comp = raw_prompt["composition"]
                        valid_comp = {}
                        # Determina ngulos permitidos: HRP=false  produto; bg window/color  closeup obrigatrio
                        _raw_colors = (
                            raw_prompt.get("colors", {})
                            if isinstance(raw_prompt.get("colors"), dict)
                            else {}
                        )
                        _raw_bg = (
                            _raw_colors.get("background", {})
                            if isinstance(_raw_colors, dict)
                            else {}
                        )
                        _bg_type = (
                            _raw_bg.get("bg_type", "")
                            if isinstance(_raw_bg, dict)
                            else ""
                        )
                        if not has_people:
                            allowed_angles = self.COPY_ASSET_ANGLE_VALUES_PRODUCT
                        elif _bg_type in ("window", "color"):
                            allowed_angles = self.COPY_ASSET_ANGLE_VALUES_CLOSEUP
                        else:
                            allowed_angles = self.COPY_ASSET_ANGLE_VALUES
                        if "angle" in comp and comp["angle"] in allowed_angles:
                            valid_comp["angle"] = comp["angle"]
                            # UGC mode requires has_realistic_people=true
                            if comp["angle"] == "UGC" and not has_people:
                                prompt_warnings.append(
                                    f"invalid: assets[{idx}].prompt.composition.angle — "
                                    "UGC mode requer has_realistic_people=true (foto de usuário real exige pessoa na cena)"
                                )
                        else:
                            prompt_warnings.append(
                                f"invalid: assets[{idx}].prompt.composition.angle (deve ser um de: {', '.join(allowed_angles)})"
                            )
                        # main_object (string, obrigatrio quando angle=HyperCloseUpShot)
                        if valid_comp.get("angle") == "HyperCloseUpShot":
                            if (
                                "main_object" in comp
                                and str(comp.get("main_object", "")).strip()
                            ):
                                valid_comp["main_object"] = str(
                                    comp["main_object"]
                                ).strip()
                            else:
                                prompt_warnings.append(
                                    f"missing: assets[{idx}].prompt.composition.main_object (OBRIGATRIO quando angle=HyperCloseUpShot  especifique o ponto exato do hiper close-up: olho, boca, relogio, colar, etc.)"
                                )
                        # Studio + black_white requer has_realistic_people=true
                        if (
                            valid_comp.get("angle") == "Studio"
                            and _bg_type == "black_white"
                            and not has_people
                        ):
                            prompt_warnings.append(
                                f"invalid: assets[{idx}].prompt — angle 'Studio' com bg_type 'black_white' "
                                "exige has_realistic_people=true (fundo preto com estúdio requer modelo humano)"
                            )

                        # product_category (string, recomendado quando angle=Studio + HRP=true)
                        if valid_comp.get("angle") == "Studio" and has_people:
                            _pc = str(comp.get("product_category", "")).strip().lower()
                            if _pc in ("cosmetics", "accessories", "clothing"):
                                valid_comp["product_category"] = _pc
                            else:
                                prompt_warnings.append(
                                    f"recommended: assets[{idx}].prompt.composition.product_category — "
                                    "angle Studio com has_realistic_people=true: defina a categoria do produto "
                                    "(cosmetics | accessories | clothing) para aplicar diretiva de foco automática"
                                )
                        if "grid" in comp and str(comp.get("grid", "")).strip():
                            valid_comp["grid"] = str(comp["grid"]).strip()
                        else:
                            prompt_warnings.append(
                                f"missing: assets[{idx}].prompt.composition.grid (OBRIGATRIO)"
                            )
                        if valid_comp:
                            valid_prompt["composition"] = valid_comp
                    else:
                        prompt_warnings.append(
                            f"missing: assets[{idx}].prompt.composition (OBRIGATRIO - objeto com angle e grid)"
                        )

                    # environment (objeto com place e objects, obrigatrio)
                    # objects: aceita string simples OU lista de {"item": str, "focus": bool}
                    if "environment" in raw_prompt and isinstance(
                        raw_prompt["environment"], dict
                    ):
                        env = raw_prompt["environment"]
                        valid_env = {}
                        if "place" in env and str(env.get("place", "")).strip():
                            valid_env["place"] = str(env["place"]).strip()
                        else:
                            prompt_warnings.append(
                                f"missing: assets[{idx}].prompt.environment.place (OBRIGATRIO)"
                            )
                        if "objects" in env:
                            raw_objs = env["objects"]
                            if isinstance(raw_objs, str) and raw_objs.strip():
                                valid_env["objects"] = raw_objs.strip()
                            elif isinstance(raw_objs, list) and len(raw_objs) > 0:
                                valid_obj_list = []
                                for obj in raw_objs:
                                    if (
                                        isinstance(obj, dict)
                                        and str(obj.get("item", "")).strip()
                                    ):
                                        obj_entry = {"item": str(obj["item"]).strip()}
                                        if "focus" in obj:
                                            obj_entry["focus"] = bool(obj["focus"])
                                        valid_obj_list.append(obj_entry)
                                    elif isinstance(obj, str) and obj.strip():
                                        valid_obj_list.append({"item": obj.strip()})
                                if valid_obj_list:
                                    valid_env["objects"] = valid_obj_list
                                else:
                                    prompt_warnings.append(
                                        f"missing: assets[{idx}].prompt.environment.objects (OBRIGATRIO)"
                                    )
                            else:
                                prompt_warnings.append(
                                    f"missing: assets[{idx}].prompt.environment.objects (OBRIGATRIO)"
                                )
                        else:
                            prompt_warnings.append(
                                f"missing: assets[{idx}].prompt.environment.objects (OBRIGATRIO)"
                            )
                        if valid_env:
                            valid_prompt["environment"] = valid_env
                    else:
                        prompt_warnings.append(
                            f"missing: assets[{idx}].prompt.environment (OBRIGATRIO - objeto com place e objects)"
                        )

                    # colors (objeto com roles: background, subject, accent + saturation_contrast, harmony)
                    # background.bg_type obrigatrio; non-HRP restringe a window/color/product_closeup
                    if "colors" in raw_prompt and isinstance(
                        raw_prompt["colors"], dict
                    ):
                        colors = raw_prompt["colors"]
                        valid_colors = {}
                        allowed_bg_types = (
                            self.COPY_ASSET_BG_TYPE_VALUES_PRODUCT
                            if not has_people
                            else self.COPY_ASSET_BG_TYPE_VALUES
                        )
                        for role in ["background", "subject", "accent"]:
                            if role in colors and isinstance(colors[role], dict):
                                role_data = colors[role]
                                if (
                                    "hex" in role_data
                                    and isinstance(role_data["hex"], list)
                                    and len(role_data["hex"]) > 0
                                ):
                                    valid_role = {
                                        "hex": [str(h) for h in role_data["hex"]]
                                    }
                                    if (
                                        "detail" in role_data
                                        and str(role_data.get("detail", "")).strip()
                                    ):
                                        valid_role["detail"] = str(
                                            role_data["detail"]
                                        ).strip()
                                    # bg_type obrigatrio apenas para background
                                    if role == "background":
                                        bg_type = role_data.get("bg_type", "")
                                        if bg_type in allowed_bg_types:
                                            valid_role["bg_type"] = bg_type
                                        else:
                                            prompt_warnings.append(
                                                f"invalid: assets[{idx}].prompt.colors.background.bg_type "
                                                f"(deve ser um de: {', '.join(allowed_bg_types)})"
                                            )
                                    valid_colors[role] = valid_role
                        for color_field in ["saturation_contrast", "harmony"]:
                            if (
                                color_field in colors
                                and str(colors.get(color_field, "")).strip()
                            ):
                                valid_colors[color_field] = str(
                                    colors[color_field]
                                ).strip()
                            else:
                                prompt_warnings.append(
                                    f"missing: assets[{idx}].prompt.colors.{color_field} (OBRIGATRIO)"
                                )
                        if valid_colors:
                            valid_prompt["colors"] = valid_colors
                    else:
                        prompt_warnings.append(
                            f"missing: assets[{idx}].prompt.colors (OBRIGATRIO - objeto com background, subject, accent, saturation_contrast, harmony)"
                        )

                    # illumination (string, obrigatrio)
                    if (
                        "illumination" in raw_prompt
                        and str(raw_prompt.get("illumination", "")).strip()
                    ):
                        valid_prompt["illumination"] = str(
                            raw_prompt["illumination"]
                        ).strip()
                    else:
                        prompt_warnings.append(
                            f"missing: assets[{idx}].prompt.illumination (OBRIGATRIO)"
                        )

                    # emotion_style (string, obrigatrio)
                    if (
                        "emotion_style" in raw_prompt
                        and str(raw_prompt.get("emotion_style", "")).strip()
                    ):
                        valid_prompt["emotion_style"] = str(
                            raw_prompt["emotion_style"]
                        ).strip()
                    else:
                        prompt_warnings.append(
                            f"missing: assets[{idx}].prompt.emotion_style (OBRIGATRIO)"
                        )

                    # negative_prompt (string, opcional)  orientaes do que NO gerar
                    if (
                        "negative_prompt" in raw_prompt
                        and str(raw_prompt.get("negative_prompt", "")).strip()
                    ):
                        valid_prompt["negative_prompt"] = str(
                            raw_prompt["negative_prompt"]
                        ).strip()

                    warnings.extend(prompt_warnings)

                    # Bloquear asset se campos crticos do prompt esto ausentes
                    critical_prompt_fields = [
                        "description",
                        "composition",
                        "environment",
                        "colors",
                        "illumination",
                        "emotion_style",
                    ]
                    missing_critical = [
                        f for f in critical_prompt_fields if f not in valid_prompt
                    ]
                    if missing_critical:
                        continue

                    # Se has_realistic_people=True, models e pose tambm so crticos
                    if (
                        valid_prompt.get("has_realistic_people")
                        and "models" not in valid_prompt
                    ):
                        continue
                    if (
                        valid_prompt.get("has_realistic_people")
                        and "pose" not in valid_prompt
                    ):
                        continue
                    # Se angle=HyperCloseUpShot, main_object  crtico
                    if valid_prompt.get("composition", {}).get(
                        "angle"
                    ) == "HyperCloseUpShot" and "main_object" not in valid_prompt.get(
                        "composition", {}
                    ):
                        continue

                    valid_asset["prompt"] = valid_prompt

                    # reference_imgs (list of strings, optional)
                    if "reference_imgs" in asset and isinstance(
                        asset.get("reference_imgs"), list
                    ):
                        ref_imgs = asset["reference_imgs"]
                        if len(ref_imgs) > 0:
                            valid_asset["reference_imgs"] = [
                                str(img) for img in ref_imgs
                            ]

                    # status  toDo para assets novos; preservar "done" se j gerado
                    existing_status = asset.get("status", "")
                    valid_asset["status"] = (
                        "done" if existing_status == "done" else "toDo"
                    )

                    if (
                        valid_asset.get("asset_type")
                        and valid_asset.get("prompt") is not None
                    ):
                        valid_assets.append(valid_asset)

                if len(valid_assets) > 0:
                    valid_data["assets"] = valid_assets
                elif not _is_variation_doc:
                    warnings.append("invalid: assets (nenhum asset vlido fornecido)")
            else:
                if not _is_variation_doc:
                    warnings.append("missing: assets (deve conter pelo menos 1 asset)")
        else:
            if not _is_variation_doc:
                warnings.append(
                    "missing: assets (SEMPRE OBRIGATRIO - array com mnimo 1 item)"
                )

        # variation  campo obrigatrio com categoria e quantidade de variaes
        _var_raw = data.get("variation", {})
        if isinstance(_var_raw, dict) and _var_raw:
            _var_category = _var_raw.get("category", "").strip()
            _var_count_raw = _var_raw.get("count", 0)
            if _var_category in COPY_VARIATION_CATEGORIES:
                try:
                    _var_count_int = int(_var_count_raw)
                    if _var_count_int >= 1:
                        _var_entry = {
                            "category": _var_category,
                            "count": _var_count_int,
                        }
                        # Preservar reference_image se fornecido dentro de variation
                        _ref_img = str(
                            _var_raw.get("reference_image", "") or ""
                        ).strip()
                        if _ref_img:
                            _var_entry["reference_image"] = _ref_img
                        valid_data["variation"] = _var_entry

                        # Aceitar variation.variations[] como alias de variation_1, variation_2 ...
                        _inline_vars = _var_raw.get("variations")
                        if isinstance(_inline_vars, list) and _inline_vars:
                            for _idx, _iv in enumerate(_inline_vars, 1):
                                if isinstance(_iv, dict) and _iv:
                                    data.setdefault(f"variation_{_idx}", _iv)
                    else:
                        warnings.append("invalid: variation.count (deve ser >= 1)")
                except (ValueError, TypeError):
                    warnings.append(
                        "invalid: variation.count (deve ser nmero inteiro >= 1)"
                    )
            else:
                warnings.append(
                    f"invalid: variation.category '{_var_category}'. "
                    f"Vlidos: {', '.join(COPY_VARIATION_CATEGORIES)}"
                )
        else:
            warnings.append(
                f'missing: variation (OBRIGATRIO  ex: {{"category": "Criativo", "count": 2}}). '
                f"Categorias: {', '.join(COPY_VARIATION_CATEGORIES)}"
            )

        # variation_1..N  sub-objetos por variao (top-level ou extraidos de variation.variations)
        _var_count_v = valid_data.get("variation", {}).get("count", 0)
        _var_cat_v = valid_data.get("variation", {}).get("category", "")
        _missing_variations: list = []
        for _vi in range(1, _var_count_v + 1):
            _vkey = f"variation_{_vi}"
            _vobj = data.get(_vkey, {})
            if not isinstance(_vobj, dict) or not _vobj:
                _missing_variations.append(_vi)
                continue
            if _var_cat_v == "Criativo":
                _missing_criativo = [
                    f for f in ("style", "description", "prompt") if not _vobj.get(f)
                ]
                if _missing_criativo:
                    warnings.append(
                        f"invalid: {_vkey} — Criativo exige 3 campos: 'style', 'description', 'prompt'. "
                        f"Faltando: {', '.join(_missing_criativo)}"
                    )
                if "human" not in _vobj or not isinstance(_vobj.get("human"), bool):
                    warnings.append(
                        f"invalid: {_vkey}.human — campo obrigatório (true = tem modelo humano, false = produto sem modelo)"
                    )
                valid_data[_vkey] = {
                    k: v for k, v in _vobj.items() if v is not None and v != ""
                }
            elif _var_cat_v in ("Gatilhos", "Comunicao"):
                if not _vobj.get("hook") or not _vobj.get("body"):
                    warnings.append(
                        f"invalid: {_vkey}  Gatilhos/Comunicao exigem 'hook' e 'body'"
                    )
                else:
                    valid_data[_vkey] = _vobj
            else:  # "Outro"  sem gate
                valid_data[_vkey] = _vobj

            # Distribuição humano/produto: mínimo 1 com human=true obrigatório
            _has_human = any(
                valid_data.get(f"variation_{_vi}", {}).get("human") is True
                for _vi in range(1, _var_count_v + 1)
            )
            if not _has_human:
                warnings.append(
                    "invalid: variações Criativas — pelo menos UMA variação deve ter human=true "
                    "(com modelo humano). Não é permitido ter todas sem humano."
                )

        # Expandir assets por variaes + formatos (substitui expanso simples de formatos)
        _var_expand_info = valid_data.get("variation", {})
        _var_expand_cat = _var_expand_info.get("category", "")
        _var_expand_count = _var_expand_info.get("count", 0)
        _expand_formats = valid_data.get("aspect_ratio", [])
        if isinstance(_expand_formats, str):
            _expand_formats = [_expand_formats]

        if _var_expand_count > 0 and _expand_formats:
            # Prompt base: primeiro asset validado (se existir) ou string vazia
            _base_assets = valid_data.get("assets", [])
            _base_prompt = _base_assets[0].get("prompt", "") if _base_assets else ""

            _expanded_by_var = []
            for _vi in range(1, _var_expand_count + 1):
                _vkey = f"variation_{_vi}"
                _vobj = valid_data.get(_vkey, {})
                if not _vobj:
                    continue
                if _var_expand_cat == "Criativo":
                    # Prompt da variação: usa o do variation_N se existir, senão o prompt base do assets[0]
                    _var_prompt = _vobj.get("prompt", _base_prompt)
                    # Se variation_N tem style/description mas não tem prompt estruturado,
                    # injeta o style como description para diferenciar as variações
                    if not _var_prompt and _vobj.get("style"):
                        _var_prompt = _vobj["style"]
                    elif (
                        isinstance(_var_prompt, dict)
                        and not _var_prompt.get("description")
                        and _vobj.get("style")
                    ):
                        _var_prompt = dict(_var_prompt)
                        _var_prompt["description"] = _vobj["style"]
                    _base = {
                        "prompt": _var_prompt,
                        "angle": _vobj.get("angle", ""),
                        "background": _vobj.get("background", ""),
                        "variation_label": _vkey,
                        "source_idx": _vi - 1,
                    }
                elif _var_expand_cat in ("Gatilhos", "Comunicao"):
                    _base = {
                        "prompt": _base_prompt,
                        "hook": _vobj.get("hook", ""),
                        "body": _vobj.get("body", ""),
                        "cta": _vobj.get("cta", ""),
                        "variation_label": _vkey,
                        "source_idx": _vi - 1,
                    }
                else:  # "Outro"
                    _base = {**_vobj, "variation_label": _vkey, "source_idx": _vi - 1}
                for _fmt in _expand_formats:
                    _a = dict(_base)
                    _a["format"] = _fmt
                    _a["asset_type"] = "img"
                    _a["status"] = "toDo"
                    _expanded_by_var.append(_a)
            if _expanded_by_var:
                valid_data["assets"] = _expanded_by_var

        # VALIDAO BLOQUEANTE: Exigir campos crticos
        critical_missing = [
            w
            for w in warnings
            if any(
                x in w
                for x in [
                    "is_paid_ad",
                    "channels",
                    "task_id",
                    "step_id",
                    "hook_pain_awareness",
                    "empathy",
                    "autority",
                    "solution_contious",
                    "product_contious",
                    "offer_concious",
                    "caption",
                    "assets",
                ]
            )
        ]

        if critical_missing:
            # Rejeitar bloqueante se algum campo crtico est faltando ou invlido
            return {
                "valid": False,
                "data": {},
                "warnings": warnings,
                "error": f"Estrutura invlida: {'; '.join(critical_missing[:3])}",
            }

        # Se h algum campo vlido e nenhum crtico est faltando, retornar sucesso com avisos
        if valid_data:
            # Reordenar: variation e variation_N aparecem antes de assets no JSON salvo
            _var_count_ord = valid_data.get("variation", {}).get("count", 0)
            if _var_count_ord > 0:
                _reordered: dict = {}
                if "variation" in valid_data:
                    _reordered["variation"] = valid_data.pop("variation")
                for _vri in range(1, _var_count_ord + 1):
                    _vrk = f"variation_{_vri}"
                    if _vrk in valid_data:
                        _reordered[_vrk] = valid_data.pop(_vrk)
                _reordered.update(valid_data)
                valid_data = _reordered

            return {
                "valid": True,
                "data": valid_data,
                "warnings": warnings,
                "missing_variations": _missing_variations,
                "error": None,
            }
        else:
            return {
                "valid": False,
                "data": {},
                "warnings": warnings,
                "missing_variations": _missing_variations,
                "error": "Nenhum campo vlido foi fornecido no copywriting",
            }

    #
    # PRODUCT DOCUMENT
    #

    def _validate_product_json(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Valida estrutura do documento product.
        Retorna {"valid": bool, "data": dict, "warnings": list, "error": str|None}
        """
        warnings = []
        valid_data = {}

        def _str(key):
            v = data.get(key, "")
            return str(v).strip() if v else ""

        # public_target  obrigatrio, define se ICP usa firmografia ou demographics
        _VALID_TARGETS = {"b2b", "b2c", "smb", "b2g"}
        pt_raw = str(data.get("public_target", "")).lower().strip()
        if pt_raw in _VALID_TARGETS:
            valid_data["public_target"] = pt_raw
        else:
            warnings.append(
                f"missing: public_target (use: {', '.join(sorted(_VALID_TARGETS))})"
            )

        # product_type  obrigatrio, determina copywriting (produto fsico/digital vs servio)
        _VALID_PRODUCT_TYPES = {"product", "service"}
        pt_type_raw = str(data.get("product_type", "")).lower().strip()
        if pt_type_raw in _VALID_PRODUCT_TYPES:
            valid_data["product_type"] = pt_type_raw
        else:
            warnings.append("missing: product_type (use: 'product' ou 'service')")

        # Obrigatrios simples (exceto price, tratado separadamente)
        for field in [
            "product_page_url",
            "value_proposition",
            "pain",
            "solution",
            "site_description",
        ]:
            val = _str(field)
            if val:
                valid_data[field] = val
            else:
                warnings.append(f"missing: {field}")

        # price  obrigatrio como {value: float, currency: "BRL"|"USD"|"EUR"|...}
        _VALID_CURRENCIES = {
            "BRL",
            "USD",
            "EUR",
            "GBP",
            "ARS",
            "MXN",
            "CLP",
            "COP",
            "PEN",
        }
        price_raw = data.get("price")
        if isinstance(price_raw, dict):
            try:
                price_value = float(str(price_raw.get("value", "")).replace(",", "."))
                price_currency = str(price_raw.get("currency", "")).upper().strip()
                if price_currency not in _VALID_CURRENCIES:
                    warnings.append(
                        f"invalid: price.currency (use: {', '.join(sorted(_VALID_CURRENCIES))})"
                    )
                else:
                    valid_data["price"] = {
                        "value": round(price_value, 2),
                        "currency": price_currency,
                    }
            except (ValueError, TypeError):
                warnings.append(
                    'invalid: price.value (deve ser nmero, ex: {"value": 199.90, "currency": "BRL"})'
                )
        else:
            warnings.append(
                'missing: price (obrigatrio como {"value": 199.90, "currency": "BRL"})'
            )

        # product_image  obrigatrio
        img_raw = str(data.get("product_image", "")).strip()
        if img_raw:
            valid_data["product_image"] = img_raw
        else:
            warnings.append(
                "missing: product_image (URL da imagem do produto  obrigatrio)"
            )

        # brand  opcional: {name, ownership: "own"|"third_party"}
        if "brand" in data and isinstance(data["brand"], dict):
            brand = data["brand"]
            brand_name = str(brand.get("name", "")).strip()
            brand_ownership = str(brand.get("ownership", "")).strip()
            if brand_name:
                if brand_ownership not in ["own", "third_party"]:
                    warnings.append(
                        "invalid: brand.ownership (deve ser 'own' ou 'third_party')"
                    )
                else:
                    valid_data["brand"] = {
                        "name": brand_name,
                        "ownership": brand_ownership,
                    }

        # consciousness_level
        valid_levels = [
            "Inconsciente",
            "Consciente do Problema",
            "Consciente da Soluo",
            "Consciente do Produto",
            "Totalmente Consciente",
        ]
        cl = data.get("consciousness_level")
        if cl:
            if isinstance(cl, str) and cl in valid_levels:
                valid_data["consciousness_level"] = cl
            elif isinstance(cl, list) and all(c in valid_levels for c in cl):
                valid_data["consciousness_level"] = cl
            else:
                warnings.append(
                    f"invalid: consciousness_level (use: {', '.join(valid_levels)})"
                )
        else:
            warnings.append("missing: consciousness_level")

        # ICP  B2B/SMB/B2G  firmografia obrigatrio; B2C  demographics obrigatrio
        public_target = pt_raw if pt_raw in _VALID_TARGETS else ""
        _b2b_targets = {"b2b", "smb", "b2g"}
        _required_profile = (
            "firmografia" if public_target in _b2b_targets else "demographics"
        )
        _forbidden_profile = (
            "demographics" if _required_profile == "firmografia" else "firmografia"
        )

        if "icp" in data:
            icp_raw = data["icp"]
            if not isinstance(icp_raw, list) or len(icp_raw) == 0:
                warnings.append("invalid: icp (deve ser array no-vazio de subgrupos)")
            else:
                valid_icps = []
                for idx, entry in enumerate(icp_raw):
                    if not isinstance(entry, dict):
                        warnings.append(f"invalid: icp[{idx}] (deve ser objeto)")
                        continue
                    valid_icp = {}
                    if entry.get("title", "").strip():
                        valid_icp["title"] = entry["title"].strip()
                    else:
                        warnings.append(f"missing: icp[{idx}].title")

                    # Rejeitar profile type errado
                    if _forbidden_profile in entry:
                        warnings.append(
                            f"invalid: icp[{idx}].{_forbidden_profile}  pblico {public_target.upper()} exige '{_required_profile}', no '{_forbidden_profile}'"
                        )

                    profile = entry.get(_required_profile)
                    if isinstance(profile, dict):
                        valid_profile = {
                            k: v for k, v in profile.items() if v and k != "motivator"
                        }
                        mot = profile.get("motivator")
                        if isinstance(mot, dict):
                            mot_type = mot.get("type", "")
                            mot_exp = str(mot.get("explanation", "")).strip()
                            if mot_type in ["pain", "ambition"] and mot_exp:
                                valid_profile["motivator"] = mot
                            else:
                                warnings.append(
                                    f"invalid: icp[{idx}].{_required_profile}.motivator (type deve ser 'pain'|'ambition' com explanation)"
                                )
                        else:
                            warnings.append(
                                f'missing: icp[{idx}].{_required_profile}.motivator ({{"type": "pain"|"ambition", "explanation": "..."}})'
                            )
                        if valid_profile:
                            valid_icp[_required_profile] = valid_profile
                    else:
                        warnings.append(
                            f"missing: icp[{idx}].{_required_profile} (OBRIGATRIO para {public_target.upper() or 'este pblico'})"
                        )

                    if valid_icp:
                        valid_icps.append(valid_icp)
                if valid_icps:
                    valid_data["icp"] = valid_icps
        else:
            warnings.append(
                f"missing: icp (array de subgrupos com {_required_profile} e motivator)"
            )

        # reviews e feedbacks  obrigatrios e devem estar presentes nos resultados do web-search
        _web_blob = ""
        if self.db_manager and self.current_chat_id:
            try:
                _ws_session = self.db_manager.get_session()
                try:
                    _web_blob = self._get_tool_messages_blob(
                        _ws_session, TOOL_WEB_SEARCH
                    )
                finally:
                    _ws_session.close()
            except Exception:
                pass

        def _found_in_web(text: str) -> bool:
            if not _web_blob:
                return False
            words = [w for w in text.lower().split() if len(w) > 3]
            if not words:
                return False
            # Pelo menos 40% das palavras significativas devem aparecer no blob
            hits = sum(1 for w in words if w in _web_blob)
            return (hits / len(words)) >= 0.40

        _has_review_search = bool(_web_blob) and any(
            kw in _web_blob
            for kw in [
                "review",
                "avalia",
                "reclame",
                "trustpilot",
                "feedback",
                "opinion",
                "rating",
            ]
        )

        for arr_field in ["reviews", "feedbacks"]:
            val = data.get(arr_field)
            items = val if isinstance(val, list) else ([str(val)] if val else [])

            # Lista vazia  aceita se a IA j pesquisou por avaliaes e no encontrou
            if not items:
                if _has_review_search:
                    valid_data[arr_field] = []
                else:
                    warnings.append(
                        f"missing: {arr_field}  pesquise por avaliaes com "
                        f"web-search(query='<produto> avaliaes reclame aqui trustpilot') antes de deixar vazio"
                    )
                continue

            valid_items = []
            for item in items:
                item_str = str(item).strip()
                if _found_in_web(item_str):
                    valid_items.append(item_str)
                else:
                    warnings.append(
                        f'invalid: {arr_field}  "{item_str[:60]}" no encontrado nas pesquisas web-search. '
                        f"Use somente avaliaes extradas de web-search(fetch='<url>') ou web-search(query='...')"
                    )
            if valid_items:
                valid_data[arr_field] = valid_items

        # availability e stock_quantity  opcionais
        if "availability" in data and data["availability"] is not None:
            valid_data["availability"] = data["availability"]
        if "stock_quantity" in data and data["stock_quantity"] is not None:
            try:
                valid_data["stock_quantity"] = int(data["stock_quantity"])
            except (ValueError, TypeError):
                warnings.append("invalid: stock_quantity (deve ser inteiro)")

        if not valid_data:
            return {
                "valid": False,
                "data": {},
                "warnings": warnings,
                "error": "Nenhum campo vlido fornecido no product",
            }

        return {
            "valid": not warnings,
            "data": valid_data,
            "warnings": warnings,
            "error": None,
        }

    #
    # COPYWRITING GUARDS
    #

    def _validate_tools_config(self):
        """CRITICAL: Validate that Tools configuration file exists and is accessible."""
        try:
            from pathlib import Path

            tools_json_path = Path(__file__).parent / "Tools" / "TOOLS.json"

            if not tools_json_path.exists():
                error(
                    f"[CRITICAL] Tools configuration file not found: {tools_json_path}"
                )
                error("[CRITICAL] Core cannot initialize without Tools.json")
                error("[CRITICAL] Server will exit now")
                import sys

                sys.exit(1)

            # Try to load and parse the JSON
            try:
                with open(tools_json_path, "r", encoding="utf-8") as f:
                    json.load(f)
                debug(f"[OK] Tools configuration loaded: {Path(tools_json_path).name}")
            except json.JSONDecodeError as json_err:
                error(f"[CRITICAL] Tools.json is invalid JSON: {json_err}")
                error("[CRITICAL] Server will exit now")
                import sys

                sys.exit(1)

        except Exception as e:
            error(f"[CRITICAL] Error validating Tools configuration: {e}")
            error("[CRITICAL] Server will exit now")
            import traceback

            error(traceback.format_exc())
            import sys

            sys.exit(1)

    # COMENTADO: Mtodo para executar chamadas de agents especializados
    # def _execute_agent(
    #     self,
    #     args: Dict[str, Any],
    #     caller_agent_id: Optional[str],
    #     chat_id: Optional[str] = None,
    #     client_id: Optional[int] = None,
    # ) -> str:
    #     """Executa tool agent."""
    #     target_agent_id = args.get("agent_id")
    #     message = args.get("message")
    #
    #     if not target_agent_id or not message:
    #         return json.dumps({"success": False, "error": "agent_id e message obrigatrios"})
    #
    #     try:
    #         handler = AgentHandler(
    #             message_processor=self.message_processor,
    #             chat_manager=self.chat_manager,
    #             agents_manager=self.agents_manager,
    #             db_manager=self.db_manager
    #         )
    #
    #         result = handler.handle_agent_call(
    #             target_agent_id=target_agent_id,
    #             message=message,
    #             caller_agent_id=caller_agent_id,
    #             chat_id=chat_id,
    #             client_id=client_id
    #         )
    #
    #         return json.dumps(result)
    #
    #     except Exception as e:
    #         error(f"[AGENT_TOOL] Erro ao chamar agent {target_agent_id}: {e}")
    #         return json.dumps({"success": False, "error": str(e)})

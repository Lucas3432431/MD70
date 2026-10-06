"""
tool_facilitator.py - Wrapper que expõe a classe ToolFacilitator e utilidades.

Este arquivo re-exporta tudo do pacote tool_facilitator para compatibilidade
com código que importa: from App.Features.Tools.ToolFacilitator import ToolFacilitator
"""

from .ToolFacilitator.core import ToolFacilitator  # noqa: F401
from .ToolFacilitator.agent_methods import (
    load_agents_from_json,
    flatten_agents,
    get_accessible_agent_ids,
    format_plan_for_display,
)
from .ToolFacilitator.plan_methods import (
    init_plan_manager,
    list_plans,
    get_plan,
    update_plan,
    submit_plan_approval,
)
from .ToolFacilitator.tool_definitions import get_internal_tool_definitions
from .ToolFacilitator.execution_methods import (
    start_plan_execution,
    get_queue_status,
    submit_task_for_approval,
    approve_task_result,
    reject_task_result,
    approve_plan_structure,
    approve_plan_execution,
)

__all__ = [
    # Classe principal
    "ToolFacilitator",
    # agent_methods
    "load_agents_from_json",
    "flatten_agents",
    "get_accessible_agent_ids",
    "format_plan_for_display",
    # plan_methods
    "init_plan_manager",
    "list_plans",
    "get_plan",
    "update_plan",
    "submit_plan_approval",
    # execution_methods
    "start_plan_execution",
    "get_queue_status",
    "submit_task_for_approval",
    "approve_task_result",
    "reject_task_result",
    "approve_plan_structure",
    "approve_plan_execution",
    # tool_definitions
    "get_internal_tool_definitions",
]

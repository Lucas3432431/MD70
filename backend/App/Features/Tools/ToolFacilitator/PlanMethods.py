"""
Métodos para manipulação de planos - DESATIVADO NO PROX
Plan management is not used in MD70 and has been disabled.
"""

from typing import Dict, Union, Any, Optional
from App.Core.Logs import warning


def _not_available():
    """Função auxiliar para métodos desativados."""
    return {
        "success": False,
        "output": "",
        "error": "Plan management is not available in MD70",
        "exit_code": -1,
    }


def init_plan_manager(bot, base_dir):
    """Plan management disabled."""
    warning("Attempted to use plan management - feature disabled in MD70")
    pass


def list_plans(bot, base_dir, status_filter=None):
    """Plan management disabled."""
    return _not_available()


def get_plan(bot, base_dir, plan_id, format_display_func):
    """Plan management disabled."""
    return _not_available()


def update_plan(bot, base_dir, plan_id, action, updates, subtask_id=None):
    """Plan management disabled."""
    return _not_available()


def submit_plan_approval(bot, base_dir, plan_id):
    """Plan management disabled."""
    return _not_available()


def list_pending_execution_approval_plans(bot, base_dir):
    """Plan management disabled."""
    return _not_available()


def approve_plan_execution(bot, base_dir, plan_id, approver_id="user"):
    """Plan management disabled."""
    return _not_available()

"""
Métodos de execução de planos - DESATIVADO NO PROX
Plan execution is not used in MD70 and has been disabled.
"""

from typing import Dict, Any, Optional
from App.Core.Logs import warning


def _not_available():
    """Função auxiliar para métodos desativados."""
    return {
        "success": False,
        "output": "",
        "error": "Plan execution is not available in MD70",
        "exit_code": -1,
    }


def start_monitor():
    """Plan execution disabled."""
    warning("Attempted to use plan execution - feature disabled in MD70")
    pass


def stop_monitor():
    """Plan execution disabled."""
    pass


def start_plan_execution(bot, base_dir, plan_id):
    """Plan execution disabled."""
    return _not_available()


def load_plan_to_queue(bot, base_dir, plan_id, auto_start=False):
    """Plan execution disabled."""
    return _not_available()


def get_queue_status(bot, queue_id=None):
    """Plan execution disabled."""
    return _not_available()


def submit_task_for_approval(bot, base_dir, queue_id, subtask_id, result):
    """Plan execution disabled."""
    return _not_available()


def approve_task_result(bot, base_dir, queue_id, subtask_id):
    """Plan execution disabled."""
    return _not_available()


def reject_task_result(bot, base_dir, queue_id, subtask_id, reason):
    """Plan execution disabled."""
    return _not_available()


def approve_plan_structure(bot, base_dir, plan_id, approver_id="SECURITY_OFFICER"):
    """Plan execution disabled."""
    return _not_available()


def approve_plan_execution(bot, base_dir, plan_id, approver_id="user"):
    """Plan execution disabled."""
    return _not_available()

"""
Tool: schedule
Permite ao agente listar tarefas agendadas existentes ou criar novas.

Modos:
  schedule(action="lookup")                         → lista as tarefas do usuário
  schedule(action="create", name=..., ...)          → cria nova tarefa agendada
"""

import json
import uuid
from datetime import datetime
from typing import Any, Dict

from App.Core.Logs import error
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager


def execute_schedule(args: Dict[str, Any], user_id: str) -> str:
    action = (args.get("action") or "lookup").strip().lower()

    if action == "lookup":
        return _lookup(user_id)
    elif action == "create":
        return _create(args, user_id)
    else:
        return json.dumps(
            {
                "success": False,
                "error": f"Ação desconhecida: '{action}'. Use 'lookup' ou 'create'.",
            },
            ensure_ascii=False,
        )


# ── lookup ──────────────────────────────────────────────────────────────────


def _lookup(user_id: str) -> str:
    try:
        db = DatabaseManager()
        rows = db.fetch_all(
            """
            SELECT id, name, description, cron_expression, cron_label,
                   status, last_executed_at, next_execution_at, created_at
            FROM scheduled_tasks
            WHERE user_id = :user_id
            ORDER BY created_at DESC
            """,
            {"user_id": user_id},
        )
        tasks = [dict(r) for r in rows] if rows else []
        return json.dumps(
            {"success": True, "action": "lookup", "tasks": tasks, "total": len(tasks)},
            ensure_ascii=False,
            default=str,
        )
    except Exception as e:
        error(f"[TOOL:schedule] lookup error: {e}")
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── create ──────────────────────────────────────────────────────────────────


def _create(args: Dict[str, Any], user_id: str) -> str:
    name = (args.get("name") or "").strip()
    cron_expression = (args.get("cron_expression") or "").strip()
    prompt = (args.get("prompt") or "").strip()

    if not name:
        return json.dumps(
            {"success": False, "error": "Campo 'name' obrigatório."}, ensure_ascii=False
        )
    if not cron_expression:
        return json.dumps(
            {
                "success": False,
                "error": "Campo 'cron_expression' obrigatório (ex: '0 9 * * 1').",
            },
            ensure_ascii=False,
        )
    if not prompt:
        return json.dumps(
            {"success": False, "error": "Campo 'prompt' obrigatório."},
            ensure_ascii=False,
        )

    # Validar cron_expression
    try:
        from croniter import croniter

        if not croniter.is_valid(cron_expression):
            return json.dumps(
                {
                    "success": False,
                    "error": f"cron_expression inválida: '{cron_expression}'.",
                },
                ensure_ascii=False,
            )
        next_run = croniter(cron_expression, datetime.utcnow()).get_next(datetime)
    except ImportError:
        next_run = None
    except Exception as e:
        return json.dumps(
            {"success": False, "error": f"Erro ao validar cron: {e}"},
            ensure_ascii=False,
        )

    task_id = str(uuid.uuid4())
    integrations = args.get("integrations") or []
    cron_label = args.get("cron_label") or ""
    description = args.get("description") or ""
    now = datetime.utcnow().isoformat()

    try:
        db = DatabaseManager()
        db.execute_query(
            """
            INSERT INTO scheduled_tasks
              (id, user_id, name, description, cron_expression, cron_label, prompt, integrations, status, next_execution_at, created_at, updated_at)
            VALUES
              (:id, :user_id, :name, :description, :cron_expression, :cron_label, :prompt, :integrations, 'active', :next_run, :now, :now)
            """,
            {
                "id": task_id,
                "user_id": user_id,
                "name": name,
                "description": description,
                "cron_expression": cron_expression,
                "cron_label": cron_label,
                "prompt": prompt,
                "integrations": json.dumps(integrations),
                "next_run": next_run.isoformat() if next_run else None,
                "now": now,
            },
        )
        return json.dumps(
            {
                "success": True,
                "action": "create",
                "task_id": task_id,
                "name": name,
                "cron_expression": cron_expression,
                "cron_label": cron_label or None,
                "next_execution_at": next_run.isoformat() if next_run else None,
            },
            ensure_ascii=False,
        )
    except Exception as e:
        error(f"[TOOL:schedule] create error: {e}")
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)

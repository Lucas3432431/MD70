"""
Tool: skill
Permite ao agente listar skills personalizadas do usuário ou criar novas.

Modos:
  skill(action="lookup")                              → lista as skills ativas do usuário
  skill(action="create", name=..., content=...)       → cria nova skill personalizada
  skill(action="read", skill_id=...)                  → lê o conteúdo de uma skill específica
"""

import json
import uuid
from datetime import datetime
from typing import Any, Dict

from App.Core.Logs import error
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager


def execute_skill(args: Dict[str, Any], user_id: str) -> str:
    action = (args.get("action") or "lookup").strip().lower()

    if action == "lookup":
        return _lookup(user_id)
    elif action == "create":
        return _create(args, user_id)
    elif action == "read":
        return _read(args, user_id)
    else:
        return json.dumps(
            {
                "success": False,
                "error": f"Ação desconhecida: '{action}'. Use 'lookup', 'create' ou 'read'.",
            },
            ensure_ascii=False,
        )


def _lookup(user_id: str) -> str:
    try:
        db = DatabaseManager()
        rows = db.fetch_all(
            """
            SELECT id, name, description, is_active, created_at, updated_at
            FROM custom_skills
            WHERE user_id = :user_id
            ORDER BY created_at ASC
            """,
            {"user_id": user_id},
        )
        skills = [dict(r) for r in rows] if rows else []
        return json.dumps(
            {
                "success": True,
                "action": "lookup",
                "skills": skills,
                "total": len(skills),
            },
            ensure_ascii=False,
            default=str,
        )
    except Exception as e:
        error(f"[TOOL:skill] lookup error: {e}")
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


def _read(args: Dict[str, Any], user_id: str) -> str:
    skill_id = (args.get("skill_id") or "").strip()
    if not skill_id:
        return json.dumps(
            {"success": False, "error": "Campo 'skill_id' obrigatório."},
            ensure_ascii=False,
        )
    try:
        db = DatabaseManager()
        row = db.fetch_one(
            "SELECT id, name, description, content, is_active FROM custom_skills WHERE id = :id AND user_id = :user_id",
            {"id": skill_id, "user_id": user_id},
        )
        if not row:
            return json.dumps(
                {"success": False, "error": "Skill não encontrada."}, ensure_ascii=False
            )
        return json.dumps(
            {"success": True, "action": "read", "skill": dict(row)}, ensure_ascii=False
        )
    except Exception as e:
        error(f"[TOOL:skill] read error: {e}")
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


def _create(args: Dict[str, Any], user_id: str) -> str:
    name = (args.get("name") or "").strip()
    content = (args.get("content") or "").strip()
    description = (args.get("description") or "").strip()

    if not name:
        return json.dumps(
            {"success": False, "error": "Campo 'name' obrigatório."}, ensure_ascii=False
        )
    if not content:
        return json.dumps(
            {
                "success": False,
                "error": "Campo 'content' obrigatório — inclua as instruções da skill.",
            },
            ensure_ascii=False,
        )

    skill_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    try:
        db = DatabaseManager()
        db.execute_query(
            """
            INSERT INTO custom_skills (id, user_id, name, description, content, is_active, created_at, updated_at)
            VALUES (:id, :user_id, :name, :description, :content, 1, :now, :now)
            """,
            {
                "id": skill_id,
                "user_id": user_id,
                "name": name,
                "description": description or None,
                "content": content,
                "now": now,
            },
        )
        return json.dumps(
            {
                "success": True,
                "action": "create",
                "skill_id": skill_id,
                "name": name,
                "description": description or None,
            },
            ensure_ascii=False,
        )
    except Exception as e:
        error(f"[TOOL:skill] create error: {e}")
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)

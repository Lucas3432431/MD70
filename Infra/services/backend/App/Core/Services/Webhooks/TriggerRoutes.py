"""
TriggerRoutes.py — endpoints REST para /api/triggers.

Mapeia webhook_secrets → Trigger e trigger_executions → TriggerExecution
para compatibilidade com o frontend (TriggersPage).
"""
from fastapi import APIRouter, Request
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Core.Logs import debug, error
from App.Core.Services.Integrations.IntegrationsRoutes import _get_auth_payload

trigger_router = APIRouter(tags=["Triggers"], prefix="/api/triggers")


def _client_id(request: Request) -> str:
    return str(_get_auth_payload(request).get("client_id", ""))


def _user_id(request: Request) -> str:
    return str(_get_auth_payload(request).get("user_id", ""))


def _ws_to_trigger(row: dict) -> dict:
    """Converte webhook_secrets row → formato Trigger esperado pelo frontend."""
    import json

    tools = row.get("tools") or "[]"
    try:
        integrations = json.loads(tools) if isinstance(tools, str) else tools
    except Exception:
        integrations = []
    return {
        "id": row["web_secret_id"],
        "name": row.get("provider", "").capitalize(),
        "provider": row.get("provider", ""),
        "trigger_prompt": row.get("prompt") or "",
        "integrations": integrations,
        "ip_whitelist": None,
        "autonomy_level": row.get("autonomy_level") or 4,
        "is_active": 1 if row.get("status") != "lost" else 0,
        "secret_preview": (row.get("webhook_secret") or "")[:8] + "...",
        "created_at": row.get("created_at") or "",
        "updated_at": row.get("updated_at") or row.get("created_at") or "",
        "webhook_status": {
            "ok": row.get("status") == "connected",
            "message": row.get("status") or "pending",
        },
    }


def _exec_to_dict(row: dict) -> dict:
    return {
        "id": row["id"],
        "task_id": row.get("web_secret_id") or "",
        "trigger_id": row.get("web_secret_id") or "",
        "user_id": row.get("user_id") or "",
        "status": row.get("status") or "running",
        "chat_id": row.get("chat_id"),
        "chat_seen": row.get("chat_seen") or 0,
        "result_summary": row.get("result_summary"),
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
        "created_at": row.get("created_at") or "",
        "external_sender_id": row.get("external_sender_id"),
        "external_sender_name": row.get("external_sender_name"),
        "chat_updated_at": row.get("chat_updated_at"),
        "trigger_name": (row.get("provider") or "").capitalize(),
        "trigger_provider": row.get("provider"),
    }


# ── Triggers (webhook_secrets) ──────────────────────────────────────────────


@trigger_router.get("")
async def list_triggers(request: Request):
    client_id = _client_id(request)
    rows = (
        DatabaseManager.fetch_all(
            "SELECT * FROM webhook_secrets WHERE client_id = :cid ORDER BY created_at DESC",
            {"cid": client_id},
        )
        or []
    )
    return {"triggers": [_ws_to_trigger(dict(r)) for r in rows]}


@trigger_router.patch("/{trigger_id}")
async def update_trigger(trigger_id: str, request: Request):
    client_id = _client_id(request)
    import json

    body = await request.json()
    fields = {}
    if "trigger_prompt" in body:
        fields["prompt"] = body["trigger_prompt"]
    if "autonomy_level" in body:
        fields["autonomy_level"] = body["autonomy_level"]
    if "integrations" in body:
        fields["tools"] = json.dumps(body["integrations"])
    if "is_active" in body:
        fields["status"] = "connected" if body["is_active"] else "lost"

    if fields:
        set_clause = ", ".join(f"{k} = :{k}" for k in fields)
        fields["wsid"] = trigger_id
        fields["cid"] = client_id
        DatabaseManager.execute_query(
            f"UPDATE webhook_secrets SET {set_clause}, updated_at = CURRENT_TIMESTAMP "
            "WHERE web_secret_id = :wsid AND client_id = :cid",
            fields,
        )
    row = DatabaseManager.fetch_one(
        "SELECT * FROM webhook_secrets WHERE web_secret_id = :wsid AND client_id = :cid",
        {"wsid": trigger_id, "cid": client_id},
    )
    return {"trigger": _ws_to_trigger(dict(row)) if row else {}}


@trigger_router.delete("/{trigger_id}")
async def delete_trigger(trigger_id: str, request: Request):
    client_id = _client_id(request)
    DatabaseManager.execute_query(
        "DELETE FROM webhook_secrets WHERE web_secret_id = :wsid AND client_id = :cid",
        {"wsid": trigger_id, "cid": client_id},
    )
    return {"ok": True}


# ── Executions ───────────────────────────────────────────────────────────────


@trigger_router.get("/executions/pending")
async def list_pending_executions(request: Request):
    user_id = _user_id(request)
    rows = (
        DatabaseManager.fetch_all(
            """
        SELECT te.*, ws.provider, ws.autonomy_level,
               c.external_sender_id, c.external_sender_name, c.updated_at AS chat_updated_at,
               c.seen AS chat_seen
        FROM trigger_executions te
        LEFT JOIN webhook_secrets ws ON ws.web_secret_id = te.web_secret_id
        LEFT JOIN chats c ON c.chat_id = te.chat_id
        WHERE te.user_id = :uid AND te.status IN ('running', 'pending_review')
        ORDER BY te.created_at DESC
        LIMIT 100
        """,
            {"uid": user_id},
        )
        or []
    )
    return {"executions": [_exec_to_dict(dict(r)) for r in rows]}


@trigger_router.get("/executions")
async def list_executions(request: Request):
    user_id = _user_id(request)
    rows = (
        DatabaseManager.fetch_all(
            """
        SELECT te.*, ws.provider, ws.autonomy_level,
               c.external_sender_id, c.external_sender_name, c.updated_at AS chat_updated_at,
               c.seen AS chat_seen
        FROM trigger_executions te
        LEFT JOIN webhook_secrets ws ON ws.web_secret_id = te.web_secret_id
        LEFT JOIN chats c ON c.chat_id = te.chat_id
        WHERE te.user_id = :uid AND te.status != 'deleted'
        ORDER BY te.created_at DESC
        LIMIT 200
        """,
            {"uid": user_id},
        )
        or []
    )
    return {"executions": [_exec_to_dict(dict(r)) for r in rows]}


@trigger_router.patch("/executions/{exec_id}/approve")
async def approve_execution(exec_id: str, request: Request):
    DatabaseManager.execute_query(
        "UPDATE trigger_executions SET status = 'approved' WHERE id = :id",
        {"id": exec_id},
    )
    row = DatabaseManager.fetch_one(
        "SELECT te.*, ws.provider FROM trigger_executions te "
        "LEFT JOIN webhook_secrets ws ON ws.web_secret_id = te.web_secret_id "
        "WHERE te.id = :id",
        {"id": exec_id},
    )
    return {"execution": _exec_to_dict(dict(row)) if row else {}}


@trigger_router.patch("/executions/{exec_id}/reject")
async def reject_execution(exec_id: str, request: Request):
    DatabaseManager.execute_query(
        "UPDATE trigger_executions SET status = 'rejected' WHERE id = :id",
        {"id": exec_id},
    )
    row = DatabaseManager.fetch_one(
        "SELECT te.*, ws.provider FROM trigger_executions te "
        "LEFT JOIN webhook_secrets ws ON ws.web_secret_id = te.web_secret_id "
        "WHERE te.id = :id",
        {"id": exec_id},
    )
    return {"execution": _exec_to_dict(dict(row)) if row else {}}


# ── Leads ────────────────────────────────────────────────────────────────────


@trigger_router.get("/leads")
async def list_leads(request: Request):
    user_id = _user_id(request)
    rows = (
        DatabaseManager.fetch_all(
            "SELECT * FROM leads WHERE user_id = :uid ORDER BY updated_at DESC",
            {"uid": user_id},
        )
        or []
    )
    return {"leads": [dict(r) for r in rows]}


@trigger_router.get("/leads/{chat_id}")
async def get_lead(chat_id: str, request: Request):
    user_id = _user_id(request)
    row = DatabaseManager.fetch_one(
        "SELECT * FROM leads WHERE user_id = :uid AND chat_id = :cid LIMIT 1",
        {"uid": user_id, "cid": chat_id},
    )
    return {"lead": dict(row) if row else None}


@trigger_router.post("/leads/{chat_id}")
async def upsert_lead(chat_id: str, request: Request):
    import json, uuid

    user_id = _user_id(request)
    body = await request.json()
    existing = DatabaseManager.fetch_one(
        "SELECT id FROM leads WHERE user_id = :uid AND chat_id = :cid LIMIT 1",
        {"uid": user_id, "cid": chat_id},
    )
    allowed = [
        "name",
        "email",
        "phone",
        "funnel_stage",
        "consciousness_level",
        "qualification",
        "origin_type",
        "origin_detail",
        "product_service",
        "product_link",
        "product_value",
        "payment_method",
        "products_history",
        "pains_ambitions",
        "objections",
        "notes",
        "role",
        "demographics",
        "mql_level",
        "cohort_ids",
        "fingerprint_id",
        "source_url",
        "next_followup",
        "action_log",
        "icp_profile",
    ]
    fields = {
        k: (json.dumps(v) if isinstance(v, (list, dict)) else v)
        for k, v in body.items()
        if k in allowed
    }
    if existing:
        if fields:
            set_clause = ", ".join(f"{k} = :{k}" for k in fields)
            fields["uid"] = user_id
            fields["cid"] = chat_id
            DatabaseManager.execute_query(
                f"UPDATE leads SET {set_clause}, updated_at = CURRENT_TIMESTAMP "
                "WHERE user_id = :uid AND chat_id = :cid",
                fields,
            )
    else:
        # Garante que o chat exista antes de inserir (FK leads.chat_id → chats.chat_id)
        chat_exists = DatabaseManager.fetch_one(
            "SELECT chat_id FROM chats WHERE chat_id = :cid", {"cid": chat_id}
        )
        if not chat_exists:
            chat_name = body.get("name") or "Lead manual"
            DatabaseManager.execute_query(
                "INSERT INTO chats (chat_id, user_id, chat_name, source, status) "
                "VALUES (:cid, :uid, :name, 'crm', 'active')",
                {"cid": chat_id, "uid": user_id, "name": chat_name},
            )
        fields["id"] = str(uuid.uuid4())
        fields["user_id"] = user_id
        fields["chat_id"] = chat_id
        fields.setdefault("funnel_stage", "nao_atendido")
        cols = ", ".join(fields.keys())
        vals = ", ".join(f":{k}" for k in fields.keys())
        DatabaseManager.execute_query(
            f"INSERT INTO leads ({cols}) VALUES ({vals})", fields
        )
    row = DatabaseManager.fetch_one(
        "SELECT * FROM leads WHERE user_id = :uid AND chat_id = :cid LIMIT 1",
        {"uid": user_id, "cid": chat_id},
    )
    return {"lead": dict(row) if row else {}}


# ── Chat delete ──────────────────────────────────────────────────────────────


@trigger_router.delete("/chats/{chat_id}")
async def delete_trigger_chat(chat_id: str, request: Request):
    DatabaseManager.execute_query(
        "UPDATE trigger_executions SET status = 'deleted' WHERE chat_id = :cid",
        {"cid": chat_id},
    )
    DatabaseManager.execute_query(
        "DELETE FROM chats WHERE chat_id = :cid",
        {"cid": chat_id},
    )
    return {"ok": True}


__all__ = ["trigger_router"]

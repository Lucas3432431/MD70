"""
Rotas de ações diretas para Google Tasks, Google Calendar e Google Keep.
Todas as rotas usam os tokens OAuth já armazenados por usuário na tabela mcp_integrations.
"""

from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from App.Core.Logs import debug, error as log_error
from App.Core.Services.Common.Dependencies import COMPONENTS
from App.Core.Services.Integrations.IntegrationsRoutes import _get_auth_payload
from App.Core.Settings.Settings import GOOGLE_AUTH_CLIENT_ID, GOOGLE_AUTH_CLIENT_SECRET

google_actions_router = APIRouter(tags=["Google Actions"], prefix="/api/google")

# ========================================================================
# PROVIDER → ENV KEYS
# ========================================================================

_PROVIDER_KEYS = {
    "google-tasks": (
        "GTASKS_CLIENT_ID",
        "GTASKS_CLIENT_SECRET",
        "GTASKS_REFRESH_TOKEN",
        "GTASKS_ACCESS_TOKEN",
    ),
    "google-calendar": (
        "GCALENDAR_CLIENT_ID",
        "GCALENDAR_CLIENT_SECRET",
        "GCALENDAR_REFRESH_TOKEN",
        "GCALENDAR_ACCESS_TOKEN",
    ),
    "google-keep": (
        "GKEEP_CLIENT_ID",
        "GKEEP_CLIENT_SECRET",
        "GKEEP_REFRESH_TOKEN",
        "GKEEP_ACCESS_TOKEN",
    ),
}


# ========================================================================
# TOKEN REFRESH HELPER
# ========================================================================


async def _get_valid_token(client_id: str, provider: str, db_manager) -> str:
    """
    Garante um access_token válido para o provider indicado.
    1. Busca env_vars da integração.
    2. Verifica o token via tokeninfo.
    3. Se expirado (ou expires_in < 120s), faz refresh e persiste o novo token.
    4. Lança HTTPException(503) se não houver refresh_token.
    """
    _, _, key_refresh, key_access = _PROVIDER_KEYS[provider]

    env_vars: dict = db_manager.execute_transaction(
        lambda session: db_manager.get_mcp_integration_env_vars(
            session, client_id=client_id, provider=provider
        )
    )

    access_token: str = env_vars.get(key_access, "")
    refresh_token: str = env_vars.get(key_refresh, "")

    if not refresh_token and not access_token:
        raise HTTPException(
            status_code=503,
            detail=f"Google token indisponível para provider '{provider}'. Reconecte a integração.",
        )

    needs_refresh = True

    if access_token:
        try:
            async with httpx.AsyncClient(timeout=10.0) as http:
                r = await http.get(
                    "https://www.googleapis.com/oauth2/v1/tokeninfo",
                    params={"access_token": access_token},
                )
            if r.status_code == 200:
                info = r.json()
                expires_in = int(info.get("expires_in", 0))
                if expires_in >= 120:
                    needs_refresh = False
        except Exception as exc:
            debug(f"[GoogleActions] tokeninfo check falhou ({provider}): {exc}")

    if not needs_refresh:
        return access_token

    if not refresh_token:
        raise HTTPException(
            status_code=503,
            detail="Google token indisponível — refresh_token ausente. Reconecte a integração.",
        )

    if not GOOGLE_AUTH_CLIENT_ID or not GOOGLE_AUTH_CLIENT_SECRET:
        raise HTTPException(
            status_code=503,
            detail="Google OAuth não configurado no servidor.",
        )

    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            resp = await http.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": GOOGLE_AUTH_CLIENT_ID,
                    "client_secret": GOOGLE_AUTH_CLIENT_SECRET,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
        token_data = resp.json()
    except Exception as exc:
        log_error(f"[GoogleActions] Erro ao fazer refresh de token ({provider}): {exc}")
        raise HTTPException(status_code=503, detail="Google token indisponível")

    new_access_token = token_data.get("access_token", "")
    if not new_access_token:
        log_error(
            f"[GoogleActions] Refresh falhou ({provider}): {token_data.get('error')} — {token_data.get('error_description')}"
        )
        raise HTTPException(status_code=503, detail="Google token indisponível")

    patch = {key_access: new_access_token}
    if token_data.get("refresh_token"):
        patch[key_refresh] = token_data["refresh_token"]

    try:
        db_manager.execute_transaction(
            lambda session: db_manager.patch_mcp_integration_env_vars(
                session, client_id=client_id, provider=provider, patch=patch
            )
        )
    except Exception as exc:
        log_error(
            f"[GoogleActions] Falha ao persistir novo access_token ({provider}): {exc}"
        )

    debug(f"[GoogleActions] Token renovado com sucesso ({provider})")
    return new_access_token


def _auth_headers(access_token: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _strip_gtask_prefix(task_id: str) -> str:
    if task_id.startswith("gtask_"):
        return task_id[len("gtask_") :]
    return task_id


# ========================================================================
# MODELS
# ========================================================================


class TaskCreateBody(BaseModel):
    title: str
    notes: Optional[str] = None
    due: Optional[str] = None


class CalendarEventBody(BaseModel):
    summary: str
    start_datetime: str
    end_datetime: str
    description: Optional[str] = None
    all_day: bool = False


class KeepNoteBody(BaseModel):
    title: Optional[str] = None
    text: str


# ========================================================================
# GOOGLE TASKS
# ========================================================================

_TASKS_BASE = "https://tasks.googleapis.com/tasks/v1/lists/@default/tasks"


@google_actions_router.post("/tasks")
async def create_task(body: TaskCreateBody, request: Request):
    """Cria uma tarefa no Google Tasks do usuário."""
    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))

    db_manager = COMPONENTS.get("db_manager")
    if not db_manager:
        raise HTTPException(status_code=500, detail="DB manager não configurado")

    access_token = await _get_valid_token(client_id, "google-tasks", db_manager)

    task_body: dict = {"title": body.title}
    if body.notes:
        task_body["notes"] = body.notes
    if body.due:
        task_body["due"] = body.due

    async with httpx.AsyncClient(timeout=15.0) as http:
        resp = await http.post(
            _TASKS_BASE, headers=_auth_headers(access_token), json=task_body
        )

    if resp.status_code == 401:
        access_token = await _get_valid_token(client_id, "google-tasks", db_manager)
        async with httpx.AsyncClient(timeout=15.0) as http:
            resp = await http.post(
                _TASKS_BASE, headers=_auth_headers(access_token), json=task_body
            )

    if resp.status_code not in (200, 201):
        log_error(
            f"[GoogleTasks] Erro ao criar tarefa: {resp.status_code} — {resp.text[:300]}"
        )
        raise HTTPException(
            status_code=502, detail="Erro ao criar tarefa no Google Tasks"
        )

    return resp.json()


@google_actions_router.patch("/tasks/{task_id}/complete")
async def complete_task(task_id: str, request: Request):
    """Marca uma tarefa como concluída no Google Tasks."""
    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))

    db_manager = COMPONENTS.get("db_manager")
    if not db_manager:
        raise HTTPException(status_code=500, detail="DB manager não configurado")

    access_token = await _get_valid_token(client_id, "google-tasks", db_manager)
    clean_id = _strip_gtask_prefix(task_id)
    url = f"{_TASKS_BASE}/{clean_id}"
    patch_body = {"status": "completed", "completed": _now_iso()}

    async with httpx.AsyncClient(timeout=15.0) as http:
        resp = await http.patch(
            url, headers=_auth_headers(access_token), json=patch_body
        )

    if resp.status_code == 401:
        access_token = await _get_valid_token(client_id, "google-tasks", db_manager)
        async with httpx.AsyncClient(timeout=15.0) as http:
            resp = await http.patch(
                url, headers=_auth_headers(access_token), json=patch_body
            )

    if resp.status_code not in (200, 204):
        log_error(
            f"[GoogleTasks] Erro ao completar tarefa {clean_id}: {resp.status_code} — {resp.text[:300]}"
        )
        raise HTTPException(
            status_code=502, detail="Erro ao completar tarefa no Google Tasks"
        )

    return {"ok": True}


@google_actions_router.delete("/tasks/{task_id}")
async def delete_task(task_id: str, request: Request):
    """Remove uma tarefa do Google Tasks."""
    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))

    db_manager = COMPONENTS.get("db_manager")
    if not db_manager:
        raise HTTPException(status_code=500, detail="DB manager não configurado")

    access_token = await _get_valid_token(client_id, "google-tasks", db_manager)
    clean_id = _strip_gtask_prefix(task_id)
    url = f"{_TASKS_BASE}/{clean_id}"

    async with httpx.AsyncClient(timeout=15.0) as http:
        resp = await http.delete(url, headers=_auth_headers(access_token))

    if resp.status_code == 401:
        access_token = await _get_valid_token(client_id, "google-tasks", db_manager)
        async with httpx.AsyncClient(timeout=15.0) as http:
            resp = await http.delete(url, headers=_auth_headers(access_token))

    if resp.status_code not in (200, 204):
        log_error(
            f"[GoogleTasks] Erro ao deletar tarefa {clean_id}: {resp.status_code} — {resp.text[:300]}"
        )
        raise HTTPException(
            status_code=502, detail="Erro ao deletar tarefa no Google Tasks"
        )

    return {"ok": True}


# ========================================================================
# GOOGLE CALENDAR
# ========================================================================

_CALENDAR_BASE = "https://www.googleapis.com/calendar/v3/calendars/primary/events"


@google_actions_router.post("/calendar/events")
async def create_calendar_event(body: CalendarEventBody, request: Request):
    """Cria um evento no Google Calendar do usuário."""
    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))

    db_manager = COMPONENTS.get("db_manager")
    if not db_manager:
        raise HTTPException(status_code=500, detail="DB manager não configurado")

    access_token = await _get_valid_token(client_id, "google-calendar", db_manager)

    if body.all_day:
        start_date = body.start_datetime[:10]
        end_date = body.end_datetime[:10]
        start_block = {"date": start_date}
        end_block = {"date": end_date}
    else:
        start_block = {"dateTime": body.start_datetime}
        end_block = {"dateTime": body.end_datetime}

    event_body: dict = {
        "summary": body.summary,
        "start": start_block,
        "end": end_block,
    }
    if body.description:
        event_body["description"] = body.description

    async with httpx.AsyncClient(timeout=15.0) as http:
        resp = await http.post(
            _CALENDAR_BASE, headers=_auth_headers(access_token), json=event_body
        )

    if resp.status_code == 401:
        access_token = await _get_valid_token(client_id, "google-calendar", db_manager)
        async with httpx.AsyncClient(timeout=15.0) as http:
            resp = await http.post(
                _CALENDAR_BASE, headers=_auth_headers(access_token), json=event_body
            )

    if resp.status_code not in (200, 201):
        log_error(
            f"[GoogleCalendar] Erro ao criar evento: {resp.status_code} — {resp.text[:300]}"
        )
        raise HTTPException(
            status_code=502, detail="Erro ao criar evento no Google Calendar"
        )

    return resp.json()


# ========================================================================
# GOOGLE KEEP
# ========================================================================

_KEEP_BASE = "https://keep.googleapis.com/v1/notes"


@google_actions_router.get("/keep/notes")
async def list_keep_notes(request: Request):
    """Lista notas do Google Keep do usuário (max 100)."""
    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))

    db_manager = COMPONENTS.get("db_manager")
    if not db_manager:
        raise HTTPException(status_code=500, detail="DB manager não configurado")

    access_token = await _get_valid_token(client_id, "google-keep", db_manager)

    async with httpx.AsyncClient(timeout=15.0) as http:
        resp = await http.get(
            _KEEP_BASE,
            headers=_auth_headers(access_token),
            params={"pageSize": 100},
        )

    if resp.status_code == 401:
        access_token = await _get_valid_token(client_id, "google-keep", db_manager)
        async with httpx.AsyncClient(timeout=15.0) as http:
            resp = await http.get(
                _KEEP_BASE,
                headers=_auth_headers(access_token),
                params={"pageSize": 100},
            )

    if resp.status_code not in (200, 201):
        log_error(
            f"[GoogleKeep] Erro ao listar notas: {resp.status_code} — {resp.text[:300]}"
        )
        raise HTTPException(
            status_code=502, detail="Erro ao listar notas do Google Keep"
        )

    data = resp.json()
    notes = []
    for n in data.get("notes", []):
        text_content = ""
        body = n.get("body", {})
        if "text" in body:
            text_content = body["text"].get("text", "")
        elif "list" in body:
            items = body["list"].get("listItems", [])
            text_content = "\n".join(
                f"- {item.get('text', {}).get('text', '')}"
                for item in items
                if not item.get("checked", False)
            )
        notes.append(
            {
                "id": n.get("name", ""),
                "title": n.get("title", ""),
                "content": text_content,
                "created_at": n.get("createTime", ""),
                "updated_at": n.get("updateTime", ""),
            }
        )
    return notes


@google_actions_router.post("/keep/notes")
async def create_keep_note(body: KeepNoteBody, request: Request):
    """Cria uma nota no Google Keep do usuário."""
    payload = _get_auth_payload(request)
    client_id = str(payload.get("client_id", ""))

    db_manager = COMPONENTS.get("db_manager")
    if not db_manager:
        raise HTTPException(status_code=500, detail="DB manager não configurado")

    access_token = await _get_valid_token(client_id, "google-keep", db_manager)

    note_body = {
        "body": {"text": {"text": body.text}},
        "title": body.title or "",
    }

    async with httpx.AsyncClient(timeout=15.0) as http:
        resp = await http.post(
            _KEEP_BASE, headers=_auth_headers(access_token), json=note_body
        )

    if resp.status_code == 401:
        access_token = await _get_valid_token(client_id, "google-keep", db_manager)
        async with httpx.AsyncClient(timeout=15.0) as http:
            resp = await http.post(
                _KEEP_BASE, headers=_auth_headers(access_token), json=note_body
            )

    if resp.status_code not in (200, 201):
        log_error(
            f"[GoogleKeep] Erro ao criar nota: {resp.status_code} — {resp.text[:300]}"
        )
        raise HTTPException(status_code=502, detail="Erro ao criar nota no Google Keep")

    data = resp.json()
    return {"ok": True, "name": data.get("name", "")}

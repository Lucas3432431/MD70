"""
Rotas de Tarefas Agendadas — /api/scheduled
GET/POST/PATCH/DELETE de scheduled_tasks e task_executions.
"""

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Optional, List

from App.Core.Logs import error as log_error
from App.Features.Auth import get_auth_service
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Core.Services.Scheduled.ScheduledService import ScheduledService
from App.Core.Scheduler.SchedulerManager import get_scheduler_manager, run_task_job

scheduled_router = APIRouter(tags=["Scheduled"], prefix="/api/scheduled")

_service = ScheduledService()


# ------------------------------------------------------------------ auth helper


def _get_user(request: Request) -> dict:
    from App.Core.Services.Auth.RequestAuth import get_payload_from_request

    return get_payload_from_request(request)


# ================================================================== TASKS


class TaskCreate(BaseModel):
    name: str
    description: Optional[str] = None
    cron_expression: str
    cron_label: Optional[str] = None
    prompt: str
    integrations: Optional[List[str]] = []
    autonomy_level: Optional[int] = 3  # 1=sem autonomia 2=acesso a dados 3=autônomo
    utc_offset: Optional[int] = 0


class TaskUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    cron_expression: Optional[str] = None
    cron_label: Optional[str] = None
    prompt: Optional[str] = None
    integrations: Optional[List[str]] = None
    autonomy_level: Optional[int] = None
    status: Optional[str] = None  # active | paused
    utc_offset: Optional[int] = None


@scheduled_router.get("/tasks")
async def list_tasks(request: Request):
    user = _get_user(request)
    try:
        return {
            "tasks": DatabaseManager.execute_transaction(
                lambda session: _service.list_tasks(session, user["user_id"])
            )
        }
    except Exception as e:
        log_error(f"[SCHEDULED] list_tasks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@scheduled_router.post("/tasks")
async def create_task(request: Request, body: TaskCreate):
    user = _get_user(request)
    try:
        task = DatabaseManager.execute_transaction(
            lambda session: _service.create_task(session, user["user_id"], body.dict())
        )
        try:
            get_scheduler_manager().add_task(task)
        except Exception as sched_err:
            log_error(
                f"[SCHEDULED] scheduler.add_task falhou (não crítico): {sched_err}"
            )
        return {"task": task}
    except Exception as e:
        log_error(f"[SCHEDULED] create_task: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@scheduled_router.patch("/tasks/{task_id}")
async def update_task(task_id: str, request: Request, body: TaskUpdate):
    user = _get_user(request)
    try:
        task = DatabaseManager.execute_transaction(
            lambda session: _service.update_task(
                session, task_id, user["user_id"], body.dict(exclude_none=True)
            )
        )
        if not task:
            raise HTTPException(status_code=404, detail="Task não encontrada")
        try:
            get_scheduler_manager().update_task(task)
        except Exception as sched_err:
            log_error(
                f"[SCHEDULED] scheduler.update_task falhou (não crítico): {sched_err}"
            )
        return {"task": task}
    except HTTPException:
        raise
    except Exception as e:
        log_error(f"[SCHEDULED] update_task: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@scheduled_router.delete("/tasks/{task_id}")
async def delete_task(task_id: str, request: Request):
    user = _get_user(request)
    try:
        ok = DatabaseManager.execute_transaction(
            lambda session: _service.delete_task(session, task_id, user["user_id"])
        )
        if not ok:
            raise HTTPException(status_code=404, detail="Task não encontrada")
        try:
            get_scheduler_manager().remove_task(task_id)
        except Exception as sched_err:
            log_error(
                f"[SCHEDULED] scheduler.remove_task falhou (não crítico): {sched_err}"
            )
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        log_error(f"[SCHEDULED] delete_task: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ================================================================== EXECUTIONS


@scheduled_router.get("/executions")
async def list_executions(request: Request, task_id: Optional[str] = None):
    user = _get_user(request)
    try:
        return {
            "executions": DatabaseManager.execute_transaction(
                lambda session: _service.list_executions(
                    session, user["user_id"], task_id
                )
            )
        }
    except Exception as e:
        log_error(f"[SCHEDULED] list_executions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@scheduled_router.get("/executions/pending")
async def list_pending(request: Request):
    user = _get_user(request)
    try:
        executions = DatabaseManager.execute_transaction(
            lambda session: _service.list_pending(session, user["user_id"])
        )
        count = DatabaseManager.execute_transaction(
            lambda session: _service.pending_count(session, user["user_id"])
        )
        return {"executions": executions, "count": count}
    except Exception as e:
        log_error(f"[SCHEDULED] list_pending: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@scheduled_router.get("/executions/pending/count")
async def pending_count(request: Request):
    user = _get_user(request)
    try:
        count = DatabaseManager.execute_transaction(
            lambda session: _service.pending_count(session, user["user_id"])
        )
        return {"count": count}
    except Exception as e:
        log_error(f"[SCHEDULED] pending_count: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@scheduled_router.patch("/executions/{execution_id}/approve")
async def approve_execution(execution_id: str, request: Request):
    user = _get_user(request)
    try:
        ex = DatabaseManager.execute_transaction(
            lambda session: _service.set_execution_status(
                session, execution_id, user["user_id"], "approved"
            )
        )
        if not ex:
            raise HTTPException(status_code=404, detail="Execução não encontrada")
        return {"execution": ex}
    except HTTPException:
        raise
    except Exception as e:
        log_error(f"[SCHEDULED] approve: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@scheduled_router.patch("/executions/{execution_id}/reject")
async def reject_execution(execution_id: str, request: Request):
    user = _get_user(request)
    try:
        ex = DatabaseManager.execute_transaction(
            lambda session: _service.set_execution_status(
                session, execution_id, user["user_id"], "rejected"
            )
        )
        if not ex:
            raise HTTPException(status_code=404, detail="Execução não encontrada")
        return {"execution": ex}
    except HTTPException:
        raise
    except Exception as e:
        log_error(f"[SCHEDULED] reject: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ================================================================== DEV TRIGGER


@scheduled_router.get("/chats")
async def list_scheduled_chats(
    request: Request,
    limit: int = 20,
    offset: int = 0,
):
    """Lista todos os chats gerados por tarefas agendadas do usuário."""
    user = _get_user(request)
    user_id = user["user_id"]
    db = DatabaseManager()
    rows = db.fetch_all(
        """SELECT chat_id, chat_name, seen, created_at, updated_at
           FROM chats
           WHERE source = 'scheduled' AND user_id = :uid
           ORDER BY updated_at DESC
           LIMIT :limit OFFSET :offset""",
        {"uid": user_id, "limit": limit, "offset": offset},
    )
    total = (
        db.fetch_one(
            "SELECT COUNT(*) as n FROM chats WHERE source = 'scheduled' AND user_id = :uid",
            {"uid": user_id},
        )
        or {}
    ).get("n", 0)
    return {"chats": list(rows or []), "total": total}


@scheduled_router.get("/google-calendar-events")
async def list_google_calendar_events(
    request: Request,
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
):
    """
    Retorna eventos do Google Calendar + Google Tasks do usuário.
    Janela padrão: semana atual (domingo a sábado).
    """
    from datetime import datetime, timedelta, timezone
    import asyncio as _asyncio
    import httpx as _httpx
    import urllib.parse

    user = _get_user(request)
    user_id = user["user_id"]
    db = DatabaseManager()

    user_row = db.fetch_one(
        "SELECT client_id FROM users WHERE user_id = :uid",
        {"uid": user_id},
    )
    if not user_row or not user_row.get("client_id"):
        return {"connected": False, "events": []}
    client_id = user_row["client_id"]

    configs = DatabaseManager.execute_transaction(
        lambda session: DatabaseManager.get_mcp_configs(session, client_id)
    )
    gcal_cfg = next((c for c in configs if c["provider"] == "google-calendar"), None)
    gtasks_cfg = next((c for c in configs if c["provider"] == "google-tasks"), None)
    gkeep_cfg = next((c for c in configs if c["provider"] == "google-keep"), None)

    if not gcal_cfg and not gtasks_cfg:
        return {
            "connected": False,
            "gkeep_connected": gkeep_cfg is not None,
            "events": [],
        }

    now = datetime.now(timezone.utc)
    if time_min:
        t_min = datetime.fromisoformat(time_min.replace("Z", "+00:00"))
    else:
        # Início do domingo da semana atual
        days_since_sunday = (now.weekday() + 1) % 7
        t_min = (now - timedelta(days=days_since_sunday)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    if time_max:
        t_max = datetime.fromisoformat(time_max.replace("Z", "+00:00"))
    else:
        # Fim do sábado (7 dias a partir do domingo)
        t_max = t_min + timedelta(days=7)

    def _make_token_helper(
        env: dict,
        access_key: str,
        refresh_key: str,
        cid_key: str,
        secret_key: str,
        auth_flag: list,
        provider: str,
    ):
        """Retorna (_get coroutine factory, token dict) para uma integração."""
        token = {"value": env.get(access_key, "")}
        refresh_token = env.get(refresh_key, "")
        client_id_oauth = env.get(cid_key, "")
        client_secret = env.get(secret_key, "")

        async def _refresh() -> bool:
            if not refresh_token:
                return False
            try:
                async with _httpx.AsyncClient(timeout=10.0) as h:
                    r = await h.post(
                        "https://oauth2.googleapis.com/token",
                        data={
                            "client_id": client_id_oauth,
                            "client_secret": client_secret,
                            "refresh_token": refresh_token,
                            "grant_type": "refresh_token",
                        },
                    )
                    new = r.json().get("access_token")
                    if new:
                        token["value"] = new
                        return True
            except Exception:
                pass
            return False

        async def _get(url: str, params: dict) -> dict:
            headers = {"Authorization": f"Bearer {token['value']}"}
            async with _httpx.AsyncClient(timeout=15.0) as http:
                resp = await http.get(url, headers=headers, params=params)
                if resp.status_code == 401:
                    if await _refresh():
                        headers["Authorization"] = f"Bearer {token['value']}"
                        async with _httpx.AsyncClient(timeout=15.0) as http2:
                            resp = await http2.get(url, headers=headers, params=params)
                if resp.status_code in (401, 403):
                    auth_flag[0] = False
                    try:
                        DatabaseManager.execute_transaction(
                            lambda session: DatabaseManager.mark_integration_token_invalid(
                                session, client_id, provider
                            )
                        )
                    except Exception:
                        pass
                    return {}
                if resp.status_code != 200:
                    log_error(
                        f"[SCHEDULED] {provider} HTTP {resp.status_code}: {resp.text[:300]}"
                    )
                    return {}
                return resp.json()

        return _get

    _gcal_auth_ok = [True]
    _gtasks_auth_ok = [True]

    async def _fetch_calendar_events() -> list:
        if not gcal_cfg:
            return []
        _get = _make_token_helper(
            gcal_cfg["env"],
            "GCALENDAR_ACCESS_TOKEN",
            "GCALENDAR_REFRESH_TOKEN",
            "GCALENDAR_CLIENT_ID",
            "GCALENDAR_CLIENT_SECRET",
            _gcal_auth_ok,
            "google-calendar",
        )
        # Busca lista de calendários do usuário
        cal_list_data = await _get(
            "https://www.googleapis.com/calendar/v3/users/me/calendarList",
            {"maxResults": 50, "minAccessRole": "reader"},
        )
        cal_ids = [
            c["id"] for c in cal_list_data.get("items", []) if not c.get("deleted")
        ]
        if not cal_ids:
            cal_ids = ["primary"]

        log_error(f"[SCHEDULED][DEBUG] calendars={cal_ids}")

        params = {
            "timeMin": t_min.isoformat(),
            "timeMax": t_max.isoformat(),
            "maxResults": 250,
            "singleEvents": True,
            "orderBy": "startTime",
        }
        results = await _asyncio.gather(
            *[
                _get(
                    f"https://www.googleapis.com/calendar/v3/calendars/{urllib.parse.quote(cid, safe='')}/events",
                    params,
                )
                for cid in cal_ids
            ]
        )

        events = []
        seen_ids: set = set()
        for cid, data in zip(cal_ids, results):
            log_error(f"[SCHEDULED][DEBUG] {cid} → {len(data.get('items', []))} events")
            for e in data.get("items", []):
                eid = e.get("id", "")
                if eid in seen_ids:
                    continue
                seen_ids.add(eid)
                start_raw = e.get("start", {})
                end_raw = e.get("end", {})
                start = start_raw.get("dateTime") or start_raw.get("date")
                end = end_raw.get("dateTime") or end_raw.get("date")
                events.append(
                    {
                        "id": f"gcal_{eid}",
                        "title": e.get("summary", "(sem título)"),
                        "start": start,
                        "end": end,
                        "description": e.get("description", ""),
                        "html_link": e.get("htmlLink", ""),
                        "all_day": "dateTime" not in start_raw,
                        "source": "google_calendar",
                    }
                )
        return events

    async def _fetch_tasks() -> list:
        if not gtasks_cfg:
            return []
        _get = _make_token_helper(
            gtasks_cfg["env"],
            "GTASKS_ACCESS_TOKEN",
            "GTASKS_REFRESH_TOKEN",
            "GTASKS_CLIENT_ID",
            "GTASKS_CLIENT_SECRET",
            _gtasks_auth_ok,
            "google-tasks",
        )
        lists_data = await _get(
            "https://tasks.googleapis.com/tasks/v1/users/@me/lists",
            {"maxResults": 20},
        )
        task_lists = lists_data.get("items", [])
        if not task_lists:
            task_lists = [{"id": "@default"}]

        all_tasks: list = []
        for tl in task_lists:
            tl_id = tl.get("id", "@default")
            data = await _get(
                f"https://tasks.googleapis.com/tasks/v1/lists/{tl_id}/tasks",
                {
                    "showCompleted": True,
                    "showHidden": False,
                    "maxResults": 100,
                    "dueMin": t_min.isoformat(),
                    "dueMax": t_max.isoformat(),
                },
            )
            for t in data.get("items", []):
                due = t.get("due")
                if not due:
                    continue
                all_tasks.append(
                    {
                        "id": f"gtask_{t.get('id', '')}",
                        "title": t.get("title", "(sem título)"),
                        "start": due,
                        "end": due,
                        "description": t.get("notes", ""),
                        "html_link": "",
                        "all_day": True,
                        "source": "google_task",
                        "status": t.get("status", "needsAction"),
                    }
                )
        return all_tasks

    try:
        cal_events, tasks = await _asyncio.gather(
            _fetch_calendar_events(),
            _fetch_tasks(),
            return_exceptions=True,
        )
        events_out = []
        if isinstance(cal_events, list):
            events_out.extend(cal_events)
        else:
            log_error(f"[SCHEDULED] calendar events error: {cal_events}")
        if isinstance(tasks, list):
            events_out.extend(tasks)
        else:
            log_error(f"[SCHEDULED] tasks error: {tasks}")

        def _sort_key(e):
            s = e.get("start") or ""
            try:
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except Exception:
                return datetime.max.replace(tzinfo=timezone.utc)

        events_out.sort(key=_sort_key)
        return {
            "connected": True,
            "gcal_connected": gcal_cfg is not None,
            "gtasks_connected": gtasks_cfg is not None,
            "gkeep_connected": gkeep_cfg is not None,
            "gcal_token_valid": _gcal_auth_ok[0],
            "gtasks_token_valid": _gtasks_auth_ok[0],
            "events": events_out,
        }
    except Exception as exc:
        log_error(f"[SCHEDULED] google-calendar-events: {exc}")
        return {
            "connected": True,
            "gcal_connected": False,
            "gtasks_connected": False,
            "gkeep_connected": gkeep_cfg is not None,
            "events": [],
            "error": str(exc),
        }


class TriggerBody(BaseModel):
    task_id: str


@scheduled_router.post("/trigger")
async def trigger_task(request: Request, body: TriggerBody):
    """Força execução imediata de uma task específica. Requer X-Dev-Bypass-Key."""
    from App.Core.Settings.Settings import GLOBAL_CONFIG

    dev_bypass_key = request.headers.get("X-Dev-Bypass-Key", "")
    expected = GLOBAL_CONFIG.get("dev_bypass_key", "")
    if not expected or dev_bypass_key != expected:
        raise HTTPException(status_code=403, detail="Acesso negado")
    try:
        run_task_job(body.task_id)
        return {"success": True, "task_id": body.task_id}
    except Exception as e:
        log_error(f"[SCHEDULED] trigger: {e}")
        raise HTTPException(status_code=500, detail=str(e))

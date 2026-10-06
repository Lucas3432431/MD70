"""Provider Google Calendar para MCP nativo."""
from typing import Dict, Any, List
import httpx

from ._shared import _TokenExpiredError, _refresh_access_token

TOOL_DEFINITIONS: List[Dict] = [
    {
        "name": "mcp__google-calendar__list_events",
        "description": "[GOOGLE-CALENDAR] Lista eventos futuros da agenda do usuário.",
        "parameters": {
            "type": "object",
            "properties": {
                "max_results": {
                    "type": "integer",
                    "description": "Número máximo de eventos (padrão 10)",
                },
                "days_ahead": {
                    "type": "integer",
                    "description": "Quantos dias à frente buscar (padrão 7)",
                },
            },
        },
    },
    {
        "name": "mcp__google-calendar__create_event",
        "description": "[GOOGLE-CALENDAR] Cria um novo evento na agenda do usuário.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Título do evento"},
                "start": {
                    "type": "string",
                    "description": "Data/hora de início (ISO 8601, ex: 2026-05-25T10:00:00)",
                },
                "end": {
                    "type": "string",
                    "description": "Data/hora de término (ISO 8601)",
                },
                "description": {
                    "type": "string",
                    "description": "Descrição opcional do evento",
                },
            },
            "required": ["title", "start", "end"],
        },
    },
    {
        "name": "mcp__google-calendar__update_event",
        "description": "[GOOGLE-CALENDAR] Atualiza um evento existente na agenda (suporta atualização parcial).",
        "parameters": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "ID do evento a atualizar",
                },
                "title": {
                    "type": "string",
                    "description": "Novo título (opcional)",
                },
                "start": {
                    "type": "string",
                    "description": "Nova data/hora de início ISO 8601 (opcional)",
                },
                "end": {
                    "type": "string",
                    "description": "Nova data/hora de fim ISO 8601 (opcional)",
                },
                "description": {
                    "type": "string",
                    "description": "Nova descrição (opcional)",
                },
                "location": {
                    "type": "string",
                    "description": "Localização do evento (opcional)",
                },
            },
            "required": ["event_id"],
        },
    },
    {
        "name": "mcp__google-calendar__delete_event",
        "description": "[GOOGLE-CALENDAR] Remove um evento da agenda do usuário.",
        "parameters": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "ID do evento a remover",
                },
            },
            "required": ["event_id"],
        },
    },
]


async def call(tool_name: str, args: Dict, env: Dict) -> Dict:
    access_token = env.get("GCALENDAR_ACCESS_TOKEN", "")
    refresh_token = env.get("GCALENDAR_REFRESH_TOKEN", "")
    client_id_oauth = env.get("GCALENDAR_CLIENT_ID", "")
    client_secret = env.get("GCALENDAR_CLIENT_SECRET", "")

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=15.0) as http:

        async def _refresh_and_retry(req_fn):
            resp = await req_fn(headers)
            if resp.status_code == 401 and refresh_token:
                new_token = await _refresh_access_token(
                    client_id_oauth, client_secret, refresh_token
                )
                if new_token:
                    headers["Authorization"] = f"Bearer {new_token}"
                    resp = await req_fn(headers)
            if resp.status_code in (401, 403):
                raise _TokenExpiredError(str(resp.status_code))
            return resp

        if tool_name == "list_events":
            from datetime import datetime, timedelta, timezone

            days = args.get("days_ahead", 7)
            now = datetime.now(timezone.utc)
            time_max = (now + timedelta(days=days)).isoformat()
            params = {
                "calendarId": "primary",
                "timeMin": now.isoformat(),
                "timeMax": time_max,
                "maxResults": args.get("max_results", 10),
                "singleEvents": True,
                "orderBy": "startTime",
            }
            resp = await _refresh_and_retry(
                lambda h: http.get(
                    "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                    headers=h,
                    params=params,
                )
            )
            events = resp.json().get("items", [])
            lines = [
                f"{e.get('summary','(sem título)')} — {e.get('start',{}).get('dateTime', e.get('start',{}).get('date',''))}"
                for e in events
            ]
            return {
                "success": True,
                "content": f"{len(events)} evento(s):\n" + "\n".join(lines),
            }

        elif tool_name == "create_event":
            body = {
                "summary": args.get("title"),
                "description": args.get("description", ""),
                "start": {"dateTime": args["start"], "timeZone": "America/Sao_Paulo"},
                "end": {"dateTime": args["end"], "timeZone": "America/Sao_Paulo"},
            }
            resp = await _refresh_and_retry(
                lambda h: http.post(
                    "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                    headers=h,
                    json=body,
                )
            )
            ev = resp.json()
            return {
                "success": True,
                "content": f"Evento criado: {ev.get('summary')} — {ev.get('htmlLink','')}",
            }

        elif tool_name == "update_event":
            event_id = args.get("event_id")
            patch_body = {}
            if args.get("title"):
                patch_body["summary"] = args["title"]
            if args.get("description") is not None:
                patch_body["description"] = args["description"]
            if args.get("location"):
                patch_body["location"] = args["location"]
            if args.get("start"):
                patch_body["start"] = {
                    "dateTime": args["start"],
                    "timeZone": "America/Sao_Paulo",
                }
            if args.get("end"):
                patch_body["end"] = {
                    "dateTime": args["end"],
                    "timeZone": "America/Sao_Paulo",
                }
            resp = await _refresh_and_retry(
                lambda h: http.patch(
                    f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{event_id}",
                    headers=h,
                    json=patch_body,
                )
            )
            ev = resp.json()
            if resp.status_code == 200:
                return {
                    "success": True,
                    "content": f"Evento atualizado: {ev.get('summary','')}",
                }
            return {
                "success": False,
                "error": ev.get("error", {}).get("message", str(resp.status_code)),
            }

        elif tool_name == "delete_event":
            event_id = args.get("event_id")
            resp = await _refresh_and_retry(
                lambda h: http.delete(
                    f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{event_id}",
                    headers=h,
                )
            )
            if resp.status_code == 204:
                return {"success": True, "content": f"Evento {event_id} removido"}
            try:
                err = resp.json().get("error", {}).get("message", str(resp.status_code))
            except Exception:
                err = str(resp.status_code)
            return {"success": False, "error": err}

    return {"success": False, "error": "Ferramenta não reconhecida"}

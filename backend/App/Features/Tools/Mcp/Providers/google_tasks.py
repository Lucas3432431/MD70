"""Provider Google Tasks para MCP nativo."""
from typing import Dict, Any, List
import httpx

from ._shared import _TokenExpiredError, _refresh_access_token

TOOL_DEFINITIONS: List[Dict] = [
    {
        "name": "mcp__google-tasks__list_task_lists",
        "description": "[GOOGLE-TASKS] Lista todas as listas de tarefas do usuário.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "mcp__google-tasks__list_tasks",
        "description": "[GOOGLE-TASKS] Lista tarefas de uma lista específica.",
        "parameters": {
            "type": "object",
            "properties": {
                "tasklist_id": {
                    "type": "string",
                    "description": "ID da lista de tarefas",
                },
                "show_completed": {
                    "type": "boolean",
                    "description": "Incluir tarefas concluídas (padrão false)",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Número máximo (padrão 20)",
                },
            },
            "required": ["tasklist_id"],
        },
    },
    {
        "name": "mcp__google-tasks__get_task",
        "description": "[GOOGLE-TASKS] Obtém detalhes de uma tarefa específica pelo ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "tasklist_id": {
                    "type": "string",
                    "description": "ID da lista de tarefas",
                },
                "task_id": {"type": "string", "description": "ID da tarefa"},
            },
            "required": ["tasklist_id", "task_id"],
        },
    },
]


async def call(tool_name: str, args: Dict, env: Dict) -> Dict:
    access_token = env.get("GTASKS_ACCESS_TOKEN", "")
    refresh_token = env.get("GTASKS_REFRESH_TOKEN", "")
    client_id_oauth = env.get("GTASKS_CLIENT_ID", "")
    client_secret = env.get("GTASKS_CLIENT_SECRET", "")

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

        if tool_name == "list_task_lists":
            resp = await _refresh_and_retry(
                lambda h: http.get(
                    "https://tasks.googleapis.com/tasks/v1/users/@me/lists", headers=h
                )
            )
            data = resp.json()
            if resp.status_code != 200:
                return {
                    "success": False,
                    "error": data.get("error", {}).get(
                        "message", str(resp.status_code)
                    ),
                }
            items = data.get("items", [])
            lines = [
                f"ID: {item['id']} | {item.get('title','(sem título)')}"
                for item in items
            ]
            return {
                "success": True,
                "content": f"{len(items)} lista(s):\n" + "\n".join(lines),
            }

        elif tool_name == "list_tasks":
            tasklist_id = args.get("tasklist_id")
            params = {
                "showCompleted": str(args.get("show_completed", False)).lower(),
                "maxResults": args.get("max_results", 20),
            }
            resp = await _refresh_and_retry(
                lambda h: http.get(
                    f"https://tasks.googleapis.com/tasks/v1/lists/{tasklist_id}/tasks",
                    headers=h,
                    params=params,
                )
            )
            data = resp.json()
            if resp.status_code != 200:
                return {
                    "success": False,
                    "error": data.get("error", {}).get(
                        "message", str(resp.status_code)
                    ),
                }
            items = data.get("items", [])
            lines = [
                f"ID: {item['id']} | {item.get('title','(sem título)')} | {item.get('status','')}"
                + (f" | vence: {item['due'][:10]}" if item.get("due") else "")
                for item in items
            ]
            return {
                "success": True,
                "content": f"{len(items)} tarefa(s):\n" + "\n".join(lines),
            }

        elif tool_name == "get_task":
            tasklist_id = args.get("tasklist_id")
            task_id = args.get("task_id")
            resp = await _refresh_and_retry(
                lambda h: http.get(
                    f"https://tasks.googleapis.com/tasks/v1/lists/{tasklist_id}/tasks/{task_id}",
                    headers=h,
                )
            )
            data = resp.json()
            if resp.status_code != 200:
                return {
                    "success": False,
                    "error": data.get("error", {}).get(
                        "message", str(resp.status_code)
                    ),
                }
            return {
                "success": True,
                "content": (
                    f"ID: {data.get('id')} | {data.get('title','')}\n"
                    f"Status: {data.get('status','')} | Vence: {data.get('due','N/A')[:10] if data.get('due') else 'N/A'}\n"
                    f"Notas: {data.get('notes','')}"
                ),
            }

    return {"success": False, "error": "Ferramenta não reconhecida"}

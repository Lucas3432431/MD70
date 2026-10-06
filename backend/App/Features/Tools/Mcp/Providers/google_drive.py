"""Provider Google Drive para MCP nativo."""
from typing import Dict, Any, List
import httpx

from ._shared import _TokenExpiredError, _refresh_access_token

TOOL_DEFINITIONS: List[Dict] = [
    {
        "name": "mcp__google-drive__search",
        "description": "[GOOGLE-DRIVE] Busca arquivos no Google Drive do usuário.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Texto ou nome do arquivo a buscar",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "mcp__google-drive__list",
        "description": "[GOOGLE-DRIVE] Lista arquivos recentes do Google Drive.",
        "parameters": {
            "type": "object",
            "properties": {
                "max_results": {
                    "type": "integer",
                    "description": "Número máximo de arquivos (padrão 10)",
                }
            },
        },
    },
    {
        "name": "mcp__google-drive__read",
        "description": "[GOOGLE-DRIVE] Lê o conteúdo de um arquivo do Google Drive pelo ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "ID do arquivo no Google Drive",
                }
            },
            "required": ["file_id"],
        },
    },
    {
        "name": "mcp__google-drive__create",
        "description": "[GOOGLE-DRIVE] Cria um novo arquivo de texto no Google Drive.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome do arquivo"},
                "content": {"type": "string", "description": "Conteúdo do arquivo"},
                "folder_id": {
                    "type": "string",
                    "description": "ID da pasta de destino (opcional, usa raiz se omitido)",
                },
            },
            "required": ["name", "content"],
        },
    },
    {
        "name": "mcp__google-drive__update",
        "description": "[GOOGLE-DRIVE] Atualiza o conteúdo de um arquivo existente no Google Drive.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "ID do arquivo a atualizar",
                },
                "content": {
                    "type": "string",
                    "description": "Novo conteúdo do arquivo",
                },
            },
            "required": ["file_id", "content"],
        },
    },
    {
        "name": "mcp__google-drive__delete",
        "description": "[GOOGLE-DRIVE] Move um arquivo do Google Drive para a lixeira.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "ID do arquivo a deletar",
                },
            },
            "required": ["file_id"],
        },
    },
]


async def call(tool_name: str, args: Dict, env: Dict) -> Dict:
    access_token = env.get("GDRIVE_ACCESS_TOKEN", "")
    refresh_token = env.get("GDRIVE_REFRESH_TOKEN", "")
    client_id_oauth = env.get("GDRIVE_CLIENT_ID", "")
    client_secret = env.get("GDRIVE_CLIENT_SECRET", "")

    headers = {"Authorization": f"Bearer {access_token}"}

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

        if tool_name == "search":
            query = args.get("query", "")
            escaped = query.replace("\\", "\\\\").replace("'", "\\'")
            params = {
                "q": f"fullText contains '{escaped}'",
                "pageSize": 10,
                "fields": "files(id,name,mimeType,modifiedTime,size)",
            }
            resp = await _refresh_and_retry(
                lambda h: http.get(
                    "https://www.googleapis.com/drive/v3/files",
                    headers=h,
                    params=params,
                )
            )
            files = resp.json().get("files", [])
            lines = [f"{f['name']} ({f['mimeType']}) — id: {f['id']}" for f in files]
            return {
                "success": True,
                "content": f"Encontrados {len(files)} arquivo(s):\n" + "\n".join(lines),
            }

        elif tool_name == "list":
            max_r = args.get("max_results", 10)
            params = {
                "pageSize": max_r,
                "fields": "files(id,name,mimeType,modifiedTime,size)",
                "orderBy": "modifiedTime desc",
            }
            resp = await _refresh_and_retry(
                lambda h: http.get(
                    "https://www.googleapis.com/drive/v3/files",
                    headers=h,
                    params=params,
                )
            )
            files = resp.json().get("files", [])
            lines = [f"{f['name']} ({f['mimeType']}) — id: {f['id']}" for f in files]
            return {
                "success": True,
                "content": f"{len(files)} arquivo(s) recentes:\n" + "\n".join(lines),
            }

        elif tool_name == "read":
            file_id = args.get("file_id", "")
            meta_resp = await _refresh_and_retry(
                lambda h: http.get(
                    f"https://www.googleapis.com/drive/v3/files/{file_id}",
                    headers=h,
                    params={"fields": "mimeType,name"},
                )
            )
            meta = meta_resp.json()
            mime = meta.get("mimeType", "")
            if mime.startswith("application/vnd.google-apps"):
                export_mime = {
                    "application/vnd.google-apps.document": "text/plain",
                    "application/vnd.google-apps.spreadsheet": "text/csv",
                    "application/vnd.google-apps.presentation": "text/plain",
                }.get(mime, "text/plain")
                resp = await _refresh_and_retry(
                    lambda h: http.get(
                        f"https://www.googleapis.com/drive/v3/files/{file_id}/export",
                        headers=h,
                        params={"mimeType": export_mime},
                    )
                )
                return {"success": True, "content": resp.text[:8000]}
            else:
                resp = await _refresh_and_retry(
                    lambda h: http.get(
                        f"https://www.googleapis.com/drive/v3/files/{file_id}",
                        headers=h,
                        params={"alt": "media"},
                    )
                )
                return {"success": True, "content": resp.text[:8000]}

        elif tool_name == "create":
            name = args.get("name", "Novo arquivo")
            content = args.get("content", "")
            folder_id = args.get("folder_id")
            metadata = {"name": name, "mimeType": "text/plain"}
            if folder_id:
                metadata["parents"] = [folder_id]
            import json as _json

            resp = await _refresh_and_retry(
                lambda h: http.post(
                    "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart",
                    headers={
                        **h,
                        "Content-Type": "multipart/related; boundary=boundary_sf",
                    },
                    content=(
                        b"--boundary_sf\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
                        + _json.dumps(metadata).encode()
                        + b"\r\n--boundary_sf\r\nContent-Type: text/plain; charset=UTF-8\r\n\r\n"
                        + content.encode()
                        + b"\r\n--boundary_sf--"
                    ),
                )
            )
            data = resp.json()
            if resp.status_code in (200, 201):
                return {
                    "success": True,
                    "file_id": data.get("id"),
                    "name": data.get("name"),
                }
            return {
                "success": False,
                "error": data.get("error", {}).get("message", str(resp.status_code)),
            }

        elif tool_name == "update":
            file_id = args.get("file_id", "")
            content = args.get("content", "")
            resp = await _refresh_and_retry(
                lambda h: http.patch(
                    f"https://www.googleapis.com/upload/drive/v3/files/{file_id}?uploadType=media",
                    headers={**h, "Content-Type": "text/plain; charset=UTF-8"},
                    content=content.encode(),
                )
            )
            data = resp.json()
            if resp.status_code == 200:
                return {
                    "success": True,
                    "file_id": data.get("id"),
                    "name": data.get("name"),
                }
            return {
                "success": False,
                "error": data.get("error", {}).get("message", str(resp.status_code)),
            }

        elif tool_name == "delete":
            file_id = args.get("file_id", "")
            resp = await _refresh_and_retry(
                lambda h: http.delete(
                    f"https://www.googleapis.com/drive/v3/files/{file_id}",
                    headers=h,
                )
            )
            if resp.status_code == 204:
                return {"success": True, "file_id": file_id}
            try:
                err = resp.json().get("error", {}).get("message", str(resp.status_code))
            except Exception:
                err = str(resp.status_code)
            return {"success": False, "error": err}

    return {"success": False, "error": "Ferramenta não reconhecida"}

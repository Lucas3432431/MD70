"""
generate_temporary_public_url — expõe qualquer arquivo do servidor como URL pública temporária.

Resolve o arquivo em ordem de prioridade:
  1. file_path absoluto fornecido pelo agente
  2. filename buscado no sandbox do usuário (/tmp/sandbox/{user_id}/)
  3. filename buscado na tabela attachments do chat atual
"""

import json
import mimetypes
import os


def execute(args: dict, chat_id: str | None, user_id: str | None) -> str:
    from App.Core.Utils.TempTokenStore import build_file_url
    from App.Core.Crunch.Storage.StorageManager import StorageManager
    from pathlib import Path as _Path

    file_path = (args.get("file_path") or "").strip()
    attachment_id = (args.get("attachment_id") or "").strip()
    filename = os.path.basename((args.get("filename") or "").strip())
    ttl_minutes = int(args.get("ttl_minutes") or 60)
    ttl_seconds = ttl_minutes * 60

    resolved_path: str | None = None

    # 1. Path absoluto fornecido diretamente
    if file_path and os.path.isfile(file_path):
        resolved_path = file_path

    # 2. attachment_id (attach_XXXX) — busca na tabela attachments
    if not resolved_path and attachment_id and user_id:
        try:
            from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager

            row = DatabaseManager.fetch_one(
                "SELECT storage_path, storage_env FROM attachments "
                "WHERE attachment_id = :aid AND user_id = :uid AND deleted_at IS NULL LIMIT 1",
                {"aid": attachment_id, "uid": user_id},
            )
            if row:
                sp = row.get("storage_path") or ""
                if row.get("storage_env") == "local":
                    fp = str(StorageManager.LOCAL_STORAGE_BASE / _Path(sp))
                else:
                    fp = sp
                if os.path.isfile(fp):
                    resolved_path = fp
        except Exception:
            pass

    # 3. filename no sandbox do usuário
    if not resolved_path and filename and user_id:
        sandbox = f"/tmp/sandbox/{user_id}/{filename}"
        if os.path.isfile(sandbox):
            resolved_path = sandbox

    # 4. filename via attachments do chat
    if not resolved_path and filename and chat_id and user_id:
        try:
            from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager

            row = DatabaseManager.fetch_one(
                "SELECT storage_path, storage_env FROM attachments "
                "WHERE chat_id = :cid AND file_name = :fname AND user_id = :uid AND deleted_at IS NULL "
                "ORDER BY created_at DESC LIMIT 1",
                {"cid": chat_id, "fname": filename, "uid": user_id},
            )
            if row:
                sp = row.get("storage_path") or ""
                if row.get("storage_env") == "local":
                    fp = str(StorageManager.LOCAL_STORAGE_BASE / _Path(sp))
                else:
                    fp = sp
                if os.path.isfile(fp):
                    resolved_path = fp
        except Exception:
            pass

    if not resolved_path:
        label = file_path or attachment_id or filename or "(não informado)"
        return json.dumps(
            {
                "success": False,
                "tool": "generate_temporary_public_url",
                "error": (
                    f"Arquivo não encontrado: {label}\n"
                    "Informe file_path (caminho absoluto), attachment_id (attach_XXXX) ou filename."
                ),
            }
        )

    try:
        url = build_file_url(filepath=resolved_path, ttl_seconds=ttl_seconds)
        mime = mimetypes.guess_type(resolved_path)[0] or "application/octet-stream"
        return json.dumps(
            {
                "success": True,
                "tool": "generate_temporary_public_url",
                "url": url,
                "mime_type": mime,
                "ttl_minutes": ttl_minutes,
                "message": f"URL pública gerada (expira em {ttl_minutes} min): {url}",
            },
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps(
            {"success": False, "tool": "generate_temporary_public_url", "error": str(e)}
        )

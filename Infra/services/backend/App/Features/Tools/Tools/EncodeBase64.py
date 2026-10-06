"""
encode_base64 — lê um arquivo e retorna sua representação em base64.

Resolve o arquivo em ordem de prioridade:
  1. file_path absoluto
  2. attachment_id (attach_XXXX) na tabela attachments
  3. filename no sandbox do usuário (/tmp/sandbox/{user_id}/)
  4. filename nos attachments do chat
"""

import base64
import json
import os


def execute(args: dict, chat_id: str | None, user_id: str | None) -> str:
    from pathlib import Path as _Path

    file_path = (args.get("file_path") or "").strip()
    attachment_id = (args.get("attachment_id") or "").strip()
    filename = os.path.basename((args.get("filename") or "").strip())

    resolved_path: str | None = None

    if file_path and os.path.isfile(file_path):
        resolved_path = file_path

    if not resolved_path and attachment_id and user_id:
        try:
            from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
            from App.Core.Crunch.Storage.StorageManager import StorageManager

            row = DatabaseManager.fetch_one(
                "SELECT storage_path, storage_env FROM attachments "
                "WHERE attachment_id = :aid AND user_id = :uid AND deleted_at IS NULL LIMIT 1",
                {"aid": attachment_id, "uid": user_id},
            )
            if row:
                sp = row.get("storage_path") or ""
                fp = (
                    str(StorageManager.LOCAL_STORAGE_BASE / _Path(sp))
                    if row.get("storage_env") == "local"
                    else sp
                )
                if os.path.isfile(fp):
                    resolved_path = fp
        except Exception:
            pass

    if not resolved_path and filename and user_id:
        sandbox = f"/tmp/sandbox/{user_id}/{filename}"
        if os.path.isfile(sandbox):
            resolved_path = sandbox

    if not resolved_path and filename and chat_id and user_id:
        try:
            from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
            from App.Core.Crunch.Storage.StorageManager import StorageManager

            row = DatabaseManager.fetch_one(
                "SELECT storage_path, storage_env FROM attachments "
                "WHERE chat_id = :cid AND file_name = :fname AND user_id = :uid AND deleted_at IS NULL "
                "ORDER BY created_at DESC LIMIT 1",
                {"cid": chat_id, "fname": filename, "uid": user_id},
            )
            if row:
                sp = row.get("storage_path") or ""
                fp = (
                    str(StorageManager.LOCAL_STORAGE_BASE / _Path(sp))
                    if row.get("storage_env") == "local"
                    else sp
                )
                if os.path.isfile(fp):
                    resolved_path = fp
        except Exception:
            pass

    if not resolved_path:
        label = file_path or attachment_id or filename or "(não informado)"
        return json.dumps(
            {
                "success": False,
                "tool": "encode_base64",
                "error": f"Arquivo não encontrado: {label}",
            }
        )

    try:
        size_bytes = os.path.getsize(resolved_path)
        # Aviso preventivo: base64 de arquivos muito grandes pode ser inviável
        if size_bytes > 10 * 1024 * 1024:
            return json.dumps(
                {
                    "success": False,
                    "tool": "encode_base64",
                    "error": f"Arquivo muito grande ({round(size_bytes/1024/1024, 1)} MB). Limite: 10 MB. Redimensione antes com convert_image.",
                }
            )

        with open(resolved_path, "rb") as fh:
            encoded = base64.b64encode(fh.read()).decode("ascii")

        return json.dumps(
            {
                "success": True,
                "tool": "encode_base64",
                "file_path": resolved_path,
                "filename": _Path(resolved_path).name,
                "size_bytes": size_bytes,
                "base64": encoded,
                "message": f"Base64 gerado ({round(size_bytes/1024, 1)} KB → {len(encoded)} chars). Passe em upload_ad_image(bytes=...).",
            },
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps({"success": False, "tool": "encode_base64", "error": str(e)})

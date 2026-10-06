"""
write_file — escreve conteúdo de texto direto no storage e registra como attachment
do agente, para ser injetado automaticamente na sandbox na próxima chamada terminal().

Args:
  filename : str  — nome do arquivo (ex: "relatorio.html", "script.py")
  content  : str  — conteúdo em texto puro
  encoding : str  — opcional, padrão "utf-8"
"""

import json
import mimetypes
import os
import uuid
from pathlib import Path


_MAX_BYTES = 2 * 1024 * 1024  # 2 MB


def execute(
    args: dict, chat_id: str | None, user_id: str | None, client_id: str | None = None
) -> str:
    filename = os.path.basename((args.get("filename") or "").strip())
    content: str = args.get("content") or ""
    encoding: str = (args.get("encoding") or "utf-8").strip().lower()

    if not filename:
        return json.dumps(
            {"success": False, "tool": "write_file", "error": "filename é obrigatório."}
        )
    if not chat_id or not user_id:
        return json.dumps(
            {
                "success": False,
                "tool": "write_file",
                "error": "Contexto de chat/usuário não disponível.",
            }
        )

    try:
        raw_bytes = content.encode(encoding)
    except (LookupError, UnicodeEncodeError) as e:
        return json.dumps(
            {"success": False, "tool": "write_file", "error": f"Encoding inválido: {e}"}
        )

    if len(raw_bytes) > _MAX_BYTES:
        return json.dumps(
            {
                "success": False,
                "tool": "write_file",
                "error": f"Conteúdo excede o limite de {_MAX_BYTES // 1024} KB ({len(raw_bytes) // 1024} KB recebido).",
            }
        )

    try:
        from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
        from App.Core.Crunch.Storage.StorageManager import StorageManager

        base = StorageManager.LOCAL_STORAGE_BASE
        _client_id = client_id or _resolve_client_id(user_id)

        storage_dir = base / f"client_{_client_id}" / str(chat_id) / "terminal"
        storage_dir.mkdir(parents=True, exist_ok=True)

        ext = Path(filename).suffix.lstrip(".")
        mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"

        # Upsert: se já existe attachment de agente com esse sandbox_path, sobrescreve
        existing = DatabaseManager.fetch_one(
            "SELECT attachment_id, storage_path FROM attachments "
            "WHERE chat_id = :cid AND sandbox_path = :sp AND source = 'agent' AND deleted_at IS NULL",
            {"cid": chat_id, "sp": filename},
        )

        if existing:
            attachment_id = existing["attachment_id"]
            existing_storage = existing.get("storage_path", "")
            dest = (
                base / existing_storage
                if existing_storage and not str(existing_storage).startswith("/")
                else Path(existing_storage or storage_dir / f"{attachment_id}.{ext}")
            )
            if not dest.parent.exists():
                dest = storage_dir / f"{attachment_id}.{ext}"
            dest.write_bytes(raw_bytes)
            rel_path = str(dest.relative_to(base))
            DatabaseManager.execute_query(
                "UPDATE attachments SET file_size=:sz, storage_path=:sp, file_type=:ft, file_name=:fn "
                "WHERE attachment_id=:aid",
                {
                    "sz": len(raw_bytes),
                    "sp": rel_path,
                    "ft": mime.split("/")[0],
                    "fn": filename,
                    "aid": attachment_id,
                },
            )
        else:
            attachment_id = f"attach_{uuid.uuid4().hex[:12]}"
            safe_name = f"{attachment_id}.{ext}" if ext else attachment_id
            dest = storage_dir / safe_name
            dest.write_bytes(raw_bytes)
            rel_path = str(dest.relative_to(base))
            DatabaseManager.execute_query(
                "INSERT INTO attachments "
                "(attachment_id, user_id, chat_id, file_name, extension, file_type, file_size, "
                "storage_path, storage_env, is_temp, source, sandbox_path) "
                "VALUES (:aid, :uid, :cid, :fname, :ext, :ftype, :fsize, :spath, 'local', 0, 'agent', :sp)",
                {
                    "aid": attachment_id,
                    "uid": str(user_id),
                    "cid": chat_id,
                    "fname": filename,
                    "ext": ext,
                    "ftype": mime.split("/")[0],
                    "fsize": len(raw_bytes),
                    "spath": rel_path,
                    "sp": filename,
                },
            )

        return json.dumps(
            {
                "success": True,
                "tool": "write_file",
                "attachment_id": attachment_id,
                "filename": filename,
                "size_bytes": len(raw_bytes),
                "message": f"Arquivo '{filename}' salvo. Disponível como '{filename}' na próxima chamada terminal().",
            },
            ensure_ascii=False,
        )

    except Exception as e:
        return json.dumps({"success": False, "tool": "write_file", "error": str(e)})


def _resolve_client_id(user_id: str) -> str:
    try:
        from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager

        row = DatabaseManager.fetch_one(
            "SELECT client_id FROM users WHERE user_id = :uid LIMIT 1",
            {"uid": user_id},
        )
        return str(row["client_id"]) if row else user_id
    except Exception:
        return user_id

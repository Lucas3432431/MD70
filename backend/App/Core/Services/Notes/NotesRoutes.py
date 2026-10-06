from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import text
import uuid
from typing import Optional

from App.Core.Logs import error as log_error
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Core.Services.Auth.RequestAuth import get_payload_from_request

notes_router = APIRouter(tags=["Notes"], prefix="/api/notes")


def _get_user_id(request: Request) -> str:
    payload = get_payload_from_request(request)
    return str(payload.get("user_id") or payload.get("sub", ""))


class NoteCreate(BaseModel):
    content: str
    group_id: Optional[str] = None


class NoteGroupCreate(BaseModel):
    name: str


class NoteGroupUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    emoji: Optional[str] = None


# ── Groups ────────────────────────────────────────────────────────────────────


@notes_router.get("/groups")
async def list_groups(request: Request):
    user_id = _get_user_id(request)

    def _query(session):
        rows = session.execute(
            text(
                "SELECT id, name, description, emoji, created_at FROM note_groups"
                " WHERE user_id = :uid ORDER BY created_at ASC"
            ),
            {"uid": user_id},
        ).fetchall()
        return [dict(r._mapping) for r in rows]

    return DatabaseManager.execute_transaction(_query)


@notes_router.patch("/groups/{group_id}")
async def update_group(group_id: str, payload: NoteGroupUpdate, request: Request):
    user_id = _get_user_id(request)

    updates = {}
    if payload.name is not None:
        updates["name"] = payload.name.strip() or None
    if payload.description is not None:
        updates["description"] = payload.description.strip() or None
    if payload.emoji is not None:
        updates["emoji"] = payload.emoji.strip() or None

    if not updates:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

    set_clause = ", ".join(f"{k} = :{k}" for k in updates)

    def _update(session):
        result = session.execute(
            text(
                f"UPDATE note_groups SET {set_clause}"
                " WHERE id = :id AND user_id = :uid"
            ),
            {**updates, "id": group_id, "uid": user_id},
        )
        if result.rowcount == 0:
            return None
        row = session.execute(
            text(
                "SELECT id, name, description, emoji, created_at FROM note_groups WHERE id = :id"
            ),
            {"id": group_id},
        ).first()
        return dict(row._mapping) if row else None

    result = DatabaseManager.execute_transaction(_update)
    if result is None:
        raise HTTPException(status_code=404, detail="Grupo não encontrado")
    return result


@notes_router.post("/groups")
async def create_group(payload: NoteGroupCreate, request: Request):
    user_id = _get_user_id(request)
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nome vazio")

    group_id = str(uuid.uuid4())

    def _insert(session):
        session.execute(
            text(
                "INSERT INTO note_groups (id, user_id, name) VALUES (:id, :uid, :name)"
            ),
            {"id": group_id, "uid": user_id, "name": name},
        )
        row = session.execute(
            text("SELECT id, name, created_at FROM note_groups WHERE id = :id"),
            {"id": group_id},
        ).first()
        return dict(row._mapping) if row else {"id": group_id, "name": name}

    try:
        return DatabaseManager.execute_transaction(_insert)
    except Exception as e:
        log_error(f"[NOTES] Erro ao criar grupo: {e}")
        raise HTTPException(status_code=500, detail="Erro ao salvar grupo")


@notes_router.delete("/groups/{group_id}")
async def delete_group(group_id: str, request: Request):
    user_id = _get_user_id(request)

    def _delete(session):
        result = session.execute(
            text("DELETE FROM note_groups WHERE id = :id AND user_id = :uid"),
            {"id": group_id, "uid": user_id},
        )
        return result.rowcount

    rows = DatabaseManager.execute_transaction(_delete)
    if rows == 0:
        raise HTTPException(status_code=404, detail="Grupo não encontrado")
    return {"ok": True}


# ── Notes ─────────────────────────────────────────────────────────────────────


@notes_router.get("")
async def list_notes(request: Request, group_id: Optional[str] = Query(None)):
    user_id = _get_user_id(request)

    def _query(session):
        if group_id:
            rows = session.execute(
                text(
                    "SELECT id, content, created_at, group_id FROM notes"
                    " WHERE user_id = :uid AND group_id = :gid ORDER BY created_at ASC LIMIT 500"
                ),
                {"uid": user_id, "gid": group_id},
            ).fetchall()
        else:
            rows = session.execute(
                text(
                    "SELECT id, content, created_at, group_id FROM notes"
                    " WHERE user_id = :uid AND group_id IS NULL ORDER BY created_at ASC LIMIT 500"
                ),
                {"uid": user_id},
            ).fetchall()
        return [dict(r._mapping) for r in rows]

    return DatabaseManager.execute_transaction(_query)


@notes_router.post("")
async def create_note(payload: NoteCreate, request: Request):
    user_id = _get_user_id(request)
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Conteúdo vazio")

    note_id = str(uuid.uuid4())
    group_id = payload.group_id or None

    def _insert(session):
        session.execute(
            text(
                "INSERT INTO notes (id, user_id, content, group_id)"
                " VALUES (:id, :uid, :content, :gid)"
            ),
            {"id": note_id, "uid": user_id, "content": content, "gid": group_id},
        )
        row = session.execute(
            text("SELECT id, content, created_at, group_id FROM notes WHERE id = :id"),
            {"id": note_id},
        ).first()
        return (
            dict(row._mapping)
            if row
            else {"id": note_id, "content": content, "group_id": group_id}
        )

    try:
        return DatabaseManager.execute_transaction(_insert)
    except Exception as e:
        log_error(f"[NOTES] Erro ao criar nota: {e}")
        raise HTTPException(status_code=500, detail="Erro ao salvar nota")


@notes_router.delete("/{note_id}")
async def delete_note(note_id: str, request: Request):
    user_id = _get_user_id(request)

    def _delete(session):
        result = session.execute(
            text("DELETE FROM notes WHERE id = :id AND user_id = :uid"),
            {"id": note_id, "uid": user_id},
        )
        return result.rowcount

    rows = DatabaseManager.execute_transaction(_delete)
    if rows == 0:
        raise HTTPException(status_code=404, detail="Nota não encontrada")
    return {"ok": True}

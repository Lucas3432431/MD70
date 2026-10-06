"""
Rotas de Marca — /api/brand
CRUD de identidade visual por cliente (fontes, cores, arquétipo, logo, etc.)
"""

import threading
from pathlib import Path
from typing import Any, Dict, Optional, Set
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from App.Core.Logs import debug, error as log_error
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Features.Auth import get_auth_service

brand_router = APIRouter(tags=["Brand"], prefix="/api/brand")

# Rastreia user_ids com análise ativa para evitar threads duplicadas
_active_analyses: Set[str] = set()


# ── Auth helper ──────────────────────────────────────────────────────────────


def _get_user_and_client(request: Request) -> tuple[str, str]:
    """Retorna (user_id, client_id) do token JWT. Levanta 401/404 em falha."""
    from App.Core.Services.Auth.RequestAuth import get_payload_from_request

    payload = get_payload_from_request(request)
    user_id = str(payload.get("user_id") or payload.get("sub", ""))
    client_id = DatabaseManager.execute_transaction(
        lambda s: DatabaseManager.get_client_id_by_user_id(s, user_id)
    )
    if not client_id:
        raise HTTPException(
            status_code=404, detail="Cliente não encontrado para este usuário"
        )

    return user_id, client_id


# ── Models ────────────────────────────────────────────────────────────────────


class BrandUpsertRequest(BaseModel):
    title: Optional[str] = None
    data: Dict[str, Any]


def _brand_to_dict(brand) -> dict:
    """Serializa um objeto Brand para dict de resposta."""
    return {
        "client_id": brand.client_id,
        "title": brand.title,
        "version": brand.version,
        "data": brand.data or {},
        "updated_at": brand.updated_at.isoformat() if brand.updated_at else None,
    }


# ── GET /api/brand ────────────────────────────────────────────────────────────


@brand_router.get("")
async def get_brand(request: Request):
    """Retorna os dados de marca do cliente autenticado."""
    try:
        _, client_id = _get_user_and_client(request)

        def _query(session):
            from App.Core.Crunch.TablesSQL.Models import Brand

            brand = session.query(Brand).filter(Brand.client_id == client_id).first()
            return _brand_to_dict(brand) if brand else None

        result = DatabaseManager.execute_transaction(_query)
        return {
            "success": True,
            "brand": result
            or {"client_id": client_id, "title": None, "version": 0, "data": {}},
        }

    except HTTPException:
        raise
    except Exception as e:
        log_error(f"[Brand GET] {e}")
        raise HTTPException(status_code=500, detail="Erro ao buscar dados de marca")


# ── PUT /api/brand ────────────────────────────────────────────────────────────


@brand_router.put("")
async def upsert_brand(request: Request, body: BrandUpsertRequest):
    """Cria ou atualiza os dados de marca do cliente autenticado."""
    try:
        _, client_id = _get_user_and_client(request)

        def _upsert(session):
            from App.Core.Crunch.TablesSQL.Models import Brand

            brand = session.query(Brand).filter(Brand.client_id == client_id).first()
            if brand:
                if body.title is not None:
                    brand.title = body.title
                brand.data = body.data
                brand.version = (brand.version or 1) + 1
            else:
                brand = Brand(
                    client_id=client_id, title=body.title, data=body.data, version=1
                )
                session.add(brand)
            session.flush()
            return _brand_to_dict(brand)

        result = DatabaseManager.execute_transaction(_upsert)
        debug(
            f"[Brand PUT] client={client_id} '{result['title']}' v{result['version']}"
        )
        return {"success": True, **result}

    except HTTPException:
        raise
    except Exception as e:
        log_error(f"[Brand PUT] {e}")
        raise HTTPException(status_code=500, detail="Erro ao salvar dados de marca")


# ── PATCH /api/brand ──────────────────────────────────────────────────────────


@brand_router.patch("")
async def patch_brand(request: Request, body: BrandUpsertRequest):
    """Mescla campos no objeto `data` de marca sem sobrescrever os demais."""
    try:
        _, client_id = _get_user_and_client(request)

        def _patch(session):
            from App.Core.Crunch.TablesSQL.Models import Brand

            brand = session.query(Brand).filter(Brand.client_id == client_id).first()
            if brand:
                if body.title is not None:
                    brand.title = body.title
                existing = dict(brand.data or {})
                existing.update(body.data)
                brand.data = existing
                brand.version = (brand.version or 1) + 1
            else:
                brand = Brand(
                    client_id=client_id, title=body.title, data=body.data, version=1
                )
                session.add(brand)
            session.flush()
            return _brand_to_dict(brand)

        result = DatabaseManager.execute_transaction(_patch)
        return {"success": True, **result}

    except HTTPException:
        raise
    except Exception as e:
        log_error(f"[Brand PATCH] {e}")
        raise HTTPException(status_code=500, detail="Erro ao atualizar dados de marca")


# ── DELETE /api/brand ─────────────────────────────────────────────────────────


@brand_router.delete("")
async def delete_brand(request: Request):
    """Remove todos os dados de marca do cliente autenticado."""
    try:
        _, client_id = _get_user_and_client(request)

        def _delete(session):
            from App.Core.Crunch.TablesSQL.Models import Brand

            brand = session.query(Brand).filter(Brand.client_id == client_id).first()
            if brand:
                session.delete(brand)
            return brand is not None

        deleted = DatabaseManager.execute_transaction(_delete)
        return {"success": True, "deleted": deleted}

    except HTTPException:
        raise
    except Exception as e:
        log_error(f"[Brand DELETE] {e}")
        raise HTTPException(status_code=500, detail="Erro ao remover dados de marca")


# ── POST /api/brand/analyze ───────────────────────────────────────────────────


class BrandAnalyzeRequest(BaseModel):
    url: str


def _get_or_create_brand_agent_chat(user_id: str) -> str:
    """Retorna um chat_id estável para brand analysis (usando agent_chat, igual ao OmniChannel)."""
    from sqlalchemy import text

    chat_id = f"brand_analysis_{user_id}"
    with DatabaseManager.get_session() as session:
        row = session.execute(
            text("SELECT chat_id FROM agent_chat WHERE chat_id = :cid LIMIT 1"),
            {"cid": chat_id},
        ).fetchone()
        if not row:
            session.execute(
                text(
                    "INSERT INTO agent_chat (chat_id, user_id, provider, external_id) "
                    "VALUES (:cid, :uid, :p, :eid)"
                ),
                {"cid": chat_id, "uid": user_id, "p": "brand_analysis", "eid": user_id},
            )
            session.commit()
    return chat_id


def _save_brand_agent_message(chat_id: str, sender: str, content: str):
    import uuid as _uuid
    from sqlalchemy import text

    with DatabaseManager.get_session() as session:
        session.execute(
            text(
                "INSERT INTO agent_messages (message_id, chat_id, sender, content) "
                "VALUES (:mid, :cid, :s, :cnt)"
            ),
            {"mid": str(_uuid.uuid4()), "cid": chat_id, "s": sender, "cnt": content},
        )
        session.commit()


def _run_brand_analysis(user_id: str, chat_id: str, user_message: str, url: str):
    """Roda análise de marca em background thread, igual ao OmniChannel."""
    from App.Core.Services.Common.Dependencies import COMPONENTS

    message_processor = COMPONENTS.get("message_processor")
    chat_manager = COMPONENTS.get("chat_manager")

    if not message_processor or not chat_manager:
        log_error("[Brand Analyze] MessageProcessor ou ChatManager não inicializados")
        _active_analyses.discard(user_id)
        return

    try:
        import uuid as _uuid

        session_id = chat_manager.create_session()
        chat_session = chat_manager.get_session(session_id)
        if chat_session:
            chat_session.chat_id = chat_id

        message_processor.process_message(
            job_id=str(_uuid.uuid4()),
            user_message=user_message,
            agent_id="orchestrator-global",
            chat_id=chat_id,
            user_id=user_id,
            context={"brand_analysis": True, "brand_url": url},
        )
        debug(f"[Brand Analyze] Análise concluída para user={user_id}")
        _save_brand_agent_message(chat_id, "assistant", "Análise concluída ✓")
    except Exception as e:
        log_error(f"[Brand Analyze] Erro na thread de análise: {e}")
    finally:
        _active_analyses.discard(user_id)


@brand_router.post("/analyze")
async def analyze_brand(request: Request, body: BrandAnalyzeRequest):
    """Inicia análise autônoma de marca em background (agent_chat), sem bloquear."""
    try:
        user_id, _ = _get_user_and_client(request)
        url = (body.url or "").strip()
        if not url:
            raise HTTPException(status_code=400, detail="URL obrigatória")

        if user_id in _active_analyses:
            chat_id = _get_or_create_brand_agent_chat(user_id)
            debug(f"[Brand Analyze] Análise já em andamento para user={user_id}")
            return {"chat_id": chat_id, "status": "analyzing"}

        chat_id = _get_or_create_brand_agent_chat(user_id)

        user_message = (
            f"URL: {url}\n\n"
            "Analise de forma autônoma e crie os documentos Business Canvas e Brand Identity "
            "para este site. Não faça perguntas — use web-search, terminal e as informações "
            "do site para preencher todos os campos. Detecte também os produtos e serviços "
            "disponíveis na loja usando terminal ou web-search e chame "
            "brand(action='add_products', links=[...]) com os URLs encontrados. "
            "Use brand(action='progress', step='...') para informar o usuário a cada etapa. "
            "Use brand(action='update', data={...}) para salvar dados parciais assim que detectá-los. "
            "Ao final, chame brand(action='done')."
        )
        _save_brand_agent_message(chat_id, "user", user_message)
        _active_analyses.add(user_id)

        thread = threading.Thread(
            target=_run_brand_analysis,
            args=(user_id, chat_id, user_message, url),
            daemon=True,
        )
        thread.start()
        debug(f"[Brand Analyze] Thread iniciada chat={chat_id} user={user_id}")

        return {"chat_id": chat_id, "status": "analyzing"}

    except HTTPException:
        raise
    except Exception as e:
        log_error(f"[Brand Analyze] {e}")
        raise HTTPException(status_code=500, detail="Erro ao iniciar análise de marca")


# ── GET /api/brand/analyze/activity ──────────────────────────────────────────


@brand_router.get("/analyze/activity")
async def get_analyze_activity(request: Request):
    """Retorna a última mensagem gravada no chat de análise de marca."""
    try:
        user_id, _ = _get_user_and_client(request)
        chat_id = f"brand_analysis_{user_id}"
        is_active = user_id in _active_analyses

        row = DatabaseManager.fetch_one(
            """SELECT sender, content, created_at
               FROM agent_messages
               WHERE chat_id = :cid
               ORDER BY created_at DESC
               LIMIT 1""",
            {"cid": chat_id},
        )

        last_message = None
        if row:
            content = row.get("content") or ""
            last_message = {
                "sender": row.get("sender"),
                "content": content[:300],
                "created_at": str(row.get("created_at") or ""),
            }

        return {
            "is_active": is_active,
            "last_message": last_message,
        }

    except HTTPException:
        raise
    except Exception as e:
        log_error(f"[Brand Activity] {e}")
        raise HTTPException(status_code=500, detail="Erro ao verificar atividade")


# ── GET /api/brand/analyze/status ─────────────────────────────────────────────


@brand_router.get("/analyze/status")
async def get_analyze_status(request: Request):
    """Verifica o status da análise de marca."""
    try:
        user_id, _ = _get_user_and_client(request)

        rows = DatabaseManager.fetch_all(
            """SELECT tool_type FROM documents
               WHERE user_id = :user_id
                 AND tool_type IN ('business_canvas', 'brand_communication')""",
            {"user_id": user_id},
        )
        types = {r.get("tool_type") for r in (rows or [])}

        if "business_canvas" in types and "brand_communication" in types:
            return {"status": "done", "types_found": list(types)}

        # Sem documentos — só está "analyzing" se há thread ativa
        if user_id in _active_analyses:
            return {"status": "analyzing", "types_found": list(types)}

        return {"status": "idle", "types_found": list(types)}

    except HTTPException:
        raise
    except Exception as e:
        log_error(f"[Brand Analyze Status] {e}")
        raise HTTPException(status_code=500, detail="Erro ao verificar status")


# ── GET /api/brand/documents ──────────────────────────────────────────────────


@brand_router.get("/documents")
async def get_brand_documents(request: Request):
    """Retorna os documentos business_canvas e brand_communication mais recentes do usuário."""
    try:
        user_id, _ = _get_user_and_client(request)

        rows = DatabaseManager.fetch_all(
            """SELECT document_id, title, content, tool_type, created_at
               FROM documents
               WHERE user_id = :user_id
                 AND tool_type IN ('business_canvas', 'brand_communication')
               ORDER BY created_at DESC""",
            {"user_id": user_id},
        )

        business_canvas = None
        brand_communication = None
        for row in rows or []:
            t = row.get("tool_type")
            if t == "business_canvas" and not business_canvas:
                business_canvas = dict(row)
            elif t == "brand_communication" and not brand_communication:
                brand_communication = dict(row)
            if business_canvas and brand_communication:
                break

        return {
            "success": True,
            "business_canvas": business_canvas,
            "brand_communication": brand_communication,
        }

    except HTTPException:
        raise
    except Exception as e:
        log_error(f"[Brand Documents] {e}")
        raise HTTPException(
            status_code=500, detail="Erro ao buscar documentos de marca"
        )


# ── GET /api/brand/fonts ──────────────────────────────────────────────────────


@brand_router.get("/fonts")
async def get_fonts():
    """Retorna a lista de fontes disponíveis no editor criativo."""
    try:
        ds_path = (
            Path(__file__).parent
            / "../../../../services/frontend/src/_shared/core/config/designSystem.json"
        )
        import json as _json

        data = _json.loads(ds_path.read_text(encoding="utf-8"))
        return {"success": True, "fonts": data.get("fonts", [])}
    except Exception:
        # Fallback estático se o arquivo não for encontrado
        return {
            "success": True,
            "fonts": ["Inter", "Roboto", "Poppins", "Montserrat", "Playfair Display"],
        }

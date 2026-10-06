"""
_brand_tool.py — Tool `brand`

Permite ao agente salvar dados de marca progressivamente e notificar o
frontend em tempo real via WebSocket (chat_watcher).

Ações disponíveis:
  update       — mescla campos no objeto Brand.data e transmite via WS
  add_products — adiciona links de produtos detectados e transmite via WS
  progress     — envia mensagem de progresso ao frontend (sem salvar no DB)
  done         — sinaliza conclusão ao frontend
"""

import asyncio
import json
import logging
from typing import Optional

_log = logging.getLogger(__name__)


# ── WS broadcast helper (thread-safe) ────────────────────────────────────────


def _broadcast(chat_id: str, data: dict) -> None:
    """Envia dados ao frontend via chat_watcher a partir de qualquer thread."""
    try:
        from App.Core.Services.Chat.ChatRoutes import chat_watcher, _main_loop  # noqa

        loop: Optional[asyncio.AbstractEventLoop] = _main_loop
        if loop and not loop.is_closed():
            asyncio.run_coroutine_threadsafe(
                chat_watcher.broadcast(chat_id, data), loop
            )
    except Exception as e:
        _log.warning(f"[brand_tool] broadcast error: {e}")


# ── DB helpers ────────────────────────────────────────────────────────────────


def _get_client_id(user_id: str) -> Optional[str]:
    from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager

    return DatabaseManager.execute_transaction(
        lambda s: DatabaseManager.get_client_id_by_user_id(s, user_id)
    )


def _upsert_brand_data(client_id: str, patch: dict) -> None:
    """Mescla `patch` em Brand.data sem sobrescrever outros campos."""
    from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager

    def _patch(session):
        from App.Core.Crunch.TablesSQL.Models import Brand

        brand = session.query(Brand).filter(Brand.client_id == client_id).first()
        if brand:
            existing = dict(brand.data or {})
            existing.update(patch)
            brand.data = existing
            brand.version = (brand.version or 1) + 1
        else:
            brand = Brand(client_id=client_id, data=patch, version=1)
            session.add(brand)
        session.flush()

    DatabaseManager.execute_transaction(_patch)


# ── Main executor ─────────────────────────────────────────────────────────────


def execute_brand(
    args: dict,
    chat_id: Optional[str],
    user_id: Optional[str],
    client_id: Optional[str] = None,
) -> str:
    action = (args.get("action") or "update").strip().lower()

    if not client_id and user_id:
        client_id = _get_client_id(user_id)

    if action == "progress":
        step = args.get("step") or args.get("message") or ""
        if chat_id:
            _broadcast(chat_id, {"type": "brand_progress", "step": step})
        return json.dumps({"success": True, "action": "progress", "step": step})

    if action == "done":
        if chat_id:
            _broadcast(chat_id, {"type": "brand_done"})
        return json.dumps({"success": True, "action": "done"})

    if action == "update":
        data_patch = args.get("data") or {}
        if not isinstance(data_patch, dict):
            return json.dumps({"success": False, "error": "'data' deve ser um objeto"})

        if not client_id:
            return json.dumps({"success": False, "error": "client_id não encontrado"})

        try:
            _upsert_brand_data(client_id, data_patch)
        except Exception as e:
            _log.error(f"[brand_tool] DB error on update: {e}")
            return json.dumps({"success": False, "error": str(e)})

        if chat_id:
            _broadcast(chat_id, {"type": "brand_update", "data": data_patch})

        return json.dumps(
            {
                "success": True,
                "action": "update",
                "saved_fields": list(data_patch.keys()),
            }
        )

    if action == "add_products":
        links = args.get("links") or args.get("product_links") or []
        if isinstance(links, str):
            links = [l.strip() for l in links.split(",") if l.strip()]

        if not client_id:
            return json.dumps({"success": False, "error": "client_id não encontrado"})

        try:
            # Merge into brand_communication product_links field
            from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager

            def _patch_links(session):
                from App.Core.Crunch.TablesSQL.Models import Brand

                brand = (
                    session.query(Brand).filter(Brand.client_id == client_id).first()
                )
                if brand:
                    existing = dict(brand.data or {})
                    bc = dict(existing.get("brand_communication", {}) or {})
                    existing_links = bc.get("product_links") or []
                    if not isinstance(existing_links, list):
                        existing_links = []
                    merged = list(dict.fromkeys(existing_links + links))
                    bc["product_links"] = merged
                    existing["brand_communication"] = bc
                    brand.data = existing
                    brand.version = (brand.version or 1) + 1
                else:
                    brand = Brand(
                        client_id=client_id,
                        data={"brand_communication": {"product_links": links}},
                        version=1,
                    )
                    session.add(brand)
                session.flush()
                return brand.data.get("brand_communication", {}).get(
                    "product_links", []
                )

            merged_links = DatabaseManager.execute_transaction(_patch_links)
        except Exception as e:
            _log.error(f"[brand_tool] DB error on add_products: {e}")
            return json.dumps({"success": False, "error": str(e)})

        if chat_id:
            _broadcast(chat_id, {"type": "brand_products", "links": merged_links})

        return json.dumps(
            {"success": True, "action": "add_products", "total": len(merged_links)}
        )

    return json.dumps(
        {
            "success": False,
            "error": f"Ação desconhecida: '{action}'. Use: update, add_products, progress, done",
        }
    )

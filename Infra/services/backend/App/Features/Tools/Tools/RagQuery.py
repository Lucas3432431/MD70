"""
Tool: rag_query
Busca semântica nos documentos indexados do usuário (Google Drive, Notion, etc.).
Sincroniza automaticamente todos os providers conectados antes de buscar.
"""

import asyncio
import concurrent.futures
import json
from typing import Any, Dict

from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Core.Logs import error, info
from App.Core.Services.VectorSearch.VectorSearchService import search

_SUPPORTED_PROVIDERS = {"google-drive", "notion"}


def _connected_integrations(user_id: str) -> list[dict]:
    """Retorna lista de {provider, client_id} para o usuário via JOIN users→integrations_mcp."""
    rows = DatabaseManager.fetch_all(
        """
        SELECT im.provider, im.client_id
        FROM integrations_mcp im
        JOIN users u ON u.client_id = im.client_id
        WHERE u.user_id = :uid AND im.is_active = 1
        """,
        {"uid": user_id},
    )
    return [r for r in (rows or []) if r["provider"] in _SUPPORTED_PROVIDERS]


def _run_async(coro):
    """Executa coroutine async a partir de contexto síncrono via thread isolada."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, coro)
        return future.result(timeout=120)


def execute_rag_query(args: Dict[str, Any], user_id: str) -> str:
    query = (args.get("query") or "").strip()
    if not query:
        return json.dumps(
            {"success": False, "error": "Campo 'query' obrigatório."},
            ensure_ascii=False,
        )

    sources = args.get("sources") or None
    if isinstance(sources, str):
        sources = [s.strip() for s in sources.split(",") if s.strip()]

    top_k = min(int(args.get("top_k", 5)), 20)

    # ── Sync automático antes de buscar ──────────────────────────────────────
    from App.Core.Services.VectorSearch.KnowledgeSyncService import sync_provider

    integrations = _connected_integrations(user_id)
    if sources:
        integrations = [i for i in integrations if i["provider"] in sources]

    for integration in integrations:
        try:
            info(f"[rag_query] sync automático: {integration['provider']}")
            _run_async(
                sync_provider(
                    client_id=integration["client_id"],
                    user_id=user_id,
                    provider=integration["provider"],
                )
            )
        except Exception as e:
            error(f"[rag_query] sync falhou ({integration['provider']}): {e}")

    # ── Busca ─────────────────────────────────────────────────────────────────
    try:
        results = search(user_id=user_id, query=query, sources=sources, top_k=top_k)
        return json.dumps(
            {
                "success": True,
                "query": query,
                "results": results,
                "total": len(results),
            },
            ensure_ascii=False,
            default=str,
        )
    except Exception as e:
        error(f"[TOOL:rag_query] error: {e}")
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)

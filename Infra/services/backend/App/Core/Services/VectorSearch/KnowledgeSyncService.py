"""
KnowledgeSyncService — indexa documentos das integrações MCP do usuário.

Fluxo por provider:
  1. mcp_manager.call_tool(client_id, "mcp__<provider>__list", {}) → lista arquivos
  2. mcp_manager.call_tool(client_id, "mcp__<provider>__read", {"file_id": ...}) → conteúdo
  3. Chunka o texto
  4. Embeda via OpenAI text-embedding-3-small
  5. Salva em knowledge_sources / knowledge_objects / knowledge_chunks

O refresh de OAuth token é transparente — gerenciado pelo MCPClientManager.
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from App.Core.Logs import debug, error, info
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager

# Máximo de caracteres por chunk
_CHUNK_SIZE = 1500
# Sobreposição entre chunks consecutivos (caracteres)
_CHUNK_OVERLAP = 200

# Providers que suportam indexação via MCP
_SUPPORTED_PROVIDERS = {
    "google-drive": {
        "list_tool": "mcp__google-drive__list",
        "read_tool": "mcp__google-drive__read",
        "id_field": "file_id",
    },
    "notion": {
        "list_tool": "mcp__notion__list_pages",
        "read_tool": "mcp__notion__read_page",
        "id_field": "page_id",
    },
}


def _chunk_text(text: str) -> List[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = start + _CHUNK_SIZE
        chunks.append(text[start:end])
        start += _CHUNK_SIZE - _CHUNK_OVERLAP
    return [c for c in chunks if c.strip()]


def _embed(text: str, user_id: str) -> Optional[List[float]]:
    try:
        from App.Core.Services.VectorSearch.VectorSearchService import embed

        return embed(text, user_id=user_id)
    except Exception as e:
        error(f"[KnowledgeSync] embed error: {e}")
        return None


def _parse_files_from_mcp_content(provider: str, content: str) -> List[Dict[str, Any]]:
    """
    Parseia a resposta de texto do MCP list em lista de dicts com id e nome.
    O google-drive retorna linhas: "nome (mimeType) — id: <id>"
    O notion retorna linhas: "<title> — id: <id>"
    """
    files = []
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        if "— id:" in line:
            parts = line.split("— id:")
            name_part = parts[0].strip()
            file_id = parts[1].strip()
            # Remove mimeType do nome (google-drive)
            if "(" in name_part and ")" in name_part:
                name = name_part[: name_part.rfind("(")].strip()
            else:
                name = name_part
            files.append({"id": file_id, "name": name})
    return files


async def sync_provider(client_id: str, user_id: str, provider: str) -> Dict[str, Any]:
    """
    Indexa todos os documentos de um provider para o usuário.
    Retorna dict com total de objetos e chunks indexados.
    """
    from App.Features.Tools.Mcp.MCPClientManager import mcp_manager

    cfg = _SUPPORTED_PROVIDERS.get(provider)
    if not cfg:
        return {
            "success": False,
            "error": f"Provider '{provider}' não suportado para indexação.",
        }

    db = DatabaseManager()

    # Garante registro em knowledge_sources
    now = datetime.now(timezone.utc).isoformat()
    source_rows = db.fetch_all(
        "SELECT id FROM knowledge_sources WHERE user_id = :uid AND provider = :prov",
        {"uid": user_id, "prov": provider},
    )
    if source_rows:
        source_id = source_rows[0]["id"]
        db.execute(
            "UPDATE knowledge_sources SET status = 'syncing', updated_at = :now WHERE id = :id",
            {"now": now, "id": source_id},
        )
    else:
        source_id = str(uuid.uuid4())
        db.execute(
            """
            INSERT INTO knowledge_sources (id, user_id, provider, status, created_at, updated_at)
            VALUES (:id, :uid, :prov, 'syncing', :now, :now)
            """,
            {"id": source_id, "uid": user_id, "prov": provider, "now": now},
        )

    try:
        # 1. Listar arquivos via MCP
        list_result = await mcp_manager.call_tool(client_id, cfg["list_tool"], {})
        if not list_result.get("success"):
            raise RuntimeError(list_result.get("error", "Falha ao listar arquivos"))

        files = _parse_files_from_mcp_content(provider, list_result.get("content", ""))
        info(f"[KnowledgeSync] {provider}: {len(files)} arquivo(s) encontrado(s)")

        total_chunks = 0
        for f in files:
            file_id = f["id"]
            file_name = f["name"]

            # 2. Ler conteúdo via MCP
            read_result = await mcp_manager.call_tool(
                client_id, cfg["read_tool"], {cfg["id_field"]: file_id}
            )
            if not read_result.get("success"):
                error(
                    f"[KnowledgeSync] Falha ao ler {file_name}: {read_result.get('error')}"
                )
                continue

            content = read_result.get("content", "").strip()
            if not content:
                continue

            # Garante registro em knowledge_objects
            obj_rows = db.fetch_all(
                "SELECT id FROM knowledge_objects WHERE source_id = :sid AND external_id = :eid",
                {"sid": source_id, "eid": file_id},
            )
            if obj_rows:
                obj_id = obj_rows[0]["id"]
                db.execute(
                    "UPDATE knowledge_objects SET last_indexed_at = :now WHERE id = :id",
                    {"now": now, "id": obj_id},
                )
                # Remove chunks antigos para reindexar
                db.execute(
                    "DELETE FROM knowledge_chunks WHERE object_id = :oid",
                    {"oid": obj_id},
                )
            else:
                obj_id = str(uuid.uuid4())
                db.execute(
                    """
                    INSERT INTO knowledge_objects
                        (id, source_id, user_id, external_id, file_name, last_indexed_at, created_at)
                    VALUES (:id, :sid, :uid, :eid, :fname, :now, :now)
                    """,
                    {
                        "id": obj_id,
                        "sid": source_id,
                        "uid": user_id,
                        "eid": file_id,
                        "fname": file_name,
                        "now": now,
                    },
                )

            # 3. Chunkeia e embeda
            chunks = _chunk_text(content)
            for i, chunk_text in enumerate(chunks):
                embedding = _embed(chunk_text, user_id=user_id)
                db.execute(
                    """
                    INSERT INTO knowledge_chunks
                        (id, object_id, user_id, chunk_index, content, embedding_json, token_count, created_at)
                    VALUES (:id, :oid, :uid, :idx, :content, :emb, :tokens, :now)
                    """,
                    {
                        "id": str(uuid.uuid4()),
                        "oid": obj_id,
                        "uid": user_id,
                        "idx": i,
                        "content": chunk_text,
                        "emb": json.dumps(embedding) if embedding else None,
                        "tokens": len(chunk_text.split()),
                        "now": now,
                    },
                )
                total_chunks += 1

            debug(f"[KnowledgeSync] {file_name}: {len(chunks)} chunk(s)")

        db.execute(
            "UPDATE knowledge_sources SET status = 'active', last_synced_at = :now, updated_at = :now WHERE id = :id",
            {"now": now, "id": source_id},
        )
        return {
            "success": True,
            "provider": provider,
            "objects_indexed": len(files),
            "chunks_indexed": total_chunks,
        }

    except Exception as e:
        error(f"[KnowledgeSync] sync error ({provider}): {e}")
        db.execute(
            "UPDATE knowledge_sources SET status = 'error', error_message = :msg, updated_at = :now WHERE id = :id",
            {"msg": str(e), "now": now, "id": source_id},
        )
        return {"success": False, "error": str(e)}

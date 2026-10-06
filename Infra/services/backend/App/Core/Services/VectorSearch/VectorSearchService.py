import json
import math
from typing import Any, Dict, List, Optional

from App.Core.Logs import error
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Core.Settings.Settings import get_openai_api_key


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _get_openai_client():
    from openai import OpenAI

    return OpenAI(api_key=get_openai_api_key())


def embed(text: str, user_id: str) -> List[float]:
    """Gera embedding via OpenAI e debita créditos do usuário."""
    from App.Features.Llm.LLMClient import OpenAIClient

    client = OpenAIClient(api_key=get_openai_api_key())
    return client.embed(text, user_id=user_id)


def search(
    user_id: str,
    query: str,
    sources: Optional[List[str]] = None,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    try:
        query_embedding = embed(query, user_id=user_id)
    except Exception as e:
        error(f"[VectorSearch] embed error: {e}")
        raise

    try:
        db = DatabaseManager()
        params: Dict[str, Any] = {"user_id": user_id}
        source_filter = ""
        if sources:
            placeholders = ", ".join(f":src{i}" for i in range(len(sources)))
            source_filter = f"AND ks.provider IN ({placeholders})"
            for i, s in enumerate(sources):
                params[f"src{i}"] = s

        rows = db.fetch_all(
            f"""
            SELECT kc.id, kc.content, kc.embedding_json,
                   ko.file_name, ko.file_path, ko.source_url,
                   ks.provider AS file_source
            FROM knowledge_chunks kc
            JOIN knowledge_objects ko ON ko.id = kc.object_id
            JOIN knowledge_sources ks ON ks.id = ko.source_id
            WHERE kc.user_id = :user_id
              AND kc.embedding_json IS NOT NULL
              {source_filter}
            """,
            params,
        )
    except Exception as e:
        error(f"[VectorSearch] db fetch error: {e}")
        raise

    scored = []
    for row in rows or []:
        try:
            emb = json.loads(row["embedding_json"])
            score = _cosine_similarity(query_embedding, emb)
        except Exception:
            continue
        scored.append(
            {
                "score": score,
                "content": row["content"],
                "file_name": row["file_name"],
                "file_path": row["file_path"],
                "source_url": row["source_url"],
                "file_source": row["file_source"],
            }
        )

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]

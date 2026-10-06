"""
RedisCache — thin wrapper over Redis DB 1 used exclusively for HTTP response caching.
DB 0 is reserved for queues/sessions (MultiQueueManager).
"""

import json
import hashlib
from typing import Any, Optional

import redis as _redis

from App.Core.Logs import debug, warning, error as log_error

_PREFIX = "cache:"
_client: Optional[_redis.Redis] = None


def _reset_client() -> None:
    global _client
    _client = None


def _get_client() -> Optional[_redis.Redis]:
    global _client
    if _client is not None:
        return _client
    try:
        from App.Core.Settings.Settings import load_config

        cfg = load_config()
        redis_url = cfg.get("redis_url", "")
        if not redis_url:
            return None
        candidate = _redis.Redis.from_url(
            redis_url,
            db=1,
            decode_responses=True,
            socket_timeout=3,
            socket_connect_timeout=2,
        )
        candidate.ping()
        _client = candidate
        debug("[RedisCache] Conectado ao Redis DB 1")
        return _client
    except Exception as exc:
        log_error(f"[RedisCache] Falha ao conectar: {exc}")
        return None


def cache_get(key: str) -> Optional[Any]:
    """Retorna o valor desserializado ou None em cache miss / erro."""
    try:
        client = _get_client()
        if not client:
            return None
        raw = client.get(_PREFIX + key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as exc:
        debug(f"[RedisCache] get '{key}' falhou: {exc}")
        _reset_client()
        return None


def cache_set(key: str, value: Any, ttl: int) -> bool:
    """Serializa e armazena value com TTL em segundos. Retorna True em sucesso."""
    try:
        client = _get_client()
        if not client:
            return False
        try:
            payload = json.dumps(value, default=str)
        except Exception as ser_exc:
            log_error(f"[RedisCache] serialização falhou para '{key}': {ser_exc}")
            return False
        client.setex(_PREFIX + key, ttl, payload)
        return True
    except Exception as exc:
        log_error(f"[RedisCache] set '{key}' falhou: {exc}")
        _reset_client()
        return False


def cache_delete(key: str) -> None:
    """Remove uma chave do cache. Em falha, reseta o client e tenta uma vez mais."""
    try:
        client = _get_client()
        if client:
            client.delete(_PREFIX + key)
    except Exception as exc:
        warning(
            f"[RedisCache] delete '{key}' falhou — reconectando e tentando novamente: {exc}"
        )
        _reset_client()
        try:
            client = _get_client()
            if client:
                client.delete(_PREFIX + key)
        except Exception as exc2:
            warning(
                f"[RedisCache] delete '{key}' falhou após reconexão — cache pode estar stale: {exc2}"
            )


def cache_flush_all() -> int:
    """Deletes all cache: keys from DB 1. Returns number of keys deleted."""
    try:
        client = _get_client()
        if not client:
            return 0
        keys = client.keys(_PREFIX + "*")
        if keys:
            deleted = client.delete(*keys)
            debug(f"[RedisCache] 🗑️ Flush: {deleted} chaves removidas")
            return deleted
        return 0
    except Exception as exc:
        warning(f"[RedisCache] flush_all falhou: {exc}")
        _reset_client()
        return 0


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:24]

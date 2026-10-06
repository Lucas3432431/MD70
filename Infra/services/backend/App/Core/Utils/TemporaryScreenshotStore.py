"""
TemporaryScreenshotStore - URLs temporárias para screenshots via API.
Usa database para persistência entre processos + cache LRU para performance.
TTL de 30 minutos. Arquivos salvos localmente em /tmp/prox_screenshots/.
"""

import time
import uuid
import os
import tempfile
from pathlib import Path
from typing import Optional, Tuple
from functools import lru_cache
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Core.Crunch.TablesSQL.Models import TempURL

SCREENSHOTS_DIR = Path(tempfile.gettempdir()) / "prox_screenshots"
TTL_SECONDS = 1800  # 30 minutos

# Criar diretório se não existir
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)


def generate(screenshot_bytes: bytes, url: str) -> Optional[Tuple[str, str]]:
    """
    Armazena screenshot em arquivo temporário e salva no database.
    Retorna (token, token) — ambos o token — para compatibilidade com crawler.

    Args:
        screenshot_bytes: Bytes da imagem PNG
        url: URL de origem (para referência)

    Returns:
        Tuple (token, token) ou None se falhar
    """
    try:
        token = str(uuid.uuid4())
        filename = f"{token}.png"
        filepath = SCREENSHOTS_DIR / filename

        # Salvar arquivo localmente
        with open(filepath, "wb") as f:
            f.write(screenshot_bytes)

        # Salvar no database para persistência entre processos
        expires_at = time.time() + TTL_SECONDS

        def _save_temp_url(session):
            temp_url = TempURL(
                token=token,
                filepath=str(filepath),
                origin_url=url,
                expires_at=expires_at,
            )
            session.add(temp_url)
            session.flush()

        DatabaseManager.execute_transaction(_save_temp_url)

        return (token, token)

    except Exception as e:
        return None


@lru_cache(maxsize=128)
def _get_filepath_cached(token: str) -> Optional[str]:
    """
    Cache LRU para evitar queries repetidas ao database.
    TTL implícito: cache é limpo periodicamente pela função cleanup_expired.

    Args:
        token: Token do screenshot

    Returns:
        Caminho do arquivo ou None se inválido/expirado
    """
    try:
        query = """
        SELECT filepath, expires_at FROM temp_urls WHERE token = :token
        """
        result = DatabaseManager.fetch_one(query, {"token": token})

        if not result:
            return None

        # Verificar expiração
        if time.time() > float(result["expires_at"]):
            # Remover do database e limpar arquivo
            def _delete_temp_url(session):
                session.query(TempURL).filter(TempURL.token == token).delete()
                session.flush()

            DatabaseManager.execute_transaction(_delete_temp_url)

            try:
                if os.path.exists(result["filepath"]):
                    os.remove(result["filepath"])
            except:
                pass
            return None

        filepath = result["filepath"]
        return filepath

    except Exception as e:
        return None


def get_filepath(token: str) -> Optional[str]:
    """
    Valida token e retorna caminho do arquivo.
    Usa cache para performance, verifica database para persistência.

    Args:
        token: Token do screenshot

    Returns:
        Caminho do arquivo ou None se inválido/expirado
    """
    return _get_filepath_cached(token)


def cleanup_expired():
    """Remove screenshots expirados do database e disco."""
    try:
        current_time = time.time()
        query = """
        SELECT token, filepath FROM temp_urls WHERE expires_at < :current_time
        """
        expired = DatabaseManager.fetch_all(query, {"current_time": current_time})

        for entry in expired:
            # Remover arquivo
            try:
                if os.path.exists(entry["filepath"]):
                    os.remove(entry["filepath"])
            except:
                pass

            # Remover do database
            def _delete_expired(session):
                session.query(TempURL).filter(TempURL.token == entry["token"]).delete()
                session.flush()

            DatabaseManager.execute_transaction(_delete_expired)

        # Limpar cache
        _get_filepath_cached.cache_clear()

    except Exception as e:
        pass

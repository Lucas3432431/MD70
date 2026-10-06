"""
TempTokenStore - Tokens temporários para URLs públicas de arquivos.

Dois modos:
  - Attachment tokens (single-use, 2 min) — para vision/LLM interno
  - File URL tokens (multi-use, 1h padrão) — para o agente expor arquivos a APIs externas
"""

import time
import uuid
from typing import Optional

TTL_SECONDS = 120  # 2 min — attachment tokens (single-use, LLM interno)
FILE_URL_TTL_SECONDS = 3600  # 1h — file URL tokens (multi-use, APIs externas)


def generate(attachment_id: str, user_id: str) -> str:
    """Gera token temporário em temp_urls com TTL de 2 minutos."""
    from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
    from App.Core.Crunch.TablesSQL.Models import TempURL

    token = str(uuid.uuid4())
    session = DatabaseManager.get_session()
    try:
        session.add(
            TempURL(
                token=token,
                attachment_id=attachment_id,
                user_id=user_id,
                expires_at=time.time() + TTL_SECONDS,
                used=0,
            )
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    _cleanup_expired()
    return token


def validate_and_consume(token: str) -> Optional[dict]:
    """
    Valida e consome o token (single-use).
    Retorna {attachment_id, user_id} se válido, None se inválido/expirado/já usado.
    """
    from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
    from App.Core.Crunch.TablesSQL.Models import TempURL

    session = DatabaseManager.get_session()
    try:
        entry = session.query(TempURL).filter(TempURL.token == token).first()
        if not entry or not entry.attachment_id:
            return None
        if entry.used:
            return None
        if time.time() > float(entry.expires_at):
            return None

        entry.used = 1
        session.commit()
        return {"attachment_id": entry.attachment_id, "user_id": entry.user_id}
    except Exception:
        session.rollback()
        return None
    finally:
        session.close()


def validate(token: str) -> Optional[dict]:
    """Alias para compatibilidade com código existente."""
    return validate_and_consume(token)


def _cleanup_expired():
    """Remove tokens de attachment expirados de temp_urls."""
    try:
        from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
        from App.Core.Crunch.TablesSQL.Models import TempURL

        session = DatabaseManager.get_session()
        try:
            session.query(TempURL).filter(
                TempURL.expires_at < time.time(),
                TempURL.attachment_id.isnot(None),
            ).delete(synchronize_session=False)
            session.commit()
        finally:
            session.close()
    except Exception:
        pass


def build_url(attachment_id: str, user_id: str, chat_id: str) -> str:
    """Gera token e retorna URL temporária completa."""
    from App.Core.Settings.Settings import get_public_url

    public_url = get_public_url().rstrip("/")
    token = generate(attachment_id=attachment_id, user_id=user_id)
    return (
        f"{public_url}/api/chat/{chat_id}/attachment/{attachment_id}/view?token={token}"
    )


# ── File URL tokens (multi-use, para APIs externas) ───────────────────────────


def generate_file_token(filepath: str, ttl_seconds: int = FILE_URL_TTL_SECONDS) -> str:
    """
    Gera token público para um arquivo pelo path absoluto no servidor.
    Multi-use — o token pode ser consumido múltiplas vezes até expirar.
    """
    from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
    from App.Core.Crunch.TablesSQL.Models import TempURL

    token = str(uuid.uuid4())
    session = DatabaseManager.get_session()
    try:
        session.add(
            TempURL(
                token=token,
                filepath=filepath,
                expires_at=time.time() + ttl_seconds,
                used=0,
            )
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return token


def validate_file_token(token: str) -> Optional[str]:
    """
    Valida token de arquivo público. Retorna o filepath se válido.
    Não consome o token (multi-use).
    """
    from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
    from App.Core.Crunch.TablesSQL.Models import TempURL

    session = DatabaseManager.get_session()
    try:
        entry = session.query(TempURL).filter(TempURL.token == token).first()
        if not entry or not entry.filepath:
            return None
        if time.time() > float(entry.expires_at):
            return None
        return entry.filepath
    except Exception:
        return None
    finally:
        session.close()


def build_file_url(filepath: str, ttl_seconds: int = FILE_URL_TTL_SECONDS) -> str:
    """Gera token e retorna URL pública completa para um filepath."""
    from App.Core.Settings.Settings import get_public_url

    public_url = get_public_url().rstrip("/")
    token = generate_file_token(filepath=filepath, ttl_seconds=ttl_seconds)
    return f"{public_url}/api/files/temp/{token}"

"""
Serviço de autenticação de dois fatores (TOTP)
"""

import pyotp
import qrcode
import base64
import hashlib
import io
from typing import Optional, Tuple

from cryptography.fernet import Fernet

from App.Core.Logs import debug, info, warning, error
from App.Core.Settings.Settings import SECRET_KEY

APP_NAME = "MD70"


def _get_fernet() -> Fernet:
    key = hashlib.sha256(SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def _encrypt(value: str) -> str:
    return _get_fernet().encrypt(value.encode()).decode()


def _decrypt(value: str) -> str:
    return _get_fernet().decrypt(value.encode()).decode()


class TwoFactorService:
    def __init__(self, db_manager=None):
        self.db = db_manager

    def generate_setup(self, user_id: str, email: str) -> dict:
        """Gera secret TOTP e QR code para configuração. Não salva no DB ainda."""
        secret = pyotp.random_base32()
        totp = pyotp.TOTP(secret)
        auth_url = totp.provisioning_uri(name=email, issuer_name=APP_NAME)

        img = qrcode.make(auth_url)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        qr_base64 = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

        return {"secret": secret, "qr_code": qr_base64}

    def verify_code(self, code: str, plain_secret: str) -> bool:
        """Verifica código TOTP contra o secret em plaintext."""
        try:
            return pyotp.TOTP(plain_secret).verify(code, valid_window=1)
        except Exception as e:
            warning(f"[2FA] Erro ao verificar código: {e}")
            return False

    def get_status(self, user_id: str) -> bool:
        """Retorna se 2FA está habilitado para o usuário."""
        if not self.db:
            return False
        try:
            from sqlalchemy import text

            session = self.db.get_session()
            row = session.execute(
                text(
                    "SELECT two_factor_enabled FROM users WHERE user_id = :uid LIMIT 1"
                ),
                {"uid": user_id},
            ).fetchone()
            return bool(row[0]) if row else False
        except Exception as e:
            warning(f"[2FA] Erro ao verificar status: {e}")
            return False
        finally:
            if "session" in locals():
                session.close()

    def enable(self, user_id: str, plain_secret: str, code: str) -> Tuple[bool, str]:
        """Habilita 2FA após verificar o código. Persiste secret criptografado."""
        if not self.verify_code(code, plain_secret):
            return False, "Código inválido"
        if not self.db:
            return False, "Database não inicializado"
        try:
            from sqlalchemy import text

            session = self.db.get_session()
            session.execute(
                text(
                    "UPDATE users SET two_factor_enabled = 1, two_factor_secret = :sec "
                    "WHERE user_id = :uid"
                ),
                {"sec": _encrypt(plain_secret), "uid": user_id},
            )
            session.commit()
            info(f"[2FA] Habilitado para user {user_id}")
            return True, "2FA habilitado com sucesso"
        except Exception as e:
            error(f"[2FA] Erro ao habilitar: {e}")
            return False, str(e)
        finally:
            if "session" in locals():
                session.close()

    def disable(self, user_id: str, code: str) -> Tuple[bool, str]:
        """Desabilita 2FA após verificar o código atual."""
        if not self.db:
            return False, "Database não inicializado"
        try:
            from sqlalchemy import text

            session = self.db.get_session()
            row = session.execute(
                text(
                    "SELECT two_factor_secret FROM users WHERE user_id = :uid LIMIT 1"
                ),
                {"uid": user_id},
            ).fetchone()
            if not row or not row[0]:
                return False, "2FA não está configurado"

            plain_secret = _decrypt(row[0])
            if not self.verify_code(code, plain_secret):
                return False, "Código inválido"

            session.execute(
                text(
                    "UPDATE users SET two_factor_enabled = 0, two_factor_secret = NULL "
                    "WHERE user_id = :uid"
                ),
                {"uid": user_id},
            )
            session.commit()
            info(f"[2FA] Desabilitado para user {user_id}")
            return True, "2FA desabilitado"
        except Exception as e:
            error(f"[2FA] Erro ao desabilitar: {e}")
            return False, str(e)
        finally:
            if "session" in locals():
                session.close()

    def get_secret_for_login(self, user_id: str) -> Optional[str]:
        """Retorna o secret descriptografado para verificação no login."""
        if not self.db:
            return None
        try:
            from sqlalchemy import text

            session = self.db.get_session()
            row = session.execute(
                text(
                    "SELECT two_factor_secret FROM users WHERE user_id = :uid LIMIT 1"
                ),
                {"uid": user_id},
            ).fetchone()
            if not row or not row[0]:
                return None
            return _decrypt(row[0])
        except Exception as e:
            warning(f"[2FA] Erro ao buscar secret: {e}")
            return None
        finally:
            if "session" in locals():
                session.close()


_tfa_service: Optional[TwoFactorService] = None


def get_2fa_service() -> TwoFactorService:
    global _tfa_service
    if not _tfa_service or not _tfa_service.db:
        from App.Core.Crunch import get_db_manager

        _tfa_service = TwoFactorService(db_manager=get_db_manager())
    return _tfa_service

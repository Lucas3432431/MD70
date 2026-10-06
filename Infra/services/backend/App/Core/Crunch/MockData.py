# -*- coding: utf-8 -*-
"""
MockData - Inserção de dados mock para o MD70.
Cria admin@md70.com.br (admin) e investidor@md70.com.br (investor) em desenvolvimento.
"""

import bcrypt
import uuid
from sqlalchemy import text
from App.Core.Logs import info, warning, error
from App.Core.Settings import (
    DEV_ENV,
    MOCK_ADMIN_EMAIL,
    MOCK_ADMIN_PASSWORD,
    MOCK_ADMIN_TOTP_SECRET,
    MOCK_INVESTOR_EMAIL,
    MOCK_INVESTOR_PASSWORD,
)


class MockData:
    """Gerencia a inserção de dados mock para o MD70."""

    @staticmethod
    def sync(engine) -> None:
        """
        Insere usuários mock se não existirem.
        Só executa em ambiente development.
        LANÇA EXCEÇÃO se não conseguir inserir dados mock.
        """
        if not DEV_ENV:
            return

        try:
            if MOCK_ADMIN_EMAIL and MOCK_ADMIN_PASSWORD:
                MockData._ensure_user(engine, MOCK_ADMIN_EMAIL, MOCK_ADMIN_PASSWORD, "admin")
            if MOCK_INVESTOR_EMAIL and MOCK_INVESTOR_PASSWORD:
                MockData._ensure_user(engine, MOCK_INVESTOR_EMAIL, MOCK_INVESTOR_PASSWORD, "investor")
        except Exception as e:
            error_msg = f"[MOCK DATA] ✗ CRÍTICO: Falha ao inserir dados mock. Erro: {e}"
            error(error_msg)
            raise RuntimeError(error_msg) from e

    @staticmethod
    def _encrypt_totp(plain_secret: str) -> str:
        """Criptografa o TOTP secret usando a mesma chave do TwoFactorService."""
        import base64, hashlib
        from cryptography.fernet import Fernet
        from App.Core.Settings.Settings import SECRET_KEY
        key = hashlib.sha256(SECRET_KEY.encode()).digest()
        return Fernet(base64.urlsafe_b64encode(key)).encrypt(plain_secret.encode()).decode()

    @staticmethod
    def _ensure_user(engine, email: str, password: str, role: str) -> None:
        """Cria o usuário se não existir e garante o perfil de role correspondente.
        Em DEV, sempre sincroniza a senha, role e TOTP secret para as credenciais mock."""
        pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        totp_secret_enc = (
            MockData._encrypt_totp(MOCK_ADMIN_TOTP_SECRET)
            if role == "admin" and MOCK_ADMIN_TOTP_SECRET
            else None
        )
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT user_id FROM users WHERE email = :email LIMIT 1"),
                {"email": email},
            ).fetchone()

            if row:
                user_id = row[0]
                # Sempre atualiza a senha, role e TOTP secret do usuário mock em DEV
                params = {"pw": pw_hash, "role": role, "tfa": 1 if role == "admin" else 0, "uid": user_id}
                totp_col = ", two_factor_secret = :totp" if totp_secret_enc else ""
                if totp_secret_enc:
                    params["totp"] = totp_secret_enc
                conn.execute(
                    text(
                        f"UPDATE users SET password = :pw, role = :role,"
                        f" two_factor_enabled = :tfa{totp_col}"
                        f" WHERE user_id = :uid"
                    ),
                    params,
                )
                conn.commit()
                info(f"[MOCK DATA] ✓ {role} mock sincronizado: {email}")
                MockData._ensure_role_profile(engine, user_id, role)
                return

        info(f"[MOCK DATA] Criando usuário mock: {email} ({role})")

        user_id = str(uuid.uuid4())
        client_id = str(uuid.uuid4())

        MockData._run_sql(
            engine,
            text(
                "INSERT INTO clients (client_id, users_available)"
                " VALUES (:cid, 1)"
            ),
            {"cid": client_id},
            f"clients ({role})",
        )

        full_name = "Admin MD70" if role == "admin" else "Investidor MD70"
        insert_params = {
            "uid": user_id,
            "cid": client_id,
            "email": email,
            "pw": pw_hash,
            "name": full_name,
            "role": role,
            "tfa": 1 if role == "admin" else 0,
            "totp": totp_secret_enc,
        }

        MockData._run_sql(
            engine,
            text(
                "INSERT INTO users"
                " (user_id, client_id, email, password, full_name, ip_address, role,"
                "  two_factor_enabled, two_factor_secret, cookies_accepted, terms_accepted, privacy_accepted)"
                " VALUES (:uid, :cid, :email, :pw, :name, '127.0.0.1', :role,"
                "  :tfa, :totp, 1, 1, 1)"
            ),
            insert_params,
            f"users ({role})",
        )

        MockData._ensure_role_profile(engine, user_id, role)
        info(f"[MOCK DATA] ✓ {role} mock criado: {email}")

    @staticmethod
    def _ensure_role_profile(engine, user_id: str, role: str) -> None:
        """Cria ou garante entrada nas tabelas investors_users / admin_users."""
        try:
            if role == "investor":
                investor_code = user_id[:8].upper()
                with engine.connect() as conn:
                    exists = conn.execute(
                        text("SELECT 1 FROM investors_users WHERE user_id = :uid LIMIT 1"),
                        {"uid": user_id},
                    ).fetchone()
                    if not exists:
                        conn.execute(
                            text(
                                "INSERT INTO investors_users (user_id, investor_code)"
                                " VALUES (:uid, :code)"
                            ),
                            {"uid": user_id, "code": investor_code},
                        )
                        conn.commit()
            elif role == "admin":
                with engine.connect() as conn:
                    exists = conn.execute(
                        text("SELECT 1 FROM admin_users WHERE user_id = :uid LIMIT 1"),
                        {"uid": user_id},
                    ).fetchone()
                    if not exists:
                        conn.execute(
                            text(
                                "INSERT INTO admin_users (user_id, access_level, two_factor_required)"
                                " VALUES (:uid, 'super', 1)"
                            ),
                            {"uid": user_id},
                        )
                        conn.commit()
        except Exception as e:
            warning(f"[MOCK DATA] _ensure_role_profile ({role}): {e}")

    @staticmethod
    def _run_sql(engine, stmt, params: dict, description: str) -> None:
        """Executa SQL parametrizado com tratamento de erros."""
        try:
            with engine.connect() as conn:
                conn.execute(stmt, params)
                conn.commit()
        except Exception as e:
            if "UNIQUE constraint failed" not in str(e):
                warning(f"[MOCK DATA] Erro ao inserir {description}: {e}")

    @staticmethod
    def clear_mock_data(engine) -> None:
        """Remove dados mock do banco."""
        emails = [MOCK_ADMIN_EMAIL, MOCK_INVESTOR_EMAIL]
        try:
            info("[MOCK DATA] Removendo dados mock...")
            with engine.connect() as conn:
                for email in emails:
                    if not email:
                        continue
                    row = conn.execute(
                        text("SELECT client_id FROM users WHERE email = :email LIMIT 1"),
                        {"email": email},
                    ).fetchone()
                    if row:
                        conn.execute(
                            text("DELETE FROM clients WHERE client_id = :cid"),
                            {"cid": row[0]},
                        )
                conn.commit()
            info("[MOCK DATA] Dados mock removidos!")
        except Exception as e:
            error(f"[MOCK DATA] Erro ao remover: {e}")

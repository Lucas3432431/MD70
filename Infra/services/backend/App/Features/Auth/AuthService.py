"""
Serviço de autenticação - Lógica de negócio
Separa a lógica de negócio das rotas FastAPI
"""

import jwt
import bcrypt
import hashlib
import json
import requests
import sys
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from sqlalchemy import text

# Importações do Google no topo para evitar travamentos em runtime
try:
    from google.oauth2 import id_token as google_id_token
    from google.auth.transport import requests as google_requests

    GOOGLE_LIBS_INSTALLED = True
except ImportError:
    GOOGLE_LIBS_INSTALLED = False

from App.Core.Logs import debug, info, warning, error
from App.Core.Settings.Settings import (
    GLOBAL_CONFIG,
    MAX_USERS,
    SECRET_KEY,
    GOOGLE_AUTH_CLIENT_ID,
    GOOGLE_AUTH_CLIENT_SECRET,
    GOOGLE_AUTH_CALLBACK_URL,
    ENVIRONMENT,
    VITE_HTTP_PROTOCOL,
    PUBLIC_URL,
    FRONTEND_HOST,
    FRONTEND_PORT,
)


class AuthConfig:
    """Configuração de Autenticação"""

    # Token Configuration
    ACCESS_EXPIRY = 3600  # 1 hora em segundos
    REFRESH_EXPIRY = 604800  # 7 dias em segundos

    # Cookie Configuration
    COOKIE_SECURE = ENVIRONMENT == "production"
    COOKIE_SAMESITE = "Lax"

    # Environment
    ENVIRONMENT = ENVIRONMENT

    @staticmethod
    def get_google_client_id():
        """Retorna Google Client ID das configurações globais"""
        return GOOGLE_AUTH_CLIENT_ID

    @staticmethod
    def get_google_client_secret():
        """Retorna Google Client Secret das configurações globais"""
        return GOOGLE_AUTH_CLIENT_SECRET

    @staticmethod
    def get_google_callback_url():
        """Retorna Google OAuth callback URL baseada no ambiente e protocolo"""
        # Se definido explicitamente no .env, usa ele
        if GOOGLE_AUTH_CALLBACK_URL:
            return GOOGLE_AUTH_CALLBACK_URL

        # Lógica de fallback baseada no ambiente
        if ENVIRONMENT == "production":
            return "https://zera.tec.br/auth/callback"

        # Desenvolvimento
        if VITE_HTTP_PROTOCOL == "https":
            return f"{PUBLIC_URL}/auth/callback"

        # Fallback HTTP Local
        return f"http://{FRONTEND_HOST}:{FRONTEND_PORT}/auth/callback"


class AuthService:
    """Serviço centralizado de autenticação"""

    def __init__(self, db_manager=None, config=None):
        """Inicializa o serviço de autenticação

        Args:
            db_manager: DatabaseManager opcional
            config: Dict de config opcional (se omitido, usa GLOBAL_CONFIG)
        """
        self.db = db_manager
        self.config = config or GLOBAL_CONFIG
        self._setup_jwt_secret()

    def _setup_jwt_secret(self):
        """Configura a chave secreta para JWT"""
        if SECRET_KEY and len(SECRET_KEY) > 10:
            info("JWT_SECRET configurado com sucesso")
            self.jwt_secret = SECRET_KEY
        else:
            warning(
                "SECRET_KEY não configurado ou muito curto no .env, usando padrão inseguro"
            )
            self.jwt_secret = "insecure-default-secret-change-in-production"

    # ========================================================================
    # TOKEN MANAGEMENT
    # ========================================================================

    def generate_access_token(
        self, user_data: Dict[str, Any], save_to_db: bool = True
    ) -> str:
        """
        Gera JWT access token e salva no banco de dados

        Args:
            user_data: Dados do usuário
            save_to_db: Se True, salva token no banco de dados

        Returns:
            JWT token como string
        """
        try:
            import uuid

            token_id = str(uuid.uuid4())
            expires_at = datetime.utcnow() + timedelta(seconds=AuthConfig.ACCESS_EXPIRY)

            payload = {
                "token_id": token_id,
                "user_id": user_data.get("user_id"),
                "email": user_data.get("email"),
                "client_id": user_data.get("client_id"),
                "role": user_data.get("role", "member"),
                "full_name": user_data.get("full_name"),
                "company_code": user_data.get("company_code"),
                "iat": datetime.utcnow(),
                "exp": expires_at,
            }

            token = jwt.encode(payload, self.jwt_secret, algorithm="HS256")

            # Salvar token no banco de dados
            if save_to_db and self.db:
                try:
                    session = self.db.get_session()
                    token_hash = hashlib.sha256(token.encode()).hexdigest()
                    self.db.save_access_token(
                        session=session,
                        token_id=token_id,
                        user_id=user_data.get("user_id"),
                        client_id=user_data.get("client_id"),
                        token_hash=token_hash,
                        expires_at=expires_at,
                    )
                    debug(f"Access token saved to DB: {token_id}")
                except Exception as e:
                    warning(f"Erro ao salvar access token no DB: {e}")
                finally:
                    if "session" in locals():
                        session.close()

            return token
        except Exception as e:
            error(f"Erro ao gerar access token: {e}")
            raise

    def generate_refresh_token(
        self, user_data: Dict[str, Any], save_to_db: bool = True
    ) -> Dict[str, str]:
        """
        Gera refresh token e salva no banco de dados

        Args:
            user_data: Dados do usuário
            save_to_db: Se True, salva token no banco de dados

        Returns:
            Dict com token_id e token
        """
        try:
            import uuid

            token_id = str(uuid.uuid4())
            expires_at = datetime.utcnow() + timedelta(
                seconds=AuthConfig.REFRESH_EXPIRY
            )

            payload = {
                "token_id": token_id,
                "user_id": user_data.get("user_id"),
                "client_id": user_data.get("client_id"),
                "iat": datetime.utcnow(),
                "exp": expires_at,
            }

            token = jwt.encode(payload, self.jwt_secret, algorithm="HS256")

            # Salvar token no banco de dados
            if save_to_db and self.db:
                try:
                    session = self.db.get_session()
                    token_hash = hashlib.sha256(token.encode()).hexdigest()
                    self.db.save_refresh_token(
                        session=session,
                        token_id=token_id,
                        user_id=user_data.get("user_id"),
                        client_id=user_data.get("client_id"),
                        token_hash=token_hash,
                        expires_at=expires_at,
                    )
                    debug(f"Refresh token saved to DB: {token_id}")
                except Exception as e:
                    warning(f"Erro ao salvar refresh token no DB: {e}")
                finally:
                    if "session" in locals():
                        session.close()

            return {"token_id": token_id, "token": token}
        except Exception as e:
            error(f"Erro ao gerar refresh token: {e}")
            raise

    def verify_token(
        self,
        token: str,
        check_db: bool = True,
        token_type: str = "access",
        fingerprint_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Verifica e decodifica um JWT token
        """
        try:
            payload = jwt.decode(token, self.jwt_secret, algorithms=["HS256"])

            if check_db and self.db:
                try:
                    session = self.db.get_session()
                    token_id = payload.get("token_id")

                    if token_type == "refresh":
                        token_record = self.db.get_refresh_token(session, token_id)
                    else:
                        token_record = self.db.get_access_token(session, token_id)

                    if not token_record:
                        warning(
                            f"Token ({token_type}) not found in DB or revoked: {token_id}"
                        )
                        return None
                except Exception as e:
                    warning(f"Erro ao verificar token no DB: {e}")
                finally:
                    if "session" in locals():
                        session.close()

            return payload
        except jwt.ExpiredSignatureError:
            warning("Token expirado")
            return None
        except jwt.InvalidTokenError as e:
            warning(f"Token inválido: {e}")
            return None

    # ========================================================================
    # 2FA PENDING TOKEN
    # ========================================================================

    def generate_pending_2fa_token(self, user_id: str) -> str:
        """Gera token temporário de 5 min exclusivo para o fluxo de 2FA."""
        import uuid

        payload = {
            "type": "2fa_pending",
            "user_id": user_id,
            "jti": str(uuid.uuid4()),
            "iat": datetime.utcnow(),
            "exp": datetime.utcnow() + timedelta(minutes=5),
        }
        return jwt.encode(payload, self.jwt_secret, algorithm="HS256")

    def verify_pending_2fa_token(self, token: str) -> Optional[str]:
        """Verifica pending token e retorna user_id, ou None se inválido."""
        try:
            payload = jwt.decode(token, self.jwt_secret, algorithms=["HS256"])
            if payload.get("type") != "2fa_pending":
                return None
            return str(payload.get("user_id"))
        except Exception:
            return None

    def hash_password(self, password: str) -> str:
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    def verify_password(self, password: str, password_hash: str) -> bool:
        try:
            return bcrypt.checkpw(
                password.encode("utf-8"), password_hash.encode("utf-8")
            )
        except Exception as e:
            error(f"Erro ao verificar senha: {e}")
            return False

    # ========================================================================
    # USER AUTHENTICATION
    # ========================================================================

    def authenticate_user(
        self,
        email: str,
        password: str,
        fingerprint_id: str,
        fingerprint_components: Dict[str, Any] | str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> tuple[bool, Optional[Dict], str]:
        """
        Autentica um usuário por email, senha e fingerprint
        """
        try:
            if not self.db:
                return False, None, "Database não inicializado"

            session = self.db.get_session()
            stmt = text("SELECT * FROM users WHERE email = :email LIMIT 1")
            result = session.execute(stmt, {"email": email}).fetchone()

            if not result:
                # Prevenção de Timing Attack: Sempre validar um hash dummy para manter tempo de resposta constante
                bcrypt.checkpw(
                    password.encode("utf-8"),
                    b"$2b$12$DummyHashForTimingAttackDetectionAvoidanceOnly",
                )
                warning(f"Usuário não encontrado: {email}")
                return False, None, "Usuário ou senha inválidos"

            result_dict = (
                dict(result._mapping) if hasattr(result, "_mapping") else dict(result)
            )

            if not self.verify_password(password, result_dict.get("password", "")):
                warning(f"Senha incorreta para: {email}")
                return False, None, "Usuário ou senha inválidos"

            user_data = {
                "user_id": result_dict.get("user_id"),
                "email": result_dict.get("email"),
                "full_name": result_dict.get("full_name"),
                "role": result_dict.get("role", "member"),
                "client_id": result_dict.get("client_id"),
                "status": result_dict.get("status"),
            }

            try:
                from datetime import datetime
                import uuid as uuid_lib

                session.execute(
                    text(
                        "INSERT OR IGNORE INTO devices (fingerprint_id, user_id, authorized, created_at) VALUES (:fp, :uid, 0, :now)"
                    ),
                    {
                        "fp": fingerprint_id,
                        "uid": user_data["user_id"],
                        "now": datetime.utcnow(),
                    },
                )

                fp_components_str = (
                    json.dumps(fingerprint_components)
                    if isinstance(fingerprint_components, dict)
                    else fingerprint_components
                )

                session.execute(
                    text(
                        "INSERT INTO auth_logs (auth_id, user_id, fingerprint_id, fingerprint_components, login_at, is_successful, created_at) VALUES (:aid, :uid, :fp, :fpc, :now, 1, :now)"
                    ),
                    {
                        "aid": str(uuid_lib.uuid4()),
                        "uid": user_data["user_id"],
                        "fp": fingerprint_id,
                        "fpc": fp_components_str,
                        "now": datetime.utcnow(),
                    },
                )
                session.commit()
            except Exception as e:
                warning(f"Erro ao registrar login no histórico: {e}")

            info(f"Usuário autenticado: {email}")
            return True, user_data, None

        except Exception as e:
            error(f"Erro ao autenticar usuário: {e}")
            return False, None, str(e)
        finally:
            if "session" in locals():
                session.close()

    # ========================================================================
    # USER REGISTRATION
    # ========================================================================

    def register_user(
        self,
        email: str,
        password: str,
        fingerprint_id: str,
        fingerprint_components: Dict[str, Any] | str,
        ip_address: Optional[str] = None,
    ) -> tuple[bool, Optional[Dict], str]:
        """
        Registra um novo usuário
        """
        try:
            if not self.db:
                return False, None, "Database não inicializado"

            session = self.db.get_session()
            from sqlalchemy import text
            from datetime import datetime

            from App.Features.Credits.PlanManager import get_plan_manager

            existing_user = session.execute(
                text("SELECT user_id FROM users WHERE email = :email"), {"email": email}
            ).fetchone()

            if existing_user:
                return False, None, "email_exists"

            # Verificar limite de MAX_USERS
            max_users = MAX_USERS

            plan_manager = get_plan_manager()
            plans_by_type = plan_manager.get_active_plans()

            paid_plan_ids = [
                plan.get("plan_id")
                for plan_type, plan in plans_by_type.items()
                if plan_type != "trial"
            ]

            if paid_plan_ids:
                paid_plan_ids_str = ",".join([f"'{pid}'" for pid in paid_plan_ids])
                result = session.execute(
                    text(
                        f"SELECT COUNT(DISTINCT u.user_id) as total FROM users u JOIN clients c ON u.client_id = c.client_id WHERE c.plan_id IN ({paid_plan_ids_str})"
                    )
                ).fetchone()
                paid_users = result[0] or 0
            else:
                paid_users = 0

            if paid_users >= max_users:
                warning(f"Signup bloqueado: limite atingido ({paid_users}/{max_users})")
                try:
                    session.execute(
                        text(
                            "INSERT INTO waitlist (email, fingerprint_id, status) VALUES (:email, :fp, 'pending') ON CONFLICT(email) DO NOTHING"
                        ),
                        {"email": email, "fp": fingerprint_id},
                    )
                    session.commit()
                except:
                    pass
                return False, None, "max_users_reached"

            # Criar novo usuário
            result = session.execute(
                text("SELECT MAX(CAST(client_id AS INTEGER)) as max_id FROM clients")
            ).fetchone()
            next_client_id = str((result[0] or 0) + 1)

            free_plan = plans_by_type.get("free")
            if not free_plan:
                return False, None, "Plano Free não disponível"

            self.db.create_client(
                session,
                {
                    "client_id": next_client_id,
                    "plan_id": free_plan.get("plan_id"),
                    "started_at": datetime.utcnow(),
                    "finishes_at": None,
                    "users_available": 1,
                },
            )

            result = session.execute(
                text("SELECT MAX(CAST(user_id AS INTEGER)) as max_id FROM users")
            ).fetchone()
            next_user_id = str((result[0] or 0) + 1)

            hashed_password = bcrypt.hashpw(
                password.encode("utf-8"), bcrypt.gensalt()
            ).decode("utf-8")

            user = self.db.create_user(
                session,
                {
                    "user_id": next_user_id,
                    "client_id": next_client_id,
                    "email": email,
                    "password": hashed_password,
                    "full_name": "new_user",
                    "ip_address": ip_address,
                    "fingerprint_id": fingerprint_id,
                },
            )

            info(f"SignUp bem-sucedido: {email}")

            INITIAL_FREE_CREDITS = 10
            _credits_ok = False
            try:
                from App.Features.Credits.CreditsManager import CreditsManager

                _credits_ok = CreditsManager.distribute_plan_credits(
                    next_user_id, free_plan.get("plan_id")
                )
            except Exception as _ce:
                warning(
                    f"[AUTH] distribute_plan_credits lançou exceção para user_id={next_user_id}: {_ce}"
                )

            if not _credits_ok:
                warning(
                    f"[AUTH] Distribuição de créditos falhou — aplicando {INITIAL_FREE_CREDITS} créditos iniciais diretos para user_id={next_user_id}"
                )
                try:
                    session.execute(
                        text(
                            "UPDATE users SET credits = :c, last_reset = 'cumulative' WHERE user_id = :uid"
                        ),
                        {"c": INITIAL_FREE_CREDITS, "uid": next_user_id},
                    )
                    session.commit()
                except Exception as _fe:
                    error(
                        f"[AUTH] Falha total ao atribuir créditos iniciais para user_id={next_user_id}: {_fe}"
                    )

            return (
                True,
                {
                    "user_id": user.user_id,
                    "email": user.email,
                    "full_name": user.full_name,
                    "role": "member",
                    "client_id": user.client_id,
                },
                None,
            )

        except Exception as e:
            error(f"Erro ao registrar usuário: {e}")
            return False, None, str(e)
        finally:
            if "session" in locals():
                session.close()

    # ========================================================================
    # GOOGLE OAUTH
    # ========================================================================

    def handle_google_auth(
        self, auth_code: str, preferred_redirect_uri: Optional[str] = None
    ) -> tuple[bool, Optional[Dict], str]:
        """Processa autenticação Google OAuth"""
        try:
            client_id = AuthConfig.get_google_client_id()
            client_secret = AuthConfig.get_google_client_secret()

            if not client_id or not client_secret:
                return False, None, "Google OAuth não configurado no servidor"

            callback_url = preferred_redirect_uri or "postmessage"

            token_response = requests.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": auth_code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": callback_url,
                    "grant_type": "authorization_code",
                },
                timeout=10,
            )

            if token_response.status_code != 200:
                return False, None, "Falha ao autenticar com Google"

            token_data = token_response.json()
            id_token_jwt = token_data.get("id_token")

            from google.oauth2 import id_token
            from google.auth.transport import requests as google_requests

            userinfo = id_token.verify_oauth2_token(
                id_token_jwt, google_requests.Request(), client_id
            )
            google_email = userinfo.get("email")
            google_name = userinfo.get("name", "Google User")

            session = self.db.get_session()
            existing_user = session.execute(
                text("SELECT * FROM users WHERE email = :email LIMIT 1"),
                {"email": google_email},
            ).fetchone()

            if existing_user:
                existing_user_dict = (
                    dict(existing_user._mapping)
                    if hasattr(existing_user, "_mapping")
                    else dict(existing_user)
                )
                return (
                    True,
                    {
                        "user_id": existing_user_dict.get("user_id"),
                        "email": existing_user_dict.get("email"),
                        "full_name": existing_user_dict.get("full_name"),
                        "role": existing_user_dict.get("role", "member"),
                        "client_id": existing_user_dict.get("client_id"),
                        "status": existing_user_dict.get("status"),
                    },
                    None,
                )

            # Auto-Signup
            if (
                session.execute(
                    text(
                        f"SELECT COUNT(DISTINCT u.user_id) FROM users u JOIN clients c ON u.client_id = c.client_id JOIN plans p ON c.plan_id = p.plan_id WHERE p.plan_type != 'trial'"
                    )
                ).fetchone()[0]
                >= MAX_USERS
            ):
                return False, None, "Limite de usuários atingido"

            next_client_id = str(
                (
                    session.execute(
                        text("SELECT MAX(CAST(client_id AS INTEGER)) FROM clients")
                    ).fetchone()[0]
                    or 0
                )
                + 1
            )

            from App.Features.Credits.PlanManager import get_plan_manager

            free_plan = get_plan_manager().get_active_plans().get("free")

            self.db.create_client(
                session,
                {
                    "client_id": next_client_id,
                    "plan_id": free_plan.get("plan_id"),
                    "started_at": datetime.utcnow(),
                    "finishes_at": None,
                    "users_available": 1,
                },
            )

            next_user_id = str(
                (
                    session.execute(
                        text("SELECT MAX(CAST(user_id AS INTEGER)) FROM users")
                    ).fetchone()[0]
                    or 0
                )
                + 1
            )

            import secrets

            dummy_password = bcrypt.hashpw(
                secrets.token_urlsafe(32).encode("utf-8"), bcrypt.gensalt()
            ).decode("utf-8")

            user = self.db.create_user(
                session,
                {
                    "user_id": next_user_id,
                    "client_id": next_client_id,
                    "email": google_email,
                    "password": dummy_password,
                    "full_name": google_name,
                    "ip_address": None,
                    "fingerprint_id": None,
                },
            )

            try:
                from App.Features.Credits.CreditsManager import CreditsManager

                CreditsManager.distribute_plan_credits(
                    next_user_id, free_plan.get("plan_id")
                )
            except:
                pass

            return (
                True,
                {
                    "user_id": user.user_id,
                    "email": user.email,
                    "full_name": user.full_name,
                    "role": "member",
                    "client_id": user.client_id,
                },
                None,
            )

        except Exception as e:
            error(f"Erro ao processar Google Auth: {e}")
            return False, None, "Erro interno"
        finally:
            if "session" in locals():
                session.close()

    def authenticate_google_token(
        self, token: str, fingerprint_components: Dict[str, Any]
    ) -> tuple[bool, Optional[Dict], str]:
        """Autentica usuário com token JWT do Google (popup flow)"""
        try:
            userinfo_response = requests.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )

            if userinfo_response.status_code != 200:
                return False, None, "Falha ao validar token Google"

            userinfo = userinfo_response.json()
            google_email = userinfo.get("email")
            google_name = userinfo.get("name", "Google User")

            session = self.db.get_session()
            existing_user = session.execute(
                text("SELECT * FROM users WHERE email = :email LIMIT 1"),
                {"email": google_email},
            ).fetchone()

            if existing_user:
                existing_user_dict = (
                    dict(existing_user._mapping)
                    if hasattr(existing_user, "_mapping")
                    else dict(existing_user)
                )
                return (
                    True,
                    {
                        "user_id": existing_user_dict.get("user_id"),
                        "email": existing_user_dict.get("email"),
                        "full_name": existing_user_dict.get("full_name"),
                        "role": existing_user_dict.get("role", "member"),
                        "client_id": existing_user_dict.get("client_id"),
                        "status": existing_user_dict.get("status"),
                    },
                    None,
                )

            # Auto-Signup
            if (
                session.execute(
                    text(
                        f"SELECT COUNT(DISTINCT u.user_id) FROM users u JOIN clients c ON u.client_id = c.client_id JOIN plans p ON c.plan_id = p.plan_id WHERE p.plan_type != 'trial'"
                    )
                ).fetchone()[0]
                >= MAX_USERS
            ):
                return False, None, "Limite de usuários atingido"

            import uuid

            next_client_id = str(uuid.uuid4())

            from App.Features.Credits.PlanManager import get_plan_manager

            free_plan = get_plan_manager().get_active_plans().get("free")

            self.db.create_client(
                session,
                {
                    "client_id": next_client_id,
                    "plan_id": free_plan.get("plan_id"),
                    "started_at": datetime.utcnow(),
                    "finishes_at": None,
                    "users_available": 1,
                },
            )

            next_user_id = str(uuid.uuid4())

            import secrets

            dummy_password = bcrypt.hashpw(
                secrets.token_urlsafe(32).encode("utf-8"), bcrypt.gensalt()
            ).decode("utf-8")

            user = self.db.create_user(
                session,
                {
                    "user_id": next_user_id,
                    "client_id": next_client_id,
                    "email": google_email,
                    "password": dummy_password,
                    "full_name": google_name,
                    "ip_address": None,
                    "fingerprint_id": (
                        fingerprint_components.get("fingerprint_id")
                        if isinstance(fingerprint_components, dict)
                        else None
                    ),
                },
            )

            try:
                from App.Features.Credits.CreditsManager import CreditsManager

                CreditsManager.distribute_plan_credits(
                    next_user_id, free_plan.get("plan_id")
                )
            except:
                pass

            return (
                True,
                {
                    "user_id": user.user_id,
                    "email": user.email,
                    "full_name": user.full_name,
                    "role": "member",
                    "client_id": user.client_id,
                },
                None,
            )

        except Exception as e:
            error(f"Erro ao processar Google Token: {e}")
            return False, None, "Erro interno"
        finally:
            if "session" in locals():
                session.close()


# Instância global do serviço
_auth_service: Optional[AuthService] = None


def init_auth_service(db_manager=None, config=None) -> AuthService:
    global _auth_service
    _auth_service = AuthService(db_manager=db_manager, config=config)
    info("[AUTH] AuthService initialized")
    return _auth_service


def get_auth_service() -> AuthService:
    global _auth_service

    if not _auth_service or not _auth_service.db:
        from App.Core.Crunch import get_db_manager

        db_manager = get_db_manager()
        if db_manager:
            init_auth_service(db_manager=db_manager, config=GLOBAL_CONFIG)
        else:
            raise RuntimeError("Database manager unavailable")

    return _auth_service

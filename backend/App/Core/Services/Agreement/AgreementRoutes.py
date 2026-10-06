"""
Rotas de Agreement - FastAPI Routes
Gerenciamento de termos, privacidade e cookies
"""

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional

from App.Core.Logs import debug, info, warning, error
from App.Features.Auth import get_auth_service, AuthConfig
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Core.Settings import load_config

# ========================================================================
# MODELS
# ========================================================================


class AgreementResponse(BaseModel):
    """Resposta com informações de acordos do usuário"""

    cookies_accepted: bool
    cookies_accepted_at: Optional[str] = None
    terms_accepted: bool
    terms_accepted_at: Optional[str] = None
    privacy_accepted: bool
    privacy_accepted_at: Optional[str] = None


class AgreementRequest(BaseModel):
    """Requisição para aceitar acordos"""

    cookies_accepted: Optional[bool] = Field(
        None, description="Aceitar cookies de rastreamento"
    )
    terms_accepted: Optional[bool] = Field(
        None, description="Aceitar termos de serviço"
    )
    privacy_accepted: Optional[bool] = Field(
        None, description="Aceitar política de privacidade"
    )


class AgreementSignupRequest(BaseModel):
    """Requisição para signup via agreement (fingerprint)"""

    fingerprint_id: str = Field(..., description="ID único do dispositivo")


# ========================================================================
# ROUTER
# ========================================================================

agreement_router = APIRouter(tags=["Agreement"], prefix="/api")


# ========================================================================
# DEPENDENCY - Extrair user_id e client_id do token
# ========================================================================


def get_user_and_client_id(request: Request) -> tuple:
    """
    Extrai o user_id e client_id do token JWT verificando o cookie ou header.
    Suporta bypass de autenticação via dev_bypass_middleware.

    Returns:
        tuple: (user_id, client_id)

    Raises:
        HTTPException: Se token inválido ou expirado
    """
    try:
        # DEV MODE: Verificar se o dev_bypass foi ativado pelo middleware
        if request.scope.get("dev_bypass_enabled"):
            dev_client_id = request.scope.get("dev_client_id", 1)
            debug(f"[AGREEMENT] DEV BYPASS: Usando client_id={dev_client_id}")
            # Retornar user_id=1 por padrão em dev bypass
            return (1, dev_client_id)

        # MODO NORMAL: Validar token JWT
        token = request.cookies.get("access_token")

        if not token:
            raise HTTPException(status_code=401, detail="Token não fornecido")

        # Verificar token
        auth_service = get_auth_service()
        payload = auth_service.verify_token(token)

        if not payload:
            raise HTTPException(status_code=401, detail="Token inválido ou expirado")

        user_id = payload.get("user_id")
        client_id = payload.get("client_id")

        if not user_id or not client_id:
            raise HTTPException(
                status_code=401, detail="User ID ou Client ID não encontrados no token"
            )

        return (user_id, client_id)

    except HTTPException:
        raise
    except Exception as e:
        error(f"[AGREEMENT] Erro ao extrair user_id e client_id: {e}")
        raise HTTPException(status_code=401, detail="Erro ao validar autenticação")


# ========================================================================
# ROUTES
# ========================================================================


@agreement_router.get("/lp")
async def get_lp_data(seconds: int = 3600):
    """
    Landing Page data - retorna visitors e users_countdown em uma única requisição.

    Args:
        seconds: Período em segundos para contar visitantes (padrão: 3600 = 1 hora)

    Returns:
        dict: {"visitors": count, "users_countdown": countdown_data}
    """
    try:
        from datetime import datetime, timedelta

        db = DatabaseManager()
        config = load_config()
        max_users = config.get("max_users", 100)

        # 1. Contar visitantes únicos
        time_limit = datetime.utcnow() - timedelta(seconds=seconds)
        query_visitors = """
            SELECT COUNT(DISTINCT fingerprint_id) as total
            FROM visitor_logs
            WHERE visited_at >= :time_limit
        """
        result_visitors = db.fetch_one(query_visitors, {"time_limit": time_limit})
        visitor_count = result_visitors.get("total") or 0 if result_visitors else 0

        # 2. Contar usuários com planos pagos/free
        query_countdown = """
            SELECT COUNT(DISTINCT u.user_id) as total
            FROM users u
            JOIN clients c ON u.client_id = c.client_id
            JOIN plans p ON c.plan_id = p.plan_id
            WHERE p.plan_id IN ('free', 'pro', 'business')
        """
        result_countdown = db.fetch_one(query_countdown, {})
        total_paid_users = result_countdown.get("total") or 0 if result_countdown else 0

        countdown = max(0, max_users - total_paid_users)

        info(f"[LP] visitors={visitor_count}, remaining={countdown}")

        return {"visitors": visitor_count, "users_countdown": {"remaining": countdown}}

    except Exception as e:
        error(f"[LP] Erro ao obter dados: {e}")
        raise HTTPException(
            status_code=500, detail="Erro ao obter dados da landing page"
        )


@agreement_router.get("/visitor")
async def get_visitors(seconds: int = 3600):
    """
    Retorna a contagem de fingerprint_ids únicos que visitaram o site nos últimos X segundos.

    Args:
        seconds: Período em segundos (padrão: 3600 = 1 hora)

    Returns:
        dict: {"visitors": count}
    """
    try:
        from datetime import datetime, timedelta

        db = DatabaseManager()

        # Calcular data limite
        time_limit = datetime.utcnow() - timedelta(seconds=seconds)

        # Query para contar fingerprints únicos visitados nos últimos X segundos
        query = """
            SELECT COUNT(DISTINCT fingerprint_id) as total
            FROM visitor_logs
            WHERE visited_at >= :time_limit
        """

        result = db.fetch_one(query, {"time_limit": time_limit})
        visitor_count = result.get("total") or 0 if result else 0

        info(f"[VISITOR] {visitor_count} fingerprints únicos nos últimos {seconds}s")

        return {"visitors": visitor_count}

    except Exception as e:
        error(f"[VISITOR] Erro ao obter visitors: {e}")
        raise HTTPException(status_code=500, detail="Erro ao obter dados de visitantes")


@agreement_router.get("/users_countdown")
async def get_users_countdown():
    """
    Retorna quantas vagas de usuários com planos pagos/free ainda estão disponíveis.
    Usuários trial (fingerprint) NÃO contam para o limite.

    Returns:
        dict: Número de vagas restantes e limite total
    """
    try:
        config = load_config()
        max_users = config.get("max_users", 100)

        db = DatabaseManager()

        # Contar apenas usuários com planos Free, Pro ou Business
        result = db.fetch_one(
            """
            SELECT COUNT(DISTINCT u.user_id) as total
            FROM users u
            JOIN clients c ON u.client_id = c.client_id
            JOIN plans p ON c.plan_id = p.plan_id
            WHERE p.plan_id IN ('free', 'pro', 'business')
        """,
            {},
        )
        total_paid_users = result.get("total") or 0 if result else 0

        countdown = max(0, max_users - total_paid_users)

        info(
            f"[AGREEMENT] Users countdown - paid_users={total_paid_users}, max={max_users}, remaining={countdown}"
        )

        return {
            "remaining": countdown,
            "paid_users": total_paid_users,
            "trial_users": "Ativo",
            "max_users": max_users,
            "can_signup": countdown > 0,
            "info": "Limite aplica-se a usuários com planos cadastrados.",
        }

    except Exception as e:
        error(f"[AGREEMENT] Erro ao obter countdown de usuários: {e}")
        raise HTTPException(
            status_code=500, detail="Erro ao obter informações de usuários"
        )


class TrackVisitorRequest(BaseModel):
    """Requisição para rastrear visitante"""

    fingerprint_id: str = Field(..., description="ID único do dispositivo")
    tab: Optional[str] = Field(
        None, description="Identificador da aba/origem (ex: 'lp')"
    )
    conversion_type: Optional[str] = Field(
        None, description="Tipo de conversão (ex: 'campaign', 'invite')"
    )
    conversion_method_id: Optional[str] = Field(
        None, description="ID do método de conversão"
    )


@agreement_router.post("/visitor/track")
async def track_visitor(request: TrackVisitorRequest):
    """
    Rastreia um visitante e registra sua origem (campaign ou invite).

    Args:
        request: TrackVisitorRequest contendo fingerprint_id, tab, conversion_type, conversion_method_id

    Returns:
        dict: {"success": true/false, "message": "..."}
    """
    try:
        from sqlalchemy import text
        from App.Core.Crunch import DatabaseManager

        def register_visit(session):
            session.execute(
                text(
                    """
                INSERT INTO visitor_logs (fingerprint_id, tab, conversion_type, conversion_method_id)
                VALUES (:fingerprint_id, :tab, :conversion_type, :conversion_method_id)
            """
                ),
                {
                    "fingerprint_id": request.fingerprint_id,
                    "tab": request.tab,
                    "conversion_type": request.conversion_type,
                    "conversion_method_id": request.conversion_method_id,
                },
            )

        DatabaseManager.execute_transaction(register_visit)
        info(
            f"[VISITOR] Visita registrada - fingerprint={request.fingerprint_id}, tab={request.tab}, conversion_type={request.conversion_type}, conversion_method_id={request.conversion_method_id}"
        )

        return {"success": True, "message": "Visitor tracked successfully"}

    except Exception as e:
        error(f"[VISITOR] Erro em track_visitor: {e}")
        raise HTTPException(
            status_code=500, detail="Erro ao processar requisição de rastreamento"
        )


@agreement_router.get("/agreement/agree")
async def agree_and_signup_get(fingerprint_id: str, tab: str = None):
    """
    GET versão de /agreement/agree para compatibilidade com query params.
    Verifica se o fingerprint existe e retorna apenas {exists: true/false}.
    Não cria conta nem retorna token.

    Args:
        fingerprint_id: ID do fingerprint do usuário
        tab: Identificador da aba/origem (ex: 'lp' para landing page)

    Returns:
        dict: {"exists": true/false}
    """
    try:
        # Verificar se fingerprint_id já existe na tabela users
        db = DatabaseManager()
        existing_user_query = """
            SELECT user_id, type
            FROM users
            WHERE fingerprint_id = :fingerprint_id
            LIMIT 1
        """
        existing_user = db.fetch_one(
            existing_user_query, {"fingerprint_id": fingerprint_id}
        )

        # Sempre retorna exists: false para forçar exibição do popup
        # Mesmo se fingerprint existir, o usuário precisa aceitar cookies novamente
        # por conta da LGPD (cada navegador/sessão precisa de consentimento)
        debug(
            f"[AGREEMENT] GET /agreement/agree - fingerprint={fingerprint_id}, exists={existing_user is not None}, but always returning false for LGPD compliance"
        )

        return {"exists": False}

    except Exception as e:
        error(f"[AGREEMENT] Erro em agree_and_signup_get: {e}")
        raise HTTPException(status_code=500, detail="Erro ao verificar fingerprint")


@agreement_router.post("/agreement/agree")
async def agree_and_signup(request: Request, agreement_data: AgreementSignupRequest):
    """
    Cria conta trial via fingerprint ou retorna conta existente.

    Se fingerprint não existe: cria novo usuário trial
    Se fingerprint existe com type='trial': retorna token de login automático
    Se fingerprint existe com type='login': retorna 404

    Args:
        agreement_data: AgreementSignupRequest contendo fingerprint_id

    Returns:
        dict: access_token, refresh_token e informações do usuário
    """
    try:
        from sqlalchemy import text
        import uuid as uuid_lib
        import bcrypt

        debug(
            f"[AGREEMENT] POST /agreement/agree - fingerprint={agreement_data.fingerprint_id}"
        )

        db = DatabaseManager()

        # 1. Verificar se fingerprint_id já existe
        existing_user_query = """
            SELECT user_id, client_id, email, full_name, type
            FROM users
            WHERE fingerprint_id = :fingerprint_id
            LIMIT 1
        """
        existing_user = db.fetch_one(
            existing_user_query, {"fingerprint_id": agreement_data.fingerprint_id}
        )

        if existing_user:
            # Se é usuário trial, fazer auto-login (e pode atualizar credenciais se necessário)
            if existing_user["type"] == "trial":
                info(
                    f"[AGREEMENT] Auto-login trial - fingerprint={agreement_data.fingerprint_id}"
                )

                # Gerar tokens
                auth_service = get_auth_service()
                user_data = {
                    "user_id": existing_user["user_id"],
                    "client_id": existing_user["client_id"],
                    "email": existing_user["email"],
                    "full_name": existing_user["full_name"],
                }

                access_token = auth_service.generate_access_token(user_data)
                refresh_token_data = auth_service.generate_refresh_token(user_data)

                # Criar response com dados
                response_data = {
                    "status": "auto_login",
                    "message": "Login automático realizado",
                    "user": user_data,
                }

                # Criar resposta JSON
                response = JSONResponse(status_code=200, content=response_data)

                # INJETAR COOKIES HTTP-ONLY
                response.set_cookie(
                    key="access_token",
                    value=access_token,
                    httponly=True,
                    secure=False,
                    samesite="lax",
                    max_age=AuthConfig.ACCESS_EXPIRY,
                )

                response.set_cookie(
                    key="refresh_token",
                    value=refresh_token_data["token"],
                    httponly=True,
                    secure=False,
                    samesite="lax",
                    max_age=AuthConfig.REFRESH_EXPIRY,
                )

                return response
            else:
                # Se é usuário login, não permitir
                warning(
                    f"[AGREEMENT] Fingerprint já registrado com type=login - fingerprint={agreement_data.fingerprint_id}"
                )
                raise HTTPException(status_code=404, detail="Conta não encontrada")

        # 2. Criar novo usuário trial com fingerprint_id
        # NOTA: Usuários trial não contam para o limite de MAX_USERS
        # O limite aplica-se apenas a usuários com planos pagos/free
        # Gerar credentials temporárias
        temp_email = f"trial_{uuid_lib.uuid4().hex[:8]}@trial.local"
        temp_password = uuid_lib.uuid4().hex
        hashed_password = bcrypt.hashpw(
            temp_password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")

        # Gerar novo client_id
        session = db.execute_transaction(lambda session: session)

        # Usar DatabaseManager para criar
        session = DatabaseManager.get_session()
        try:
            from sqlalchemy import text
            from datetime import datetime
            import uuid as uuid_lib

            # Gerar novos UUIDs para user_id e client_id
            new_client_id = str(uuid_lib.uuid4())
            new_user_id = str(uuid_lib.uuid4())

            # Obter plano Trial
            from App.Features.Credits.PlanManager import get_plan_manager

            plan_manager = get_plan_manager()
            plans_by_type = plan_manager.get_active_plans()
            trial_plan = plans_by_type.get("trial")

            if not trial_plan:
                raise Exception("Plano Trial não encontrado nos planos ativos")

            trial_plan_id = trial_plan.get("plan_id")

            # Criar client com plano Trial
            client_data = {
                "client_id": new_client_id,
                "plan_id": trial_plan_id,
                "started_at": datetime.utcnow(),
                "finishes_at": None,
                "users_available": 1,
            }
            DatabaseManager.create_client(session, client_data)

            # Criar usuário trial
            user_data_new = {
                "user_id": new_user_id,
                "client_id": new_client_id,
                "email": temp_email,
                "password": hashed_password,
                "full_name": "new_user",
                "type": "trial",
                "fingerprint_id": agreement_data.fingerprint_id,
                "credits": 5,  # Créditos iniciais do plano Trial
            }
            DatabaseManager.create_user(session, user_data_new)

            info(
                f"[AGREEMENT] Novo usuário trial criado - fingerprint={agreement_data.fingerprint_id}, user_id={new_user_id}"
            )

            # Verificar atribuição de referral via visitor_logs
            try:
                visitor = db.fetch_one(
                    """
                    SELECT conversion_method_id, channel_id
                    FROM visitor_logs
                    WHERE fingerprint_id = :fp
                      AND (conversion_method_id IS NOT NULL OR channel_id IS NOT NULL)
                    ORDER BY visited_at DESC
                    LIMIT 1
                    """,
                    {"fp": agreement_data.fingerprint_id},
                )
                if visitor:
                    campaign_code = visitor.get("channel_id") or visitor.get(
                        "conversion_method_id"
                    )
                    if campaign_code:
                        from App.Core.Services.Sharing.ReferralManager import (
                            ReferralManager,
                        )

                        ReferralManager.create_attribution(
                            agreement_data.fingerprint_id, campaign_code
                        )
            except Exception as ref_err:
                warning(f"[AGREEMENT] Erro ao verificar referral: {ref_err}")

            # Gerar tokens
            auth_service = get_auth_service()
            token_user_data = {
                "user_id": new_user_id,
                "client_id": new_client_id,
                "email": temp_email,
                "full_name": "new_user",
            }

            access_token = auth_service.generate_access_token(token_user_data)
            refresh_token_data = auth_service.generate_refresh_token(token_user_data)

            # Criar response com dados
            response_data = {
                "status": "created",
                "message": "Conta trial criada com sucesso",
                "user": {
                    "user_id": new_user_id,
                    "email": temp_email,
                    "full_name": "new_user",
                    "client_id": new_client_id,
                },
            }

            # Criar resposta JSON
            response = JSONResponse(status_code=200, content=response_data)

            # INJETAR COOKIES HTTP-ONLY
            response.set_cookie(
                key="access_token",
                value=access_token,
                httponly=True,
                secure=False,
                samesite="lax",
                max_age=AuthConfig.ACCESS_EXPIRY,
            )

            response.set_cookie(
                key="refresh_token",
                value=refresh_token_data["token"],
                httponly=True,
                secure=False,
                samesite="lax",
                max_age=AuthConfig.REFRESH_EXPIRY,
            )

            return response

        except Exception as e:
            session.rollback()
            error(f"[AGREEMENT] Erro ao criar usuário trial: {e}")
            raise HTTPException(status_code=500, detail="Erro ao criar conta trial")
        finally:
            session.close()

    except HTTPException:
        raise
    except Exception as e:
        error(f"[AGREEMENT] Erro em agree_and_signup: {e}")
        raise HTTPException(status_code=500, detail="Erro ao processar requisição")


# ========================================================================
# EXPORTS
# ========================================================================

__all__ = ["agreement_router"]

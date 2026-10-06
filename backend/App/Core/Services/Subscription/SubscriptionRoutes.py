"""
Rotas de Subscription - FastAPI Routes
Apenas rotas e validações HTTP, lógica de negócio delegada para SubscriptionService
UPDATED: Added POST /new-card and POST /new-card/info routes
"""

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, Union
import uuid as uuid_lib
from datetime import datetime, timedelta
import json

from App.Core.Logs import debug, info, warning, error
from App.Features.Auth import get_auth_service
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Core.Settings import load_config
from App.Core.Settings.Settings import WEBHOOK_PREFIX
from App.Core.Services.Subscription.PaymentService import get_payment_service
from App.Core.Services.Subscription.StripePaymentService import (
    get_stripe_payment_service,
)
from App.Core.Services.Subscription.EncryptionUtil import (
    encrypt_field,
    decrypt_field,
    hash_payment_method,
)
from App.Features.Credits.CreditsManager import CreditsManager

# ========================================================================
# MODELS
# ========================================================================


class CreditsResponse(BaseModel):
    """Resposta com informações de créditos do usuário"""

    credits_available: float
    credits_reset_in: Optional[
        int
    ] = None  # Horas do período de reset (cumulative_resets_in)
    reset_credits: Optional[float] = None  # Quantidade de créditos que será resetada
    plan_name: Optional[str] = None  # Nome do plano do usuário
    plan_type: Optional[str] = None  # trial, free, pro, business, extra
    plan_id: str
    currency: str
    client_subscription_id: Optional[
        str
    ] = None  # ID da subscription ativa para cancelamento

    class Config:
        exclude_none = False


class PlanResponse(BaseModel):
    """Resposta com informações de um plano"""

    id: int
    subscription_id: str
    name: str
    description: Optional[str] = None
    message: Optional[str] = None
    cumulative_credits: Optional[float] = None
    cumulative_resets_in: Optional[int] = None
    non_cumulative_credits: Optional[float] = None
    non_cumulative_resets_in: Optional[int] = None
    users_limit: Optional[int] = None
    currency: Dict[str, Any]
    features: Dict[str, Any]
    sell: bool = False  # Se o plano deve ser vendido
    plan_type: str = "plan"  # Tipo: "plan" ou "extra"


class PlansListResponse(BaseModel):
    """Resposta com lista de planos"""

    plans: list[PlanResponse]
    count: int


class CardRequest(BaseModel):
    """Request para registrar cartão"""

    card_number: str = Field(..., description="Número do cartão (16 dígitos)")
    holder_name: str = Field(..., description="Nome do titular do cartão")
    expiry_month: int = Field(..., description="Mês de expiração (1-12)")
    expiry_year: int = Field(..., description="Ano de expiração (YYYY)")
    cvv: str = Field(..., description="Código de segurança (3 ou 4 dígitos)")


class NewCardRequest(BaseModel):
    """
    Request para registrar novo cartão

    ⚠️ IMPORTANTE: O Front DEVE validar e tokenizar o cartão via Pagarme tokenizecard.js
    Este endpoint APENAS recebe a resposta do Pagarme (card_id, last_4, etc)
    NUNCA enviando dados brutos do cartão para o backend
    """

    card_id: str = Field(..., description="UUID do cartão retornado pelo Pagarme")
    last_4: str = Field(..., description="Últimos 4 dígitos (ex: '5060')")
    brand: str = Field(..., description="Bandeira (ex: 'visa', 'mastercard', 'amex')")
    holder_name: str = Field(..., description="Nome do titular do cartão")


class NewCardInfoRequest(BaseModel):
    """
    Request para confirmar cartão após tokenização no Stripe

    ✅ COMPLIANCE: Dados do cartão nunca tocam no servidor
    Fluxo:
    1. POST /new-card → Gera UUID temporário (status='temp')
    2. Front tokeniza com StripeTokenizer (usa Token API do Stripe.js)
    3. POST /new-card/info → Confirma e salva token_id (status='valid')

    ⚠️ payment_method_id pode ser:
    - Token ID (ex: tok_visa_4242) criado via Token API
    - Payment Method ID criado via Payment Method API
    """

    card_id: str = Field(..., description="UUID temporário gerado em /new-card")
    payment_method_id: str = Field(
        ..., description="Token ID ou Payment Method ID do Stripe (PCI compliant)"
    )
    brand: str = Field(..., description="Bandeira do cartão")
    last_4: str = Field(..., description="Últimos 4 dígitos")
    exp_month: int = Field(..., description="Mês de expiração (1-12)")
    exp_year: int = Field(..., description="Ano de expiração (YYYY)")
    holder_name: str = Field(..., description="Nome do titular")


class BillingInfoRequest(BaseModel):
    """
    Request para registrar informações de cobrança (INDEPENDENTE DE CARTÃO)

    ✅ Fluxo correto:
    1. POST /billing → Registra dados do usuário
    2. POST /new-card → Registra cartão (opcional com dados de billing)
    3. POST /charge → Cobra com cartão registrado
    """

    address: str = Field(..., description="Endereço completo")
    complement: Optional[str] = Field(None, description="Complemento do endereço")
    neighborhood: str = Field(..., description="Bairro (obrigatório para Stripe/PSP)")
    city: str = Field(..., description="Cidade")
    state: str = Field(..., description="Estado (UF)")
    postal_code: str = Field(..., description="CEP")
    phone_number: str = Field(..., description="Telefone com DDD")
    document: str = Field(..., description="CPF ou CNPJ")
    # email é carregado do banco de dados (user.email), não precisa ser enviado


class ConfirmPaymentRequest(BaseModel):
    """Request para confirmar pagamento e ativar plano"""

    billing_id: str = Field(
        ..., description="UUID do billing_info (retornado da rota billing)"
    )
    card_id: str = Field(..., description="UUID do cartão tokenizado")
    plan_id: Union[int, str] = Field(
        ..., description="ID do plano (int ou string como 'pro')"
    )
    type: str = Field(..., description="'monthly' ou 'annual'")
    coupon: Optional[str] = Field(None, description="Código do cupom (opcional)")


class CheckoutTrackingUpdateRequest(BaseModel):
    """Request para atualizar status do rastreamento de checkout"""

    tracking_id: str = Field(..., description="UUID do rastreamento")
    status: str = Field(
        ...,
        description="Status: viewed, billing_started, card_registered, payment_completed, abandoned",
    )


class SubscriptionResponse(BaseModel):
    """Resposta com informações de subscrição"""

    subscription_id: str
    plan_id: int
    plan_name: str
    status: str
    charge_scheduled_at: str
    canceled_at: Optional[str] = None
    created_at: str


class UserSubscriptionsResponse(BaseModel):
    """Resposta com subscrições do usuário"""

    subscriptions: list[SubscriptionResponse]
    count: int


# ========================================================================
# ROUTER
# ========================================================================

subscription_router = APIRouter(tags=["Subscription"], prefix="/api/subscriptions")
subscription_cancel_router = APIRouter(
    tags=["Subscription"], prefix="/api/subscription"
)
credits_router = APIRouter(tags=["Credits"], prefix="/api")
webhook_router = APIRouter(tags=["Webhooks"], prefix=WEBHOOK_PREFIX)


# ========================================================================
# HELPER FUNCTIONS
# ========================================================================


def parse_credits_reset_in(value) -> Optional[int]:
    """
    Converte credits_reset_in para int ou None.
    Se for 'never' (string), retorna None.
    """
    if value is None or value == "never" or value == "never ":
        return None
    try:
        return int(value) if value else None
    except (ValueError, TypeError):
        return None


def extract_features_by_language(features_string: str, language: str = "pt") -> str:
    """
    Extrai features no idioma especificado.

    Formato esperado: pt=feature1|feature2&&es=feature1|feature2&&en=feature1|feature2

    Args:
        features_string: String com features em múltiplos idiomas
        language: Idioma desejado (pt, es, en). Padrão: pt

    Returns:
        String com features do idioma solicitado, separadas por |
    """
    if not features_string or not isinstance(features_string, str):
        return ""

    # Validar idioma
    if language not in ["pt", "es", "en"]:
        language = "pt"

    # Se não tiver &&, é formato antigo (sem multi-idioma)
    if "&&" not in features_string:
        return features_string

    # Split por && para pegar cada idioma
    language_blocks = features_string.split("&&")

    for block in language_blocks:
        if f"{language}=" in block:
            # Extrair a parte após "pt=", "es=" ou "en="
            return block.split(f"{language}=", 1)[1] if f"{language}=" in block else ""

    # Se não encontrar o idioma solicitado, retornar vazio
    return ""


def calculate_hours_until_reset(
    credits_reset_at, created_at, credits_reset_in_hours
) -> Optional[int]:
    """
    Calcula quantas horas faltam até o próximo reset de créditos.

    Args:
        credits_reset_at: Data do último reset (string ou None)
        created_at: Data de criação do usuário (string)
        credits_reset_in_hours: Horas até reset (int ou None)

    Returns:
        Horas restantes até próximo reset, ou None se nunca reseta
    """
    from datetime import datetime, timedelta

    if credits_reset_in_hours is None or credits_reset_in_hours == 0:
        return None

    try:
        # Base: usar última data de reset ou data de criação
        base_date_str = credits_reset_at or created_at
        base_date = datetime.fromisoformat(base_date_str.replace("Z", "+00:00"))

        # Calcular próximo reset
        next_reset = base_date + timedelta(hours=credits_reset_in_hours)
        now = datetime.now(base_date.tzinfo)

        # Calcular horas restantes
        remaining = next_reset - now
        hours_remaining = int(remaining.total_seconds() / 3600)

        # Se já passou, retornar 0
        return max(0, hours_remaining)
    except Exception as e:
        debug(f"[CREDITS] Erro ao calcular horas até reset: {e}")
        return None


# ========================================================================
# DEPENDENCY - Extrair client_id do token
# ========================================================================


def get_client_id_from_token(request: Request) -> int:
    """
    Extrai o client_id do token JWT verificando o cookie ou header.
    Suporta bypass de autenticação via dev_bypass_middleware.

    Returns:
        client_id: ID do cliente autenticado

    Raises:
        HTTPException: Se token inválido ou expirado
    """
    try:
        # DEV MODE: Verificar se o dev_bypass foi ativado pelo middleware PRIMEIRO
        if request.scope.get("dev_bypass_enabled"):
            dev_client_id = request.scope.get("dev_client_id", 1)
            debug(f"[SUBSCRIPTION] DEV BYPASS: Usando client_id={dev_client_id}")
            return dev_client_id

        # MODO NORMAL: Validar token JWT
        token = request.cookies.get("access_token")

        if not token:
            raise HTTPException(status_code=401, detail="Token não fornecido")

        # Verificar token
        auth_service = get_auth_service()
        payload = auth_service.verify_token(token)

        if not payload:
            raise HTTPException(status_code=401, detail="Token inválido ou expirado")

        client_id = payload.get("client_id")
        if not client_id:
            raise HTTPException(
                status_code=401, detail="Client ID não encontrado no token"
            )

        return client_id

    except HTTPException:
        raise
    except Exception as e:
        error(f"[SUBSCRIPTION] Erro ao extrair client_id: {e}")
        debug(f"Request scope keys: {list(request.scope.keys())}")
        raise HTTPException(status_code=401, detail="Erro ao validar autenticação")


# ========================================================================
# ROUTES
# ========================================================================


@subscription_router.get("/plans/ab-test/{test_id}", response_model=PlansListResponse)
async def get_plans_by_test(test_id: str):
    """
    Retorna planos ativos para um teste A/B específico.

    Args:
        test_id: ID do teste A/B

    Returns:
        PlansListResponse: Lista de planos ativos com o test_id especificado
    """
    try:
        debug(f"[SUBSCRIPTION] GET /plans/ab-test/{test_id}")

        db = DatabaseManager()

        # Query para obter planos ativos com test_id específico
        query = """
            SELECT
                id,
                plan_id,
                name,
                description,
                message,
                cumulative_credits,
                cumulative_resets_in,
                non_cumulative_credits,
                non_cumulative_resets_in,
                users_limit,
                annual_price,
                monthly_price,
                currency,
                credits_reset_in,
                features,
                sell,
                plan_type
            FROM plans
            WHERE active = 1 AND test_id = :test_id
            ORDER BY id ASC
        """

        results = db.fetch_all(query, {"test_id": test_id})

        if not results:
            info(f"[SUBSCRIPTION] Nenhum plano ativo encontrado para test_id={test_id}")
            return PlansListResponse(plans=[], count=0)

        plans = [
            PlanResponse(
                id=row.get("id"),
                subscription_id=row.get("plan_id"),
                name=row.get("name"),
                description=row.get("description"),
                message=row.get("message"),
                cumulative_credits=row.get("cumulative_credits"),
                cumulative_resets_in=row.get("cumulative_resets_in"),
                non_cumulative_credits=row.get("non_cumulative_credits"),
                non_cumulative_resets_in=row.get("non_cumulative_resets_in"),
                users_limit=row.get("users_limit"),
                annual_price=row.get("annual_price"),
                monthly_price=row.get("monthly_price"),
                currency=row.get("currency"),
                credits_reset_in=parse_credits_reset_in(row.get("credits_reset_in")),
                features=row.get("features"),
                sell=row.get("sell"),
                plan_type=row.get("plan_type") or "plan",
            )
            for row in results
        ]

        info(
            f"[SUBSCRIPTION] Planos de teste retornados - test_id={test_id}, count={len(plans)}"
        )
        return PlansListResponse(plans=plans, count=len(plans))

    except Exception as e:
        error(f"[SUBSCRIPTION] Erro ao obter planos de teste: {e}")
        raise HTTPException(status_code=500, detail="Erro ao obter planos de teste")


@subscription_router.get("", response_model=PlansListResponse)
async def get_subscriptions(plan_id: Optional[int] = None, language: str = "pt"):
    """
    Retorna planos disponíveis (com status 'on').
    Sem autenticação necessária.

    Query Parameters:
        plan_id: ID do plano específico (opcional). Se fornecido, retorna apenas esse plano.
        language: Idioma das features (pt, es, en). Padrão: pt

    Returns:
        PlansListResponse: Lista de planos disponíveis ou plano específico
    """
    try:
        debug(
            f"[SUBSCRIPTION] GET / - listando planos disponíveis (plan_id={plan_id}, language={language})"
        )

        db = DatabaseManager()

        # Buscar planos com status 'on' (disponíveis), sem test_id
        query = "SELECT id, plan_id, name, description, message, cumulative_credits, cumulative_resets_in, non_cumulative_credits, non_cumulative_resets_in, users_limit, credits_reset_in, sell, plan_type FROM plans WHERE active = 1 AND test_id IS NULL"

        # Adicionar filtro por plan_id se fornecido
        if plan_id is not None:
            query += " AND id = :plan_id"
            results = db.fetch_all(query, {"plan_id": plan_id})
        else:
            query += " ORDER BY id ASC"
            results = db.fetch_all(query, {})

        if not results:
            info("[SUBSCRIPTION] Nenhum plano disponível encontrado")
            return PlansListResponse(plans=[], count=0)

        plans = []
        for row in results:
            p_id = row.get("plan_id")

            # Aggregate currency
            prices = db.fetch_all(
                "SELECT currency, price, period, adoption_stage FROM prices WHERE plan_id = :plan_id",
                {"plan_id": p_id},
            )
            currency_dict = {}
            for price_row in prices:
                c_symbol = price_row.get("currency")
                if c_symbol not in currency_dict:
                    currency_dict[c_symbol] = {"early_adopter": {}, "late_adopter": {}}
                stage = price_row.get("adoption_stage")
                period = price_row.get("period")
                currency_dict[c_symbol][stage][period] = price_row.get("price")

            # Aggregate features
            features_query = db.fetch_all(
                "SELECT feature_type, feature FROM features WHERE plan_id = :plan_id AND language = :language",
                {"plan_id": p_id, "language": language},
            )
            features_dict = {"main_features": [], "early_adopters_features": []}
            for f_row in features_query:
                f_type = (
                    "main_features"
                    if f_row.get("feature_type") == "main"
                    else "early_adopters_features"
                )
                features_dict[f_type].append(f_row.get("feature"))

            plans.append(
                PlanResponse(
                    id=row.get("id"),
                    subscription_id=p_id,
                    name=row.get("name"),
                    description=row.get("description"),
                    message=row.get("message"),
                    cumulative_credits=row.get("cumulative_credits"),
                    cumulative_resets_in=row.get("cumulative_resets_in"),
                    non_cumulative_credits=row.get("non_cumulative_credits"),
                    non_cumulative_resets_in=row.get("non_cumulative_resets_in"),
                    users_limit=row.get("users_limit"),
                    currency=currency_dict,
                    credits_reset_in=parse_credits_reset_in(
                        row.get("credits_reset_in")
                    ),
                    features=features_dict,
                    sell=row.get("sell"),
                    plan_type=row.get("plan_type") or "plan",
                )
            )

        info(f"[SUBSCRIPTION] Planos retornados - count={len(plans)}")
        return PlansListResponse(plans=plans, count=len(plans))

    except Exception as e:
        error(f"[SUBSCRIPTION] Erro ao obter planos: {e}")
        import traceback

        error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Erro ao obter planos: {str(e)}")


@credits_router.get("/subscription/credits")
async def get_credits_single(request: Request):
    """
    Retorna os créditos disponíveis do usuário autenticado e o status da assinatura.
    """
    try:
        # Extrair user_id e client_id
        if request.scope.get("dev_bypass_enabled"):
            user_id = request.scope.get("dev_user_id", "1")
            client_id = request.scope.get("dev_client_id", "1")
        else:
            auth_service = get_auth_service()
            token = request.cookies.get("access_token")
            if not token:
                raise HTTPException(status_code=401)
            payload = auth_service.verify_token(token)
            if not payload:
                raise HTTPException(status_code=401)
            user_id = payload.get("user_id")
            client_id = payload.get("client_id")

        db = DatabaseManager()

        # Query unificada para créditos, status da assinatura e dados de uso por sessão/semana
        query = """
            SELECT
                u.credits,
                u.current_session_usage,
                u.current_session_starts_at,
                u.current_week_usage,
                u.current_week_starts_at,
                bs.status as plan_status,
                bs.payment_retry_count,
                bs.webhook_pending,
                bs.subscription_id,
                p.plan_type,
                p.name as plan_name,
                p.cumulative_credits
            FROM users u
            JOIN clients c ON u.client_id = c.client_id
            LEFT JOIN plans p ON c.plan_id = p.plan_id
            LEFT JOIN billing_subscriptions bs ON c.client_id = bs.client_id
            WHERE u.user_id = :user_id
            ORDER BY bs.created_at DESC
            LIMIT 1
        """
        result = db.fetch_one(query, {"user_id": user_id})

        if not result:
            return {
                "credits": 0.0,
                "plan_status": "free",
                "payment_failed": False,
                "plan_name": "Free",
                "plan_type": "free",
            }

        # Lógica de status e falha
        plan_status = result.get("plan_status") or "active"
        retry_count = result.get("payment_retry_count") or 0
        webhook_pending = result.get("webhook_pending") or 0

        debug(
            f"[CREDITS] user_id={user_id} status={plan_status} retry={retry_count} pending={webhook_pending}"
        )

        # 🚨 SE HOUVER WEBHOOK PENDENTE, NÃO MOSTRAR POPUP DE ERRO
        is_payment_failed = retry_count > 0 and webhook_pending == 0

        # Se estiver suspenso mas com webhook vindo, fingir que está ativo para o front (temporariamente)
        display_status = (
            "active"
            if (plan_status == "suspended" and webhook_pending == 1)
            else plan_status
        )

        credits_val = float(result["credits"])

        # Créditos totais do plano (da tabela plans ou fallback por tipo)
        monthly_credits = float(result.get("cumulative_credits") or 0)
        if monthly_credits <= 0:
            if result.get("plan_type") == "pro":
                monthly_credits = 20.0
            elif result.get("plan_type") == "scale":
                monthly_credits = 100.0
            else:
                monthly_credits = 10.0

        reset_credits = monthly_credits

        # Planos free/trial não têm limites de sessão/semana
        plan_type_val = result.get("plan_type", "free")
        has_usage_limits = plan_type_val not in ("free", "trial")

        session_limit = (
            (monthly_credits / 24 if monthly_credits > 0 else 0.0)
            if has_usage_limits
            else 0.0
        )
        week_limit = (
            (monthly_credits / 3 if monthly_credits > 0 else 0.0)
            if has_usage_limits
            else 0.0
        )

        # Dados de uso de sessão/semana (apenas para planos com limites)
        now = datetime.utcnow()
        session_td = timedelta(hours=3.5)
        week_td = timedelta(days=4)

        if not has_usage_limits:
            session_usage = 0.0
            week_usage = 0.0
            session_ends_at = None
            week_ends_at = None
            session_pct = 0.0
            week_pct = 0.0
        else:
            session_usage = float(result.get("current_session_usage") or 0)
            week_usage = float(result.get("current_week_usage") or 0)

            session_starts_raw = result.get("current_session_starts_at")
            week_starts_raw = result.get("current_week_starts_at")

            session_starts = (
                datetime.fromisoformat(session_starts_raw)
                if isinstance(session_starts_raw, str) and session_starts_raw
                else None
            )
            week_starts = (
                datetime.fromisoformat(week_starts_raw)
                if isinstance(week_starts_raw, str) and week_starts_raw
                else None
            )

            if session_starts is None or now >= session_starts + session_td:
                session_usage = 0.0
                session_starts = now
            if week_starts is None or now >= week_starts + week_td:
                week_usage = 0.0
                week_starts = now

            session_ends_at = (session_starts + session_td).isoformat()
            week_ends_at = (week_starts + week_td).isoformat()
            session_pct = (
                round(session_usage / session_limit, 6) if session_limit > 0 else 0.0
            )
            week_pct = round(week_usage / week_limit, 6) if week_limit > 0 else 0.0

        return {
            "credits": credits_val,
            "credits_available": credits_val,
            "reset_credits": reset_credits,
            "plan_status": display_status,
            "payment_failed": is_payment_failed,
            "subscription_id": result.get("subscription_id"),
            "plan_name": result.get("plan_name", "Free"),
            "plan_type": result.get("plan_type", "free"),
            # Usage por sessão (3h30)
            "session_usage": round(session_usage, 6),
            "session_limit": round(session_limit, 6),
            "session_pct": min(session_pct, 1.0),
            "session_ends_at": session_ends_at,
            # Usage semanal (7 dias)
            "week_usage": round(week_usage, 6),
            "week_limit": round(week_limit, 6),
            "week_pct": min(week_pct, 1.0),
            "week_ends_at": week_ends_at,
        }

    except HTTPException:
        raise
    except Exception as e:
        error(f"[SUBSCRIPTION] Erro ao buscar créditos: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@subscription_cancel_router.post("/retry-payment")
async def retry_payment(request: Request):
    """
    Tenta processar o pagamento novamente para uma subscrição suspensa ou com falha.
    Usa o cartão mais recente do usuário.
    """
    try:
        # Extrair user_id e client_id
        if request.scope.get("dev_bypass_enabled"):
            user_id = request.scope.get("dev_user_id", "1")
            client_id = request.scope.get("dev_client_id", "1")
        else:
            auth_service = get_auth_service()
            token = request.cookies.get("access_token")
            if not token:
                raise HTTPException(status_code=401)
            payload = auth_service.verify_token(token)
            if not payload:
                raise HTTPException(status_code=401)
            user_id = payload.get("user_id")
            client_id = payload.get("client_id")

        db = DatabaseManager()

        # 1. Buscar subscrição que precisa de retry (mais recente)
        sub = db.fetch_one(
            """
            SELECT subscription_id, plan_id, billing_cycle, stripe_customer_id, billing_id
            FROM billing_subscriptions
            WHERE client_id = :cid
            ORDER BY created_at DESC LIMIT 1
            """,
            {"cid": client_id},
        )

        if not sub:
            raise HTTPException(
                status_code=404,
                detail="Nenhuma assinatura encontrada para tentar novamente",
            )

        # 2. Buscar cartão principal (status_main = 1)
        card = db.fetch_one(
            "SELECT pagarme_card_id_encrypted as pm_id FROM cards WHERE user_id = :uid AND status_main = 1 ORDER BY created_at DESC LIMIT 1",
            {"uid": user_id},
        )
        if not card:
            # Fallback para o mais recente se não houver main (para dados legados)
            card = db.fetch_one(
                "SELECT pagarme_card_id_encrypted as pm_id FROM cards WHERE user_id = :uid ORDER BY created_at DESC LIMIT 1",
                {"uid": user_id},
            )

        if not card:
            raise HTTPException(
                status_code=404,
                detail="Nenhum cartão encontrado. Por favor, adicione um cartão primeiro.",
            )

        payment_method_id = decrypt_field(card["pm_id"])

        # 3. Buscar preço do plano via JOIN com prices (usando early_adopter)
        plan_query = """
            SELECT
                p.id,
                p.name,
                MAX(CASE WHEN pr.period = 'monthly' THEN pr.price END) as monthly_price,
                MAX(CASE WHEN pr.period = 'annual' THEN pr.price END) as annual_price
            FROM plans p
            LEFT JOIN prices pr ON p.plan_id = pr.plan_id
            WHERE p.plan_id = :pid AND pr.adoption_stage = 'early_adopter'
            GROUP BY p.id, p.name
        """
        plan = db.fetch_one(plan_query, {"pid": sub["plan_id"]})

        if not plan:
            raise HTTPException(
                status_code=404, detail="Plano ou preços não encontrados"
            )

        amount = (
            int(plan["annual_price"] * 100)
            if sub["billing_cycle"] == "annual"
            else int(plan["monthly_price"] * 100)
        )

        # 4. Tentar cobrança via Stripe
        stripe_service = get_stripe_payment_service()
        stripe_customer_id = sub.get("stripe_customer_id")

        # 4.1 Garantir que temos um Customer ID válido
        if not stripe_customer_id:
            debug(
                f"[RETRY] Subscrição sem stripe_customer_id, tentando buscar por email..."
            )
            user_data = db.fetch_one(
                "SELECT email, full_name FROM users WHERE user_id = :uid",
                {"uid": user_id},
            )

            import stripe

            stripe.api_key = load_config().get("stripe_secret_key")
            customers = stripe.Customer.list(email=user_data["email"], limit=1)

            if customers.data:
                stripe_customer_id = customers.data[0].id
                # Atualizar no banco para futuras chamadas
                db.execute_query(
                    "UPDATE billing_subscriptions SET stripe_customer_id = :cid WHERE subscription_id = :sid",
                    {"cid": stripe_customer_id, "sid": sub["subscription_id"]},
                )
            else:
                # Criar novo se não existir
                customer = stripe.Customer.create(
                    email=user_data["email"],
                    name=user_data["full_name"],
                    metadata={"user_id": str(user_id)},
                )
                stripe_customer_id = customer.id
                db.execute_query(
                    "UPDATE billing_subscriptions SET stripe_customer_id = :cid WHERE subscription_id = :sid",
                    {"cid": stripe_customer_id, "sid": sub["subscription_id"]},
                )

        # Se for ANUAL (Assinatura real no Stripe), podemos tentar atualizar o default PM
        if sub["billing_cycle"] == "annual":
            import stripe

            stripe.api_key = load_config().get("stripe_secret_key")
            try:
                # Attach PM ao customer se necessário e definir como default
                stripe.PaymentMethod.attach(
                    payment_method_id, customer=stripe_customer_id
                )
                stripe.Customer.modify(
                    stripe_customer_id,
                    invoice_settings={"default_payment_method": payment_method_id},
                )
            except Exception as e:
                debug(f"[RETRY] Erro ao atualizar default PM: {e}")

        # Cobrança off-session (Retry manual)
        success, charge_id, error_msg = stripe_service.charge_off_session(
            customer_id=stripe_customer_id,
            payment_method_id=payment_method_id,
            amount_cents=amount,
            description=f"Retry Pagamento: {plan['name']}",
            subscription_id=sub["subscription_id"],
        )

        if not success:
            return {
                "status": "error",
                "message": f"Falha na tentativa de cobrança: {error_msg}",
            }

        # SUCESSO DA SOLICITAÇÃO: Limpar APENAS o retry_count.
        # O status permanece o mesmo (ex: 'suspended') até o Webhook confirmar.
        db.execute_query(
            """
            UPDATE billing_subscriptions
            SET payment_retry_count = 0,
                last_payment_error = NULL,
                webhook_pending = 1,
                updated_at = datetime('now')
            WHERE subscription_id = :sid
            """,
            {"sid": sub["subscription_id"]},
        )

        info(
            f"[RETRY] Solicitação enviada e retries resetados - sub={sub['subscription_id']}"
        )

        return {
            "status": "success",
            "message": "Solicitação enviada! Aguarde a confirmação automática do sistema em instantes.",
        }

    except HTTPException:
        raise
    except Exception as e:
        error(f"[RETRY] Erro ao tentar processar pagamento: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ========================================================================
# 🔍 GET - RECUPERAR DADOS JÁ CADASTRADOS
# ========================================================================


@subscription_cancel_router.get("/billing", response_model=Dict[str, Any])
async def get_billing_info(request: Request):
    """
    Recupera informações de cobrança já cadastradas do usuário

    ✅ Uso: Front verifica se billing_info já existe
    ✅ Se existir, pode pré-preencher formulário ou pular etapa

    Returns:
        dict: billing_info (descriptografado) ou erro 404
    """
    try:
        # Extrair user_id
        if request.scope.get("dev_bypass_enabled"):
            user_id = 1
            debug(f"[SUBSCRIPTION] GET /billing - DEV_BYPASS: user_id={user_id}")
        else:
            auth_service = get_auth_service()
            token = request.cookies.get("access_token")
            if not token:
                raise HTTPException(status_code=401, detail="Token não fornecido")
            payload = auth_service.verify_token(token)
            if not payload:
                raise HTTPException(
                    status_code=401, detail="Token inválido ou expirado"
                )
            user_id = payload.get("user_id")
            if not user_id:
                raise HTTPException(
                    status_code=401, detail="User ID não encontrado no token"
                )
            debug(f"[SUBSCRIPTION] GET /billing - user_id={user_id}")

        db = DatabaseManager()

        # Buscar billing_info mais recente
        billing = db.fetch_one(
            """
            SELECT billing_id, address_encrypted, complement_encrypted,
                   neighborhood_encrypted, city_encrypted, state_encrypted, postal_code_encrypted,
                   phone_number_encrypted, document_encrypted, created_at
            FROM billing_info
            WHERE user_id = :user_id
            ORDER BY created_at DESC
            LIMIT 1
            """,
            {"user_id": user_id},
        )

        if not billing:
            raise HTTPException(
                status_code=404, detail="Nenhuma informação de cobrança cadastrada"
            )

        billing_id = billing.get("billing_id")
        addr_enc = billing.get("address_encrypted")
        comp_enc = billing.get("complement_encrypted")
        neighborhood_enc = billing.get("neighborhood_encrypted")
        city_enc = billing.get("city_encrypted")
        state_enc = billing.get("state_encrypted")
        postal_enc = billing.get("postal_code_encrypted")
        phone_enc = billing.get("phone_number_encrypted")
        doc_enc = billing.get("document_encrypted")

        # ✅ Descriptografar todos os campos
        address = decrypt_field(addr_enc)
        complement = decrypt_field(comp_enc) if comp_enc else None
        neighborhood = decrypt_field(neighborhood_enc)
        city = decrypt_field(city_enc)
        state = decrypt_field(state_enc)
        postal_code = decrypt_field(postal_enc)
        phone_number = decrypt_field(phone_enc)
        document = decrypt_field(doc_enc)

        info(
            f"[SUBSCRIPTION] GET /billing - user_id={user_id}, billing_id={billing_id}"
        )

        # Buscar email do usuário
        user = db.fetch_one(
            "SELECT email FROM users WHERE user_id = :user_id", {"user_id": user_id}
        )
        email = user.get("email") if user else None

        # Retornar dados sem criptografia
        response_data = {
            "status": "success",
            "billing_id": billing_id,
            "address": address,
            "complement": complement,
            "neighborhood": neighborhood,
            "city": city,
            "state": state,
            "postal_code": postal_code,
            "phone_number": phone_number,
            "document": document,
            "email": email,
            "message": "Informação de cobrança recuperada com sucesso",
        }

        return response_data

    except HTTPException:
        raise
    except Exception as e:
        error(f"[SUBSCRIPTION] Erro ao recuperar billing info: {e}")
        raise HTTPException(status_code=500, detail="Erro ao recuperar informações")


@subscription_cancel_router.get("/cards", response_model=Dict[str, Any])
async def get_user_cards(request: Request):
    """
    Recupera cartões cadastrados do usuário

    ✅ Uso: Front lista cartões disponíveis
    ✅ Front pode let user escolher qual usar ou registrar novo

    Returns:
        dict: Lista de cartões (sem dados sensíveis, apenas last_4 e brand)
    """
    try:
        # Extrair user_id
        if request.scope.get("dev_bypass_enabled"):
            user_id = 1
            debug(f"[SUBSCRIPTION] GET /cards - DEV_BYPASS: user_id={user_id}")
        else:
            auth_service = get_auth_service()
            token = request.cookies.get("access_token")
            if not token:
                raise HTTPException(status_code=401, detail="Token não fornecido")
            payload = auth_service.verify_token(token)
            if not payload:
                raise HTTPException(
                    status_code=401, detail="Token inválido ou expirado"
                )
            user_id = payload.get("user_id")
            if not user_id:
                raise HTTPException(
                    status_code=401, detail="User ID não encontrado no token"
                )
            debug(f"[SUBSCRIPTION] GET /cards - user_id={user_id}")

        db = DatabaseManager()

        # Buscar todos os cartões do usuário com todas as informações
        cards = db.fetch_all(
            """
            SELECT card_id, pagarme_card_id_encrypted, last_4, brand, holder_name, expires_at, created_at
            FROM cards
            WHERE user_id = :user_id
            ORDER BY created_at DESC
            """,
            {"user_id": user_id},
        )

        # ✅ 404 se não houver cartões (lista vazia)
        if not cards:
            raise HTTPException(status_code=404, detail="Nenhum cartão cadastrado")

        # Formatar resposta com informações completas
        cards_list = [
            {
                "card_id": card.get("card_id"),
                "payment_method_id": card.get(
                    "pagarme_card_id_encrypted"
                ),  # Stripe payment method (criptografado)
                "brand": card.get("brand"),
                "last_4": card.get("last_4"),
                "expires_at": card.get("expires_at"),
                "holder_name": card.get("holder_name"),
                "created_at": card.get("created_at"),
            }
            for card in cards
        ]

        info(f"[SUBSCRIPTION] GET /cards - user_id={user_id}, total={len(cards_list)}")

        return {"status": "success", "cards": cards_list, "count": len(cards_list)}

    except HTTPException:
        raise
    except Exception as e:
        error(f"[SUBSCRIPTION] Erro ao recuperar cartões: {e}")
        raise HTTPException(status_code=500, detail="Erro ao recuperar cartões")


@subscription_cancel_router.post("/tokenize-card", response_model=Dict[str, Any])
async def tokenize_card(request: Request, body: CardRequest):
    """
    Tokeniza um cartão diretamente com Pagarme.

    ✅ Fluxo:
    1. Frontend coleta dados do cartão
    2. Frontend envia para este endpoint
    3. Backend tokeniza com Pagarme (seguro - usa secret key)
    4. Frontend recebe card_id para uso em cobrança

    Args:
        body: CardRequest com dados brutos do cartão
              - card_number: Número do cartão
              - holder_name: Nome do titular
              - expiry_month: Mês de expiração
              - expiry_year: Ano de expiração
              - cvv: CVV/CVC

    Returns:
        dict: card_id tokenizado + detalhes do cartão
    """
    try:
        # Extrair user_id
        if request.scope.get("dev_bypass_enabled"):
            user_id = request.scope.get("dev_user_id", 1)
            debug(f"[SUBSCRIPTION] POST /tokenize-card - DEV_BYPASS: user_id={user_id}")
        else:
            auth_service = get_auth_service()
            token = request.cookies.get("access_token")
            if not token:
                raise HTTPException(status_code=401, detail="Token não fornecido")
            payload = auth_service.verify_token(token)
            if not payload:
                raise HTTPException(
                    status_code=401, detail="Token inválido ou expirado"
                )
            user_id = payload.get("user_id")
            if not user_id:
                raise HTTPException(
                    status_code=401, detail="User ID não encontrado no token"
                )
            debug(f"[SUBSCRIPTION] POST /tokenize-card - user_id={user_id}")

        # Receber dados do cartão sem criptografia
        card_number = body.card_number
        holder_name = body.holder_name
        expiry_month = int(body.expiry_month)
        expiry_year = int(body.expiry_year)
        cvv = body.cvv
        debug(
            f"[SUBSCRIPTION] POST /tokenize-card - expiry_year={expiry_year} (type={type(expiry_year).__name__})"
        )

        # Buscar dados de billing verdadeiros do usuário
        db = DatabaseManager()
        billing_info = db.fetch_one(
            "SELECT document_encrypted, phone_number_encrypted FROM billing_info WHERE user_id = :user_id",
            {"user_id": user_id},
        )

        # Extrair e descriptografar informações de billing (se existirem)
        user_document = None
        user_phone = None
        if billing_info:
            doc_encrypted = billing_info.get("document_encrypted")
            phone_encrypted = billing_info.get("phone_number_encrypted")
            if doc_encrypted:
                user_document = decrypt_field(doc_encrypted)
            if phone_encrypted:
                user_phone = decrypt_field(phone_encrypted)

        # Tokenizar cartão com Pagarme usando dados verdadeiros
        payment_service = get_payment_service()
        success, customer_id, error_msg = payment_service.validate_and_tokenize_card(
            card_number=card_number,
            holder_name=holder_name,
            expiry_month=expiry_month,
            expiry_year=expiry_year,
            cvv=cvv,
            user_document=user_document,
            user_phone=user_phone,
        )

        if not success:
            error(f"[SUBSCRIPTION] Falha ao tokenizar cartão: {error_msg}")
            raise HTTPException(
                status_code=400, detail=error_msg or "Falha ao tokenizar cartão"
            )

        # ✅ Cartão tokenizado com sucesso - usar informações do Pagarme
        card_info = customer_id  # Agora customer_id contém o dicionário com informações

        info(f"[SUBSCRIPTION] Cartão tokenizado com sucesso - {card_info}")

        # ✅ SALVAR cartão no banco de dados com informações completas
        internal_card_id = str(uuid_lib.uuid4())
        pagarme_card_id_encrypted = encrypt_field(card_info["card_id"])

        # Construir data de expiração (MM/YY) - SEMPRE usar valores de card_info
        exp_month = card_info.get("exp_month")
        exp_year = card_info.get("exp_year")

        if exp_month and exp_year:
            expires_at = f"{str(int(exp_month)).zfill(2)}/{str(int(exp_year))[-2:]}"
        else:
            error(
                f"[SUBSCRIPTION] Dados de expiração inválidos - exp_month={exp_month}, exp_year={exp_year}"
            )
            expires_at = None

        debug(
            f"[SUBSCRIPTION] Expiration date - exp_month={exp_month}, exp_year={exp_year}, expires_at={expires_at}"
        )

        db.execute_query(
            """
            INSERT INTO cards (card_id, user_id, pagarme_card_id_encrypted, last_4, brand, holder_name, expires_at, created_at, updated_at)
            VALUES (:card_id, :user_id, :pagarme_card_id_encrypted, :last_4, :brand, :holder_name, :expires_at, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            {
                "card_id": internal_card_id,
                "user_id": user_id,
                "pagarme_card_id_encrypted": pagarme_card_id_encrypted,
                "last_4": card_info.get("last_4"),
                "brand": card_info.get("brand"),
                "holder_name": card_info.get("holder_name"),
                "expires_at": expires_at,
            },
        )

        info(
            f"[SUBSCRIPTION] Cartão salvo no banco - internal_card_id={internal_card_id}"
        )

        return {
            "status": "success",
            "card_id": internal_card_id,
            "brand": card_info.get("brand"),
            "last_4": card_info.get("last_4"),
            "exp_month": card_info.get("exp_month"),
            "exp_year": card_info.get("exp_year"),
            "holder_name": card_info.get("holder_name"),
            "message": "Cartão tokenizado e salvo com sucesso!",
        }

    except HTTPException:
        raise
    except Exception as e:
        error(f"[SUBSCRIPTION] Erro ao tokenizar cartão: {e}")
        raise HTTPException(status_code=500, detail="Erro ao tokenizar cartão")


@subscription_cancel_router.post("/dev-tokenize-card", response_model=Dict[str, Any])
async def dev_tokenize_card(request: Request, body: CardRequest):
    """
    [DEV ONLY] Tokeniza cartão para testes sem SDK do Pagarme.

    Mimic frontend behavior: pegue dados de billing e tokenize o cartão direto.

    Returns:
        dict: card_id para usar em confirm-payment
    """
    # Only allow in dev bypass mode
    if not request.scope.get("dev_bypass_enabled"):
        raise HTTPException(
            status_code=403, detail="Esta rota é apenas para desenvolvimento"
        )

    try:
        user_id = request.scope.get("dev_user_id", "1")
        debug(f"[SUBSCRIPTION] POST /dev-tokenize-card - DEV_BYPASS: user_id={user_id}")

        db = DatabaseManager()

        # 1. Buscar dados de billing do usuário
        billing_info = db.fetch_one(
            "SELECT document_encrypted, phone_number_encrypted FROM billing_info WHERE user_id = :user_id",
            {"user_id": user_id},
        )

        if not billing_info:
            raise HTTPException(
                status_code=400,
                detail="Dados de faturamento não encontrados. Registre billing info primeiro.",
            )

        # 2. Descriptografar documento e telefone
        user_document = decrypt_field(billing_info.get("document_encrypted"))
        user_phone = decrypt_field(billing_info.get("phone_number_encrypted"))
        user_email = None  # PaymentService gera automaticamente se não houver

        # 3. Tokenizar com Pagarme
        payment_service = get_payment_service()
        success, customer_id, error_msg = payment_service.validate_and_tokenize_card(
            card_number=body.card_number,
            holder_name=body.holder_name,
            expiry_month=int(body.expiry_month),
            expiry_year=int(body.expiry_year),
            cvv=body.cvv,
            user_document=user_document,
            user_phone=user_phone,
            user_email=user_email,
        )

        if not success:
            error(f"[SUBSCRIPTION] DEV: Falha ao tokenizar cartão: {error_msg}")
            raise HTTPException(
                status_code=400, detail=error_msg or "Falha ao tokenizar cartão"
            )

        # 4. Salvar cartão tokenizado
        card_info = customer_id
        internal_card_id = str(uuid_lib.uuid4())
        pagarme_card_id_encrypted = encrypt_field(card_info["card_id"])

        exp_month = card_info.get("exp_month")
        exp_year = card_info.get("exp_year")

        if exp_month and exp_year:
            expires_at = f"{str(int(exp_month)).zfill(2)}/{str(int(exp_year))[-2:]}"
        else:
            expires_at = None

        pagarme_customer_id_encrypted = encrypt_field(card_info["customer_id"])
        debug(
            f"[SUBSCRIPTION] DEV: Salvando cartão - pagarme_customer_id={card_info['customer_id']}, pagarme_card_id={card_info['card_id']}"
        )

        db.execute_query(
            """
            INSERT INTO cards (card_id, user_id, pagarme_card_id_encrypted, pagarme_customer_id_encrypted, last_4, brand, holder_name, expires_at, created_at, updated_at)
            VALUES (:card_id, :user_id, :pagarme_card_id_encrypted, :pagarme_customer_id_encrypted, :last_4, :brand, :holder_name, :expires_at, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            {
                "card_id": internal_card_id,
                "user_id": user_id,
                "pagarme_card_id_encrypted": pagarme_card_id_encrypted,
                "pagarme_customer_id_encrypted": pagarme_customer_id_encrypted,
                "last_4": card_info.get("last_4"),
                "brand": card_info.get("brand"),
                "holder_name": card_info.get("holder_name"),
                "expires_at": expires_at,
            },
        )

        info(
            f"[SUBSCRIPTION] DEV: Cartão tokenizado e salvo - card_id={internal_card_id}"
        )

        return {
            "status": "success",
            "card_id": internal_card_id,
            "brand": card_info.get("brand"),
            "last_4": card_info.get("last_4"),
            "exp_month": card_info.get("exp_month"),
            "exp_year": card_info.get("exp_year"),
            "holder_name": card_info.get("holder_name"),
            "message": "Cartão tokenizado com sucesso!",
        }

    except HTTPException:
        raise
    except Exception as e:
        error(f"[SUBSCRIPTION] DEV: Erro ao tokenizar cartão: {e}")
        raise HTTPException(
            status_code=500, detail=f"Erro ao tokenizar cartão: {str(e)}"
        )


@subscription_cancel_router.post("/new-card", response_model=Dict[str, Any])
async def create_temp_card(request: Request, body: Optional[Dict] = None):
    """
    Cria um cartão TEMPORÁRIO (status='temp') para fluxo de tokenização.

    ⚠️ NOVO FLUXO:
    1. POST /new-card → Gera UUID temporário (status='temp')
    2. Front tokeniza cartão com Pagarme (PagarmeTokenizer)
    3. POST /new-card/info → Confirma e salva dados (status='valid')

    Returns:
        dict: card_id temporário para usar na próxima etapa
    """
    try:
        # Extrair user_id
        if request.scope.get("dev_bypass_enabled"):
            user_id = 1
            debug(f"[SUBSCRIPTION] POST /new-card - DEV_BYPASS: user_id={user_id}")
        else:
            auth_service = get_auth_service()
            token = request.cookies.get("access_token")
            if not token:
                raise HTTPException(status_code=401, detail="Token não fornecido")
            payload = auth_service.verify_token(token)
            if not payload:
                raise HTTPException(
                    status_code=401, detail="Token inválido ou expirado"
                )
            user_id = payload.get("user_id")
            if not user_id:
                raise HTTPException(
                    status_code=401, detail="User ID não encontrado no token"
                )
            debug(f"[SUBSCRIPTION] POST /new-card - user_id={user_id}")

        db = DatabaseManager()

        # ✅ Gerar UUID temporário
        temp_card_id = str(uuid_lib.uuid4())

        # ✅ Inserir cartão com status='temp' (sem dados do Pagarme ainda)
        db.execute_query(
            """
            INSERT INTO cards (card_id, user_id, status, created_at, updated_at)
            VALUES (:card_id, :user_id, 'temp', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            {"card_id": temp_card_id, "user_id": user_id},
        )

        info(
            f"[SUBSCRIPTION] Cartão temporário criado - user_id={user_id}, temp_card_id={temp_card_id}"
        )

        return {
            "status": "success",
            "card_id": temp_card_id,
            "message": "Cartão temporário criado. Prossiga com a tokenização.",
        }

    except HTTPException:
        raise
    except Exception as e:
        error(f"[SUBSCRIPTION] Erro ao criar cartão temporário: {e}")
        raise HTTPException(status_code=500, detail="Erro ao criar cartão temporário")


@subscription_cancel_router.post("/new-card/info", response_model=Dict[str, Any])
async def confirm_card_info(request: Request, body: NewCardInfoRequest):
    """
    Confirma e salva as informações do cartão após tokenização no Pagarme.

    ⚠️ FLUXO CORRETO:
    1. POST /new-card → Gera UUID temporário (status='temp')
    2. Front tokeniza cartão com PagarmeTokenizer
    3. POST /new-card/info → Confirma e salva dados (status='valid')

    Args:
        body: Dados do cartão retornados pelo Pagarme após tokenização
              - card_id: UUID temporário gerado em /new-card
              - pagarme_card_id: ID do cartão no Pagarme
              - pagarme_customer_id: ID do customer no Pagarme
              - brand, last_4, exp_month, exp_year, holder_name

    Returns:
        dict: Confirmação com card_id para uso em pagamentos
    """
    try:
        # Extrair user_id
        if request.scope.get("dev_bypass_enabled"):
            user_id = 1
            debug(f"[SUBSCRIPTION] POST /new-card/info - DEV_BYPASS: user_id={user_id}")
        else:
            auth_service = get_auth_service()
            token = request.cookies.get("access_token")
            if not token:
                raise HTTPException(status_code=401, detail="Token não fornecido")
            payload = auth_service.verify_token(token)
            if not payload:
                raise HTTPException(
                    status_code=401, detail="Token inválido ou expirado"
                )
            user_id = payload.get("user_id")
            if not user_id:
                raise HTTPException(
                    status_code=401, detail="User ID não encontrado no token"
                )
            debug(f"[SUBSCRIPTION] POST /new-card/info - user_id={user_id}")

        db = DatabaseManager()

        # ✅ Validar que o cartão temporário existe
        card = db.fetch_one(
            "SELECT card_id, status FROM cards WHERE card_id = :card_id AND user_id = :user_id",
            {"card_id": body.card_id, "user_id": user_id},
        )

        if not card:
            raise HTTPException(
                status_code=404, detail="Cartão temporário não encontrado"
            )

        if card.get("status") != "temp":
            raise HTTPException(
                status_code=400,
                detail="Cartão já foi confirmado ou está em estado inválido",
            )

        # ✅ Encriptar payment_method_id (token sensitivo do Stripe)
        payment_method_id_encrypted = encrypt_field(body.payment_method_id)

        # ✅ Calcular hash determinístico para deduplicação
        payment_method_hash = hash_payment_method(body.payment_method_id)

        # ✅ Formatar expires_at como MM/YY
        expires_at = (
            f"{str(body.exp_month).zfill(2)}/{str(body.exp_year)[-2:]}"
            if body.exp_month and body.exp_year
            else None
        )

        # ✅ 1. Definir este novo cartão como principal e desativar outros
        db.execute_query(
            "UPDATE cards SET status_main = 0 WHERE user_id = :user_id",
            {"user_id": user_id},
        )

        # ✅ 2. Atualizar cartão com dados do Stripe e mudar status para 'valid' e status_main = 1
        db.execute_query(
            """
            UPDATE cards
            SET pagarme_card_id_encrypted = :payment_method_id_encrypted,
                payment_method_hash = :payment_method_hash,
                brand = :brand,
                last_4 = :last_4,
                expires_at = :expires_at,
                holder_name = :holder_name,
                status = 'valid',
                status_main = 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE card_id = :card_id AND user_id = :user_id
            """,
            {
                "card_id": body.card_id,
                "user_id": user_id,
                "payment_method_id_encrypted": payment_method_id_encrypted,
                "payment_method_hash": payment_method_hash,
                "brand": body.brand,
                "last_4": body.last_4,
                "expires_at": expires_at,
                "holder_name": body.holder_name,
            },
        )

        info(
            f"[SUBSCRIPTION] Cartão confirmado - user_id={user_id}, card_id={body.card_id}, payment_method_id={body.payment_method_id}, brand={body.brand}, last_4={body.last_4}"
        )

        return {
            "status": "success",
            "card_id": body.card_id,
            "brand": body.brand,
            "last_4": body.last_4,
            "holder_name": body.holder_name,
            "message": "Cartão confirmado e pronto para uso!",
        }

    except HTTPException:
        raise
    except Exception as e:
        error(f"[SUBSCRIPTION] Erro ao confirmar cartão: {e}")
        raise HTTPException(status_code=500, detail="Erro ao confirmar cartão")


@subscription_cancel_router.post("/billing", response_model=Dict[str, Any])
async def register_billing_info(request: Request, body: BillingInfoRequest):
    """
    Registra informações de cobrança (INDEPENDENTE DE CARTÃO)

    ✅ Fluxo seguro:
    1. POST /billing → Coleta dados verdadeiros do usuário
    2. POST /new-card → Registra cartão (com dados de billing)
    3. POST /charge → Finaliza com cartão registrado

    Args:
        body: Dados de cobrança (endereço, telefone, documento, etc)

    Returns:
        dict: billing_id para usar em próximas etapas
    """
    try:
        # Extrair user_id
        if request.scope.get("dev_bypass_enabled"):
            user_id = request.scope.get("dev_user_id", 1)
            debug(f"[SUBSCRIPTION] POST /billing - DEV_BYPASS: user_id={user_id}")
        else:
            auth_service = get_auth_service()
            token = request.cookies.get("access_token")
            if not token:
                raise HTTPException(status_code=401, detail="Token não fornecido")
            payload = auth_service.verify_token(token)
            if not payload:
                raise HTTPException(
                    status_code=401, detail="Token inválido ou expirado"
                )
            user_id = payload.get("user_id")
            if not user_id:
                raise HTTPException(
                    status_code=401, detail="User ID não encontrado no token"
                )
            debug(f"[SUBSCRIPTION] POST /billing - user_id={user_id}")

        db = DatabaseManager()

        # Receber dados sem criptografia
        address = body.address
        complement = body.complement
        neighborhood = body.neighborhood
        city = body.city
        state = body.state
        postal_code = body.postal_code
        phone_number = body.phone_number
        document = body.document
        debug("[SUBSCRIPTION] POST /billing - Dados recebidos")

        # ✅ Carregar email do banco de dados (não vem do frontend)
        user_data = db.fetch_one(
            "SELECT email FROM users WHERE user_id = :user_id", {"user_id": user_id}
        )
        email = user_data.get("email") if user_data else None
        debug(f"[SUBSCRIPTION] Email carregado do DB: {email}")

        # ✅ Gerar billing_id único
        billing_id_uuid = str(uuid_lib.uuid4())

        # ✅ Re-encriptar com Fernet para salvar no banco (camada de armazenamento)
        address_encrypted = encrypt_field(address)
        complement_encrypted = encrypt_field(complement) if complement else None
        neighborhood_encrypted = encrypt_field(neighborhood)
        city_encrypted = encrypt_field(city)
        state_encrypted = encrypt_field(state)
        postal_code_encrypted = encrypt_field(postal_code)
        phone_number_encrypted = encrypt_field(phone_number)
        document_encrypted = encrypt_field(document)
        email_encrypted = encrypt_field(email) if email else None

        # ✅ Inserir billing_info (100% independente, sem card_id!)
        db.execute_query(
            """
            INSERT INTO billing_info (
                billing_id, user_id, address_encrypted, complement_encrypted,
                neighborhood_encrypted, city_encrypted, state_encrypted, postal_code_encrypted,
                phone_number_encrypted, document_encrypted, email_encrypted
            )
            VALUES (
                :billing_id, :user_id, :address_encrypted, :complement_encrypted,
                :neighborhood_encrypted, :city_encrypted, :state_encrypted, :postal_code_encrypted,
                :phone_number_encrypted, :document_encrypted, :email_encrypted
            )
            """,
            {
                "billing_id": billing_id_uuid,
                "user_id": user_id,
                "address_encrypted": address_encrypted,
                "complement_encrypted": complement_encrypted,
                "neighborhood_encrypted": neighborhood_encrypted,
                "city_encrypted": city_encrypted,
                "state_encrypted": state_encrypted,
                "postal_code_encrypted": postal_code_encrypted,
                "phone_number_encrypted": phone_number_encrypted,
                "document_encrypted": document_encrypted,
                "email_encrypted": email_encrypted,
            },
        )

        info(
            f"[SUBSCRIPTION] Informações de cobrança registradas - user_id={user_id}, billing_id={billing_id_uuid}"
        )

        return {
            "status": "success",
            "billing_id": billing_id_uuid,
            "message": "Informações de cobrança registradas com sucesso!",
        }

    except HTTPException:
        raise
    except Exception as e:
        error(f"[SUBSCRIPTION] Erro ao registrar informações de cobrança: {e}")
        raise HTTPException(
            status_code=500, detail="Erro ao registrar informações de cobrança"
        )


@subscription_cancel_router.post("/confirm-payment", response_model=Dict[str, Any])
async def confirm_payment(request: Request, body: ConfirmPaymentRequest):
    """
    Confirma pagamento e ativa plano.

    Fluxo:
    1. Valida billing_id, card_id (com pagarme_card_id tokenizado) e plan_id
    2. Cobra IMEDIATAMENTE no Pagarme
    3. Se sucesso: cria billing_subscription + atualiza plan do cliente
    4. Se falha: retorna erro sem criar nada

    Args:
        body: billing_id, card_id, plan_id, type (monthly/annual)

    Returns:
        dict: Status do pagamento e subscription_id se sucesso
    """
    try:
        # Extrair user_id
        if request.scope.get("dev_bypass_enabled"):
            user_id = request.scope.get("dev_user_id", 1)
            client_id = request.scope.get("dev_client_id", 1)
            debug(
                f"[SUBSCRIPTION] POST /confirm-payment - DEV_BYPASS: user_id={user_id}"
            )
        else:
            auth_service = get_auth_service()
            token = request.cookies.get("access_token")
            if not token:
                raise HTTPException(status_code=401, detail="Token não fornecido")
            payload = auth_service.verify_token(token)
            if not payload:
                raise HTTPException(
                    status_code=401, detail="Token inválido ou expirado"
                )
            user_id = payload.get("user_id")
            if not user_id:
                raise HTTPException(
                    status_code=401, detail="User ID não encontrado no token"
                )
            client_id = get_client_id_from_token(request)
            debug(
                f"[SUBSCRIPTION] POST /confirm-payment - user_id={user_id}, billing_id={body.billing_id}, card_id={body.card_id}, plan_id={body.plan_id}"
            )

        db = DatabaseManager()

        # 1. Validar billing_info pertence ao usuário
        billing = db.fetch_one(
            "SELECT billing_id FROM billing_info WHERE billing_id = :billing_id AND user_id = :user_id",
            {"billing_id": body.billing_id, "user_id": user_id},
        )

        if not billing:
            warning(
                f"[SUBSCRIPTION] Billing não encontrado - billing_id={body.billing_id}"
            )
            raise HTTPException(
                status_code=404, detail="Informações de cobrança não encontradas"
            )

        # 2. Validar cartão tokenizado pertence ao usuário
        card = db.fetch_one(
            "SELECT pagarme_card_id_encrypted, pagarme_customer_id_encrypted, last_4, brand, holder_name FROM cards WHERE card_id = :card_id AND user_id = :user_id",
            {"card_id": body.card_id, "user_id": user_id},
            table_name="cards",  # DBManager descriptografa automaticamente
        )

        if not card:
            warning(f"[SUBSCRIPTION] Cartão não encontrado - card_id={body.card_id}")
            raise HTTPException(status_code=404, detail="Cartão não encontrado")

        debug(f"[SUBSCRIPTION] Card found: {card}")
        pagarme_card_id = card.get("pagarme_card_id_encrypted")
        pagarme_customer_id = card.get(
            "pagarme_customer_id_encrypted"
        )  # Já descriptografado pelo DBManager
        card_last_4 = card.get("last_4")
        card_brand = card.get("brand")
        card_holder_name = card.get("holder_name")
        debug(
            f"[SUBSCRIPTION] pagarme_card_id={pagarme_card_id}, pagarme_customer_id={pagarme_customer_id}"
        )

        if not pagarme_card_id or not pagarme_customer_id:
            error(
                f"[SUBSCRIPTION] Cartão não está tokenizado - card_id={body.card_id} | pagarme_card_id={pagarme_card_id} | pagarme_customer_id={pagarme_customer_id}"
            )
            raise HTTPException(
                status_code=400, detail="Cartão não foi tokenizado corretamente"
            )

        # 3. Validar plano existe
        plan = db.fetch_one(
            "SELECT id, plan_id, name, monthly_price, annual_price, currency FROM plans WHERE (id = :plan_id OR plan_id = :plan_id) AND active = 1",
            {"plan_id": body.plan_id},
        )

        if not plan:
            warning(f"[SUBSCRIPTION] Plano não encontrado - plan_id={body.plan_id}")
            raise HTTPException(status_code=404, detail="Plano não encontrado")

        plan_id_uuid = plan.get("plan_id")
        plan_name = plan.get("name")
        monthly_price = plan.get("monthly_price")
        annual_price = plan.get("annual_price")
        currency = plan.get("currency")

        # 4. Calcular amount baseado no tipo (monthly/annual)
        amount = (
            int(annual_price * 100)
            if body.type == "annual"
            else int(monthly_price * 100)
        )
        description = f"Plano {plan_name} ({body.type})"
        coupon_id = None
        discount_amount = 0

        # 5. COBRAR IMEDIATAMENTE NO PAGARME
        payment_service = get_payment_service()
        subscription_id = str(uuid_lib.uuid4())

        # Descriptografar os valores do Pagarme antes de enviar
        pagarme_customer_id_decrypted = (
            decrypt_field(pagarme_customer_id)
            if isinstance(pagarme_customer_id, str)
            else pagarme_customer_id
        )
        pagarme_card_id_decrypted = (
            decrypt_field(pagarme_card_id)
            if isinstance(pagarme_card_id, str)
            else pagarme_card_id
        )

        # Obter billing info para PSP
        billing_info = db.fetch_one(
            "SELECT phone_number_encrypted, document_encrypted, address_encrypted, complement_encrypted, neighborhood_encrypted, postal_code_encrypted, city_encrypted, state_encrypted, email_encrypted FROM billing_info WHERE billing_id = :billing_id",
            {"billing_id": body.billing_id},
        )

        customer_phone = None
        customer_document = None
        billing_psp = None

        if billing_info:
            phone_encrypted = billing_info.get("phone_number_encrypted")
            if phone_encrypted:
                customer_phone_raw = decrypt_field(phone_encrypted)
                phone_cleaned = (
                    customer_phone_raw.replace("(", "")
                    .replace(")", "")
                    .replace("-", "")
                    .replace(" ", "")
                )
                if phone_cleaned.startswith("55") and len(phone_cleaned) > 2:
                    phone_cleaned = phone_cleaned[2:]
                if len(phone_cleaned) >= 10:
                    customer_phone = {
                        "country_code": "55",
                        "area_code": phone_cleaned[:2],
                        "number": phone_cleaned[2:],
                    }

            doc_encrypted = billing_info.get("document_encrypted")
            if doc_encrypted:
                customer_document = (
                    decrypt_field(doc_encrypted).replace(".", "").replace("-", "")
                )

            street = decrypt_field(billing_info.get("address_encrypted"))
            postal_code = decrypt_field(
                billing_info.get("postal_code_encrypted")
            ).replace("-", "")
            city = decrypt_field(billing_info.get("city_encrypted"))
            state = decrypt_field(billing_info.get("state_encrypted")).upper()
            neighborhood = decrypt_field(billing_info.get("neighborhood_encrypted"))
            email = decrypt_field(billing_info.get("email_encrypted"))

            billing_psp = {
                "name": card_holder_name or "Customer",
                "email": email,
                "document": customer_document,
                "address": {
                    "country": "BR",
                    "street": street,
                    "street_number": "1",
                    "state": state,
                    "city": city,
                    "neighborhood": neighborhood,
                    "zipcode": postal_code,
                },
            }

        success, charge_id, error_msg = payment_service.charge_subscription(
            subscription_id=subscription_id,
            customer_id=pagarme_customer_id_decrypted,
            card_id=pagarme_card_id_decrypted,
            amount=amount,
            description=description,
            customer_phone=customer_phone,
            customer_name=card_holder_name or "Customer",
            customer_document=customer_document,
            billing_psp=billing_psp,
        )

        if not success:
            warning(f"[SUBSCRIPTION] Cobrança falhou - {error_msg}")
            raise HTTPException(
                status_code=400, detail=f"Cobrança recusada: {error_msg}"
            )

        # 7. SUCESSO: Criar subscrição com status 'active' (ou 'pending' se preferir aguardar webhook 100%)
        # Mantendo 'active' aqui para compatibilidade com o front imediato,
        # mas a VERDADE (créditos e plano oficial) vem do Webhook.
        db.execute_query(
            """
            INSERT INTO billing_subscriptions (
                subscription_id, user_id, client_id, plan_id, card_id, billing_id,
                status, charge_id_pagarme, pagarme_customer_id, created_at, updated_at
            ) VALUES (
                :subscription_id, :user_id, :client_id, :plan_id, :card_id, :billing_id,
                'active', :charge_id_pagarme, :pagarme_customer_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """,
            {
                "subscription_id": subscription_id,
                "user_id": user_id,
                "client_id": client_id,
                "plan_id": plan_id_uuid,
                "card_id": body.card_id,
                "billing_id": body.billing_id,
                "charge_id_pagarme": charge_id,
                "pagarme_customer_id": pagarme_customer_id,
            },
        )

        # ⚠️ ATUALIZAÇÃO DE PLANO E CRÉDITOS REMOVIDOS DAQUI - Serão processados via Webhook

        info(
            f"[SUBSCRIPTION] Pagamento confirmado e subscrição registrada - user_id={user_id}, subscription_id={subscription_id}"
        )

        return {
            "status": "success",
            "subscription_id": subscription_id,
            "charge_id": charge_id,
            "plan_name": plan_name,
            "message": f"Plano {plan_name} ativado com sucesso! Seus créditos serão liberados em instantes.",
        }

    except HTTPException:
        raise
    except Exception as e:
        error(f"[SUBSCRIPTION] Erro em confirm-payment: {e}")
        import traceback

        debug(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Erro ao processar pagamento")


@subscription_cancel_router.post(
    "/{subscription_id}/cancel", response_model=Dict[str, Any]
)
async def cancel_subscription_post(request: Request, subscription_id: str):
    """
    Cancela uma subscrição via POST.

    Fluxo:
    - Até 7 dias: Refund completo + cancelar subscription
    - Após 7 dias: Apenas marcar como "no_renewal" (não renovar)

    Args:
        subscription_id: ID da subscrição a cancelar

    Returns:
        dict: Status do cancelamento
    """
    try:
        client_id = get_client_id_from_token(request)
        debug(
            f"[SUBSCRIPTION] POST /{subscription_id}/cancel - client_id={client_id}, subscription_id={subscription_id}"
        )

        db = DatabaseManager()
        stripe_service = get_stripe_payment_service()

        # 1. Buscar assinatura de cobrança completa
        billing_sub = db.fetch_one(
            """
            SELECT id, created_at, stripe_customer_id, billing_cycle, stripe_subscription_id, renewal_date
            FROM billing_subscriptions
            WHERE subscription_id = :subscription_id AND client_id = :client_id
            """,
            {"subscription_id": subscription_id, "client_id": client_id},
        )

        if not billing_sub:
            warning(
                f"[SUBSCRIPTION] Subscrição de cobrança não encontrada - subscription_id={subscription_id}"
            )
            raise HTTPException(status_code=404, detail="Subscrição não encontrada")

        created_at = billing_sub.get("created_at")
        billing_cycle = billing_sub.get("billing_cycle")

        # 2. Calcular dias desde a criação para verificar elegibilidade de reembolso (7 dias)
        created_dt = datetime.fromisoformat(created_at)
        days_since_creation = (datetime.now() - created_dt).days
        refund_eligible = days_since_creation <= 7

        debug(
            f"[SUBSCRIPTION] Análise de cancelamento - days_since={days_since_creation}, refund_eligible={refund_eligible}, billing_cycle={billing_cycle}"
        )

        # 3. Elegibilidade para refund até 7 dias (MONTHLY E ANNUAL)
        if refund_eligible:
            # 3A. REFUND: Buscar charge_id para fazer refund
            payment = db.fetch_one(
                "SELECT charge_id_stripe FROM payments WHERE subscription_id = :subscription_id LIMIT 1",
                {"subscription_id": subscription_id},
            )

            if payment and payment.get("charge_id_stripe"):
                charge_id = payment.get("charge_id_stripe")
                debug(
                    f"[SUBSCRIPTION] Iniciando refund ({billing_cycle}) - charge_id={charge_id}"
                )

                # Fazer refund no Stripe
                refund_success, refund_id = stripe_service.refund_charge(charge_id)
                if not refund_success:
                    warning(
                        f"[SUBSCRIPTION] Falha ao fazer refund - charge_id={charge_id}"
                    )
                    raise HTTPException(
                        status_code=400, detail="Falha ao processar reembolso"
                    )

                info(
                    f"[SUBSCRIPTION] Refund realizado - refund_id={refund_id}, charge_id={charge_id}"
                )

            # 3B. Cancelar no Stripe se for annual (monthly usa Payment Intent, não precisa)
            if billing_cycle == "annual":
                stripe_subscription_id = billing_sub.get("stripe_subscription_id")
                if stripe_subscription_id:
                    debug(
                        f"[SUBSCRIPTION] Cancelando Stripe subscription (annual com refund) - stripe_subscription_id={stripe_subscription_id}"
                    )
                    cancel_success, cancel_error = stripe_service.cancel_subscription(
                        stripe_subscription_id
                    )
                    if not cancel_success:
                        warning(
                            f"[SUBSCRIPTION] Falha ao cancelar subscription no Stripe: {cancel_error}"
                        )
                        raise HTTPException(
                            status_code=400,
                            detail="Falha ao cancelar subscription no Stripe",
                        )

            # 3C. Marcar como 'canceled' no BD
            db.execute_query(
                """
                UPDATE billing_subscriptions
                SET status = 'canceled', canceled_at = datetime('now'), updated_at = datetime('now')
                WHERE subscription_id = :subscription_id
                """,
                {"subscription_id": subscription_id},
            )

            # 3D. Rebaixar cliente para plano FREE imediatamente
            free_plan = db.fetch_one(
                "SELECT plan_id FROM plans WHERE plan_type = 'free' OR name = 'Free' LIMIT 1",
                {},
            )
            if free_plan:
                free_plan_id = free_plan.get("plan_id")
                debug(
                    f"[SUBSCRIPTION] Rebaixando cliente para plano FREE - client_id={client_id}, plan_id={free_plan_id}"
                )
                db.execute_query(
                    """
                    UPDATE clients
                    SET plan_id = :plan_id, updated_at = CURRENT_TIMESTAMP
                    WHERE client_id = :client_id
                    """,
                    {"plan_id": free_plan_id, "client_id": client_id},
                )
                info(
                    f"[SUBSCRIPTION] Cliente rebaixado para FREE - client_id={client_id}"
                )

            message = "Subscrição cancelada com reembolso realizado! Sua conta foi rebaixada para o plano Free."

        else:
            # 4. APÓS 7 DIAS: Apenas desabilitar renovação automática (sem refund)
            debug(
                f"[SUBSCRIPTION] Desabilitando renovação automática (passou de 7 dias)"
            )

            db.execute_query(
                """
                UPDATE billing_subscriptions
                SET auto_renew = 0, updated_at = datetime('now')
                WHERE subscription_id = :subscription_id
                """,
                {"subscription_id": subscription_id},
            )

            # Rebaixar cliente para plano FREE imediatamente
            free_plan = db.fetch_one(
                "SELECT plan_id FROM plans WHERE plan_type = 'free' OR name = 'Free' LIMIT 1",
                {},
            )
            if free_plan:
                free_plan_id = free_plan.get("plan_id")
                debug(
                    f"[SUBSCRIPTION] Rebaixando cliente para plano FREE - client_id={client_id}, plan_id={free_plan_id}"
                )
                db.execute_query(
                    """
                    UPDATE clients
                    SET plan_id = :plan_id, updated_at = CURRENT_TIMESTAMP
                    WHERE client_id = :client_id
                    """,
                    {"plan_id": free_plan_id, "client_id": client_id},
                )
                info(
                    f"[SUBSCRIPTION] Cliente rebaixado para FREE - client_id={client_id}"
                )

            message = "Subscrição marcada para não renovar. Sua conta foi rebaixada para o plano Free."

        # 5. Log de cancelamento
        import uuid as uuid_lib

        log_id = str(uuid_lib.uuid4())
        db.execute_query(
            """
            INSERT OR IGNORE INTO subscription_logs (
                client_id, old_plan_id, new_plan_id, event, changed_by, notes
            ) VALUES (
                :client_id, NULL, NULL, 'canceled', 'user',
                :notes
            )
            """,
            {
                "client_id": client_id,
                "notes": f"Subscrição cancelada - {'com refund' if refund_eligible else 'sem refund (passado de 7 dias)'}",
            },
        )

        info(
            f"[SUBSCRIPTION] Subscrição cancelada - subscription_id={subscription_id}, days_since={days_since_creation}, refund_eligible={refund_eligible}"
        )

        return {
            "status": "success",
            "subscription_id": subscription_id,
            "message": message,
            "days_since_creation": days_since_creation,
            "refund_eligible": refund_eligible,
        }

    except HTTPException:
        raise
    except Exception as e:
        error(f"[SUBSCRIPTION] Erro ao cancelar subscrição: {e}")
        raise HTTPException(status_code=500, detail="Erro ao cancelar subscrição")


@subscription_router.delete("/{subscription_id}/cancel", response_model=Dict[str, Any])
async def cancel_subscription(request: Request, subscription_id: str):
    """
    Cancela uma subscrição.
    - Se dentro de 7 dias: não cobra
    - Se após 7 dias: cobrança já foi feita

    Args:
        subscription_id: ID da subscrição a cancelar

    Returns:
        dict: Status do cancelamento
    """
    try:
        client_id = get_client_id_from_token(request)
        debug(
            f"[SUBSCRIPTION] DELETE /{subscription_id}/cancel - client_id={client_id}"
        )

        db = DatabaseManager()

        # 1. Buscar subscrição
        sub = db.fetch_one(
            "SELECT id, status, charge_scheduled_at FROM billing_subscriptions WHERE subscription_id = :subscription_id AND client_id = :client_id",
            {"subscription_id": subscription_id, "client_id": client_id},
        )

        if not sub:
            warning(
                f"[SUBSCRIPTION] Subscrição não encontrada - subscription_id={subscription_id}"
            )
            raise HTTPException(status_code=404, detail="Subscrição não encontrada")

        sub_id, status, charge_scheduled_at = sub

        if status == "canceled":
            warning(
                f"[SUBSCRIPTION] Subscrição já cancelada - subscription_id={subscription_id}"
            )
            raise HTTPException(status_code=400, detail="Subscrição já foi cancelada")

        # 2. Cancelar subscrição
        db.execute_query(
            """
            UPDATE billing_subscriptions
            SET status = 'canceled', canceled_at = datetime('now'), updated_at = datetime('now')
            WHERE subscription_id = :subscription_id
            """,
            {"subscription_id": subscription_id},
        )

        # 3. Rebaixar cliente para plano FREE imediatamente
        free_plan = db.fetch_one(
            "SELECT plan_id FROM plans WHERE plan_type = 'free' OR name = 'Free' LIMIT 1",
            {},
        )
        if free_plan:
            free_plan_id = free_plan.get("plan_id")
            debug(
                f"[SUBSCRIPTION] Rebaixando cliente para plano FREE - client_id={client_id}, plan_id={free_plan_id}"
            )
            db.execute_query(
                """
                UPDATE clients
                SET plan_id = :plan_id, updated_at = CURRENT_TIMESTAMP
                WHERE client_id = :client_id
                """,
                {"plan_id": free_plan_id, "client_id": client_id},
            )
            info(f"[SUBSCRIPTION] Cliente rebaixado para FREE - client_id={client_id}")

        # 4. Verificar se foi dentro do período de 7 dias
        charge_dt = datetime.fromisoformat(charge_scheduled_at)
        days_until_charge = (charge_dt - datetime.now()).days
        within_7_days = days_until_charge >= 0

        info(
            f"[SUBSCRIPTION] Subscrição cancelada - subscription_id={subscription_id}, within_7_days={within_7_days}"
        )

        return {
            "status": "success",
            "subscription_id": subscription_id,
            "message": "Subscrição cancelada com sucesso. Sua conta foi rebaixada para o plano Free.",
            "refund_eligible": within_7_days,
        }

    except HTTPException:
        raise
    except Exception as e:
        error(f"[SUBSCRIPTION] Erro ao cancelar subscrição: {e}")
        raise HTTPException(status_code=500, detail="Erro ao cancelar subscrição")


# ========================================================================
# 💳 ROTAS DE PAGAMENTO COM RETRY
# ========================================================================


@subscription_router.post("/api/subscription/{plan_id}/charge")
async def charge_subscription_with_retry(
    request: Request, plan_id: str, payment_method: str = "credit_card"
):
    """
    Cria um pagamento com retry automático (backoff exponencial)

    Fluxo:
    1. Cria entry em `payments` table
    2. Tenta cobrar no Pagarme com idempotency
    3. Se falhar, agenda retry automático
    4. Webhook monitora status e atualiza
    """
    try:
        user_id = await get_user_id_from_token(request)

        if not user_id:
            raise HTTPException(status_code=401, detail="Não autenticado")

        db_manager = DatabaseManager()

        # Buscar subscrição ativa
        subscription = db_manager.fetch_one(
            "SELECT subscription_id, customer_id, card_id, user_id FROM billing_subscriptions WHERE user_id=? AND status='active'",
            (user_id,),
        )

        if not subscription:
            raise HTTPException(
                status_code=404, detail="Nenhuma subscrição ativa encontrada"
            )

        subscription_id, customer_id, card_id, sub_user_id = subscription

        # Buscar plano - busca por numeric ID ou string plan_id
        plan = db_manager.fetch_one(
            "SELECT id, name, price FROM plans WHERE id=? OR plan_id=?",
            (plan_id, plan_id),
        )

        if not plan:
            raise HTTPException(status_code=404, detail="Plano não encontrado")

        plan_id, plan_name, price = plan
        amount_cents = int(price * 100)

        # Criar payment com retry automático
        payment_service = get_payment_service()
        success, payment_id, error_msg = payment_service.charge_subscription_with_retry(
            subscription_id=subscription_id,
            user_id=user_id,
            customer_id=customer_id,
            card_id=card_id,
            amount=amount_cents,
            description=f"Cobrança de {plan_name}",
        )

        if success:
            info(f"[SUBSCRIPTION] Payment criado com sucesso - payment_id={payment_id}")
            return {
                "status": "pending",
                "payment_id": payment_id,
                "message": "Pagamento em processamento. Aguarde confirmação via webhook.",
            }
        else:
            warning(f"[SUBSCRIPTION] Falha ao criar payment - {error_msg}")
            return {
                "status": "failed",
                "payment_id": payment_id,
                "error": error_msg,
                "message": "Falha ao processar pagamento. Será retentado automaticamente.",
            }, 400

    except HTTPException:
        raise
    except Exception as e:
        error(f"[SUBSCRIPTION] Erro ao cobrar subscrição: {e}")
        raise HTTPException(status_code=500, detail="Erro ao processar pagamento")


# ========================================================================
# 🪝 WEBHOOK - PAGARME
# ========================================================================


@webhook_router.get("/pagarme")
async def health_check_pagarme_webhook():
    """Health check para verificar se webhook está acessível"""
    return {"status": "ok", "version": "1.0"}


@webhook_router.post("/pagarme")
async def handle_pagarme_webhook(request: Request):
    """
    Recebe eventos em tempo real do Pagarme

    Eventos suportados:
    - charge.paid → Atualiza payment como pago
    - charge.failed → Agenda retry
    - charge.refunded → Processa reembolso
    """
    try:
        info("[WEBHOOK] Webhook POST recebida!")

        # Obter corpo bruto (necessário para validação de assinatura)
        body_bytes = await request.body()
        body_str = body_bytes.decode("utf-8")

        # Obter signature header
        signature = request.headers.get("X-Pagar-Me-Signature", "")
        debug(
            f"[WEBHOOK] Header X-Pagar-Me-Signature: {signature[:50] if signature else 'VAZIO'}..."
        )

        if not signature:
            warning("[WEBHOOK] Requisição sem assinatura")
            raise HTTPException(status_code=401, detail="Assinatura inválida")

        # Validar assinatura
        payment_service = get_payment_service()
        if not payment_service.validate_webhook_signature(body_str, signature):
            warning("[WEBHOOK] Assinatura inválida - possível ataque!")
            raise HTTPException(status_code=401, detail="Assinatura inválida")

        # Parse JSON
        webhook_data = json.loads(body_str)

        # Processar evento
        event_type = webhook_data.get("type")
        debug(f"[WEBHOOK] Evento recebido: {event_type}")

        success = await payment_service.handle_webhook_event(webhook_data)

        if success:
            info(f"[WEBHOOK] Evento processado com sucesso: {event_type}")
            return {"status": "ok", "message": "Webhook processada com sucesso"}
        else:
            warning(f"[WEBHOOK] Erro ao processar evento: {event_type}")
            # Ainda retorna 200 pois Pagarme vai reenviar
            return {"status": "error", "message": "Erro ao processar webhook"}

    except json.JSONDecodeError:
        error("[WEBHOOK] JSON inválido recebido")
        raise HTTPException(status_code=400, detail="JSON inválido")
    except HTTPException:
        raise
    except Exception as e:
        error(f"[WEBHOOK] Erro ao processar webhook: {e}")
        # Retornar 200 mesmo em erro para Pagarme reenviar
        return {"status": "error", "message": str(e)}


# ========================================================================
# 📊 CHECKOUT TRACKING - Rastrear funnel de usuários no carrinho
# ========================================================================


@subscription_cancel_router.post("/{plan_id}/", response_model=Dict[str, Any])
async def track_checkout_view(request: Request, plan_id: str):
    """
    Registra quando um usuário visualiza/chega no checkout para um plano.

    Args:
        plan_id: ID do plano (número ou string como "pro")

    Returns:
        dict: tracking_id e status da rastreamento
    """
    try:
        # Extrair client_id do token (mesmo método usado em ChatRoutes)
        from App.Core.Services.Chat.ChatRoutes import get_client_id_from_token

        client_id = get_client_id_from_token(request)
        debug(f"[CHECKOUT_TRACKING] client_id extraído do token: {client_id}")

        # Buscar user_id associado ao client_id
        db = DatabaseManager()
        user_query = """
        SELECT u.user_id FROM users u
        WHERE u.client_id = :client_id
        LIMIT 1
        """
        user_result = db.fetch_one(user_query, {"client_id": client_id})

        if not user_result:
            warning(
                f"[CHECKOUT_TRACKING] ❌ user_id não encontrado para client_id={client_id}"
            )
            raise HTTPException(status_code=401, detail="Usuário não encontrado")

        user_id = user_result.get("user_id")
        debug(f"[CHECKOUT_TRACKING] user_id encontrado: {user_id}")

        # 1. Validar plano existe - buscar preço da nova tabela prices
        plan = db.fetch_one(
            """
            SELECT
                p.id,
                p.plan_id as plan_uuid,
                p.name,
                pr.price as monthly_price
            FROM plans p
            LEFT JOIN prices pr ON p.plan_id = pr.plan_id
            WHERE (p.plan_id = :plan_id OR p.id = :plan_id)
              AND pr.period = 'monthly'
              AND pr.adoption_stage = 'late_adopter'
            LIMIT 1
            """,
            {"plan_id": plan_id},
        )

        if not plan:
            warning(f"[CHECKOUT_TRACKING] Plano não encontrado - plan_id={plan_id}")
            raise HTTPException(status_code=404, detail="Plano não encontrado")

        # 2. Extrair informações do dispositivo/navegador
        user_agent = request.headers.get("User-Agent", "unknown")
        referrer = request.headers.get("Referer", None)

        # Tentar extrair IP real (pode estar atrás de proxy)
        x_forwarded_for = request.headers.get("X-Forwarded-For", None)
        ip_address = (
            x_forwarded_for.split(",")[0].strip()
            if x_forwarded_for
            else request.client.host
            if request.client
            else "unknown"
        )

        # Extrair informações de dispositivo (pode vir do body ou headers)
        device_info = request.headers.get("X-Device-Info", "web")

        # 3. Gerar tracking_id único
        tracking_id = str(uuid_lib.uuid4())

        # 4. Inserir no banco
        # user_id pode ser None para usuários anônimos (constraint ON DELETE SET NULL permite)

        db.execute_query(
            """
            INSERT INTO checkout_tracking_logs (
                tracking_id, user_id, plan_id, plan_name, plan_price,
                device_info, user_agent, ip_address, referrer, status,
                created_at, updated_at
            ) VALUES (
                :tracking_id, :user_id, :plan_uuid, :plan_name, :plan_price,
                :device_info, :user_agent, :ip_address, :referrer, 'viewed',
                datetime('now'), datetime('now')
            )
            """,
            {
                "tracking_id": tracking_id,
                "user_id": user_id,
                "plan_uuid": plan.get("plan_uuid"),
                "plan_name": plan.get("name"),
                "plan_price": plan.get("monthly_price"),
                "device_info": device_info,
                "user_agent": user_agent,
                "ip_address": ip_address,
                "referrer": referrer,
            },
        )

        info(
            f"[CHECKOUT_TRACKING] Rastreamento criado - tracking_id={tracking_id}, plan_id={plan_id}, user_id={user_id}"
        )

        return {
            "status": "success",
            "tracking_id": tracking_id,
            "plan_id": plan_id,
            "plan_name": plan.get("name"),
            "message": "Rastreamento iniciado",
        }

    except HTTPException:
        raise
    except Exception as e:
        error(f"[CHECKOUT_TRACKING] Erro ao rastrear checkout: {e}")
        raise HTTPException(status_code=500, detail="Erro ao rastrear checkout")


@subscription_cancel_router.post("/track/update", response_model=Dict[str, Any])
async def update_checkout_tracking_logs(body: CheckoutTrackingUpdateRequest):
    """
    Atualiza o status do rastreamento conforme usuário progride no fluxo.

    Statuses válidos:
    - viewed: Usuário visualizou o checkout
    - billing_started: Começou a preencher dados de cobrança
    - card_registered: Registrou um cartão
    - payment_completed: Pagamento completado
    - abandoned: Abandonou o carrinho

    Args:
        body: CheckoutTrackingUpdateRequest com tracking_id e novo status

    Returns:
        dict: Status da atualização
    """
    try:
        db = DatabaseManager()

        # Validar status
        valid_statuses = [
            "viewed",
            "billing_started",
            "card_registered",
            "payment_completed",
            "abandoned",
        ]
        if body.status not in valid_statuses:
            warning(f"[CHECKOUT_TRACKING] Status inválido: {body.status}")
            raise HTTPException(
                status_code=400,
                detail=f"Status inválido. Deve ser um de: {', '.join(valid_statuses)}",
            )

        # 1. Verificar se rastreamento existe
        tracking = db.fetch_one(
            "SELECT tracking_id, status FROM checkout_tracking_logs WHERE tracking_id = :tracking_id",
            {"tracking_id": body.tracking_id},
        )

        if not tracking:
            warning(
                f"[CHECKOUT_TRACKING] Rastreamento não encontrado - tracking_id={body.tracking_id}"
            )
            raise HTTPException(status_code=404, detail="Rastreamento não encontrado")

        old_status = tracking.get("status")

        # 2. Atualizar status
        db.execute_query(
            "UPDATE checkout_tracking_logs SET status = :status, updated_at = datetime('now') WHERE tracking_id = :tracking_id",
            {"status": body.status, "tracking_id": body.tracking_id},
        )

        info(
            f"[CHECKOUT_TRACKING] Status atualizado - tracking_id={body.tracking_id}, {old_status} → {body.status}"
        )

        return {
            "status": "success",
            "tracking_id": body.tracking_id,
            "old_status": old_status,
            "new_status": body.status,
            "message": f"Status atualizado de {old_status} para {body.status}",
        }

    except HTTPException:
        raise
    except Exception as e:
        error(f"[CHECKOUT_TRACKING] Erro ao atualizar rastreamento: {e}")
        raise HTTPException(status_code=500, detail="Erro ao atualizar rastreamento")


async def get_user_id_from_token(request: Request) -> Optional[int]:
    """Extrai user_id do token JWT ou dev bypass"""
    # Dev bypass
    if request.scope.get("dev_bypass_enabled"):
        debug("[AUTH] Dev bypass ativado")
        return request.scope.get("dev_user_id", 1)

    # JWT token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        # TODO: Validar JWT e extrair user_id
        # Por enquanto, retornar None para forçar error
        return None

    return None


# ========================================================================
# STRIPE WEBHOOKS
# ========================================================================

stripe_webhook_router = APIRouter(prefix=WEBHOOK_PREFIX, tags=["stripe-webhook"])


@stripe_webhook_router.get("/stripe")
async def stripe_webhook_health():
    """Health check para verificar se o endpoint de webhook Stripe está acessível"""
    return {
        "status": "ok",
        "version": "1.0",
        "message": "Stripe Webhook endpoint is active",
    }


@stripe_webhook_router.post("/stripe")
async def stripe_webhook(request: Request):
    """
    Webhook para eventos do Stripe.

    Fluxo:
    1. Valida assinatura Stripe-Signature
    2. Processa evento
    3. Atualiza status da subscrição no banco

    Configurar em: https://dashboard.stripe.com/webhooks
    URL: https://unelaborate-unselfishly-felton.ngrok-free.dev/webhook/stripe

    Eventos rastreados:
    - checkout.session.completed       → ativa subscrição após checkout
    - customer.subscription.created    → registra stripe_subscription_id no banco
    - customer.subscription.deleted    → revoga acesso (status=cancelled)
    - customer.subscription.trial_will_end → alerta de trial encerrando em 3 dias
    - invoice.finalized                → invoice pronta aguardando cobrança
    - invoice.payment_failed           → cobrança recorrente falhou (status=past_due)
    - invoice.payment_succeeded        → cobrança recorrente aprovada (status=active)
    - payment_intent.succeeded         → pagamento pontual aprovado
    - payment_intent.payment_failed    → pagamento pontual recusado
    - charge.refunded                  → reembolso processado
    - charge.dispute.created           → disputa/chargeback aberta
    """
    try:
        # Obter body bruto e assinatura
        body = await request.body()
        signature = request.headers.get("stripe-signature")

        if not signature:
            warning("[STRIPE_WEBHOOK] Header stripe-signature não encontrado")
            raise HTTPException(
                status_code=400, detail="Missing stripe-signature header"
            )

        debug(f"[STRIPE_WEBHOOK] Webhook recebida - signature={signature[:50]}...")

        # Validar assinatura
        stripe_service = get_stripe_payment_service()
        is_valid = stripe_service.validate_webhook_signature(body.decode(), signature)

        if not is_valid:
            error("[STRIPE_WEBHOOK] Assinatura INVÁLIDA!")
            raise HTTPException(status_code=403, detail="Invalid signature")

        # Parsear evento
        event_data = json.loads(body)
        event_type = event_data.get("type")

        debug(f"[STRIPE_WEBHOOK] Evento validado - type={event_type}")

        # Processar evento
        success = await stripe_service.handle_webhook_event(event_data)

        if not success:
            error(f"[STRIPE_WEBHOOK] Falha ao processar evento - type={event_type}")
            raise HTTPException(status_code=500, detail="Failed to process event")

        info(f"[STRIPE_WEBHOOK] Evento processado com sucesso - type={event_type}")

        return {"status": "success", "received": True}

    except HTTPException:
        raise
    except Exception as e:
        error(f"[STRIPE_WEBHOOK] Erro ao processar webhook: {e}")
        import traceback

        error(f"[STRIPE_WEBHOOK] Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Webhook processing failed")


# ========================================================================
# STRIPE INTEGRATION
# ========================================================================


class StripeCreatePaymentIntentRequest(BaseModel):
    """Request para criar payment intent no Stripe"""

    plan_id: Union[int, str] = Field(..., description="ID do plano")
    type: str = Field(..., description="'monthly' ou 'annual'")
    coupon: Optional[str] = Field(None, description="Código do cupom (opcional)")
    billing_email: str = Field(..., description="Email para faturamento")


class StripeConfirmPaymentRequest(BaseModel):
    """Request para confirmar pagamento no Stripe"""

    intent_id: str = Field(..., description="ID do Payment Intent do Stripe")
    card_id: str = Field(..., description="UUID do cartão registrado em /new-card/info")
    plan_id: Union[int, str] = Field(..., description="ID do plano")
    type: str = Field(..., description="'monthly' ou 'annual'")


stripe_router = APIRouter(prefix="/api/stripe", tags=["stripe"])


@stripe_router.post("/create-payment-intent", response_model=Dict[str, Any])
async def stripe_create_payment_intent(
    request: Request, body: StripeCreatePaymentIntentRequest
):
    """
    Cria um Payment Intent no Stripe para cobrança de plano.

    Fluxo:
    1. Valida plan_id e calcula amount
    2. Cria Payment Intent no Stripe
    3. Retorna client_secret para confirmação no frontend

    Args:
        body: plan_id, type (monthly/annual), coupon (opcional), billing_email

    Returns:
        dict: intent_id, client_secret e details
    """
    try:
        # Extrair user_id
        if request.scope.get("dev_bypass_enabled"):
            user_id = request.scope.get("dev_user_id", 1)
            client_id = request.scope.get("dev_client_id", 1)
            debug(
                f"[STRIPE] POST /create-payment-intent - DEV_BYPASS: user_id={user_id}"
            )
        else:
            auth_service = get_auth_service()
            token = request.cookies.get("access_token")
            if not token:
                raise HTTPException(status_code=401, detail="Token não fornecido")
            payload = auth_service.verify_token(token)
            if not payload:
                raise HTTPException(
                    status_code=401, detail="Token inválido ou expirado"
                )
            user_id = payload.get("user_id")
            if not user_id:
                raise HTTPException(
                    status_code=401, detail="User ID não encontrado no token"
                )
            client_id = get_client_id_from_token(request)
            debug(
                f"[STRIPE] POST /create-payment-intent - user_id={user_id}, plan_id={body.plan_id}"
            )

        db = DatabaseManager()

        # 1. Validar plano existe - buscar preços da tabela prices
        # Usar sempre early_adopter (preço promocional de lançamento)
        plan = db.fetch_one(
            """
            SELECT
                p.id,
                p.plan_id,
                p.name,
                MAX(CASE WHEN pr.period = 'monthly' THEN pr.price END) as monthly_price,
                MAX(CASE WHEN pr.period = 'annual' THEN pr.price END) as annual_price
            FROM plans p
            LEFT JOIN prices pr ON p.plan_id = pr.plan_id
            WHERE (p.id = :plan_id OR p.plan_id = :plan_id) AND p.active = 1 AND pr.adoption_stage = 'early_adopter'
            GROUP BY p.id, p.plan_id, p.name
            """,
            {"plan_id": body.plan_id},
        )

        if not plan:
            warning(f"[STRIPE] Plano não encontrado - plan_id={body.plan_id}")
            raise HTTPException(status_code=404, detail="Plano não encontrado")

        plan_id_db = plan.get("id")
        plan_name = plan.get("name")
        monthly_price = plan.get("monthly_price")
        annual_price = plan.get("annual_price")
        currency = "brl"  # Moeda padrão Brasil

        # 2. Calcular amount (usando early_adopter)
        amount = (
            int(annual_price * 100)
            if body.type == "annual"
            else int(monthly_price * 100)
        )
        description = f"Plano {plan_name} ({body.type})"
        coupon_id = None
        discount_amount = 0

        # 2.1 Validar e aplicar cupom se fornecido
        if body.coupon:
            coupon = db.fetch_one(
                "SELECT id, code, discount_type, discount_value, active, valid_from, valid_until FROM coupons WHERE code = :code",
                {"code": body.coupon.strip().upper()},
            )

            if not coupon:
                warning(f"[STRIPE] Cupom não encontrado - code={body.coupon}")
                raise HTTPException(status_code=400, detail="Cupom inválido")

            coupon_id = coupon.get("id")
            is_active = coupon.get("active")
            valid_from = coupon.get("valid_from")
            valid_until = coupon.get("valid_until")
            discount_type = coupon.get("discount_type")
            discount_value = coupon.get("discount_value")

            if not is_active:
                warning(f"[STRIPE] Cupom inativo - code={body.coupon}")
                raise HTTPException(status_code=400, detail="Cupom não está ativo")

            now = datetime.now().isoformat()
            if valid_from and now < valid_from:
                warning(f"[STRIPE] Cupom não está válido ainda - code={body.coupon}")
                raise HTTPException(
                    status_code=400, detail="Cupom não está válido ainda"
                )

            if valid_until and now > valid_until:
                warning(f"[STRIPE] Cupom expirado - code={body.coupon}")
                raise HTTPException(status_code=400, detail="Cupom expirado")

            if discount_type == "percentage":
                discount_amount = int(amount * (discount_value / 100))
            else:
                discount_amount = int(discount_value * 100)

            discount_amount = min(discount_amount, amount)
            amount = amount - discount_amount

            description += f" (Cupom: {body.coupon})"
            info(
                f"[STRIPE] Cupom aplicado - code={body.coupon}, discount={discount_amount/100}"
            )

        # 3. Criar Payment Intent no Stripe
        stripe_service = get_stripe_payment_service()

        # 🚨 GERAR ID ÚNICO PARA PERSISTIR ANTES DO WEBHOOK
        stable_subscription_id = str(uuid_lib.uuid4())

        metadata = {
            "user_id": str(user_id),
            "plan_id": str(plan_id_db),
            "plan_type": body.type,
            "coupon_id": str(coupon_id) if coupon_id else None,
        }

        success, intent_data, error_msg = stripe_service.create_payment_intent(
            subscription_id=stable_subscription_id,
            user_id=user_id,
            amount=amount,
            customer_email=body.billing_email,
            customer_name="Customer",
            description=description,
            metadata=metadata,
        )

        if not success:
            error(f"[STRIPE] Falha ao criar payment intent - {error_msg}")
            raise HTTPException(
                status_code=400, detail=f"Erro ao criar pagamento: {error_msg}"
            )

        info(
            f"[STRIPE] Payment intent criado com sucesso - intent_id={intent_data['intent_id']}"
        )

        return {
            "status": "success",
            "intent_id": intent_data["intent_id"],
            "subscription_id": stable_subscription_id,
            "client_secret": intent_data["client_secret"],
            "amount": amount,
            "currency": currency,
            "plan_name": plan_name,
            "plan_type": body.type,
            "discount_amount": discount_amount,
        }

    except HTTPException:
        raise
    except Exception as e:
        error(f"[STRIPE] Erro ao criar payment intent: {e}")
        import traceback

        error(f"[STRIPE] Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Erro ao criar pagamento")


@stripe_router.post("/test-charge", response_model=Dict[str, Any])
async def stripe_test_charge(request: Request, body: StripeCreatePaymentIntentRequest):
    """
    ⚠️ APENAS PARA TESTES - Simula cobrança completa sem frontend.

    Fluxo automático:
    1. Cria Payment Intent
    2. Confirma com payment method de teste
    3. Retorna resultado da cobrança

    Args:
        body: plan_id, type, billing_email, coupon (opcional)

    Returns:
        dict: Resultado da cobrança (sucesso ou erro)
    """
    try:
        # Validar dev bypass
        if not request.scope.get("dev_bypass_enabled"):
            raise HTTPException(
                status_code=403, detail="Rota apenas para desenvolvimento"
            )

        user_id = request.scope.get("dev_user_id", 1)
        client_id = request.scope.get("dev_client_id", 1)

        debug(
            f"[STRIPE_TEST] POST /test-charge - user_id={user_id}, plan_id={body.plan_id}"
        )

        db = DatabaseManager()

        # 1. Validar plano
        plan = db.fetch_one(
            "SELECT id, name, monthly_price, annual_price, currency FROM plans WHERE (id = :plan_id OR plan_id = :plan_id) AND active = 1",
            {"plan_id": body.plan_id},
        )

        if not plan:
            warning(f"[STRIPE_TEST] Plano não encontrado - plan_id={body.plan_id}")
            raise HTTPException(status_code=404, detail="Plano não encontrado")

        plan_id_db = plan.get("id")
        plan_name = plan.get("name")
        monthly_price = plan.get("monthly_price")
        annual_price = plan.get("annual_price")
        currency = plan.get("currency").lower()

        # 2. Calcular amount e aplicar cupom
        amount = (
            int(annual_price * 100)
            if body.type == "annual"
            else int(monthly_price * 100)
        )
        coupon_id = None
        discount_amount = 0

        if body.coupon:
            coupon = db.fetch_one(
                "SELECT id, code, discount_type, discount_value, active, valid_from, valid_until FROM coupons WHERE code = :code",
                {"code": body.coupon.strip().upper()},
            )

            if coupon and coupon.get("active"):
                coupon_id = coupon.get("id")
                discount_type = coupon.get("discount_type")
                discount_value = coupon.get("discount_value")

                if discount_type == "percentage":
                    discount_amount = int(amount * (discount_value / 100))
                else:
                    discount_amount = int(discount_value * 100)

                discount_amount = min(discount_amount, amount)
                amount = amount - discount_amount
                info(
                    f"[STRIPE_TEST] Cupom aplicado - {body.coupon}, desconto={discount_amount/100}"
                )

        description = f"[TEST] Plano {plan_name} ({body.type})"
        if body.coupon:
            description += f" (Cupom: {body.coupon})"

        # 3. Criar Payment Intent
        stripe_service = get_stripe_payment_service()
        subscription_id = str(uuid_lib.uuid4())

        metadata = {
            "user_id": str(user_id),
            "plan_id": str(plan_id_db),
            "plan_type": body.type,
            "test": "true",
        }

        success, intent_data, error_msg = stripe_service.create_payment_intent(
            subscription_id=subscription_id,
            user_id=user_id,
            amount=amount,
            customer_email=body.billing_email,
            customer_name="Test Customer",
            description=description,
            metadata=metadata,
        )

        if not success:
            error(f"[STRIPE_TEST] Falha ao criar intent - {error_msg}")
            raise HTTPException(
                status_code=400, detail=f"Erro ao criar intent: {error_msg}"
            )

        intent_id = intent_data["intent_id"]
        info(f"[STRIPE_TEST] Intent criado - {intent_id}")

        # 4. Confirmar com test payment method
        # Stripe test payment methods: tok_visa, tok_mastercard, tok_amex
        # Usando tok_visa para teste
        test_payment_method = "pm_card_visa"  # Test payment method visa

        success, charge_id, error_msg = stripe_service.confirm_payment(
            subscription_id=subscription_id,
            user_id=user_id,
            intent_id=intent_id,
            payment_method_id=test_payment_method,
            amount=amount,
        )

        if not success:
            warning(f"[STRIPE_TEST] Cobrança falhou - {error_msg}")
            return {
                "status": "failed",
                "subscription_id": subscription_id,
                "intent_id": intent_id,
                "error": error_msg,
                "amount": amount,
                "currency": currency,
            }

        info(
            f"[STRIPE_TEST] ✅ Teste completo com sucesso - subscription_id={subscription_id}, charge_id={charge_id}"
        )

        return {
            "status": "success",
            "message": "✅ Cobrança de teste bem-sucedida!",
            "subscription_id": subscription_id,
            "intent_id": intent_id,
            "charge_id": charge_id,
            "plan_id": plan_id_db,
            "plan_name": plan_name,
            "plan_type": body.type,
            "amount": amount,
            "discount_amount": discount_amount,
            "currency": currency,
            "test_payment_method": test_payment_method,
        }

    except HTTPException:
        raise
    except Exception as e:
        error(f"[STRIPE_TEST] Erro no teste: {e}")
        import traceback

        error(f"[STRIPE_TEST] Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Erro no teste: {str(e)}")


@stripe_router.post("/confirm-payment", response_model=Dict[str, Any])
async def stripe_confirm_payment(request: Request, body: StripeConfirmPaymentRequest):
    """
    Confirma um Payment Intent e ativa a subscrição.

    Fluxo:
    1. Confirma payment intent com payment method
    2. Se sucesso: cria subscription
    3. Se falha: retorna erro

    Args:
        body: intent_id, payment_method_id, plan_id, type

    Returns:
        dict: subscription_id e status
    """
    try:
        # Extrair user_id
        if request.scope.get("dev_bypass_enabled"):
            user_id = request.scope.get("dev_user_id", 1)
            client_id = request.scope.get("dev_client_id", 1)
            debug(f"[STRIPE] POST /confirm-payment - DEV_BYPASS: user_id={user_id}")
        else:
            auth_service = get_auth_service()
            token = request.cookies.get("access_token")
            if not token:
                raise HTTPException(status_code=401, detail="Token não fornecido")
            payload = auth_service.verify_token(token)
            if not payload:
                raise HTTPException(
                    status_code=401, detail="Token inválido ou expirado"
                )
            user_id = payload.get("user_id")
            if not user_id:
                raise HTTPException(
                    status_code=401, detail="User ID não encontrado no token"
                )
            client_id = get_client_id_from_token(request)
            debug(
                f"[STRIPE] POST /confirm-payment - user_id={user_id}, intent_id={body.intent_id}"
            )

        db = DatabaseManager()

        # 1. Validar plano - buscar preços da tabela prices
        # Usar sempre early_adopter (preço promocional de lançamento)
        plan = db.fetch_one(
            """
            SELECT
                p.id,
                p.plan_id,
                p.name,
                MAX(CASE WHEN pr.period = 'monthly' THEN pr.price END) as monthly_price,
                MAX(CASE WHEN pr.period = 'annual' THEN pr.price END) as annual_price
            FROM plans p
            LEFT JOIN prices pr ON p.plan_id = pr.plan_id
            WHERE (p.id = :plan_id OR p.plan_id = :plan_id) AND p.active = 1 AND pr.adoption_stage = 'early_adopter'
            GROUP BY p.id, p.plan_id, p.name
            """,
            {"plan_id": body.plan_id},
        )

        if not plan:
            warning(f"[STRIPE] Plano não encontrado - plan_id={body.plan_id}")
            raise HTTPException(status_code=404, detail="Plano não encontrado")

        plan_id_uuid = plan.get("plan_id")  # UUID do plano (para usar em clients)
        plan_id_numeric = plan.get(
            "id"
        )  # ID numérico (para usar em billing_subscriptions)
        plan_name = plan.get("name")
        monthly_price = plan.get("monthly_price")
        annual_price = plan.get("annual_price")

        # 2. Calcular amount
        amount = (
            int(annual_price * 100)
            if body.type == "annual"
            else int(monthly_price * 100)
        )

        # 2.5 Buscar cartão registrado pelo card_id e descriptografar payment_method_id
        card_id = body.card_id
        card = db.fetch_one(
            """
            SELECT pagarme_card_id_encrypted FROM cards
            WHERE card_id = :card_id AND user_id = :user_id AND status IN ('valid', 'active')
            """,
            {"card_id": card_id, "user_id": user_id},
        )

        if not card:
            warning(
                f"[STRIPE] Cartão não encontrado - card_id={card_id}, user_id={user_id}"
            )
            raise HTTPException(
                status_code=404,
                detail="Cartão não encontrado. Por favor, registre um cartão antes de confirmar o pagamento.",
            )

        # Descriptografar o payment_method_id armazenado no banco
        payment_method_id_encrypted = card.get("pagarme_card_id_encrypted")
        payment_method_id = decrypt_field(payment_method_id_encrypted)

        if not payment_method_id:
            error(
                f"[STRIPE] Falha ao descriptografar payment_method_id para card_id={card_id}"
            )
            raise HTTPException(status_code=500, detail="Erro ao processar cartão")

        debug(
            f"[STRIPE] Cartão encontrado - card_id={card_id}, payment_method_id={payment_method_id[:20]}..."
        )

        # 3. Confirmar pagamento no Stripe - FLUXO DIFERENCIADO POR TIPO
        stripe_service = get_stripe_payment_service()
        subscription_id = str(uuid_lib.uuid4())

        # Extrair origin do request para return_url dinâmico
        origin = (
            request.headers.get("origin")
            or request.headers.get("referer", "").split("/")[2:3]
        )
        if isinstance(origin, list):
            origin = origin[0] if origin else None

        # Obter customer_id (criado em create_payment_intent)
        # Buscar na metadata do intent
        intent = stripe_service.retrieve_intent(body.intent_id)
        customer_id = intent.get("customer") if intent else None

        stripe_subscription_id = None
        if body.type == "annual":
            # FLUXO ANUAL: Usar Stripe Subscription (12x parcelado)
            debug(
                f"[STRIPE] Fluxo ANUAL - Criando subscription com early_adopter pricing"
            )

            (
                success,
                charge_id,
                stripe_subscription_id,
                error_msg,
            ) = stripe_service.create_subscription(
                customer_id=customer_id,
                payment_method_id=payment_method_id,
                plan_id=plan_id_numeric,
                monthly_price=monthly_price,
                annual_price=annual_price,
                plan_name=plan_name or "Subscription",
                metadata={
                    "subscription_id": subscription_id,
                    "user_id": str(user_id),
                    "type": "subscription",
                    "plan_type": "annual",
                },
            )
        else:
            # FLUXO MENSAL: Usar Payment Intent (pagamento único)
            debug(f"[STRIPE] Fluxo MENSAL - Confirmando payment intent")
            success, charge_id, error_msg = stripe_service.confirm_payment(
                subscription_id=subscription_id,
                user_id=user_id,
                intent_id=body.intent_id,
                payment_method_id=payment_method_id,
                amount=amount,
                origin=origin,
            )

        if not success:
            warning(f"[STRIPE] Cobrança falhou - {error_msg}")
            raise HTTPException(
                status_code=400, detail=f"Cobrança recusada: {error_msg}"
            )

        # 4. SUCESSO: Criar subscription record com o card_id já fornecido
        from datetime import timedelta
        from dateutil.relativedelta import relativedelta

        # Calcular renewal_date baseado no billing_cycle
        now = datetime.now()
        if body.type == "annual":
            renewal_date = now + relativedelta(years=1)
        else:  # monthly
            renewal_date = now + relativedelta(months=1)

        db.execute_query(
            """
            INSERT INTO billing_subscriptions (
                subscription_id, client_id, plan_id, card_id,
                billing_cycle, charge_scheduled_at, renewal_date, status,
                stripe_customer_id, stripe_subscription_id, created_at, updated_at
            ) VALUES (
                :subscription_id, :client_id, :plan_id, :card_id,
                :billing_cycle, CURRENT_TIMESTAMP, :renewal_date, 'active',
                :stripe_customer_id, :stripe_subscription_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """,
            {
                "subscription_id": subscription_id,
                "client_id": client_id,
                "plan_id": plan_id_uuid,
                "card_id": card_id,
                "billing_cycle": body.type,  # 'monthly' ou 'annual'
                "renewal_date": renewal_date.isoformat(),
                "stripe_customer_id": customer_id,  # Armazenar customer_id do Stripe
                "stripe_subscription_id": stripe_subscription_id,  # Armazenar subscription_id do Stripe (só para annual)
            },
        )

        # ⚠️ ATUALIZAÇÃO DE PLANO E CRÉDITOS REMOVIDOS DAQUI - Serão processados via Webhook

        # 4.2 Criar payment record com charge_id_stripe
        payment_id = str(uuid_lib.uuid4())

        db.execute_query(
            """
            INSERT INTO payments (
                payment_id, charge_id_stripe, idempotency_key, subscription_id,
                amount, status, created_at, updated_at
            ) VALUES (
                :payment_id, :charge_id_stripe, :idempotency_key, :subscription_id,
                :amount, 'paid', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """,
            {
                "payment_id": payment_id,
                "charge_id_stripe": charge_id,
                "idempotency_key": subscription_id,  # Usar subscription_id como chave única
                "subscription_id": subscription_id,
                "amount": amount,
            },
        )

        info(
            f"[STRIPE] Subscrição criada com sucesso - subscription_id={subscription_id}, charge_id={charge_id}"
        )

        return {
            "status": "success",
            "subscription_id": subscription_id,
            "plan_id": plan_id_uuid,
            "plan_name": plan_name,
            "charge_id": charge_id,
            "message": f"Pagamento confirmado! Plano {plan_name} será ativado em instantes após processamento.",
        }

    except HTTPException:
        raise
    except Exception as e:
        error(f"[STRIPE] Erro ao confirmar pagamento: {e}")
        import traceback

        error(f"[STRIPE] Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Erro ao confirmar pagamento")


# ========================================================================
# EXPORTS
# ========================================================================

__all__ = [
    "subscription_router",
    "subscription_cancel_router",
    "credits_router",
    "webhook_router",
    "stripe_router",
    "stripe_webhook_router",
]

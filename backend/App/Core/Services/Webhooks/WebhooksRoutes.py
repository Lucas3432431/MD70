"""
Rotas de Webhooks - FastAPI Routes
Processa webhooks de serviços terceiros (Pagarme, etc)
"""

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
import json
import base64
import uuid as uuid_lib
from datetime import datetime

from App.Core.Logs import debug, info, warning, error
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Core.Settings import load_config
from App.Core.Settings.Settings import WEBHOOK_PREFIX

# ========================================================================
# MODELS
# ========================================================================


class PagarmeWebhookData(BaseModel):
    """Dados do webhook do Pagarme"""

    id: str = Field(..., description="ID único do evento")
    type: str = Field(
        ..., description="Tipo do evento (ex: 'charge.paid', 'charge.failed')"
    )
    data: Optional[Dict[str, Any]] = Field(
        None, description="Dados adicionais do evento"
    )


# ========================================================================
# ROUTER
# ========================================================================

webhooks_router = APIRouter(tags=["Webhooks"], prefix=f"{WEBHOOK_PREFIX}/payments")


# ========================================================================
# HELPER FUNCTIONS
# ========================================================================


def verify_pagarme_basic_auth(
    request: Request, webhook_user: str, webhook_password: str
) -> bool:
    """
    Verifica autenticação básica do webhook do Pagarme Stone.

    Args:
        request: Request object do FastAPI
        webhook_user: Usuário do webhook configurado na Pagarme
        webhook_password: Senha do webhook configurado na Pagarme

    Returns:
        bool: True se a autenticação é válida
    """
    try:
        # Obter header Authorization
        auth_header = request.headers.get("Authorization", "")

        if not auth_header.startswith("Basic "):
            warning("[PAGARME] Header Authorization ausente ou inválido")
            return False

        # Decodificar credenciais
        try:
            encoded_creds = auth_header.replace("Basic ", "")
            decoded_creds = base64.b64decode(encoded_creds).decode("utf-8")
            received_user, received_password = decoded_creds.split(":", 1)
        except Exception as e:
            warning(f"[PAGARME] Erro ao decodificar credenciais: {e}")
            return False

        # Validar credenciais
        is_valid = (
            received_user == webhook_user and received_password == webhook_password
        )
        debug(f"[PAGARME] Validação de Basic Auth: {is_valid}")
        return is_valid

    except Exception as e:
        error(f"[PAGARME] Erro ao verificar autenticação: {e}")
        return False


# ========================================================================
# ROUTES
# ========================================================================


@webhooks_router.post("/pagarme")
async def pagarme_webhook(request: Request):
    """
    Recebe webhooks do Pagarme.

    Eventos suportados:
    - charge.created
    - charge.updated
    - charge.paid
    - charge.failed
    - charge.canceled
    - charge.refunded
    - charge.chargeback_created

    Returns:
        dict: Confirmação de recebimento
    """
    try:
        # Carregar configurações
        config = load_config()
        webhook_user = config.get("pagarme_webhook_user", "")
        webhook_password = config.get("pagarme_webhook_password", "")

        if not webhook_user or not webhook_password:
            error(
                "[PAGARME] PAGARME_WEBHOOK_USER ou PAGARME_WEBHOOK_PASSWORD não configurados"
            )
            raise HTTPException(
                status_code=500, detail="Webhook credentials não configuradas"
            )

        # Validar autenticação básica
        if not verify_pagarme_basic_auth(request, webhook_user, webhook_password):
            warning("[PAGARME] Falha na autenticação básica do webhook")
            raise HTTPException(status_code=401, detail="Autenticação falhou")

        # Obter corpo da requisição
        body = await request.body()
        body_str = body.decode("utf-8")

        debug("[PAGARME] Webhook autenticado com sucesso")

        # Parse JSON
        try:
            webhook_data = json.loads(body_str)
        except json.JSONDecodeError:
            error("[PAGARME] Erro ao parsear JSON do webhook")
            raise HTTPException(status_code=400, detail="JSON inválido")

        event_type = webhook_data.get("type", "unknown")
        event_id = webhook_data.get("id", "unknown")

        info(
            f"[PAGARME] Webhook autenticado e processado - type={event_type}, id={event_id}"
        )

        # Processar diferentes tipos de eventos
        if event_type == "charge.paid":
            await handle_charge_paid(webhook_data)
        elif event_type == "charge.failed":
            await handle_charge_failed(webhook_data)
        elif event_type == "charge.refunded":
            await handle_charge_refunded(webhook_data)
        elif event_type == "charge.canceled":
            await handle_charge_canceled(webhook_data)
        else:
            debug(f"[PAGARME] Evento não tratado: {event_type}")

        return {"status": "received", "event_type": event_type, "event_id": event_id}

    except HTTPException:
        raise
    except Exception as e:
        error(f"[PAGARME] Erro ao processar webhook: {e}")
        raise HTTPException(status_code=500, detail="Erro ao processar webhook")


async def handle_charge_paid(webhook_data: Dict[str, Any]):
    """
    Processa evento de cobrança paga.
    Cria/atualiza payment record e adiciona créditos ao usuário.

    Args:
        webhook_data: Dados do webhook
    """
    try:
        config = load_config()
        db = DatabaseManager()

        charge_data = webhook_data.get("data", {})
        charge_id = charge_data.get("id")
        customer = charge_data.get("customer", {})
        customer_id = customer.get("id")
        amount = charge_data.get("amount", 0)  # Em centavos
        payment_method = charge_data.get("payment_method", {}).get("type", "unknown")

        if not charge_id:
            warning("[PAGARME] charge.paid sem charge_id")
            return

        info(
            f"[PAGARME] Cobrança paga - charge_id={charge_id}, amount={amount}, customer_id={customer_id}"
        )

        # 1. Buscar se payment já existe (evitar duplicatas)
        existing_payment = db.fetch_one(
            "SELECT id, client_id FROM payments WHERE charge_id = :charge_id",
            {"charge_id": charge_id},
        )

        if existing_payment:
            # Payment já foi processado
            info(f"[PAGARME] Payment já existe - charge_id={charge_id}")
            return

        # 2. Buscar client_id usando customer_id do Pagarme (será mapeado em metadados)
        # Por enquanto, assumimos que customer_id contém o client_id
        try:
            client_id = int(customer_id)
        except (ValueError, TypeError):
            warning(f"[PAGARME] customer_id inválido - {customer_id}")
            return

        # 3. Verificar se client_id existe
        client = db.fetch_one(
            "SELECT client_id, plan FROM clients WHERE client_id = :client_id",
            {"client_id": client_id},
        )

        if not client:
            warning(f"[PAGARME] client_id não encontrado - {client_id}")
            return

        # 4. Calcular créditos com base no amount e rate configurado
        credit_value_centavos = config.get("credit_value_centavos", 100)
        credits_granted = int(amount / credit_value_centavos)

        # 5. Criar payment record
        payment_id = str(uuid_lib.uuid4())
        db.execute_query(
            """
            INSERT INTO payments (
                charge_id, client_id, amount, currency, status, payment_method,
                description, credits_granted, created_at, updated_at
            ) VALUES (
                :charge_id, :client_id, :amount, 'BRL', 'paid', :payment_method,
                :description, :credits_granted, datetime('now'), datetime('now')
            )
            """,
            {
                "charge_id": charge_id,
                "client_id": client_id,
                "amount": amount,
                "payment_method": payment_method,
                "description": f"Pagarme charge {charge_id}",
                "credits_granted": credits_granted,
            },
        )

        # 6. Adicionar créditos ao usuário
        if credits_granted > 0:
            db.execute_query(
                """
                UPDATE users
                SET credits_available = credits_available + :credits
                WHERE client_id = :client_id
                """,
                {"credits": credits_granted, "client_id": client_id},
            )

        info(
            f"[PAGARME] Pagamento processado com sucesso - charge_id={charge_id}, credits_granted={credits_granted}"
        )

        # Conceder créditos ao referrer se o pagador foi indicado
        try:
            user_result = db.fetch_one(
                "SELECT user_id FROM users WHERE client_id = :client_id LIMIT 1",
                {"client_id": client_id},
            )
            if user_result:
                from App.Core.Services.Sharing.ReferralManager import ReferralManager

                ReferralManager.award_subscription_credits_to_referrer(
                    user_result["user_id"]
                )
        except Exception as referral_error:
            error(
                f"[REFERRAL] Erro ao verificar subscription credits: {referral_error}"
            )

    except Exception as e:
        error(f"[PAGARME] Erro ao processar pagamento: {e}")


async def handle_charge_failed(webhook_data: Dict[str, Any]):
    """
    Processa evento de cobrança falhada.
    Cria payment record com status failed.

    Args:
        webhook_data: Dados do webhook
    """
    try:
        db = DatabaseManager()

        charge_data = webhook_data.get("data", {})
        charge_id = charge_data.get("id")
        customer = charge_data.get("customer", {})
        customer_id = customer.get("id")
        amount = charge_data.get("amount", 0)
        reason = charge_data.get("failure_reason", "unknown")

        warning(f"[PAGARME] Cobrança falhada - charge_id={charge_id}, reason={reason}")

        if not charge_id:
            return

        # Verificar se já existe
        existing = db.fetch_one(
            "SELECT id FROM payments WHERE charge_id = :charge_id",
            {"charge_id": charge_id},
        )

        if not existing:
            # Criar payment record com status failed
            try:
                client_id = int(customer_id)
                db.execute_query(
                    """
                    INSERT INTO payments (
                        charge_id, client_id, amount, currency, status,
                        description, created_at, updated_at
                    ) VALUES (
                        :charge_id, :client_id, :amount, 'BRL', 'failed',
                        :description, datetime('now'), datetime('now')
                    )
                    """,
                    {
                        "charge_id": charge_id,
                        "client_id": client_id,
                        "amount": amount,
                        "description": f"Pagarme failed: {reason}",
                    },
                )
            except (ValueError, TypeError):
                pass

        info(f"[PAGARME] Falha de pagamento registrada - charge_id={charge_id}")

    except Exception as e:
        error(f"[PAGARME] Erro ao processar cobrança falhada: {e}")


async def handle_charge_refunded(webhook_data: Dict[str, Any]):
    """
    Processa evento de reembolso.
    Atualiza payment record e remove créditos do usuário.

    Args:
        webhook_data: Dados do webhook
    """
    try:
        config = load_config()
        db = DatabaseManager()

        charge_data = webhook_data.get("data", {})
        charge_id = charge_data.get("id")
        amount = charge_data.get("amount", 0)

        info(f"[PAGARME] Reembolso processado - charge_id={charge_id}, amount={amount}")

        if not charge_id:
            return

        # Buscar payment
        payment = db.fetch_one(
            "SELECT client_id, credits_granted FROM payments WHERE charge_id = :charge_id",
            {"charge_id": charge_id},
        )

        if not payment:
            warning(
                f"[PAGARME] Payment não encontrado para refund - charge_id={charge_id}"
            )
            return

        client_id, credits_granted = payment[0], payment[1]

        # Atualizar status para refunded
        db.execute_query(
            "UPDATE payments SET status = 'refunded', updated_at = datetime('now') WHERE charge_id = :charge_id",
            {"charge_id": charge_id},
        )

        # Remover créditos se foram adicionados
        if credits_granted and credits_granted > 0:
            db.execute_query(
                """
                UPDATE users
                SET credits_available = MAX(0, credits_available - :credits)
                WHERE client_id = :client_id
                """,
                {"credits": credits_granted, "client_id": client_id},
            )

            info(
                f"[PAGARME] Créditos removidos por refund - charge_id={charge_id}, credits={credits_granted}"
            )

    except Exception as e:
        error(f"[PAGARME] Erro ao processar reembolso: {e}")


async def handle_charge_canceled(webhook_data: Dict[str, Any]):
    """
    Processa evento de cobrança cancelada.
    Cria ou atualiza payment record com status canceled.

    Args:
        webhook_data: Dados do webhook
    """
    try:
        db = DatabaseManager()

        charge_data = webhook_data.get("data", {})
        charge_id = charge_data.get("id")
        customer = charge_data.get("customer", {})
        customer_id = customer.get("id")
        amount = charge_data.get("amount", 0)

        info(f"[PAGARME] Cobrança cancelada - charge_id={charge_id}")

        if not charge_id:
            return

        # Buscar ou criar payment
        payment = db.fetch_one(
            "SELECT id FROM payments WHERE charge_id = :charge_id",
            {"charge_id": charge_id},
        )

        if payment:
            # Atualizar status
            db.execute_query(
                "UPDATE payments SET status = 'canceled', updated_at = datetime('now') WHERE charge_id = :charge_id",
                {"charge_id": charge_id},
            )
        else:
            # Criar novo record com status canceled
            try:
                client_id = int(customer_id)
                db.execute_query(
                    """
                    INSERT INTO payments (
                        charge_id, client_id, amount, currency, status,
                        description, created_at, updated_at
                    ) VALUES (
                        :charge_id, :client_id, :amount, 'BRL', 'canceled',
                        :description, datetime('now'), datetime('now')
                    )
                    """,
                    {
                        "charge_id": charge_id,
                        "client_id": client_id,
                        "amount": amount,
                        "description": f"Pagarme canceled charge {charge_id}",
                    },
                )
            except (ValueError, TypeError):
                pass

        info(f"[PAGARME] Cancelamento de pagamento registrado - charge_id={charge_id}")

    except Exception as e:
        error(f"[PAGARME] Erro ao processar cancelamento: {e}")


# ========================================================================
# EXPORTS
# ========================================================================

__all__ = ["webhooks_router"]

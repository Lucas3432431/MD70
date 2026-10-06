"""
Job de Subscrição - Processa renovações automáticas de planos
Integrado com Stripe para Monthly (Payment Intent) e Annual (Subscriptions)
Deve ser executado diariamente via APScheduler (2:00 AM)
"""

from datetime import datetime, timedelta
from typing import List, Dict, Any

from App.Core.Logs import debug, info, warning, error
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Core.Settings import load_config
from App.Core.Services.Subscription.StripePaymentService import (
    get_stripe_payment_service,
)
from App.Core.Services.Subscription.EncryptionUtil import decrypt_field


class SubscriptionJob:
    """Job para processar renovações de subscrições (Stripe integration)"""

    MAX_RETRY_ATTEMPTS = 3
    SUSPENDED_TIMEOUT_DAYS = 7

    def __init__(self):
        self.db = DatabaseManager()
        self.stripe_service = get_stripe_payment_service()
        self.config = load_config()

    def process_all(self):
        """Processa renovações e limpeza de subscrições"""
        info("[SUBSCRIPTION_JOB] Iniciando processamento de subscrições")

        # 1. Processar renovações automáticas (monthly via Stripe, annual gerenciado pelo Stripe)
        self.process_renewals()

        # 2. Limpar subscrições suspensas que passaram timeout
        self.cleanup_suspended()

        info("[SUBSCRIPTION_JOB] Processamento concluído")

    def process_renewals(self):
        """
        Processa renovações automáticas de subscrições ativas cuja data de renovação chegou.
        - Monthly: cria novo Payment Intent off-session
        - Annual: Stripe gerencia automaticamente (webhook confirma status)
        """
        try:
            debug("[SUBSCRIPTION_JOB] Processando renovações automáticas")

            # Buscar subscrições prontas para renovação (apenas monthly - annual é gerenciado pelo Stripe)
            query = """
                SELECT
                    bs.id, bs.subscription_id, bs.client_id,
                    bs.plan_id as plan_uuid, bs.card_id, bs.billing_cycle,
                    bs.stripe_customer_id,
                    c.pagarme_card_id_encrypted as payment_method_id_encrypted,
                    pr.price
                FROM billing_subscriptions bs
                JOIN cards c ON bs.card_id = c.card_id
                JOIN plans p ON bs.plan_id = p.plan_id
                LEFT JOIN prices pr ON p.plan_id = pr.plan_id
                WHERE bs.status = 'active'
                  AND bs.renewal_date IS NOT NULL
                  AND bs.renewal_date <= datetime('now')
                  AND bs.billing_cycle = 'monthly'
                  AND pr.period = 'monthly'
                  AND pr.adoption_stage = 'early_adopter'
                ORDER BY bs.renewal_date ASC
            """

            results = self.db.fetch_all(query, {})

            if not results:
                debug("[SUBSCRIPTION_JOB] Nenhuma renovação monthly pendente")
                return

            info(
                f"[SUBSCRIPTION_JOB] Encontradas {len(results)} renovações monthly para processar"
            )

            for row in results:
                sub_id = row.get("id")
                subscription_id = row.get("subscription_id")
                client_id = row.get("client_id")
                stripe_customer_id = row.get("stripe_customer_id")
                payment_method_id_encrypted = row.get("payment_method_id_encrypted")
                price = row.get("price") or 0
                amount_cents = int(price * 100)

                # Descriptografar payment_method_id
                try:
                    payment_method_id = decrypt_field(payment_method_id_encrypted)
                    if not payment_method_id:
                        warning(
                            f"[SUBSCRIPTION_JOB] Falha ao descriptografar payment_method - subscription_id={subscription_id}"
                        )
                        continue
                except Exception as decrypt_err:
                    warning(
                        f"[SUBSCRIPTION_JOB] Erro decrypt payment_method - subscription_id={subscription_id}: {decrypt_err}"
                    )
                    continue

                self._charge_renewal(
                    sub_id=sub_id,
                    subscription_id=subscription_id,
                    client_id=client_id,
                    stripe_customer_id=stripe_customer_id,
                    payment_method_id=payment_method_id,
                    amount_cents=amount_cents,
                )

        except Exception as e:
            error(f"[SUBSCRIPTION_JOB] Erro ao processar renovações: {e}")
            import traceback

            error(f"[SUBSCRIPTION_JOB] Traceback: {traceback.format_exc()}")

    def cleanup_suspended(self):
        """
        Cancela automaticamente subscrições que ficaram suspensas
        por mais de SUSPENDED_TIMEOUT_DAYS (7 dias)
        """
        try:
            debug("[SUBSCRIPTION_JOB] Limpando subscrições suspensas expiradas")

            cutoff_date = (
                datetime.now() - timedelta(days=self.SUSPENDED_TIMEOUT_DAYS)
            ).isoformat()

            query = """
                SELECT id, subscription_id FROM billing_subscriptions
                WHERE status = 'suspended'
                  AND last_payment_attempt_at < :cutoff_date
            """

            results = self.db.fetch_all(query, {"cutoff_date": cutoff_date})

            if not results:
                debug("[SUBSCRIPTION_JOB] Nenhuma subscrição suspensa para cancelar")
                return

            info(
                f"[SUBSCRIPTION_JOB] Cancelando {len(results)} subscrições suspensas expiradas"
            )

            for row in results:
                sub_id = row.get("id")
                subscription_id = row.get("subscription_id")

                self.db.execute_query(
                    """
                    UPDATE billing_subscriptions
                    SET status = 'canceled',
                        canceled_at = datetime('now'),
                        cancellation_reason = 'Suspenso por mais de 7 dias',
                        updated_at = datetime('now')
                    WHERE id = :sub_id
                    """,
                    {"sub_id": sub_id},
                )

                info(
                    f"[SUBSCRIPTION_JOB] Subscrição cancelada - subscription_id={subscription_id}"
                )

        except Exception as e:
            error(f"[SUBSCRIPTION_JOB] Erro ao limpar suspensões: {e}")

    def _charge_renewal(
        self,
        sub_id: int,
        subscription_id: str,
        client_id: str,
        stripe_customer_id: str,
        payment_method_id: str,
        amount_cents: int,
    ):
        """
        Processa cobrança de renovação via Stripe (off-session).

        Args:
            sub_id: ID interno da subscrição
            subscription_id: UUID da subscrição
            client_id: ID do cliente
            stripe_customer_id: ID do customer no Stripe
            payment_method_id: ID do payment method (cartão)
            amount_cents: Valor em centavos
        """
        try:
            description = f"Renovação de subscrição {subscription_id}"

            # 1. Cobrar via Stripe off-session
            success, charge_id, error_msg = self.stripe_service.charge_off_session(
                customer_id=stripe_customer_id,
                payment_method_id=payment_method_id,
                amount_cents=amount_cents,
                description=description,
                subscription_id=subscription_id,
            )

            if success:
                # 2. Cobrança bem-sucedida
                next_renewal = (datetime.now() + timedelta(days=30)).isoformat()

                self.db.execute_query(
                    """
                    UPDATE billing_subscriptions
                    SET status = 'active',
                        charge_completed_at = datetime('now'),
                        renewal_date = :next_renewal,
                        payment_retry_count = 0,
                        last_payment_error = NULL,
                        last_payment_attempt_at = datetime('now'),
                        updated_at = datetime('now')
                    WHERE id = :sub_id
                    """,
                    {"sub_id": sub_id, "next_renewal": next_renewal},
                )

                # 2.1 ATIVAR PLANO NO CLIENTE (Garantia se o webhook demorar)
                # Selecionar explicitamente a coluna plan_id (UUID) que é o FK correto em clients
                sub_data = self.db.fetch_one(
                    "SELECT plan_id FROM billing_subscriptions WHERE id = :sub_id",
                    {"sub_id": sub_id},
                )
                if sub_data and sub_data.get("plan_id"):
                    plan_uuid = sub_data["plan_id"]
                    self.db.execute_query(
                        "UPDATE clients SET plan_id = :plan_uuid, updated_at = datetime('now') WHERE client_id = :client_id",
                        {"plan_uuid": plan_uuid, "client_id": client_id},
                    )

                # 3. Registrar pagamento em payments table
                import uuid as uuid_lib

                payment_id = str(uuid_lib.uuid4())

                self.db.execute_query(
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
                        "idempotency_key": subscription_id,
                        "subscription_id": subscription_id,
                        "amount": amount_cents,
                    },
                )

                # 4. DISTRIBUIR CRÉDITOS (O Job é síncrono aqui)
                try:
                    from App.Features.Credits.CreditsManager import CreditsManager

                    # Buscar plan_uuid e user_id associado ao cliente
                    query = """
                        SELECT bs.plan_id, u.user_id
                        FROM billing_subscriptions bs
                        JOIN users u ON bs.client_id = u.client_id
                        WHERE bs.id = :sub_id
                        LIMIT 1
                    """
                    sub_data = self.db.fetch_one(query, {"sub_id": sub_id})
                    if sub_data:
                        CreditsManager.distribute_plan_credits(
                            sub_data["user_id"], sub_data["plan_id"]
                        )
                except Exception as e:
                    error(
                        f"[SUBSCRIPTION_JOB] Erro ao distribuir créditos na renovação: {e}"
                    )

                info(
                    f"[SUBSCRIPTION_JOB] Renovação bem-sucedida - subscription_id={subscription_id}, charge_id={charge_id}"
                )

            else:
                # 2. Cobrança falhou
                retry_count = self._get_retry_count(sub_id) + 1

                # Descobrir se é Monthly ou Annual
                sub_info = self.db.fetch_one(
                    "SELECT billing_cycle FROM billing_subscriptions WHERE id = :sub_id",
                    {"sub_id": sub_id},
                )
                billing_cycle = (
                    sub_info.get("billing_cycle", "monthly") if sub_info else "monthly"
                )

                if retry_count >= self.MAX_RETRY_ATTEMPTS:
                    # LIMITE DE RETRIES ATINGIDO
                    if billing_cycle == "monthly":
                        # MENSAL: Cancela o plano
                        new_status = "canceled"
                        reason = "Falha no pagamento mensal após múltiplas tentativas"
                    else:
                        # ANUAL: Mantém suspenso para não perder acesso aos créditos já pagos, mas não renova
                        new_status = "suspended"
                        reason = "Falha na renovação anual - aguardando regularização"

                    self.db.execute_query(
                        """
                        UPDATE billing_subscriptions
                        SET status = :status,
                            canceled_at = :cancel_date,
                            cancellation_reason = :reason,
                            last_payment_error = :error,
                            last_payment_attempt_at = datetime('now'),
                            payment_retry_count = :retry_count,
                            updated_at = datetime('now')
                        WHERE id = :sub_id
                        """,
                        {
                            "sub_id": sub_id,
                            "status": new_status,
                            "cancel_date": (
                                datetime.now().isoformat()
                                if new_status == "canceled"
                                else None
                            ),
                            "reason": reason,
                            "error": error_msg,
                            "retry_count": retry_count,
                        },
                    )

                    warning(
                        f"[SUBSCRIPTION_JOB] Limite de retries atingido ({billing_cycle}) - status={new_status}, sub={subscription_id}"
                    )

                else:
                    # AINDA EM RETRY: Suspender temporariamente
                    self.db.execute_query(
                        """
                        UPDATE billing_subscriptions
                        SET status = 'suspended',
                            last_payment_error = :error,
                            last_payment_attempt_at = datetime('now'),
                            payment_retry_count = :retry_count,
                            updated_at = datetime('now')
                        WHERE id = :sub_id
                        """,
                        {
                            "sub_id": sub_id,
                            "error": error_msg,
                            "retry_count": retry_count,
                        },
                    )

                    warning(
                        f"[SUBSCRIPTION_JOB] Subscrição suspensa - subscription_id={subscription_id}, tentativa={retry_count}/{self.MAX_RETRY_ATTEMPTS}"
                    )

        except Exception as e:
            error(
                f"[SUBSCRIPTION_JOB] Erro ao processar renovação - subscription_id={subscription_id}: {e}"
            )
            import traceback

            error(f"[SUBSCRIPTION_JOB] Traceback: {traceback.format_exc()}")

    def _get_retry_count(self, sub_id: int) -> int:
        """Retorna número atual de tentativas de cobrança"""
        try:
            result = self.db.fetch_one(
                "SELECT payment_retry_count FROM billing_subscriptions WHERE id = :sub_id",
                {"sub_id": sub_id},
            )
            return result.get("payment_retry_count", 0) if result else 0
        except Exception:
            return 0


def run_subscription_job():
    """Função executada pelo APScheduler"""
    job = SubscriptionJob()
    job.process_all()

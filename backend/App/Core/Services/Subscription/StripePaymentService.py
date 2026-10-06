"""
Serviço de Pagamento - Integração com Stripe
Responsável por criar payment intents, confirmar pagamentos e processar webhooks
"""

from typing import Dict, Any, Tuple, Optional
import uuid as uuid_lib
import json
import hmac
import hashlib
import asyncio
from datetime import datetime, timedelta

import stripe
from App.Core.Logs import debug, info, warning, error
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Core.Settings import load_config


class StripePaymentService:
    """Serviço para integração com Stripe"""

    def __init__(self):
        self.config = load_config()
        self.api_key = self.config.get("stripe_secret_key", "")
        self.webhook_secret = self.config.get("stripe_webhook_secret", "")
        self.max_retries = 3
        self.base_wait_time = 300  # 5 minutos

        if not self.api_key:
            error("[STRIPE] STRIPE_SECRET_KEY não configurado")
        else:
            stripe.api_key = self.api_key
            debug("[STRIPE] Stripe inicializado com sucesso")

    def retrieve_intent(self, intent_id: str) -> Optional[Dict]:
        """Recupera um Payment Intent do Stripe"""
        try:
            intent = stripe.PaymentIntent.retrieve(intent_id)
            return {
                "id": intent.id,
                "customer": intent.customer,
                "status": intent.status,
                "amount": intent.amount,
            }
        except Exception as e:
            error(f"[STRIPE] Erro ao recuperar intent: {e}")
            return None

    @staticmethod
    def get_stripe_return_url(origin: Optional[str] = None) -> str:
        """Retorna Stripe return URL apropriada baseada na origem

        Args:
            origin: URL de origem (ex: http://localhost:5082 ou https://ngrok-free.dev)

        Returns:
            URL de return que corresponde à origem
        """
        config = load_config()

        # Tentar carregar da lista de URLs autorizadas
        return_urls = config.get("stripe_return_urls", [])

        if return_urls:
            # Se origem foi fornecida, tentar encontrar URL correspondente
            if origin:
                for url in return_urls:
                    if url.startswith(origin):
                        return url
                # Se não encontrou correspondência exata, usar primeira como fallback

            # Retorna a primeira URL como padrão
            return return_urls[0]

        # Fallback: tentar carregar do .env
        url = config.get("stripe_return_url", "")
        if url:
            return url

        # Fallback final
        warning("[STRIPE] Nenhuma Stripe return URL configurada")
        return "http://localhost:5082/checkout/return"

    def create_payment_intent(
        self,
        subscription_id: str,
        user_id: int,
        amount: int,
        customer_email: str,
        customer_name: str = "Customer",
        description: str = "Cobrança de subscrição",
        metadata: Optional[Dict] = None,
    ) -> Tuple[bool, Optional[Dict], Optional[str]]:
        """
        Cria um Payment Intent no Stripe para futura confirmação.

        Args:
            subscription_id: ID da subscrição
            user_id: ID do usuário
            amount: Valor em centavos
            customer_email: Email do cliente
            customer_name: Nome do cliente
            description: Descrição da cobrança
            metadata: Dados adicionais

        Returns:
            Tuple: (sucesso: bool, intent_data: dict, error_message: str)
        """
        try:
            debug(
                f"[STRIPE] Criando payment intent - subscription_id={subscription_id}, amount={amount}"
            )

            # 1. Criar ou obter Stripe Customer (necessário para reutilizar payment methods)
            customer_id = None
            try:
                # Buscar customer existente por email
                customers = stripe.Customer.list(email=customer_email, limit=1)
                if customers.data:
                    customer_id = customers.data[0].id
                    debug(
                        f"[STRIPE] Customer existente encontrado - customer_id={customer_id}"
                    )
                else:
                    # Criar novo customer
                    customer = stripe.Customer.create(
                        email=customer_email,
                        name=customer_name,
                        metadata={"user_id": str(user_id)},
                    )
                    customer_id = customer.id
                    debug(f"[STRIPE] Novo Customer criado - customer_id={customer_id}")
            except stripe.error.StripeError as e:
                warning(f"[STRIPE] Erro ao criar/obter customer: {e}")
                # Continuar mesmo sem customer (fallback)
                customer_id = None

            # Preparar metadata
            payment_metadata = {
                "subscription_id": subscription_id,
                "user_id": str(user_id),
                "type": "subscription",
            }
            if metadata:
                payment_metadata.update(metadata)

            # 2. Criar payment intent COM customer attachment
            intent_params = {
                "amount": amount,
                "currency": "brl",  # Real brasileiro
                "description": description,
                "metadata": payment_metadata,
                "receipt_email": customer_email,
            }

            # Se temos customer, anexar para permitir reutilização de payment methods
            if customer_id:
                intent_params["customer"] = customer_id
                intent_params[
                    "setup_future_usage"
                ] = "off_session"  # Permitir uso futuro

            intent = stripe.PaymentIntent.create(**intent_params)

            intent_data = {
                "intent_id": intent.id,
                "client_secret": intent.client_secret,
                "status": intent.status,
                "amount": intent.amount,
                "currency": intent.currency,
                "created_at": datetime.fromtimestamp(intent.created).isoformat(),
            }

            info(f"[STRIPE] Payment intent criado - intent_id={intent.id}")
            debug(f"[STRIPE] Intent data: {intent_data}")

            return True, intent_data, None

        except stripe.error.CardError as e:
            error(f"[STRIPE] Erro de cartão: {e.user_message}")
            return False, None, f"Erro no cartão: {e.user_message}"

        except stripe.error.StripeError as e:
            error(f"[STRIPE] Erro Stripe: {str(e)}")
            return False, None, f"Erro ao processar pagamento: {str(e)}"

        except Exception as e:
            error(f"[STRIPE] Erro ao criar payment intent: {e}")
            return False, None, f"Erro ao criar intent: {str(e)}"

    def create_subscription(
        self,
        customer_id: str,
        payment_method_id: str,
        plan_id: int,
        monthly_price: float,
        annual_price: float,
        plan_name: str = "Subscription",
        metadata: Optional[Dict] = None,
    ) -> Tuple[bool, Optional[str], Optional[str], Optional[str]]:
        """
        Cria uma Subscription no Stripe para cobranças recorrentes (anual parcelado em 12x).

        Args:
            customer_id: ID do customer Stripe
            payment_method_id: ID do payment method
            plan_id: ID do plano
            monthly_price: Preço mensal em reais
            annual_price: Preço anual em reais (será dividido por 12)
            plan_name: Nome do plano para descrição
            metadata: Dados adicionais

        Returns:
            Tuple: (sucesso: bool, charge_id: str, stripe_subscription_id: str, error_message: str)
        """
        try:
            debug(
                f"[STRIPE] Criando subscription - customer_id={customer_id}, plan_id={plan_id}, annual_price={annual_price}"
            )

            # 1. Attach payment_method ao customer
            debug(
                f"[STRIPE] Anexando payment_method={payment_method_id} ao customer={customer_id}"
            )
            try:
                stripe.PaymentMethod.attach(payment_method_id, customer=customer_id)
                debug(f"[STRIPE] Payment method anexado com sucesso")
            except stripe.error.InvalidRequestError as attach_err:
                # Payment method já pode estar attachado
                if "already attached" in str(attach_err).lower():
                    debug(f"[STRIPE] Payment method já estava anexado ao customer")
                else:
                    raise

            # Usar early_adopter pricing (melhor desconto para annual)
            # annual_price já vem de early_adopter do frontend
            # Calcular preço mensal (anual/12) e converter para centavos
            monthly_from_annual = int((annual_price / 12) * 100)

            # Criar produto no Stripe
            product = stripe.Product.create(
                name=f"Plano {plan_id}",
                type="service",
                metadata={"plan_id": str(plan_id)},
            )

            # Criar price com valor mensal (1/12 do annual)
            price = stripe.Price.create(
                product=product.id,
                unit_amount=monthly_from_annual,  # Valor anual dividido por 12
                currency="brl",
                recurring={"interval": "month", "interval_count": 1},
                metadata={"plan_id": str(plan_id), "annual_price": str(annual_price)},
            )

            # Criar subscription
            subscription = stripe.Subscription.create(
                customer=customer_id,
                items=[{"price": price.id}],
                default_payment_method=payment_method_id,
                collection_method="charge_automatically",
                automatic_tax={"enabled": False},
                description=f"Plano {plan_name} (annual)",
                metadata=metadata or {},
            )

            # Obter charge ID do primeiro invoice para refund futuro
            charge_id = None
            if subscription.latest_invoice:
                invoice = stripe.Invoice.retrieve(subscription.latest_invoice)
                if invoice.charge:
                    charge_id = invoice.charge
                    debug(
                        f"[STRIPE] Charge ID obtido do invoice - charge_id={charge_id}"
                    )

            info(
                f"[STRIPE] Subscription criada - subscription_id={subscription.id}, charge_id={charge_id}, monthly_charge={monthly_from_annual/100:.2f}, plan={plan_name}"
            )
            # Retornar charge_id (para refund), stripe_subscription_id (para cancelamento), e status
            return True, charge_id, subscription.id, None

        except stripe.error.StripeError as e:
            error(f"[STRIPE] Erro Stripe ao criar subscription: {str(e)}")
            return False, None, None, f"Erro ao criar subscription: {str(e)}"

        except Exception as e:
            error(f"[STRIPE] Erro ao criar subscription: {e}")
            import traceback

            error(f"[STRIPE] Traceback: {traceback.format_exc()}")
            return False, None, None, f"Erro ao criar subscription: {str(e)}"

    def charge_off_session(
        self,
        customer_id: str,
        payment_method_id: str,
        amount_cents: int,
        description: str,
        subscription_id: str,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Cobra um customer off-session (sem redirecionamento) para renovações.
        Usado para pagamentos recorrentes (monthly) já confirmados.

        Args:
            customer_id: ID do customer no Stripe
            payment_method_id: ID do payment method (cartão tokenizado)
            amount_cents: Valor em centavos
            description: Descrição do pagamento
            subscription_id: ID da subscrição (para logging)

        Returns:
            Tuple: (sucesso: bool, charge_id: str, error_message: str)
        """
        try:
            debug(
                f"[STRIPE] Tentando cobrança off-session para subscription_id={subscription_id}"
            )

            # Buscar o Customer para garantir que ele existe
            try:
                customer = stripe.Customer.retrieve(customer_id)
                debug(f"[STRIPE] Customer recuperado: {customer_id}")
            except Exception as ce:
                error(f"[STRIPE] Erro ao recuperar Customer {customer_id}: {ce}")

            # Criar Payment Intent com confirm=True para cobrança imediata off-session
            intent = stripe.PaymentIntent.create(
                amount=amount_cents,
                currency="brl",
                customer=customer_id,
                payment_method=payment_method_id,
                off_session=True,
                confirm=True,
                description=description,
                metadata={"subscription_id": subscription_id, "type": "retry_payment"},
            )

            if intent.status == "succeeded":
                info(
                    f"[STRIPE] Cobrança off-session bem-sucedida - subscription_id={subscription_id}, intent_id={intent.id}"
                )
                return True, intent.id, None
            elif intent.status == "processing":
                info(
                    f"[STRIPE] Cobrança em processamento - subscription_id={subscription_id}, intent_id={intent.id}"
                )
                return True, intent.id, None
            else:
                warning(
                    f"[STRIPE] Cobrança falhou - subscription_id={subscription_id}, status={intent.status}"
                )
                return False, intent.id, f"Pagamento falhou: {intent.status}"

        except stripe.error.CardError as e:
            error(
                f"[STRIPE] Erro de cartão (off-session) - subscription_id={subscription_id}: {e.user_message}"
            )
            return False, None, f"Cartão recusado: {e.user_message}"

        except stripe.error.StripeError as e:
            error(
                f"[STRIPE] Erro Stripe (off-session) - subscription_id={subscription_id}: {str(e)}"
            )
            return False, None, f"Erro ao cobrar: {str(e)}"

        except Exception as e:
            error(
                f"[STRIPE] Erro ao cobrar off-session - subscription_id={subscription_id}: {e}"
            )
            import traceback

            error(f"[STRIPE] Traceback: {traceback.format_exc()}")
            return False, None, f"Erro ao processar cobrança: {str(e)}"

    def confirm_payment(
        self,
        subscription_id: str,
        user_id: int,
        intent_id: str,
        payment_method_id: str,
        amount: int,
        origin: Optional[str] = None,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Confirma um Payment Intent com um payment method (para pagamentos únicos).

        Args:
            subscription_id: ID da subscrição
            user_id: ID do usuário
            intent_id: ID do payment intent
            payment_method_id: ID do payment method (cartão)
            amount: Valor em centavos

        Returns:
            Tuple: (sucesso: bool, charge_id: str, error_message: str)
        """
        try:
            debug(f"[STRIPE] Confirmando payment intent - intent_id={intent_id}")

            # 1. Buscar o payment intent para obter customer_id
            current_intent = stripe.PaymentIntent.retrieve(intent_id)
            customer_id = current_intent.customer

            # 2. Se tem customer, anexar payment method ao customer (para reutilização futura)
            if customer_id:
                try:
                    stripe.PaymentMethod.attach(payment_method_id, customer=customer_id)
                    debug(
                        f"[STRIPE] Payment method anexado ao customer - customer_id={customer_id}"
                    )
                except stripe.error.StripeError as e:
                    # Pode já estar anexado, não é erro crítico
                    debug(f"[STRIPE] Payment method attach (ignorado): {e}")

            # 3. Confirmar o payment intent com o payment method
            return_url = self.get_stripe_return_url(origin)
            intent = stripe.PaymentIntent.confirm(
                intent_id,
                payment_method=payment_method_id,
                return_url=return_url,  # Necessário para redirect-based payment methods
                # Não usar off_session aqui pois o intent já tem setup_future_usage
                # User está on-session agora, permitindo salvar payment method para uso futuro
            )

            debug(f"[STRIPE] Intent confirmado - status={intent.status}")

            # Extrair charge_id do latest_charge ou da lista de charges
            charge_id = None
            if hasattr(intent, "latest_charge") and intent.latest_charge:
                charge_id = intent.latest_charge
            else:
                # Fallback: usar intent.id para manter compatibilidade
                charge_id = intent.id

            if intent.status == "succeeded":
                info(
                    f"[STRIPE] Pagamento confirmado com sucesso - charge_id={charge_id}"
                )
                return True, charge_id, None
            elif intent.status == "processing":
                info(f"[STRIPE] Pagamento em processamento - charge_id={charge_id}")
                return True, charge_id, None
            elif intent.status == "requires_action":
                warning(
                    f"[STRIPE] Pagamento requer ação adicional - charge_id={charge_id}"
                )
                return False, charge_id, "Pagamento requer autenticação adicional"
            else:
                warning(
                    f"[STRIPE] Pagamento falhou - status={intent.status}, charge_id={charge_id}"
                )
                return False, charge_id, f"Pagamento falhou: {intent.status}"

        except stripe.error.CardError as e:
            error(f"[STRIPE] Erro de cartão ao confirmar: {e.user_message}")
            return False, None, f"Cartão recusado: {e.user_message}"

        except stripe.error.StripeError as e:
            error(f"[STRIPE] Erro Stripe ao confirmar: {str(e)}")
            return False, None, f"Erro ao confirmar pagamento: {str(e)}"

        except Exception as e:
            error(f"[STRIPE] Erro ao confirmar payment intent: {e}")
            import traceback

            error(f"[STRIPE] Traceback: {traceback.format_exc()}")
            return False, None, f"Erro ao confirmar: {str(e)}"

    def validate_webhook_signature(self, body: str, signature: str) -> bool:
        """
        Valida assinatura da webhook Stripe (HMAC-SHA256 com timestamp).

        Args:
            body: Corpo bruto da requisição
            signature: Header Stripe-Signature

        Returns:
            bool: True se assinatura válida
        """
        if not self.webhook_secret:
            error("[STRIPE_WEBHOOK] Webhook secret NÃO configurado!")
            return False

        try:
            # Stripe usa formato: t=timestamp,v1=signature
            event = stripe.Webhook.construct_event(body, signature, self.webhook_secret)

            info(f"[STRIPE_WEBHOOK] Assinatura validada - event_type={event.type}")
            return True

        except ValueError:
            error("[STRIPE_WEBHOOK] Payload inválido")
            return False

        except stripe.error.SignatureVerificationError:
            error("[STRIPE_WEBHOOK] Assinatura INVÁLIDA!")
            return False

        except Exception as e:
            error(f"[STRIPE_WEBHOOK] Erro ao validar assinatura: {e}")
            return False

    async def handle_webhook_event(self, event: Dict[str, Any]) -> bool:
        """
        Processa eventos webhook do Stripe com auditoria.
        """
        db_manager = DatabaseManager()
        stripe_event_id = event.get("id")
        event_type = event.get("type", "unknown")

        # 1. Registrar Auditoria (Audit Log)
        try:
            db_manager.execute_query(
                """INSERT OR IGNORE INTO stripe_webhook_events (stripe_event_id, event_type, body_raw, status)
                   VALUES (:eid, :type, :body, 'pending')""",
                {"eid": stripe_event_id, "type": event_type, "body": json.dumps(event)},
            )
        except Exception as e:
            error(f"[STRIPE_WEBHOOK] Falha ao registrar log de auditoria: {e}")

        try:
            data = event.get("data", {}).get("object", {})
            info(f"[STRIPE_WEBHOOK] Processando evento '{event_type}'")

            success = False
            if event_type == "payment_intent.succeeded":
                success = await self._handle_payment_succeeded(data)
            elif event_type == "payment_intent.payment_failed":
                success = await self._handle_payment_failed(data)
            elif event_type == "charge.refunded":
                success = await self._handle_charge_refunded(data)
            elif event_type == "checkout.session.completed":
                success = await self._handle_checkout_completed(data)
            elif event_type == "customer.subscription.created":
                success = await self._handle_subscription_created(data)
            elif event_type == "customer.subscription.deleted":
                success = await self._handle_subscription_deleted(data)
            elif event_type == "invoice.payment_failed":
                success = await self._handle_invoice_payment_failed(data)
            elif event_type == "invoice.payment_succeeded":
                success = await self._handle_invoice_payment_succeeded(data)
            else:
                debug(f"[STRIPE_WEBHOOK] Evento ignorado: '{event_type}'")
                success = True  # Ignorar é sucesso

            # 2. Atualizar Auditoria
            db_manager.execute_query(
                "UPDATE stripe_webhook_events SET status = :status, processed_at = :now WHERE stripe_event_id = :eid",
                {
                    "status": "processed" if success else "failed",
                    "eid": stripe_event_id,
                    "now": datetime.now().isoformat(),
                },
            )
            return success

        except Exception as e:
            error(f"[STRIPE_WEBHOOK] Erro crítico no handler: {e}")
            db_manager.execute_query(
                "UPDATE stripe_webhook_events SET status = 'failed', error_message = :err WHERE stripe_event_id = :eid",
                {"err": str(e), "eid": stripe_event_id},
            )
            return False

    async def _handle_payment_succeeded(self, data: Dict) -> bool:
        """Pagamento foi bem-sucedido ✅"""
        try:
            charge_id = data.get("id")
            metadata = data.get("metadata", {})
            subscription_id = metadata.get("subscription_id")
            user_id = metadata.get("user_id")
            plan_id = metadata.get("plan_id")
            plan_type = metadata.get("plan_type", "monthly")

            # Dados do Stripe para o cartão
            stripe_pm_id = data.get("payment_method")
            stripe_cus_id = data.get("customer")

            db_manager = DatabaseManager()

            # 1. Tentar recuperar dados faltantes se metadata estiver incompleto
            if not subscription_id and stripe_cus_id:
                # Tentar encontrar a subscrição pelo stripe_customer_id
                sub_by_cus = db_manager.fetch_one(
                    "SELECT subscription_id, client_id, plan_id FROM billing_subscriptions WHERE stripe_customer_id = :cid ORDER BY created_at DESC LIMIT 1",
                    {"cid": stripe_cus_id},
                )
                if sub_by_cus:
                    subscription_id = sub_by_cus["subscription_id"]
                    debug(
                        f"[STRIPE_WEBHOOK] Recuperado subscription_id={subscription_id} via stripe_customer_id"
                    )

            if not subscription_id:
                error(
                    "[STRIPE_WEBHOOK] PaymentIntent sem subscription_id no metadata e não encontrado no DB"
                )
                return False

            # 2. Garantir que temos um user_id para as constraints de DB
            if not user_id:
                # Buscar o primeiro usuário associado a esta subscrição/cliente
                user_row = db_manager.fetch_one(
                    """SELECT u.user_id FROM users u
                       JOIN billing_subscriptions bs ON u.client_id = bs.client_id
                       WHERE bs.subscription_id = :sid LIMIT 1""",
                    {"sid": subscription_id},
                )
                if user_row:
                    user_id = user_row["user_id"]
                    debug(
                        f"[STRIPE_WEBHOOK] Recuperado user_id={user_id} via subscription_id"
                    )
                else:
                    # Último recurso: buscar por stripe_customer_id
                    user_by_cus = db_manager.fetch_one(
                        "SELECT user_id FROM users WHERE client_id = (SELECT client_id FROM billing_subscriptions WHERE stripe_customer_id = :cid LIMIT 1)",
                        {"cid": stripe_cus_id},
                    )
                    user_id = user_by_cus["user_id"] if user_by_cus else None

            if not user_id:
                error(
                    f"[STRIPE_WEBHOOK] Impossível determinar user_id para subscription={subscription_id}"
                )
                return False

            # 🚨 AUTO-CREATE REGISTRO: Se o webhook ganhar a corrida, nós criamos o registro aqui
            sub_row = db_manager.get_subscription_by_id(subscription_id)

            if not sub_row:
                debug(
                    f"[STRIPE_WEBHOOK] Subscrição {subscription_id} não encontrada. Criando registro via Webhook..."
                )

                # Buscar client_id do usuário
                user_data = db_manager.fetch_one(
                    "SELECT client_id FROM users WHERE user_id = :uid", {"uid": user_id}
                )
                client_id = user_data["client_id"] if user_data else f"client_{user_id}"

                # Garantir que temos um cartão registrado
                card_id = "none"
                if stripe_pm_id:
                    # Buscar detalhes do PM no Stripe se necessário (opcional)
                    card_id = db_manager.get_or_create_card_from_stripe(
                        user_id, stripe_pm_id
                    )

                # Tentar converter plan_id numérico para UUID se necessário
                actual_plan_id = plan_id
                if str(plan_id).isdigit() or not plan_id:
                    p_query = (
                        "SELECT plan_id FROM plans WHERE id = :pid"
                        if str(plan_id).isdigit()
                        else "SELECT plan_id FROM plans ORDER BY id ASC LIMIT 1"
                    )
                    p_params = {"pid": plan_id} if str(plan_id).isdigit() else {}
                    p_row = db_manager.fetch_one(p_query, p_params)
                    if p_row:
                        actual_plan_id = p_row["plan_id"]

                # Criar registro via DBManager (centralizado)
                db_manager.create_subscription_record(
                    {
                        "subscription_id": subscription_id,
                        "client_id": client_id,
                        "plan_id": actual_plan_id,
                        "card_id": card_id,
                        "status": "pending_charge",
                        "billing_cycle": plan_type,
                        "stripe_customer_id": stripe_cus_id,
                    }
                )

            # Atualizar payment como pago e gravar charge_id_stripe
            db_manager.execute_query(
                """UPDATE payments
                   SET status = 'paid', charge_id_stripe = :charge_id, updated_at = :updated_at
                   WHERE subscription_id = :subscription_id AND status = 'pending'
                """,
                {
                    "charge_id": charge_id,
                    "updated_at": datetime.now().isoformat(),
                    "subscription_id": subscription_id,
                },
            )

            # 1. Limpar webhook_pending e ativar assinatura
            db_manager.execute_query(
                """UPDATE billing_subscriptions
                   SET status = 'active', webhook_pending = 0, updated_at = :now
                   WHERE subscription_id = :sid
                """,
                {"sid": subscription_id, "now": datetime.now().isoformat()},
            )

            # 2. Buscar user_id (da tabela users) e plan_id (da sub)
            query = """
                SELECT u.user_id, bs.plan_id, bs.client_id
                FROM billing_subscriptions bs
                JOIN users u ON bs.client_id = u.client_id
                WHERE bs.subscription_id = :sid
                LIMIT 1
            """
            sub_data = db_manager.fetch_one(query, {"sid": subscription_id})

            if sub_data:
                # 1. Atualizar plano do cliente
                db_manager.execute_query(
                    "UPDATE clients SET plan_id = (SELECT bs.plan_id FROM billing_subscriptions bs WHERE bs.subscription_id = :sid), updated_at = :now WHERE client_id = :client_id",
                    {
                        "sid": subscription_id,
                        "client_id": sub_data["client_id"],
                        "now": datetime.now().isoformat(),
                    },
                )

                # 2. Distribuir créditos
                from App.Features.Credits.CreditsManager import CreditsManager

                CreditsManager.distribute_plan_credits(
                    sub_data["user_id"], sub_data["plan_id"]
                )

                info(
                    f"[STRIPE_WEBHOOK] Plano ativado e créditos distribuídos - user={sub_data['user_id']}, plan={sub_data['plan_id']}"
                )

            debug(f"[STRIPE_WEBHOOK] Payment succeeded - charge_id={charge_id}")
            info(
                f"[STRIPE_WEBHOOK] Pagamento aprovado - charge_id={charge_id}, subscription_id={subscription_id}"
            )
            return True

        except Exception as e:
            error(f"[STRIPE_WEBHOOK] Erro ao processar pagamento aprovado: {e}")
            return False

    async def _handle_payment_failed(self, data: Dict) -> bool:
        """Pagamento foi recusado ❌"""
        try:
            charge_id = data.get("id")
            failure_message = data.get("last_payment_error", {}).get(
                "message", "Unknown"
            )
            metadata = data.get("metadata", {})
            subscription_id = metadata.get("subscription_id")

            db_manager = DatabaseManager()

            # Agendar retry
            next_retry_at = datetime.now() + timedelta(minutes=5)
            db_manager.execute_query(
                """UPDATE payments
                   SET status = 'failed', charge_id_stripe = :charge_id, error_message = :error_message,
                       next_retry_at = :next_retry_at, retry_count = retry_count + 1, updated_at = :updated_at
                   WHERE subscription_id = :subscription_id AND status = 'pending'
                """,
                {
                    "charge_id": charge_id,
                    "error_message": failure_message,
                    "next_retry_at": next_retry_at.isoformat(),
                    "updated_at": datetime.now().isoformat(),
                    "subscription_id": subscription_id,
                },
            )

            debug(
                f"[STRIPE_WEBHOOK] Payment failed - charge_id={charge_id}, reason={failure_message}"
            )
            warning(
                f"[STRIPE_WEBHOOK] Pagamento falhou - charge_id={charge_id}, motivo={failure_message}"
            )
            return True

        except Exception as e:
            error(f"[STRIPE_WEBHOOK] Erro ao processar pagamento falho: {e}")
            return False

    async def _handle_charge_refunded(self, data: Dict) -> bool:
        """Cobrança foi reembolsada"""
        try:
            charge_id = data.get("id")

            db_manager = DatabaseManager()

            # Atualizar payment como refunded
            db_manager.execute_query(
                """UPDATE payments
                   SET status = 'refunded', updated_at = :updated_at
                   WHERE charge_id_stripe = :charge_id
                """,
                {"updated_at": datetime.now().isoformat(), "charge_id": charge_id},
            )

            debug(f"[STRIPE_WEBHOOK] Charge refunded - charge_id={charge_id}")
            info(f"[STRIPE_WEBHOOK] Reembolso processado - charge_id={charge_id}")
            return True

        except Exception as e:
            error(f"[STRIPE_WEBHOOK] Erro ao processar reembolso: {e}")
            return False

    async def _handle_dispute_created(self, data: Dict) -> bool:
        """Disputa/chargeback foi criada"""
        try:
            dispute_id = data.get("id")
            charge_id = data.get("charge")
            reason = data.get("reason", "unknown")

            db_manager = DatabaseManager()

            # Registrar disputa no payment
            db_manager.execute_query(
                """UPDATE payments
                   SET error_message = :error_message, updated_at = :updated_at
                   WHERE charge_id_stripe = :charge_id
                """,
                {
                    "error_message": f"Dispute created: {reason} (dispute_id={dispute_id})",
                    "updated_at": datetime.now().isoformat(),
                    "charge_id": charge_id,
                },
            )

            debug(
                f"[STRIPE_WEBHOOK] Dispute created - dispute_id={dispute_id}, reason={reason}"
            )
            warning(
                f"[STRIPE_WEBHOOK] Disputa criada - dispute_id={dispute_id}, charge_id={charge_id}"
            )
            return True

        except Exception as e:
            error(f"[STRIPE_WEBHOOK] Erro ao processar disputa: {e}")
            return False

    def _get_user_and_plan_by_stripe_ids(
        self, stripe_subscription_id=None, stripe_customer_id=None
    ):
        """Helper para buscar user_id e plan_id baseados no Stripe IDs (JOIN com users)"""
        db = DatabaseManager()

        # O bs.plan_id já é o UUID do plano
        query_base = """
            SELECT u.user_id, bs.plan_id, bs.client_id
            FROM billing_subscriptions bs
            JOIN users u ON bs.client_id = u.client_id
        """

        if stripe_subscription_id:
            return db.fetch_one(
                f"{query_base} WHERE bs.stripe_subscription_id = :sid LIMIT 1",
                {"sid": stripe_subscription_id},
            )
        if stripe_customer_id:
            return db.fetch_one(
                f"{query_base} WHERE bs.stripe_customer_id = :cid ORDER BY bs.created_at DESC LIMIT 1",
                {"cid": stripe_customer_id},
            )
        return None

    async def _handle_checkout_completed(self, data: Dict) -> bool:
        """Checkout finalizado — ativa a subscrição no banco"""
        try:
            stripe_subscription_id = data.get("subscription")
            stripe_customer_id = data.get("customer")

            if not stripe_subscription_id:
                debug(
                    "[STRIPE_WEBHOOK] checkout.session.completed sem subscription_id — one-time payment, ignorado"
                )
                return True

            db_manager = DatabaseManager()
            db_manager.execute_query(
                """UPDATE billing_subscriptions
                   SET status = 'active', stripe_customer_id = :customer_id, updated_at = :updated_at
                   WHERE stripe_subscription_id = :sub_id
                """,
                {
                    "customer_id": stripe_customer_id,
                    "sub_id": stripe_subscription_id,
                    "updated_at": datetime.now().isoformat(),
                },
            )

            # 2. Atualizar plano e Distribuir créditos
            sub_data = self._get_user_and_plan_by_stripe_ids(
                stripe_subscription_id=stripe_subscription_id
            )
            if sub_data:
                # 1. Atualizar plano do cliente
                db_manager.execute_query(
                    "UPDATE clients SET plan_id = :plan_id, updated_at = :now WHERE client_id = :client_id",
                    {
                        "plan_id": sub_data["plan_id"],
                        "client_id": sub_data["client_id"],
                        "now": datetime.now().isoformat(),
                    },
                )

                # 2. Distribuir créditos
                from App.Features.Credits.CreditsManager import CreditsManager

                CreditsManager.distribute_plan_credits(
                    sub_data["user_id"], sub_data["plan_id"]
                )

                info(
                    f"[STRIPE_WEBHOOK] Checkout: Plano ativado e créditos distribuídos - client={sub_data['client_id']}"
                )

            info(
                f"[STRIPE_WEBHOOK] Checkout concluído — subscription={stripe_subscription_id}, customer={stripe_customer_id}"
            )
            return True

        except Exception as e:
            error(f"[STRIPE_WEBHOOK] Erro ao processar checkout.session.completed: {e}")
            return False

    async def _handle_subscription_created(self, data: Dict) -> bool:
        """Subscrição criada na Stripe — registra stripe_subscription_id no banco"""
        try:
            stripe_subscription_id = data.get("id")
            stripe_customer_id = data.get("customer")
            status = data.get("status", "active")

            db_manager = DatabaseManager()
            db_manager.execute_query(
                """UPDATE billing_subscriptions
                   SET stripe_subscription_id = :sub_id, stripe_customer_id = :customer_id,
                       status = :status, updated_at = :updated_at
                   WHERE stripe_customer_id = :customer_id AND stripe_subscription_id IS NULL
                """,
                {
                    "sub_id": stripe_subscription_id,
                    "customer_id": stripe_customer_id,
                    "status": status,
                    "updated_at": datetime.now().isoformat(),
                },
            )

            info(
                f"[STRIPE_WEBHOOK] Subscrição criada — sub={stripe_subscription_id}, status={status}"
            )
            return True

        except Exception as e:
            error(
                f"[STRIPE_WEBHOOK] Erro ao processar customer.subscription.created: {e}"
            )
            return False

    async def _handle_subscription_deleted(self, data: Dict) -> bool:
        """Subscrição cancelada/expirada — revoga acesso"""
        try:
            stripe_subscription_id = data.get("id")

            db_manager = DatabaseManager()
            db_manager.execute_query(
                """UPDATE billing_subscriptions
                   SET status = 'canceled', updated_at = :updated_at
                   WHERE stripe_subscription_id = :sub_id
                """,
                {
                    "sub_id": stripe_subscription_id,
                    "updated_at": datetime.now().isoformat(),
                },
            )

            warning(
                f"[STRIPE_WEBHOOK] Subscrição cancelada — sub={stripe_subscription_id}"
            )
            return True

        except Exception as e:
            error(
                f"[STRIPE_WEBHOOK] Erro ao processar customer.subscription.deleted: {e}"
            )
            return False

    async def _handle_trial_will_end(self, data: Dict) -> bool:
        """Trial encerrando em 3 dias — log de alerta"""
        try:
            stripe_subscription_id = data.get("id")
            trial_end = data.get("trial_end")

            warning(
                f"[STRIPE_WEBHOOK] Trial encerrando em breve — sub={stripe_subscription_id}, trial_end={trial_end}"
            )
            return True

        except Exception as e:
            error(
                f"[STRIPE_WEBHOOK] Erro ao processar customer.subscription.trial_will_end: {e}"
            )
            return False

    async def _handle_invoice_finalized(self, data: Dict) -> bool:
        """Invoice finalizada — aguardando cobrança"""
        try:
            invoice_id = data.get("id")
            stripe_subscription_id = data.get("subscription")
            amount_due = data.get("amount_due", 0)

            info(
                f"[STRIPE_WEBHOOK] Invoice finalizada — invoice={invoice_id}, sub={stripe_subscription_id}, amount={amount_due}"
            )
            return True

        except Exception as e:
            error(f"[STRIPE_WEBHOOK] Erro ao processar invoice.finalized: {e}")
            return False

    async def _handle_invoice_payment_failed(self, data: Dict) -> bool:
        """Cobrança recorrente falhou — marca subscrição como inadimplente (suspended)"""
        try:
            invoice_id = data.get("id")
            stripe_subscription_id = data.get("subscription")
            attempt_count = data.get("attempt_count", 1)
            failure_message = data.get("last_finalization_error", {}).get(
                "message", "unknown"
            )

            db_manager = DatabaseManager()
            db_manager.execute_query(
                """UPDATE billing_subscriptions
                   SET status = 'suspended', updated_at = :updated_at
                   WHERE stripe_subscription_id = :sub_id
                """,
                {
                    "sub_id": stripe_subscription_id,
                    "updated_at": datetime.now().isoformat(),
                },
            )

            warning(
                f"[STRIPE_WEBHOOK] Cobrança recorrente falhou — invoice={invoice_id}, sub={stripe_subscription_id}, tentativa={attempt_count}, motivo={failure_message}"
            )
            return True

        except Exception as e:
            error(f"[STRIPE_WEBHOOK] Erro ao processar invoice.payment_failed: {e}")
            return False

    async def _handle_invoice_payment_succeeded(self, data: Dict) -> bool:
        """Cobrança recorrente aprovada — renova acesso (JOIN com users)"""
        try:
            invoice_id = data.get("id")
            stripe_subscription_id = data.get("subscription")
            amount_paid = data.get("amount_paid", 0)
            period_end = (
                data.get("lines", {}).get("data", [{}])[0].get("period", {}).get("end")
            )

            db_manager = DatabaseManager()
            db_manager.execute_query(
                """UPDATE billing_subscriptions
                   SET status = 'active', updated_at = :updated_at
                   WHERE stripe_subscription_id = :sub_id
                """,
                {
                    "sub_id": stripe_subscription_id,
                    "updated_at": datetime.now().isoformat(),
                },
            )

            # 2. Atualizar plano e Distribuir créditos na renovação (Helper já faz JOIN)
            sub_data = self._get_user_and_plan_by_stripe_ids(
                stripe_subscription_id=stripe_subscription_id
            )
            if sub_data:
                # 1. Atualizar plano do cliente
                db_manager.execute_query(
                    "UPDATE clients SET plan_id = :plan_id, updated_at = :now WHERE client_id = :client_id",
                    {
                        "plan_id": sub_data["plan_id"],
                        "client_id": sub_data["client_id"],
                        "now": datetime.now().isoformat(),
                    },
                )

                # 2. Distribuir créditos
                from App.Features.Credits.CreditsManager import CreditsManager

                CreditsManager.distribute_plan_credits(
                    sub_data["user_id"], sub_data["plan_id"]
                )

                info(
                    f"[STRIPE_WEBHOOK] Renovação: Plano atualizado e créditos distribuídos - user={sub_data['user_id']}"
                )

            info(
                f"[STRIPE_WEBHOOK] Cobrança recorrente aprovada — invoice={invoice_id}, sub={stripe_subscription_id}, amount={amount_paid}, period_end={period_end}"
            )
            return True

        except Exception as e:
            error(f"[STRIPE_WEBHOOK] Erro ao processar invoice.payment_succeeded: {e}")
            return False

    def refund_charge(self, charge_id: str) -> Tuple[bool, Optional[str]]:
        """
        Faz refund de um charge no Stripe (payment intent ou charge).

        Suporta:
        - Charge ID direto (ex: ch_xxxxx)
        - Subscription ID (ex: sub_xxxxx) - busca o charge do latest_invoice

        Args:
            charge_id: ID do charge/payment intent/subscription a ser reembolsado

        Returns:
            Tuple: (sucesso: bool, refund_id: Optional[str])
        """
        try:
            debug(f"[STRIPE] Iniciando refund - charge_id={charge_id}")

            # Se for subscription ID, obter charge do latest_invoice
            actual_charge_id = charge_id
            if charge_id.startswith("sub_"):
                debug(
                    f"[STRIPE] Detectado subscription ID, buscando charge do invoice..."
                )
                subscription = stripe.Subscription.retrieve(charge_id)
                if subscription.latest_invoice:
                    invoice = stripe.Invoice.retrieve(subscription.latest_invoice)
                    if invoice.charge:
                        actual_charge_id = invoice.charge
                        debug(
                            f"[STRIPE] Charge obtido do subscription - actual_charge_id={actual_charge_id}"
                        )
                else:
                    warning(
                        f"[STRIPE] Subscription sem invoice para refund - subscription_id={charge_id}"
                    )
                    return False, None

            # Criar refund para o charge
            refund = stripe.Refund.create(charge=actual_charge_id)

            info(
                f"[STRIPE] Refund criado com sucesso - refund_id={refund.id}, charge_id={actual_charge_id}"
            )
            return True, refund.id

        except stripe.error.StripeError as e:
            error(f"[STRIPE] Erro Stripe ao fazer refund: {str(e)}")
            return False, None
        except Exception as e:
            error(f"[STRIPE] Erro ao fazer refund: {e}")
            return False, None

    def cancel_subscription(self, subscription_id: str) -> Tuple[bool, Optional[str]]:
        """
        Cancela uma subscription no Stripe.

        Args:
            subscription_id: ID da subscription a ser cancelada

        Returns:
            Tuple: (sucesso: bool, error_message: Optional[str])
        """
        try:
            debug(
                f"[STRIPE] Cancelando subscription - subscription_id={subscription_id}"
            )

            # Cancelar subscription
            stripe.Subscription.delete(subscription_id)

            info(
                f"[STRIPE] Subscription cancelada com sucesso - subscription_id={subscription_id}"
            )
            return True, None

        except stripe.error.StripeError as e:
            error(f"[STRIPE] Erro Stripe ao cancelar subscription: {str(e)}")
            return False, str(e)
        except Exception as e:
            error(f"[STRIPE] Erro ao cancelar subscription: {e}")
            return False, str(e)


# Instância global do serviço
_stripe_payment_service = None


def get_stripe_payment_service() -> StripePaymentService:
    """Retorna instância singleton do StripePaymentService"""
    global _stripe_payment_service
    if _stripe_payment_service is None:
        _stripe_payment_service = StripePaymentService()
    return _stripe_payment_service

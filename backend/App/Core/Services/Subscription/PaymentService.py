"""
Serviço de Pagamento - Integração com Pagarme v5
Responsável por tokenização, validação, cobrança e retry de cartões
Usa a biblioteca oficial pagarme-python para evitar erros de validação
"""

from typing import Dict, Any, Tuple, Optional
import uuid as uuid_lib
import json
import hmac
import hashlib

# from pagarme import transaction as pg_transaction  # DEPRECATED
# from pagarme import authentication_key  # DEPRECATED
# from pagarme import customer as pg_customer  # DEPRECATED
# from pagarme import card as pg_card  # DEPRECATED
import requests
import base64

from App.Core.Logs import debug, info, warning, error
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Core.Settings import load_config


class PaymentService:
    """Serviço para integração com Pagarme v5 usando pagarme-python"""

    def __init__(self):
        self.config = load_config()
        self.api_key = self.config.get("pagarme_api_key", "")
        self.webhook_secret = self.config.get("pagarme_webhook_secret", "")

        if not self.api_key:
            error("[PAYMENT] PAGARME_API_KEY não configurado")
        else:
            # Configurar chave de autenticação da biblioteca pagarme-python
            authentication_key(api_key=self.api_key)

    def _format_document(self, document: str) -> Optional[str]:
        """
        Formata documento para envio à API Pagarme (apenas números, máx 50 chars).

        Args:
            document: Documento (pode estar criptografado ou plaintext)

        Returns:
            str: Documento formatado (apenas números) ou None se inválido
        """
        if not document:
            return None

        # Remover caracteres especiais, deixar apenas números
        clean_doc = "".join(c for c in document if c.isdigit())

        # Validar tamanho (CPF=11, CNPJ=14)
        if len(clean_doc) not in [11, 14]:
            error(f"[PAYMENT] Documento inválido - tamanho={len(clean_doc)}")
            return None

        return clean_doc[:50]

    def _parse_phone(self, phone: str) -> Optional[Dict]:
        """
        Faz parsing do telefone para formato Pagarme.

        Args:
            phone: Telefone no formato (11) 99999-9999 ou 11999999999

        Returns:
            Dict: {country_code, area_code, number} ou None se inválido
        """
        if not phone:
            return None

        # Remover caracteres especiais
        clean_phone = "".join(c for c in phone if c.isdigit())

        # Se começar com 55 (código Brasil), remover
        if clean_phone.startswith("55"):
            clean_phone = clean_phone[2:]

        # Extrair DDD (2 primeiros) e número (últimos 8-9)
        if len(clean_phone) >= 10:
            area_code = clean_phone[:2]
            number = clean_phone[2:]

            return {"country_code": "55", "area_code": area_code, "number": number}

        error(f"[PAYMENT] Telefone inválido: {phone}")
        return None

    def update_customer_phone(
        self,
        customer_id: str,
        phone_data: dict,
        customer_name: str = "Customer",
        customer_document: str = None,
        customer_email: str = None,
    ) -> bool:
        """
        Atualiza dados do customer no Pagarme (nome, telefone, documento, email).

        Args:
            customer_id: ID do customer no Pagarme
            phone_data: Dict com {country_code, area_code, number}
            customer_name: Nome do cliente (obrigatório pelo Pagarme)
            customer_document: CPF/CNPJ do cliente (obrigatório)
            customer_email: Email do cliente (obrigatório para billing no Pagarme)

        Returns:
            bool: True se sucesso
        """
        try:
            headers = {
                "Authorization": f"Basic {self._encode_basic_auth()}",
                "Content-Type": "application/json",
            }

            update_data = {
                "name": customer_name,
                "type": "individual",
                "phones": {"mobile_phone": phone_data},
            }

            if customer_document:
                update_data["document"] = customer_document

            if customer_email:
                update_data["email"] = customer_email

            debug(f"[PAYMENT] Atualizando customer - update_data={update_data}")
            response = requests.put(
                f"{self.base_url}/customers/{customer_id}",
                json=update_data,
                headers=headers,
                timeout=10,
            )

            if response.status_code not in [200, 201]:
                warning(
                    f"[PAYMENT] Falha ao atualizar telefone do customer: {response.text}"
                )
                return False

            debug(
                f"[PAYMENT] Customer atualizado com telefone - customer_id={customer_id}"
            )
            return True

        except Exception as e:
            error(f"[PAYMENT] Erro ao atualizar customer: {e}")
            return False

    def validate_and_tokenize_card(
        self,
        card_number: str,
        holder_name: str,
        expiry_month: int,
        expiry_year: int,
        cvv: str,
        user_document: str = None,
        user_phone: str = None,
        user_email: str = None,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Valida e tokeniza o cartão no Pagarme.
        Utiliza dados reais do usuário (documento e telefone).

        Args:
            card_number: Número do cartão
            holder_name: Nome do titular
            expiry_month: Mês de expiração
            expiry_year: Ano de expiração
            cvv: CVV/CVC
            user_document: Documento do usuário (já descriptografado pelo DBManager)
            user_phone: Telefone do usuário (já descriptografado pelo DBManager)
            user_email: Email do usuário (opcional)

        Returns:
            Tuple: (sucesso: bool, customer_info: dict, error_message: str)
        """
        try:
            debug(f"[PAYMENT] Validando cartão - last_4={card_number[-4:]}")

            # 1. Validar que dados de faturamento existem
            if not user_document or not user_phone:
                error(
                    "[PAYMENT] Billing info incompleto - documento e telefone são obrigatórios"
                )
                return (
                    False,
                    None,
                    "Dados de faturamento incompletos. Preencha billing antes de adicionar cartão.",
                )

            # 2. Formatar e validar documento
            clean_document = self._format_document(user_document)
            if not clean_document:
                error("[PAYMENT] Documento inválido ou não conseguiu ser formatado")
                return False, None, "Documento de faturamento inválido"

            # 3. Parse e validar telefone
            phone_data = self._parse_phone(user_phone)
            if not phone_data:
                error("[PAYMENT] Telefone inválido ou não conseguiu ser parseado")
                return False, None, "Telefone de faturamento inválido"

            # 4. Preparar dados do customer com valores REAIS
            final_email = user_email or f"user+{uuid_lib.uuid4()}@example.com"

            customer_data = {
                "name": holder_name,
                "type": "individual",
                "email": final_email,
                "document": clean_document,
                "phones": {"mobile_phone": phone_data},
            }

            debug(
                f"[PAYMENT] Criando customer com dados reais: email={final_email}, document={clean_document}, phone={phone_data}"
            )

            # 5. Criar customer usando pagarme-python SDK
            try:
                customer = pg_customer.create(customer_data)
                customer_id = customer.get("id")
                debug(
                    f"[PAYMENT] Customer criado com sucesso - customer_id={customer_id}"
                )
            except Exception as e:
                error(f"[PAYMENT] Erro ao criar customer: {str(e)}")
                return False, None, "Erro ao validar cartão com Pagarme"

            # 3. Tokenizar cartão usando pagarme-python SDK
            exp_year_full = int(expiry_year)
            debug(
                f"[PAYMENT] Year format: expiry_year={expiry_year} -> exp_year_full={exp_year_full}"
            )

            card_data = {
                "customer_id": customer_id,
                "number": card_number,
                "holder_name": holder_name,
                "exp_month": expiry_month,
                "exp_year": exp_year_full,
                "cvv": cvv,
            }
            debug(f"[PAYMENT] Card data being sent: {card_data}")

            try:
                card = pg_card.create(card_data)
                card_token = card.get("id")
                debug(f"[PAYMENT] Cartão tokenizado com sucesso - card_id={card_token}")
            except Exception as e:
                error(f"[PAYMENT] Erro ao tokenizar cartão: {str(e)}")
                return False, None, "Cartão inválido ou expirado"

            # Extrair informações do cartão retornadas pelo Pagarme
            card_info = {
                "card_id": card_token,
                "customer_id": customer_id,
                "brand": card.get("brand", "unknown"),
                "last_4": card.get("last_four")
                or card.get("last_4")
                or card_number[-4:],
                "exp_month": int(card.get("exp_month") or expiry_month),
                "exp_year": int(card.get("exp_year") or exp_year_full),
                "holder_name": card.get("holder_name") or holder_name,
            }

            debug(f"[PAYMENT] Card info extraído: {card_info}")

            # Cartão tokenizado com sucesso - retornar informações completas
            info(f"[PAYMENT] Cartão tokenizado com sucesso - {card_info}")
            return True, card_info, None

        except Exception as e:
            error(f"[PAYMENT] Erro ao validar cartão: {e}")
            return False, None, "Erro ao validar cartão"

    def charge_subscription(
        self,
        subscription_id: str,
        customer_id: str,
        card_id: str,
        amount: int,
        description: str = "Cobrança de subscrição",
        idempotency_key: Optional[str] = None,
        customer_phone: Optional[Dict] = None,
        customer_name: str = "Customer",
        customer_document: Optional[str] = None,
        billing_psp: Optional[Dict] = None,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Cobra um valor específico do cartão do usuário usando pagarme-python SDK.

        Args:
            subscription_id: ID da subscrição (para referência)
            customer_id: ID do customer no Pagarme
            card_id: ID do cartão tokenizado
            amount: Valor em centavos
            description: Descrição da cobrança

        Returns:
            Tuple: (sucesso: bool, charge_id: str, error_message: str)
        """
        try:
            debug(
                f"[PAYMENT] Cobrando subscrição - subscription_id={subscription_id}, amount={amount}"
            )

            # Preparar billing_address para o credit_card
            billing_address_data = {}
            if billing_psp and "address" in billing_psp:
                billing_addr = billing_psp["address"]
                street_full = f"{billing_addr.get('street', '')}, {billing_addr.get('street_number', '1')}"
                if billing_addr.get("neighborhood"):
                    street_full += f" - {billing_addr.get('neighborhood')}"

                billing_address_data = {
                    "country": billing_addr.get("country", "BR"),
                    "state": billing_addr.get("state"),
                    "city": billing_addr.get("city"),
                    "zip_code": billing_addr.get("zipcode", "").replace("-", ""),
                    "line_1": street_full,
                }

            # Criar transação usando a biblioteca pagarme-python
            # Esta é a estrutura simplificada que a lib espera
            transaction_data = {
                "amount": amount,
                "customer": {
                    "external_id": subscription_id,
                    "name": customer_name,
                    "type": "individual",
                    "country": "BR",
                    "email": (
                        billing_psp.get("email")
                        if billing_psp
                        else "customer@example.com"
                    ),
                    "documents": [
                        {"type": "cpf", "number": customer_document or "00000000000"}
                    ],
                    "phone_numbers": (
                        [
                            f"{customer_phone.get('country_code', '55')}{customer_phone.get('area_code', '11')}{customer_phone.get('number', '0')}"
                        ]
                        if customer_phone
                        else ["5511999999999"]
                    ),
                    "birthday": "1990-01-01" if not customer_document else None,
                },
                "card_id": card_id,
                "description": description,
                "metadata": {
                    "subscription_id": subscription_id,
                    "type": "subscription",
                },
            }

            debug(f"[PAYMENT] Transaction data payload: {transaction_data}")

            # Pagarme v5 usa /charges, não /transactions
            # A biblioteca pagarme-python usa endpoint errado, então usar requests direto
            auth_string = f"{self.api_key}:"
            auth_b64 = base64.b64encode(auth_string.encode()).decode()

            headers = {
                "Authorization": f"Basic {auth_b64}",
                "Content-Type": "application/json",
            }

            response = requests.post(
                "https://api.pagar.me/core/v5/charges",
                json=transaction_data,
                headers=headers,
                timeout=10,
            )

            debug(f"[PAYMENT] Response status: {response.status_code}")

            if response.status_code not in [200, 201]:
                error(f"[PAYMENT] Charge failed - {response.text}")
                raise Exception(f"Charge creation failed: {response.text}")

            response = response.json()

            debug(
                f"[PAYMENT] Transaction response: {json.dumps(response, indent=2, default=str)}"
            )

            debug(
                f"[PAYMENT] Transaction response (full): {json.dumps(response, indent=2, default=str)}"
            )

            if response.get("status") == "paid":
                charge_id = response.get("id")
                info(f"[PAYMENT] Cobrança bem-sucedida - charge_id={charge_id}")
                return True, charge_id, None
            else:
                charge_id = response.get("id")
                status = response.get("status")

                # Extrair mensagem de erro com fallback seguro
                error_msg = "Unknown error"

                # Tentar diferentes locais de erro
                if isinstance(response.get("errors"), list) and response["errors"]:
                    error_msg = response["errors"][0].get(
                        "message", str(response["errors"][0])
                    )
                elif isinstance(response.get("last_transaction"), dict):
                    gateway_errors = (
                        response["last_transaction"]
                        .get("gateway_response", {})
                        .get("errors", [])
                    )
                    if isinstance(gateway_errors, list) and gateway_errors:
                        error_msg = gateway_errors[0].get(
                            "message", str(gateway_errors[0])
                        )
                else:
                    error_msg = f"status={status}"

                warning(
                    f"[PAYMENT] Cobrança falhou - charge_id={charge_id}, {error_msg}"
                )
                return False, charge_id, error_msg

        except Exception as e:
            error(f"[PAYMENT] Erro ao cobrar: {str(e)}")
            import traceback

            error(f"[PAYMENT] Traceback: {traceback.format_exc()}")

            # Tentar extrair resposta do Pagarme se disponível
            import sys

            exc_info = sys.exc_info()
            if exc_info[1] and hasattr(exc_info[1], "response"):
                try:
                    response_data = exc_info[1].response.json()
                    error(
                        f"[PAYMENT] Pagarme response: {json.dumps(response_data, indent=2)}"
                    )
                except:
                    pass

            return False, None, f"Erro ao processar cobrança: {str(e)}"

    def charge_subscription_with_retry(
        self,
        subscription_id: str,
        user_id: int,
        customer_id: str,
        card_id: str,
        amount: int,
        description: str = "Cobrança de subscrição",
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Cria uma transação de pagamento com retry automático

        Args:
            subscription_id: UUID da subscrição
            user_id: ID do usuário
            customer_id: ID do customer no Pagarme
            card_id: ID do cartão tokenizado
            amount: Valor em centavos
            description: Descrição da cobrança

        Returns:
            Tuple: (sucesso, payment_id, error_message)
        """
        try:
            # Gerar IDs únicos
            payment_id = str(uuid_lib.uuid4())
            idempotency_key = str(uuid_lib.uuid4())

            info(
                f"[PAYMENT] Criando payment - payment_id={payment_id}, subscription_id={subscription_id}"
            )

            # Buscar e descriptografar pagarme_card_id
            pagarme_card_id = self.get_pagarme_card_id(card_id)
            if not pagarme_card_id:
                error(
                    f"[PAYMENT] Não conseguiu recuperar pagarme_card_id para card_id={card_id}"
                )
                return (
                    False,
                    payment_id,
                    "Cartão não encontrado ou pagarme_card_id inválido",
                )

            # Salvar no DB como pending
            db_manager = DatabaseManager()
            db_manager.execute(
                """
                INSERT INTO payments (payment_id, idempotency_key, subscription_id, user_id,
                                    charge_id_pagarme, amount, description, status, retry_count, max_retries)
                VALUES (?, ?, ?, ?, NULL, ?, ?, 'pending', 0, ?)
                """,
                (
                    payment_id,
                    idempotency_key,
                    subscription_id,
                    user_id,
                    amount,
                    description,
                    self.max_retries,
                ),
            )

            # Tentar cobrar com pagarme_card_id descriptografado
            success, charge_id, error_msg = self.charge_subscription(
                subscription_id=subscription_id,
                customer_id=customer_id,
                card_id=pagarme_card_id,
                amount=amount,
                description=description,
                idempotency_key=idempotency_key,
            )

            if success:
                # Atualizar com charge_id do Pagarme
                db_manager.execute(
                    "UPDATE payments SET charge_id_pagarme=?, status='paid', updated_at=CURRENT_TIMESTAMP WHERE payment_id=?",
                    (charge_id, payment_id),
                )
                info(
                    f"[PAYMENT] Payment aprovado - payment_id={payment_id}, charge_id={charge_id}"
                )
                return True, payment_id, None
            else:
                # Agendarretry próximo
                next_retry_at = datetime.now() + timedelta(seconds=self.base_wait_time)
                db_manager.execute(
                    """
                    UPDATE payments
                    SET status='failed', error_message=?, retry_count=1, next_retry_at=?, updated_at=CURRENT_TIMESTAMP
                    WHERE payment_id=?
                    """,
                    (error_msg, next_retry_at, payment_id),
                )
                warning(
                    f"[PAYMENT] Payment falhou - payment_id={payment_id}, erro={error_msg}"
                )
                return False, payment_id, error_msg

        except Exception as e:
            error(f"[PAYMENT] Erro ao criar payment: {e}")
            return False, None, str(e)

    def process_pending_retries(self) -> int:
        """
        Processa payments pendentes de retry
        Chamada periodicamente (cron job)

        Returns:
            int: Número de payments processados
        """
        try:
            db_manager = DatabaseManager()

            # Buscar payments com retry pendente
            result = db_manager.fetch(
                """
                SELECT payment_id, idempotency_key, subscription_id, user_id, charge_id_pagarme,
                       amount, description, retry_count, max_retries
                FROM payments
                WHERE status='failed'
                AND retry_count < max_retries
                AND next_retry_at <= CURRENT_TIMESTAMP
                ORDER BY next_retry_at ASC
                LIMIT 10
                """
            )

            if not result:
                debug("[PAYMENT] Nenhum retry pendente")
                return 0

            processed_count = 0

            for payment in result:
                payment_id = payment[0]
                idempotency_key = payment[1]
                subscription_id = payment[2]
                user_id = payment[3]
                charge_id_pagarme = payment[4]
                amount = payment[5]
                description = payment[6]
                retry_count = payment[7]
                max_retries = payment[8]

                info(
                    f"[PAYMENT] Retentando payment - payment_id={payment_id}, tentativa {retry_count + 1}/{max_retries}"
                )

                # TODO: Buscar customer_id e card_id do banco
                # Por enquanto, skip de retry automático sem esses dados

                processed_count += 1

            return processed_count

        except Exception as e:
            error(f"[PAYMENT] Erro ao processar retries: {e}")
            return 0

    def validate_webhook_signature(self, body: str, signature: str) -> bool:
        """
        Valida assinatura HMAC-SHA256 da webhook

        Args:
            body: Corpo bruto da requisição
            signature: Header X-Pagar-Me-Signature

        Returns:
            bool: True se assinatura válida
        """
        if not self.webhook_secret:
            error("[WEBHOOK] Webhook secret NÃO configurado!")
            return False

        debug(f"[WEBHOOK] Secret carregado: {self.webhook_secret[:20]}...")
        debug(f"[WEBHOOK] Signature recebida: {signature[:50]}...")

        expected_signature = hmac.new(
            self.webhook_secret.encode(), body.encode(), hashlib.sha256
        ).hexdigest()

        debug(f"[WEBHOOK] Signature esperada: {expected_signature[:50]}...")

        is_valid = hmac.compare_digest(expected_signature, signature)

        if not is_valid:
            warning(f"[WEBHOOK] Assinatura INVÁLIDA!")
            debug(f"[WEBHOOK] Esperado: {expected_signature}")
            debug(f"[WEBHOOK] Recebido: {signature}")
        else:
            info("[WEBHOOK] Assinatura VALIDADA com sucesso!")

        return is_valid

    async def handle_webhook_event(self, webhook_data: Dict[str, Any]) -> bool:
        """
        Processa eventos webhook do Pagarme

        Args:
            webhook_data: Dados do evento

        Returns:
            bool: True se processado com sucesso
        """
        try:
            event_type = webhook_data.get("type")
            charge_data = webhook_data.get("data", {})
            charge_id = charge_data.get("id")
            status = charge_data.get("status")

            info(
                f"[WEBHOOK] Processando evento {event_type} - charge_id={charge_id}, status={status}"
            )

            if event_type == "charge.paid":
                return await self._handle_charge_paid(charge_data)
            elif event_type == "charge.failed":
                return await self._handle_charge_failed(charge_data)
            elif event_type == "charge.refunded":
                return await self._handle_charge_refunded(charge_data)
            elif event_type == "charge.updated":
                return await self._handle_charge_updated(charge_data)
            else:
                warning(f"[WEBHOOK] Evento desconhecido: {event_type}")
                return True

        except Exception as e:
            error(f"[WEBHOOK] Erro ao processar evento: {e}")
            return False

    async def _handle_charge_paid(self, charge_data: Dict) -> bool:
        """Cobrança foi aprovada ✅"""
        try:
            charge_id = charge_data.get("id")
            db_manager = DatabaseManager()

            # Atualizar payment como pago
            db_manager.execute(
                "UPDATE payments SET status='paid', charge_id_pagarme=?, updated_at=CURRENT_TIMESTAMP WHERE charge_id_pagarme=?",
                (charge_id, charge_id),
            )

            # TODO: Atualizar subscription como ativa

            info(f"[WEBHOOK] Cobrança aprovada: {charge_id}")
            return True

        except Exception as e:
            error(f"[WEBHOOK] Erro ao processar charge.paid: {e}")
            return False

    async def _handle_charge_failed(self, charge_data: Dict) -> bool:
        """Cobrança foi recusada ❌"""
        try:
            charge_id = charge_data.get("id")
            decline_reason = charge_data.get("decline_reason", "Unknown")
            db_manager = DatabaseManager()

            # Atualizar payment como falho e agendar retry
            next_retry_at = datetime.now() + timedelta(minutes=5)
            db_manager.execute(
                """
                UPDATE payments
                SET status='failed', error_message=?, retry_count=retry_count+1, next_retry_at=?, updated_at=CURRENT_TIMESTAMP
                WHERE charge_id_pagarme=?
                """,
                (f"Decline reason: {decline_reason}", next_retry_at, charge_id),
            )

            warning(f"[WEBHOOK] Cobrança recusada: {charge_id} - {decline_reason}")
            return True

        except Exception as e:
            error(f"[WEBHOOK] Erro ao processar charge.failed: {e}")
            return False

    async def _handle_charge_refunded(self, charge_data: Dict) -> bool:
        """Cobrança foi reembolsada"""
        try:
            charge_id = charge_data.get("id")
            db_manager = DatabaseManager()

            # Atualizar payment como reembolsado
            db_manager.execute(
                "UPDATE payments SET status='refunded', updated_at=CURRENT_TIMESTAMP WHERE charge_id_pagarme=?",
                (charge_id,),
            )

            # TODO: Atualizar subscription como inativa

            info(f"[WEBHOOK] Reembolso processado: {charge_id}")
            return True

        except Exception as e:
            error(f"[WEBHOOK] Erro ao processar charge.refunded: {e}")
            return False

    async def _handle_charge_updated(self, charge_data: Dict) -> bool:
        """Log apenas para status updates"""
        charge_id = charge_data.get("id")
        status = charge_data.get("status")
        debug(f"[WEBHOOK] Cobrança atualizada: {charge_id} - novo status: {status}")
        return True

    def get_pagarme_card_id(self, card_id: str) -> str:
        """
        Busca o pagarme_card_id do cartão.
        O DBManager já descriptografa automaticamente (table_name='cards').

        Args:
            card_id: ID interno do cartão na tabela cards

        Returns:
            str: pagarme_card_id descriptografado (token do Pagarme)
        """
        try:
            db = DatabaseManager()
            # DBManager.fetch_one com table_name='cards' já descriptografa automaticamente
            card = db.fetch_one(
                "SELECT pagarme_card_id FROM cards WHERE card_id = :card_id",
                {"card_id": card_id},
                table_name="cards",  # Isso já descriptografa pagarme_card_id automaticamente
            )

            if not card:
                error(f"[PAYMENT] Cartão não encontrado - card_id={card_id}")
                return None

            pagarme_card_id = card.get("pagarme_card_id")
            if not pagarme_card_id:
                error(
                    f"[PAYMENT] pagarme_card_id não encontrado para card_id={card_id}"
                )
                return None

            debug(
                f"[PAYMENT] pagarme_card_id obtido (já descriptografado) para card_id={card_id}"
            )
            return pagarme_card_id
        except Exception as e:
            error(f"[PAYMENT] Erro ao obter pagarme_card_id: {e}")
            return None


# Instância global do serviço
_payment_service = None


def get_payment_service() -> PaymentService:
    """Retorna instância singleton do PaymentService"""
    global _payment_service
    if _payment_service is None:
        _payment_service = PaymentService()
    return _payment_service

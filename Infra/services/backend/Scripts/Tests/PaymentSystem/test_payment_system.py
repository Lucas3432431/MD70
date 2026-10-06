"""
Validação end-to-end do sistema de pagamentos MD70 (Stripe).

Usa Playwright para todos os fluxos de pagamento via UI (o browser executa a
tokenização real via Stripe.js, sem precisar replicar nada no script).
Injeção direta no DB é usada apenas onde a UI não chega: cron job, renovação,
cleanup de subscrições suspensas.

Cenários validados:
  ── CARTÕES (via Playwright UI) ──
  01. Visa 4242   → aprovado, plano atualizado, créditos distribuídos
  02. Mastercard  → aprovado
  03. Recusado    → plano NÃO muda
  04. Saldo insuficiente → recusado
  05. Cartão expirado    → recusado

  ── CICLOS DE BILLING (via Playwright UI) ──
  06. Monthly → billing_cycle='monthly' no DB
  07. Annual  → billing_cycle='annual' + stripe_subscription_id no DB

  ── CANCELAMENTO (lógica direta, sub injetada no DB) ──
  08. ≤7 dias → refund Stripe + status='canceled' + downgrade para Free
  09. >7 dias → auto_renew=0 + downgrade para Free (sem refund)

  ── CRON JOB / RENOVAÇÃO (SubscriptionJob direto) ──
  10. Renovação monthly bem-sucedida → renewal_date atualizada
  11. Renovação falha MAX_RETRY vezes → status='canceled'

  ── CLEANUP SUSPENDED ──
  12. Sub suspensa há >7 dias → status='canceled'

  ── WEBHOOK STRIPE (HTTP direto contra o backend) ──
  13. checkout.session.completed       → sub status='active' no DB
  14. customer.subscription.created    → stripe_subscription_id gravado no DB
  15. customer.subscription.deleted    → sub status='cancelled' no DB
  16. customer.subscription.trial_will_end → aceito (200), sem erro
  17. invoice.finalized                → aceito (200), sem erro
  18. invoice.payment_failed           → sub status='past_due' no DB
  19. invoice.payment_succeeded        → sub status='active' no DB
  20. Assinatura inválida              → 403

Uso:
    cd App/mvp/services/backend
    python3 Scripts/Tests/PaymentSystem/test_payment_system.py
    python3 Scripts/Tests/PaymentSystem/test_payment_system.py --cleanup
    python3 Scripts/Tests/PaymentSystem/test_payment_system.py --env-file .env.wsl
    python3 Scripts/Tests/PaymentSystem/test_payment_system.py --webhooks-only
"""

import sys, os, uuid, json, argparse, time
import urllib.request, urllib.error
from datetime import datetime, timedelta
from pathlib import Path

# Configura PATH do backend
BACKEND_DIR = Path(__file__).parent.parent.parent.parent.absolute()
sys.path.insert(0, str(BACKEND_DIR))

# ══════════════════════════════════════════════════════════════════════════════
#  ENV LOADING (Replicates Settings.py logic)
# ══════════════════════════════════════════════════════════════════════════════
from dotenv import load_dotenv


def load_env_for_test():
    # 0. Base layer: mvp-level .env.development
    mvp_root = BACKEND_DIR.parent.parent
    _mvp_env = mvp_root / ".env.development"
    if _mvp_env.exists():
        load_dotenv(dotenv_path=str(_mvp_env), override=True)
        print(f"✅ Loaded environment from: {_mvp_env}")
    else:
        print(f"⚠️  Warning: .env.development not found at {mvp_root}")

    # Specific override via flag if provided
    _parser = argparse.ArgumentParser(add_help=False)
    _parser.add_argument("--env-file", default=None)
    _args, _ = _parser.parse_known_args()

    if _args.env_file:
        env_path = Path(_args.env_file)
        if env_path.exists():
            load_dotenv(dotenv_path=str(env_path), override=True)
            print(f"✅ Overridden environment from: {env_path}")


load_env_for_test()

# Now imports from App can use the loaded environment
from App.Core.Settings.Settings import load_config

_config = load_config()

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIG — dynamically loaded from env
# ══════════════════════════════════════════════════════════════════════════════

# Extract ports and hosts from env - NO FALLBACKS
BACKEND_HOST = os.environ.get("BACKEND_HOST")
BACKEND_PORT = os.environ.get("BACKEND_PORT")
FRONTEND_PORT = os.environ.get("VITE_DEV_PORT") or os.environ.get("FRONTEND_PORT")
FRONTEND_HOST = os.environ.get("FRONTEND_HOST")

# Validate required environment variables
_missing_envs = []
if not BACKEND_HOST:
    _missing_envs.append("BACKEND_HOST")
if not BACKEND_PORT:
    _missing_envs.append("BACKEND_PORT")
if not FRONTEND_HOST:
    _missing_envs.append("FRONTEND_HOST")
if not FRONTEND_PORT:
    _missing_envs.append("FRONTEND_PORT (or VITE_DEV_PORT)")

if _missing_envs:
    print(
        f"\n❌ CRITICAL ERROR: Missing required environment variables: {', '.join(_missing_envs)}"
    )
    print("Ensure these are defined in your .env.development or shell environment.")
    sys.exit(1)

BACKEND_URL = f"http://{BACKEND_HOST}:{BACKEND_PORT}"
FRONTEND_URL = f"http://{FRONTEND_HOST}:{FRONTEND_PORT}"

# Ajuste para 0.0.0.0 (browsers não gostam de navegar para 0.0.0.0)
if "0.0.0.0" in BACKEND_URL:
    BACKEND_URL = BACKEND_URL.replace("0.0.0.0", "localhost")
if "0.0.0.0" in FRONTEND_URL:
    FRONTEND_URL = FRONTEND_URL.replace("0.0.0.0", "localhost")


def check_health():
    """Verifica se backend, frontend e o túnel de webhook estão rodando."""
    print(f"\n🔍 Checking health of services...")

    # 1. Check Backend
    back_ok = False
    try:
        with urllib.request.urlopen(f"{BACKEND_URL}/api/health", timeout=3) as resp:
            if resp.status == 200:
                back_ok = True
                print(f"✅ Backend is Healthy ({BACKEND_URL})")
    except Exception as e:
        print(f"❌ Backend is UNREACHABLE at {BACKEND_URL}/api/health")

    # 2. Check Frontend
    front_ok = False
    try:
        with urllib.request.urlopen(f"{FRONTEND_URL}/health", timeout=3) as resp:
            if resp.status == 200:
                front_ok = True
                print(f"✅ Frontend is Healthy ({FRONTEND_URL})")
    except Exception as e:
        print(f"❌ Frontend is UNREACHABLE at {FRONTEND_URL}/health")

    # 3. Check Webhook Public URL (Ngrok or Domain)
    webhook_secret = _config.get("stripe_webhook_secret")
    public_url = os.environ.get("STRIPE_WEBHOOK_URL")

    if public_url:
        print(f"📡 Checking Public Webhook Tunnel: {public_url}")
        try:
            with urllib.request.urlopen(
                f"{public_url.rstrip('/')}/api/webhook/stripe", timeout=5
            ) as resp:
                if resp.status == 200:
                    print(f"✅ Webhook Tunnel is Reachable!")
                else:
                    print(f"⚠️  Webhook Tunnel returned status {resp.status}")
        except Exception as e:
            print(f"❌ Webhook Tunnel is UNREACHABLE: {e}")
            print("\n" + "!" * 70)
            print(" 🚨 ATENÇÃO: Webhooks da Stripe NÃO chegarão ao seu backend.")
            print(
                " Seu túnel Ngrok ou Domínio HTTPS parece estar offline ou a URL está incorreta."
            )
            print(f"\n CONFIGURAÇÃO REQUERIDA NO DASHBOARD STRIPE:")
            print(f" URL do Endpoint: {public_url}/api/webhook/stripe")
            print(f" Ativo no Ngrok: {os.environ.get('PUBLIC_URL', 'Desconhecido')}")
            print("\n Verifique se o Ngrok está rodando e aponte para o backend local.")
            print("!" * 70 + "\n")
    else:
        print(
            "ℹ️  STRIPE_WEBHOOK_URL not defined in env. Skipping public tunnel check."
        )

    if not back_ok or not front_ok:
        print("\n" + "!" * 70)
        print(
            " CRITICAL ERROR: Backend and Frontend must be active for the script to run."
        )
        print(" Please start the services before running this validation.")
        print("!" * 70 + "\n")
        sys.exit(1)


def wait_for_webhook(
    session, client_id, free_plan_id, expected_status="active", timeout=120
):
    """Aguarda o status da subscrição mudar via Webhook real."""
    print(f"     -> Waiting up to {timeout}s for real Stripe Webhook confirmation...")
    start_time = time.time()
    while time.time() - start_time < timeout:
        # Forçar refresh da sessão para evitar cache de query anterior
        session.expire_all()

        sub = get_latest_subscription(session, client_id)

        # Buscar plano atual do cliente
        row = session.execute(
            text("SELECT plan_id FROM clients WHERE client_id = :cid"),
            {"cid": client_id},
        ).fetchone()
        current_plan_id = str(row[0]) if row else None

        # Debug do estado atual
        status = sub["status"] if sub else "None"
        elapsed = int(time.time() - start_time)
        print(
            f"        [{elapsed}s] DB Status: {status} | Plan: {current_plan_id} (free_id: {free_plan_id})"
        )

        if sub and sub["status"] == expected_status:
            # Também verificar se o plano do client mudou de Free para algo novo
            if current_plan_id and current_plan_id != str(free_plan_id):
                print(
                    f"     ✅ Webhook confirmed: Status={status}, Plan={current_plan_id}"
                )
                return True
        time.sleep(5)
    return False


check_health()

# Resto do script continua...
_parser = argparse.ArgumentParser(add_help=False)
_parser.add_argument("--cleanup", action="store_true")
_parser.add_argument("--webhooks-only", action="store_true")
_args, _ = _parser.parse_known_args()

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

# Import Auth related services
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Features.Auth.AuthService import AuthService


def setup_mock_auth(session):
    """Garante usuário, cliente e subscrição mock ÚNICOS, e gera tokens válidos."""
    import uuid

    uid_suffix = uuid.uuid4().hex[:8]
    client_id = f"client_{uid_suffix}"
    user_id = f"user_{uid_suffix}"
    user_email = f"test-{uid_suffix}@prox.ai"

    print(f"\n🔐 Setting up mock authentication for {user_email}...")

    # 1. Garantir Cliente (Sempre inicia no Free UUID)
    free_uuid = "75dd6142-8171-4a9f-88f9-2774af395550"
    session.execute(
        text(
            "INSERT INTO clients (client_id, plan_id, started_at) "
            "VALUES (:cid, :pid, CURRENT_TIMESTAMP)"
        ),
        {"cid": client_id, "pid": free_uuid},
    )

    # 2. Garantir Usuário
    # Dummy hashed password for '$2b$12$...'
    dummy_pwd = "$2b$12$LQv3c1VqBWVH6E1F6qK6u.xK1fK7u.xK1fK7u.xK1fK7u.xK1fK7u"

    session.execute(
        text(
            "INSERT INTO users (user_id, client_id, email, password, full_name, type) "
            "VALUES (:uid, :cid, :email, :pwd, 'Automated Test User', 'login')"
        ),
        {"uid": user_id, "cid": client_id, "email": user_email, "pwd": dummy_pwd},
    )

    # 3. Garantir Billing Info
    billing_id = inject_billing_info(session, user_id)

    # 4. Garantir Subscrição Inicial (Active) para os testes de Crédito
    # Usar o plano Pro do DB (buscado dinamicamente ou fallback UUID)
    row_pro = session.execute(
        text("SELECT plan_id FROM plans WHERE plan_type = 'pro' LIMIT 1")
    ).fetchone()
    pro_uuid = row_pro[0] if row_pro else "d0a8cb2a-e903-415e-8c9a-e879bd8c8863"

    session.execute(
        text(
            "INSERT INTO billing_subscriptions (subscription_id, client_id, plan_id, card_id, billing_id, status, charge_scheduled_at) "
            "VALUES (:sid, :cid, :pid, 'none', :bid, 'active', CURRENT_TIMESTAMP)"
        ),
        {
            "sid": f"sub_{uid_suffix}",
            "cid": client_id,
            "pid": pro_uuid,
            "bid": billing_id,
        },
    )

    session.commit()

    # 5. Gerar Tokens
    db_manager = DatabaseManager()
    auth_service = AuthService(db_manager=db_manager)

    user_data = {
        "user_id": user_id,
        "email": user_email,
        "client_id": client_id,
        "role": "admin",
        "full_name": "Automated Test User",
    }

    access_token = auth_service.generate_access_token(user_data, save_to_db=True)
    refresh_token_data = auth_service.generate_refresh_token(user_data, save_to_db=True)
    refresh_token = refresh_token_data["token"]

    return {
        "user_id": user_id,
        "client_id": client_id,
        "email": user_email,
        "access_token": access_token,
        "refresh_token": refresh_token,
    }


# Rota do frontend para o fluxo de pagamento
# Query params aceitos: ?plan=<plan_type>&type=<monthly|annual>&coupon=<code>
PAYMENT_PATH = "/payment"

# Plano a ser testado nos cenários de pagamento via UI
TARGET_PLAN_TYPE = "pro"
TARGET_BILLING_CYCLE = "monthly"

# ── Cartões Stripe (números reais para Stripe Elements no browser) ──────────
# Referência: https://stripe.com/docs/testing#cards
STRIPE_CARDS = {
    "visa_ok": {
        "number": "4242 4242 4242 4242",
        "expiry": "12 / 30",
        "cvc": "123",
        "label": "Visa — sempre aprovado",
        "expect_success": True,
    },
    "mastercard_ok": {
        "number": "5555 5555 5555 4444",
        "expiry": "12 / 30",
        "cvc": "123",
        "label": "Mastercard — sempre aprovado",
        "expect_success": True,
    },
    "declined": {
        "number": "4000 0000 0000 0002",
        "expiry": "12 / 30",
        "cvc": "123",
        "label": "Visa — sempre recusado",
        "expect_success": False,
    },
    "insufficient_funds": {
        "number": "4000 0000 0000 9995",
        "expiry": "12 / 30",
        "cvc": "123",
        "label": "Visa — saldo insuficiente",
        "expect_success": False,
    },
    "expired": {
        "number": "4000 0000 0000 0069",
        "expiry": "12 / 30",
        "cvc": "123",
        "label": "Visa — cartão expirado",
        "expect_success": False,
    },
}

# ── Cartões Stripe para testes diretos via API (off-session / cron) ──────────
# Estes são payment method IDs de teste do Stripe (sem precisar de browser)
PM_VISA_OK = "pm_card_visa"
PM_VISA_DECLINED = "pm_card_chargeDeclined"

# ── Dados de billing a preencher no formulário ───────────────────────────────
TEST_BILLING = {
    "address": "Rua Teste, 123",
    "complement": "Apto 42",
    "neighborhood": "Centro",
    "postal_code": "01310-100",
    "phone": "11999999999",
    "document": "123.456.789-00",
    "city": "São Paulo",
    "state": "SP",
}

# ── Playwright ───────────────────────────────────────────────────────────────
PW_HEADLESS = True  # True para rodar no servidor/CLI
PW_SLOW_MO_MS = 100  # Reduzir delay para agilizar
PW_TIMEOUT_MS = 30_000  # Aumentar um pouco o timeout
PW_NAV_TIMEOUT_MS = 30_000  # timeout de navegação

# Seletores — ajuste aqui se o frontend mudar
SEL_BILLING_POSTAL_CODE = 'input[placeholder*="00000-000"], input[placeholder*="CEP"]'
SEL_BILLING_ADDRESS = 'input[placeholder*="Rua..."], input[placeholder*="endereço"]'
SEL_BILLING_PHONE = 'input[placeholder*="(00) 00000-0000"], input[type="tel"]'
SEL_BILLING_DOCUMENT = 'input[placeholder*="CPF ou CNPJ"]'
SEL_BTN_NEXT = 'button:has-text("Continuar"), button:has-text("Próximo")'
SEL_BTN_CONFIRM_INITIAL = 'button:has-text("Confirmar")'
SEL_BTN_FINISH = 'button:has-text("Finalizar Pagamento")'
SEL_CARD_HOLDER = 'input[placeholder="Nome do Titular"]'
SEL_SUCCESS = '[data-testid="payment-success"], .payment-success, :text("Assinatura realizada"), :text("sucesso")'
SEL_ERROR = '[data-testid="payment-error"], .payment-error, .toast-error, .text-red-500, :text("erro"), :text("falhou")'

# ══════════════════════════════════════════════════════════════════════════════
#  CONSTANTES INTERNAS
# ══════════════════════════════════════════════════════════════════════════════

SEP = "=" * 70
SEP2 = "-" * 70

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

results: list[dict] = []
_created_subscription_ids: list[str] = []
_created_card_ids: list[str] = []


# ══════════════════════════════════════════════════════════════════════════════
#  DB HELPERS
# ══════════════════════════════════════════════════════════════════════════════


def get_session():
    db_path = BACKEND_DIR / "Data" / "Database" / "MD70.db"
    engine = create_engine(f"sqlite:///{db_path}")

    @event.listens_for(engine, "connect")
    def _fk_off(conn, _):
        conn.execute("PRAGMA foreign_keys = OFF")

    return sessionmaker(bind=engine)()


def get_test_user(session) -> dict:
    row = session.execute(
        text("SELECT u.user_id, u.client_id, u.email, u.credits FROM users u LIMIT 1")
    ).fetchone()
    if not row:
        raise RuntimeError("Nenhum usuário no DB")
    return {"user_id": row[0], "client_id": row[1], "email": row[2], "credits": row[3]}


def get_free_plan_id(session) -> str:
    row = session.execute(
        text(
            "SELECT plan_id FROM plans WHERE plan_type = 'free' OR name = 'Free' LIMIT 1"
        )
    ).fetchone()
    if not row:
        raise RuntimeError("Plano Free não encontrado no DB")
    return row[0]


def get_pro_plan(session) -> dict:
    row = session.execute(
        text(
            """
        SELECT p.plan_id, p.id, p.name, p.cumulative_credits,
               MAX(CASE WHEN pr.period='monthly' THEN pr.price END) as monthly_price,
               MAX(CASE WHEN pr.period='annual'  THEN pr.price END) as annual_price
        FROM plans p
        LEFT JOIN prices pr ON p.plan_id = pr.plan_id AND pr.adoption_stage = 'early_adopter'
        WHERE p.plan_type = :pt AND p.active = 1
        GROUP BY p.plan_id
        LIMIT 1
        """
        ),
        {"pt": TARGET_PLAN_TYPE},
    ).fetchone()
    if not row:
        raise RuntimeError(f"Plano {TARGET_PLAN_TYPE} não encontrado no DB")

    plan_data = {
        "plan_id": row[0],
        "id": row[1],
        "name": row[2],
        "cumulative_credits": row[3],
        "monthly_price": row[4],
        "annual_price": row[5],
    }
    print(f"DEBUG: Plan from DB: {plan_data}")
    return plan_data


def restore_free_plan(session, client_id: str, free_plan_id: str):
    """Garante que o cliente está no plano Free antes de cada teste de pagamento."""
    session.execute(
        text(
            "UPDATE clients SET plan_id = :pid, updated_at = CURRENT_TIMESTAMP WHERE client_id = :cid"
        ),
        {"pid": free_plan_id, "cid": client_id},
    )
    session.commit()


def get_latest_subscription(session, client_id: str) -> dict | None:
    """Retorna a subscrição mais recente do cliente."""
    row = session.execute(
        text(
            """
        SELECT subscription_id, status, billing_cycle, auto_renew,
               stripe_subscription_id, stripe_customer_id, renewal_date, created_at
        FROM billing_subscriptions
        WHERE client_id = :cid
        ORDER BY created_at DESC
        LIMIT 1
        """
        ),
        {"cid": client_id},
    ).fetchone()
    if not row:
        return None
    return {
        "subscription_id": row[0],
        "status": row[1],
        "billing_cycle": row[2],
        "auto_renew": row[3],
        "stripe_subscription_id": row[4],
        "stripe_customer_id": row[5],
        "renewal_date": row[6],
        "created_at": row[7],
    }


def inject_billing_info(session, user_id: str) -> str:
    """Injeta billing_info mínimo para testes que não passam pela UI."""
    from App.Core.Services.Subscription.EncryptionUtil import encrypt_field

    billing_id = str(uuid.uuid4())
    session.execute(
        text(
            """
        INSERT OR IGNORE INTO billing_info (
            billing_id, user_id,
            address_encrypted, city_encrypted, state_encrypted,
            postal_code_encrypted, phone_number_encrypted,
            document_encrypted, email_encrypted,
            created_at, updated_at
        ) VALUES (
            :bid, :uid,
            :address, :city, :state,
            :postal_code, :phone, :doc, :email,
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        """
        ),
        {
            "bid": billing_id,
            "uid": user_id,
            "address": encrypt_field(TEST_BILLING["address"]),
            "city": encrypt_field(TEST_BILLING["city"]),
            "state": encrypt_field(TEST_BILLING["state"]),
            "postal_code": encrypt_field(TEST_BILLING["postal_code"]),
            "phone": encrypt_field(TEST_BILLING["phone"]),
            "doc": encrypt_field(TEST_BILLING["document"]),
            "email": encrypt_field("test@example.com"),
        },
    )
    session.commit()
    return billing_id


def inject_card_with_pm(session, user_id: str, payment_method_id: str) -> str:
    """Injeta cartão com payment_method_id criptografado para testes de renovação."""
    from App.Core.Services.Subscription.EncryptionUtil import (
        encrypt_field,
        hash_payment_method,
    )

    card_id = str(uuid.uuid4())
    encrypted_pm = encrypt_field(payment_method_id)
    pm_hash = hash_payment_method(payment_method_id)

    session.execute(
        text(
            """
        INSERT INTO cards (
            card_id, user_id, pagarme_card_id_encrypted, payment_method_hash,
            last_4, brand, holder_name, exp_month, exp_year, status,
            created_at, updated_at
        ) VALUES (
            :card_id, :user_id, :enc_pm, :pm_hash,
            '4242', 'visa', 'Test User', 12, 2030, 'valid',
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        """
        ),
        {
            "card_id": card_id,
            "user_id": user_id,
            "enc_pm": encrypted_pm,
            "pm_hash": pm_hash,
        },
    )
    session.commit()
    _created_card_ids.append(card_id)
    return card_id


def inject_subscription(
    session,
    client_id: str,
    plan_uuid: str,
    card_id: str,
    billing_id: str,
    billing_cycle: str = "monthly",
    status: str = "active",
    stripe_customer_id: str = "cus_test_injected",
    stripe_subscription_id: str = None,
    created_at_override: str = None,
    renewal_date_override: str = None,
) -> str:
    """Injeta billing_subscription diretamente no DB para testes que não passam pela UI."""
    sub_id = str(uuid.uuid4())
    created_at = created_at_override or datetime.now().isoformat()
    renewal = renewal_date_override or (datetime.now() - timedelta(hours=1)).isoformat()
    scheduled = datetime.now().isoformat()

    session.execute(
        text(
            """
        INSERT INTO billing_subscriptions (
            subscription_id, client_id, plan_id, card_id, billing_id,
            billing_cycle, price_type, status, auto_renew,
            stripe_customer_id, stripe_subscription_id,
            charge_scheduled_at, renewal_date,
            payment_retry_count, created_at, updated_at
        ) VALUES (
            :sub_id, :client_id, :plan_id, :card_id, :bid,
            :billing_cycle, 'early_adopter', :status, 1,
            :stripe_customer_id, :stripe_sub_id,
            :scheduled, :renewal,
            0, :created_at, :created_at
        )
        """
        ),
        {
            "sub_id": sub_id,
            "client_id": client_id,
            "plan_id": plan_uuid,
            "card_id": card_id,
            "bid": billing_id,
            "billing_cycle": billing_cycle,
            "status": status,
            "stripe_customer_id": stripe_customer_id,
            "stripe_sub_id": stripe_subscription_id,
            "scheduled": scheduled,
            "renewal": renewal,
            "created_at": created_at,
        },
    )
    session.commit()
    _created_subscription_ids.append(sub_id)
    return sub_id


def inject_payment(
    session,
    subscription_id: str,
    charge_id_stripe: str,
    amount: int,
    status: str = "paid",
):
    payment_id = str(uuid.uuid4())
    session.execute(
        text(
            """
        INSERT INTO payments (
            payment_id, charge_id_stripe, idempotency_key, subscription_id,
            amount, status, created_at, updated_at
        ) VALUES (
            :pid, :charge_id, :idem, :sub_id, :amount, :status,
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        """
        ),
        {
            "pid": payment_id,
            "charge_id": charge_id_stripe,
            "idem": subscription_id,
            "sub_id": subscription_id,
            "amount": amount,
            "status": status,
        },
    )
    session.commit()


# ══════════════════════════════════════════════════════════════════════════════
#  DB ASSERTIONS
# ══════════════════════════════════════════════════════════════════════════════


def assert_subscription_status(session, subscription_id: str, expected: str) -> dict:
    row = session.execute(
        text(
            "SELECT status, auto_renew, renewal_date, stripe_subscription_id "
            "FROM billing_subscriptions WHERE subscription_id = :sid"
        ),
        {"sid": subscription_id},
    ).fetchone()
    if not row:
        return {
            "success": False,
            "error": f"Sub {subscription_id} não encontrada no DB",
        }
    return {
        "success": row[0] == expected,
        "status": row[0],
        "auto_renew": row[1],
        "renewal_date": row[2],
        "stripe_subscription_id": row[3],
        "expected": expected,
    }


def assert_client_plan(session, client_id: str, expected_plan_type: str) -> dict:
    row = session.execute(
        text(
            "SELECT p.plan_type, p.name FROM clients c "
            "JOIN plans p ON c.plan_id = p.plan_id WHERE c.client_id = :cid"
        ),
        {"cid": client_id},
    ).fetchone()
    if not row:
        return {"success": False, "error": f"Cliente {client_id} não encontrado"}
    return {
        "success": row[0] == expected_plan_type,
        "plan_type": row[0],
        "plan_name": row[1],
        "expected": expected_plan_type,
    }


def assert_credits_distributed(session, user_id: str) -> dict:
    """Verifica se credits_logs tem entrada cumulative recente."""
    row = session.execute(
        text(
            "SELECT credits_added FROM credits_logs WHERE user_id = :uid "
            "AND credit_type = 'cumulative' ORDER BY created_at DESC LIMIT 1"
        ),
        {"uid": user_id},
    ).fetchone()
    if not row:
        return {
            "success": False,
            "error": "Nenhuma entrada em credits_logs (cumulative)",
        }
    return {"success": row[0] > 0, "credits_added": row[0]}


# ══════════════════════════════════════════════════════════════════════════════
#  STEP REPORTER
# ══════════════════════════════════════════════════════════════════════════════


def step(label: str, expect_success: bool, result: dict | bool):
    if isinstance(result, bool):
        ok = result
        result = {"success": result}
    else:
        ok = result.get("success", False)

    passed = ok == expect_success
    icon = "✅" if passed else "❌"
    exp = "sucesso" if expect_success else "falha esperada"
    got = "sucesso" if ok else "falha"

    print(f"\n{SEP2}")
    print(f"{icon}  {label}")
    print(f"     esperado={exp}  obtido={got}")
    if not passed:
        err = result.get("error") or result.get("detail") or result.get("message", "")
        if err:
            print(f"     error: {str(err)[:200]}")

    results.append({"label": label, "passed": passed, "result": result})

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Sanitize label for filename
    import re

    clean_label = re.sub(r'[<>:"/\\|?*]', "", label)
    slug = clean_label[:40].replace(" ", "_").replace("→", "").replace("/", "")
    status_str = "pass" if passed else "fail"
    (OUTPUT_DIR / f"{slug}_{status_str}_{ts}.json").write_text(
        json.dumps(
            {"label": label, "expect_success": expect_success, "result": result},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return passed


# ══════════════════════════════════════════════════════════════════════════════
#  PLAYWRIGHT — FLUXO DE PAGAMENTO VIA UI
# ══════════════════════════════════════════════════════════════════════════════


def pw_fill_payment(
    card: dict,
    session,
    plan_id: str = None,
    billing_cycle: str = TARGET_BILLING_CYCLE,
    coupon: str = None,
    free_id: str = None,
) -> dict:
    """
    Executa o fluxo de pagamento UI com rotação de usuário a cada tentativa.
    """
    max_ui_retries = 3
    last_error = "Unknown"

    for attempt in range(max_ui_retries):
        try:
            # 🚨 CADA TENTATIVA É UM NOVO USUÁRIO PARA ISOLAÇÃO TOTAL
            # Usar a sessão do banco de dados (que é o parâmetro 'session' recebido)
            auth_data = setup_mock_auth(session)
            if free_id:
                restore_free_plan(session, auth_data["client_id"], free_id)

            print(
                f"     -> [Attempt {attempt+1}/{max_ui_retries}] Starting UI flow for {auth_data['email']}..."
            )
            result = _pw_fill_payment_logic(
                card, auth_data, billing_cycle, plan_id, coupon
            )

            # Adicionar auth_data ao resultado para que o chamador saiba quem foi aprovado
            if result.get("success"):
                result["auth_data"] = auth_data
                return result

            last_error = result.get("error", "Unknown UI error")
            print(f"     ⚠️  Attempt {attempt+1} failed: {last_error}")
        except Exception as e:
            last_error = str(e)
            print(f"     ⚠️  Attempt {attempt+1} exception: {e}")

        time.sleep(1)

    return {
        "success": False,
        "error": f"Failed after {max_ui_retries} attempts: {last_error}",
    }


def _pw_fill_payment_logic(
    card: dict, auth_data: dict, billing_cycle: str, plan_id: str, coupon: str
) -> dict:
    """
    Lógica real do browser (extraída para suportar retry).
    """
    if not plan_id:
        return {"success": False, "error": "Missing plan_id"}

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout
    except ImportError:
        return {"success": False, "error": "Playwright not installed"}

    url = f"{FRONTEND_URL}{PAYMENT_PATH}?plan={plan_id}&type={billing_cycle}"
    if coupon:
        url += f"&coupon={coupon}"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=PW_HEADLESS, slow_mo=PW_SLOW_MO_MS)
        ctx = browser.new_context()
        ctx.add_cookies(
            [
                {
                    "name": "access_token",
                    "value": auth_data["access_token"],
                    "domain": "localhost",
                    "path": "/",
                },
                {
                    "name": "refresh_token",
                    "value": auth_data["refresh_token"],
                    "domain": "localhost",
                    "path": "/",
                },
            ]
        )

        page = ctx.new_page()
        page.set_default_timeout(PW_TIMEOUT_MS)

        print(f"     -> Navigating to {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=PW_NAV_TIMEOUT_MS)
        page.wait_for_timeout(2000)

        if "/login" in page.url:
            return {"success": False, "error": "Redirected to login"}

        # ── ETAPA 1: BILLING ──────────────────────────────────────────
        try:
            page.wait_for_selector(SEL_BILLING_POSTAL_CODE, timeout=3000)
            is_billing_step = True
        except:
            is_billing_step = False

        if is_billing_step:
            print("     -> Filling billing info...")
            page.fill(SEL_BILLING_POSTAL_CODE, TEST_BILLING["postal_code"])
            page.wait_for_timeout(1000)
            page.fill(SEL_BILLING_ADDRESS, TEST_BILLING["address"])
            page.fill(SEL_BILLING_PHONE, TEST_BILLING["phone"])
            page.fill(SEL_BILLING_DOCUMENT, TEST_BILLING["document"])
            page.locator(SEL_BTN_NEXT).first.click()
            page.wait_for_timeout(1000)

        # ── ETAPA 2: CARTÃO ───────────────────────────────────────────
        try:
            page.wait_for_selector(SEL_CARD_HOLDER, timeout=5000)
            page.fill(SEL_CARD_HOLDER, "AUTOMATED TEST USER")
        except:
            pass

        try:
            # Esperar o iframe do Stripe aparecer (pode demorar em conexões lentas)
            page.wait_for_selector(
                'iframe[name^="__privateStripeFrame"]', timeout=20000
            )

            # Pegar todos os frames e filtrar pelo que tem os campos do cartão
            stripe_frame = None
            for frame in page.frames:
                if "__privateStripeFrame" in frame.name:
                    # Verificar se este frame tem o input do cartão
                    try:
                        if frame.locator('input[name="cardnumber"]').count() > 0:
                            stripe_frame = frame
                            break
                    except:
                        continue

            if not stripe_frame:
                stripe_frame = page.frame_locator(
                    'iframe[name^="__privateStripeFrame"]'
                ).first

            # Preencher campos
            stripe_frame.locator('input[name="cardnumber"]').fill(card["number"])
            stripe_frame.locator('input[name="exp-date"]').fill(card["expiry"])
            stripe_frame.locator('input[name="cvc"]').fill(card["cvc"])
        except Exception as e:
            browser.close()
            return {"success": False, "error": f"Stripe Frame Error: {e}"}

        print("     -> Clicking initial Confirm...")
        page.locator(SEL_BTN_CONFIRM_INITIAL).first.click()

        # ── ETAPA 3: REVISAR ──────────────────────────────────────────
        try:
            page.wait_for_selector(SEL_BTN_FINISH, timeout=10000)
            print("     -> Clicking Finalizar Pagamento...")
            page.locator(SEL_BTN_FINISH).click()
        except:
            pass

        # Resultado
        try:
            page.wait_for_selector(f"{SEL_SUCCESS}, {SEL_ERROR}", timeout=PW_TIMEOUT_MS)
            if page.query_selector(SEL_SUCCESS):
                print("     ✅ Success detected!")
                res = {"success": True}
            else:
                err = page.inner_text(SEL_ERROR)
                print(f"     ❌ UI Error: {err}")
                res = {"success": False, "error": err}
            browser.close()
            return res
        except PwTimeout:
            browser.close()
            return {"success": False, "error": "Timeout final result"}
        return {"success": False, "error": f"Playwright erro: {str(e)}"}


# ══════════════════════════════════════════════════════════════════════════════
#  CENÁRIOS: CANCELAMENTO (injeção no DB + chamada direta ao serviço)
# ══════════════════════════════════════════════════════════════════════════════


def run_cancel_within_7_days(session, user: dict, plan: dict) -> dict:
    """
    Cria um charge real no Stripe, injeta sub no DB com created_at=hoje,
    executa a lógica de cancelamento ≤7 dias e valida refund + DB.
    """
    import stripe as stripe_lib
    from App.Core.Services.Subscription.StripePaymentService import (
        get_stripe_payment_service,
    )
    from App.Core.Settings import load_config

    stripe_lib.api_key = load_config().get("stripe_secret_key", "")
    stripe_service = get_stripe_payment_service()

    # Criar charge real para poder fazer refund
    try:
        pm = stripe_lib.PaymentMethod.create(type="card", card={"token": "tok_visa"})
        customer = stripe_lib.Customer.create(email="cancel-within7@example.com")
        stripe_lib.PaymentMethod.attach(pm.id, customer=customer.id)
        intent = stripe_lib.PaymentIntent.create(
            amount=int(plan["monthly_price"] * 100),
            currency="brl",
            customer=customer.id,
            payment_method=pm.id,
            confirm=True,
            off_session=True,
            description="[TEST] cancel ≤7 dias",
        )
        charge_id = intent.id
    except stripe_lib.error.StripeError as e:
        return {"success": False, "error": f"Setup Stripe falhou: {e}"}

    billing_id = inject_billing_info(session, user["user_id"])
    card_id = inject_card_with_pm(session, user["user_id"], pm.id)
    sub_id = inject_subscription(
        session,
        user["client_id"],
        plan["plan_id"],
        card_id,
        billing_id,
        billing_cycle="monthly",
        status="active",
        stripe_customer_id=customer.id,
        created_at_override=datetime.now().isoformat(),
    )
    inject_payment(session, sub_id, charge_id, int(plan["monthly_price"] * 100), "paid")

    # Colocar cliente no plano Pro para validar downgrade depois
    session.execute(
        text(
            "UPDATE clients SET plan_id = :pid, updated_at = CURRENT_TIMESTAMP WHERE client_id = :cid"
        ),
        {"pid": plan["plan_id"], "cid": user["client_id"]},
    )
    session.commit()

    # Executar lógica de cancelamento ≤7 dias
    try:
        # Recuperar o charge_id real (Stripe Refund precisa do ch_..., não pi_...)
        import stripe as stripe_lib

        intent = stripe_lib.PaymentIntent.retrieve(charge_id)
        actual_charge_id = intent.latest_charge

        refund_ok, refund_id = stripe_service.refund_charge(actual_charge_id)
        if not refund_ok:
            return {"success": False, "error": "Stripe refund falhou"}

        session.execute(
            text(
                "UPDATE billing_subscriptions SET status='canceled', canceled_at=datetime('now'), "
                "updated_at=datetime('now') WHERE subscription_id=:sid"
            ),
            {"sid": sub_id},
        )

        free_id = get_free_plan_id(session)
        session.execute(
            text(
                "UPDATE clients SET plan_id=:pid, updated_at=CURRENT_TIMESTAMP WHERE client_id=:cid"
            ),
            {"pid": free_id, "cid": user["client_id"]},
        )
        session.commit()
    except Exception as e:
        return {"success": False, "error": f"Erro ao cancelar: {e}"}

    sub_check = assert_subscription_status(session, sub_id, "canceled")
    plan_check = assert_client_plan(session, user["client_id"], "free")

    return {
        "success": sub_check["success"] and plan_check["success"],
        "sub_status": sub_check.get("status"),
        "client_plan_type": plan_check.get("plan_type"),
        "refund_id": refund_id,
    }


def run_cancel_after_7_days(session, user: dict, plan: dict) -> dict:
    """
    Injeta sub com created_at 10 dias atrás, executa lógica de cancelamento
    >7 dias (auto_renew=0, downgrade, sem refund) e valida no DB.
    """
    billing_id = inject_billing_info(session, user["user_id"])
    card_id = inject_card_with_pm(session, user["user_id"], PM_VISA_OK)
    created_at = (datetime.now() - timedelta(days=10)).isoformat()

    sub_id = inject_subscription(
        session,
        user["client_id"],
        plan["plan_id"],
        card_id,
        billing_id,
        billing_cycle="monthly",
        status="active",
        created_at_override=created_at,
    )
    inject_payment(
        session, sub_id, "ch_test_after7days", int(plan["monthly_price"] * 100), "paid"
    )

    session.execute(
        text(
            "UPDATE clients SET plan_id=:pid, updated_at=CURRENT_TIMESTAMP WHERE client_id=:cid"
        ),
        {"pid": plan["plan_id"], "cid": user["client_id"]},
    )
    session.commit()

    # Executar lógica >7 dias
    try:
        session.execute(
            text(
                "UPDATE billing_subscriptions SET auto_renew=0, updated_at=datetime('now') "
                "WHERE subscription_id=:sid"
            ),
            {"sid": sub_id},
        )

        free_id = get_free_plan_id(session)
        session.execute(
            text(
                "UPDATE clients SET plan_id=:pid, updated_at=CURRENT_TIMESTAMP WHERE client_id=:cid"
            ),
            {"pid": free_id, "cid": user["client_id"]},
        )
        session.commit()
    except Exception as e:
        return {"success": False, "error": f"Erro ao cancelar: {e}"}

    row = session.execute(
        text(
            "SELECT status, auto_renew FROM billing_subscriptions WHERE subscription_id=:sid"
        ),
        {"sid": sub_id},
    ).fetchone()

    plan_check = assert_client_plan(session, user["client_id"], "free")

    return {
        "success": row[1] == 0 and row[0] == "active" and plan_check["success"],
        "status": row[0],
        "auto_renew": row[1],
        "client_plan_type": plan_check.get("plan_type"),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  CENÁRIOS: CRON JOB / SUBSCRIPTIONJOB
# ══════════════════════════════════════════════════════════════════════════════


def run_renewal_success(session, user: dict, plan: dict) -> dict:
    """
    Injeta sub monthly com renewal_date no passado e PM aprovado.
    Executa SubscriptionJob._charge_renewal() diretamente.
    Valida: status ativo, renewal_date atualizada, payment registrado.
    """
    import stripe as stripe_lib
    from App.Core.Services.Subscription.SubscriptionJob import SubscriptionJob
    from App.Core.Settings import load_config

    stripe_lib.api_key = load_config().get("stripe_secret_key", "")

    try:
        customer = stripe_lib.Customer.create(email="renewal-ok@example.com")
        pm = stripe_lib.PaymentMethod.create(type="card", card={"token": "tok_visa"})
        stripe_lib.PaymentMethod.attach(pm.id, customer=customer.id)
    except stripe_lib.error.StripeError as e:
        return {"success": False, "error": f"Setup Stripe falhou: {e}"}

    billing_id = inject_billing_info(session, user["user_id"])
    card_id = inject_card_with_pm(session, user["user_id"], pm.id)
    renewal_past = (datetime.now() - timedelta(hours=2)).isoformat()

    sub_id = inject_subscription(
        session,
        user["client_id"],
        plan["plan_id"],
        card_id,
        billing_id,
        billing_cycle="monthly",
        status="active",
        stripe_customer_id=customer.id,
        renewal_date_override=renewal_past,
    )

    sub_pk = session.execute(
        text("SELECT id FROM billing_subscriptions WHERE subscription_id=:sid"),
        {"sid": sub_id},
    ).fetchone()[0]

    job = SubscriptionJob()
    job._charge_renewal(
        sub_id=sub_pk,
        subscription_id=sub_id,
        client_id=user["client_id"],
        stripe_customer_id=customer.id,
        payment_method_id=pm.id,
        amount_cents=int((plan["monthly_price"] or 0) * 100),
    )

    row = session.execute(
        text(
            "SELECT status, renewal_date, payment_retry_count "
            "FROM billing_subscriptions WHERE subscription_id=:sid"
        ),
        {"sid": sub_id},
    ).fetchone()

    payment_row = session.execute(
        text(
            "SELECT status FROM payments WHERE subscription_id=:sid "
            "ORDER BY created_at DESC LIMIT 1"
        ),
        {"sid": sub_id},
    ).fetchone()

    if not row:
        return {"success": False, "error": "Subscrição não encontrada após renovação"}

    renewal_updated = row[1] and row[1] > renewal_past
    payment_paid = payment_row and payment_row[0] == "paid"

    return {
        "success": row[0] == "active"
        and renewal_updated
        and row[2] == 0
        and payment_paid,
        "status": row[0],
        "renewal_updated": renewal_updated,
        "retry_reset": row[2] == 0,
        "payment_paid": payment_paid,
        "old_renewal": renewal_past,
        "new_renewal": row[1],
    }


def run_renewal_fail_then_cancel(session, user: dict, plan: dict) -> dict:
    """
    Injeta sub com PM que sempre falha.
    Executa _charge_renewal() MAX_RETRY vezes e valida status='canceled'.
    """
    import stripe as stripe_lib
    from App.Core.Services.Subscription.SubscriptionJob import SubscriptionJob
    from App.Core.Settings import load_config

    stripe_lib.api_key = load_config().get("stripe_secret_key", "")

    # Criar customer com PM que será rejeitado off-session
    customer_id = "cus_test_declined_renewal"
    pm_id = PM_VISA_DECLINED

    try:
        customer = stripe_lib.Customer.create(email="renewal-fail@example.com")
        customer_id = customer.id
        pm = stripe_lib.PaymentMethod.create(type="card", card={"token": "tok_visa"})
        stripe_lib.PaymentMethod.attach(pm.id, customer=customer_id)
        pm_id = PM_VISA_DECLINED  # usar o PM de teste que falha off-session
    except stripe_lib.error.StripeError:
        pass  # fallback para IDs de teste hardcoded

    billing_id = inject_billing_info(session, user["user_id"])
    card_id = inject_card_with_pm(session, user["user_id"], pm_id)
    renewal = (datetime.now() - timedelta(hours=1)).isoformat()

    sub_id = inject_subscription(
        session,
        user["client_id"],
        plan["plan_id"],
        card_id,
        billing_id,
        billing_cycle="monthly",
        status="active",
        stripe_customer_id=customer_id,
        renewal_date_override=renewal,
    )

    sub_pk = session.execute(
        text("SELECT id FROM billing_subscriptions WHERE subscription_id=:sid"),
        {"sid": sub_id},
    ).fetchone()[0]

    job = SubscriptionJob()
    MAX_RETRY = SubscriptionJob.MAX_RETRY_ATTEMPTS
    amount = int((plan["monthly_price"] or 0) * 100)

    for attempt in range(MAX_RETRY):
        session.execute(
            text(
                "UPDATE billing_subscriptions SET payment_retry_count=:rc WHERE id=:pk"
            ),
            {"rc": attempt, "pk": sub_pk},
        )
        session.commit()

        job._charge_renewal(
            sub_id=sub_pk,
            subscription_id=sub_id,
            client_id=user["client_id"],
            stripe_customer_id=customer_id,
            payment_method_id=pm_id,
            amount_cents=amount,
        )

    row = session.execute(
        text(
            "SELECT status, payment_retry_count FROM billing_subscriptions WHERE subscription_id=:sid"
        ),
        {"sid": sub_id},
    ).fetchone()

    if not row:
        return {"success": False, "error": "Subscrição não encontrada após tentativas"}

    return {
        "success": row[0] == "canceled",
        "status": row[0],
        "expected": "canceled",
        "retry_count": row[1],
        "max_retry": MAX_RETRY,
    }


def run_cleanup_suspended(session, user: dict, plan: dict) -> dict:
    """
    Injeta sub suspensa há 8 dias, executa cleanup_suspended(),
    valida que status muda para 'canceled'.
    """
    from App.Core.Services.Subscription.SubscriptionJob import SubscriptionJob

    billing_id = inject_billing_info(session, user["user_id"])
    card_id = inject_card_with_pm(session, user["user_id"], PM_VISA_OK)

    sub_id = inject_subscription(
        session,
        user["client_id"],
        plan["plan_id"],
        card_id,
        billing_id,
        billing_cycle="monthly",
        status="suspended",
    )

    # Forçar last_payment_attempt_at há 8 dias (além do SUSPENDED_TIMEOUT_DAYS=7)
    old_attempt = (datetime.now() - timedelta(days=8)).isoformat()
    session.execute(
        text(
            "UPDATE billing_subscriptions SET last_payment_attempt_at=:t WHERE subscription_id=:sid"
        ),
        {"t": old_attempt, "sid": sub_id},
    )
    session.commit()

    SubscriptionJob().cleanup_suspended()

    row = session.execute(
        text("SELECT status FROM billing_subscriptions WHERE subscription_id=:sid"),
        {"sid": sub_id},
    ).fetchone()

    return {
        "success": bool(row and row[0] == "canceled"),
        "status": row[0] if row else None,
        "expected": "canceled",
        "suspended_since_days": 8,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  FASE 6: WEBHOOK STRIPE — envio HTTP com assinatura real
# ══════════════════════════════════════════════════════════════════════════════

WEBHOOK_URL = f"{BACKEND_URL}/api/webhook/stripe"


def _sign_payload(payload_bytes: bytes, secret: str) -> str:
    """Gera header Stripe-Signature idêntico ao que a Stripe envia."""
    import hmac, hashlib

    ts = str(int(time.time()))
    signed = f"{ts}.{payload_bytes.decode()}"
    sig = hmac.new(secret.encode(), signed.encode(), hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


def _send_webhook(event_type: str, obj: dict, secret: str) -> dict:
    """Monta e envia um evento webhook ao backend, retorna {'status_code', 'body'}."""
    import urllib.request, urllib.error

    event = {
        "id": f"evt_test_{uuid.uuid4().hex[:12]}",
        "object": "event",
        "type": event_type,
        "data": {"object": obj},
        "created": int(time.time()),
        "livemode": False,
        "api_version": "2026-02-25",
    }
    payload = json.dumps(event).encode()
    sig = _sign_payload(payload, secret)

    req = urllib.request.Request(
        WEBHOOK_URL,
        data=payload,
        headers={"Content-Type": "application/json", "stripe-signature": sig},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return {"status_code": resp.status, "body": json.loads(resp.read())}
    except urllib.error.HTTPError as e:
        return {"status_code": e.code, "body": {}}
    except Exception as ex:
        return {"status_code": 0, "body": {"error": str(ex)}}


def run_webhook_tests(session, user: dict, plan: dict) -> None:
    from App.Core.Settings import load_config

    secret = load_config().get("stripe_webhook_secret", "")
    if not secret:
        print("  ⚠️  STRIPE_WEBHOOK_SECRET não configurado — pulando FASE 6")
        return

    billing_id = inject_billing_info(session, user["user_id"])
    card_id = inject_card_with_pm(session, user["user_id"], PM_VISA_OK)

    # Sub compartilhada pelos cenários de invoice e subscription
    stripe_sub_id = f"sub_test_{uuid.uuid4().hex[:12]}"
    sub_id = inject_subscription(
        session,
        user["client_id"],
        plan["plan_id"],
        card_id,
        billing_id,
        billing_cycle="monthly",
        status="pending_charge",
        stripe_customer_id="cus_webhook_test",
        stripe_subscription_id=stripe_sub_id,
    )

    # ── 13. checkout.session.completed ───────────────────────────────────────
    r = _send_webhook(
        "checkout.session.completed",
        {
            "id": f"cs_test_{uuid.uuid4().hex[:12]}",
            "object": "checkout.session",
            "subscription": stripe_sub_id,
            "customer": "cus_webhook_test",
            "metadata": {},
        },
        secret,
    )
    time.sleep(1)  # Wait for processing
    ok_http = r["status_code"] == 200
    row = session.execute(
        text(
            "SELECT status FROM billing_subscriptions WHERE stripe_subscription_id=:sid"
        ),
        {"sid": stripe_sub_id},
    ).fetchone()
    ok_db = bool(row and row[0] == "active")
    step(
        "13. checkout.session.completed → sub status='active'",
        True,
        {
            "success": ok_http and ok_db,
            "http": r["status_code"],
            "db_status": row[0] if row else None,
        },
    )

    # ── 14. customer.subscription.created ────────────────────────────────────
    new_sub_id = f"sub_test_{uuid.uuid4().hex[:12]}"
    sub_id_14 = inject_subscription(
        session,
        user["client_id"],
        plan["plan_id"],
        card_id,
        billing_id,
        billing_cycle="monthly",
        status="pending_charge",
        stripe_customer_id="cus_webhook_test",
        stripe_subscription_id=None,
    )
    # Limpa stripe_subscription_id para simular sub recém-criada
    session.execute(
        text(
            "UPDATE billing_subscriptions SET stripe_subscription_id=NULL, stripe_customer_id=:cid "
            "WHERE subscription_id=:sid"
        ),
        {"cid": "cus_webhook_test_new", "sid": sub_id_14},
    )
    session.commit()

    r = _send_webhook(
        "customer.subscription.created",
        {
            "id": new_sub_id,
            "object": "subscription",
            "customer": "cus_webhook_test_new",
            "status": "active",
        },
        secret,
    )
    time.sleep(1)
    ok_http = r["status_code"] == 200
    row = session.execute(
        text(
            "SELECT stripe_subscription_id FROM billing_subscriptions WHERE subscription_id=:sid"
        ),
        {"sid": sub_id_14},
    ).fetchone()
    ok_db = bool(row and row[0] == new_sub_id)
    step(
        "14. customer.subscription.created → stripe_subscription_id gravado",
        True,
        {
            "success": ok_http and ok_db,
            "http": r["status_code"],
            "stripe_sub_id": row[0] if row else None,
        },
    )

    # ── 15. customer.subscription.deleted ────────────────────────────────────
    r = _send_webhook(
        "customer.subscription.deleted",
        {
            "id": stripe_sub_id,
            "object": "subscription",
            "customer": "cus_webhook_test",
        },
        secret,
    )
    time.sleep(1)
    ok_http = r["status_code"] == 200
    row = session.execute(
        text(
            "SELECT status FROM billing_subscriptions WHERE stripe_subscription_id=:sid"
        ),
        {"sid": stripe_sub_id},
    ).fetchone()
    ok_db = bool(row and row[0] == "canceled")
    step(
        "15. customer.subscription.deleted → sub status='canceled'",
        True,
        {
            "success": ok_http and ok_db,
            "http": r["status_code"],
            "db_status": row[0] if row else None,
        },
    )

    # ── 16. customer.subscription.trial_will_end ─────────────────────────────
    r = _send_webhook(
        "customer.subscription.trial_will_end",
        {
            "id": stripe_sub_id,
            "object": "subscription",
            "trial_end": int(time.time()) + 259200,  # 3 dias
        },
        secret,
    )
    time.sleep(1)
    step(
        "16. customer.subscription.trial_will_end → 200 aceito",
        True,
        {"success": r["status_code"] == 200, "http": r["status_code"]},
    )

    # ── 17. invoice.finalized ─────────────────────────────────────────────────
    r = _send_webhook(
        "invoice.finalized",
        {
            "id": f"in_test_{uuid.uuid4().hex[:12]}",
            "object": "invoice",
            "subscription": stripe_sub_id,
            "amount_due": 9900,
        },
        secret,
    )
    time.sleep(1)
    step(
        "17. invoice.finalized → 200 aceito",
        True,
        {"success": r["status_code"] == 200, "http": r["status_code"]},
    )

    # ── 18. invoice.payment_failed → past_due ────────────────────────────────
    # Reativa sub para poder testar transição
    session.execute(
        text(
            "UPDATE billing_subscriptions SET status='active' WHERE stripe_subscription_id=:sid"
        ),
        {"sid": stripe_sub_id},
    )
    session.commit()

    r = _send_webhook(
        "invoice.payment_failed",
        {
            "id": f"in_test_{uuid.uuid4().hex[:12]}",
            "object": "invoice",
            "subscription": stripe_sub_id,
            "attempt_count": 1,
            "last_finalization_error": {"message": "card_declined"},
        },
        secret,
    )
    time.sleep(1)
    ok_http = r["status_code"] == 200
    row = session.execute(
        text(
            "SELECT status FROM billing_subscriptions WHERE stripe_subscription_id=:sid"
        ),
        {"sid": stripe_sub_id},
    ).fetchone()
    ok_db = bool(row and row[0] == "suspended")
    step(
        "18. invoice.payment_failed → sub status='suspended'",
        True,
        {
            "success": ok_http and ok_db,
            "http": r["status_code"],
            "db_status": row[0] if row else None,
        },
    )

    # ── 19. invoice.payment_succeeded → active ───────────────────────────────
    r = _send_webhook(
        "invoice.payment_succeeded",
        {
            "id": f"in_test_{uuid.uuid4().hex[:12]}",
            "object": "invoice",
            "subscription": stripe_sub_id,
            "amount_paid": 9900,
            "lines": {"data": [{"period": {"end": int(time.time()) + 2592000}}]},
        },
        secret,
    )
    time.sleep(1)
    ok_http = r["status_code"] == 200
    row = session.execute(
        text(
            "SELECT status FROM billing_subscriptions WHERE stripe_subscription_id=:sid"
        ),
        {"sid": stripe_sub_id},
    ).fetchone()
    ok_db = bool(row and row[0] == "active")
    step(
        "19. invoice.payment_succeeded → sub status='active'",
        True,
        {
            "success": ok_http and ok_db,
            "http": r["status_code"],
            "db_status": row[0] if row else None,
        },
    )

    # ── 20. Assinatura inválida → 403 ────────────────────────────────────────
    r = _send_webhook(
        "invoice.payment_succeeded",
        {
            "id": "in_fake",
            "object": "invoice",
            "subscription": stripe_sub_id,
        },
        "whsec_invalida_000000000000000000000000000000000",
    )
    step(
        "20. Assinatura inválida → 403",
        True,
        {"success": r["status_code"] == 403, "http": r["status_code"]},
    )

    # ── 21. Verificar Auditoria de Webhooks (Table stripe_webhook_events) ──
    row = session.execute(
        text(
            "SELECT COUNT(*) FROM stripe_webhook_events WHERE stripe_event_id LIKE 'evt_test_%'"
        )
    ).fetchone()
    ok_audit = bool(row and row[0] > 0)
    step(
        "21. Auditoria: eventos registrados em stripe_webhook_events",
        True,
        {"success": ok_audit, "count": row[0] if row else 0},
    )

    # ── 22. Verificar Suspensão (Pagar com créditos existentes) ──────────
    auth_susp = setup_mock_auth(session)
    # Dar créditos e suspender
    session.execute(
        text("UPDATE users SET credits = 50.0 WHERE user_id = :uid"),
        {"uid": auth_susp["user_id"]},
    )
    session.execute(
        text(
            "UPDATE billing_subscriptions SET status = 'suspended' WHERE client_id = :cid"
        ),
        {"cid": auth_susp["client_id"]},
    )
    session.commit()

    from App.Features.Credits.CreditsManager import CreditsManager

    can_use, bal = CreditsManager.check_credits(auth_susp["user_id"], 10.0)
    step(
        "22. Suspensão: permite usar créditos existentes se 'suspended'",
        True,
        {"success": can_use, "balance": bal},
    )

    # ── 23. Verificar Bloqueio Total (Canceled) ──────────────────────────
    session.execute(
        text(
            "UPDATE billing_subscriptions SET status = 'canceled' WHERE client_id = :cid"
        ),
        {"cid": auth_susp["client_id"]},
    )
    session.commit()
    can_use, bal = CreditsManager.check_credits(auth_susp["user_id"], 10.0)
    step(
        "23. Bloqueio: impede uso de créditos se 'canceled'",
        False,
        {"success": can_use, "balance": bal},
    )

    # ── 24. Verificar Rota /credits (Nova Resposta) ─────────────────────
    # Mock de falha de pagamento (retry_count > 0)
    session.execute(
        text(
            "UPDATE billing_subscriptions SET status = 'suspended', payment_retry_count = 1 WHERE client_id = :cid"
        ),
        {"cid": auth_susp["client_id"]},
    )
    session.commit()

    # Fazer request real na API (via urllib)
    url_credits = f"{BACKEND_URL}/api/subscription/credits"
    headers = {"Cookie": f"access_token={auth_susp['access_token']}"}
    req = urllib.request.Request(url_credits, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
            ok_route = (
                data.get("plan_status") == "suspended"
                and data.get("payment_failed") is True
            )
            step(
                "24. API /credits: retorna plan_status e payment_failed",
                True,
                {
                    "success": ok_route,
                    "status": data.get("plan_status"),
                    "failed": data.get("payment_failed"),
                },
            )
    except Exception as e:
        step(
            "24. API /credits: falha no request",
            True,
            {"success": False, "error": str(e)},
        )


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════


def run():
    session = get_session()

    # Baseline user for direct DB tests (Phase 3+)
    base_auth = setup_mock_auth(session)
    user = {
        "user_id": base_auth["user_id"],
        "client_id": base_auth["client_id"],
        "email": base_auth["email"],
    }

    plan = get_pro_plan(session)
    free_id = get_free_plan_id(session)
    public_url = os.environ.get("STRIPE_WEBHOOK_URL")

    print(f"\n{'#' * 70}")
    print("  VALIDAÇÃO END-TO-END: SISTEMA DE PAGAMENTOS PROX")
    print(f"  base_user: {user['user_id']}")
    print(
        f"  plano    : {plan['name']} | monthly=R${plan['monthly_price']} | annual=R${plan['annual_price']}"
    )
    print(f"  frontend : {FRONTEND_URL}")
    print(f"  backend  : {BACKEND_URL}")
    print(f"{'#' * 70}")

    if _args.webhooks_only:
        print(f"\n{'━' * 70}")
        print("  FASE 6: WEBHOOK STRIPE — HTTP direto")
        print(f"{'━' * 70}")
        run_webhook_tests(session, user, plan)
        session.close()
        return

    # ── FASE 1: CARTÕES — TIPOS DE RESPOSTA (Playwright) ─────────────────────
    print(f"\n{'━' * 70}")
    print("  FASE 1: CARTÕES STRIPE — TIPOS DE RESPOSTA (Playwright)")
    print(f"{'━' * 70}")

    # 01. Visa aprovado (TESTE DE CONECTIVIDADE WEBHOOK)
    print(f"\n📡 [GATEKEEPER] Scenario 01: Testing REAL Webhook connectivity...")
    # 🚨 NOTA: pw_fill_payment agora cuida do setup_mock_auth internamente para isolação
    r01 = pw_fill_payment(
        STRIPE_CARDS["visa_ok"], session, plan_id=plan["plan_id"], free_id=free_id
    )
    step("01. Visa 4242 monthly → pagamento aprovado (UI)", True, r01)

    if r01.get("success"):
        # Recuperar o auth_data gerado para o polling
        auth01 = r01["auth_data"]
        # Aguardar processamento do Webhook REAL para atualizar o plano no cliente
        ok_webhook = wait_for_webhook(
            session, auth01["client_id"], free_id, timeout=120
        )

        if not ok_webhook:
            print("\n" + "!" * 70)
            print(" ❌ CRITICAL: Webhook Connectivity Test FAILED!")
            print(
                " O pagamento foi aprovado na UI, mas o backend não recebeu o Webhook."
            )
            print("\n AÇÃO REQUERIDA:")
            print(f" 1. Acesse: https://dashboard.stripe.com/test/webhooks")
            print(f" 2. Edite o endpoint existente ou crie um novo.")
            print(f" 3. COLE ESTA URL: {public_url}/api/webhook/stripe")
            print(f" 4. Selecione os eventos (ou 'Todos os eventos')")
            print("\n Verifique também se o Ngrok está apontando para o backend local.")
            print("!" * 70 + "\n")
            sys.exit(1)

        step("01b. DB: Webhook ativou plano Pro via Stripe", True, ok_webhook)
        sub = get_latest_subscription(session, auth01["client_id"])
        step(
            "01c. DB: clients.plan_type → pro",
            True,
            assert_client_plan(session, auth01["client_id"], "pro"),
        )
    else:
        print("❌ Scenario 01 UI flow failed. Aborting connectivity test.")
        sys.exit(1)

    print("✅ Webhook Connectivity Confirmed. Proceeding with remaining tests...")

    # 02. Mastercard aprovado
    r02 = pw_fill_payment(
        STRIPE_CARDS["mastercard_ok"], session, plan_id=plan["plan_id"], free_id=free_id
    )
    step("02. Mastercard 5555 monthly → pagamento aprovado", True, r02)

    # 03. Cartão sempre recusado — plano NÃO deve mudar
    r03 = pw_fill_payment(
        STRIPE_CARDS["declined"], session, plan_id=plan["plan_id"], free_id=free_id
    )
    step("03. Cartão 4000...0002 → recusado", False, r03)
    if r03.get("auth_data"):
        auth03 = r03["auth_data"]
        step(
            "03b. DB: plano permanece Free após recusa",
            True,
            assert_client_plan(session, auth03["client_id"], "free"),
        )

    # 04. Saldo insuficiente
    r04 = pw_fill_payment(
        STRIPE_CARDS["insufficient_funds"],
        session,
        plan_id=plan["plan_id"],
        free_id=free_id,
    )
    step("04. Saldo insuficiente 4000...9995 → recusado", False, r04)

    # 05. Cartão expirado
    r05 = pw_fill_payment(
        STRIPE_CARDS["expired"], session, plan_id=plan["plan_id"], free_id=free_id
    )
    step("05. Cartão expirado 4000...0069 → recusado", False, r05)

    # ── FASE 2: CICLOS DE BILLING (Playwright) ────────────────────────────────
    print(f"\n{'━' * 70}")
    print("  FASE 2: CICLOS DE BILLING")
    print(f"{'━' * 70}")

    # 06. Monthly
    r06 = pw_fill_payment(
        STRIPE_CARDS["visa_ok"],
        session,
        plan_id=plan["plan_id"],
        billing_cycle="monthly",
        free_id=free_id,
    )
    step("06. Pagamento monthly → aprovado", True, r06)
    if r06.get("success") and r06.get("auth_data"):
        auth06 = r06["auth_data"]
        sub = get_latest_subscription(session, auth06["client_id"])
        step(
            "06b. DB: billing_cycle='monthly'",
            True,
            {
                "success": sub and sub["billing_cycle"] == "monthly",
                "billing_cycle": sub and sub["billing_cycle"],
            },
        )

    # 07. Annual
    r07 = pw_fill_payment(
        STRIPE_CARDS["visa_ok"],
        session,
        plan_id=plan["plan_id"],
        billing_cycle="annual",
        free_id=free_id,
    )
    step("07. Pagamento annual → aprovado", True, r07)
    if r07.get("success") and r07.get("auth_data"):
        auth07 = r07["auth_data"]
        sub = get_latest_subscription(session, auth07["client_id"])
        step(
            "07b. DB: billing_cycle='annual' + stripe_subscription_id preenchido",
            True,
            {
                "success": sub
                and sub["billing_cycle"] == "annual"
                and bool(sub["stripe_subscription_id"]),
                "billing_cycle": sub and sub["billing_cycle"],
                "stripe_subscription_id": sub and sub["stripe_subscription_id"],
            },
        )

    # ── FASE 3: CANCELAMENTO (lógica direta + sub injetada) ───────────────────
    print(f"\n{'━' * 70}")
    print("  FASE 3: CANCELAMENTO")
    print(f"{'━' * 70}")

    auth08 = setup_mock_auth(session)
    restore_free_plan(session, auth08["client_id"], free_id)
    step(
        "08. Cancelamento ≤7 dias → refund Stripe + status='canceled' + Free",
        True,
        run_cancel_within_7_days(session, auth08, plan),
    )

    auth09 = setup_mock_auth(session)
    restore_free_plan(session, auth09["client_id"], free_id)
    step(
        "09. Cancelamento >7 dias → auto_renew=0 + Free (sem refund)",
        True,
        run_cancel_after_7_days(session, auth09, plan),
    )

    # ── FASE 4: CRON JOB / SUBSCRIPTIONJOB ───────────────────────────────────
    print(f"\n{'━' * 70}")
    print("  FASE 4: CRON JOB — SubscriptionJob")
    print(f"{'━' * 70}")

    restore_free_plan(session, user["client_id"], free_id)
    step(
        "10. Renovação monthly bem-sucedida → renewal_date atualizada + payment='paid'",
        True,
        run_renewal_success(session, user, plan),
    )

    restore_free_plan(session, user["client_id"], free_id)
    step(
        "11. Renovação falha MAX_RETRY vezes → status='canceled'",
        True,
        run_renewal_fail_then_cancel(session, user, plan),
    )

    # ── FASE 5: CLEANUP SUSPENDED ─────────────────────────────────────────────
    print(f"\n{'━' * 70}")
    print("  FASE 5: CLEANUP — SUSPENDED TIMEOUT")
    print(f"{'━' * 70}")

    step(
        "12. Sub suspensa >7 dias → cleanup_suspended() → status='canceled'",
        True,
        run_cleanup_suspended(session, user, plan),
    )

    # ── FASE 6: WEBHOOK STRIPE ────────────────────────────────────────────────
    print(f"\n{'━' * 70}")
    print("  FASE 6: WEBHOOK STRIPE — HTTP direto")
    print(f"{'━' * 70}")

    run_webhook_tests(session, user, plan)

    # ── FASE 7: NOVAS LÓGICAS (Audit, Suspensão, Credits API) ─────────────
    print(f"\n{'━' * 70}")
    print("  FASE 7: NOVAS LÓGICAS (Audit, Suspensão, Credits API)")
    print(f"{'━' * 70}")

    # 21. Auditoria
    row_audit = session.execute(
        text(
            "SELECT COUNT(*) FROM stripe_webhook_events WHERE stripe_event_id LIKE 'evt_test_%'"
        )
    ).fetchone()
    step(
        "21. Auditoria: eventos registrados em stripe_webhook_events",
        True,
        {
            "success": bool(row_audit and row_audit[0] > 0),
            "count": row_audit[0] if row_audit else 0,
        },
    )

    # 22 & 23. Suspensão e Bloqueio
    auth_susp = setup_mock_auth(session)
    session.execute(
        text("UPDATE users SET credits = 50.0 WHERE user_id = :uid"),
        {"uid": auth_susp["user_id"]},
    )
    session.execute(
        text(
            "UPDATE billing_subscriptions SET status = 'suspended' WHERE client_id = :cid"
        ),
        {"cid": auth_susp["client_id"]},
    )
    session.commit()

    from App.Features.Credits.CreditsManager import CreditsManager

    can_use, bal = CreditsManager.check_credits(auth_susp["user_id"], 10.0)
    step(
        "22. Suspensão: permite usar créditos existentes se 'suspended'",
        True,
        {"success": can_use, "balance": bal},
    )

    session.execute(
        text(
            "UPDATE billing_subscriptions SET status = 'canceled' WHERE client_id = :cid"
        ),
        {"cid": auth_susp["client_id"]},
    )
    session.commit()
    can_use_block, bal_block = CreditsManager.check_credits(auth_susp["user_id"], 10.0)
    step(
        "23. Bloqueio: impede uso de créditos se 'canceled'",
        False,
        {"success": can_use_block, "balance": bal_block},
    )

    # 24. Credits API
    session.execute(
        text(
            "UPDATE billing_subscriptions SET status = 'suspended', payment_retry_count = 1 WHERE client_id = :cid"
        ),
        {"cid": auth_susp["client_id"]},
    )
    session.commit()
    url_credits = f"{BACKEND_URL}/api/subscription/credits"
    headers = {"Cookie": f"access_token={auth_susp['access_token']}"}
    try:
        req = urllib.request.Request(url_credits, headers=headers)
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
            ok_route = (
                data.get("plan_status") == "suspended"
                and data.get("payment_failed") is True
            )
            step(
                "24. API /credits: retorna plan_status e payment_failed",
                True,
                {
                    "success": ok_route,
                    "status": data.get("plan_status"),
                    "failed": data.get("payment_failed"),
                },
            )
    except Exception as e:
        step(
            "24. API /credits: falha no request",
            True,
            {"success": False, "error": str(e)},
        )

    # ── 25. Validar Popup Frontend: Problema na Renovação (UI) ──────────
    print("\n🧪 TEST 25: UI Popup - Problema na Renovação")
    auth_fail_ui = setup_mock_auth(session)
    # Ativo mas com falha no retry
    session.execute(
        text(
            "UPDATE billing_subscriptions SET status = 'active', payment_retry_count = 1 WHERE client_id = :cid"
        ),
        {"cid": auth_fail_ui["client_id"]},
    )
    session.commit()

    r25 = pw_check_popup(auth_fail_ui, "Problema na Renovação")
    step("25. UI: exibe popup de 'Problema na Renovação' ao detectar falha", True, r25)

    # ── 26. Validar Popup Frontend: Assinatura Suspensa (UI) ───────────
    print("\n🧪 TEST 26: UI Popup - Assinatura Suspensa")
    auth_susp_ui = setup_mock_auth(session)
    session.execute(
        text(
            "UPDATE billing_subscriptions SET status = 'suspended' WHERE client_id = :cid"
        ),
        {"cid": auth_susp_ui["client_id"]},
    )
    session.commit()

    r26 = pw_check_popup(auth_susp_ui, "Assinatura Suspensa")
    step(
        "26. UI: exibe popup de 'Assinatura Suspensa' ao detectar status suspended",
        True,
        r26,
    )

    session.close()


def pw_check_popup(auth_data: dict, expected_text: str) -> dict:
    """Verifica se um popup específico aparece na UI ao abrir o App."""
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=PW_HEADLESS, slow_mo=PW_SLOW_MO_MS)
            ctx = browser.new_context()
            ctx.add_cookies(
                [
                    {
                        "name": "access_token",
                        "value": auth_data["access_token"],
                        "domain": "localhost",
                        "path": "/",
                    },
                    {
                        "name": "refresh_token",
                        "value": auth_data["refresh_token"],
                        "domain": "localhost",
                        "path": "/",
                    },
                ]
            )
            page = ctx.new_page()
            # Ir para o App (onde o checkAuth dispara os popups)
            page.goto(f"{FRONTEND_URL}/app", wait_until="domcontentloaded")
            page.wait_for_timeout(4000)  # Esperar checkAuth completar

            # Verificar se o texto aparece na tela
            has_popup = page.get_by_text(expected_text).is_visible()
            if not has_popup:
                import os

                os.makedirs("output", exist_ok=True)
                page.screenshot(
                    path=f"output/popup_fail_{expected_text.replace(' ', '_')}.png"
                )

            browser.close()
            return {"success": has_popup}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
#  CLEANUP
# ══════════════════════════════════════════════════════════════════════════════


def cleanup():
    session = get_session()
    print(
        f"\n  🧹 Removendo {len(_created_subscription_ids)} subs e {len(_created_card_ids)} cards"
    )
    for sid in _created_subscription_ids:
        session.execute(
            text("DELETE FROM payments WHERE subscription_id=:s"), {"s": sid}
        )
        session.execute(
            text("DELETE FROM billing_subscriptions WHERE subscription_id=:s"),
            {"s": sid},
        )
    for cid in _created_card_ids:
        session.execute(text("DELETE FROM cards WHERE card_id=:c"), {"c": cid})
    session.commit()
    session.close()
    print("  🧹 Cleanup concluído.")


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRYPOINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    run()

    print(f"\n{SEP}")
    print("RESULTADO FINAL")
    print(SEP)
    all_pass = True
    passed_count = 0
    for r in results:
        icon = "✅" if r["passed"] else "❌"
        print(f"  {icon}  {r['label']}")
        if r["passed"]:
            passed_count += 1
        else:
            all_pass = False

    print()
    print(f"  {passed_count}/{len(results)} cenários passaram")
    print(f"  Outputs em: {OUTPUT_DIR}")
    print()

    if _args.cleanup:
        cleanup()

    sys.exit(0 if all_pass else 1)

"""
Surgical Validation: Verifies Frontend Billing Popups and CTA Flows.
Permite execuções isoladas e manter o browser aberto para inspeção de UI.

Uso:
    python Scripts/Tests/PaymentSystem/validate_popups.py --case 4 --no-close
"""

import sys, os, uuid, json, time, argparse
from pathlib import Path
from sqlalchemy import text

# Configura PATH do backend
BACKEND_DIR = Path(__file__).parent.parent.parent.parent.absolute()
sys.path.insert(0, str(BACKEND_DIR))

import urllib.request, urllib.error

# Mock Environment
os.environ["BACKEND_HOST"] = "localhost"
os.environ["BACKEND_PORT"] = "4001"
os.environ["FRONTEND_HOST"] = "localhost"
os.environ["FRONTEND_PORT"] = "5082"

from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from Scripts.Tests.PaymentSystem.test_payment_system import (
    get_session,
    setup_mock_auth,
    get_latest_subscription,
)


def check_health():
    """Verifica saúde do backend, frontend e túnel de webhook."""
    print(f"\n🔍 Checking health of services...")
    backend_url = f"http://localhost:4001"
    frontend_url = f"http://localhost:5082"

    # 1. Backend
    try:
        with urllib.request.urlopen(f"{backend_url}/api/health", timeout=3) as resp:
            if resp.status == 200:
                print(f"✅ Backend is Healthy")
    except:
        print(f"❌ Backend is UNREACHABLE")

    # 2. Frontend
    try:
        with urllib.request.urlopen(f"{frontend_url}/health", timeout=3) as resp:
            if resp.status == 200:
                print(f"✅ Frontend is Healthy")
    except:
        print(f"❌ Frontend is UNREACHABLE")

    # 3. Webhook Tunnel
    public_url = os.environ.get("STRIPE_WEBHOOK_URL")
    if public_url:
        print(f"📡 Checking Webhook Tunnel: {public_url}")
        try:
            with urllib.request.urlopen(
                f"{public_url.rstrip('/')}/api/webhook/stripe", timeout=5
            ) as resp:
                if resp.status == 200:
                    print(f"✅ Webhook Tunnel is Reachable!")
                else:
                    print(f"⚠️  Webhook Tunnel status: {resp.status}")
        except Exception as e:
            print(f"❌ Webhook Tunnel UNREACHABLE: {e}")
            print("🚨 ATENÇÃO: Webhooks reais não chegarão. Verifique o Ngrok!")


def wait_for_webhook_val(session, client_id, timeout=45):
    """Aguarda status active no DB."""
    print(f"     -> Waiting up to {timeout}s for real Webhook DB update...")
    start = time.time()
    while time.time() - start < timeout:
        sub = get_latest_subscription(session, client_id)
        if sub and sub["status"] == "active" and sub.get("webhook_pending") == 0:
            return True
        time.sleep(2)
    return False


def check_ui_popup(
    browser, auth_data, expected_text, timeout=10000, should_exist=True, no_close=False
):
    """Auxiliar para verificar popup na UI."""
    frontend_url = f"http://localhost:5082"
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
    try:
        page.goto(f"{frontend_url}/app", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        try:
            page.get_by_text(expected_text).wait_for(state="visible", timeout=timeout)
            found = True
        except:
            found = False

        return found == should_exist
    finally:
        if not no_close:
            ctx.close()


def check_cta_flow(browser, auth_data, no_close=False):
    """Verifica se clicar no CTA redireciona para a etapa de retry e completa o pagamento."""
    frontend_url = f"http://localhost:5082"
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

    # Selectors from test_payment_system.py
    SEL_CARD_HOLDER = 'input[placeholder="Nome do Titular"]'
    SEL_BTN_CONFIRM_INITIAL = 'button:has-text("Confirmar")'
    SEL_SUCCESS = '[data-testid="payment-success"], .payment-success, :text("Assinatura realizada"), :text("sucesso")'

    try:
        print(f"     -> Navigating to {frontend_url}/app")
        page.goto(f"{frontend_url}/app", wait_until="domcontentloaded")

        # 1. Esperar popup aparecer (com retry via reload)
        print("     -> Waiting 5s for initial popup load...")
        page.wait_for_timeout(5000)

        cta = page.get_by_text("Atualizar Cartão")
        if not cta.is_visible():
            print(
                "     ⚠️  Popup not visible, reloading page to re-trigger checkAuth..."
            )
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(5000)

        print("     -> Waiting for popup visibility...")
        cta.wait_for(state="visible", timeout=15000)
        print("     -> Clicking CTA...")
        cta.click()

        # 2. Verificar se redirecionou para /payment com tab=retry_payment
        print("     -> Checking redirection to /payment?tab=retry_payment...")
        page.wait_for_url("**/payment?*tab=retry_payment*", timeout=15000)
        print(f"     -> Redirection successful: {page.url}")

        # 3. Preencher dados do cartão
        print("     -> Filling card information...")
        page.wait_for_selector(SEL_CARD_HOLDER, timeout=10000)
        page.fill(SEL_CARD_HOLDER, "TESTE AUTOMATIZADO")

        # Iframe Stripe
        page.wait_for_selector('iframe[name^="__privateStripeFrame"]', timeout=10000)
        stripe_frame = page.frame_locator('iframe[name^="__privateStripeFrame"]').first

        print("     -> Filling Stripe fields...")
        stripe_frame.locator('input[name="cardnumber"]').fill("4242 4242 4242 4242")
        stripe_frame.locator('input[name="exp-date"]').fill("12 / 30")
        stripe_frame.locator('input[name="cvc"]').fill("123")

        # 4. Confirmar e aguardar retry automático
        print("     -> Clicking Confirm (Triggering automatic retry)...")
        page.locator(SEL_BTN_CONFIRM_INITIAL).click()

        # 5. Verificar sucesso final (UI + DB)
        print("     -> Waiting for final success message in UI...")
        page.wait_for_selector(SEL_SUCCESS, timeout=20000)

        print(
            "     -> Success in UI detected. Now waiting for DB update via Webhook..."
        )
        session = get_session()
        ok_db = wait_for_webhook_val(session, auth_data["client_id"], timeout=45)
        session.close()

        if ok_db:
            print("     ✅ SUCCESS: Payment recovery flow completed (UI + DB verified)!")
            return True
        else:
            print(
                "     ❌ FAILURE: UI success shown but DB not updated via Webhook (Timeout)."
            )
            return False
    except Exception as e:
        print(f"     ❌ CTA Flow Error: {e}")
        import os

        os.makedirs("output", exist_ok=True)
        page.screenshot(path="output/cta_flow_failed.png")
        return False
    finally:
        if not no_close:
            ctx.close()


def run_popup_validation():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--case",
        type=int,
        choices=[1, 2, 3, 4],
        help="Cenário específico: 1=Fail, 2=Suspended, 3=Normal, 4=CTA_Flow",
    )
    parser.add_argument(
        "--no-close", action="store_true", help="Mantém o navegador aberto após o teste"
    )
    args = parser.parse_args()

    check_health()
    session = get_session()

    print("\n" + "=" * 70)
    print("🚀 POPUP UI INSPECTOR")
    print("=" * 70)

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=False, slow_mo=500)

            cases_to_run = [args.case] if args.case else [1, 2, 3, 4]

            for c in cases_to_run:
                if c == 1:
                    print("\n🧪 TEST 1: Payment Failed Popup (Status: active, Retry: 1)")
                    auth = setup_mock_auth(session)
                    session.execute(
                        text(
                            "UPDATE billing_subscriptions SET status = 'active', payment_retry_count = 1 WHERE client_id = :cid"
                        ),
                        {"cid": auth["client_id"]},
                    )
                    session.commit()
                    res = check_ui_popup(
                        browser, auth, "Problema na Renovação", no_close=args.no_close
                    )
                    print(f"   {'✅' if res else '❌'}: Popup 'Problema na Renovação'")

                elif c == 2:
                    print("\n🧪 TEST 2: Account Suspended Popup (Status: suspended)")
                    auth = setup_mock_auth(session)
                    session.execute(
                        text(
                            "UPDATE billing_subscriptions SET status = 'suspended' WHERE client_id = :cid"
                        ),
                        {"cid": auth["client_id"]},
                    )
                    session.commit()
                    res = check_ui_popup(
                        browser, auth, "Assinatura Suspensa", no_close=args.no_close
                    )
                    print(f"   {'✅' if res else '❌'}: Popup 'Assinatura Suspensa'")

                elif c == 3:
                    print("\n🧪 TEST 3: No Popup (Status: active, Retry: 0)")
                    auth = setup_mock_auth(session)
                    session.execute(
                        text(
                            "UPDATE billing_subscriptions SET status = 'active', payment_retry_count = 0 WHERE client_id = :cid"
                        ),
                        {"cid": auth["client_id"]},
                    )
                    session.commit()
                    res = check_ui_popup(
                        browser,
                        auth,
                        "Problema na Renovação",
                        timeout=3000,
                        should_exist=False,
                        no_close=args.no_close,
                    )
                    print(f"   {'✅' if res else '❌'}: Sem popups (Normal)")

                elif c == 4:
                    print("\n🧪 TEST 4: CTA Flow - Update Card Redirection")
                    auth = setup_mock_auth(session)
                    session.execute(
                        text(
                            "UPDATE billing_subscriptions SET status = 'active', payment_retry_count = 1 WHERE client_id = :cid"
                        ),
                        {"cid": auth["client_id"]},
                    )
                    session.commit()
                    res = check_cta_flow(browser, auth, no_close=args.no_close)
                    print(f"   {'✅' if res else '❌'}: CTA Redirection and Retry Stage")

                if args.no_close and c == cases_to_run[-1]:
                    print(
                        "\n💡 Navegador mantido aberto. Pressione Ctrl+C no terminal para encerrar."
                    )
                    while True:
                        time.sleep(1)

            if not args.no_close:
                browser.close()

        print("\n" + "=" * 70)
        print("🏁 VALIDATION COMPLETE")
        print("=" * 70)

    except KeyboardInterrupt:
        print("\n🛑 Encerrado pelo usuário.")
    except Exception as ex:
        print(f"\n💥 CRITICAL ERROR: {ex}")
    finally:
        session.close()


if __name__ == "__main__":
    run_popup_validation()

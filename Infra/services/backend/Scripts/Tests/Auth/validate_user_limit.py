"""
Validation Script: User Limit Popup and Auto-Signup Flow.
Valida o sucesso inicial e o bloqueio posterior por limite de usuários usando e-mails de bypass oficiais.
Finaliza limpando COMPLETAMENTE todas as tabelas de usuários e clientes (Wipe Total).
"""

import os
import sys
import time
import argparse
import uuid
import requests
from pathlib import Path

# Adicionar root do backend ao sys.path
backend_root = Path(__file__).parent.parent.parent.parent.absolute()
sys.path.append(str(backend_root))

from App.Core.Settings.Settings import (
    MAX_USERS,
    EMAIL_BYPASS,
    GLOBAL_CONFIG,
    FRONTEND_HOST,
    FRONTEND_PORT,
    HOST,
    PORT,
    VITE_HTTP_PROTOCOL,
    DEV_BYPASS_KEY,
    DEV_USER_ID,
)
from App.Core.Crunch import get_db_manager
from sqlalchemy import text
from playwright.sync_api import sync_playwright


# Ajuste de hosts para Windows
def get_accessible_host(host):
    # Use 127.0.0.1 instead of 0.0.0.0 or localhost to avoid security warnings and ensure local binding
    return "127.0.0.1" if host == "0.0.0.0" or not host else host


BACKEND_URL = f"{VITE_HTTP_PROTOCOL}://{get_accessible_host(HOST)}:{PORT}"
FRONTEND_URL = (
    f"{VITE_HTTP_PROTOCOL}://{get_accessible_host(FRONTEND_HOST)}:{FRONTEND_PORT}"
)


def check_health():
    """Verifica se os serviços estão online antes de iniciar."""
    print(f"\n🔍 Verificando saúde dos serviços...")
    try:
        response = requests.get(f"{BACKEND_URL}/api/auth/health", timeout=5)
        if response.status_code == 200:
            print(f"✅ Backend OK")
    except Exception as e:
        print(f"❌ Backend INACESSÍVEL - {e}")
        return False
    try:
        response = requests.get(f"{FRONTEND_URL}/", timeout=5)
        if response.status_code == 200:
            print(f"✅ Frontend OK")
    except Exception as e:
        print(f"❌ Frontend INACESSÍVEL - {e}")
        return False
    return True


def cleanup_environment(full_wipe=False):
    """
    Limpa o DB.
    Se full_wipe=True, apaga ABSOLUTAMENTE TUDO das tabelas de usuários e clientes.
    """
    label = "TOTAL (WIPE)" if full_wipe else "PROFUNDA"
    print(f"[TEST] Iniciando limpeza {label} do ambiente...")
    db = get_db_manager()
    session = db.get_session()
    try:
        if full_wipe:
            # WIPE TOTAL - Ordem de dependência para evitar erros de FK
            tables = [
                "auth_logs",
                "access_tokens",
                "refresh_tokens",
                "devices",
                "messages",
                "assets",
                "documents",
                "chats",
                "users",
                "clients",
                "waitlist",
            ]
            for table in tables:
                try:
                    session.execute(text(f"DELETE FROM {table}"))
                except:
                    pass  # Algumas tabelas podem não existir em todas as versões do schema
            print("✅ [TEST] Todas as tabelas de usuários e clientes foram zeradas.")
        else:
            # Limpeza seletiva para o Passo 1
            test_patterns = ["mock_user_%", "test_%"] + EMAIL_BYPASS

            def delete_uids(uids):
                if not uids:
                    return
                uids_str = ",".join([f"'{u}'" for u in uids])
                session.execute(
                    text(f"DELETE FROM auth_logs WHERE user_id IN ({uids_str})")
                )
                session.execute(
                    text(f"DELETE FROM access_tokens WHERE user_id IN ({uids_str})")
                )
                session.execute(
                    text(f"DELETE FROM refresh_tokens WHERE user_id IN ({uids_str})")
                )
                session.execute(
                    text(f"DELETE FROM devices WHERE user_id IN ({uids_str})")
                )
                session.execute(
                    text(
                        f"DELETE FROM messages WHERE chat_id IN (SELECT chat_id FROM chats WHERE user_id IN ({uids_str}))"
                    )
                )
                session.execute(
                    text(f"DELETE FROM assets WHERE user_id IN ({uids_str})")
                )
                session.execute(
                    text(f"DELETE FROM documents WHERE user_id IN ({uids_str})")
                )
                session.execute(
                    text(f"DELETE FROM chats WHERE user_id IN ({uids_str})")
                )
                session.execute(
                    text(
                        f"DELETE FROM clients WHERE client_id IN (SELECT client_id FROM users WHERE user_id IN ({uids_str}))"
                    )
                )
                session.execute(
                    text(f"DELETE FROM users WHERE user_id IN ({uids_str})")
                )

            for pattern in test_patterns:
                uids = [
                    r[0]
                    for r in session.execute(
                        text(
                            "SELECT user_id FROM users WHERE email LIKE :p OR email = :p"
                        ),
                        {"p": pattern},
                    ).fetchall()
                ]
                delete_uids(uids)

            # Garantir que estamos abaixo do limite para o Passo 1
            current_count = session.execute(
                text("SELECT COUNT(*) FROM users")
            ).fetchone()[0]
            if current_count >= MAX_USERS:
                limit_to_keep = max(0, MAX_USERS - 2)
                uids_to_del = [
                    r[0]
                    for r in session.execute(
                        text(
                            "SELECT user_id FROM users WHERE user_id != :dev ORDER BY created_at ASC"
                        ),
                        {"dev": DEV_USER_ID},
                    ).fetchall()
                ]
                to_delete = (
                    uids_to_del[:-limit_to_keep] if limit_to_keep > 0 else uids_to_del
                )
                delete_uids(to_delete)

            session.execute(text("DELETE FROM waitlist"))
            session.execute(
                text(
                    "DELETE FROM clients WHERE client_id NOT IN (SELECT client_id FROM users)"
                )
            )

        session.commit()

        count = session.execute(text("SELECT COUNT(*) FROM users")).fetchone()[0]
        print(f"✅ [TEST] Limpeza concluída. Usuários restantes no DB: {count}")
        return True

    except Exception as e:
        session.rollback()
        print(f"❌ [TEST] FALHA NA LIMPEZA: {e}")
        return False
    finally:
        session.close()


def inject_mock_users(count):
    """Injeta usuários no banco para atingir o limite."""
    if count <= 0:
        return True
    print(
        f"[TEST] Injetando {count} usuários mock para atingir o limite ({MAX_USERS})..."
    )
    db = get_db_manager()
    session = db.get_session()
    try:
        res = session.execute(
            text("SELECT plan_id FROM plans WHERE plan_type = 'free' LIMIT 1")
        ).fetchone()
        plan_id = res[0]
        res = session.execute(
            text("SELECT MAX(CAST(client_id AS INTEGER)) FROM clients")
        ).fetchone()
        next_cid = (res[0] or 0) + 1
        res = session.execute(
            text("SELECT MAX(CAST(user_id AS INTEGER)) FROM users")
        ).fetchone()
        next_uid = (res[0] or 0) + 1
        for i in range(count):
            cid, uid = str(next_cid + i), str(next_uid + i)
            session.execute(
                text(
                    "INSERT INTO clients (client_id, plan_id, started_at, users_available) VALUES (:cid, :pid, CURRENT_TIMESTAMP, 1)"
                ),
                {"cid": cid, "pid": plan_id},
            )
            session.execute(
                text(
                    "INSERT INTO users (user_id, client_id, email, password, full_name, created_at) VALUES (:uid, :cid, :email, 'hash', 'Mock', CURRENT_TIMESTAMP)"
                ),
                {"uid": uid, "cid": cid, "email": f"mock_user_{uid}@example.com"},
            )
        session.commit()
        print(f"✅ [TEST] {count} usuários injetados.")
        return True
    except Exception as e:
        session.rollback()
        print(f"❌ [TEST] Erro na injeção: {e}")
        return False
    finally:
        session.close()


def run_step(page, email, expect_popup=False, is_retry=False):
    """Executa um passo de registro no frontend com monitoramento de rede."""
    step_id = uuid.uuid4().hex[:4]
    print(
        f"\n[TEST-{step_id}] Registro: {email} (Popup: {expect_popup}, Retry: {is_retry})"
    )

    def handle_response(response):
        if "/api/auth/signup" in response.url:
            print(
                f"📊 [NETWORK-{step_id}] {response.request.method} {response.url} -> STATUS: {response.status}"
            )

    page.on("response", handle_response)

    try:
        page.goto(f"{FRONTEND_URL}/login")

        try:
            btn = page.locator(
                'button:has-text("Confirmar"), button:has-text("Concordo")'
            ).first
            if btn.is_visible(timeout=3000):
                btn.click()
        except:
            pass

        page.locator('input[type="email"]').wait_for(state="visible")
        page.locator('input[type="email"]').fill(email)

        submit_btn = page.locator('button[type="submit"]').first
        page.wait_for_function(
            "() => !document.querySelector('button[type=\"submit\"]').disabled",
            timeout=15000,
        )
        submit_btn.click()

        try:
            pwd_input = page.locator('input[id="password"]')
            pwd_input.wait_for(state="visible", timeout=10000)

            if page.locator('input[id="name"]').is_visible(timeout=2000):
                page.locator('input[id="name"]').fill("Test User")

            pwd_input.fill("Test123456!")

            if page.locator('input[id="confirmPassword"]').is_visible(timeout=1000):
                page.locator('input[id="confirmPassword"]').fill("Test123456!")

            final_btn = page.locator('button[type="submit"]').first
            page.wait_for_function(
                "() => !document.querySelector('button[type=\"submit\"]').disabled",
                timeout=10000,
            )
            final_btn.click()
        except:
            if page.locator("text=Interesse confirmado!").is_visible():
                return True
            if not is_retry:
                return run_step(page, email, expect_popup, is_retry=True)
            return False

        if expect_popup:
            try:
                page.wait_for_selector("text=Interesse confirmado!", timeout=20000)
                print(f"✨ ✅ [TEST-{step_id}] SUCESSO: Popup detectado!")
                time.sleep(2)

                confirm_btn = page.locator('button:has-text("Entendido")').first
                if confirm_btn.is_visible():
                    print(f"[TEST-{step_id}] Clicando em 'Entendido'...")
                    confirm_btn.click()
                    time.sleep(2)

                return True
            except:
                if not is_retry:
                    return run_step(page, email, expect_popup, is_retry=True)
                return False
        else:
            try:
                page.wait_for_url("**/app**", timeout=20000)
                print(f"✅ [TEST-{step_id}] Registro OK.")
                return True
            except:
                if not is_retry:
                    return run_step(page, email, expect_popup, is_retry=True)
                return False
    except Exception as e:
        if not is_retry:
            return run_step(page, email, expect_popup, is_retry=True)
        return False
    finally:
        page.remove_listener("response", handle_response)


def run_validation(no_close=False):
    if not check_health():
        return
    if len(EMAIL_BYPASS) < 2:
        return

    # Limpeza Inicial Seletiva (para o teste rodar)
    cleanup_environment(full_wipe=False)

    with sync_playwright() as p:
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        browser = p.chromium.launch(headless=False, slow_mo=300)
        context = browser.new_context(
            user_agent=user_agent,
            extra_http_headers={
                "X-Dev-Bypass-Key": DEV_BYPASS_KEY,
                "Origin": FRONTEND_URL,
                "Referer": f"{FRONTEND_URL}/",
            },
        )
        page = context.new_page()
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', { get: () => false })"
        )

        # 1. SignUp Sucesso
        print("\n--- PASSO 1: Registro inicial (Sucesso) ---")
        if not run_step(page, EMAIL_BYPASS[0], expect_popup=False):
            if not no_close:
                browser.close()
            return

        # 2. Atingir Limite
        db = get_db_manager()
        session = db.get_session()
        current = session.execute(
            text(
                "SELECT COUNT(DISTINCT u.user_id) FROM users u JOIN clients c ON u.client_id = c.client_id JOIN plans p ON c.plan_id = p.plan_id WHERE p.plan_type != 'trial'"
            )
        ).fetchone()[0]
        session.close()
        inject_mock_users(MAX_USERS - current)

        # 3. SignUp Bloqueio
        print(f"\n--- PASSO 3: Testando Bloqueio com {EMAIL_BYPASS[1]} ---")
        run_step(page, EMAIL_BYPASS[1], expect_popup=True)

        if no_close:
            print("\n[TEST] Validação concluída. Aguardando 5s antes do Wipe Final...")
            time.sleep(5)

        browser.close()

    # FINALIZAÇÃO: WIPE TOTAL
    print("\n--- FINALIZAÇÃO: Zerando todas as tabelas de usuários e clientes ---")
    cleanup_environment(full_wipe=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-close", action="store_true")
    args = parser.parse_args()
    run_validation(no_close=args.no_close)

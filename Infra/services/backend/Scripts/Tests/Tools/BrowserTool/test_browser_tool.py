"""
Validação automatizada do sistema UserBrowser (extensão Chrome + WebSocket + tool).

Fluxo:
  1. Cria usuário mock e gera access_token
  2. Lança Chromium com a extensão MD70 carregada
  3. Injeta o access_token como cookie para o domínio do app
  4. Navega para o app — a extensão detecta o domínio e autentica no WS
  5. Aguarda a conexão aparecer em /dev/browser-connections
  6. Executa cada ação e valida o resultado
  7. Cleanup do usuário mock

Uso:
  python test_browser_tool.py [--headless] [--base-url http://localhost:4001] [--cleanup]
"""

import sys
import os
import json
import asyncio
import uuid
import argparse
import time
import base64
import requests
import tempfile
from pathlib import Path
from datetime import datetime
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# ─── Paths & env ──────────────────────────────────────────────────────────────

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv

mvp_root = BACKEND_DIR.parent.parent
_env = mvp_root / ".env.development"
if _env.exists():
    load_dotenv(dotenv_path=str(_env), override=True)

from App.Core.Settings.Settings import (
    HOST,
    PORT,
    FRONTEND_HOST,
    FRONTEND_PORT,
    VITE_HTTP_PROTOCOL,
)
from App.Features.Auth.AuthService import get_auth_service

PROX_ROOT = BACKEND_DIR.parent.parent.parent.parent
EXT_PATH = str(PROX_ROOT / "prox_agent_ext")

# ─── Args ─────────────────────────────────────────────────────────────────────

_parser = argparse.ArgumentParser(description="Validação do UserBrowser Tool")
_parser.add_argument("--headless", action="store_true", default=False)
_parser.add_argument(
    "--base-url", default=None, help="URL direta do backend (ex: http://localhost:4001)"
)
_parser.add_argument("--cleanup", action="store_true", default=True)
args, _ = _parser.parse_known_args()


def get_accessible_host(h):
    return "localhost" if not h or h == "0.0.0.0" else h


BACKEND_URL = (
    args.base_url or f"{VITE_HTTP_PROTOCOL}://{get_accessible_host(HOST)}:{PORT}"
)
FRONTEND_URL = (
    f"{VITE_HTTP_PROTOCOL}://{get_accessible_host(FRONTEND_HOST)}:{FRONTEND_PORT}"
)
DB_PATH = BACKEND_DIR / "Data" / "Database" / "MD70.db"
OUTPUT_DIR = Path(__file__).parent / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

EXECUTION_UUID = str(uuid.uuid4())[:8]
TEST_EMAIL = f"bt_test_{EXECUTION_UUID}@prox.test"
TEST_PASSWORD = f"BTest@{EXECUTION_UUID}!"

STATE = {
    "user_id": None,
    "token": None,
    "refresh_token": None,
    "passed": 0,
    "failed": 0,
}

# ─── Helpers ──────────────────────────────────────────────────────────────────

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"
BOLD = "\033[1m"


def log(msg, color=RESET):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"{color}[{ts}] {msg}{RESET}")


def ok(label, detail=""):
    STATE["passed"] += 1
    log(f"✓ {label} {detail}", GREEN)


def fail(label, detail=""):
    STATE["failed"] += 1
    log(f"✗ {label} {detail}", RED)


def section(title):
    print(f"\n{BOLD}{'─'*60}{RESET}")
    print(f"{BOLD}  {title}{RESET}")
    print(f"{BOLD}{'─'*60}{RESET}")


def _dev(method, path, **kwargs):
    """Chamada direta ao backend (porta 4001) — não passa pelo Nginx."""
    cookies = {"access_token": STATE["token"]} if STATE["token"] else {}
    headers = kwargs.pop("headers", {"Content-Type": "application/json"})
    return getattr(requests, method)(
        f"{BACKEND_URL}{path}", cookies=cookies, headers=headers, timeout=55, **kwargs
    )


def wait_for_connection(user_id: str, timeout: int = 30) -> bool:
    """Aguarda até o user_id aparecer nas conexões ativas do WS."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = _dev("get", "/dev/browser-connections")
            if r.status_code == 200 and user_id in r.json().get("connected_users", []):
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


# ─── Setup ────────────────────────────────────────────────────────────────────


def setup():
    section("SETUP — Criando usuário mock")
    auth = get_auth_service()

    ok_flag, user_data, err = auth.register_user(
        email=TEST_EMAIL,
        password=TEST_PASSWORD,
        fingerprint_id=f"fp_{EXECUTION_UUID}",
        fingerprint_components={},
        ip_address="127.0.0.1",
    )
    if not ok_flag:
        fail("register_user", err)
        sys.exit(1)

    STATE["user_id"] = user_data["user_id"]
    client_id = user_data["client_id"]

    STATE["token"] = auth.generate_access_token(
        {
            "user_id": STATE["user_id"],
            "client_id": client_id,
            "email": TEST_EMAIL,
            "role": "member",
            "full_name": "BrowserTool Test",
        },
        save_to_db=True,
    )

    refresh_data = auth.generate_refresh_token(
        {
            "user_id": STATE["user_id"],
            "client_id": client_id,
            "email": TEST_EMAIL,
        }
    )
    STATE["refresh_token"] = refresh_data["token"]

    ok("Usuário mock criado", f"user_id={STATE['user_id']}")


# ─── Cleanup ──────────────────────────────────────────────────────────────────


def cleanup():
    section("CLEANUP")
    if not STATE["user_id"]:
        return
    engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"timeout": 10})
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        session.execute(
            text("DELETE FROM users WHERE user_id = :uid"), {"uid": STATE["user_id"]}
        )
        session.commit()
        ok("Usuário mock removido")
    except Exception as e:
        fail("Cleanup", str(e))
    finally:
        session.close()


# ─── Testes ───────────────────────────────────────────────────────────────────


def run_tool(action: str, **kwargs) -> dict:
    r = _dev(
        "post",
        "/dev/browser-tool",
        json={
            "user_id": STATE["user_id"],
            "action": action,
            **kwargs,
        },
    )
    return (
        r.json()
        if r.status_code == 200
        else {"error": f"HTTP {r.status_code}", "detail": r.text}
    )


def test_screenshot():
    result = run_tool("screenshot")
    data = result.get("data", "")
    if isinstance(data, str) and data.startswith("data:image/png;base64,"):
        b64 = data.split(",", 1)[1]
        size_kb = len(base64.b64decode(b64)) // 1024
        ok("screenshot", f"({size_kb} KB)")
        (OUTPUT_DIR / "screenshot.png").write_bytes(base64.b64decode(b64))
    else:
        fail("screenshot", str(result))


def test_scrape():
    result = run_tool("scrape")
    # content script retorna {data: {url, title, content}}, background wraps em {data: ...}
    inner = result.get("data", {})
    if isinstance(inner, dict) and "data" in inner:
        inner = inner["data"]
    if isinstance(inner, dict) and inner.get("content"):
        ok(
            "scrape",
            f"title='{inner.get('title', '')}' ({len(inner['content'])} chars)",
        )
    else:
        fail("scrape", str(result))


def test_redirect(url: str):
    result = run_tool("redirect", url=url)
    if result.get("status") == "success":
        ok("redirect", f"→ {url}")
        time.sleep(2)  # aguarda carregamento
    else:
        fail("redirect", str(result))


def test_scroll(amount: int = 300):
    result = run_tool("scroll", amount=amount)
    data = result.get("data", {})
    if data.get("success"):
        ok("scroll", f"{amount}px (scrollY={data.get('scrollY', '?')})")
    else:
        fail("scroll", str(result))


def test_click_text(text: str):
    result = run_tool("click_text", text=text)
    data = result.get("data", {})
    if data.get("success"):
        ok(
            "click_text",
            f'"{text}" → <{data.get("tag")}> "{data.get("text", "")[:50]}"',
        )
    else:
        fail("click_text", str(result))


def test_type(selector: str, text: str):
    result = run_tool("type", selector=selector, text=text)
    data = result.get("data", {})
    if data.get("success"):
        ok("type", f'selector="{selector}" text="{text}"')
    else:
        fail("type", str(result))


def test_press_key(key: str = "Enter", selector: str = None):
    kwargs = {"key": key}
    if selector:
        kwargs["selector"] = selector
    result = run_tool("press_key", **kwargs)
    data = result.get("data", {})
    if data.get("success"):
        ok("press_key", f'key="{key}"')
    else:
        fail("press_key", str(result))


# ─── Runner principal ─────────────────────────────────────────────────────────


async def run_tests_with_browser():
    from playwright.async_api import async_playwright

    section("BROWSER — Iniciando com extensão")
    log(f"Extensão: {EXT_PATH}")

    with tempfile.TemporaryDirectory() as tmp_dir:
        async with async_playwright() as p:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=tmp_dir,
                headless=args.headless,
                args=[
                    f"--disable-extensions-except={EXT_PATH}",
                    f"--load-extension={EXT_PATH}",
                    "--no-sandbox",
                    "--start-maximized",
                ],
                no_viewport=True,
            )

            page = await context.new_page()

            # Injeta os cookies antes de navegar para o domínio
            cookie_domain = get_accessible_host(FRONTEND_HOST)
            await context.add_cookies(
                [
                    {
                        "name": "access_token",
                        "value": STATE["token"],
                        "domain": cookie_domain,
                        "path": "/",
                        "httpOnly": True,
                        "sameSite": "Lax",
                    },
                    {
                        "name": "refresh_token",
                        "value": STATE["refresh_token"],
                        "domain": cookie_domain,
                        "path": "/",
                        "httpOnly": True,
                        "sameSite": "Lax",
                    },
                ]
            )

            # Navega para o app — aciona detecção de domínio na extensão
            log(f"Navegando para {FRONTEND_URL} ...")
            await page.goto(FRONTEND_URL, wait_until="domcontentloaded", timeout=15000)

            section("WS — Aguardando conexão da extensão")
            connected = wait_for_connection(STATE["user_id"], timeout=30)
            if connected:
                ok("WS conectado", f"user_id={STATE['user_id']}")
            else:
                fail("WS conexão — timeout 30s")
                await context.close()
                return

            section("TESTES DAS ACTIONS")

            WIKI_URL = "https://en.wikipedia.org/wiki/Python_(programming_language)"

            # 1. Redirect para Wikipedia (Python)
            test_redirect(WIKI_URL)
            time.sleep(3)  # aguarda carregamento completo

            # 2. Screenshot inicial da Wikipedia
            test_screenshot()

            # 3. Scrape — verifica conteúdo da Wikipedia
            result = run_tool("scrape")
            inner = result.get("data", {})
            if isinstance(inner, dict) and "data" in inner:
                inner = inner["data"]
            content = inner.get("content", "")
            if "Python" in content and "programming" in content.lower():
                ok("scrape", f"title='{inner.get('title', '')}' ({len(content)} chars)")
            else:
                fail("scrape", f"Conteúdo inesperado: {str(inner)[:200]}")

            # 4. Scroll para baixo — navega pelo artigo
            test_scroll(800)
            time.sleep(1)

            # 5. Screenshot após scroll — confirma posição diferente
            test_screenshot()

            # 6. Click no link "History" do TOC da Wikipedia
            test_click_text("History")
            time.sleep(1)

            # 7. Scrape após click — confirma seção History no conteúdo
            result = run_tool("scrape")
            inner = result.get("data", {})
            if isinstance(inner, dict) and "data" in inner:
                inner = inner["data"]
            if "history" in inner.get("content", "").lower():
                ok("scrape após click", f"'History' encontrado no conteúdo")
            else:
                fail("scrape após click", "Seção 'History' não encontrada")

            # 8. Type na barra de busca da Wikipedia
            test_type("input[name='search']", "JavaScript")
            time.sleep(1)

            # 9. Press Enter para executar a busca
            test_press_key("Enter", selector="input[name='search']")
            time.sleep(3)  # aguarda navegação para a página do JavaScript

            # 10. Scrape — confirma que navegou para o artigo do JavaScript
            result = run_tool("scrape")
            inner = result.get("data", {})
            if isinstance(inner, dict) and "data" in inner:
                inner = inner["data"]
            if (
                "javascript" in inner.get("title", "").lower()
                or "javascript" in inner.get("content", "").lower()[:500]
            ):
                ok("scrape após Enter", f"Navegou para: '{inner.get('title', '')}'")
            else:
                fail(
                    "scrape após Enter",
                    f"Título inesperado: '{inner.get('title', '')}'",
                )

            # 11. Redirect de volta para o app
            test_redirect(FRONTEND_URL)

            await context.close()


def main():
    setup()

    try:
        asyncio.run(run_tests_with_browser())
    except Exception as e:
        fail("Execução do browser", str(e))
        raise
    finally:
        if args.cleanup:
            cleanup()

    section("RESULTADO FINAL")
    total = STATE["passed"] + STATE["failed"]
    color = GREEN if STATE["failed"] == 0 else RED
    log(f"{STATE['passed']}/{total} testes passaram", color)

    result_path = OUTPUT_DIR / f"result_{EXECUTION_UUID}.json"
    result_path.write_text(
        json.dumps(
            {
                "uuid": EXECUTION_UUID,
                "passed": STATE["passed"],
                "failed": STATE["failed"],
                "total": total,
                "timestamp": datetime.now().isoformat(),
            },
            indent=2,
        )
    )

    sys.exit(0 if STATE["failed"] == 0 else 1)


if __name__ == "__main__":
    main()

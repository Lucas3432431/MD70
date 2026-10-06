"""
Valida a integração com Browserbase antes do deploy.

Força o uso do Browserbase independente do ENV, criando uma sessão isolada
por request e verificando que o Google não retorna captcha.

Uso:
    python test_browserbase.py               # roda 2 queries de validação
    python test_browserbase.py --full        # roda cenário completo (4 queries)
    python test_browserbase.py --session     # exibe info da sessão criada
"""

import asyncio
import os
import sys
import argparse
import logging
from pathlib import Path
from datetime import datetime

# ── Path setup ─────────────────────────────────────────────────────────────────
backend_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.append(str(backend_root))

# ── Mocks mínimos ──────────────────────────────────────────────────────────────
import unittest.mock as mock

sys.modules.setdefault("App.Core.Services.Common.Dependencies", mock.MagicMock())
sys.modules.setdefault("App.Core.Services.Common.AppSetup", mock.MagicMock())
sys.modules.setdefault("App.Core.Settings.Settings", mock.MagicMock())

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

CAPTCHA_MARKERS = [
    "nossos sistemas detectaram",
    "our systems have detected",
    "unusual traffic",
    "tráfego incomum",
    "verify you're a human",
    "recaptcha",
]


def is_captcha(content: str) -> bool:
    text = (content or "").lower()
    return any(m in text for m in CAPTCHA_MARKERS)


def print_section(title: str):
    print(f"\n{'─' * 70}")
    print(f"  {title}")
    print(f"{'─' * 70}")


# ── Browserbase session helper ─────────────────────────────────────────────────


def create_bb_session(api_key: str, project_id: str, show_info: bool = False) -> str:
    """Cria uma sessão Browserbase e retorna a connect_url."""
    from browserbase import Browserbase

    bb = Browserbase(api_key=api_key)
    session = bb.sessions.create(project_id=project_id)
    if show_info:
        print(f"  Session ID  : {session.id}")
        print(f"  Connect URL : {session.connect_url[:60]}...")
    return session.connect_url


# ── Core: scrape via Browserbase ───────────────────────────────────────────────


async def screenshot_via_browserbase(
    url: str, connect_url: str, save_dir: Path
) -> dict:
    """Tira screenshot via Browserbase e salva em disco."""
    import random
    from playwright.async_api import async_playwright

    try:
        from playwright_stealth import stealth_async
    except ImportError:
        stealth_async = None

    start = asyncio.get_event_loop().time()
    try:
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(connect_url)
            context = (
                browser.contexts[0]
                if browser.contexts
                else await browser.new_context(viewport={"width": 1280, "height": 900})
            )
            page = await context.new_page()
            if stealth_async:
                await stealth_async(page)
            await asyncio.sleep(random.uniform(0.5, 1.0))
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2.0)
            screenshot_bytes = await page.screenshot(type="png", full_page=False)
            await browser.close()

        elapsed = asyncio.get_event_loop().time() - start
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = save_dir / f"{ts}_screenshot.png"
        out_path.write_bytes(screenshot_bytes)
        return {
            "status": "success",
            "size_kb": len(screenshot_bytes) // 1024,
            "path": str(out_path),
            "elapsed": elapsed,
        }
    except Exception as e:
        elapsed = asyncio.get_event_loop().time() - start
        return {"status": "error", "error": str(e), "elapsed": elapsed}


async def scrape_via_browserbase(url: str, connect_url: str) -> dict:
    """Abre uma página via Browserbase e extrai conteúdo com trafilatura."""
    import random
    import trafilatura
    from playwright.async_api import async_playwright

    try:
        from playwright_stealth import stealth_async
    except ImportError:
        stealth_async = None

    start = asyncio.get_event_loop().time()
    try:
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(connect_url)
            context = (
                browser.contexts[0] if browser.contexts else await browser.new_context()
            )
            page = await context.new_page()
            if stealth_async:
                await stealth_async(page)
            await asyncio.sleep(random.uniform(0.5, 1.5))
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(random.uniform(1.0, 2.0))
            html = await page.content()
            await browser.close()

        content = (
            trafilatura.extract(html, output_format="markdown", include_links=True)
            or ""
        )
        elapsed = asyncio.get_event_loop().time() - start
        captcha = is_captcha(content)
        return {
            "status": "captcha" if captcha else ("success" if content else "empty"),
            "content": content,
            "chars": len(content),
            "elapsed": elapsed,
        }
    except Exception as e:
        elapsed = asyncio.get_event_loop().time() - start
        return {
            "status": "error",
            "content": "",
            "chars": 0,
            "elapsed": elapsed,
            "error": str(e),
        }


# ── Testes ─────────────────────────────────────────────────────────────────────

QUERIES = [
    {
        "label": "Google SERP — site:linkedin.com",
        "url": "https://www.google.com/search?q=site:linkedin.com+%22head+of+marketing%22+fintech",
    },
    {
        "label": "Google SERP — site:instagram.com",
        "url": "https://www.google.com/search?q=site:instagram.com+%22personal+trainer%22+sp",
    },
    {
        "label": "Google SERP paginada (start=10)",
        "url": "https://www.google.com/search?q=site:linkedin.com+%22head+of+marketing%22+fintech&start=10",
    },
    {
        "label": "Fetch direto — G1",
        "url": "https://g1.globo.com",
    },
]

SCREENSHOT_URL = "https://www.instagram.com/explore/tags/personaltrainer/"


async def run_validation(api_key: str, project_id: str, full: bool, show_session: bool):
    print_section("TESTE 1 — Credenciais Browserbase")
    try:
        from browserbase import Browserbase

        bb = Browserbase(api_key=api_key)
        # Lista projetos como smoke test de autenticação
        _ = bb.projects.retrieve(project_id)
        print(f"  ✓ API key válida")
        print(f"  ✓ Project ID encontrado: {project_id}")
    except Exception as e:
        print(f"  ✗ Falha ao autenticar: {e}")
        return

    queries = QUERIES if full else QUERIES[:2]
    results = []

    for i, q in enumerate(queries):
        print_section(f"TESTE {i + 2} — {q['label']}")
        print(f"  URL: {q['url'][:80]}...")

        connect_url = create_bb_session(api_key, project_id, show_info=show_session)
        result = await scrape_via_browserbase(q["url"], connect_url)

        icon = {
            "success": "✓",
            "captcha": "✗ CAPTCHA",
            "empty": "~ vazio",
            "error": "✗ erro",
        }.get(result["status"], "?")
        print(f"  Status  : {icon}")
        print(f"  Chars   : {result['chars']}")
        print(f"  Tempo   : {result['elapsed']:.1f}s")
        if result.get("error"):
            print(f"  Erro    : {result['error'][:100]}")
        if result["chars"] > 0 and result["status"] == "success":
            preview = result["content"][:300].replace("\n", " ")
            print(f"  Preview : {preview}...")

        results.append({"label": q["label"], **result})

    # Teste de screenshot
    screenshot_idx = len(queries) + 2
    print_section(f"TESTE {screenshot_idx} — Screenshot (visual rendering)")
    print(f"  URL: {SCREENSHOT_URL}")
    save_dir = Path(__file__).parent / "output"
    save_dir.mkdir(exist_ok=True)
    connect_url = create_bb_session(api_key, project_id, show_info=show_session)
    ss_result = await screenshot_via_browserbase(SCREENSHOT_URL, connect_url, save_dir)
    if ss_result["status"] == "success":
        print(
            f"  ✓ Screenshot capturado: {ss_result['size_kb']} KB em {ss_result['elapsed']:.1f}s"
        )
        print(f"  Salvo em: {ss_result['path']}")
    else:
        print(f"  ✗ Falha: {ss_result.get('error', '')[:100]}")

    print_section("SUMÁRIO")
    ok = sum(1 for r in results if r["status"] == "success")
    captcha = sum(1 for r in results if r["status"] == "captcha")
    errors = sum(1 for r in results if r["status"] == "error")
    for r in results:
        icon = {"success": "✓", "captcha": "✗ captcha", "empty": "~", "error": "✗"}.get(
            r["status"], "?"
        )
        print(f"  {icon} {r['label']} — {r['chars']} chars ({r['elapsed']:.1f}s)")
    ss_icon = "✓" if ss_result["status"] == "success" else "✗"
    print(
        f"  {ss_icon} Screenshot — {ss_result.get('size_kb', 0)} KB ({ss_result['elapsed']:.1f}s)"
    )
    print()
    print(
        f"  Total SERP: {ok}/{len(results)} ok  |  {captcha} captcha  |  {errors} erros"
    )
    print(f"  Screenshot: {'ok' if ss_result['status'] == 'success' else 'falhou'}")

    if captcha > 0:
        print(
            "\n  AVISO: Captcha detectado — verifique o plano Browserbase (proxy residencial)."
        )
    if ok == len(results) and ss_result["status"] == "success":
        print("\n  Browserbase operacional. Pode fazer deploy.")
    print()


# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Valida integração Browserbase")
    parser.add_argument(
        "--full", action="store_true", help="Roda 4 queries em vez de 2"
    )
    parser.add_argument(
        "--session", action="store_true", help="Exibe info da sessão criada"
    )
    args = parser.parse_args()

    # Carrega credenciais do .env do mvp
    env_file = backend_root.parent.parent / ".env.development"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

    api_key = os.environ.get("BROWSERBASE_API_KEY", "")
    project_id = os.environ.get("BROWSERBASE_PROJECT_ID", "")

    if not api_key or not project_id:
        print("✗ BROWSERBASE_API_KEY e BROWSERBASE_PROJECT_ID não encontrados.")
        print(f"  Verifique: {env_file}")
        sys.exit(1)

    print(f"\n  API Key    : {api_key[:12]}...{api_key[-4:]}")
    print(f"  Project ID : {project_id}")
    print(f"  Modo       : {'full (4 queries)' if args.full else 'padrão (2 queries)'}")

    asyncio.run(
        run_validation(api_key, project_id, full=args.full, show_session=args.session)
    )

"""
Testa o fluxo de Creative Design (Canva-like Architecture).

Valida:
  01. Lógica da ferramenta design-creative via Core.py (ShouldUseCanvaTree=True)
  02. Persistência da tabela creative_compositions no DB
  03. POST /api/chat/{chat_id}/creative/{id}/update (Criação e Atualização)
  04. GET /api/chat/{chat_id}/creative/{id} (Recuperação do JSON)
  05. Validação UI (Playwright): Botão "Ativar Editor" e Renderização Konva

Uso:
    cd App/mvp/services/backend
    python3 Scripts/Tests/CreativeDesign/test_creative_design_flow.py --start
"""

import sys
import os
import uuid
import json
import asyncio
import argparse
from datetime import datetime
from pathlib import Path
from sqlalchemy import text, create_engine
from sqlalchemy.orm import sessionmaker

# ── Path e ENV ────────────────────────────────────────────────────────────────
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(BACKEND_DIR))

_parser = argparse.ArgumentParser(add_help=False)
_parser.add_argument("--start", action="store_true", help="Executar testes")
_parser.add_argument("--base-url", default="http://localhost:4000")
_parser.add_argument("--frontend-url", default="http://localhost:3000")
_parser.add_argument("--cleanup", action="store_true")
_parser.add_argument("--headless", action="store_true", default=False)
_args, _ = _parser.parse_known_args()

if not _args.start:
    print("Informe --start para executar os testes.")
    sys.exit(1)

from dotenv import load_dotenv

_env_file = BACKEND_DIR.parent.parent / ".env.development"
if _env_file.exists():
    load_dotenv(dotenv_path=str(_env_file), override=True)

BASE_URL = _args.base_url.rstrip("/")
FRONTEND_URL = _args.frontend_url.rstrip("/")
CLEANUP = _args.cleanup

from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Features.Auth.AuthService import get_auth_service

# ── Constantes ────────────────────────────────────────────────────────────────
SEP = "=" * 70
SEP2 = "-" * 70

DB_PATH = BACKEND_DIR / "Data" / "Database" / "MD70.db"

results: list[dict] = []

TEST_STATE = {
    "user_id": None,
    "client_id": None,
    "chat_id": None,
    "token": None,
    "refresh_token": None,
    "composition_id": "test-comp-" + str(uuid.uuid4())[:8],
}

# ── Helpers ───────────────────────────────────────────────────────────────────


def get_db_session():
    engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"timeout": 10})
    return sessionmaker(bind=engine)()


def step(label: str, *, passed: bool, detail: str = "") -> bool:
    icon = "[OK]  " if passed else "[FAIL]"
    print(f"\n{SEP2}\n  {icon} {label}")
    if detail:
        print(f"       {detail}")
    results.append({"label": label, "passed": passed})
    return passed


def _http(method: str, path: str, **kwargs):
    import requests as _req

    token = TEST_STATE["token"]
    cookies = {"access_token": token} if token else {}
    headers = kwargs.pop("headers", {})
    headers.setdefault("Content-Type", "application/json")
    url = f"{BASE_URL}{path}"
    return getattr(_req, method)(
        url, cookies=cookies, headers=headers, timeout=15, **kwargs
    )


# ── Setup ─────────────────────────────────────────────────────────────────────


async def setup():
    print(f"\n{SEP}\n  SETUP: preparando ambiente de teste\n{SEP}")

    # Inicializar schema se necessário
    try:
        from App.Core.Crunch.TablesSQL.Database import database

        database.initialize()
        from App.Core.Crunch.TablesSQL.SchemaManager import SchemaManager

        schema_manager = SchemaManager()
        schema_manager.create_tables()
        print("  [OK] Schema inicializado")
    except Exception as e:
        print(f"  [WARN] Erro ao inicializar schema: {e}")

    auth_service = get_auth_service()
    test_id = str(uuid.uuid4())[:8]
    email = f"canva.{test_id}@prox.test"
    password = f"Test@{test_id}!"

    ok, user_data, err = auth_service.register_user(
        email=email,
        password=password,
        fingerprint_id=f"fp_canva_{test_id}",
        fingerprint_components={},
        ip_address="127.0.0.1",
    )
    if not ok:
        print(f"  [ERRO] Falha ao criar usuário: {err}")
        sys.exit(1)

    user_id = user_data["user_id"]
    client_id = str(user_data["client_id"])

    user_payload = {
        "user_id": user_id,
        "client_id": client_id,
        "email": email,
        "role": "member",
    }
    token = auth_service.generate_access_token(user_payload, save_to_db=True)
    refresh_data = auth_service.generate_refresh_token(user_payload, save_to_db=True)
    refresh_token = refresh_data["token"]

    chat_id = str(uuid.uuid4())
    session = get_db_session()
    try:
        session.execute(
            text(
                """
            INSERT INTO chats (chat_id, user_id, chat_name, status, created_at, updated_at)
            VALUES (:cid, :uid, 'Canva Test Chat', 'active', datetime('now'), datetime('now'))
        """
            ),
            {"cid": chat_id, "uid": user_id},
        )

        # Inserir um asset fake para garantir que o preview apareça
        asset_id = "test-asset-" + str(uuid.uuid4())[:8]
        session.execute(
            text(
                """
            INSERT INTO assets (asset_id, user_id, client_id, chat_id, type, created_at, updated_at)
            VALUES (:aid, :uid, :cid_db, :chat_id, 'img', datetime('now'), datetime('now'))
        """
            ),
            {"aid": asset_id, "uid": user_id, "cid_db": client_id, "chat_id": chat_id},
        )

        session.commit()
    finally:
        session.close()

    TEST_STATE.update(
        {
            "user_id": user_id,
            "client_id": client_id,
            "chat_id": chat_id,
            "token": token,
            "refresh_token": refresh_token,
        }
    )

    print(f"  [OK] Usuário: {email}")
    print(f"  [OK] Chat:    {chat_id}")


# ── Testes ────────────────────────────────────────────────────────────────────


async def run_tests():
    print(f"\n{SEP}\n  EXECUTANDO TESTES DE DESIGN_CREATIVE\n{SEP}")

    chat_id = TEST_STATE["chat_id"]
    comp_id = TEST_STATE["composition_id"]

    # 01. Lógica da ferramenta
    from App.Features.Tools.Tools.CreativeDesign import run_design_logic

    mock_composition = {
        "dimensions": {"width": 1080, "height": 1080},
        "layers": {
            "layer_1": {
                "id": "layer_1",
                "type": "text",
                "x_position": 50,
                "y_position": 50,
                "width": 100,
                "height": 50,
                "rotate": 0,
                "scale": 1,
                "opacity": 1,
                "zIndex": 1,
                "props": {
                    "content": "Texto de Teste",
                    "fontSize": 40,
                    "color": "#FF0000",
                },
            }
        },
    }

    res_tool = run_design_logic(
        chat_id=chat_id, action="create", composition=mock_composition
    )
    step(
        "01. Lógica da ferramenta design-creative (run_design_logic)",
        passed=res_tool.get("success") == True,
    )

    # 02. POST /update
    payload = {
        "title": "Design Inicial",
        "state": mock_composition,
        "preview_url": "http://placeholder.com/thumb.png",
    }
    r = _http("post", f"/api/chat/{chat_id}/creative/{comp_id}/update", json=payload)
    step(
        "02. POST /update -> Criação de nova composição",
        passed=r.status_code == 200 and r.json().get("success") == True,
    )

    # 03. Verificação no Banco
    session = get_db_session()
    try:
        row = session.execute(
            text("SELECT title FROM creative_compositions WHERE composition_id = :id"),
            {"id": comp_id},
        ).first()
        step(
            "03. Persistência no Banco de Dados (SQLite)",
            passed=row is not None and row[0] == "Design Inicial",
        )
    finally:
        session.close()

    # 04. GET /creative
    r = _http("get", f"/api/chat/{chat_id}/creative/{comp_id}")
    data = r.json()
    step(
        "04. GET /creative/{id} -> Recuperação do JSON",
        passed=r.status_code == 200 and data.get("state") == mock_composition,
    )

    # 05. UI Validation (Playwright)
    print(f"\n{SEP}\n  INICIANDO VALIDAÇÃO UI COM PLAYWRIGHT\n{SEP}")
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=_args.headless)
        context = await browser.new_context()

        # Adicionar cookies para bypass de login
        await context.add_cookies(
            [
                {
                    "name": "access_token",
                    "value": TEST_STATE["token"],
                    "domain": "localhost",
                    "path": "/",
                    "httpOnly": True,
                    "sameSite": "Lax",
                },
                {
                    "name": "refresh_token",
                    "value": TEST_STATE["refresh_token"],
                    "domain": "localhost",
                    "path": "/",
                    "httpOnly": True,
                    "sameSite": "Lax",
                },
            ]
        )

        page = await context.new_page()

        try:
            # Ir para o chat específico
            target_url = f"{FRONTEND_URL}/chat/{chat_id}"
            print(f"  [UI] Navegando para {target_url}...")
            await page.goto(target_url, wait_until="networkidle")

            # 1. Verificar se o botão "Ativar Editor" existe
            # O botão tem o texto "Ativar Editor de Design"
            btn_selector = "button:has-text('Ativar Editor de Design')"
            await page.wait_for_selector(btn_selector, timeout=10000)
            btn_exists = await page.is_visible(btn_selector)
            step("05.1 UI: Botão 'Ativar Editor de Design' visível", passed=btn_exists)

            if btn_exists:
                # 2. Clicar no botão
                await page.click(btn_selector)
                print("  [UI] Botão clicado. Aguardando renderização do Canvas...")

                # 3. Verificar se o Stage do Konva aparece
                # O Konva adiciona uma div com class "konvajs-content"
                await page.wait_for_selector(".konvajs-content", timeout=5000)
                canvas_exists = await page.is_visible(".konvajs-content")
                step(
                    "05.2 UI: Renderização do Stage (KonvaJS) confirmada",
                    passed=canvas_exists,
                )

                # 4. Verificar se o texto de teste está no canvas (indiretamente via inspeção do estado se necessário)
                # Como é Canvas, não aparece no DOM, mas podemos verificar se a URL mudou ou se o componente mudou
                is_raw_tab = "preview_type=raw" in page.url or "tab=editor" in page.url
                step(
                    "05.3 UI: URL atualizada para modo editor",
                    passed=is_raw_tab,
                    detail=f"URL: {page.url}",
                )

        except Exception as e:
            step(
                "05. UI: Falha catastrófica no teste Playwright",
                passed=False,
                detail=str(e),
            )
        finally:
            await browser.close()


def cleanup():
    chat_id = TEST_STATE.get("chat_id")
    user_id = TEST_STATE.get("user_id")
    if not chat_id:
        return
    session = get_db_session()
    try:
        session.execute(
            text("DELETE FROM creative_compositions WHERE chat_id = :cid"),
            {"cid": chat_id},
        )
        session.execute(
            text("DELETE FROM assets WHERE chat_id = :cid"), {"cid": chat_id}
        )
        session.execute(
            text("DELETE FROM chats WHERE chat_id = :cid"), {"cid": chat_id}
        )
        session.execute(
            text("DELETE FROM access_tokens WHERE user_id = :uid"), {"uid": user_id}
        )
        session.execute(
            text("DELETE FROM refresh_tokens WHERE user_id = :uid"), {"uid": user_id}
        )
        session.execute(
            text("DELETE FROM users WHERE user_id = :uid"), {"uid": user_id}
        )
        session.commit()
        print(f"\n  [CLEAN] Dados de teste removidos.")
    finally:
        session.close()


async def run():
    await setup()
    try:
        await run_tests()
    finally:
        if CLEANUP:
            cleanup()

    print(f"\n{SEP}\nRESULTADO FINAL\n{SEP}")
    all_pass = True
    for r in results:
        icon = "[OK]  " if r["passed"] else "[FAIL]"
        print(f"  {icon} {r['label']}")
        if not r["passed"]:
            all_pass = False

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    asyncio.run(run())

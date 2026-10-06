import sys
import os
import json
import asyncio
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from sqlalchemy import create_engine, text, event
from sqlalchemy.orm import sessionmaker

# Configura PATH do backend
BACKEND_DIR = Path(__file__).parent.parent.parent.parent.absolute()
sys.path.insert(0, str(BACKEND_DIR))

# Carregar ENV do backend
from dotenv import load_dotenv

mvp_root = BACKEND_DIR.parent.parent
_mvp_env = mvp_root / ".env.development"
if _mvp_env.exists():
    load_dotenv(dotenv_path=str(_mvp_env), override=True)
    print(f"✅ Environment loaded: {_mvp_env}")

from App.Core.Settings.Settings import load_config
from App.Features.Auth.AuthService import get_auth_service, AuthConfig

# Configurações de URL
BACKEND_HOST = os.environ.get("BACKEND_HOST", "localhost")
BACKEND_PORT = os.environ.get("BACKEND_PORT", "4001")
FRONTEND_HOST = os.environ.get("FRONTEND_HOST", "localhost")
FRONTEND_PORT = os.environ.get("FRONTEND_PORT", "5082")
FRONTEND_URL = f"http://{FRONTEND_HOST}:{FRONTEND_PORT}"


# DB Helper
def get_session():
    # Usar o caminho absoluto confirmado pelo usuário
    db_path = Path(
        r"C:\Users\Lucas\z__LUCAS_CAMARGO__\PJ\ZERA\Operation\Products\MD70\App\mvp\services\backend\Data\Database\MD70.db"
    )

    if not db_path.exists():
        print(f"❌ DATABASE NOT FOUND AT: {db_path}")
        sys.exit(1)

    # No Windows, o prefixo para caminhos absolutos no SQLAlchemy sqlite é /// seguido do path
    engine = create_engine(f"sqlite:///{db_path}")
    return sessionmaker(bind=engine)()


async def run_refresh_validation():
    print("\n" + "=" * 70)
    print("🧪 REFRESH TOKEN VALIDATION & ROTATION TEST")
    print("=" * 70 + "\n")

    output_dir = Path(__file__).parent / "outputs"
    output_dir.mkdir(exist_ok=True)

    session = get_session()
    auth_service = get_auth_service()

    # 1. Criar usuário e cliente mock
    test_id = str(uuid.uuid4())[:8]
    user_id = f"refresh_user_{test_id}"
    client_id = f"refresh_client_{test_id}"
    email = f"refresh_{test_id}@test.local"

    print(f"👤 Creating test user: {email}")

    # Criar cliente e usuário no banco seguindo as constraints (type IN ('trial', 'login'))
    session.execute(
        text("INSERT INTO clients (client_id, plan_id) VALUES (:cid, 'free_early')"),
        {"cid": client_id},
    )

    # Gerar hash de senha real por segurança
    hashed_pw = auth_service.hash_password("test_password_123")

    session.execute(
        text(
            """
        INSERT INTO users (user_id, client_id, email, password, full_name, type, credits)
        VALUES (:uid, :cid, :email, :pw, 'Refresh Tester', 'login', 10.0)
    """
        ),
        {"uid": user_id, "cid": client_id, "email": email, "pw": hashed_pw},
    )
    session.commit()

    user_data = {
        "user_id": user_id,
        "client_id": client_id,
        "email": email,
        "full_name": "Refresh Tester",
        "role": "member",
    }

    # 2. Gerar Tokens
    print("🔑 Generating tokens...")

    # Access Token expirado (há 10 minutos)
    import jwt

    access_token_id = str(uuid.uuid4())
    access_payload = {
        "token_id": access_token_id,
        "user_id": user_id,
        "email": email,
        "client_id": client_id,
        "role": "member",
        "iat": datetime.utcnow() - timedelta(minutes=20),
        "exp": datetime.utcnow() - timedelta(minutes=10),
    }
    expired_access_token = jwt.encode(
        access_payload, auth_service.jwt_secret, algorithm="HS256"
    )

    # Salvar access token no banco (mesmo expirado) para passar na verificação de revogação inicial
    import hashlib

    token_hash = hashlib.sha256(expired_access_token.encode()).hexdigest()
    auth_service.db.save_access_token(
        session=session,
        token_id=access_token_id,
        user_id=user_id,
        client_id=client_id,
        token_hash=token_hash,
        expires_at=datetime.utcnow() - timedelta(minutes=10),
    )

    # Refresh Token válido
    refresh_data = auth_service.generate_refresh_token(user_data)
    valid_refresh_token = refresh_data["token"]
    initial_refresh_token_id = refresh_data["token_id"]

    print(f"✅ Tokens ready. Initial Refresh ID: {initial_refresh_token_id}")
    session.close()

    # 3. Playwright Automation
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=500)
        context = await browser.new_context()

        # Injetar Cookies
        await context.add_cookies(
            [
                {
                    "name": "access_token",
                    "value": expired_access_token,
                    "url": FRONTEND_URL,
                    "httpOnly": True,
                    "sameSite": "Lax",
                },
                {
                    "name": "refresh_token",
                    "value": valid_refresh_token,
                    "url": FRONTEND_URL,
                    "httpOnly": True,
                    "sameSite": "Lax",
                },
            ]
        )

        page = await context.new_page()

        # Monitorar requisições
        refresh_called = False
        new_refresh_token_detected = False

        async def handle_request(request):
            nonlocal refresh_called
            if "/api/auth/refresh" in request.url:
                print("🔄 Detected call to /api/auth/refresh")
                refresh_called = True

        async def handle_response(response):
            nonlocal new_refresh_token_detected
            if "/api/auth/refresh" in response.url and response.status == 200:
                print("✅ Refresh successful (200 OK)")
                # Verificar se o cookie refresh_token mudou (rotação)
                cookies = await context.cookies(FRONTEND_URL)
                for cookie in cookies:
                    if (
                        cookie["name"] == "refresh_token"
                        and cookie["value"] != valid_refresh_token
                    ):
                        print("♻️ Token Rotation Detected! New refresh token issued.")
                        new_refresh_token_detected = True

        page.on("request", handle_request)
        page.on("response", handle_response)

        print(f"🌐 Navigating to {FRONTEND_URL}/app...")
        try:
            await page.goto(
                f"{FRONTEND_URL}/app", wait_until="networkidle", timeout=30000
            )
            await page.wait_for_timeout(2000)  # Esperar logs e efeitos
        except Exception as e:
            print(f"⚠️ Navigation error: {e}")

        # 4. Resultados
        final_results = {
            "test_user": email,
            "expired_access_token_sent": True,
            "refresh_endpoint_called": refresh_called,
            "refresh_successful": refresh_called and page.url.endswith("/app"),
            "token_rotation_working": new_refresh_token_detected,
            "final_url": page.url,
        }

        print("\n" + "-" * 70)
        print("📊 TEST RESULTS:")
        print(json.dumps(final_results, indent=4))
        print("-" * 70 + "\n")

        with open(output_dir / "refresh_test_results.json", "w") as f:
            json.dump(final_results, f, indent=4)

        # Tirar print final
        await page.screenshot(path=output_dir / "final_screen.png")

        await browser.close()


if __name__ == "__main__":
    try:
        asyncio.run(run_refresh_validation())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"❌ Script failed: {e}")
        import traceback

        traceback.print_exc()

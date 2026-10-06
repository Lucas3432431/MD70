import sys
import os
import json
import asyncio
import uuid
import argparse
import requests
from datetime import datetime
from pathlib import Path
from sqlalchemy import create_engine, text
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

from App.Core.Settings.Settings import (
    GLOBAL_CONFIG,
    FRONTEND_HOST,
    FRONTEND_PORT,
    HOST,
    PORT,
    VITE_HTTP_PROTOCOL,
)
from App.Features.Auth.AuthService import get_auth_service
from Scripts.HealthCheck.health_check import run_health_check


def get_accessible_host(host):
    return "localhost" if not host or host == "0.0.0.0" else host


# Configurações
BACKEND_URL = f"{VITE_HTTP_PROTOCOL}://{get_accessible_host(HOST)}:{PORT}"
FRONTEND_URL = (
    f"{VITE_HTTP_PROTOCOL}://{get_accessible_host(FRONTEND_HOST)}:{FRONTEND_PORT}"
)
EXECUTION_UUID = str(uuid.uuid4())
DB_PATH = BACKEND_DIR / "Data" / "Database" / "MD70.db"
OUTPUT_DIR = Path(__file__).parent / "outputs"
DASHBOARD_PORT = 8765

_parser = argparse.ArgumentParser()
_parser.add_argument(
    "--start",
    choices=[
        "0",
        "bmc",
        "brandIdentity",
        "product",
        "copywriting",
        "cancel",
        "attachVariation",
        "copywritingNewProduct",
        "variationFlow",
        "competitorAnalysis",
        "validate-ui",
    ],
    default=None,
    help="Estágio de início: 0=do zero, bmc=com BMC criado, brandIdentity=BMC+Brand criados, product=BMC+Brand+Product criados, copywriting=BMC+Brand+Product+Copywriting criados, cancel=testa tool cancel, attachVariation=testa asset Modo 2, copywritingNewProduct=testa quiz criar novo produto, variationFlow=testa fluxo completo de variação A/B (quiz→vision→web-search→document→asset), competitorAnalysis=testa análise de concorrentes, validate-ui=testa visualização de gráficos e tabelas",
)
_parser.add_argument(
    "--no-monitoring",
    action="store_true",
    default=False,
    help="Desativa o polling do banco de dados e a geração do dashboard HTML",
)
_parser.add_argument(
    "--manual",
    action="store_true",
    default=False,
    help="Usa um usuário existente — pula limpeza do DB e criação de conta",
)
_parser.add_argument(
    "--email", default=None, help="Email do usuário existente (requer --manual)"
)
_parser.add_argument(
    "--password", default=None, help="Senha do usuário existente (requer --manual)"
)
_args, _ = _parser.parse_known_args()
START_STAGE = _args.start
NO_MONITORING = _args.no_monitoring
MANUAL_MODE = _args.manual
MANUAL_EMAIL = _args.email
MANUAL_PASSWORD = _args.password

if START_STAGE is None:
    print("❌ Informe o estágio de início com --start")
    print(
        "   Opções: --start 0 | --start bmc | --start brandIdentity | --start product | --start copywriting | --start cancel | --start attachVariation | --start copywritingNewProduct | --start variationFlow | --start competitorAnalysis | --start validate-ui"
    )
    sys.exit(1)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FIXTURE_MAP = {
    "bmc": FIXTURES_DIR / "StageSettedUp-BMC.json",
    "brandIdentity": FIXTURES_DIR / "StageSettedUp-BMC_N_BrandIdentity.json",
    "product": FIXTURES_DIR / "StageSettedUp-Product.json",
    "copywriting": FIXTURES_DIR / "StageSettedUp-Copywriting.json",
    "cancel": FIXTURES_DIR / "StageSettedUp-Cancel.json",
    "attachVariation": FIXTURES_DIR / "StageSettedUp-AttachVariation.json",
    "copywritingNewProduct": FIXTURES_DIR / "StageSettedUp-CopyrightingNewProduct.json",
    "variationFlow": FIXTURES_DIR / "StageSettedUp-VariationFlow.json",
    "competitorAnalysis": FIXTURES_DIR / "StageSettedUp-CompetitorAnalysis.json",
    "validate-ui": FIXTURES_DIR / "StageSettedUp-VisualizationUI.json",
}

state_container = {"chat_id": None}


def get_db_data(chat_id):
    if not chat_id:
        return [], [], "idle"
    try:
        engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"timeout": 10})
        session = sessionmaker(bind=engine)()

        # Obter user_id do chat
        user_sql = "SELECT user_id FROM chats WHERE chat_id = :cid"
        user_row = session.execute(text(user_sql), {"cid": chat_id}).fetchone()
        user_id = user_row[0] if user_row else None

        # Obter mensagens principais
        sql = "SELECT message_id, message_type as role, content, created_at FROM messages WHERE chat_id = :cid ORDER BY created_at ASC"
        msgs = session.execute(text(sql), {"cid": chat_id}).fetchall()
        msgs_list = [dict(row._mapping) for row in msgs]

        # Obter mensagens isoladas
        iso_sql = "SELECT isolated_message_id as message_id, role, content, created_at, tool_called, input_tokens, output_tokens FROM isolated_messages WHERE isolated_chat_id = :cid ORDER BY created_at ASC"
        iso_msgs = session.execute(text(iso_sql), {"cid": chat_id}).fetchall()
        iso_list = [dict(row._mapping) for row in iso_msgs]

        # Obter logs de créditos para este usuário
        logs_list = []
        if user_id:
            logs_sql = "SELECT credits_charged, reason, created_at FROM credits_logs WHERE user_id = :uid AND credits_charged > 0 ORDER BY created_at ASC"
            logs = session.execute(text(logs_sql), {"uid": user_id}).fetchall()
            logs_list = [dict(row._mapping) for row in logs]

        # Tentar associar custos às mensagens (Heurística baseada em Reason e Tempo)
        # Para isolated_messages é mais fácil pois o reason contém o nome da tool ou tokens
        for im in iso_list:
            cost = 0.0
            t_called = im.get("tool_called")
            i_tokens = im.get("input_tokens") or 0
            o_tokens = im.get("output_tokens") or 0

            # Match por tool ou por tokens no reason
            for log in logs_list:
                reason = log.get("reason", "")
                if t_called and t_called.lower() in reason.lower():
                    cost += log.get("credits_charged", 0)
                elif (
                    i_tokens > 0 and str(i_tokens) in reason and str(o_tokens) in reason
                ):
                    cost += log.get("credits_charged", 0)

            im["credits_cost"] = cost

        # Para as mensagens principais, somamos os custos das isoladas que as originaram (mesmo message_id)
        iso_map = {m["message_id"]: m.get("credits_cost", 0) for m in iso_list}
        for m in msgs_list:
            m["credits_cost"] = iso_map.get(m["message_id"], 0)

        job_sql = "SELECT status FROM jobs WHERE chat_id = :cid ORDER BY created_at DESC LIMIT 1"
        job_row = session.execute(text(job_sql), {"cid": chat_id}).fetchone()
        job_status = dict(job_row._mapping).get("status", "idle") if job_row else "idle"

        session.close()
        return msgs_list, iso_list, job_status
    except Exception as e:
        print(f"⚠️ [SQL ERROR] {e}", flush=True)
        import traceback

        traceback.print_exc()
        return [], [], "idle"


def generate_html_dashboard(msgs, iso_msgs, status):
    status_color = (
        "#4ec9b0"
        if status == "running"
        else "#ce9178"
        if status == "completed"
        else "#f44747"
    )

    total_main_credits = sum([m.get("credits_cost") or 0 for m in msgs])
    total_iso_credits = sum([m.get("credits_cost") or 0 for m in iso_msgs])

    def format_msg(m):
        cost = m.get("credits_cost") or 0
        cost_html = (
            f'<div style="color: #dcdcaa; font-size: 11px; margin-bottom: 4px; font-weight: bold;">💰 Custo: {cost:.6f} créditos</div>'
            if cost > 0
            else ""
        )
        return f"""
        <div class="msg-entry">
            <span class="timestamp">[{m.get("created_at")}]</span>
            <b class="role-{m.get("role")}">{m.get("role")}</b>
            {cost_html}
            <pre>{m.get("content")}</pre>
        </div>
        """

    return f"""
    <html>
    <head>
        <title>MD70 Monitor - {status.upper()}</title>
        <style>
            body {{ background: #1e1e1e; color: #d4d4d4; font-family: 'Consolas', monospace; margin: 0; padding: 20px; }}
            .container {{ display: flex; gap: 20px; }}
            .panel {{ flex: 1; border: 1px solid #333; border-radius: 8px; background: #252526; overflow: hidden; }}
            .header {{ background: #333; padding: 10px; font-weight: bold; color: #569cd6; border-bottom: 1px solid #444; display: flex; justify-content: space-between; align-items: center; }}
            .status-tag {{ color: {status_color}; text-transform: uppercase; font-size: 14px; margin-left: 10px; }}
            .content {{ padding: 15px; height: 82vh; overflow-y: auto; }}
            pre {{ white-space: pre-wrap; word-break: break-all; font-size: 12px; line-height: 1.4; color: #bbb; background: #1a1a1a; padding: 10px; border-radius: 4px; border: 1px solid #333; }}
            .msg-entry {{ margin-bottom: 25px; border-left: 3px solid #444; padding-left: 15px; }}
            .role-user {{ color: #4ec9b0; font-size: 13px; text-transform: uppercase; }}
            .role-assistant {{ color: #ce9178; font-size: 13px; text-transform: uppercase; }}
            .role-tool {{ color: #569cd6; font-size: 13px; text-transform: uppercase; }}
            .timestamp {{ color: #6a9955; font-size: 10px; opacity: 0.7; display: block; margin-bottom: 5px; }}
            .sync-btn {{ background: #333; border: 1px solid #444; color: #d4d4d4; padding: 6px 16px; border-radius: 20px; cursor: pointer; font-size: 13px; font-family: inherit; }}
            .sync-btn:hover {{ background: #444; }}
            .total-credits {{ font-size: 12px; color: #dcdcaa; }}
        </style>
    </head>
    <body>
        <div class="header" style="background: transparent; border: 0; padding: 0 0 15px 0;">
            <div style="display: flex; flex-direction: column;">
                <span style="font-size: 18px;">🚀 Cockpit UUID: {EXECUTION_UUID}</span>
                <span style="font-size: 11px; color: #777;">Chat: {state_container['chat_id']}</span>
            </div>

            <div style="display: flex; align-items: center; gap: 20px;">
                <button class="sync-btn" onclick="location.reload()">🔄 Sync</button>
                <span class="status-tag">Job: {status}</span>
            </div>
        </div>

        <div class="container">
            <div class="panel">
                <div class="header">
                    <span>MAIN MESSAGES ({len(msgs)})</span>
                    <span class="total-credits">Total: {total_main_credits:.6f} 🪙</span>
                </div>
                <div class="content">
                    {"".join([format_msg(m) for m in msgs])}
                </div>
            </div>
            <div class="panel">
                <div class="header">
                    <span>ISOLATED MESSAGES ({len(iso_msgs)})</span>
                    <span class="total-credits">Total: {total_iso_credits:.6f} 🪙</span>
                </div>
                <div class="content">
                    {"".join([format_msg(m) for m in iso_msgs])}
                </div>
            </div>
        </div>
    </body>
    </html>
    """


async def dashboard_server_handler(reader, writer):
    try:
        await reader.read(4096)
    except Exception:
        pass

    chat_id = state_container["chat_id"]
    msgs, iso_msgs, status = get_db_data(chat_id)
    print(
        f"📊 Dashboard sync: {len(msgs)} main, {len(iso_msgs)} isolated. Status: {status}",
        flush=True,
    )

    html = generate_html_dashboard(msgs, iso_msgs, status)
    encoded = html.encode("utf-8")
    response = (
        f"HTTP/1.1 200 OK\r\n"
        f"Content-Type: text/html; charset=utf-8\r\n"
        f"Content-Length: {len(encoded)}\r\n"
        f"Connection: close\r\n"
        f"\r\n"
    ).encode("utf-8") + encoded

    try:
        writer.write(response)
        await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


def seed_fixture(
    user_id: str, client_id: str, chat_name: str, fixture_path: Path
) -> str:
    """Cria chat, isolated_chat, isolated_messages e documents a partir de um fixture.
    Retorna o chat_id criado."""
    with open(fixture_path, encoding="utf-8") as f:
        fixture = json.load(f)

    docs = fixture.get("documents", [])
    iso_msgs = fixture.get("isolated_messages", [])

    chat_id = str(uuid.uuid4())
    engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"timeout": 10})
    session = sessionmaker(bind=engine)()
    try:
        # 1. chat principal
        session.execute(
            text(
                """
            INSERT INTO chats (chat_id, user_id, chat_name, status, created_at, updated_at)
            VALUES (:cid, :uid, :name, 'active', datetime('now'), datetime('now'))
        """
            ),
            {"cid": chat_id, "uid": user_id, "name": chat_name},
        )

        # 2. isolated_chat
        session.execute(
            text(
                """
            INSERT INTO isolated_chat (chat_id, agent_id, created_at, updated_at)
            VALUES (:cid, 'orchestrator-global', datetime('now'), datetime('now'))
        """
            ),
            {"cid": chat_id},
        )

        # 3. isolated_messages — pular role="system" para que o MessageProcessor gere dinamicamente
        for msg in iso_msgs:
            if msg.get("role") == "system":
                continue
            content = msg["content"]
            session.execute(
                text(
                    """
                INSERT INTO isolated_messages (
                    isolated_chat_id, isolated_message_id, tool_call_id, tool_called,
                    tool_call_type, fk_tool_id, agent_id, agent, role, content,
                    input_tokens, output_tokens, type, context_window, provider_type,
                    created_at, updated_at
                ) VALUES (
                    :isolated_chat_id, :isolated_message_id, :tool_call_id, :tool_called,
                    :tool_call_type, :fk_tool_id, :agent_id, :agent, :role, :content,
                    :input_tokens, :output_tokens, :type, :context_window, :provider_type,
                    :created_at, datetime('now')
                )
            """
                ),
                {
                    "isolated_chat_id": chat_id,
                    "isolated_message_id": str(uuid.uuid4()),
                    "tool_call_id": msg.get("tool_call_id"),
                    "tool_called": msg.get("tool_called"),
                    "tool_call_type": msg.get("tool_call_type"),
                    "fk_tool_id": msg.get("fk_tool_id"),
                    "agent_id": msg.get("agent_id", "orchestrator-global"),
                    "agent": msg.get("agent", "orchestrator"),
                    "role": msg["role"],
                    "content": (
                        json.dumps(msg["content"], ensure_ascii=False)
                        if isinstance(content, (dict, list))
                        else content
                    ),
                    "input_tokens": msg.get("input_tokens", 0),
                    "output_tokens": msg.get("output_tokens", 0),
                    "type": msg.get("type", "message"),
                    "context_window": msg.get("context_window", 1),
                    "provider_type": msg.get("provider_type", "main"),
                    "created_at": msg.get("created_at", datetime.now().isoformat()),
                },
            )

        # 4. documents
        for doc in docs:
            session.execute(
                text(
                    """
                INSERT INTO documents (document_id, chat_id, user_id, client_id, title, content, extension, tool_type, created_at, updated_at)
                VALUES (:doc_id, :chat_id, :user_id, :client_id, :title, :content, 'json', :tool_type, datetime('now'), datetime('now'))
            """
                ),
                {
                    "doc_id": str(uuid.uuid4()),
                    "chat_id": chat_id,
                    "user_id": user_id,
                    "client_id": client_id,
                    "title": doc["title"],
                    "content": json.dumps(doc["content"], ensure_ascii=False),
                    "tool_type": doc["tool_type"],
                },
            )

        session.commit()
        print(
            f"✅ Fixture '{fixture_path.name}': {len(docs)} doc(s), {len(iso_msgs)} msg(s) | chat_id={chat_id}"
        )
    finally:
        session.close()

    return chat_id


async def run_full_flow():
    print(f"🚀 COCKPIT START - {EXECUTION_UUID}  [--start {START_STAGE}]")
    run_health_check()
    OUTPUT_DIR.mkdir(exist_ok=True)

    auth_service = get_auth_service()

    if MANUAL_MODE:
        email = MANUAL_EMAIL or input("📧 Email: ").strip()
        password = MANUAL_PASSWORD or input("🔑 Senha: ").strip()

        ok, user_data, err = auth_service.authenticate_user(
            email=email,
            password=password,
            fingerprint_id="manual-mode",
            fingerprint_components={},
            ip_address="127.0.0.1",
        )
        if not ok:
            print(f"❌ Autenticação falhou: {err}")
            sys.exit(1)

        user_id = user_data["user_id"]
        client_id = user_data["client_id"]
        print(f"✅ Login manual: {email} | user_id={user_id} | client_id={client_id}")

    else:
        # Limpar tabelas para evitar conflitos de dados remanescentes
        try:
            engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"timeout": 10})
            session = sessionmaker(bind=engine)()

            tables_to_clear = [
                "users",
                "clients",
                "chats",
                "messages",
                "isolated_chat",
                "isolated_messages",
                "billing_subscriptions",
                "cards",
                "payments",
                "credits_logs",
                "usage",
                "sessions",
                "refresh_tokens",
                "access_tokens",
                "tasks",
                "jobs",
                "assets",
                "documents",
            ]

            for table in tables_to_clear:
                try:
                    session.execute(text(f"DELETE FROM {table}"))
                except Exception as te:
                    print(f"  - Tabela {table} ignorada (pode não existir): {te}")

            session.commit()
            session.close()
            print(
                "🧹 Banco de dados limpo com sucesso (Tabelas: "
                + ", ".join(tables_to_clear)
                + ")"
            )
        except Exception as e:
            print(f"⚠️ Erro ao limpar tabelas: {e}")

        test_id = EXECUTION_UUID[:8]
        email = f"test.{test_id}@prox.ai"
        password = f"Test@{test_id}!"

        ok, user_data, err = auth_service.register_user(
            email=email,
            password=password,
            fingerprint_id=f"fp_{test_id}",
            fingerprint_components={},
            ip_address="127.0.0.1",
        )
        if not ok:
            print(f"❌ Falha ao criar usuário de teste: {err}")
            sys.exit(1)

        user_id = user_data["user_id"]
        client_id = user_data["client_id"]
        print(f"✅ Usuário criado: {email} | user_id={user_id} | client_id={client_id}")

        # Elevar plano para pro para passar na checagem de /api/new-chat
        try:
            engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"timeout": 10})
            session = sessionmaker(bind=engine)()
            row = session.execute(
                text("SELECT plan_id FROM plans WHERE plan_type = 'pro' LIMIT 1")
            ).fetchone()
            pro_plan_id = row[0] if row else None
            if pro_plan_id:
                session.execute(
                    text("UPDATE clients SET plan_id = :pid WHERE client_id = :cid"),
                    {"pid": pro_plan_id, "cid": client_id},
                )
                session.commit()
                print(f"✅ Plano atualizado para pro: {pro_plan_id}")
            session.close()
        except Exception as e:
            print(f"⚠️ Erro ao atualizar plano: {e}")

    # Validar créditos no DB antes de abrir o Playwright
    MIN_CREDITS = 5
    try:
        engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"timeout": 10})
        session = sessionmaker(bind=engine)()
        row = session.execute(
            text("SELECT credits FROM users WHERE user_id = :uid"), {"uid": user_id}
        ).fetchone()
        session.close()
        credits = float(row[0]) if row and row[0] is not None else 0.0
        if credits < MIN_CREDITS:
            print(
                f"❌ Usuário com apenas {credits} créditos (mínimo: {MIN_CREDITS}). Abortando."
            )
            sys.exit(1)
        print(f"✅ Créditos validados: {credits} (mínimo exigido: {MIN_CREDITS})")
    except Exception as e:
        print(f"❌ Erro ao validar créditos no DB: {e}")
        sys.exit(1)

    full_name = user_data.get("full_name", "Test User") if MANUAL_MODE else "Test User"
    user_payload = {
        "user_id": user_id,
        "client_id": client_id,
        "email": email,
        "role": user_data.get("role", "member"),
        "full_name": full_name,
    }
    access_token = auth_service.generate_access_token(user_payload, save_to_db=True)
    refresh_token = auth_service.generate_refresh_token(user_payload, save_to_db=True)[
        "token"
    ]
    print(f"✅ Tokens gerados | access={access_token[:30]}...")

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        is_headless = os.getenv("HEADLESS", "false").lower() == "true"
        browser = await p.chromium.launch(
            headless=is_headless, args=["--start-maximized"] if not is_headless else []
        )
        context = await browser.new_context(
            no_viewport=True if not is_headless else False
        )

        # Configurar cookies com domínio localhost para garantir recepção correta
        await context.add_cookies(
            [
                {
                    "name": "access_token",
                    "value": access_token,
                    "domain": "localhost",
                    "path": "/",
                    "httpOnly": True,
                    "sameSite": "Lax",
                },
                {
                    "name": "refresh_token",
                    "value": refresh_token,
                    "domain": "localhost",
                    "path": "/",
                    "httpOnly": True,
                    "sameSite": "Lax",
                },
            ]
        )

        page = await context.new_page()

        _dashboard_server = None
        if not NO_MONITORING:
            _dashboard_server = await asyncio.start_server(
                dashboard_server_handler, "127.0.0.1", DASHBOARD_PORT
            )
            print(f"📊 Dashboard: http://localhost:{DASHBOARD_PORT}/", flush=True)

        dash_page = await context.new_page() if not NO_MONITORING else None

        if START_STAGE == "0":
            await page.goto(f"{FRONTEND_URL}/app", wait_until="networkidle")
            print(f"🌐 URL após goto: {page.url}", flush=True)

            prompt = "Me ajude a estruturar o meu marketing para o site http://localhost:5082/. E gere os criativos da minha primeira semana por favor"
            textarea = page.locator("textarea").first
            await textarea.wait_for(state="visible")
            await textarea.fill(prompt)

            if not NO_MONITORING:
                await dash_page.goto(f"http://localhost:{DASHBOARD_PORT}/")
            await page.bring_to_front()

            await textarea.press("Enter")

            await page.wait_for_url("**/chat/**", timeout=30000)
            raw_chat_id = page.url.split("/chat/")[1].split("?")[0].rstrip("/")
            state_container["chat_id"] = raw_chat_id
            print(f"🎯 Chat ID Extracted: {state_container['chat_id']}")

        else:
            fixture_path = FIXTURE_MAP.get(START_STAGE)
            if fixture_path and fixture_path.exists():
                seeded_chat_id = seed_fixture(
                    user_id, client_id, f"Test [{START_STAGE}] {test_id}", fixture_path
                )
            else:
                print(
                    f"⚠️  Fixture para '--start {START_STAGE}' ainda não criado. Criando chat vazio."
                )
                seeded_chat_id = str(uuid.uuid4())
                engine = create_engine(
                    f"sqlite:///{DB_PATH}", connect_args={"timeout": 10}
                )
                session = sessionmaker(bind=engine)()
                try:
                    session.execute(
                        text(
                            """
                        INSERT INTO chats (chat_id, user_id, chat_name, status, created_at, updated_at)
                        VALUES (:cid, :uid, :name, 'active', datetime('now'), datetime('now'))
                    """
                        ),
                        {
                            "cid": seeded_chat_id,
                            "uid": user_id,
                            "name": f"Test [{START_STAGE}] {test_id}",
                        },
                    )
                    session.execute(
                        text(
                            """
                        INSERT INTO isolated_chat (chat_id, agent_id, created_at, updated_at)
                        VALUES (:cid, 'orchestrator-global', datetime('now'), datetime('now'))
                    """
                        ),
                        {"cid": seeded_chat_id},
                    )
                    session.commit()
                finally:
                    session.close()

            state_container["chat_id"] = seeded_chat_id
            print(f"🎯 Chat ID (seeded): {seeded_chat_id}")

            await page.goto(
                f"{FRONTEND_URL}/chat/{seeded_chat_id}", wait_until="networkidle"
            )
            print(f"🌐 URL após goto: {page.url}", flush=True)

            if not NO_MONITORING:
                await dash_page.goto(f"http://localhost:{DASHBOARD_PORT}/")
            await page.bring_to_front()

            # Enviar mensagem inicial conforme o estágio
            if START_STAGE == "copywriting":
                prompt = "Gere os assets do documento de copywriting existente. Não crie nem altere nenhum documento — apenas execute asset() com o document_id do copywriting já salvo."
                textarea = page.locator("textarea").first
                await textarea.wait_for(state="visible")
                await textarea.fill(prompt)
                await textarea.press("Enter")
                print(f"💬 Mensagem enviada: '{prompt}'")

            elif START_STAGE == "cancel":
                prompt = "carregue skill copywriting, execute tool cancel e web-search fetch de http://localhost:8081/"
                textarea = page.locator("textarea").first
                await textarea.wait_for(state="visible")
                await textarea.fill(prompt)
                await textarea.press("Enter")
                print(f"💬 Mensagem enviada: '{prompt}'")

            elif START_STAGE == "attachVariation":
                prompt = "Me ajude a gerar variações do meu criativo"
                textarea = page.locator("textarea").first
                await textarea.wait_for(state="visible")
                await textarea.fill(prompt)
                await textarea.press("Enter")
                print(f"💬 Mensagem enviada: '{prompt}'")

            elif START_STAGE == "copywritingNewProduct":
                prompt = "Quero criar um copywriting para um novo produto que ainda não está cadastrado. Me ajude."
                textarea = page.locator("textarea").first
                await textarea.wait_for(state="visible")
                await textarea.fill(prompt)
                await textarea.press("Enter")
                print(f"💬 Mensagem enviada: '{prompt}'")

            elif START_STAGE == "variationFlow":
                prompt = (
                    "Quero criar variações A/B de um criativo. "
                    "Não tenho nenhum documento cadastrado ainda — quero testar o fluxo de variação direto com uma imagem de referência. "
                    "Use essa URL como referência: https://prox.com/imgs/Logo1_InvisibleBackground.png"
                )
                textarea = page.locator("textarea").first
                await textarea.wait_for(state="visible")
                await textarea.fill(prompt)
                await textarea.press("Enter")
                print(f"💬 Mensagem enviada: '{prompt}'")

            elif START_STAGE == "competitorAnalysis":
                prompt = (
                    "Quero analisar os criativos e posicionamento dos concorrentes do MD70. "
                    "Me ajude a fazer um benchmark competitivo."
                )
                textarea = page.locator("textarea").first
                await textarea.wait_for(state="visible")
                await textarea.fill(prompt)
                await textarea.press("Enter")
                print(f"💬 Mensagem enviada: '{prompt}'")

            elif START_STAGE == "validate-ui":
                prompt = "Por favor, gere um gráfico de barras mock sobre crescimento de leads e uma tabela CSV mock com um cronograma de postagens detalhado com 30 linhas para eu validar a interface e o scroll."
                textarea = page.locator("textarea").first
                await textarea.wait_for(state="visible")
                await textarea.fill(prompt)
                await textarea.press("Enter")
                print(f"💬 Mensagem enviada: '{prompt}'")

        print("\n🔥 SYSTEM ACTIVE. Monitor UI in the second tab. Press Ctrl+C to exit.")
        try:
            # Manter o script rodando indefinidamente até interrupção manual
            while True:
                await asyncio.sleep(10)
        except (KeyboardInterrupt, asyncio.CancelledError):
            print("\n👋 Encerrando por solicitação do usuário...")
        except Exception as e:
            print(f"❌ Erro durante acompanhamento: {e}")
        finally:
            if _dashboard_server:
                _dashboard_server.close()
            await browser.close()
            print("👋 Browser fechado. Fim da validação.")


if __name__ == "__main__":
    asyncio.run(run_full_flow())

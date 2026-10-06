from typing import Dict, Any
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel
from openai import OpenAI
from pathlib import Path
import subprocess
import platform
import os
import sys
import json

from App.Core.Settings.Settings import (
    load_config,
    validate_config,
    set_public_url_online,
    GOOGLE_AUTH_CLIENT_ID,
    GOOGLE_AUTH_CLIENT_SECRET,
)

BASE_DIR = Path(__file__).parent.parent.parent.parent.parent
from App.Core.Logs import info, debug, warning, error  # MOVER ESTA LINHA PARA CIMA!

from App.Core.Crunch.Storage.MediaCompressor import MediaCompressor
from App.Core.Crunch.Storage.StorageManager import StorageManager
from App.Core.Services.Subscription.EncryptionUtil import validate_encryption_key

from App.Features.Llm.LLMClient import LLMClient
from App.Features.Llm.APIKeyRotator import APIKeyRotator

try:
    from App.Features.Chat import ChatManager
except ImportError as e:
    warning(f"Failed to import ChatManager: {e}")
    ChatManager = None

try:
    from App.Features.Chat.MessageProcessor import MessageProcessor
except ImportError as e:
    warning(f"Failed to import MessageProcessor: {e}")
    MessageProcessor = None


# ToolFacilitator - Using minimal stub (Tools/Tasks/Plan module not available)
class ToolFacilitator:
    """Minimal stub for ToolFacilitator when Tools module is not available."""

    def __init__(self, *args, **kwargs):
        pass

    def set_agent_session_manager(self, *args, **kwargs):
        """Stub method for compatibility."""
        pass


from App.Features.Agents import AgentsManager

# mcp_manager importado lazily em setup_app() para evitar circular import
# (Core → MCPClientManager → Dependencies → AppSetup → MCPClientManager)

# CORREÇÃO SIMPLIFICADA: Importação direta
try:
    # Primeiro tenta importar do novo módulo modular
    from App.Core.Crunch import init_db, DatabaseManager, get_db_manager

    debug_import = "Import from new modular Crunch structure"
except ImportError as import_err:
    # Se falhar, verifica se o arquivo antigo ainda existe
    try:
        # Verifica se o arquivo Crunch.py existe no mesmo diretório
        crunch_path = Path(__file__).parent.parent.parent / "Crunch" / "Crunch.py"
        if crunch_path.exists():
            # Adiciona o diretório ao sys.path temporariamente
            import sys

            sys.path.insert(0, str(crunch_path.parent))
            from Crunch import DatabaseManager, init_db

            get_db_manager = lambda: DatabaseManager()
            debug_import = f"Import from legacy Crunch.py at {crunch_path}"
        else:
            # Se não existir, cria stubs
            raise ImportError(f"Crunch module not found. Path checked: {crunch_path}")
    except Exception as e:
        # Se ambos falharem, criar stubs
        error(f"Failed to import Crunch modules: {import_err}. Also tried: {e}")

        class DatabaseManager:
            """Stub DatabaseManager for compatibility."""

            @staticmethod
            def get_session():
                return None

            @staticmethod
            def create_chat(session, chat_data):
                return None

        def init_db():
            error("Warning: init_db stub called - database functionality disabled")
            return True

        def get_db_manager():
            return DatabaseManager()

        debug_import = "Using stubs - Crunch not available"

from App.Features.Auth import AuthManager, init_auth_service
from App.Features.Credits.PlanManager import init_plan_manager
from App.Core.Queues import initialize_queue_system, get_queue_system

from .Dependencies import COMPONENTS

# ========================================================================
# MODELOS
# ========================================================================


class ExecuteCommandRequest(BaseModel):
    """Modelo para requisição de execução de comando."""

    path: str
    command: str


# ========================================================================
# APLICAÇÃO FASTAPI
# ========================================================================

app = FastAPI(
    title="Voicebot API",
    description="API para sistema de automação com múltiplos agentes de IA",
    version="1.0.0",
)

# ========================================================================
# ADICIONAR MIDDLEWARE DE CRIPTOGRAFIA
# ========================================================================
# Descriptografa requisições criptografadas do frontend (POST/PUT/PATCH)
# Criptografa responses automaticamente com AES-256
# NOTA: Desabilitado temporariamente - usar descriptografia manual nas rotas
# Middleware de criptografia foi removido para simplificação


MIN_LLM_BALANCE_USD = 5.0


def _check_llm_balances(config: dict) -> None:
    """
    Verifica saldo dos providers LLM via sandbox (que tem acesso à internet).
    Loga warning e envia alerta se saldo < $5.00, mas não bloqueia o startup.
    """
    import requests as _req
    import json as _json

    sandbox_url = os.environ.get("SANDBOX_URL", "").rstrip("/")
    if not sandbox_url:
        warning(
            "[LLM Balance] SANDBOX_URL não definida — verificação de saldo ignorada."
        )
        return

    primary_ai = config.get("ai", "").lower()
    llm_rotator = config.get("llm_rotator", {})
    providers_cfg = llm_rotator.get("providers", {})

    def _get_keys(provider: str):
        raw = providers_cfg.get(provider, {}).get("keys", [])
        keys = []
        for entry in raw:
            if isinstance(entry, dict):
                keys.append(entry.get("key", ""))
            elif isinstance(entry, str):
                keys.append(entry)
        if not keys:
            direct = config.get(f"{provider}_api_key") or ""
            if direct:
                keys = [direct]
        return [k for k in keys if k]

    def _sandbox_exec(command: str) -> dict:
        resp = _req.post(
            f"{sandbox_url}/execute",
            json={"command": command, "user_id": "system"},
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()

    # --- DeepSeek ---
    deepseek_keys = _get_keys("deepseek")
    if deepseek_keys:
        try:
            key = deepseek_keys[0]
            result = _sandbox_exec(
                f'curl -s "https://api.deepseek.com/user/balance" -H "Authorization: Bearer {key}"'
            )
            stdout = result.get("stdout", "")
            data = _json.loads(stdout)
            balance_usd = 0.0
            for b in data.get("balance_infos", []):
                if b.get("currency") == "USD":
                    balance_usd = float(b.get("total_balance", 0))
                    break
            if balance_usd < MIN_LLM_BALANCE_USD:
                warning(
                    f"[LLM Balance] ⚠️ DeepSeek: ${balance_usd:.2f} (abaixo de ${MIN_LLM_BALANCE_USD:.2f}) — adicione créditos em breve."
                )
                try:
                    from App.Core.Services.AdminEmail import admin_email_service

                    admin_email_service.send_critical_alert(
                        "LLM SALDO BAIXO - DeepSeek",
                        f"Saldo DeepSeek está em ${balance_usd:.2f}, abaixo do mínimo de ${MIN_LLM_BALANCE_USD:.2f}.\nAdicione créditos para evitar interrupções.",
                    )
                except Exception:
                    pass
            else:
                info(f"[LLM Balance] ✅ DeepSeek: ${balance_usd:.2f}")
        except Exception as e:
            warning(
                f"[LLM Balance] Não foi possível checar saldo DeepSeek via sandbox: {e}"
            )

    # --- OpenAI (sem endpoint de saldo público — valida se chave responde 200) ---
    openai_keys = _get_keys("openai")
    if openai_keys:
        try:
            key = openai_keys[0]
            result = _sandbox_exec(
                f'curl -s -o /dev/null -w "%{{http_code}}" "https://api.openai.com/v1/models" -H "Authorization: Bearer {key}"'
            )
            http_code = result.get("stdout", "").strip()
            if http_code == "200":
                info("[LLM Balance] ✅ OpenAI: chave válida")
            elif http_code == "401":
                warning("[LLM Balance] ⚠️ OpenAI: chave inválida ou revogada (401).")
                try:
                    from App.Core.Services.AdminEmail import admin_email_service

                    admin_email_service.send_critical_alert(
                        "LLM CHAVE INVÁLIDA - OpenAI",
                        "A chave OpenAI retornou 401. Verifique OPENAI_API_KEY no .env.",
                    )
                except Exception:
                    pass
            else:
                warning(
                    f"[LLM Balance] OpenAI retornou HTTP {http_code} — verificação inconclusiva."
                )
        except Exception as e:
            warning(
                f"[LLM Balance] Não foi possível validar chave OpenAI via sandbox: {e}"
            )
    else:
        warning(
            "[LLM Balance] ⚠️ OpenAI: nenhuma chave configurada (OPENAI_API_KEY ausente)"
        )


_GOOGLE_OAUTH_PROVIDERS = {
    "google-drive",
    "google-calendar",
    "google-tasks",
    "gmail",
    "google-analytics",
    "google-ads",
}
_META_OAUTH_PROVIDERS = {"meta-ads", "instagram"}
_GITHUB_PROVIDERS = {"github"}


async def _check_oauth_integrations(db_manager) -> None:
    """Verifica se tokens OAuth de todas as integrações ativas estão válidos.
    Envia alerta padrão para qualquer token revogado ou expirado.
    Não bloqueia o startup — apenas loga e alerta.
    """
    import httpx as _httpx
    import json as _json

    try:
        from App.Core.Crunch.TablesSQL.Models import IntegrationMCP
        from App.Core.Crunch.TablesSQL.DBCryptographyManager import (
            DBCryptographyManager,
        )

        def _load_all(session):
            rows = (
                session.query(IntegrationMCP)
                .filter(IntegrationMCP.is_active == True)
                .all()
            )
            # Extrai atributos para dicts enquanto a session ainda está aberta,
            # evitando DetachedInstanceError ao acessar fora da transação.
            return [
                {
                    "env_vars": row.env_vars,
                    "provider": row.provider,
                    "client_id": row.client_id,
                }
                for row in rows
            ]

        records = db_manager.execute_transaction(_load_all)
    except Exception as exc:
        warning(f"[IntegrationCheck] Não foi possível carregar integrações: {exc}")
        return

    def _decrypt_env(raw) -> dict:
        if isinstance(raw, dict) and "_enc" in raw:
            try:
                decrypted = DBCryptographyManager.decrypt_field(raw["_enc"])
                return _json.loads(decrypted) if decrypted else {}
            except Exception:
                return {}
        return raw if isinstance(raw, dict) else {}

    revoked: list[tuple[str, str, str]] = []  # (client_id, provider, reason)

    try:
        async with _httpx.AsyncClient(timeout=10.0) as http:
            for rec in records:
                env = _decrypt_env(rec["env_vars"])
                provider = rec["provider"]
                client_id = rec["client_id"]

                try:
                    if provider in _GOOGLE_OAUTH_PROVIDERS:
                        refresh_token = env.get("GOOGLE_REFRESH_TOKEN", "")
                        if not refresh_token or not GOOGLE_AUTH_CLIENT_ID:
                            continue
                        r = await http.post(
                            "https://oauth2.googleapis.com/token",
                            data={
                                "grant_type": "refresh_token",
                                "refresh_token": refresh_token,
                                "client_id": GOOGLE_AUTH_CLIENT_ID,
                                "client_secret": GOOGLE_AUTH_CLIENT_SECRET,
                            },
                        )
                        if r.status_code != 200:
                            err_code = r.json().get("error", r.text[:80])
                            revoked.append(
                                (client_id, provider, f"token inválido: {err_code}")
                            )
                        else:
                            debug(f"[IntegrationCheck] ✅ {provider} client={client_id}")

                    elif provider in _META_OAUTH_PROVIDERS:
                        token = env.get("META_ACCESS_TOKEN", "") or env.get(
                            "INSTAGRAM_ACCESS_TOKEN", ""
                        )
                        if not token:
                            continue
                        r = await http.get(
                            "https://graph.facebook.com/me",
                            params={"access_token": token, "fields": "id"},
                        )
                        data = r.json()
                        if "error" in data or r.status_code not in (200, 400):
                            err_msg = (
                                data.get("error", {}).get("message", r.text[:80])
                                if isinstance(data, dict)
                                else r.text[:80]
                            )
                            revoked.append(
                                (client_id, provider, f"token inválido: {err_msg}")
                            )
                        else:
                            debug(f"[IntegrationCheck] ✅ {provider} client={client_id}")

                    elif provider in _GITHUB_PROVIDERS:
                        token = env.get("GITHUB_TOKEN", "") or env.get(
                            "GITHUB_PERSONAL_ACCESS_TOKEN", ""
                        )
                        if not token:
                            continue
                        r = await http.get(
                            "https://api.github.com/user",
                            headers={
                                "Authorization": f"Bearer {token}",
                                "Accept": "application/vnd.github+json",
                            },
                        )
                        if r.status_code == 401:
                            revoked.append(
                                (client_id, provider, "token revogado (401)")
                            )
                        else:
                            debug(f"[IntegrationCheck] ✅ {provider} client={client_id}")

                except Exception as exc_inner:
                    debug(
                        f"[IntegrationCheck] Erro ao verificar {provider} client={client_id}: {exc_inner}"
                    )

    except Exception as exc:
        warning(f"[IntegrationCheck] Erro geral na verificação: {exc}")
        return

    if revoked:
        try:
            from App.Core.Services.AdminEmail import admin_email_service

            for client_id, provider, reason in revoked:
                warning(
                    f"[IntegrationCheck] ⚠️ Token revogado — provider={provider} client={client_id}: {reason}"
                )
                admin_email_service.send_critical_alert(
                    f"TOKEN REVOGADO — {provider.upper()}",
                    f"Provider: {provider}\nCliente: {client_id}\nMotivo: {reason}\n\nAção necessária: o usuário deve reconectar a integração em Configurações → Conectores.",
                )
        except Exception as exc:
            warning(f"[IntegrationCheck] Falha ao enviar alerta: {exc}")
    else:
        info("[IntegrationCheck] ✅ Todos os tokens OAuth verificados e válidos")


@app.on_event("startup")
async def startup_event():
    """Inicializa todos os componentes na inicialização do servidor."""
    info("Initializing components...")

    from App.Core.Cache.RedisCache import cache_flush_all

    flushed = cache_flush_all()
    info(f"[Cache] ♻️ Cache limpo no startup ({flushed} chaves removidas)")

    from App.Core.Services.Chat.ChatRoutes import capture_main_loop

    capture_main_loop()

    config = load_config()

    # Initialize MCP Client Manager
    try:
        from App.Features.Tools.Mcp.MCPClientManager import mcp_manager

        await mcp_manager.initialize()
        info("[MCP] Client Manager initialized")
    except Exception as e:
        error(f"[MCP] Failed to initialize MCP Client Manager: {e}")

    # ========================================================================
    # VALIDAR TODAS AS VARS DO .env DE UMA VEZ (via Settings.validate_config)
    # ========================================================================
    config_errors = validate_config(config)
    if config_errors:
        error("[CONFIG] FALHA CRÍTICA: vars obrigatórias ausentes no .env:")
        for msg in config_errors:
            error(f"  ✗ {msg}")
        error("[CONFIG] Corrija o .env e reinicie o servidor.")
        sys.exit(1)

    # ========================================================================
    # VALIDAR CHAVE DE CRIPTOGRAFIA (crítica para sistema de billing)
    # ========================================================================
    try:
        validate_encryption_key()
    except ValueError as e:
        error(f"[ENCRYPTION] FALHA CRÍTICA: {str(e)}")
        error("[ENCRYPTION] Execute: python generate_encryption_key.py")
        sys.exit(1)

    # ========================================================================
    # VALIDAR MÉTODO DE ACESSO PÚBLICO (ngrok ou self_domain)
    # ========================================================================
    so = config.get("so", "windows").lower()
    https_public_url_method = config.get("https_public_url_method", "ngrok").lower()
    health_answer = os.environ.get("HEALTH_ANSWER", "")

    if https_public_url_method == "ngrok" and not health_answer:
        error(
            "[HTTPS_PUBLIC] ❌ HEALTH_ANSWER não definida no .env — obrigatória quando HTTPS_PUBLIC_URL_METHOD=ngrok"
        )
        sys.exit(1)

    if https_public_url_method == "ngrok":
        # Verificar se ngrok está disponível e validar porta
        try:
            result = subprocess.run(
                ["curl", "-f", "-s", "http://127.0.0.1:4040/api/tunnels"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                raise Exception("ngrok API não respondeu")

            # Extrair JSON e validar porta
            ngrok_response = json.loads(result.stdout)
            tunnels = ngrok_response.get("tunnels", [])

            if not tunnels:
                raise Exception("Nenhum túnel ativo no ngrok")

            # Obter a primeira porta redirecionada
            tunnel_addr = tunnels[0].get("config", {}).get("addr", "")
            expected_port = str(health_answer)

            if f":{expected_port}" not in tunnel_addr:
                error(f"[HTTPS_PUBLIC] ⚠️  Porta redirecionada mismatch!")
                error(
                    f"[HTTPS_PUBLIC] Esperado: http://localhost:{expected_port} (HEALTH_ANSWER)"
                )
                error(f"[HTTPS_PUBLIC] Obtido: {tunnel_addr}")
                raise Exception(
                    f"ngrok não está redirecionando para a porta correta ({expected_port})"
                )

            info(f"[HTTPS_PUBLIC] ✅ HEALTH_ANSWER validado: {health_answer}")

            info(
                f"[HTTPS_PUBLIC] ✅ Método HTTPS público disponível: {https_public_url_method}"
            )
            info(
                f"[HTTPS_PUBLIC] ✅ Porta validada: {tunnel_addr} → {tunnels[0].get('public_url', '')}"
            )
        except Exception as e:
            error(
                f"[HTTPS_PUBLIC] ❌ FALHA CRÍTICA: Método HTTPS público indisponível: {https_public_url_method}"
            )
            error(f"[HTTPS_PUBLIC] Erro: {str(e)}")
            error(
                f"[HTTPS_PUBLIC] Execute em outro terminal: ngrok http {config.get('port', '4001')}"
            )
            error(f"[HTTPS_PUBLIC] Servidor será desligado!")
            sys.exit(1)

    # Verificar acessibilidade externa da public_url (ngrok/domínio)
    _pub_url = config.get("public_url", "").rstrip("/")
    if _pub_url:
        try:
            import requests as _req

            _resp = _req.get(f"{_pub_url}/health", timeout=5)
            if _resp.status_code < 500:
                info(f"[HTTPS_PUBLIC] ✅ public_url acessível externamente")
                set_public_url_online(True)
            else:
                warning(
                    f"[HTTPS_PUBLIC] ⚠️ public_url retornou {_resp.status_code} — imagens via base64"
                )
                set_public_url_online(False)
        except Exception as _e:
            warning(
                f"[HTTPS_PUBLIC] ⚠️ public_url inacessível ({_e}) — imagens via base64"
            )
            set_public_url_online(False)

    # Initialize APIKeyRotator (for intelligent API key rotation)
    try:
        llm_rotator_config = config.get("llm_rotator", {})
        if not llm_rotator_config:
            warning(
                "[AppSetup] llm_rotator config is empty - check LLM API Keys in .env"
            )
        else:
            providers = llm_rotator_config.get("providers", {})
            for provider_name, provider_config in providers.items():
                keys = provider_config.get("keys", [])

        rotator = APIKeyRotator(config=llm_rotator_config)
    except Exception as e:
        error(f"[AppSetup] APIKeyRotator initialization error: {e}")
        import traceback

        error(f"[AppSetup] Traceback: {traceback.format_exc()}")

    # VALIDAÇÃO CRÍTICA PRÉ-INICIALIZAÇÃO: Verificar banco local em modo hybrid
    db_env = config.get("db_env", "local").lower()
    if db_env != "local":
        # Em modo hybrid (cloud-rest, cloud-tcp), banco local é OBRIGATÓRIO
        local_db_path = BASE_DIR / "Data" / "Database" / "MD70.db"
        if not local_db_path.exists():
            error(
                f"[FATAL] DB_ENV={db_env} (hybrid mode) requires local SQLite database"
            )
            error(f"[FATAL] Local database not found: {local_db_path}")
            error(f"[FATAL] Cannot proceed without local SQLite in hybrid architecture")
            sys.exit(1)

    # Initialize database (critical - will exit if fails)
    db_initialized = False
    try:
        if init_db():
            db_initialized = True
        else:
            error("Database initialization failed")
    except Exception as e:
        error(f"Database initialization error: {e}")

    # Ensure all ORM-defined tables exist (including attachment_temp_tokens)
    try:
        from App.Core.Crunch.TablesSQL.SchemaManager import SchemaManager

        SchemaManager().create_all_tables()
        info("[SCHEMA] Todas as tabelas verificadas/criadas")
    except Exception as e:
        error(f"[SCHEMA] Erro ao criar tabelas ORM: {e}")

    # Seed MD70 demo data (idempotent — skips if already seeded)
    try:
        from App.Core.Services.MD70.MD70Seed import seed_md70_data
        from App.Core.Crunch.TablesSQL.Database import database as _db

        if _db.engine is not None:
            seed_md70_data(_db.engine)
        else:
            warning("[MD70Seed] Engine not ready — skipping seed.")
    except Exception as e:
        error(f"[MD70Seed] Seed error: {e}")

    # Inicialização dos Componentes
    debug("[AppSetup] Criando cliente OpenAI...")
    try:
        # Tentar obter openai_api_key primeiro, depois api_key como fallback
        api_key = config.get("openai_api_key") or config.get("api_key")

        if not api_key:
            error("[FATAL] API_KEY da OpenAI não encontrada no .env ou config.")
            error(
                "[FATAL] Verifique se OPENAI_API_KEY está definida no seu .env.development"
            )
            sys.exit(1)

        # Usar timeout curto para evitar DNS hang durante a criação do cliente
        import httpx

        http_client = httpx.Client(timeout=5.0)
        openai_client = OpenAI(api_key=api_key, http_client=http_client)
        debug("[AppSetup] Cliente OpenAI criado com sucesso.")
    except SystemExit:
        raise
    except Exception as e:
        error(f"[FATAL] Erro ao criar cliente OpenAI: {e}")
        sys.exit(1)

    debug("[AppSetup] Obtendo db_manager...")
    db_manager = get_db_manager()

    # Initialize AuthService with db_manager
    try:
        debug("[AppSetup] Inicializando AuthService...")
        init_auth_service(db_manager=db_manager, config=config)
    except Exception as e:
        error(f"Auth service initialization error: {e}")

    # Initialize PlanManager with db_manager
    try:
        debug("[AppSetup] Inicializando PlanManager...")
        init_plan_manager(db_manager=db_manager)
    except Exception as e:
        error(f"Plan manager initialization error: {e}")

    auth_manager = AuthManager(config=config)

    # Initialize ChatManager if available, otherwise set to None
    chat_manager = None
    try:
        debug("[AppSetup] Inicializando ChatManager...")
        if ChatManager:
            chat_manager = ChatManager(base_dir=BASE_DIR)
    except Exception as e:
        error(f"ChatManager initialization error: {e}")

    # Initialize AgentsManager
    agents_manager = None
    try:
        debug("[AppSetup] Inicializando AgentsManager...")
        agents_json_path = (
            BASE_DIR / "App" / "Features" / "Agents" / "Agents" / "AGENTS.json"
        )
        agents_manager = AgentsManager(agents_json_path=agents_json_path)
    except Exception as e:
        error(f"AgentsManager initialization error: {e}")
        # CRITICAL: If agents file not found, exit server
        error(
            "[CRITICAL] AgentsManager initialization failed - server cannot start without agents configuration"
        )
        sys.exit(1)

    # Initialize LLMClient
    llm_client = None
    try:
        debug("[AppSetup] Inicializando LLMClient...")
        # Sem fallbacks: deve vir do .env via Settings
        current_ai = config.get("ai")
        current_model = config.get("model")

        if not current_ai or not current_model:
            error(
                "[FATAL] AI provider ('ai') ou modelo ('model') não configurados no .env"
            )
            sys.exit(1)

        llm_client = LLMClient(
            ai=current_ai,
            model=current_model,
        )
    except Exception as e:
        error(f"LLMClient initialization error: {e}")
        sys.exit(1)

    # Initialize ToolFacilitator
    tool_facilitator = None
    if ToolFacilitator:
        try:
            tool_facilitator = ToolFacilitator(agent_manager=agents_manager)
        except Exception as e:
            error(f"ToolFacilitator initialization error: {e}")
            import traceback

            error(f"Traceback: {traceback.format_exc()}")
    else:
        error("ToolFacilitator class not available")

    # Initialize QueueSystem (multi-operation job queues with workers) - CREATE CORE FIRST
    queue_system = None
    tools_core = None
    queue_manager = None
    worker_pool = None

    try:
        from App.Core.Queues import MultiQueueManager, MultiWorkerPool
        from App.Features.Tools import Core

        # Create MultiQueueManager with redis_url from settings
        redis_url = config.get("redis_url", "")
        queue_manager = MultiQueueManager(redis_url=redis_url)

        # [SECURITY CHECK] Verify if Redis is publicly accessible (no password)
        try:
            debug("[AppSetup] Iniciando verificação de segurança do Redis...")
            import redis

            # Parse host and port from redis_url
            from urllib.parse import urlparse

            url_data = urlparse(redis_url)

            # Test connection WITHOUT password
            public_test = redis.Redis(
                host=url_data.hostname or "localhost",
                port=url_data.port or 6379,
                socket_timeout=2,
                decode_responses=True,
            )
            if public_test.ping():
                error(
                    "[SECURITY CRITICAL] REDIS ESTÁ PÚBLICO! Acesso sem senha permitido."
                )
                error(
                    "[SECURITY CRITICAL] O servidor será encerrado para evitar vazamento de dados."
                )
                sys.exit(1)
        except redis.exceptions.AuthenticationError:
            info("[SECURITY OK] Redis requer autenticação (conforme esperado).")
        except Exception as e:
            debug(f"Redis public check skipped/failed: {e}")

        # Test Redis connection (with password/url from config)
        try:
            queue_manager.test_connection()
        except Exception as e:
            error(f"Redis connection failed: {str(e)}")
            error("[REDIS] FALHA CRÍTICA: Não foi possível conectar ao Redis.")
            sys.exit(1)

        # ========================================================================
        # VERIFICAR SANDBOX SERVICE (tool terminal)
        # ========================================================================
        _sandbox_url = os.environ.get("SANDBOX_URL", "").rstrip("/")
        if not _sandbox_url:
            error("[SANDBOX] CRÍTICO: SANDBOX_URL não definida.")
            error("[SANDBOX] O terminal isolado é obrigatório para segurança.")
            sys.exit(1)
        else:
            try:
                import urllib.request as _urllib_req

                _req = _urllib_req.Request(f"{_sandbox_url}/health", method="GET")
                with _urllib_req.urlopen(_req, timeout=5) as _resp:
                    import json as _json

                    _health = _json.loads(_resp.read())
                    if _health.get("status") == "ok":
                        info(f"[SANDBOX] ✅ Sandbox service saudável em {_sandbox_url}")
                    else:
                        error(
                            f"[SANDBOX] ❌ Sandbox em {_sandbox_url} respondeu status inválido: {_health}"
                        )
                        sys.exit(1)
            except Exception as _se:
                error(
                    f"[SANDBOX] ❌ Falha crítica ao conectar no Sandbox em {_sandbox_url}: {_se}"
                )
                error(
                    "[SANDBOX] Certifique-se que o container 'sandbox' está rodando e acessível."
                )
                sys.exit(1)

        # ========================================================================
        # VERIFICAR SALDO DOS PROVIDERS LLM via sandbox
        # ========================================================================
        _check_llm_balances(config)

        # ========================================================================
        # VERIFICAR TOKENS OAUTH DAS INTEGRAÇÕES (Google, Meta, GitHub)
        # ========================================================================
        try:
            await _check_oauth_integrations(db_manager)
        except Exception as _oauth_exc:
            warning(f"[IntegrationCheck] Verificação de OAuth falhou: {_oauth_exc}")

        # ========================================================================
        # VERIFICAR BROWSER SERVICE (scraping com Playwright)
        # ========================================================================
        _browser_url = os.environ.get("BROWSER_SERVICE_URL", "").rstrip("/")
        if not _browser_url:
            error("[BROWSER] CRÍTICO: BROWSER_SERVICE_URL não definida.")
            error("[BROWSER] O serviço de browser isolado é obrigatório para scraping.")
            sys.exit(1)
        else:
            try:
                import urllib.request as _urllib_req
                import json as _json

                _req = _urllib_req.Request(f"{_browser_url}/health", method="GET")
                with _urllib_req.urlopen(_req, timeout=5) as _resp:
                    _health = _json.loads(_resp.read())
                    if _health.get("status") == "ok":
                        info(f"[BROWSER] ✅ Browser service saudável em {_browser_url}")
                    else:
                        error(
                            f"[BROWSER] ❌ Browser em {_browser_url} respondeu status inválido: {_health}"
                        )
                        sys.exit(1)
            except Exception as _be:
                error(
                    f"[BROWSER] ❌ Falha crítica ao conectar no Browser em {_browser_url}: {_be}"
                )
                error(
                    "[BROWSER] Certifique-se que o container 'browser' está rodando e acessível."
                )
                sys.exit(1)

        # Create Core instance FIRST (needed by both MessageProcessor and MultiWorkerPool)
        tools_core = Core(
            message_processor=None,
            chat_manager=chat_manager,
            agents_manager=agents_manager,
            db_manager=db_manager,
        )

        # Create MultiWorkerPool with shared Core instance
        # message_processor will be set after it's created
        worker_pool = MultiWorkerPool(
            queue_manager=queue_manager,
            core=tools_core,
            message_processor=None,  # Will be set after MessageProcessor is created
            chat_service=None,  # Will be set later (created in endpoints)
            db_manager=db_manager,
        )
    except Exception as e:
        error(f"[FAIL] QueueSystem initialization error: {e}")
        import traceback

        error(f"Traceback: {traceback.format_exc()}")

    # Initialize MessageProcessor if all dependencies are available
    message_processor = None

    if chat_manager and agents_manager and llm_client and tool_facilitator:
        try:
            message_processor = MessageProcessor(
                chat_manager=chat_manager,
                agents_manager=agents_manager,
                config=config,
                core=tools_core,
            )
            if tools_core:
                tools_core.message_processor = message_processor

            if "worker_pool" in locals() and worker_pool:
                worker_pool.message_processor = message_processor

                # Also set message_processor on external_tool_worker for resume_after_tool_call
                if (
                    hasattr(worker_pool, "external_tool_worker")
                    and worker_pool.external_tool_worker
                ):
                    worker_pool.external_tool_worker.message_processor = (
                        message_processor
                    )
                    debug(
                        f"[AppSetup] Message processor injected into external_tool_worker"
                    )

                from App.Core.Queues import MessageWorker

                new_message_worker = MessageWorker(
                    queue_manager=queue_manager,
                    message_processor=message_processor,
                    num_workers=3,
                )
                worker_pool.message_worker = new_message_worker
            else:
                error("Cannot register MessageWorker - worker_pool not initialized")
        except Exception as e:
            error(f"MessageProcessor initialization error: {e}")
            import traceback

            error(f"Traceback: {traceback.format_exc()}")
            message_processor = None
    else:
        error("MessageProcessor dependencies missing - skipping initialization")

    # Set agent_session_manager for tool_facilitator
    if tool_facilitator and llm_client and chat_manager:
        try:
            tool_facilitator.set_agent_session_manager(
                llm_client=llm_client, chat_manager=chat_manager
            )
        except Exception as e:
            error(f"Error setting AgentSessionManager for ToolFacilitator: {e}")
            import traceback

            error(f"Traceback: {traceback.format_exc()}")

    # Start queue system after MessageProcessor is ready
    if queue_system is None and queue_manager and worker_pool:
        try:
            info("[QueueSystem] Initializing...")

            # Create wrapper object with queue_manager and worker_pool attributes
            class QueueSystemContainer:
                def __init__(self, qm, wp):
                    self.queue_manager = qm
                    self.worker_pool = wp

            container = QueueSystemContainer(queue_manager, worker_pool)
            queue_system = initialize_queue_system(
                core_instance=container, config=config
            )
            queue_system.start()
            info("[QueueSystem] Initialized successfully")
        except Exception as e:
            error(f"[QueueSystem] Initialization failed: {e}")
            import traceback

            error(f"Traceback: {traceback.format_exc()}")

    # Adiciona BASE_DIR ao config para uso em endpoints que precisam de paths
    config["BASE_DIR"] = str(BASE_DIR)

    components = {
        "chat_manager": chat_manager,
        "agents_manager": agents_manager,
        "message_processor": message_processor,
        "db_manager": db_manager,
        "auth_manager": auth_manager,
        "config": config,
        "openai_client": openai_client,
        "media_compressor": MediaCompressor,
        "queue_system": queue_system,
        "queue_manager": queue_manager,
        "worker_pool": worker_pool,
    }

    setup_app(components)

    # Initialize Subscription Job Scheduler
    try:
        info("[SCHEDULER] Iniciando importação...")
        from App.Core.Scheduler import get_scheduler_manager

        info("[SCHEDULER] Importação OK, obtendo scheduler_manager...")

        from App.Core.Services.Subscription.SubscriptionJob import run_subscription_job
        from apscheduler.triggers.cron import CronTrigger

        info("[SCHEDULER] Chamando get_scheduler_manager()...")
        scheduler_manager = get_scheduler_manager()
        info("[SCHEDULER] Scheduler manager obtido, adicionando job...")

        # Agendar job de subscrição para rodar diariamente às 2:00 AM
        scheduler_manager.add_job(
            func=run_subscription_job,
            trigger=CronTrigger(hour=2, minute=0),  # 2:00 AM todos os dias
            id="subscription_job",
            name="Subscription Charges & Renewals",
            replace_existing=True,
        )
        info("[SCHEDULER] Job adicionado, iniciando scheduler...")

        scheduler_manager.start()
        scheduler_manager.load_tasks_from_db()
        info("[OK] Subscription scheduler initialized and started")
    except Exception as e:
        error(f"[FAIL] Subscription scheduler initialization error: {e}")
        import traceback

        error(f"Traceback: {traceback.format_exc()}")

    # Initialize Litestream S3 replication monitor
    try:
        from App.Core.Services.LitestreamMonitor import litestream_monitor

        litestream_monitor.start()
    except Exception as e:
        error(f"[LitestreamMonitor] Erro ao iniciar monitor: {e}")

    # Start iFood order poller
    try:
        from App.Core.Services.Integrations.Delivery.IFoodOrderPoller import ifood_order_poller

        ifood_order_poller.start()
    except Exception as e:
        error(f"[IFoodPoller] Erro ao iniciar poller: {e}")

    info("Server started successfully")


@app.on_event("shutdown")
async def shutdown_event():
    """Encerra todos os componentes na desligamento do servidor."""

    # Stop iFood order poller
    try:
        from App.Core.Services.Integrations.Delivery.IFoodOrderPoller import ifood_order_poller

        ifood_order_poller.stop()
    except Exception as e:
        error(f"[IFoodPoller] Erro ao parar poller: {e}")

    # Stop subscription scheduler
    try:
        from App.Core.Scheduler import get_scheduler_manager

        scheduler_manager = get_scheduler_manager()
        scheduler_manager.stop()
        info("Subscription scheduler stopped successfully")
    except Exception as e:
        error(f"Error stopping subscription scheduler: {e}")

    try:
        queue_system = get_queue_system()
        if queue_system:
            queue_system.stop(timeout=10)
            info("QueueSystem stopped successfully")
    except Exception as e:
        error(f"Error stopping QueueSystem: {e}")

    info("Server shutdown completed")


# ========================================================================
# HANDLERS DA API
# ========================================================================


@app.get("/api/health", tags=["API"])
async def send_health_check():
    """Health check endpoint retorna status code HTTP como valor + info detalhada do serviço."""
    import psutil
    from datetime import datetime

    # Coleta informações do sistema
    cpu_percent = psutil.cpu_percent(interval=0.1)
    memory = psutil.virtual_memory()

    return {
        "status": 200,  # Status code HTTP como valor
        "service": "prox-backend",
        "env": "production",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "version": "1.0",
        "app": "prox-api",
        "system": {
            "cpu_percent": round(cpu_percent, 1),
            "memory_percent": round(memory.percent, 1),
            "memory_available_gb": round(memory.available / (1024**3), 2),
        },
        "database": {"connected": True, "type": "sqlite"},
        "message": "Serviço funcionando corretamente",
    }


@app.get("/api/check-caching", tags=["API"])
async def check_caching():
    """
    Verifica se o servidor está cacheado (rodando código antigo)

    Retorna um valor hardcoded que muda a cada commit.
    Se receber um valor diferente do esperado, o servidor está cacheado.

    Valor esperado atual: "2026-04-14T15:25:00"
    """
    # MUDANÇA ESTE VALOR PARA TESTAR SE SERVIDOR RECARREGOU
    cache_check_value = "2026-04-14T19:45:00"

    from datetime import datetime

    return {
        "status": "ok",
        "cache_check_value": cache_check_value,
        "timestamp": datetime.utcnow().isoformat(),
        "hint": "Se cache_check_value != '2026-04-14T15:25:00', servidor está cacheado",
    }


def validate_dependencies_with_pip_check():
    """Valida se todas as dependências estão instaladas e compatíveis usando pip check."""
    info("🔍 Validando dependências com pip check...")

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "check"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            error("❌ PIP CHECK ENCONTROU DEPENDÊNCIAS COM PROBLEMAS:")
            error(result.stdout)
            if result.stderr:
                error(result.stderr)
            sys.exit(1)

        info("✅ Todas as dependências estão instaladas e compatíveis")
    except subprocess.TimeoutExpired:
        error("❌ pip check excedeu tempo limite (timeout)")
        sys.exit(1)
    except Exception as e:
        warning(f"⚠️  Erro ao validar dependências: {e}")


def validate_requirements_with_pip_missing_reqs():
    """Valida se todos os imports estão em requirements.txt usando pip-missing-reqs."""
    import shlex

    info("🔍 Validando se imports estão em requirements.txt...")

    try:
        cmd = [
            "pip-missing-reqs",
            str(BASE_DIR / "App"),
            f"--requirements-file={BASE_DIR / 'requirements.txt'}",
            "--ignore-file=*_legacy*",
            "--ignore-file=*.backup*",
            "--ignore-file=*__agentx*",
            "--ignore-file=*edit_session*",
            "--ignore-file=*/Scripts/*",
            "--ignore-file=*/Data/*",
        ]

        # Criar comando com quotes para caminhos com espaços
        cmd_quoted = " ".join(shlex.quote(arg) for arg in cmd)
        debug(f"📋 Executando comando: {cmd_quoted}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # Aumentado para 5 minutos
                cwd=str(BASE_DIR),
            )
        except subprocess.TimeoutExpired:
            warning(
                "⏱️  pip-missing-reqs excedeu tempo limite (300s) - pulando validação"
            )
            info(
                "✅ Backend iniciando mesmo assim. Verifique requirements.txt manualmente se necessário."
            )
            return (
                True  # Permitir que o backend inicie mesmo se o comando exceder timeout
            )

        if result.returncode != 0:
            error("❌ PIP-MISSING-REQS ENCONTROU IMPORTS NÃO DECLARADOS:\n")

            # Mostrar o comando que foi executado
            error("📋 Comando executado:")
            error(f"  {cmd_quoted}\n")

            # Capturar output (pode ter imports faltantes no stdout)
            output = result.stdout.strip() if result.stdout else ""
            errors = result.stderr.strip() if result.stderr else ""

            # Se há output, mostra os imports faltantes
            if output:
                error("📄 Imports não declarados encontrados:")
                for line in output.split("\n"):
                    if line.strip() and not line.startswith("#"):
                        # Converter caminho absoluto para relativo
                        rel_path = line.replace(str(BASE_DIR), "").lstrip("/\\")
                        error(f"  ❌ {rel_path}")
            else:
                error("📄 Output do pip-missing-reqs: (vazio)")

            # Se há erro no stderr, mostra também
            if errors:
                error("\n⚠️  Detalhes do erro completo:")
                error(f"  {errors}")

            error(
                "\n✓ Solução: Adicione os imports faltantes ao requirements.txt ou requirements.in"
            )
            error(f"\n🔧 Para debugar manualmente, execute:")
            error(f"  {cmd_quoted}")
            sys.exit(1)

        info("✅ Todos os imports estão declarados em requirements.txt")
    except FileNotFoundError:
        warning("⚠️  pip-missing-reqs não encontrado. Pulando validação.")
    except subprocess.TimeoutExpired:
        error("❌ pip-missing-reqs excedeu tempo limite (timeout)")
        sys.exit(1)
    except Exception as e:
        warning(f"⚠️  Erro ao validar requirements.txt: {e}")


def setup_app(components: Dict[str, Any]):
    """Configura a aplicação FastAPI com componentes e arquivos estáticos."""
    config_data = components.get("config", {})
    validate_deps = config_data.get("validate_deps", False)

    if validate_deps:
        validate_dependencies_with_pip_check()
        validate_requirements_with_pip_missing_reqs()
    else:
        debug("[AppSetup] VALIDATE_DEPS=false, pulando validação de dependências")

    global COMPONENTS
    COMPONENTS.update(components)  # Use update to merge components, not overwrite

    config = COMPONENTS.get("config", {})

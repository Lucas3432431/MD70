# StdLib
import json
from pathlib import Path
import os
import platform
from dotenv import load_dotenv

# Define o diretório do projeto como base para todos os paths
# (sobe um nível a partir de modules/)

BASE_DIR = Path(__file__).parent.parent.parent.parent.absolute()

# Lido diretamente do os.environ antes de qualquer dotenv para detectar modo container
_is_containered = os.environ.get("IS_CONTAINERED", "false").lower() == "true"

# Arquivo .env pode ser especificado via ENV_FILE (--env flag no startup)
env_file_name = os.environ.get("ENV_FILE")

if not env_file_name:
    # Fallback automático se não for especificado via flag
    if platform.system() == "Windows":
        env_file_name = ".env.windows"
    else:
        env_file_name = ".env"

    # Tentar encontrar o arquivo no BASE_DIR ou na raiz do MVP
    # Se não existir, tenta o .env.development como última tentativa de desenvolvimento
    if not (BASE_DIR / env_file_name).exists():
        mvp_root = BASE_DIR.parent.parent
        if (mvp_root / env_file_name).exists():
            env_file_name = str(mvp_root / env_file_name)
        elif (mvp_root / ".env.development").exists():
            env_file_name = str(mvp_root / ".env.development")

# Usar o arquivo especificado (pode ser caminho relativo ou absoluto)
if Path(env_file_name).is_absolute():
    env_file = Path(env_file_name)
else:
    # Tentar primeiro no BASE_DIR, depois no diretório atual
    env_file = BASE_DIR / env_file_name
    if not env_file.exists():
        env_file = Path(env_file_name)

if not env_file.exists():
    # Se ainda não encontrou, e o nome não tem path, tenta subir dois níveis (raiz do projeto)
    mvp_root_env = BASE_DIR.parent.parent / Path(env_file_name).name
    if mvp_root_env.exists():
        env_file = mvp_root_env
    elif not _is_containered:
        raise FileNotFoundError(
            f"❌ Arquivo de configuração não encontrado: {env_file_name}\n(procurou em: {env_file.absolute()} e {mvp_root_env.absolute()})"
        )

# Carregar variáveis de ambiente
if _is_containered:
    # Container: carrega de /run/secrets/app.env (montado pelo compose, nunca exposto em env)
    _secrets_path = Path("/run/secrets/app.env")
    if _secrets_path.exists():
        load_dotenv(dotenv_path=str(_secrets_path), override=False)
else:
    # Local: carrega do .env.development e depois do .env específico (override=True)
    _mvp_env_file = BASE_DIR.parent.parent / ".env.development"
    if _mvp_env_file.exists():
        load_dotenv(dotenv_path=str(_mvp_env_file), override=False)
    if env_file.exists():
        load_dotenv(dotenv_path=str(env_file), override=True)

# Flag para evitar logs duplicados de config
_config_loaded_once = False

# Cache para LLM config
_llm_config_cache = None


def load_llm_config() -> dict:
    """Load pricing config from llm-config.json (no API keys — those live in .env)."""
    global _llm_config_cache
    if _llm_config_cache is None:
        llm_config_path = BASE_DIR / "llm-config.json"
        if llm_config_path.exists():
            try:
                with open(llm_config_path, "r", encoding="utf-8") as f:
                    _llm_config_cache = json.load(f)
            except Exception:
                _llm_config_cache = {}
        else:
            _llm_config_cache = {}
    return _llm_config_cache


def save_config(
    ai,
    model,
    api_key=None,
    openai_api_key=None,
    deepseek_api_key=None,
    voice_mode="on",
    chat_mode="paused",
    yellow="\\033[93m",
    magenta="\\033[95m",
    white="\\033[97m",
    reset="\\033[0m",
    bold="\\033[1m",
    grey="\\033[90m",
    chat_message_max_width=80,
    chats_data_dir="Data/Chats",
    reports_data_dir="Data/Reports",
    system_prompt="Você é um assistente de IA útil.",
    chat_filename_prefix="chat_",
    chat_filename_extension=".json",
    temp_speech_filename="speech.mp3",
    tts_model="tts-1",
    tts_voice="alloy",
    max_total_duration_seconds=120,
    temp_audio_filename="audio.wav",
    temp_transcription_filename="transcription.txt",
    whisper_model="whisper-1",
    whisper_language="pt",
    external_editor="notepad.exe",
    host="localhost",
    port=8000,
    password="",
    admin_email="",
    hot_reload="false",
    log_level="info",
    session_id="on",
    log_id="on",
    log_timestamp="off",
    log_responsible_file="off",
    log_silence="off",
    external_logging="off",
    log_storage="file",
    log_format="text",
    context="",
    db_env="local",
    supabase_url="",
    supabase_key="",
    reset_local_db="false",
    claude_api_key="",
    google_api_key="",
    proxy_list="",
    rotating_proxy_url="",
    redis_url=None,
):
    """
    Salva configuração no arquivo .env

    Args:
        ai: Provedor de IA (openai ou deepseek)
        model: Nome do modelo específico (gpt-4, gpt-3.5-turbo, deepseek-coder, qwen2.5:0.5b, etc)
        api_key: Chave de API genérica (fallback, compatibilidade)
        openai_api_key: Chave específica do OpenAI
        deepseek_api_key: Chave específica do Deepseek
        claude_api_key: Chave de API do Claude (Anthropic) para fallback de Vision
        google_api_key: Chave de API do Google para VEO 3.1 (fallback de video)
        proxy_list: Lista de proxies separados por vírgula (ip:porta:user:pass)
        rotating_proxy_url: URL de um serviço de proxy rotativo (http://user:pass@host:port)
        redis_url: URL de conexão do Redis
        voice_mode: on ou off
        chat_mode: paused ou conversation
        yellow: Código ANSI para cor amarela
        magenta: Código ANSI para cor magenta
        white: Código ANSI para cor branca
        reset: Código ANSI para resetar cor
        bold: Código ANSI para negrito
        grey: Código ANSI para cor cinza
        chat_message_max_width: Largura máxima da mensagem no chat (terminal)
        chats_data_dir: Diretório onde os dados dos chats são salvos (relativo à BASE_DIR)
        reports_data_dir: Diretório onde os relatórios são salvos (relativo à BASE_DIR)
        system_prompt: Prompt inicial para o sistema (agent principal)
        chat_filename_prefix: Prefixo para o nome dos arquivos de chat
        chat_filename_extension: Extensão para o nome dos arquivos de chat
        temp_speech_filename: Nome do arquivo temporário para fala
        tts_model: Modelo de Text-to-Speech (TTS) a ser usado
        tts_voice: Voz do TTS a ser usada
        max_total_duration_seconds: Duração máxima total em segundos para transcrição de áudio
        temp_audio_filename: Nome do arquivo temporário para áudio
        temp_transcription_filename: Nome do arquivo temporário para transcrição
        whisper_model: Modelo de Speech-to-Text (STT) a ser usado (ex: Whisper)
        whisper_language: Linguagem do Whisper a ser usada (ex: pt, en)
        external_editor: Comando para abrir o editor externo
        host: Host do servidor (ex: localhost, 0.0.0.0)
        port: Porta do servidor (ex: 8000)
        password: Senha para login na interface (se usada)
        admin_email: Email do admin para receber código 2FA
        hot_reload: Ativar ou desativar o hot reload do backend
        log_storage: Armazenamento de logs (file ou database)
        log_format: Formato de logs (text ou json)
        db_env: Ambiente do banco de dados (local ou cloud)
        supabase_url: URL do Supabase (apenas para cloud)
        supabase_key: Chave do Supabase (apenas para cloud)
    """
    env_path = BASE_DIR / ".env"

    with open(env_path, "w", encoding="utf-8") as f:
        f.write(f"# Voice Chat AI Configuration\n\n")
        f.write(f"# AI Provider (openai or deepseek)\n")
        f.write(f"ai={ai}\n\n")
        f.write(f"# Model name\n")
        f.write(
            f"# OpenAI: gpt-4o (RECOMENDADO - multimodal), gpt-4, gpt-4-turbo, gpt-3.5-turbo\n"
        )
        f.write(
            f"# Deepseek: deepseek-chat (multimodal - audio, image, file + prompt)\n"
        )
        f.write(f"model={model}\n\n")
        f.write(f"# API Keys (específicas por provider)\n")
        f.write(f"openai_api_key={openai_api_key if openai_api_key else ''}\n")
        f.write(f"deepseek_api_key={deepseek_api_key if deepseek_api_key else ''}\n")
        f.write(f"claude_api_key={claude_api_key if claude_api_key else ''}\n")
        f.write(f"google_api_key={google_api_key if google_api_key else ''}\n\n")
        if api_key:
            f.write(f"# API Key genérica (fallback para compatibilidade)\n")
            f.write(f"api_key={api_key}\n\n")
        f.write(f"# Voice mode (on or off)\n")
        f.write(f"voice_mode={voice_mode}\n\n")
        f.write(f"# Chat mode (paused or conversation)\n")
        f.write(f"chat_mode={chat_mode}\n\n")
        f.write(f"# --- Logging Settings ---\n\n")
        f.write(f"LOG_LEVEL={log_level}\n")
        f.write(f"SESSION_ID={session_id}\n")
        f.write(f"LOG_ID={log_id}\n")
        f.write(f"LOG_TIMESTAMP={log_timestamp}\n")
        f.write(f"LOG_RESPONSIBLE_FILE={log_responsible_file}\n")
        f.write(f"LOG_SILENCE={log_silence}\n")
        f.write(f"EXTERNAL_LOGGING={external_logging}\n")
        f.write(f"LOG_STORAGE={log_storage}\n")
        f.write(f"LOG_FORMAT={log_format}\n\n")
        f.write(f"# --- UI/Chat Settings ---\n\n")
        f.write(f"yellow={yellow}\n")
        f.write(f"magenta={magenta}\n")
        f.write(f"white={white}\n")
        f.write(f"reset={reset}\n")
        f.write(f"bold={bold}\n")
        f.write(f"grey={grey}\n")
        f.write(f"chat_message_max_width={chat_message_max_width}\n")
        f.write(f"chats_data_dir={chats_data_dir}\n")
        f.write(f"reports_data_dir={reports_data_dir}\n")
        f.write(f"system_prompt={system_prompt}\n")
        f.write(f"chat_filename_prefix={chat_filename_prefix}\n")
        f.write(f"chat_filename_extension={chat_filename_extension}\n\n")
        f.write(f"# --- Audio/Transcription Settings ---\n\n")
        f.write(f"temp_speech_filename={temp_speech_filename}\n")
        f.write(f"tts_model={tts_model}\n")
        f.write(f"tts_voice={tts_voice}\n")
        f.write(f"max_total_duration_seconds={max_total_duration_seconds}\n")
        f.write(f"temp_audio_filename={temp_audio_filename}\n")
        f.write(f"temp_transcription_filename={temp_transcription_filename}\n")
        f.write(f"whisper_model={whisper_model}\n")
        f.write(f"whisper_language={whisper_language}\n")
        f.write(f"external_editor={external_editor}\n\n")
        f.write(f"# --- Server Settings ---\n\n")
        f.write(f"host={host}\n")
        f.write(f"port={port}\n")
        f.write(f"PASSWORD={password}\n")
        f.write(f"ADMIN_EMAIL={admin_email}\n")
        f.write(f"HOT_RELOAD={hot_reload}\n")
        f.write(f"REDIS_URL={redis_url}\n\n")
        f.write(f"# --- Database Settings ---\n\n")
        f.write(f"DB_ENV={db_env}\n")
        f.write(f"SUPABASE_URL={supabase_url if supabase_url else ''}\n")
        f.write(f"SUPABASE_KEY={supabase_key if supabase_key else ''}\n")
        f.write(f"RESET_LOCAL_DB={reset_local_db}\n\n")
        f.write(f"# --- Context Settings ---\n\n")
        f.write(f"context={context}\n")

    print(f"✓ Configuração salva em: {env_path.absolute()}")


def load_config():
    """
    Carrega configurações do .env e .config

    Prioridade: .config > .env > defaults

    .env: Configurações genéricas para usuários finais
    .config: Configurações técnicas do backend

    Returns:
        Dict com:
        - model: Nome do modelo específico
        - api_key: Chave da API (se OpenAI)
        - voice_mode: Boolean (True se ativado)
        - chat_mode: String (paused ou conversation)
        - log_level: String (critical, info, ou debug)
        - db_env: Ambiente do banco de dados (local ou cloud)
        - supabase_url: URL do Supabase (se cloud)
        - supabase_key: Chave do Supabase (se cloud)
    """
    # Determinar qual .env carregar baseado no OS
    if platform.system() == "Windows":
        env_path = BASE_DIR / ".env.windows"
    else:
        env_path = BASE_DIR / ".env"

    config_path = Path(__file__).parent / ".config"

    config = {}

    # Helper function para buscar config com suporte a CAPS e minúsculas
    # Quando IS_CONTAINERED=true, os.environ (injetado pelo container) é a fonte primária
    def get_config(key, default=""):
        """Procura chave em MAIÚSCULAS primeiro, depois minúsculas; fallback em os.environ"""
        return config.get(
            key.upper(),
            config.get(
                key.lower(),
                os.environ.get(key.upper(), os.environ.get(key.lower(), default)),
            ),
        )

    def _parse_env_into(path, target):
        if not Path(path).exists():
            return
        with open(path, "r", encoding="utf-8") as _f:
            for _line in _f:
                _line = _line.strip()
                if not _line or _line.startswith("#") or "=" not in _line:
                    continue
                _k, _v = _line.split("=", 1)
                _k, _v = _k.strip(), _v.strip()
                if not (_v.startswith('"') or _v.startswith("'")):
                    if "#" in _v:
                        _v = _v.split("#")[0].strip()
                if (_v.startswith('"') and _v.endswith('"')) or (
                    _v.startswith("'") and _v.endswith("'")
                ):
                    _v = _v[1:-1]
                target[_k] = _v

    if _is_containered:
        # Container: carrega de /run/secrets/app.env — nunca expõe vars via os.environ
        _container_secrets = Path("/run/secrets/app.env")
        if _container_secrets.exists():
            _parse_env_into(_container_secrets, config)
        # Dev overlay: .env.development montado via docker-compose.dev.yml
        # PUBLIC_URL muda a cada restart do túnel — dev.env sempre vence para essas chaves.
        # Para demais chaves, não sobrescreve vars reais injetados pelo compose (REDIS_HOST etc).
        _dev_env = Path("/run/secrets/dev.env")
        if _dev_env.exists() and os.environ.get("ENV", "") == "development":
            _ALWAYS_FROM_DEV_ENV = {"PUBLIC_URL", "HTTPS_PUBLIC_URL_METHOD"}
            _dev_config: dict = {}
            _parse_env_into(_dev_env, _dev_config)
            for _k, _v in _dev_config.items():
                composed_val = os.environ.get(_k.upper(), "")
                if _k in _ALWAYS_FROM_DEV_ENV or not composed_val:
                    config[_k] = _v
    else:
        # Local: carrega do .env.development e .env específico
        _mvp_env = BASE_DIR.parent.parent / ".env.development"
        _parse_env_into(_mvp_env, config)
        _parse_env_into(env_file, config)

    # In container mode, compose-injected env vars take priority over secrets file.
    # Use setdefault so secrets provide defaults but don't override orchestrator values.
    for _k, _v in config.items():
        if _is_containered:
            os.environ.setdefault(_k.upper(), _v)
        else:
            os.environ[_k.upper()] = _v

    # 2. Carrega .config e faz merge (configurações técnicas, prioridade sobre .env)
    _config_before = dict(config)
    _parse_env_into(config_path, config)
    for _k, _v in config.items():
        if _k not in _config_before or config[_k] != _config_before.get(_k):
            os.environ[_k.upper()] = _v

    # 3. Constrói llm_rotator a partir das vars do .env
    llm_config = load_llm_config()

    llm_rotator_config = {"providers": {}}

    def _make_provider(key_val, model=None):
        entry = {"keys": [{"account": "default", "key": key_val}]}
        if model:
            entry["model"] = model
        return entry

    _openai_key = config.get("OPENAI_API_KEY", config.get("openai_api_key", ""))
    if _openai_key:
        llm_rotator_config["providers"]["openai"] = _make_provider(
            _openai_key, "gpt-4o"
        )

    _deepseek_key = config.get("DEEPSEEK_API_KEY", config.get("deepseek_api_key", ""))
    if _deepseek_key:
        llm_rotator_config["providers"]["deepseek"] = _make_provider(
            _deepseek_key, "deepseek-chat"
        )

    config["llm_rotator"] = llm_rotator_config

    # Carrega configurações com defaults
    ai = get_config("ai").lower()
    model = get_config("model", "")

    # [NOVO] Carrega API keys específicas por provider
    openai_api_key = get_config("openai_api_key", "")
    deepseek_api_key = get_config("deepseek_api_key", "")

    # [NOVO] Pagarme webhook keys
    pagarme_api_key = get_config("PAGARME_API_KEY", "")
    pagarme_webhook = get_config("PAGARME_WEBHOOK", "")
    pagarme_webhook_secret = get_config("PAGARME_WEBHOOK_SECRET", "")
    pagarme_webhook_user = get_config("PAGARME_WEBHOOK_USER", "")
    pagarme_webhook_password = get_config("PAGARME_WEBHOOK_PASSWORD", "")

    # [NOVO] Stripe keys
    stripe_secret_key = get_config("STRIPE_SECRET_KEY")
    stripe_publishable_key = get_config("STRIPE_PUBLISHABLE_KEY", "")
    stripe_webhook_secret = get_config("STRIPE_WEBHOOK_SECRET")

    # Load pricing from confidential-llm.json with fallbacks
    llm_config = load_llm_config()

    # Credit value cost: JSON > ENV (required)
    credit_value_cost = llm_config.get("credit_value_cost")
    if credit_value_cost is None:
        credit_value_cost = int(get_config("CREDIT_VALUE_COST"))
    else:
        credit_value_cost = int(credit_value_cost)

    # Signup bonus
    signup_bonus = int(get_config("SIGNUP_BONUS"))

    # Charging rates (custo em centavos) - JSON > ENV (required)
    def get_pricing(env_key: str) -> int:
        return int(get_config(env_key))

    token_input_cost = get_pricing("TOKEN_INPUT_COST")
    token_output_cost = get_pricing("TOKEN_OUTPUT_COST")

    # Output token cost: JSON > ENV (required)
    output_token_cost = llm_config.get("tools", {}).get("output_token_cost")
    if output_token_cost is None:
        output_token_cost = int(get_config("OUTPUT_TOKEN_COST"))
    else:
        output_token_cost = int(output_token_cost)

    gen_img_cost = get_pricing("GEN_IMG_COST")
    gen_film_cost = get_pricing("GEN_FILM_COST")
    web_search_cost = get_pricing("WEB_SEARCH_COST")
    max_iterations = int(get_config("max_iterations"))

    # Define modelo padrão se não especificado
    if not model:
        if ai == "openai":
            model = "gpt-4o-mini"
        elif ai == "deepseek":
            model = "deepseek-chat"

    # Configurações do Servidor (críticas, sem fallback)
    host = get_config("host")
    port = int(get_config("port"))
    public_url = get_config("PUBLIC_URL", "")
    https_public_url_method = get_config("HTTPS_PUBLIC_URL_METHOD").lower()

    password = get_config("password", "")

    # Email do Admin
    admin_email = get_config("admin_email")
    admin_totp_secret = get_config("ADMIN_TOTP_SECRET", "")

    # Database settings (DB_ENV é obrigatório - sem fallback)
    db_env = get_config("DB_ENV", "").lower()
    supabase_url = get_config("SUPABASE_URL", "")
    supabase_key = get_config("SUPABASE_KEY", "")
    supabase_db_password = get_config("SUPABASE_DB_PASSWORD", "")
    supabase_database_url = get_config("SUPABASE_DATABASE_URL", "")
    reset_local_db = (
        get_config("RESET_LOCAL_DB", "false").lower() == "true"
    )  # Já estava correto

    # 2FA setting
    two_factor_auth = get_config("2FA").lower() == "true"

    # Hot reload setting
    hot_reload = get_config("hot_reload").lower() == "true"

    # Redis Config
    redis_host = get_config("REDIS_HOST", "localhost")
    redis_port = int(get_config("REDIS_PORT", 6379))
    redis_password = get_config("REDIS_PASSWORD", "")
    wsl_redis_url = get_config("WSL_REDIS_URL", "")
    _env_redis_url = get_config("REDIS_URL", "")

    if _env_redis_url:
        redis_url = _env_redis_url
    else:
        auth = f":{redis_password}@" if redis_password else ""
        redis_url = f"redis://{auth}{redis_host}:{redis_port}"

    # Logging settings
    log_level = get_config("log_level", "info").lower()
    session_id = get_config("SESSION_ID", "false").lower() == "true"
    log_id = get_config("LOG_ID", "true").lower() == "true"
    log_timestamp = get_config("LOG_TIMESTAMP", "false").lower() == "true"
    log_responsible_file = get_config("LOG_RESPONSIBLE_FILE", "false").lower() == "true"
    log_silence = get_config("LOG_SILENCE", "false").lower() == "true"
    external_logging = get_config("EXTERNAL_LOGGING", "false").lower() == "true"
    sensitive_filter = get_config("SENSITIVE_FILTER", "true").lower() == "true"
    log_storage = get_config("LOG_STORAGE", "database").lower()
    log_format = get_config("LOG_FORMAT", "text").lower()

    # Load security filters from file
    security_filters_config = {"sensitive_fields": [], "silence_system": False}
    security_filters_path = Path(__file__).parent / "security_filters.json"
    if security_filters_path.exists():
        try:
            with open(security_filters_path, "r", encoding="utf-8") as f:
                security_filters_config = json.load(f)
        except Exception:
            pass  # Use defaults if file not found or invalid

    # Context settings (path onde o agent trabalha)
    context = get_config("context", "")

    # Proxy / Browserbase settings
    proxy_list = get_config("PROXY_LIST", "")
    rotating_proxy_url = get_config("ROTATING_PROXY_URL", "")
    browserbase_api_key = get_config("BROWSERBASE_API_KEY", "")
    browserbase_project_id = get_config("BROWSERBASE_PROJECT_ID", "")
    brave_search_api_key = get_config("BRAVE_SEARCH_API_KEY", "")

    # Path settings
    relative_path = str(BASE_DIR)

    # Security settings
    secret_key = get_config("SECRET_KEY", "")

    # Instagram settings
    instagram_email = get_config("INSTAGRAM_EMAIL", "")
    instagram_password = get_config("INSTAGRAM_PASSWORD", "")

    # Vision AI settings
    # Lê ANTHROPIC_API_KEY (novo padrão) com fallback para CLAUDE_API_KEY (legado)
    claude_api_key = get_config("ANTHROPIC_API_KEY", "") or get_config(
        "CLAUDE_API_KEY", ""
    )
    google_api_key = get_config("GOOGLE_API_KEY", "")

    # External Validation APIs (Abstract API)
    abstract_email_api_key = get_config("ABSTRACT_EMAIL_API_KEY", "")
    abstract_phone_api_key = get_config("ABSTRACT_PHONE_API_KEY", "")

    # Resend email API
    resend_api_key = get_config("RESEND_API_KEY", "")
    omni_email_from = get_config(
        "OMNI_EMAIL_FROM", "MD70 <prox@prox.app.br>"
    )
    resend_email_domain = get_config("RESEND_EMAIL_DOMAIN", "prox.app.br")

    # Google OAuth
    google_client_id = get_config(
        "GOOGLE_AUTH_CLIENT_ID", get_config("GOOGLE_CLIENT_ID", "")
    )
    google_client_secret = get_config(
        "GOOGLE_AUTH_CLIENT_SECRET", get_config("GOOGLE_CLIENT_SECRET", "")
    )
    google_refresh_token = get_config("GOOGLE_REFRESH_TOKEN", "")
    google_callback_url = get_config("GOOGLE_CALLBACK_URL", "")

    # Google Auth (Novo padrão)
    google_auth_client_id = get_config("GOOGLE_AUTH_CLIENT_ID", "")
    google_auth_client_secret = get_config("GOOGLE_AUTH_CLIENT_SECRET", "")
    google_auth_callback_url = get_config("GOOGLE_AUTH_CALLBACK_URL", "")

    # Google Ads server-level credentials (manager account — not per-user)
    gads_developer_token = get_config("GADS_DEVELOPER_TOKEN", "")
    gads_manager_customer_id = get_config("GADS_CUSTOMER_ID", "").replace("-", "")

    # GitHub OAuth (para integrações MCP)
    github_client_id = get_config("GITHUB_CLIENT_ID", "")
    github_client_secret = get_config("GITHUB_CLIENT_SECRET", "")

    # Meta OAuth
    meta_client_id = get_config("META_CLIENT_ID", "")
    meta_client_secret = get_config("META_CLIENT_SECRET", "")

    # Notion OAuth
    notion_client_id = get_config("NOTION_CLIENT_ID", "")
    notion_client_secret = get_config("NOTION_CLIENT_SECRET", "")

    # iFood Integration
    ifood_client_id = get_config("IFOOD_CLIENT_ID", "")
    ifood_client_secret = get_config("IFOOD_CLIENT_SECRET", "")

    # LinkedIn OAuth
    linkedin_client_id = get_config("LINKEDIN_CLIENT_ID", "")
    linkedin_client_secret = get_config("LINKEDIN_CLIENT_SECRET", "")

    # Mock credentials (only set in development via .env.development)
    mock_admin_email = get_config("MOCK_ADMIN_EMAIL", "")
    mock_admin_password = get_config("MOCK_ADMIN_PASSWORD", "")
    mock_admin_totp_secret = get_config("MOCK_ADMIN_TOTP_SECRET", "")
    mock_investor_email = get_config("MOCK_INVESTOR_EMAIL", "")
    mock_investor_password = get_config("MOCK_INVESTOR_PASSWORD", "")
    rate_limiting_on = get_config("RATE_LIMITING_ON", "true").lower() == "true"

    # Dev bypass vars from .env
    dev_bypass_key = get_config("DEV_BYPASS_KEY", "")
    dev_user_id = get_config("DEV_USER_ID", "")
    dev_client_id = get_config("DEV_CLIENT_ID", "")
    email_bypass = [
        e.strip() for e in get_config("EMAIL_BYPASS", "").split(",") if e.strip()
    ]
    phone_bypass = [
        p.strip() for p in get_config("PHONE_BYPASS", "").split(",") if p.strip()
    ]

    # OAuth callback URLs from .env (comma-separated)
    raw_google_callbacks = get_config("GOOGLE_AUTH_CALLBACK_URLS") or get_config(
        "GOOGLE_CALLBACK_URLS", ""
    )
    google_callback_urls = [
        u.strip() for u in raw_google_callbacks.split(",") if u.strip()
    ]

    raw_instagram_callbacks = get_config("INSTAGRAM_CALLBACK_URLS", "")
    instagram_callback_urls = [
        u.strip() for u in raw_instagram_callbacks.split(",") if u.strip()
    ]

    if not dev_user_id:
        raise RuntimeError("DEV_USER_ID is required in .env")

    # Development restart key
    dev_restart_key = get_config("DEV_RESTART_KEY", "")
    environment = get_config("ENV", "production").lower()
    dev_env = environment == "development"

    # User limits
    max_users = int(get_config("MAX_USERS", "100"))

    # Tool execution limits
    max_consecutive_tool_errors = int(get_config("MAX_CONSECUTIVE_TOOL_ERRORS"))

    # Terminal & Container settings
    clear_terminal = get_config("CLEAR_TERMINAL", "false").lower() == "true"
    is_containered = get_config("IS_CONTAINERED", "false").lower() == "true"

    # Dependency validation setting
    validate_deps = get_config("VALIDATE_DEPS", "false").lower() == "true"

    # DevOps settings
    devops_host = get_config("DEVOPS_HOST", "http://localhost:3002")
    devops_service_id = get_config("DEVOPS_SERVICE_ID", "1")

    # Operating System indicator (windows, wsl, linux, etc)
    so = get_config("SO", "windows").lower()

    # [IMPORTANTE] Não fazer logging aqui! Essa função é chamada durante Logger.__init__
    # Chamadas a logging functions durante load_config() causam recursão infinita.
    # O Logger será inicializado DEPOIS e poderá logar essas informações se necessário.
    global _config_loaded_once
    _config_loaded_once = True

    return {
        # AI/LLM
        "ai": ai,
        "model": model,
        "openai_api_key": openai_api_key,
        "deepseek_api_key": deepseek_api_key,
        # Pagarme Payment
        "pagarme_api_key": pagarme_api_key,
        "pagarme_webhook": pagarme_webhook,
        "pagarme_webhook_secret": pagarme_webhook_secret,
        "pagarme_webhook_user": pagarme_webhook_user,
        "pagarme_webhook_password": pagarme_webhook_password,
        # Stripe Payment
        "stripe_secret_key": stripe_secret_key,
        "stripe_publishable_key": stripe_publishable_key,
        "stripe_webhook_secret": stripe_webhook_secret,
        "credit_value_cost": credit_value_cost,
        # Charging rates (custo em centavos)
        "token_input_cost": token_input_cost,
        "token_output_cost": token_output_cost,
        "output_token_cost": output_token_cost,  # Preço para tools (document, print, task, context, client, calendar, attachment)
        "gen_img_cost": gen_img_cost,
        "gen_film_cost": gen_film_cost,
        "web_search_cost": web_search_cost,
        # Iterations
        "max_iterations": max_iterations,
        # Server Settings
        "host": host,
        "port": port,
        "so": so,
        "public_url": public_url,
        "https_public_url_method": https_public_url_method,
        "password": password,
        "admin_email": admin_email,
        "admin_email_password": os.environ.get("ADMIN_EMAIL_PASSWORD", ""),
        "admin_totp_secret": admin_totp_secret,
        # Google Cloud Service Account
        "google_credentials_project_id": os.environ.get(
            "GOOGLE_CREDENTIALS_PROJECT_ID", ""
        ),
        "google_credentials_private_key": os.environ.get(
            "GOOGLE_CREDENTIALS_PRIVATE_KEY", ""
        ),
        "google_credentials_client_email": os.environ.get(
            "GOOGLE_CREDENTIALS_CLIENT_EMAIL", ""
        ),
        "google_credentials_token_uri": os.environ.get(
            "GOOGLE_CREDENTIALS_TOKEN_URI", ""
        ),
        # Database Settings
        "db_env": db_env,
        "supabase_url": supabase_url,
        "supabase_key": supabase_key,
        "supabase_db_password": supabase_db_password,
        "supabase_database_url": supabase_database_url,
        "reset_local_db": reset_local_db,
        # Security
        "secret_key": secret_key,
        "two_factor_auth": two_factor_auth,
        # Mock admin (only populated in development via .env.development)
        "mock_admin_email": mock_admin_email or None,
        "mock_admin_password": mock_admin_password or None,
        "mock_admin_totp_secret": mock_admin_totp_secret or None,
        "mock_investor_email": mock_investor_email or None,
        "mock_investor_password": mock_investor_password or None,
        # Development bypass (from .env)
        "dev_bypass_key": dev_bypass_key,
        "dev_user_id": dev_user_id,
        "dev_client_id": dev_client_id,
        "dev_restart_key": dev_restart_key,
        "dev_env": dev_env,
        "rate_limiting_on": rate_limiting_on,
        # User limits
        "max_users": max_users,
        # Tool execution limits
        "max_consecutive_tool_errors": max_consecutive_tool_errors,
        # Terminal & Container
        "clear_terminal": clear_terminal,
        "is_containered": is_containered,
        "validate_deps": validate_deps,
        # DevOps settings
        "devops_host": devops_host,
        "devops_service_id": devops_service_id,
        # Features
        "hot_reload": hot_reload,
        "redis_url": redis_url,
        "wsl_redis_url": wsl_redis_url,
        "redis_port": redis_port,
        # Logging
        "log_level": log_level,
        "session_id": session_id,
        "log_id": log_id,
        "log_timestamp": log_timestamp,
        "log_responsible_file": log_responsible_file,
        "log_silence": log_silence,
        "external_logging": external_logging,
        "sensitive_filter": sensitive_filter,
        "log_storage": log_storage,
        "log_format": log_format,
        "security_filters_config": security_filters_config,
        # Context
        "context": context,
        # Proxy / Browserbase
        "proxy_list": proxy_list,
        "rotating_proxy_url": rotating_proxy_url,
        "browserbase_api_key": browserbase_api_key,
        "browserbase_project_id": browserbase_project_id,
        "brave_search_api_key": brave_search_api_key,
        # Paths
        "relative_path": relative_path,
        # Instagram
        "instagram_email": instagram_email,
        "instagram_password": instagram_password,
        # Vision AI & Fallbacks
        "claude_api_key": claude_api_key,
        "anthropic_api_key": claude_api_key,
        "google_api_key": google_api_key,
        # External Validation APIs
        "abstract_email_api_key": abstract_email_api_key,
        "abstract_phone_api_key": abstract_phone_api_key,
        # Resend
        "resend_api_key": resend_api_key,
        "omni_email_from": omni_email_from,
        # Google OAuth
        "google_client_id": google_client_id,
        "google_client_secret": google_client_secret,
        "google_refresh_token": os.environ.get("GOOGLE_REFRESH_TOKEN", ""),
        # Telegram (AgentX - notificações de sistema)
        "telegram_bot_token": os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        "telegram_chat_id": os.environ.get("TELEGRAM_CHAT_ID", ""),
        # OmniChannel
        "omni_verify_token": os.environ.get(
            "OMNI_VERIFY_TOKEN", "prox_default_token"
        ),
        "omni_telegram_bot_token": os.environ.get("OMNI_TELEGRAM_BOT_TOKEN", ""),
        "omni_telegram_bot_username": os.environ.get("OMNI_TELEGRAM_BOT_USERNAME", ""),
        "google_callback_url": google_callback_url,
        "google_callback_urls": google_callback_urls,
        "instagram_callback_urls": instagram_callback_urls,
        # Google Auth (Novo padrão)
        "google_auth_client_id": google_auth_client_id,
        "google_auth_client_secret": google_auth_client_secret,
        "google_auth_callback_url": google_auth_callback_url,
        # Google Ads server-level credentials (manager account)
        "gads_developer_token": gads_developer_token,
        "gads_manager_customer_id": gads_manager_customer_id,
        # GitHub OAuth
        "github_client_id": github_client_id,
        "github_client_secret": github_client_secret,
        # Meta OAuth
        "meta_client_id": meta_client_id,
        "meta_client_secret": meta_client_secret,
        # Notion OAuth
        "notion_client_id": notion_client_id,
        "notion_client_secret": notion_client_secret,
        # LinkedIn OAuth
        "linkedin_client_id": linkedin_client_id,
        "linkedin_client_secret": linkedin_client_secret,
        # iFood Integration
        "ifood_client_id": ifood_client_id,
        "ifood_client_secret": ifood_client_secret,
        # Google Cloud Credentials (Zera Project - from env vars)
        "google_credentials_type": get_config("GOOGLE_CREDENTIALS_TYPE", ""),
        "google_credentials_project_id": get_config(
            "GOOGLE_CREDENTIALS_PROJECT_ID", ""
        ),
        "google_credentials_private_key_id": get_config(
            "GOOGLE_CREDENTIALS_PRIVATE_KEY_ID", ""
        ),
        "google_credentials_private_key": get_config(
            "GOOGLE_CREDENTIALS_PRIVATE_KEY", ""
        ).replace("\\n", "\n"),
        "google_credentials_client_email": get_config(
            "GOOGLE_CREDENTIALS_CLIENT_EMAIL", ""
        ),
        "google_credentials_client_id": get_config("GOOGLE_CREDENTIALS_CLIENT_ID", ""),
        "google_credentials_auth_uri": get_config("GOOGLE_CREDENTIALS_AUTH_URI", ""),
        "google_credentials_token_uri": get_config("GOOGLE_CREDENTIALS_TOKEN_URI", ""),
        "google_credentials_auth_provider_x509_cert_url": get_config(
            "GOOGLE_CREDENTIALS_AUTH_PROVIDER_X509_CERT_URL", ""
        ),
        "google_credentials_client_x509_cert_url": get_config(
            "GOOGLE_CREDENTIALS_CLIENT_X509_CERT_URL", ""
        ),
        "google_credentials_universe_domain": get_config(
            "GOOGLE_CREDENTIALS_UNIVERSE_DOMAIN", "googleapis.com"
        ),
        "google_cloud_location": get_config("GOOGLE_CLOUD_LOCATION", "us-central1"),
        # Bypass lists (from .env)
        "email_bypass": email_bypass,
        "phone_bypass": phone_bypass,
        "signup_bonus": signup_bonus,
        "llm_rotator": llm_rotator_config,
        "llm_config": llm_config,
        "environment": environment,
        "vite_http_protocol": get_config("VITE_HTTP_PROTOCOL", "http"),
        "frontend_host": get_config("FRONTEND_HOST", "localhost"),
        "frontend_port": get_config("FRONTEND_PORT", "5082"),
        "nginx_port": get_config("NGINX_PORT", "8081"),
    }


def get_billing_encryption_key() -> str:
    return load_config().get("secret_key", "")


def get_agent_llm_config(agent_id: str = None, agent_config: dict = None):
    """
    Obtém a configuração LLM específica de um agent (ai, model e api_key).

    Args:
        agent_id: ID do agent (para buscar em AGENTS.json)
        agent_config: Configuração do agent (se já tiver carregada)

    Returns:
        Dict com {"ai": "openai|deepseek", "model": "...", "api_key": "..."}
    """
    try:
        config_data = load_config()

        # Se agent_config foi fornecido, usa diretamente
        if agent_config:
            ai = agent_config.get("ai", "openai")
            model = agent_config.get("model", "gpt-4o-mini")
            # Retorna a chave API correta baseado no ai provider
            api_key = _get_api_key_for_provider(ai, config_data)
            return {"ai": ai, "model": model, "api_key": api_key}

        # Se só agent_id foi fornecido, busca em AGENTS.json
        if agent_id:
            agents_file = BASE_DIR / "Data" / "Agents" / "AGENTS.json"
            if agents_file.exists():
                with open(agents_file, "r", encoding="utf-8") as f:
                    agents_data = json.load(f)

                # Busca o agent recursivamente em toda árvore
                def find_agent(agents_list, target_id):
                    for agent in agents_list:
                        if agent.get("id") == target_id:
                            return agent
                        # Busca em sub_agents
                        if "sub_agents" in agent:
                            result = find_agent(agent["sub_agents"], target_id)
                            if result:
                                return result
                    return None

                agent = find_agent(agents_data.get("agents", []), agent_id)
                if agent:
                    ai = agent.get("ai", "openai")
                    model = agent.get("model", "gpt-4o-mini")
                    # Retorna a chave API correta baseado no ai provider
                    api_key = _get_api_key_for_provider(ai, config_data)
                    return {"ai": ai, "model": model, "api_key": api_key}

        # Fallback: retorna config global
        return {
            "ai": config_data.get("ai", "openai"),
            "model": config_data.get("model", "gpt-4o-mini"),
            "api_key": _get_api_key_for_provider(
                config_data.get("ai", "openai"), config_data
            ),
        }

    except Exception as e:
        # Se erro, retorna config global
        config_data = load_config()
        return {
            "ai": config_data.get("ai", "openai"),
            "model": config_data.get("model", "gpt-4o-mini"),
            "api_key": _get_api_key_for_provider(
                config_data.get("ai", "openai"), config_data
            ),
        }


def _get_api_key_for_provider(ai_provider: str, config_data: dict):
    """
    Retorna a API key correta baseado no provider.

    Args:
        ai_provider: Provider ("openai", "deepseek")
        config_data: Dicionário de configuração do load_config()

    Returns:
        String com a API key
    """
    ai_provider = ai_provider.lower()
    if ai_provider == "openai":
        return config_data.get("openai_api_key", "")
    elif ai_provider == "deepseek":
        return config_data.get("deepseek_api_key", "")
    else:  # For any other provider, including unsupported ones
        return ""


def get_openai_api_key():
    """
    Retorna a API key do OpenAI a partir do llm_rotator no config.

    Returns:
        String com a API key do OpenAI ou string vazia
    """
    try:
        config = load_config()

        # Tentar obter do llm_rotator (carregado de confidential-keys.json)
        llm_rotator = config.get("llm_rotator", {})
        openai_config = llm_rotator.get("providers", {}).get("openai", {})
        keys = openai_config.get("keys", [])

        if keys and isinstance(keys, list) and len(keys) > 0:
            # Se é uma lista de dicts com 'key' field
            if isinstance(keys[0], dict) and "key" in keys[0]:
                return keys[0]["key"]
            # Se é uma lista de strings
            elif isinstance(keys[0], str):
                return keys[0]

        return ""
    except:
        return ""


def get_public_url() -> str:
    """
    Retorna a URL pública do backend (PUBLIC_URL do .env).

    Returns:
        URL pública (ex: https://transpenetrable-supernormally-donnie.ngrok-free.dev)
    """
    config = load_config()
    public_url = config.get("public_url")
    return public_url.rstrip("/")


# Prefixo base de todos os endpoints que recebem chamadas de serviços externos.
# Altere aqui para propagar para todos os routers e URLs construídas.
WEBHOOK_PREFIX = "/webhook"


def get_webhook_base_url() -> str:
    """Retorna a URL pública completa para os endpoints de webhook."""
    return f"{get_public_url()}{WEBHOOK_PREFIX}"


def validate_config(config: dict) -> list[str]:
    """
    Valida que todas as vars obrigatórias foram carregadas pelo Settings.

    Retorna lista de erros. Lista vazia = tudo ok.
    """
    errors = []

    def _check(group: str, fields: list[tuple[str, str]]):
        for config_key, env_name in fields:
            if not config.get(config_key, "").strip():
                errors.append(f"[{group}] {env_name} não definida no .env")

    _check(
        "SECURITY",
        [
            ("secret_key", "SECRET_KEY"),
        ],
    )

    _check(
        "DEV_BYPASS",
        [
            ("dev_user_id", "DEV_USER_ID"),
            ("dev_bypass_key", "DEV_BYPASS_KEY"),
        ],
    )

    _check(
        "GOOGLE_CLOUD",
        [
            ("google_credentials_type", "GOOGLE_CREDENTIALS_TYPE"),
            ("google_credentials_project_id", "GOOGLE_CREDENTIALS_PROJECT_ID"),
            ("google_credentials_private_key", "GOOGLE_CREDENTIALS_PRIVATE_KEY"),
            ("google_credentials_client_email", "GOOGLE_CREDENTIALS_CLIENT_EMAIL"),
            ("google_credentials_token_uri", "GOOGLE_CREDENTIALS_TOKEN_URI"),
        ],
    )

    _check(
        "STRIPE",
        [
            ("stripe_secret_key", "STRIPE_SECRET_KEY"),
            ("stripe_webhook_secret", "STRIPE_WEBHOOK_SECRET"),
        ],
    )

    _check(
        "REDIS",
        [
            ("redis_url", "REDIS_URL"),
        ],
    )

    if config.get("db_env", "") in ("cloud-rest", "cloud-tcp"):
        _check(
            "SUPABASE",
            [
                ("supabase_url", "SUPABASE_URL"),
                ("supabase_key", "SUPABASE_KEY"),
            ],
        )

    if config.get("db_env", "") == "cloud-tcp":
        _check(
            "SUPABASE_TCP",
            [
                ("supabase_db_password", "SUPABASE_DB_PASSWORD"),
                ("supabase_database_url", "SUPABASE_DATABASE_URL"),
            ],
        )

    _check(
        "VALIDATION_API",
        [
            ("abstract_email_api_key", "ABSTRACT_EMAIL_API_KEY"),
            ("abstract_phone_api_key", "ABSTRACT_PHONE_API_KEY"),
        ],
    )

    # Pelo menos um provider LLM precisa ter chave
    llm_rotator = config.get("llm_rotator", {})
    providers_with_keys = [
        p for p, v in llm_rotator.get("providers", {}).items() if v.get("keys")
    ]
    if not providers_with_keys:
        errors.append(
            "[LLM] Nenhuma API key de LLM definida (OPENAI_API_KEY, DEEPSEEK_API_KEY, ANTHROPIC_API_KEY...)"
        )

    return errors


def get_google_cloud_config() -> dict:
    """
    Retorna configurações do Google Cloud para Vertex AI.

    Monta o dict de credenciais a partir das vars de ambiente individuais
    (GOOGLE_CREDENTIALS_*) em vez de um arquivo físico.

    Returns:
        Dict com project_id, location e credentials_info (pronto para
        service_account.Credentials.from_service_account_info())
    """
    config = load_config()

    credentials_info = {
        "type": config.get("google_credentials_type", "service_account"),
        "project_id": config.get("google_credentials_project_id", ""),
        "private_key_id": config.get("google_credentials_private_key_id", ""),
        "private_key": config.get("google_credentials_private_key", ""),
        "client_email": config.get("google_credentials_client_email", ""),
        "client_id": config.get("google_credentials_client_id", ""),
        "auth_uri": config.get("google_credentials_auth_uri", ""),
        "token_uri": config.get("google_credentials_token_uri", ""),
        "auth_provider_x509_cert_url": config.get(
            "google_credentials_auth_provider_x509_cert_url", ""
        ),
        "client_x509_cert_url": config.get(
            "google_credentials_client_x509_cert_url", ""
        ),
        "universe_domain": config.get(
            "google_credentials_universe_domain", "googleapis.com"
        ),
    }

    return {
        "project_id": credentials_info.get("project_id", ""),
        "location": config.get("google_cloud_location", "us-central1"),
        "credentials_info": credentials_info,
    }


# ============================================================================
# 🌍 GLOBAL CONFIGURATION CONSTANTS
# ============================================================================
# Carregadas uma única vez na importação do módulo
GLOBAL_CONFIG = load_config()

# Expor variáveis para importação direta em outros serviços
MAX_USERS = GLOBAL_CONFIG["max_users"]
EMAIL_BYPASS = GLOBAL_CONFIG["email_bypass"]
PHONE_BYPASS = GLOBAL_CONFIG["phone_bypass"]
SECRET_KEY = GLOBAL_CONFIG["secret_key"]
# Security Settings
COOKIE_SECURE = GLOBAL_CONFIG.get("environment") == "production"
COOKIE_HTTPONLY = True
COOKIE_SAMESITE = "Lax"
ACCESS_TOKEN_EXPIRY = 3600
REFRESH_TOKEN_EXPIRY = 604800

DEV_BYPASS_KEY = GLOBAL_CONFIG["dev_bypass_key"]
DEV_USER_ID = GLOBAL_CONFIG["dev_user_id"]
GOOGLE_AUTH_CLIENT_ID = GLOBAL_CONFIG["google_auth_client_id"]
GOOGLE_AUTH_CLIENT_SECRET = GLOBAL_CONFIG["google_auth_client_secret"]
GOOGLE_AUTH_CALLBACK_URL = GLOBAL_CONFIG["google_auth_callback_url"]
GADS_DEVELOPER_TOKEN = GLOBAL_CONFIG.get("gads_developer_token", "")
GADS_MANAGER_CUSTOMER_ID = GLOBAL_CONFIG.get("gads_manager_customer_id", "")
GITHUB_CLIENT_ID = GLOBAL_CONFIG.get("github_client_id", "")
GITHUB_CLIENT_SECRET = GLOBAL_CONFIG.get("github_client_secret", "")
META_CLIENT_ID = GLOBAL_CONFIG.get("meta_client_id", "")
META_CLIENT_SECRET = GLOBAL_CONFIG.get("meta_client_secret", "")
NOTION_CLIENT_ID = GLOBAL_CONFIG.get("notion_client_id", "")
NOTION_CLIENT_SECRET = GLOBAL_CONFIG.get("notion_client_secret", "")
LINKEDIN_CLIENT_ID = GLOBAL_CONFIG.get("linkedin_client_id", "")
LINKEDIN_CLIENT_SECRET = GLOBAL_CONFIG.get("linkedin_client_secret", "")
META_CLIENT_ID = GLOBAL_CONFIG.get("meta_client_id", "")
META_CLIENT_SECRET = GLOBAL_CONFIG.get("meta_client_secret", "")
NOTION_CLIENT_ID = GLOBAL_CONFIG.get("notion_client_id", "")
NOTION_CLIENT_SECRET = GLOBAL_CONFIG.get("notion_client_secret", "")
LINKEDIN_CLIENT_ID = GLOBAL_CONFIG.get("linkedin_client_id", "")
LINKEDIN_CLIENT_SECRET = GLOBAL_CONFIG.get("linkedin_client_secret", "")
DB_ENV = GLOBAL_CONFIG["db_env"]
ENVIRONMENT = GLOBAL_CONFIG["environment"]
DEV_ENV = GLOBAL_CONFIG["dev_env"]
MOCK_ADMIN_EMAIL = GLOBAL_CONFIG["mock_admin_email"]
MOCK_ADMIN_PASSWORD = GLOBAL_CONFIG["mock_admin_password"]
MOCK_ADMIN_TOTP_SECRET = GLOBAL_CONFIG.get("mock_admin_totp_secret", "")
MOCK_INVESTOR_EMAIL = GLOBAL_CONFIG.get("mock_investor_email", "")
MOCK_INVESTOR_PASSWORD = GLOBAL_CONFIG.get("mock_investor_password", "")
RATE_LIMITING_ON = GLOBAL_CONFIG["rate_limiting_on"]
SIGNUP_BONUS = GLOBAL_CONFIG["signup_bonus"]
HOST = GLOBAL_CONFIG["host"]
PORT = GLOBAL_CONFIG["port"]
HOT_RELOAD = GLOBAL_CONFIG["hot_reload"]

# Frontend / OAuth Redirects
VITE_HTTP_PROTOCOL = GLOBAL_CONFIG["vite_http_protocol"]
PUBLIC_URL = GLOBAL_CONFIG["public_url"]

# Flag de acessibilidade externa da public_url (ngrok/domínio).
# Definida no startup pelo AppSetup via set_public_url_online().
# False = usar base64 URI em vez de URL temporária para imagens.
_PUBLIC_URL_ONLINE: bool = True


def set_public_url_online(value: bool) -> None:
    global _PUBLIC_URL_ONLINE
    _PUBLIC_URL_ONLINE = value


def is_public_url_online() -> bool:
    return _PUBLIC_URL_ONLINE


FRONTEND_HOST = GLOBAL_CONFIG["frontend_host"]
FRONTEND_PORT = GLOBAL_CONFIG["frontend_port"]
NGINX_PORT = GLOBAL_CONFIG["nginx_port"]
ADMIN_EMAIL = GLOBAL_CONFIG["admin_email"]
ADMIN_EMAIL_PASSWORD = GLOBAL_CONFIG["admin_email_password"]
RESEND_API_KEY = GLOBAL_CONFIG.get("resend_api_key", "")
OMNI_EMAIL_FROM = GLOBAL_CONFIG.get(
    "omni_email_from", "MD70 <prox@prox.app.br>"
)
RESEND_EMAIL_DOMAIN = GLOBAL_CONFIG.get("resend_email_domain", "prox.app.br")

# Google OAuth
GOOGLE_CLIENT_ID = GLOBAL_CONFIG["google_client_id"]
GOOGLE_CLIENT_SECRET = GLOBAL_CONFIG["google_client_secret"]
GOOGLE_REFRESH_TOKEN = GLOBAL_CONFIG["google_refresh_token"]

# Telegram (AgentX)
TELEGRAM_BOT_TOKEN = GLOBAL_CONFIG["telegram_bot_token"]
TELEGRAM_CHAT_ID = GLOBAL_CONFIG["telegram_chat_id"]

# OmniChannel
OMNI_VERIFY_TOKEN = GLOBAL_CONFIG["omni_verify_token"]
OMNI_TELEGRAM_BOT_TOKEN = GLOBAL_CONFIG["omni_telegram_bot_token"]
OMNI_TELEGRAM_BOT_USERNAME = GLOBAL_CONFIG["omni_telegram_bot_username"]

# Google Credentials
GOOGLE_CREDENTIALS_PROJECT_ID = GLOBAL_CONFIG["google_credentials_project_id"]
GOOGLE_CREDENTIALS_PRIVATE_KEY = GLOBAL_CONFIG["google_credentials_private_key"]
GOOGLE_CREDENTIALS_CLIENT_EMAIL = GLOBAL_CONFIG["google_credentials_client_email"]
GOOGLE_CREDENTIALS_TOKEN_URI = GLOBAL_CONFIG["google_credentials_token_uri"]

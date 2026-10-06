# -*- coding: utf-8 -*-
"""
Sistema centralizado de logs para toda a aplicacao com suporte a SQLite.

Carrega configuracoes do config.py:
- debug_mode: Se "on", printa todos os logs. Se "off", apenas status != 200/201
- log_level: Nivel minimo de log (debug, info, warning, error, critical)
- log_id: Se "on", gera UUID unico para cada execucao
- log_timestamp: Se "on", inclui timestamp em cada log
- log_responsible_file: Se "on", mostra qual arquivo emitiu o log
- hot_reload: Apenas informacao para dev que hot reload esta ativo
- external_logging: Se "on", envia logs para servidor externo
- log_format: "text" ou "json" (define se logs são salvos em text bruto ou estruturado json)
- log_storage: "file" ou "database" (define se usa arquivos .txt ou SQLite)

Regras de Impressao:
1. Na INICIALIZACAO: Printa as configuracoes carregadas
2. Durante EXECUCAO:
   - Se debug_mode=on: Printa tudo
   - Se debug_mode=off: Printa apenas logs com status != 200 e != 201
3. Nunca printa "| DEBUG |" em todos os logs (apenas quando necessario)
4. Se external_logging=on: Envia logs para http://localhost:5000/logs/MD70
"""

from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any, List
from uuid import uuid4
import inspect
from pathlib import Path
import os
import sys
from contextvars import ContextVar
import requests  # Para envio de logs externos
import time
import websocket
import threading
import json
import sqlite3
import atexit

# ============================================================================
# CONFIGURAÇÕES E STRINGS (ISOLADO PARA FÁCIL AJUSTE)
# ============================================================================

DEFAULT_DEVOPS_HOST = "http://localhost:3002"
DEFAULT_EXTERNAL_LOG_URL = "http://localhost:5000/logs/MD70"

# Configurações de Path e Arquivos
from App.Core.Settings.Settings import BASE_DIR

LOGS_BASE_DIR = BASE_DIR / "Data" / ".Logs"
DB_FILE = LOGS_BASE_DIR / "logs.db"
SILENCE_FILENAME = ".silence"

# Padrões de Arquivo e Formatos
LOG_FILE_NAME_PATTERN = "{timestamp}_logs_{session_id}.txt"
TIMESTAMP_FORMAT = "%d.%m.%Y - %H:%M:%S"
LOG_TIMESTAMP_PATTERN = "%Y%m%d_%H%M%S"

# Tags e Formatos de Saída
LEVEL_TAGS = {
    "error": "[ERROR]",
    "warning": "[WARNING]",
    "info": "[INFO]",
    "critical": "[CRITICAL]",
    "audit": "[AUDIT]",
    "debug": "[DEBUG]",
}

HTTP_STATUS_FORMAT = "[HTTP {status}]"
DATA_SEPARATOR = " | "

# Cabeçalhos e Templates
LOG_SESSION_HEADER = """=== SESSION LOG ===
Session ID: {session_id}
Start Time: {start_time}
Log Level: {log_level}
DB Environment: {db_env}
Log File: {log_file}
External Logging: {external_logging}
====== LOGS ======

"""

MSG_PRODUCTION_MODE = "\n[PRODUCTION MODE - BLOCKING CONDITIONS]"
MSG_PRODUCTION_OK = "  * Todas as condições de produção atendidas"
MSG_BLOCK_LOG_LEVEL = "log_level={level} (deve ser warning/error)"
MSG_BLOCK_EXTERNAL = "external_logging=ON (deve estar OFF)"
MSG_BLOCK_SECURITY = "security_filter=OFF (deve estar ON)"

# Comandos de Sistema
CMD_CLEAR_LINUX = "clear"
CMD_CLEAR_WIN = "cls"

# SQL Queries
SQL_CREATE_LOGS_TABLE = """
    CREATE TABLE IF NOT EXISTS logs (
        id TEXT PRIMARY KEY,
        session_id TEXT,
        log_id TEXT,
        timestamp TEXT NOT NULL,
        log_level TEXT NOT NULL,
        responsible_file TEXT,
        message TEXT NOT NULL,
        status INTEGER,
        vars TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
"""

SQL_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_session_id ON logs(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_log_level ON logs(log_level)",
    "CREATE INDEX IF NOT EXISTS idx_timestamp ON logs(timestamp)",
]

SQL_INSERT_LOG = """
    INSERT INTO logs
    (id, session_id, log_id, timestamp, log_level, responsible_file, message, status, vars)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

LEVEL_DESCRIPTIONS = {
    "critical": "Apenas erros críticos e catastróficos",
    "audit": "Ações de conformidade e segurança (sempre ON)",
    "error": "Erros que impactam a operação",
    "warning": "Avisos e situações inesperadas",
    "info": "Informações essenciais de fluxo",
    "debug": "Modo detalhado (todos os logs)",
}

# ============================================================================
# CONTEXTO E VARIÁVEIS TÉCNICAS
# ============================================================================

# Context variable to hold the request-specific log ID
request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
session_id_var: ContextVar[Optional[str]] = ContextVar(
    "session_id", default=None
)  # NEW: ContextVar para session_id


def clear_terminal() -> None:
    """Limpa o terminal de forma segura sem usar shell=True."""
    try:
        if os.name == "nt":
            # No Windows, chamamos o cmd.exe explicitamente com shell=False
            import subprocess

            subprocess.run(["cmd", "/c", CMD_CLEAR_WIN], shell=False)
        else:
            # No Linux/Mac, usamos sequência ANSI (mais seguro, sem subprocesso)
            sys.stdout.write("\033[H\033[2J")
            sys.stdout.flush()
    except Exception:
        pass


def set_request_id(request_id: Optional[str] = None) -> str:
    """Generates and sets a unique request ID for logging context."""
    if request_id is None:
        request_id = str(uuid4())[:8]
    request_id_var.set(request_id)
    return request_id


def get_request_id() -> Optional[str]:
    """Gets the current request ID from the logging context."""
    return request_id_var.get()


# NEW: Funções para gerenciar o session_id no contexto
def set_session_id(session_id: Optional[str] = None) -> Optional[str]:
    """Sets a session ID for logging context."""
    if session_id is None:
        return None  # Não gerar um novo aqui, apenas usar o que foi passado
    session_id_var.set(session_id)
    return session_id


def get_session_id() -> Optional[str]:
    """Gets the current session ID from the logging context."""
    return session_id_var.get()


class LogDatabase:
    """Gerenciador de banco de dados SQLite para logs."""

    def __init__(self, db_path: Path):
        """Inicializa o banco de dados."""
        self.db_path = db_path
        self.connection = None
        self._init_db()

    def _init_db(self) -> None:
        """Cria o banco de dados e a tabela se não existirem."""
        try:
            self.connection = sqlite3.connect(
                str(self.db_path), check_same_thread=False, timeout=0.5
            )
            cursor = self.connection.cursor()

            cursor.execute(SQL_CREATE_LOGS_TABLE)

            # Criar índices para melhor performance
            for sql in SQL_CREATE_INDEXES:
                cursor.execute(sql)

            # Tornar a tabela append-only: impede UPDATE e DELETE via triggers
            cursor.execute(
                """
                CREATE TRIGGER IF NOT EXISTS prevent_log_delete
                BEFORE DELETE ON logs
                BEGIN SELECT RAISE(ABORT, 'Log deletion not allowed'); END
            """
            )
            cursor.execute(
                """
                CREATE TRIGGER IF NOT EXISTS prevent_log_update
                BEFORE UPDATE ON logs
                BEGIN SELECT RAISE(ABORT, 'Log modification not allowed'); END
            """
            )

            self.connection.commit()
        except Exception as e:
            pass

    def insert_log(
        self,
        session_id: Optional[str],
        log_id: str,
        timestamp: str,
        log_level: str,
        responsible_file: Optional[str],
        message: str,
        status: Optional[int] = None,
        vars_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Insere um log no banco de dados."""
        if not self.connection:
            return

        try:
            cursor = self.connection.cursor()
            log_uuid = str(uuid4())
            vars_json = json.dumps(vars_data) if vars_data else None

            cursor.execute(
                SQL_INSERT_LOG,
                (
                    log_uuid,
                    session_id,
                    log_id,
                    timestamp,
                    log_level,
                    responsible_file,
                    message,
                    status,
                    vars_json,
                ),
            )

            self.connection.commit()
        except Exception as e:
            pass

    def get_logs(
        self,
        session_id: Optional[str] = None,
        log_level: Optional[str] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """Recupera logs do banco de dados."""
        if not self.connection:
            return []

        try:
            cursor = self.connection.cursor()
            query = "SELECT * FROM logs WHERE 1=1"
            params = []

            if session_id:
                query += " AND session_id = ?"
                params.append(session_id)

            if log_level:
                query += " AND log_level = ?"
                params.append(log_level)

            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)
            columns = [description[0] for description in cursor.description]
            rows = cursor.fetchall()

            return [dict(zip(columns, row)) for row in rows]
        except Exception:
            return []

    def export_json(self, session_id: Optional[str] = None) -> str:
        """Exporta logs em formato JSON."""
        logs = self.get_logs(session_id=session_id, limit=10000)

        # Processar vars_data de volta para dict
        for log in logs:
            if log.get("vars"):
                try:
                    log["vars"] = json.loads(log["vars"])
                except:
                    pass

        return json.dumps(logs, indent=2, default=str)

    def cleanup_old_logs(self, days: int = 30) -> int:
        """Remove logs com mais de `days` dias em batches para não segurar o write lock."""
        try:
            conn = sqlite3.connect(str(self.db_path), timeout=10)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("DROP TRIGGER IF EXISTS prevent_log_delete")
            conn.execute("DROP TRIGGER IF EXISTS prevent_log_update")
            conn.commit()

            deleted = 0
            while True:
                cur = conn.execute(
                    "DELETE FROM logs WHERE rowid IN "
                    "(SELECT rowid FROM logs WHERE created_at < datetime('now', ?) LIMIT 5000)",
                    (f"-{days} days",),
                )
                batch = cur.rowcount
                conn.commit()
                deleted += batch
                if batch == 0:
                    break

            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS prevent_log_delete
                BEFORE DELETE ON logs
                BEGIN SELECT RAISE(ABORT, 'Log deletion not allowed'); END
            """
            )
            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS prevent_log_update
                BEFORE UPDATE ON logs
                BEGIN SELECT RAISE(ABORT, 'Log modification not allowed'); END
            """
            )
            conn.commit()
            conn.close()
            return deleted
        except Exception:
            return 0

    def close(self) -> None:
        """Fecha a conexão com o banco de dados."""
        if self.connection:
            self.connection.close()


class LogLevel(str, Enum):
    """Niveis de log disponiveis."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    AUDIT = "audit"  # NEW: Acima de ERROR, sempre impresso.
    CRITICAL = "critical"


class LogStatus(str, Enum):
    """Status de requisicao HTTP."""

    SUCCESS_200 = 200
    CREATED_201 = 201
    BAD_REQUEST_400 = 400
    UNAUTHORIZED_401 = 401
    FORBIDDEN_403 = 403
    NOT_FOUND_404 = 404
    SERVER_ERROR_500 = 500


class Logger:
    """Gerenciador centralizado de logs."""

    _initialized = False  # Previne reinicializacao multipla em hot reload
    _external_server_available = True  # Cache do status do servidor externo
    _last_health_check = 0  # Timestamp do último health check
    _health_check_interval = 30  # Segundos entre health checks
    _connection_warning_shown = False  # Flag para controlar aviso de conexão
    _header_buffer = []  # Buffer para headers de inicialização
    _ws_client = None  # WebSocket client para DevOps
    _devops_server_available = False  # Flag de disponibilidade do servidor DevOps
    _ws_run_id = None  # Run ID para WebSocket

    def __init__(self):
        """Inicializa o logger carregando configs do config.py."""
        # Initialize all attributes to None first - all loaded from .env
        self.config = None
        self.is_initialized = False
        self.log_level = None
        self.log_file = None
        self.db_instance = None
        self.log_format = None
        self.log_storage = None
        self.session_id = str(uuid4())
        self.silence_enabled = False
        self.silence_filters = []
        self.external_logging = None
        self.external_logging_url = "http://localhost:5000/logs/MD70"
        self.clear_terminal = None
        self.is_containered = None
        self.external_only = False
        self.use_session_id = True
        self.use_log_id = True
        self.use_timestamp = True
        self.log_responsible_file = True
        self.environment = None
        self.two_factor_auth = None
        self.sensitive_filter = None
        self.hot_reload = None
        self.db_env = None
        self.db_env_raw = None

        try:
            # 1. CARREGAR CONFIG PRIMEIRAMENTE
            self._load_config()
            self._load_silence_filters()

            # 2. INICIALIZAR BANCO DE DADOS
            self._init_database()

            # 3. CABEÇALHO (antes de limpar terminal!)
            self._print_initialization_config()

            # 4. LIMPAR TERMINAL SE CONFIGURADO (DEPOIS do header!)
            if self.clear_terminal:
                clear_terminal()

            # 5. REGISTRAR CLEANUP AO FINALIZAR
            atexit.register(self._cleanup)

            Logger._initialized = True
        except Exception as e:
            # Log qualquer erro e continue com defaults
            print(f"[WARNING] Logger initialization error: {e}")
            # Apply fallback defaults
            self.environment = self.environment or "production"
            self.log_level = self.log_level or "info"
            self.log_storage = self.log_storage or "file"
            self.log_format = self.log_format or "text"
            self.clear_terminal = self.clear_terminal or False
            self.use_session_id = True
            self.use_log_id = True
            self.use_timestamp = True
            self.log_responsible_file = True
            self.two_factor_auth = self.two_factor_auth or False
            self.sensitive_filter = self.sensitive_filter or True
            self.hot_reload = self.hot_reload or False
            self.db_env = self.db_env or "local"
            self.db_env_raw = self.db_env_raw or "local"
            self.external_logging = self.external_logging or False
            self.is_containered = self.is_containered or False

    def _check_external_server_health(self) -> bool:
        """Verifica se o servidor externo está disponível."""
        current_time = time.time()

        # Verificar cache para evitar checks frequentes
        if current_time - Logger._last_health_check < Logger._health_check_interval:
            return Logger._external_server_available

        Logger._last_health_check = current_time

        try:
            # Primeiro verifica se a API de health está respondendo
            response = requests.get(
                "http://localhost:5000/api/health",
                timeout=3,  # Timeout curto para health check
            )

            # Verifica se a resposta é bem-sucedida
            if response.status_code == 200:
                Logger._external_server_available = True
                return True
            else:
                Logger._external_server_available = False
                return False

        except requests.exceptions.RequestException:
            Logger._external_server_available = False
            return False
        except Exception:
            Logger._external_server_available = False
            return False

    def _load_config(self) -> None:
        """Carrega configuracoes do Settings.py que lê do .env"""
        try:
            # Usar Settings.load_config() que é responsável por carregar .env
            from App.Core.Settings.Settings import load_config

            settings = load_config()
            print(f"[DEBUG] Settings loaded, log_level={settings.get('log_level')}")

            # Extrair apenas as configurações de log do settings
            self.config = {
                "log_level": settings.get("log_level"),
                "log_storage": settings.get("log_storage", "database"),
                "log_format": settings.get("log_format", "text"),
                "environment": settings.get("environment", "development"),
                "session_id": settings.get("session_id", True),
                "log_id": settings.get("log_id", True),
                "log_timestamp": settings.get("log_timestamp", True),
                "log_responsible_file": settings.get("log_responsible_file", True),
                "clear_terminal": settings.get("clear_terminal", False),
                "hot_reload": settings.get("hot_reload", False),
                "two_factor_auth": settings.get("two_factor_auth", False),
                "sensitive_filter": settings.get("sensitive_filter", True),
                "db_env": settings.get("db_env", "local"),
                "is_containered": settings.get("is_containered", False),
                "external_logging": settings.get("external_logging", False),
            }
            print(
                f"[DEBUG] Config loaded from Settings: log_level={self.config.get('log_level')}, clear_terminal={self.config.get('clear_terminal')}"
            )

            # Atribuir configurações após carregar com sucesso
            self.log_level = self.config.get("log_level", "info").lower()
            self.log_storage = self.config.get("log_storage", "database").lower()
            self.log_format = self.config.get("log_format", "text").lower()
            self.environment = self.config.get("environment", "development").lower()
            self.use_session_id = self.config.get("session_id", True)
            self.use_log_id = self.config.get("log_id", True)
            self.use_timestamp = self.config.get("log_timestamp", True)
            self.log_responsible_file = self.config.get("log_responsible_file", True)
            self.clear_terminal = self.config.get("clear_terminal", False)
            self.hot_reload = self.config.get("hot_reload", False)
            self.two_factor_auth = self.config.get("two_factor_auth", False)
            self.sensitive_filter = self.config.get("sensitive_filter", True)
            self.db_env = self.config.get("db_env", "local").lower()
            self.db_env_raw = self.db_env
            self.is_containered = self.config.get("is_containered", False)
            self.external_logging = self.config.get("external_logging", False)
            self.is_initialized = True

        except Exception as e:
            # Fallback se Settings não conseguir carregar
            import os

            print(f"[WARNING] Failed to load config from Settings: {e}")
            import traceback

            print(f"[WARNING] Traceback: {traceback.format_exc()}")
            self.config = {
                "log_level": os.environ.get("LOG_LEVEL"),
                "log_storage": os.environ.get("LOG_STORAGE") or "database",
                "log_format": os.environ.get("LOG_FORMAT") or "text",
                "environment": os.environ.get("ENVIRONMENT") or "development",
                "session_id": os.environ.get("SESSION_ID", "true") == "true",
                "log_id": os.environ.get("LOG_ID", "on") == "on",
                "log_timestamp": os.environ.get("LOG_TIMESTAMP", "on") == "on",
                "log_responsible_file": os.environ.get("LOG_RESPONSIBLE_FILE", "on")
                == "on",
                "clear_terminal": os.environ.get("CLEAR_TERMINAL", "true") == "true",
            }
            print(
                f"[WARNING] Using fallback config: log_level={self.config.get('log_level')}, clear_terminal={self.config.get('clear_terminal')}"
            )

            # Extrair configuracoes de log - sem fallback
            log_level_raw = self.config.get("log_level") or self.config.get("LOG_LEVEL")
            print(f"[DEBUG] log_level_raw from config: {log_level_raw}")
            if not log_level_raw:
                raise ValueError(
                    "LOG_LEVEL must be configured in .env (debug, info, warning, error, critical)"
                )
            self.log_level = log_level_raw.lower()
            print(f"[DEBUG] self.log_level set to: {self.log_level}")
            if self.log_level not in ["critical", "info", "debug", "warning", "error"]:
                raise ValueError(
                    f"Invalid LOG_LEVEL '{log_level_raw}'. Must be: debug, info, warning, error, critical"
                )

            session_id_val = self.config.get("session_id")
            if session_id_val is None:
                raise ValueError("SESSION_ID must be configured in .env")
            self.use_session_id = (
                session_id_val
                if isinstance(session_id_val, bool)
                else str(session_id_val).lower() == "true"
            )

            log_id_val = self.config.get("log_id")
            if log_id_val is None:
                raise ValueError("LOG_ID must be configured in .env")
            self.use_log_id = (
                log_id_val
                if isinstance(log_id_val, bool)
                else str(log_id_val).lower() == "true"
            )

            timestamp_val = self.config.get("log_timestamp")
            if timestamp_val is None:
                raise ValueError("LOG_TIMESTAMP must be configured in .env")
            self.use_timestamp = (
                timestamp_val
                if isinstance(timestamp_val, bool)
                else str(timestamp_val).lower() == "true"
            )

            responsible_val = self.config.get("log_responsible_file")
            if responsible_val is None:
                raise ValueError("LOG_RESPONSIBLE_FILE must be configured in .env")
            self.log_responsible_file = (
                responsible_val
                if isinstance(responsible_val, bool)
                else str(responsible_val).lower() == "true"
            )

            clear_terminal_val = self.config.get("clear_terminal")
            print(f"[DEBUG] clear_terminal_val from config: {clear_terminal_val}")
            if clear_terminal_val is None:
                raise ValueError("CLEAR_TERMINAL must be configured in .env")
            self.clear_terminal = (
                clear_terminal_val
                if isinstance(clear_terminal_val, bool)
                else str(clear_terminal_val).lower() == "true"
            )
            print(f"[DEBUG] self.clear_terminal set to: {self.clear_terminal}")

            log_storage = self.config.get("log_storage") or self.config.get(
                "LOG_STORAGE"
            )
            if not log_storage:
                raise ValueError(
                    "LOG_STORAGE must be configured in .env (file, database, or both)"
                )
            self.log_storage = log_storage.lower()

            log_format = self.config.get("log_format") or self.config.get("LOG_FORMAT")
            if not log_format:
                raise ValueError("LOG_FORMAT must be configured in .env (text or json)")
            self.log_format = log_format.lower()

            environment = self.config.get("environment") or self.config.get(
                "ENVIRONMENT"
            )
            if not environment:
                raise ValueError(
                    "ENVIRONMENT must be configured in .env (development or production)"
                )
            self.environment = environment.lower()

            # Additional attributes for print_initialization_config
            self.two_factor_auth = self.config.get("two_factor_auth", False)
            if isinstance(self.two_factor_auth, str):
                self.two_factor_auth = self.two_factor_auth.lower() == "true"

            self.sensitive_filter = self.config.get("sensitive_filter", True)
            if isinstance(self.sensitive_filter, str):
                self.sensitive_filter = self.sensitive_filter.lower() == "true"

            self.hot_reload = self.config.get("hot_reload", False)
            if isinstance(self.hot_reload, str):
                self.hot_reload = self.hot_reload.lower() == "true"

            self.db_env = self.config.get("db_env", "local")
            if isinstance(self.db_env, str):
                self.db_env = self.db_env.lower()
            self.db_env_raw = self.db_env

            self.is_containered = self.config.get("is_containered", False)
            if isinstance(self.is_containered, str):
                self.is_containered = self.is_containered.lower() == "true"

            self.external_logging = self.config.get("external_logging", False)
            if isinstance(self.external_logging, str):
                self.external_logging = self.external_logging.lower() == "true"

            self.is_initialized = True

        except Exception as e:
            # Set fallback defaults when config loading fails
            self.silence_enabled = False
            self.external_logging = False
            self.sensitive_filter = True
            self.clear_terminal = False
            self.is_containered = False
            self.log_storage = "file"
            self.log_format = "text"
            self.db_env = "local"
            self.db_env_raw = "local"
            self.security_filters_config = {}
            self.security_silence_system = False
            self.environment = "production"
            self.is_initialized = False

    def _load_silence_filters(self) -> None:
        """Carrega as strings de silence do arquivo .silence em TODA inicialização."""
        try:
            silence_file = Path(__file__).parent / SILENCE_FILENAME

            if not silence_file.exists():
                self.silence_filters = []
                return

            with open(silence_file, "r", encoding="utf-8") as f:
                lines = f.readlines()

            # Filtrar linhas vazias e comentários - SEMPRE carregar
            self.silence_filters = [
                line.strip()
                for line in lines
                if line.strip() and not line.strip().startswith("#")
            ]

        except Exception as e:
            self.silence_filters = []

    def _init_database(self) -> None:
        """Inicializa o banco de dados SQLite para logs."""
        try:
            LOGS_BASE_DIR.mkdir(parents=True, exist_ok=True)
            self.db_instance = LogDatabase(DB_FILE)
            # Cleanup em background para não bloquear o startup
            threading.Thread(target=self._cleanup_old_logs_bg, daemon=True).start()
        except Exception as e:
            self.db_instance = None

    def _cleanup_old_logs_bg(self) -> None:
        """Executa limpeza de logs antigos em background."""
        try:
            deleted = self.db_instance.cleanup_old_logs(days=30)
            if deleted:
                print(f"[Logs] Cleanup: {deleted} logs com mais de 30 dias removidos.")
        except Exception:
            pass

    def _cleanup(self) -> None:
        """Limpa recursos ao finalizar."""
        if self.db_instance:
            self.db_instance.close()

    def _setup_log_file(self) -> None:
        """Cria pasta logs na raiz e abre arquivo de log para sessao."""
        try:
            # Criar pasta logs
            LOGS_BASE_DIR.mkdir(parents=True, exist_ok=True)

            # Criar arquivo de log com nome: <timestamp>_logs_<session_id>.txt
            timestamp = datetime.now().strftime(LOG_TIMESTAMP_PATTERN)
            current_session_id = get_session_id() or "N/A"

            log_filename = LOG_FILE_NAME_PATTERN.format(
                timestamp=timestamp,
                session_id=(
                    current_session_id[:8]
                    if current_session_id != "N/A"
                    else uuid4().hex[:8]
                ),
            )

            self.log_file = LOGS_BASE_DIR / log_filename

            # Escrever cabecalho no arquivo
            db_env_str = f"{(self.db_env or 'local').upper()}"
            if self.db_env and self.db_env == "hybrid":
                db_env_str += f" ({self.db_env_raw or 'N/A'})"

            header = LOG_SESSION_HEADER.format(
                session_id=current_session_id,
                start_time=datetime.now().isoformat(),
                log_level=(self.log_level or "info").upper(),
                db_env=db_env_str,
                log_file=self.log_file,
                external_logging="ON" if self.external_logging else "OFF",
            )

            with open(self.log_file, "w", encoding="utf-8") as f:
                f.write(header)

        except Exception as e:
            self.log_file = None

    def _send_to_external_server(
        self,
        formatted_message: str,
        level: Optional[str] = None,
        message: Optional[str] = None,
        status: Optional[int] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Envia o log para o servidor externo e para o DevOps se ativado."""
        # Sempre tenta enviar para o DevOps via WebSocket se estiver conectado
        self._send_to_devops_ws(
            formatted_message, level=level, message=message, status=status, data=data
        )

        if not self.external_logging:
            return

        # Verificar saúde do servidor antes de tentar enviar
        if not self._check_external_server_health():
            # Se servidor não estiver disponível, não tenta enviar
            return

        try:
            # Se usar JSON, enviar estruturado dentro do campo message
            if self.log_format == "json" and level and message is not None:
                log_entry = {
                    "session_id": self.session_id,
                    "log_id": self._get_log_id(),
                    "timestamp": datetime.now().isoformat(),
                    "log_level": level,
                    "responsible_file": None,
                    "message": message,
                    "status": status,
                    "vars": data,
                }
                log_data = {
                    "application": "MD70",
                    "message": json.dumps(
                        log_entry, ensure_ascii=False, indent=2, default=str
                    ),
                    "timestamp": datetime.now().isoformat(),
                }
            else:
                # Fallback para texto
                log_data = {
                    "application": "MD70",
                    "message": formatted_message,
                    "timestamp": datetime.now().isoformat(),
                    "session_id": self.session_id,
                    "request_id": get_request_id(),
                    "level": self._get_log_level_from_message(formatted_message),
                }

            # Enviar via POST para o servidor externo
            response = requests.post(
                self.external_logging_url,
                json=log_data,
                timeout=2,  # Timeout curto para não bloquear a aplicação
            )

            # Se resposta não for bem-sucedida, marcar servidor como indisponível
            if response.status_code not in [200, 201]:
                Logger._external_server_available = False
                Logger._last_health_check = time.time()  # Forçar novo health check

        except requests.exceptions.RequestException as e:
            # Se ocorrer erro de conexão, marcar servidor como indisponível
            Logger._external_server_available = False
            Logger._last_health_check = time.time()  # Forçar novo health check

        except Exception:
            # Capturar qualquer outra exceção silenciosamente
            pass

    def _send_to_devops_ws(
        self,
        formatted_message: str,
        level: Optional[str] = None,
        message: Optional[str] = None,
        status: Optional[int] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Envia o log para o ZeraDevOps via WebSocket."""
        if not Logger._devops_server_available or not Logger._ws_client:
            return

        try:
            # Se usar JSON, enviar como string JSON dentro do campo message
            if self.log_format == "json":
                log_entry = {
                    "session_id": self.session_id,
                    "log_id": self._get_log_id(),
                    "timestamp": datetime.now().isoformat(),
                    "log_level": level
                    or self._get_log_level_from_message(formatted_message),
                    "responsible_file": None,
                    "message": message or formatted_message,
                    "status": status,
                    "vars": data,
                }
                # Enviar JSON formatado dentro de um único campo "message"
                log_data = {
                    "message": json.dumps(
                        log_entry, ensure_ascii=False, indent=2, default=str
                    ),
                    "run_id": Logger._ws_run_id,
                }
            else:
                # Fallback para texto
                log_data = {
                    "message": formatted_message,
                    "level": self._get_log_level_from_message(formatted_message),
                    "run_id": Logger._ws_run_id,
                }
            Logger._ws_client.send(json.dumps(log_data))
        except Exception:
            # Se falhar, marca como indisponível para o próximo loop de reconexão tratar
            Logger._devops_server_available = False

    def _get_log_id(self) -> str:
        """Obtém o log_id atual (request_id ou novo UUID)."""
        return get_request_id() or str(uuid4())[:8]

    def _get_log_level_from_message(self, formatted_message: str) -> str:
        """Extrai o nível do log da mensagem formatada usando LEVEL_TAGS."""
        for level_name, tag in LEVEL_TAGS.items():
            if tag in formatted_message:
                return level_name
        return "info"

    def _print_initialization_config(self) -> None:
        """Printa as configuracoes carregadas na inicializacao."""
        # Print initialization config (only once during first init)
        print(
            f"[DEBUG] _print_initialization_config called, is_initialized={self.is_initialized}"
        )

        # Obter path relativo do arquivo Logs.py
        logs_file_path = Path(__file__).resolve()
        try:
            from App.Core.Settings.Settings import BASE_DIR

            relative_path = logs_file_path.relative_to(BASE_DIR)
            module_path = (
                "."
                + str(relative_path)
                .replace("\\", ".")
                .replace("/", ".")
                .replace(".py", "")
                + ".py"
            )
        except:
            module_path = str(logs_file_path)

        def log_line(line: str = ""):
            # SEMPRE guarda no buffer para o DevOps (será enviado assim que o WS conectar)
            Logger._header_buffer.append(line)

            if self.external_only:
                # Envia via WS se já estiver disponível (mensagens de inicialização)
                if Logger._ws_client and Logger._devops_server_available:
                    try:
                        log_data = {
                            "message": line,
                            "level": "info",
                            "run_id": Logger._ws_run_id,
                        }
                        Logger._ws_client.send(json.dumps(log_data))
                    except:
                        pass
            else:
                # Modo LOCAL exclusivo: Printa no console e escreve no arquivo
                print(line)
                if self.log_file:
                    try:
                        with open(self.log_file, "a", encoding="utf-8") as f:
                            f.write(line + "\n")
                    except:
                        pass

        log_line("\n" + "=" * 60)
        log_line(f"Logs File: {module_path}")
        log_line("=" * 60)
        log_line("LOG SETTINGS")
        log_line("=" * 60)

        level_desc = {
            "critical": "Apenas erros críticos",
            "info": "Informações essenciais",
            "debug": "Modo detalhado (todos os logs)",
        }
        log_line(
            f"  Log Level:        {(self.log_level or 'info').upper()} - {level_desc.get(self.log_level, '?')}"
        )
        log_line(f"  Log Storage:      {self.log_storage}")
        log_line(f"  Log Format:       {self.log_format}")

        session_id_log_status = "ON" if self.use_session_id else "OFF"
        log_line(f"  Session ID:       {session_id_log_status} - {self.session_id}")

        log_line(f"  Log ID:           {'ON' if self.use_log_id else 'OFF'}")
        log_line(f"  Timestamp:        {'ON' if self.use_timestamp else 'OFF'}")
        log_line(f"  Responsible File: {'ON' if self.log_responsible_file else 'OFF'}")
        log_line(f"  External Logging: {'ON' if self.external_logging else 'OFF'}")

        silence_status = "ON" if self.silence_enabled else "OFF"
        filter_count = len(self.silence_filters) if self.silence_enabled else 0
        log_line(
            f"  Silence System:   {silence_status} ({filter_count} filtros carregados)"
        )
        log_line(f"  Clear Terminal:   {'ON' if self.clear_terminal else 'OFF'}")

        log_line("=" * 60)
        log_line("SECURITY SETTINGS")
        log_line("=" * 60)

        log_line(f"  Environment:      {(self.environment or 'production').upper()}")
        log_line(f"  2FA:              {'ON' if self.two_factor_auth else 'OFF'}")
        log_line(f"  Security Filter:  {'ON' if self.sensitive_filter else 'OFF'}")
        log_line(f"  Hot Reload:       {'ON' if self.hot_reload else 'OFF'}")

        if self.db_env and self.db_env == "hybrid":
            log_line(
                f"  DB Environment:   {(self.db_env or 'local').upper()} ({self.db_env_raw or 'N/A'})"
            )
        else:
            log_line(f"  DB Environment:   {(self.db_env or 'local').upper()}")

        log_line(f"  Is Containered:   {'ON' if self.is_containered else 'OFF'}")

        if self.environment == "production":
            log_line(MSG_PRODUCTION_MODE)
            blocking_conditions = []
            if self.log_level not in ["warning", "error", "critical"]:
                blocking_conditions.append(
                    MSG_BLOCK_LOG_LEVEL.format(level=self.log_level)
                )
            if self.external_logging:
                blocking_conditions.append(MSG_BLOCK_EXTERNAL)
            if not self.sensitive_filter:
                blocking_conditions.append(MSG_BLOCK_SECURITY)

            if blocking_conditions:
                for condition in blocking_conditions:
                    log_line(f"  ! {condition}")
            else:
                log_line(MSG_PRODUCTION_OK)

        log_line("=" * 60 + "\n")

    def _write_to_log_file(self, formatted_message: str) -> None:
        """Escreve mensagem formatada no arquivo de log."""
        if not self.log_file:
            return
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(formatted_message + "\n")
        except Exception as e:
            pass

    def _save_to_database(
        self,
        level: str,
        message: str,
        status: Optional[int] = None,
        data: Optional[Dict[str, Any]] = None,
        responsible_file: Optional[str] = None,
    ) -> None:
        """Salva o log no banco de dados SQLite."""
        if not self.db_instance:
            return

        try:
            now = datetime.now()
            timestamp = (
                now.strftime(TIMESTAMP_FORMAT) + f".{now.microsecond // 100:04d}"
            )
            log_id = get_request_id() or str(uuid4())[:8]

            self.db_instance.insert_log(
                session_id=self.session_id,
                log_id=log_id,
                timestamp=timestamp,
                log_level=level,
                responsible_file=responsible_file,
                message=message,
                status=status,
                vars_data=data,
            )
        except Exception as e:
            pass

    def _print_log(
        self,
        level: str,
        message: str,
        status: Optional[int] = None,
        data: Optional[Dict[str, Any]] = None,
        responsible_file: Optional[str] = None,
    ) -> None:
        """Printa log em console conforme log_format."""
        try:
            now = datetime.now()
            timestamp = (
                now.strftime(TIMESTAMP_FORMAT) + f".{now.microsecond // 100:04d}"
            )
            log_id = get_request_id() or str(uuid4())[:8]

            if self.log_format == "json":
                # Printa JSON estruturado
                log_entry = {
                    "session_id": self.session_id,
                    "log_id": log_id,
                    "timestamp": timestamp,
                    "log_level": level,
                    "responsible_file": responsible_file,
                    "message": message,
                    "status": status,
                    "vars": data,
                }
                print(json.dumps(log_entry, ensure_ascii=False, indent=2, default=str))
            else:
                # Printa em texto formatado (mantém lógica antiga)
                parts = []
                if self.use_timestamp:
                    parts.append(f"[{timestamp}]")
                if self.use_session_id:
                    parts.append(f"[{self.session_id}]")
                if self.use_log_id:
                    parts.append(f"[{log_id}]")
                if self.log_responsible_file and responsible_file:
                    parts.append(f"[{responsible_file}]")
                parts.append(f"[{level}]")
                parts.append(message)
                if status is not None:
                    parts.append(f"[HTTP {status}]")
                if data:
                    data_str = " | ".join(f"{k}={v}" for k, v in data.items())
                    parts.append(f"| {data_str}")
                print(" ".join(parts))
        except Exception as e:
            pass

    def _is_silenced(self, formatted_message: str) -> bool:
        """Verifica se o log deve ser silenciado baseado no arquivo .silence."""
        if not self.silence_enabled or not self.silence_filters:
            return False

        # Verificar se alguma string de silence está na mensagem formatada
        for filter_str in self.silence_filters:
            if filter_str in formatted_message:
                return True

        return False

    def _should_print(self, level: LogLevel, status: Optional[int] = None) -> bool:
        """
        Determina se o log deve ser impresso baseado em log_level.
        Hierarquia: DEBUG < INFO < WARNING < ERROR < AUDIT < CRITICAL
        """
        # Se external logging está ON, não printamos no console (envia para servidor)
        if self.external_logging:
            return False

        # AUDIT e CRITICAL sempre são impressos se não houver external logging
        if level in [LogLevel.AUDIT, LogLevel.CRITICAL]:
            return True

        # Debug mode: printa tudo (all levels)
        if self.log_level == "debug":
            return True

        # Info mode: printa INFO (se essencial), WARNING, ERROR, CRITICAL
        if self.log_level == "info":
            if level == LogLevel.DEBUG:
                return False
            if level == LogLevel.INFO:
                # For INFO level, only print if status is None or status >= 400
                return status is None or (status is not None and status >= 400)
            # For WARNING, ERROR, CRITICAL, always print
            return True

        # Warning mode: printa WARNING, ERROR, CRITICAL (não DEBUG, não INFO)
        if self.log_level == "warning":
            if level in [LogLevel.DEBUG, LogLevel.INFO]:
                return False
            # For WARNING, ERROR, CRITICAL, always print
            return True

        # Error mode: printa ERROR, CRITICAL (não DEBUG, INFO, WARNING)
        if self.log_level == "error":
            if level in [LogLevel.DEBUG, LogLevel.INFO, LogLevel.WARNING]:
                return False
            # For ERROR, CRITICAL, always print
            return True

        # Critical mode: apenas CRITICAL
        if self.log_level == "critical":
            if level != LogLevel.CRITICAL:
                return False
            # CRITICAL sempre é impresso
            return True

        return True

    def _get_caller_file(self) -> Optional[str]:
        """Obtem o arquivo que chamou o logger com caminho relativo em formato .App.Core.Example.file"""
        try:
            # Usar sys._getframe para evitar problemas com inspect.stack() durante hot reload
            frame = None
            try:
                # Pula frames: _get_caller_file, _format_log, metodo de log (debug/info/etc)
                for i in range(3, 15):  # Limita a busca a 15 frames
                    try:
                        f = sys._getframe(i)
                        filename = f.f_code.co_filename

                        # Pular arquivos do logger
                        if "Logs.py" not in filename and "__pycache__" not in filename:
                            # Obter caminho relativo a partir do ÚLTIMO "App" (dentro de services/backend)
                            path = Path(filename)
                            try:
                                # Procurar pelo último diretório "App" no caminho
                                parts = path.parts
                                if "App" in parts:
                                    # Encontrar o ÚLTIMO índice de "App" (a partir do final do caminho)
                                    app_indices = [
                                        idx
                                        for idx, part in enumerate(parts)
                                        if part == "App"
                                    ]
                                    if app_indices:
                                        app_idx = app_indices[
                                            -1
                                        ]  # Pegar o último índice
                                        relative_parts = list(
                                            parts[app_idx:]
                                        )  # Incluir "App"
                                        # Remover extensão .py do último arquivo
                                        if relative_parts and relative_parts[
                                            -1
                                        ].endswith(".py"):
                                            relative_parts[-1] = relative_parts[-1][
                                                :-3
                                            ]  # Remove ".py"
                                        # Retornar em formato .App.Core.Example.file
                                        return "." + ".".join(relative_parts)
                            except (ValueError, IndexError):
                                pass
                            # Se não encontrar App, retornar apenas o nome do arquivo
                            return path.name
                    except ValueError:
                        # Fim da stack
                        break
            except Exception:
                pass
            return None
        except Exception:
            return None

    def _format_log(
        self,
        level: LogLevel,
        message: str,
        status: Optional[int] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Formata a mensagem de log."""
        # Construir partes da mensagem
        parts = []

        # Timestamp (se ativado)
        if self.use_timestamp:
            now = datetime.now()
            timestamp = (
                now.strftime(TIMESTAMP_FORMAT) + f".{now.microsecond // 100:04d}"
            )
            parts.append(f"[{timestamp}]")

        # Session ID (se ativado para log)
        if self.use_session_id:
            current_session_id = get_session_id()  # NEW: Obter session_id da ContextVar
            if current_session_id:
                parts.append(f"[{current_session_id}]")

        # Log ID (Request ID)
        if self.use_log_id:
            log_id = get_request_id()
            if not log_id:
                # Se não houver ID de requisição no contexto, gera um ID único para este log
                log_id = str(uuid4())[:8]
            parts.append(f"[{log_id}]")

        # Arquivo responsavel (se ativado)
        if self.log_responsible_file:
            caller_file = self._get_caller_file()
            if caller_file:
                parts.append(f"[{caller_file}]")

        # Level (sem debug literal em logs normais)
        level_tag = LEVEL_TAGS.get(level.value, f"[{level.value.upper()}]")
        parts.append(level_tag)

        # Message
        parts.append(message)

        # Status (se fornecido)
        if status is not None:
            parts.append(HTTP_STATUS_FORMAT.format(status=status))

        # Data extra (se fornecida)
        if data:
            data_str = DATA_SEPARATOR.join(f"{k}={v}" for k, v in data.items())
            parts.append(f"| {data_str}")

        return " ".join(parts)

    def debug(
        self,
        message: str,
        status: Optional[int] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log de DEBUG."""
        caller_file = self._get_caller_file()

        # Salvar no banco de dados
        self._save_to_database(
            level="DEBUG",
            message=message,
            status=status,
            data=data,
            responsible_file=caller_file,
        )

        # Printar no console
        formatted = self._format_log(LogLevel.DEBUG, message, status, data)
        if self._should_print(LogLevel.DEBUG, status) and not self._is_silenced(
            formatted
        ):
            self._print_log("DEBUG", message, status, data, caller_file)

        self._send_to_external_server(
            formatted, level="DEBUG", message=message, status=status, data=data
        )

    def info(
        self,
        message: str,
        status: Optional[int] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log de INFO."""
        caller_file = self._get_caller_file()

        # Salvar no banco de dados
        self._save_to_database(
            level="INFO",
            message=message,
            status=status,
            data=data,
            responsible_file=caller_file,
        )

        # Printar no console
        formatted = self._format_log(LogLevel.INFO, message, status, data)
        if self._should_print(LogLevel.INFO, status) and not self._is_silenced(
            formatted
        ):
            self._print_log("INFO", message, status, data, caller_file)

        self._send_to_external_server(
            formatted, level="INFO", message=message, status=status, data=data
        )

    def warning(
        self,
        message: str,
        status: Optional[int] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log de WARNING."""
        caller_file = self._get_caller_file()

        # Salvar no banco de dados
        self._save_to_database(
            level="WARNING",
            message=message,
            status=status,
            data=data,
            responsible_file=caller_file,
        )

        # Printar no console
        formatted = self._format_log(LogLevel.WARNING, message, status, data)
        if self._should_print(LogLevel.WARNING, status) and not self._is_silenced(
            formatted
        ):
            self._print_log("WARNING", message, status, data, caller_file)

        self._send_to_external_server(
            formatted, level="WARNING", message=message, status=status, data=data
        )

    def error(
        self,
        message: str,
        status: Optional[int] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log de ERROR."""
        caller_file = self._get_caller_file()

        # Salvar no banco de dados
        self._save_to_database(
            level="ERROR",
            message=message,
            status=status,
            data=data,
            responsible_file=caller_file,
        )

        # Printar no console
        formatted = self._format_log(LogLevel.ERROR, message, status, data)
        if self._should_print(LogLevel.ERROR, status) and not self._is_silenced(
            formatted
        ):
            self._print_log("ERROR", message, status, data, caller_file)

        self._send_to_external_server(
            formatted, level="ERROR", message=message, status=status, data=data
        )

    def critical(
        self,
        message: str,
        status: Optional[int] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log de CRITICAL."""
        caller_file = self._get_caller_file()

        # Salvar no banco de dados
        self._save_to_database(
            level="CRITICAL",
            message=message,
            status=status,
            data=data,
            responsible_file=caller_file,
        )

        # Printar no console
        formatted = self._format_log(LogLevel.CRITICAL, message, status, data)
        if self._should_print(LogLevel.CRITICAL, status) and not self._is_silenced(
            formatted
        ):
            self._print_log("CRITICAL", message, status, data, caller_file)

        self._send_to_external_server(
            formatted, level="CRITICAL", message=message, status=status, data=data
        )

    def audit(
        self,
        message: str,
        status: Optional[int] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log de AUDIT - Sempre impresso, para conformidade."""
        caller_file = self._get_caller_file()

        # Salvar no banco de dados
        self._save_to_database(
            level="AUDIT",
            message=message,
            status=status,
            data=data,
            responsible_file=caller_file,
        )

        # Printar no console
        formatted = self._format_log(LogLevel.AUDIT, message, status, data)
        # Nota: AUDIT sempre passa pelos filtros de nível
        if not self._is_silenced(formatted):
            self._print_log("AUDIT", message, status, data, caller_file)

        self._send_to_external_server(
            formatted, level="AUDIT", message=message, status=status, data=data
        )

    def http(
        self,
        method: str,
        endpoint: str,
        status: int,
        duration_ms: float = 0,
        extra_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log de requisicao HTTP."""
        message = f"{method} {endpoint}"
        data = {"duration_ms": duration_ms}

        if extra_data:
            data.update(extra_data)

        # Determinar nivel baseado em status
        if status in [200, 201]:
            self.info(f"{message}", status, data)
        elif status in [400, 401, 403, 404]:
            self.warning(f"{message}", status, data)
        else:  # 500+
            self.error(f"{message}", status, data)

    def get_log_file_path(self) -> Optional[str]:
        """Retorna o caminho do arquivo de log da sessao."""
        return str(self.log_file) if self.log_file else None


# Instancia global do logger
_logger_instance = None
_logger_created = False


def get_logger() -> Logger:
    """Obtem a instancia global do logger (singleton)."""
    global _logger_instance, _logger_created

    # Criar nova instancia apenas se nao existir
    if _logger_instance is None:
        try:
            _logger_instance = Logger()
            _logger_created = True
        except Exception as e:
            # Fallback: se Logger falhar, usa stdlib logging
            import logging

            logging.basicConfig(level=logging.INFO)
            print(f"[WARNING] Failed to initialize Logger: {e}")

            # Retorna um mock logger
            class MockLogger:
                def debug(self, msg, *args, **kwargs):
                    logging.debug(msg)

                def info(self, msg, *args, **kwargs):
                    logging.info(msg)

                def warning(self, msg, *args, **kwargs):
                    logging.warning(msg)

                def error(self, msg, *args, **kwargs):
                    logging.error(msg)

                def critical(self, msg, *args, **kwargs):
                    logging.critical(msg)

                def http(self, *args, **kwargs):
                    pass

            _logger_instance = MockLogger()

    return _logger_instance


# Aliases para facil acesso
def debug(
    message: str, status: Optional[int] = None, data: Optional[Dict[str, Any]] = None
) -> None:
    """Log de DEBUG."""
    get_logger().debug(message, status, data)


def info(
    message: str, status: Optional[int] = None, data: Optional[Dict[str, Any]] = None
) -> None:
    """Log de INFO."""
    get_logger().info(message, status, data)


def warning(
    message: str, status: Optional[int] = None, data: Optional[Dict[str, Any]] = None
) -> None:
    """Log de WARNING."""
    get_logger().warning(message, status, data)


def error(
    message: str, status: Optional[int] = None, data: Optional[Dict[str, Any]] = None
) -> None:
    """Log de ERROR."""
    get_logger().error(message, status, data)


def critical(
    message: str, status: Optional[int] = None, data: Optional[Dict[str, Any]] = None
) -> None:
    """Log de CRITICAL."""
    get_logger().critical(message, status, data)


def audit(
    message: str, status: Optional[int] = None, data: Optional[Dict[str, Any]] = None
) -> None:
    """Log de AUDIT."""
    get_logger().audit(message, status, data)


def http(
    method: str,
    endpoint: str,
    status: int,
    duration_ms: float = 0,
    extra_data: Optional[Dict[str, Any]] = None,
) -> None:
    """Log de requisicao HTTP."""
    get_logger().http(method, endpoint, status, duration_ms, extra_data)


def log_by_level(
    message: str, status: Optional[int] = None, data: Optional[Dict[str, Any]] = None
) -> None:
    """
    Log adaptativo baseado no nível de logging configurado.

    Se log_level == 'debug': usa debug()
    Se log_level == 'info' ou acima: usa info()

    Útil para logs que devem ser show em DEBUG mas também em INFO.
    """
    logger = get_logger()
    if logger.log_level == "debug":
        debug(message, status, data)
    else:
        info(message, status, data)


# NEW: Funções globais para session_id e log_file_path
# Funções set_session_id e get_session_id já foram definidas no topo do arquivo.
def get_log_file_path() -> Optional[str]:
    """Retorna o caminho do arquivo de log da sessao."""
    return get_logger().get_log_file_path()


def get_logs_from_database(
    session_id: Optional[str] = None, log_level: Optional[str] = None, limit: int = 1000
) -> List[Dict[str, Any]]:
    """Recupera logs do banco de dados SQLite."""
    logger = get_logger()
    if not logger.db_instance:
        return []
    return logger.db_instance.get_logs(
        session_id=session_id, log_level=log_level, limit=limit
    )


def export_logs_json(session_id: Optional[str] = None) -> str:
    """Exporta logs em formato JSON."""
    logger = get_logger()
    if not logger.db_instance:
        return json.dumps([], indent=2)
    return logger.db_instance.export_json(session_id=session_id)


def export_logs_table(session_id: Optional[str] = None, limit: int = 100) -> str:
    """Exporta logs em formato tabela (ASCII)."""
    logs = get_logs_from_database(session_id=session_id, limit=limit)
    if not logs:
        return "Nenhum log encontrado."

    # Calcular largura das colunas
    columns = ["timestamp", "level", "file", "message", "status"]
    col_widths = {col: len(col) for col in columns}

    for log in logs:
        col_widths["timestamp"] = max(
            col_widths["timestamp"], len(str(log.get("timestamp", "")))
        )
        col_widths["level"] = max(
            col_widths["level"], len(str(log.get("log_level", "")))
        )
        col_widths["file"] = max(
            col_widths["file"], len(str(log.get("responsible_file", "") or ""))
        )
        msg = str(log.get("message", ""))
        col_widths["message"] = max(col_widths["message"], min(len(msg), 50))
        col_widths["status"] = max(
            col_widths["status"], len(str(log.get("status", "") or ""))
        )

    # Limitar mensagem
    for col in col_widths:
        if col != "message":
            col_widths[col] = min(col_widths[col], 30)

    # Header
    header = " | ".join(col.upper().ljust(col_widths[col]) for col in columns)
    separator = "-" * len(header)

    lines = [separator, header, separator]

    # Rows
    for log in logs:
        row = " | ".join(
            str(
                log.get(
                    {
                        "timestamp": "timestamp",
                        "level": "log_level",
                        "file": "responsible_file",
                        "message": "message",
                        "status": "status",
                    }[col],
                    "",
                )
                or ""
            ).ljust(col_widths[col])[: col_widths[col]]
            for col in columns
        )
        lines.append(row)

    lines.append(separator)
    return "\n".join(lines)

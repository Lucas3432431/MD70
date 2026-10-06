import json
import uuid
import os
import time
import sys
import redis
import threading
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum
from dataclasses import dataclass, asdict, fields
from App.Core.Settings.Settings import load_config
from App.Core.Logs import info, debug, warning, error

# CRITICAL: Use os._exit() instead of sys.exit() for thread-safe termination
# When called from worker threads, sys.exit() only kills that thread
# os._exit() kills the entire process, ensuring FastAPI dies and gets restarted


class OperationType(Enum):
    # Message processing (critical, high priority)
    MESSAGE = "message"  # User or AI message processing
    SYNC_MESSAGE = "sync_message"  # Sync isolated→main per message

    # Tool Call processing (categorized by type)
    EXTERNAL_TOOL_CALL = (
        "external_tool_call"  # Scraping, image_gen, video_gen, vision (API limited)
    )
    DOCUMENT_TOOL_CALL = "document_tool_call"  # Document processing (no API limit)
    SYNC_TOOL_CALL = "sync_tool_call"  # Sync message after tool call completes

    # Context compression (parallel processing)
    COMPACTOR = "compactor"  # Context compression and summarization
    SYNC_COMPACTOR = "sync_compactor"  # Sync context_window after compaction

    # Legacy tool operations (deprecated, use above)
    AGENT = "agent"
    SCRAPING = "scraping"
    IMAGE_GEN = "image_gen"
    VIDEO_GEN = "video_gen"
    VISION = "vision"
    SYNC = "sync"


class JobStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ToolCall:
    """Tool call to be executed (scraping, document, mediaai, etc)"""

    tool_call_id: str  # UUID of the tool call
    message_id: str  # Parent message ID
    chat_id: str
    user_id: str
    tool_name: str  # "scraping", "document", "image_gen", "video_gen", "vision"
    job_id: str = (
        ""  # Parent job ID for sync coordination (optional, for backward compatibility)
    )
    arguments: Optional[Dict[str, Any]] = None
    tool_type: str = "external"  # "external" or "document"
    agent_id: str = "orchestrator-global"  # Agent executing the tool call
    generated_content_id: str = ""  # UUID for generated content (media tools only)
    client_id: str = ""  # Client ID for generated content tracking
    isolated_message_id: str = ""  # ID of the isolated message (user input)
    created_at: str = None
    status: str = JobStatus.PENDING.value

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "ToolCall":
        valid_fields = {f.name for f in ToolCall.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}
        return ToolCall(**filtered_data)


@dataclass
class Message:
    """Message to be processed (user or AI response)"""

    message_id: str  # UUID of the message
    chat_id: str
    job_id: Optional[str] = None  # Job ID for tracking
    user_id: Optional[str] = None
    role: str = "user"  # "user" or "assistant"
    content: str = ""
    context: Optional[Dict[str, Any]] = None
    model: str = "gpt-4o-mini"
    agent_id: str = "orchestrator-global"
    attachment: Optional[
        Dict[str, str]
    ] = None  # {attachment_type: "file"|"template", attachment_id: str}
    created_at: str = None
    status: str = JobStatus.PENDING.value

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "Message":
        valid_fields = {f.name for f in Message.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}
        return Message(**filtered_data)


@dataclass
class Job:
    job_id: str
    chat_id: str
    operation_type: str
    priority: int = 0
    created_at: str = None
    status: str = JobStatus.PENDING.value
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    # Extra fields for operation-specific data
    client_id: Optional[str] = None
    agent_id: Optional[str] = None
    tool_name: Optional[str] = None
    arguments: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        return data

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "Job":
        # Filter data to only include valid Job fields
        valid_fields = {f.name for f in Job.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}
        return Job(**filtered_data)


@dataclass
class CompactorJob:
    """Job para compactação de contexto"""

    job_id: str
    chat_id: str
    client_id: int
    isolated_chat_id: int
    cut_message_uuid: str  # UUID até qual mensagem compactar
    agent_id: str = "orchestrator-global"
    priority: int = 5  # Média prioridade (após MESSAGE, antes de TOOL_CALL)
    created_at: str = None
    status: str = JobStatus.PENDING.value
    result: Optional[Dict[str, Any]] = None  # Contexto compactado
    error: Optional[str] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "CompactorJob":
        valid_fields = {f.name for f in CompactorJob.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}
        return CompactorJob(**filtered_data)


# Singleton instance to ensure all components use the same Redis connection
_queue_manager_instance = None
_queue_manager_lock = threading.Lock()


class MultiQueueManager:
    def __new__(
        cls,
        redis_host: str = None,
        redis_port: int = None,
        redis_db: int = 0,
        redis_url: str = None,
    ):
        """
        Singleton pattern: all calls return the same instance.
        First call initializes with the provided arguments.
        Subsequent calls return the same instance (arguments are ignored).
        """
        global _queue_manager_instance

        if _queue_manager_instance is None:
            with _queue_manager_lock:
                if _queue_manager_instance is None:
                    instance = super().__new__(cls)
                    instance._initialized = False
                    _queue_manager_instance = instance

        return _queue_manager_instance

    def __init__(
        self,
        redis_host: str = None,
        redis_port: int = None,
        redis_db: int = 0,
        redis_url: str = None,
    ):
        # Only initialize once (singleton pattern)
        if self._initialized:
            debug(
                "[REDIS] MultiQueueManager already initialized - using existing singleton instance"
            )
            return
        self._initialized = True

        info("[REDIS] Initializing MultiQueueManager singleton...")

        # Carrega porta padrão do Settings se não for passada
        if redis_port is None:
            config = load_config()
            redis_port = config.get("redis_port", 6379)

        # Prioridade: redis_url argument > REDIS_URL env > individual components
        if not redis_url:
            from App.Core.Settings.Settings import load_config as _load_config

            redis_url = _load_config().get("redis_url", "")

        if redis_url:
            # Obfuscate password for logging
            log_url = redis_url
            if "@" in redis_url:
                prefix = redis_url.split("@")[0]
                if ":" in prefix:
                    parts = prefix.split(":")
                    log_url = f"{parts[0]}:****@{redis_url.split('@')[1]}"

            info(f"[REDIS] Using redis_url: {log_url}")
            self.redis_client = redis.Redis.from_url(
                redis_url,
                db=redis_db,
                decode_responses=True,
                socket_keepalive=True,
                socket_timeout=10,
                socket_connect_timeout=5,
                retry_on_timeout=True,
                max_connections=50,
            )
        else:
            # Fallback para componentes individuais
            if redis_host is None:
                redis_host = os.getenv("REDIS_HOST", "localhost")

            info(f"[REDIS] Using redis_host={redis_host}, redis_port={redis_port}")
            # Se não houver REDIS_URL nem redis_host definido, o comportamento padrão do redis-py
            # será tentar localhost:6379, mas aqui respeitamos o redis_port passado.
            self.redis_client = redis.Redis(
                host=redis_host,
                port=redis_port,
                db=redis_db,
                decode_responses=True,
                socket_keepalive=True,
                socket_timeout=10,
                socket_connect_timeout=5,
                retry_on_timeout=True,
                max_connections=50,
            )
        self.operation_types = [op.value for op in OperationType]

    def _execute_with_retry(self, func_name, *args, **kwargs):
        """
        Executa um comando do redis_client com política de retry (1s, 2s, 5s, 10s, 15s).
        Se falhar após 5 tentativas, encerra o servidor (sys.exit).
        """
        retries = [1, 2, 5, 10, 15]
        last_exception = None

        for i, delay in enumerate(retries):
            try:
                func = getattr(self.redis_client, func_name)
                return func(*args, **kwargs)
            except (
                redis.ConnectionError,
                redis.TimeoutError,
                redis.exceptions.ConnectionError,
            ) as e:
                last_exception = e
                warning(
                    f"[REDIS] Falha de conexão durante {func_name} (tentativa {i+1}/5): {e}. Retentando em {delay}s..."
                )
                time.sleep(delay)
            except Exception as e:
                # Outros erros não relacionados à conexão não devem necessariamente derrubar o servidor via retry
                # Mas vamos logar e re-lançar
                error(f"[REDIS] Erro inesperado durante {func_name}: {e}")
                raise e

        # Se chegou aqui, todas as tentativas de reconexão falharam
        error(
            f"[REDIS] FALHA CRÍTICA: Não foi possível restabelecer conexão com Redis após 5 tentativas ({func_name})"
        )
        error(f"[REDIS] Erro: {last_exception}")
        error("[REDIS] O servidor será encerrado para evitar inconsistência de dados.")
        # Use os._exit() instead of sys.exit() for immediate termination from worker threads
        os._exit(1)

    def test_connection(self) -> bool:
        """Test Redis connection. Raises exception if fails."""
        try:
            self._execute_with_retry("ping")
            self._execute_with_retry("set", "_connection_test", "ok", ex=5)
            result = self._execute_with_retry("get", "_connection_test")
            if result != "ok":
                raise Exception("SET/GET test failed")
            self._execute_with_retry("delete", "_connection_test")
            return True
        except SystemExit:
            raise
        except Exception as e:
            raise Exception(f"Redis connection test failed: {str(e)}")

    def _get_queue_key(self, operation_type: str, chat_id: str) -> str:
        return f"queue:{operation_type}:{chat_id}"

    def _get_job_key(self, chat_id: str, job_id: str) -> str:
        return f"job:{chat_id}:{job_id}"

    def _get_job_result_key(self, chat_id: str, job_id: str) -> str:
        return f"result:{chat_id}:{job_id}"

    def _get_operation_stats_key(self, operation_type: str) -> str:
        return f"stats:{operation_type}"

    def enqueue_job(
        self,
        chat_id: str,
        operation_type: str,
        job_data: Dict[str, Any],
        priority: int = 0,
    ) -> str:
        if operation_type not in self.operation_types:
            raise ValueError(f"Invalid operation type: {operation_type}")

        job_id = str(uuid.uuid4())
        job = Job(
            job_id=job_id,
            chat_id=chat_id,
            operation_type=operation_type,
            priority=priority,
            status=JobStatus.PENDING.value,
        )

        queue_key = self._get_queue_key(operation_type, chat_id)
        job_key = self._get_job_key(chat_id, job_id)

        job_dict = job.to_dict()
        job_dict.update(job_data)

        # Remove None values as Redis doesn't accept them
        job_dict = {k: v for k, v in job_dict.items() if v is not None}

        self._execute_with_retry("hset", job_key, mapping=job_dict)
        self._execute_with_retry("zadd", queue_key, {job_id: -priority})

        self._update_stats(operation_type, "enqueued")

        return job_id

    def dequeue_job(self, chat_id: str, operation_type: str) -> Optional[Job]:
        if operation_type not in self.operation_types:
            raise ValueError(f"Invalid operation type: {operation_type}")

        queue_key = self._get_queue_key(operation_type, chat_id)

        job_ids = self._execute_with_retry("zrange", queue_key, 0, 0)
        if not job_ids:
            return None

        job_id = job_ids[0]
        self._execute_with_retry("zrem", queue_key, job_id)

        job_key = self._get_job_key(chat_id, job_id)
        job_data = self._execute_with_retry("hgetall", job_key)

        if job_data:
            job = Job.from_dict(job_data)
            job.status = JobStatus.PROCESSING.value
            # Remove None values as Redis doesn't accept them
            job_dict = asdict(job)
            job_dict = {k: v for k, v in job_dict.items() if v is not None}
            self._execute_with_retry("hset", job_key, mapping=job_dict)
            self._update_stats(operation_type, "dequeued")
            return job

        return None

    def dequeue_job_any_chat(self, operation_type: str) -> Optional[Job]:
        """Dequeue from any chat's queue for this operation type"""
        if operation_type not in self.operation_types:
            raise ValueError(f"Invalid operation type: {operation_type}")

        # Get all queue keys for this operation type
        pattern = self._get_queue_key(operation_type, "*")
        queue_keys = self._execute_with_retry("keys", pattern)

        if not queue_keys:
            return None

        # Try to dequeue from the first available queue
        for queue_key in queue_keys:
            job_ids = self._execute_with_retry("zrange", queue_key, 0, 0)
            if job_ids:
                job_id = job_ids[0]
                self._execute_with_retry("zrem", queue_key, job_id)

                # Extract chat_id from queue_key
                # queue_key format: queue:{operation_type}:{chat_id}
                chat_id = queue_key.split(":")[-1]
                job_key = self._get_job_key(chat_id, job_id)
                job_data = self._execute_with_retry("hgetall", job_key)

                if job_data:
                    job = Job.from_dict(job_data)
                    job.status = JobStatus.PROCESSING.value
                    # Remove None values as Redis doesn't accept them
                    job_dict = asdict(job)
                    job_dict = {k: v for k, v in job_dict.items() if v is not None}
                    self._execute_with_retry("hset", job_key, mapping=job_dict)
                    self._update_stats(operation_type, "dequeued")
                    return job

        return None

    def get_job_status(self, chat_id: str, job_id: str) -> Optional[Dict[str, Any]]:
        job_key = self._get_job_key(chat_id, job_id)
        job_data = self._execute_with_retry("hgetall", job_key)

        if not job_data:
            return None

        return {
            "job_id": job_data.get("job_id"),
            "chat_id": job_data.get("chat_id"),
            "operation_type": job_data.get("operation_type"),
            "status": job_data.get("status"),
            "priority": int(job_data.get("priority", 0)),
            "created_at": job_data.get("created_at"),
            "error": job_data.get("error"),
        }

    def get_job_result(self, chat_id: str, job_id: str) -> Optional[Dict[str, Any]]:
        result_key = self._get_job_result_key(chat_id, job_id)
        result_data = self._execute_with_retry("get", result_key)

        if not result_data:
            return None

        return json.loads(result_data)

    def update_job_status(
        self,
        chat_id: str,
        job_id: str,
        status: str,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ):
        job_key = self._get_job_key(chat_id, job_id)
        job_data = self._execute_with_retry("hgetall", job_key)

        if not job_data:
            raise ValueError(f"Job not found: {job_id}")

        job_data["status"] = status
        if error:
            job_data["error"] = error

        self._execute_with_retry("hset", job_key, mapping=job_data)

        if result:
            result_key = self._get_job_result_key(chat_id, job_id)
            self._execute_with_retry("set", result_key, json.dumps(result))

    def list_queue_stats(self, operation_type: Optional[str] = None) -> Dict[str, Any]:
        if operation_type:
            if operation_type not in self.operation_types:
                raise ValueError(f"Invalid operation type: {operation_type}")
            return self._get_operation_stats(operation_type)

        stats = {}
        for op_type in self.operation_types:
            stats[op_type] = self._get_operation_stats(op_type)

        return stats

    def _get_operation_stats(self, operation_type: str) -> Dict[str, Any]:
        stats_key = self._get_operation_stats_key(operation_type)
        stats = self._execute_with_retry("hgetall", stats_key)

        return {
            "operation_type": operation_type,
            "enqueued": int(stats.get("enqueued", 0)),
            "dequeued": int(stats.get("dequeued", 0)),
            "completed": int(stats.get("completed", 0)),
            "failed": int(stats.get("failed", 0)),
        }

    def _update_stats(self, operation_type: str, stat_type: str):
        stats_key = self._get_operation_stats_key(operation_type)
        self._execute_with_retry("hincrby", stats_key, stat_type, 1)

    def clear_chat_queue(self, chat_id: str, operation_type: str) -> int:
        if operation_type not in self.operation_types:
            raise ValueError(f"Invalid operation type: {operation_type}")

        queue_key = self._get_queue_key(operation_type, chat_id)
        return self._execute_with_retry("delete", queue_key)

    def get_queue_length(self, chat_id: str, operation_type: str) -> int:
        if operation_type not in self.operation_types:
            raise ValueError(f"Invalid operation type: {operation_type}")

        queue_key = self._get_queue_key(operation_type, chat_id)
        return self._execute_with_retry("zcard", queue_key)

    def get_all_queues_for_chat(self, chat_id: str) -> Dict[str, int]:
        queues = {}
        for op_type in self.operation_types:
            length = self.get_queue_length(chat_id, op_type)
            if length > 0:
                queues[op_type] = length
        return queues

    def delete_job(self, chat_id: str, job_id: str) -> bool:
        job_key = self._get_job_key(chat_id, job_id)
        result_key = self._get_job_result_key(chat_id, job_id)

        job_data = self._execute_with_retry("hgetall", job_key)
        if not job_data:
            return False

        operation_type = job_data.get("operation_type")
        queue_key = self._get_queue_key(operation_type, chat_id)

        self._execute_with_retry("delete", job_key)
        self._execute_with_retry("delete", result_key)
        self._execute_with_retry("zrem", queue_key, job_id)

        return True

    # ==================== MESSAGE QUEUE METHODS ====================
    # Global MESSAGE_QUEUE (not per chat, but global FIFO)

    def _get_message_queue_key(self) -> str:
        """Global message queue key"""
        return "queue:messages"

    def _get_message_key(self, message_id: str) -> str:
        """Key for storing message data"""
        return f"message:{message_id}"

    def _get_sync_queue_key(self) -> str:
        """Global sync queue key (per message)"""
        return "queue:sync_messages"

    def enqueue_message(self, message: Message) -> str:
        """Enqueue a message (user or AI) for processing"""
        message_key = self._get_message_key(message.message_id)
        queue_key = self._get_message_queue_key()

        message_dict = message.to_dict()
        # Remove None values and serialize nested dicts to JSON strings
        message_dict = {
            k: json.dumps(v) if isinstance(v, dict) else v
            for k, v in message_dict.items()
            if v is not None
        }

        self._execute_with_retry("hset", message_key, mapping=message_dict)
        # Add to global queue with priority (negative priority for sorting)
        self._execute_with_retry(
            "zadd", queue_key, {message.message_id: 0}
        )  # FIFO order

        return message.message_id

    def dequeue_message(self, timeout: int = 2) -> Optional[Message]:
        """Dequeue next message (FIFO from global queue) - blocking pop for efficiency

        Args:
            timeout: Seconds to block waiting for message (0 = no block)
        """
        queue_key = self._get_message_queue_key()

        # Use bzpopmin for blocking dequeue - thread sleeps until message appears
        # bzpopmin returns (key, member, score) or None if timeout
        result = self._execute_with_retry("bzpopmin", queue_key, timeout=timeout)
        if not result:
            return None

        message_id = result[1]  # bzpopmin returns (key, member, score)

        message_key = self._get_message_key(message_id)
        message_data = self._execute_with_retry("hgetall", message_key)

        if message_data:
            # Deserialize JSON strings back to dicts
            for k, v in message_data.items():
                if k in ("attachment", "context") and isinstance(v, (str, bytes)):
                    try:
                        message_data[k] = (
                            json.loads(v)
                            if isinstance(v, str)
                            else json.loads(v.decode("utf-8"))
                        )
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        pass  # Keep as is if not valid JSON

            message = Message.from_dict(message_data)
            message.status = JobStatus.PROCESSING.value
            # Update status in Redis
            message_dict = message.to_dict()
            # Serialize nested dicts to JSON strings
            message_dict = {
                k: json.dumps(v) if isinstance(v, dict) else v
                for k, v in message_dict.items()
                if v is not None
            }
            self._execute_with_retry("hset", message_key, mapping=message_dict)
            return message

        return None

    def mark_message_completed(self, message_id: str) -> bool:
        """Mark message as completed and enqueue for sync"""
        message_key = self._get_message_key(message_id)
        message_data = self._execute_with_retry("hgetall", message_key)

        if not message_data:
            return False

        message_data["status"] = JobStatus.COMPLETED.value
        self._execute_with_retry("hset", message_key, mapping=message_data)

        # Enqueue for sync - store chat_id and client_id with job_id for sync worker
        # Format: "{job_id}|{chat_id}|{client_id}|{agent_id}|{user_id}"
        job_id = message_data.get("job_id", "")
        chat_id = message_data.get("chat_id", "")
        client_id = message_data.get("client_id", "")
        agent_id = message_data.get("agent_id", "orchestrator-global")
        user_id = message_data.get("user_id", "0")

        sync_queue_entry = f"{job_id}|{chat_id}|{client_id}|{agent_id}|{user_id}"
        sync_queue_key = self._get_sync_queue_key()
        self._execute_with_retry("zadd", sync_queue_key, {sync_queue_entry: 0})  # FIFO

        return True

    def enqueue_sync_message(
        self, chat_id: str, agent_id: str, job_id: str, user_id: int = 0
    ) -> bool:
        """Enqueue sync job after message iteration

        Args:
            chat_id: Chat ID to sync
            agent_id: Agent ID
            job_id: Job ID (for active job validation)
            user_id: User ID (for context)

        Returns:
            True if enqueued successfully
        """
        # Format: "{job_id}|{chat_id}|{agent_id}|{user_id}"
        sync_queue_entry = f"{job_id}|{chat_id}|{agent_id}|{user_id}"
        sync_queue_key = self._get_sync_queue_key()
        self._execute_with_retry("zadd", sync_queue_key, {sync_queue_entry: 0})  # FIFO
        return True

    def dequeue_sync_message(self, timeout: int = 2) -> Optional[str]:
        """Dequeue next message ID for syncing (FIFO) - blocking pop for efficiency

        Args:
            timeout: Seconds to block waiting for sync message (0 = no block)
        """
        sync_queue_key = self._get_sync_queue_key()

        # Use bzpopmin for blocking dequeue - thread sleeps until item appears
        # bzpopmin returns (key, member, score) or None if timeout
        result = self._execute_with_retry("bzpopmin", sync_queue_key, timeout=timeout)
        if not result:
            return None

        message_id = result[1]  # bzpopmin returns (key, member, score)

        return message_id

    def get_message(self, message_id: str) -> Optional[Message]:
        """Get message data by ID"""
        message_key = self._get_message_key(message_id)
        message_data = self._execute_with_retry("hgetall", message_key)

        if message_data:
            return Message.from_dict(message_data)

        return None

    # ==================== TOOL CALL QUEUE METHODS ====================
    # Separate queues for external tools (API limited) vs document tools

    def _get_external_tool_queue_key(self) -> str:
        """Queue for external API tool calls (scraping, image_gen, video_gen, vision)"""
        return "queue:external_tool_calls"

    def _get_document_tool_queue_key(self) -> str:
        """Queue for document tool calls (no API limit)"""
        return "queue:document_tool_calls"

    def _get_tool_call_key(self, tool_call_id: str) -> str:
        """Key for storing tool call data"""
        return f"tool_call:{tool_call_id}"

    def enqueue_tool_call(self, tool_call: ToolCall) -> str:
        """Enqueue a tool call (external or document)"""
        tool_call_key = self._get_tool_call_key(tool_call.tool_call_id)

        # Choose queue based on tool type
        if tool_call.tool_type == "document":
            queue_key = self._get_document_tool_queue_key()
        else:  # "external"
            queue_key = self._get_external_tool_queue_key()

        tool_call_dict = tool_call.to_dict()
        tool_call_dict = {k: v for k, v in tool_call_dict.items() if v is not None}

        # Serialize all dict/list values — Redis only accepts primitive types.
        # Inclui arguments={} (dict vazio é falsy, bug original) e quaisquer outros campos.
        for k in list(tool_call_dict.keys()):
            if isinstance(tool_call_dict[k], (dict, list)):
                tool_call_dict[k] = json.dumps(tool_call_dict[k])

        self._execute_with_retry("hset", tool_call_key, mapping=tool_call_dict)
        self._execute_with_retry("zadd", queue_key, {tool_call.tool_call_id: 0})  # FIFO

        return tool_call.tool_call_id

    def dequeue_tool_call(
        self, tool_type: str = "external", timeout: int = 2
    ) -> Optional[ToolCall]:
        """Dequeue next tool call (FIFO) - blocking pop for efficiency

        Args:
            tool_type: "external" or "document"
            timeout: Seconds to block waiting for item (0 = no block, returns immediately)
        """
        if tool_type == "document":
            queue_key = self._get_document_tool_queue_key()
        else:
            queue_key = self._get_external_tool_queue_key()

        # Use bzpopmin for blocking dequeue - thread sleeps until item appears
        # bzpopmin returns (key, member, score) or None if timeout
        result = self._execute_with_retry("bzpopmin", queue_key, timeout=timeout)
        if not result:
            return None

        tool_call_id = result[1]  # bzpopmin returns (key, member, score)

        tool_call_key = self._get_tool_call_key(tool_call_id)
        tool_call_data = self._execute_with_retry("hgetall", tool_call_key)

        if tool_call_data:
            # Deserialize arguments from JSON string to dict
            if tool_call_data.get("arguments") and isinstance(
                tool_call_data["arguments"], (str, bytes)
            ):
                try:
                    tool_call_data["arguments"] = json.loads(
                        tool_call_data["arguments"]
                    )
                except (json.JSONDecodeError, TypeError):
                    pass  # Keep as string if deserialization fails

            tool_call = ToolCall.from_dict(tool_call_data)
            tool_call.status = JobStatus.PROCESSING.value
            tool_call_dict = tool_call.to_dict()
            tool_call_dict = {k: v for k, v in tool_call_dict.items() if v is not None}

            # Re-serialize quaisquer dict/list antes de armazenar no Redis
            for k in list(tool_call_dict.keys()):
                if isinstance(tool_call_dict[k], (dict, list)):
                    tool_call_dict[k] = json.dumps(tool_call_dict[k])

            self._execute_with_retry("hset", tool_call_key, mapping=tool_call_dict)
            return tool_call

        return None

    def mark_tool_call_completed(
        self, tool_call_id: str, result: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Mark tool call as completed (sync will be handled by mark_message_completed at the end)"""
        tool_call_key = self._get_tool_call_key(tool_call_id)
        tool_call_data = self._execute_with_retry("hgetall", tool_call_key)

        if not tool_call_data:
            return False

        tool_call_data["status"] = JobStatus.COMPLETED.value
        if result:
            tool_call_data["result"] = json.dumps(result)

        # Re-serialize quaisquer dict/list antes de armazenar no Redis
        for k in list(tool_call_data.keys()):
            if isinstance(tool_call_data[k], (dict, list)):
                tool_call_data[k] = json.dumps(tool_call_data[k])

        self._execute_with_retry("hset", tool_call_key, mapping=tool_call_data)

        return True

    def get_tool_call(self, tool_call_id: str) -> Optional[ToolCall]:
        """Get tool call data by ID"""
        tool_call_key = self._get_tool_call_key(tool_call_id)
        tool_call_data = self._execute_with_retry("hgetall", tool_call_key)

        if tool_call_data:
            return ToolCall.from_dict(tool_call_data)

        return None

    def health_check(self) -> bool:
        try:
            self._execute_with_retry("ping")
            return True
        except Exception as e:
            error(f"Redis health check failed: {e}")
            return False


# ============================================================================
# FACTORY FUNCTIONS FOR SINGLETON ACCESS
# ============================================================================


def get_queue_manager(
    redis_host: str = None,
    redis_port: int = None,
    redis_db: int = 0,
    redis_url: str = None,
) -> MultiQueueManager:
    """
    Factory function to get the MultiQueueManager singleton.

    IMPORTANT: The first call to this function (or direct instantiation of MultiQueueManager)
    will initialize the singleton with the provided arguments. Subsequent calls will return
    the same instance (arguments are ignored on subsequent calls).

    Args:
        redis_host: Redis hostname (fallback if redis_url not provided)
        redis_port: Redis port (default: 6379)
        redis_db: Redis database number (default: 0)
        redis_url: Full Redis URL (takes precedence over redis_host:redis_port)

    Returns:
        MultiQueueManager singleton instance
    """
    return MultiQueueManager(
        redis_host=redis_host,
        redis_port=redis_port,
        redis_db=redis_db,
        redis_url=redis_url,
    )


def reset_queue_manager():
    """
    Reset the singleton instance (useful for testing).
    CRITICAL: This should NEVER be called in production - only for testing.
    """
    global _queue_manager_instance
    with _queue_manager_lock:
        if _queue_manager_instance is not None:
            try:
                _queue_manager_instance.redis_client.close()
            except:
                pass
        _queue_manager_instance = None
    debug("[REDIS] Queue manager singleton reset (testing only)")

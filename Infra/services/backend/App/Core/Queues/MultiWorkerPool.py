import logging
import json
import time
import uuid as uuid_lib
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
from sqlalchemy.exc import IntegrityError as SQLAlchemyIntegrityError
from App.Core.Logs import debug, info, warning, error
from App.Core.Crunch.TablesSQL.Models import IsolatedMessage, GeneratedContent
from App.Features.Job import get_job_manager


def _complete_trigger_execution(job_id: str, user_id: str) -> None:
    """Atualiza status da trigger_execution e notifica frontend via WS."""
    if not job_id:
        return
    try:
        from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
        from datetime import datetime as _dt

        db = DatabaseManager()
        row = db.fetch_one(
            """SELECT te.id, te.user_id, ws.autonomy_level
               FROM trigger_executions te
               JOIN webhook_secrets ws ON ws.web_secret_id = te.web_secret_id
               WHERE te.id = :jid AND te.status = 'running'""",
            {"jid": job_id},
        )
        if not row:
            return
        autonomy = row["autonomy_level"]
        uid = row["user_id"] or user_id
        new_status = "pending_review" if autonomy in (1, 2) else "completed"
        now = _dt.utcnow().isoformat()
        db.execute_query(
            "UPDATE trigger_executions SET status = :s, finished_at = :now WHERE id = :id",
            {"s": new_status, "id": job_id, "now": now},
        )
        info(f"[TriggerExec] execution {job_id} → {new_status} (autonomy={autonomy})")
        try:
            from App.Core.Services.Chat.ChatRoutes import notify_user_ws

            notify_user_ws(
                uid,
                {
                    "type": "unseen_update",
                    "triggers": 1,
                    "execution_id": job_id,
                    "status": new_status,
                },
            )
        except Exception:
            pass
    except Exception as e:
        error(f"[TriggerExec] Erro ao finalizar execution {job_id}: {e}")


def _complete_scheduled_execution(job_id: str, user_id: str) -> None:
    """Atualiza status da task_execution e notifica frontend via WS."""
    if not job_id:
        return
    try:
        from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
        from datetime import datetime as _dt

        db = DatabaseManager()
        row = db.fetch_one(
            """SELECT te.id, te.user_id, st.autonomy_level
               FROM task_executions te
               JOIN scheduled_tasks st ON te.task_id = st.id
               WHERE te.id = :jid AND te.status = 'running'""",
            {"jid": job_id},
        )
        if not row:
            return
        autonomy = row["autonomy_level"]
        uid = row["user_id"] or user_id
        new_status = "pending_review" if autonomy in (1, 2) else "completed"
        now = _dt.now().isoformat()
        db.execute_query(
            "UPDATE task_executions SET status = :s, finished_at = :now WHERE id = :id",
            {"s": new_status, "id": job_id, "now": now},
        )
        info(f"[ScheduledExec] execution {job_id} → {new_status} (autonomy={autonomy})")
        try:
            from App.Core.Services.Chat.ChatRoutes import notify_user_ws

            notify_user_ws(
                uid,
                {
                    "type": "unseen_update",
                    "scheduled": 1,
                    "execution_id": job_id,
                    "status": new_status,
                },
            )
        except Exception:
            pass
    except Exception as e:
        error(f"[ScheduledExec] Erro ao finalizar execution {job_id}: {e}")


class JobStatus(Enum):
    """Job status enum"""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass
class WorkerStats:
    """Statistics for a worker"""

    operation_type: str
    jobs_processed: int = 0
    jobs_failed: int = 0
    total_execution_time: float = 0.0
    avg_execution_time: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "operation_type": self.operation_type,
            "jobs_processed": self.jobs_processed,
            "jobs_failed": self.jobs_failed,
            "total_execution_time": self.total_execution_time,
            "avg_execution_time": self.avg_execution_time,
        }


class MessageWorker:
    """Worker for processing messages (user or AI) from global MESSAGE_QUEUE"""

    def __init__(self, queue_manager, message_processor, num_workers: int = 3):
        """
        Initialize message worker

        Args:
            queue_manager: MultiQueueManager instance
            message_processor: MessageProcessor instance for processing messages
            num_workers: Number of worker threads
        """
        self.queue_manager = queue_manager
        self.message_processor = message_processor
        self.num_workers = num_workers
        self.executor = ThreadPoolExecutor(
            max_workers=num_workers, thread_name_prefix="message_worker"
        )
        self.running = False
        self.stats = WorkerStats(operation_type="message")

    def start(self) -> None:
        """Start the message worker threads"""
        if self.running:
            warning("Message worker is already running")
            return

        self.running = True

        for i in range(self.num_workers):
            future = self.executor.submit(self._worker_loop)

    def stop(self) -> None:
        """Stop message worker threads gracefully"""
        if not self.running:
            warning("Message worker is not running")
            return

        self.running = False
        self.executor.shutdown(wait=True)

    def _worker_loop(self) -> None:
        """Main worker loop - continuously dequeue and process messages"""
        while self.running:
            try:
                # Dequeue next message (FIFO from global queue)
                message = self.queue_manager.dequeue_message()

                if not message:
                    continue  # BZPOPMIN will block until next message, no need for sleep

                info(f"[MessageWorker] Processing message: {message.message_id}")
                debug(
                    f"[MessageWorker] Message details: job_id={message.job_id}, agent_id={message.agent_id}, chat_id={message.chat_id}"
                )
                start_time = time.time()

                try:
                    # Recover job object to pass to process_message
                    job = None
                    try:
                        job_manager = get_job_manager()
                        job = job_manager.get_job(message.job_id)
                    except Exception as e:
                        debug(
                            f"[MessageWorker] Could not recover job {message.job_id}: {e}"
                        )

                    # Verify message_processor is available
                    if not self.message_processor:
                        error(
                            f"[MessageWorker] message_processor is None! Cannot process message {message.message_id}"
                        )
                        self.stats.jobs_failed += 1
                        continue

                    debug(
                        f"[MessageWorker] About to call process_message for {message.message_id}"
                    )

                    # Process message via MessageProcessor
                    result = self.message_processor.process_message(
                        job_id=message.job_id,
                        user_message=message.content,
                        agent_id=message.agent_id,
                        chat_id=message.chat_id,
                        user_id=message.user_id,
                        message_id=message.message_id,
                        job=job,
                        attachment=message.attachment,
                        context=message.context,
                    )

                    debug(
                        f"[MessageWorker] process_message returned for {message.message_id}"
                    )

                    # Mark message as completed (this enqueues for sync).
                    # O ciclo de vida do job (mark_completed) é gerenciado pelo process_message
                    # e pelo SyncWorker via enqueue_sync_message com job_id real.
                    # Aqui zeramos job_id antes para garantir que este sync nunca acione
                    # mark_completed no SyncWorker — evita race condition com ExternalToolWorker.
                    try:
                        msg_key = self.queue_manager._get_message_key(
                            message.message_id
                        )
                        self.queue_manager._execute_with_retry(
                            "hset", msg_key, "job_id", ""
                        )
                        debug(
                            f"[MessageWorker] job_id zerado antes de mark_message_completed para {message.message_id}"
                        )
                    except Exception as _ze:
                        debug(f"[MessageWorker] Erro ao zerar job_id: {_ze}")
                    self.queue_manager.mark_message_completed(message.message_id)

                    # Finalizar trigger_execution ou task_execution se aplicável
                    _complete_trigger_execution(message.job_id, message.user_id)
                    _complete_scheduled_execution(message.job_id, message.user_id)

                    execution_time = time.time() - start_time
                    self.stats.jobs_processed += 1
                    self.stats.total_execution_time += execution_time
                    self.stats.avg_execution_time = (
                        self.stats.total_execution_time / self.stats.jobs_processed
                    )

                    info(
                        f"[MessageWorker] Message {message.message_id} processed in {execution_time:.2f}s"
                    )

                except Exception as e:
                    error(
                        f"[MessageWorker] Error processing message {message.message_id}: {e}",
                    )
                    self.stats.jobs_failed += 1

            except Exception as e:
                error(
                    f"[MessageWorker] Unexpected error in worker loop: {e}",
                )
                time.sleep(1)

    def get_stats(self) -> Dict[str, Any]:
        """Get worker statistics"""
        return self.stats.to_dict()


class SyncMessageWorker:
    """Worker for syncing messages from isolated_chat to main_chat"""

    def __init__(self, queue_manager, chat_service, db_manager, num_workers: int = 2):
        """
        Initialize sync message worker

        Args:
            queue_manager: MultiQueueManager instance
            chat_service: ChatService instance
            db_manager: DatabaseManager instance
            num_workers: Number of worker threads
        """
        self.queue_manager = queue_manager
        self.chat_service = chat_service
        self.db_manager = db_manager
        self.num_workers = num_workers
        self.executor = ThreadPoolExecutor(
            max_workers=num_workers, thread_name_prefix="sync_worker"
        )
        self.running = False
        self.stats = WorkerStats(operation_type="sync_message")

    def start(self) -> None:
        """Start the sync worker threads"""
        if self.running:
            warning("Sync worker is already running")
            return

        self.running = True

        for i in range(self.num_workers):
            self.executor.submit(self._worker_loop)

    def stop(self) -> None:
        """Stop sync worker threads gracefully"""
        if not self.running:
            warning("Sync worker is not running")
            return

        self.running = False
        self.executor.shutdown(wait=True)

    def _worker_loop(self) -> None:
        """Main sync worker loop - continuously dequeue and sync messages"""
        from logging import debug as debug_log

        while self.running:
            try:
                # Dequeue next sync job (FIFO from sync queue)
                # Format: "{job_id}|{chat_id}|{agent_id}|{user_id}"
                sync_queue_entry = self.queue_manager.dequeue_sync_message()

                if not sync_queue_entry:
                    debug_log(
                        "[SyncWorker] BZPOPMIN blocking, waiting for sync jobs..."
                    )
                    continue  # BZPOPMIN will block until next sync job, no need for sleep

                info(f"[SyncWorker] Processing sync job: {sync_queue_entry}")
                start_time = time.time()

                try:
                    # Parse encoded sync queue entry to extract components
                    # Format: "{job_id}|{chat_id}|{agent_id}|{user_id}"
                    parts = sync_queue_entry.split("|")
                    if len(parts) < 3:
                        warning(
                            f"[SyncWorker] Invalid sync queue format: {sync_queue_entry} - skipping"
                        )
                        continue

                    job_id, chat_id, agent_id = parts[0], parts[1], parts[2]
                    user_id = parts[3] if len(parts) > 3 else "0"

                    debug(
                        f"[SyncWorker] Extracted: job_id={job_id}, chat_id={chat_id}, agent_id={agent_id}, user_id={user_id}"
                    )

                    # VALIDAÇÃO: Verificar se o job ainda está ativo
                    # job_id é apenas um UUID de tracking, não precisa validar
                    # O sync sempre deve acontecer quando enfileirado
                    debug(f"[SyncWorker] Validating job {job_id} for sync")

                    # Sync isolated_chat → main_chat usando parâmetros extraídos
                    db_session = self.db_manager.get_session()
                    try:
                        self.db_manager.sync_isolated_to_main(
                            session=db_session,
                            chat_id=chat_id,
                            agent_id=agent_id or "orchestrator-global",
                        )
                        db_session.commit()
                    finally:
                        db_session.close()

                    # Marcar job como COMPLETED agora que sync terminou.
                    # Garante que o frontend só detecta finished=True depois das mensagens
                    # estarem disponíveis em main_chat (evita race condition).
                    if job_id:
                        try:
                            jm = get_job_manager()
                            synced_job = jm.get_job(job_id)
                            if synced_job and not synced_job.is_finished():
                                synced_job.mark_completed("Processamento concluído")
                                info(
                                    f"[SyncWorker] Job {job_id} marcado como COMPLETED após sync"
                                )
                        except Exception as _je:
                            error(
                                f"[SyncWorker] Erro ao marcar job {job_id} como COMPLETED: {_je}"
                            )

                    execution_time = time.time() - start_time
                    self.stats.jobs_processed += 1
                    self.stats.total_execution_time += execution_time
                    self.stats.avg_execution_time = (
                        self.stats.total_execution_time / self.stats.jobs_processed
                    )

                    info(f"[SyncWorker] Job {job_id} synced in {execution_time:.2f}s")

                except Exception as e:
                    error(
                        f"[SyncWorker] Error syncing job {sync_queue_entry}: {e}",
                    )
                    self.stats.jobs_failed += 1

            except Exception as e:
                error(f"[SyncWorker] Unexpected error in worker loop: {e}")
                time.sleep(1)

    def get_stats(self) -> Dict[str, Any]:
        """Get worker statistics"""
        return self.stats.to_dict()


class ExternalToolCallWorker:
    """Worker for processing external tool calls (scraping, image_gen, video_gen, vision - API limited)"""

    def __init__(
        self,
        queue_manager,
        core,
        db_manager=None,
        message_processor=None,
        num_workers: int = 2,
    ):
        """
        Initialize external tool call worker

        Args:
            queue_manager: MultiQueueManager instance
            core: Core instance for executing tools
            db_manager: DatabaseManager instance for saving tool results
            message_processor: MessageProcessor instance for resuming after wait=true
            num_workers: Number of worker threads (limited due to API rate limits)
        """
        self.queue_manager = queue_manager
        self.core = core
        self.db_manager = db_manager
        self.message_processor = message_processor
        self.num_workers = num_workers
        self.executor = ThreadPoolExecutor(
            max_workers=num_workers, thread_name_prefix="external_tool_worker"
        )
        self.running = False
        self.stats = WorkerStats(operation_type="external_tool_call")

    def start(self) -> None:
        """Start the external tool worker threads"""
        if self.running:
            warning("External tool worker is already running")
            return

        self.running = True

        for i in range(self.num_workers):
            self.executor.submit(self._worker_loop)

    def stop(self) -> None:
        """Stop external tool worker threads gracefully"""
        if not self.running:
            warning("External tool worker is not running")
            return

        self.running = False
        self.executor.shutdown(wait=True)

    def _worker_loop(self) -> None:
        """Main worker loop - continuously dequeue and execute external tool calls"""
        while self.running:
            try:
                # Dequeue next external tool call (FIFO)
                tool_call = self.queue_manager.dequeue_tool_call(tool_type="external")

                if not tool_call:
                    continue  # BZPOPMIN will block until next item, no need for sleep

                info(
                    f"[ExternalToolWorker] Processing {tool_call.tool_name}: {tool_call.tool_call_id}"
                )
                start_time = time.time()
                should_reactivate = (
                    False  # Flag para reativar looping se wait() está aguardando
                )

                # ⚠️ CHECK CANCELAMENTO ANTES DE EXECUTAR: Se o job foi cancelado, pula a execução
                if tool_call.job_id:
                    job_manager = get_job_manager()
                    job = job_manager.get_job(tool_call.job_id)
                    if job and job.status == "cancelled":
                        warning(
                            f"[ExternalToolWorker] ⚠️ Job {tool_call.job_id} foi cancelado, pulando execução de {tool_call.tool_name}"
                        )
                        continue

                try:
                    # Execute tool via Core (convert arguments dict to JSON string)
                    # IMPORTANTE: Remover wait=true dos arguments para executar de verdade
                    args_dict = (
                        tool_call.arguments.copy()
                        if isinstance(tool_call.arguments, dict)
                        else {}
                    )
                    args_dict.pop(
                        "wait", None
                    )  # Remove wait flag - não queremos esperar novamente
                    arguments_str = json.dumps(args_dict) if args_dict else "{}"
                    debug(
                        f"[ExternalToolWorker] Executando {tool_call.tool_name} com args: {arguments_str[:100]}..."
                    )
                    result = self.core.execute_tool(
                        tool_name=tool_call.tool_name,
                        arguments=arguments_str,
                        agent_id=tool_call.agent_id or "system",
                        chat_id=tool_call.chat_id,
                        user_id=tool_call.user_id,
                        job_id=tool_call.job_id,
                        isolated_message_id=tool_call.isolated_message_id,
                    )

                    # Calculate execution time for stats
                    execution_time = time.time() - start_time
                    debug(
                        f"[ExternalToolWorker] Tool {tool_call.tool_name} executada em {execution_time:.2f}s"
                    )
                    debug(
                        f"[ExternalToolWorker] Resultado recebido (length: {len(result) if isinstance(result, str) else 'N/A'} chars)"
                    )

                    # Save result to isolated messages if db_manager available
                    if self.db_manager and tool_call.chat_id:
                        debug(
                            f"[ExternalToolWorker] Iniciando salvamento de resultado para {tool_call.tool_call_id}"
                        )
                        debug(
                            f"[ExternalToolWorker] db_manager={self.db_manager is not None}, chat_id={tool_call.chat_id}"
                        )
                        try:
                            session = self.db_manager.get_session()
                            debug(
                                f"[ExternalToolWorker] ✓ Sessão obtida, iniciando salvamento"
                            )
                            try:
                                # Get or create isolated chat (caller should have created it, but just in case)
                                isolated_chat = (
                                    self.db_manager.get_or_create_isolated_chat(
                                        session=session,
                                        chat_id=tool_call.chat_id,
                                        agent_id=tool_call.agent_id or "system",
                                        user_id=tool_call.user_id,
                                    )
                                )
                                debug(
                                    f"[ExternalToolWorker] Chat isolado obtido/criado: {isolated_chat.id}"
                                )

                                # NOVO: External tools com wait=true devem reativar o looping
                                # Sempre tentamos reativar, o MessageProcessor verificará se há um job aguardando
                                should_reactivate = True
                                debug(
                                    f"[ExternalToolWorker] Marcado para reativação após conclusão do {tool_call.tool_name}"
                                )

                                # Save COMPLETE result to isolated_chat
                                # Then trim result for main_chat
                                result_for_isolated = result
                                result_for_main = result

                                try:
                                    result_json = (
                                        json.loads(result)
                                        if isinstance(result, str)
                                        else result
                                    )
                                    if isinstance(result_json, dict):
                                        # Trim only: success, tool, one identifier (search/url/etc), type, tool_call_id
                                        trimmed = {
                                            "success": result_json.get("success"),
                                            "tool": result_json.get("tool"),
                                            "tool_call_id": tool_call.tool_call_id,
                                        }

                                        # Add the identifying field (search, url, filename, search-result, etc)
                                        for key in [
                                            "search",
                                            "url",
                                            "filename",
                                            "image_url",
                                            "search-result",
                                            "content",
                                        ]:
                                            if key in result_json:
                                                trimmed[key] = result_json[key]
                                                break

                                        # Add type if present
                                        if "type" in result_json:
                                            trimmed["type"] = result_json["type"]

                                        result_for_main = json.dumps(
                                            trimmed, ensure_ascii=False
                                        )
                                except (json.JSONDecodeError, TypeError):
                                    result_for_main = result

                                # Save COMPLETE result to isolated_chat
                                debug(
                                    f"[ExternalToolWorker] Salvando resultado completo em isolated_messages"
                                )
                                self.db_manager.save_isolated_message(
                                    session=session,
                                    isolated_chat_id=isolated_chat.chat_id,
                                    agent_id=tool_call.agent_id or "system",
                                    agent=tool_call.agent_id or "system",
                                    role="assistant",
                                    content=result_for_isolated,
                                    message_type="tool_call",
                                    isolated_message_id=str(
                                        uuid_lib.uuid4()
                                    ),  # Generate NEW UUID to avoid UNIQUE constraint error
                                    tool_call_id=tool_call.tool_call_id,  # Keep original ID for grouping
                                    tool_called=tool_call.tool_name,
                                    tool_call_type="output",
                                )
                                debug(
                                    f"[ExternalToolWorker] save_isolated_message() concluído, committing session"
                                )

                                # NOTE: GeneratedContent foi salvo em Core.py quando a tool foi enfileirada
                                # NÃO salvar novamente aqui para evitar UNIQUE constraint error
                                # O worker apenas processa e retorna resultado - o salvamento foi feito em Core
                                debug(
                                    f"[ExternalToolWorker] Generated content já foi salvo em Core.py (ID: {tool_call.generated_content_id})"
                                )

                                session.commit()
                                info(
                                    f"[ExternalToolWorker] ✅ Complete result saved to isolated_messages with UUID {tool_call.tool_call_id}"
                                )

                                # Sync intermediário: propaga o output da tool para o main chat
                                # via db_updated, MAS não marca o job como completed.
                                # job_id="" → SyncWorker pula o mark_completed neste sync.
                                # resume_after_tool_call → process_message → enfileira sync
                                # final com job_id real → SyncWorker marca completed depois
                                # que a resposta final do LLM já está no main chat.
                                debug(
                                    f"[ExternalToolWorker] Enfileirando sync intermediário (sem mark_completed)"
                                )
                                self.queue_manager.enqueue_sync_message(
                                    chat_id=tool_call.chat_id,
                                    agent_id=tool_call.agent_id or "system",
                                    job_id="",  # Vazio → SyncWorker não marca completed aqui
                                    user_id=tool_call.user_id,
                                )
                                debug(
                                    f"[ExternalToolWorker] Sync intermediário enqueued para {tool_call.tool_name}"
                                )
                            except Exception as e:
                                import traceback

                                error(
                                    f"[ExternalToolWorker] ❌ Erro ao salvar resultado: {str(e)}"
                                )
                                error(
                                    f"[ExternalToolWorker] Traceback: {traceback.format_exc()}"
                                )
                                session.rollback()
                                error(f"[ExternalToolWorker] Session rolled back")
                            finally:
                                session.close()
                                debug(f"[ExternalToolWorker] Sessão fechada")
                        except Exception as e:
                            import traceback

                            error(
                                f"[ExternalToolWorker] ❌ Erro ao obter sessão: {str(e)}"
                            )
                            error(
                                f"[ExternalToolWorker] Traceback: {traceback.format_exc()}"
                            )

                    # Mark as completed and enqueue for sync
                    debug(f"[ExternalToolWorker] Marcando tool_call como completed")
                    self.queue_manager.mark_tool_call_completed(
                        tool_call.tool_call_id,
                        result=(
                            {"result": result}
                            if isinstance(result, dict)
                            else {"result": str(result)}
                        ),
                    )
                    debug(f"[ExternalToolWorker] ✓ Tool call marcada como completed")

                    # ========== REATIVAÇÃO: Retomar looping se job estava aguardando (wait=true) ==========
                    debug(
                        f"[ExternalToolWorker] Verificando message_processor: {self.message_processor is not None}"
                    )
                    if self.message_processor:
                        # CHECK: Verificar se o job foi cancelado antes de retomar
                        job_manager = get_job_manager()
                        # Tentar obter job pelo job_id específico primeiro
                        job = None
                        if tool_call.job_id:
                            job = job_manager.get_job(tool_call.job_id)
                            if job:
                                debug(
                                    f"[ExternalToolWorker] Job encontrado pelo job_id: {tool_call.job_id}"
                                )
                        # Fallback: procurar por chat_id se job_id não tiver sucesso
                        if not job:
                            job = job_manager.find_active_job_by_chat_id(
                                tool_call.chat_id
                            )
                            if job:
                                debug(
                                    f"[ExternalToolWorker] Job encontrado pelo chat_id (fallback): {tool_call.chat_id}"
                                )

                        if job and job.status == "cancelled":
                            warning(
                                f"[ExternalToolWorker] ⚠️ Job foi cancelado, pulando reativação para {tool_call.tool_call_id}"
                            )
                            debug(
                                f"[ExternalToolWorker] Job status: {job.status}, tool: {tool_call.tool_name}"
                            )
                        else:
                            try:
                                info(
                                    f"[ExternalToolWorker] 🔄 Ativando reativação para {tool_call.tool_call_id} ({tool_call.tool_name})"
                                )
                                debug(
                                    f"[ExternalToolWorker] Chamando resume_after_tool_call com:"
                                )
                                debug(f"  - chat_id: {tool_call.chat_id}")
                                debug(f"  - message_id: {tool_call.tool_call_id}")
                                debug(f"  - tool_name: {tool_call.tool_name}")
                                debug(f"  - user_id: {tool_call.user_id}")
                                debug(
                                    f"  - agent_id: {tool_call.agent_id or 'orchestrator-global'}"
                                )

                                # Chamar resume_after_tool_call para retomar looping com job_id correto
                                resume_result = self.message_processor.resume_after_tool_call(
                                    chat_id=tool_call.chat_id,
                                    message_id=tool_call.tool_call_id,
                                    content=result,  # Resultado da tool como contexto para próxima iteração
                                    user_id=tool_call.user_id,
                                    agent_id=tool_call.agent_id
                                    or "orchestrator-global",
                                    job_id=tool_call.job_id,  # Usar job_id do tool_call para continuar o job original
                                )
                                info(
                                    f"[ExternalToolWorker] ✅ Looping retomado para {tool_call.tool_call_id}"
                                )
                                debug(
                                    f"[ExternalToolWorker] Resume result: {resume_result}"
                                )
                            except Exception as e:
                                import traceback as _tb

                                error(
                                    f"[ExternalToolWorker] ❌ Erro ao retomar looping: {e}\n{_tb.format_exc()}"
                                )
                    else:
                        warning(
                            f"[ExternalToolWorker] MessageProcessor não disponível para reativação - job {tool_call.chat_id} permanecerá aguardando"
                        )

                    # Update stats (execution_time already calculated above)
                    self.stats.jobs_processed += 1
                    self.stats.total_execution_time += execution_time
                    self.stats.avg_execution_time = (
                        self.stats.total_execution_time / self.stats.jobs_processed
                    )

                    info(
                        f"[ExternalToolWorker] ✅ {tool_call.tool_name} completed in {execution_time:.2f}s (reactivation handled)"
                    )
                    debug(
                        f"[ExternalToolWorker] Stats updated: jobs_processed={self.stats.jobs_processed}, avg_time={self.stats.avg_execution_time:.2f}s"
                    )

                except Exception as e:
                    import traceback

                    error(
                        f"[ExternalToolWorker] ❌ ERRO ao processar {tool_call.tool_name} ({tool_call.tool_call_id}): {e}"
                    )
                    error(f"[ExternalToolWorker] Traceback: {traceback.format_exc()}")
                    self.stats.jobs_failed += 1
                    debug(
                        f"[ExternalToolWorker] Stats updated: jobs_failed={self.stats.jobs_failed}"
                    )

                    # Enfileirar sync para sobrepor a resposta de erro no main chat também
                    try:
                        debug(
                            f"[ExternalToolWorker] Enfileirando sync de erro para {tool_call.tool_name}"
                        )
                        self.queue_manager.enqueue_sync_message(
                            chat_id=tool_call.chat_id,
                            agent_id=tool_call.agent_id or "system",
                            job_id=tool_call.job_id,
                            user_id=tool_call.user_id,
                        )
                        debug(
                            f"[ExternalToolWorker] Sync de erro enfileirado para {tool_call.tool_call_id}"
                        )
                    except Exception as sync_err:
                        error(
                            f"[ExternalToolWorker] Erro ao enfileirar sync de erro: {sync_err}"
                        )

            except Exception as e:
                error(
                    f"[ExternalToolWorker] Unexpected error in worker loop: {e}",
                )
                time.sleep(1)

    def get_stats(self) -> Dict[str, Any]:
        """Get worker statistics"""
        return self.stats.to_dict()


class DocumentToolCallWorker:
    """Worker for processing document tool calls (no API limit)"""

    def __init__(self, queue_manager, core, db_manager=None, num_workers: int = 4):
        """
        Initialize document tool call worker

        Args:
            queue_manager: MultiQueueManager instance
            core: Core instance for executing tools
            db_manager: DatabaseManager instance for saving tool results
            num_workers: Number of worker threads (no API limit, can be higher)
        """
        self.queue_manager = queue_manager
        self.core = core
        self.db_manager = db_manager
        self.num_workers = num_workers
        self.executor = ThreadPoolExecutor(
            max_workers=num_workers, thread_name_prefix="document_tool_worker"
        )
        self.running = False
        self.stats = WorkerStats(operation_type="document_tool_call")

    def start(self) -> None:
        """Start the document tool worker threads"""
        if self.running:
            warning("Document tool worker is already running")
            return

        self.running = True

        for i in range(self.num_workers):
            self.executor.submit(self._worker_loop)

    def stop(self) -> None:
        """Stop document tool worker threads gracefully"""
        if not self.running:
            warning("Document tool worker is not running")
            return

        self.running = False
        self.executor.shutdown(wait=True)

    def _worker_loop(self) -> None:
        """Main worker loop - continuously dequeue and execute document tool calls"""
        while self.running:
            try:
                # Dequeue next document tool call (FIFO)
                tool_call = self.queue_manager.dequeue_tool_call(tool_type="document")

                if not tool_call:
                    continue  # BZPOPMIN will block until next tool call, no need for sleep

                info(
                    f"[DocumentToolWorker] Processing {tool_call.tool_name}: {tool_call.tool_call_id}"
                )
                start_time = time.time()

                try:
                    # Execute tool via Core (convert arguments dict to JSON string)
                    arguments_str = (
                        json.dumps(tool_call.arguments)
                        if isinstance(tool_call.arguments, dict)
                        else (tool_call.arguments or "{}")
                    )
                    result = self.core.execute_tool(
                        tool_name=tool_call.tool_name,
                        arguments=arguments_str,
                        agent_id="system",
                        chat_id=tool_call.chat_id,
                        user_id=tool_call.user_id,
                        job_id=tool_call.job_id,
                        isolated_message_id=tool_call.isolated_message_id,
                    )

                    # Mark as completed and enqueue for sync
                    self.queue_manager.mark_tool_call_completed(
                        tool_call.tool_call_id,
                        result=(
                            {"result": result}
                            if isinstance(result, dict)
                            else {"result": str(result)}
                        ),
                    )

                    execution_time = time.time() - start_time
                    self.stats.jobs_processed += 1
                    self.stats.total_execution_time += execution_time
                    self.stats.avg_execution_time = (
                        self.stats.total_execution_time / self.stats.jobs_processed
                    )

                    info(
                        f"[DocumentToolWorker] {tool_call.tool_name} completed in {execution_time:.2f}s"
                    )

                except Exception as e:
                    error(
                        f"[DocumentToolWorker] Error executing {tool_call.tool_name}: {e}",
                    )
                    self.stats.jobs_failed += 1

            except Exception as e:
                error(
                    f"[DocumentToolWorker] Unexpected error in worker loop: {e}",
                )
                time.sleep(1)

    def get_stats(self) -> Dict[str, Any]:
        """Get worker statistics"""
        return self.stats.to_dict()


class OperationWorker:
    """Worker for processing jobs of a specific operation type"""

    def __init__(
        self,
        queue_manager,
        operation_type: str,
        num_workers: int,
        core,
        db_manager=None,
    ):
        """
        Initialize an operation worker

        Args:
            queue_manager: MultiQueueManager instance
            operation_type: Type of operation (scraping, image_gen, video_gen, vision)
            num_workers: Number of worker threads
            core: Core instance for executing tools
            db_manager: DatabaseManager instance for saving results to isolated messages
        """
        self.queue_manager = queue_manager
        self.operation_type = operation_type
        self.num_workers = num_workers
        self.core = core
        self.db_manager = db_manager
        self.executor = ThreadPoolExecutor(
            max_workers=num_workers, thread_name_prefix=f"{operation_type}_worker"
        )
        self.running = False
        self.stats = WorkerStats(operation_type=operation_type)

    def start(self) -> None:
        """Start the worker threads"""
        if self.running:
            warning(f"Worker for {self.operation_type} is already running")
            return

        self.running = True

        for i in range(self.num_workers):
            self.executor.submit(self._worker_loop)

    def stop(self) -> None:
        """Stop the worker threads gracefully"""
        if not self.running:
            warning(f"Worker for {self.operation_type} is not running")
            return

        self.running = False

        # Shutdown executor gracefully
        self.executor.shutdown(wait=True)

    def _worker_loop(self) -> None:
        """Main worker loop that processes jobs"""
        while self.running:
            try:
                # Dequeue job from any chat for this operation type
                job = self.queue_manager.dequeue_job_any_chat(self.operation_type)

                if job is None:
                    # No job available, sleep briefly to allow graceful shutdown
                    time.sleep(1.0)
                    continue

                # Process the job
                self._process_job(job)

            except Exception as e:
                error(
                    f"Error in worker loop for {self.operation_type}: {str(e)}",
                )
                # Don't crash the worker, continue processing
                continue

    def _process_job(self, job: Any) -> None:
        """
        Process a single job

        Args:
            job: Job object with tool_name, arguments, agent_id, chat_id, client_id
                 or sync_specific data for sync operations
        """
        start_time = time.time()
        job_id = job.job_id
        chat_id = job.chat_id

        try:
            # Update job status to PROCESSING
            self.queue_manager.update_job_status(
                chat_id=chat_id, job_id=job_id, status=JobStatus.PROCESSING.value
            )

            # Handle tool execution (only tool execution in this worker)
            # NOTE: Sync operations are handled by SyncMessageWorker, not here
            # Extract job data
            tool_name = job.tool_name
            arguments = job.arguments or {}
            agent_id = job.agent_id
            client_id = job.client_id

            debug(f"Processing job {job_id}: {tool_name} for {self.operation_type}")

            # Execute the tool
            result = self.core.execute_tool(
                tool_name=tool_name,
                arguments=arguments,
                agent_id=agent_id,
                chat_id=chat_id,
                user_id=None,
                job_id=job_id,
            )

            # Save result to isolated messages if tool executed successfully
            if self.db_manager and client_id:
                try:
                    session = self.db_manager.get_session()
                    try:
                        self.db_manager.save_isolated_message(
                            session=session,
                            isolated_chat_id=None,  # Will be retrieved by chat_id/client_id
                            agent_id=agent_id,
                            agent=agent_id,
                            role="assistant",
                            content=result,
                            chat_id=chat_id,
                            client_id=client_id,
                        )
                        session.commit()
                        debug(
                            f"[OperationWorker] Result saved to isolated messages for {tool_name}"
                        )
                    except Exception as e:
                        session.rollback()
                        warning(
                            f"[OperationWorker] Failed to save result to isolated messages: {str(e)}"
                        )
                    finally:
                        session.close()
                except Exception as e:
                    warning(
                        f"[OperationWorker] Error saving to isolated messages: {str(e)}"
                    )

            # Update job status to COMPLETED
            execution_time = time.time() - start_time
            self.queue_manager.update_job_status(
                chat_id=chat_id,
                job_id=job_id,
                status=JobStatus.COMPLETED.value,
                result=result,
            )

            # Update stats
            self.stats.jobs_processed += 1
            self.stats.total_execution_time += execution_time
            self.stats.avg_execution_time = (
                self.stats.total_execution_time / self.stats.jobs_processed
            )

            info(
                f"Job {job_id} completed successfully in {execution_time:.2f}s "
                f"for {self.operation_type}"
            )

        except Exception as e:
            execution_time = time.time() - start_time
            error_message = str(e)

            error(
                f"Job {job_id} failed after {execution_time:.2f}s: {error_message}",
            )

            # Update job status to FAILED
            self.queue_manager.update_job_status(
                chat_id=chat_id,
                job_id=job_id,
                status=JobStatus.FAILED.value,
                result={"error": error_message},
            )

            # Update stats
            self.stats.jobs_failed += 1

    def get_stats(self) -> Dict[str, Any]:
        """
        Get worker statistics

        Returns:
            Dictionary with worker stats
        """
        return self.stats.to_dict()


class CompactorWorker:
    """Worker for compacting conversation contexts to manage token limits"""

    def __init__(
        self, queue_manager, message_processor, db_manager=None, num_workers: int = 2
    ):
        """
        Initialize compactor worker

        Args:
            queue_manager: MultiQueueManager instance
            message_processor: MessageProcessor instance
            db_manager: DatabaseManager instance
            num_workers: Number of worker threads
        """
        self.queue_manager = queue_manager
        self.message_processor = message_processor
        self.db_manager = db_manager
        self.num_workers = num_workers
        self.executor = ThreadPoolExecutor(
            max_workers=num_workers, thread_name_prefix="compactor_worker"
        )
        self.running = False
        self.stats = WorkerStats(operation_type="compactor")

    def start(self) -> None:
        """Start the compactor worker threads"""
        if self.running:
            warning("Compactor worker is already running")
            return

        self.running = True

        for i in range(self.num_workers):
            self.executor.submit(self._worker_loop, i)

        info(f"[CompactorWorker] Started {self.num_workers} workers")

    def stop(self) -> None:
        """Stop the compactor worker"""
        self.running = False
        self.executor.shutdown(wait=True)
        info(f"[CompactorWorker] Stopped")

    def _worker_loop(self, worker_id: int) -> None:
        """Worker loop for processing compactor jobs"""
        while self.running:
            try:
                # Get next compactor job from queue
                job = self.queue_manager.dequeue_job(
                    operation_type="compactor", timeout=5
                )

                if not job:
                    time.sleep(0.1)
                    continue

                info(
                    f"[CompactorWorker-{worker_id}] Processing compactor job: {job.job_id}"
                )
                start_time = time.time()

                try:
                    # Extract compactor job data
                    from App.Core.Queues.MultiQueueManager import CompactorJob

                    compactor_job = CompactorJob.from_dict(
                        job.job_data if hasattr(job, "job_data") else job.__dict__
                    )

                    # Call message processor to compact context
                    result = self.message_processor.compact_context(
                        isolated_chat_id=compactor_job.isolated_chat_id,
                        chat_id=compactor_job.chat_id,
                        client_id=compactor_job.client_id,
                        cut_isolated_message_id=compactor_job.cut_message_isolated_message_id,
                        agent_id=compactor_job.agent_id,
                    )

                    execution_time = time.time() - start_time
                    self.stats.jobs_processed += 1
                    self.stats.total_execution_time += execution_time
                    self.stats.avg_execution_time = (
                        self.stats.total_execution_time / self.stats.jobs_processed
                    )

                    info(
                        f"[CompactorWorker-{worker_id}] Context compacted in {execution_time:.2f}s | "
                        f"Result tokens: {result.get('tokens', 0)}"
                    )

                    # Mark compactor job as completed
                    self.queue_manager.mark_job_completed(
                        operation_type="compactor", job_id=job.job_id, result=result
                    )

                except Exception as e:
                    error(
                        f"[CompactorWorker-{worker_id}] Error compacting context: {e}",
                    )
                    self.stats.jobs_failed += 1
                    self.queue_manager.mark_job_failed(
                        operation_type="compactor", job_id=job.job_id, error=str(e)
                    )

            except Exception as e:
                error(
                    f"[CompactorWorker-{worker_id}] Unexpected error in worker loop: {e}",
                )
                time.sleep(1)

    def get_stats(self) -> Dict[str, Any]:
        """Get worker statistics"""
        return self.stats.to_dict()


class MultiWorkerPool:
    """Manages multiple OperationWorker instances for different operation types"""

    def __init__(
        self,
        queue_manager,
        core,
        message_processor=None,
        chat_service=None,
        db_manager=None,
    ):
        """
        Initialize the multi-worker pool

        Args:
            queue_manager: MultiQueueManager instance
            core: Core instance for executing tools
            message_processor: MessageProcessor instance (for message workers)
            chat_service: ChatService instance (for sync workers)
            db_manager: DatabaseManager instance (for sync workers)
        """
        self.queue_manager = queue_manager
        self.core = core
        self.message_processor = message_processor
        self.chat_service = chat_service
        self.db_manager = db_manager

        # Initialize MESSAGE and SYNC_MESSAGE workers (critical, high priority)
        self.message_worker = None
        self.sync_message_worker = None
        self.external_tool_worker = None
        self.document_tool_worker = None
        self.compactor_worker = None  # Context compaction worker

        if message_processor:
            self.message_worker = MessageWorker(
                queue_manager=queue_manager,
                message_processor=message_processor,
                num_workers=3,  # Process 3 messages in parallel
            )

        # Initialize SyncMessageWorker (db_manager is required, chat_service is optional)
        if db_manager:
            self.sync_message_worker = SyncMessageWorker(
                queue_manager=queue_manager,
                chat_service=chat_service,  # Can be None, will use DatabaseManager directly
                db_manager=db_manager,
                num_workers=2,  # 2 workers for parallel sync
            )

        # Initialize tool call workers (background, independent)
        self.external_tool_worker = ExternalToolCallWorker(
            queue_manager=queue_manager,
            core=core,
            db_manager=db_manager,  # For saving tool results
            message_processor=message_processor,  # For resuming after wait=true
            num_workers=2,  # Rate limited (API calls)
        )

        self.document_tool_worker = DocumentToolCallWorker(
            queue_manager=queue_manager,
            core=core,
            db_manager=db_manager,  # For saving tool results
            num_workers=4,  # No limit (internal processing)
        )

        # Initialize CompactorWorker (context compression, background)
        if message_processor and db_manager:
            self.compactor_worker = CompactorWorker(
                queue_manager=queue_manager,
                message_processor=message_processor,
                db_manager=db_manager,
                num_workers=2,  # 2 workers for parallel context compression
            )

        # Initialize workers for different operation types (background tools)
        # Configuration: operation_type -> num_workers
        workers_config = {
            "scraping": 2,
            "image_gen": 4,
            "video_gen": 2,
            "vision": 3,
            "sync": 3,  # Legacy sync per job (deprecated)
        }

        self.workers: Dict[str, OperationWorker] = {}
        for operation_type, num_workers in workers_config.items():
            self.workers[operation_type] = OperationWorker(
                queue_manager=queue_manager,
                operation_type=operation_type,
                num_workers=num_workers,
                core=core,
                db_manager=db_manager,  # Pass db_manager for saving results to isolated messages
            )

    def register_chat_service(self, chat_service, db_manager) -> None:
        """Register ChatService and initialize SyncMessageWorker"""
        self.chat_service = chat_service
        self.db_manager = db_manager

        if not self.sync_message_worker and chat_service and db_manager:
            self.sync_message_worker = SyncMessageWorker(
                queue_manager=self.queue_manager,
                chat_service=chat_service,
                db_manager=db_manager,
                num_workers=2,
            )
            info("SyncMessageWorker initialized and registered")

            # Start it if worker pool is already running
            if self.workers[list(self.workers.keys())[0]].running:
                self.sync_message_worker.start()

    @property
    def num_workers(self) -> int:
        """Calculate total number of workers across all operation types"""
        return sum(worker.num_workers for worker in self.workers.values())

    def start(self) -> None:
        """Start all workers (message, sync, tool call, and operation workers)"""
        workers_list = []

        # Start critical message workers first (priority 1)
        if self.message_worker:
            self.message_worker.start()
            workers_list.append("MessageWorker(3)")
        else:
            error(
                "[MultiWorkerPool.start] message_worker is None! Message processing will not work!"
            )
        if self.sync_message_worker:
            self.sync_message_worker.start()
            workers_list.append("SyncMessageWorker(2)")

        # Start tool call workers (priority 2)
        if self.external_tool_worker:
            self.external_tool_worker.start()
            workers_list.append("ExternalToolCallWorker(2)")
        if self.document_tool_worker:
            self.document_tool_worker.start()
            workers_list.append("DocumentToolCallWorker(4)")

        # Start compactor worker (priority 2.5 - background context compression)
        if self.compactor_worker:
            self.compactor_worker.start()
            workers_list.append("CompactorWorker(2)")

        # Start operation workers (background tools - priority 3)
        for operation_type, worker in self.workers.items():
            worker.start()
            # Get number of workers from the worker instance
            num = worker.num_workers if hasattr(worker, "num_workers") else 1
            workers_list.append(f"{operation_type}({num})")

        # Log final summary
        info(f"[WORKERS] Started: {', '.join(workers_list)}")

    def stop(self) -> None:
        """Stop all workers gracefully (message, sync, tool call, and operation workers)"""
        workers_stopped = 0

        # Stop message workers first (priority 1)
        if self.message_worker:
            self.message_worker.stop()
            workers_stopped += self.message_worker.num_workers
        if self.sync_message_worker:
            self.sync_message_worker.stop()
            workers_stopped += self.sync_message_worker.num_workers

        # Stop tool call workers (priority 2)
        if self.external_tool_worker:
            self.external_tool_worker.stop()
            workers_stopped += self.external_tool_worker.num_workers
        if self.document_tool_worker:
            self.document_tool_worker.stop()
            workers_stopped += self.document_tool_worker.num_workers

        # Stop compactor worker (priority 2.5)
        if self.compactor_worker:
            self.compactor_worker.stop()
            workers_stopped += self.compactor_worker.num_workers

        # Stop operation workers (priority 3)
        for operation_type, worker in self.workers.items():
            worker.stop()
            workers_stopped += worker.num_workers

        info(f"[WORKERS] Stopped: {workers_stopped} workers")

    def get_stats(self) -> Dict[str, Any]:
        """
        Get statistics from all workers

        Returns:
            Dictionary with stats for each operation type
        """
        all_stats = {}
        for operation_type, worker in self.workers.items():
            all_stats[operation_type] = worker.get_stats()

        return {
            "workers": all_stats,
            "timestamp": time.time(),
        }

"""Job Manager - Gerenciamento de jobs de processamento de mensagens no banco de dados."""

import uuid
import threading
import time
from datetime import datetime
from typing import Dict, Any, Optional
from App.Core.Logs import debug, info, warning, error
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager


class ProcessingJob:
    """
    Rastreia o status de um job de processamento de mensagem no banco de dados.
    Funciona como um proxy para atualizar o registro no banco em tempo real.
    """

    def __init__(self, job_id: str, chat_id: str, user_id: Optional[str] = None):
        self.job_id = job_id
        self.chat_id = chat_id
        self.user_id = user_id
        self.messages = []  # Compatibilidade com código legado que adiciona em memória
        self.steps = []  # Compatibilidade com código legado que adiciona em memória
        self._cancelled = threading.Event()

    @property
    def status(self) -> str:
        session = DatabaseManager.get_session()
        try:
            job_data = DatabaseManager.get_job(session, self.job_id)
            return job_data.get("status", "error") if job_data else "error"
        finally:
            session.close()

    @status.setter
    def status(self, value: str):
        self.set_status(value)

    def _broadcast_chat_ws(self, status: str):
        """Envia job_status ao WS do chat (qualquer mudança de status)."""
        try:
            from App.Core.Services.Chat.ChatRoutes import _broadcast_job_status

            _broadcast_job_status(
                self.chat_id, self.job_id, status, user_id=self.user_id
            )
        except Exception:
            pass

    def _notify_browser_done(self, status: str = "completed"):
        """Notifica extension/browser overlay que o job finalizou (estados terminais)."""
        if self.user_id:
            try:
                from App.Core.Services.WS.UserBrowserRouter import (
                    manager as _ws_manager,
                )

                _ws_manager.send_signal_sync(str(self.user_id), {"type": "job_done"})
            except Exception:
                pass
        self._broadcast_chat_ws(status)

    def cancel(self):
        """Sinaliza o cancelamento do job."""
        if not self.is_finished():
            self._cancelled.set()
            session = DatabaseManager.get_session()
            try:
                DatabaseManager.update_job_status(
                    session,
                    self.job_id,
                    "cancelled",
                    error_message="Job cancelled by user.",
                )
                info(f"[JOB {self.job_id}] Cancelamento solicitado")
            finally:
                session.close()
            self._notify_browser_done("cancelled")

    def is_cancelled(self) -> bool:
        """Verifica se o cancelamento foi solicitado."""
        if self._cancelled.is_set():
            return True
        return self.status == "cancelled"

    def set_status(self, new_status: str):
        """Define o status do job e notifica o frontend via WS."""
        valid_statuses = ["running", "waiting", "completed", "error", "cancelled"]
        if new_status not in valid_statuses:
            warning(f"[JOB {self.job_id}] Status inválido: {new_status}")
            return

        session = DatabaseManager.get_session()
        try:
            DatabaseManager.update_job_status(session, self.job_id, new_status)
            debug(f"[JOB {self.job_id}] Status atualizado para: {new_status}")
        finally:
            session.close()
        self._broadcast_chat_ws(new_status)

    def mark_agent_save_complete(self):
        """Marca que o salvamento do agent foi concluído."""
        # TODO: Se precisar realmente disso, tem que atualizar no banco
        pass

    def mark_completed(self, response: str):
        """Marca o job como concluído com sucesso."""
        if self.is_cancelled():
            return
        session = DatabaseManager.get_session()
        try:
            DatabaseManager.update_job_status(
                session, self.job_id, "completed", response=response
            )
            debug(f"[JOB {self.job_id}] Concluído com sucesso")
        finally:
            session.close()
        self._notify_browser_done("completed")

    def mark_error(self, error_msg: str):
        """Marca o job como erro."""
        if self.is_cancelled():
            return
        session = DatabaseManager.get_session()
        try:
            DatabaseManager.update_job_status(
                session, self.job_id, "error", error_message=error_msg
            )
            if "Limite de iterações" in error_msg:
                warning(f"[JOB {self.job_id}] {error_msg}")
            else:
                error(f"[JOB {self.job_id}] Erro: {error_msg}")
        finally:
            session.close()
        self._notify_browser_done("error")
        # Broadcast especial para limite de contexto — bloqueia o input no frontend
        if (
            "maximum context length" in error_msg
            or "context_length_exceeded" in error_msg
        ):
            try:
                from App.Core.Services.Chat.ChatRoutes import (
                    broadcast_context_limit_reached,
                )

                broadcast_context_limit_reached(self.chat_id)
            except Exception:
                pass

    def is_finished(self) -> bool:
        """Verifica se o job finalizou (completed, error ou cancelled)."""
        return self.status in ["completed", "error", "cancelled"]

    def time_since_finished(self) -> Optional[float]:
        """Retorna segundos desde que o job finalizou, ou None se ainda rodando."""
        session = DatabaseManager.get_session()
        try:
            job_data = DatabaseManager.get_job(session, self.job_id)
            if not job_data or not job_data.get("finished_at"):
                return None

            finished_at = job_data.get("finished_at")
            if isinstance(finished_at, str):
                finished_at = datetime.fromisoformat(finished_at)

            return (datetime.utcnow() - finished_at).total_seconds()
        finally:
            session.close()


class JobManager:
    """Gerencia todos os jobs de processamento usando o banco de dados."""

    # Configuração de cleanup automático
    AUTO_CLEANUP_ENABLED = False
    CLEANUP_INTERVAL = 60  # Verificar a cada minuto
    WAITING_JOB_TIMEOUT = (
        900  # Auto-complete jobs stuck in "waiting" após 15 minutos (900s)
    )

    def __init__(self):
        self._cleanup_thread = None
        self._cleanup_running = False
        self._start_auto_cleanup()

    def _start_auto_cleanup(self):
        """Inicia thread de cleanup automático."""
        if not self.AUTO_CLEANUP_ENABLED:
            return

        self._cleanup_running = True
        self._cleanup_thread = threading.Thread(
            target=self._auto_cleanup_loop, daemon=True, name="JobManager-AutoCleanup"
        )
        self._cleanup_thread.start()
        info("[JobManager] Auto-cleanup iniciado")

    def _auto_cleanup_loop(self):
        """Loop de cleanup automático executado em background."""
        # Aqui você implementaria um SELECT para buscar jobs "waiting" que já passaram de WAITING_JOB_TIMEOUT
        # e atualizaria eles para error/completed.
        # (Omitido para focar na migração principal, pode ser feito depois em DBManager)
        while self._cleanup_running:
            try:
                time.sleep(self.CLEANUP_INTERVAL)
            except Exception as e:
                error(f"[JobManager] Erro no auto-cleanup: {e}")

    def stop_auto_cleanup(self):
        """Para a thread de cleanup automático."""
        self._cleanup_running = False
        if self._cleanup_thread:
            self._cleanup_thread.join(timeout=5)
            info("[JobManager] Auto-cleanup parado")

    def create_job(self, chat_id: str, user_id: Optional[str] = None) -> ProcessingJob:
        """Cria um novo job de processamento no banco de dados."""
        job_id = str(uuid.uuid4())
        session = DatabaseManager.get_session()
        try:
            success = DatabaseManager.create_job(
                session, job_id, chat_id, user_id=user_id
            )
            if not success:
                error(
                    f"[JobManager] Falha ao criar job no banco de dados para o chat {chat_id}"
                )
            debug(f"[JobManager] Job criado: {job_id} para o chat {chat_id}")
        finally:
            session.close()

        job = ProcessingJob(job_id=job_id, chat_id=chat_id, user_id=user_id)
        job._broadcast_chat_ws("running")
        return job

    def cancel_job(self, job_id: str) -> bool:
        """Solicita o cancelamento de um job em execução."""
        job = self.get_job(job_id)
        if job and not job.is_finished():
            job.cancel()
            return True
        warning(
            f"[JobManager] Tentativa de cancelar job não encontrado ou já finalizado: {job_id}"
        )
        return False

    def find_active_job_by_user_id(self, user_id: str) -> Optional[ProcessingJob]:
        """Encontra o job ativo mais recente para um user_id."""
        session = DatabaseManager.get_session()
        try:
            # Prefer direct user_id column; fall back to JOIN with chats for older jobs
            row = DatabaseManager.fetch_one(
                "SELECT job_id, chat_id FROM jobs "
                "WHERE user_id = :user_id AND status = 'running' "
                "ORDER BY created_at DESC LIMIT 1",
                {"user_id": str(user_id)},
            )
            if not row:
                row = DatabaseManager.fetch_one(
                    "SELECT j.job_id, j.chat_id FROM jobs j "
                    "JOIN chats c ON j.chat_id = c.chat_id "
                    "WHERE c.user_id = :user_id AND j.status = 'running' "
                    "ORDER BY j.created_at DESC LIMIT 1",
                    {"user_id": str(user_id)},
                )
            if row:
                return ProcessingJob(
                    job_id=row["job_id"], chat_id=row["chat_id"], user_id=str(user_id)
                )
            return None
        except Exception as e:
            error(f"[JobManager] find_active_job_by_user_id erro: {e}")
            return None
        finally:
            session.close()

    def find_active_job_by_chat_id(self, chat_id: str) -> Optional[ProcessingJob]:
        """Encontra o job ativo mais recente (não finalizado) para um chat específico."""
        session = DatabaseManager.get_session()
        try:
            job_data = DatabaseManager.find_latest_active_job(session, chat_id)
            if job_data:
                debug(
                    f"[JobManager] Job ativo mais recente encontrado para chat {chat_id}: {job_data['job_id']}"
                )
                return ProcessingJob(
                    job_id=job_data["job_id"],
                    chat_id=chat_id,
                    user_id=job_data.get("user_id"),
                )
            return None
        finally:
            session.close()

    def get_job(self, job_id: str) -> Optional[ProcessingJob]:
        """Obtém um job pelo ID."""
        session = DatabaseManager.get_session()
        try:
            job_data = DatabaseManager.get_job(session, job_id)
            if job_data:
                return ProcessingJob(
                    job_id=job_id,
                    chat_id=job_data["chat_id"],
                    user_id=job_data.get("user_id"),
                )
            return None
        finally:
            session.close()

    def get_job_status(self, job_id: str) -> Dict[str, Any]:
        """Retorna status detalhado de um job direto do banco."""
        session = DatabaseManager.get_session()
        try:
            job_data = DatabaseManager.get_job(session, job_id)
            if not job_data:
                return {"not_found": True, "error": f"Job {job_id} não encontrado"}

            is_finished = job_data["status"] in ["completed", "error", "cancelled"]

            created_at_iso = (
                job_data["created_at"].isoformat()
                if isinstance(job_data["created_at"], datetime)
                else job_data["created_at"]
            )

            finished_at_iso = None
            if job_data["finished_at"]:
                finished_at_iso = (
                    job_data["finished_at"].isoformat()
                    if isinstance(job_data["finished_at"], datetime)
                    else job_data["finished_at"]
                )

            result = {
                "success": job_data["status"] == "completed",
                "job_id": job_id,
                "status": job_data["status"],
                "finished": is_finished,
                "messages": [],  # Backward compat
                "messages_count": 0,
                "steps": [],  # Backward compat
                "response": job_data["response"] if is_finished else None,
                "error": (
                    job_data["error_message"]
                    if is_finished and job_data["status"] == "error"
                    else None
                ),
                "created_at": created_at_iso,
                "finished_at": finished_at_iso,
            }
            return result
        except Exception as e:
            error(f"[JobManager.get_job_status] Exception ao buscar status: {e}")
            return {"error": str(e)}
        finally:
            session.close()

    def cleanup_job(self, job_id: str):
        """No DB backed manager, cleanup is not necessary as jobs are persistent."""
        debug(
            f"[JobManager] cleanup_job ignorado - usando persistência em banco: {job_id}"
        )

    def get_stats(self) -> Dict[str, Any]:
        """Retorna estatísticas dos jobs do banco de dados usando SQL puro."""
        session = DatabaseManager.get_session()
        try:
            total_jobs = session.execute(text("SELECT COUNT(*) FROM jobs")).scalar()
            running_count = session.execute(
                text("SELECT COUNT(*) FROM jobs WHERE status = 'running'")
            ).scalar()
            completed_count = session.execute(
                text("SELECT COUNT(*) FROM jobs WHERE status = 'completed'")
            ).scalar()
            error_count = session.execute(
                text("SELECT COUNT(*) FROM jobs WHERE status = 'error'")
            ).scalar()

            return {
                "total_jobs": total_jobs,
                "running": running_count,
                "completed": completed_count,
                "error": error_count,
                "auto_cleanup_enabled": self.AUTO_CLEANUP_ENABLED,
            }
        except Exception as e:
            error(f"[JobManager.get_stats] Erro: {e}")
            return {"error": str(e)}
        finally:
            session.close()

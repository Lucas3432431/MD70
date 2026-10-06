"""
Gerenciador de Scheduler - APScheduler
Responsável por executar jobs agendados (ex: cobranças de subscrição, tasks de usuário)
"""

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.executors.pool import ThreadPoolExecutor
import logging
from datetime import datetime, timedelta, timezone

from App.Core.Logs import info, warning, error, debug
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Core.Services.Subscription.StripePaymentService import (
    get_stripe_payment_service,
)

# Janela de catch-up: tasks vencidas há mais de 2h não são recuperadas
MISFIRE_GRACE_SECONDS = 7200


def _make_cron_trigger(cron_expr: str, utc_offset: int) -> CronTrigger:
    """Cria um CronTrigger no fuso do usuário (offset fixo em horas)."""
    tz = timezone(timedelta(hours=utc_offset))
    return CronTrigger.from_crontab(cron_expr, timezone=tz)


def _job_id(task_id: str) -> str:
    return f"scheduled_task_{task_id}"


class SchedulerManager:
    """Gerenciador de agendamento com APScheduler"""

    _instance = None
    _scheduler = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SchedulerManager, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if self._scheduler is None:
            self._setup_scheduler()

    def _setup_scheduler(self):
        try:
            config = {
                "jobstores": {"default": MemoryJobStore()},
                "executors": {"default": ThreadPoolExecutor(max_workers=10)},
                "job_defaults": {"coalesce": True, "max_instances": 1},
            }
            self._scheduler = BackgroundScheduler(config)

            logging.getLogger("apscheduler.schedulers.background").setLevel(
                logging.WARNING
            )
            logging.getLogger("apscheduler.executors.default").setLevel(logging.WARNING)

            # Cancelamentos de subscription annual — diariamente às 2:00 AM UTC
            self._scheduler.add_job(
                process_annual_subscription_cancellations,
                CronTrigger(hour=2, minute=0),
                id="process_annual_subscription_cancellations",
                name="Process Annual Subscription Cancellations",
                replace_existing=True,
            )
            info(
                "[SCHEDULER] Job 'process_annual_subscription_cancellations' adicionado (diariamente às 2:00 AM)"
            )
            info("[SCHEDULER] APScheduler configurado com sucesso")

        except Exception as e:
            error(f"[SCHEDULER] Erro ao configurar scheduler: {e}")
            raise

    def start(self):
        try:
            if self._scheduler and not self._scheduler.running:
                self._scheduler.start()
                info("[SCHEDULER] Scheduler iniciado")
        except Exception as e:
            error(f"[SCHEDULER] Erro ao iniciar scheduler: {e}")
            raise

    def stop(self):
        try:
            if self._scheduler and self._scheduler.running:
                self._scheduler.shutdown()
                info("[SCHEDULER] Scheduler parado")
        except Exception as e:
            error(f"[SCHEDULER] Erro ao parar scheduler: {e}")

    # ------------------------------------------------------------------ generic

    def add_job(self, func, trigger, **kwargs):
        try:
            job_id = kwargs.pop("id", func.__name__)
            self._scheduler.add_job(func, trigger, id=job_id, **kwargs)
            info(f"[SCHEDULER] Job adicionado - job_id={job_id}")
        except Exception as e:
            error(f"[SCHEDULER] Erro ao adicionar job: {e}")
            raise

    def get_scheduler(self):
        return self._scheduler

    # ------------------------------------------------------------------ tasks por usuário

    def load_tasks_from_db(self):
        """Carrega todas as tasks ativas do banco no startup e registra no APScheduler."""
        try:
            db = DatabaseManager()
            tasks = db.fetch_all(
                """SELECT id, cron_expression, utc_offset, last_executed_at, updated_at
                   FROM scheduled_tasks WHERE status = 'active'""",
                {},
            )
            if not tasks:
                info("[SCHEDULER] Nenhuma scheduled task ativa para carregar")
                return

            count = 0
            for task in tasks:
                try:
                    self._register_task_job(
                        task["id"], task["cron_expression"], task.get("utc_offset") or 0
                    )
                    count += 1
                    self._catchup_if_missed(task)
                except Exception as e:
                    warning(f"[SCHEDULER] Falha ao registrar task={task['id']}: {e}")

            info(f"[SCHEDULER] {count} scheduled task(s) carregada(s) do banco")
        except Exception as e:
            error(f"[SCHEDULER] Erro ao carregar tasks do banco: {e}")

    def add_task(self, task: dict):
        """Registra uma nova task no APScheduler após criação."""
        task_id = task["id"]
        cron_expr = task["cron_expression"]
        utc_offset = task.get("utc_offset") or 0
        try:
            self._register_task_job(task_id, cron_expr, utc_offset)
            info(f"[SCHEDULER] Task adicionada ao scheduler — task_id={task_id}")
        except Exception as e:
            error(f"[SCHEDULER] Erro ao adicionar task={task_id}: {e}")

    def update_task(self, task: dict):
        """Atualiza trigger de uma task existente. Se pausada, remove o job."""
        task_id = task["id"]
        status = task.get("status", "active")
        jid = _job_id(task_id)

        try:
            if status == "paused":
                self._remove_job_if_exists(jid)
                info(f"[SCHEDULER] Task pausada — job removido task_id={task_id}")
                return

            cron_expr = task["cron_expression"]
            utc_offset = task.get("utc_offset") or 0
            trigger = _make_cron_trigger(cron_expr, utc_offset)

            existing = self._scheduler.get_job(jid)
            if existing:
                self._scheduler.reschedule_job(jid, trigger=trigger)
                info(
                    f"[SCHEDULER] Task reagendada — task_id={task_id}, cron={cron_expr}"
                )
            else:
                self._register_task_job(task_id, cron_expr, utc_offset)
                info(f"[SCHEDULER] Task (re)ativada — task_id={task_id}")
        except Exception as e:
            error(f"[SCHEDULER] Erro ao atualizar task={task_id}: {e}")

    def remove_task(self, task_id: str):
        """Remove task do APScheduler após deleção."""
        self._remove_job_if_exists(_job_id(task_id))
        info(f"[SCHEDULER] Task removida do scheduler — task_id={task_id}")

    # ------------------------------------------------------------------ internos

    def _register_task_job(self, task_id: str, cron_expr: str, utc_offset: int):
        import functools

        trigger = _make_cron_trigger(cron_expr, utc_offset)
        self._scheduler.add_job(
            functools.partial(run_task_job, task_id),
            trigger,
            id=_job_id(task_id),
            name=f"ScheduledTask:{task_id}",
            replace_existing=True,
            misfire_grace_time=MISFIRE_GRACE_SECONDS,
            max_instances=1,
            coalesce=True,
        )

    def _remove_job_if_exists(self, job_id: str):
        try:
            job = self._scheduler.get_job(job_id)
            if job:
                self._scheduler.remove_job(job_id)
        except Exception:
            pass

    def _catchup_if_missed(self, task: dict):
        """Dispara imediatamente se a task perdeu seu horário no último restart (janela 2h)."""
        import threading
        import functools

        task_id = task["id"]
        cron_expr = task["cron_expression"]
        utc_offset = task.get("utc_offset") or 0
        now_utc = datetime.utcnow()

        # Se já executou desde o último updated_at, nada a recuperar
        if task.get("last_executed_at"):
            return

        # updated_at é sempre salvo em UTC pelo ScheduledService
        updated_at = task.get("updated_at")
        if not updated_at:
            return
        try:
            reference_utc = datetime.fromisoformat(str(updated_at).replace("Z", ""))
        except Exception:
            return

        if now_utc - reference_utc > timedelta(hours=2):
            return

        try:
            from croniter import croniter

            reference_local = reference_utc + timedelta(hours=utc_offset)
            now_local = now_utc + timedelta(hours=utc_offset)
            next_local = croniter(cron_expr, reference_local).get_next(datetime)
            if next_local <= now_local:
                info(
                    f"[SCHEDULER] Catch-up: task={task_id} deveria ter disparado às {next_local} (local) — executando agora"
                )
                threading.Thread(
                    target=functools.partial(run_task_job, task_id), daemon=True
                ).start()
        except Exception as e:
            warning(f"[SCHEDULER] Catch-up check falhou para task={task_id}: {e}")


# ─── Helpers standalone ──────────────────────────────────────────────────────


def _remove_task_job(task_id: str):
    """Remove o job do APScheduler sem precisar da instância do manager."""
    manager = get_scheduler_manager()
    manager._remove_job_if_exists(_job_id(task_id))


# ─── Job de execução por task ─────────────────────────────────────────────────


def run_task_job(task_id: str):
    """
    Chamado pelo APScheduler no horário cron de cada task.
    Despacha a execução e atualiza last_executed_at / next_execution_at.
    """
    try:
        db = DatabaseManager()
        task = db.fetch_one(
            """SELECT id, user_id, name, cron_expression, cron_label, prompt, integrations,
                      COALESCE(autonomy_level, 4) as autonomy_level,
                      COALESCE(utc_offset, 0) as utc_offset
               FROM scheduled_tasks
               WHERE id = :id AND status = 'active'""",
            {"id": task_id},
        )
        if not task:
            warning(f"[SCHEDULER] Task não encontrada ou inativa — task_id={task_id}")
            return

        _dispatch_task(task, db)

    except Exception as e:
        error(f"[SCHEDULER] Erro em run_task_job task={task_id}: {e}")


def _dispatch_task(task: dict, db: DatabaseManager):
    """Cria task_execution, chat e enfileira mensagem para o agente."""
    import uuid as _uuid
    import json as _json

    task_id = task["id"]
    user_id = task["user_id"]
    utc_offset = task.get("utc_offset") or 0
    now_utc = datetime.utcnow()
    now_local = now_utc + timedelta(hours=utc_offset)  # hora local do usuário

    try:
        from croniter import croniter

        next_local = croniter(task["cron_expression"], now_local).get_next(datetime)
    except Exception:
        next_local = None

    execution_id = str(_uuid.uuid4())
    chat_id = str(_uuid.uuid4())

    integrations = task.get("integrations") or []
    if isinstance(integrations, str):
        try:
            integrations = _json.loads(integrations)
        except Exception:
            integrations = []

    # Timestamps visíveis ao usuário são salvos em hora local (utc_offset aplicado)
    db.execute_query(
        """INSERT INTO chats (chat_id, user_id, chat_name, connections, status, source, seen, created_at, updated_at)
           VALUES (:chat_id, :user_id, :chat_name, :connections, 'active', 'scheduled', 0, :now, :now)""",
        {
            "chat_id": chat_id,
            "user_id": user_id,
            "chat_name": f"Agendamento: {task['name']}",
            "connections": _json.dumps(integrations),
            "now": now_local.isoformat(),
        },
    )
    db.execute_query(
        """INSERT INTO task_executions (id, task_id, user_id, chat_id, status, started_at, created_at)
           VALUES (:id, :task_id, :user_id, :chat_id, 'running', :now, :now)""",
        {
            "id": execution_id,
            "task_id": task_id,
            "user_id": user_id,
            "chat_id": chat_id,
            "now": now_local.isoformat(),
        },
    )
    is_one_time = str(task.get("cron_label") or "").startswith("Uma vez")

    db.execute_query(
        """UPDATE scheduled_tasks
           SET last_executed_at = :now,
               next_execution_at = :next_run,
               status = :status,
               updated_at = :now
           WHERE id = :task_id""",
        {
            "now": now_local.isoformat(),
            "next_run": None
            if is_one_time
            else (next_local.isoformat() if next_local else None),
            "status": "paused" if is_one_time else "active",
            "task_id": task_id,
        },
    )

    if is_one_time:
        try:
            _remove_task_job(task_id)
        except Exception:
            pass
        info(
            f"[SCHEDULER] Tarefa única '{task['name']}' executada e pausada — execution_id={execution_id}"
        )
    else:
        info(
            f"[SCHEDULER] Tarefa '{task['name']}' disparada — execution_id={execution_id}, próxima={next_local}"
        )

    _AUTONOMY_CTX = {
        1: "[Nível 1 — Sem autonomia] Apenas analise e responda em texto. Nenhuma tool externa será executada.",
        2: "[Nível 2 — Acesso a dados] Você pode consultar dados (leitura). Ações de escrita/envio aguardam aprovação humana.",
    }
    autonomy = task.get("autonomy_level", 3)
    autonomy_prefix = _AUTONOMY_CTX.get(autonomy, "")
    content = (
        f"{autonomy_prefix}\n{task['prompt']}".strip()
        if autonomy_prefix
        else task["prompt"]
    )

    try:
        from App.Core.Services.Common.Dependencies import COMPONENTS
        from App.Core.Queues.MultiQueueManager import Message

        queue_manager = COMPONENTS.get("queue_manager")
        if queue_manager:
            msg = Message(
                message_id=str(_uuid.uuid4()),
                chat_id=chat_id,
                job_id=execution_id,
                user_id=user_id,
                role="user",
                content=content,
                agent_id="orchestrator-global",
            )
            queue_manager.enqueue_message(msg)
            info(
                f"[SCHEDULER] Mensagem enfileirada — chat={chat_id}, task={task_id}, autonomia={autonomy}"
            )
        else:
            warning(f"[SCHEDULER] queue_manager não disponível para task={task_id}")
            db.execute_query(
                "UPDATE task_executions SET status='failed', finished_at=:now WHERE id=:id",
                {"now": now_utc.isoformat(), "id": execution_id},
            )
    except Exception as dispatch_err:
        warning(f"[SCHEDULER] Dispatch falhou para task={task_id}: {dispatch_err}")
        db.execute_query(
            "UPDATE task_executions SET status='failed', finished_at=:now WHERE id=:id",
            {"now": now_utc.isoformat(), "id": execution_id},
        )


# ─── Job de subscrição (mantido) ─────────────────────────────────────────────


def process_annual_subscription_cancellations():
    """Processa cancelamentos de subscriptions annual após 12 meses."""
    try:
        debug(
            "[SCHEDULER] Iniciando processamento de cancelamentos de subscription annual"
        )
        db = DatabaseManager()
        stripe_service = get_stripe_payment_service()

        subscriptions_to_cancel = db.fetch_all(
            """SELECT subscription_id, client_id, stripe_customer_id, billing_cycle, stripe_subscription_id
               FROM billing_subscriptions
               WHERE auto_renew = 0
                 AND billing_cycle = 'annual'
                 AND status = 'active'
                 AND renewal_date IS NOT NULL
                 AND renewal_date <= datetime('now')""",
            {},
        )
        if not subscriptions_to_cancel:
            debug("[SCHEDULER] Nenhuma subscription annual para cancelar")
            return

        info(
            f"[SCHEDULER] Encontradas {len(subscriptions_to_cancel)} subscriptions para cancelar"
        )
        free_plan = db.fetch_one(
            "SELECT plan_id FROM plans WHERE plan_type = 'free' OR name = 'Free' LIMIT 1",
            {},
        )
        free_plan_id = free_plan.get("plan_id") if free_plan else None

        for sub in subscriptions_to_cancel:
            subscription_id = sub.get("subscription_id")
            client_id = sub.get("client_id")
            billing_cycle = sub.get("billing_cycle")
            stripe_subscription_id = sub.get("stripe_subscription_id")
            try:
                if billing_cycle == "annual" and stripe_subscription_id:
                    cancel_success, cancel_error = stripe_service.cancel_subscription(
                        stripe_subscription_id
                    )
                    if not cancel_success:
                        warning(
                            f"[SCHEDULER] Falha ao cancelar no Stripe: {cancel_error} — subscription_id={subscription_id}"
                        )
                        continue
                    info(
                        f"[SCHEDULER] Subscription cancelada no Stripe — subscription_id={subscription_id}"
                    )

                db.execute_query(
                    """UPDATE billing_subscriptions
                       SET status = 'canceled', canceled_at = datetime('now'), updated_at = datetime('now')
                       WHERE subscription_id = :subscription_id""",
                    {"subscription_id": subscription_id},
                )
                if free_plan_id and client_id:
                    db.execute_query(
                        "UPDATE clients SET plan_id = :plan_id, updated_at = CURRENT_TIMESTAMP WHERE client_id = :client_id",
                        {"plan_id": free_plan_id, "client_id": client_id},
                    )
            except Exception as e:
                error(
                    f"[SCHEDULER] Erro ao processar cancelamento {subscription_id}: {e}"
                )

        info(
            f"[SCHEDULER] Processamento concluído — {len(subscriptions_to_cancel)} processadas"
        )
    except Exception as e:
        error(f"[SCHEDULER] Erro ao processar cancelamentos: {e}")
        import traceback

        error(f"[SCHEDULER] Traceback: {traceback.format_exc()}")


# ─── Instância global ─────────────────────────────────────────────────────────

_scheduler_manager = None


def get_scheduler_manager() -> SchedulerManager:
    global _scheduler_manager
    if _scheduler_manager is None:
        _scheduler_manager = SchedulerManager()
    return _scheduler_manager

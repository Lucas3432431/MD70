"""
ScheduledService — CRUD de scheduled_tasks e task_executions.
"""

import uuid
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import text

from App.Core.Crunch.TablesSQL.Models import ScheduledTask, TaskExecution
from App.Core.Logs import error


class ScheduledService:
    # ------------------------------------------------------------------ tasks

    def list_tasks(self, db: Session, user_id: str) -> list:
        tasks = (
            db.query(ScheduledTask)
            .filter(ScheduledTask.user_id == user_id)
            .order_by(ScheduledTask.created_at.desc())
            .all()
        )
        return [self._task_to_dict(t) for t in tasks]

    def get_task(self, db: Session, task_id: str, user_id: str) -> Optional[dict]:
        t = (
            db.query(ScheduledTask)
            .filter(ScheduledTask.id == task_id, ScheduledTask.user_id == user_id)
            .first()
        )
        return self._task_to_dict(t) if t else None

    def _next_local(self, cron_expr: str, utc_offset: int) -> datetime | None:
        """Calcula a próxima execução em hora local do usuário."""
        try:
            from croniter import croniter

            now_utc = datetime.utcnow()
            now_local = now_utc + timedelta(hours=utc_offset)
            return croniter(cron_expr, now_local).get_next(datetime)
        except Exception:
            return None

    def create_task(self, db: Session, user_id: str, data: dict) -> dict:
        utc_offset = data.get("utc_offset", 0) or 0
        next_exec = self._next_local(data["cron_expression"], utc_offset)
        task = ScheduledTask(
            id=str(uuid.uuid4()),
            user_id=user_id,
            name=data["name"],
            description=data.get("description"),
            cron_expression=data["cron_expression"],
            cron_label=data.get("cron_label"),
            prompt=data["prompt"],
            integrations=data.get("integrations", []),
            autonomy_level=data.get("autonomy_level", 4),
            utc_offset=utc_offset,
            status="active",
            next_execution_at=next_exec,
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        return self._task_to_dict(task)

    def update_task(
        self, db: Session, task_id: str, user_id: str, data: dict
    ) -> Optional[dict]:
        task = (
            db.query(ScheduledTask)
            .filter(ScheduledTask.id == task_id, ScheduledTask.user_id == user_id)
            .first()
        )
        if not task:
            return None
        cron_changed = (
            "cron_expression" in data
            and data["cron_expression"] != task.cron_expression
        )
        for field in (
            "name",
            "description",
            "cron_expression",
            "cron_label",
            "prompt",
            "integrations",
            "autonomy_level",
            "utc_offset",
            "status",
        ):
            if field in data:
                setattr(task, field, data[field])
        if cron_changed or "utc_offset" in data:
            task.next_execution_at = self._next_local(
                task.cron_expression, task.utc_offset or 0
            )
        task.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(task)
        return self._task_to_dict(task)

    def delete_task(self, db: Session, task_id: str, user_id: str) -> bool:
        task = (
            db.query(ScheduledTask)
            .filter(ScheduledTask.id == task_id, ScheduledTask.user_id == user_id)
            .first()
        )
        if not task:
            return False
        db.delete(task)
        db.commit()
        return True

    # -------------------------------------------------------------- executions

    def list_executions(
        self, db: Session, user_id: str, task_id: Optional[str] = None
    ) -> list:
        if task_id:
            rows = (
                db.execute(
                    text(
                        """SELECT te.id, te.task_id, te.user_id, te.chat_id, te.status,
                               te.result_summary, te.started_at, te.finished_at, te.created_at,
                               COALESCE(c.seen, 1) AS chat_seen
                          FROM task_executions te
                          LEFT JOIN chats c ON te.chat_id = c.chat_id
                         WHERE te.user_id = :uid AND te.task_id = :tid
                         ORDER BY te.created_at DESC"""
                    ),
                    {"uid": user_id, "tid": task_id},
                )
                .mappings()
                .all()
            )
        else:
            rows = (
                db.execute(
                    text(
                        """SELECT te.id, te.task_id, te.user_id, te.chat_id, te.status,
                               te.result_summary, te.started_at, te.finished_at, te.created_at,
                               COALESCE(c.seen, 1) AS chat_seen
                          FROM task_executions te
                          LEFT JOIN chats c ON te.chat_id = c.chat_id
                         WHERE te.user_id = :uid
                         ORDER BY te.created_at DESC"""
                    ),
                    {"uid": user_id},
                )
                .mappings()
                .all()
            )
        return [self._row_to_exec_dict(r) for r in rows]

    def list_pending(self, db: Session, user_id: str) -> list:
        rows = (
            db.execute(
                text(
                    """SELECT te.id, te.task_id, te.user_id, te.chat_id, te.status,
                           te.result_summary, te.started_at, te.finished_at, te.created_at,
                           COALESCE(c.seen, 1) AS chat_seen
                      FROM task_executions te
                      INNER JOIN chats c ON te.chat_id = c.chat_id
                     WHERE te.user_id = :uid AND c.seen = 0
                     ORDER BY te.created_at DESC"""
                ),
                {"uid": user_id},
            )
            .mappings()
            .all()
        )
        return [self._row_to_exec_dict(r) for r in rows]

    def pending_count(self, db: Session, user_id: str) -> int:
        row = (
            db.execute(
                text(
                    """SELECT COUNT(*) as n
                   FROM task_executions te
                   INNER JOIN chats c ON te.chat_id = c.chat_id
                   WHERE te.user_id = :uid AND c.seen = 0"""
                ),
                {"uid": user_id},
            )
            .mappings()
            .first()
        )
        return row["n"] if row else 0

    def set_execution_status(
        self, db: Session, execution_id: str, user_id: str, status: str
    ) -> Optional[dict]:
        ex = (
            db.query(TaskExecution)
            .filter(TaskExecution.id == execution_id, TaskExecution.user_id == user_id)
            .first()
        )
        if not ex:
            return None
        ex.status = status
        if status in ("approved", "rejected", "completed", "failed"):
            ex.finished_at = datetime.utcnow()
        db.commit()
        db.refresh(ex)
        return self._exec_to_dict(ex)

    # ----------------------------------------------------------------- helpers

    def _task_to_dict(self, t: ScheduledTask) -> dict:
        return {
            "id": t.id,
            "user_id": t.user_id,
            "name": t.name,
            "description": t.description,
            "cron_expression": t.cron_expression,
            "cron_label": t.cron_label,
            "prompt": t.prompt,
            "integrations": t.integrations or [],
            "autonomy_level": t.autonomy_level or 4,
            "utc_offset": t.utc_offset or 0,
            "status": t.status,
            "last_executed_at": t.last_executed_at.isoformat()
            if t.last_executed_at
            else None,
            "next_execution_at": t.next_execution_at.isoformat()
            if t.next_execution_at
            else None,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        }

    def _exec_to_dict(self, e: TaskExecution) -> dict:
        return {
            "id": e.id,
            "task_id": e.task_id,
            "user_id": e.user_id,
            "chat_id": e.chat_id,
            "chat_seen": 1,
            "status": e.status,
            "result_summary": e.result_summary,
            "started_at": e.started_at.isoformat() if e.started_at else None,
            "finished_at": e.finished_at.isoformat() if e.finished_at else None,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }

    def _row_to_exec_dict(self, r) -> dict:
        def _iso(v):
            return v.isoformat() if hasattr(v, "isoformat") else v

        return {
            "id": r["id"],
            "task_id": r["task_id"],
            "user_id": r["user_id"],
            "chat_id": r["chat_id"],
            "chat_seen": int(r["chat_seen"] if r["chat_seen"] is not None else 1),
            "status": r["status"],
            "result_summary": r["result_summary"],
            "started_at": _iso(r["started_at"]),
            "finished_at": _iso(r["finished_at"]),
            "created_at": _iso(r["created_at"]),
        }

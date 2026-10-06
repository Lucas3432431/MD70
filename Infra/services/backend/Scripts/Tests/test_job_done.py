"""
Test: job lifecycle + job_done WS signal.

Run from the backend service root:
    python test_job_done.py [user_id]

If user_id is omitted, fetches the first user from the DB.
Requires the backend to be running (WS must be connected) for the
final WS signal test; the DB flow works standalone.
"""

import sys
import os
import asyncio

# Garante que os módulos do backend estão no path independente do CWD
_BACKEND_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "../..")
)
sys.path.insert(0, _BACKEND_ROOT)
os.chdir(_BACKEND_ROOT)

from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Features.Job.JobManager import JobManager, ProcessingJob
from App.Core.Logs import info, error

# ─────────────────────────────────────────────────────────────────────────────


def get_test_user_id(override: str | None) -> str:
    if override:
        return override
    row = DatabaseManager.fetch_one("SELECT user_id FROM users LIMIT 1", {})
    if not row:
        raise RuntimeError("Nenhum user encontrado no banco.")
    return row["user_id"]


def test_create_job(jm: JobManager, chat_id: str, user_id: str) -> ProcessingJob:
    print(f"\n[1] Criando job para chat={chat_id}, user={user_id}")
    job = jm.create_job(chat_id=chat_id, user_id=user_id)
    print(f"    job_id  = {job.job_id}")
    print(f"    user_id = {job.user_id}")  # deve ser não-None
    assert (
        job.user_id == user_id
    ), f"FALHA: user_id no objeto é {job.user_id!r}, esperado {user_id!r}"
    print("    OK: user_id preservado no ProcessingJob")
    return job


def test_get_job_preserves_user_id(jm: JobManager, job_id: str, expected_user_id: str):
    print(f"\n[2] Recuperando job via get_job({job_id})")
    fetched = jm.get_job(job_id)
    if fetched is None:
        print("    FALHA: get_job retornou None")
        return
    print(f"    user_id = {fetched.user_id!r}")
    if fetched.user_id != expected_user_id:
        print(
            f"    *** FALHA ***: user_id é {fetched.user_id!r}, esperado {expected_user_id!r}"
        )
        print("    Este é o bug — get_job não repassa user_id ao ProcessingJob")
    else:
        print("    OK: user_id preservado após get_job")


def test_db_row_has_user_id(job_id: str, expected_user_id: str):
    print(f"\n[3] Verificando coluna user_id no banco para job {job_id}")
    session = DatabaseManager.get_session()
    try:
        job_data = DatabaseManager.get_job(session, job_id)
        if not job_data:
            print("    FALHA: job não encontrado no banco")
            return
        db_uid = job_data.get("user_id")
        print(f"    user_id no banco = {db_uid!r}")
        if db_uid != expected_user_id:
            print(
                f"    *** FALHA ***: banco tem {db_uid!r}, esperado {expected_user_id!r}"
            )
            print(
                "    Possível causa: coluna user_id ainda não existe (migration pendente)"
            )
        else:
            print("    OK: banco tem user_id correto")
    finally:
        session.close()


def test_notify_browser_done(job: ProcessingJob):
    print(f"\n[4] Testando _notify_browser_done() para user={job.user_id}")
    try:
        from App.Core.Services.WS.UserBrowserRouter import manager as ws_manager

        connected = job.user_id in ws_manager.active_connections
        print(f"    WS conectado para user: {connected}")
        if not connected:
            print(
                "    INFO: extensão não conectada — sinal não será enviado (esperado em teste isolado)"
            )
        else:
            print("    Enviando job_done via send_signal_sync...")
            ws_manager.send_signal_sync(job.user_id, {"type": "job_done"})
            print("    Sinal disparado — verifique o console da extensão")
    except Exception as e:
        print(f"    ERRO ao acessar WS manager: {e}")


def test_mark_completed(job: ProcessingJob):
    print(f"\n[5] Chamando mark_completed no job {job.job_id}")
    job.mark_completed("Teste concluído com sucesso")
    session = DatabaseManager.get_session()
    try:
        job_data = DatabaseManager.get_job(session, job.job_id)
        status = job_data.get("status") if job_data else "N/A"
        print(f"    Status no banco após mark_completed: {status!r}")
        assert status == "completed", f"FALHA: status é {status!r}"
        print("    OK: status = 'completed'")
    finally:
        session.close()


# ─────────────────────────────────────────────────────────────────────────────


def main():
    user_id = get_test_user_id(sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"=== Usando user_id: {user_id} ===")

    # Busca um chat_id válido para esse usuário
    row = DatabaseManager.fetch_one(
        "SELECT chat_id FROM chats WHERE user_id = :uid LIMIT 1", {"uid": user_id}
    )
    if not row:
        print("Nenhum chat encontrado para esse usuário. Usando 'test-chat-id'.")
        chat_id = "test-chat-id"
    else:
        chat_id = row["chat_id"]
    print(f"=== Usando chat_id: {chat_id} ===")

    jm = JobManager()

    job = test_create_job(jm, chat_id, user_id)
    test_db_row_has_user_id(job.job_id, user_id)
    test_get_job_preserves_user_id(jm, job.job_id, user_id)
    test_notify_browser_done(job)
    test_mark_completed(job)

    print("\n=== Resumo ===")
    print("Se [2] mostrou FALHA, o bug é JobManager.get_job não repassando user_id.")
    print("Se [3] mostrou FALHA, a migration da coluna user_id ainda não rodou.")
    print(
        "Se [4] mostrou WS conectado mas extensão não recebeu job_done, cheque send_signal_sync."
    )


if __name__ == "__main__":
    main()

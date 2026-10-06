"""
Script de validação do SyncManager.
Executa standalone (sem servidor). Conecta direto ao SQLite e roda o sync.

Uso:
    python validate_sync.py
    python validate_sync.py --chat-id <uuid>
    python validate_sync.py --dry-run   (mostra o que seria sincronizado sem commitar)
"""

import sys
import argparse
import json
from pathlib import Path
from datetime import datetime

# ─── Path setup ────────────────────────────────────────────────────────────────
BACKEND_DIR = Path(__file__).parent.parent.parent.parent.absolute()
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv

_env_file = BACKEND_DIR.parent.parent / ".env.development"
if _env_file.exists():
    load_dotenv(dotenv_path=str(_env_file), override=True)

# ─── Imports do projeto ────────────────────────────────────────────────────────
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from App.Core.Crunch.SyncManager import SyncManager
from App.Core.Crunch.TablesSQL.Models import IsolatedMessage, Message

# ─── Config ────────────────────────────────────────────────────────────────────
DB_PATH = BACKEND_DIR / "Data" / "Database" / "MD70.db"
DEFAULT_CHAT_ID = "4e3ca098-435c-46fd-8f01-8e0039f21163"

SEP = "=" * 70
SEP2 = "-" * 70


# ─── Helpers ───────────────────────────────────────────────────────────────────


def _preview(content: str, length: int = 90) -> str:
    return (content or "").replace("\n", " ").strip()[:length]


def print_main_messages(session, chat_id: str, label: str):
    msgs = (
        session.query(Message)
        .filter(Message.chat_id == chat_id)
        .order_by(Message.created_at)
        .all()
    )
    print(f"\n{SEP}")
    print(f"  {label}  —  {len(msgs)} mensagem(s) no chat principal")
    print(SEP)
    if not msgs:
        print("  (vazio)")
        return
    for m in msgs:
        mid = (m.message_id or "")[:8]
        tool = m.tool or "—"
        ts = str(m.created_at)[:19] if m.created_at else "?"
        print(f"  [{m.message_type:10}] {mid}…  tool={tool:20}  {ts}")
        print(f"    {_preview(m.content)}")


def print_isolated_messages(session, chat_id: str):
    isos = (
        session.query(IsolatedMessage)
        .filter(IsolatedMessage.isolated_chat_id == chat_id)
        .order_by(IsolatedMessage.created_at)
        .all()
    )
    print(f"\n{SEP}")
    print(f"  ISOLATED  —  {len(isos)} mensagem(s) isolada(s)")
    print(SEP)
    if not isos:
        print("  (vazio)")
        return isos

    for m in isos:
        mid = (m.isolated_message_id or "")[:8]
        tcid = (m.tool_call_id or "")[:8] or "—"
        tool = m.tool_called or "—"
        ts = str(m.created_at)[:19] if m.created_at else "?"
        print(
            f"  [{m.role:10}/{m.type or '':10}]  {mid}…  tc={tcid}…  tool={tool:20}  {ts}"
        )
        print(f"    {_preview(m.content)}")

    return isos


def diff_snapshots(before_snap: dict, after_msgs: list):
    """Compara snapshot de valores (antes) com objetos ORM atuais (depois)."""
    after_ids = {m.message_id: m for m in after_msgs}

    new_ids = set(after_ids) - set(before_snap)
    updated_ids = {
        mid
        for mid in set(before_snap) & set(after_ids)
        if before_snap[mid]["content"] != after_ids[mid].content
    }

    print(f"\n{SEP}")
    print(f"  DIFF  —  +{len(new_ids)} novo(s)  /  ~{len(updated_ids)} atualizado(s)")
    print(SEP)
    for mid in new_ids:
        m = after_ids[mid]
        print(f"  [NEW]     [{m.message_type}] {mid[:8]}…  tool={m.tool or '—'}")
        print(f"    {_preview(m.content)}")
    for mid in updated_ids:
        b_content = before_snap[mid]["content"]
        a = after_ids[mid]
        print(f"  [UPDATED] [{a.message_type}] {mid[:8]}…  tool={a.tool or '—'}")
        print(f"    ANTES:  {_preview(b_content)}")
        print(f"    DEPOIS: {_preview(a.content)}")
    if not new_ids and not updated_ids:
        print("  Nenhuma mudança.")


# ─── Main ──────────────────────────────────────────────────────────────────────


def run(chat_id: str, dry_run: bool):
    print(f"\n{SEP}")
    print(f"  SyncManager Validator")
    print(f"  chat_id : {chat_id}")
    print(f"  db      : {DB_PATH}")
    print(f"  dry_run : {dry_run}")
    print(f"  {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print(SEP)

    if not DB_PATH.exists():
        print(f"\n❌  Banco não encontrado: {DB_PATH}")
        sys.exit(1)

    engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"timeout": 10})
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Estado antes — snapshot de valores (não referências ORM, que mudam in-place)
        before_snap = {
            m.message_id: {"content": m.content, "type": m.message_type}
            for m in session.query(Message).filter(Message.chat_id == chat_id).all()
        }
        print_main_messages(session, chat_id, "ANTES DO SYNC")
        isolated = print_isolated_messages(session, chat_id)

        if not isolated:
            print(f"\n⚠️   Nenhuma mensagem isolada para este chat_id.")
            return

        # Sync
        if dry_run:
            print(f"\n{SEP2}")
            print("  DRY RUN — nenhuma alteração será commitada")
            print(SEP2)

        print(f"\n🔄  Executando SyncManager.sync_isolated_messages …")
        synced = SyncManager.sync_isolated_messages(session, isolated, chat_id)

        if dry_run:
            session.rollback()
            print(f"↩️   Rollback realizado (dry-run)")
        else:
            print(f"✅  Sync concluído: {synced} operação(ões)")

        # Estado depois
        after_msgs = session.query(Message).filter(Message.chat_id == chat_id).all()
        print_main_messages(session, chat_id, "DEPOIS DO SYNC")
        diff_snapshots(before_snap, after_msgs)

    except Exception as e:
        import traceback

        print(f"\n❌  Erro durante sync:")
        traceback.print_exc()
    finally:
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Valida o SyncManager contra um chat real"
    )
    parser.add_argument(
        "--chat-id", default=DEFAULT_CHAT_ID, help="UUID do chat a sincronizar"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Executa sem commitar alterações"
    )
    args = parser.parse_args()

    run(chat_id=args.chat_id, dry_run=args.dry_run)

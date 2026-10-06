"""
Remove todos os triggers de teste do usuário admin.

Reconhece triggers de teste pelo prefixo do nome:
  [SIM], [AG], [WS], [TEST]

Preserva triggers reais (sem esses prefixos).

Uso:
    cd App/mvp/services/backend
    python3 Scripts/Tests/TriggersValidation/cleanup_test_triggers.py
    python3 Scripts/Tests/TriggersValidation/cleanup_test_triggers.py --env-file .env.development
    python3 Scripts/Tests/TriggersValidation/cleanup_test_triggers.py --dry-run
"""

import argparse
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(BACKEND_DIR))

_parser = argparse.ArgumentParser()
_parser.add_argument("--env-file", default=str(BACKEND_DIR / ".env.wsl"))
_parser.add_argument(
    "--dry-run", action="store_true", help="Mostra o que seria deletado sem deletar"
)
_args = _parser.parse_args()

os.environ["ENV_FILE"] = _args.env_file

TEST_PREFIXES = (
    "[SIM]",
    "[AG]",
    "[AG1]",
    "[AG2]",
    "[AG3]",
    "[AG4]",
    "[AG5]",
    "[AG6]",
    "[WS1]",
    "[WS2]",
    "[WS3]",
    "[TEST]",
    "[AG ",
)


def is_test_trigger(name: str) -> bool:
    return (
        any(name.startswith(p) for p in TEST_PREFIXES)
        or name.startswith("[SIM")
        or name.startswith("[AG")
        or name.startswith("[WS")
    )


def run():
    from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
    from sqlalchemy import text

    # Buscar admin (primeiro usuário criado)
    admin = DatabaseManager.fetch_one(
        "SELECT user_id FROM users ORDER BY created_at ASC LIMIT 1", {}
    )
    if not admin:
        print("[ERRO] Nenhum usuário encontrado.")
        sys.exit(1)

    uid = admin["user_id"]
    print(f"[INFO] Usuário admin: {uid}")

    session = DatabaseManager.get_session()
    try:
        rows = session.execute(
            text(
                "SELECT id, name, provider, autonomy_level FROM triggers WHERE user_id = :uid ORDER BY created_at"
            ),
            {"uid": uid},
        ).fetchall()

        real = [r for r in rows if not is_test_trigger(r[1])]
        test = [r for r in rows if is_test_trigger(r[1])]

        print(f"\n[INFO] Triggers reais ({len(real)}) — serão preservados:")
        for r in real:
            print(f"  ✓  {r[0]}  |  {r[1]}  |  {r[2]}  |  autonomy={r[3]}")

        print(f"\n[INFO] Triggers de teste ({len(test)}) — serão removidos:")
        for r in test:
            print(f"  ✗  {r[0]}  |  {r[1]}  |  {r[2]}  |  autonomy={r[3]}")

        if not test:
            print("\n[OK] Nenhum trigger de teste encontrado.")
            return

        if _args.dry_run:
            print("\n[DRY-RUN] Nada foi deletado.")
            return

        print(f"\n[INFO] Deletando {len(test)} triggers de teste...")
        for r in test:
            tid = r[0]
            session.execute(
                text("DELETE FROM trigger_executions WHERE trigger_id = :id"),
                {"id": tid},
            )
            session.execute(
                text(
                    "DELETE FROM trigger_tool_approvals WHERE chat_id IN "
                    "(SELECT chat_id FROM chats WHERE trigger_id = :id)"
                ),
                {"id": tid},
            )
            session.execute(
                text("DELETE FROM chats WHERE trigger_id = :id"), {"id": tid}
            )
            session.execute(text("DELETE FROM triggers WHERE id = :id"), {"id": tid})
            print(f"  deletado: {tid}  ({r[1]})")

        session.commit()
        print(f"\n[OK] {len(test)} trigger(s) de teste removidos.")

    except Exception as e:
        session.rollback()
        print(f"[ERRO] {e}")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    run()

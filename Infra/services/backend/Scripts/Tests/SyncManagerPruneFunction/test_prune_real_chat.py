"""
Executa prune_main_chat no chat real e valida o resultado.

Uso:
    cd App/mvp/services/backend
    python3 Scripts/Tests/SyncManagerPruneFunction/test_prune_real_chat.py [CHAT_ID]

Padrão: f38bb07f-89b9-415c-b137-ccf6b6fb1406
"""

import sys
import json
from pathlib import Path

BACKEND_DIR = Path(__file__).parent.parent.parent.parent.absolute()
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv

_env = BACKEND_DIR.parent.parent / ".env.development"
if _env.exists():
    load_dotenv(dotenv_path=str(_env), override=True)

import os

os.environ.setdefault("ENV_FILE", str(BACKEND_DIR / ".env.development"))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from App.Core.Crunch.TablesSQL.Models import Message
from App.Core.Crunch.SyncManager import SyncManager

CHAT_ID = sys.argv[1] if len(sys.argv) > 1 else "f38bb07f-89b9-415c-b137-ccf6b6fb1406"
DB_PATH = BACKEND_DIR / "Data" / "Database" / "MD70.db"

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"timeout": 10})
Session = sessionmaker(bind=engine)

SEP = "=" * 60


def _is_error(m: Message) -> bool:
    try:
        return json.loads(m.content).get("success") is False
    except:
        return False


def _is_quiz_output(m: Message) -> bool:
    try:
        d = json.loads(m.content)
        return d.get("success") is True or "final_answers" in d
    except:
        return False


def snapshot(session, label: str) -> list:
    msgs = (
        session.query(Message)
        .filter_by(chat_id=CHAT_ID)
        .order_by(Message.created_at, Message.id)
        .all()
    )
    print(f"\n{label}  ({len(msgs)} mensagens)")
    print("-" * 60)
    for m in msgs:
        try:
            data = json.loads(m.content)
            success = data.get("success")
            tool_key = data.get("tool", "")
            final_ans = "final_answers" in data
            preview = (
                f"success={success}"
                + (" [final_answers]" if final_ans else "")
                + (f" tool={tool_key}" if tool_key else "")
            )
        except:
            preview = m.content[:60]
        print(f"  [{m.tool or m.message_type:12}] {m.message_id[:8]}...  {preview}")
    return msgs


s = Session()

print(f"\n{SEP}")
print(f"  PRUNE REAL CHAT")
print(f"  chat_id: {CHAT_ID}")
print(SEP)

before = snapshot(s, "ANTES")

errors_before = [m for m in before if _is_error(m)]
quizzes_before = [m for m in before if m.tool == "quiz"]
quiz_orphans_before = [m for m in quizzes_before if not _is_quiz_output(m)]

print(f"\n  Erros encontrados antes: {len(errors_before)}")
print(f"  Quiz inputs órfãos antes: {len(quiz_orphans_before)}")

# ── executa prune ────────────────────────────────────────────────────────────
pruned = SyncManager.prune_main_chat(s, CHAT_ID)
print(f"\n  prune_main_chat removeu: {pruned} mensagem(ns)")

after = snapshot(s, "DEPOIS")

# ── validações ───────────────────────────────────────────────────────────────
errors_after = [m for m in after if _is_error(m)]
quizzes_after = [m for m in after if m.tool == "quiz"]
quiz_orphans_after = [m for m in quizzes_after if not _is_quiz_output(m)]

_pass = _fail = 0


def check(label, condition):
    global _pass, _fail
    status = "✅ PASS" if condition else "❌ FAIL"
    if condition:
        _pass += 1
    else:
        _fail += 1
    print(f"  {status}  {label}")


print(f"\n── Checagens ─────────────────────────────────────────────────")

# Erros: só 0 ou 1 deve restar
check(
    f"Erros restantes ≤ 1  (era {len(errors_before)}, ficou {len(errors_after)})",
    len(errors_after) <= 1,
)

# Se havia 2+ erros, deve ter removido todos menos 1
if len(errors_before) > 1:
    check(f"Removeu {len(errors_before) - 1} erro(s) antigo(s)", len(errors_after) == 1)

# Quiz órfãos com 2+ msgs depois devem ter sido removidos
# (recalcula quais deviam ser removidos com base na ordem pré-prune)
msgs_ordered = sorted(before, key=lambda m: (m.created_at, m.id))
after_ids = {m.message_id for m in after}
should_have_removed = []
for m in msgs_ordered:
    if m.tool != "quiz" or _is_quiz_output(m):
        continue
    idx = msgs_ordered.index(m)
    if len(msgs_ordered) - idx - 1 >= 2:
        should_have_removed.append(m.message_id)

for mid in should_have_removed:
    check(f"Quiz órfão {mid[:8]}... removido", mid not in after_ids)

if not should_have_removed:
    check("Nenhum quiz órfão com 2+ msgs (nada a remover)", True)

# Msgs que não eram erro nem quiz órfão devem permanecer
safe_ids = {
    m.message_id
    for m in before
    if not _is_error(m)
    and not (
        m.tool == "quiz"
        and not _is_quiz_output(m)
        and m.message_id in should_have_removed
    )
}
# remove os erros antigos (todos menos o último)
error_ids_before = [
    m.message_id for m in sorted(errors_before, key=lambda m: (m.created_at, m.id))
]
for mid in error_ids_before[:-1]:
    safe_ids.discard(mid)

survivors_ok = all(mid in after_ids for mid in safe_ids)
check("Todas as mensagens não-prunáveis preservadas", survivors_ok)

total = _pass + _fail
print(f"\n{SEP}")
print(
    f"  Resultado: {_pass}/{total} passou  {'✅ TUDO OK' if _fail == 0 else f'❌ {_fail} falhou'}"
)
print(f"{SEP}\n")

s.close()

if _fail:
    sys.exit(1)

"""
Testa SyncManager.prune_main_chat.

Cenários:
  1. Múltiplos erros (success=false) → mantém só o último, remove os anteriores
  2. Quiz input órfão com 2+ msgs depois → remove
  3. Quiz com output (success=true / final_answers) → NÃO remove
  4. Quiz órfão com apenas 1 msg depois → NÃO remove
  5. Só 1 erro → não remove nada (nenhum "anterior" existe)

Uso:
    cd App/mvp/services/backend
    python3 Scripts/Tests/SyncManagerPruneFunction/test_prune_main_chat.py
"""

import sys
import json
from datetime import datetime, timedelta
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
from App.Core.Crunch.TablesSQL.Models import Base, Message
from App.Core.Crunch.SyncManager import SyncManager

# ── banco em memória (isolado por execução) ──────────────────────────────────
engine = create_engine("sqlite:///:memory:")
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)

CHAT = "test-prune-chat"
BASE_TIME = datetime(2026, 1, 1, 12, 0, 0)

_pass = _fail = 0


def check(label: str, condition: bool):
    global _pass, _fail
    if condition:
        _pass += 1
        print(f"  ✅ PASS  {label}")
    else:
        _fail += 1
        print(f"  ❌ FAIL  {label}")


def make_msg(
    message_id: str, tool: str | None, content: dict, offset_min: int
) -> Message:
    return Message(
        message_id=message_id,
        chat_id=CHAT,
        message_type="tool" if tool else "assistant",
        content=json.dumps(content),
        tool=tool,
        model="orchestrator",
        created_at=BASE_TIME + timedelta(minutes=offset_min),
    )


def reset(session):
    session.query(Message).filter_by(chat_id=CHAT).delete()
    session.commit()


def ids(session) -> list[str]:
    return [m.message_id for m in session.query(Message).filter_by(chat_id=CHAT).all()]


# ══════════════════════════════════════════════════════════════════════════════
# Cenário 1: Múltiplos erros → mantém só o último
# ══════════════════════════════════════════════════════════════════════════════
print("\n── Cenário 1: Múltiplos erros — mantém só o último ─────────────")
s = Session()
s.add_all(
    [
        make_msg("err-1", "document", {"success": False, "error": "falhou 1"}, 0),
        make_msg("err-2", "document", {"success": False, "error": "falhou 2"}, 1),
        make_msg("err-3", "document", {"success": False, "error": "falhou 3"}, 2),
        make_msg("ok-1", "document", {"success": True, "doc": "canvas"}, 3),
    ]
)
s.commit()
SyncManager.prune_main_chat(s, CHAT)
remaining = ids(s)
check("err-1 removido", "err-1" not in remaining)
check("err-2 removido", "err-2" not in remaining)
check("err-3 (último erro) mantido", "err-3" in remaining)
check("ok-1 (success=true) mantido", "ok-1" in remaining)
reset(s)

# ══════════════════════════════════════════════════════════════════════════════
# Cenário 2: Quiz órfão com 2+ msgs depois → remove
# ══════════════════════════════════════════════════════════════════════════════
print("\n── Cenário 2: Quiz órfão com 2+ msgs depois — remove ────────────")
s.add_all(
    [
        make_msg("quiz-orphan", "quiz", {"quiz": [{"question": "Qual produto?"}]}, 0),
        make_msg("after-1", None, {"text": "resposta 1"}, 1),
        make_msg("after-2", None, {"text": "resposta 2"}, 2),
    ]
)
s.commit()
SyncManager.prune_main_chat(s, CHAT)
remaining = ids(s)
check("quiz-orphan removido", "quiz-orphan" not in remaining)
check("after-1 mantido", "after-1" in remaining)
check("after-2 mantido", "after-2" in remaining)
reset(s)

# ══════════════════════════════════════════════════════════════════════════════
# Cenário 3: Quiz com output (success=true) → NÃO remove
# ══════════════════════════════════════════════════════════════════════════════
print("\n── Cenário 3: Quiz com output (success=true) — NÃO remove ───────")
s.add_all(
    [
        make_msg(
            "quiz-answered", "quiz", {"success": True, "final_answers": ["A", "B"]}, 0
        ),
        make_msg("after-3", None, {"text": "msg"}, 1),
        make_msg("after-4", None, {"text": "msg"}, 2),
    ]
)
s.commit()
SyncManager.prune_main_chat(s, CHAT)
remaining = ids(s)
check("quiz-answered mantido (tem output)", "quiz-answered" in remaining)
reset(s)

# ══════════════════════════════════════════════════════════════════════════════
# Cenário 4: Quiz órfão com apenas 1 msg depois → NÃO remove
# ══════════════════════════════════════════════════════════════════════════════
print("\n── Cenário 4: Quiz órfão com 1 msg depois — NÃO remove ──────────")
s.add_all(
    [
        make_msg("quiz-recent", "quiz", {"quiz": [{"question": "Qual?"}]}, 0),
        make_msg("after-only", None, {"text": "uma mensagem"}, 1),
    ]
)
s.commit()
SyncManager.prune_main_chat(s, CHAT)
remaining = ids(s)
check("quiz-recent mantido (só 1 msg depois)", "quiz-recent" in remaining)
reset(s)

# ══════════════════════════════════════════════════════════════════════════════
# Cenário 5: Só 1 erro → não remove nada
# ══════════════════════════════════════════════════════════════════════════════
print("\n── Cenário 5: Apenas 1 erro — não remove nada ───────────────────")
s.add_all(
    [
        make_msg(
            "single-err", "document", {"success": False, "error": "único erro"}, 0
        ),
        make_msg("ok-2", "document", {"success": True, "doc": "canvas"}, 1),
    ]
)
s.commit()
SyncManager.prune_main_chat(s, CHAT)
remaining = ids(s)
check("single-err mantido (único erro, é o último)", "single-err" in remaining)
check("ok-2 mantido", "ok-2" in remaining)
reset(s)

s.close()

# ── resultado final ──────────────────────────────────────────────────────────
total = _pass + _fail
print(f"\n{'=' * 50}")
print(
    f"  Resultado: {_pass}/{total} passou  {'✅ TUDO OK' if _fail == 0 else f'❌ {_fail} falhou'}"
)
print(f"{'=' * 50}\n")

if _fail:
    sys.exit(1)

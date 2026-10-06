"""
LLMClient Cancel Filter — valida que _sanitize_messages_for_llm remove o lookup
de SkillCopywriting.md do contexto quando existe um cancel bem-sucedido depois dele.

Chat de referência: 575dc780-de83-45e1-b18b-b364f9e0cdf2
  row 5754 → lookup SkillCopywriting.md (deve ser removido)
  row 5764 → cancel success cancelled=true (deve permanecer)

Uso:
    cd App/mvp/services/backend
    python3 Scripts/Tests/LLMClientFilter/test_llmclient_cancel_filter.py
    python3 Scripts/Tests/LLMClientFilter/test_llmclient_cancel_filter.py --env-file .env.development
"""

import sys
import os
import json
import argparse
from pathlib import Path

BACKEND_DIR = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(BACKEND_DIR))

_parser = argparse.ArgumentParser(add_help=False)
_parser.add_argument(
    "--env-file", default=str(BACKEND_DIR.parent.parent.parent / ".env.development")
)
_args, _ = _parser.parse_known_args()
os.environ["ENV_FILE"] = _args.env_file

# ── Import após path setup ────────────────────────────────────────────────────

import importlib.util as _ilu

_llmclient_path = BACKEND_DIR / "App" / "Features" / "Llm" / "LLMClient.py"
_spec = _ilu.spec_from_file_location("LLMClient", _llmclient_path)
_mod = _ilu.module_from_spec(_spec)
# Stub das dependências que causam circular import antes de executar o módulo
import unittest.mock as _mock
import sys as _sys

_sys.modules.setdefault("App.Core.Services.AdminEmail", _mock.MagicMock())
_sys.modules.setdefault("App.Core.Services", _mock.MagicMock())
_sys.modules.setdefault("App.Core.Crunch.TablesSQL.DBManager", _mock.MagicMock())
_spec.loader.exec_module(_mod)
_sanitize_messages_for_llm = _mod._sanitize_messages_for_llm

SEP = "=" * 70
SEP2 = "-" * 70

CHAT_ID = "575dc780-de83-45e1-b18b-b364f9e0cdf2"

results: list[dict] = []


def ok(name: str, detail: str = "") -> None:
    tag = "✅ PASS"
    results.append({"name": name, "status": "PASS"})
    print(f"  {tag}  {name}" + (f"  ({detail})" if detail else ""))


def fail(name: str, detail: str = "") -> None:
    tag = "❌ FAIL"
    results.append({"name": name, "status": "FAIL", "detail": detail})
    print(f"  {tag}  {name}" + (f"  — {detail}" if detail else ""))


# ── Helpers ───────────────────────────────────────────────────────────────────


def _is_lookup_skill(msg: dict, skill: str) -> bool:
    """Retorna True se a mensagem é um lookup output bem-sucedido da skill dada."""
    if msg.get("role") != "assistant":
        return False
    try:
        cj = json.loads(msg.get("content", ""))
        return (
            isinstance(cj, dict)
            and cj.get("tool") == "lookup"
            and cj.get("success") is True
            and skill.lower() in str(cj.get("file", "")).lower()
        )
    except Exception:
        return False


def _is_cancel_success(msg: dict) -> bool:
    """Retorna True se a mensagem é um cancel bem-sucedido."""
    if msg.get("role") != "assistant":
        return False
    try:
        cj = json.loads(msg.get("content", ""))
        return (
            isinstance(cj, dict)
            and cj.get("cancelled") is True
            and cj.get("success") is True
        )
    except Exception:
        return False


def _load_messages_from_db(chat_id: str) -> list[dict]:
    """Carrega isolated_messages do DB e converte para o formato {role, content}."""
    import sqlite3

    db_path = BACKEND_DIR / "Data" / "Database" / "MD70.db"
    if not db_path.exists():
        db_path = BACKEND_DIR / "Data" / "MD70.db"
    if not db_path.exists():
        db_path = BACKEND_DIR / "MD70.db"

    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT id, role, content FROM isolated_messages "
            "WHERE isolated_chat_id = ? ORDER BY id ASC",
            (chat_id,),
        ).fetchall()
    finally:
        conn.close()

    messages = []
    for row_id, role, content in rows:
        if role and content:
            messages.append(
                {
                    "role": role,
                    "content": content,
                    "_db_id": row_id,  # extra para debug, não afeta o filtro
                }
            )
    return messages


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_with_real_chat() -> None:
    """Valida o filtro contra o chat real 575dc780-de83-45e1-b18b-b364f9e0cdf2."""
    print(f"\n{SEP}")
    print("TEST: filtro cancel × lookup real do DB")
    print(SEP2)

    messages = _load_messages_from_db(CHAT_ID)
    if not messages:
        fail("carregar mensagens do DB", "nenhuma mensagem encontrada")
        return

    print(f"  Mensagens carregadas: {len(messages)}")

    # Identificar lookup e cancel no input
    lookup_indices = [
        i for i, m in enumerate(messages) if _is_lookup_skill(m, "SkillCopywriting")
    ]
    cancel_indices = [i for i, m in enumerate(messages) if _is_cancel_success(m)]

    if not lookup_indices:
        fail("lookup SkillCopywriting presente no input", "nenhum lookup encontrado")
        return
    ok("lookup SkillCopywriting presente no input", f"índices: {lookup_indices}")

    if not cancel_indices:
        fail("cancel success presente no input", "nenhum cancel encontrado")
        return
    ok("cancel success presente no input", f"índices: {cancel_indices}")

    # Verificar que o cancel vem DEPOIS do lookup
    last_lookup = max(lookup_indices)
    last_cancel = max(cancel_indices)
    if last_cancel > last_lookup:
        ok(
            "cancel posterior ao lookup",
            f"lookup[{last_lookup}] → cancel[{last_cancel}]",
        )
    else:
        fail(
            "cancel posterior ao lookup",
            f"cancel[{last_cancel}] não é posterior a lookup[{last_lookup}]",
        )
        return

    # Executar o filtro (remover _db_id antes para não interferir)
    messages_clean = [{"role": m["role"], "content": m["content"]} for m in messages]
    sanitized = _sanitize_messages_for_llm(messages_clean)

    # Lookup deve ter sido removido
    lookup_in_output = [m for m in sanitized if _is_lookup_skill(m, "SkillCopywriting")]
    if not lookup_in_output:
        ok(
            "lookup SkillCopywriting removido do output",
            f"{len(messages)} → {len(sanitized)} msgs",
        )
    else:
        fail(
            "lookup SkillCopywriting removido do output",
            f"{len(lookup_in_output)} lookup(s) ainda presente(s) após filtro",
        )

    # Cancel deve permanecer
    cancel_in_output = [m for m in sanitized if _is_cancel_success(m)]
    if cancel_in_output:
        ok("cancel success mantido no output", f"{len(cancel_in_output)} cancel(s)")
    else:
        fail("cancel success mantido no output", "cancel foi removido indevidamente")

    # Mensagens do usuário devem permanecer
    user_in = sum(1 for m in messages if m["role"] == "user")
    user_out = sum(1 for m in sanitized if m["role"] == "user")
    if user_in == user_out:
        ok("mensagens do usuário intactas", f"{user_in} mensagens")
    else:
        fail("mensagens do usuário intactas", f"antes={user_in}, depois={user_out}")


def test_synthetic_no_cancel() -> None:
    """Sem cancel: lookup NÃO deve ser removido."""
    print(f"\n{SEP}")
    print("TEST: sem cancel — lookup preservado")
    print(SEP2)

    messages = [
        {"role": "user", "content": "quero criar criativos"},
        {
            "role": "assistant",
            "content": json.dumps(
                {
                    "tool": "lookup",
                    "success": True,
                    "file": "SkillCopywriting.md",
                    "content": "# Skill content...",
                }
            ),
        },
        {"role": "user", "content": "ok"},
    ]

    sanitized = _sanitize_messages_for_llm(messages)
    lookup_present = any(_is_lookup_skill(m, "SkillCopywriting") for m in sanitized)

    if lookup_present:
        ok("lookup preservado quando não há cancel")
    else:
        fail("lookup preservado quando não há cancel", "foi removido sem cancel")


def test_synthetic_cancel_after_lookup() -> None:
    """Cancel depois do lookup: lookup deve ser removido."""
    print(f"\n{SEP}")
    print("TEST: cancel após lookup — lookup removido")
    print(SEP2)

    messages = [
        {"role": "user", "content": "quero criar criativos"},
        {
            "role": "assistant",
            "content": json.dumps(
                {
                    "tool": "lookup",
                    "success": True,
                    "file": "SkillCopywriting.md",
                    "content": "# Skill content muito longa...",
                }
            ),
        },
        {"role": "user", "content": "cancel"},
        {
            "role": "assistant",
            "content": json.dumps(
                {
                    "success": True,
                    "cancelled": True,
                    "reason": "usuário cancelou",
                    "message": "PARE imediatamente.",
                }
            ),
        },
        {"role": "user", "content": "vamos fazer outra coisa"},
    ]

    sanitized = _sanitize_messages_for_llm(messages)
    lookup_present = any(_is_lookup_skill(m, "SkillCopywriting") for m in sanitized)
    cancel_present = any(_is_cancel_success(m) for m in sanitized)

    if not lookup_present:
        ok("lookup removido após cancel")
    else:
        fail("lookup removido após cancel", "lookup ainda presente")

    if cancel_present:
        ok("cancel mantido")
    else:
        fail("cancel mantido", "cancel foi removido indevidamente")

    user_msgs_out = [m for m in sanitized if m["role"] == "user"]
    if len(user_msgs_out) == 3:
        ok("mensagens do usuário intactas", "3 mensagens")
    else:
        fail(
            "mensagens do usuário intactas", f"esperado=3, obtido={len(user_msgs_out)}"
        )


def test_synthetic_cancel_before_lookup() -> None:
    """Cancel antes do lookup: lookup NÃO deve ser removido (cancel é mais antigo)."""
    print(f"\n{SEP}")
    print("TEST: cancel ANTES do lookup — lookup preservado")
    print(SEP2)

    messages = [
        {"role": "user", "content": "cancelar algo antigo"},
        {
            "role": "assistant",
            "content": json.dumps(
                {
                    "success": True,
                    "cancelled": True,
                    "reason": "cancel antigo",
                    "message": "PARE.",
                }
            ),
        },
        {"role": "user", "content": "agora criar criativos"},
        {
            "role": "assistant",
            "content": json.dumps(
                {
                    "tool": "lookup",
                    "success": True,
                    "file": "SkillCopywriting.md",
                    "content": "# Skill novo ciclo...",
                }
            ),
        },
        {"role": "user", "content": "ok"},
    ]

    sanitized = _sanitize_messages_for_llm(messages)
    lookup_present = any(_is_lookup_skill(m, "SkillCopywriting") for m in sanitized)

    if lookup_present:
        ok("lookup preservado quando cancel é anterior")
    else:
        fail(
            "lookup preservado quando cancel é anterior",
            "lookup removido incorretamente",
        )


def test_synthetic_multiple_lookups_with_cancel() -> None:
    """Dois lookups de skills diferentes: ambos removidos pelo cancel."""
    print(f"\n{SEP}")
    print("TEST: múltiplos lookups — todos removidos pelo cancel")
    print(SEP2)

    messages = [
        {"role": "user", "content": "criar conteúdo"},
        {
            "role": "assistant",
            "content": json.dumps(
                {
                    "tool": "lookup",
                    "success": True,
                    "file": "SkillCopywriting.md",
                    "content": "# Copywriting...",
                }
            ),
        },
        {
            "role": "assistant",
            "content": json.dumps(
                {
                    "tool": "lookup",
                    "success": True,
                    "file": "SkillCaption.md",
                    "content": "# Caption...",
                }
            ),
        },
        {"role": "user", "content": "cancel"},
        {
            "role": "assistant",
            "content": json.dumps(
                {
                    "success": True,
                    "cancelled": True,
                    "reason": "cancelado",
                    "message": "PARE.",
                }
            ),
        },
    ]

    sanitized = _sanitize_messages_for_llm(messages)
    copy_present = any(_is_lookup_skill(m, "SkillCopywriting") for m in sanitized)
    caption_present = any(_is_lookup_skill(m, "SkillCaption") for m in sanitized)

    if not copy_present:
        ok("SkillCopywriting removida")
    else:
        fail("SkillCopywriting removida", "ainda presente")

    if not caption_present:
        ok("SkillCaption removida")
    else:
        fail("SkillCaption removida", "ainda presente")


# ── Summary ───────────────────────────────────────────────────────────────────


def print_summary() -> None:
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    print(f"\n{SEP}")
    print(f"RESULTADO: {passed}/{len(results)} PASS  |  {failed} FAIL")
    if failed:
        print("\nFalhas:")
        for r in results:
            if r["status"] == "FAIL":
                print(
                    f"  ❌  {r['name']}"
                    + (f"  — {r.get('detail','')}" if r.get("detail") else "")
                )
    print(SEP)
    sys.exit(1 if failed else 0)


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"\n{SEP}")
    print("LLMClient Cancel Filter — Validation Script")
    print(f"Chat de referência: {CHAT_ID}")
    print(SEP)

    test_with_real_chat()
    test_synthetic_no_cancel()
    test_synthetic_cancel_after_lookup()
    test_synthetic_cancel_before_lookup()
    test_synthetic_multiple_lookups_with_cancel()

    print_summary()

"""
Validação dos limites de uso por sessão, semana e mês (créditos).

Cria 9 usuários injetados diretamente no DB — sem custo real — e valida o
comportamento do CreditsManager em cada cenário:

  ── SESSÃO (janela de 3h30) ──
  01. Sessão OK      → dentro do limite → PASS
  02. Sessão BLOCK   → limite atingido, janela ativa → BLOCK
  03. Sessão RESET   → limite atingido mas janela expirada → janela reseta → PASS

  ── SEMANA (janela de 4 dias) ──
  04. Semana OK      → dentro do limite → PASS
  05. Semana BLOCK   → limite atingido, janela ativa → BLOCK
  06. Semana RESET   → limite atingido mas janela expirada → janela reseta → PASS

  ── CRÉDITOS (mês) ──
  07. Créditos OK    → tem saldo → PASS
  08. Créditos BLOCK → saldo zero → BLOCK
  09. Créditos RESET → saldo zero mas cumulative_resets_at expirado → distribui créditos → PASS

  ── VALIDAÇÃO DE LOGS E CAMPOS ──
  10. consume_credits → credits_logs.session_usage_pct e week_usage_pct preenchidos
  11. consume_credits → users.current_session_usage e current_week_usage incrementados

Uso:
    cd App/mvp/services/backend
    python3 Scripts/Tests/UsageLimits/test_usage_limits.py
    python3 Scripts/Tests/UsageLimits/test_usage_limits.py --cleanup
    python3 Scripts/Tests/UsageLimits/test_usage_limits.py --env-file .env.wsl
"""

import sys
import os
import uuid
import json
import re
import argparse
from datetime import datetime, timedelta
from pathlib import Path

# ══════════════════════════════════════════════════════════════════════════════
#  PATH + ENV
# ══════════════════════════════════════════════════════════════════════════════

BACKEND_DIR = Path(__file__).parent.parent.parent.parent.absolute()
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv


def load_env_for_test():
    mvp_root = BACKEND_DIR.parent.parent
    _mvp_env = mvp_root / ".env.development"
    if _mvp_env.exists():
        load_dotenv(dotenv_path=str(_mvp_env), override=True)
        print(f"✅ Loaded environment from: {_mvp_env}")
    else:
        print(f"⚠️  .env.development not found at {mvp_root}")

    _parser = argparse.ArgumentParser(add_help=False)
    _parser.add_argument("--env-file", default=None)
    _parser.add_argument("--cleanup", action="store_true")
    _args, _ = _parser.parse_known_args()

    if _args.env_file:
        env_path = Path(_args.env_file)
        if env_path.exists():
            load_dotenv(dotenv_path=str(env_path), override=True)
            print(f"✅ Overridden environment from: {env_path}")

    return _args


args = load_env_for_test()

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from App.Features.Credits.CreditsManager import CreditsManager

# ══════════════════════════════════════════════════════════════════════════════
#  CONSTANTES DE TESTE
# ══════════════════════════════════════════════════════════════════════════════

# Plano de teste com créditos mensais bem definidos para limites calculáveis:
#   session_limit = 24 / 24 = 1.0 crédito
#   week_limit    = 24 /  3 = 8.0 créditos
TEST_PLAN_MONTHLY = 24.0
TEST_PLAN_SESSION_LIMIT = TEST_PLAN_MONTHLY / 24  # 1.0
TEST_PLAN_WEEK_LIMIT = TEST_PLAN_MONTHLY / 3  # 8.0

SESSION_DURATION_H = 3.5  # horas por sessão
WEEK_DURATION_D = 4  # dias por período semanal

SEP = "═" * 70
SEP2 = "─" * 50

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# ══════════════════════════════════════════════════════════════════════════════
#  RESULTADOS
# ══════════════════════════════════════════════════════════════════════════════

results: list[dict] = []
all_test_user_ids: list[str] = []
test_plan_id: str | None = None


def step(label: str, expect_success: bool, result) -> bool:
    if isinstance(result, bool):
        ok = result
        result = {"success": result}
    else:
        ok = result.get("success", False)

    passed = ok == expect_success
    icon = "✅" if passed else "❌"
    exp = "PASS" if expect_success else "BLOCK"
    got = "PASS" if ok else "BLOCK"

    print(f"\n{SEP2}")
    print(f"{icon}  {label}")
    print(f"     esperado={exp}  obtido={got}")

    if not passed:
        detail = (
            result.get("error") or result.get("detail") or result.get("message", "")
        )
        if detail:
            print(f"     detalhe: {str(detail)[:200]}")

    results.append({"label": label, "passed": passed, "expected": exp, "got": got})

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = re.sub(r'[<>:"/\\|?*→]', "", label)[:40].replace(" ", "_")
    status_str = "pass" if passed else "fail"
    (OUTPUT_DIR / f"{slug}_{status_str}_{ts}.json").write_text(
        json.dumps(
            {"label": label, "expect_success": expect_success, "result": result},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return passed


# ══════════════════════════════════════════════════════════════════════════════
#  DB
# ══════════════════════════════════════════════════════════════════════════════


def get_session():
    db_path = BACKEND_DIR / "Data" / "Database" / "MD70.db"
    if not db_path.exists():
        raise FileNotFoundError(f"DB não encontrado: {db_path}")
    engine = create_engine(f"sqlite:///{db_path}")

    @event.listens_for(engine, "connect")
    def _fk_off(conn, _):
        conn.execute("PRAGMA foreign_keys = OFF")

    return sessionmaker(bind=engine)()


# ══════════════════════════════════════════════════════════════════════════════
#  SETUP: plano e usuários de teste
# ══════════════════════════════════════════════════════════════════════════════


def setup_test_plan(session) -> str:
    """Cria um plano de teste determinístico com cumulative_credits=24."""
    global test_plan_id
    plan_id = "test_usage_limits_plan"

    session.execute(text("DELETE FROM plans WHERE plan_id = :pid"), {"pid": plan_id})
    session.execute(
        text(
            """
        INSERT INTO plans (
            plan_id, name, description, cumulative_credits, non_cumulative_credits,
            cumulative_resets_in, non_cumulative_resets_in,
            plan_type, active, sell
        ) VALUES (
            :pid, 'Test Usage Limits', 'Plano temporário para testes de usage limits',
            :credits, 0,
            720, 24,
            'pro', 1, 0
        )
    """
        ),
        {"pid": plan_id, "credits": TEST_PLAN_MONTHLY},
    )
    session.commit()
    test_plan_id = plan_id
    print(
        f"\n✅ Plano de teste criado: {plan_id} (cumulative_credits={TEST_PLAN_MONTHLY})"
    )
    print(
        f"   session_limit = {TEST_PLAN_SESSION_LIMIT:.4f} | week_limit = {TEST_PLAN_WEEK_LIMIT:.4f}"
    )
    return plan_id


def inject_user(
    session,
    plan_id: str,
    label: str,
    credits: float = 10.0,
    session_usage: float = 0.0,
    session_starts_ago_h: float | None = 1.0,
    week_usage: float = 0.0,
    week_starts_ago_d: float | None = 1.0,
    last_reset: str = "non_cumulative",
    cumulative_resets_at_ago_h: float | None = None,
) -> str:
    """
    Injeta um usuário no DB com estado de usage pré-definido.

    Args:
        session_starts_ago_h: horas atrás que a sessão iniciou (None = NULL no DB)
        week_starts_ago_d:    dias atrás que a semana iniciou (None = NULL no DB)
        cumulative_resets_at_ago_h: horas atrás que cumulative_resets_at deveria ter expirado
                                    (None = não expirado, 30 dias no futuro)
    """
    now = datetime.utcnow()
    suffix = uuid.uuid4().hex[:8]
    client_id = f"test_ul_client_{suffix}"
    user_id = f"test_ul_user_{suffix}"
    email = f"test-ul-{suffix}@prox.ai"

    session_starts = (
        now - timedelta(hours=session_starts_ago_h)
        if session_starts_ago_h is not None
        else None
    )
    week_starts = (
        now - timedelta(days=week_starts_ago_d)
        if week_starts_ago_d is not None
        else None
    )

    if cumulative_resets_at_ago_h is not None:
        cumulative_resets_at = now - timedelta(hours=cumulative_resets_at_ago_h)
    else:
        cumulative_resets_at = now + timedelta(hours=720)

    non_cumulative_resets_at = now + timedelta(hours=24)

    session.execute(
        text(
            """
        INSERT INTO clients (client_id, plan_id, started_at, users_available)
        VALUES (:cid, :pid, CURRENT_TIMESTAMP, 1)
    """
        ),
        {"cid": client_id, "pid": plan_id},
    )

    session.execute(
        text(
            """
        INSERT INTO users (
            user_id, client_id, email, password, full_name,
            credits, last_reset,
            cumulative_resets_at, non_cumulative_resets_at,
            current_session_usage, current_session_starts_at,
            current_week_usage, current_week_starts_at,
            created_at, updated_at
        ) VALUES (
            :uid, :cid, :email, 'test_hash_bcrypt', :label,
            :credits, :last_reset,
            :cum_resets_at, :non_cum_resets_at,
            :session_usage, :session_starts,
            :week_usage, :week_starts,
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
    """
        ),
        {
            "uid": user_id,
            "cid": client_id,
            "email": email,
            "label": label,
            "credits": credits,
            "last_reset": last_reset,
            "cum_resets_at": cumulative_resets_at.isoformat(),
            "non_cum_resets_at": non_cumulative_resets_at.isoformat(),
            "session_usage": session_usage,
            "session_starts": session_starts.isoformat() if session_starts else None,
            "week_usage": week_usage,
            "week_starts": week_starts.isoformat() if week_starts else None,
        },
    )

    session.commit()
    all_test_user_ids.append(user_id)
    print(f"   👤 Injetado [{label}] → user_id={user_id}")
    return user_id


# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS DE VALIDAÇÃO
# ══════════════════════════════════════════════════════════════════════════════


def get_user_row(session, user_id: str) -> dict:
    row = session.execute(
        text(
            """
            SELECT credits, current_session_usage, current_session_starts_at,
                   current_week_usage, current_week_starts_at
            FROM users WHERE user_id = :uid
        """
        ),
        {"uid": user_id},
    ).fetchone()
    if not row:
        return {}
    return {
        "credits": row[0],
        "current_session_usage": row[1],
        "current_session_starts_at": row[2],
        "current_week_usage": row[3],
        "current_week_starts_at": row[4],
    }


def get_latest_log(session, user_id: str) -> dict:
    row = session.execute(
        text(
            """
            SELECT value, session_usage_pct, week_usage_pct, reason, created_at
            FROM credits_logs
            WHERE user_id = :uid
            ORDER BY created_at DESC LIMIT 1
        """
        ),
        {"uid": user_id},
    ).fetchone()
    if not row:
        return {}
    return {
        "value": row[0],
        "session_usage_pct": row[1],
        "week_usage_pct": row[2],
        "reason": row[3],
        "created_at": row[4],
    }


def check_credits(user_id: str) -> dict:
    """Executa check_credits e retorna resultado padronizado."""
    ok, available = CreditsManager.check_credits(user_id)
    return {"success": ok, "available": available}


def reset_and_check(user_id: str) -> dict:
    """Executa reset_credits_if_needed e depois check_credits."""
    CreditsManager.reset_credits_if_needed(user_id)
    return check_credits(user_id)


# ══════════════════════════════════════════════════════════════════════════════
#  CLEANUP
# ══════════════════════════════════════════════════════════════════════════════


def cleanup(session):
    """Remove todos os dados de teste."""
    print(f"\n{SEP}")
    print("🧹 CLEANUP — removendo dados de teste")

    for uid in all_test_user_ids:
        session.execute(
            text("DELETE FROM credits_logs WHERE user_id = :uid"), {"uid": uid}
        )
        session.execute(text("DELETE FROM users WHERE user_id = :uid"), {"uid": uid})

    session.execute(text("DELETE FROM clients WHERE client_id LIKE 'test_ul_client_%'"))

    if test_plan_id:
        session.execute(
            text("DELETE FROM plans WHERE plan_id = :pid"), {"pid": test_plan_id}
        )

    session.commit()
    removed = len(all_test_user_ids)
    print(f"   Removidos {removed} usuários, clientes e plano de teste.")


# ══════════════════════════════════════════════════════════════════════════════
#  CENÁRIOS DE TESTE
# ══════════════════════════════════════════════════════════════════════════════


def run_tests(session):
    plan_id = setup_test_plan(session)

    print(f"\n{SEP}")
    print("📋 Injetando 9 usuários de teste...")

    # ── SESSÃO ──────────────────────────────────────────────────────────────
    # Usuário dentro do limite de sessão → PASS
    u_session_ok = inject_user(
        session,
        plan_id,
        label="session_ok",
        credits=10.0,
        session_usage=TEST_PLAN_SESSION_LIMIT * 0.5,  # 0.5 (50% do limite)
        session_starts_ago_h=1.0,  # janela iniciou há 1h (ativa)
    )

    # Usuário no limite de sessão, janela ainda ativa → BLOCK
    u_session_blocked = inject_user(
        session,
        plan_id,
        label="session_blocked",
        credits=10.0,
        session_usage=TEST_PLAN_SESSION_LIMIT,  # 1.0 (100% — no limite)
        session_starts_ago_h=1.0,  # janela iniciou há 1h (ativa)
    )

    # Usuário no limite mas janela expirada (> 3h30 atrás) → reseta → PASS
    u_session_reset = inject_user(
        session,
        plan_id,
        label="session_reset",
        credits=10.0,
        session_usage=TEST_PLAN_SESSION_LIMIT,  # 1.0 (estava no limite)
        session_starts_ago_h=SESSION_DURATION_H
        + 1,  # janela iniciou há 4h30 → expirada
    )

    # ── SEMANA ──────────────────────────────────────────────────────────────
    # Usuário dentro do limite semanal → PASS
    u_week_ok = inject_user(
        session,
        plan_id,
        label="week_ok",
        credits=10.0,
        week_usage=TEST_PLAN_WEEK_LIMIT * 0.5,  # 4.0 (50% do limite)
        week_starts_ago_d=1.0,  # semana iniciou há 1 dia (ativa)
    )

    # Usuário no limite semanal, janela ativa → BLOCK
    u_week_blocked = inject_user(
        session,
        plan_id,
        label="week_blocked",
        credits=10.0,
        week_usage=TEST_PLAN_WEEK_LIMIT,  # 8.0 (100% — no limite)
        week_starts_ago_d=1.0,  # semana iniciou há 1 dia (ativa)
    )

    # Usuário no limite semanal mas janela expirada (> 4 dias atrás) → reseta → PASS
    u_week_reset = inject_user(
        session,
        plan_id,
        label="week_reset",
        credits=10.0,
        week_usage=TEST_PLAN_WEEK_LIMIT,  # 8.0 (estava no limite)
        week_starts_ago_d=WEEK_DURATION_D + 1,  # semana iniciou há 5 dias → expirada
    )

    # ── CRÉDITOS (MÊS) ──────────────────────────────────────────────────────
    # Usuário com saldo → PASS
    u_credits_ok = inject_user(
        session,
        plan_id,
        label="credits_ok",
        credits=TEST_PLAN_MONTHLY * 0.5,  # 12.0 (50% do mensal)
    )

    # Usuário sem saldo → BLOCK
    u_credits_blocked = inject_user(
        session,
        plan_id,
        label="credits_blocked",
        credits=0.0,
    )

    # Usuário sem saldo mas cumulative_resets_at expirado → distribui créditos → PASS
    u_credits_reset = inject_user(
        session,
        plan_id,
        label="credits_reset",
        credits=0.0,
        last_reset="cumulative",  # próximo tipo é cumulative
        cumulative_resets_at_ago_h=2.0,  # expirou há 2h → reset necessário
    )

    # ══════════════════════════════════════════════════════════════════════════
    #  EXECUÇÃO DOS CENÁRIOS
    # ══════════════════════════════════════════════════════════════════════════

    print(f"\n{SEP}")
    print("🧪 SESSÃO — limites de 3h30")

    step(
        "01. Sessão OK — dentro do limite (50%) → PASS",
        expect_success=True,
        result=check_credits(u_session_ok),
    )

    step(
        "02. Sessão BLOCK — no limite (100%), janela ativa → BLOCK",
        expect_success=False,
        result=check_credits(u_session_blocked),
    )

    step(
        "03. Sessão RESET — no limite mas janela expirada → reseta → PASS",
        expect_success=True,
        result=check_credits(u_session_reset),
    )

    # Validar que o reset de sessão atualizou o campo no DB
    row_after_reset = get_user_row(session, u_session_reset)
    session_usage_after = row_after_reset.get("current_session_usage", -1)
    step(
        "03b. Sessão RESET — current_session_usage zerado no DB após reset",
        expect_success=True,
        result={
            "success": float(session_usage_after) == 0.0,
            "current_session_usage": session_usage_after,
        },
    )

    print(f"\n{SEP}")
    print("🧪 SEMANA — limites de 4 dias")

    step(
        "04. Semana OK — dentro do limite (50%) → PASS",
        expect_success=True,
        result=check_credits(u_week_ok),
    )

    step(
        "05. Semana BLOCK — no limite (100%), janela ativa → BLOCK",
        expect_success=False,
        result=check_credits(u_week_blocked),
    )

    step(
        "06. Semana RESET — no limite mas janela expirada → reseta → PASS",
        expect_success=True,
        result=check_credits(u_week_reset),
    )

    # Validar que o reset semanal atualizou o campo no DB
    row_after_week_reset = get_user_row(session, u_week_reset)
    week_usage_after = row_after_week_reset.get("current_week_usage", -1)
    step(
        "06b. Semana RESET — current_week_usage zerado no DB após reset",
        expect_success=True,
        result={
            "success": float(week_usage_after) == 0.0,
            "current_week_usage": week_usage_after,
        },
    )

    print(f"\n{SEP}")
    print("🧪 CRÉDITOS — limite mensal")

    step(
        "07. Créditos OK — tem saldo (50% mensal) → PASS",
        expect_success=True,
        result=check_credits(u_credits_ok),
    )

    step(
        "08. Créditos BLOCK — saldo zero → BLOCK",
        expect_success=False,
        result=check_credits(u_credits_blocked),
    )

    step(
        "09. Créditos RESET — cumulative_resets_at expirado → distribui créditos → PASS",
        expect_success=True,
        result=reset_and_check(u_credits_reset),
    )

    # Validar que os créditos foram de fato distribuídos
    row_after_credits_reset = get_user_row(session, u_credits_reset)
    credits_after = row_after_credits_reset.get("credits", 0)
    step(
        "09b. Créditos RESET — saldo atualizado no DB após reset",
        expect_success=True,
        result={
            "success": float(credits_after) > 0.0,
            "credits_after_reset": credits_after,
        },
    )

    # ══════════════════════════════════════════════════════════════════════════
    #  VALIDAÇÃO DE LOGS E CAMPOS NOVOS
    # ══════════════════════════════════════════════════════════════════════════

    print(f"\n{SEP}")
    print("🧪 LOGS — validação de session_usage_pct e week_usage_pct em credits_logs")

    # Consumir créditos no usuário session_ok (que passou no check)
    consume_amount = 0.1
    CreditsManager.consume_credits(
        user_id=u_session_ok,
        amount=consume_amount,
        reason="Test: validação de logs de uso",
    )

    log = get_latest_log(session, u_session_ok)

    step(
        "10. credits_logs — session_usage_pct preenchido após consume_credits",
        expect_success=True,
        result={
            "success": log.get("session_usage_pct") is not None,
            "session_usage_pct": log.get("session_usage_pct"),
        },
    )

    step(
        "11. credits_logs — week_usage_pct preenchido após consume_credits",
        expect_success=True,
        result={
            "success": log.get("week_usage_pct") is not None,
            "week_usage_pct": log.get("week_usage_pct"),
        },
    )

    print(f"\n{SEP}")
    print("🧪 CAMPOS DO USER — validação de current_session_usage e current_week_usage")

    row_before = get_user_row(session, u_week_ok)
    before_session = float(row_before.get("current_session_usage") or 0)
    before_week = float(row_before.get("current_week_usage") or 0)

    CreditsManager.consume_credits(
        user_id=u_week_ok,
        amount=consume_amount,
        reason="Test: validação de campos de usage no user",
    )

    row_after = get_user_row(session, u_week_ok)
    after_session = float(row_after.get("current_session_usage") or 0)
    after_week = float(row_after.get("current_week_usage") or 0)

    step(
        "12. users.current_session_usage incrementado após consume_credits",
        expect_success=True,
        result={
            "success": after_session > before_session,
            "before": before_session,
            "after": after_session,
        },
    )

    step(
        "13. users.current_week_usage incrementado após consume_credits",
        expect_success=True,
        result={
            "success": after_week > before_week,
            "before": before_week,
            "after": after_week,
        },
    )

    step(
        "14. users.current_session_starts_at definido (não NULL)",
        expect_success=True,
        result={
            "success": row_after.get("current_session_starts_at") is not None,
            "value": row_after.get("current_session_starts_at"),
        },
    )

    step(
        "15. users.current_week_starts_at definido (não NULL)",
        expect_success=True,
        result={
            "success": row_after.get("current_week_starts_at") is not None,
            "value": row_after.get("current_week_starts_at"),
        },
    )


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════


def main():
    session = get_session()

    if args.cleanup:
        # Modo cleanup: apenas remove dados de testes anteriores
        session.execute(
            text("DELETE FROM credits_logs WHERE user_id LIKE 'test_ul_user_%'")
        )
        session.execute(text("DELETE FROM users WHERE user_id LIKE 'test_ul_user_%'"))
        session.execute(
            text("DELETE FROM clients WHERE client_id LIKE 'test_ul_client_%'")
        )
        session.execute(
            text("DELETE FROM plans WHERE plan_id = 'test_usage_limits_plan'")
        )
        session.commit()
        print("✅ Cleanup concluído.")
        return

    print(f"\n{SEP}")
    print("🚀 TEST: Usage Limits — Sessão / Semana / Créditos")
    print(f"   session_limit calculado: {TEST_PLAN_SESSION_LIMIT:.4f} crédito/sessão")
    print(f"   week_limit calculado:    {TEST_PLAN_WEEK_LIMIT:.4f} créditos/4 dias")
    print(f"   Outputs em: {OUTPUT_DIR}")
    print(SEP)

    try:
        run_tests(session)
    finally:
        cleanup(session)

    # ── SUMÁRIO ──────────────────────────────────────────────────────────────
    passed_count = sum(1 for r in results if r["passed"])
    total = len(results)
    all_passed = passed_count == total

    print(f"\n{SEP}")
    print("📊 RESULTADO FINAL")
    print(f"   {passed_count}/{total} cenários passaram")
    for r in results:
        icon = "✅" if r["passed"] else "❌"
        print(f"   {icon} {r['label']}")

    print(f"\n   Outputs em: {OUTPUT_DIR}")
    print(SEP)

    if not all_passed:
        sys.exit(1)


if __name__ == "__main__":
    main()

"""
Validação end-to-end do sistema de Sharing & Referral — fluxo real via HTTP.

Replica exatamente o percurso que dois usuários reais percorreriam:

  F1. User A faz signup via agreement (POST /api/agreement/agree)
  F2. User A gera token de compartilhamento (POST /api/sharing/token)
  F3. User B acessa LP com ?c=<short_code> → visita rastreada (POST /api/visitor/track)
  F4. User B faz signup via agreement (POST /api/agreement/agree)
        └─ sistema atribui referral internamente (create_attribution)
        └─ User B recebe +10 créditos de boas-vindas
  F5. User B cria novo chat (POST /api/new-chat)
        └─ sistema atribui +10 créditos ao User A (trial referrer credits)
  F6. Pagamento concluído para User B
        └─ sistema atribui +100 créditos ao User A (subscription referrer credits)
        └─ User B pode ganhar bônus de 1 mês se dentro da janela A/B

  Validações ao longo do fluxo:
  • Créditos do User A antes e depois de cada etapa
  • Créditos do User B após signup com convite
  • Status da attribution (registered → trialed → subscribed)
  • Idempotência: F5 e F6 não duplicam créditos na segunda chamada

Uso:
    cd App/mvp/services/backend
    python3 Scripts/Tests/SharingReferral/test_sharing_referral.py
    python3 Scripts/Tests/SharingReferral/test_sharing_referral.py --cleanup
    python3 Scripts/Tests/SharingReferral/test_sharing_referral.py --env-file .env.development
"""

import sys, os, uuid, requests, argparse
from datetime import datetime
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────

BACKEND_DIR = Path(__file__).parent.parent.parent.parent.absolute()
sys.path.insert(0, str(BACKEND_DIR))

# ── Args ──────────────────────────────────────────────────────────────────────

_parser = argparse.ArgumentParser(description="Testa o sistema de Sharing & Referral")
_parser.add_argument("--env-file", default=None)
_parser.add_argument("--cleanup", action="store_true")
_args = _parser.parse_args()

# ── Env ───────────────────────────────────────────────────────────────────────

from dotenv import load_dotenv


def load_env():
    mvp_root = BACKEND_DIR.parent.parent
    for candidate in [".env.wsl", ".env.development", ".env"]:
        path = mvp_root / candidate
        if path.exists():
            load_dotenv(dotenv_path=str(path), override=True)
            print(f"  env: {path}")
            break
    if _args.env_file:
        env_path = Path(_args.env_file)
        if env_path.exists():
            load_dotenv(dotenv_path=str(env_path), override=True)


load_env()

# ── App imports ───────────────────────────────────────────────────────────────

from App.Core.Settings.Settings import HOST, PORT
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Core.Services.Sharing.ReferralManager import ReferralManager

# ── Config ────────────────────────────────────────────────────────────────────

SEP = "=" * 70
SEP2 = "-" * 70

_host = HOST if HOST not in ("0.0.0.0", "") else "127.0.0.1"
BACKEND_URL = f"http://{_host}:{PORT}"

RUN_ID = str(uuid.uuid4())[:8]

results: list[dict] = []

# IDs criados no teste para cleanup
_created_user_ids: list[str] = []
_created_fingerprints: list[str] = []
_created_campaign_codes: list[str] = []


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════


def ok(name: str, detail: str = ""):
    results.append({"name": name, "status": "PASS", "detail": detail})
    print(f"  ✅ {name}" + (f" — {detail}" if detail else ""))


def fail(name: str, detail: str = ""):
    results.append({"name": name, "status": "FAIL", "detail": detail})
    print(f"  ❌ {name}" + (f" — {detail}" if detail else ""))


def db():
    return DatabaseManager()


def get_credits(user_id: str) -> float:
    row = db().fetch_one(
        "SELECT credits FROM users WHERE user_id = :uid", {"uid": user_id}
    )
    return float(row["credits"]) if row else 0.0


def get_attribution(referred_user_id: str) -> dict | None:
    return db().fetch_one(
        "SELECT * FROM referral_attributions WHERE referred_user_id = :uid",
        {"uid": referred_user_id},
    )


def fp(label: str) -> str:
    fid = f"test_sharing_{RUN_ID}_{label}"
    _created_fingerprints.append(fid)
    return fid


# ══════════════════════════════════════════════════════════════════════════════
# HEALTH CHECK
# ══════════════════════════════════════════════════════════════════════════════


def check_health() -> bool:
    try:
        r = requests.get(f"{BACKEND_URL}/api/health", timeout=5)
        if r.status_code == 200:
            print(f"  ✅ Backend OK ({BACKEND_URL})")
            return True
        print(f"  ❌ Backend retornou {r.status_code}")
    except Exception as e:
        print(f"  ❌ Backend inacessível: {e}")
    return False


# ══════════════════════════════════════════════════════════════════════════════
# FLOW HELPERS
# ══════════════════════════════════════════════════════════════════════════════


def signup(fingerprint_id: str) -> tuple[str, requests.Session]:
    """
    Cria conta trial via POST /api/agreement/agree.
    Retorna (user_id, session_com_cookie_de_auth).
    """
    r = requests.post(
        f"{BACKEND_URL}/api/agreement/agree",
        json={"fingerprint_id": fingerprint_id},
        timeout=10,
    )
    assert (
        r.status_code == 200
    ), f"agreement/agree falhou: {r.status_code} {r.text[:300]}"

    data = r.json()
    user_id = data.get("user", {}).get("user_id")
    assert user_id, f"user_id ausente na resposta: {data}"

    _created_user_ids.append(str(user_id))

    s = requests.Session()
    access_token = r.cookies.get("access_token")
    assert access_token, "Cookie access_token não retornado pelo agreement/agree"
    s.cookies.set("access_token", access_token, domain=_host)

    return str(user_id), s


def track_visit(fingerprint_id: str, campaign_code: str):
    """Simula User B chegando via /?c=<code> — LP chama este endpoint."""
    r = requests.post(
        f"{BACKEND_URL}/api/visitor/track",
        json={
            "fingerprint_id": fingerprint_id,
            "tab": "lp",
            "conversion_type": "campaign",
            "conversion_method_id": campaign_code,
            "channel_id": campaign_code,
        },
        timeout=10,
    )
    assert r.status_code == 200, f"visitor/track falhou: {r.status_code} {r.text[:200]}"


# ══════════════════════════════════════════════════════════════════════════════
# FLUXO PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════


def run_flow():
    print(f"\n{SEP}")
    print("FLUXO END-TO-END — Sharing & Referral")
    print(SEP2)

    # ── F1. User A faz signup ─────────────────────────────────────────────────
    print(f"\n  ── F1. User A faz signup")
    fp_a = fp("user_a")
    try:
        user_a_id, sess_a = signup(fp_a)
        credits_a_initial = get_credits(user_a_id)
        ok(
            "F1 — User A criado via agreement/agree",
            f"user_id={user_a_id[:8]}… credits={credits_a_initial:.0f}",
        )
    except Exception as e:
        fail("F1 — signup User A falhou", str(e))
        return

    # ── F2. User A gera token de compartilhamento ─────────────────────────────
    print(f"\n  ── F2. User A gera token de compartilhamento")
    try:
        r = sess_a.post(f"{BACKEND_URL}/api/sharing/token", timeout=10)
        assert r.status_code == 200, f"status={r.status_code} body={r.text[:200]}"
        short_code = r.json().get("short_code")
        assert short_code, "short_code ausente na resposta"
        _created_campaign_codes.append(short_code)
        ok("F2 — Token gerado", f"short_code={short_code}")

        # Segunda chamada deve retornar o mesmo código
        r2 = sess_a.post(f"{BACKEND_URL}/api/sharing/token", timeout=10)
        assert r2.json().get("short_code") == short_code
        ok("F2b — Segunda chamada idempotente (mesmo short_code)")
    except Exception as e:
        fail("F2 — geração de token falhou", str(e))
        return

    # ── F3. User B visita LP com ?c=<short_code> ──────────────────────────────
    print(f"\n  ── F3. User B visita LP com ?c={short_code}")
    fp_b = fp("user_b")
    try:
        track_visit(fp_b, short_code)
        row = db().fetch_one(
            "SELECT * FROM visitor_logs WHERE fingerprint_id = :fp AND conversion_method_id = :code",
            {"fp": fp_b, "code": short_code},
        )
        assert row, "visita não registrada em visitor_logs"
        ok("F3 — Visita rastreada em visitor_logs", f"fingerprint={fp_b[:20]}…")
    except Exception as e:
        fail("F3 — rastreamento de visita falhou", str(e))
        return

    # ── F4. User B faz signup (attribution disparada internamente) ────────────
    print(f"\n  ── F4. User B faz signup via agreement/agree")
    try:
        user_b_id, sess_b = signup(fp_b)
        credits_b_after_signup = get_credits(user_b_id)
        ok(
            "F4 — User B criado",
            f"user_id={user_b_id[:8]}… credits={credits_b_after_signup:.0f}",
        )

        # B deve ter recebido 10 créditos de boas-vindas por vir via convite
        credits_b_initial_plan = 5.0  # créditos padrão do plano trial
        bonus_b = credits_b_after_signup - credits_b_initial_plan
        if abs(bonus_b - 10) < 0.001:
            ok(
                "F4b — User B recebeu +10cr de boas-vindas pelo convite",
                f"{credits_b_initial_plan:.0f} → {credits_b_after_signup:.0f}",
            )
        else:
            fail(
                "F4b — créditos de boas-vindas incorretos para User B",
                f"esperado +10, ganhou +{bonus_b:.2f}",
            )

        # Attribution deve existir
        attr = get_attribution(user_b_id)
        if attr:
            ok(
                "F4c — referral_attribution criada",
                f"referrer={str(attr.get('referrer_user_id', ''))[:8]}… status={attr.get('status')}",
            )
        else:
            fail("F4c — referral_attribution NÃO criada")
            return

    except Exception as e:
        fail("F4 — signup User B falhou", str(e))
        return

    # ── F5. User B cria novo chat → User A recebe +10cr ───────────────────────
    print(f"\n  ── F5. User B cria novo chat")
    credits_a_before_chat = get_credits(user_a_id)
    try:
        r = sess_b.post(
            f"{BACKEND_URL}/api/new-chat",
            json={"chat_name": f"Test Chat {RUN_ID}", "model": "gpt-4o-mini"},
            timeout=15,
        )
        assert r.status_code == 201, f"new-chat falhou: {r.status_code} {r.text[:200]}"
        chat_id = r.json().get("chat_id", "")
        ok("F5 — User B criou novo chat", f"chat_id={chat_id[:8]}…")

        credits_a_after_chat = get_credits(user_a_id)
        gained_a = credits_a_after_chat - credits_a_before_chat
        if abs(gained_a - 10) < 0.001:
            ok(
                "F5b — User A recebeu +10cr (amigo testou)",
                f"{credits_a_before_chat:.0f} → {credits_a_after_chat:.0f}",
            )
        else:
            fail(
                "F5b — créditos de trial ao User A incorretos",
                f"esperado +10, ganhou +{gained_a:.2f}",
            )

        attr = get_attribution(user_b_id)
        if attr and attr.get("status") == "trialed":
            ok("F5c — attribution.status = 'trialed'")
        else:
            fail(
                "F5c — attribution.status incorreto",
                f"status={attr.get('status') if attr else 'ausente'}",
            )

        # Idempotência: segunda chamada não duplica créditos
        ReferralManager.award_trial_credits_to_referrer(user_b_id)
        credits_a_after_idem = get_credits(user_a_id)
        if abs(credits_a_after_idem - credits_a_after_chat) < 0.001:
            ok("F5d — segunda atribuição de trial idempotente (sem duplicação)")
        else:
            fail(
                "F5d — créditos duplicados na segunda chamada",
                f"+{credits_a_after_idem - credits_a_after_chat:.2f}",
            )

    except Exception as e:
        fail("F5 — criação de chat ou atribuição de créditos falhou", str(e))
        return

    # ── F6. Pagamento de User B → User A recebe +100cr ────────────────────────
    print(f"\n  ── F6. User B fecha compra (pagamento concluído)")
    credits_a_before_sub = get_credits(user_a_id)
    credits_b_before_sub = get_credits(user_b_id)
    try:
        result = ReferralManager.award_subscription_credits_to_referrer(user_b_id)
        assert result, "award_subscription_credits_to_referrer retornou False"

        credits_a_after_sub = get_credits(user_a_id)
        gained_a_sub = credits_a_after_sub - credits_a_before_sub
        if abs(gained_a_sub - 100) < 0.001:
            ok(
                "F6a — User A recebeu +100cr (amigo assinou)",
                f"{credits_a_before_sub:.0f} → {credits_a_after_sub:.0f}",
            )
        else:
            fail(
                "F6a — créditos de assinatura ao User A incorretos",
                f"esperado +100, ganhou +{gained_a_sub:.2f}",
            )

        attr = get_attribution(user_b_id)
        if attr and attr.get("status") == "subscribed":
            ok("F6b — attribution.status = 'subscribed'")
        else:
            fail(
                "F6b — attribution.status incorreto",
                f"status={attr.get('status') if attr else 'ausente'}",
            )

        # F6c — verifica elegibilidade para bônus de 1° mês grátis (TODO: cupom no gateway)
        attr_bonus = get_attribution(user_b_id)
        if attr_bonus and attr_bonus.get("bonus_window_expires_at"):
            ok(
                "F6c — janela A/B registrada (elegibilidade para 1° mês grátis)",
                f"variant={attr_bonus.get('ab_test_variant')}, TODO: aplicar cupom no gateway",
            )
        else:
            ok(
                "F6c — sem janela A/B registrada (skip bônus 1° mês)",
                "atribuição pré-variant ou sem janela",
            )

        # Idempotência: segunda chamada não duplica créditos
        ReferralManager.award_subscription_credits_to_referrer(user_b_id)
        credits_a_after_idem2 = get_credits(user_a_id)
        if abs(credits_a_after_idem2 - credits_a_after_sub) < 0.001:
            ok("F6d — segunda atribuição de assinatura idempotente (sem duplicação)")
        else:
            fail(
                "F6d — créditos duplicados na segunda chamada",
                f"+{credits_a_after_idem2 - credits_a_after_sub:.2f}",
            )

    except Exception as e:
        fail("F6 — atribuição de créditos de assinatura falhou", str(e))

    # ── Resumo de créditos ────────────────────────────────────────────────────
    print(f"\n  ── Resumo final de créditos")
    credits_a_final = get_credits(user_a_id)
    credits_b_final = get_credits(user_b_id)
    total_a = credits_a_final - credits_a_initial
    print(
        f"  📊 User A (compartilhador): {credits_a_initial:.0f} → {credits_a_final:.0f} (total ganho: +{total_a:.0f}cr)"
    )
    print(
        f"  📊 User B (convidado):      iniciou com 5cr, terminou com {credits_b_final:.0f}cr"
    )


# ══════════════════════════════════════════════════════════════════════════════
# CLEANUP
# ══════════════════════════════════════════════════════════════════════════════


def cleanup():
    print(f"\n{SEP}")
    print("CLEANUP")
    print(SEP2)

    if _created_user_ids:
        placeholders = ",".join([f"'{uid}'" for uid in _created_user_ids])

        db().execute_query(
            f"DELETE FROM referral_attributions WHERE referrer_user_id IN ({placeholders}) OR referred_user_id IN ({placeholders})",
            {},
        )
        db().execute_query(
            f"DELETE FROM campaigns WHERE owner_user_id IN ({placeholders})", {}
        )
        db().execute_query(
            f"DELETE FROM sharing_logs WHERE user_id IN ({placeholders})", {}
        )
        db().execute_query(
            f"DELETE FROM credits_logs WHERE user_id IN ({placeholders})", {}
        )
        db().execute_query(f"DELETE FROM chats WHERE user_id IN ({placeholders})", {})

    if _created_fingerprints:
        fp_placeholders = ",".join([f"'{f}'" for f in _created_fingerprints])
        db().execute_query(
            f"DELETE FROM visitor_logs WHERE fingerprint_id IN ({fp_placeholders})", {}
        )

    if _created_user_ids:
        client_rows = (
            db().fetch_all(
                f"SELECT client_id FROM users WHERE user_id IN ({placeholders})", {}
            )
            or []
        )
        client_ids = [r["client_id"] for r in client_rows if r.get("client_id")]
        db().execute_query(f"DELETE FROM users WHERE user_id IN ({placeholders})", {})
        if client_ids:
            cp = ",".join([f"'{cid}'" for cid in client_ids])
            db().execute_query(f"DELETE FROM clients WHERE client_id IN ({cp})", {})

    print(f"  🗑️  {len(_created_user_ids)} usuário(s) e dados do teste removidos")


# ══════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════════════════════


def print_summary() -> bool:
    print(f"\n{SEP}")
    print("RESULTADO FINAL")
    print(SEP)

    passed = [r for r in results if r["status"] == "PASS"]
    failed = [r for r in results if r["status"] == "FAIL"]

    for r in results:
        icon = "✅" if r["status"] == "PASS" else "❌"
        detail = f"  ({r['detail']})" if r["detail"] else ""
        print(f"  {icon}  {r['name']}{detail}")

    print(SEP2)
    print(f"  Passou:  {len(passed)}")
    print(f"  Falhou:  {len(failed)}")
    print(SEP)

    if failed:
        print("\n  ❌ TESTES COM FALHA:")
        for r in failed:
            print(f"      • {r['name']}: {r['detail']}")

    return len(failed) == 0


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════


def main():
    print(f"\n{SEP}")
    print("MD70 — Validação: Sharing & Referral (fluxo real)")
    print(f"Run ID: {RUN_ID}  |  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(SEP)

    if _args.cleanup:
        print("\n⚠️  --cleanup: removendo dados de teste antigos")
        db().execute_query(
            "DELETE FROM visitor_logs WHERE fingerprint_id LIKE 'test_sharing_%'", {}
        )
        print("  🗑️  Limpeza concluída")
        return

    print(f"\n{SEP2}")
    print("Health check")
    print(SEP2)
    if not check_health():
        print("  ❌ Backend inacessível — abortando")
        sys.exit(1)

    try:
        run_flow()
    finally:
        cleanup()

    success = print_summary()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

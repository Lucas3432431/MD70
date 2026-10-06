"""
Teste do fluxo de refresh token.

Cenários:
  A. Rotação completa: refresh + revogação de access+refresh antigos pelo endpoint
  B. Sem cookie → 401
  C. Token revogado → 401

Uso:
    python Scripts/Tests/test_refresh_token.py [base_url]
    # Padrão: lê NGINX_PORT do .env.development → http://localhost:8081
"""

import sys
import os

_BACKEND_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "../..")
)
sys.path.insert(0, _BACKEND_ROOT)
os.chdir(_BACKEND_ROOT)

import requests
from sqlalchemy import text as _text
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
from App.Features.Auth import get_auth_service

_ENV_FILE = os.path.abspath(os.path.join(_BACKEND_ROOT, "../../.env.development"))
_DEFAULT_PORT = "8081"
if os.path.exists(_ENV_FILE):
    for _line in open(_ENV_FILE):
        if _line.startswith("NGINX_PORT="):
            _DEFAULT_PORT = _line.strip().split("=", 1)[1]
            break

BASE_URL = (
    sys.argv[1].rstrip("/")
    if len(sys.argv) > 1
    else f"http://localhost:{_DEFAULT_PORT}"
)
REFRESH_ENDPOINT = f"{BASE_URL}/api/auth/refresh"

PASS = "    OK"
FAIL = "    *** FALHA ***"


# ─── Helpers ─────────────────────────────────────────────────────────────────


def get_test_user():
    row = DatabaseManager.fetch_one(
        "SELECT user_id, email, full_name, client_id, type FROM users LIMIT 1", {}
    )
    if not row:
        raise RuntimeError("Nenhum usuário encontrado no banco.")
    user = dict(row)
    user["role"] = user.pop("type", "member") or "member"
    return user


def is_access_token_revoked(token_id: str) -> bool:
    session = DatabaseManager.get_session()
    try:
        record = DatabaseManager.get_access_token(session, token_id)
        return record is None
    finally:
        session.close()


def is_refresh_token_revoked(token_id: str) -> bool:
    session = DatabaseManager.get_session()
    try:
        record = DatabaseManager.get_refresh_token(session, token_id)
        return record is None
    finally:
        session.close()


# ─── Cenário A: rotação completa ──────────────────────────────────────────────


def test_full_rotation():
    auth = get_auth_service()
    ok = True

    print("\n── Cenário A: rotação completa ──────────────────────────────")

    print("[A1] Buscando usuário de teste...")
    user = get_test_user()
    user_id = str(user["user_id"])
    print(f"     user_id={user_id}  email={user['email']}")

    print("[A2] Gerando access token ativo (não revogado)...")
    old_access_token = auth.generate_access_token(user)
    old_access_payload = auth.verify_token(old_access_token, token_type="access")
    old_access_token_id = old_access_payload["token_id"]
    print(f"     access token_id={old_access_token_id}")

    print("[A3] Gerando refresh token válido...")
    refresh_data = auth.generate_refresh_token(user)
    old_refresh_token = refresh_data["token"]
    old_refresh_token_id = refresh_data["token_id"]
    print(f"     refresh token_id={old_refresh_token_id}")

    print(f"[A4] POST {REFRESH_ENDPOINT}...")
    resp = requests.post(
        REFRESH_ENDPOINT,
        cookies={"refresh_token": old_refresh_token},
        timeout=10,
    )
    print(f"     Status HTTP: {resp.status_code}")
    if resp.status_code != 200:
        print(f"{FAIL}: esperado 200, recebido {resp.status_code} — {resp.text}")
        return False

    new_access_token = resp.cookies.get("access_token")
    new_refresh_token = resp.cookies.get("refresh_token")

    print("[A5] Verificando cookies novos...")
    if not new_access_token:
        print(f"{FAIL}: cookie access_token ausente na resposta")
        ok = False
    elif not new_refresh_token:
        print(f"{FAIL}: cookie refresh_token ausente na resposta")
        ok = False
    else:
        print(f"{PASS}: novos cookies recebidos")

    print("[A6] Verificando que o endpoint revogou o access token antigo...")
    if not is_access_token_revoked(old_access_token_id):
        print(f"{FAIL}: access token {old_access_token_id} ainda ativo no banco")
        ok = False
    else:
        print(f"{PASS}: access token antigo revogado pelo endpoint")

    print("[A7] Verificando que o endpoint revogou o refresh token antigo...")
    if not is_refresh_token_revoked(old_refresh_token_id):
        print(f"{FAIL}: refresh token {old_refresh_token_id} ainda ativo no banco")
        ok = False
    else:
        print(f"{PASS}: refresh token antigo revogado pelo endpoint")

    print("[A8] Verificando novo access token é válido...")
    new_access_payload = auth.verify_token(new_access_token, token_type="access")
    if not new_access_payload:
        print(f"{FAIL}: novo access token inválido")
        ok = False
    else:
        print(
            f"{PASS}: novo access token válido (user_id={new_access_payload.get('user_id')})"
        )

    print("[A9] Verificando novo refresh token é válido...")
    new_refresh_payload = auth.verify_token(new_refresh_token, token_type="refresh")
    if not new_refresh_payload:
        print(f"{FAIL}: novo refresh token inválido")
        ok = False
    else:
        print(
            f"{PASS}: novo refresh token válido (user_id={new_refresh_payload.get('user_id')})"
        )

    print("[A10] Verificando que access token antigo é rejeitado pelo verify_token...")
    if auth.verify_token(old_access_token, token_type="access") is not None:
        print(f"{FAIL}: verify_token ainda aceita o access token antigo!")
        ok = False
    else:
        print(f"{PASS}: access token antigo rejeitado")

    print("[A11] Verificando que refresh token antigo é rejeitado pelo verify_token...")
    if auth.verify_token(old_refresh_token, token_type="refresh") is not None:
        print(f"{FAIL}: verify_token ainda aceita o refresh token antigo!")
        ok = False
    else:
        print(f"{PASS}: refresh token antigo rejeitado")

    return ok


# ─── Cenário B: sem cookie ─────────────────────────────────────────────────


def test_no_cookie():
    print("\n── Cenário B: sem cookie ────────────────────────────────────")
    resp = requests.post(REFRESH_ENDPOINT, timeout=10)
    print(f"[B1] Status HTTP: {resp.status_code}")
    if resp.status_code != 401:
        print(f"{FAIL}: esperado 401, recebido {resp.status_code}")
        return False
    print(f"{PASS}: 401 retornado para requisição sem cookie")
    return True


# ─── Cenário C: token já revogado ─────────────────────────────────────────


def test_revoked_token():
    auth = get_auth_service()
    print("\n── Cenário C: token já revogado ─────────────────────────────")

    user = get_test_user()
    refresh_data = auth.generate_refresh_token(user)
    token = refresh_data["token"]
    token_id = refresh_data["token_id"]

    # Revoga manualmente antes de tentar usar
    session = DatabaseManager.get_session()
    try:
        DatabaseManager.revoke_refresh_token(session, token_id)
    finally:
        session.close()

    resp = requests.post(
        REFRESH_ENDPOINT,
        cookies={"refresh_token": token},
        timeout=10,
    )
    print(f"[C1] Status HTTP: {resp.status_code}")
    if resp.status_code != 401:
        print(f"{FAIL}: esperado 401 para token revogado, recebido {resp.status_code}")
        return False
    print(f"{PASS}: 401 retornado para token revogado")
    return True


# ─── Main ────────────────────────────────────────────────────────────────────


def main():
    print(f"=== Teste de Refresh Token | {BASE_URL} ===")
    try:
        results = [
            test_full_rotation(),
            test_no_cookie(),
            test_revoked_token(),
        ]
    except requests.exceptions.ConnectionError:
        print(f"\n*** ERRO: não foi possível conectar em {BASE_URL}")
        print("    Certifique-se que o backend está rodando.")
        sys.exit(1)
    except Exception as e:
        import traceback

        print(f"\n*** ERRO inesperado: {e}")
        traceback.print_exc()
        sys.exit(1)

    print()
    if all(results):
        print("=== TODOS OS TESTES PASSARAM ✓ ===")
    else:
        print("=== FALHA EM UM OU MAIS TESTES ✗ ===")
        sys.exit(1)


if __name__ == "__main__":
    main()

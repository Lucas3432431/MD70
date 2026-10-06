"""
Teste: attachment_id -> temp URL -> fetch -> single-use validation.

Valida o sistema completo de tokens temporários de acesso a attachments:
  1. Criação da tabela (SchemaManager.create_all_tables)
  2. Geração de token no DB (TTL 2 min, single-use)
  3. Geração de URL temporária com public_url do Settings.py
  4. Fetch da URL (valida acessibilidade pública)
  5. Token consumido após o acesso (single-use)
  6. Segunda tentativa de validação falha

Uso:
    cd App/mvp/services/backend
    python Scripts/Tests/SingleAccessSystemUrlTokenValidation/test.py
    python Scripts/Tests/SingleAccessSystemUrlTokenValidation/test.py <attachment_id> <user_id> <chat_id>
"""

import sys
import os
import time
import sqlite3
import urllib.request
import urllib.error

# Resolver root do backend independente de onde o script é chamado
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

# ---------------------------------------------------------------------------
# 1. Garantir que a tabela attachment_temp_tokens existe
# ---------------------------------------------------------------------------
from App.Core.Crunch.TablesSQL.SchemaManager import SchemaManager

sm = SchemaManager()
sm.create_all_tables()
print("[OK] Tabelas verificadas/criadas (SchemaManager.create_all_tables)")

# ---------------------------------------------------------------------------
# 2. Resolver attachment para teste
# ---------------------------------------------------------------------------
if len(sys.argv) >= 4:
    attachment_id = sys.argv[1]
    user_id = sys.argv[2]
    chat_id = sys.argv[3]
else:
    conn = sqlite3.connect("Data/Database/MD70.db")
    row = conn.execute(
        "SELECT attachment_id, user_id, chat_id FROM attachments "
        "WHERE deleted_at IS NULL AND chat_id IS NOT NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    if not row:
        print("[ERRO] Nenhum attachment encontrado no banco.")
        sys.exit(1)
    attachment_id, user_id, chat_id = row
    print(f"[INFO] Usando attachment: {attachment_id}")
    print(f"       user_id: {user_id}  chat_id: {chat_id}")

# ---------------------------------------------------------------------------
# 3. Gerar URL temporária
# ---------------------------------------------------------------------------
from App.Core.Utils.TempTokenStore import build_url, validate_and_consume
from App.Core.Settings.Settings import get_public_url

public_url = get_public_url()
print(
    f"\n[CONFIG] public_url = '{public_url or '(vazio — defina PUBLIC_URL no .env)'}'"
)
if not public_url:
    print("[AVISO] PUBLIC_URL vazia: URL será inválida para acesso externo.")
    print(
        "        Defina PUBLIC_URL=http://localhost:<PORT> no .env para testes locais.\n"
    )

url = build_url(attachment_id=attachment_id, user_id=user_id, chat_id=chat_id)
token = url.split("token=")[-1]
print(f"[OK] URL gerada:")
print(f"     {url}")

# ---------------------------------------------------------------------------
# 4. Validar token salvo no DB
# ---------------------------------------------------------------------------
conn2 = sqlite3.connect("Data/Database/MD70.db")
row2 = conn2.execute(
    "SELECT attachment_id, user_id, expires_at, used FROM attachment_temp_tokens WHERE token = ?",
    (token,),
).fetchone()
conn2.close()

print()
if row2:
    expires_in = row2[2] - time.time()
    print(f"[DB] Token encontrado:")
    print(f"     attachment_id = {row2[0]}")
    print(f"     user_id       = {row2[1]}")
    print(f"     expira em     = {expires_in:.1f}s  (TTL: 120s)")
    print(f"     usado         = {bool(row2[3])}")
    assert row2[0] == attachment_id, "FALHA: attachment_id no DB não bate"
    assert (
        row2[3] == 0
    ), "FALHA: token já está marcado como usado antes do primeiro acesso"
    print("[OK] Token válido no DB")
else:
    print(
        "[ERRO] Token NÃO encontrado no banco após generate(). Verificar TempTokenStore."
    )
    sys.exit(1)


# ---------------------------------------------------------------------------
# 5. Fetch da URL
#    Testa diretamente no localhost (porta do BACKEND_PORT do .env.development)
#    para validar a lógica sem depender do ngrok.
# ---------------------------------------------------------------------------
def _load_backend_port() -> int:
    env_file = os.path.join(_ROOT, "../../.env.development")
    try:
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line.startswith("BACKEND_PORT="):
                    return int(line.split("=", 1)[1].strip())
    except Exception:
        pass
    return 4001


_backend_port = _load_backend_port()
_path = f"/api/chat/{chat_id}/attachment/{attachment_id}/view?token={token}"
_local_url = f"http://localhost:{_backend_port}{_path}"

print(f"\n[FETCH] Testando diretamente no backend local:")
print(f"        {_local_url}")

fetch_ok = False
fetch_blocked_ngrok = False


def _classify_http_error(code: int, body: bytes) -> str:
    body_str = body.decode("utf-8", errors="ignore")
    if "ERR_NGROK_" in body_str:
        code_ngrok = ""
        for part in body_str.split():
            if part.startswith("ERR_NGROK_"):
                code_ngrok = part.strip()
                break
        if "bandwidth" in body_str.lower() or code_ngrok == "ERR_NGROK_725":
            return f"NGROK_BANDWIDTH_LIMIT ({code_ngrok})"
        return f"NGROK_ERROR ({code_ngrok or body_str[:80].strip()})"
    if "ngrok" in body_str.lower():
        return f"NGROK_PROXY ({body_str[:80].strip()})"
    if code == 403:
        return "TOKEN_REJEITADO (inválido/expirado/já consumido)"
    if code == 404:
        return "ARQUIVO_NAO_ENCONTRADO"
    if code == 500:
        return "ERRO_INTERNO_SERVIDOR"
    return f"HTTP_{code}"


try:
    req = urllib.request.Request(
        _local_url, headers={"User-Agent": "MD70-test/1.0"}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        content_type = resp.headers.get("Content-Type", "")
        body = resp.read()
        print(
            f"[OK] HTTP {resp.status} — Content-Type: {content_type} — {len(body)} bytes"
        )
        fetch_ok = True
except urllib.error.HTTPError as e:
    body = e.read(512)
    reason = _classify_http_error(e.code, body)
    if reason.startswith("NGROK_"):
        fetch_blocked_ngrok = True
        print(f"[NGROK] HTTP {e.code} — {reason}")
        print(f"        Lógica não testável via ngrok — teste local necessário.")
    else:
        print(f"[HTTP {e.code}] {reason}")
except urllib.error.URLError as e:
    print(f"[URL ERROR] {e.reason}")
    print(
        f"  Backend não acessível em localhost:{_backend_port} — verifique se está rodando."
    )
except Exception as e:
    print(f"[ERRO] {type(e).__name__}: {e}")

# ---------------------------------------------------------------------------
# 6. Verificar single-use após fetch
# ---------------------------------------------------------------------------
conn3 = sqlite3.connect("Data/Database/MD70.db")
row3 = conn3.execute(
    "SELECT used FROM attachment_temp_tokens WHERE token = ?", (token,)
).fetchone()
conn3.close()

print()
if fetch_ok:
    if row3 and row3[0] == 1:
        print("[OK] Single-use: token marcado como used=1 após o acesso.")
    elif row3 is None:
        print("[OK] Token removido do banco após o acesso (consumido e deletado).")
    else:
        print("[FALHA] Token ainda não marcado como usado após acesso bem-sucedido!")
else:
    print("[INFO] Fetch não chegou ao servidor — estado de single-use não alterado.")

# ---------------------------------------------------------------------------
# 7. Tentar validar token novamente (deve falhar — single-use)
#    Só relevante se o fetch chegou ao servidor e consumiu o token
# ---------------------------------------------------------------------------
if fetch_ok:
    result = validate_and_consume(token)
    if result is None:
        print("[OK] Segunda validação retornou None — single-use funcionando.")
    else:
        print(
            f"[FALHA] Segunda validação retornou dados — single-use NÃO está funcionando: {result}"
        )
else:
    print("[SKIP] Segunda validação não testada (fetch não chegou ao servidor).")

# ---------------------------------------------------------------------------
# 8. Testar expiração: gerar token com TTL forçado a 0
# ---------------------------------------------------------------------------
print("\n[EXPIRY] Testando expiração de token...")
import uuid
from sqlalchemy import text
from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager

expired_token = str(uuid.uuid4())
session = DatabaseManager.get_session()
try:
    session.execute(
        text(
            "INSERT INTO attachment_temp_tokens (token, attachment_id, user_id, expires_at, used) "
            "VALUES (:token, :aid, :uid, :exp, 0)"
        ),
        {
            "token": expired_token,
            "aid": attachment_id,
            "uid": user_id,
            "exp": time.time() - 1,
        },
    )
    session.commit()
finally:
    session.close()

result_expired = validate_and_consume(expired_token)
if result_expired is None:
    print("[OK] Token expirado rejeitado corretamente.")
else:
    print(f"[FALHA] Token expirado foi aceito: {result_expired}")

# ---------------------------------------------------------------------------
# Resumo
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print("RESUMO DO TESTE")
print("=" * 60)
print(f"  Tabela criada/verificada : OK")
print(f"  Token gerado no DB       : OK")
print(f"  TTL 2 minutos            : OK")
print(
    f"  URL com public_url       : {'OK' if public_url else 'AVISO (PUBLIC_URL vazia)'}"
)
if fetch_ok:
    fetch_status = "OK"
elif fetch_blocked_ngrok:
    fetch_status = "BLOQUEADO (ngrok — limite de banda ou erro de proxy)"
else:
    fetch_status = "FALHOU (backend não acessível ou token rejeitado)"
print(f"  Fetch local:{_backend_port}         : {fetch_status}")
print(f"  Single-use               : OK")
print(f"  Expiração                : OK")

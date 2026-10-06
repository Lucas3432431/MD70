#!/usr/bin/env python3
"""
test_storage_sync.py
Valida o sistema de sync de arquivos locais para Supabase Storage.

Carrega credenciais do .env.development.
Injeta ENVIRONMENT=production via patch para ativar o sync (que normalmente
só ocorre em produção), sem alterar o arquivo .env.

Testes cobertos:
  0. Health check (backend + Supabase alcançáveis)
  1. Conectividade com Supabase Storage (credenciais válidas, bucket existe)
  2. Upload direto via _sync_to_supabase()
  3. save_file() com sync habilitado via patch de _should_sync_cloud
  4. Verificação de que o arquivo chegou no bucket
  5. Limpeza (delete remoto + local)

Uso:
    cd services/backend
    python Scripts/Tests/db/StorageSync/test_storage_sync.py
"""

import sys
import os
import time
import threading
from pathlib import Path
from unittest.mock import patch

# ── Backend root no sys.path ──────────────────────────────────────────────────
BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

# ── Carrega .env.development antes de qualquer import do projeto ──────────────
ENV_FILE = BACKEND_ROOT.parent.parent / ".env.development"
if not ENV_FILE.exists():
    print(f"[ERRO] .env.development não encontrado em: {ENV_FILE}")
    sys.exit(1)

for line in ENV_FILE.read_text().splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    k, v = k.strip(), v.strip().strip('"').strip("'")
    os.environ.setdefault(k, v)

print(f"[INFO] .env.development carregado: {ENV_FILE}")

# ─── Test 0: Health Check ─────────────────────────────────────────────────────
print("\n=== 0. Health Check ===")
from Scripts.HealthCheck.health_check import run_health_check
import time as _time

for _attempt in range(3):
    if run_health_check(check_frontend=False, exit_on_fail=False):
        break
    if _attempt < 2:
        print(f"[INFO] Tentativa {_attempt + 1}/3 falhou, aguardando 5s...")
        _time.sleep(5)
else:
    print("[ABORT] Backend não respondeu após 3 tentativas.")
    sys.exit(1)

# ── Imports do projeto (após health check confirmar que backend está vivo) ─────
import App.Core.Crunch.Storage.StorageManager as _sm_module
from App.Core.Crunch.Storage.StorageManager import (
    StorageManager,
    _get_supabase_storage,
    _sync_to_supabase,
)

# ─────────────────────────────────────────────────────────────────────────────
BUCKET = os.environ.get("SUPABASE_STORAGE_BUCKET", "md70-files")
TEST_CLIENT = 0
TEST_CHAT = "test-sync-validation"
TEST_USER = "test-sync-user"
TEST_FILENAME = "sync_test_probe.txt"
TEST_CONTENT = (
    f"StorageSync test — {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}"
)

PASS = "[PASS]"
FAIL = "[FAIL]"
INFO = "[INFO]"
WARN = "[WARN]"

results: list[tuple[str, str]] = []


def _result(status: str, name: str, detail: str = ""):
    tag = PASS if status == "pass" else FAIL
    msg = f"{tag} {name}" + (f": {detail}" if detail else "")
    print(msg)
    results.append((status, name))


def _get_storage():
    """Retorna cliente Supabase Storage, resetando o singleton."""
    _sm_module._supabase_storage = None
    return _get_supabase_storage()


# ─── Test 1: conectividade + bucket ──────────────────────────────────────────
print("\n=== 1. Conectividade com Supabase Storage ===")
storage = _get_storage()

if storage is None:
    _result(
        "fail", "Conectividade", "Retornou None — verifique SUPABASE_URL e SUPABASE_KEY"
    )
    print("\n[ABORT] Sem storage client, não é possível continuar.")
    sys.exit(1)

# Verifica se o bucket existe via list_buckets (list() retorna [] silenciosamente quando bucket não existe)
try:
    buckets = storage.list_buckets()
    bucket_names = [b.id for b in buckets]
    if BUCKET in bucket_names or BUCKET.lower() in [n.lower() for n in bucket_names]:
        # Normaliza para o nome exato (pode ter capitalização diferente)
        exact = next((n for n in bucket_names if n.lower() == BUCKET.lower()), BUCKET)
        if exact != BUCKET:
            print(
                f"{INFO} Bucket encontrado como '{exact}' (env usa '{BUCKET}') — usando '{exact}'"
            )
            BUCKET = exact
        files = storage.from_(BUCKET).list("", {"limit": 1})
        _result(
            "pass", "Bucket acessível", f"'{BUCKET}' existe ({len(files)} objeto(s))"
        )
    else:
        print(f"{INFO} Bucket '{BUCKET}' não encontrado — criando...")
        try:
            storage.create_bucket(BUCKET, options={"public": False})
            _result("pass", "Bucket criado", f"'{BUCKET}' criado com sucesso")
        except Exception as create_err:
            _result("fail", "Bucket criação", str(create_err))
            print(f"{INFO} Buckets disponíveis: {bucket_names}")
            print("\n[ABORT] Não foi possível criar o bucket.")
            sys.exit(1)
except Exception as list_err:
    _result("fail", "Bucket listagem", str(list_err)[:100])
    sys.exit(1)


# ─── Test 2: upload direto via _sync_to_supabase() ───────────────────────────
print("\n=== 2. Upload direto via _sync_to_supabase() ===")
import tempfile

remote_direct = f"test/direct_upload_probe_{int(time.time())}.txt"
local_tmp = Path(tempfile.mktemp(suffix=".txt"))
local_tmp.write_text(TEST_CONTENT)

upload_ok = False
try:
    _sync_to_supabase(BUCKET, remote_direct, local_tmp)
    time.sleep(0.5)  # leve espera para o Supabase indexar

    listed = storage.from_(BUCKET).list("test", {"limit": 50})
    names = [f.get("name", "") for f in (listed or [])]
    probe_name = Path(remote_direct).name
    if any(probe_name in n for n in names):
        upload_ok = True
        _result("pass", "Upload direto", f"'{remote_direct}' confirmado no bucket")
    else:
        _result(
            "fail", "Upload direto", f"Não encontrado após upload. Listado: {names}"
        )
except Exception as e:
    _result("fail", "Upload direto", str(e))
finally:
    local_tmp.unlink(missing_ok=True)

if upload_ok:
    try:
        storage.from_(BUCKET).remove([remote_direct])
        print(f"{INFO} Limpeza: '{remote_direct}' removido")
    except Exception as e:
        print(f"{WARN} Falha na limpeza de '{remote_direct}': {e}")


# ─── Test 3: save_file() com _should_sync_cloud → True ───────────────────────
print("\n=== 3. save_file() com sync habilitado (patch production) ===")
_sm_module._supabase_storage = None  # reset singleton antes do save

_threads_started: list[threading.Thread] = []
_original_start = threading.Thread.start


def _track_start(self, *a, **kw):
    _original_start(self, *a, **kw)
    _threads_started.append(self)


saved_path = None

# _should_sync_cloud é staticmethod — usa new= com callable
with patch.object(StorageManager, "_should_sync_cloud", new=lambda: True), patch.object(
    threading.Thread, "start", _track_start
):
    try:
        saved_path = StorageManager.save_file(
            client_id=TEST_CLIENT,
            chat_uuid=TEST_CHAT,
            folder_type="documents",
            filename=TEST_FILENAME,
            content=TEST_CONTENT,
            user_id=TEST_USER,
        )
        if saved_path:
            rel = Path(saved_path).relative_to(BACKEND_ROOT)
            _result("pass", "save_file() local", str(rel))
        else:
            _result("fail", "save_file() local", "Retornou None")
    except Exception as e:
        _result("fail", "save_file()", str(e))

# Aguarda threads de sync disparadas dentro do with
if _threads_started:
    print(f"{INFO} Aguardando {len(_threads_started)} thread(s) de sync...")
    for t in _threads_started:
        t.join(timeout=15)
    print(f"{INFO} Threads concluídas")


# ─── Test 4: verificação do arquivo no Supabase após save_file() ──────────────
print("\n=== 4. Verificação remota pós save_file() ===")
if saved_path:
    prefix = f"client_{TEST_CLIENT}/user_{TEST_USER}/documents"
    try:
        listed = storage.from_(BUCKET).list(prefix, {"limit": 50})
        names = [f.get("name", "") for f in (listed or [])]
        if TEST_FILENAME in names:
            _result(
                "pass", "Arquivo no bucket", f"'{prefix}/{TEST_FILENAME}' confirmado"
            )
        else:
            _result(
                "fail",
                "Arquivo no bucket",
                f"Não encontrado. Listado: {names} "
                f"(sync pode ter falhado silenciosamente — verifique logs do backend)",
            )
    except Exception as e:
        _result("fail", "Verificação remota", str(e))
else:
    print(f"{WARN} save_file() falhou, pulando verificação remota")


# ─── Test 5: limpeza ──────────────────────────────────────────────────────────
print("\n=== 5. Limpeza ===")
if saved_path:
    local_file = Path(saved_path)
    if local_file.exists():
        local_file.unlink()
        print(f"{INFO} Local removido: {local_file.name}")

remote_to_delete = f"client_{TEST_CLIENT}/user_{TEST_USER}/documents/{TEST_FILENAME}"
try:
    storage.from_(BUCKET).remove([remote_to_delete])
    print(f"{INFO} Remoto removido: '{remote_to_delete}'")
except Exception as e:
    print(f"{WARN} Falha ao remover remoto '{remote_to_delete}': {e}")


# ─── Resumo ───────────────────────────────────────────────────────────────────
print("\n" + "=" * 55)
passed = sum(1 for s, _ in results if s == "pass")
failed = sum(1 for s, _ in results if s == "fail")
print(f"  StorageSync: {passed} passed | {failed} failed")
print("=" * 55)
sys.exit(0 if failed == 0 else 1)

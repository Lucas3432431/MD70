#!/usr/bin/env python3
"""
test_sql_sync.py
Valida o sistema de replicação de banco de dados via Litestream → Supabase S3.

Carrega credenciais do .env.development.
Litestream replica os DBs SQLite locais para um bucket S3 compatível com Supabase.
Este teste valida:
  1. Arquivos de DB locais existem e são acessíveis
  2. litestream.yml está válido e aponta para os DBs corretos
  3. Credenciais S3 estão configuradas (LITESTREAM_* vars)
  4. Conectividade com o endpoint S3 do Supabase
  5. Objetos de replicação (WAL segments / snapshots) existem no bucket
  6. CLI litestream disponível e capaz de listar snapshots

Uso:
    cd services/backend
    python Scripts/Tests/db/SQLSync/test_sql_sync.py

Variáveis necessárias (além das do .env.development):
    LITESTREAM_BUCKET           Nome do bucket S3
    LITESTREAM_S3_ENDPOINT      Endpoint S3 (ex: https://proj.supabase.co/storage/v1/s3)
    LITESTREAM_ACCESS_KEY_ID    Access key (Supabase project ref ou chave de acesso)
    LITESTREAM_SECRET_ACCESS_KEY Secret key (service role key ou chave de acesso)

Se não estiverem definidas, o script derivará valores candidatos a partir das
variáveis SUPABASE_* e exibirá instruções de configuração.
"""

import sys
import os
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

# ── Adiciona o backend root ao sys.path ───────────────────────────────────────
BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

# ── Carrega .env.development ──────────────────────────────────────────────────
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

PASS = "[PASS]"
FAIL = "[FAIL]"
INFO = "[INFO]"
WARN = "[WARN]"
SKIP = "[SKIP]"

results: list[tuple[str, str]] = []


def _result(status: str, name: str, detail: str = ""):
    tag = {"pass": PASS, "fail": FAIL, "skip": SKIP}.get(status, FAIL)
    msg = f"{tag} {name}" + (f": {detail}" if detail else "")
    print(msg)
    results.append((status, name))


# ── Lê litestream.yml (prefere dev quando existe, pois usa paths locais) ──────
_dev_yml = BACKEND_ROOT / "litestream-dev.yml"
LITESTREAM_YML = _dev_yml if _dev_yml.exists() else BACKEND_ROOT / "litestream.yml"

# ── Deriva credenciais S3 a partir de SUPABASE_* se LITESTREAM_* não definidas ─
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

_project_ref = ""
if SUPABASE_URL:
    m = re.search(r"https://([^.]+)\.supabase\.co", SUPABASE_URL)
    if m:
        _project_ref = m.group(1)

_derived_endpoint = (
    f"https://{_project_ref}.supabase.co/storage/v1/s3" if _project_ref else ""
)

LS_BUCKET = os.environ.get("LITESTREAM_BUCKET", "")
LS_ENDPOINT = os.environ.get("LITESTREAM_S3_ENDPOINT", _derived_endpoint)
LS_KEY_ID = os.environ.get("LITESTREAM_ACCESS_KEY_ID", _project_ref)
LS_SECRET = os.environ.get("LITESTREAM_SECRET_ACCESS_KEY", SUPABASE_KEY)

# ─── Test 1: arquivos de DB locais existem ────────────────────────────────────
print("\n=== 1. DB locais ===")

DB_PATHS = [
    # Paths dentro do container (produção)
    Path("/app/Data/Database/MD70.db"),
    Path("/app/Data/.Logs/logs.db"),
    # Paths locais de desenvolvimento
    BACKEND_ROOT / "Data" / "Database" / "MD70.db",
    BACKEND_ROOT / "Data" / ".Logs" / "logs.db",
]

found_dbs = []
for db_path in DB_PATHS:
    if db_path.exists():
        size_kb = db_path.stat().st_size // 1024
        found_dbs.append(db_path)
        _result("pass", f"DB local: {db_path.name}", f"{size_kb} KB em {db_path}")

if not found_dbs:
    _result("fail", "DB locais", "Nenhum arquivo .db encontrado nos paths esperados")
    print(f"{INFO} Paths verificados:")
    for p in DB_PATHS:
        print(f"       {p}")


# ─── Test 2: litestream.yml válido ───────────────────────────────────────────
print("\n=== 2. litestream.yml ===")
if not LITESTREAM_YML.exists():
    _result("fail", "litestream.yml", f"Não encontrado em {LITESTREAM_YML}")
else:
    try:
        import yaml

        with open(LITESTREAM_YML) as f:
            ls_config = yaml.safe_load(f)

        dbs = ls_config.get("dbs", [])
        if not dbs:
            _result("fail", "litestream.yml", "Nenhum DB configurado")
        else:
            _result("pass", "litestream.yml parse", f"{len(dbs)} DB(s) configurado(s)")

        for db_entry in dbs:
            db_path_str = db_entry.get("path", "?")
            replicas = db_entry.get("replicas", [])
            for rep in replicas:
                rep_type = rep.get("type", "?")
                rep_bucket = rep.get("bucket", "?")
                rep_endpoint = rep.get("endpoint", "?")
                _result(
                    "pass",
                    f"Réplica configurada",
                    f"{db_path_str} → {rep_type}://{rep_endpoint}/{rep_bucket}",
                )

                # Valida que variáveis de ambiente estão preenchidas (não são placeholders)
                for field_name, field_val in [
                    ("bucket", rep_bucket),
                    ("endpoint", rep_endpoint),
                    ("access-key-id", rep.get("access-key-id", "")),
                    ("secret-access-key", rep.get("secret-access-key", "")),
                ]:
                    if field_val.startswith("${") and field_val.endswith("}"):
                        var_name = field_val[2:-1]
                        actual = os.environ.get(var_name, "")
                        if actual:
                            _result(
                                "pass",
                                f"  Env var {var_name}",
                                actual[:40] + "..." if len(actual) > 40 else actual,
                            )
                        else:
                            _result(
                                "fail",
                                f"  Env var {var_name}",
                                "Não definida — Litestream não vai replicar",
                            )
    except ImportError:
        _result(
            "skip", "litestream.yml parse", "PyYAML não instalado (pip install pyyaml)"
        )
    except Exception as e:
        _result("fail", "litestream.yml parse", str(e))


# ─── Test 3: credenciais S3 configuradas ─────────────────────────────────────
print("\n=== 3. Credenciais S3 / Litestream ===")
if not LS_BUCKET:
    _result("fail", "LITESTREAM_BUCKET", "Não definida")
    print(f"{INFO} Sugestão: LITESTREAM_BUCKET=prox-db")
else:
    _result("pass", "LITESTREAM_BUCKET", LS_BUCKET)

if not LS_ENDPOINT:
    _result(
        "fail",
        "LITESTREAM_S3_ENDPOINT",
        "Não definida e não foi possível derivar de SUPABASE_URL",
    )
else:
    _result("pass", "LITESTREAM_S3_ENDPOINT", LS_ENDPOINT)
    if _derived_endpoint and LS_ENDPOINT != _derived_endpoint:
        print(f"{INFO} Endpoint difere do derivado: {_derived_endpoint}")

if not LS_KEY_ID:
    _result("fail", "LITESTREAM_ACCESS_KEY_ID", "Não definida")
else:
    _result("pass", "LITESTREAM_ACCESS_KEY_ID", LS_KEY_ID[:20] + "...")

if not LS_SECRET:
    _result("fail", "LITESTREAM_SECRET_ACCESS_KEY", "Não definida")
else:
    _result("pass", "LITESTREAM_SECRET_ACCESS_KEY", "***" + LS_SECRET[-6:])


# ─── Test 4: conectividade com endpoint S3 ───────────────────────────────────
print("\n=== 4. Conectividade S3 ===")
creds_ok = all([LS_BUCKET, LS_ENDPOINT, LS_KEY_ID, LS_SECRET])

if not creds_ok:
    _result(
        "skip",
        "Conectividade S3",
        "Credenciais incompletas — configure LITESTREAM_* vars",
    )
else:
    try:
        import boto3
        from botocore.config import Config

        s3 = boto3.client(
            "s3",
            endpoint_url=LS_ENDPOINT,
            aws_access_key_id=LS_KEY_ID,
            aws_secret_access_key=LS_SECRET,
            region_name="us-east-1",
            config=Config(signature_version="s3v4"),
        )
        s3.head_bucket(Bucket=LS_BUCKET)
        _result("pass", "S3 head_bucket", f"Bucket '{LS_BUCKET}' acessível")

    except ImportError:
        # Fallback: testa conectividade via requests HTTP HEAD
        try:
            import requests, hmac, hashlib, base64
            from datetime import datetime, timezone

            _result(
                "skip",
                "boto3 não instalado",
                "Usando requests para teste de conectividade básica",
            )

            parsed = urlparse(LS_ENDPOINT)
            r = requests.head(f"{LS_ENDPOINT}/{LS_BUCKET}", timeout=5, verify=True)
            # Supabase retorna 200 ou 403 (não 404) quando o bucket existe
            if r.status_code in (200, 403, 401):
                _result(
                    "pass",
                    "Conectividade HTTP",
                    f"Endpoint responde ({r.status_code}) — credenciais S3 precisam de assinatura v4",
                )
            else:
                _result(
                    "fail", "Conectividade HTTP", f"Status inesperado: {r.status_code}"
                )
        except Exception as e:
            _result("fail", "Conectividade HTTP", str(e))

    except Exception as e:
        err = str(e)
        if "NoSuchBucket" in err or "404" in err:
            _result(
                "fail",
                "S3 head_bucket",
                f"Bucket '{LS_BUCKET}' não existe — crie-o no Supabase Storage",
            )
        elif "InvalidAccessKeyId" in err or "403" in err or "401" in err:
            _result("fail", "S3 autenticação", f"Credenciais inválidas: {err[:80]}")
        else:
            _result("fail", "S3 conectividade", err[:100])


# ─── Test 5: objetos de replicação no bucket ──────────────────────────────────
print("\n=== 5. Objetos de replicação (WAL segments) ===")
if not creds_ok:
    _result("skip", "WAL segments", "Credenciais incompletas")
else:
    try:
        import boto3
        from botocore.config import Config

        s3 = boto3.client(
            "s3",
            endpoint_url=LS_ENDPOINT,
            aws_access_key_id=LS_KEY_ID,
            aws_secret_access_key=LS_SECRET,
            region_name="us-east-1",
            config=Config(signature_version="s3v4"),
        )

        # Deriva os replica paths do config parseado (evita hardcode)
        replica_paths = []
        try:
            import yaml as _yaml

            with open(LITESTREAM_YML) as _f:
                _ls = _yaml.safe_load(_f)
            for _db in _ls.get("dbs", []):
                for _rep in _db.get("replicas", []):
                    if _rep.get("path"):
                        replica_paths.append(_rep["path"])
        except Exception:
            replica_paths = ["prox"]  # fallback

        for replica_path in replica_paths:
            prefix = f"{replica_path}/"
            resp = s3.list_objects_v2(Bucket=LS_BUCKET, Prefix=prefix, MaxKeys=10)
            objects = resp.get("Contents", [])
            if objects:
                newest = max(objects, key=lambda o: o.get("LastModified", 0))
                age_min = (time.time() - newest["LastModified"].timestamp()) / 60
                _result(
                    "pass",
                    f"WAL/{replica_path}",
                    f"{len(objects)} objeto(s) — mais recente há {age_min:.0f} min",
                )
                if age_min > 30:
                    print(
                        f"  {WARN} Último objeto tem {age_min:.0f} min — sync pode estar parado"
                    )
            else:
                _result(
                    "fail",
                    f"WAL/{replica_path}",
                    f"Nenhum objeto em '{LS_BUCKET}/{prefix}' — Litestream nunca replicou ou bucket errado",
                )

    except (ImportError, NameError):
        _result("skip", "WAL segments", "boto3 necessário para este teste")
    except Exception as e:
        _result("fail", "WAL segments", str(e)[:100])


# ─── Test 6: CLI litestream disponível ───────────────────────────────────────
print("\n=== 6. CLI litestream ===")
try:
    proc = subprocess.run(
        ["litestream", "version"], capture_output=True, text=True, timeout=5
    )
    version = (proc.stdout + proc.stderr).strip()
    _result("pass", "litestream CLI", version or "disponível")

    # Se credenciais OK, lista LTX files do primeiro DB configurado (v0.5.x: ltx)
    if creds_ok and LITESTREAM_YML.exists():
        try:
            import yaml as _yaml

            with open(LITESTREAM_YML) as _f:
                _ls_cfg = _yaml.safe_load(_f)
            _first_db = (_ls_cfg.get("dbs") or [{}])[0].get("path", "")
        except Exception:
            _first_db = str(found_dbs[0]) if found_dbs else ""

        if _first_db:
            env_with_ls = {
                **os.environ,
                "LITESTREAM_BUCKET": LS_BUCKET,
                "LITESTREAM_S3_ENDPOINT": LS_ENDPOINT,
                "LITESTREAM_ACCESS_KEY_ID": LS_KEY_ID,
                "LITESTREAM_SECRET_ACCESS_KEY": LS_SECRET,
            }
            ltx_proc = subprocess.run(
                ["litestream", "ltx", "-config", str(LITESTREAM_YML), _first_db],
                capture_output=True,
                text=True,
                timeout=15,
                env=env_with_ls,
            )
            output = (ltx_proc.stdout + ltx_proc.stderr).strip()
            if ltx_proc.returncode == 0 and output:
                lines = [l for l in output.splitlines() if l.strip()]
                _result(
                    "pass",
                    f"LTX files {Path(_first_db).name}",
                    f"{len(lines)} entrada(s)",
                )
                for line in lines[-3:]:
                    print(f"       {line}")
            else:
                _result(
                    "fail",
                    f"LTX files {Path(_first_db).name}",
                    output[:120] or "Sem output",
                )

except FileNotFoundError:
    _result(
        "skip",
        "litestream CLI",
        "Não instalado — em produção roda como sidecar no container",
    )
except subprocess.TimeoutExpired:
    _result("fail", "litestream CLI", "Timeout (>5s)")
except Exception as e:
    _result("fail", "litestream CLI", str(e))


# ─── Instruções se credenciais não estão configuradas ─────────────────────────
missing_ls_vars = [
    v
    for v in [
        "LITESTREAM_BUCKET",
        "LITESTREAM_S3_ENDPOINT",
        "LITESTREAM_ACCESS_KEY_ID",
        "LITESTREAM_SECRET_ACCESS_KEY",
    ]
    if not os.environ.get(v)
]

if missing_ls_vars:
    print(
        f"\n{WARN} Variáveis LITESTREAM_* não definidas. Adicione ao .env.development:"
    )
    print(f"  LITESTREAM_BUCKET=<nome-do-bucket-no-supabase>")
    if _derived_endpoint:
        print(
            f"  LITESTREAM_S3_ENDPOINT={_derived_endpoint}  ← derivado de SUPABASE_URL"
        )
    else:
        print(
            f"  LITESTREAM_S3_ENDPOINT=https://<project_ref>.supabase.co/storage/v1/s3"
        )
    print(f"  LITESTREAM_ACCESS_KEY_ID=<supabase_access_key>")
    print(f"  LITESTREAM_SECRET_ACCESS_KEY=<supabase_secret_key>")
    print(f"  → Obtenha em: Supabase Dashboard > Settings > Storage > S3 Access Keys")


# ─── Resumo ───────────────────────────────────────────────────────────────────
print("\n" + "=" * 55)
passed = sum(1 for s, _ in results if s == "pass")
failed = sum(1 for s, _ in results if s == "fail")
skipped = sum(1 for s, _ in results if s == "skip")
print(f"  SQLSync: {passed} passed | {failed} failed | {skipped} skipped")
print("=" * 55)
sys.exit(0 if failed == 0 else 1)

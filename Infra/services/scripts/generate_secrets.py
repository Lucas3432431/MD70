#!/usr/bin/env python3
"""
Gera os arquivos de secrets usados pelos containers a partir de um .env:

  secrets/app.secrets       → backend   (todas as variáveis + overrides de container)
  secrets/frontend.secrets  → frontend  (apenas variáveis públicas/de build do frontend)
  secrets/redis.conf        → redis     (porta + senha vindas de REDIS_INTERNAL_PORT/REDIS_PASSWORD)

Os caminhos são relativos a Infra/services (onde ficam os docker-compose*.yml).

Uso (a partir de Infra/services):
  python3 scripts/generate_secrets.py                        # usa .env.development
  python3 scripts/generate_secrets.py --env .env.production  # usa .env.production
"""

import sys
import argparse
from pathlib import Path
from urllib.parse import quote

# Overrides específicos de container — sobrescrevem o .env de origem
CONTAINER_OVERRIDES = {
    "IS_CONTAINERED": "true",
    "REDIS_HOST": "redis",
    "CHOKIDAR_USEPOLLING": "true",
    "WATCHPACK_POLLING": "true",
    "SANDBOX_URL": "http://sandbox:8101",
    "BROWSER_SERVICE_URL": "http://browser:8102",
}

# Chaves não-VITE_ que o frontend precisa; o resto (senhas, chaves de API) fica só no backend
FRONTEND_KEYS = {
    "ENV",
    "ENVIRONMENT",
    "IS_CONTAINERED",
    "HOT_RELOAD_ENABLED",
    "FRONTEND_PORT",
    "PUBLIC_URL",
    "CHOKIDAR_USEPOLLING",
    "WATCHPACK_POLLING",
}


def parse_env_file(path: Path) -> dict:
    result = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key, value = key.strip(), value.strip()
            if not (value.startswith('"') or value.startswith("'")):
                if "#" in value:
                    value = value.split("#")[0].strip()
            if len(value) >= 2 and (
                (value.startswith('"') and value.endswith('"')) or
                (value.startswith("'") and value.endswith("'"))
            ):
                value = value[1:-1]
            result[key] = value
    return result


def write_secrets_file(path: Path, env: dict, source_name: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("# ================================================================\n")
        f.write("# Arquivo de secrets gerado automaticamente — NÃO COMMITAR\n")
        f.write(f"# Gerado de {source_name} com overrides de container\n")
        f.write("# ================================================================\n\n")
        for key, value in env.items():
            needs_quotes = any(c in value for c in [" ", "#"])
            if needs_quotes:
                escaped = value.replace('"', '\\"')
                f.write(f'{key}="{escaped}"\n')
            else:
                f.write(f"{key}={value}\n")


def write_redis_conf(path: Path, password: str, port: str, source_name: str) -> None:
    escaped = password.replace("\\", "\\\\").replace('"', '\\"')
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("# Gerado automaticamente — NÃO COMMITAR\n")
        f.write(f"# Gerado de {source_name} (REDIS_PASSWORD / REDIS_INTERNAL_PORT)\n\n")
        f.write("bind 0.0.0.0\n")
        f.write(f"port {port}\n")
        f.write("protected-mode yes\n")
        f.write(f'requirepass "{escaped}"\n')
        f.write("dir /data\n")
        f.write("appendonly yes\n")


def main():
    # Console do Windows (cp1252) não codifica os emojis das mensagens
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser()
    parser.add_argument("--env", default=None, help="Caminho do arquivo .env a usar (relativo a Infra/services)")
    args = parser.parse_args()

    services_root = Path(__file__).resolve().parent.parent
    env_file = services_root / (args.env if args.env else ".env.development")
    secrets_dir = services_root / "secrets"

    if not env_file.exists():
        print(f"❌ {env_file} não encontrado", file=sys.stderr)
        sys.exit(1)

    env = parse_env_file(env_file)

    redis_password = env.get("REDIS_PASSWORD", "")
    if not redis_password:
        print(f"❌ REDIS_PASSWORD não definido em {env_file.name}", file=sys.stderr)
        sys.exit(1)
    redis_internal_port = env.get("REDIS_INTERNAL_PORT", "6379")

    env.update(CONTAINER_OVERRIDES)
    env["REDIS_PORT"] = redis_internal_port

    # Garantir que ENVIRONMENT sempre bate com ENV (safety net)
    if "ENVIRONMENT" not in env:
        env["ENVIRONMENT"] = env.get("ENV", "development")

    # Derivar REDIS_URL dos componentes para não expor senha como env var
    env["REDIS_URL"] = f"redis://:{quote(redis_password, safe='')}@redis:{redis_internal_port}"

    secrets_dir.mkdir(exist_ok=True)

    app_file = secrets_dir / "app.secrets"
    write_secrets_file(app_file, env, env_file.name)

    frontend_env = {k: v for k, v in env.items() if k.startswith("VITE_") or k in FRONTEND_KEYS}
    frontend_file = secrets_dir / "frontend.secrets"
    write_secrets_file(frontend_file, frontend_env, env_file.name)

    redis_file = secrets_dir / "redis.conf"
    write_redis_conf(redis_file, redis_password, redis_internal_port, env_file.name)

    for path in (app_file, frontend_file, redis_file):
        path.chmod(0o644)

    print(f"✅ {app_file} gerado de {env_file.name} ({len(env)} variáveis)")
    print(f"✅ {frontend_file} gerado ({len(frontend_env)} variáveis)")
    print(f"✅ {redis_file} gerado (porta {redis_internal_port})")
    print(f"   ENVIRONMENT={env.get('ENVIRONMENT')}  VITE_HTTP_PROTOCOL={env.get('VITE_HTTP_PROTOCOL')}  PUBLIC_URL={env.get('PUBLIC_URL', '(não definido)')}")


if __name__ == "__main__":
    main()

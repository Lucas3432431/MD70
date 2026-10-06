#!/usr/bin/env python3
"""
Gera secrets/app.secrets para uso em containers.
Lê .env.development (padrão) ou arquivo especificado via --env, aplica overrides
de container e escreve em secrets/app.secrets.

Uso:
  python3 scripts/generate_secrets.py                        # usa .env.development
  python3 scripts/generate_secrets.py --env .env.production  # usa .env.production
"""

import sys
import argparse
from pathlib import Path

# Overrides específicos de container — sobrescrevem .env.development
CONTAINER_OVERRIDES = {
    "IS_CONTAINERED": "true",
    "REDIS_HOST": "redis",
    "REDIS_PORT": "6379",
    "CHOKIDAR_USEPOLLING": "true",
    "WATCHPACK_POLLING": "true",
    "SANDBOX_URL": "http://sandbox:8001",
    "BROWSER_SERVICE_URL": "http://browser:8002",
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


def write_secrets_file(path: Path, env: dict, source_name: str = ".env.development") -> None:
    with open(path, "w", encoding="utf-8") as f:
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", default=None, help="Caminho do arquivo .env a usar (relativo ao mvp root)")
    args = parser.parse_args()

    mvp_root = Path(__file__).parent.parent
    env_file = mvp_root / (args.env if args.env else ".env.development")
    secrets_dir = mvp_root / "secrets"
    secrets_file = secrets_dir / "app.secrets"

    if not env_file.exists():
        print(f"❌ {env_file} não encontrado", file=sys.stderr)
        sys.exit(1)

    secrets_dir.mkdir(exist_ok=True)

    env = parse_env_file(env_file)
    env.update(CONTAINER_OVERRIDES)

    # Garantir que ENVIRONMENT sempre bate com ENV (safety net)
    if "ENVIRONMENT" not in env:
        env["ENVIRONMENT"] = env.get("ENV", "development")

    # Derivar REDIS_URL dos componentes para não expor senha como env var
    redis_password = env.get("REDIS_PASSWORD", "")
    redis_internal_port = env.get("REDIS_INTERNAL_PORT", "6379")
    env["REDIS_URL"] = f"redis://:{redis_password}@redis:{redis_internal_port}"

    write_secrets_file(secrets_file, env, env_file.name)
    secrets_file.chmod(0o644)

    print(f"✅ {secrets_file} gerado de {env_file.name} ({len(env)} variáveis, permissões 644)")
    print(f"   ENVIRONMENT={env.get('ENVIRONMENT')}  VITE_HTTP_PROTOCOL={env.get('VITE_HTTP_PROTOCOL')}  PUBLIC_URL={env.get('PUBLIC_URL', '(não definido)')}")


if __name__ == "__main__":
    main()

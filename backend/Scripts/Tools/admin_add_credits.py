#!/usr/bin/env python3
"""
admin_add_credits.py — Adiciona créditos a um usuário via rota admin.

O token TOTP é enviado no header X-Admin-Token (nunca no body).

Uso:
  python Scripts/Tools/admin_add_credits.py \
    --env dev \
    --user_id "uuid-do-usuario" \
    --amount 1000 \
    --totp "123456"

  # Ou informando a URL diretamente:
  python Scripts/Tools/admin_add_credits.py \
    --base-url https://api.prox.app.br \
    --user_id "..." --amount 500 --totp "..."

  # Omitir --totp para digitar interativamente (oculto no terminal):
  python Scripts/Tools/admin_add_credits.py --env prod --user_id "..." --amount 100
"""

import argparse
import getpass
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    print("❌  Instale requests: pip install requests")
    sys.exit(1)


# ── Resolução de URL ──────────────────────────────────────────────────────────


def _resolve_base_url(env: str) -> str:
    """Lê PUBLIC_URL do .env correto e usa como base da API."""
    root = Path(__file__).parent.parent.parent.parent.parent  # App/mvp/
    candidates = {
        "dev": [root / ".env", root / ".env.development", root / ".env.dev"],
        "prod": [root / ".env.production", root / ".env.prod", root / ".env"],
    }
    env_key = env.lower()
    files = candidates.get(env_key, candidates["dev"])

    for env_file in files:
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("PUBLIC_URL=") and not line.startswith("#"):
                    value = line.split("=", 1)[1].strip().rstrip("/")
                    if value:
                        return value

    # Fallback por ambiente
    if env_key == "prod":
        print("⚠️   PUBLIC_URL não encontrada no .env de produção. Informe --base-url.")
        sys.exit(1)

    return "http://localhost:8081"


# ── Main ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Adiciona créditos a um usuário via rota admin TOTP.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--env",
        choices=["dev", "prod"],
        default="dev",
        help="Ambiente (lê PUBLIC_URL do .env correspondente). Padrão: dev",
    )
    group.add_argument(
        "--base-url",
        metavar="URL",
        help="URL base da API (ex: https://api.prox.app.br). Sobrepõe --env.",
    )
    parser.add_argument("--user_id", required=True, help="ID do usuário")
    parser.add_argument(
        "--amount", required=True, type=float, help="Créditos a adicionar"
    )
    parser.add_argument(
        "--totp",
        default=None,
        help="Token TOTP de 6 dígitos. Se omitido, será solicitado de forma oculta.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=15,
        help="Timeout da requisição em segundos. Padrão: 15",
    )

    args = parser.parse_args()

    # Resolve base URL
    base_url = (
        args.base_url.rstrip("/") if args.base_url else _resolve_base_url(args.env)
    )
    endpoint = f"{base_url}/api/admin/add_credits"

    # TOTP — interativo se não passado
    totp = args.totp
    if not totp:
        totp = getpass.getpass("🔐  TOTP (6 dígitos): ").strip()
    if len(totp) != 6 or not totp.isdigit():
        print("❌  TOTP deve ter exatamente 6 dígitos numéricos.")
        sys.exit(1)

    payload = {
        "user_id": args.user_id,
        "amount": args.amount,
    }

    print(f"\n🌐  Endpoint : {endpoint}")
    print(f"👤  user_id  : {args.user_id}")
    print(f"💰  amount   : {args.amount}")
    print()

    try:
        resp = requests.post(
            endpoint,
            json=payload,
            headers={"X-Admin-Token": totp},
            timeout=args.timeout,
        )
    except requests.exceptions.ConnectionError:
        print(f"❌  Não foi possível conectar em {endpoint}")
        sys.exit(1)
    except requests.exceptions.Timeout:
        print(f"❌  Timeout após {args.timeout}s")
        sys.exit(1)

    if resp.status_code == 200:
        data = resp.json()
        print("✅  Créditos adicionados com sucesso!")
        print(f"    Saldo anterior : {data.get('balance_before', '?'):.6f}")
        print(f"    Adicionado     : +{data.get('amount_added', '?'):.6f}")
        print(f"    Saldo atual    : {data.get('balance_after', '?'):.6f}")
    elif resp.status_code == 401:
        print("❌  TOTP inválido ou expirado.")
        sys.exit(1)
    elif resp.status_code == 404:
        print(f"❌  Usuário não encontrado: {args.user_id}")
        sys.exit(1)
    else:
        print(f"❌  Erro {resp.status_code}: {resp.text}")
        sys.exit(1)


if __name__ == "__main__":
    main()

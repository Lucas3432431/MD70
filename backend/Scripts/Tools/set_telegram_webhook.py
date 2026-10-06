#!/usr/bin/env python3
"""
set_telegram_webhook.py
Registra (ou remove) o webhook do bot MD70 OmniChannel no Telegram.

Lê OMNI_TELEGRAM_BOT_TOKEN e PUBLIC_URL do .env.development automaticamente.

Uso:
    cd App/mvp/services/backend
    python Scripts/Tools/set_telegram_webhook.py            # registra
    python Scripts/Tools/set_telegram_webhook.py --remove   # remove webhook
    python Scripts/Tools/set_telegram_webhook.py --info     # mostra webhook atual
"""

import sys
import os
import argparse
import urllib.request
import urllib.error
import json
from pathlib import Path


# ── Carrega .env.development ──────────────────────────────────────────────────


def load_env(env_file: Path) -> dict:
    env = {}
    if not env_file.exists():
        return env
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


REPO_ROOT = Path(__file__).resolve().parents[4]  # …/MD70/App/mvp
ENV_FILE = REPO_ROOT / ".env.development"
env = load_env(ENV_FILE)

BOT_TOKEN = os.environ.get("OMNI_TELEGRAM_BOT_TOKEN") or env.get(
    "OMNI_TELEGRAM_BOT_TOKEN", ""
)
PUBLIC_URL = os.environ.get("PUBLIC_URL") or env.get("PUBLIC_URL", "")
WEBHOOK_PATH = "/webhook/omnichannel/telegram"


# ── Helpers ───────────────────────────────────────────────────────────────────


def tg(method: str, payload: dict | None = None) -> dict:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    data = json.dumps(payload).encode() if payload else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(
        url, data=data, headers=headers, method="POST" if data else "GET"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())


def validate() -> bool:
    ok = True
    if not BOT_TOKEN:
        print("✖  OMNI_TELEGRAM_BOT_TOKEN não encontrado.")
        print(f"   Defina em {ENV_FILE} ou exporte a variável de ambiente.")
        ok = False
    if not PUBLIC_URL:
        print("✖  PUBLIC_URL não encontrado.")
        print(f"   Defina em {ENV_FILE} (ex: https://seu-tunnel.trycloudflare.com)")
        ok = False
    return ok


# ── Ações ─────────────────────────────────────────────────────────────────────


def show_info():
    result = tg("getWebhookInfo")
    info = result.get("result", {})
    print("\n── Webhook atual ────────────────────────────────")
    print(f"  URL             : {info.get('url') or '(nenhum)'}")
    print(f"  Pending updates : {info.get('pending_update_count', 0)}")
    print(f"  Last error      : {info.get('last_error_message') or '–'}")
    print(f"  Last error at   : {info.get('last_error_date') or '–'}")
    print("─────────────────────────────────────────────────\n")


def set_webhook():
    webhook_url = PUBLIC_URL.rstrip("/") + WEBHOOK_PATH
    print(f"\n▶  Registrando webhook do bot @prox_bot")
    print(f"   URL: {webhook_url}\n")

    result = tg(
        "setWebhook",
        {
            "url": webhook_url,
            "allowed_updates": ["message", "callback_query"],
            "drop_pending_updates": True,
        },
    )

    if result.get("ok"):
        print(f"✔  Webhook registrado com sucesso!")
        print(f"   {result.get('description', '')}")
    else:
        print(f"✖  Falha ao registrar webhook:")
        print(f"   {result.get('description') or result}")
        sys.exit(1)

    show_info()


def remove_webhook():
    print("\n▶  Removendo webhook...")
    result = tg("deleteWebhook", {"drop_pending_updates": True})
    if result.get("ok"):
        print("✔  Webhook removido.")
    else:
        print(f"✖  {result.get('description') or result}")
        sys.exit(1)


# ── Main ──────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Gerencia o webhook do MD70 OmniChannel Telegram"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--remove", action="store_true", help="Remove o webhook atual")
    group.add_argument(
        "--info", action="store_true", help="Exibe informações do webhook atual"
    )
    args = parser.parse_args()

    if not validate():
        sys.exit(1)

    if args.info:
        show_info()
    elif args.remove:
        remove_webhook()
    else:
        set_webhook()


if __name__ == "__main__":
    main()

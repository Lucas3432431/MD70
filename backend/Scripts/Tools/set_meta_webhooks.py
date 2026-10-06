"""
Registra/verifica webhooks Meta (WhatsApp + Instagram) para o OmniChannel MD70.

Uso:
  python Scripts/Tools/set_meta_webhooks.py               # verifica status atual
  python Scripts/Tools/set_meta_webhooks.py --register    # registra ambos webhooks
  python Scripts/Tools/set_meta_webhooks.py --whatsapp    # só WhatsApp
  python Scripts/Tools/set_meta_webhooks.py --instagram   # só Instagram

Pré-requisitos no .env.development:
  WHATSAPP_ACCESS_TOKEN      = token Meta com permissão whatsapp_business_messaging
  WHATSAPP_PHONE_NUMBER_ID   = Phone Number ID (painel Meta → WhatsApp → API Setup)
  INSTAGRAM_PAGE_ACCESS_TOKEN= token Meta com permissão instagram_manage_messages
  OMNI_VERIFY_TOKEN          = token de verificação (mesmo valor no painel Meta)
  PUBLIC_URL                 = URL pública do servidor
"""

import argparse
import sys
import requests
from pathlib import Path
from dotenv import dotenv_values

# ── Carrega .env.development ────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[4]
env = dotenv_values(REPO_ROOT / ".env.development")


def _get(key: str, required: bool = False) -> str:
    val = env.get(key, "").strip()
    if required and not val:
        print(f"  ✗  {key} não configurado no .env.development")
        sys.exit(1)
    return val


PUBLIC_URL = _get("PUBLIC_URL", required=True).rstrip("/")
VERIFY_TOKEN = _get("OMNI_VERIFY_TOKEN") or "prox_dev_token"
WA_TOKEN = _get("WHATSAPP_ACCESS_TOKEN")
WA_PHONE_ID = _get("WHATSAPP_PHONE_NUMBER_ID")
IG_TOKEN = _get("INSTAGRAM_PAGE_ACCESS_TOKEN")

GRAPH_API = "https://graph.facebook.com/v19.0"
WA_WEBHOOK_URL = f"{PUBLIC_URL}/webhook/omnichannel/whatsapp"
IG_WEBHOOK_URL = f"{PUBLIC_URL}/webhook/omnichannel/instagram"


# ── Helpers ─────────────────────────────────────────────────────────────────────


def _print_header(title: str):
    print(f"\n── {title} {'─' * (50 - len(title))}")


def _test_verify_endpoint(provider: str):
    """Testa se o nosso endpoint de verificação responde corretamente."""
    url = f"{PUBLIC_URL}/webhook/omnichannel/{provider}"
    params = {
        "hub.mode": "subscribe",
        "hub.verify_token": VERIFY_TOKEN,
        "hub.challenge": "TEST_CHALLENGE_12345",
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code == 200 and resp.text.strip() == "TEST_CHALLENGE_12345":
            print(
                f"  ✔  Endpoint /webhook/omnichannel/{provider} respondeu ao challenge corretamente"
            )
            return True
        else:
            print(
                f"  ✗  Endpoint /webhook/omnichannel/{provider} retornou {resp.status_code}: {resp.text[:200]}"
            )
            return False
    except Exception as e:
        print(f"  ✗  Falha ao testar endpoint: {e}")
        return False


def register_whatsapp():
    _print_header("WhatsApp Business Webhook")

    if not WA_TOKEN:
        print("  ✗  WHATSAPP_ACCESS_TOKEN não configurado")
        return False
    if not WA_PHONE_ID:
        print("  ✗  WHATSAPP_PHONE_NUMBER_ID não configurado")
        print(
            "     → Encontre em: Meta for Developers → App → WhatsApp → API Setup → Phone Number ID"
        )
        return False

    # 1. Testa nosso endpoint local
    print(f"  Testando endpoint: {WA_WEBHOOK_URL}")
    endpoint_ok = _test_verify_endpoint("whatsapp")

    if not endpoint_ok:
        print(
            "  ⚠  Endpoint não está respondendo corretamente. Verifique se o servidor está acessível."
        )
        print(f"     PUBLIC_URL = {PUBLIC_URL}")

    # 2. Registra webhook na Meta Graph API via Phone Number
    print(f"\n  Registrando webhook no Meta para número {WA_PHONE_ID}...")
    resp = requests.post(
        f"{GRAPH_API}/{WA_PHONE_ID}/subscriptions",
        params={"access_token": WA_TOKEN},
        json={
            "object": "whatsapp_business_account",
            "callback_url": WA_WEBHOOK_URL,
            "verify_token": VERIFY_TOKEN,
            "fields": ["messages"],
        },
        timeout=15,
    )

    if resp.status_code == 200 and resp.json().get("success"):
        print(f"  ✔  Webhook WhatsApp registrado com sucesso!")
        print(f"     URL: {WA_WEBHOOK_URL}")
    else:
        data = resp.json()
        print(f"  ✗  Falha ao registrar via API: {resp.status_code}")
        print(f"     {data}")
        print()
        print("  📋  REGISTRO MANUAL (Meta for Developers):")
        print(f"     1. Acesse: https://developers.facebook.com/apps/")
        print(f"     2. Selecione seu app → WhatsApp → Configuration → Webhooks")
        print(f"     3. Callback URL:  {WA_WEBHOOK_URL}")
        print(f"     4. Verify Token:  {VERIFY_TOKEN}")
        print(f"     5. Ative o campo: messages")
    return True


def register_instagram():
    _print_header("Instagram Webhook")

    if not IG_TOKEN:
        print("  ✗  INSTAGRAM_PAGE_ACCESS_TOKEN não configurado")
        return False

    # Descobre o Page ID / App ID a partir do token
    me_resp = requests.get(
        f"{GRAPH_API}/me",
        params={"access_token": IG_TOKEN, "fields": "id,name"},
        timeout=10,
    )
    if me_resp.status_code != 200:
        print(f"  ✗  Token inválido ou sem permissão: {me_resp.json()}")
        return False

    me = me_resp.json()
    print(f"  Token válido para: {me.get('name', '?')} (id={me.get('id', '?')})")
    page_id = me.get("id")

    # 1. Testa nosso endpoint local
    print(f"  Testando endpoint: {IG_WEBHOOK_URL}")
    endpoint_ok = _test_verify_endpoint("instagram")

    if not endpoint_ok:
        print("  ⚠  Endpoint não está respondendo corretamente.")

    # 2. Registra via Graph API (Page subscription)
    print(f"\n  Registrando webhook no Instagram para page {page_id}...")
    resp = requests.post(
        f"{GRAPH_API}/{page_id}/subscribed_apps",
        params={"access_token": IG_TOKEN},
        json={"subscribed_fields": ["messages", "messaging_postbacks"]},
        timeout=15,
    )

    if resp.status_code == 200 and resp.json().get("success"):
        print(f"  ✔  Webhook Instagram registrado com sucesso!")
        print(f"     URL: {IG_WEBHOOK_URL}")
    else:
        data = resp.json()
        print(f"  ✗  Falha via API: {resp.status_code} — {data}")
        print()
        print("  📋  REGISTRO MANUAL (Meta for Developers):")
        print(f"     1. Acesse: https://developers.facebook.com/apps/")
        print(f"     2. Selecione seu app → Instagram → Webhooks")
        print(f"     3. Callback URL:  {IG_WEBHOOK_URL}")
        print(f"     4. Verify Token:  {VERIFY_TOKEN}")
        print(f"     5. Ative os campos: messages, messaging_postbacks")

    return True


def show_status():
    _print_header("Status dos Webhooks Meta OmniChannel")
    print(f"  PUBLIC_URL     : {PUBLIC_URL}")
    print(f"  VERIFY_TOKEN   : {VERIFY_TOKEN}")
    print(f"  WA Token       : {'✔ configurado' if WA_TOKEN else '✗ vazio'}")
    print(f"  WA Phone ID    : {WA_PHONE_ID or '✗ vazio'}")
    print(f"  IG Token       : {'✔ configurado' if IG_TOKEN else '✗ vazio'}")
    print()
    print("  URLs dos webhooks:")
    print(f"    WhatsApp  → {WA_WEBHOOK_URL}")
    print(f"    Instagram → {IG_WEBHOOK_URL}")
    print()
    print("  Testando endpoints locais...")
    _test_verify_endpoint("whatsapp")
    _test_verify_endpoint("instagram")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Registra webhooks Meta para MD70 OmniChannel"
    )
    parser.add_argument(
        "--register", action="store_true", help="Registra WhatsApp + Instagram"
    )
    parser.add_argument("--whatsapp", action="store_true", help="Registra só WhatsApp")
    parser.add_argument(
        "--instagram", action="store_true", help="Registra só Instagram"
    )
    args = parser.parse_args()

    if args.register:
        register_whatsapp()
        register_instagram()
    elif args.whatsapp:
        register_whatsapp()
    elif args.instagram:
        register_instagram()
    else:
        show_status()

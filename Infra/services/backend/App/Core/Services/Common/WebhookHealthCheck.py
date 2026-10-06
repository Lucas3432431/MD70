"""
WebhookHealthCheck - Verifica ngrok após app estar pronto
Aguarda 30 segundos antes de testar a conectividade com ngrok
Se falhar, deruba o container
"""

import asyncio
import requests
import sys
from App.Core.Logs import info, error, warning


async def check_webhook_health_after_startup(pagarme_webhook: str):
    """
    Aguarda 30 segundos para app estar pronto, depois verifica ngrok.
    Se falhar, deruba o container.

    Args:
        pagarme_webhook: URL do webhook do Pagarme (ngrok)
    """
    try:
        # Aguardar 30 segundos para app estar pronto
        info("[PAGARME_HC] Aguardando 30 segundos para app estar pronto...")
        await asyncio.sleep(30)

        info(f"[PAGARME_HC] Verificando ngrok: {pagarme_webhook}")

        # Fazer request
        response = requests.get(f"{pagarme_webhook}/api/health", timeout=5)

        if response.status_code == 200:
            info(f"[PAGARME_HC] ✓ Webhook acessível após startup: {pagarme_webhook}")
            return True
        elif response.status_code == 404:
            error(f"[PAGARME_HC] ✗ NGROK OFFLINE OU URL ERRADA: {pagarme_webhook}")
            error("[PAGARME_HC] Recebeu status 404 - ngrok não está rodando")
            error("[PAGARME_HC] Container será desligado!")
            sys.exit(1)
        else:
            error(
                f"[PAGARME_HC] ✗ Status inesperado {response.status_code}: {pagarme_webhook}"
            )
            error("[PAGARME_HC] Container será desligado!")
            sys.exit(1)

    except requests.exceptions.ConnectionError as e:
        error(f"[PAGARME_HC] ✗ NGROK INACESSÍVEL: {pagarme_webhook}")
        error(f"[PAGARME_HC] Erro: {e}")
        error("[PAGARME_HC] Para iniciar ngrok, execute: ngrok http 4001")
        error("[PAGARME_HC] Container será desligado!")
        sys.exit(1)
    except Exception as e:
        error(f"[PAGARME_HC] ✗ Erro ao verificar webhook: {e}")
        error("[PAGARME_HC] Container será desligado!")
        sys.exit(1)

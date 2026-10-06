"""
Script de Teste para o AdminEmailService
Valida se o envio de e-mails via SMTP do Google está funcionando.
"""

import os
import sys
from pathlib import Path

# Adicionar o diretório backend ao PYTHONPATH
backend_dir = Path(__file__).resolve().parent.parent.parent.parent
sys.path.append(str(backend_dir))

from App.Core.Services.AdminEmail import admin_email_service
from App.Core.Settings.Settings import (
    ADMIN_EMAIL,
    GOOGLE_REFRESH_TOKEN,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
)


def test_send_email():
    print("=== Testando AdminEmailService (Gmail + Telegram) ===")
    print(f"Admin Email: {ADMIN_EMAIL}")
    print(f"Gmail Token set: {'Sim' if GOOGLE_REFRESH_TOKEN else 'Não'}")
    print(f"Telegram Token set: {'Sim' if TELEGRAM_BOT_TOKEN else 'Não'}")
    print(f"Telegram Chat ID: {TELEGRAM_CHAT_ID}")

    if not ADMIN_EMAIL or not GOOGLE_REFRESH_TOKEN:
        print("❌ ERRO: Gmail não configurado.")

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ AVISO: Telegram não configurado.")

    subject = "TESTE MULTI-CANAL - MD70"
    message = "Este é um teste de alertas combinados: Gmail API + Telegram Bot!\nSe você recebeu em ambos, o sistema está blindado."

    print("\nEnviando e-mail de teste...")
    success = admin_email_service.send_critical_alert(subject, message)

    if success:
        print("✅ SUCESSO: O e-mail foi enviado via API!")
    else:
        print(
            "❌ FALHA: Não foi possível enviar o e-mail. Verifique os logs do backend."
        )


if __name__ == "__main__":
    test_send_email()

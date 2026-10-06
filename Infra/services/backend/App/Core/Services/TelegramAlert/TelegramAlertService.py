"""
TelegramAlertService - Serviço para envio de alertas críticos para o administrador via Telegram Bot.
"""

import requests
import json
from App.Core.Logs import debug, error, info
from App.Core.Settings.Settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


class TelegramAlertService:
    def __init__(self):
        self.token = TELEGRAM_BOT_TOKEN
        self.chat_id = TELEGRAM_CHAT_ID
        self.api_url = f"https://api.telegram.org/bot{self.token}/sendMessage"

    def send_critical_alert(self, subject: str, message: str):
        """Envia um alerta crítico via Telegram."""
        if not self.token or not self.chat_id:
            debug("[TelegramAlert] Token ou Chat ID não configurados")
            return False

        try:
            # Formatar mensagem amigável com emojis e HTML
            text = (
                f"<b>🚨 ALERTA CRÍTICO: {subject}</b>\n\n"
                f"<code>{message}</code>\n\n"
                f"📅 <i>MD70 Backend System</i>"
            )

            payload = {"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"}

            response = requests.post(self.api_url, json=payload, timeout=5)

            # Fire and forget: Não validamos o status_code para não travar ou poluir logs
            # se o chat_id estiver incorreto ou o bot bloqueado.
            debug(
                f"[TelegramAlert] Tentativa de envio concluída (Status: {response.status_code})"
            )
            return True

        except Exception as e:
            debug(f"[TelegramAlert] Erro silencioso ao enviar: {e}")
            return False


# Singleton instance
telegram_alert_service = TelegramAlertService()

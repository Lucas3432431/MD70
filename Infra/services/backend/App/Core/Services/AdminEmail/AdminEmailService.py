"""
AdminEmailService - Envio de e-mails transacionais e alertas críticos via Resend API.
"""

import httpx
from typing import List, Dict, Any

from App.Core.Logs import error, info
from App.Core.Settings.Settings import ADMIN_EMAIL, RESEND_API_KEY
from App.Core.Services.TelegramAlert import telegram_alert_service

_RESEND_URL = "https://api.resend.com/emails"
NOREPLY_FROM = "MD70 <no_reply@prox.dev.br>"
LUCAS_FROM = "Lucas · MD70 <lucas@prox.dev.br>"


class AdminEmailService:
    def send_email(
        self,
        to: str,
        subject: str,
        html_body: str,
        from_email: str = NOREPLY_FROM,
        attachments: List[Dict[str, Any]] | None = None,
    ) -> bool:
        if not RESEND_API_KEY:
            error("[Resend] RESEND_API_KEY não configurada")
            return False
        try:
            payload: Dict[str, Any] = {
                "from": from_email,
                "to": [to],
                "subject": subject,
                "html": html_body,
            }
            if attachments:
                payload["attachments"] = attachments
            resp = httpx.post(
                _RESEND_URL,
                headers={
                    "Authorization": f"Bearer {RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=15,
            )
            if resp.status_code in (200, 201):
                info(f"[Resend] E-mail enviado para {to}: {subject}")
                return True
            error(f"[Resend] Falha ao enviar para {to}: {resp.status_code} {resp.text}")
            return False
        except Exception as e:
            error(f"[Resend] Erro ao enviar e-mail para {to}: {e}")
            return False

    def send_critical_alert(self, subject: str, message: str) -> bool:
        if not ADMIN_EMAIL:
            error("[Resend] ADMIN_EMAIL não configurado")
            return False

        html = f"""
        <h3>Alerta Crítico do Sistema MD70</h3>
        <p><strong>Evento:</strong> {subject}</p>
        <p><strong>Detalhes:</strong></p>
        <pre style="background:#f4f4f4;padding:10px;border:1px solid #ddd;">{message}</pre>
        <p>Favor verificar imediatamente.</p>
        <hr>
        <p><small>E-mail automático enviado via Resend.</small></p>
        """

        ok = self.send_email(
            to=ADMIN_EMAIL,
            subject=f"🚨 CRITICAL ALERT: {subject}",
            html_body=html,
        )

        telegram_alert_service.send_critical_alert(subject, message)
        return ok


# Singleton instance
admin_email_service = AdminEmailService()

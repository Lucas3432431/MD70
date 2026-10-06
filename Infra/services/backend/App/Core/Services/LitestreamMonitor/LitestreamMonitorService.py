"""
LitestreamMonitorService — Monitor de replicação S3/Litestream.

Verifica periodicamente a conectividade com o endpoint S3 do Supabase.
Dispara alertas via Gmail + Telegram (via admin_email_service) quando
detecta falhas persistentes, e notifica recuperação quando o serviço volta.
"""

import asyncio
import os
from datetime import datetime

import httpx

from App.Core.Logs import error, info, warning
from App.Core.Services.AdminEmail import admin_email_service
from App.Core.Settings import DEV_ENV

_CHECK_INTERVAL_S = 60  # Verificação a cada 60 s
_FAILURE_THRESHOLD = 3  # Alertar após N falhas consecutivas
_ALERT_COOLDOWN_MIN = 30  # Mínimo de 30 min entre alertas do mesmo incidente
_RETRY_ATTEMPTS = 2  # Tentativas por ciclo de check (absorve blips de DNS)
_RETRY_DELAY_S = 5  # Pausa entre tentativas dentro do mesmo ciclo

_ERROR_REASONS: dict[int, str] = {
    540: "Projeto Supabase pausado — acesse o dashboard e reative o projeto",
    530: "Origem inacessível (Cloudflare 530) — endpoint S3 offline",
    544: "Timeout de conexão reportado pelo gateway Supabase (544)",
    403: "Credenciais S3 inválidas ou expiradas (403 Forbidden)",
    404: "Bucket ou path S3 não encontrado (404 Not Found)",
    500: "Erro interno no servidor S3 (500 Internal Server Error)",
    502: "Gateway inválido no endpoint S3 (502 Bad Gateway)",
    503: "Serviço S3 indisponível (503 Service Unavailable)",
}


class LitestreamMonitorService:
    def __init__(self):
        self._endpoint = os.environ.get("LITESTREAM_S3_ENDPOINT", "").rstrip("/")
        self._bucket = os.environ.get("LITESTREAM_BUCKET", "")
        self._enabled = os.environ.get("LITESTREAM_ENABLED", "false").lower() == "true"

        self._consecutive_failures = 0
        self._incident_active = False
        self._last_alert_at: datetime | None = None
        self._task: asyncio.Task | None = None

    def start(self):
        if not self._enabled or not self._endpoint:
            info(
                "[LitestreamMonitor] Desabilitado ou endpoint não configurado — pulando"
            )
            return
        self._task = asyncio.create_task(self._run())
        info(
            f"[LitestreamMonitor] Monitor S3 iniciado — verificando a cada {_CHECK_INTERVAL_S}s"
        )

    async def _run(self):
        while True:
            await asyncio.sleep(_CHECK_INTERVAL_S)
            try:
                await self._check()
            except Exception as e:
                error(
                    f"[LitestreamMonitor] Erro inesperado no loop de monitoramento: {e}"
                )

    async def _check(self):
        status_code: int | None = None
        error_desc = "timeout"

        for attempt in range(1, _RETRY_ATTEMPTS + 1):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(self._endpoint)
                    status_code = resp.status_code
                    # Qualquer código abaixo de 500 indica que o endpoint responde
                    # (mesmo 4xx de auth mostra que o serviço está de pé)
                    if status_code < 500:
                        await self._on_healthy()
                        return
                    error_desc = f"HTTP {status_code}"
                    break  # erro HTTP definitivo — não adianta retentar
            except httpx.TimeoutException:
                error_desc = "timeout de conexão"
            except Exception as exc:
                error_desc = str(exc)[:120]

            if attempt < _RETRY_ATTEMPTS:
                await asyncio.sleep(_RETRY_DELAY_S)

        await self._on_failure(status_code, error_desc)

    async def _on_healthy(self):
        if self._incident_active:
            info("[LitestreamMonitor] ✅ S3 recuperado — replicação restaurada")
            if not DEV_ENV:
                admin_email_service.send_critical_alert(
                    "S3 Replicação RECUPERADA",
                    (
                        f"O endpoint S3 do Supabase voltou ao normal.\n"
                        f"Endpoint: {self._endpoint}\n"
                        f"Bucket: {self._bucket}\n"
                        f"Falhas consecutivas anteriores: {self._consecutive_failures}"
                    ),
                )
        self._consecutive_failures = 0
        self._incident_active = False
        self._last_alert_at = None

    async def _on_failure(self, status_code: int | None, error_desc: str):
        self._consecutive_failures += 1
        warning(
            f"[LitestreamMonitor] Falha #{self._consecutive_failures} — {error_desc}"
        )

        if self._consecutive_failures < _FAILURE_THRESHOLD:
            return

        now = datetime.utcnow()
        if self._last_alert_at:
            elapsed_min = (now - self._last_alert_at).total_seconds() / 60
            if elapsed_min < _ALERT_COOLDOWN_MIN:
                return

        reason = _ERROR_REASONS.get(
            status_code or 0,
            f"Erro desconhecido: {error_desc}",
        )

        subject = "Falha Crítica de Replicação S3 — Litestream"
        message = (
            f"Detectadas {self._consecutive_failures} falhas consecutivas "
            f"na replicação do banco de dados para o S3.\n\n"
            f"Endpoint : {self._endpoint}\n"
            f"Bucket   : {self._bucket}\n"
            f"HTTP     : {status_code or 'N/A'}\n"
            f"Erro     : {error_desc}\n"
            f"Causa    : {reason}\n\n"
            f"O banco LOCAL está íntegro, mas NÃO está sendo replicado para a cloud.\n"
            f"Em caso de falha do servidor sem backup válido, dados podem ser perdidos."
        )

        error(
            f"[LitestreamMonitor] 🚨 Falha crítica de replicação: {status_code} — {reason}"
        )
        if not DEV_ENV:
            admin_email_service.send_critical_alert(subject, message)
        else:
            warning("[LitestreamMonitor] Alerta suprimido em ambiente de desenvolvimento")

        self._incident_active = True
        self._last_alert_at = now


litestream_monitor = LitestreamMonitorService()

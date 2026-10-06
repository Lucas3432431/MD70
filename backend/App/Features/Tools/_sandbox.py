"""
_sandbox.py — SandboxMixin
Terminal shell isolado por usuário (bash).

Fase 1: subprocess local com resource limits (fallback)
Fase 2: HTTP para serviço sandbox dedicado (SANDBOX_URL env var)

Tool args:
  shell: str  — comando bash (suporta pipes, &&, variáveis, python3, curl, etc.)
"""

import json
import logging
import os
import re
import resource
import subprocess
import uuid
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

# ── Constantes ────────────────────────────────────────────────────────────────

SANDBOX_TIMEOUT = 30  # segundos
MAX_STDOUT = 8000  # chars retornados ao LLM
MAX_STDERR = 2000

# URL do serviço sandbox dedicado (Fase 2). Vazio = usa Fase 1.
SANDBOX_URL = os.environ.get("SANDBOX_URL", "").rstrip("/")

# Egress proxy para subprocessos da Fase 1 (fallback local).
# Na Fase 2, o proxy é configurado dentro do container sandbox via env var.
_EGRESS_PROXY = os.environ.get("EGRESS_PROXY_URL", "").rstrip("/")

# Env mínimo — sem variáveis do backend (tokens, secrets, etc.)
_SAFE_ENV: dict[str, str] = {
    "PATH": "/usr/bin:/usr/local/bin:/bin",
    "HOME": "/tmp",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONIOENCODING": "utf-8",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "TERM": "xterm-256color",
    # Force subprocess HTTP/HTTPS through egress proxy (blocks RFC 1918).
    # Only active when EGRESS_PROXY_URL is set (Fase 1 fallback).
    **(
        {
            "http_proxy": _EGRESS_PROXY,
            "https_proxy": _EGRESS_PROXY,
            "HTTP_PROXY": _EGRESS_PROXY,
            "HTTPS_PROXY": _EGRESS_PROXY,
            "no_proxy": "localhost,127.0.0.1",
            "NO_PROXY": "localhost,127.0.0.1",
        }
        if _EGRESS_PROXY
        else {}
    ),
}

# ── Blacklist ─────────────────────────────────────────────────────────────────
# Tuplas (regex_pattern, label) — checados contra o comando completo (lowercase)

_BLACKLIST: list[tuple[str, str]] = [
    # Escalada de privilégio
    (r"\bsudo\b", "sudo"),
    (r"(?<!\w)su\s", "su"),
    # Deleção recursiva
    (r"\brm\s+.*-[a-z]*r[a-z]*", "rm -r"),
    (r"\brm\s+-[a-z]*f[a-z]*\s", "rm -f"),
    # Download de arquivos
    (r"\bwget\b", "wget"),
    # Gestão de pacotes
    (r"\bapt(-get)?\b", "apt"),
    (r"\byum\b|\bdnf\b|\bpacman\b|\bapk\b", "package manager"),
    (r"\bpip\s+install\b", "pip install"),
    (r"\bnpm\s+install\b", "npm install"),
    # Acesso remoto / backdoor
    (r"\bssh\b|\bscp\b|\bsftp\b|\btelnet\b|\bftp\b", "ssh/scp/sftp"),
    (r"\bnc\b|\bncat\b|\bnetcat\b", "netcat"),
    # Scanning de rede
    (r"\bnmap\b|\bmasscan\b", "nmap"),
    # Controle do sistema
    (
        r"\breboot\b|\bshutdown\b|\bhalt\b|\bpoweroff\b|\binit\s+[06]\b",
        "system shutdown",
    ),
    (r"\bkillall\b|\bpkill\b", "killall/pkill"),
    # Disco / filesystem
    (r"\bmkfs\b|\bfdisk\b|\bparted\b", "disk formatting"),
    (r"\bdd\s+if=", "dd"),
    (r"\bmount\b|\bumount\b", "mount"),
    # Permissões
    (r"\bchown\b", "chown"),
    (r"\bchmod\b", "chmod"),
    # Kernel / módulos
    (r"\binsmod\b|\bmodprobe\b|\brmmod\b", "kernel modules"),
    (r"\bcrontab\b", "crontab"),
    # Configuração de rede
    (r"\biptables\b|\bnftables\b", "iptables"),
    (
        r"\bip\s+(link|addr|route|rule|neigh|tunnel|netns|maddr|mroute|monitor|xfrm)\b",
        "ip config",
    ),
    # ── IPs locais/privados — qualquer contexto (raw socket, etc.) ───────────
    (r"\blocalhost\b", "localhost"),
    (r"\b127\.\d+\.\d+\.\d+\b", "127.x loopback"),
    (r"\b::1\b", "IPv6 loopback"),
    (r"\b0\.0\.0\.0\b", "0.0.0.0"),
    (r"\b10\.\d+\.\d+\.\d+\b", "10.x private network"),
    (r"\b192\.168\.\d+\.\d+\b", "192.168.x private network"),
    (r"\b172\.(1[6-9]|2\d|3[01])\.\d+\.\d+\b", "172.16-31.x private network"),
    (r"\b169\.254\.\d+\.\d+\b", "169.254.x link-local"),
    (r"file://", "file://"),
    # ── Python sem acesso à rede ─────────────────────────────────────────────
    (
        r"\bimport\s+(urllib|requests|socket|httpx|aiohttp|http)\b",
        "python: módulo de rede bloqueado",
    ),
    (
        r"\bfrom\s+(urllib|requests|socket|httpx|aiohttp|http)\b",
        "python: módulo de rede bloqueado",
    ),
    (
        r"__import__\s*\(\s*['\"](?:urllib|requests|socket|httpx|aiohttp|http)",
        "python: módulo de rede bloqueado",
    ),
    # ── curl — flags proibidas (defesa em profundidade + whitelist) ───────────
    (r"\bcurl\b[^#\n]*--resolve\b", "curl --resolve"),
    (r"\bcurl\b[^#\n]*(\s-x\s|--proxy\b)", "curl proxy flag"),
    (
        r"\bcurl\b[^#\n]*\|\s*(ba?sh|python3?|node|perl|ruby)\b",
        "curl pipe to interpreter",
    ),
]

# ── Whitelist curl: apenas HTTPS para FQDNs públicos ─────────────────────────

_FQDN_RE = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$"
)
_INTERNAL_TLDS = frozenset(
    {
        "local",
        "internal",
        "localhost",
        "localdomain",
        "lan",
        "home",
        "corp",
        "intranet",
    }
)


def _check_curl_whitelist(command: str) -> Optional[str]:
    """Se curl presente, exige HTTPS + FQDN público. Qualquer outra coisa é bloqueada."""
    if not re.search(r"\bcurl\b", command, re.IGNORECASE):
        return None

    urls = re.findall(r"(?i)(https?://[^\s'\"<>|&;`\\]+)", command)

    if not urls:
        return "curl requer URL com https:// explícito"

    for raw_url in urls:
        parsed = urlparse(raw_url.rstrip("'\",.)"))
        if parsed.scheme != "https":
            return f"curl requer HTTPS — recebido: {parsed.scheme}://"
        host = (parsed.hostname or "").rstrip(".")
        if not host:
            return "curl: host não identificado na URL"
        if not _FQDN_RE.match(host):
            return f"curl: '{host}' não é um domínio válido (IPs e hostnames simples não são permitidos)"
        tld = host.rsplit(".", 1)[-1].lower()
        if tld in _INTERNAL_TLDS:
            return f"curl: TLD '.{tld}' é reservado para redes internas"

    return None


def _check_blacklist(command: str) -> Optional[str]:
    """Retorna o label do padrão bloqueado, ou None se permitido."""
    lower = command.lower()
    for pattern, label in _BLACKLIST:
        if re.search(pattern, lower):
            return label
    return _check_curl_whitelist(command)


# ── Mixin ─────────────────────────────────────────────────────────────────────


class SandboxMixin:
    """Tool `terminal` — executa comandos bash em sandbox isolado por usuário."""

    def _execute_terminal(self, args: dict) -> str:
        command = (
            args.get("shell") or args.get("command") or args.get("code") or ""
        ).strip()

        if not command:
            return _err("Nenhum comando fornecido.")

        blocked = _check_blacklist(command)
        if blocked:
            return _err(
                f"Comando bloqueado: '{blocked}' não é permitido no sandbox.",
                command,
            )

        user_id = str(self.current_user_id or "anon")

        # ── Fase 2: serviço sandbox dedicado ──────────────────────────────
        if SANDBOX_URL:
            try:
                # Resolve client_id para operações de arquivo
                client_id = None
                try:
                    client_id = self._get_client_id_from_user(self.current_user_id)
                except Exception:
                    pass

                # Injetar arquivos do chat atual no sandbox
                input_files = []
                if client_id and self.current_chat_id:
                    input_files = self._get_chat_input_files()

                raw = self._call_sandbox_service(command, user_id, input_files)
                data = json.loads(raw)
                data["command"] = command

                # Salvar arquivos gerados como attachments do chat
                generated_files = data.pop("generated_files", []) or []
                if generated_files and client_id and self.current_chat_id:
                    saved = self._save_generated_attachments(generated_files, client_id)
                    if saved:
                        data["generated_attachments"] = saved

                return json.dumps(data, ensure_ascii=False)
            except Exception:
                pass  # fallback para Fase 1

        # ── Fase 1: subprocess local ───────────────────────────────────────
        sandbox_dir = f"/tmp/sandbox/{user_id}"
        try:
            os.makedirs(sandbox_dir, mode=0o700, exist_ok=True)
        except Exception as e:
            return _err(f"Erro ao criar sandbox local: {str(e)}", command)

        return self._run_shell(sandbox_dir, command)

    # ── Fase 2 — HTTP ─────────────────────────────────────────────────────

    def _call_sandbox_service(
        self, command: str, user_id: str, input_files: list = None
    ) -> str:
        import requests as _req

        payload: dict = {"command": command, "user_id": user_id}
        if input_files:
            payload["input_files"] = input_files

        resp = _req.post(
            f"{SANDBOX_URL}/execute",
            json=payload,
            timeout=SANDBOX_TIMEOUT + 15,
        )
        resp.raise_for_status()
        return json.dumps(resp.json(), ensure_ascii=False)

    # ── File injection — lê attachments do chat e envia ao sandbox ─────────

    def _get_chat_input_files(self) -> list:
        """Lê attachments e assets gerados do chat atual e retorna como base64 para injeção no sandbox."""
        if not self.current_chat_id:
            return []
        try:
            import base64
            from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
            from App.Core.Crunch.Storage.StorageManager import StorageManager

            base = StorageManager.LOCAL_STORAGE_BASE
            MAX_FILE = 100 * 1024 * 1024  # 100 MB por arquivo
            MAX_TOTAL = 100 * 1024 * 1024  # 100 MB total
            total = 0
            result = []

            # Attachments enviados pelo usuário e arquivos gerados pelo agente
            att_rows = DatabaseManager.fetch_all(
                "SELECT attachment_id, file_name, extension, storage_path, source, sandbox_path FROM attachments "
                "WHERE chat_id = :chat_id AND deleted_at IS NULL "
                "AND storage_path IS NOT NULL AND is_temp = 0",
                {"chat_id": self.current_chat_id},
            )
            for row in att_rows:
                fname = (
                    row.get("file_name")
                    or f"{row['attachment_id']}.{row.get('extension', 'bin')}"
                )
                storage = row.get("storage_path")
                if not storage:
                    continue
                path = (
                    base / storage
                    if not str(storage).startswith("/")
                    else Path(storage)
                )
                if not path.exists():
                    logging.warning(
                        f"[SANDBOX] arquivo não encontrado para injeção: {path}"
                    )
                    continue
                size = path.stat().st_size
                if size > MAX_FILE:
                    logging.warning(
                        f"[SANDBOX] arquivo '{fname}' ignorado na injeção: {size // 1024} KB > limite"
                    )
                    continue
                if total + size > MAX_TOTAL:
                    logging.warning(
                        f"[SANDBOX] arquivo '{fname}' ignorado na injeção: total excede MAX_TOTAL"
                    )
                    continue
                content = base64.b64encode(path.read_bytes()).decode()
                entry: dict = {"name": fname, "content_b64": content}
                # Arquivos do agente voltam ao seu caminho original no sandbox
                if row.get("source") == "agent" and row.get("sandbox_path"):
                    entry["sandbox_path"] = row["sandbox_path"]
                result.append(entry)
                total += size

            # Assets gerados pelo agente (imagens, vídeos, etc.) → sempre em user/
            asset_rows = DatabaseManager.fetch_all(
                "SELECT asset_id, content_name, storage_path FROM assets "
                "WHERE chat_id = :chat_id AND storage_path IS NOT NULL",
                {"chat_id": self.current_chat_id},
            )
            for row in asset_rows:
                fname = row.get("asset_id") or row.get("content_name") or "asset"
                storage = row.get("storage_path")
                if not storage:
                    continue
                path = (
                    base / storage
                    if not str(storage).startswith("/")
                    else Path(storage)
                )
                if not path.exists():
                    logging.warning(f"[SANDBOX] asset não encontrado: {path}")
                    continue
                size = path.stat().st_size
                if size > MAX_FILE or total + size > MAX_TOTAL:
                    continue
                content = base64.b64encode(path.read_bytes()).decode()
                result.append({"name": fname, "content_b64": content})
                total += size

            return result
        except Exception as e:
            logging.warning(f"[SANDBOX] _get_chat_input_files error: {e}")
            return []

    # ── File collection — salva arquivos gerados como attachments ──────────

    def _save_generated_attachments(
        self, generated_files: list, client_id: str
    ) -> list:
        """Salva arquivos gerados pelo sandbox como attachments persistentes do chat."""
        if (
            not generated_files
            or not client_id
            or not self.current_chat_id
            or not self.current_user_id
        ):
            return []
        try:
            import base64
            from App.Core.Crunch.TablesSQL.DBManager import DatabaseManager
            from App.Core.Crunch.Storage.StorageManager import StorageManager

            base = StorageManager.LOCAL_STORAGE_BASE
            chat_terminal_dir = (
                base / f"client_{client_id}" / str(self.current_chat_id) / "terminal"
            )
            chat_terminal_dir.mkdir(parents=True, exist_ok=True)

            saved = []
            for gf in generated_files:
                try:
                    # gf['name'] é o caminho relativo dentro do sandbox (ex: "relatorio.html", "sub/data.csv")
                    sandbox_rel = gf.get("name", "file")
                    fname = Path(sandbox_rel).name  # só o nome do arquivo
                    ext = Path(fname).suffix.lstrip(".")
                    mime_type = gf.get("mime_type", "application/octet-stream")
                    file_type = mime_type.split("/")[0]

                    # Verificar se já existe attachment do agente com esse sandbox_path neste chat
                    existing = DatabaseManager.fetch_one(
                        "SELECT attachment_id, storage_path FROM attachments "
                        "WHERE chat_id = :chat_id AND sandbox_path = :sp AND source = 'agent' AND deleted_at IS NULL",
                        {"chat_id": self.current_chat_id, "sp": sandbox_rel},
                    )

                    raw_bytes = base64.b64decode(gf.get("content_b64", ""))

                    if existing:
                        # Upsert: sobrescrever arquivo no storage e atualizar registro
                        attachment_id = existing["attachment_id"]
                        existing_storage = existing.get("storage_path", "")
                        # Tentar sobrescrever o arquivo existente no storage
                        try:
                            dest_path = (
                                base / existing_storage
                                if existing_storage
                                and not str(existing_storage).startswith("/")
                                else Path(existing_storage or "")
                            )
                            if dest_path.parent.exists():
                                dest_path.write_bytes(raw_bytes)
                            else:
                                # Storage path inválido — salvar em novo caminho
                                safe_name = (
                                    f"{attachment_id}.{ext}" if ext else attachment_id
                                )
                                dest_path = chat_terminal_dir / safe_name
                                dest_path.write_bytes(raw_bytes)
                                existing_storage = str(dest_path.relative_to(base))
                        except Exception:
                            safe_name = (
                                f"{attachment_id}.{ext}" if ext else attachment_id
                            )
                            dest_path = chat_terminal_dir / safe_name
                            dest_path.write_bytes(raw_bytes)
                            existing_storage = str(dest_path.relative_to(base))

                        size = gf.get("size") or len(raw_bytes)
                        DatabaseManager.execute_query(
                            "UPDATE attachments SET file_size=:file_size, storage_path=:storage_path, file_type=:file_type WHERE attachment_id=:attachment_id",
                            {
                                "file_size": size,
                                "storage_path": existing_storage,
                                "file_type": file_type,
                                "attachment_id": attachment_id,
                            },
                        )
                    else:
                        # Inserir novo attachment do agente
                        attachment_id = f"attach_{uuid.uuid4().hex[:12]}"
                        safe_name = f"{attachment_id}.{ext}" if ext else attachment_id
                        dest = chat_terminal_dir / safe_name
                        dest.write_bytes(raw_bytes)
                        size = gf.get("size") or dest.stat().st_size
                        rel_path = str(dest.relative_to(base))

                        DatabaseManager.execute_query(
                            "INSERT INTO attachments "
                            "(attachment_id, user_id, chat_id, file_name, extension, file_type, file_size, "
                            "storage_path, storage_env, is_temp, source, sandbox_path) "
                            "VALUES (:attachment_id, :user_id, :chat_id, :file_name, :extension, :file_type, "
                            ":file_size, :storage_path, 'local', 0, 'agent', :sandbox_path)",
                            {
                                "attachment_id": attachment_id,
                                "user_id": str(self.current_user_id),
                                "chat_id": self.current_chat_id,
                                "file_name": fname,
                                "extension": ext,
                                "file_type": file_type,
                                "file_size": size,
                                "storage_path": rel_path,
                                "sandbox_path": sandbox_rel,
                            },
                        )

                    saved.append(
                        {
                            "attachment_id": attachment_id,
                            "filename": fname,
                            "mime_type": mime_type,
                            "size": size,
                        }
                    )
                except Exception as e:
                    logging.warning(
                        f"[SANDBOX] Failed to save generated file '{gf.get('name')}': {e}"
                    )

            return saved
        except Exception as e:
            logging.warning(f"[SANDBOX] _save_generated_attachments error: {e}")
            return []

    # ── Fase 1 — Shell ────────────────────────────────────────────────────

    def _run_shell(self, sandbox_dir: str, command: str) -> str:
        try:
            result = subprocess.run(
                ["bash", "-c", command],
                timeout=SANDBOX_TIMEOUT,
                cwd=sandbox_dir,
                capture_output=True,
                text=True,
                env={**_SAFE_ENV, "HOME": sandbox_dir},
                preexec_fn=_apply_limits,
            )
            return json.dumps(
                {
                    "success": True,
                    "command": command,
                    "exit_code": result.returncode,
                    "stdout": result.stdout[:MAX_STDOUT],
                    "stderr": result.stderr[:MAX_STDERR],
                },
                ensure_ascii=False,
            )

        except subprocess.TimeoutExpired:
            return _err(f"Timeout: execução excedeu {SANDBOX_TIMEOUT}s.", command)
        except Exception as exc:
            return _err(str(exc), command)


# ── Resource limits ───────────────────────────────────────────────────────────


def _apply_limits():
    _rlimit(resource.RLIMIT_AS, 512 * 1024 * 1024)  # 512 MB RAM
    _rlimit(resource.RLIMIT_FSIZE, 10 * 1024 * 1024)  # 10 MB arquivo
    # RLIMIT_NPROC removido: conta processos por UID no sistema inteiro,
    # então inclui threads do backend e causa "fork: Resource temporarily unavailable"
    # Proteção real vem do timeout (30s) + RLIMIT_AS (RAM)


def _rlimit(res: int, value: int):
    try:
        resource.setrlimit(res, (value, value))
    except Exception:
        pass


def _err(msg: str, command: str = "") -> str:
    return json.dumps(
        {"success": False, "error": msg, **({"command": command} if command else {})},
        ensure_ascii=False,
    )

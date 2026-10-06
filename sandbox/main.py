"""
Sandbox Service — Fase 2
Serviço HTTP dedicado para execução isolada de comandos shell por usuário.
Roda em container separado (sem acesso à rede pública, sem secrets do backend).

POST /execute
  body: { command, user_id, input_files?: [{name, content_b64}] }
  returns: { success, command, exit_code, stdout, stderr, generated_files }

GET /health
  returns: { status: "ok" }
"""

import base64
import mimetypes
import os
import re
import resource
import shutil
import subprocess
from typing import List, Optional
from urllib.parse import urlparse

from fastapi import FastAPI
from pydantic import BaseModel

# ── Config ────────────────────────────────────────────────────────────────────

SANDBOX_TIMEOUT = 30
MAX_STDOUT      = 8000
MAX_STDERR      = 2000
PORT            = int(os.environ.get("SANDBOX_PORT", 8001))

_EGRESS_PROXY = os.environ.get("EGRESS_PROXY_URL", "").rstrip("/")

_SAFE_ENV: dict[str, str] = {
    "PATH":                    "/usr/bin:/usr/local/bin:/bin",
    "HOME":                    "/tmp",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONIOENCODING":        "utf-8",
    "LANG":                    "C.UTF-8",
    "LC_ALL":                  "C.UTF-8",
    "TERM":                    "xterm-256color",
    "MPLCONFIGDIR":            "/tmp",   # matplotlib config dir no container read-only
    **({
        "http_proxy":  _EGRESS_PROXY,
        "https_proxy": _EGRESS_PROXY,
        "HTTP_PROXY":  _EGRESS_PROXY,
        "HTTPS_PROXY": _EGRESS_PROXY,
        "no_proxy":    "localhost,127.0.0.1",
        "NO_PROXY":    "localhost,127.0.0.1",
    } if _EGRESS_PROXY else {}),
}

_BLACKLIST: list[tuple[str, str]] = [
    (r'\bsudo\b',                              "sudo"),
    (r'(?<!\w)su\s',                           "su"),
    (r'\brm\s+.*-[a-z]*r[a-z]*',              "rm -r"),
    (r'\brm\s+-[a-z]*f[a-z]*\s',              "rm -f"),
    (r'\bwget\b',                              "wget"),
    (r'\bapt(-get)?\b',                        "apt"),
    (r'\byum\b|\bdnf\b|\bpacman\b|\bapk\b',   "package manager"),
    (r'\bpip\s+install\b',                     "pip install"),
    (r'\bnpm\s+install\b',                     "npm install"),
    (r'\bssh\b|\bscp\b|\bsftp\b|\btelnet\b|\bftp\b', "ssh/scp/sftp"),
    (r'\bnc\b|\bncat\b|\bnetcat\b',            "netcat"),
    (r'\bnmap\b|\bmasscan\b',                  "nmap"),
    (r'\breboot\b|\bshutdown\b|\bhalt\b|\bpoweroff\b|\binit\s+[06]\b', "system shutdown"),
    (r'\bkillall\b|\bpkill\b',                 "killall/pkill"),
    (r'\bmkfs\b|\bfdisk\b|\bparted\b',         "disk formatting"),
    (r'\bdd\s+if=',                             "dd"),
    (r'\bmount\b|\bumount\b',                   "mount"),
    (r'\bchown\b',                              "chown"),
    (r'\bchmod\b',                              "chmod"),
    (r'\binsmod\b|\bmodprobe\b|\brmmod\b',     "kernel modules"),
    (r'\bcrontab\b',                            "crontab"),
    (r'\biptables\b|\bnftables\b',             "iptables"),
    (r'\bip\s+(link|addr|route|rule|neigh|tunnel|netns|maddr|mroute|monitor|xfrm)\b', "ip config"),
    (r'\blocalhost\b',                          "localhost"),
    (r'\b127\.\d+\.\d+\.\d+\b',               "127.x loopback"),
    (r'\b::1\b',                               "IPv6 loopback"),
    (r'\b0\.0\.0\.0\b',                        "0.0.0.0"),
    (r'\b10\.\d+\.\d+\.\d+\b',                "10.x private network"),
    (r'\b192\.168\.\d+\.\d+\b',               "192.168.x private network"),
    (r'\b172\.(1[6-9]|2\d|3[01])\.\d+\.\d+\b', "172.16-31.x private network"),
    (r'\b169\.254\.\d+\.\d+\b',               "169.254.x link-local"),
    (r'file://',                               "file://"),
    (r'\bimport\s+(urllib|requests|socket|httpx|aiohttp|http)\b', "python: módulo de rede bloqueado"),
    (r'\bfrom\s+(urllib|requests|socket|httpx|aiohttp|http)\b',   "python: módulo de rede bloqueado"),
    (r'__import__\s*\(\s*[\'\"](urllib|requests|socket|httpx|aiohttp|http)', "python: módulo de rede bloqueado"),
    (r'\bcurl\b[^#\n]*--resolve\b',           "curl --resolve"),
    (r'\bcurl\b[^#\n]*(\s-x\s|--proxy\b)',    "curl proxy flag"),
    (r'\bcurl\b[^#\n]*\|\s*(ba?sh|python3?|node|perl|ruby)\b', "curl pipe to interpreter"),
]

_FQDN_RE = re.compile(r'^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$')
_INTERNAL_TLDS = frozenset({'local', 'internal', 'localhost', 'localdomain', 'lan', 'home', 'corp', 'intranet'})

# Limites de coleta de arquivos gerados
_MAX_GENERATED_FILE  = 100 * 1024 * 1024  # 100 MB por arquivo gerado
_MAX_GENERATED_TOTAL = 200 * 1024 * 1024  # 200 MB total gerado
_MAX_INPUT_FILE      = 100 * 1024 * 1024  # 100 MB por arquivo injetado
_MAX_INPUT_TOTAL     = 200 * 1024 * 1024  # 200 MB total injetado
_SKIP_EXTENSIONS     = frozenset({'.pyc', '.pyo', '.pyd'})


def _check_curl_whitelist(command: str) -> Optional[str]:
    if not re.search(r'\bcurl\b', command, re.IGNORECASE):
        return None
    urls = re.findall(r'(?i)(https?://[^\s\'"<>|&;`\\]+)', command)
    if not urls:
        return "curl requer URL com https:// explícito"
    for raw_url in urls:
        parsed = urlparse(raw_url.rstrip('\'\".,)'))
        if parsed.scheme != 'https':
            return f"curl requer HTTPS — recebido: {parsed.scheme}://"
        host = (parsed.hostname or '').rstrip('.')
        if not host:
            return "curl: host não identificado na URL"
        if not _FQDN_RE.match(host):
            return f"curl: '{host}' não é um domínio válido"
        tld = host.rsplit('.', 1)[-1].lower()
        if tld in _INTERNAL_TLDS:
            return f"curl: TLD '.{tld}' é reservado para redes internas"
    return None


def _check_blacklist(command: str) -> Optional[str]:
    lower = command.lower()
    for pattern, label in _BLACKLIST:
        if re.search(pattern, lower):
            return label
    return _check_curl_whitelist(command)


# ── Models ────────────────────────────────────────────────────────────────────

class FileEntry(BaseModel):
    name:         str
    content_b64:  str
    sandbox_path: Optional[str] = None  # caminho relativo dentro do sandbox (ex: "relatorio.html")


class GeneratedFile(BaseModel):
    name:        str
    content_b64: str
    mime_type:   str
    size:        int


class ExecuteRequest(BaseModel):
    command:     str
    user_id:     str = "anon"
    input_files: List[FileEntry] = []


class ExecuteResponse(BaseModel):
    success:         bool
    command:         Optional[str] = None
    exit_code:       Optional[int] = None
    stdout:          Optional[str] = None
    stderr:          Optional[str] = None
    error:           Optional[str] = None
    generated_files: List[GeneratedFile] = []


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="Prox Sandbox", docs_url=None, redoc_url=None)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/execute", response_model=ExecuteResponse)
def execute(req: ExecuteRequest):
    command = (req.command or "").strip()
    if not command:
        return ExecuteResponse(success=False, error="Nenhum comando fornecido.")

    blocked = _check_blacklist(command)
    if blocked:
        return ExecuteResponse(
            success=False,
            command=command,
            error=f"Comando bloqueado: '{blocked}' não é permitido no sandbox.",
        )

    sandbox_dir = f"/tmp/sandbox/{req.user_id}"
    os.makedirs(sandbox_dir, mode=0o700, exist_ok=True)

    # 1. Limpar arquivos gerados em execuções anteriores (exceto user/)
    _purge_generated(sandbox_dir)

    # 2. Injetar arquivos: user files → user/{name}, agent files → sandbox_path
    user_dir = os.path.join(sandbox_dir, "user")
    os.makedirs(user_dir, mode=0o755, exist_ok=True)
    _write_input_files(sandbox_dir, req.input_files)

    # 3. Snapshot completo de /tmp/ após injeção — baseline para detectar qualquer novo arquivo
    tmp_snapshot = _snapshot_tmp()

    # 4. Executar comando
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
        # Coletar qualquer arquivo novo ou modificado em qualquer path dentro de /tmp/
        generated = _collect_new_files(tmp_snapshot)
        _cleanup_all(sandbox_dir)

        return ExecuteResponse(
            success=True,
            command=command,
            exit_code=result.returncode,
            stdout=result.stdout[:MAX_STDOUT],
            stderr=result.stderr[:MAX_STDERR],
            generated_files=generated,
        )

    except subprocess.TimeoutExpired:
        _cleanup_all(sandbox_dir)
        return ExecuteResponse(success=False, command=command, error=f"Timeout: excedeu {SANDBOX_TIMEOUT}s.")
    except Exception as exc:
        _cleanup_all(sandbox_dir)
        return ExecuteResponse(success=False, command=command, error=str(exc))


# ── File helpers ──────────────────────────────────────────────────────────────


def _purge_generated(sandbox_dir: str) -> None:
    """Remove sobras de execuções anteriores (tudo exceto user/)."""
    try:
        with os.scandir(sandbox_dir) as it:
            for entry in it:
                if entry.name == "user":
                    continue
                if entry.is_file(follow_symlinks=False):
                    os.unlink(entry.path)
                elif entry.is_dir(follow_symlinks=False):
                    shutil.rmtree(entry.path, ignore_errors=True)
    except Exception:
        pass


def _write_input_files(sandbox_dir: str, files: List[FileEntry]) -> None:
    """Injeta arquivos no sandbox: caminhos absolutos → exato; sandbox_path relativo → sandbox_dir/; senão → user/."""
    import logging as _logging
    total = 0
    for f in files:
        try:
            raw = base64.b64decode(f.content_b64)
            size = len(raw)
            if size > _MAX_INPUT_FILE:
                _logging.warning(f"[SANDBOX] arquivo '{f.name}' ignorado: {size // 1024} KB > limite")
                continue
            if total + size > _MAX_INPUT_TOTAL:
                _logging.warning(f"[SANDBOX] arquivo '{f.name}' ignorado: total excede limite")
                continue
            if f.sandbox_path:
                if f.sandbox_path.startswith("/"):
                    # Caminho absoluto — reinjetar exatamente onde estava (ex: /tmp/relatorio.html)
                    dest = f.sandbox_path
                else:
                    rel = os.path.normpath(f.sandbox_path).lstrip("/")
                    if rel.startswith(".."):
                        rel = os.path.basename(f.sandbox_path)
                    dest = os.path.join(sandbox_dir, rel)
            else:
                safe_name = os.path.basename(f.name) or "file"
                dest = os.path.join(sandbox_dir, "user", safe_name)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as fh:
                fh.write(raw)
            total += size
        except Exception as e:
            _logging.warning(f"[SANDBOX] erro ao injetar arquivo '{f.name}': {e}")


def _snapshot_tmp() -> set:
    """Snapshot completo recursivo de /tmp/ — retorna set de (caminho_abs, mtime_ns, size).
    Usado como baseline: qualquer arquivo ausente ou com mtime/size diferente após exec = novo/modificado."""
    result: set = set()
    try:
        for root, dirs, files in os.walk("/tmp"):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for fname in files:
                fpath = os.path.join(root, fname)
                try:
                    st = os.stat(fpath)
                    result.add((fpath, st.st_mtime_ns, st.st_size))
                except OSError:
                    pass
    except Exception:
        pass
    return result


def _collect_new_files(before: set) -> List[GeneratedFile]:
    """Coleta todos os arquivos em /tmp/ que são novos ou foram modificados desde o snapshot antes da exec."""
    before_dict = {path: (mtime, size) for path, mtime, size in before}
    collected: List[GeneratedFile] = []
    total = 0
    try:
        for root, dirs, files in os.walk("/tmp"):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for fname in files:
                if fname.startswith("."):
                    continue
                _, ext = os.path.splitext(fname)
                if ext.lower() in _SKIP_EXTENSIONS:
                    continue
                fpath = os.path.join(root, fname)
                try:
                    st = os.stat(fpath)
                    prev = before_dict.get(fpath)
                    if prev and prev == (st.st_mtime_ns, st.st_size):
                        continue  # inalterado — arquivo que já existia antes da exec
                    size = st.st_size
                    if size == 0 or size > _MAX_GENERATED_FILE or total + size > _MAX_GENERATED_TOTAL:
                        continue
                    with open(fpath, "rb") as fh:
                        content = base64.b64encode(fh.read()).decode()
                    mime_type = mimetypes.guess_type(fname)[0] or "application/octet-stream"
                    # name = caminho absoluto para reinjeção exata na próxima execução
                    collected.append(GeneratedFile(name=fpath, content_b64=content, mime_type=mime_type, size=size))
                    total += size
                except Exception:
                    pass
    except Exception:
        pass
    return collected


def _cleanup_all(sandbox_dir: str) -> None:
    """Remove tudo em sandbox_dir: user/ + arquivos gerados."""
    try:
        with os.scandir(sandbox_dir) as it:
            for entry in it:
                if entry.is_file(follow_symlinks=False):
                    os.unlink(entry.path)
                elif entry.is_dir(follow_symlinks=False):
                    shutil.rmtree(entry.path, ignore_errors=True)
    except Exception:
        pass


# ── Resource limits ───────────────────────────────────────────────────────────

def _apply_limits():
    _rl(resource.RLIMIT_AS,    2 * 1024 * 1024 * 1024)  # 2 GB RAM
    _rl(resource.RLIMIT_NPROC, 256)
    _rl(resource.RLIMIT_FSIZE, 200 * 1024 * 1024)        # 200 MB por arquivo criado
    _rl(resource.RLIMIT_NOFILE, 256)


def _rl(res, val):
    try:
        resource.setrlimit(res, (val, val))
    except Exception:
        pass


# ── Entry ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)

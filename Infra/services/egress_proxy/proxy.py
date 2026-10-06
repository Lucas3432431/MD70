#!/usr/bin/env python3
"""
Egress proxy for Prox sandbox.
Allows connections to the public internet only.
Blocks RFC 1918, link-local, and Docker-internal hostnames.

Handles:
  - HTTP  — forwarded request/response
  - HTTPS — CONNECT tunnel (opaque, not intercepted)
"""
import http.client
import ipaddress
import json
import os
import select
import socket
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

PORT = int(os.getenv("PROXY_PORT", "3128"))
TIMEOUT = 30

_BLOCKED_NETS = [
    ipaddress.ip_network(n)
    for n in (
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "127.0.0.0/8",
        "169.254.0.0/16",  # link-local / AWS metadata
        "0.0.0.0/8",
        "100.64.0.0/10",   # carrier-grade NAT
        "198.18.0.0/15",   # benchmarking
        "::1/128",         # IPv6 loopback
        "fc00::/7",        # IPv6 unique local
        "fe80::/10",       # IPv6 link-local
    )
]

_BLOCKED_HOSTS = frozenset(
    os.getenv("BLOCKED_HOSTS", "backend,db,redis,gateway,sandbox,egress_proxy").split(",")
)


def _log(event: str, host: str, path: str = "", status: str = "", client: str = "") -> None:
    print(json.dumps({
        "ts":     datetime.now(timezone.utc).isoformat(),
        "event":  event,   # "allow" | "block" | "error"
        "host":   host,
        "path":   path,
        "status": status,
        "client": client,
    }, ensure_ascii=False), flush=True)


def _resolve(host: str) -> tuple[str | None, str | None]:
    """Resolve host e verifica blocklist. Retorna (ip, None) ou (None, motivo).
    Resolve uma única vez para evitar TOCTOU entre check e connect."""
    bare = host.lower().split(":")[0].strip("[]")
    if bare in _BLOCKED_HOSTS:
        return None, f"blocked host: {bare}"
    try:
        resolved = socket.gethostbyname(bare)
        ip = ipaddress.ip_address(resolved)
        if any(ip in net for net in _BLOCKED_NETS):
            return None, f"blocked IP: {resolved}"
        return resolved, None
    except OSError as exc:
        return None, str(exc)


def _relay(a: socket.socket, b: socket.socket) -> None:
    """Bidirectional TCP relay. Blocks until either side closes."""
    try:
        while True:
            r, _, _ = select.select([a, b], [], [], TIMEOUT)
            if not r:
                break
            for s in r:
                data = s.recv(65536)
                if not data:
                    return
                (b if s is a else a).sendall(data)
    except OSError:
        pass
    finally:
        for s in (a, b):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # suprime o log padrão — usamos _log() estruturado

    def _client_ip(self) -> str:
        return self.client_address[0] if self.client_address else ""

    # ── HTTPS CONNECT tunnel ──────────────────────────────────────────────────
    def do_CONNECT(self):
        host, _, port_s = self.path.rpartition(":")
        port = int(port_s) if port_s.isdigit() else 443

        resolved_ip, err = _resolve(host)
        if err:
            _log("block", host, client=self._client_ip(), status=f"403 {err}")
            self.send_error(403, "Blocked: internal destination")
            return
        try:
            remote = socket.create_connection((resolved_ip, port), TIMEOUT)
        except OSError as exc:
            _log("error", host, client=self._client_ip(), status=f"502 {exc}")
            self.send_error(502, str(exc))
            return

        _log("allow", host, path=f":{port}", client=self._client_ip(), status="CONNECT")
        self.send_response(200, "Connection established")
        self.end_headers()
        _relay(self.connection, remote)

    # ── HTTP forward ──────────────────────────────────────────────────────────
    def _forward(self):
        parsed = urlparse(self.path)
        host = parsed.hostname or ""

        resolved_ip, err = _resolve(host)
        if err:
            _log("block", host, path=parsed.path, client=self._client_ip(), status=f"403 {err}")
            self.send_error(403, "Blocked: internal destination")
            return

        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        path = (parsed.path or "/") + (f"?{parsed.query}" if parsed.query else "")

        skip = {"proxy-connection", "connection", "keep-alive", "host"}
        headers = {k: v for k, v in self.headers.items() if k.lower() not in skip}
        headers["Host"] = f"{host}:{parsed.port}" if parsed.port else host

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else None

        ConnCls = (
            http.client.HTTPSConnection
            if parsed.scheme == "https"
            else http.client.HTTPConnection
        )
        conn = ConnCls(resolved_ip, port, timeout=TIMEOUT)
        try:
            conn.request(self.command, path, body=body, headers=headers)
            resp = conn.getresponse()
            _log("allow", host, path=parsed.path, client=self._client_ip(), status=str(resp.status))
            self.send_response(resp.status, resp.reason)
            for k, v in resp.getheaders():
                if k.lower() not in ("transfer-encoding", "connection"):
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(resp.read())
        except OSError as exc:
            _log("error", host, path=parsed.path, client=self._client_ip(), status=f"502 {exc}")
            self.send_error(502, str(exc))
        finally:
            conn.close()

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _forward


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", PORT), _Handler)
    print(
        f"[egress-proxy] :{PORT} — blocking RFC1918 + {sorted(_BLOCKED_HOSTS)}",
        flush=True,
    )
    server.serve_forever()

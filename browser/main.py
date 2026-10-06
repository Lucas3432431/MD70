"""
Browser Service
Container isolado com Playwright/Chromium para scraping e screenshots.
Todo tráfego passa pelo egress proxy (bloqueia RFC 1918).

POST /scrape           — retorna HTML da página (com suporte a cookies)
POST /scrape_cffi      — scraping com TLS fingerprint aleatório (curl-cffi), sem browser
POST /screenshot       — retorna PNG em base64 (com suporte a cookies)
POST /execute          — carrega página, faz scroll, executa JS e retorna resultado + HTML
POST /login_instagram  — faz login no Instagram e retorna cookies de sessão
POST /extract          — extrai markdown de HTML raw (trafilatura + markdownify fallback)
POST /parse_bing       — parseia HTML de resultados Bing em markdown estruturado
GET  /health
"""

import asyncio
import base64
import logging
import os
import random
import re
import time
from contextlib import asynccontextmanager
from typing import Any, List, Optional
from urllib.parse import urlparse

from fastapi import FastAPI
from pydantic import BaseModel

# ── Config ────────────────────────────────────────────────────────────────────

PORT         = int(os.getenv("BROWSER_PORT", "8002"))
EGRESS_PROXY = os.getenv("EGRESS_PROXY_URL", "")
TIMEOUT_MS   = 35_000
MAX_CONTEXTS = int(os.getenv("BROWSER_MAX_CONTEXTS", "5"))

_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
]

# Pool de fingerprints TLS reais para curl-cffi (rotaciona aleatoriamente)
_CFFI_FINGERPRINTS = [
    # Chrome desktop
    "chrome146", "chrome145", "chrome142", "chrome136", "chrome131",
    "chrome124", "chrome123", "chrome120", "chrome119", "chrome116",
    "chrome110", "chrome107", "chrome104", "chrome101", "chrome100", "chrome99",
    # Firefox
    "firefox147", "firefox144", "firefox135", "firefox133",
    # Safari desktop
    "safari260", "safari2601", "safari184", "safari180", "safari170",
    "safari15_5", "safari15_3",
    # Edge
    "edge101", "edge99",
    # Tor
    "tor145",
]

# ── URL validation ────────────────────────────────────────────────────────────

_FQDN_RE = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$"
)

_INTERNAL_TLDS = frozenset({
    "local", "internal", "localdomain",
    "lan", "home", "corp", "intranet", "localhost",
})


def _validate_url(url: str) -> Optional[str]:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return f"scheme não permitido: {parsed.scheme}"
    host = (parsed.hostname or "").rstrip(".")
    if not host:
        return "URL sem host"
    if not _FQDN_RE.match(host):
        return f"'{host}' não é FQDN válido — IPs e hostnames simples são bloqueados"
    tld = host.rsplit(".", 1)[-1].lower()
    if tld in _INTERNAL_TLDS:
        return f"TLD '.{tld}' é reservado para redes internas"
    return None


# ── Playwright helpers ────────────────────────────────────────────────────────

def _launch_opts() -> dict:
    opts: dict = {
        "headless": True,
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-extensions",
        ],
    }
    if EGRESS_PROXY:
        opts["proxy"] = {"server": EGRESS_PROXY}
    return opts


def _ctx_opts() -> dict:
    return {
        "user_agent": random.choice(_UA_POOL),
        "viewport": {"width": random.randint(1280, 1920), "height": 800},
        "locale": "pt-BR",
        "timezone_id": "America/Sao_Paulo",
    }


async def _add_cookies(context, cookies: list) -> None:
    if cookies:
        try:
            await context.add_cookies(cookies)
        except Exception as e:
            logging.warning(f"[BROWSER] Falha ao injetar cookies: {e}")


# ── Persistent Browser Pool ───────────────────────────────────────────────────

class _BrowserPool:
    """
    Mantém um processo Chromium vivo entre requests.
    Cada request recebe um contexto isolado (cookies/storage separados),
    que é fechado ao final. O processo browser não é relançado.

    Semáforo limita contextos simultâneos a MAX_CONTEXTS.
    Se o browser cair (crash/OOM) é relançado automaticamente.
    """

    def __init__(self) -> None:
        self._playwright = None
        self._browser = None
        self._lock = asyncio.Lock()
        self._semaphore: asyncio.Semaphore | None = None

    async def start(self) -> None:
        from playwright.async_api import async_playwright as _apw
        self._playwright = await _apw().start()
        self._browser = await self._playwright.chromium.launch(**_launch_opts())
        self._semaphore = asyncio.Semaphore(MAX_CONTEXTS)
        logging.info(f"[POOL] Chromium iniciado (max_contexts={MAX_CONTEXTS})")

    async def stop(self) -> None:
        try:
            if self._browser:
                await self._browser.close()
        except Exception:
            pass
        try:
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass
        logging.info("[POOL] Chromium encerrado")

    async def _ensure_alive(self) -> None:
        if self._browser and self._browser.is_connected():
            return
        async with self._lock:
            if self._browser and self._browser.is_connected():
                return
            logging.warning("[POOL] Browser desconectado — relançando...")
            try:
                if self._playwright is None:
                    from playwright.async_api import async_playwright as _apw
                    self._playwright = await _apw().start()
                self._browser = await self._playwright.chromium.launch(**_launch_opts())
                logging.info("[POOL] Browser relançado com sucesso")
            except Exception as exc:
                logging.error(f"[POOL] Falha ao relançar browser: {exc}")
                raise

    @asynccontextmanager
    async def new_context(self, cookies: list | None = None):
        """Context manager: cria contexto isolado, faz cleanup garantido."""
        await self._ensure_alive()
        assert self._semaphore is not None
        async with self._semaphore:
            ctx = await self._browser.new_context(**_ctx_opts())
            if cookies:
                await _add_cookies(ctx, cookies)
            try:
                yield ctx
            finally:
                try:
                    await ctx.close()
                except Exception:
                    pass


_pool = _BrowserPool()


# ── App ───────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    await _pool.start()
    yield
    await _pool.stop()


app = FastAPI(
    title="Prox Browser",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)


# ── /scrape ───────────────────────────────────────────────────────────────────

class ScrapeRequest(BaseModel):
    url: str
    wait_until: str = "load"
    cookies: List[dict] = []


class ScrapeResponse(BaseModel):
    success: bool
    html: Optional[str] = None
    url: Optional[str] = None
    error: Optional[str] = None


@app.get("/health")
def health():
    browser_connected = bool(_pool._browser and _pool._browser.is_connected())
    return {
        "status": "ok" if browser_connected else "degraded",
        "browser": "connected" if browser_connected else "disconnected",
        "max_contexts": MAX_CONTEXTS,
    }


_JS_CHALLENGE_SIGNALS = [
    "_bm_skipml", "verifychallenge", "micro-landing-container",
    "just a moment", "checking your browser", "cf-browser-verification",
    "enable javascript and cookies",
]

_SPA_SHELL_SIGNALS = [
    "turn on javascript", "enable javascript", "requires javascript",
    "javascript is required", "you need to enable javascript",
    "please enable javascript", "without javascript",
    "oh no! pinterest", "pinterest doesn't work",
    '<div id="root"></div>', '<div id="__next"></div>', '<div id="app"></div>',
]

# Sinais de loading state (React/Vue já montou mas ainda busca dados da API)
_LOADING_STATE_SIGNALS = [
    "carregando...", "carregando ", "loading...", "loading ",
    "please wait", "aguarde", "a carregar",
    'class="loading"', 'class="spinner"', 'class="loader"',
    'id="loading"', 'class="skeleton"',
    "animate-pulse",  # Tailwind skeleton loader
]


def _has_js_challenge(html: str) -> bool:
    sample = html[:15_000].lower()
    return sum(1 for s in _JS_CHALLENGE_SIGNALS if s in sample) >= 1


def _is_spa_shell(html: str) -> bool:
    sample = html[:10_000].lower()
    return any(s in sample for s in _SPA_SHELL_SIGNALS)


@app.post("/scrape", response_model=ScrapeResponse)
async def scrape(req: ScrapeRequest):
    err = _validate_url(req.url)
    if err:
        return ScrapeResponse(success=False, error=f"URL bloqueada: {err}")

    try:
        from playwright_stealth import Stealth as _Stealth

        async with _pool.new_context(req.cookies) as context:
            page = await context.new_page()
            await _Stealth().apply_stealth_async(page)
            await page.goto(req.url, wait_until=req.wait_until, timeout=TIMEOUT_MS)
            html = await page.content()

            # SPA shell detectada ou loading state: aguarda networkidle + loop de retry
            _needs_wait = _is_spa_shell(html) or any(s in html.lower() for s in _LOADING_STATE_SIGNALS)
            if _needs_wait:
                if _is_spa_shell(html):
                    logging.info(f"[BROWSER] scrape: SPA shell detectada para {req.url}, aguardando render")
                else:
                    logging.info(f"[BROWSER] scrape: loading state detectado para {req.url}, aguardando networkidle")
                try:
                    await page.wait_for_load_state("networkidle", timeout=10_000)
                except Exception:
                    pass
                html = await page.content()

            # Loop de retry: aguarda 1s por vez até loading sumir ou HTML estabilizar
            _loading_attempts = 0
            _loading_max = 12
            _prev_html = ""
            while any(s in html.lower() for s in _LOADING_STATE_SIGNALS) and _loading_attempts < _loading_max:
                _loading_attempts += 1
                logging.info(f"[BROWSER] scrape: loading state ({_loading_attempts}/{_loading_max}) para {req.url}")
                await asyncio.sleep(1)
                html = await page.content()
                if html == _prev_html and _loading_attempts >= 3:
                    logging.info(f"[BROWSER] scrape: elemento loading permanente detectado, prosseguindo para {req.url}")
                    break
                _prev_html = html
            if _loading_attempts:
                if _loading_attempts >= _loading_max:
                    logging.warning(f"[BROWSER] scrape: loading persistente após {_loading_max}s para {req.url}")
                else:
                    logging.info(f"[BROWSER] scrape: loading resolvido em {_loading_attempts}s para {req.url}")

            # Se detectar challenge JS (ML PoW, Cloudflare), aguarda auto-redirecionamento
            if _has_js_challenge(html):
                logging.warning(f"[BROWSER] Challenge JS detectado, aguardando resolução automática")
                try:
                    original_url = page.url
                    await page.wait_for_url(
                        lambda u: u != original_url,
                        timeout=15_000,
                    )
                    await asyncio.sleep(1.5)
                except Exception:
                    await asyncio.sleep(12)
                try:
                    await page.wait_for_load_state("networkidle", timeout=8_000)
                except Exception:
                    pass
                html = await page.content()

        return ScrapeResponse(success=True, html=html, url=req.url)

    except Exception as exc:
        logging.warning(f"[BROWSER] scrape falhou ({req.url}): {exc}")
        return ScrapeResponse(success=False, error=str(exc), url=req.url)


# ── /scrape_cffi ─────────────────────────────────────────────────────────────
# Scraping leve com TLS fingerprint aleatório via curl-cffi.
# Não executa JavaScript — ideal para páginas com HTML server-side (Google, DDG, etc.)

class CffiScrapeRequest(BaseModel):
    url: str
    fingerprint: Optional[str] = None  # None = aleatório
    cookies: List[dict] = []


class CffiScrapeResponse(BaseModel):
    success: bool
    html: Optional[str] = None
    url: Optional[str] = None
    fingerprint: Optional[str] = None
    error: Optional[str] = None


@app.post("/scrape_cffi", response_model=CffiScrapeResponse)
async def scrape_cffi(req: CffiScrapeRequest):
    err = _validate_url(req.url)
    if err:
        return CffiScrapeResponse(success=False, error=f"URL bloqueada: {err}")

    fp = req.fingerprint or random.choice(_CFFI_FINGERPRINTS)

    try:
        from curl_cffi.requests import AsyncSession

        proxy = EGRESS_PROXY or None
        cookie_dict = {c["name"]: c["value"] for c in req.cookies if "name" in c and "value" in c}

        async with AsyncSession(impersonate=fp, verify=False) as session:
            resp = await session.get(
                req.url,
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
                    "Accept-Encoding": "gzip, deflate, br",
                    "DNT": "1",
                    "Upgrade-Insecure-Requests": "1",
                },
                cookies=cookie_dict or None,
                proxies={"https": proxy, "http": proxy} if proxy else None,
                timeout=30,
                allow_redirects=True,
            )
            html = resp.text

        return CffiScrapeResponse(success=True, html=html, url=req.url, fingerprint=fp)

    except Exception as exc:
        logging.warning(f"[BROWSER/CFFI] scrape_cffi falhou ({req.url}, fp={fp}): {exc}")
        return CffiScrapeResponse(success=False, error=str(exc), url=req.url, fingerprint=fp)


# ── /screenshot ───────────────────────────────────────────────────────────────

class ScreenshotRequest(BaseModel):
    url: str
    cookies: List[dict] = []


class ScreenshotResponse(BaseModel):
    success: bool
    screenshot_base64: Optional[str] = None
    url: Optional[str] = None
    error: Optional[str] = None


@app.post("/screenshot", response_model=ScreenshotResponse)
async def screenshot(req: ScreenshotRequest):
    err = _validate_url(req.url)
    if err:
        return ScreenshotResponse(success=False, error=f"URL bloqueada: {err}")

    try:
        from playwright_stealth import Stealth as _Stealth

        async with _pool.new_context(req.cookies) as context:
            page = await context.new_page()
            await _Stealth().apply_stealth_async(page)
            await page.goto(req.url, wait_until="load", timeout=TIMEOUT_MS)

            html_check = await page.content()
            if _is_spa_shell(html_check):
                logging.info(f"[BROWSER] screenshot: SPA shell detectado para {req.url}, aguardando render adicional")
                try:
                    await page.wait_for_load_state("networkidle", timeout=8_000)
                except Exception:
                    pass
                await asyncio.sleep(3)

            png = await page.screenshot(type="png", full_page=False)

        b64 = base64.b64encode(png).decode()
        return ScreenshotResponse(
            success=True,
            screenshot_base64=f"data:image/png;base64,{b64}",
            url=req.url,
        )

    except Exception as exc:
        logging.warning(f"[BROWSER] screenshot falhou ({req.url}): {exc}")
        return ScreenshotResponse(success=False, error=str(exc), url=req.url)


# ── /execute ──────────────────────────────────────────────────────────────────

class ExecuteRequest(BaseModel):
    url: str
    script: str               # JavaScript a avaliar após carregar a página
    cookies: List[dict] = []
    scroll_seconds: int = 0   # segundos de scroll contínuo (ex: Google Maps)
    scroll_delay_s: float = 0.5
    wait_until: str = "domcontentloaded"
    timeout_ms: int = 30_000
    stealth: bool = False     # injeta script para ocultar webdriver


class ExecuteResponse(BaseModel):
    success: bool
    result: Any = None        # retorno JSON do script
    html: Optional[str] = None
    error: Optional[str] = None


@app.post("/execute", response_model=ExecuteResponse)
async def execute(req: ExecuteRequest):
    err = _validate_url(req.url)
    if err:
        return ExecuteResponse(success=False, error=f"URL bloqueada: {err}")

    try:
        from playwright_stealth import Stealth as _Stealth

        async with _pool.new_context(req.cookies) as context:
            page = await context.new_page()

            if req.stealth:
                await _Stealth().apply_stealth_async(page)

            await page.set_extra_http_headers({
                "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            })

            await page.goto(req.url, wait_until=req.wait_until, timeout=req.timeout_ms)

            # Scroll contínuo com detecção de estabilização
            if req.scroll_seconds > 0:
                deadline = time.monotonic() + req.scroll_seconds
                last_count = 0
                no_change = 0
                while time.monotonic() < deadline:
                    vp = await page.evaluate(
                        "() => ({w: window.innerWidth, h: window.innerHeight})"
                    )
                    cx, cy = vp["w"] // 2, vp["h"] // 2
                    await page.mouse.move(cx, cy)
                    for _ in range(5):
                        await page.mouse.wheel(0, 300)
                        await asyncio.sleep(0.1)
                    await asyncio.sleep(req.scroll_delay_s)
                    count = await page.evaluate(
                        "document.querySelectorAll('[data-review-id],[role=\"article\"],.jxjwge,article').length"
                    )
                    if count == last_count:
                        no_change += 1
                        if no_change >= int(3 / req.scroll_delay_s) and (time.monotonic() - (deadline - req.scroll_seconds)) >= 30:
                            break
                    else:
                        no_change = 0
                        last_count = count

            result = await page.evaluate(req.script)
            html   = await page.content()

        return ExecuteResponse(success=True, result=result, html=html)

    except Exception as exc:
        logging.warning(f"[BROWSER] execute falhou ({req.url}): {exc}")
        return ExecuteResponse(success=False, error=str(exc))


# ── /login_instagram ──────────────────────────────────────────────────────────

class InstagramLoginRequest(BaseModel):
    email: str
    password: str
    existing_cookies: List[dict] = []  # cookies a injetar antes do login


class InstagramLoginResponse(BaseModel):
    success: bool
    cookies: List[dict] = []
    error: Optional[str] = None


@app.post("/login_instagram", response_model=InstagramLoginResponse)
async def login_instagram(req: InstagramLoginRequest):
    login_url = "https://www.instagram.com/accounts/login/"
    err = _validate_url(login_url)
    if err:
        return InstagramLoginResponse(success=False, error=err)

    try:
        async with _pool.new_context(req.existing_cookies) as context:
            page = await context.new_page()

            await page.goto(login_url, wait_until="domcontentloaded", timeout=60_000)
            await asyncio.sleep(2)

            try:
                await page.fill('input[name="username"]', req.email, timeout=8_000)
                await asyncio.sleep(0.5)
                await page.fill('input[name="password"]', req.password, timeout=8_000)
                await asyncio.sleep(0.5)
                await page.click('button[type="submit"]', timeout=8_000)
            except Exception as e:
                return InstagramLoginResponse(success=False, error=f"Falha ao preencher credenciais: {e}")

            await asyncio.sleep(5)
            try:
                await page.wait_for_url(
                    lambda url: "/accounts/login" not in url,
                    timeout=30_000,
                )
            except Exception:
                pass

            current_url = page.url
            is_logged = "/accounts/login" not in current_url

            if is_logged:
                cookies = await context.cookies()
                return InstagramLoginResponse(success=True, cookies=cookies)
            else:
                return InstagramLoginResponse(
                    success=False,
                    error=f"Login falhou — URL atual: {current_url} (pode ser 2FA ou CAPTCHA)",
                )

    except Exception as exc:
        logging.warning(f"[BROWSER] login_instagram falhou: {exc}")
        return InstagramLoginResponse(success=False, error=str(exc))


# ── /scrape_uc ────────────────────────────────────────────────────────────────
# Usa undetected-chromedriver para sites com anti-bot agressivo (Instagram, etc.)

_UC_DRIVER_PATH = "/usr/bin/chromedriver"
# Ubuntu Noble: chromium-driver instala o browser em /usr/bin/chromium (sem o -browser)
_UC_BROWSER_PATH: Optional[str] = (
    "/usr/bin/chromium"
    if os.path.isfile("/usr/bin/chromium") else
    "/usr/bin/chromium-browser"
    if os.path.isfile("/usr/bin/chromium-browser") else
    None
)


class UCScrapeRequest(BaseModel):
    url: str
    wait_seconds: float = 3.0
    cookies: List[dict] = []


class UCScrapeResponse(BaseModel):
    success: bool
    html: Optional[str] = None
    url: Optional[str] = None
    error: Optional[str] = None


def _run_uc_scrape(url: str, wait_seconds: float, cookies: list) -> str:
    import undetected_chromedriver as uc
    import time as _time

    if not os.path.isfile(_UC_DRIVER_PATH):
        raise RuntimeError(
            f"chromedriver não encontrado em {_UC_DRIVER_PATH}. "
            "Certifique-se que chromium-driver está instalado."
        )
    if _UC_BROWSER_PATH is None:
        raise RuntimeError(
            "Binário do chromium não encontrado. "
            "Instale chromium-driver (apt) para obter /usr/bin/chromium."
        )

    opts = uc.ChromeOptions()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-extensions")
    opts.add_argument(f"--user-agent={random.choice(_UA_POOL)}")
    if EGRESS_PROXY:
        opts.add_argument(f"--proxy-server={EGRESS_PROXY}")

    driver = uc.Chrome(
        options=opts,
        driver_executable_path=_UC_DRIVER_PATH,
        browser_executable_path=_UC_BROWSER_PATH,
        headless=True,
        version_main=None,  # detecta automaticamente via chromedriver instalado
    )
    try:
        if cookies:
            driver.get(f"{urlparse(url).scheme}://{urlparse(url).netloc}/")
            for c in cookies:
                try:
                    driver.add_cookie({k: v for k, v in c.items() if k in ("name", "value", "domain", "path")})
                except Exception:
                    pass

        driver.get(url)
        _time.sleep(max(0.5, wait_seconds))
        return driver.page_source
    finally:
        try:
            driver.quit()
        except Exception:
            pass


@app.post("/scrape_uc", response_model=UCScrapeResponse)
async def scrape_uc(req: UCScrapeRequest):
    err = _validate_url(req.url)
    if err:
        return UCScrapeResponse(success=False, error=f"URL bloqueada: {err}")

    loop = asyncio.get_event_loop()
    try:
        html = await loop.run_in_executor(
            None, _run_uc_scrape, req.url, req.wait_seconds, req.cookies
        )
        return UCScrapeResponse(success=True, html=html, url=req.url)
    except Exception as exc:
        logging.warning(f"[BROWSER/UC] scrape_uc falhou ({req.url}): {exc}")
        return UCScrapeResponse(success=False, error=str(exc), url=req.url)


# ── /link-preview ─────────────────────────────────────────────────────────────
# Busca HTML via curl-cffi (sem Playwright) e extrai OG/meta tags.
# Retorna dados estruturados — sem HTML bruto.

class LinkPreviewRequest(BaseModel):
    url: str


class LinkPreviewResponse(BaseModel):
    success: bool
    url: str
    title: Optional[str] = None
    description: Optional[str] = None
    image: Optional[str] = None
    domain: str = ""
    error: Optional[str] = None


@app.post("/link-preview", response_model=LinkPreviewResponse)
async def link_preview(req: LinkPreviewRequest):
    err = _validate_url(req.url)
    if err:
        return LinkPreviewResponse(success=False, url=req.url, error=f"URL bloqueada: {err}")

    parsed = urlparse(req.url)
    domain = parsed.netloc
    html: Optional[str] = None

    try:
        from curl_cffi.requests import AsyncSession
        fp = random.choice(_CFFI_FINGERPRINTS)
        async with AsyncSession(impersonate=fp, verify=False) as session:
            resp = await session.get(
                req.url,
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
                },
                timeout=15,
                allow_redirects=True,
            )
            html = resp.text
    except Exception as exc:
        logging.warning(f"[BROWSER] link-preview fetch falhou ({req.url}): {exc}")

    if not html:
        return LinkPreviewResponse(success=False, url=req.url, domain=domain, error="fetch falhou")

    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")

        def _meta(*pairs: tuple) -> Optional[str]:
            for prop, attr in pairs:
                tag = soup.find("meta", {attr: prop})
                if tag and tag.get("content"):
                    return tag["content"].strip()
            return None

        title = _meta(
            ("og:title", "property"), ("twitter:title", "name")
        ) or (soup.find("title").get_text().strip() if soup.find("title") else None)

        description = _meta(
            ("og:description", "property"),
            ("twitter:description", "name"),
            ("description", "name"),
        )

        image = _meta(("og:image", "property"), ("twitter:image", "name"))

        if image and image.startswith("/"):
            image = f"{parsed.scheme}://{parsed.netloc}{image}"

        return LinkPreviewResponse(
            success=True,
            url=req.url,
            title=title,
            description=description[:300] if description else None,
            image=image,
            domain=domain,
        )
    except Exception as exc:
        logging.warning(f"[BROWSER] link-preview parse falhou ({req.url}): {exc}")
        return LinkPreviewResponse(success=False, url=req.url, domain=domain, error=str(exc))


class ExtractImagesRequest(BaseModel):
    url: str


class ExtractImagesResponse(BaseModel):
    success: bool
    images: List[str] = []
    url: str = ""
    error: Optional[str] = None


@app.post("/extract-images", response_model=ExtractImagesResponse)
async def extract_images(req: ExtractImagesRequest):
    """
    Carrega a página com Playwright, remove header/footer/nav/aside do DOM via JS
    e retorna todos os src de <img> do conteúdo principal.
    Scroll parcial para disparar lazy-loading antes da extração.
    """
    err = _validate_url(req.url)
    if err:
        return ExtractImagesResponse(success=False, url=req.url, error=f"URL bloqueada: {err}")

    try:
        from playwright_stealth import Stealth as _Stealth

        async with _pool.new_context() as context:
            page = await context.new_page()
            await _Stealth().apply_stealth_async(page)
            await page.goto(req.url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)

            try:
                await page.wait_for_load_state("networkidle", timeout=5_000)
            except Exception:
                pass

            await page.evaluate("window.scrollTo(0, Math.floor(document.body.scrollHeight * 0.5))")
            await asyncio.sleep(1.5)

            images: List[str] = await page.evaluate("""
                () => {
                    const STRUCTURAL = [
                        'header', 'footer', 'nav', 'aside',
                        '[role="banner"]', '[role="navigation"]', '[role="contentinfo"]',
                    ];
                    STRUCTURAL.forEach(sel => {
                        try { document.querySelectorAll(sel).forEach(el => el.remove()); } catch(e) {}
                    });
                    const seen = new Set();
                    const result = [];
                    document.querySelectorAll('img').forEach(img => {
                        const src = img.currentSrc || img.src
                            || img.dataset.src || img.dataset.lazySrc
                            || img.dataset.original || img.getAttribute('data-lazy') || '';
                        if (!src || !src.startsWith('http')) return;
                        const w = img.naturalWidth || img.width || 0;
                        const h = img.naturalHeight || img.height || 0;
                        if ((w > 0 && w < 60) || (h > 0 && h < 60)) return;
                        if (!seen.has(src)) { seen.add(src); result.push(src); }
                    });
                    return result.slice(0, 30);
                }
            """)

        return ExtractImagesResponse(success=True, images=images or [], url=req.url)

    except Exception as exc:
        logging.warning(f"[BROWSER] extract-images falhou ({req.url}): {exc}")
        return ExtractImagesResponse(success=False, error=str(exc), url=req.url)


class ExtractRequest(BaseModel):
    html: str
    url: str

class ExtractResponse(BaseModel):
    success: bool
    markdown: Optional[str] = None
    method: str = "trafilatura"
    error: Optional[str] = None

@app.post("/extract", response_model=ExtractResponse)
def extract(req: ExtractRequest):
    """
    Recebe HTML raw e URL base, retorna markdown processado.
    Usa trafilatura como extrator principal, markdownify como fallback.
    """
    if not req.html:
        return ExtractResponse(success=False, error="html vazio")
    try:
        import trafilatura
        from markdownify import markdownify as _md
        from bs4 import BeautifulSoup
        from urllib.parse import urljoin

        # Attempt 1: trafilatura
        content = trafilatura.extract(req.html, output_format="markdown", include_links=True)

        if not content or len(content.strip()) < 150:
            # Fallback: sanitize with bs4 then markdownify
            soup = BeautifulSoup(req.html, "lxml")
            for element in soup(["script", "style", "noscript", "iframe", "svg",
                                  "nav", "footer", "header", "aside", "form",
                                  "input", "button"]):
                element.decompose()
            for tag in soup.find_all(["a", "img"]):
                if tag.has_attr("href"):
                    tag["href"] = urljoin(req.url, tag["href"])
                if tag.has_attr("src"):
                    tag["src"] = urljoin(req.url, tag["src"])
            allowed_attrs = ["href", "src", "alt", "title"]
            for tag in soup.find_all(True):
                attrs = dict(tag.attrs)
                for attr in attrs:
                    if attr not in allowed_attrs:
                        del tag[attr]
            sanitized = str(soup)
            md_content = _md(sanitized, heading_style="ATX")
            if md_content and len(md_content.strip()) > len(content or ""):
                content = md_content
                return ExtractResponse(success=True, markdown=content, method="markdownify")

        return ExtractResponse(success=bool(content), markdown=content, method="trafilatura")
    except Exception as exc:
        logging.warning(f"[BROWSER] /extract error: {exc}")
        return ExtractResponse(success=False, error=str(exc))


class ParseBingRequest(BaseModel):
    html: str
    query: str

class ParseBingResponse(BaseModel):
    success: bool
    markdown: Optional[str] = None
    results_count: int = 0
    error: Optional[str] = None

@app.post("/parse_bing", response_model=ParseBingResponse)
def parse_bing(req: ParseBingRequest):
    """
    Parseia HTML de resultados do Bing e retorna markdown estruturado.
    """
    if not req.html:
        return ParseBingResponse(success=False, error="html vazio")
    try:
        from bs4 import BeautifulSoup
        import re as _re

        soup = BeautifulSoup(req.html, "lxml")
        lines = [f"# Resultados de busca: {req.query}\n"]
        results_found = 0

        def _decode_bing_url(href: str) -> str:
            import urllib.parse as _up
            m = _re.search(r"[?&]u=([^&]+)", href)
            if m:
                try:
                    encoded = m.group(1).replace("a1", "").replace("aHR0", "aHR0")
                    decoded = _up.unquote(base64.b64decode(encoded + "==").decode("utf-8", errors="ignore"))
                    if decoded.startswith("http"):
                        return decoded
                except Exception:
                    pass
            return href

        for li in soup.select("li.b_algo"):
            h2 = li.select_one("h2 a")
            if not h2:
                continue
            title = h2.get_text(strip=True)
            href = h2.get("href", "")
            if not href.startswith("http"):
                continue
            snippet_tag = li.select_one(".b_caption p, .b_algoSlug, p.b_paractl")
            snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""
            href = _decode_bing_url(href)
            lines.append(f"### {title}")
            lines.append(f"[{href}]({href})")
            if snippet:
                lines.append(snippet)
            lines.append("")
            results_found += 1
            if results_found >= 10:
                break

        if results_found == 0:
            return ParseBingResponse(success=False, error="Nenhum resultado encontrado", results_count=0)

        content = f"# Resultados de busca (Bing): {req.query}\n\n" + "\n".join(lines)
        return ParseBingResponse(success=True, markdown=content, results_count=results_found)
    except Exception as exc:
        logging.warning(f"[BROWSER] /parse_bing error: {exc}")
        return ParseBingResponse(success=False, error=str(exc))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")

"""Web crawler and scraping main tool"""

import asyncio
import base64
import json
import logging
import os
import random
import re
import sys
import tempfile
from contextlib import redirect_stdout, redirect_stderr
from io import BytesIO, StringIO
from pathlib import Path
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse

try:
    from PIL import Image

    HAS_PIL = True
except ImportError:
    HAS_PIL = False

from urllib.parse import urljoin

from .config import get_scraping_proxy
from .setup import get_load_config

# ── Serviços externos ─────────────────────────────────────────────────────────
_EGRESS_PROXY = os.getenv("EGRESS_PROXY_URL", "")
_BROWSER_SERVICE_URL = os.getenv("BROWSER_SERVICE_URL", "").rstrip("/")

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

_BOT_CHALLENGE_SIGNALS = frozenset(
    {
        # Cloudflare
        "just a moment",
        "checking your browser",
        "cf-browser-verification",
        "enable javascript and cookies to continue",
        "ray id",
        "attention required! | cloudflare",
        "please wait while we check your browser",
        "verify you are human",
        # DDoS-Guard / outros
        "ddos-guard",
        "perimeterx",
        "px-captcha",
        "bot management",
        "akamai edge",
        "incapsula incident",
        "sucuri website firewall",
        # MercadoLivre bot protection
        "_bm_skipml",
        "verifychallenge",
        "micro-landing-container",
        "_bmstate",
    }
)

_BOT_CHALLENGE_THRESHOLD = {
    # Sinais muito fortes — basta 1 para confirmar challenge
    "_bm_skipml",
    "cf-browser-verification",
    "ddos-guard",
    "perimeterx",
    "px-captcha",
    "incapsula incident",
}


def _is_bot_challenged(html: Optional[str]) -> bool:
    """Detecta páginas de challenge anti-bot (Cloudflare, MercadoLivre, DDoS-Guard, etc.)."""
    if not html:
        return False
    sample = html[:15_000].lower()
    # Sinal único fortíssimo é suficiente
    for strong_sig in _BOT_CHALLENGE_THRESHOLD:
        if strong_sig in sample:
            return True
    # Caso geral: ≥2 sinais
    hits = sum(1 for sig in _BOT_CHALLENGE_SIGNALS if sig in sample)
    return hits >= 2


_SPA_SHELL_SIGNALS = frozenset(
    {
        # Genérico
        "turn on javascript",
        "enable javascript",
        "requires javascript",
        "javascript is required",
        "you need to enable javascript",
        "please enable javascript",
        "without javascript",
        # Pinterest
        "oh no! pinterest",
        "pinterest doesn't work",
        # React/Next.js apps com conteúdo vazio
        '<div id="root"></div>',
        '<div id="__next"></div>',
        '<div id="app"></div>',
    }
)


def _is_spa_shell(html: Optional[str]) -> bool:
    """Detecta páginas SPA que retornaram shell vazio sem renderização JS."""
    if not html:
        return False
    sample = html[:10_000].lower()
    return any(sig in sample for sig in _SPA_SHELL_SIGNALS)


def _validate_scraping_url(url: str) -> Optional[str]:
    """Retorna mensagem de erro se a URL for interna/inválida, None se permitida."""
    if not url or url.startswith("fetched://"):
        return None
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return f"scheme não permitido: {parsed.scheme}"
    host = (parsed.hostname or "").rstrip(".")
    if not host:
        return "URL sem host"
    if not _FQDN_RE.match(host):
        return f"'{host}' não é um FQDN válido — IPs e hostnames simples são bloqueados"
    tld = host.rsplit(".", 1)[-1].lower()
    if tld in _INTERNAL_TLDS:
        return f"TLD '.{tld}' é reservado para redes internas"
    return None


class ScrapingScrawlingTool:
    """Web crawler tool using LLM-Agnostic Sanitization Pipeline."""

    def __init__(self):
        self.name = "scraping_crawling"
        self.description = "Acessa uma URL e converte para Markdown limpo e semântico."

    # ── Browser Service (container isolado) ──────────────────────────────────

    async def _browser_service_scrape(self, url: str) -> Optional[str]:
        """Chama o browser service isolado. Retorna HTML ou None."""
        if not _BROWSER_SERVICE_URL:
            return None
        try:
            import requests as _req

            resp = await asyncio.to_thread(
                lambda: _req.post(
                    f"{_BROWSER_SERVICE_URL}/scrape",
                    json={"url": url},
                    timeout=45,
                )
            )
            data = resp.json()
            if data.get("success"):
                return data.get("html")
            logging.warning(f"[BROWSER-SVC] scrape erro: {data.get('error')}")
        except Exception as exc:
            logging.warning(f"[BROWSER-SVC] scrape falhou ({url}): {exc}")
        return None

    async def _browser_service_scrape_cffi(
        self, url: str, fingerprint: Optional[str] = None
    ) -> Optional[str]:
        """Chama /scrape_cffi (curl-cffi TLS fingerprint aleatório). Retorna HTML ou None."""
        if not _BROWSER_SERVICE_URL:
            return None
        try:
            import requests as _req

            payload: dict = {"url": url}
            if fingerprint:
                payload["fingerprint"] = fingerprint

            resp = await asyncio.to_thread(
                lambda: _req.post(
                    f"{_BROWSER_SERVICE_URL}/scrape_cffi",
                    json=payload,
                    timeout=35,
                )
            )
            data = resp.json()
            if data.get("success"):
                return data.get("html")
            logging.warning(f"[BROWSER-SVC/CFFI] erro: {data.get('error')}")
        except Exception as exc:
            logging.warning(f"[BROWSER-SVC/CFFI] falhou ({url}): {exc}")
        return None

    async def _browser_service_scrape_uc(
        self, url: str, wait_seconds: float = 4.0
    ) -> Optional[str]:
        """Chama /scrape_uc (undetected-chromedriver) no browser service. Retorna HTML ou None."""
        if not _BROWSER_SERVICE_URL:
            return None
        try:
            import requests as _req

            resp = await asyncio.to_thread(
                lambda: _req.post(
                    f"{_BROWSER_SERVICE_URL}/scrape_uc",
                    json={"url": url, "wait_seconds": wait_seconds},
                    timeout=65,
                )
            )
            data = resp.json()
            if data.get("success"):
                return data.get("html")
            logging.warning(f"[BROWSER-SVC/UC] scrape_uc erro: {data.get('error')}")
        except Exception as exc:
            logging.warning(f"[BROWSER-SVC/UC] scrape_uc falhou ({url}): {exc}")
        return None

    async def _browser_service_execute(
        self,
        url: str,
        script: str,
        cookies: list = [],
        scroll_seconds: int = 0,
        wait_until: str = "domcontentloaded",
        timeout_ms: int = 30_000,
        stealth: bool = False,
    ) -> Optional[dict]:
        """Chama /execute no browser service. Retorna dict com result e html, ou None."""
        if not _BROWSER_SERVICE_URL:
            return None
        try:
            import requests as _req

            resp = await asyncio.to_thread(
                lambda: _req.post(
                    f"{_BROWSER_SERVICE_URL}/execute",
                    json={
                        "url": url,
                        "script": script,
                        "cookies": cookies,
                        "scroll_seconds": scroll_seconds,
                        "wait_until": wait_until,
                        "timeout_ms": timeout_ms,
                        "stealth": stealth,
                    },
                    timeout=max(120, scroll_seconds + 30),
                )
            )
            data = resp.json()
            if data.get("success"):
                return data
            logging.warning(f"[BROWSER-SVC] execute erro: {data.get('error')}")
        except Exception as exc:
            logging.warning(f"[BROWSER-SVC] execute falhou ({url}): {exc}")
        return None

    async def _browser_service_screenshot(self, url: str) -> Optional[dict]:
        """Chama o browser service isolado. Retorna dict com screenshot_base64 ou None."""
        if not _BROWSER_SERVICE_URL:
            return None
        try:
            import requests as _req

            resp = await asyncio.to_thread(
                lambda: _req.post(
                    f"{_BROWSER_SERVICE_URL}/screenshot",
                    json={"url": url},
                    timeout=50,
                )
            )
            data = resp.json()
            if data.get("success"):
                return {"screenshot": data.get("screenshot_base64")}
            logging.warning(f"[BROWSER-SVC] screenshot erro: {data.get('error')}")
        except Exception as exc:
            logging.warning(f"[BROWSER-SVC] screenshot falhou ({url}): {exc}")
        return None

    async def _browser_fetch(
        self,
        url: str,
        proxy: Optional[str] = None,
        profile: str = "browser",
        wait_until: str = "networkidle",
    ) -> Optional[str]:
        """
        Playwright com perfil persistente, stealth e comportamento humano.
        Tenta browser service isolado primeiro; fallback para Playwright local.
        Retorna HTML bruto ou None em caso de falha.
        profile='google' usa perfil/UA separado para não misturar cookies do Google.
        """
        # 1. curl-cffi: TLS fingerprint aleatório, sem browser, mais rápido
        html = await self._browser_service_scrape_cffi(url)
        if html and not _is_bot_challenged(html) and not _is_spa_shell(html):
            logging.info(f"[SCRAPING] cffi OK para {url} ({len(html)} bytes)")
            return html

        if html and _is_spa_shell(html):
            logging.info(
                f"[SCRAPING] cffi retornou SPA shell para {url}, escalando para Playwright"
            )
        elif html:
            logging.warning(
                f"[SCRAPING] cffi retornou challenge para {url}, tentando Playwright"
            )
        else:
            logging.info(f"[SCRAPING] cffi falhou para {url}, tentando Playwright")

        # 2. Playwright + stealth (executa JS, aguarda auto-redirecionamento de challenges)
        html = await self._browser_service_scrape(url)

        # 3. Fallback para undetected-chromedriver se Playwright também retornar challenge
        if _is_bot_challenged(html):
            logging.warning(
                f"[SCRAPING] Challenge detectado no Playwright para {url}, tentando UC"
            )
            html_uc = await self._browser_service_scrape_uc(url)
            if html_uc and not _is_bot_challenged(html_uc):
                logging.info(f"[SCRAPING] UC bypass bem-sucedido para {url}")
                return html_uc
            if html_uc:
                return html_uc if len(html_uc or "") > len(html or "") else html

        if not html:
            logging.warning(f"[SCRAPING] Todos os métodos falharam para {url}")
        return html

    async def _extract_markdown(self, html: str, url: str) -> Optional[str]:
        """Delega extração de markdown ao browser service (/extract)."""
        if not _BROWSER_SERVICE_URL or not html:
            return None
        try:
            import requests as _req

            resp = _req.post(
                f"{_BROWSER_SERVICE_URL}/extract",
                json={"html": html, "url": url},
                timeout=20,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("markdown") if data.get("success") else None
        except Exception as e:
            logging.warning(f"[SCRAPING] /extract error: {e}")
        return None

    def get_proxy(self) -> Optional[str]:
        """Retorna proxy para o browser. Prioridade: rotativo > lista > egress proxy.
        O egress proxy é sempre o fallback mínimo — bloqueia RFC 1918 e hosts internos.
        """
        try:
            load_config = get_load_config()
            if load_config:
                config = load_config()

                # 1. Proxy rotativo externo (anti-bot)
                rotating_url = config.get("rotating_proxy_url", "")
                if rotating_url:
                    return rotating_url

                # 2. Lista de proxies externos
                proxy_list_str = config.get("proxy_list", "")
                if proxy_list_str:
                    proxies = [
                        p.strip() for p in proxy_list_str.split(",") if p.strip()
                    ]
                    if proxies:
                        return random.choice(proxies)

            # 3. Variável de ambiente explícita
            env_proxy = os.getenv("PROXY_URL")
            if env_proxy:
                return env_proxy

        except Exception as e:
            logging.warning(f"[SCRAPING] Erro ao obter proxy: {e}")

        # 4. Egress proxy interno — fallback garantido para bloquear rede interna
        return _EGRESS_PROXY or None

    def _compress_base64_for_vision(self, image_base64: str) -> str:
        """Otimiza imagem base64 para vision (redimensiona para 512x384 em PNG)."""
        if not image_base64 or not image_base64.startswith("data:"):
            return image_base64

        try:
            # Extrair dados do data URI
            parts = image_base64.split(",", 1)
            if len(parts) != 2:
                return image_base64

            header = parts[0]
            data = parts[1]

            # Decodificar base64
            image_bytes = base64.b64decode(data)

            # Criar arquivo temporario
            with tempfile.NamedTemporaryFile(suffix=".tmp", delete=False) as tmp_file:
                tmp_path = Path(tmp_file.name)
                tmp_file.write(image_bytes)

            try:
                from PIL import Image

                logging.info(f"Otimizando favicon ({len(image_bytes)} bytes)...")

                # Redimensionar e converter para PNG
                with Image.open(tmp_path) as img:
                    img.thumbnail((512, 384), Image.Resampling.LANCZOS)

                    if img.mode not in ("RGB", "RGBA"):
                        img = img.convert("RGB")

                    # Salvar como PNG (melhor compatibilidade com modelos de vision)
                    optimized_path = tmp_path.with_suffix(".png")
                    img.save(optimized_path, "PNG", optimize=True)

                # Ler e converter para base64
                with open(optimized_path, "rb") as f:
                    optimized_bytes = f.read()

                optimized_base64 = base64.b64encode(optimized_bytes).decode("utf-8")
                result = f"data:image/png;base64,{optimized_base64}"

                reduction = (
                    (len(image_bytes) - len(optimized_bytes)) / len(image_bytes) * 100
                )
                logging.info(
                    f"Favicon otimizada: {reduction:.1f}% reducao ({len(image_bytes)}B -> {len(optimized_bytes)}B)"
                )

                return result

            finally:
                # Limpar temporarios
                try:
                    if tmp_path.exists():
                        tmp_path.unlink()
                    if optimized_path.exists():
                        optimized_path.unlink()
                except:
                    pass

        except Exception as e:
            logging.warning(f"Erro ao otimizar favicon: {str(e)}")
            return image_base64  # Retorna original se falhar

    async def analyze_favicon_with_vision(
        self,
        favicon_input: str = "",
        page_content: str = "",
        debug: bool = False,
        favicon_url: str = "",
        page_url: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Analisa favicon com modelo de vision do Replicate, usando conteudo da pagina como contexto.

        Tenta enviar URL da favicon direto para melhor eficiencia. Se nao houver URL, usa base64.
        """
        if not favicon_input and not favicon_url:
            return None

        try:
            # Tentar usar URL da favicon direto (mais eficiente)
            image_to_send = (
                favicon_url if favicon_url and favicon_url.startswith("http") else None
            )

            if not image_to_send:
                # Fallback para base64 se URL nao disponivel
                if debug:
                    logging.info(
                        f"[DEBUG-VISION] Favicon URL nao disponivel, usando base64"
                    )
                    logging.info(
                        f"[DEBUG-VISION] Favicon original size: {len(favicon_input)} chars"
                    )
                    logging.info(
                        f"[DEBUG-VISION] Favicon original preview: {favicon_input[:100]}..."
                    )

                # Comprimir favicon antes de enviar (reduz para 512x384, WebP, quality=40)
                image_to_send = self._compress_base64_for_vision(favicon_input)

                if debug:
                    logging.info(
                        f"[DEBUG-VISION] Favicon after compression: {len(image_to_send)} chars"
                    )
                    logging.info(
                        f"[DEBUG-VISION] Favicon format: {image_to_send.split(';')[0] if ';' in image_to_send else 'unknown'}"
                    )
                    logging.info(
                        f"[DEBUG-VISION] Favicon data preview: {image_to_send[:100]}..."
                    )
                    # Verificar se e valido base64
                    if image_to_send.startswith("data:"):
                        try:
                            parts = image_to_send.split(",", 1)
                            if len(parts) == 2:
                                import base64

                                test_decode = base64.b64decode(
                                    parts[1][:100]
                                )  # Testa os primeiros 100 chars
                                logging.info(
                                    f"[DEBUG-VISION] Base64 decode test: SUCCESS ({len(test_decode)} bytes)"
                                )
                            else:
                                logging.warning(
                                    f"[DEBUG-VISION] Base64 format invalid: no comma found"
                                )
                        except Exception as e:
                            logging.error(
                                f"[DEBUG-VISION] Base64 decode test FAILED: {str(e)}"
                            )
            else:
                if debug:
                    logging.info(
                        f"[DEBUG-VISION] Usando URL da favicon direto: {favicon_url}"
                    )
                    logging.info(
                        f"[DEBUG-VISION] URL reduz processamento local - enviando link direto"
                    )

            # Prompt para analise de favicon focado em branding com contexto da pagina
            context_info = ""
            if page_content:
                # Extrair primeiros 5000 chars do conteudo como contexto
                page_context = page_content[:5000].strip()
                context_info = (
                    f"\n\nContexto da pagina\nURL: {page_url}\n\n{page_context}"
                )

            prompt = f"""A imagem fornecida E a favicon que voce deve analisar. Analise APENAS esta favicon que foi extraida e descreva:
1. Composicao visual (icone, texto, forma)
2. Cores principais e o que comunicam
3. Estilo de design (minimalista, flat, moderno, etc)
4. Setor/industria que a favicon representa
5. Qualidade geral do design (escala 1-10)

Responda de forma concisa e profissional.{context_info}"""

            # Carregar OpenAI API key
            try:
                from App.Core.Settings.Settings import get_openai_api_key

                openai_api_key = get_openai_api_key()
                if not openai_api_key:
                    logging.warning(f"[DEBUG-VISION] OpenAI API Key nao configurada")
                    return None
            except Exception as e:
                if debug:
                    logging.error(
                        f"[DEBUG-VISION] Erro ao carregar OpenAI API Key: {e}"
                    )
                return None

            # Request ao OpenAI GPT-4o REST API
            if debug:
                logging.info(f"[DEBUG-VISION] Fazendo request ao OpenAI GPT-4o")
                if image_to_send.startswith("http"):
                    logging.info(f"[DEBUG-VISION] Enviando: URL da favicon (direto)")
                    logging.info(f"[DEBUG-VISION] URL: {image_to_send}")
                else:
                    logging.info(f"[DEBUG-VISION] Enviando: Base64 comprimido")
                    logging.info(f"[DEBUG-VISION] Tamanho: {len(image_to_send)} chars")
                logging.info(f"[DEBUG-VISION] Tamanho do prompt: {len(prompt)} chars")

            try:
                import requests

                headers = {
                    "Authorization": f"Bearer {openai_api_key}",
                    "Content-Type": "application/json",
                }

                payload = {
                    "model": "gpt-4o",
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": image_to_send},
                                },
                            ],
                        }
                    ],
                    "temperature": 0.7,
                }

                response = requests.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=60,
                )

                if response.status_code == 200:
                    data = response.json()
                    analysis_text = data["choices"][0]["message"]["content"].strip()
                    result = {"status": "succeeded", "output": analysis_text}
                else:
                    logging.warning(
                        f"[DEBUG-VISION] OpenAI API falhou ({response.status_code}): {response.text}"
                    )
                    result = {"status": "failed", "output": None}

                if debug and result["status"] == "succeeded":
                    logging.info(f"[DEBUG-VISION] Status: succeeded")
                    logging.info(
                        f"[DEBUG-VISION] Output length: {len(str(result.get('output', '')))}"
                    )
                    logging.info(
                        f"[DEBUG-VISION] Output preview: {str(result.get('output', ''))[:200]}"
                    )

            except Exception as e:
                logging.warning(f"[DEBUG-VISION] Erro ao fazer request: {e}")
                result = {"status": "failed", "output": None}

            if debug:
                logging.info(f"[DEBUG-VISION] Resultado status: {result.get('status')}")

            # Verificar se foi sucesso
            if result.get("status") == "succeeded" and result.get("output"):
                analysis_text = result["output"]

                if analysis_text and analysis_text.strip():
                    logging.info(
                        f"Favicon analisada com vision: {len(analysis_text)} chars"
                    )
                    return {"vision_analysis": analysis_text, "model": "gpt-4o-vision"}
                else:
                    logging.warning(f"Output vazio ou invalido: {analysis_text}")
                    return None
            else:
                logging.warning(f"Request falhou: {result.get('status')}")
                return None

        except Exception as e:
            logging.warning(f"Erro ao analisar favicon com vision: {str(e)}")

            if debug:
                import traceback

                logging.error(f"[DEBUG-VISION] EXCECAO NA ANALISE")
                logging.error(f"[DEBUG-VISION] Erro: {str(e)}")
                logging.error(f"[DEBUG-VISION] Traceback:\n{traceback.format_exc()}")

            return None

    def analyze_screenshot_design(
        self, screenshot_bytes: bytes, origin_url: str, debug: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Analisa screenshot com GPT-4o Vision da OpenAI para extrair informacoes de design.

        Args:
            screenshot_bytes: Bytes da imagem PNG
            origin_url: URL de origem (para referencia)
            debug: Debug mode

        Returns:
            Dict com design_analysis ou None se falhar
        """
        # print(f"[ANALYZE_DESIGN-START] Function called with screenshot_bytes={len(screenshot_bytes)}, origin_url={origin_url}")
        logging.info("[ANALYZE_DESIGN] Iniciando analise de design do screenshot")
        logging.info(
            f"[ANALYZE_DESIGN] screenshot_bytes length: {len(screenshot_bytes)}"
        )
        logging.info(f"[ANALYZE_DESIGN] origin_url: {origin_url}")

        if not screenshot_bytes:
            logging.warning("[ANALYZE_DESIGN] screenshot_bytes esta vazio")
            return None

        # Gerar URL temporaria para o screenshot (retorna screenshot_id e token)
        # print("[ANALYZE_DESIGN] Importing generate_temp_url...")
        from App.Core.Utils.TemporaryScreenshotStore import (
            generate as generate_temp_url,
        )
        from App.Core.Settings.Settings import get_public_url

        # print("[ANALYZE_DESIGN] Calling generate_temp_url()...")
        logging.info(f"[ANALYZE_DESIGN] Chamando generate_temp_url()...")
        result = generate_temp_url(screenshot_bytes, origin_url)
        # print(f"[ANALYZE_DESIGN] generate_temp_url returned: {result}")
        logging.info(f"[ANALYZE_DESIGN] generate_temp_url result: {result}")
        if not result:
            logging.error("[ANALYZE_DESIGN] Erro ao gerar URL temporaria")
            return None

        temp_token, _ = result
        public_url = get_public_url()
        screenshot_url = (
            f"{public_url}/api/screenshot/{temp_token}/view?token={temp_token}"
        )
        # print(f"[ANALYZE_DESIGN] Screenshot URL = '{screenshot_url}'")

        logging.info(f"[ANALYZE_DESIGN] PUBLIC_URL: '{public_url}'")
        logging.info(f"[ANALYZE_DESIGN] URL temporaria: {screenshot_url}")

        # print("[ANALYZE_DESIGN] Entering try block...")
        try:
            # print("[ANALYZE_DESIGN] Building prompt...")
            prompt = """Analise esta captura de tela e extraia informacoes de design em JSON valido (sem markdown, sem codigo blocks):
{
  "colors": [
    {
      "hex": "#RRGGBB",
      "design_name": "Nome da escala de design (ex: Slate-900, Sky-400, Emerald-500)",
      "functional_role": "Funcao exata da cor na UI (ex: 'Fundo de alta densidade visual', 'Accent para affordance de links', 'Texto primario em Dark Mode')",
      "emotion": "Emocao e psicologia associadas (ex: 'Autoridade tecnica e estabilidade', 'Inovacao fluida e clarity de dados')"
    }
  ],
  "typography": {
    "primary_font": "Nome da font (ex: Inter Variable Weight) + peso/estilo e uso especifico",
    "secondary_font": "Nome da font (ex: JetBrains Mono) + peso/estilo e uso especifico (ex: para dados, metricas, codigo)"
  },
  "brand_archetype": "Arquetipo principal identificado (O Heroi, O Sabio, O Criador, etc) + breve explicacao da transformacao que a marca promete (ex: 'O Mago - Transformacao de processos complexos em fluxos simples')",
  "ui_analysis": {
    "border_radius": "Valor exato em px (ex: 8px a 12px) + classificacao de 'temperatura' (ex: 'Soft-Industry') + explicacao psicologica do uso",
    "typography_hierarchy": "Escala matematica utilizada (ex: Major Third 1.25, Perfect Fourth 1.33) + detalhes de peso/estilo em cada nivel + exemplos concretos de como guiam o usuario",
    "animations_microinteractions": "Especificar ease function (ex: ease-out), duracao exata em ms (ex: 200ms), transformacoes (ex: scale 0.98) + impacto na percepcao de responsividade",
    "objects_images": "Tecnicas especificas utilizadas (ex: Glassmorphism, icones de linha fina 2px) + paleta (grayscale, cor, gradiente) + o que cada tecnica comunica",
    "coherence": "Nivel de coerencia visual + grid utilizado (ex: 8px) + como cria 'gramatica visual' previsivel",
    "information_density": "Classificacao (Baixa/Media/Alta) + estrategia de white space (ex: isolamento do CTA) + tecnicas de Progressive Disclosure se aplicavel",
    "microcopy": "Tone of voice (ex: Direct-to-Action, ROI-focused) + exemplos de verbos utilizados (ex: 'Automatize', 'Dispare') + como reduzem friccao",
    "visual_cues": "Tecnicas especificas de direcionamento (ex: Gaze Cueing, contraste de luminancia, leading lines) + elementos que apontam para conversao",
    "social_proof_authority": "Presenca de logos/badges + estilo visual (ex: grayscale com opacity 0.5) + posicionamento na hierarquia visual",
    "friction_analysis": "Tipo de friccao identificada (Friccao Progressiva, Confirmacao Explicita, etc) + exemplo de como a UI gerencia complexidade (ex: Progressive Disclosure mantem porta de entrada simples)"
  },
  "moodboard": "Formato ultra-especifico: [Categoria de produto] + [Estilo de interface] + [Modo de tema] + [Tecnica de iluminacao] + [Composicao] + [Renderizacao] + [Efeitos especificos] + [Paleta HEX exata]. Exemplo: 'Clean Tech SaaS + Automation Dashboard + Dark Mode + Soft rim lighting + Center-weighted + Octane 4K + Glass cards blur 20px, borders opacity 0.1, Inter typography, focus on Golden Path, hyper-minimalist, shadows high-spread low-opacity'",
  "image_description": "Estrutura: [Estilo Artistico] + [Composicao e Enquadramento] + [Elementos Visuais Principais com detalhes] + [Paleta de Cores exata] + [Atmosfera e Tone] + [Tecnica de Renderizacao especifica] + [Optica/Lente]. Exemplo: 'Minimalismo Digital + Hero Section centralizado + Grafico crescimento em gradiente azul, botao CTA pulsante sutil, tipografia sans-serif robusta + Control, efficiency, modernity + Octane Render DOF focado em email input + 85mm equivalent lens'"
}

[CRITICO ABSOLUTO - LEIA COM ATENCAO]:
1. Retorne APENAS JSON SINTATICAMENTE VALIDO. Sem erros de sintaxe.
2. ZERO ```json, ZERO marcadores de codigo, ZERO markdown, ZERO backticks.
3. Comece EXATAMENTE com { e termine EXATAMENTE com }
4. TODA linha que nao e a ultima deve terminar com uma VIRGULA.
5. Nenhuma explicacao. Apenas JSON.
6. Colors: EXATAMENTE 3 cores. Hex obrigatorio em cada uma.
7. Valores SEMPRE especificos (px, ms, escalas matematicas).
8. Moodboard e image_description devem ser detalhados para gerar imagens em primeira tentativa.
9. TESTE MENTALMENTE a sintaxe antes de responder.
10. Se houver duvida, simplifique a resposta mas MANTENHA SINTAXE VALIDA."""

            # print("[ANALYZE_DESIGN] Prompt built successfully")

            if debug:
                logging.info(
                    "[VISION] Analisando screenshot com OpenAI GPT-4o Vision..."
                )
                logging.info(f"[VISION] Screenshot size: {len(screenshot_bytes)} bytes")

            try:
                import base64
                import json
                import requests
                from App.Core.Settings.Settings import get_openai_api_key

                # print("[ANALYZE_DESIGN] Getting OpenAI API key...")
                openai_api_key = get_openai_api_key()
                # print(f"[ANALYZE_DESIGN] OpenAI API key: {'SET' if openai_api_key else 'NOT SET'}")

                if not openai_api_key:
                    logging.warning("[ANALYZE_DESIGN] OpenAI API key nao disponivel")
                    return None

                # Converter screenshot para base64
                screenshot_base64 = base64.b64encode(screenshot_bytes).decode("utf-8")

                # Chamar OpenAI ChatGPT Vision via HTTP request
                # print("[ANALYZE_DESIGN] Calling OpenAI ChatGPT Vision via HTTP...")

                url = "https://api.openai.com/v1/chat/completions"
                headers = {
                    "Authorization": f"Bearer {openai_api_key}",
                    "Content-Type": "application/json",
                }

                payload = {
                    "model": "gpt-4o",
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/png;base64,{screenshot_base64}",
                                    },
                                },
                                {"type": "text", "text": prompt},
                            ],
                        }
                    ],
                }

                # print(f"[ANALYZE_DESIGN] POSTing to {url}")
                response = requests.post(url, headers=headers, json=payload, timeout=60)
                # print(f"[ANALYZE_DESIGN] Response status: {response.status_code}")

                if response.status_code != 200:
                    # print(f"[ANALYZE_DESIGN] Error response: {response.text[:500]}")
                    logging.error(
                        f"[ANALYZE_DESIGN] OpenAI API error: {response.status_code} - {response.text[:500]}"
                    )
                    return None

                response_data = response.json()
                logging.info(
                    f"[ANALYZE_DESIGN] Response received: {response.status_code}"
                )

                # Extrair texto da resposta
                if "choices" in response_data and len(response_data["choices"]) > 0:
                    analysis_text = (
                        response_data["choices"][0]
                        .get("message", {})
                        .get("content", "")
                    )
                    logging.info(
                        f"[ANALYZE_DESIGN] Response text length: {len(analysis_text)} chars"
                    )
                    # print(f"[ANALYZE_DESIGN] Got analysis text: {len(analysis_text)} chars")
                else:
                    # print("[ANALYZE_DESIGN] No choices in response")
                    logging.warning("[ANALYZE_DESIGN] No choices in OpenAI response")
                    return None

                if analysis_text and analysis_text.strip():
                    logging.info("[ANALYZE_DESIGN] Screenshot analisado com sucesso")

                    # Remover markdown code blocks se presentes
                    json_text = analysis_text.strip()
                    if json_text.startswith("```"):
                        # Remove ```json ... ```
                        json_text = (
                            json_text.replace("```json", "").replace("```", "").strip()
                        )

                    try:
                        # Tentar parsear como JSON
                        design_json = json.loads(json_text)
                        logging.info(
                            f"[ANALYZE_DESIGN] JSON parseado com sucesso: {len(str(design_json))} chars"
                        )
                        # print(f"[ANALYZE_DESIGN] Design analysis parsed successfully")
                        return {"design_analysis": design_json, "model": "gpt-4o"}
                    except json.JSONDecodeError as e:
                        logging.warning(
                            f"[ANALYZE_DESIGN] Resposta nao e JSON valido: {e}"
                        )
                        logging.warning(
                            f"[ANALYZE_DESIGN] Primeiro 200 chars: {analysis_text[:200]}"
                        )
                        # print(f"[ANALYZE_DESIGN] Returning raw text (not JSON)")
                        return {"design_analysis": analysis_text, "model": "gpt-4o"}
                else:
                    logging.warning("[ANALYZE_DESIGN] Resposta vazia de OpenAI")
                    # print(f"[ANALYZE_DESIGN] Empty response from OpenAI")
                    return None

            except Exception as e:
                logging.error(f"[ANALYZE_DESIGN] Erro ao fazer request: {str(e)}")
                import traceback

                tb = traceback.format_exc()
                logging.error(f"[ANALYZE_DESIGN] Traceback: {traceback.format_exc()}")
                return None

        except Exception as e:
            # print(f"[ANALYZE_DESIGN] OUTER EXCEPTION: {e}")
            # print(f"[ANALYZE_DESIGN] Exception type: {type(e)}")
            import traceback

            # print(f"[ANALYZE_DESIGN] Traceback: {traceback.format_exc()}")
            logging.error(f"[VISION] Erro ao analisar screenshot: {str(e)}")
            return None

    async def take_screenshot_as_base64(
        self, url: str, proxy: Optional[str] = None, analyze: bool = False
    ) -> Optional[Dict[str, Any]]:
        """Tira screenshot da pagina e retorna como base64."""
        logging.info(f"[SCREENSHOT] URL: {url}, analyze: {analyze}")

        # Browser service isolado tem prioridade
        svc_result = await self._browser_service_screenshot(url)
        if svc_result:
            result = {"screenshot": svc_result.get("screenshot")}
            if analyze:
                screenshot_b64 = svc_result.get("screenshot", "")
                if screenshot_b64.startswith("data:image/png;base64,"):
                    import base64 as _b64

                    png_bytes = _b64.b64decode(screenshot_b64.split(",", 1)[1])
                    design_analysis = self.analyze_screenshot_design(png_bytes, url)
                    if design_analysis:
                        result["design_analysis"] = design_analysis.get(
                            "design_analysis"
                        )
            return result

        logging.warning("[SCREENSHOT] Browser service indisponível")
        return None

    async def extract_favicon_as_base64(self, url: str) -> Optional[Dict[str, str]]:
        """Extrai favicon via HTML scrapeado pelo browser service, converte para PNG.

        Retorna: {"base64": data_uri, "url": favicon_url}
        """
        import base64
        import re as _re

        import requests
        from PIL import Image

        try:
            # Obtém HTML via browser service para extrair URL do favicon
            html = await self._browser_service_scrape(url)
            if not html:
                return None

            # Extrai favicon URL do HTML (link rel icon ou og:image)
            favicon_url: Optional[str] = None
            m = _re.search(
                r'<link[^>]+rel=["\'][^"\']*icon[^"\']*["\'][^>]+href=["\']([^"\']+)["\']',
                html,
                _re.IGNORECASE,
            )
            if not m:
                m = _re.search(
                    r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\'][^"\']*icon[^"\']*["\']',
                    html,
                    _re.IGNORECASE,
                )
            if m:
                favicon_url = m.group(1)
            else:
                m = _re.search(
                    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
                    html,
                    _re.IGNORECASE,
                )
                if m:
                    favicon_url = m.group(1)

            if not favicon_url:
                return None

            # Normaliza URL
            favicon_url_full = (
                favicon_url
                if favicon_url.startswith("http")
                else url.rstrip("/") + "/" + favicon_url.lstrip("/")
            )

            proxies = (
                {"http": _EGRESS_PROXY, "https": _EGRESS_PROXY}
                if _EGRESS_PROXY
                else None
            )
            response = requests.get(favicon_url_full, timeout=10, proxies=proxies)
            if response.status_code != 200:
                return None

            logging.info(f"Favicon URL extraida: {favicon_url_full}")

            try:
                img = Image.open(BytesIO(response.content))
                if img.mode in ("RGBA", "LA", "P"):
                    rgb_img = Image.new("RGB", img.size, (255, 255, 255))
                    rgb_img.paste(
                        img,
                        mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None,
                    )
                    img = rgb_img
                elif img.mode != "RGB":
                    img = img.convert("RGB")

                png_buffer = BytesIO()
                img.save(png_buffer, format="PNG")
                base64_data = base64.b64encode(png_buffer.getvalue()).decode("utf-8")
                return {
                    "base64": f"data:image/png;base64,{base64_data}",
                    "url": favicon_url_full,
                }

            except Exception as e:
                logging.warning(f"Erro ao converter favicon para PNG: {e}")
                content_type = response.headers.get("Content-Type", "image/x-icon")
                base64_data = base64.b64encode(response.content).decode("utf-8")
                return {
                    "base64": f"data:{content_type};base64,{base64_data}",
                    "url": favicon_url_full,
                }

        except Exception as e:
            logging.warning(f"Erro ao extrair favicon como base64: {e}")
            return None

    async def extract_dominant_colors(self, url: str) -> Optional[Dict[str, Any]]:
        """Extrai cores: tenta favicon primeiro, fallback para screenshot."""
        # Tenta favicon primeiro
        result = await self.extract_favicon_as_base64(url)
        if result:
            logging.info("Cores extraidas da favicon")
            return result

        # Fallback para screenshot
        logging.info("Favicon sem cores uteis, usando screenshot")
        return None

    async def execute(
        self,
        url: str,
        css_selector: Optional[str] = None,
        is_google_search: bool = False,
        extract_colors: bool = False,
        debug: bool = False,
        proxy: Optional[str] = None,
        vision_only: bool = False,
        screenshot: bool = False,
    ) -> Dict[str, Any]:
        """Execute web crawling for a given URL using Trafilatura."""
        try:
            # Valida URL antes de qualquer acesso à rede
            url_err = _validate_scraping_url(url)
            if url_err:
                logging.warning(f"[SCRAPING] URL bloqueada: {url_err} — {url}")
                return {"status": "error", "message": f"URL bloqueada: {url_err}"}

            # Obtem proxy se nao fornecido
            if not proxy:
                proxy = self.get_proxy()

            # Visual-analysis: fetch local → Playwright local → Browserbase (produção)
            if vision_only:
                logging.info(
                    "[SCRAPING] Modo vision_only: tentando localmente primeiro"
                )
                result = await self.take_screenshot_as_base64(url, proxy, analyze=True)
                if result:
                    return {
                        "status": "success",
                        "content": url,
                        "type": "visual-analysis",
                        "design_analysis": result.get("design_analysis"),
                    }

                return {"status": "error", "message": "Falha ao capturar screenshot"}

            content = None

            _load_fn = get_load_config()
            _app_config = _load_fn() if _load_fn else {}
            is_production = (
                _app_config.get("environment", "development") == "production"
            )

            # 1. Bing direto (Brave API como fallback se Bing falhar)
            if is_google_search:
                return await self._bing_search_with_brave_fallback(url)

            # 2. Fetch normal — Playwright via browser service, extração delegada ao /extract
            if not content:
                logging.info(f"[SCRAPING] Playwright fetch para {url}")
                html = await self._browser_fetch(
                    url, proxy, profile="browser", wait_until="networkidle"
                )
                if html:
                    content = await self._extract_markdown(html, url)

                if not content:
                    logging.info(
                        f"[SCRAPING] Playwright vazio, tentando scrape_cffi para {url}"
                    )
                    html_cffi = await self._browser_service_scrape_cffi(url)
                    if html_cffi:
                        content = await self._extract_markdown(html_cffi, url)

            if content:
                # Limpeza final de espacos e linhas vazias excessivas
                import re

                content = re.sub(r"\n{3,}", "\n\n", content).strip()
                content = re.sub(r" +", " ", content)  # Remover espacos duplos

                response = {"status": "success", "content": content}

                # Extração de cores/favicon (Mantém lógica existente)
                if extract_colors:
                    try:
                        favicon_data = await self.extract_favicon_as_base64(url)
                        if favicon_data:
                            response["favicon_url"] = favicon_data.get("url")
                    except:
                        pass

                return response
            else:
                return {
                    "status": "error",
                    "message": f"Nao foi possivel extrair conteudo util de {url}",
                }

        except Exception as e:
            import traceback

            logging.error(f"[SCRAPING] Exception ao processar URL {url}: {e}")
            return {"status": "error", "message": str(e)}

    async def _brave_search(self, query_or_url: str, start: int = 0) -> Dict[str, Any]:
        """
        Executa busca via Brave Search API (produção).
        Aceita query de texto ou URL completa do Google Search (extrai a query).
        Retorna conteúdo formatado em markdown compatível com o formato padrão do crawler.
        """
        import aiohttp
        from urllib.parse import urlparse, parse_qs, unquote_plus

        # Extrai query se for URL do Google
        if query_or_url.startswith("http"):
            parsed = urlparse(query_or_url)
            qs = parse_qs(parsed.query)
            query = unquote_plus(qs.get("q", [""])[0])
            start = int(qs.get("start", [start])[0])
        else:
            query = query_or_url

        if not query:
            return {"status": "error", "message": "Query vazia para Brave Search"}

        _load_fn = get_load_config()
        _cfg = _load_fn() if _load_fn else {}
        api_key = _cfg.get("brave_search_api_key") or os.getenv(
            "BRAVE_SEARCH_API_KEY", ""
        )

        if not api_key:
            return {
                "status": "error",
                "message": "BRAVE_SEARCH_API_KEY não configurado",
            }

        offset = (start // 10) if start else 0
        params = {
            "q": query,
            "count": 10,
            "offset": offset,
            "country": "BR",
            "ui_lang": "pt-BR",
        }
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": api_key,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    params=params,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        return {
                            "status": "error",
                            "message": f"Brave Search HTTP {resp.status}: {text[:200]}",
                        }
                    data = await resp.json()

            results = data.get("web", {}).get("results", [])
            if not results:
                return {
                    "status": "error",
                    "message": "Nenhum resultado retornado pelo Brave Search",
                }

            lines = ["# Search Results\n"]
            for r in results:
                title = r.get("title", "")
                link = r.get("url", "")
                snippet = r.get("description", "")
                lines.append(f"### {title}")
                lines.append(f"[{link}]({link})")
                if snippet:
                    lines.append(snippet)
                lines.append("")

            content = "\n".join(lines)
            return {"status": "success", "content": content}

        except Exception as e:
            logging.warning(f"[SERP] Erro na chamada SerpAPI: {e}")
            return {"status": "error", "message": str(e)}

    async def _bing_search_with_brave_fallback(
        self, query_or_url: str
    ) -> Dict[str, Any]:
        """Tenta Bing; se falhar e Brave API estiver configurada, usa Brave como fallback final."""
        result = await self._bing_search(query_or_url)
        if result.get("status") == "success":
            return result

        logging.warning(
            "[SCRAPING] Bing falhou — tentando Brave Search API como fallback final"
        )
        brave_result = await self._brave_search(query_or_url)
        if brave_result.get("status") == "success":
            return brave_result

        # Todos falharam — retorna o erro do Bing (mais descritivo)
        return result

    @staticmethod
    def _decode_bing_url(href: str) -> str:
        """Decodifica URLs de tracking do Bing (base64 no param u=a1...)."""
        import base64 as _b64
        from urllib.parse import urlparse as _up, parse_qs as _pq

        try:
            if "bing.com/ck/" in href:
                qs = _pq(_up(href).query)
                u = qs.get("u", [""])[0]
                if u.startswith("a1"):
                    decoded = _b64.b64decode(u[2:] + "==").decode(
                        "utf-8", errors="ignore"
                    )
                    if decoded.startswith("http"):
                        return decoded
        except Exception:
            pass
        return href

    async def _bing_search(self, query_or_url: str) -> Dict[str, Any]:
        """
        Busca via Bing usando curl-cffi (TLS fingerprint aleatório).
        Fallback quando Google retorna CAPTCHA. Funciona sem API key.
        Aceita query de texto ou URL do Google (extrai a query).
        """
        import re as _re
        from urllib.parse import urlparse, parse_qs, unquote_plus, quote_plus

        # Extrai query se for URL do Google
        if query_or_url.startswith("http") and "google" in query_or_url:
            parsed = urlparse(query_or_url)
            qs = parse_qs(parsed.query)
            query = unquote_plus(qs.get("q", [""])[0])
        else:
            query = query_or_url

        if not query:
            return {"status": "error", "message": "Query vazia para Bing Search"}

        bing_url = f"https://www.bing.com/search?q={quote_plus(query)}&mkt=pt-BR&setlang=pt-BR&count=10"
        logging.info(f"[BING] Buscando: {query[:80]}")

        try:
            html = await self._browser_service_scrape_cffi(bing_url)
            if not html:
                return {
                    "status": "error",
                    "message": "Bing: sem resposta do browser service",
                }

            # Verifica se foi bloqueado
            if any(
                s in html[:3000].lower()
                for s in ["captcha", "blocked", "unusual traffic"]
            ):
                return {"status": "error", "message": "Bing também retornou bloqueio"}

            # Delega parse ao browser service (/parse_bing)
            if not _BROWSER_SERVICE_URL:
                return {
                    "status": "error",
                    "message": "BROWSER_SERVICE_URL não configurada",
                }
            try:
                import requests as _req

                resp = _req.post(
                    f"{_BROWSER_SERVICE_URL}/parse_bing",
                    json={"html": html, "query": query},
                    timeout=15,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("success"):
                        logging.info(
                            f"[BING] Extração OK: {data.get('results_count')} resultados"
                        )
                        return {"status": "success", "content": data["markdown"]}
            except Exception as _e:
                logging.warning(f"[BING] /parse_bing error: {_e}")

            return {
                "status": "error",
                "message": "Bing: não foi possível extrair resultados",
            }

        except Exception as e:
            logging.warning(f"[BING] Erro: {e}")
            return {"status": "error", "message": str(e)}

    async def execute_multiple(
        self, searches: list, debug: bool = False, proxy: Optional[str] = None
    ) -> Dict[str, Any]:
        """Processa multiplas pesquisas em paralelo usando o novo motor Trafilatura."""
        if not searches or not isinstance(searches, list):
            return {
                "status": "error",
                "message": "searches deve ser uma lista nao-vazia",
            }

        logging.info(
            f"[SCRAPING] Processando {len(searches)} pesquisas em paralelo (Motor: Trafilatura)..."
        )

        # Trafilatura é leve, podemos aumentar a concorrência
        semaphore = asyncio.Semaphore(5)

        async def execute_task(search_item):
            async with semaphore:
                url = None
                is_google = False
                search_type = "fetch"
                search_content = ""

                if search_item.get("fetch"):
                    url = search_item.get("fetch", "").strip()
                    search_content = url
                elif search_item.get("query"):
                    search_content = search_item.get("query", "").strip()
                    url = f"https://www.google.com/search?q={search_content.replace(' ', '+')}"
                    is_google = True
                    search_type = "query"
                elif search_item.get("visual-analysis"):
                    url = search_item.get("visual-analysis", "").strip()
                    search_type = "visual-analysis"
                    search_content = url

                if not url:
                    return {"status": "error", "message": "Busca invalida"}

                res = await self.execute(
                    url=url,
                    is_google_search=is_google,
                    vision_only=(search_type == "visual-analysis"),
                    proxy=proxy,
                )

                if res.get("status") == "success":
                    return {
                        "type": search_type,
                        "search": search_content,
                        "status": "success",
                        "content": res.get("content"),
                        "design_analysis": res.get("design_analysis"),
                    }
                return {
                    "type": search_type,
                    "search": search_content,
                    "status": "error",
                    "message": res.get("message"),
                }

        tasks = [execute_task(s) for s in searches if isinstance(s, dict)]
        if not tasks:
            return {"status": "error", "message": "Nenhuma pesquisa valida"}

        task_results = await asyncio.gather(*tasks)
        success_count = sum(1 for r in task_results if r.get("status") == "success")

        return {
            "status": "success" if success_count > 0 else "error",
            "results": task_results,
            "total": len(task_results),
            "success_count": success_count,
        }

    async def execute_specific_source_research(
        self,
        site: str,
        terms: list,
        pages: int,
    ) -> Dict[str, Any]:
        """
        Researches Google for terms within a specific domain using the site: operator.

        Builds URLs: https://www.google.com/search?q=site:{domain}+"{term}"&start={N}
        where N increments by 10 for each page (0, 10, 20...).

        Args:
            site: Domain to search within (e.g. "instagram.com", "linkedin.com")
            terms: List of search terms
            pages: Number of Google index pages to scrape per term

        Returns:
            {status, site, terms, pages_per_term, total_pages_scraped, success_count, results}
        """
        from urllib.parse import quote_plus

        domain = site.replace("https://", "").replace("http://", "").rstrip("/")

        _load_fn = get_load_config()
        _app_config = _load_fn() if _load_fn else {}
        is_production = _app_config.get("environment", "development") == "production"

        async def scrape_page(term: str, page_idx: int):
            start = page_idx * 10
            # Brave não suporta aspas duplas ao redor do termo; Google/Playwright sim
            brave_query = f"site:{domain} {term}"
            google_query = f'site:{domain} "{term}"'
            encoded = quote_plus(google_query)
            url = f"https://www.google.com/search?q={encoded}&start={start}"
            try:
                if is_production:
                    res = await self._brave_search(brave_query, start=start)
                else:
                    res = await self.execute(
                        url, is_google_search=True, extract_colors=False
                    )
                return {
                    "site": domain,
                    "term": term,
                    "page": page_idx + 1,
                    "start": start,
                    "url": url,
                    "status": res.get("status"),
                    "content": res.get("content", "")
                    if res.get("status") == "success"
                    else "",
                    "error": res.get("message")
                    if res.get("status") != "success"
                    else None,
                }
            except Exception as e:
                logging.error(f"[SPECIFIC_SOURCE] Erro p{page_idx+1} '{term}': {e}")
                return {
                    "site": domain,
                    "term": term,
                    "page": page_idx + 1,
                    "start": start,
                    "url": url,
                    "status": "error",
                    "content": "",
                    "error": str(e),
                }

        all_results = []
        for term in terms:
            for page_idx in range(pages):
                result = await scrape_page(term, page_idx)
                all_results.append(result)
                # Delay anti-bot após cada página carregada, exceto a última
                if page_idx < pages - 1 or term != terms[-1]:
                    await asyncio.sleep(random.uniform(2.0, 5.0))

        success_count = sum(1 for r in all_results if r["status"] == "success")

        return {
            "status": "success" if success_count > 0 else "error",
            "site": domain,
            "terms": terms,
            "pages_per_term": pages,
            "total_pages_scraped": len(all_results),
            "success_count": success_count,
            "results": list(all_results),
        }

    async def execute_pain_mapping(
        self, input_str: str, debug: bool = False
    ) -> Dict[str, Any]:
        """
        Mapeia dores de concorrentes atraves de reviews em Google Maps e Trustpilot.

        Args:
            input_str: Dominio (ex: make.com) ou Nome + Cidade (ex: Xavier Camargo Imobiliaria, Rio Claro)
            debug: Debug mode (headless=False quando True)

        Returns:
            {
                "status": "success",
                "type": "pain_mapping",
                "google_maps_reviews": [...],  # 100 piores reviews com 200+ chars
                "trustpilot_reviews": [...],   # 100 piores reviews com 200+ chars
                "pain_analysis": "Analise consolidada de dores"
            }
        """
        logging.info(f"[PAIN_MAPPING] Iniciando mapeamento de dores para: {input_str}")
        logging.info(f"[PAIN_MAPPING] Debug mode: {debug} (headless={not debug})")

        google_maps_reviews = []
        trustpilot_reviews = []

        # Verificar se e dominio (contem ponto) ou nome + cidade
        is_domain = "." in input_str and "," not in input_str

        try:
            # =================================================================
            # 1. BUSCAR REVIEWS NO TRUSTPILOT
            # =================================================================
            if is_domain:
                domain = input_str.strip()
                logging.info(
                    f"[PAIN_MAPPING] Buscando Trustpilot para dominio: {domain}"
                )
                trustpilot_reviews = await self._extract_trustpilot_reviews(
                    domain, debug
                )
            else:
                # Tentar extrair dominio de busca em Google Maps
                logging.info(f"[PAIN_MAPPING] Buscando Google Maps para: {input_str}")
                maps_url = await self._find_google_maps_url(input_str, debug)
                if maps_url:
                    maps_reviews = await self._extract_google_maps_reviews(
                        maps_url, debug
                    )
                    google_maps_reviews.extend(maps_reviews)

                    # Tentar extrair dominio do nome da empresa para Trustpilot
                    domain = input_str.split(",")[0].strip().lower().replace(" ", "")
                    if domain:
                        logging.info(
                            f"[PAIN_MAPPING] Tentando Trustpilot com: {domain}"
                        )
                        trustpilot_reviews = await self._extract_trustpilot_reviews(
                            domain, debug
                        )

            # =================================================================
            # 2. CONSOLIDAR E ANALISAR DORES
            # =================================================================
            all_reviews = google_maps_reviews + trustpilot_reviews
            pain_analysis = self._analyze_pains(all_reviews)

            logging.info(f"[PAIN_MAPPING] Total reviews extraidos: {len(all_reviews)}")

            return {
                "status": "success",
                "type": "pain_mapping",
                "google_maps_reviews": google_maps_reviews[:100],  # Top 100
                "trustpilot_reviews": trustpilot_reviews[:100],  # Top 100
                "pain_analysis": pain_analysis,
            }

        except Exception as e:
            logging.error(f"[PAIN_MAPPING] Erro ao mapear dores: {str(e)}")
            import traceback

            logging.error(f"[PAIN_MAPPING] Traceback: {traceback.format_exc()}")
            return {"status": "error", "message": f"Erro ao mapear dores: {str(e)}"}

    async def _find_google_maps_url(
        self, company_location: str, debug: bool = False
    ) -> Optional[str]:
        """Busca URL de reviews no Google Search via browser service."""
        google_url = (
            f"https://www.google.com/search?q={company_location.replace(' ', '+')}"
        )
        logging.info(f"[PAIN_MAPPING] Buscando no Google Search: {company_location}")

        _script = """
        () => {
            for (let el of document.querySelectorAll('*')) {
                if (/\\d+\\s*avalia|\\d+\\s*review/i.test(el.textContent)) {
                    let cur = el;
                    for (let i = 0; i < 10; i++) {
                        if (cur.tagName === 'A' && cur.href) return { href: cur.href, text: cur.textContent };
                        cur = cur.parentElement;
                        if (!cur) break;
                    }
                }
            }
            const m = document.querySelector('a[href*="/maps/place/"]');
            return m ? { href: m.href, text: m.textContent } : null;
        }
        """

        try:
            data = await self._browser_service_execute(
                url=google_url,
                script=_script,
                wait_until="domcontentloaded",
                stealth=True,
            )
            if data and data.get("result") and data["result"].get("href"):
                href = data["result"]["href"]
                logging.info(f"[PAIN_MAPPING] Link encontrado: {href[:100]}")
                return href
            logging.warning("[PAIN_MAPPING] Nenhum link de avaliacoes encontrado")
        except Exception as e:
            logging.warning(f"[PAIN_MAPPING] Erro ao buscar reviews: {e}")
        return None

    async def _extract_google_maps_reviews(
        self, maps_url: str, debug: bool = False
    ) -> List[Dict[str, Any]]:
        """Extrai reviews do Google Maps via browser service (scroll 90s + JS)."""
        logging.info(
            "[PAIN_MAPPING] Extraindo reviews do Google Maps (browser service)..."
        )

        _js = """
        () => {
            const reviews = [];
            document.querySelectorAll('[data-review-id],[role="article"],.jxjwge').forEach(el => {
                try {
                    let rating = 0;
                    const al = el.getAttribute('aria-label') || '';
                    const m = al.match(/(\\d+[,.]\\d+|\\d+)\\s*(?:de|out of|star)/i);
                    if (m) rating = Math.round(parseFloat(m[1].replace(',','.')));
                    if (!rating) { const dr = el.getAttribute('data-rating'); if (dr) rating = parseInt(dr); }
                    let text = '';
                    for (let p of el.querySelectorAll('p,div[role="paragraph"],[role="button"]')) {
                        const t = p.textContent.trim();
                        if (t.length > 30) { text = t; break; }
                    }
                    if (!text) text = el.textContent.trim().substring(0, 500);
                    if (rating >= 1 && rating <= 5 && text.length > 10)
                        reviews.push({ rating, text: text.substring(0, 1000) });
                } catch(e) {}
            });
            return reviews;
        }
        """

        try:
            data = await self._browser_service_execute(
                url=maps_url,
                script=_js,
                scroll_seconds=90,
                wait_until="domcontentloaded",
                timeout_ms=30_000,
                stealth=True,
            )
            if not data:
                logging.warning(
                    "[PAIN_MAPPING] Browser service indisponível (Google Maps)"
                )
                return []

            reviews_with_ratings = data.get("result") or []
            html_content = data.get("html") or ""

            if reviews_with_ratings:
                logging.info(
                    f"[PAIN_MAPPING] {len(reviews_with_ratings)} reviews via JS"
                )
                fallback_reviews = reviews_with_ratings
            else:
                fallback_reviews = self._parse_google_maps_html(html_content)
                logging.info(
                    f"[PAIN_MAPPING] Parser HTML: {len(fallback_reviews)} reviews"
                )

            if not fallback_reviews:
                return []

            rating_counts: dict = {}
            for r in fallback_reviews:
                rating_counts[r.get("rating", 5)] = (
                    rating_counts.get(r.get("rating", 5), 0) + 1
                )
            logging.info(f"[PAIN_MAPPING] Ratings: {rating_counts}")

            sorted_reviews = sorted(fallback_reviews, key=lambda x: x.get("rating", 5))
            if len(sorted_reviews) >= 100:
                return [r for r in sorted_reviews if len(r.get("text", "")) >= 200]
            return sorted_reviews

        except Exception as e:
            logging.warning(
                f"[PAIN_MAPPING] Erro ao extrair reviews do Google Maps: {e}"
            )
            return []

    async def _extract_trustpilot_reviews(
        self, domain: str, debug: bool = False
    ) -> List[Dict[str, Any]]:
        """Extrai reviews do Trustpilot via browser service (scroll + parse HTML)."""
        trustpilot_url = f"https://br.trustpilot.com/review/{domain}?languages=all&stars=1&stars=2&stars=3"
        logging.info(
            f"[PAIN_MAPPING] Extraindo reviews do Trustpilot: {trustpilot_url}"
        )

        try:
            data = await self._browser_service_execute(
                url=trustpilot_url,
                script="() => document.querySelectorAll('article').length",
                scroll_seconds=15,
                wait_until="networkidle",
                timeout_ms=35_000,
            )
            if not data:
                logging.warning(
                    "[PAIN_MAPPING] Browser service indisponível (Trustpilot)"
                )
                return []

            html_content = data.get("html") or ""
            logging.info(f"[PAIN_MAPPING] HTML Trustpilot: {len(html_content)} chars")

            reviews_data = self._parse_trustpilot_html(html_content)
            logging.info(f"[PAIN_MAPPING] Parser encontrou {len(reviews_data)} reviews")

            if not reviews_data:
                return []

            _NEG1 = ["pessimo", "horrivel", "pessima", "horror", "nunca"]
            _NEG2 = [
                "ruim",
                "decepcionado",
                "decepcao",
                "frustr",
                "problema",
                "nao recomendo",
            ]
            _POS = ["excelente", "maravilh", "perfeito", "recomendo", "otimo", "adorei"]
            for review in reviews_data:
                text = review.get("text", "").lower()
                if any(w in text for w in _NEG1):
                    review["rating"] = 1
                elif any(w in text for w in _NEG2):
                    review["rating"] = 2
                elif any(w in text for w in _POS):
                    review["rating"] = 5

            sorted_reviews = sorted(reviews_data, key=lambda x: x.get("rating", 5))
            if len(sorted_reviews) >= 100:
                return [r for r in sorted_reviews if len(r.get("text", "")) >= 200]
            return sorted_reviews

        except Exception as e:
            logging.warning(
                f"[PAIN_MAPPING] Erro ao extrair reviews do Trustpilot: {e}"
            )
            return []

    def _parse_google_maps_html(self, html: str) -> List[Dict[str, Any]]:
        """
        Fallback parser para Google Maps usando HTML bruto.
        Extrai TODOS os reviews encontrados, agrupando por rating.
        """
        import re

        reviews = []

        try:
            # Remover scripts e estilos
            clean_html = re.sub(
                r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE
            )
            clean_html = re.sub(
                r"<style[^>]*>.*?</style>",
                "",
                clean_html,
                flags=re.DOTALL | re.IGNORECASE,
            )

            # Estrategia 1: Procurar TODOS os padroes de rating
            # Captura: numero 1-5 + contexto antes + texto da review

            # Padrao expandido: procurar numeros de rating em qualquer contexto
            rating_sections = re.finditer(
                r"([1-5])\s*(?:?|de 5|out of 5|estrela)", clean_html, re.IGNORECASE
            )

            for match in rating_sections:
                try:
                    rating = int(match.group(1))
                    pos = match.start()

                    # Extrair contexto: 500 chars antes e 1500 chars depois
                    start = max(0, pos - 500)
                    end = min(len(clean_html), pos + 1500)
                    context = clean_html[start:end]

                    # Procurar por blocos de texto apos o rating (20+ chars)
                    texts = re.findall(
                        r">([^<]{20,1000}?)</(?:div|p|span|article)>", context
                    )

                    if texts:
                        for text in texts:
                            text_clean = re.sub(r"\s+", " ", text).strip()
                            text_clean = re.sub(
                                r"^[^\w]*", "", text_clean
                            )  # Remove simbolos no inicio

                            # Manter se tiver mais de 10 caracteres
                            if len(text_clean) > 10 and len(text_clean) < 2000:
                                # Evitar texts muito curtos (ex: "Rating", "Author", etc)
                                if not any(
                                    kw in text_clean.lower()
                                    for kw in ["rating", "author", "data", "date"]
                                ):
                                    reviews.append(
                                        {
                                            "rating": rating,
                                            "author": "Anonimo",
                                            "date": "",
                                            "text": text_clean[:1000],
                                        }
                                    )
                                    break  # Pegar apenas o primeiro texto significativo
                except (ValueError, IndexError, AttributeError):
                    pass

            logging.info(
                f"[PAIN_MAPPING] Parser estrategia 1: encontrou {len(reviews)} reviews"
            )

            # Estrategia 2: Se poucos reviews, procurar por padroes alternados
            if len(reviews) < 50:
                logging.info(
                    f"[PAIN_MAPPING] Parser estrategia 2: tentando padrao alternado"
                )

                # Procurar padrao: estrelas/numeros + nome (maiuscula) + texto
                alt_pattern = r"(?:?|[1-5]\s*de 5)[^<]*?>([A-Z][^<]{3,50}?)<[^>]*>([^<]{40,1000}?)<"
                alt_matches = re.finditer(alt_pattern, clean_html, re.IGNORECASE)

                for match in alt_matches:
                    try:
                        # Tentar extrair rating do contexto
                        rating = 3  # Default
                        # Procurar rating nos 200 chars antes
                        before_text = clean_html[
                            max(0, match.start() - 200) : match.start()
                        ]
                        rating_match = re.search(
                            r"([1-5])\s*(?:?|de 5)", before_text, re.IGNORECASE
                        )
                        if rating_match:
                            rating = int(rating_match.group(1))

                        text = re.sub(r"\s+", " ", match.group(2)).strip()

                        if len(text) > 30 and len(text) < 2000:
                            reviews.append(
                                {
                                    "rating": rating,
                                    "author": (
                                        match.group(1).strip()
                                        if match.group(1)
                                        else "Anonimo"
                                    ),
                                    "date": "",
                                    "text": text[:1000],
                                }
                            )
                    except (ValueError, IndexError, AttributeError):
                        pass

            logging.info(
                f"[PAIN_MAPPING] Parser: total de {len(reviews)} reviews encontrados"
            )

        except Exception as e:
            logging.warning(f"[PAIN_MAPPING] Erro ao fazer parsing HTML: {str(e)}")

        # Remove duplicates (comparar primeiros 100 chars do texto)
        unique_reviews = []
        seen_texts = set()
        for review in reviews:
            text_key = review["text"][:100]
            if text_key not in seen_texts:
                seen_texts.add(text_key)
                unique_reviews.append(review)

        logging.info(
            f"[PAIN_MAPPING] Parser final: {len(unique_reviews)} reviews unicos"
        )
        return unique_reviews

    def _parse_trustpilot_html(self, html: str) -> List[Dict[str, Any]]:
        """
        Parser otimizado para Trustpilot usando HTML renderizado.
        Busca por <article> tags com class contendo 'reviewCard'.
        """
        import re

        reviews = []

        try:
            # Padrao: Procurar por article tags com class reviewCard
            review_pattern = (
                r'<article[^>]*?class="[^"]*reviewCard[^"]*"[^>]*?>.*?</article>'
            )
            matches = re.finditer(review_pattern, html, re.DOTALL | re.IGNORECASE)

            for match in matches:
                review_html = match.group(0)

                try:
                    # Extrair rating - procurar no atributo alt da imagem de stars
                    rating_match = re.search(
                        r'alt="Avaliado com (\d) de um total de',
                        review_html,
                        re.IGNORECASE,
                    )
                    if not rating_match:
                        # Fallback: procurar por "out of 5"
                        rating_match = re.search(
                            r"(\d)\s*out of\s*5", review_html, re.IGNORECASE
                        )
                    if not rating_match:
                        # Fallback: procurar por aria-label
                        rating_match = re.search(
                            r'aria-label="(\d)\s*(?:star|estrela)',
                            review_html,
                            re.IGNORECASE,
                        )

                    rating = int(rating_match.group(1)) if rating_match else None
                    if not rating:
                        continue  # Pular se nao conseguir extrair rating

                    # Extrair autor - procurar na tag span com class consumerName
                    author_match = re.search(
                        r'<span[^>]*?styles_consumerName__[^"]*"[^>]*?>([^<]+)</span>',
                        review_html,
                        re.IGNORECASE,
                    )
                    author = (
                        author_match.group(1).strip() if author_match else "Anonimo"
                    )

                    # Extrair data - procurar na tag time
                    date_match = re.search(
                        r"<time[^>]*?>([^<]+)</time>", review_html, re.IGNORECASE
                    )
                    date = date_match.group(1).strip() if date_match else ""

                    # Extrair texto do review - procurar por <p> tags
                    text = ""

                    # Metodo 1: Procurar por paragrafo com data-relevant-review-text-typography
                    text_match = re.search(
                        r'data-relevant-review-text-typography="true"[^>]*?>([^<]+)</p>',
                        review_html,
                        re.IGNORECASE | re.DOTALL,
                    )
                    if text_match:
                        text = text_match.group(1).strip()

                    # Metodo 2: Se nao encontrou, procurar todas as <p> tags
                    if not text:
                        p_matches = re.findall(
                            r"<p[^>]*>([^<]+)</p>",
                            review_html,
                            re.IGNORECASE | re.DOTALL,
                        )
                        # Pegar a primeira que tem mais de 10 caracteres
                        for p_text in p_matches:
                            p_clean = p_text.strip()
                            if len(p_clean) > 10:
                                text = p_clean
                                break

                    # Limpar texto
                    text = re.sub(r"\s+", " ", text).strip()

                    # Validar
                    if len(text) > 10:
                        reviews.append(
                            {
                                "rating": rating,
                                "author": author,
                                "date": date,
                                "text": text,
                            }
                        )
                        logging.debug(
                            f"[PAIN_MAPPING] Review extraido: {rating}? - {author} ({len(text)} chars)"
                        )

                except Exception as e:
                    logging.debug(f"[PAIN_MAPPING] Erro ao extrair review: {e}")
                    continue

        except Exception as e:
            logging.warning(
                f"[PAIN_MAPPING] Erro ao fazer fallback parsing HTML: {str(e)}"
            )

        return reviews[:100]

    def _parse_google_maps_reviews(
        self, content: str, debug: bool = False
    ) -> List[Dict[str, Any]]:
        """Parse reviews from Google Maps markdown content."""
        import re

        reviews = []

        # Regex para extrair reviews (estrutura basica do Google Maps)
        # Padrao: "Rating" "Author" "Date" "Text"
        review_pattern = r"(\d)?.*?(?=\d?|$)"

        matches = re.finditer(review_pattern, content, re.DOTALL | re.IGNORECASE)

        for match in matches:
            review_text = match.group(0).strip()

            # Extrair rating
            rating_match = re.search(r"(\d)?", review_text)
            rating = int(rating_match.group(1)) if rating_match else 3

            # Extrair autor e data (simplificado)
            lines = review_text.split("\n")
            author = lines[1] if len(lines) > 1 else "Anonimo"
            date = ""
            text = "\n".join(lines[2:]) if len(lines) > 2 else review_text

            reviews.append(
                {"rating": rating, "author": author, "date": date, "text": text.strip()}
            )

        return reviews

    def _parse_trustpilot_reviews(
        self, content: str, debug: bool = False
    ) -> List[Dict[str, Any]]:
        """Parse reviews from Trustpilot markdown content."""
        import re

        reviews = []

        # Regex para extrair reviews (estrutura Trustpilot)
        # Padrao: "Rating Stars" "Title" "Author" "Date" "Text"
        lines = content.split("\n")

        for i, line in enumerate(lines):
            # Procurar padrao de rating (??? ou 3 stars)
            if "?" in line or "stars" in line.lower():
                # Extrair rating
                rating_match = re.search(r"(\d)[\s?]*", line)
                rating = int(rating_match.group(1)) if rating_match else 3

                # Proximas linhas contem autor, data e texto
                author = lines[i + 1] if i + 1 < len(lines) else "Anonimo"
                date = lines[i + 2] if i + 2 < len(lines) else ""
                text = lines[i + 3] if i + 3 < len(lines) else ""

                if len(text.strip()) > 10:  # Apenas se houver texto significativo
                    reviews.append(
                        {
                            "rating": rating,
                            "author": author.strip(),
                            "date": date.strip(),
                            "text": text.strip(),
                        }
                    )

        return reviews

    def _analyze_pains(self, reviews: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Analisa reviews consolidados e identifica principais dores.

        Args:
            reviews: Lista de reviews extraidos

        Returns:
            Dicionario com analise consolidada de dores em formato JSON
        """
        if not reviews:
            return {"total_reviews": 0, "pain_types": [], "reviews": []}

        # Consolidar textos
        all_texts = " ".join([r.get("text", "") for r in reviews])

        # Palavras-chave para identificar dores comuns
        pain_keywords = {
            "suporte": ["suporte", "atendimento", "resposta", "ajuda", "support"],
            "preco": ["caro", "preco", "custo", "valor", "expensive", "price"],
            "interface": [
                "interface",
                "usabilidade",
                "confuso",
                "complexo",
                "dificil",
                "ui",
                "ux",
            ],
            "confiabilidade": [
                "bugs",
                "erro",
                "crash",
                "falha",
                "nao funciona",
                "problema",
                "issue",
            ],
            "funcionalidades": [
                "falta",
                "inexistente",
                "nao tem",
                "missing",
                "feature",
            ],
            "performance": ["lento", "demora", "lag", "slow", "speed"],
            "documentacao": ["documentacao", "guia", "tutorial", "help", "manual"],
            "integracao": ["integracao", "api", "connect", "integrar", "integration"],
        }

        # Contar mencoes de cada tipo de dor
        pain_counts = {}
        for pain_type, keywords in pain_keywords.items():
            count = sum(
                1 for keyword in keywords if keyword.lower() in all_texts.lower()
            )
            if count > 0:
                pain_counts[pain_type] = count

        # Ordenar por frequencia
        sorted_pains = sorted(pain_counts.items(), key=lambda x: x[1], reverse=True)

        # Construir lista de dores formatada
        pain_types_list = []
        for i, (pain_type, count) in enumerate(sorted_pains, 1):
            percentage = (count / len(reviews)) * 100
            pain_types_list.append(
                {
                    "rank": i,
                    "type": pain_type.capitalize(),
                    "count": count,
                    "percentage": round(percentage, 1),
                    "description": f"Mencionado em {count} reviews ({percentage:.1f}%)",
                }
            )

        # Retornar como dicionario estruturado
        return {
            "total_reviews": len(reviews),
            "pain_types": pain_types_list,
            "reviews": reviews,
        }

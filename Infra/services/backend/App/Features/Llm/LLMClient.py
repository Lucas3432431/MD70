"""
LLMClient - Abstração para comunicação com diferentes provedores de IA
Suporta: OpenAI, Anthropic, Deepseek com seleção por agent
"""

from typing import List, Dict, Any, Optional
from abc import ABC, abstractmethod
from openai import OpenAI
import os
import json

from App.Core.Logs import debug, error, warning, info
from App.Core.Settings.Settings import load_config, _get_api_key_for_provider
from App.Features.Llm.APIKeyRotator import APIKeyRotator
from App.Features.Credits import CreditsManager

# Importado diretamente para evitar circular import (Core → MCPClientManager → AppSetup → LLMClient)
LOOKUP_HISTORY_LIMIT = 20  # deve coincidir com Core.LOOKUP_HISTORY_LIMIT
from App.Core.Services.AdminEmail import admin_email_service

# ========================================================================
# EXCEPTIONS
# ========================================================================


class LLMBillingError(Exception):
    """Exceção lançada quando há erro de saldo ou quota na API do LLM."""

    def __init__(self, provider: str, message: str, account: str = "unknown"):
        self.provider = provider
        self.account = account
        super().__init__(f"[{provider}] Billing Error: {message}")


# ========================================================================
# CONSTANTS & STRINGS (Isolated from Logic)
# ========================================================================

# Roles
ROLE_ASSISTANT = "assistant"
ROLE_SYSTEM = "system"
ROLE_USER = "user"

# Tools
TOOL_WEB_SEARCH = "web-search"
TOOL_LOOKUP = "lookup"
TOOL_DOCUMENT = "document"
TOOL_CONTEXT = "context"
TOOL_VISUAL_ANALYSIS = "visual-analysis"
TOOL_MULTIPLE_SEARCHES = "multiple_searches"

# Providers & Models
PROVIDER_OPENAI = "openai"
PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_DEEPSEEK = "deepseek"

DEFAULT_MODEL_OPENAI = "gpt-4o"
DEFAULT_MODEL_DEEPSEEK = "deepseek-chat"
DEFAULT_MODEL_ANTHROPIC = "claude-3-5-sonnet-20241022"

# Configuration
TIMEOUT_API = 60

# Log Messages
LOG_PREFIX = "[LLMClient]"
LOG_REMOVED_REDUNDANT = (
    f"{LOG_PREFIX} {{}} [{{}}] removido (documento de SUCESSO em [{{}}])"
)
LOG_KEPT_FAILURE = f"{LOG_PREFIX} {{}} [{{}}] MANTIDO (documento em [{{}}] falhou)"
LOG_REMOVED_HISTORY = f"{LOG_PREFIX} {{}} [{{}}] removido (limite de {LOOKUP_HISTORY_LIMIT} mensagens excedido)"
LOG_REMOVING_BASE64_SINGLE = (
    f"{LOG_PREFIX} Removendo base64 de visual-analysis (single): {{}} chars"
)
LOG_REMOVING_BASE64_MULTI = (
    f"{LOG_PREFIX} Removendo base64 de visual-analysis (multiple): {{}} chars"
)
LOG_MSG_OPTIMIZATION = f"{LOG_PREFIX} Mensagem {{}}: {{}} → {{}} chars"
LOG_SAVED_CHARS = f"{LOG_PREFIX} Mensagens: {{}} → {{}} chars ({{}} economizados)"
LOG_CREDITS_CONSUMPTION = f"{LOG_PREFIX} Consumindo créditos: user_id={{}}, tokens=({{}}in, {{}}out), model={{}}"
LOG_INSUFFICIENT_FUNDS = f"{LOG_PREFIX} Saldo insuficiente: {{}}"

# Error Messages
ERR_MSG_PARSE = "Não é JSON, deixar como está"
ERR_MSG_CREDITS = "Erro ao processar créditos: {}"
ERR_INSUFFICIENT_BALANCE = (
    "INSUFFICIENT BALANCE/QUOTA - relançando exceção para quebrar pipeline"
)
ERR_TIMEOUT = "API call TIMEOUT (60s exceeded): {}"
ERR_API_CALL = "Error calling API: {}"
ERR_KEY_NOT_FOUND = "API key not found for primary AI: {}"
ERR_FALLBACK_FAILED = (
    "Failed to initialize any LLM: Primary ({}) and Fallback ({}) failed."
)

# ========================================================================


def _sanitize_messages_for_llm(messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    Sanitiza mensagens removendo base64 e otimizando espaço de contexto.
    """
    if not messages:
        return messages

    messages_to_remove = set()
    total_messages = len(messages)

    # PRÉ-SCAN: detectar índice do último lookup bem-sucedido de cada skill
    # — lookups anteriores ao mais recente de cada skill são removidos,
    #   assim como todos os context(type='document') anteriores ao último lookup ativo
    _lookup_by_skill: dict = {}  # skill_file → list of (idx, success)
    _context_doc_indices: list = []
    for idx, msg in enumerate(messages):
        if msg.get("role") != ROLE_ASSISTANT:
            continue
        try:
            cj = json.loads(msg.get("content", ""))
            if not isinstance(cj, dict):
                continue
            tn = cj.get("tool")
            if tn == TOOL_LOOKUP:
                _file = cj.get("file", cj.get("args", {}).get("file", ""))
                if not _file and isinstance(cj.get("content"), str):
                    _file = cj.get("file", "")
                if _file:
                    _lookup_by_skill.setdefault(_file, []).append(
                        (idx, bool(cj.get("success")))
                    )
            if tn == TOOL_CONTEXT and ("document" in str(cj.get("type", "")).lower()):
                _context_doc_indices.append(idx)
        except Exception:
            pass

    # PRÉ-SCAN: detectar cancel bem-sucedido
    # Quando o agente chama cancel(), lookups de skills anteriores são removidos do contexto
    # para que o LLM não continue seguindo as instruções da skill cancelada.
    _cancel_indices: list = []
    for idx, msg in enumerate(messages):
        if msg.get("role") != ROLE_ASSISTANT:
            continue
        try:
            cj = json.loads(msg.get("content", ""))
            if (
                isinstance(cj, dict)
                and cj.get("cancelled") is True
                and cj.get("success") is True
            ):
                _cancel_indices.append(idx)
        except Exception:
            pass

    if _cancel_indices:
        _last_cancel_idx = max(_cancel_indices)
        for _skill_file, _entries in _lookup_by_skill.items():
            for _lidx, _lok in _entries:
                if _lok and _lidx < _last_cancel_idx:
                    messages_to_remove.add(_lidx)
                    debug(
                        f"{LOG_PREFIX} lookup/{_skill_file} [{_lidx}] removido (cancel em [{_last_cancel_idx}])"
                    )

    # Índice do lookup ativo mais recente (última skill carregada com sucesso)
    _last_active_lookup_idx = -1
    for _skill_file, _entries in _lookup_by_skill.items():
        _successful = [i for i, ok in _entries if ok]
        if _successful:
            _last_active_lookup_idx = max(_last_active_lookup_idx, max(_successful))

    # Remover lookups de skills que foram substituídas (não são o último lookup bem-sucedido por skill)
    for _skill_file, _entries in _lookup_by_skill.items():
        _successful = [i for i, ok in _entries if ok]
        if len(_successful) > 1:
            # Manter apenas o mais recente
            for _old_idx in _successful[:-1]:
                messages_to_remove.add(_old_idx)
                debug(
                    f"{LOG_PREFIX} lookup/{_skill_file} [{_old_idx}] removido (skill substituída por versão mais recente)"
                )

    # Remover todos os context(type='documents') ANTERIORES ao último lookup ativo
    for _ci in _context_doc_indices:
        if _ci < _last_active_lookup_idx:
            messages_to_remove.add(_ci)
            debug(
                f"{LOG_PREFIX} context/documents [{_ci}] removido (anterior ao último lookup ativo)"
            )

    for idx, msg in enumerate(messages):
        if msg.get("role") != ROLE_ASSISTANT:
            continue

        try:
            content = msg.get("content", "")
            if isinstance(content, str):
                content_json = json.loads(content)

                if not isinstance(content_json, dict):
                    continue

                tool_name = content_json.get("tool")

                # FILTRO 1: Redundância por Documento (web-search, lookup)
                if tool_name in (TOOL_WEB_SEARCH, TOOL_LOOKUP):
                    for next_idx in range(idx + 1, len(messages)):
                        next_msg = messages[next_idx]
                        if next_msg.get("role") != ROLE_ASSISTANT:
                            break
                        try:
                            next_content = next_msg.get("content", "")
                            if isinstance(next_content, str):
                                next_json = json.loads(next_content)
                                if (
                                    isinstance(next_json, dict)
                                    and next_json.get("tool") == TOOL_DOCUMENT
                                ):
                                    if next_json.get("success") is True:
                                        debug(
                                            LOG_REMOVED_REDUNDANT.format(
                                                tool_name, idx, next_idx
                                            )
                                        )
                                        messages_to_remove.add(idx)
                                        break
                                    else:
                                        debug(
                                            LOG_KEPT_FAILURE.format(
                                                tool_name, idx, next_idx
                                            )
                                        )
                                        break
                        except:
                            continue

                        if isinstance(next_content, str):
                            try:
                                next_json = json.loads(next_content)
                                if (
                                    isinstance(next_json, dict)
                                    and next_json.get("tool")
                                    and next_json.get("tool") != TOOL_DOCUMENT
                                ):
                                    break
                            except:
                                pass

                # FILTRO 2: Limite de Mensagens / Idade (lookup e context)
                if tool_name in (TOOL_LOOKUP, TOOL_CONTEXT):
                    if idx < total_messages - LOOKUP_HISTORY_LIMIT:
                        if idx not in messages_to_remove:
                            debug(LOG_REMOVED_HISTORY.format(tool_name, idx))
                            messages_to_remove.add(idx)

        except (json.JSONDecodeError, ValueError, TypeError):
            continue

    # REMOÇÃO DE MENSAGENS DESATIVADA TEMPORARIAMENTE — base64 stripping ainda ativo
    messages_to_remove = set()

    sanitized = []
    total_removed_chars = 0
    removed_count = 0
    removed_tools_count = 0

    for msg_idx, msg in enumerate(messages):
        if msg_idx in messages_to_remove:
            removed_tools_count += 1
            continue

        sanitized_msg = msg.copy()

        if "content" in sanitized_msg and isinstance(sanitized_msg["content"], str):
            original_len = len(sanitized_msg["content"])
            try:
                content_json = json.loads(sanitized_msg["content"])

                if isinstance(content_json, dict):
                    if (
                        content_json.get("type") == TOOL_VISUAL_ANALYSIS
                        and "result" in content_json
                    ):
                        result_size = len(str(content_json["result"]))
                        debug(LOG_REMOVING_BASE64_SINGLE.format(result_size))
                        content_json.pop("result", None)
                        total_removed_chars += result_size
                        removed_count += 1

                    elif (
                        content_json.get("type") == TOOL_MULTIPLE_SEARCHES
                        and "results" in content_json
                    ):
                        for result in content_json.get("results", []):
                            if (
                                result.get("type") == TOOL_VISUAL_ANALYSIS
                                and "result" in result
                            ):
                                result_size = len(str(result["result"]))
                                debug(LOG_REMOVING_BASE64_MULTI.format(result_size))
                                result.pop("result", None)
                                total_removed_chars += result_size
                                removed_count += 1

                new_content = json.dumps(content_json, ensure_ascii=False)
                new_len = len(new_content)
                if original_len != new_len:
                    debug(LOG_MSG_OPTIMIZATION.format(msg_idx, original_len, new_len))

                sanitized_msg["content"] = new_content
            except (json.JSONDecodeError, ValueError, TypeError):
                pass

        sanitized.append(sanitized_msg)

    if removed_count > 0 or removed_tools_count > 0:
        summary = []
        if removed_count > 0:
            summary.append(f"{removed_count} base64(s) [{total_removed_chars} chars]")
        if removed_tools_count > 0:
            summary.append(
                f"{removed_tools_count} tool(s) [redundantes/fora de contexto]"
            )
        debug(f"{LOG_PREFIX} ✓ Otimizações: {', '.join(summary)}")

    return sanitized


class BaseLLMClient(ABC):
    @abstractmethod
    def chat(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        pass

    @abstractmethod
    def validate_api_key(self) -> bool:
        pass


class OpenAIClient(BaseLLMClient):
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL_OPENAI):
        self.api_key = api_key
        self.model = model
        self.client = OpenAI(api_key=api_key)
        debug(f"{LOG_PREFIX} OpenAIClient initialized with model: {model}")

    def validate_api_key(self) -> bool:
        try:
            response = self.client.models.retrieve(self.model)
            return response.id == self.model
        except Exception as e:
            error(f"{LOG_PREFIX} OpenAI API key validation failed: {e}")
            return False

    def chat(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        try:
            if system_prompt:
                full_messages = [
                    {"role": ROLE_SYSTEM, "content": system_prompt}
                ] + messages
            else:
                full_messages = messages

            model_temperature = temperature
            if "gpt-5" in self.model.lower():
                model_temperature = 1

            kwargs = {
                "model": self.model,
                "messages": full_messages,
                "temperature": model_temperature,
            }

            if max_tokens:
                kwargs["max_completion_tokens"] = max_tokens

            if tools:
                kwargs["tools"] = [
                    {"type": "function", "function": tool} for tool in tools
                ]
                kwargs["tool_choice"] = tool_choice if tool_choice else "auto"

            debug(
                f"[OpenAI] Calling {self.model} with {len(messages)} messages, timeout={TIMEOUT_API}s"
            )

            response = self.client.chat.completions.create(
                **kwargs, timeout=TIMEOUT_API
            )

            content = ""
            tool_calls = []

            for choice in response.choices:
                if choice.message.content:
                    content = choice.message.content

                if choice.message.tool_calls:
                    for tool_call in choice.message.tool_calls:
                        tool_calls.append(
                            {
                                "id": tool_call.id,
                                "name": tool_call.function.name,
                                "arguments": tool_call.function.arguments,
                            }
                        )

            usage = {
                "input": response.usage.prompt_tokens,
                "output": response.usage.completion_tokens,
            }

            debug(f"[OpenAI] Response: {len(content)} chars, tokens: {usage}")

            return {
                "content": content,
                "tool_calls": tool_calls,
                "model": self.model,
                "usage": usage,
                "error": None,
            }

        except Exception as e:
            error_msg = str(e).lower()
            is_billing_error = (
                "insufficient" in error_msg
                or "billing" in error_msg
                or "credit" in error_msg
                or "balance" in error_msg
            )

            if is_billing_error:
                # Apenas lança a exceção; o LLMClient.chat enviará o e-mail
                raise LLMBillingError(PROVIDER_OPENAI, str(e))

            if "timeout" in error_msg or "timed out" in error_msg:
                error(ERR_TIMEOUT.format(e))
            else:
                error(ERR_API_CALL.format(e))

            return {
                "content": "",
                "tool_calls": [],
                "model": self.model,
                "usage": {"input": 0, "output": 0},
                "error": str(e),
            }

    def embed(
        self, text: str, user_id: str, model: str = "text-embedding-3-small"
    ) -> list:
        """Gera embedding e debita créditos do usuário. Retorna vetor float[]."""
        from App.Features.Credits.CreditsManager import CreditsManager

        response = self.client.embeddings.create(model=model, input=text)
        token_count = response.usage.total_tokens
        cost = CreditsManager.calculate_embedding_cost(token_count, model)
        if cost > 0:
            CreditsManager.consume_credits(
                user_id=user_id,
                amount=cost,
                reason=f"Embedding {model} ({token_count} tokens)",
            )
        return response.data[0].embedding

    def transcribe_audio(self, file_path: str, language: str = "pt") -> dict:
        """Transcreve áudio via Whisper. Retorna {text, duration_seconds, error}."""
        import os as _os

        try:
            with open(file_path, "rb") as audio_file:
                response = self.client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    language=language,
                    response_format="verbose_json",
                )
            duration = getattr(response, "duration", None) or 0.0
            return {
                "text": response.text,
                "duration_seconds": float(duration),
                "error": None,
            }
        except Exception as e:
            error(f"[Whisper] Transcrição falhou: {e}")
            return {"text": "", "duration_seconds": 0.0, "error": str(e)}

    def synthesize_speech(
        self, text: str, voice: str = "nova", model: str = "tts-1"
    ) -> bytes:
        """Sintetiza texto em áudio MP3 via OpenAI TTS. Retorna bytes do MP3."""
        response = self.client.audio.speech.create(
            model=model,
            voice=voice,
            input=text,
            response_format="mp3",
        )
        return response.content


class DeepseekClient(BaseLLMClient):
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL_DEEPSEEK):
        self.api_key = api_key
        self.model = model
        self.client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        debug(f"{LOG_PREFIX} DeepseekClient initialized with model: {model}")

    def validate_api_key(self) -> bool:
        try:
            response = self.client.models.retrieve(self.model)
            return response.id == self.model
        except Exception as e:
            error(f"{LOG_PREFIX} Deepseek API key validation failed: {e}")
            return False

    def chat(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        try:
            full_messages = (
                [{"role": ROLE_SYSTEM, "content": system_prompt}] + messages
                if system_prompt
                else messages
            )

            kwargs = {
                "model": self.model,
                "messages": full_messages,
                "temperature": temperature,
            }

            if max_tokens:
                kwargs["max_tokens"] = max_tokens

            if tools:
                kwargs["tools"] = [
                    {"type": "function", "function": tool} for tool in tools
                ]
                kwargs["tool_choice"] = tool_choice if tool_choice else "auto"

            debug(
                f"[Deepseek] Calling {self.model} with {len(messages)} messages, timeout={TIMEOUT_API}s"
            )

            response = self.client.chat.completions.create(
                **kwargs, timeout=TIMEOUT_API
            )

            content = ""
            tool_calls = []

            for choice in response.choices:
                if choice.message.content:
                    content = choice.message.content

                if choice.message.tool_calls:
                    for tool_call in choice.message.tool_calls:
                        tool_calls.append(
                            {
                                "id": tool_call.id,
                                "name": tool_call.function.name,
                                "arguments": tool_call.function.arguments,
                            }
                        )

            usage = {
                "input": response.usage.prompt_tokens,
                "output": response.usage.completion_tokens,
            }

            debug(f"[Deepseek] Response: {len(content)} chars, tokens: {usage}")

            finish_reason = (
                response.choices[0].finish_reason if response.choices else "stop"
            )
            stop_reason = "max_tokens" if finish_reason == "length" else finish_reason

            return {
                "content": content,
                "tool_calls": tool_calls,
                "model": self.model,
                "usage": usage,
                "error": None,
                "stop_reason": stop_reason,
            }

        except Exception as e:
            error_msg = str(e).lower()
            is_billing_error = (
                "insufficient balance" in error_msg
                or "402" in error_msg
                or "billing" in error_msg
            )

            if is_billing_error:
                raise LLMBillingError(PROVIDER_DEEPSEEK, str(e))

            if "timeout" in error_msg or "timed out" in error_msg:
                error(ERR_TIMEOUT.format(e))
            else:
                error(ERR_API_CALL.format(e))

            return {
                "content": "",
                "tool_calls": [],
                "model": self.model,
                "usage": {"input": 0, "output": 0},
                "error": str(e),
            }


class AnthropicClient(BaseLLMClient):
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL_ANTHROPIC):
        try:
            from anthropic import Anthropic
        except ImportError:
            error("Anthropic SDK not installed. Install with: pip install anthropic")
            raise

        self.api_key = api_key
        self.model = model
        self.client = Anthropic(api_key=api_key)
        debug(f"{LOG_PREFIX} AnthropicClient initialized with model: {model}")

    def validate_api_key(self) -> bool:
        try:
            self.client.messages.create(
                model=self.model,
                max_tokens=10,
                messages=[{"role": ROLE_USER, "content": "test"}],
            )
            return True
        except Exception as e:
            error(f"{LOG_PREFIX} Anthropic API key validation failed: {e}")
            return False

    def chat(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        try:
            kwargs = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens or 8192,
            }

            if system_prompt:
                kwargs["system"] = system_prompt

            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = tool_choice if tool_choice else "auto"

            debug(
                f"[Anthropic] Calling {self.model} with {len(messages)} messages, timeout={TIMEOUT_API}s"
            )

            response = self.client.messages.create(**kwargs, timeout=TIMEOUT_API)

            content = ""
            tool_calls = []

            for block in response.content:
                if hasattr(block, "text"):
                    content = block.text
                elif hasattr(block, "type") and block.type == "tool_use":
                    tool_calls.append(
                        {
                            "id": block.id,
                            "name": block.name,
                            "arguments": block.input,
                        }
                    )

            usage = {
                "input": (
                    response.usage.input_tokens
                    if hasattr(response.usage, "input_tokens")
                    else 0
                ),
                "output": (
                    response.usage.output_tokens
                    if hasattr(response.usage, "output_tokens")
                    else 0
                ),
            }

            # Quando truncado por max_tokens com tool calls pendentes, os args estão
            # incompletos — descartar tool_calls para que o MessageProcessor injete
            # "Continue." e a geração seja refeita corretamente.
            if response.stop_reason == "max_tokens" and tool_calls:
                warning(
                    f"[Anthropic] stop_reason=max_tokens com {len(tool_calls)} tool call(s) — descartando calls truncadas"
                )
                tool_calls = []

            debug(f"[Anthropic] Response: {len(content)} chars, tokens: {usage}")

            return {
                "content": content,
                "tool_calls": tool_calls,
                "model": self.model,
                "usage": usage,
                "error": None,
                "stop_reason": response.stop_reason,
            }

        except Exception as e:
            error_msg = str(e).lower()
            is_billing_error = (
                "insufficient" in error_msg
                or "quota" in error_msg
                or "billing" in error_msg
                or "credit" in error_msg
            )

            if is_billing_error:
                raise LLMBillingError(PROVIDER_ANTHROPIC, str(e))

            if "timeout" in error_msg or "timed out" in error_msg:
                error(ERR_TIMEOUT.format(e))
            else:
                error(ERR_API_CALL.format(e))

            return {
                "content": "",
                "tool_calls": [],
                "model": self.model,
                "usage": {"input": 0, "output": 0},
                "error": str(e),
            }


class LLMClient:
    def __init__(self, ai: str, model: str, api_key: Optional[str] = None):
        self.ai = ai.lower()
        self.model = model
        self.client = None
        self.current_account = "default"

        config_data = load_config()

        def _get_api_key_local(provider_name: str):
            try:
                rotator = APIKeyRotator()
                _, _, key, account = rotator.get_next_key(provider=provider_name)
                if key:
                    debug(
                        f"{LOG_PREFIX} Got key from APIKeyRotator for {provider_name} ({account})"
                    )
                    return key, account
            except Exception as e:
                debug(f"{LOG_PREFIX} APIKeyRotator unavailable: {e}")

            settings_key = _get_api_key_for_provider(provider_name.lower(), config_data)
            if settings_key:
                return settings_key, "default"

            return None, None

        current_api_key, account_name = _get_api_key_local(self.ai)
        if api_key:
            current_api_key = api_key
            account_name = "manual"

        self.current_account = account_name
        current_model = self.model
        current_ai = self.ai

        fallback_used = False

        try:
            if not current_api_key:
                raise ValueError(ERR_KEY_NOT_FOUND.format(self.ai))

            if current_ai == PROVIDER_OPENAI:
                self.client = OpenAIClient(api_key=current_api_key, model=current_model)
            elif current_ai == PROVIDER_ANTHROPIC:
                self.client = AnthropicClient(
                    api_key=current_api_key, model=current_model
                )
            elif current_ai == PROVIDER_DEEPSEEK:
                self.client = DeepseekClient(
                    api_key=current_api_key, model=current_model
                )
            else:
                raise ValueError(f"Unsupported AI provider: {current_ai}")

        except ValueError as e:
            warning(
                f"Primary LLM initialization failed for {self.ai} ({e}). Attempting fallback to Deepseek."
            )
            fallback_used = True
            current_ai = PROVIDER_DEEPSEEK
            current_model = DEFAULT_MODEL_DEEPSEEK
            current_api_key, account_name = _get_api_key_local(current_ai)
            self.current_account = account_name

            if not current_api_key:
                error(
                    f"Fallback LLM (Deepseek) initialization failed: API key not found for {current_ai}"
                )
                raise ValueError(ERR_KEY_NOT_FOUND.format(current_ai))

            try:
                self.client = DeepseekClient(
                    api_key=current_api_key, model=current_model
                )
                warning(
                    f"Deepseek fallback used. Initialized with {current_ai} / {current_model}."
                )
            except ValueError as e_fallback:
                error(f"Fallback LLM (Deepseek) initialization failed: {e_fallback}")
                raise ValueError(ERR_FALLBACK_FAILED.format(self.ai, current_ai))

        debug(
            f"{LOG_PREFIX} LLMClient initialized: {current_ai} / {current_model} ({self.current_account})"
        )

    def chat(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        user_id: Optional[str] = None,
        isolated_chat_id: Optional[str] = None,
        isolated_message_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Processa chat com suporte a auto-retry exaustivo em caso de billing error.
        Tenta TODAS as chaves disponíveis para o provider atual.
        Se TODAS falharem por cota/saldo, derruba o servidor.
        """
        original_size = sum(len(str(msg.get("content", ""))) for msg in messages)
        sanitized_messages = _sanitize_messages_for_llm(messages)
        sanitized_size = sum(
            len(str(msg.get("content", ""))) for msg in sanitized_messages
        )

        if original_size != sanitized_size:
            debug(
                LOG_SAVED_CHARS.format(
                    original_size, sanitized_size, original_size - sanitized_size
                )
            )

        rotator = APIKeyRotator()
        status = rotator.get_status()
        provider_info = status.get("providers", {}).get(self.ai, {})
        total_keys = provider_info.get("total_keys", 1)

        attempts = 0

        while attempts < total_keys:
            try:
                attempts += 1
                response = self.client.chat(
                    messages=sanitized_messages,
                    system_prompt=system_prompt,
                    tools=tools,
                    tool_choice=tool_choice,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

                # Sucesso: resetar status de falha no rotator
                if hasattr(self.client, "api_key"):
                    rotator.reset_key_status(self.ai, self.client.api_key)

                if user_id:
                    usage = response.get("usage", {})
                    input_tokens = usage.get("input", 0)
                    output_tokens = usage.get("output", 0)

                    if input_tokens > 0 or output_tokens > 0:
                        debug(
                            LOG_CREDITS_CONSUMPTION.format(
                                user_id, input_tokens, output_tokens, self.model
                            )
                        )
                        try:
                            (
                                has_credits,
                                error_msg,
                                remaining,
                            ) = CreditsManager.check_and_consume_for_llm(
                                user_id=user_id,
                                input_tokens=input_tokens,
                                output_tokens=output_tokens,
                                model=self.model,
                                isolated_chat_id=isolated_chat_id,
                                isolated_message_id=isolated_message_id,
                            )

                            if not has_credits:
                                response["error"] = error_msg
                                debug(LOG_INSUFFICIENT_FUNDS.format(error_msg))
                        except Exception as e:
                            error(f"{LOG_PREFIX} {ERR_MSG_CREDITS.format(e)}")
                            response["error"] = ERR_MSG_CREDITS.format(str(e))

                return response

            except LLMBillingError as be:
                warning(
                    f"{LOG_PREFIX} Billing error na tentativa {attempts}/{total_keys} para {self.ai} ({self.current_account}): {be}"
                )

                # ENVIAR EMAIL PARA CADA FALHA INDIVIDUAL
                admin_email_service.send_critical_alert(
                    f"LLM BILLING ERROR - {self.ai.upper()}",
                    f"A chave '{self.current_account}' do provider '{self.ai}' falhou por saldo/quota insuficiente.\n\n"
                    f"Tentativa: {attempts}/{total_keys}\n"
                    f"Erro: {be}",
                )

                # Reportar falha ao rotador
                if hasattr(self.client, "api_key"):
                    rotator.report_failure(self.ai, self.client.api_key)

                if attempts < total_keys:
                    info(
                        f"{LOG_PREFIX} Tentando rotacionar chave de API ({attempts}/{total_keys})..."
                    )
                    _, _, new_key, account_name = rotator.get_next_key(provider=self.ai)

                    if new_key:
                        self.current_account = account_name
                        # Re-inicializar o client interno com a nova chave
                        if self.ai == PROVIDER_OPENAI:
                            self.client = OpenAIClient(
                                api_key=new_key, model=self.model
                            )
                        elif self.ai == PROVIDER_ANTHROPIC:
                            self.client = AnthropicClient(
                                api_key=new_key, model=self.model
                            )
                        elif self.ai == PROVIDER_DEEPSEEK:
                            self.client = DeepseekClient(
                                api_key=new_key, model=self.model
                            )

                        info(
                            f"{LOG_PREFIX} Chave rotacionada para '{self.current_account}'. Reiniciando tentativa..."
                        )
                        continue

                # Se esgotou todas as chaves — tentar fallback para OpenAI
                warning(
                    f"🚨 FALHA CRÍTICA DEFINITIVA: Todas as {total_keys} chaves para '{self.ai}' falharam por saldo insuficiente. Tentando fallback para OpenAI..."
                )
                admin_email_service.send_critical_alert(
                    f"LLM EXHAUSTED - {self.ai.upper()} → OpenAI fallback",
                    f"Todas as chaves de '{self.ai}' falharam. Tentando OpenAI como fallback.",
                )

                if self.ai != PROVIDER_OPENAI:
                    try:
                        fallback_key, fallback_account = _get_api_key_local(
                            PROVIDER_OPENAI
                        )
                        if fallback_key:
                            self.ai = PROVIDER_OPENAI
                            self.model = DEFAULT_MODEL_OPENAI
                            self.current_account = fallback_account
                            self.client = OpenAIClient(
                                api_key=fallback_key, model=self.model
                            )
                            warning(
                                f"[LLMClient] Fallback ativo: usando OpenAI ({fallback_account}) para esta sessão."
                            )
                            # Reiniciar o loop com o novo provider
                            attempts = 0
                            total_keys = 1
                            continue
                    except Exception as fe:
                        error(f"[LLMClient] Fallback para OpenAI também falhou: {fe}")

                error(
                    "🚨 Todos os providers LLM esgotados. Retornando erro sem derrubar o servidor."
                )
                return {
                    "content": "",
                    "tool_calls": [],
                    "model": self.model,
                    "usage": {"input": 0, "output": 0},
                    "error": "Todos os providers LLM estão sem saldo. Tente novamente mais tarde.",
                }

            except Exception as e:
                error(f"{LOG_PREFIX} Erro inesperado no chat: {e}")
                return {
                    "content": "",
                    "tool_calls": [],
                    "model": self.model,
                    "usage": {"input": 0, "output": 0},
                    "error": str(e),
                }

    def validate_api_key(self) -> bool:
        return self.client.validate_api_key()

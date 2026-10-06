"""
APIKeyRotator - Rotação simples de chaves com failover entre providers
Lógica: Se todas as chaves de um provider falham, muda permanentemente para outro
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
from threading import Lock

from App.Core.Logs import debug, error, warning


@dataclass
class KeyStatus:
    """Status de uma chave API."""

    provider: str
    model: str
    account: str
    key: str
    failures: int = 0
    last_failure_at: Optional[datetime] = None


class APIKeyRotator:
    """
    Rotação simples de chaves com failover de provider.
    Singleton - mantém estado entre requisições.

    LÓGICA:
    1. OpenAI key1 falha → tenta OpenAI key2
    2. OpenAI key2 falha → muda PERMANENTEMENTE para DeepSeek
    3. DeepSeek key1 falha → tenta DeepSeek key2
    4. DeepSeek key2 falha → muda para próximo provider disponível
    """

    _instance = None
    _lock = Lock()

    def __new__(cls, config: Optional[Dict] = None):
        """Singleton pattern."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, config: Optional[Dict] = None):
        """
        Inicializa o rotador.

        Args:
            config: {
                "providers": {
                    "openai": {
                        "keys": ["sk-key1", "sk-key2"],
                        "model": "gpt-4o-mini"
                    },
                    "deepseek": {
                        "keys": ["sk-key1", "sk-key2"],
                        "model": "deepseek-chat"
                    }
                }
            }
        """
        if self._initialized:
            return

        self.config = config or {}
        self.key_status: Dict[str, List[KeyStatus]] = {}
        self.provider_order = []  # Ordem dos providers
        self.current_provider_idx = 0  # Índice do provider atual
        self.current_key_idx: Dict[str, int] = {}  # Índice da chave por provider

        self._load_config()

        # Reordenar para DeepSeek primeiro se disponível
        if "deepseek" in self.provider_order:
            self.provider_order.remove("deepseek")
            self.provider_order.insert(0, "deepseek")
            self.current_provider_idx = 0

        self._initialized = True
        debug(
            f"[APIKeyRotator] Inicializado. Provider padrão: {self.get_current_provider()}"
        )

    def _load_config(self):
        """Carrega chaves dos providers."""
        providers = self.config.get("providers", {})
        self.provider_order = list(providers.keys())

        for provider_name, provider_config in providers.items():
            keys = provider_config.get("keys", [])
            model = provider_config.get("model")

            if not keys:
                warning(f"[APIKeyRotator] Nenhuma chave para {provider_name}")
                continue

            self.key_status[provider_name] = []
            for key_entry in keys:
                # Suporta novo formato: {account, key} ou formato antigo: just key string
                if isinstance(key_entry, dict):
                    account = key_entry.get("account", "unknown")
                    key = key_entry.get("key", "")
                else:
                    account = "default"
                    key = key_entry

                if key:
                    self.key_status[provider_name].append(
                        KeyStatus(
                            provider=provider_name,
                            model=model,
                            account=account,
                            key=key,
                        )
                    )

            self.current_key_idx[provider_name] = 0
            debug(
                f"[APIKeyRotator] {provider_name}: {len(self.key_status[provider_name])} chaves"
            )

    def get_current_provider(self) -> str:
        """Retorna o provider atualmente em uso."""
        if not self.provider_order:
            return None
        return self.provider_order[self.current_provider_idx % len(self.provider_order)]

    def get_next_key(self, provider: Optional[str] = None) -> Tuple[str, str, str, str]:
        """
        Retorna (provider, model, api_key, account) para usar agora.
        Implementa round-robin simples: próxima chave do provider atual ou especificado.

        Args:
            provider: Provider específico ('openai', 'deepseek'). Se None, usa provider atual.

        IMPORTANTE: NÃO logue a chave (key) retornada! Ela é sensível.
        """
        target_provider = provider or self.get_current_provider()

        if not target_provider or target_provider not in self.key_status:
            error(f"[APIKeyRotator] Provider {target_provider} não configurado")
            return None, None, None, None

        keys = self.key_status[target_provider]
        if not keys:
            error(f"[APIKeyRotator] Nenhuma chave disponível para {target_provider}")
            return None, None, None, None

        idx = self.current_key_idx[target_provider]

        # Round-robin entre chaves
        key_status = keys[idx]
        self.current_key_idx[target_provider] = (idx + 1) % len(keys)

        # Log apenas safe info - sem a chave
        debug(
            f"[APIKeyRotator] Usando {target_provider} [{key_status.account}] key #{idx+1}/{len(keys)}"
        )
        return target_provider, key_status.model, key_status.key, key_status.account

    def reset_key_status(self, provider: str, key: str):
        """Reset contador de falhas de uma chave (chamado após sucesso)."""
        if provider not in self.key_status:
            return

        for key_status in self.key_status[provider]:
            if key_status.key == key:
                if key_status.failures > 0:
                    key_status.failures = 0
                    debug(f"[APIKeyRotator] {provider} key resetada após sucesso")
                break

    def report_failure(self, provider: str, key: str):
        """
        Registra falha de uma chave.
        Se TODAS as chaves do provider atual falharem, muda para o próximo provider.
        """
        if provider not in self.key_status:
            return

        # Incrementa contador de falhas
        for key_status in self.key_status[provider]:
            if key_status.key == key:
                key_status.failures += 1
                key_status.last_failure_at = datetime.now()
                warning(
                    f"[APIKeyRotator] {provider} key falhou ({key_status.failures}x)"
                )
                break

        # Verifica se TODAS as chaves do provider atual falharam
        if provider == self.get_current_provider():
            all_failed = all(k.failures > 0 for k in self.key_status[provider])

            if all_failed:
                self._switch_to_next_provider()

    def _switch_to_next_provider(self):
        """Troca para o próximo provider da lista (e fica nele)."""
        current = self.get_current_provider()
        self.current_provider_idx = (self.current_provider_idx + 1) % len(
            self.provider_order
        )
        new_provider = self.get_current_provider()

        error(
            f"[APIKeyRotator] Todas as chaves de {current} falharam. Trocando para: {new_provider}"
        )

    def get_status(self) -> Dict:
        """Retorna status atual com informações de conta."""
        return {
            "current_provider": self.get_current_provider(),
            "providers": {
                provider: {
                    "total_keys": len(keys),
                    "failed_keys": sum(1 for k in keys if k.failures > 0),
                    "keys": [
                        {
                            "account": k.account,
                            "key": k.key[:10] + "...",
                            "failures": k.failures,
                            "last_failure": (
                                k.last_failure_at.isoformat()
                                if k.last_failure_at
                                else None
                            ),
                        }
                        for k in keys
                    ],
                }
                for provider, keys in self.key_status.items()
            },
        }

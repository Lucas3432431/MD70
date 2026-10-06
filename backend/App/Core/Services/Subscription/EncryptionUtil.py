"""
Utilitário de Criptografia para Dados Sensíveis
Usando Fernet (simétrica, reversível)
"""

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import hashlib
import base64
import os

from App.Core.Logs import error, info
from App.Core.Settings import get_billing_encryption_key

_encryption_key_cache = None


def validate_encryption_key() -> bool:
    """Valida se a chave de 256 bits está configurada corretamente."""
    try:
        key_hex = get_billing_encryption_key().strip()
        if not key_hex:
            raise ValueError("BILLING_ENCRYPTION_KEY não configurada")

        # Tentar decodificar e carregar
        key_bytes = bytes.fromhex(key_hex)
        if len(key_bytes) != 32:
            raise ValueError(
                f"Chave deve ter 32 bytes (64 caracteres hex), mas tem {len(key_bytes)} bytes"
            )

        aesgcm = AESGCM(key_bytes)
        nonce = os.urandom(12)
        aesgcm.encrypt(nonce, b"test", None)
        info(
            "[ENCRYPTION] AES-256-GCM validado com sucesso (Resistente a ataques quânticos)"
        )
        return True
    except Exception as e:
        error(f"[ENCRYPTION] Erro na chave: {e}")
        raise


def get_encryption_key():
    global _encryption_key_cache
    if _encryption_key_cache:
        return _encryption_key_cache

    key_hex = get_billing_encryption_key().strip()
    try:
        key_bytes = bytes.fromhex(key_hex)
        if len(key_bytes) != 32:
            raise ValueError("Chave inválida para AES-256")
        _encryption_key_cache = key_bytes
        return key_bytes
    except Exception as e:
        error(f"[ENCRYPTION] Erro ao carregar chave: {e}")
        raise


def encrypt_field(value: str) -> str:
    """Criptografa usando AES-256-GCM (Nonce + Ciphertext em Base64)"""
    if not value:
        return None
    try:
        key = get_encryption_key()
        aesgcm = AESGCM(key)
        nonce = os.urandom(12)  # GCM recomenda 12 bytes de nonce
        ciphertext = aesgcm.encrypt(nonce, value.encode("utf-8"), None)
        # Retorna nonce + ciphertext para poder descriptografar depois
        return base64.b64encode(nonce + ciphertext).decode("utf-8")
    except Exception as e:
        error(f"[ENCRYPTION] Erro ao encriptar: {e}")
        raise


def decrypt_field(encrypted_value: str) -> str:
    """Descriptografa dados AES-256-GCM"""
    if not encrypted_value:
        return None
    try:
        key = get_encryption_key()
        aesgcm = AESGCM(key)
        data = base64.b64decode(encrypted_value)
        nonce = data[:12]
        ciphertext = data[12:]
        decrypted = aesgcm.decrypt(nonce, ciphertext, None)
        return decrypted.decode("utf-8")
    except Exception as e:
        error(f"[ENCRYPTION] Erro ao descriptografar: {e}")
        return None


def hash_payment_method(value: str) -> str:
    """
    Hash SHA-256 determinístico para deduplicação de payment methods.
    Diferente da criptografia (que usa nonce aleatório), o hash é sempre igual
    para o mesmo valor, permitindo comparação e busca no banco.

    Args:
        value: Token do payment method (ex: "pm_abc123")

    Returns:
        str: Hash SHA-256 em hexadecimal (64 caracteres)
    """
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "encrypt_field",
    "decrypt_field",
    "get_encryption_key",
    "validate_encryption_key",
    "hash_payment_method",
]

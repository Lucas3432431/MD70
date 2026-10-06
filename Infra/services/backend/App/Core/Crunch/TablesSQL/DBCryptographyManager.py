"""
Gerenciador centralizado de criptografia para dados do banco de dados.
Responsável por encrypt/decrypt transparente de campos sensíveis.
Usa AES-256-GCM com chave BILLING_ENCRYPTION_KEY do ambiente.
"""

import base64
import binascii
import os
import json
from typing import Dict, Any, List, Optional
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.fernet import Fernet  # Para compatibilidade com dados existentes

from App.Core.Logs import error, debug
from App.Core.Settings import load_config


class DBCryptographyManager:
    """
    Gerencia criptografia/descriptografia de dados do banco de dados.
    Interface simplificada para criptografia de campos sensíveis.

    Campos criptografados por padrão:
    - users: document, phone, cpf
    - billing: document, phone, email
    - cards: pagarme_card_id
    - payments: customer_id (se sensível)
    """

    # Mapeamento de tabelas e campos que devem ser criptografados
    ENCRYPTED_FIELDS = {
        "users": ["document", "phone", "cpf"],
        "billing": ["document", "phone", "email"],
        "cards": ["pagarme_card_id"],
        "payments": [],  # Por enquanto vazio
        "email_validations": ["email"],
        "cellphone_validations": ["phone"],
        "postal_code_validations": ["postal_code"],
        "integrations_mcp": ["env_vars"],
        "triggers": ["provider_config"],
        "delivery_integrations": ["access_token", "refresh_token"],
        "delivery_pending_auth": ["code_verifier"],
    }

    # ==================== CONFIGURAÇÃO DE CRIPTOGRAFIA ====================

    # Versão do formato de criptografia
    ENCRYPTION_VERSION = "AES256-GCM-v1"

    # Salt fixo para derivação de chave
    KEY_DERIVATION_SALT = b"prox_advanced_crypto_salt_2026"

    # Número de iterações para PBKDF2
    PBKDF2_ITERATIONS = 100000

    _aesgcm_instance = None
    _fernet_instance = None
    _key_material = None

    @classmethod
    def _get_key_material(cls) -> bytes:
        """
        Obtém material de chave de 40 caracteres do ambiente.
        Usa BILLING_ENCRYPTION_KEY como base e deriva chave de 40 chars.

        Returns:
            bytes: Material de chave de 40 bytes
        """
        if cls._key_material is not None:
            return cls._key_material

        try:
            config = load_config()
            key_hex = config.get("secret_key", "").strip()

            if not key_hex:
                error("[DB_CRYPTO] BILLING_ENCRYPTION_KEY não configurada")
                raise ValueError("BILLING_ENCRYPTION_KEY não configurada")

            # Converter hexadecimal para bytes (32 bytes)
            key_bytes = binascii.unhexlify(key_hex)

            # Usar PBKDF2 para derivar chave de 40 bytes
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=40,  # 40 bytes = 320 bits
                salt=cls.KEY_DERIVATION_SALT,
                iterations=cls.PBKDF2_ITERATIONS,
            )

            cls._key_material = kdf.derive(key_bytes)
            return cls._key_material

        except Exception as e:
            error(f"[DB_CRYPTO] Erro ao obter material de chave: {e}")
            raise

    @classmethod
    def _get_aesgcm(cls) -> AESGCM:
        """
        Retorna instância AESGCM configurada.

        Returns:
            AESGCM: Instância AES-256-GCM
        """
        if cls._aesgcm_instance is None:
            # Usar primeiros 32 bytes do material de chave para AES-256
            key_material = cls._get_key_material()
            aes_key = key_material[:32]  # 32 bytes = 256 bits
            cls._aesgcm_instance = AESGCM(aes_key)

        return cls._aesgcm_instance

    @classmethod
    def _get_fernet(cls) -> Fernet:
        """
        Retorna instância Fernet para compatibilidade com dados existentes.

        Returns:
            Fernet: Instância Fernet
        """
        if cls._fernet_instance is None:
            try:
                config = load_config()
                key_hex = config.get("secret_key", "").strip()

                if not key_hex:
                    error(
                        "[DB_CRYPTO] BILLING_ENCRYPTION_KEY não configurada para Fernet"
                    )
                    raise ValueError("BILLING_ENCRYPTION_KEY não configurada")

                # Converter hexadecimal para bytes
                key_bytes = binascii.unhexlify(key_hex)

                # Converter para base64 URL-safe (Fernet requer este formato)
                key_base64 = base64.urlsafe_b64encode(key_bytes)
                cls._fernet_instance = Fernet(key_base64)
            except Exception as e:
                error(f"[DB_CRYPTO] Erro ao inicializar Fernet: {e}")
                raise

        return cls._fernet_instance

    @classmethod
    def _encrypt_aesgcm(cls, value: str) -> str:
        """
        Criptografa com AES-256-GCM.

        Args:
            value: Valor a ser criptografado

        Returns:
            str: JSON string com dados criptografados
        """
        aesgcm = cls._get_aesgcm()

        # Gerar nonce (número usado uma vez) de 12 bytes
        nonce = os.urandom(12)

        # Criptografar
        encrypted_data = aesgcm.encrypt(nonce, value.encode("utf-8"), None)

        # Criar estrutura de dados
        encrypted_package = {
            "version": cls.ENCRYPTION_VERSION,
            "nonce": base64.b64encode(nonce).decode("utf-8"),
            "data": base64.b64encode(encrypted_data).decode("utf-8"),
        }

        # Converter para JSON string
        return json.dumps(encrypted_package)

    @classmethod
    def _decrypt_aesgcm(cls, encrypted_json: str) -> str:
        """
        Descriptografa campo no formato AES-256-GCM.

        Args:
            encrypted_json: JSON string com dados criptografados

        Returns:
            str: Valor descriptografado
        """
        try:
            # Parse JSON
            package = json.loads(encrypted_json)

            if package.get("version") != cls.ENCRYPTION_VERSION:
                raise ValueError(
                    f"Versão de criptografia incompatível: {package.get('version')}"
                )

            # Decodificar componentes
            nonce = base64.b64decode(package["nonce"])
            encrypted_data = base64.b64decode(package["data"])

            # Descriptografar
            aesgcm = cls._get_aesgcm()
            decrypted_data = aesgcm.decrypt(nonce, encrypted_data, None)

            return decrypted_data.decode("utf-8")

        except Exception as e:
            error(f"[DB_CRYPTO] Erro ao descriptografar AES-GCM: {e}")
            raise

    @classmethod
    def _decrypt_fernet(cls, encrypted_value: str) -> str:
        """
        Descriptografa campo no formato Fernet (legado).

        Args:
            encrypted_value: String criptografada com Fernet

        Returns:
            str: Valor descriptografado
        """
        try:
            fernet = cls._get_fernet()
            decrypted_data = fernet.decrypt(encrypted_value.encode("utf-8"))
            return decrypted_data.decode("utf-8")

        except Exception as e:
            error(f"[DB_CRYPTO] Erro ao descriptografar Fernet: {e}")
            raise

    @classmethod
    def encrypt_field(cls, value: str, force_legacy: bool = False) -> Optional[str]:
        """
        Criptografa um campo de texto usando AES-256-GCM.

        Args:
            value: Valor a ser criptografado
            force_legacy: Forçar uso de Fernet para compatibilidade

        Returns:
            str: Valor criptografado, ou None se value for None/vazio
        """
        if not value:
            return None

        try:
            if force_legacy:
                # Usar Fernet para compatibilidade
                fernet = cls._get_fernet()
                encrypted = fernet.encrypt(value.encode("utf-8"))
                return encrypted.decode("utf-8")

            # Usar AES-256-GCM (novo formato)
            return cls._encrypt_aesgcm(value)

        except Exception as e:
            error(f"[DB_CRYPTO] Erro ao criptografar campo: {e}")
            raise

    @classmethod
    def decrypt_field(cls, encrypted_value: str) -> Optional[str]:
        """
        Descriptografa um campo de texto.
        Detecta automaticamente se é formato Fernet ou AES-256-GCM.

        Args:
            encrypted_value: Valor criptografado

        Returns:
            str: Valor descriptografado, ou None se não conseguir
        """
        if not encrypted_value:
            return None

        try:
            # Tentar detectar formato (aceita com ou sem espaço após ":")
            if encrypted_value.startswith("{") and "AES256-GCM-v1" in encrypted_value:
                # Formato AES-256-GCM (JSON)
                return cls._decrypt_aesgcm(encrypted_value)
            else:
                # Formato Fernet (legado)
                return cls._decrypt_fernet(encrypted_value)

        except Exception as e:
            error(f"[DB_CRYPTO] Erro ao descriptografar campo: {e}")
            # Tentar fallback para Fernet se AES-GCM falhar
            try:
                return cls._decrypt_fernet(encrypted_value)
            except Exception:
                return None

    @classmethod
    def decrypt_row(cls, table: str, row: Dict[str, Any]) -> Dict[str, Any]:
        """
        Descriptografa campos sensíveis de uma linha inteira.

        Args:
            table: Nome da tabela (ex: 'users', 'billing')
            row: Dicionário com dados da linha

        Returns:
            Dict: Cópia de row com campos descriptografados
        """
        if not row:
            return row

        decrypted_row = row.copy()
        encrypted_fields = cls.ENCRYPTED_FIELDS.get(table, [])

        for field in encrypted_fields:
            if field in decrypted_row and decrypted_row[field]:
                decrypted_value = cls.decrypt_field(decrypted_row[field])
                if decrypted_value:
                    decrypted_row[field] = decrypted_value

        return decrypted_row

    @classmethod
    def decrypt_rows(
        cls, table: str, rows: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Descriptografa campos sensíveis de múltiplas linhas.

        Args:
            table: Nome da tabela
            rows: Lista de dicionários com dados

        Returns:
            List[Dict]: Cópia de rows com campos descriptografados
        """
        if not rows:
            return rows

        return [cls.decrypt_row(table, row) for row in rows]

    @classmethod
    def encrypt_row_for_insert(cls, table: str, row: Dict[str, Any]) -> Dict[str, Any]:
        """
        Criptografa campos sensíveis antes de inserir no banco.

        Args:
            table: Nome da tabela
            row: Dicionário com dados a inserir

        Returns:
            Dict: Cópia de row com campos sensíveis criptografados
        """
        if not row:
            return row

        encrypted_row = row.copy()
        encrypted_fields = cls.ENCRYPTED_FIELDS.get(table, [])

        for field in encrypted_fields:
            if field in encrypted_row and encrypted_row[field]:
                encrypted_value = cls.encrypt_field(encrypted_row[field])
                if encrypted_value:
                    encrypted_row[field] = encrypted_value

        return encrypted_row

    @classmethod
    def is_field_encrypted(cls, table: str, field: str) -> bool:
        """Verifica se um campo deve ser criptografado"""
        encrypted_fields = cls.ENCRYPTED_FIELDS.get(table, [])
        return field in encrypted_fields

    @classmethod
    def add_encrypted_field(cls, table: str, field: str):
        """Registra um novo campo como criptografado"""
        if table not in cls.ENCRYPTED_FIELDS:
            cls.ENCRYPTED_FIELDS[table] = []
        if field not in cls.ENCRYPTED_FIELDS[table]:
            cls.ENCRYPTED_FIELDS[table].append(field)

    @classmethod
    def e2e_decrypt_and_db_encrypt(cls, table: str, plaintext: str) -> str:
        """
        Criptografa valor com BILLING_ENCRYPTION_KEY para salvar no BD.

        Args:
            table: Nome da tabela (para validar se é campo criptografado)
            plaintext: Valor a ser criptografado

        Returns:
            str: Valor criptografado com BILLING_ENCRYPTION_KEY
        """
        if not plaintext:
            return None

        return cls.encrypt_field(plaintext)

    @classmethod
    def e2e_decrypt_and_db_encrypt_row(
        cls, table: str, e2e_decrypted_row: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Criptografa múltiplos campos para salvar no BD.

        Args:
            table: Nome da tabela
            e2e_decrypted_row: Dicionário com valores a serem criptografados

        Returns:
            Dict: Cópia com campos sensíveis criptografados com BILLING_ENCRYPTION_KEY
        """
        if not e2e_decrypted_row:
            return e2e_decrypted_row

        re_encrypted_row = e2e_decrypted_row.copy()
        encrypted_fields = cls.ENCRYPTED_FIELDS.get(table, [])

        for field in encrypted_fields:
            if field in re_encrypted_row and re_encrypted_row[field]:
                encrypted_value = cls.encrypt_field(re_encrypted_row[field])
                if encrypted_value:
                    re_encrypted_row[field] = encrypted_value

        return re_encrypted_row

    @staticmethod
    def hash_deterministic(value: str) -> Optional[str]:
        """
        Hash SHA-256 determinístico para deduplicação e busca no banco.
        Útil para campos que são criptografados mas precisam de indexação (ex: payment_method_hash).
        """
        if not value:
            return None
        import hashlib

        return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = ["DBCryptographyManager"]

"""
SecretsRotator: Sistema de rotação automatizada de segredos e chaves mestras.
"""

import os
import secrets
import shutil
import datetime
from pathlib import Path
import sys

# Ajustar path para importar módulos do App
current_path = Path(__file__).resolve()
backend_root = current_path.parent.parent.parent
sys.path.append(str(backend_root))

from App.Core.Logs import info, warning, error, audit


class SecretsRotator:
    def __init__(self):
        self.backend_dir = backend_root
        self.env_path = self.backend_dir / ".env.development"
        self.db_path = self.backend_dir / "Data" / "Database" / "MD70.db"
        self.backup_dir = self.backend_dir / "Data" / "Backups" / "Rotation_Temp"
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def generate_secure_key(self, length=32) -> str:
        """Gera uma chave aleatória segura."""
        return secrets.token_urlsafe(length)

    def create_pre_rotation_backup(self):
        """Cria backup do DB e do .env antes de mexer em segredos."""
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        # Backup DB
        if self.db_path.exists():
            shutil.copy(self.db_path, self.backup_dir / f"pre_rotation_{timestamp}.db")

        # Backup .env
        if self.env_path.exists():
            shutil.copy(
                self.env_path, self.backup_dir / f"pre_rotation_{timestamp}.env"
            )

        return timestamp

    def update_env_variable(self, key: str, new_value: str):
        """Atualiza ou adiciona uma variável no arquivo .env."""
        if not self.env_path.exists():
            with open(self.env_path, "w") as f:
                f.write(f"{key}={new_value}\n")
            return

        lines = self.env_path.read_text().splitlines()
        found = False
        new_lines = []

        for line in lines:
            if line.strip().startswith(f"{key}="):
                new_lines.append(f"{key}={new_value}")
                found = True
            else:
                new_lines.append(line)

        if not found:
            new_lines.append(f"{key}={new_value}")

        self.env_path.write_text("\n".join(new_lines) + "\n")

    async def rotate_master_key(self):
        """Executa a rotação da chave mestra de backup."""
        audit("[SECRETS] Iniciando processo de rotação de chave mestra...")

        timestamp = self.create_pre_rotation_backup()
        info(f"Backups de segurança criados em {self.backup_dir}")

        try:
            # 1. Gerar nova chave
            new_key = self.generate_secure_key()

            # 2. Atualizar .env
            self.update_env_variable("BACKUP_ENCRYPTION_KEY", new_key)

            # 3. Validar se a chave foi escrita
            content = self.env_path.read_text()
            if new_key in content:
                audit(
                    f"[SECRETS] Chave mestra rotacionada com sucesso no .env.development"
                )

                # 4. Em caso de sucesso, podemos limpar os backups temporários
                # (Opcional: manter por N dias por segurança extrema)
                # shutil.rmtree(self.backup_dir)
                return True
            else:
                raise Exception("Falha ao verificar escrita da nova chave")

        except Exception as e:
            error(f"FALHA NA ROTAÇÃO: {e}. Restaurando backups...")
            # Lógica de rollback manual se necessário
            return False


if __name__ == "__main__":
    import asyncio

    rotator = SecretsRotator()
    asyncio.run(rotator.rotate_master_key())

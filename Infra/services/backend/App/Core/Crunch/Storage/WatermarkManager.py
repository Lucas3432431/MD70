"""
WatermarkManager.py - Gerencia marca d'água para usuários free
Adiciona logo/stamp em imagens, PDFs e vídeos
"""

from pathlib import Path
from io import BytesIO
from typing import Optional, Union
from PIL import Image, ImageDraw

from App.Core.Logs import debug, info, warning, error
from App.Core.Crunch.Storage.StorageManager import StorageManager


class WatermarkManager:
    """Gerencia adição de marca d'água em mídias para usuários free"""

    # Logo path - MD70 logo (relativo à raiz do backend)
    LOGO_PATH = (
        Path(__file__).parent.parent.parent.parent.parent
        / "Data"
        / "Database"
        / "MD70.png"
    )

    # Extensões de imagem suportadas para watermark
    SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}

    @staticmethod
    def _ensure_logo_exists() -> bool:
        """Verifica se logo existe"""
        if not WatermarkManager.LOGO_PATH.exists():
            warning(f"[Watermark] Logo não encontrado: {WatermarkManager.LOGO_PATH}")
            return False
        return True

    @staticmethod
    def is_image_file(file_path: Union[str, Path]) -> bool:
        """
        Verifica se arquivo é uma imagem suportada.

        Args:
            file_path: Caminho do arquivo

        Returns:
            True se arquivo é imagem suportada
        """
        path = Path(file_path)
        return path.suffix.lower() in WatermarkManager.SUPPORTED_IMAGE_EXTENSIONS

    @staticmethod
    def add_image_watermark(
        original_path: Union[str, Path],
        output_path: Union[str, Path],
        opacity: float = 0.75,
        position: str = "top-center",
    ) -> bool:
        """
        Adiciona watermark a uma imagem.

        Args:
            original_path: Caminho da imagem original
            output_path: Caminho para salvar imagem com watermark
            opacity: Opacidade do watermark (0.0 - 1.0)
            position: Posição ('bottom-center', 'bottom-right', etc)

        Returns:
            True se sucesso, False se falhar
        """
        try:
            original_path = Path(original_path)
            output_path = Path(output_path)

            if not original_path.exists():
                warning(f"[Watermark] Imagem original não encontrada: {original_path}")
                return False

            if not WatermarkManager._ensure_logo_exists():
                return False

            # Abrir imagem original
            img = Image.open(original_path)

            # Converter para RGB se necessário (suporta PNG com transparência)
            if img.mode in ("RGBA", "LA", "P"):
                rgb_img = Image.new("RGB", img.size, (255, 255, 255))
                rgb_img.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
                img = rgb_img

            # Abrir logo
            logo = Image.open(WatermarkManager.LOGO_PATH)

            # Redimensionar logo (15% da altura da imagem)
            logo_height = int(img.height * 0.15)
            logo_ratio = logo.width / logo.height
            logo_width = int(logo_height * logo_ratio)
            logo = logo.resize((logo_width, logo_height), Image.Resampling.LANCZOS)

            # Aplicar opacidade ao logo
            if logo.mode != "RGBA":
                logo = logo.convert("RGBA")

            # Ajustar alpha para opacidade desejada
            alpha = logo.split()[3]
            alpha = alpha.point(lambda p: int(p * opacity))
            logo.putalpha(alpha)

            # Calcular posição (1/4 de baixo para cima, horizontalmente centralizado)
            x = (img.width - logo_width) // 2
            y = int(img.height * 0.75) - (
                logo_height // 2
            )  # 1/4 de baixo, centralizado

            # Colar logo
            if img.mode == "RGBA":
                img.alpha_composite(logo, (x, y))
            else:
                img.paste(logo, (x, y), logo)

            # Salvar com qualidade máxima
            output_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(output_path, quality=95, optimize=False)

            rel_path = StorageManager.get_relative_path(output_path)
            debug(f"[Watermark] Imagem com watermark salva: {rel_path}")
            return True

        except Exception as e:
            error(f"[Watermark] Erro ao adicionar watermark: {e}")
            import traceback

            error(f"[Watermark] Traceback: {traceback.format_exc()}")
            return False

    @staticmethod
    def add_image_watermark_memory(
        image_bytes: bytes, opacity: float = 0.75, position: str = "top-center"
    ) -> Optional[BytesIO]:
        """
        Adiciona watermark a imagem em memória (para ZIP download).

        Args:
            image_bytes: Bytes da imagem original
            opacity: Opacidade do watermark
            position: Posição do watermark

        Returns:
            BytesIO com imagem watermarkada ou None se falhar
        """
        try:
            if not WatermarkManager._ensure_logo_exists():
                return None

            # Abrir imagem do buffer
            img = Image.open(BytesIO(image_bytes))

            # Converter para RGB
            if img.mode in ("RGBA", "LA", "P"):
                rgb_img = Image.new("RGB", img.size, (255, 255, 255))
                rgb_img.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
                img = rgb_img

            # Abrir logo
            logo = Image.open(WatermarkManager.LOGO_PATH)

            # Redimensionar (30% da altura da imagem - 200% maior)
            logo_height = int(img.height * 0.3)
            logo_ratio = logo.width / logo.height
            logo_width = int(logo_height * logo_ratio)
            logo = logo.resize((logo_width, logo_height), Image.Resampling.LANCZOS)

            # Aplicar opacidade
            if logo.mode != "RGBA":
                logo = logo.convert("RGBA")
            alpha = logo.split()[3]
            alpha = alpha.point(lambda p: int(p * opacity))
            logo.putalpha(alpha)

            # Colar (1/4 de baixo para cima, horizontalmente centralizado)
            x = (img.width - logo_width) // 2
            y = int(img.height * 0.75) - (
                logo_height // 2
            )  # 1/4 de baixo, centralizado

            if img.mode == "RGBA":
                img.alpha_composite(logo, (x, y))
            else:
                img.paste(logo, (x, y), logo)

            # Retornar como BytesIO
            output = BytesIO()
            img.save(output, format="PNG", quality=95, optimize=False)
            output.seek(0)

            debug(f"[Watermark] Imagem com watermark gerada em memória")
            return output

        except Exception as e:
            error(f"[Watermark] Erro ao adicionar watermark em memória: {e}")
            return None

    @staticmethod
    def get_stamped_filename(original_filename: str) -> str:
        """
        Gera nome do arquivo com stamp.

        Exemplo: image.png → image_stamped.png

        Args:
            original_filename: Nome do arquivo original

        Returns:
            Nome do arquivo com stamp
        """
        path = Path(original_filename)
        return f"{path.stem}_stamped{path.suffix}"

    @staticmethod
    def get_watermarked_filename(original_filename: str) -> str:
        """
        Gera nome do arquivo com marca d'água.

        Exemplo: image.png → image_watermark.png

        Args:
            original_filename: Nome do arquivo original

        Returns:
            Nome do arquivo com watermark
        """
        path = Path(original_filename)
        return f"{path.stem}_watermark{path.suffix}"

    @staticmethod
    def should_apply_watermark(user_id: str) -> bool:
        """
        Verifica se usuário deve ter watermark (é free).
        Consulta o banco de dados para verificar o plano de subscrição via Client e Plans.

        Args:
            user_id: ID do usuário (string UUID)

        Returns:
            True se user é free e deve ter watermark
        """
        try:
            from App.Core.Crunch.TablesSQL.Database import database
            from sqlalchemy import text

            session = database.get_session()
            # Obter plan_type: user → client → plan
            result = session.execute(
                text(
                    """
                    SELECT p.plan_type
                    FROM users u
                    JOIN clients c ON u.client_id = c.client_id
                    JOIN plans p ON c.plan_id = p.plan_id
                    WHERE u.user_id = :user_id
                    LIMIT 1
                """
                ),
                {"user_id": user_id},
            ).fetchone()
            session.close()

            if not result:
                debug(
                    f"[Watermark] User {user_id} not found or no plan, returning False"
                )
                return False

            # Extrair plan_type e verificar se é free
            plan_type = result[0] if result else None
            is_free = plan_type in ("free", "freemium", "trial")

            debug(
                f"[Watermark] User {user_id} - Plan Type: {plan_type} - Should watermark: {is_free}"
            )
            return is_free

        except Exception as e:
            error(
                f"[Watermark] Erro ao verificar subscription do usuário {user_id}: {e}"
            )
            import traceback

            error(f"[Watermark] Traceback: {traceback.format_exc()}")
            return False

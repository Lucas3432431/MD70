"""
DocumentConverter.py - Converte HTML para PDF e JPG
Recebe HTML do frontend e gera PDF + JPG para download
Aplica watermark se usuário é free
"""

from pathlib import Path
from typing import Optional, Dict, Tuple
from io import BytesIO
import tempfile

from App.Core.Logs import debug, info, warning, error
from App.Core.Crunch.Storage.StorageManager import StorageManager
from App.Core.Crunch.Storage.WatermarkManager import WatermarkManager


class DocumentConverter:
    """Gerenciador de conversão HTML para PDF e JPG"""

    @staticmethod
    def convert_html_to_pdf(
        html_content: str, output_path: Path, filename: str = "document"
    ) -> bool:
        """
        Converte HTML para PDF.

        Args:
            html_content: Conteúdo HTML
            output_path: Caminho para salvar PDF
            filename: Nome do arquivo (sem extensão)

        Returns:
            True se sucesso, False se falhar
        """
        try:
            from weasyprint import HTML

            # Criar diretório se não existir
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Converter HTML para PDF
            pdf_path = output_path / f"{filename}.pdf"
            HTML(string=html_content).write_pdf(pdf_path)

            debug(f"[DocConverter] PDF gerado: {filename}.pdf")
            return True

        except ImportError:
            error(
                "[DocConverter] weasyprint não instalado. Instale: pip install weasyprint"
            )
            return False
        except Exception as e:
            error(f"[DocConverter] Erro ao gerar PDF: {e}")
            return False

    @staticmethod
    def convert_html_to_jpg(
        html_content: str, output_path: Path, filename: str = "document"
    ) -> bool:
        """
        Converte HTML para JPG (imagem).

        Args:
            html_content: Conteúdo HTML
            output_path: Caminho para salvar JPG
            filename: Nome do arquivo (sem extensão)

        Returns:
            True se sucesso, False se falhar
        """
        try:
            from html2image import HtmlImageConverter

            # Criar diretório se não existir
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Salvar HTML temporário
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".html", delete=False, encoding="utf-8"
            ) as f:
                f.write(html_content)
                temp_html = Path(f.name)

            try:
                # Converter para JPG
                converter = HtmlImageConverter(
                    temp_html, str(output_path / f"{filename}")
                )
                converter.save(image_format="jpg")

                debug(f"[DocConverter] JPG gerado: {filename}.jpg")
                return True

            finally:
                # Limpar arquivo temporário
                try:
                    temp_html.unlink()
                except:
                    pass

        except ImportError:
            error(
                "[DocConverter] html2image não instalado. Instale: pip install html2image"
            )
            return False
        except Exception as e:
            error(f"[DocConverter] Erro ao gerar JPG: {e}")
            return False

    @staticmethod
    def convert_html_to_pdf_and_jpg(
        html_content: str,
        output_dir: Path,
        filename: str = "document",
        user_id: Optional[str] = None,
    ) -> Optional[Dict[str, str]]:
        """
        Converte HTML para PDF e JPG com watermark opcional.

        Args:
            html_content: Conteúdo HTML
            output_dir: Diretório para salvar arquivos
            filename: Nome base do arquivo (sem extensão)
            user_id: ID do usuário (para verificar se é free e aplicar watermark)

        Returns:
            Dict com paths dos arquivos ou None se falhar
            {
                "pdf": "/caminho/para/arquivo.pdf",
                "jpg": "/caminho/para/arquivo.jpg",
                "watermarked_pdf": "/caminho/para/arquivo_watermark.pdf" (opcional),
                "watermarked_jpg": "/caminho/para/arquivo_watermark.jpg" (opcional)
            }
        """
        try:
            output_dir.mkdir(parents=True, exist_ok=True)

            # Verificar se deve aplicar watermark
            should_watermark = False
            if user_id:
                should_watermark = WatermarkManager.should_apply_watermark(user_id)
                if should_watermark:
                    debug(
                        f"[DocConverter] Usuário {user_id} é free - será aplicado watermark"
                    )

            result = {}

            # 1. Converter para PDF
            if not DocumentConverter.convert_html_to_pdf(
                html_content, output_dir, filename
            ):
                error("[DocConverter] Falha ao gerar PDF")
                return None

            pdf_path = output_dir / f"{filename}.pdf"
            result["pdf"] = str(pdf_path)

            # 2. Converter para JPG
            if not DocumentConverter.convert_html_to_jpg(
                html_content, output_dir, filename
            ):
                error("[DocConverter] Falha ao gerar JPG")
                return None

            jpg_path = output_dir / f"{filename}.jpg"
            result["jpg"] = str(jpg_path)

            # 3. Aplicar watermark se necessário
            if should_watermark:
                try:
                    # Aplicar watermark ao PDF (se for imagem antes)
                    # Para PDF, salvar versão com "_watermark" no nome
                    watermarked_pdf_path = output_dir / f"{filename}_watermark.pdf"
                    # Na verdade, não podemos adicionar watermark com PIL em PDF
                    # Vamos converter JPG com watermark e descartar o PDF watermarkado

                    # Aplicar watermark ao JPG
                    watermarked_jpg_path = output_dir / f"{filename}_watermark.jpg"
                    if WatermarkManager.add_image_watermark(
                        jpg_path, watermarked_jpg_path
                    ):
                        result["watermarked_jpg"] = str(watermarked_jpg_path)
                        debug(
                            f"[DocConverter] JPG com watermark gerado: {filename}_watermark.jpg"
                        )
                    else:
                        warning(f"[DocConverter] Falha ao gerar JPG com watermark")

                except Exception as e:
                    warning(f"[DocConverter] Erro ao aplicar watermark: {e}")

            info(f"[DocConverter] Conversão concluída: {filename}")
            return result

        except Exception as e:
            error(f"[DocConverter] Erro ao converter HTML: {e}")
            import traceback

            error(f"[DocConverter] Traceback: {traceback.format_exc()}")
            return None

"""
MediaCompressor.py - Sistema de compressão de mídia
Converte imagens para WebP + reduz resolução para IA
"""

from pathlib import Path
from typing import Optional, Tuple, Dict
from PIL import Image
import io

from App.Core.Logs import debug, info, warning, error
from App.Core.Crunch.Storage.StorageManager import StorageManager


class MediaCompressor:
    """Compressor de mídia com suporte a múltiplos formatos"""

    # Configurações
    SUPPORTED_FORMATS = {
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
        "image/bmp",
    }
    MAX_WIDTH_STORAGE = 4096  # Armazenamento: sem limite prático
    MAX_WIDTH_AI = 512  # IA: máximo 512px (reduzido bastante)
    MAX_HEIGHT_AI = 384  # IA: máximo 384px (metade de 1024x768)

    # Qualidade de compressão
    QUALITY_WEBP = 85  # 1-100 (armazenamento, alta qualidade)
    QUALITY_AI = 40  # 1-100 (IA muito agressivo, metade de 75%)

    @staticmethod
    def get_image_dimensions(file_path: Path) -> Optional[Tuple[int, int]]:
        """Obtém dimensões da imagem sem carregar na memória"""
        try:
            with Image.open(file_path) as img:
                return img.size
        except Exception as e:
            error(f"[COMPRESS] Erro ao obter dimensões: {e}")
            return None

    @staticmethod
    def convert_to_webp(
        input_path: Path, output_path: Optional[Path] = None, quality: int = 85
    ) -> Optional[Path]:
        """
        Converte imagem para WebP com compressão.

        Args:
            input_path: Caminho do arquivo original
            output_path: Caminho de saída (default: mesmo nome, extensão .webp)
            quality: Qualidade (1-100)

        Returns:
            Path do arquivo convertido ou None se falhar
        """
        try:
            if not input_path.exists():
                raise FileNotFoundError(f"Arquivo não encontrado: {input_path}")

            if output_path is None:
                output_path = input_path.with_suffix(".webp")

            # Abrir e converter
            with Image.open(input_path) as img:
                # Converter RGBA para RGB se necessário (WebP suporta alpha)
                if img.mode in ("RGBA", "LA", "P"):
                    # Se tiver transparência, manter como RGBA
                    if img.mode == "P" and "transparency" in img.info:
                        pass  # WebP suporta
                    elif img.mode != "RGBA":
                        img = img.convert("RGBA")
                else:
                    img = img.convert("RGB")

                # Salvar como WebP
                img.save(
                    output_path,
                    "WEBP",
                    quality=quality,
                    method=6,  # Método mais lento = melhor compressão
                )

            original_size = input_path.stat().st_size
            compressed_size = output_path.stat().st_size
            reduction = (
                ((original_size - compressed_size) / original_size * 100)
                if original_size > 0
                else 0
            )

            debug(f"[COMPRESS] WebP: {input_path.name} → {output_path.name}")
            debug(
                f"[COMPRESS] Redução: {reduction:.1f}% ({original_size}B → {compressed_size}B)"
            )

            return output_path

        except Exception as e:
            error(f"[COMPRESS] Erro ao converter para WebP: {e}")
            return None

    @staticmethod
    def resize_for_ai(
        input_path: Path,
        output_path: Optional[Path] = None,
        max_width: int = 1024,
        max_height: int = 768,
        quality: int = 75,
    ) -> Optional[Path]:
        """
        Redimensiona imagem para enviar para IA (reduz latência + tokens).

        Args:
            input_path: Caminho do arquivo original
            output_path: Caminho de saída (default: {name}_ai.webp)
            max_width: Largura máxima
            max_height: Altura máxima
            quality: Qualidade WebP

        Returns:
            Path do arquivo redimensionado
        """
        try:
            if not input_path.exists():
                raise FileNotFoundError(f"Arquivo não encontrado: {input_path}")

            if output_path is None:
                stem = input_path.stem
                output_path = input_path.parent / f"{stem}_ai.webp"

            with Image.open(input_path) as img:
                original_size = img.size

                # Calcular novo tamanho mantendo proporção
                img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)

                # Converter para RGB/RGBA
                if img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGB")

                # Salvar como WebP
                img.save(output_path, "WEBP", quality=quality, method=6)

            final_size = output_path.stat().st_size
            debug(f"[COMPRESS] Resize IA: {original_size} → {img.size}")
            debug(f"[COMPRESS] Tamanho final: {final_size}B")

            return output_path

        except Exception as e:
            error(f"[COMPRESS] Erro ao redimensionar para IA: {e}")
            return None

    @staticmethod
    def process_upload(
        file_path: Path, client_id: int, for_ai: bool = True
    ) -> Dict[str, Optional[Path]]:
        """
        Pipeline completo de processamento de upload:
        1. Converte para WebP (armazenamento)
        2. Cria versão reduzida para IA

        Args:
            file_path: Arquivo de upload
            client_id: ID do cliente
            for_ai: Se deve criar versão reduzida para IA

        Returns:
            Dict com caminhos: {'storage': Path, 'ai': Path}
        """
        try:
            result = {"storage": None, "ai": None, "original": file_path}

            # 1. Converter para WebP (armazenamento)
            webp_path = file_path.with_suffix(".webp")
            result["storage"] = MediaCompressor.convert_to_webp(
                file_path, output_path=webp_path, quality=MediaCompressor.QUALITY_WEBP
            )

            if not result["storage"]:
                rel_path = StorageManager.get_relative_path(file_path)
                error(f"[PROCESS] Falha ao converter para WebP: {rel_path}")
                return result

            # 2. Criar versão para IA (se pedido)
            if for_ai:
                result["ai"] = MediaCompressor.resize_for_ai(
                    result["storage"],
                    max_width=MediaCompressor.MAX_WIDTH_AI,
                    max_height=MediaCompressor.MAX_HEIGHT_AI,
                    quality=MediaCompressor.QUALITY_AI,
                )

            # 3. Deletar original se não for necessário
            try:
                if file_path != result["storage"] and file_path.exists():
                    file_path.unlink()
                    rel_path = StorageManager.get_relative_path(file_path)
                    debug(f"[PROCESS] Original deletado: {rel_path}")
            except Exception as e:
                warning(f"[PROCESS] Não foi possível deletar original: {e}")

            info(f"[PROCESS] Upload processado para client {client_id}")
            return result

        except Exception as e:
            error(f"[PROCESS] Erro no pipeline: {e}")
            return {"storage": None, "ai": None, "original": file_path}

    @staticmethod
    def batch_process_folder(
        folder_path: Path,
        client_id: int,
        for_ai: bool = True,
        skip_existing: bool = True,
    ) -> Dict[str, int]:
        """
        Processa todas as imagens em uma pasta.

        Args:
            folder_path: Pasta com imagens
            client_id: ID do cliente
            for_ai: Criar versões para IA
            skip_existing: Pular se já é WebP

        Returns:
            Dict com contagem de processadas/erradas
        """
        stats = {
            "processed": 0,
            "skipped": 0,
            "errors": 0,
            "total_saved": 0,
            "total_reduction": 0,
        }

        try:
            # Buscar todas as imagens
            image_files = list(folder_path.glob("*.*"))
            image_files = [
                f
                for f in image_files
                if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".bmp"}
            ]

            if not image_files:
                debug(f"[BATCH] Nenhuma imagem encontrada em {folder_path}")
                return stats

            info(f"[BATCH] Processando {len(image_files)} imagens em {folder_path}")

            for img_file in image_files:
                # Skip se é WebP e skip_existing=True
                if skip_existing and img_file.suffix.lower() == ".webp":
                    stats["skipped"] += 1
                    continue

                result = MediaCompressor.process_upload(
                    img_file, client_id, for_ai=for_ai
                )

                if result["storage"]:
                    stats["processed"] += 1
                    stats["total_saved"] += result["storage"].stat().st_size
                else:
                    stats["errors"] += 1

            info(
                f"[BATCH] Resultado: {stats['processed']} processadas, {stats['skipped']} puladas, {stats['errors']} erros"
            )
            return stats

        except Exception as e:
            error(f"[BATCH] Erro ao processar pasta: {e}")
            stats["errors"] += 1
            return stats

    @staticmethod
    def get_compression_stats(
        original_path: Path, compressed_path: Path
    ) -> Dict[str, float]:
        """Calcula estatísticas de compressão"""
        try:
            original_size = (
                original_path.stat().st_size if original_path.exists() else 0
            )
            compressed_size = (
                compressed_path.stat().st_size if compressed_path.exists() else 0
            )

            if original_size == 0:
                return {
                    "reduction_percent": 0,
                    "original_size": 0,
                    "compressed_size": 0,
                    "saved_bytes": 0,
                }

            reduction = ((original_size - compressed_size) / original_size) * 100
            saved = original_size - compressed_size

            return {
                "reduction_percent": round(reduction, 2),
                "original_size": original_size,
                "compressed_size": compressed_size,
                "saved_bytes": saved,
            }

        except Exception as e:
            error(f"[STATS] Erro ao calcular: {e}")
            return {"error": str(e)}

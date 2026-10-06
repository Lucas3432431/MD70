"""
Storage Package - Gerencia armazenamento, compressão, watermark e downloads
"""

from App.Core.Crunch.Storage.StorageManager import StorageManager
from App.Core.Crunch.Storage.MediaCompressor import MediaCompressor
from .WatermarkManager import WatermarkManager

__all__ = [
    "StorageManager",
    "MediaCompressor",
    "WatermarkManager",
]

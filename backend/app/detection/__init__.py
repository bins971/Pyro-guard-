"""Detection package initialization"""
from .detector import FireDetector
from .classifier import FireLevelClassifier
from .stream_handler import StreamHandler, MultiStreamHandler

__all__ = ['FireDetector', 'FireLevelClassifier', 'StreamHandler', 'MultiStreamHandler']

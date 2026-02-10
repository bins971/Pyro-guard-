"""API package initialization"""
from .cameras import router as cameras_router
from .detections import router as detections_router
from .alerts import router as alerts_router

__all__ = ['cameras_router', 'detections_router', 'alerts_router']

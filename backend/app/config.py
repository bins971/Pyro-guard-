"""
Configuration management for PYRO-GUARD system
"""
import os

# Set environment variables BEFORE any other imports to bypass Windows path issues with spaces
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..")).replace("\\", "/")
CONFIG_DIR = os.path.join(PROJECT_ROOT, "yolo_config").replace("\\", "/")
os.makedirs(CONFIG_DIR, exist_ok=True)
os.environ["YOLO_CONFIG_DIR"] = CONFIG_DIR
os.environ["ULTRALYTICS_CONFIG_DIR"] = CONFIG_DIR
os.environ["ULTRALYTICS_DATASETS_DIR"] = PROJECT_ROOT
os.environ["PYTHONUTF8"] = "1"

from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # Database
    DATABASE_URL: str = "postgresql://postgres:password@localhost:5432/pyroguard"
    
    # Model Configuration
    MODEL_PATH: str = "models/fire_yolov8.pt"
    
    @property
    def absolute_model_path(self) -> str:
        """Resolve model path to absolute based on project root"""
        if os.path.isabs(self.MODEL_PATH):
            return self.MODEL_PATH
        return os.path.join(PROJECT_ROOT, self.MODEL_PATH).replace("\\", "/")

    CONFIDENCE_THRESHOLD: float = 0.5
    FIRE_LEVEL_THRESHOLDS: str = "0.05,0.15"
    
    # Email Configuration (Brevo SMTP)
    SMTP_HOST: str = "smtp-relay.brevo.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""  # Your Brevo SMTP login
    SMTP_PASSWORD: str = ""  # Your Brevo SMTP key
    SMTP_FROM: str = "pyroguard@example.com"
    ALERT_RECIPIENTS: str = ""
    
    # Application Settings
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"
    
    # Camera Settings
    MAX_CAMERAS: int = 10
    FRAME_SKIP: int = 3
    FRAME_WIDTH: int = 320
    FRAME_HEIGHT: int = 240
    
    # Alert Settings
    ALERT_COOLDOWN_SECONDS: int = 300
    MIN_CONFIDENCE_FOR_ALERT: float = 0.7
    
    class Config:
        env_file = os.path.join(PROJECT_ROOT, ".env")
        case_sensitive = True
    
    @property
    def fire_level_thresholds_list(self) -> List[float]:
        """Parse fire level thresholds from string"""
        return [float(x) for x in self.FIRE_LEVEL_THRESHOLDS.split(",")]
    
    @property
    def alert_recipients_list(self) -> List[str]:
        """Parse alert recipients from string"""
        if not self.ALERT_RECIPIENTS:
            return []
        return [x.strip() for x in self.ALERT_RECIPIENTS.split(",")]


# Global settings instance
settings = Settings()

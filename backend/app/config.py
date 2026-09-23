import os

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
    DATABASE_URL: str = "sqlite:///./pyroguard.db"
    MODEL_PATH: str = "models/fire_yolov8.pt"

    @property
    def absolute_model_path(self) -> str:
        if os.path.isabs(self.MODEL_PATH):
            return self.MODEL_PATH
        return os.path.join(PROJECT_ROOT, self.MODEL_PATH).replace("\\", "/")

    CONFIDENCE_THRESHOLD: float = 0.50
    SMOKE_CONFIDENCE_THRESHOLD: float = 0.35
    SMALL_FIRE_CONFIDENCE_THRESHOLD: float = 0.50
    FIRE_LEVEL_THRESHOLDS: str = "0.02,0.10"
    ENABLE_COLOR_FALLBACK: bool = False
    ENABLE_FLICKER_VERIFICATION: bool = True
    MIN_FLICKER_SCORE: float = 1.5

    SMTP_HOST: str = "smtp-relay.brevo.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "pyroguard@example.com"
    ALERT_RECIPIENTS: str = ""
    
    BREVO_API_KEY: str = ""
    SMS_RECIPIENTS: str = ""

    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    MAX_CAMERAS: int = 4
    FRAME_SKIP: int = 2
    FRAME_WIDTH: int = 640
    FRAME_HEIGHT: int = 480
    
    INFERENCE_SIZE: int = 192


    ALERT_COOLDOWN_SECONDS: int = 300
    MIN_CONFIDENCE_FOR_ALERT: float = 0.25

    DETECTION_PERSISTENCE_FRAMES: int = 4
    SENSOR_VERIFICATION_ENABLED: bool = True
    REQUIRE_SMOKE_FOR_LOW_CONF: bool = True

    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_S3_BUCKET: str = ""
    AWS_REGION: str = "ap-southeast-1"

    HARDWARE_MODE: str = "pc"

    class Config:
        env_file = os.path.join(PROJECT_ROOT, ".env")
        case_sensitive = True
        extra = "ignore"

    @property
    def fire_level_thresholds_list(self) -> List[float]:
        return [float(x) for x in self.FIRE_LEVEL_THRESHOLDS.split(",")]

    @property
    def alert_recipients_list(self) -> List[str]:
        if not self.ALERT_RECIPIENTS:
            return []
        return [x.strip() for x in self.ALERT_RECIPIENTS.split(",")]


settings = Settings()


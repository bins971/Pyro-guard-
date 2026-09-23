from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


class CameraBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    location: Optional[str] = Field(None, max_length=200)
    rtsp_url: Optional[str] = Field(None, max_length=500)
    is_active: bool = True


class CameraCreate(CameraBase):
    pass


class CameraUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    location: Optional[str] = None
    rtsp_url: Optional[str] = None
    is_active: Optional[bool] = None


class Camera(CameraBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class DetectionBase(BaseModel):
    camera_id: int
    fire_level: int = Field(..., ge=0, le=3)
    confidence: float = Field(..., ge=0.0, le=1.0)
    bbox_area: Optional[float] = Field(None, ge=0.0, le=1.0)
    image_path: Optional[str] = None
    detection_metadata: Optional[Dict[str, Any]] = None


class DetectionCreate(DetectionBase):
    pass


class Detection(DetectionBase):
    id: int
    timestamp: datetime

    class Config:
        from_attributes = True


class DetectionWithCamera(Detection):
    camera: Camera


class AlertBase(BaseModel):
    detection_id: int
    alert_type: str = Field(..., pattern="^(email|sms|both)$")
    recipients: List[str]


class AlertCreate(AlertBase):
    pass


class Alert(AlertBase):
    id: int
    sent_at: datetime
    status: str
    error_message: Optional[str] = None

    class Config:
        from_attributes = True


class AlertWithDetection(Alert):
    detection: Detection


class FireLevelStats(BaseModel):
    level_0: int = 0
    level_1: int = 0
    level_2: int = 0
    level_3: int = 0


class CameraStats(BaseModel):
    camera_id: int
    camera_name: str
    total_detections: int
    fire_level_distribution: FireLevelStats
    last_detection: Optional[datetime] = None


class SystemStats(BaseModel):
    total_cameras: int
    active_cameras: int
    total_detections: int
    total_alerts: int
    fire_level_distribution: FireLevelStats
    recent_detections: List[Detection]


class LiveDetectionResult(BaseModel):
    camera_id: int
    fire_detected: bool
    fire_level: int
    confidence: float
    bbox_area: Optional[float] = None
    bounding_boxes: Optional[List[Dict[str, Any]]] = None
    timestamp: datetime

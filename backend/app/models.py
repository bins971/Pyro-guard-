from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, ARRAY, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
from .database import Base


class Camera(Base):
    __tablename__ = "cameras"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    location = Column(String(200))
    rtsp_url = Column(String(500))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    ptz_enabled = Column(Boolean, default=False)
    ptz_user = Column(String(100), nullable=True)
    ptz_password = Column(String(100), nullable=True)
    ptz_port = Column(Integer, default=80)

    detections = relationship("Detection", back_populates="camera", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Camera(id={self.id}, name='{self.name}', location='{self.location}')>"


class Detection(Base):
    __tablename__ = "detections"

    id = Column(Integer, primary_key=True, index=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=False), default=datetime.now, index=True)

    fire_level = Column(Integer, nullable=False)
    confidence = Column(Float, nullable=False)
    bbox_area = Column(Float)

    image_path = Column(String(500))
    image_url = Column(String(1000))

    detection_metadata = Column(JSON)

    camera = relationship("Camera", back_populates="detections")
    alerts = relationship("Alert", back_populates="detection", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Detection(id={self.id}, camera_id={self.camera_id}, level={self.fire_level}, confidence={self.confidence:.2f})>"


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    detection_id = Column(Integer, ForeignKey("detections.id"), nullable=False, index=True)

    alert_type = Column(String(50))
    sent_at = Column(DateTime(timezone=True), server_default=func.now())
    status = Column(String(20), default='pending')

    recipients = Column(JSON)

    error_message = Column(String(500))

    detection = relationship("Detection", back_populates="alerts")

    def __repr__(self):
        return f"<Alert(id={self.id}, detection_id={self.detection_id}, type='{self.alert_type}', status='{self.status}')>"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    hashed_password = Column(String(200), nullable=False)
    is_admin = Column(Boolean, default=False)
    role = Column(String(20), default="operator")  # "admin", "operator", "viewer"
    is_approved = Column(Boolean, default=True)  # True for approved users, False for pending registration
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<User(id={self.id}, username='{self.username}', role='{self.role}')>"


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=False), default=datetime.now, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    username = Column(String(50), nullable=False)
    action = Column(String(100), nullable=False)
    details = Column(String(500), nullable=True)
    ip_address = Column(String(50), nullable=True)

    def __repr__(self):
        return f"<AuditLog(id={self.id}, username='{self.username}', action='{self.action}')>"


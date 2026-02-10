"""
SQLAlchemy database models for PYRO-GUARD
"""
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, ARRAY, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .database import Base


class Camera(Base):
    """Camera configuration and metadata"""
    __tablename__ = "cameras"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    location = Column(String(200))
    rtsp_url = Column(String(500))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    detections = relationship("Detection", back_populates="camera", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Camera(id={self.id}, name='{self.name}', location='{self.location}')>"


class Detection(Base):
    __tablename__ = "detections"
    
    id = Column(Integer, primary_key=True, index=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    
    # Detection details
    fire_level = Column(Integer, nullable=False)
    confidence = Column(Float, nullable=False)
    bbox_area = Column(Float) 
    
    # Image storage
    image_path = Column(String(500))
    
    # Additional metadata (bounding boxes, etc.)
    detection_metadata = Column(JSON)
    
    # Relationships
    camera = relationship("Camera", back_populates="detections")
    alerts = relationship("Alert", back_populates="detection", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Detection(id={self.id}, camera_id={self.camera_id}, level={self.fire_level}, confidence={self.confidence:.2f})>"


class Alert(Base):
    """Alert notification records"""
    __tablename__ = "alerts"
    
    id = Column(Integer, primary_key=True, index=True)
    detection_id = Column(Integer, ForeignKey("detections.id"), nullable=False, index=True)
    
    # Alert details
    alert_type = Column(String(50)) 
    sent_at = Column(DateTime(timezone=True), server_default=func.now())
    status = Column(String(20), default='pending') 
    
    # Recipients
    recipients = Column(JSON)
    
    # Error message if failed
    error_message = Column(String(500))
    
    # Relationships
    detection = relationship("Detection", back_populates="alerts")
    
    def __repr__(self):
        return f"<Alert(id={self.id}, detection_id={self.detection_id}, type='{self.alert_type}', status='{self.status}')>"

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List, Optional
from datetime import datetime, timedelta
from ..database import get_db
from ..models import Detection, Camera
from ..schemas import Detection as DetectionSchema, DetectionWithCamera, FireLevelStats

router = APIRouter(prefix="/detections", tags=["detections"])


@router.get("/", response_model=List[DetectionWithCamera])
def list_detections(
    skip: int = 0,
    limit: int = 100,
    camera_id: Optional[int] = None,
    fire_level: Optional[int] = Query(None, ge=0, le=3),
    min_confidence: Optional[float] = Query(None, ge=0.0, le=1.0),
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Detection)

    if camera_id:
        query = query.filter(Detection.camera_id == camera_id)

    if fire_level is not None:
        query = query.filter(Detection.fire_level == fire_level)

    if min_confidence:
        query = query.filter(Detection.confidence >= min_confidence)

    if start_date:
        query = query.filter(Detection.timestamp >= start_date)

    if end_date:
        query = query.filter(Detection.timestamp <= end_date)

    query = query.order_by(desc(Detection.timestamp))

    detections = query.offset(skip).limit(limit).all()
    return detections


@router.get("/{detection_id}", response_model=DetectionWithCamera)
def get_detection(detection_id: int, db: Session = Depends(get_db)):
    detection = db.query(Detection).filter(Detection.id == detection_id).first()
    if not detection:
        raise HTTPException(status_code=404, detail="Detection not found")
    return detection


@router.get("/stats/summary")
def get_detection_stats(
    camera_id: Optional[int] = None,
    days: int = Query(7, ge=1, le=365),
    db: Session = Depends(get_db)
):
    start_date = datetime.now() - timedelta(days=days)

    query = db.query(Detection).filter(Detection.timestamp >= start_date)

    if camera_id:
        query = query.filter(Detection.camera_id == camera_id)

    detections = query.all()

    total_detections = len(detections)

    fire_level_distribution = {
        "level_0": sum(1 for d in detections if d.fire_level == 0),
        "level_1": sum(1 for d in detections if d.fire_level == 1),
        "level_2": sum(1 for d in detections if d.fire_level == 2),
        "level_3": sum(1 for d in detections if d.fire_level == 3),
    }

    avg_confidence = sum(d.confidence for d in detections) / total_detections if total_detections > 0 else 0

    return {
        "total_detections": total_detections,
        "fire_level_distribution": fire_level_distribution,
        "average_confidence": avg_confidence,
        "period_days": days,
        "start_date": start_date,
        "end_date": datetime.now()
    }


@router.get("/stats/timeline")
def get_detection_timeline(
    camera_id: Optional[int] = None,
    days: int = Query(7, ge=1, le=365),
    db: Session = Depends(get_db)
):
    start_date = datetime.now() - timedelta(days=days)

    query = db.query(Detection).filter(Detection.timestamp >= start_date)

    if camera_id:
        query = query.filter(Detection.camera_id == camera_id)

    detections = query.order_by(Detection.timestamp).all()

    timeline = {}
    for detection in detections:
        date_key = detection.timestamp.strftime('%Y-%m-%d')
        if date_key not in timeline:
            timeline[date_key] = {
                "date": date_key,
                "total": 0,
                "level_0": 0,
                "level_1": 0,
                "level_2": 0,
                "level_3": 0
            }

        timeline[date_key]["total"] += 1
        timeline[date_key][f"level_{detection.fire_level}"] += 1

    return {
        "timeline": list(timeline.values()),
        "period_days": days
    }


@router.get("/stats/by-camera")
def get_detections_by_camera(
    days: int = Query(7, ge=1, le=365),
    db: Session = Depends(get_db)
):
    start_date = datetime.now() - timedelta(days=days)

    cameras = db.query(Camera).all()

    camera_stats = []
    for camera in cameras:
        detections = db.query(Detection).filter(
            Detection.camera_id == camera.id,
            Detection.timestamp >= start_date
        ).all()

        fire_level_distribution = {
            "level_0": sum(1 for d in detections if d.fire_level == 0),
            "level_1": sum(1 for d in detections if d.fire_level == 1),
            "level_2": sum(1 for d in detections if d.fire_level == 2),
            "level_3": sum(1 for d in detections if d.fire_level == 3),
        }

        last_detection = max((d.timestamp for d in detections), default=None)

        camera_stats.append({
            "camera_id": camera.id,
            "camera_name": camera.name,
            "location": camera.location,
            "total_detections": len(detections),
            "fire_level_distribution": fire_level_distribution,
            "last_detection": last_detection
        })

    return {
        "cameras": camera_stats,
        "period_days": days
    }

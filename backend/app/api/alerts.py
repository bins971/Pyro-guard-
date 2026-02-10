"""
Alert API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List, Optional
from ..database import get_db
from ..models import Alert, Detection
from ..schemas import Alert as AlertSchema, AlertWithDetection

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("/", response_model=List[AlertWithDetection])
def list_alerts(
    skip: int = 0,
    limit: int = 100,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    List all alerts
    """
    query = db.query(Alert)
    
    if status:
        query = query.filter(Alert.status == status)
    
    query = query.order_by(desc(Alert.sent_at))
    
    alerts = query.offset(skip).limit(limit).all()
    return alerts


@router.get("/{alert_id}", response_model=AlertWithDetection)
def get_alert(alert_id: int, db: Session = Depends(get_db)):
    """
    Get alert by ID
    """
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert


@router.get("/stats/summary")
def get_alert_stats(db: Session = Depends(get_db)):
    """
    Get alert statistics
    """
    total_alerts = db.query(Alert).count()
    sent_alerts = db.query(Alert).filter(Alert.status == 'sent').count()
    failed_alerts = db.query(Alert).filter(Alert.status == 'failed').count()
    pending_alerts = db.query(Alert).filter(Alert.status == 'pending').count()
    
    return {
        "total_alerts": total_alerts,
        "sent": sent_alerts,
        "failed": failed_alerts,
        "pending": pending_alerts,
        "success_rate": (sent_alerts / total_alerts * 100) if total_alerts > 0 else 0
    }

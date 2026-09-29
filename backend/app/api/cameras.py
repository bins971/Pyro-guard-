from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from ..database import get_db
from ..models import Camera
from ..schemas import Camera as CameraSchema, CameraCreate, CameraUpdate
from ..detection import MultiStreamHandler

router = APIRouter(prefix="/cameras", tags=["cameras"])

stream_handler: MultiStreamHandler = None


def set_stream_handler(handler: MultiStreamHandler):
    global stream_handler
    stream_handler = handler


@router.post("/", response_model=CameraSchema, status_code=status.HTTP_201_CREATED)
def create_camera(camera: CameraCreate, db: Session = Depends(get_db)):
    db_camera = Camera(**camera.model_dump())
    db.add(db_camera)
    db.commit()
    db.refresh(db_camera)

    if db_camera.is_active and db_camera.rtsp_url and stream_handler:
        stream_handler.add_stream(db_camera.id, db_camera.rtsp_url)

    return db_camera


def _enrich_camera(cam: Camera) -> dict:
    is_online = False
    if stream_handler and cam.is_active:
        stream = stream_handler.get_stream(cam.id)
        if stream and stream.is_active():
            is_online = True

    cam_name = "Camera 1" if cam.name and "usb" in cam.name.lower() else cam.name
    return {
        "id": cam.id,
        "name": cam_name,
        "location": cam.location,
        "rtsp_url": cam.rtsp_url,
        "is_active": cam.is_active,
        "is_online": is_online,
        "created_at": cam.created_at,
        "updated_at": cam.updated_at
    }


@router.get("/", response_model=List[CameraSchema])
def list_cameras(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    cameras = db.query(Camera).offset(skip).limit(limit).all()
    return [_enrich_camera(c) for c in cameras]


@router.get("/{camera_id}", response_model=CameraSchema)
def get_camera(camera_id: int, db: Session = Depends(get_db)):
    camera = db.query(Camera).filter(Camera.id == camera_id).first()
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    return _enrich_camera(camera)


@router.put("/{camera_id}", response_model=CameraSchema)
def update_camera(camera_id: int, camera_update: CameraUpdate, db: Session = Depends(get_db)):
    db_camera = db.query(Camera).filter(Camera.id == camera_id).first()
    if not db_camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    update_data = camera_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_camera, field, value)

    db.commit()
    db.refresh(db_camera)

    if stream_handler:
        if db_camera.is_active and db_camera.rtsp_url:
            stream_handler.remove_stream(camera_id)
            stream_handler.add_stream(camera_id, db_camera.rtsp_url)
        else:
            stream_handler.remove_stream(camera_id)

    return db_camera


@router.delete("/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_camera(camera_id: int, db: Session = Depends(get_db)):
    db_camera = db.query(Camera).filter(Camera.id == camera_id).first()
    if not db_camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    if stream_handler:
        stream_handler.remove_stream(camera_id)

    db.delete(db_camera)
    db.commit()

    return None


@router.get("/{camera_id}/status")
def get_camera_status(camera_id: int, db: Session = Depends(get_db)):
    camera = db.query(Camera).filter(Camera.id == camera_id).first()
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    stream_active = False
    fps = 0.0

    if stream_handler:
        stream = stream_handler.get_stream(camera_id)
        if stream:
            stream_active = stream.is_active()
            fps = stream.get_fps()

    return {
        "camera_id": camera_id,
        "is_active": camera.is_active,
        "stream_active": stream_active,
        "fps": fps
    }

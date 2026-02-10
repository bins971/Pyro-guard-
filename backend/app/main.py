"""
Main FastAPI application for PYRO-GUARD
"""
from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from contextlib import asynccontextmanager
import asyncio
import cv2
import os
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from .config import settings
from .database import init_db, SessionLocal
from .models import Camera, Detection, Alert
from .detection import FireDetector, MultiStreamHandler
from .services import AlertService
from .api import cameras_router, detections_router, alerts_router
from .api.cameras import set_stream_handler
from .hardware import SensorManager, VirtualFireSensor

import logging
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("backend.log")
    ]
)
logger = logging.getLogger(__name__)

# Global instances
detector = FireDetector()
stream_handler = MultiStreamHandler()
alert_service = AlertService()
sensor_manager = SensorManager(update_interval=2.0)

# Register default virtual sensor for testing
sensor_manager.register_sensor(VirtualFireSensor("sim_temp_01", "Ambient Monitor"))

# Track last alert time per camera to implement cooldown
last_alert_time = {}


async def monitor_cameras():
    """
    Background task to continuously monitor cameras and detect fire
    """
    logger.info("Starting camera monitoring...")
    
    while True:
        try:
            db = SessionLocal()
            
            # Get all active streams
            streams = stream_handler.get_all_streams()
            
            frame_count = getattr(monitor_cameras, 'frame_count', 0)
            monitor_cameras.frame_count = frame_count + 1
            
            # Process every 3rd frame (adjust number based on CPU load)
            if monitor_cameras.frame_count % 3 != 0:
                await asyncio.sleep(0.01)
                continue
            
            for camera_id, stream in streams.items():
                frame = stream.get_frame(timeout=0.5)
                
                if frame is None:
                    continue
                
                result = detector.detect(frame)
                
                camera = db.query(Camera).filter(Camera.id == camera_id).first()
                if not camera:
                    continue
                
                # Only save if fire detected or periodically
                if result['fire_detected'] and result['fire_level'] > 0:
                    image_dir = "detections"
                    os.makedirs(image_dir, exist_ok=True)
                    
                    timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
                    image_filename = f"{camera_id}_{timestamp_str}.jpg"
                    image_path = os.path.join(image_dir, image_filename)
                    
                    # Draw detections and save
                    annotated_frame = detector.draw_detections(frame, result)
                    cv2.imwrite(image_path, annotated_frame)
                    
                    # Create detection record
                    detection = Detection(
                        camera_id=camera_id,
                        fire_level=result['fire_level'],
                        confidence=result['confidence'],
                        bbox_area=result['bbox_area'],
                        image_path=image_path,
                        detection_metadata=result['metadata']
                    )
                    db.add(detection)
                    db.commit()
                    db.refresh(detection)
                    
                    if result['confidence'] >= settings.MIN_CONFIDENCE_FOR_ALERT:
                        current_time = datetime.now()
                        last_alert = last_alert_time.get(camera_id)
                        
                        # Check cooldown
                        if last_alert is None or (current_time - last_alert).total_seconds() >= settings.ALERT_COOLDOWN_SECONDS:
                            email_sent = alert_service.send_email_alert(
                                camera_name=camera.name,
                                location=camera.location or "Unknown",
                                fire_level=result['fire_level'],
                                confidence=result['confidence'],
                                timestamp=detection.timestamp,
                                image_path=image_path
                            )
                            
                            # Record alert
                            alert_type = 'email'
                            alert_status = 'sent' if email_sent else 'failed'
                            
                            alert = Alert(
                                detection_id=detection.id,
                                alert_type=alert_type,
                                status=alert_status,
                                recipients=settings.alert_recipients_list
                            )
                            db.add(alert)
                            db.commit()
                            
                            # Update last alert time
                            last_alert_time[camera_id] = current_time
                            
                            logger.info(f"ALERT: Fire Level {result['fire_level']} detected at {camera.name}")
            
            db.close()
            
            # Sleep briefly to avoid overwhelming the system
            await asyncio.sleep(0.1)
            
        except Exception as e:
            logger.error(f"Error in monitoring loop: {e}")
            await asyncio.sleep(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
 
    # Startup
    logger.info("Starting PYRO-GUARD system...")
    
    # Initialize database
    init_db()
    logger.info("Database initialized")
    
    # Set stream handler for camera API
    set_stream_handler(stream_handler)
    
    # Load existing active cameras
    db = SessionLocal()
    active_cameras = db.query(Camera).filter(Camera.is_active == True).all()
    for camera in active_cameras:
        if camera.rtsp_url:
            stream_handler.add_stream(camera.id, camera.rtsp_url)
            logger.info(f"Started stream for camera: {camera.name}")
    db.close()
    
    # Start monitoring task
    monitoring_task = asyncio.create_task(monitor_cameras())
    
    # Start sensor manager
    sensor_manager.start()
    
    logger.info("PYRO-GUARD system ready!")
    
    yield
    
    # Shutdown
    logger.info("Shutting down PYRO-GUARD system...")
    monitoring_task.cancel()
    stream_handler.stop_all()
    sensor_manager.stop()
    logger.info("Shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="PYRO-GUARD API",
    description="Vision-Based Fire Level Detection System for Surveillance Networks",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(cameras_router)
app.include_router(detections_router)
app.include_router(alerts_router)


@app.get("/")
def root():
    """Root endpoint"""
    return {
        "message": "PYRO-GUARD API",
        "version": "1.0.0",
        "status": "running"
    }


@app.get("/health")
def health_check():
    """Health check endpoint"""
    active_streams = len(stream_handler.get_all_streams())
    
    return {
        "status": "healthy",
        "active_cameras": active_streams,
        "detector_loaded": detector.model is not None,
        "sensors": sensor_manager.get_latest_data(),
        "sensor_status": sensor_manager.get_sensor_statuses()
    }


@app.get("/live/{camera_id}")
async def live_feed(camera_id: int):

    logger.debug(f"Live feed requested for camera {camera_id}")
    stream = stream_handler.get_stream(camera_id)
    
    if not stream:
        return {"error": "Camera stream not found"}
    
    def generate_frames():
        frame_count = 0
        last_result = None
        persistence_counter = 0
        PERSISTENCE_FRAMES = 10 
        
        while True:
            frame = stream.get_frame(timeout=1.0)
            
            if frame is None:
                continue
            
            display_frame = cv2.resize(frame, (640, 480))
            
            if frame_count % settings.FRAME_SKIP == 0:
                current_result = detector.detect(display_frame)
                
                if current_result['fire_detected']:
                    last_result = current_result
                    persistence_counter = PERSISTENCE_FRAMES
                elif persistence_counter > 0:
                    persistence_counter -= 1
                else:
                    last_result = None
            
            # Draw detections using cached result - draw if ANY bounding boxes exist
            if last_result and len(last_result.get('bounding_boxes', [])) > 0:
                display_frame = detector.draw_detections(display_frame, last_result)
            
            ret, buffer = cv2.imencode('.jpg', display_frame, [cv2.IMWRITE_JPEG_QUALITY, 50])
            if not ret:
                continue
            
            frame_bytes = buffer.tobytes()
            
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            
            frame_count += 1
    
    return StreamingResponse(
        generate_frames(),
        media_type='multipart/x-mixed-replace; boundary=frame',
        headers={
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache',
            'Expires': '0'
        }
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.DEBUG
    )

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import asyncio
import cv2
import os
import time
import threading
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from .config import settings
from .database import init_db, SessionLocal
from .models import Camera, Detection, Alert, User
from .detection import FireDetector, MultiStreamHandler
from .services import AlertService, S3Service
from .services.ptz_service import PTZController
from .api import cameras_router, detections_router, alerts_router
from .api.auth import router as auth_router
from .api.cameras import set_stream_handler
from .hardware import SensorManager, VirtualFireSensor, InfraredThermalSensor, GPIOController
import platform

import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("backend.log")
    ]
)
logger = logging.getLogger(__name__)

detector = FireDetector()
stream_handler = MultiStreamHandler()
alert_service = AlertService()
ptz_controller = PTZController()
sensor_manager = SensorManager(update_interval=2.0)
gpio_controller = GPIOController()
s3_service = S3Service()

_is_raspberry_pi = (
    settings.HARDWARE_MODE == "raspberry_pi"
    or "aarch64" in platform.machine()
    or "armv" in platform.machine()
)

if _is_raspberry_pi:
    # ── GPIO first (LEDs + Buzzer) — must work even if sensors fail ──
    try:
        gpio_controller.initialize()
        logger.info("GPIO Controller initialized — LEDs and Buzzer ready")
    except Exception as e:
        logger.error(f"GPIO initialization failed: {e}")

    # ── Physical sensors (DHT22 + MQ2) — independent of GPIO ──
    try:
        from .hardware import DHT22Sensor, MQ2SmokeSensor
        sensor_manager.register_sensor(DHT22Sensor("dht22_01", "Temperature & Humidity", gpio_pin=17))
        sensor_manager.register_sensor(MQ2SmokeSensor("mq2_01", "Smoke Detector", gpio_pin=4))
        logger.info("Hardware mode: Raspberry Pi — real sensors active (DHT22 on GPIO 17, MQ-2 on GPIO 4)")
    except Exception as e:
        logger.warning(f"Real sensor init failed, falling back to virtual: {e}")
        sensor_manager.register_sensor(VirtualFireSensor("sim_temp_01", "Ambient Monitor"))
        sensor_manager.register_sensor(InfraredThermalSensor("ir_thermal_01", "Thermal Scanner Alpha"))
else:
    sensor_manager.register_sensor(VirtualFireSensor("sim_temp_01", "Ambient Monitor"))
    sensor_manager.register_sensor(InfraredThermalSensor("ir_thermal_01", "Thermal Scanner Alpha"))
    logger.info("Hardware mode: PC — using virtual sensors")

last_alert_time = {}
last_save_time = {}
consecutive_detections = {}

# GPIO fire reaction & hold configuration: hold LED/buzzer for 3.5s so breadboard LED glows visibly
_gpio_last_fire_time = 0.0
_GPIO_HOLD_SECONDS = 3.5  # Seconds to hold LED indicator ON after detection

# Cache detection results so the live feed can overlay them without re-running AI
_cached_detections = {}


def record_fire_clip(camera_id: int, start_frame: cv2.typing.MatLike, stream, output_path: str, duration_sec: float = 10.0, fps: int = 15):
    """
    Records an authentic 10-second H.264 video clip starting from when fire is detected.
    Uses ffmpeg with libx264 for universal HTML5 browser playback with +faststart.
    """
    import subprocess
    import shutil

    h, w = start_frame.shape[:2]
    ffmpeg_bin = shutil.which("ffmpeg")

    if ffmpeg_bin:
        # Prefer Raspberry Pi VideoCore hardware H.264 encoder (0% CPU, 6.5x speed) on Linux
        use_hw = platform.system() == "Linux"
        encoder_args = ['-c:v', 'h264_v4l2m2m', '-b:v', '1500k'] if use_hw else ['-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency', '-crf', '24']

        cmd = [
            ffmpeg_bin, '-y',
            '-f', 'rawvideo',
            '-vcodec', 'rawvideo',
            '-s', f'{w}x{h}',
            '-pix_fmt', 'bgr24',
            '-r', str(fps),
            '-i', '-',
            *encoder_args,
            '-pix_fmt', 'yuv420p',
            '-movflags', '+faststart',
            output_path
        ]
        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            start_time = time.time()
            frame_interval = 1.0 / fps

            # Write initial frame
            first_frame = start_frame.copy()
            cv2.putText(first_frame, "REC 0.0s / 10.0s [FIRE TRIGGER]", (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 255), 2)
            proc.stdin.write(first_frame.tobytes())

            while (time.time() - start_time) < duration_sec:
                loop_t = time.time()
                frame = stream.get_frame(timeout=0.2)
                if frame is not None:
                    overlay = frame.copy()
                    cached = _cached_detections.get(camera_id)
                    if cached and cached.get('fire_detected'):
                        overlay = detector.draw_detections(overlay, cached)

                    elapsed = time.time() - start_time
                    cv2.putText(
                        overlay,
                        f"REC +{elapsed:.1f}s / {duration_sec:.0f}s",
                        (15, 30),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.65,
                        (0, 0, 255),
                        2
                    )
                    proc.stdin.write(overlay.tobytes())

                sleep_t = frame_interval - (time.time() - loop_t)
                if sleep_t > 0:
                    time.sleep(sleep_t)

            proc.stdin.close()
            proc.wait(timeout=5)
            logger.info(f"10-second H.264 fire incident video recorded via ffmpeg: {output_path}")
            return
        except Exception as e:
            logger.error(f"Error in ffmpeg recording for camera {camera_id}: {e}, falling back to cv2")

    # Fallback to OpenCV VideoWriter
    try:
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(output_path, fourcc, float(fps), (w, h))
        if not out.isOpened():
            fourcc = cv2.VideoWriter_fourcc(*'avc1')
            out = cv2.VideoWriter(output_path, fourcc, float(fps), (w, h))
        if not out.isOpened():
            logger.error(f"Failed to open video writer for {output_path}")
            return

        start_time = time.time()
        frame_interval = 1.0 / fps
        out.write(start_frame)

        while (time.time() - start_time) < duration_sec:
            loop_t = time.time()
            frame = stream.get_frame(timeout=0.2)
            if frame is not None:
                overlay = frame.copy()
                cached = _cached_detections.get(camera_id)
                if cached and cached.get('fire_detected'):
                    overlay = detector.draw_detections(overlay, cached)

                elapsed = time.time() - start_time
                cv2.putText(
                    overlay,
                    f"REC +{elapsed:.1f}s / {duration_sec:.0f}s",
                    (15, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.65,
                    (0, 0, 255),
                    2
                )
                out.write(overlay)
            sleep_t = frame_interval - (time.time() - loop_t)
            if sleep_t > 0:
                time.sleep(sleep_t)

        out.release()
        logger.info(f"10-second fire incident video saved via cv2: {output_path}")
    except Exception as e:
        logger.error(f"Error in cv2 recording for camera {camera_id}: {e}")


async def monitor_cameras():
    global _gpio_last_fire_time
    logger.info("Starting camera monitoring...")

    while True:
        db = None
        try:
            db = SessionLocal()

            streams = stream_handler.get_all_streams()

            monitor_cameras.frame_count = getattr(monitor_cameras, 'frame_count', 0) + 1
            if monitor_cameras.frame_count % 300 == 0:
                import gc
                gc.collect()

            latest_sensors = sensor_manager.get_latest_data()
            physical_smoke_detected = False
            for sensor_id, data in latest_sensors.items():
                if data.get('smoke_detected'):
                    physical_smoke_detected = True
                    break

            for camera_id, stream in streams.items():
                frame = stream.get_frame(timeout=0.5)

                if frame is None:
                    continue

                result = await asyncio.to_thread(detector.detect, frame, camera_id)

                if not hasattr(monitor_cameras, '_cam_cache') or monitor_cameras.frame_count % 60 == 0:
                    monitor_cameras._cam_cache = {c.id: c for c in db.query(Camera).all()}
                camera = monitor_cameras._cam_cache.get(camera_id)
                if not camera:
                    camera = db.query(Camera).filter(Camera.id == camera_id).first()
                if not camera:
                    continue

                # ── GPIO fire reaction: LED (Blue=Small, Green=Medium, Red=Critical) + Buzzer ──
                if gpio_controller.initialized:
                    detected_level = result.get('fire_level', 0)
                    now_ts = time.time()
                    if detected_level >= 1:
                        _gpio_last_fire_time = now_ts
                        gpio_controller.set_fire_level(detected_level)
                    else:
                        # Only return to safe level 0 after hold duration expires
                        if now_ts - _gpio_last_fire_time > _GPIO_HOLD_SECONDS:
                            if gpio_controller.current_level != 0:
                                gpio_controller.set_fire_level(0)
                # ───────────────────────────────────────────────────────────────────

                if camera_id not in consecutive_detections:
                    consecutive_detections[camera_id] = 0

                is_fire_legit = result['fire_detected']
                required_frames = settings.DETECTION_PERSISTENCE_FRAMES

                # Cache the result for the live feed overlay
                _cached_detections[camera_id] = result

                if is_fire_legit:
                    consecutive_detections[camera_id] += 1
                    consecutive_detections[camera_id] = min(consecutive_detections[camera_id], required_frames * 2)
                    
                    if camera.ptz_enabled and 'bounding_boxes' in result and len(result['bounding_boxes']) > 0:
                        biggest_box = max(result['bounding_boxes'], key=lambda b: (b['bbox'][2]-b['bbox'][0])*(b['bbox'][3]-b['bbox'][1]))
                        h, w = frame.shape[:2]
                        ptz_controller.track_target(camera, biggest_box['bbox'], w, h)
                        
                    # Notify sensors about fire detection so they react
                    sensor_manager.notify_fire_event(result['fire_level'], result['confidence'])
                    logger.debug(f"Camera {camera_id}: fire detected (consecutive={consecutive_detections[camera_id]}/{required_frames}) conf={result['confidence']:.2f} level={result['fire_level']}")
                else:
                    if camera_id in consecutive_detections:
                        consecutive_detections[camera_id] = max(0, consecutive_detections[camera_id] - 1)
                        if consecutive_detections[camera_id] == 0:
                            del consecutive_detections[camera_id]

                if camera_id in consecutive_detections and consecutive_detections[camera_id] >= required_frames:
                    if result['fire_detected'] and result['fire_level'] > 0:
                        current_time = datetime.now()
                        last_save = last_save_time.get(camera_id)
                        if last_save is not None and (current_time - last_save).total_seconds() < 30:
                            pass  # Skip saving, cooldown active
                        else:
                            last_save_time[camera_id] = current_time
                            consecutive_detections[camera_id] = 0  

                            image_dir = "detections"
                            os.makedirs(image_dir, exist_ok=True)

                            timestamp_str = current_time.strftime('%Y%m%d_%H%M%S')
                            image_filename = f"{camera_id}_{timestamp_str}.jpg"
                            image_path = os.path.join(image_dir, image_filename)

                            video_filename = f"{camera_id}_{timestamp_str}.mp4"
                            video_path = os.path.join(image_dir, video_filename)

                            annotated_frame = detector.draw_detections(frame, result)
                            await asyncio.to_thread(cv2.imwrite, image_path, annotated_frame)

                            # Launch 10-second video recording starting from fire detection trigger
                            threading.Thread(
                                target=record_fire_clip,
                                args=(camera_id, annotated_frame.copy(), stream, video_path, 10.0, 15),
                                daemon=True
                            ).start()

                            # Include sensor verification data and video metadata
                            detection_meta = result['metadata'].copy() if result.get('metadata') else {}
                            sensor_data = sensor_manager.get_latest_data()
                            verification_score = sensor_manager.get_verification_score()
                            detection_meta['sensor_data'] = sensor_data
                            detection_meta['sensor_verification_score'] = verification_score
                            detection_meta['video_path'] = video_path
                            detection_meta['video_duration'] = 10.0

                            detection = Detection(
                                camera_id=camera_id,
                                fire_level=result['fire_level'],
                                confidence=result['confidence'],
                                bbox_area=result['bbox_area'],
                                image_path=image_path,
                                video_path=video_path,
                                detection_metadata=detection_meta
                            )

                            if s3_service.enabled:
                                s3_url = await asyncio.to_thread(s3_service.upload_image, image_path)
                                if s3_url:
                                    detection.image_url = s3_url

                            db.add(detection)
                            db.commit()
                            db.refresh(detection)

                            logger.info(f"FIRE SAVED: Level {result['fire_level']} conf={result['confidence']:.2f} camera={camera_id}")

                            # ── ALERT TRIGGER LOGIC ──
                            # Only trigger software alerts (Email/SMS) if confidence is high AND fire level is critical (Level 3)
                            if result['confidence'] >= settings.MIN_CONFIDENCE_FOR_ALERT and result['fire_level'] >= 3:
                                last_alert = last_alert_time.get(camera_id)
                                if last_alert is None or (current_time - last_alert).total_seconds() >= settings.ALERT_COOLDOWN_SECONDS:
                                    email_sent = await asyncio.to_thread(
                                        alert_service.send_email_alert,
                                        camera_name=camera.name,
                                        location=camera.location or "Unknown",
                                        fire_level=result['fire_level'],
                                        confidence=result['confidence'],
                                        timestamp=detection.timestamp,
                                        image_path=image_path
                                    )
                                    
                                    # Send SMS alert to community fire volunteer
                                    sms_sent = await asyncio.to_thread(
                                        alert_service.send_sms_alert,
                                        location=camera.location or camera.name,
                                        fire_level=result['fire_level'],
                                        timestamp=detection.timestamp
                                    )

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

                                    last_alert_time[camera_id] = current_time
                                    logger.info(f"ALERT: Fire Level {result['fire_level']} detected at {camera.name}")


            latest_sensor_data = sensor_manager.get_latest_data()
            for sensor_id, data in latest_sensor_data.items():
                if sensor_id.startswith('ir_') and data.get('status') == 'anomaly_detected':
                    first_camera = db.query(Camera).filter(Camera.is_active == True).first()
                    if first_camera:
                        detection = Detection(
                            camera_id=first_camera.id,
                            fire_level=2,
                            confidence=data.get('anomaly_score', 0.85),
                            bbox_area=0.0,
                            image_path=None,
                            detection_metadata={
                                "type": "thermal_anomaly",
                                "sensor_id": sensor_id,
                                "peak_temp": data.get('peak_temperature'),
                                "original_data": data
                            }
                        )
                        db.add(detection)
                        db.commit()
                        logger.warning(f"THERMAL ANOMALY: High heat detected by {sensor_id} ({data.get('peak_temperature')}°C)")

                        if sensor_id in sensor_manager.sensors:
                            sensor_manager.sensors[sensor_id].current_state['status'] = 'nominal'

            # Optimized sleep for Raspberry Pi: ~3.5 evaluations/sec balances real-time detection with low CPU/heat
            await asyncio.sleep(0.28)

        except Exception as e:
            logger.error(f"Error in monitoring loop: {e}")
            await asyncio.sleep(1)
        finally:
            if db:
                db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting PYRO-GUARD system...")

    init_db()
    logger.info("Database initialized")

    # Ensure any legacy 'viewer' role is upgraded to 'operator'
    try:
        mig_db = SessionLocal()
        mig_db.query(User).filter(User.role == "viewer").update({"role": "operator"})
        mig_db.commit()
        mig_db.close()
    except Exception as e:
        logger.warning(f"Role migration notice: {e}")

    set_stream_handler(stream_handler)

    db = SessionLocal()
    active_cameras = db.query(Camera).filter(Camera.is_active == True).all()
    for camera in active_cameras:
        source = camera.rtsp_url or '0'
        stream_handler.add_stream(camera.id, source)
        logger.info(f"Started stream for camera: {camera.name} (source={source})")
    db.close()

    monitoring_task = asyncio.create_task(monitor_cameras())

    sensor_manager.start()

    logger.info("PYRO-GUARD system ready!")

    yield

    logger.info("Shutting down PYRO-GUARD system...")
    monitoring_task.cancel()
    stream_handler.stop_all()
    sensor_manager.stop()
    gpio_controller.set_fire_level(0)
    gpio_controller.cleanup()
    logger.info("Shutdown complete")


app = FastAPI(
    title="PYRO-GUARD API",
    description="Vision-Based Fire Level Detection System for Surveillance Networks",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://192.168.1.12:3000",
        "http://192.168.1.20:3000",
    ],
    allow_origin_regex=r"^https?://.*$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

app.include_router(cameras_router)
app.include_router(detections_router)
app.include_router(alerts_router)
app.include_router(auth_router)

# Mount the detections directory to serve image snapshots
os.makedirs("detections", exist_ok=True)
app.mount("/media/detections", StaticFiles(directory="detections"), name="detections_media")


@app.get("/")
def root():
    return {
        "message": "PYRO-GUARD API",
        "version": "2.0.0",
        "status": "running",
        "hardware_mode": "raspberry_pi" if _is_raspberry_pi else "pc"
    }


@app.get("/health")
async def health_check():
    active_streams = len(stream_handler.get_all_streams())

    # Fast non-blocking read from sensor memory cache
    sensor_data = {}
    for sid, sensor in sensor_manager.sensors.items():
        if sensor.last_value:
            sensor_data[sid] = sensor.last_value.copy()

    # Merge cached EMA data if available
    cached = sensor_manager.get_latest_data()
    if cached:
        for sid, cdata in cached.items():
            if sid in sensor_data:
                sensor_data[sid].update(cdata)
            else:
                sensor_data[sid] = cdata

    aggregated_sensors = {
        "temperature": 25.0,
        "humidity": 50.0,
        "smoke_analog": 35.0,
        "smoke_detected": False,
        "anomaly_score": None,
        "peak_temperature": None,
        "thermal_status": "nominal",
        "ambient_status": "normal"
    }
    for sid, data in sensor_data.items():
        if 'temperature' in data and data['temperature'] is not None:
            aggregated_sensors['temperature'] = data['temperature']
            aggregated_sensors['humidity'] = data.get('humidity')
        if 'smoke_detected' in data:
            is_smoke = bool(data['smoke_detected'])
            aggregated_sensors['smoke_detected'] = is_smoke
            aggregated_sensors['smoke_analog'] = data.get('smoke_analog', 480 if is_smoke else 35)
            if is_smoke:
                aggregated_sensors['ambient_status'] = 'danger'
        if 'anomaly_score' in data:
            aggregated_sensors['anomaly_score'] = data['anomaly_score']
            aggregated_sensors['peak_temperature'] = data.get('peak_temperature')
            aggregated_sensors['thermal_status'] = data.get('status', 'nominal')

    return {
        "status": "healthy",
        "active_cameras": active_streams,
        "detector_loaded": detector.model is not None,
        "sensors": sensor_data,
        "sensor_summary": aggregated_sensors,
        "sensor_status": sensor_manager.get_sensor_statuses(),
        "verification_score": sensor_manager.get_verification_score(),
        "hardware_mode": "raspberry_pi" if _is_raspberry_pi else "pc"
    }


from pydantic import BaseModel

class SensorCreate(BaseModel):
    name: str
    type: str

@app.post("/sensors/")
def create_sensor(sensor: SensorCreate):
    import uuid
    sensor_id = f"{sensor.type}_{uuid.uuid4().hex[:6]}"

    if sensor.type == 'ambient':
        from .hardware.sensors import VirtualFireSensor
        new_sensor = VirtualFireSensor(sensor_id, sensor.name)
    elif sensor.type == 'infrared':
        from .hardware.sensors import InfraredThermalSensor
        new_sensor = InfraredThermalSensor(sensor_id, sensor.name)
    else:
        from .hardware.sensors import VirtualFireSensor
        new_sensor = VirtualFireSensor(sensor_id, sensor.name)

    sensor_manager.register_sensor(new_sensor)
    return {"status": "success", "sensor_id": sensor_id, "name": sensor.name}


@app.get("/live/{camera_id}")
async def live_feed(camera_id: int):
    logger.debug(f"Live feed requested for camera {camera_id}")
    stream = stream_handler.get_stream(camera_id) if stream_handler else None

    if not stream or not stream.is_active() or stream.get_frame() is None:
        raise HTTPException(status_code=503, detail="Camera feed offline or disconnected")

    def generate_frames():
        import time as _time
        TARGET_FPS = 10  # Limit to 10 FPS to save CPU/bandwidth
        frame_interval = 1.0 / TARGET_FPS
        none_count = 0

        while True:
            loop_start = _time.time()
            frame = stream.get_frame(timeout=1.0)

            if frame is None:
                none_count += 1
                if none_count > 15:
                    break
                _time.sleep(0.1)
                continue
            none_count = 0

            # Preserve native aspect ratio (16:9 widescreen or 4:3) so camera is never distorted or cropped
            fh, fw = frame.shape[:2]
            target_w = 640 if _is_raspberry_pi else (960 if fw >= 1280 else 640)
            target_h = int(target_w * fh / fw) if fw > 0 else 360
            display_frame = cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_LINEAR)

            # Use cached detection results from monitor_cameras instead of re-running AI
            cached = _cached_detections.get(camera_id)
            if cached and cached.get('fire_detected') and len(cached.get('bounding_boxes', [])) > 0:
                display_frame = detector.draw_detections(display_frame, cached)

            ret, buffer = cv2.imencode('.jpg', display_frame, [
                cv2.IMWRITE_JPEG_QUALITY, 40,
                cv2.IMWRITE_JPEG_OPTIMIZE, 0
            ])
            if not ret:
                continue

            frame_bytes = buffer.tobytes()

            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

            # Rate limit to target FPS
            elapsed = _time.time() - loop_start
            if elapsed < frame_interval:
                _time.sleep(frame_interval - elapsed)

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

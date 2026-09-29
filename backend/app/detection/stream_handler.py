import cv2
import numpy as np
from typing import Optional, Generator
import threading
import time
import platform
import logging
from ..config import settings

logger = logging.getLogger(__name__)

IS_LINUX = platform.system() == "Linux"
CAMERA_BACKEND = cv2.CAP_V4L2 if IS_LINUX else cv2.CAP_DSHOW

if IS_LINUX:
    try:
        cv2.setNumThreads(2)
        cv2.ocl.setUseOpenCL(False)
    except Exception:
        pass


class StreamHandler:

    def __init__(self, source: str, frame_skip: int = None):
        self.source = source
        self.frame_skip = frame_skip or settings.FRAME_SKIP
        self.frame_width = settings.FRAME_WIDTH
        self.frame_height = settings.FRAME_HEIGHT

        self.cap = None
        self.is_running = False
        self.latest_frame = None
        self.frame_lock = threading.Lock()
        self.thread = None

        self.frame_count = 0
        self.fps = 0
        self.last_fps_time = time.time()

        self._consecutive_failures = 0
        self._max_failures_before_reconnect = 30
        self._is_rtsp = False

    def _is_rtsp_source(self) -> bool:
        if isinstance(self.source, str) and self.source.lower().startswith("rtsp://"):
            return True
        return False

    def _open_capture(self) -> bool:
        try:
            if self._is_rtsp:
                import os
                os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay"
                self.cap = cv2.VideoCapture(self.source, cv2.CAP_FFMPEG)
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            elif isinstance(self.source, int) or str(self.source).isdigit():
                cam_index = int(self.source)
                import os
                if os.path.exists("/dev") and not os.path.exists(f"/dev/video{cam_index}"):
                    # Physical camera hardware not plugged into Raspberry Pi / Linux
                    return False
                self.cap = cv2.VideoCapture(cam_index)
            else:
                self.cap = cv2.VideoCapture(self.source)

            if not self.cap or not self.cap.isOpened():
                logger.error(f"Could not open video source: {self.source}")
                return False

            if not self._is_rtsp:
                # Set width and height first to engage native 16:9 widescreen full FoV sensor
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.frame_width)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.frame_height)
                try:
                    self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
                except Exception as e:
                    logger.debug(f"Could not set MJPG codec: {e}")
                actual_w = self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)
                actual_h = self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
                logger.info(f"Camera opened with hardware resolution: {actual_w:.0f}x{actual_h:.0f} (Full FoV)")

            return True
        except Exception as e:
            logger.error(f"Error opening capture: {e}")
            return False

    def start(self) -> bool:
        self._is_rtsp = self._is_rtsp_source()
        opened = self._open_capture()

        self.is_running = True
        self._consecutive_failures = 0
        self.thread = threading.Thread(target=self._capture_frames, daemon=True)
        self.thread.start()

        source_type = "RTSP" if self._is_rtsp else "Local"
        if opened:
            logger.info(f"Stream started [{source_type}]: {self.source}")
        else:
            logger.info(f"Stream initialized [{source_type}]: {self.source} (Waiting for hardware connection)")
        return True

    def stop(self):
        self.is_running = False

        if self.thread:
            self.thread.join(timeout=3)

        if self.cap:
            self.cap.release()
            self.cap = None

        with self.frame_lock:
            self.latest_frame = None

        logger.info(f"Stream stopped: {self.source}")

    def _reconnect(self):
        if self.cap:
            self.cap.release()
            self.cap = None

        backoff = min(15, 2 ** min(self._consecutive_failures // 5, 3))
        time.sleep(backoff)

        if self._open_capture():
            self._consecutive_failures = 0
            logger.info(f"Reconnected to {self.source}")
        else:
            logger.debug(f"Reconnection attempt pending for {self.source}")

    def _capture_frames(self):
        while self.is_running:
            try:
                if self.cap is None or not self.cap.isOpened():
                    with self.frame_lock:
                        self.latest_frame = None
                    # Progressive backoff for offline cameras: avoid spinning CPU in tight V4L2 probe loops
                    backoff = min(8.0, 2.5 + (self._consecutive_failures * 1.5))
                    slept = 0.0
                    while slept < backoff and self.is_running:
                        time.sleep(0.2)
                        slept += 0.2
                    if self._open_capture():
                        logger.info(f"Camera connected and streaming: {self.source}")
                        self._consecutive_failures = 0
                    else:
                        self._consecutive_failures += 1
                    continue

                # Skip frames directly on the buffer using grab (no decoding overhead)
                if self.frame_skip > 1:
                    for _ in range(self.frame_skip - 1):
                        if not self.cap.grab():
                            break

                ret, frame = self.cap.read()

                if not ret:
                    self._consecutive_failures += 1
                    if self._consecutive_failures >= 3:
                        with self.frame_lock:
                            self.latest_frame = None
                        if self.cap:
                            self.cap.release()
                            self.cap = None
                        logger.warning(f"Camera connection lost: {self.source}")
                    time.sleep(0.5)
                    continue

                self._consecutive_failures = 0

                if frame.shape[1] != self.frame_width or frame.shape[0] != self.frame_height:
                    frame = cv2.resize(frame, (self.frame_width, self.frame_height))

                with self.frame_lock:
                    self.latest_frame = frame.copy()

                self.frame_count += 1
                current_time = time.time()
                if current_time - self.last_fps_time >= 1.0:
                    self.fps = self.frame_count / (current_time - self.last_fps_time)
                    self.frame_count = 0
                    self.last_fps_time = current_time

            except Exception as e:
                logger.error(f"Error in capture thread: {e}")
                time.sleep(0.1)

    def get_frame(self, timeout: float = 1.0, copy: bool = False) -> Optional[np.ndarray]:
        with self.frame_lock:
            if self.latest_frame is not None:
                return self.latest_frame.copy() if copy else self.latest_frame
            return None

    def read_frames(self) -> Generator[np.ndarray, None, None]:
        while self.is_running:
            frame = self.get_frame()
            if frame is not None:
                yield frame

    def get_fps(self) -> float:
        return self.fps

    def is_active(self) -> bool:
        return (
            self.is_running
            and self.cap is not None
            and self.cap.isOpened()
            and self.latest_frame is not None
        )


class MultiStreamHandler:
    def __init__(self):
        self.streams = {}

    def add_stream(self, camera_id: int, source: str) -> bool:
        if camera_id in self.streams:
            logger.warning(f"Stream {camera_id} already exists, removing old stream first")
            self.remove_stream(camera_id)

        handler = StreamHandler(source)
        handler.start()
        self.streams[camera_id] = handler
        return True

    def remove_stream(self, camera_id: int):
        if camera_id in self.streams:
            self.streams[camera_id].stop()
            del self.streams[camera_id]

    def get_stream(self, camera_id: int) -> Optional[StreamHandler]:
        return self.streams.get(camera_id)

    def get_all_streams(self) -> dict:
        return self.streams

    def stop_all(self):
        for handler in self.streams.values():
            handler.stop()
        self.streams.clear()

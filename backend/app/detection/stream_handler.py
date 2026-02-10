"""
Video stream handler for RTSP and webcam sources
"""
import cv2
import numpy as np
from typing import Optional, Generator
import threading
import queue
import time
from ..config import settings


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
        
        # Statistics
        self.frame_count = 0
        self.fps = 0
        self.last_fps_time = time.time()
    
    def start(self) -> bool:
        try:
            # Open video capture
            if isinstance(self.source, int) or str(self.source).isdigit():
                self.cap = cv2.VideoCapture(int(self.source), cv2.CAP_DSHOW)
            else:
                # RTSP or video file
                self.cap = cv2.VideoCapture(self.source)
            
            if not self.cap.isOpened():
                print(f"Error: Could not open video source: {self.source}")
                if isinstance(self.source, int) or str(self.source).isdigit():
                    self.cap = cv2.VideoCapture(int(self.source))
                    if not self.cap.isOpened():
                        return False
                else:
                    return False
            
            # Set frame size
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.frame_width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.frame_height)
            
            # Start capture thread
            self.is_running = True
            self.thread = threading.Thread(target=self._capture_frames, daemon=True)
            self.thread.start()
            
            print(f"Stream started: {self.source}")
            return True
            
        except Exception as e:
            print(f"Error starting stream: {e}")
            return False
    
    def stop(self):
        """Stop video stream"""
        self.is_running = False
        
        if self.thread:
            self.thread.join(timeout=2)
        
        if self.cap:
            self.cap.release()
        
        print(f"Stream stopped: {self.source}")
    
    def _capture_frames(self):
        """Background thread for capturing frames"""
        frame_counter = 0
        
        while self.is_running:
            try:
                ret, frame = self.cap.read()
                
                if not ret:
                    print(f"Warning: Failed to read frame from {self.source}")
                    time.sleep(0.1)
                    continue
                
                # Skip frames for performance
                frame_counter += 1
                if frame_counter % self.frame_skip != 0:
                    continue
                
                # Resize frame if needed
                if frame.shape[1] != self.frame_width or frame.shape[0] != self.frame_height:
                    frame = cv2.resize(frame, (self.frame_width, self.frame_height))
                
                # Update latest frame thread-safely
                with self.frame_lock:
                    self.latest_frame = frame.copy()
                
                # Update FPS
                self.frame_count += 1
                current_time = time.time()
                if current_time - self.last_fps_time >= 1.0:
                    self.fps = self.frame_count / (current_time - self.last_fps_time)
                    self.frame_count = 0
                    self.last_fps_time = current_time
                
            except Exception as e:
                print(f"Error in capture thread: {e}")
                time.sleep(0.1)
    
    def get_frame(self, timeout: float = 1.0) -> Optional[np.ndarray]:
        with self.frame_lock:
            if self.latest_frame is not None:
                return self.latest_frame.copy()
            return None
    
    def read_frames(self) -> Generator[np.ndarray, None, None]:
        while self.is_running:
            frame = self.get_frame()
            if frame is not None:
                yield frame
    
    def get_fps(self) -> float:
        """Get current FPS"""
        return self.fps
    
    def is_active(self) -> bool:
        """Check if stream is active"""
        return self.is_running and self.cap is not None and self.cap.isOpened()


class MultiStreamHandler:
    def __init__(self):
        self.streams = {} 
    
    def add_stream(self, camera_id: int, source: str) -> bool:
        if camera_id in self.streams:
            print(f"Warning: Stream {camera_id} already exists")
            return False
        
        handler = StreamHandler(source)
        if handler.start():
            self.streams[camera_id] = handler
            return True
        return False
    
    def remove_stream(self, camera_id: int):
        """Remove a stream"""
        if camera_id in self.streams:
            self.streams[camera_id].stop()
            del self.streams[camera_id]
    
    def get_stream(self, camera_id: int) -> Optional[StreamHandler]:
        """Get stream handler by camera ID"""
        return self.streams.get(camera_id)
    
    def get_all_streams(self) -> dict:
        """Get all active streams"""
        return self.streams
    
    def stop_all(self):
        """Stop all streams"""
        for handler in self.streams.values():
            handler.stop()
        self.streams.clear()

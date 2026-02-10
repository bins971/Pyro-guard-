"""
YOLOv8-based fire detection engine
"""
import cv2
import numpy as np
from ultralytics import YOLO
from typing import List, Dict, Any, Optional
import os
from ..config import settings
from .classifier import FireLevelClassifier


import logging

# Configure logger
logger = logging.getLogger(__name__)

class FireDetector:
    """
    Fire detection using YOLOv8 model
    """
    
    def __init__(self, model_path: Optional[str] = None):
        """
        Initialize fire detector
        
        Args:
            model_path: Path to YOLOv8 model weights. If None, uses settings.absolute_model_path
        """
        self.model_path = model_path or settings.absolute_model_path
        self.confidence_threshold = settings.CONFIDENCE_THRESHOLD
        
        # Initialize classifier
        self.classifier = FireLevelClassifier()
        
        # Load model
        self.model = None
        self._load_model()
    
    def _load_model(self):
        """Load YOLOv8 model"""
        if not os.path.exists(self.model_path):
            logger.warning(f"Model not found at {self.model_path}")
            logger.warning("Using default YOLOv8n model. Train your custom fire detection model!")
            self.model = YOLO('yolov8n.pt')
        else:
            self.model = YOLO(self.model_path)
        
        logger.info(f"Fire detection model loaded: {self.model_path}")
    
    def detect(self, frame: np.ndarray) -> Dict[str, Any]:
        """
        Detect fire in a single frame
        
        Args:
            frame: Input frame (BGR format from OpenCV)
        
        Returns:
            Dictionary containing detection results
        """
        if frame is None or frame.size == 0:
            return self._empty_result()
        
        # Get frame dimensions
        frame_height, frame_width = frame.shape[:2]
        

        inference_frame = frame
        if frame_width > 640:
            scale = 640 / frame_width
            new_height = int(frame_height * scale)
            inference_frame = cv2.resize(frame, (640, new_height))
        
        results = self.model(inference_frame, conf=self.confidence_threshold, verbose=False)
        
        # Parse results
        bounding_boxes = []
        
        if len(results) > 0:
            result = results[0]
            
            if result.boxes is not None and len(result.boxes) > 0:
                for box in result.boxes:
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                    confidence = float(box.conf[0].cpu().numpy())
                    class_id = int(box.cls[0].cpu().numpy())
                    
                    # Get class name
                    class_name = self.model.names[class_id] if class_id < len(self.model.names) else "unknown"
                    

                    
                    display_name = class_name
                    
                    # Specific handling for 'light' class (Small Fire)
                    if class_name.lower() == 'light':

                        if confidence < 0.25:
                            continue
                        display_name = "Small Fire"
                        class_name = "small fire" 
                    
                    # Include fire, smoke, flame, and small fire
                    if class_name.lower() in ['fire', 'smoke', 'flame', 'light', 'small fire']:
                        bounding_boxes.append({
                            'bbox': [float(x1), float(y1), float(x2), float(y2)],
                            'confidence': confidence,
                            'class': display_name 
                        })
                        logger.info(f"🔥 Added {display_name} detection to results ({confidence:.2f})")
                    else:
                        pass
        
        # Classify fire level
        if bounding_boxes:
            fire_level, bbox_area, metadata = self.classifier.classify(
                bounding_boxes, frame_width, frame_height
            )
            
            return {
                'fire_detected': True,
                'fire_level': fire_level,
                'confidence': metadata['max_confidence'],
                'bbox_area': bbox_area,
                'bounding_boxes': bounding_boxes,
                'metadata': metadata,
                'frame_width': frame_width,
                'frame_height': frame_height
            }
        else:
            return self._empty_result(frame_width, frame_height)
    
    def _empty_result(self, frame_width: int = 0, frame_height: int = 0) -> Dict[str, Any]:
        """Return empty detection result"""
        return {
            'fire_detected': False,
            'fire_level': 0,
            'confidence': 0.0,
            'bbox_area': 0.0,
            'bounding_boxes': [],
            'metadata': {},
            'frame_width': frame_width,
            'frame_height': frame_height
        }
    
    def draw_detections(self, frame: np.ndarray, detection_result: Dict[str, Any]) -> np.ndarray:
        """
        Draw bounding boxes and labels on frame
        
        Args:
            frame: Input frame
            detection_result: Detection result from detect()
        
        Returns:
            Frame with drawn detections
        """
        annotated_frame = frame.copy()
        
        # Get frame dimensions
        frame_height, frame_width = frame.shape[:2]
        
        # Only draw if we have bounding boxes
        if not detection_result.get('bounding_boxes'):
            return annotated_frame
        
        fire_level = detection_result['fire_level']
        level_color = self.classifier.get_level_color(fire_level)
        
        # Convert hex color to BGR
        color_bgr = self._hex_to_bgr(level_color)
        
        # Draw bounding boxes
        for box in detection_result['bounding_boxes']:
            x1, y1, x2, y2 = [int(coord) for coord in box['bbox']]
            x1 = max(0, min(x1, frame_width - 1))
            y1 = max(0, min(y1, frame_height - 1))
            x2 = max(0, min(x2, frame_width - 1))
            y2 = max(0, min(y2, frame_height - 1))
            
            if x2 <= x1 or y2 <= y1:
                continue
            
            confidence = box['confidence']
            class_name = box.get('class', 'fire')
            
            # Draw thicker rectangle for better visibility
            cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), color_bgr, 3)
            
            # Draw label with background
            label = f"{class_name.upper()}: {confidence:.2f}"
            label_size, _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
            
            # Ensure label stays within frame
            label_y1 = max(label_size[1] + 10, y1)
            label_y2 = label_y1 - label_size[1] - 10
            
            cv2.rectangle(
                annotated_frame,
                (x1, label_y2),
                (min(x1 + label_size[0] + 10, frame_width), label_y1),
                color_bgr,
                -1
            )
            cv2.putText(
                annotated_frame,
                label,
                (x1 + 5, label_y1 - 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                2
            )
        
        # Draw prominent fire level banner at top
        level_desc = self.classifier.get_level_description(fire_level)
        banner_text = f"ALERT: {level_desc.upper()}"
        
        # Get text size for banner
        text_size, _ = cv2.getTextSize(banner_text, cv2.FONT_HERSHEY_SIMPLEX, 1.2, 3)
        banner_height = text_size[1] + 30
        
        # Draw colored banner background
        cv2.rectangle(
            annotated_frame,
            (0, 0),
            (annotated_frame.shape[1], banner_height),
            color_bgr,
            -1
        )
        
        # Draw banner text
        cv2.putText(
            annotated_frame,
            banner_text,
            (15, banner_height - 15),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.2,
            (255, 255, 255),
            3
        )
        
        return annotated_frame
    
    def _hex_to_bgr(self, hex_color: str) -> tuple:
        """Convert hex color to BGR tuple"""
        hex_color = hex_color.lstrip('#')
        rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        return (rgb[2], rgb[1], rgb[0]) 

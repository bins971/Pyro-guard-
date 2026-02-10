"""
Fire level classifier based on bounding box analysis
"""
from typing import Tuple, List, Dict, Any
import numpy as np
from ..config import settings


class FireLevelClassifier:
    """
    Classifies fire intensity based on bounding box area and other metrics
    
    Fire Levels:
    - Level 0: No fire detected
    - Level 1: Small fire (< 5% of frame)
    - Level 2: Medium fire (5-15% of frame)
    - Level 3: Large/Critical fire (> 15% of frame)
    """
    
    def __init__(self):
        self.thresholds = settings.fire_level_thresholds_list
        if len(self.thresholds) != 2:
            raise ValueError("Expected 2 thresholds for fire level classification")
        
        self.small_threshold = self.thresholds[0] 
        self.medium_threshold = self.thresholds[1]  
    
    def classify(
        self,
        bounding_boxes: List[Dict[str, Any]],
        frame_width: int,
        frame_height: int
    ) -> Tuple[int, float, Dict[str, Any]]:
        """
        Classify fire level based on detection results
        
        Args:
            bounding_boxes: List of detected fire bounding boxes
            frame_width: Width of the video frame
            frame_height: Height of the video frame
        
        Returns:
            Tuple of (fire_level, bbox_area_percentage, metadata)
        """
        if not bounding_boxes:
            return 0, 0.0, {}
        
        # Calculate total fire area
        total_fire_area = 0
        frame_area = frame_width * frame_height
        
        max_confidence = 0.0
        all_boxes = []
        
        for box in bounding_boxes:
            # Extract bounding box coordinates
            x1, y1, x2, y2 = box['bbox']
            confidence = box['confidence']
            
            # Calculate box area
            box_width = x2 - x1
            box_height = y2 - y1
            box_area = box_width * box_height
            
            total_fire_area += box_area
            max_confidence = max(max_confidence, confidence)
            
            all_boxes.append({
                'bbox': [float(x1), float(y1), float(x2), float(y2)],
                'confidence': float(confidence),
                'area': float(box_area)
            })
        
        # Calculate percentage of frame covered by fire
        bbox_area_percentage = total_fire_area / frame_area if frame_area > 0 else 0
        
        # Classify fire level
        fire_level = self._determine_level(bbox_area_percentage)
        
        # Prepare metadata
        metadata = {
            'total_fire_area': float(total_fire_area),
            'frame_area': float(frame_area),
            'bbox_area_percentage': float(bbox_area_percentage),
            'num_detections': len(bounding_boxes),
            'max_confidence': float(max_confidence),
            'bounding_boxes': all_boxes
        }
        
        return fire_level, bbox_area_percentage, metadata
    
    def _determine_level(self, bbox_area_percentage: float) -> int:
        """
        Determine fire level based on area percentage
        
        Args:
            bbox_area_percentage: Percentage of frame covered by fire (0.0 to 1.0)
        
        Returns:
            Fire level (0-3)
        """
        if bbox_area_percentage < self.small_threshold:
            return 1 
        elif bbox_area_percentage < self.medium_threshold:
            return 2  
        else:
            return 3 
    
    def get_level_description(self, level: int) -> str:
        """Get human-readable description of fire level"""
        descriptions = {
            0: "No Fire",
            1: "Small Fire",
            2: "Medium Fire",
            3: "Large/Critical Fire"
        }
        return descriptions.get(level, "Unknown")
    
    def get_level_color(self, level: int) -> str:
        """Get color code for fire level (for UI)"""
        colors = {
            0: "#10B981",  
            1: "#FBBF24",  
            2: "#F97316",  
            3: "#EF4444"   
        }
        return colors.get(level, "#6B7280")  


from typing import Tuple, List, Dict, Any
import numpy as np
from ..config import settings

class FireLevelClassifier:

    
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
        if not bounding_boxes:
            return 0, 0.0, {}
        
        # Calculate total fire area using binary mask union to prevent overlapping boxes from inflating fire level
        mask = np.zeros((max(1, frame_height), max(1, frame_width)), dtype=np.uint8)
        frame_area = frame_width * frame_height
        
        max_confidence = 0.0
        all_boxes = []
        has_fire = False
        has_smoke = False
        has_small_fire = False
        
        for box in bounding_boxes:
            # Extract bounding box coordinates
            x1, y1, x2, y2 = box['bbox']
            confidence = box['confidence']
            cls_name = box.get('class', '').lower()
            
            if 'fire' in cls_name and 'small' not in cls_name:
                has_fire = True
            if 'smoke' in cls_name:
                has_smoke = True
            if 'small fire' in cls_name:
                has_small_fire = True
            
            bx1, by1 = max(0, int(x1)), max(0, int(y1))
            bx2, by2 = min(frame_width, int(x2)), min(frame_height, int(y2))
            box_area = max(0, bx2 - bx1) * max(0, by2 - by1)
            if bx2 > bx1 and by2 > by1:
                mask[by1:by2, bx1:bx2] = 1

            max_confidence = max(max_confidence, confidence)
            
            all_boxes.append({
                'bbox': [float(x1), float(y1), float(x2), float(y2)],
                'confidence': float(confidence),
                'area': float(box_area),
                'class': cls_name
            })
        total_fire_area = int(np.sum(mask))
        
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
            'has_fire': has_fire,
            'has_smoke': has_smoke,
            'has_small_fire': has_small_fire,
            'bounding_boxes': all_boxes
        }
        
        return fire_level, bbox_area_percentage, metadata
    
    def _determine_level(self, bbox_area_percentage: float) -> int:

        if bbox_area_percentage < self.small_threshold:
            return 1 
        elif bbox_area_percentage < self.medium_threshold:
            return 2  
        else:
            return 3 
    
    def get_level_description(self, level: int) -> str:
        descriptions = {
            0: "No Fire",
            1: "Small Fire",
            2: "Medium Fire",
            3: "Large/Critical Fire"
        }
        return descriptions.get(level, "Unknown")
    
    def get_level_color(self, level: int) -> str:
        colors = {
            0: "#10B981",  
            1: "#FBBF24",  
            2: "#F97316",  
            3: "#EF4444"   
        }
        return colors.get(level, "#6B7280")  

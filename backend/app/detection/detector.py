import cv2
import numpy as np
from ultralytics import YOLO
from typing import List, Dict, Any, Optional, Tuple
import os
import threading
import logging
from ..config import settings
from .classifier import FireLevelClassifier

logger = logging.getLogger(__name__)


class FlameVerifier:
   

    def __init__(self):
        self.prev_frames: Dict[int, np.ndarray] = {}
        # Track candidate bounding boxes across frames: camera_id -> list of tracking records
        self.tracked_objects: Dict[int, List[Dict[str, Any]]] = {}
        self.lock = threading.Lock()

    def verify_flame_chrominance(self, crop: np.ndarray, is_small_fire: bool = False) -> Tuple[bool, float, Dict[str, Any]]:
        if crop is None or crop.size == 0:
            return False, 0.0, {}

        h, w = crop.shape[:2]
        total_px = max(1, h * w)

        b, g, r = cv2.split(crop.astype(np.int32))
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        s_ch = hsv[:, :, 1]
        v_ch = hsv[:, :, 2]

        # 1. Warm flame combustion color (Red distinctly higher than Blue)
        flame_mask = (
            (r >= 130) &
            (r >= b + 35) &
            (v_ch >= 100) &
            (s_ch >= 25)
        )

        # 2. Emissive combustion core (hot luminous white/yellow core characteristic of real flames)
        core_mask = (
            (r >= 190) &
            (g >= 125) &
            (v_ch >= 170) &
            (r >= b + 25)
        )

        flame_px = int(np.sum(flame_mask))
        core_px = int(np.sum(core_mask))
        flame_ratio = flame_px / total_px

        stats = {
            'flame_ratio': flame_ratio,
            'flame_px': flame_px,
            'core_px': core_px,
            'mean_bgr': (float(b.mean()), float(g.mean()), float(r.mean()))
        }

        # Real flames or fire test targets require warm combustion pixels or luminous core
        if is_small_fire:
            is_valid = (flame_px >= 3) or (core_px >= 1)
        else:
            is_valid = (flame_px >= 6 and flame_ratio >= 0.015) or (core_px >= 2) or (flame_px >= 12)

        return is_valid, flame_ratio, stats

    def verify_smoke_chrominance(self, crop: np.ndarray) -> bool:
        """Smoke has low saturation (grey, white, dark smoke) and non-pure uniform color."""
        if crop is None or crop.size == 0:
            return False

        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        s_ch = hsv[:, :, 1]
        # At least 40% of the box should have low saturation (smoke is not vividly colored)
        low_sat_fraction = np.mean(s_ch <= 90)
        return bool(low_sat_fraction >= 0.40)

    def check_temporal_flicker(
        self,
        camera_id: int,
        bbox: List[float],
        curr_gray: np.ndarray,
        min_flicker_score: float = 1.5
    ) -> Tuple[bool, float]:
        x1, y1, x2, y2 = [int(v) for v in bbox]
        h, w = curr_gray.shape[:2]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)

        if x2 <= x1 or y2 <= y1:
            return True, 0.0

        with self.lock:
            prev_gray = self.prev_frames.get(camera_id)

            if prev_gray is None or prev_gray.shape != curr_gray.shape:
                return True, 2.0  # First frame for this camera

            curr_crop = curr_gray[y1:y2, x1:x2]
            prev_crop = prev_gray[y1:y2, x1:x2]

            diff = cv2.absdiff(curr_crop, prev_crop)
            flicker_score = float(np.mean(diff))

            # Maintain history of flicker scores for this camera's tracked region
            tracks = self.tracked_objects.setdefault(camera_id, [])
            center_x, center_y = (x1 + x2) / 2.0, (y1 + y2) / 2.0

            matched_track = None
            for track in tracks:
                dist = np.hypot(track['center'][0] - center_x, track['center'][1] - center_y)
                if dist < max(20, (x2 - x1) * 0.5):
                    matched_track = track
                    break

            if matched_track is None:
                # For a brand new track, require positive flicker from the start
                is_dyn = flicker_score >= (min_flicker_score * 0.8)
                matched_track = {
                    'center': (center_x, center_y),
                    'streak': 1,
                    'flicker_history': [flicker_score]
                }
                tracks.append(matched_track)
                return is_dyn, flicker_score
            else:
                matched_track['center'] = (center_x, center_y)
                matched_track['streak'] += 1
                matched_track['flicker_history'].append(flicker_score)
                if len(matched_track['flicker_history']) > 8:
                    matched_track['flicker_history'].pop(0)

                avg_flicker = float(np.mean(matched_track['flicker_history']))
                # Static objects (toys, rolls, walls, lamps) have very low variance (< min_flicker_score)
                if avg_flicker < min_flicker_score:
                    logger.debug(
                        f"Cam {camera_id}: Static false positive suppressed "
                        f"(streak={matched_track['streak']}, avg_flicker={avg_flicker:.2f} < {min_flicker_score})"
                    )
                    is_dynamic = False
                else:
                    is_dynamic = True

            # Prune old tracks
            if len(tracks) > 20:
                self.tracked_objects[camera_id] = tracks[-10:]

            return is_dynamic, flicker_score

    def update_frame(self, camera_id: int, frame_gray: np.ndarray):
        """Update last known frame for a camera."""
        with self.lock:
            self.prev_frames[camera_id] = frame_gray.copy()


class FireDetector:

    # HSV fire colour ranges for optional fallback (only used if explicitly enabled)
    # HSV fire colour ranges for sensitive fallback (only used if explicitly enabled)
    _HSV_FIRE_RANGES = [
        ((0,   30, 180), (25,  255, 255)),   # warm orange/red/yellow flame (including webcam desaturated core)
        ((160, 30, 180), (180, 255, 255)),   # wrapped red flame
    ]
    _MIN_COLOR_AREA_PX = 30  # At least 30 pixels (handles small lighter flames)

    def __init__(self, model_path: Optional[str] = None):
        self.model_path = model_path or settings.absolute_model_path
        self.confidence_threshold = settings.CONFIDENCE_THRESHOLD
        self.lock = threading.Lock()

        self.classifier = FireLevelClassifier()
        self.verifier = FlameVerifier()

        self.model = None
        self.target_class_ids = None
        self._load_model()

    def _load_model(self):
        try:
            import torch
            # 2 threads achieves fastest inference on Pi Cortex-A72 (434ms vs 758ms with 4 threads)
            # while leaving 2 full cores for camera capture, web streaming, and system tasks
            torch.set_num_threads(2)
        except Exception:
            pass

        if not os.path.exists(self.model_path):
            self.model = YOLO('yolov8n.pt')
        else:
            self.model = YOLO(self.model_path)

        try:
            dummy_frame = np.zeros((100, 100, 3), dtype=np.uint8)
            self.model(dummy_frame, imgsz=settings.INFERENCE_SIZE, verbose=False)
        except Exception:
            pass

        # Strictly isolate fire/small_fire and smoke classes, completely ignoring 'no-fire' and 'light'
        if hasattr(self.model, 'names') and self.model.names:
            self.target_class_ids = [
                idx for idx, name in self.model.names.items()
                if name.lower() in ['fire', 'flame', 'smoke', 'small_fire', 'small fire']
            ]
            if not self.target_class_ids:
                # If custom model has single class (0: small_fire), use all classes
                self.target_class_ids = None

    def _detect_color_fire(self, frame: np.ndarray) -> List[Dict[str, Any]]:
        """Strict HSV + emissive color-based fire detector for small flames."""
        h, w = frame.shape[:2]

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = np.zeros((h, w), dtype=np.uint8)
        for (lo, hi) in self._HSV_FIRE_RANGES:
            mask = cv2.bitwise_or(mask, cv2.inRange(hsv, np.array(lo), np.array(hi)))

        b_c, g_c, r_c = cv2.split(frame.astype(np.int32))
        core_flame = ((r_c >= 190) & (g_c >= 140) & (r_c >= b_c + 15) & (hsv[:, :, 2] >= 180)).astype(np.uint8) * 255
        mask = cv2.bitwise_and(mask, core_flame)

        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_DILATE, kernel, iterations=2)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        boxes = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < self._MIN_COLOR_AREA_PX:
                continue
            x, y, bw, bh = cv2.boundingRect(cnt)
            crop = frame[y:y+bh, x:x+bw]
            is_valid, flame_ratio, _ = self.verifier.verify_flame_chrominance(crop, is_small_fire=True)
            if not is_valid:
                continue

            conf = min(0.65, 0.40 + (area / (h * w)) * 5)
            boxes.append({
                'bbox': [float(x), float(y), float(x + bw), float(y + bh)],
                'confidence': conf,
                'class': 'Fire',
                'source': 'combustion_color'
            })

        return boxes

    def _apply_nms(self, boxes: List[Dict[str, Any]], iou_threshold: float = 0.35) -> List[Dict[str, Any]]:
        """Apply Non-Maximum Suppression to eliminate overlapping duplicate detections."""
        if len(boxes) <= 1:
            return boxes
        rects = []
        scores = []
        for b in boxes:
            x1, y1, x2, y2 = b['bbox']
            rects.append([int(x1), int(y1), int(x2 - x1), int(y2 - y1)])
            scores.append(float(b['confidence']))
        indices = cv2.dnn.NMSBoxes(rects, scores, score_threshold=0.0, nms_threshold=iou_threshold)
        if len(indices) == 0:
            return []
        if isinstance(indices, (list, tuple)) or hasattr(indices, 'flatten'):
            indices = np.array(indices).flatten().tolist()
        return [boxes[i] for i in indices]

    def detect(self, frame: np.ndarray, camera_id: int = 0) -> Dict[str, Any]:
        if frame is None or frame.size == 0:
            return self._empty_result()

        frame_height, frame_width = frame.shape[:2]
        frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        inference_conf = min(0.25, self.confidence_threshold)

        with self.lock:
            # Run inference targeting only fire and smoke classes
            import torch
            with torch.inference_mode():
                results = self.model(
                    frame,
                    conf=inference_conf,
                    classes=self.target_class_ids,
                    imgsz=settings.INFERENCE_SIZE,
                    verbose=False
                )

        bounding_boxes = []

        if len(results) > 0:
            result = results[0]

            if result.boxes is not None and len(result.boxes) > 0:
                for box in result.boxes:
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                    confidence = float(box.conf[0].cpu().numpy())
                    class_id = int(box.cls[0].cpu().numpy())
                    class_name = self.model.names[class_id] if class_id < len(self.model.names) else "unknown"
                    class_lower = class_name.lower()

                    bx1, by1 = max(0, int(x1)), max(0, int(y1))
                    bx2, by2 = min(frame_width, int(x2)), min(frame_height, int(y2))
                    crop = frame[by1:by2, bx1:bx2]
                    if crop.size == 0:
                        continue

                    # 1. Smoke Detection
                    if class_lower == 'smoke':
                        smoke_thresh = getattr(settings, 'SMOKE_CONFIDENCE_THRESHOLD', 0.25)
                        if confidence < smoke_thresh:
                            continue
                        if not self.verifier.verify_smoke_chrominance(crop):
                            continue
                        bounding_boxes.append({
                            'bbox': [float(x1), float(y1), float(x2), float(y2)],
                            'confidence': confidence,
                            'class': 'Smoke'
                        })
                        continue

                    # 2. Fire / Small Fire Detection
                    if class_lower in ['fire', 'flame', 'small_fire', 'small fire']:
                        fire_thresh = getattr(settings, 'SMALL_FIRE_CONFIDENCE_THRESHOLD', 0.35)
                        if confidence < fire_thresh:
                            continue

                        # Verify flame chrominance and emissivity
                        is_valid_flame, flame_ratio, _ = self.verifier.verify_flame_chrominance(
                            crop, is_small_fire=(confidence < 0.45 or (bx2 - bx1) * (by2 - by1) < 15000)
                        )
                        if not is_valid_flame:
                            logger.debug(f"Cam {camera_id}: Fire candidate rejected by chrominance check (ratio={flame_ratio:.2f})")
                            continue

                        # Verify dynamic flicker if enabled
                        if settings.ENABLE_FLICKER_VERIFICATION:
                            is_dynamic, flicker_score = self.verifier.check_temporal_flicker(
                                camera_id, [x1, y1, x2, y2], frame_gray, settings.MIN_FLICKER_SCORE
                            )
                            if not is_dynamic:
                                continue

                        bounding_boxes.append({
                            'bbox': [float(x1), float(y1), float(x2), float(y2)],
                            'confidence': confidence,
                            'class': 'Fire'
                        })
                        continue

        # ── 3. Optional Small Flame Candidate Slicing (only if explicitly enabled) ───
        if not bounding_boxes and getattr(settings, 'ENABLE_HOTSPOT_SCANNING', False):
            b_ch, g_ch, r_ch = cv2.split(frame.astype(np.int32))
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            v_ch = hsv[:, :, 2]

            core_mask = (
                (r_ch >= 190) &
                (g_ch >= 140) &
                (v_ch >= 180) &
                (r_ch >= b_ch + 15)
            ).astype(np.uint8) * 255

            contours, _ = cv2.findContours(core_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for cnt in contours:
                area = cv2.contourArea(cnt)
                if area < 35 or area > 10000:
                    continue
                x, y, bw, bh = cv2.boundingRect(cnt)
                pad_w = max(40, bw)
                pad_h = max(40, bh)
                cx, cy = x + bw // 2, y + bh // 2
                cx1 = max(0, cx - pad_w)
                cy1 = max(0, cy - pad_h)
                cx2 = min(frame_width, cx + pad_w)
                cy2 = min(frame_height, cy + pad_h)

                crop = frame[cy1:cy2, cx1:cx2]
                if crop.size == 0:
                    continue

                with self.lock:
                    crop_res = self.model(
                        crop,
                        conf=max(0.35, self.confidence_threshold),
                        classes=self.target_class_ids,
                        verbose=False
                    )[0]

                for b in crop_res.boxes:
                    cls_id = int(b.cls[0].cpu().numpy())
                    cname = self.model.names[cls_id].lower()
                    if cname in ['fire', 'flame', 'small_fire', 'small fire']:
                        conf = float(b.conf[0].cpu().numpy())
                        xy = b.xyxy[0].cpu().numpy()
                        gx1, gy1, gx2, gy2 = xy[0] + cx1, xy[1] + cy1, xy[2] + cx1, xy[3] + cy1
                        # Verify candidate crop
                        flame_crop = frame[max(0, int(gy1)):min(frame_height, int(gy2)), max(0, int(gx1)):min(frame_width, int(gx2))]
                        if flame_crop.size > 0:
                            is_valid, _, _ = self.verifier.verify_flame_chrominance(flame_crop, is_small_fire=True)
                            if is_valid:
                                bounding_boxes.append({
                                    'bbox': [float(gx1), float(gy1), float(gx2), float(gy2)],
                                    'confidence': conf,
                                    'class': 'Fire'
                                })

        # ── 4. Optional Colour-based fallback ──────────────────────────────────
        if not bounding_boxes and getattr(settings, 'ENABLE_COLOR_FALLBACK', False):
            color_boxes = self._detect_color_fire(frame)
            if color_boxes:
                bounding_boxes = color_boxes
                logger.debug(f"Color-fallback detected {len(color_boxes)} fire region(s)")
        # ───────────────────────────────────────────────────────────────────────

        # Apply Non-Maximum Suppression to remove overlapping duplicate boxes
        bounding_boxes = self._apply_nms(bounding_boxes, iou_threshold=0.35)

        # Update previous frame for flicker tracking
        self.verifier.update_frame(camera_id, frame_gray)

        if bounding_boxes:
            fire_level, bbox_area, metadata = self.classifier.classify(
                bounding_boxes, frame_width, frame_height
            )

            return {
                'fire_detected': True,
                'fire_level': fire_level,
                'confidence': metadata.get('max_confidence', 0.0),
                'has_fire': metadata.get('has_fire', False),
                'has_smoke': metadata.get('has_smoke', False),
                'has_small_fire': metadata.get('has_small_fire', False),
                'bbox_area': bbox_area,
                'bounding_boxes': bounding_boxes,
                'metadata': metadata,
                'frame_width': frame_width,
                'frame_height': frame_height
            }
        else:
            return self._empty_result(frame_width, frame_height)

    def _empty_result(self, frame_width: int = 0, frame_height: int = 0) -> Dict[str, Any]:
        return {
            'fire_detected': False,
            'fire_level': 0,
            'confidence': 0.0,
            'has_fire': False,
            'has_smoke': False,
            'has_small_fire': False,
            'bbox_area': 0.0,
            'bounding_boxes': [],
            'metadata': {},
            'frame_width': frame_width,
            'frame_height': frame_height
        }

    def draw_detections(self, frame: np.ndarray, detection_result: Dict[str, Any]) -> np.ndarray:
        annotated_frame = frame.copy()
        h, w = frame.shape[:2]

        if not detection_result.get('bounding_boxes'):
            return annotated_frame

        fire_level = detection_result['fire_level']
        level_color = self.classifier.get_level_color(fire_level)
        color_bgr = self._hex_to_bgr(level_color)

        for box in detection_result['bounding_boxes']:
            x1, y1, x2, y2 = [int(coord) for coord in box['bbox']]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w - 1, x2), min(h - 1, y2)

            if x2 <= x1 or y2 <= y1:
                continue

            bw, bh = x2 - x1, y2 - y1
            conf = box['confidence']
            label = box.get('class', 'fire').upper()

            overlay = annotated_frame.copy()
            cv2.rectangle(overlay, (x1, y1), (x2, y2), color_bgr, -1)
            cv2.addWeighted(overlay, 0.15, annotated_frame, 0.85, 0, annotated_frame)

            line_len = min(20, bw // 4, bh // 4)
            thickness = 2

            cv2.line(annotated_frame, (x1, y1), (x1 + line_len, y1), color_bgr, thickness)
            cv2.line(annotated_frame, (x1, y1), (x1, y1 + line_len), color_bgr, thickness)
            cv2.line(annotated_frame, (x2, y1), (x2 - line_len, y1), color_bgr, thickness)
            cv2.line(annotated_frame, (x2, y1), (x2, y1 + line_len), color_bgr, thickness)
            cv2.line(annotated_frame, (x1, y2), (x1 + line_len, y2), color_bgr, thickness)
            cv2.line(annotated_frame, (x1, y2), (x1, y2 - line_len), color_bgr, thickness)
            cv2.line(annotated_frame, (x2, y2), (x2 - line_len, y2), color_bgr, thickness)
            cv2.line(annotated_frame, (x2, y2), (x2, y2 - line_len), color_bgr, thickness)

            cv2.line(annotated_frame, (x1, y1 + 5), (x2, y1 + 5), color_bgr, 1)

            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.4
            font_thickness = 1

            status_text = f"{label} [LVL {fire_level}] {int(conf * 100)}%"

            t_size, _ = cv2.getTextSize(status_text, font, font_scale, font_thickness)
            tx = max(0, min(x1, w - t_size[0] - 6))
            ty = y1 - 8
            if ty - t_size[1] < 0:
                ty = y1 + t_size[1] + 12
            cv2.rectangle(annotated_frame, (tx, ty - t_size[1] - 2), (tx + t_size[0] + 4, ty + 2), color_bgr, -1)
            cv2.putText(annotated_frame, status_text, (tx + 2, ty), font, font_scale, (255, 255, 255), font_thickness)

        # Only show the large flashing alert banner for Level 2 (Medium) or Level 3 (Critical) fires.
        # Level 1 (Small Fire / lighter) shows the neat bounding box without the alarming full-width banner.
        if fire_level >= 2:
            level_desc = self.classifier.get_level_description(fire_level)
            banner_text = f">> SYSTEM_ALERT: {level_desc.upper()} <<"
            t_size, _ = cv2.getTextSize(banner_text, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)

            banner_h = t_size[1] + 20
            banner_overlay = annotated_frame.copy()
            cv2.rectangle(banner_overlay, (0, 0), (w, banner_h), color_bgr, -1)
            cv2.addWeighted(banner_overlay, 0.7, annotated_frame, 0.3, 0, annotated_frame)

            cv2.putText(annotated_frame, banner_text, (20, banner_h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

        return annotated_frame

    def _hex_to_bgr(self, hex_color: str) -> tuple:
        hex_color = hex_color.lstrip('#')
        rgb = tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
        return (rgb[2], rgb[1], rgb[0])

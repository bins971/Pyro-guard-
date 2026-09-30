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

    def is_artificial_light(self, crop: np.ndarray) -> bool:
        """Reject artificial ceiling lights, fluorescent tubes, LED fixtures, and window glare."""
        if crop is None or crop.size == 0:
            return False
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        s_ch = hsv[:, :, 1]
        v_ch = hsv[:, :, 2]
        b, g, r = cv2.split(crop.astype(np.int32))

        # Check for warm incandescent flame halo (characteristic of real flames even when core is overexposed white)
        warm_halo = (
            (r >= 140) &
            (r >= b + 20) &
            (g >= 60) &
            (v_ch >= 80)
        )
        if np.sum(warm_halo) >= 2:
            # Genuine flame with warm combustion halo is NEVER an artificial light
            return False

        bright_mask = v_ch >= 150
        num_bright = int(np.sum(bright_mask))
        if num_bright < 10:
            return False

        # Artificial lights have very low saturation (S < 35) or balanced RGB (r ~ g ~ b)
        desat_bright = bright_mask & (s_ch < 35)
        desat_ratio = float(np.sum(desat_bright)) / float(num_bright)

        # Cold white artificial lamps (fluorescent tubes, ceiling downlights) have ZERO warm combustion
        # and are predominantly white/desaturated (> 80%) with balanced RGB
        if desat_ratio >= 0.80 and float(np.mean(np.abs(r - b))) < 18 and float(np.mean(np.abs(r - g))) < 18:
            return True
        return False

    def verify_flame_chrominance(self, crop: np.ndarray, is_small_fire: bool = False) -> Tuple[bool, float, Dict[str, Any]]:
        if crop is None or crop.size == 0:
            return False, 0.0, {}

        # First filter out artificial light fixtures and daylight reflections
        if self.is_artificial_light(crop):
            return False, 0.0, {'rejected_reason': 'artificial_light'}

        h, w = crop.shape[:2]
        total_px = max(1, h * w)

        # Minimum physical box size: reject tiny sensor noise clusters (< 8x8 or < 64px)
        if w < 8 or h < 8 or total_px < 64:
            return False, 0.0, {'reason': 'box_too_small'}

        b, g, r = cv2.split(crop.astype(np.int32))
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        s_ch = hsv[:, :, 1]
        v_ch = hsv[:, :, 2]

        # 1. Warm flame combustion color (genuine fire has distinct orange/yellow warmth with G >= 55)
        flame_mask = (
            (r >= 135) &
            (g >= 55) &
            (r >= b + 30) &
            (r >= g - 15) &
            (v_ch >= 90) &
            (s_ch >= 45)
        )

        # 2. Emissive combustion core (hot luminous white/yellow core characteristic of real flames)
        # Must still exhibit warm fire emissivity (R >= B + 20), not cold blue-white daylight sky (where R ~ B)
        core_mask = (
            (r >= 210) &
            (g >= 130) &
            (v_ch >= 170) &
            (r >= b + 20) &
            (s_ch >= 25)
        )

        # 3. Butane / Gas blue flame base (characteristic of lighters and torch burners)
        gas_mask = (
            (b >= 130) &
            (v_ch >= 110) &
            (g >= 80) &
            (b >= r + 20) &
            (s_ch >= 45)
        )

        flame_px = int(np.sum(flame_mask))
        core_px = int(np.sum(core_mask))
        gas_px = int(np.sum(gas_mask))
        active_fire_px = flame_px + core_px + gas_px
        flame_ratio = active_fire_px / total_px

        stats = {
            'flame_ratio': flame_ratio,
            'flame_px': flame_px,
            'core_px': core_px,
            'gas_px': gas_px,
            'total_px': total_px,
            'mean_bgr': (float(b.mean()), float(g.mean()), float(r.mean()))
        }

        min_active_px = 8 if is_small_fire or total_px < 600 else 20
        min_flame_mantle = 4 if is_small_fire or total_px < 600 else 10

        is_valid = bool(
            (active_fire_px >= min_active_px) and
            (flame_ratio >= 0.05) and
            ((flame_px >= min_flame_mantle) or (gas_px >= min_flame_mantle))
        )

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
            # Use 90th percentile difference so a small flame inside a large bounding box is not diluted
            flicker_score = float(np.percentile(diff, 90)) if diff.size > 0 else 0.0

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
                # Brand new detection candidate: track center and motion
                matched_track = {
                    'center': (center_x, center_y),
                    'streak': 1,
                    'flicker_history': [flicker_score]
                }
                tracks.append(matched_track)
                # If a previous frame exists and this candidate has essentially zero motion/flicker, suppress immediately
                if flicker_score < (min_flicker_score * 0.5):
                    return False, flicker_score
                return True, flicker_score
            else:
                matched_track['center'] = (center_x, center_y)
                matched_track['streak'] += 1
                matched_track['flicker_history'].append(flicker_score)
                if len(matched_track['flicker_history']) > 8:
                    matched_track['flicker_history'].pop(0)

                avg_flicker = float(np.mean(matched_track['flicker_history']))
                # Static objects (windows, daylight glare, walls, lamps) that persist with zero flicker are suppressed
                if matched_track['streak'] >= 2 and avg_flicker < min_flicker_score:
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
                    if (bx2 - bx1) < 8 or (by2 - by1) < 8 or ((bx2 - bx1) * (by2 - by1)) < 64:
                        continue
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
                        fire_thresh = getattr(settings, 'SMALL_FIRE_CONFIDENCE_THRESHOLD', 0.28)
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

        # ── 3. High-Sensitivity Hotspot Slicing (detects small flames/lighters in 720p/1080p feeds) ──
        if not bounding_boxes:
            b_ch, g_ch, r_ch = cv2.split(frame.astype(np.int32))
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            s_ch = hsv[:, :, 1]
            v_ch = hsv[:, :, 2]

            # Fast combustion hotspot mask: incandescent yellow/orange or butane blue gas
            # Pure desaturated white sky/daylight is strictly excluded
            hotspot_mask = (
                ((r_ch >= 170) & (g_ch >= 80) & (r_ch >= b_ch + 20) & (s_ch >= 40) & (v_ch >= 130)) |
                ((b_ch >= 130) & (b_ch >= r_ch + 20) & (s_ch >= 40) & (v_ch >= 130))
            ).astype(np.uint8) * 255

            num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(hotspot_mask)
            candidates = []
            for i in range(1, num_labels):
                area = stats[i, cv2.CC_STAT_AREA]
                if 8 <= area <= 6000:
                    candidates.append((area, centroids[i], stats[i]))

            # Test up to 3 candidate hotspots
            candidates.sort(key=lambda c: c[0], reverse=True)
            for _, centroid, stat in candidates[:3]:
                cx, cy = int(centroid[0]), int(centroid[1])
                bw, bh = stat[cv2.CC_STAT_WIDTH], stat[cv2.CC_STAT_HEIGHT]
                pad = max(60, max(bw, bh) * 2)
                cx1 = max(0, cx - pad)
                cy1 = max(0, cy - pad)
                cx2 = min(frame_width, cx + pad)
                cy2 = min(frame_height, cy + pad)
                crop = frame[cy1:cy2, cx1:cx2]
                if crop.size == 0:
                    continue

                with self.lock:
                    import torch
                    with torch.inference_mode():
                        crop_res = self.model(
                            crop,
                            conf=0.22,
                            classes=self.target_class_ids,
                            verbose=False
                        )[0]

                if crop_res.boxes is not None and len(crop_res.boxes) > 0:
                    fire_thresh = getattr(settings, 'SMALL_FIRE_CONFIDENCE_THRESHOLD', 0.28)
                    for b in crop_res.boxes:
                        conf = float(b.conf[0].cpu().numpy())
                        if conf < fire_thresh:
                            continue
                        xy = b.xyxy[0].cpu().numpy()
                        gx1, gy1 = float(xy[0] + cx1), float(xy[1] + cy1)
                        gx2, gy2 = float(xy[2] + cx1), float(xy[3] + cy1)

                        flame_crop = frame[max(0, int(gy1)):min(frame_height, int(gy2)), max(0, int(gx1)):min(frame_width, int(gx2))]
                        if flame_crop.size > 0:
                            is_valid, _, _ = self.verifier.verify_flame_chrominance(flame_crop, is_small_fire=True)
                            if is_valid:
                                if settings.ENABLE_FLICKER_VERIFICATION:
                                    is_dynamic, _ = self.verifier.check_temporal_flicker(
                                        camera_id, [gx1, gy1, gx2, gy2], frame_gray, settings.MIN_FLICKER_SCORE
                                    )
                                    if not is_dynamic:
                                        continue
                                bounding_boxes.append({
                                    'bbox': [gx1, gy1, gx2, gy2],
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

        orig_w = detection_result.get('frame_width', w) or w
        orig_h = detection_result.get('frame_height', h) or h
        scale_x = w / float(orig_w) if orig_w > 0 else 1.0
        scale_y = h / float(orig_h) if orig_h > 0 else 1.0

        fire_level = detection_result.get('fire_level', 1)
        level_color = self.classifier.get_level_color(fire_level)
        color_bgr = self._hex_to_bgr(level_color)

        for box in detection_result['bounding_boxes']:
            raw_box = box['bbox']
            x1 = int(raw_box[0] * scale_x)
            y1 = int(raw_box[1] * scale_y)
            x2 = int(raw_box[2] * scale_x)
            y2 = int(raw_box[3] * scale_y)
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

            line_len = min(20, max(6, bw // 4), max(6, bh // 4))
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

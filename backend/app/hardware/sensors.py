
import random
import logging
import time
from typing import Dict, Any
from datetime import datetime
from .base_sensor import HardwareSensor

logger = logging.getLogger(__name__)


class VirtualFireSensor(HardwareSensor):
    
    def __init__(self, sensor_id: str = "virtual_01", name: str = "PC Simulator"):
        super().__init__(sensor_id, name)
        self._baseline_temp = 28.0
        self._baseline_humidity = 55.0
        self._baseline_smoke = 120.0
        
        self.current_state = {
            "temperature": self._baseline_temp,
            "smoke_analog": self._baseline_smoke,
            "humidity": self._baseline_humidity,
            "smoke_detected": False,
            "status": "normal"
        }
        
        # Fire event tracking
        self._fire_active = False
        self._fire_level = 0
        self._fire_confidence = 0.0
        self._fire_last_seen = 0.0 
        self._fire_decay_seconds = 10.0  
        
    def initialize(self) -> bool:
        logger.info(f"Virtual sensor {self.name} initialized (Simulation mode)")
        return True
    
    def notify_fire_event(self, fire_level: int, confidence: float):
        self._fire_active = True
        self._fire_level = fire_level
        self._fire_confidence = confidence
        self._fire_last_seen = time.time()
    
    def read(self) -> Dict[str, Any]:
        now = time.time()
        time_since_fire = now - self._fire_last_seen if self._fire_last_seen > 0 else 999
        
        fire_influence = 0.0
        if time_since_fire < self._fire_decay_seconds:
            if time_since_fire < 2.0:
                fire_influence = min(1.0, self._fire_level / 3.0) * self._fire_confidence
            else:
                decay_progress = (time_since_fire - 2.0) / (self._fire_decay_seconds - 2.0)
                fire_influence = max(0.0, (1.0 - decay_progress) * min(1.0, self._fire_level / 3.0) * self._fire_confidence)
        
        # Temperature: rises dramatically near fire
        # Level 1: +5-10°C, Level 2: +15-25°C, Level 3: +30-50°C
        temp_boost = fire_influence * (15.0 + self._fire_level * 12.0)
        target_temp = self._baseline_temp + temp_boost + random.uniform(-0.3, 0.3)
        self.current_state["temperature"] += (target_temp - self.current_state["temperature"]) * 0.3
        
        # Humidity: drops when fire is present (fire dries the air)
        humidity_drop = fire_influence * (10.0 + self._fire_level * 5.0)
        target_humidity = self._baseline_humidity - humidity_drop + random.uniform(-0.5, 0.5)
        target_humidity = max(15.0, target_humidity)
        self.current_state["humidity"] += (target_humidity - self.current_state["humidity"]) * 0.3
        
        # Smoke: rises significantly when fire is present
        # Normal: ~120, Fire Level 1: ~300, Level 2: ~500, Level 3: ~800
        smoke_boost = fire_influence * (200.0 + self._fire_level * 200.0)
        target_smoke = self._baseline_smoke + smoke_boost + random.uniform(-5.0, 5.0)
        self.current_state["smoke_analog"] += (target_smoke - self.current_state["smoke_analog"]) * 0.25
        
        # Smoke detection threshold
        self.current_state["smoke_detected"] = self.current_state["smoke_analog"] > 250.0
        
        # Status determination
        temp = self.current_state["temperature"]
        smoke = self.current_state["smoke_analog"]
        if temp > 50.0 or smoke > 500.0:
            self.current_state["status"] = "danger"
        elif temp > 35.0 or smoke > 250.0:
            self.current_state["status"] = "warning"
        else:
            self.current_state["status"] = "normal"

        self.last_value = {
            "temperature": round(self.current_state["temperature"], 1),
            "smoke_analog": int(self.current_state["smoke_analog"]),
            "humidity": round(self.current_state["humidity"], 1),
            "smoke_detected": self.current_state["smoke_detected"],
            "status": self.current_state["status"]
        }
        self.last_update = datetime.now()
        return self.last_value
    
    def cleanup(self):
        logger.info(f"Virtual sensor {self.name} cleaned up")


class RPiGPYOSensor(HardwareSensor):
   
    
    def __init__(self, sensor_id: str, name: str, pin: int):
        super().__init__(sensor_id, name)
        self.pin = pin
        
    def initialize(self) -> bool:
        try:
            import RPi.GPIO as GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.pin, GPIO.IN)
            logger.info(f"RPi GPIO Sensor {self.name} initialized on pin {self.pin}")
            return True
        except (ImportError, RuntimeError):
            logger.warning(f"RPi GPIO Sensor {self.name} could not initialize (Not on RPi or missing library)")
            return False
            
    def read(self) -> Dict[str, Any]:
        return {"status": "hardware_disconnected"}
    
    def cleanup(self):
        try:
            import RPi.GPIO as GPIO
            GPIO.cleanup(self.pin)
        except Exception:
            pass


class InfraredThermalSensor(HardwareSensor):
    
    def __init__(self, sensor_id: str = "ir_thermal_01", name: str = "Thermal Scanner Alpha"):
        super().__init__(sensor_id, name)
        self._baseline_peak_temp = 32.0
        self.current_state = {
            "thermal_anomaly_score": 0.05,
            "peak_temp": self._baseline_peak_temp,
            "status": "nominal"
        }
        
        # Fire event tracking
        self._fire_active = False
        self._fire_level = 0
        self._fire_confidence = 0.0
        self._fire_last_seen = 0.0
        self._fire_decay_seconds = 10.0
        
    def initialize(self) -> bool:
        logger.info(f"Infrared Thermal Sensor {self.name} initialized")
        return True
    
    def notify_fire_event(self, fire_level: int, confidence: float):
        """Called by the detection loop when fire is detected."""
        self._fire_active = True
        self._fire_level = fire_level
        self._fire_confidence = confidence
        self._fire_last_seen = time.time()
    
    def read(self) -> Dict[str, Any]:
        now = time.time()
        time_since_fire = now - self._fire_last_seen if self._fire_last_seen > 0 else 999
        
        # Calculate fire influence with decay
        fire_influence = 0.0
        if time_since_fire < self._fire_decay_seconds:
            if time_since_fire < 2.0:
                fire_influence = min(1.0, self._fire_level / 3.0) * self._fire_confidence
            else:
                decay_progress = (time_since_fire - 2.0) / (self._fire_decay_seconds - 2.0)
                fire_influence = max(0.0, (1.0 - decay_progress) * min(1.0, self._fire_level / 3.0) * self._fire_confidence)
        
        # Anomaly score: 0.05 at rest, spikes to 0.7-0.95 when fire detected
        target_anomaly = 0.05 + fire_influence * (0.5 + self._fire_level * 0.15)
        target_anomaly = min(0.98, target_anomaly)
        self.current_state["thermal_anomaly_score"] += (target_anomaly - self.current_state["thermal_anomaly_score"]) * 0.3
        self.current_state["thermal_anomaly_score"] += random.uniform(-0.005, 0.005)
        self.current_state["thermal_anomaly_score"] = max(0.01, min(0.99, self.current_state["thermal_anomaly_score"]))
        
        # Peak temp: baseline ~32°C, fire can push it to 80-200°C+
        temp_boost = fire_influence * (50.0 + self._fire_level * 40.0)
        target_peak = self._baseline_peak_temp + temp_boost + random.uniform(-0.5, 0.5)
        self.current_state["peak_temp"] += (target_peak - self.current_state["peak_temp"]) * 0.3
        
        # Status
        anomaly = self.current_state["thermal_anomaly_score"]
        if anomaly > 0.6:
            self.current_state["status"] = "anomaly_detected"
        elif anomaly > 0.3:
            self.current_state["status"] = "elevated"
        else:
            self.current_state["status"] = "nominal"
        
        self.last_value = {
            "anomaly_score": round(self.current_state["thermal_anomaly_score"], 2),
            "peak_temperature": round(self.current_state["peak_temp"], 1),
            "status": self.current_state["status"]
        }
        self.last_update = datetime.now()
        return self.last_value
    
    def cleanup(self):
        logger.info(f"Infrared Thermal Sensor {self.name} cleaned up")

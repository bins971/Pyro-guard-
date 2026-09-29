import threading
import time
import logging
from typing import Dict, List, Any, Optional
from .base_sensor import HardwareSensor

logger = logging.getLogger(__name__)


class SensorManager:
  
    def __init__(self, update_interval: float = 1.0):
        self.sensors: Dict[str, HardwareSensor] = {}
        self.update_interval = update_interval
        self.is_running = False
        self.thread = None
        self.latest_data = {}
        self.ema_data = {}
        self.alpha = 0.3
        self.data_lock = threading.Lock()
        
    def register_sensor(self, sensor: HardwareSensor):
        if sensor.initialize():
            sensor.is_active = True
            self.sensors[sensor.sensor_id] = sensor
            if sensor.last_value:
                self.ema_data[sensor.sensor_id] = sensor.last_value.copy()
                with self.data_lock:
                    self.latest_data[sensor.sensor_id] = {
                        k: (round(v, 2) if isinstance(v, (float, int)) else v)
                        for k, v in sensor.last_value.items()
                    }
            logger.info(f"Registered sensor: {sensor.name} ({sensor.sensor_id})")
        else:
            logger.warning(f"Failed to initialize sensor: {sensor.name}")
            
    def start(self):
        if self.is_running:
            return
            
        self.is_running = True
        self.thread = threading.Thread(target=self._poll_sensors, daemon=True)
        self.thread.start()
        logger.info("Sensor Manager started")
        
    def stop(self):
        self.is_running = False
        if self.thread:
            self.thread.join(timeout=2)
            
        for sensor in self.sensors.values():
            sensor.cleanup()
        logger.info("Sensor Manager stopped")
        
    def _poll_sensors(self):
        while self.is_running:
            current_raw_data = {}
            for sid, sensor in self.sensors.items():
                try:
                    reading = sensor.read()
                    current_raw_data[sid] = reading
                    
                    if sid not in self.ema_data:
                        self.ema_data[sid] = reading.copy()
                    else:
                        for key, value in reading.items():
                            if isinstance(value, (int, float)):
                                if key in ('smoke_analog', 'digital_raw'):
                                    self.ema_data[sid][key] = value
                                else:
                                    prev_ema = self.ema_data[sid].get(key, value)
                                    filtered_val = (self.alpha * value) + ((1 - self.alpha) * prev_ema)
                                    self.ema_data[sid][key] = filtered_val
                            else:
                                self.ema_data[sid][key] = value
                except Exception as e:
                    logger.error(f"Error reading sensor {sid}: {e}")
                    
            with self.data_lock:
                output_data = {}
                for sid, data in self.ema_data.items():
                    output_data[sid] = {
                        k: (round(v, 2) if isinstance(v, (float, int)) else v) 
                        for k, v in data.items()
                    }
                self.latest_data = output_data
                
            time.sleep(self.update_interval)
            
    def get_latest_data(self) -> Dict[str, Any]:
        with self.data_lock:
            return self.latest_data.copy()

    def get_sensor_statuses(self) -> List[Dict[str, Any]]:
        return [s.get_status() for s in self.sensors.values()]

    def notify_fire_event(self, fire_level: int, confidence: float):
        """Broadcast a fire detection event to all sensors that support it."""
        for sensor in self.sensors.values():
            if hasattr(sensor, 'notify_fire_event'):
                try:
                    sensor.notify_fire_event(fire_level, confidence)
                except Exception as e:
                    logger.error(f"Error notifying sensor {sensor.sensor_id}: {e}")

    def get_verification_score(self) -> float:
        scores = []
        data = self.get_latest_data()
        
        for sensor_id, reading in data.items():
            # Temperature check: above 35°C is suspicious, above 45°C confirms
            temp = reading.get('temperature')
            if temp is not None:
                if temp > 45.0:
                    scores.append(1.0)
                elif temp > 35.0:
                    scores.append(0.5)
                else:
                    scores.append(0.0)
            
            # Smoke check
            smoke = reading.get('smoke_analog')
            if smoke is not None:
                if smoke > 400:
                    scores.append(1.0)
                elif smoke > 250:
                    scores.append(0.5)
                else:
                    scores.append(0.0)
            
            # Thermal anomaly check
            anomaly = reading.get('anomaly_score')
            if anomaly is not None:
                if anomaly > 0.6:
                    scores.append(1.0)
                elif anomaly > 0.3:
                    scores.append(0.5)
                else:
                    scores.append(0.0)
        
        return sum(scores) / len(scores) if scores else 0.0

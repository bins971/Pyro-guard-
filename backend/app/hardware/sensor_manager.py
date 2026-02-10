"""
Sensor manager for coordinating multiple hardware sensors
"""
import threading
import time
from typing import Dict, List, Any, Optional
from .base_sensor import HardwareSensor

class SensorManager:
    """
    Coordinates data collection from all registered hardware sensors
    """
    
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
        """Add a new sensor to the manager"""
        if sensor.initialize():
            sensor.is_active = True
            self.sensors[sensor.sensor_id] = sensor
            print(f"Registered sensor: {sensor.name} ({sensor.sensor_id})")
        else:
            print(f"Failed to initialize sensor: {sensor.name}")
            
    def start(self):
        """Start the background polling thread"""
        if self.is_running:
            return
            
        self.is_running = True
        self.thread = threading.Thread(target=self._poll_sensors, daemon=True)
        self.thread.start()
        print("Sensor Manager started")
        
    def stop(self):
        """Stop polling and cleanup sensors"""
        self.is_running = False
        if self.thread:
            self.thread.join(timeout=2)
            
        for sensor in self.sensors.values():
            sensor.cleanup()
        print("Sensor Manager stopped")
        
    def _poll_sensors(self):
        """Background thread to poll all active sensors with EMA filtering"""
        while self.is_running:
            current_raw_data = {}
            for sid, sensor in self.sensors.items():
                try:
                    reading = sensor.read()
                    current_raw_data[sid] = reading
                    
                    # Apply EMA filtering to numeric values
                    if sid not in self.ema_data:
                        self.ema_data[sid] = reading.copy()
                    else:
                        for key, value in reading.items():
                            if isinstance(value, (int, float)):
                                prev_ema = self.ema_data[sid].get(key, value)
                                # EMA formula: S_t = alpha * Y_t + (1 - alpha) * S_{t-1}
                                filtered_val = (self.alpha * value) + ((1 - self.alpha) * prev_ema)
                                self.ema_data[sid][key] = filtered_val
                            else:
                                self.ema_data[sid][key] = value
                except Exception as e:
                    print(f"Error reading sensor {sid}: {e}")
                    
            with self.data_lock:
                # Round EMA values for output
                output_data = {}
                for sid, data in self.ema_data.items():
                    output_data[sid] = {
                        k: (round(v, 2) if isinstance(v, (float, int)) else v) 
                        for k, v in data.items()
                    }
                self.latest_data = output_data
                
            time.sleep(self.update_interval)
            
    def get_latest_data(self) -> Dict[str, Any]:
        """Return the most recent readings from all sensors"""
        with self.data_lock:
            return self.latest_data.copy()

    def get_sensor_statuses(self) -> List[Dict[str, Any]]:
        """Return status for all registered sensors"""
        return [s.get_status() for s in self.sensors.values()]

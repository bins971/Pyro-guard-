"""
Concrete sensor implementations for PYRO-GUARD
"""
import random
from typing import Dict, Any
from datetime import datetime
from .base_sensor import HardwareSensor

class VirtualFireSensor(HardwareSensor):
    """
    Stochastic virtual sensor for testing on PC.
    Simulates temperature and smoke levels.
    """
    
    def __init__(self, sensor_id: str = "virtual_01", name: str = "PC Simulator"):
        super().__init__(sensor_id, name)
        self.current_state = {
            "temperature": 24.5,
            "smoke_analog": 150.0,
            "humidity": 50.0
        }
        
    def initialize(self) -> bool:
        print(f"Virtual sensor {self.name} initialized (Simulation mode)")
        return True
    
    def read(self) -> Dict[str, Any]:
        self.current_state["temperature"] += random.uniform(-0.1, 0.1)
        self.current_state["temperature"] = max(20.0, min(35.0, self.current_state["temperature"]))
        self.current_state["smoke_analog"] += random.uniform(-2.0, 2.0)
        self.current_state["smoke_analog"] = max(100.0, min(500.0, self.current_state["smoke_analog"]))
        
        # humidity
        self.current_state["humidity"] += random.uniform(-0.2, 0.2)
        self.current_state["humidity"] = max(30.0, min(70.0, self.current_state["humidity"]))

        self.last_value = {
            "temperature": round(self.current_state["temperature"], 2),
            "smoke_analog": int(self.current_state["smoke_analog"]),
            "humidity": round(self.current_state["humidity"], 2)
        }
        self.last_update = datetime.now()
        return self.last_value
    
    def cleanup(self):
        print(f"Virtual sensor {self.name} cleaned up")


class RPiGPYOSensor(HardwareSensor):
    """
    Placeholder for Raspberry Pi GPIO sensors (DHT/MQ).
    Will fail initialize on non-Pi hardware gracefully.
    """
    
    def __init__(self, sensor_id: str, name: str, pin: int):
        super().__init__(sensor_id, name)
        self.pin = pin
        
    def initialize(self) -> bool:
        try:
            import RPi.GPIO as GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.pin, GPIO.IN)
            print(f"RPi GPIO Sensor {self.name} initialized on pin {self.pin}")
            return True
        except (ImportError, RuntimeError):
            print(f"RPi GPIO Sensor {self.name} could not initialize (Not on RPi or missing library)")
            return False
            
    def read(self) -> Dict[str, Any]:
        return {"status": "hardware_disconnected"}
    
    def cleanup(self):
        try:
            import RPi.GPIO as GPIO
            GPIO.cleanup(self.pin)
        except:
            pass

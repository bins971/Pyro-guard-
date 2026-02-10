"""
Hardware sensor abstraction for PYRO-GUARD
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from datetime import datetime

class HardwareSensor(ABC):
    """
    Base class for all hardware sensors (Temperature, Gas, Smoke, etc.)
    """
    
    def __init__(self, sensor_id: str, name: str):
        self.sensor_id = sensor_id
        self.name = name
        self.is_active = False
        self.last_value = None
        self.last_update = None
        
    @abstractmethod
    def initialize(self) -> bool:
        """Initialize the hardware connection"""
        pass
    
    @abstractmethod
    def read(self) -> Dict[str, Any]:
        """Read data from the sensor"""
        pass
    
    @abstractmethod
    def cleanup(self):
        """Release hardware resources"""
        pass

    def get_status(self) -> Dict[str, Any]:
        """Return current sensor status and last reading"""
        return {
            "sensor_id": self.sensor_id,
            "name": self.name,
            "is_active": self.is_active,
            "last_value": self.last_value,
            "last_update": self.last_update.isoformat() if self.last_update else None
        }

from .sensor_manager import SensorManager
from .sensors import VirtualFireSensor, InfraredThermalSensor
from .gpio_controller import GPIOController

# Real hardware sensors (only functional on Raspberry Pi)
try:
    from .real_sensors import DHT22Sensor, MQ2SmokeSensor
    REAL_SENSORS_AVAILABLE = True
except ImportError:
    REAL_SENSORS_AVAILABLE = False

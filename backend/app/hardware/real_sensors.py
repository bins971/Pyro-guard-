from typing import Dict, Any
from datetime import datetime
import time
import logging
from .base_sensor import HardwareSensor

logger = logging.getLogger(__name__)


class DHT22Sensor(HardwareSensor):

    def __init__(self, sensor_id: str = "dht22_01", name: str = "Temperature & Humidity",
                 gpio_pin: int = 17):
        super().__init__(sensor_id, name)
        self.gpio_pin = gpio_pin
        self.device = None
        self.last_good_reading = {
            "temperature": 25.0,
            "humidity": 50.0,
            "smoke_analog": 0
        }

    def initialize(self) -> bool:
        try:
            # pyrefly: ignore 
            import adafruit_dht
            # pyrefly: ignore 
            import board

            pin_map = {
                4: board.D4,
                5: board.D5,
                6: board.D6,
                12: board.D12,
                13: board.D13,
                16: board.D16,
                17: board.D17,
                18: board.D18,
                19: board.D19,
                20: board.D20,
                21: board.D21,
                22: board.D22,
                23: board.D23,
                24: board.D24,
                25: board.D25,
                26: board.D26,
                27: board.D27,
            }

            board_pin = pin_map.get(self.gpio_pin)
            if board_pin is None:
                logger.error(f"Unsupported GPIO pin for DHT22: {self.gpio_pin}")
                return False

            self.device = adafruit_dht.DHT22(board_pin)
            logger.info(f"DHT22 sensor initialized on GPIO {self.gpio_pin}")
            return True

        except ImportError:
            logger.warning("adafruit_dht library not installed. Run: pip install adafruit-circuitpython-dht")
            return False
        except RuntimeError as e:
            logger.warning(f"DHT22 init failed (not on Pi?): {e}")
            return False
        except Exception as e:
            logger.error(f"DHT22 unexpected error: {e}")
            return False

    def read(self) -> Dict[str, Any]:
        if self.device is None:
            return self.last_good_reading

        from concurrent.futures import ThreadPoolExecutor, TimeoutError

        def _fetch_dht():
            try:
                t = self.device.temperature
                h = self.device.humidity
                return t, h
            except Exception:
                return None, None

        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_fetch_dht)
                temp, hum = future.result(timeout=0.8)

            if temp is not None and hum is not None:
                self.last_good_reading = {
                    "temperature": round(temp, 1),
                    "humidity": round(hum, 1),
                    "smoke_analog": 0
                }
                self.last_value = self.last_good_reading
                self.last_update = datetime.now()
        except TimeoutError:
            pass
        except Exception as e:
            logger.debug(f"DHT22 read note: {e}")

        return self.last_good_reading

    def cleanup(self):
        if self.device:
            try:
                self.device.exit()
            except Exception:
                pass
            logger.info("DHT22 sensor cleaned up")


class MQ2SmokeSensor(HardwareSensor):

    def __init__(self, sensor_id: str = "mq2_01", name: str = "Smoke Detector",
                 gpio_pin: int = 4, latch_seconds: float = 20.0):
        super().__init__(sensor_id, name)
        self.gpio_pin = gpio_pin
        self.latch_seconds = latch_seconds
        self.smoke_detected = False
        self._gpio_initialized = False
        self._last_smoke_time = 0.0

    def _on_smoke_edge(self, channel):
        self._last_smoke_time = time.time()
        logger.warning(f"MQ-2 hardware interrupt: Smoke edge detected on GPIO {self.gpio_pin}!")

    def initialize(self) -> bool:
        try:
            import RPi.GPIO as GPIO  
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.gpio_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            try:
                # Catch falling edge (transition from HIGH clear to LOW smoke)
                GPIO.add_event_detect(self.gpio_pin, GPIO.FALLING, callback=self._on_smoke_edge, bouncetime=200)
            except Exception as e:
                logger.debug(f"MQ-2 add_event_detect note: {e}")
            self._gpio_initialized = True
            logger.info(f"MQ-2 smoke sensor initialized on GPIO {self.gpio_pin}")
            return True
        except ImportError:
            logger.warning("RPi.GPIO not available. Run: pip install RPi.GPIO")
            return False
        except RuntimeError as e:
            logger.warning(f"MQ-2 init failed (not on Pi?): {e}")
            return False

    def read(self) -> Dict[str, Any]:
        if not self._gpio_initialized:
            return {"smoke_detected": False, "smoke_level": "UNAVAILABLE", "digital_raw": -1, "smoke_analog": 35}

        try:
            import RPi.GPIO as GPIO  
            digital_value = GPIO.input(self.gpio_pin)
            now = time.time()

            # Active low: 0 = smoke currently present
            if digital_value == 0:
                self._last_smoke_time = now

            # Check if smoke was detected right now OR latched within last latch_seconds
            time_since_smoke = now - self._last_smoke_time
            if time_since_smoke < self.latch_seconds:
                self.smoke_detected = True
                # Decay smoke_analog smoothly from 480 down to 200 over latch_seconds
                progress = time_since_smoke / self.latch_seconds  # 0.0 -> 1.0
                smoke_ppm = round(480 - (progress * 280))  # 480 down to 200
            else:
                self.smoke_detected = False
                smoke_ppm = 35

            self.last_value = {
                "smoke_detected": self.smoke_detected,
                "smoke_level": "SMOKE DETECTED" if self.smoke_detected else "CLEAR",
                "smoke_analog": smoke_ppm,
                "digital_raw": digital_value
            }
            self.last_update = datetime.now()
            return self.last_value

        except Exception as e:
            logger.error(f"MQ-2 read error: {e}")
            return {"smoke_detected": False, "smoke_level": "ERROR", "digital_raw": -1, "smoke_analog": 35}

    def cleanup(self):
        if self._gpio_initialized:
            try:
                import RPi.GPIO as GPIO 
                GPIO.cleanup(self.gpio_pin)
            except Exception:
                pass
        logger.info("MQ-2 sensor cleaned up")


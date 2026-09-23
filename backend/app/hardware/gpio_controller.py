
import logging
import threading
import time

logger = logging.getLogger(__name__)

# GPIO Pin Assignments
PIN_LED_RED = 22
PIN_LED_BLUE = 23
PIN_LED_GREEN = 24
PIN_BUZZER = 27

try:
    import RPi.GPIO as GPIO 
    GPIO_AVAILABLE = True
except (ImportError, RuntimeError):
    GPIO_AVAILABLE = False
    logger.info("RPi.GPIO not available — GPIO controller will run in simulation mode")


class GPIOController:
    def __init__(self):
        self.initialized = False
        self.current_level = 0
        self._blink_thread = None
        self._blink_running = False

    def initialize(self) -> bool:
        if not GPIO_AVAILABLE:
            logger.info("GPIO not available (not on Raspberry Pi) — indicators disabled")
            return False

        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)

            for pin in [PIN_LED_RED, PIN_LED_BLUE, PIN_LED_GREEN, PIN_BUZZER]:
                GPIO.setup(pin, GPIO.OUT)
                GPIO.output(pin, GPIO.LOW)

            self.initialized = True
            logger.info("GPIO Controller initialized — LEDs (Red=22, Blue=23, Green=24) and Buzzer=27 ready")
            return True
        except Exception as e:
            logger.error(f"GPIO initialization failed: {e}")
            return False

    def set_fire_level(self, level: int):
        if not self.initialized:
            return

        # Stop any existing blink thread
        self._stop_blink()

        self.current_level = level

        try:
            if level == 0:
                # ── Safe (No Fire): All LEDs OFF, Buzzer OFF ──
                GPIO.output(PIN_LED_GREEN, GPIO.LOW)
                GPIO.output(PIN_LED_BLUE, GPIO.LOW)
                GPIO.output(PIN_LED_RED, GPIO.LOW)
                GPIO.output(PIN_BUZZER, GPIO.LOW)

            elif level == 1:
                # ── Small Fire: GREEN LED ON + Buzzer ON ──
                GPIO.output(PIN_LED_GREEN, GPIO.HIGH)
                GPIO.output(PIN_LED_BLUE, GPIO.LOW)
                GPIO.output(PIN_LED_RED, GPIO.LOW)
                GPIO.output(PIN_BUZZER, GPIO.HIGH)

            elif level == 2:
                # ── Medium Fire: BLUE LED ON + Buzzer ON ──
                GPIO.output(PIN_LED_GREEN, GPIO.LOW)
                GPIO.output(PIN_LED_BLUE, GPIO.HIGH)
                GPIO.output(PIN_LED_RED, GPIO.LOW)
                GPIO.output(PIN_BUZZER, GPIO.HIGH)

            elif level >= 3:
                # ── Critical Fire: RED LED ON (blinking) + Buzzer ON ──
                GPIO.output(PIN_LED_GREEN, GPIO.LOW)
                GPIO.output(PIN_LED_BLUE, GPIO.LOW)
                GPIO.output(PIN_BUZZER, GPIO.HIGH)
                self._start_blink(PIN_LED_RED, interval=0.2)

            logger.info(f"GPIO indicators set to fire level {level}")
        except Exception as e:
            logger.error(f"GPIO set_fire_level error: {e}")

    def _start_blink(self, pin: int, interval: float = 0.5):
        self._blink_running = True
        self._blink_thread = threading.Thread(
            target=self._blink_loop, args=(pin, interval), daemon=True
        )
        self._blink_thread.start()

    def _blink_loop(self, pin: int, interval: float):
        state = True
        while self._blink_running:
            try:
                GPIO.output(pin, GPIO.HIGH if state else GPIO.LOW)
                state = not state
                time.sleep(interval)
            except Exception:
                break

    def _stop_blink(self):
        self._blink_running = False
        if self._blink_thread and self._blink_thread.is_alive():
            self._blink_thread.join(timeout=1)
        self._blink_thread = None

    def test_all(self):
        if not self.initialized:
            logger.warning("Cannot test GPIO — not initialized")
            return

        logger.info("Testing GPIO outputs...")
        for pin, name in [
            (PIN_LED_GREEN, "Green LED"),
            (PIN_LED_BLUE, "Blue LED"),
            (PIN_LED_RED, "Red LED"),
            (PIN_BUZZER, "Buzzer"),
        ]:
            logger.info(f"  Testing {name}...")
            GPIO.output(pin, GPIO.HIGH)
            time.sleep(0.5)
            GPIO.output(pin, GPIO.LOW)
            time.sleep(0.3)

        # Return to safe state (all off)
        for pin in [PIN_LED_GREEN, PIN_LED_BLUE, PIN_LED_RED, PIN_BUZZER]:
            GPIO.output(pin, GPIO.LOW)
        logger.info("GPIO test complete")

    def cleanup(self):
        self._stop_blink()
        if self.initialized and GPIO_AVAILABLE:
            try:
                GPIO.output(PIN_BUZZER, GPIO.LOW)
                GPIO.output(PIN_LED_RED, GPIO.LOW)
                GPIO.output(PIN_LED_BLUE, GPIO.LOW)
                GPIO.output(PIN_LED_GREEN, GPIO.LOW)
                GPIO.cleanup()
            except Exception:
                pass
            logger.info("GPIO cleaned up")
        self.initialized = False

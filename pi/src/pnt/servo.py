from __future__ import annotations

from time import sleep, time

try:
    import RPi.GPIO as GPIO
except ImportError:  # pragma: no cover
    GPIO = None


def angle_to_duty_cycle(angle_deg: float) -> float:
    angle_deg = max(0.0, min(180.0, angle_deg))
    return 3.0 if angle_deg <= 0.0 else 12.0 if angle_deg >= 180.0 else 3.0 + (angle_deg / 180.0) * 9.0


class ServoController:
    def __init__(
        self,
        gpio_pin: int = 11,
        min_seconds_between_flips: float = 0.5,
        pwm_hz: float = 50.0,
        gpio_mode: str = "BOARD",
    ) -> None:
        self._gpio_pin = gpio_pin
        self._min_seconds_between_flips = min_seconds_between_flips
        self._pwm_hz = pwm_hz
        self._gpio_mode = gpio_mode.upper()
        self._last_flip = 0.0
        self._position = "DOWN"
        self._pwm = None
        self._setup_pwm()
        self._set_angle(0.0)

    def flip_camera(self, direction: str | None = None) -> str:
        if direction is None:
            direction = "UP" if self._position == "DOWN" else "DOWN"
        direction = direction.upper()
        if direction not in {"UP", "DOWN"}:
            raise ValueError(f"unsupported direction: {direction}")
        if direction == self._position:
            return self._position

        now = time()
        if now - self._last_flip < self._min_seconds_between_flips:
            return self._position

        angle = 180.0 if direction == "UP" else 0.0
        self._set_angle(angle)
        self._position = direction
        self._last_flip = now
        return self._position

    def set_position(self, position: str) -> str:
        return self.flip_camera(position)

    def get_position(self) -> str:
        return self._position

    def cleanup(self) -> None:
        if self._pwm is not None:
            self._pwm.stop()
            self._pwm = None
        if GPIO is not None:
            GPIO.cleanup()

    def _setup_pwm(self) -> None:
        if GPIO is None:
            return
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BOARD if self._gpio_mode == "BOARD" else GPIO.BCM)
        GPIO.setup(self._gpio_pin, GPIO.OUT)
        self._pwm = GPIO.PWM(self._gpio_pin, self._pwm_hz)
        self._pwm.start(0)

    def _set_angle(self, angle_deg: float) -> None:
        if self._pwm is None:
            return
        self._pwm.ChangeDutyCycle(angle_to_duty_cycle(angle_deg))
        sleep(1.0)
        self._pwm.ChangeDutyCycle(0)

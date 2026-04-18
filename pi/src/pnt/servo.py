from __future__ import annotations

import time

try:
    import RPi.GPIO as GPIO
except ImportError:  # pragma: no cover
    GPIO = None


class ServoController:
    def __init__(
        self,
        min_seconds_between_flips: float = 3.0,
        gpio_pin: int = 2,
        pwm_hz: float = 50.0,
        up_angle_deg: float = 135.0,
        down_angle_deg: float = 45.0,
    ) -> None:
        self._position = "DOWN"
        self._last_flip = 0.0
        self._min_seconds_between_flips = min_seconds_between_flips
        self._gpio_pin = gpio_pin
        self._pwm_hz = pwm_hz
        self._up_angle_deg = up_angle_deg
        self._down_angle_deg = down_angle_deg
        self._pwm = None
        self._gpio_ready = False
        self._setup_gpio()

    def flip_camera(self, direction: str) -> bool:
        direction = direction.upper()
        now = time.time()
        if direction not in {"UP", "DOWN"}:
            raise ValueError(f"unsupported direction: {direction}")
        if direction == self._position:
            return True
        if now - self._last_flip < self._min_seconds_between_flips:
            return False
        angle = self._up_angle_deg if direction == "UP" else self._down_angle_deg
        self._set_angle(angle)
        self._position = direction
        self._last_flip = now
        time.sleep(0.5)
        return True

    def sweep(self, cycles: int = 3, dwell_s: float = 1.0) -> None:
        for _ in range(max(0, cycles)):
            self._set_angle(self._down_angle_deg)
            self._position = "DOWN"
            time.sleep(dwell_s)
            self._set_angle(self._up_angle_deg)
            self._position = "UP"
            time.sleep(dwell_s)

    def center(self) -> None:
        self._set_angle((self._up_angle_deg + self._down_angle_deg) / 2.0)

    def get_position(self) -> str:
        return self._position

    def cleanup(self) -> None:
        if self._pwm is not None:
            self._pwm.stop()
            self._pwm = None
        if self._gpio_ready and GPIO is not None:
            GPIO.cleanup(self._gpio_pin)
            self._gpio_ready = False

    def _setup_gpio(self) -> None:
        if GPIO is None:
            return
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self._gpio_pin, GPIO.OUT)
        self._pwm = GPIO.PWM(self._gpio_pin, self._pwm_hz)
        self._pwm.start(0.0)
        self._gpio_ready = True

    def _set_angle(self, angle_deg: float) -> None:
        angle_deg = max(0.0, min(180.0, angle_deg))
        duty_cycle = self._angle_to_duty_cycle(angle_deg)
        if self._pwm is None:
            return
        self._pwm.ChangeDutyCycle(duty_cycle)
        time.sleep(0.35)
        self._pwm.ChangeDutyCycle(0.0)

    @staticmethod
    def _angle_to_duty_cycle(angle_deg: float) -> float:
        # 2.5% to 12.5% duty is a common 0-180 degree mapping for 50 Hz hobby servos.
        return 2.5 + (angle_deg / 180.0) * 10.0


def main() -> None:
    servo = ServoController(gpio_pin=2, min_seconds_between_flips=0.0)
    try:
        servo.sweep(cycles=5, dwell_s=1.0)
    finally:
        servo.cleanup()


if __name__ == "__main__":
    main()

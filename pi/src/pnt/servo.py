from __future__ import annotations

from time import sleep, time

import RPi.GPIO as GPIO


class ServoController:
    def __init__(
        self,
        gpio_pin: int = 11,
        min_seconds_between_flips: float = 0.5,
        pwm_hz: float = 50.0,
    ) -> None:
        self._gpio_pin = gpio_pin
        self._min_seconds_between_flips = min_seconds_between_flips
        self._pwm_hz = pwm_hz
        self._last_flip = 0.0
        self._position = "DOWN"

        GPIO.setmode(GPIO.BOARD)
        GPIO.setup(self._gpio_pin, GPIO.OUT)
        self._pwm = GPIO.PWM(self._gpio_pin, self._pwm_hz)
        self._pwm.start(0)
        self._set_angle(0)

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

        angle = 180 if direction == "UP" else 0
        self._set_angle(angle)
        self._position = direction
        self._last_flip = now
        return self._position

    def get_position(self) -> str:
        return self._position

    def cleanup(self) -> None:
        self._pwm.stop()
        GPIO.cleanup()

    def _set_angle(self, angle: int) -> None:
        duty_cycle = 3 if angle == 0 else 12
        self._pwm.ChangeDutyCycle(duty_cycle)
        sleep(1)
        self._pwm.ChangeDutyCycle(0)


def main() -> None:
    servo = ServoController()
    try:
        while True:
            print(servo.flip_camera())
            sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        servo.cleanup()


if __name__ == "__main__":
    main()

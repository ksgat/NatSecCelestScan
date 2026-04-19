from __future__ import annotations

import argparse
import sys
from pathlib import Path
from time import sleep

SRC_ROOT = Path(__file__).resolve().parents[1]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pnt.servo import ServoController


def main() -> None:
    parser = argparse.ArgumentParser(description="Flip the servo back and forth for hardware debugging.")
    parser.add_argument("--pin", type=int, default=11)
    parser.add_argument("--mode", default="BOARD", choices=["BOARD", "BCM"])
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()

    servo = ServoController(gpio_pin=args.pin, gpio_mode=args.mode, min_seconds_between_flips=0.0)
    try:
        while True:
            print(servo.flip_camera())
            sleep(args.delay)
    except KeyboardInterrupt:
        pass
    finally:
        servo.cleanup()


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pnt.imu import ImuInterface


def main() -> None:
    parser = argparse.ArgumentParser(description="MPU-6050 debug reader with filtering and calibration.")
    parser.add_argument("--sample-hz", type=float, default=100.0)
    parser.add_argument("--recalibrate", action="store_true")
    parser.add_argument("--print-calibration", action="store_true")
    args = parser.parse_args()

    try:
        imu = ImuInterface(sample_hz=args.sample_hz, auto_calibrate=not args.recalibrate)
    except Exception as exc:
        print(f"MPU-6050 init failed on I2C bus 1 at 0x68: {type(exc).__name__}: {exc}")
        return

    if args.recalibrate:
        print("Calibrating IMU. Keep the sensor still.")
        calibration = imu.calibrate()
    else:
        calibration = imu.get_calibration()

    print("MPU-6050 detected on I2C bus 1 at 0x68")
    if args.print_calibration or args.recalibrate:
        print(
            "gyro_bias_dps="
            f"({calibration.gyro_bias_dps[0]:.4f}, {calibration.gyro_bias_dps[1]:.4f}, {calibration.gyro_bias_dps[2]:.4f}) "
            f"accel_norm_g={calibration.accel_norm_g:.4f} "
            f"gyro_stddev_dps=({calibration.gyro_stddev_dps[0]:.4f}, {calibration.gyro_stddev_dps[1]:.4f}, {calibration.gyro_stddev_dps[2]:.4f})"
        )

    try:
        while True:
            reading = imu.read_once()
            attitude = imu.get_attitude()
            print(
                f"ax={reading.ax:.3f}g ay={reading.ay:.3f}g az={reading.az:.3f}g "
                f"gx={reading.gx:.3f}dps gy={reading.gy:.3f}dps gz={reading.gz:.3f}dps "
                f"temp={reading.temp:.2f}C "
                f"roll={attitude.roll:.2f}deg pitch={attitude.pitch:.2f}deg yaw={attitude.yaw:.2f}deg "
                f"stationary={imu.is_stationary()}"
            )
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        imu.stop()


if __name__ == "__main__":
    main()

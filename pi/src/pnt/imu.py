from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass

from smbus2 import SMBus

try:
    from .models import Attitude, ImuReading
except ImportError:
    @dataclass
    class ImuReading:
        ax: float = 0.0
        ay: float = 0.0
        az: float = 0.0
        gx: float = 0.0
        gy: float = 0.0
        gz: float = 0.0
        temp: float = 0.0
        timestamp: float = 0.0

    @dataclass
    class Attitude:
        roll: float = 0.0
        pitch: float = 0.0
        yaw: float = 0.0


class ImuInterface:
    MPU_ADDR = 0x68
    PWR_MGMT_1 = 0x6B
    ACCEL_XOUT_H = 0x3B
    TEMP_OUT_H = 0x41
    GYRO_XOUT_H = 0x43

    def __init__(self, bus_id: int = 1, sample_hz: float = 20.0) -> None:
        self._bus_id = bus_id
        self._sample_hz = sample_hz
        self._bus = SMBus(self._bus_id)
        self._reading = ImuReading(timestamp=time.time())
        self._attitude = Attitude()
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._wake_sensor()

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
        self._bus.close()

    def _run(self) -> None:
        period = 1.0 / self._sample_hz
        while self._running:
            reading = self._read_sensor()
            with self._lock:
                self._reading = reading
            time.sleep(period)

    def get_reading(self) -> ImuReading:
        with self._lock:
            return ImuReading(**self._reading.__dict__)

    def get_attitude(self) -> Attitude:
        with self._lock:
            return Attitude(**self._attitude.__dict__)

    def _wake_sensor(self) -> None:
        self._bus.write_byte_data(self.MPU_ADDR, self.PWR_MGMT_1, 0)
        time.sleep(0.1)

    def _read_sensor(self) -> ImuReading:
        accel_x = self._read_word_2c(self.ACCEL_XOUT_H) / 16384.0
        accel_y = self._read_word_2c(self.ACCEL_XOUT_H + 2) / 16384.0
        accel_z = self._read_word_2c(self.ACCEL_XOUT_H + 4) / 16384.0
        temp_raw = self._read_word_2c(self.TEMP_OUT_H)
        gyro_x = self._read_word_2c(self.GYRO_XOUT_H) / 131.0
        gyro_y = self._read_word_2c(self.GYRO_XOUT_H + 2) / 131.0
        gyro_z = self._read_word_2c(self.GYRO_XOUT_H + 4) / 131.0
        temp_c = (temp_raw / 340.0) + 36.53
        roll, pitch = self._estimate_roll_pitch(accel_x, accel_y, accel_z)
        with self._lock:
            self._attitude = Attitude(roll=roll, pitch=pitch, yaw=self._attitude.yaw)
        return ImuReading(
            ax=accel_x,
            ay=accel_y,
            az=accel_z,
            gx=gyro_x,
            gy=gyro_y,
            gz=gyro_z,
            temp=temp_c,
            timestamp=time.time(),
        )

    @staticmethod
    def _estimate_roll_pitch(ax: float, ay: float, az: float) -> tuple[float, float]:
        roll = math.degrees(math.atan2(ay, az))
        pitch = math.degrees(math.atan2(-ax, math.sqrt((ay * ay) + (az * az))))
        return roll, pitch

    def _read_word_2c(self, register: int) -> int:
        high = self._bus.read_byte_data(self.MPU_ADDR, register)
        low = self._bus.read_byte_data(self.MPU_ADDR, register + 1)
        value = (high << 8) + low
        if value >= 0x8000:
            return -((65535 - value) + 1)
        return value


def main() -> None:
    try:
        imu = ImuInterface()
    except Exception as exc:
        print(f"MPU-6050 init failed on I2C bus 1 at 0x68: {type(exc).__name__}: {exc}")
        return

    print("MPU-6050 detected on I2C bus 1 at 0x68")
    try:
        while True:
            reading = imu._read_sensor()
            attitude = imu.get_attitude()
            print(
                f"ax={reading.ax:.3f}g ay={reading.ay:.3f}g az={reading.az:.3f}g "
                f"gx={reading.gx:.3f}dps gy={reading.gy:.3f}dps gz={reading.gz:.3f}dps "
                f"temp={reading.temp:.2f}C "
                f"roll={attitude.roll:.2f}deg pitch={attitude.pitch:.2f}deg"
            )
            time.sleep(0.25)
    except KeyboardInterrupt:
        pass
    finally:
        imu.stop()


if __name__ == "__main__":
    main()

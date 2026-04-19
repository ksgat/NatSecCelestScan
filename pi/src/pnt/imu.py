from __future__ import annotations

import json
import math
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

try:
    from smbus2 import SMBus
except ImportError:  # pragma: no cover
    SMBus = None

try:
    from ahrs.filters import Mahony as MahonyFilter
except ImportError:  # pragma: no cover
    MahonyFilter = None

from .models import Attitude, ImuReading


MPU6050_ADDR = 0x68
SMPLRT_DIV = 0x19
CONFIG = 0x1A
GYRO_CONFIG = 0x1B
ACCEL_CONFIG = 0x1C
INT_ENABLE = 0x38
ACCEL_XOUT_H = 0x3B
TEMP_OUT_H = 0x41
GYRO_XOUT_H = 0x43
PWR_MGMT_1 = 0x6B
WHO_AM_I = 0x75

DEFAULT_SAMPLE_HZ = 100.0
DEFAULT_ACCEL_RANGE_G = 4
DEFAULT_GYRO_RANGE_DPS = 500
DEFAULT_DLPF_CFG = 3
DEFAULT_ACCEL_FILTER_TIME_CONSTANT_S = 0.25
DEFAULT_GYRO_BIAS_ADAPT_RATE = 0.01
DEFAULT_STATIONARY_GYRO_THRESHOLD_DPS = 1.5
DEFAULT_STATIONARY_ACCEL_TOLERANCE_G = 0.08
DEFAULT_CALIBRATION_SAMPLES = 400
DEFAULT_MAHONY_KP = 0.8
DEFAULT_MAHONY_KI = 0.1
GRAVITY_MPS2 = 9.80665

ACCEL_RANGE_BITS = {2: 0, 4: 1, 8: 2, 16: 3}
GYRO_RANGE_BITS = {250: 0, 500: 1, 1000: 2, 2000: 3}
ACCEL_LSB_PER_G = {2: 16384.0, 4: 8192.0, 8: 4096.0, 16: 2048.0}
GYRO_LSB_PER_DPS = {250: 131.0, 500: 65.5, 1000: 32.8, 2000: 16.4}


@dataclass
class ImuCalibration:
    gyro_bias_dps: tuple[float, float, float] = (0.0, 0.0, 0.0)
    accel_norm_g: float = 1.0
    sample_count: int = 0
    gyro_stddev_dps: tuple[float, float, float] = (0.0, 0.0, 0.0)
    calibrated_at: float = 0.0


@dataclass
class ImuSettings:
    bus_id: int = 1
    address: int = MPU6050_ADDR
    sample_hz: float = DEFAULT_SAMPLE_HZ
    accel_range_g: int = DEFAULT_ACCEL_RANGE_G
    gyro_range_dps: int = DEFAULT_GYRO_RANGE_DPS
    dlpf_cfg: int = DEFAULT_DLPF_CFG
    mahony_kp: float = DEFAULT_MAHONY_KP
    mahony_ki: float = DEFAULT_MAHONY_KI
    accel_filter_time_constant_s: float = DEFAULT_ACCEL_FILTER_TIME_CONSTANT_S
    gyro_bias_adapt_rate: float = DEFAULT_GYRO_BIAS_ADAPT_RATE
    stationary_gyro_threshold_dps: float = DEFAULT_STATIONARY_GYRO_THRESHOLD_DPS
    stationary_accel_tolerance_g: float = DEFAULT_STATIONARY_ACCEL_TOLERANCE_G
    calibration_samples: int = DEFAULT_CALIBRATION_SAMPLES
    calibration_path: Path | None = None


def default_calibration_path() -> Path:
    return Path(__file__).resolve().parents[1] / "assets" / "calibration" / "imu_cal.json"


def open_imu(bus_id: int = 1, address: int = MPU6050_ADDR, *, accel_range_g: int = DEFAULT_ACCEL_RANGE_G, gyro_range_dps: int = DEFAULT_GYRO_RANGE_DPS, dlpf_cfg: int = DEFAULT_DLPF_CFG, sample_hz: float = DEFAULT_SAMPLE_HZ) -> SMBus:
    if SMBus is None:
        raise RuntimeError("smbus2 is not installed")
    bus = SMBus(bus_id)
    configure_imu(
        bus,
        address=address,
        accel_range_g=accel_range_g,
        gyro_range_dps=gyro_range_dps,
        dlpf_cfg=dlpf_cfg,
        sample_hz=sample_hz,
    )
    return bus


def close_imu(bus: SMBus) -> None:
    bus.close()


def configure_imu(bus: SMBus, *, address: int = MPU6050_ADDR, accel_range_g: int = DEFAULT_ACCEL_RANGE_G, gyro_range_dps: int = DEFAULT_GYRO_RANGE_DPS, dlpf_cfg: int = DEFAULT_DLPF_CFG, sample_hz: float = DEFAULT_SAMPLE_HZ) -> None:
    if accel_range_g not in ACCEL_RANGE_BITS:
        raise ValueError(f"unsupported accel range: {accel_range_g}")
    if gyro_range_dps not in GYRO_RANGE_BITS:
        raise ValueError(f"unsupported gyro range: {gyro_range_dps}")

    whoami = bus.read_byte_data(address, WHO_AM_I)
    if whoami not in {0x68, 0x69}:
        raise RuntimeError(f"unexpected MPU-6050 WHO_AM_I value: 0x{whoami:02X}")

    bus.write_byte_data(address, PWR_MGMT_1, 0x01)
    time.sleep(0.1)
    bus.write_byte_data(address, CONFIG, dlpf_cfg & 0x07)
    divider = max(0, min(255, int(round((1000.0 / max(sample_hz, 1.0)) - 1.0))))
    bus.write_byte_data(address, SMPLRT_DIV, divider)
    bus.write_byte_data(address, GYRO_CONFIG, GYRO_RANGE_BITS[gyro_range_dps] << 3)
    bus.write_byte_data(address, ACCEL_CONFIG, ACCEL_RANGE_BITS[accel_range_g] << 3)
    bus.write_byte_data(address, INT_ENABLE, 0x00)
    time.sleep(0.05)


def load_calibration(path: str | Path | None = None) -> ImuCalibration | None:
    target = Path(path) if path else default_calibration_path()
    if not target.exists():
        return None
    payload = json.loads(target.read_text(encoding="utf-8"))
    return ImuCalibration(
        gyro_bias_dps=tuple(float(v) for v in payload.get("gyro_bias_dps", (0.0, 0.0, 0.0))),
        accel_norm_g=float(payload.get("accel_norm_g", 1.0)),
        sample_count=int(payload.get("sample_count", 0)),
        gyro_stddev_dps=tuple(float(v) for v in payload.get("gyro_stddev_dps", (0.0, 0.0, 0.0))),
        calibrated_at=float(payload.get("calibrated_at", 0.0)),
    )


def save_calibration(calibration: ImuCalibration, path: str | Path | None = None) -> Path:
    target = Path(path) if path else default_calibration_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(asdict(calibration), indent=2), encoding="utf-8")
    return target


def read_word_2c(high: int, low: int) -> int:
    value = (high << 8) | low
    if value >= 0x8000:
        return value - 0x10000
    return value


def read_raw_sample(bus: SMBus, address: int = MPU6050_ADDR) -> tuple[tuple[int, int, int], int, tuple[int, int, int], float]:
    block = bus.read_i2c_block_data(address, ACCEL_XOUT_H, 14)
    accel = (
        read_word_2c(block[0], block[1]),
        read_word_2c(block[2], block[3]),
        read_word_2c(block[4], block[5]),
    )
    temp_raw = read_word_2c(block[6], block[7])
    gyro = (
        read_word_2c(block[8], block[9]),
        read_word_2c(block[10], block[11]),
        read_word_2c(block[12], block[13]),
    )
    return accel, temp_raw, gyro, time.time()


def estimate_roll_pitch(ax_g: float, ay_g: float, az_g: float) -> tuple[float, float]:
    roll = math.degrees(math.atan2(ay_g, az_g))
    pitch = math.degrees(math.atan2(-ax_g, math.sqrt((ay_g * ay_g) + (az_g * az_g))))
    return roll, pitch


def attitude_to_quaternion(roll_deg: float, pitch_deg: float, yaw_deg: float = 0.0):
    roll = math.radians(roll_deg) * 0.5
    pitch = math.radians(pitch_deg) * 0.5
    yaw = math.radians(yaw_deg) * 0.5

    cr = math.cos(roll)
    sr = math.sin(roll)
    cp = math.cos(pitch)
    sp = math.sin(pitch)
    cy = math.cos(yaw)
    sy = math.sin(yaw)

    return np.array(
        [
            (cr * cp * cy) + (sr * sp * sy),
            (sr * cp * cy) - (cr * sp * sy),
            (cr * sp * cy) + (sr * cp * sy),
            (cr * cp * sy) - (sr * sp * cy),
        ],
        dtype=float,
    )


def quaternion_to_attitude(q) -> Attitude:
    w, x, y, z = q

    sinr_cosp = 2.0 * ((w * x) + (y * z))
    cosr_cosp = 1.0 - 2.0 * ((x * x) + (y * y))
    roll = math.degrees(math.atan2(sinr_cosp, cosr_cosp))

    sinp = 2.0 * ((w * y) - (z * x))
    if abs(sinp) >= 1.0:
        pitch = math.degrees(math.copysign(math.pi / 2.0, sinp))
    else:
        pitch = math.degrees(math.asin(sinp))

    siny_cosp = 2.0 * ((w * z) + (x * y))
    cosy_cosp = 1.0 - 2.0 * ((y * y) + (z * z))
    yaw = math.degrees(math.atan2(siny_cosp, cosy_cosp))

    return Attitude(roll=roll, pitch=pitch, yaw=yaw)


def low_pass_scalar(previous: float | None, current: float, dt_s: float, time_constant_s: float) -> float:
    if previous is None or time_constant_s <= 0.0:
        return current
    alpha = dt_s / (time_constant_s + dt_s)
    return previous + alpha * (current - previous)


def low_pass_vector(previous: tuple[float, float, float] | None, current: tuple[float, float, float], dt_s: float, time_constant_s: float) -> tuple[float, float, float]:
    if previous is None:
        return current
    return (
        low_pass_scalar(previous[0], current[0], dt_s, time_constant_s),
        low_pass_scalar(previous[1], current[1], dt_s, time_constant_s),
        low_pass_scalar(previous[2], current[2], dt_s, time_constant_s),
    )


def is_stationary(*, accel_norm_g: float, gyro_dps: tuple[float, float, float], reference_norm_g: float, gyro_threshold_dps: float, accel_tolerance_g: float) -> bool:
    gyro_mag = math.sqrt(sum(axis * axis for axis in gyro_dps))
    return gyro_mag <= gyro_threshold_dps and abs(accel_norm_g - reference_norm_g) <= accel_tolerance_g


def calibrate_imu(bus: SMBus, *, address: int = MPU6050_ADDR, accel_range_g: int = DEFAULT_ACCEL_RANGE_G, gyro_range_dps: int = DEFAULT_GYRO_RANGE_DPS, samples: int = DEFAULT_CALIBRATION_SAMPLES, sample_delay_s: float = 0.005) -> ImuCalibration:
    gyro_scale = GYRO_LSB_PER_DPS[gyro_range_dps]
    accel_scale = ACCEL_LSB_PER_G[accel_range_g]

    gyro_sums = [0.0, 0.0, 0.0]
    gyro_sq_sums = [0.0, 0.0, 0.0]
    accel_norm_sum = 0.0

    for _ in range(max(1, samples)):
        accel_raw, _, gyro_raw, _ = read_raw_sample(bus, address)
        gyro_dps = tuple(value / gyro_scale for value in gyro_raw)
        accel_g = tuple(value / accel_scale for value in accel_raw)
        accel_norm = math.sqrt(sum(axis * axis for axis in accel_g))
        for index, value in enumerate(gyro_dps):
            gyro_sums[index] += value
            gyro_sq_sums[index] += value * value
        accel_norm_sum += accel_norm
        time.sleep(sample_delay_s)

    count = float(max(1, samples))
    gyro_bias = tuple(total / count for total in gyro_sums)
    gyro_stddev = []
    for total, total_sq in zip(gyro_sums, gyro_sq_sums):
        mean = total / count
        variance = max(0.0, (total_sq / count) - (mean * mean))
        gyro_stddev.append(math.sqrt(variance))

    return ImuCalibration(
        gyro_bias_dps=gyro_bias,
        accel_norm_g=accel_norm_sum / count,
        sample_count=int(count),
        gyro_stddev_dps=tuple(gyro_stddev),
        calibrated_at=time.time(),
    )


def decode_imu_sample(*, accel_raw: tuple[int, int, int], temp_raw: int, gyro_raw: tuple[int, int, int], timestamp: float, accel_range_g: int, gyro_range_dps: int, calibration: ImuCalibration) -> tuple[ImuReading, tuple[float, float, float], tuple[float, float, float]]:
    accel_scale = ACCEL_LSB_PER_G[accel_range_g]
    gyro_scale = GYRO_LSB_PER_DPS[gyro_range_dps]

    accel_g = tuple(value / accel_scale for value in accel_raw)
    corrected_gyro = tuple((value / gyro_scale) - bias for value, bias in zip(gyro_raw, calibration.gyro_bias_dps))
    reading = ImuReading(
        ax=accel_g[0],
        ay=accel_g[1],
        az=accel_g[2],
        gx=corrected_gyro[0],
        gy=corrected_gyro[1],
        gz=corrected_gyro[2],
        temp=(temp_raw / 340.0) + 36.53,
        timestamp=timestamp,
    )
    raw_gyro_dps = tuple(value / gyro_scale for value in gyro_raw)
    return reading, accel_g, raw_gyro_dps


class ImuInterface:
    def __init__(
        self,
        *,
        bus_id: int = 1,
        address: int = MPU6050_ADDR,
        sample_hz: float = DEFAULT_SAMPLE_HZ,
        accel_range_g: int = DEFAULT_ACCEL_RANGE_G,
        gyro_range_dps: int = DEFAULT_GYRO_RANGE_DPS,
        dlpf_cfg: int = DEFAULT_DLPF_CFG,
        mahony_kp: float = DEFAULT_MAHONY_KP,
        mahony_ki: float = DEFAULT_MAHONY_KI,
        accel_filter_time_constant_s: float = DEFAULT_ACCEL_FILTER_TIME_CONSTANT_S,
        gyro_bias_adapt_rate: float = DEFAULT_GYRO_BIAS_ADAPT_RATE,
        stationary_gyro_threshold_dps: float = DEFAULT_STATIONARY_GYRO_THRESHOLD_DPS,
        stationary_accel_tolerance_g: float = DEFAULT_STATIONARY_ACCEL_TOLERANCE_G,
        calibration_samples: int = DEFAULT_CALIBRATION_SAMPLES,
        calibration_path: str | Path | None = None,
        auto_calibrate: bool = True,
    ) -> None:
        if np is None:
            raise RuntimeError("numpy is not installed")
        if MahonyFilter is None:
            raise RuntimeError("ahrs is not installed")
        self._settings = ImuSettings(
            bus_id=bus_id,
            address=address,
            sample_hz=sample_hz,
            accel_range_g=accel_range_g,
            gyro_range_dps=gyro_range_dps,
            dlpf_cfg=dlpf_cfg,
            mahony_kp=mahony_kp,
            mahony_ki=mahony_ki,
            accel_filter_time_constant_s=accel_filter_time_constant_s,
            gyro_bias_adapt_rate=gyro_bias_adapt_rate,
            stationary_gyro_threshold_dps=stationary_gyro_threshold_dps,
            stationary_accel_tolerance_g=stationary_accel_tolerance_g,
            calibration_samples=calibration_samples,
            calibration_path=Path(calibration_path) if calibration_path else default_calibration_path(),
        )
        self._bus = open_imu(
            bus_id=bus_id,
            address=address,
            accel_range_g=accel_range_g,
            gyro_range_dps=gyro_range_dps,
            dlpf_cfg=dlpf_cfg,
            sample_hz=sample_hz,
        )
        self._calibration = load_calibration(self._settings.calibration_path)
        if auto_calibrate and self._calibration is None:
            self._calibration = self.calibrate()
        if self._calibration is None:
            self._calibration = ImuCalibration()

        self._reading = ImuReading(timestamp=time.time())
        self._attitude = Attitude()
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._last_timestamp: float | None = None
        self._filtered_accel_g: tuple[float, float, float] | None = None
        self._last_stationary = False
        self._quaternion = np.array([1.0, 0.0, 0.0, 0.0], dtype=float)
        self._mahony = MahonyFilter(
            frequency=sample_hz,
            k_P=mahony_kp,
            k_I=mahony_ki,
            q0=self._quaternion.copy(),
        )

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
        save_calibration(self._calibration, self._settings.calibration_path)
        close_imu(self._bus)

    def calibrate(self, samples: int | None = None) -> ImuCalibration:
        calibration = calibrate_imu(
            self._bus,
            address=self._settings.address,
            accel_range_g=self._settings.accel_range_g,
            gyro_range_dps=self._settings.gyro_range_dps,
            samples=samples or self._settings.calibration_samples,
        )
        self._calibration = calibration
        self._last_timestamp = None
        self._filtered_accel_g = None
        self._quaternion = np.array([1.0, 0.0, 0.0, 0.0], dtype=float)
        self._mahony = MahonyFilter(
            frequency=self._settings.sample_hz,
            k_P=self._settings.mahony_kp,
            k_I=self._settings.mahony_ki,
            q0=self._quaternion.copy(),
        )
        save_calibration(self._calibration, self._settings.calibration_path)
        return calibration

    def get_calibration(self) -> ImuCalibration:
        with self._lock:
            return ImuCalibration(
                gyro_bias_dps=tuple(self._calibration.gyro_bias_dps),
                accel_norm_g=self._calibration.accel_norm_g,
                sample_count=self._calibration.sample_count,
                gyro_stddev_dps=tuple(self._calibration.gyro_stddev_dps),
                calibrated_at=self._calibration.calibrated_at,
            )

    def get_reading(self) -> ImuReading:
        with self._lock:
            return ImuReading(**self._reading.__dict__)

    def get_attitude(self) -> Attitude:
        with self._lock:
            return Attitude(**self._attitude.__dict__)

    def read_once(self) -> ImuReading:
        accel_raw, temp_raw, gyro_raw, timestamp = read_raw_sample(self._bus, self._settings.address)
        reading, accel_g, raw_gyro_dps = decode_imu_sample(
            accel_raw=accel_raw,
            temp_raw=temp_raw,
            gyro_raw=gyro_raw,
            timestamp=timestamp,
            accel_range_g=self._settings.accel_range_g,
            gyro_range_dps=self._settings.gyro_range_dps,
            calibration=self._calibration,
        )

        first_sample = self._last_timestamp is None
        dt_s = 1.0 / self._settings.sample_hz if first_sample else max(1e-3, timestamp - self._last_timestamp)
        self._last_timestamp = timestamp

        self._filtered_accel_g = low_pass_vector(
            self._filtered_accel_g,
            accel_g,
            dt_s,
            self._settings.accel_filter_time_constant_s,
        )

        filtered_accel = self._filtered_accel_g
        accel_norm = math.sqrt(sum(axis * axis for axis in filtered_accel))

        if not np.isfinite(accel_norm) or accel_norm < 1e-6:
            filtered_accel = accel_g
            accel_norm = math.sqrt(sum(axis * axis for axis in filtered_accel))

        if first_sample:
            roll, pitch = estimate_roll_pitch(*filtered_accel)
            self._quaternion = attitude_to_quaternion(roll, pitch)
        else:
            gyro_rad_s = np.deg2rad(np.array([reading.gx, reading.gy, reading.gz], dtype=float))
            acc_mps2 = np.array(filtered_accel, dtype=float) * GRAVITY_MPS2
            self._mahony.Dt = dt_s
            self._quaternion = self._mahony.updateIMU(self._quaternion, gyr=gyro_rad_s, acc=acc_mps2, dt=dt_s)

        attitude = quaternion_to_attitude(self._quaternion)

        stationary = is_stationary(
            accel_norm_g=accel_norm,
            gyro_dps=(reading.gx, reading.gy, reading.gz),
            reference_norm_g=self._calibration.accel_norm_g,
            gyro_threshold_dps=self._settings.stationary_gyro_threshold_dps,
            accel_tolerance_g=self._settings.stationary_accel_tolerance_g,
        )
        self._last_stationary = stationary
        if stationary:
            self._adapt_gyro_bias(raw_gyro_dps)

        with self._lock:
            self._reading = reading
            self._attitude = attitude
        return reading

    def is_stationary(self) -> bool:
        return self._last_stationary

    def _adapt_gyro_bias(self, raw_gyro_dps: tuple[float, float, float]) -> None:
        rate = self._settings.gyro_bias_adapt_rate
        updated = []
        for bias, raw in zip(self._calibration.gyro_bias_dps, raw_gyro_dps):
            updated.append(bias + rate * (raw - bias))
        self._calibration.gyro_bias_dps = tuple(updated)

    def _run(self) -> None:
        period = 1.0 / self._settings.sample_hz
        while self._running:
            start = time.time()
            self.read_once()
            remaining = period - (time.time() - start)
            if remaining > 0:
                time.sleep(remaining)

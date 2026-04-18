# TODO

## Session Summary

This session converted the repo from a single rough `spec.md` into a self-contained project scaffold with vendored `tetra3`, asset storage, a generated wide-FOV plate-solving database, and initial navigation-module code.

## What Was Done

### Spec rewrite

- Rewrote the navigation spec into a UAV-oriented design in [pi/src/spec.md](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/spec.md).
- Changed the architecture so:
  - stereo visual odometry is the primary relative-motion source
  - ground-to-map matching is the primary absolute correction path
  - IMU is for propagation / stabilization
  - night star solving is a bounded-area fallback for featureless-ground conditions
- Removed the earlier overclaim that celestial should be the primary full `lat/lon` solution.

### Project scaffold

Added the main package structure under `pi/src`:

- `pnt/`
- `edge/`
- `comms/`
- `tetra3/`
- `assets/`
- `scripts/`

### Navigation code scaffold

Implemented first-pass modules:

- [pi/src/pnt/main.py](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/pnt/main.py)
- [pi/src/pnt/models.py](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/pnt/models.py)
- [pi/src/pnt/config.py](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/pnt/config.py)
- [pi/src/pnt/servo.py](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/pnt/servo.py)
- [pi/src/pnt/imu.py](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/pnt/imu.py)
- [pi/src/pnt/sky_assessor.py](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/pnt/sky_assessor.py)
- [pi/src/pnt/visual_odometry.py](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/pnt/visual_odometry.py)
- [pi/src/pnt/geo_match.py](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/pnt/geo_match.py)
- [pi/src/pnt/map_manager.py](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/pnt/map_manager.py)
- [pi/src/pnt/celestial_locator.py](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/pnt/celestial_locator.py)
- [pi/src/pnt/confidence.py](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/pnt/confidence.py)
- [pi/src/pnt/nmea_output.py](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/pnt/nmea_output.py)
- [pi/src/pnt/celestial/star_solver.py](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/pnt/celestial/star_solver.py)
- [pi/src/pnt/celestial/sun_solver.py](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/pnt/celestial/sun_solver.py)
- [pi/src/pnt/stereo/stereo_depth.py](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/pnt/stereo/stereo_depth.py)
- [pi/src/pnt/stereo/calibration.py](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/pnt/stereo/calibration.py)
- [pi/src/edge/terrain_classifier.py](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/edge/terrain_classifier.py)
- [pi/src/edge/benchmark.py](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/edge/benchmark.py)
- [pi/src/comms/udp_tx.py](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/comms/udp_tx.py)

### What those modules currently are

- The package wiring is real.
- The code compiles and imports.
- `NavigationSystem.tick()` runs end to end with synthetic frames.
- NMEA formatting and UDP transmit interfaces are present.
- Most navigation math is still placeholder / scaffold logic.

### Star solving and tetra3

- Added asset config for star solving in [pi/src/assets/config/star_solver.json](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/assets/config/star_solver.json).
- Backed up the bundled tetra3 `default_database.npz` in [pi/src/assets/tetra3](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/assets/tetra3).
- Vendored the minimal tetra3 runtime into [pi/src/tetra3](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/tetra3) so the repo is self-contained and no longer depends on `external/`.
- Updated [pi/src/pnt/celestial/star_solver.py](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/pnt/celestial/star_solver.py) to:
  - load config from assets
  - prefer `primary_database.npz`
  - fall back to `fallback_database.npz` or `default_database.npz`
  - use real `tetra3.Tetra3.solve_from_image(...)` when available
- Added [pi/src/scripts/generate_tetra3_db.py](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/scripts/generate_tetra3_db.py).
- Downloaded the `BSC5` source catalog and vendored it into [pi/src/tetra3/bsc5](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/tetra3/bsc5).
- Generated a real wide-FOV database:
  - [pi/src/assets/tetra3/primary_database.npz](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/assets/tetra3/primary_database.npz)
- Verified that `StarSolver` now loads `primary_database.npz`.

### Assets and backup layout

Added:

- [pi/src/assets/README.md](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/assets/README.md)
- [pi/src/assets/tetra3/README.md](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/assets/tetra3/README.md)
- calibration placeholders under [pi/src/assets/calibration](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/assets/calibration)
- mission and star-solver config under [pi/src/assets/config](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/assets/config)
- placeholder test-image folders under [pi/src/assets/test_images](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/assets/test_images)

### Repo setup

- Initialized a top-level git repo in `NatSecCelestScan`.
- Added [.gitignore](C:/Users/imalw/Downloads/NatSecCelestScan/.gitignore).
- Removed the nested `external/tetra3` repo metadata, then later removed `external/` entirely after vendoring the needed code into `pi/src/tetra3`.
- Cleaned generated `__pycache__` directories under `pi/src`.

## What Is Still Placeholder

These modules exist but are not yet production implementations:

- `visual_odometry.py`
- `stereo_depth.py`
- `geo_match.py`
- `celestial_locator.py`
- `sky_assessor.py`
- `imu.py`
- `terrain_classifier.py`
- `sun_solver.py`

Specifically:

- `visual_odometry.py` uses synthetic quality heuristics, not real feature tracking.
- `stereo_depth.py` does not yet run real rectification + SGBM.
- `geo_match.py` does not yet perform real image-to-map matching.
- `celestial_locator.py` does not yet perform a real bounded-area optimization using star geometry.
- `sky_assessor.py` uses crude image statistics and not tuned night/day observability logic.
- `imu.py` is a thread-safe stub, not a real MPU-6050 driver/filter.
- `terrain_classifier.py` is a fake cycling placeholder and not a real model.
- `sun_solver.py` is a stub only.

## What Is Left Before You Have "All the Code Needed"

### 1. Hardware integration

- Implement real camera capture for cam0 and cam1.
- Replace placeholder frame passing with actual image acquisition.
- Implement real servo GPIO control on Raspberry Pi.
- Implement real MPU-6050 reads and calibration persistence.
- Add camera-mode handling for cam0 up/down transitions.

### 2. Real stereo pipeline

- Implement real stereo calibration workflow and file format.
- Use OpenCV rectification maps from calibration output.
- Implement real `StereoSGBM`-based disparity.
- Compute robust altitude / scale from depth.
- Add frame-quality rejection for blur, sync mismatch, and low disparity confidence.

### 3. Real visual odometry

- Implement feature detection and tracking:
  - likely Shi-Tomasi + Lucas-Kanade or ORB first
- Add RANSAC outlier rejection
- Add metric scale recovery from stereo depth
- Fuse IMU rotation into frame-to-frame motion estimation
- Update pose propagation logic in `main.py`
- Add unit tests / regression tests for VO health metrics

### 4. Real geo-match

- Choose one map source and cache format
- Implement tile lookup in `map_manager.py`
- Implement feature matching between downward imagery and map imagery
- Estimate image-to-map transform robustly
- Validate scale and temporal consistency
- Decide whether map matching runs on raw frames or stitched keyframes

### 5. Real celestial fallback

- Tune `star_solver.json` extraction parameters using actual night-sky frames from the real upward camera
- Validate that the `70 deg` `primary_database.npz` solves your images reliably
- Implement actual bounded-area localization in `celestial_locator.py`
- Use:
  - UTC
  - IMU gravity vector
  - heading prior
  - camera-to-body transform
  - mission bounds
- Produce a real confidence / ambiguity metric
- Add rejection logic for ambiguous or low-confidence star-based fixes

### 6. Real sky assessment

- Calibrate thresholds with real sky imagery
- Distinguish:
  - usable stars
  - clouds / occlusion
  - glare / saturation
  - marginal conditions
- Make it robust enough that it does not flip cam0 uselessly

### 7. Real confidence fusion

- Replace current heuristic scoring with real sensor-health logic
- Define how VO, geo-match, celestial fallback, terrain type, and time since last absolute fix combine
- Ensure the nav mode transitions are driven by measured confidence, not placeholder constants

### 8. Real terrain classifier

- Decide whether a real model is actually feasible on Pi 3B
- If yes:
  - select model/runtime
  - implement preprocessing and inference
  - connect to benchmark logger
- If not:
  - reduce scope or move inference offboard

### 9. Config and calibration completion

- Fill in:
  - [camera_intrinsics.json](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/assets/calibration/camera_intrinsics.json)
  - [camera_body_transform.json](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/assets/calibration/camera_body_transform.json)
  - [stereo_cal.json](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/assets/calibration/stereo_cal.json)
  - [mission.json](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/assets/config/mission.json)
- Add any missing runtime config for camera IDs, serial ports, GPIO pins, and map cache location

### 10. Telemetry and control-loop hardening

- Add structured debug packet output, not just NMEA
- Add logging
- Add exception handling around camera / sensor failures
- Add startup health checks
- Add shutdown cleanup for hardware resources

### 11. Testing

- Add unit tests for:
  - NMEA checksum / formatting
  - config loading
  - star-solver config loading
  - confidence fusion
- Add image-based regression tests for:
  - star solving
  - sky assessment
  - stereo depth
  - geo-match
- Add system smoke test for `NavigationSystem`

## Highest-Priority Next Steps

If the goal is to get from scaffold to real working code, the next implementation order should be:

1. real camera capture + real IMU interface
2. stereo calibration + stereo depth
3. real visual odometry
4. real nav state propagation in `main.py`
5. tune star solving on actual night frames
6. real celestial bounded-area fallback
7. geo-match correction

## Current Repo State Notes

- The repo is ready for an initial commit.
- `dash/` has been left alone.
- `external/` has been removed.
- `tetra3` is now vendored under `pi/src/tetra3`.
- `primary_database.npz` is already generated and stored in assets.

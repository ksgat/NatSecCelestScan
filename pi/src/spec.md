Passive UAV Navigation + Edge Inference System
Technical Specification v0.4

Overview

This system is designed for a UAV that navigates primarily from the ground scene and uses celestial sensing as a fallback when ground imagery is weak or featureless.

Navigation priority:

1. Stereo visual odometry is the primary relative-motion source.
2. Ground-to-map matching is the primary absolute correction source when the terrain supports it.
3. IMU provides high-rate attitude propagation and short-gap stabilization.
4. Night star solving is a bounded-area fallback for absolute correction when ground methods degrade.
5. Terrain classification is an independent edge-inference task and also feeds confidence scoring.

The main design rule is:

- Downward-looking navigation is primary.
- Celestial navigation is not the first choice.
- Night plate solving exists specifically for low-feature terrain, weak map correlation, and recovery from drift in a known operating region.

Hardware

- Raspberry Pi 3B
- Cam 0: USB webcam on servo pivot, up for celestial, down for stereo ground pairing
- Cam 1: USB webcam fixed downward
- MPU-6050 IMU over I2C
- 9g servo over GPIO PWM
- WiFi UDP output to base station

Core Assumptions

- UTC time is known accurately.
- Camera intrinsics are calibrated.
- Camera-to-body transform is calibrated.
- IMU provides a usable gravity vector and short-term attitude propagation.
- Heading estimate is available and drift-corrected well enough for bounded-area search.
- The UAV operates inside a restricted mission area, not globally.
- Map tiles are cached offline before mission start.

System Modes

- VISUAL_ODOMETRY: cam0 down, stereo pair active, ground feature tracking active
- GEO_MATCH: cam0 down, ground-to-map correction active
- CELESTIAL_FALLBACK: cam0 up, night-sky assessment and star-based bounded-area correction attempt
- ACQUIRING: transition / settle / quality check state
- DEGRADED_IMU: short-duration fallback when imagery is too poor for VO

Mode Ownership

- `main.py` owns the state machine.
- `sky_assessor.py` reports observability only.
- `visual_odometry.py` reports ground-feature usability.
- `geo_match.py` reports map-match usability.
- `star_solver.py` reports night-sky solution quality.
- `celestial_locator.py` converts star observations plus priors into a bounded-area position estimate.

Directory Layout

```text
/pnt
  main.py
  config.py
  sky_assessor.py
  servo.py
  nmea_output.py
  imu.py
  confidence.py
  visual_odometry.py
  geo_match.py
  map_manager.py
  celestial_locator.py
  celestial/
    sun_solver.py
    star_solver.py
  stereo/
    stereo_depth.py
    calibration.py
/edge
  terrain_classifier.py
  benchmark.py
/comms
  udp_tx.py
/tests
```

Navigation Philosophy

Navigation is split into:

1. Relative motion
   - stereo visual odometry
   - IMU propagation

2. Absolute correction
   - ground-to-map matching
   - night celestial fallback inside a bounded search area

This is intentional. Plate solving is strong for attitude and weak for unconstrained global position. It becomes useful only when fused with strict priors such as UTC, gravity, heading, and mission-area bounds.

Main State Machine

`main.py`

Responsibilities:

- Initialize cameras, IMU, servo, stereo calibration, map manager, VO, terrain classifier, celestial modules, and telemetry.
- Run the main navigation loop at 5-10 Hz if feasible.
- Keep IMU and terrain classifier in background threads.
- Keep cam0 pointed down by default.
- Fuse:
  - VO pose increment
  - IMU attitude and angular rate
  - stereo altitude and scale quality
  - geo-match correction
  - optional celestial fallback correction
- Emit current nav solution, confidence, and mode over NMEA and debug telemetry.

Transition policy:

- Start in `ACQUIRING`
- Enter `VISUAL_ODOMETRY` when stereo and feature tracking are healthy
- Use `GEO_MATCH` when map alignment is confident
- Drop to `DEGRADED_IMU` when VO quality collapses but IMU remains healthy
- Attempt `CELESTIAL_FALLBACK` only when:
  - it is night
  - ground is feature-poor or geo-match confidence is persistently low
  - nav confidence remains below threshold for a configured interval
  - the servo flip budget / retry timer allows it
- Return to downward mode after the celestial attempt succeeds, fails, or times out

Visual Odometry

`visual_odometry.py`

Purpose:

- Primary relative-motion estimator using the downward stereo pair.

Input:

- Rectified frame from cam0 down
- Rectified frame from cam1 down
- IMU attitude and angular-rate estimate
- Stereo calibration data
- Previous tracked feature state

Output:

```python
{
  "valid": bool,
  "delta_position_m": [dx, dy, dz],
  "delta_yaw_deg": float,
  "velocity_mps": [vx, vy, vz],
  "track_count": int,
  "inlier_ratio": float,
  "parallax_score": float,
  "reprojection_error": float,
  "feature_quality": float,
  "confidence": float
}
```

Method:

- Detect and track strong ground features between consecutive frames.
- Use stereo disparity to recover metric scale.
- Use geometric consistency checks with RANSAC.
- Fuse IMU rotation to stabilize inter-frame motion estimation.
- Reject updates when:
  - track count is too low
  - inlier ratio is too low
  - blur is too high
  - disparity quality is too low
  - observed motion exceeds the model assumptions

Recommended implementation order:

1. Shi-Tomasi + Lucas-Kanade or ORB tracking
2. RANSAC filtering
3. Stereo scale recovery
4. IMU-assisted smoothing

Do not start with a heavy learned VO model on Pi 3B.

Stereo Depth

`stereo/stereo_depth.py`

Purpose:

- Provide disparity, altitude estimate, and metric scale support for VO.

Output:

```python
{
  "valid": bool,
  "altitude_m": float,
  "disparity_confidence": float,
  "center_depth_m": float,
  "depth_variance": float
}
```

Method:

- Load rectification maps at startup.
- Rectify both frames.
- Run StereoSGBM.
- Convert disparity to depth using calibrated baseline and focal length.
- Estimate altitude from robust statistics over the central ground region.
- Reject low-quality disparity frames.

Calibration

`stereo/calibration.py`

Purpose:

- Calibrate the downward stereo pair with cam0 in the down position.

Requirements:

- Intrinsics, extrinsics, baseline, and rectification maps must be produced before flight testing.
- Camera-to-body alignment for celestial mode must also be calibrated and stored.

Ground Matching

`geo_match.py`

Purpose:

- Provide absolute or drift-correcting position updates by matching live downward imagery to cached map imagery.

Input:

- Current downward frame or local keyframe
- Current altitude estimate
- Current attitude estimate
- Seed location from mission plan or current nav estimate
- Map tiles from `map_manager.py`

Output:

```python
{
  "valid": bool,
  "lat": float,
  "lon": float,
  "heading_deg": float,
  "match_score": float,
  "inlier_count": int,
  "scale_error": float,
  "confidence": float,
  "source": "osm" | "satellite" | "cached"
}
```

Method:

- Use preloaded map tiles only.
- Query candidate map windows near the current seed.
- Normalize scale using altitude and camera intrinsics.
- Extract and match local features between UAV imagery and map imagery.
- Estimate image-to-map transform with RANSAC.
- Accept correction only when geometry, scale, and temporal consistency all pass thresholds.

Important constraints:

- Geo-match is expensive and runs slower than VO.
- OSM vector data by itself is not enough; the module needs raster or rendered map imagery suitable for feature matching.
- Geo-match is a correction module, not the per-frame motion engine.

Map Management

`map_manager.py`

Purpose:

- Serve cached map tiles and mission-area metadata for geo-match.

Responsibilities:

- Load mission-area tiles from disk.
- Store tile bounds, zoom, meters-per-pixel estimate, and source metadata.
- Provide candidate tile lookup near a seed position.
- Avoid live downloads in the control loop.

IMU

`imu.py`

Purpose:

- Provide raw inertial data and a filtered attitude estimate.

Responsibilities:

- Sample MPU-6050 at 100 Hz if feasible.
- Expose accel, gyro, timestamp, and filtered roll/pitch/yaw.
- Maintain a complementary or similar lightweight attitude filter.

Important limitation:

- IMU translation is not trusted as a long-duration absolute solution.
- IMU is used for propagation and stabilization between stronger updates.

Sky Assessment

`sky_assessor.py`

Purpose:

- Decide whether an upward celestial attempt is worth performing.
- Report observability evidence only.

Input:

- Frame from cam0 with camera pointed up

Output:

```python
{
  "usable_for_sun": bool,
  "usable_for_stars": bool,
  "sky_fraction": float,
  "brightness": float,
  "saturation_fraction": float,
  "star_candidate_count": int,
  "occlusion_score": float,
  "confidence": float
}
```

Method:

- Estimate whether the frame is mostly sky.
- Detect saturation, clouding, and occlusion.
- Estimate whether a star solve is likely to succeed.

This module must not directly output nav states.

Star Solving

`celestial/star_solver.py`

Purpose:

- Solve the night sky image and estimate the camera pointing direction in celestial coordinates.

Input:

- Upward-looking frame from cam0
- Accurate UTC time
- Camera intrinsics

Output:

```python
{
  "valid": bool,
  "ra_deg": float,
  "dec_deg": float,
  "roll_deg": float,
  "fov_deg": float,
  "star_count": int,
  "residual_px": float,
  "confidence": float,
  "catalog_id_count": int
}
```

Method:

- Preprocess night image for star detection.
- Extract star centroids.
- Solve with a plate-solving library.
- Return inertial pointing solution and quality metrics.

Important note:

- `star_solver.py` is primarily an attitude / sky-reference module.
- It does not, by itself, claim a precise standalone global `lat/lon` fix.

Celestial Localization

`celestial_locator.py`

Purpose:

- Use star-solver output plus mission priors to produce a bounded-area fallback position estimate.

Input:

- Star-solver solution
- Accurate UTC
- IMU gravity vector / filtered attitude
- Drift-corrected heading estimate
- Camera-to-body calibration
- Mission-area bounds
- Current nav estimate as seed

Output:

```python
{
  "valid": bool,
  "lat": float,
  "lon": float,
  "position_error_m": float,
  "attitude_residual_deg": float,
  "search_score": float,
  "ambiguity_score": float,
  "confidence": float,
  "method": "bounded_star_fallback"
}
```

Method:

- Treat the problem as a bounded-area estimation problem, not a global solve.
- For candidate locations in the allowed region:
  - predict local sky geometry at the known UTC
  - compare predicted geometry against the star-solver result
  - enforce consistency with gravity vector, heading, and camera alignment
- Select the best candidate only if:
  - residual is low enough
  - ambiguity across nearby candidates is low enough
  - result is consistent with the recent motion history

Role in the system:

- This module is a fallback when the ground scene is weak.
- It is intended as a coarse absolute correction or drift reset.
- It should not override a healthy geo-match solution.

Sun Solver

`celestial/sun_solver.py`

Purpose:

- Optional daytime observability / coarse heading aid.

Status in v0.4:

- Secondary only.
- Not required for first implementation.
- Night star fallback is the main celestial path worth building first.

Terrain Classifier

`edge/terrain_classifier.py`

Purpose:

- Independent edge-inference deliverable on the downward camera stream.

Output:

```python
{
  "class": "snow" | "water" | "vegetation" | "urban" | "unknown",
  "confidence": float,
  "inference_ms": float
}
```

Navigation coupling:

- `snow` and `water` reduce VO and geo-match confidence because the ground is often feature-poor.
- `urban` can increase confidence because it is usually feature-rich.
- Terrain class can be used as one trigger for celestial fallback at night.

Confidence Fusion

`confidence.py`

Purpose:

- Produce one consistent navigation confidence output.

Inputs:

- visual odometry quality
- stereo depth quality
- IMU health
- geo-match confidence
- star-solver confidence
- celestial locator confidence
- terrain penalty / bonus
- age of last absolute correction

Output:

```python
{
  "confidence": float,
  "fix_quality": int,
  "fix_type": str
}
```

Suggested fix-type mapping:

- `1`: absolute correction from geo-match
- `2`: absolute correction from celestial fallback
- `6`: propagated visual odometry / dead reckoning
- `0`: invalid or untrusted solution

If strict NMEA compatibility matters, keep standard GGA meanings and publish custom mode labels separately in debug telemetry.

NMEA Output

`nmea_output.py`

Purpose:

- Format the nav solution into standard NMEA-compatible messages.

Requirements:

- Use standard checksum generation.
- Avoid redefining standard fix-quality semantics unless the consumer is fully custom.

Telemetry

`comms/udp_tx.py`

Purpose:

- Send NMEA and debug packets to the base station.

Recommended debug fields:

- nav mode
- VO confidence
- geo-match confidence
- celestial confidence
- track count
- altitude
- terrain class

Dependencies

- opencv-python
- numpy
- smbus2
- RPi.GPIO
- socket
- threading
- json
- csv

Celestial-specific dependencies:

- tetra3 for plate solving
- astropy for coordinate math and bounded-area celestial geometry

Optional offline tooling:

- astroquery for catalog prep / validation

Performance Targets

- VO update: 5-10 Hz target
- Geo-match correction: 0.2-1 Hz target
- Celestial fallback attempt: on demand only, not continuous
- Terrain classification: best-effort background rate
- IMU: 100 Hz target

Implementation Order

1. Stereo calibration
2. Stereo depth
3. Visual odometry
4. Confidence fusion for VO + IMU
5. Map manager with offline tiles
6. Geo-match correction
7. Terrain-based confidence penalties
8. Sky assessor
9. Star solver
10. Celestial locator bounded-area fallback

Demo Scenario

1. Boot with cam0 down.
2. Stereo depth and visual odometry start on the downward pair.
3. IMU stabilizes attitude propagation.
4. Geo-match provides absolute corrections when the ground scene supports it.
5. Terrain classifier identifies feature-poor terrain such as water or snow and reduces ground-nav confidence.
6. At night, if VO / geo-match confidence remains poor long enough, the system flips cam0 up and checks star visibility.
7. If the sky is usable, `star_solver.py` solves the field and `celestial_locator.py` searches the bounded mission area for the best consistent fallback position.
8. If the celestial fallback is confident, it is applied as a coarse absolute correction and the system returns cam0 down.
9. If celestial fallback fails, the system returns cam0 down and continues with IMU-assisted propagation until the ground scene improves.

# Assets

Offline runtime and calibration assets live here.

## Layout

- `tetra3/`
  - `README.md`: notes about the active plate-solver database files
  - place `*.npz` tetra3 databases here
- `calibration/`
  - `camera_intrinsics.json`: upward / downward camera intrinsics
  - `camera_body_transform.json`: camera-to-body alignment
  - `stereo_cal.json`: stereo baseline and rectification metadata
- `config/`
  - `star_solver.json`: extraction and solve parameters for tetra3
  - `mission.json`: mission-area bounds and nav overrides
- `test_images/`
  - `night_sky/`: known-good and known-bad celestial frames
  - `ground/`: ground imagery for VO / geo-match regression

## What to back up

- tetra3 database files
- all calibration JSON files
- solver configuration JSON files
- representative night-sky test images
- representative ground-scene test images

## What tetra3 does not need

- Wi-Fi during solve
- live network access
- Earth location as an input to the plate solve itself


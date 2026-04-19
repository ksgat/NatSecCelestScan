# TODO

## Current Direction

The project has shifted away from making celestial navigation a major pillar.

Working assumption now:
- primary relative navigation: `camera + IMU`
- primary absolute correction: `ground-to-map matching`
- celestial: optional demo/fallback only, and likely to be reduced hard or removed if it stays gimmicky / non-defensible

That is the healthier plan.

## Completed This Session

### Dashboard / map data

- Reworked `dash/` so it can use real imagery sources instead of only OSM placeholder tiles.
- Added NoVA source presets in [dash/app.py](C:/Users/imalw/Downloads/NatSecCelestScan/dash/app.py):
  - `Fairfax 2025 Ortho`
  - `Loudoun 2023 Ortho`
  - `OSM Placeholder`
- Updated the dashboard UI to select imagery source directly and keep preview/download source in sync.
- Added [dash/download_preset_collection.py](C:/Users/imalw/Downloads/NatSecCelestScan/dash/download_preset_collection.py) to download a square collection directly without using the Flask UI.
- Pulled a real Fairfax collection:
  - [fairfax-runtime-1mi-b6f538ab](C:/Users/imalw/Downloads/NatSecCelestScan/dash/data/collections/fairfax-runtime-1mi-b6f538ab)
  - `z17-z19`
  - `1036` tiles
- Verified nav-side [MapManager](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/pnt/map_manager.py) resolves that collection automatically as the active runtime map collection.

### Runtime geo-match direction

- Reworked [map_manager.py](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/pnt/map_manager.py) so runtime matching does not require embeddings.
- Reworked [geo_match.py](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/pnt/geo_match.py) into a classical Pi-friendly matcher:
  - local candidate search around the seed
  - ORB feature matching
  - BFMatcher ratio test
  - RANSAC homography
  - tile-pixel to `lat/lon` conversion
- Kept embeddings optional instead of required.
- Set runtime search-space assumptions to a small local region, which matches how this will actually be tested.

### Seasonal-robustness hardening

- Added edge-enhanced preprocessing to [geo_match.py](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/pnt/geo_match.py):
  - CLAHE grayscale
  - blur
  - Canny edges
  - edge-weighted feature image
- Added structural verification scoring:
  - edge overlap after homography
  - corner-map overlap
  - density consistency
- Added related config knobs in [config.py](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/pnt/config.py):
  - `verify_min_structural_score`
  - `edge_weight`
  - Canny thresholds
  - corner extraction settings
- Added `structural_score` to [models.py](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/pnt/models.py) and [geo_match_debug.py](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/scripts/geo_match_debug.py).

### Test and evaluation tooling

- Added [generate_synth_data.py](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/scripts/generate_synth_data.py) to generate synthetic downward test queries from cached map tiles.
- Added [assessment.py](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/scripts/assessment.py) to run the matcher across a synthetic manifest and write:
  - `assessment.json`
  - `assessment_cases.csv`
  - `assessment_summary.csv`
- Ran a real smoke test against the Fairfax collection and generated:
  - [fairfax-runtime-1mi-b6f538ab-synth](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/assets/test_images/ground/synthetic/fairfax-runtime-1mi-b6f538ab-synth)
- Smoke-test results were good for:
  - clean
  - noise
  - moderate rotations
  - rotation + noise
- Horizontal-only and vertical-only flips were rejected, which is desirable.

### Data ingest tooling

- Added [ingest_sid_collection.py](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/scripts/ingest_sid_collection.py) for one-time `MrSID -> XYZ tile collection` ingest.
- Important note: this still requires GDAL tools with MrSID support; it is not exercised yet.

### IMU / camera / bring-up work already done and still relevant

- `imu.py` is now using Mahony via `ahrs` instead of a hand-rolled fusion approximation.
- `camera.py` exists and `main.py` already uses real camera capture interfaces.
- `camera_debug_server.py` exists and was updated to the real camera layout:
  - `cam0 = /dev/video0` servo cam
  - `cam1 = /dev/video2` fixed downward cam

## Change In Plans

### Celestial stack

The celestial path should now be treated as one of:
- optional fallback only
- demo-only feature
- or cut entirely

Reason:
- it is easy to oversell
- it is weak compared to the map/vision path
- it risks turning the project into something that feels fraudulent rather than technically solid

Practical consequence:
- do not spend major implementation time polishing `sun_solver`, `celestial_locator`, or sky-state logic unless the rest of the system is already working
- do not let celestial drive the main architecture anymore

## What Is Real Now

These parts are meaningfully real enough to test:

- dashboard tile collection from real NoVA imagery
- cached tile collections in the correct runtime format
- nav-side collection loading
- classical local-search geo-match pipeline
- structural robustness scoring
- synthetic robustness test generation
- synthetic assessment reporting
- camera/IMU bring-up scripts and debug tooling

## What Is Still Placeholder / Not Done

### Major runtime pieces still not real enough

- [visual_odometry.py](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/pnt/visual_odometry.py)
  - still not a proper production VO implementation
- [stereo_depth.py](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/pnt/stereo/stereo_depth.py)
  - still not real rectified stereo + disparity
- [terrain_classifier.py](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/edge/terrain_classifier.py)
  - still not a real deployed model
- [confidence.py](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/pnt/confidence.py)
  - still heuristic

### Optional / de-prioritized pieces

- [celestial_locator.py](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/pnt/celestial_locator.py)
- [sky_assessor.py](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/pnt/sky_assessor.py)
- [sun_solver.py](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/pnt/celestial/sun_solver.py)

These may stay rough, move to demo-only status, or get removed from the critical path.

## What Is Left Before This Is a Real Working Detection / Localization Stack

### 1. Real saved-frame validation

- Run `geo_match_debug.py` on real downward images from the actual camera, not just synthetic map-derived images.
- Build a small labeled test set from the real module.
- Confirm the matcher still behaves when the query image is not literally derived from the cached map tile source.

### 2. Real stereo / altitude path

- Implement or replace the placeholder stereo depth path with something real enough to provide a useful altitude/scale prior.
- If stereo proves painful, consider a simpler temporary altitude source before continuing.

### 3. Real VO

- Implement real feature tracking in [visual_odometry.py](C:/Users/imalw/Downloads/NatSecCelestScan/pi/src/pnt/visual_odometry.py).
- Use IMU to stabilize frame-to-frame motion estimation.
- Make VO the real between-fix propagation source.

### 4. Geo-match tuning on real imagery

- Tune:
  - ORB feature count
  - ratio test
  - RANSAC threshold
  - structural thresholds
  - seed search radius
- Add match visualization output so failures can be inspected visually, not just numerically.

### 5. Nav-loop integration quality

- Make sure `main.py` uses the geo-match result in a controlled way and not too aggressively.
- Add better logging and debug capture.
- Add failure handling so a bad map match cannot yank the nav solution around.

### 6. MrSID ingest decision

One of:
- keep using direct county imagery services and cached XYZ tiles
- or install GDAL with MrSID support and make `ingest_sid_collection.py` part of the offline asset workflow

This is no longer blocking immediate progress because Fairfax imagery is already cached.

## Recommended Next Order

1. real downward frame capture set from the actual module
2. run `geo_match_debug.py` and `assessment.py` style tests on real images
3. add match visualization output
4. implement real `visual_odometry.py`
5. improve/replace `stereo_depth.py`
6. tighten `main.py` fusion and mode logic
7. decide whether celestial stays as demo-only or gets cut from the serious roadmap

## Short Truth

The project is now much more honest than it was at the start:
- map-based detection/localization is the serious path
- Pi runtime is classical and defensible
- DINO is optional support infrastructure
- celestial is no longer something the project should lean on heavily

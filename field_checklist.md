# Field Completion Checklist

## Before You Leave For The Field
- [ ] `dash` runs on the laptop and shows the live map, diagnostics, camera panes, and NMEA/debug telemetry.
- [ ] The Pi can start `pnt.main` without crashing.
- [ ] The Pi camera debug server works.
- [ ] `NATSEC_UDP_HOST` points to the laptop IP.
- [ ] The stereo `baseline_m` in `config.py` matches the real rig as closely as possible.
- [ ] The mission bounds roughly cover the test area.
- [ ] You know where logs, screenshots, and recorded clips will be saved.

## At The Field: Bring-Up
- [ ] Put the rig on the ground or a table and confirm both cameras are live.
- [ ] Confirm IMU values update in `dash`.
- [ ] Confirm NMEA is streaming into `dash`.
- [ ] Confirm the live pin appears on the map.
- [ ] Confirm the debug packet is updating once per loop.

## At The Field: Tune Only These Knobs
- [ ] Tune stereo `baseline_m` until reported altitude is at least plausible.
- [ ] Tune `camera.down_camera_yaw_offset_deg` until VO direction matches the real direction of motion.
- [ ] Tune `maps.verify_min_structural_score` if geo-match is accepting obvious garbage.
- [ ] Tune `maps.verify_min_inlier_ratio` if geo-match is too easy to trigger on bad scenes.
- [ ] Tune `maps.match_ratio_test` if ORB matching is too loose or too strict.
- [ ] Tune `maps.seed_search_radius_m` only if the search region is clearly too small or too large.
- [ ] Do not start changing everything at once.

## At The Field: Required Tests
- [ ] Stationary test for 20-30 seconds.
- [ ] Slow straight-line carry test.
- [ ] Slow turn-in-place test.
- [ ] Out-and-back walk test.
- [ ] One test over the actual ground you want in the demo footage.
- [ ] If safe, one short elevated or flight-like pass.

## What “Good Enough” Looks Like
- [ ] Stereo altitude is nonzero and roughly believable.
- [ ] VO changes when you move and mostly points the correct way.
- [ ] VO does not explode immediately when the rig is moved slowly.
- [ ] Geo-match gets at least one believable lock in the real scene.
- [ ] Geo-match does not yank the pose to nonsense repeatedly.
- [ ] When geo-match is bad, the system degrades instead of pretending.
- [ ] NMEA continues streaming the whole time.
- [ ] `dash` stays usable and shows the internal state clearly.

## Data You Must Capture Before Leaving
- [ ] Screen recording of `dash` during a successful run.
- [ ] Phone video of the physical rig during that same run.
- [ ] One clip showing the map pin moving.
- [ ] One clip showing diagnostics updating live.
- [ ] One clip showing camera feeds.
- [ ] Saved screenshots of a good geo-match case.
- [ ] Saved screenshots of stereo + VO numbers during motion.
- [ ] The exact config values you changed in the field.

## Minimum Bar To Leave The Field
- [ ] You have one continuous successful run on video.
- [ ] You have one believable map lock.
- [ ] You have one believable VO motion segment.
- [ ] You have one believable altitude estimate.
- [ ] You can explain at least one failure mode honestly.
- [ ] You are no longer guessing whether the system “does anything.”

## What To Say In The Demo
- [ ] “This is a GPS-like output pipeline driven by camera, IMU, and map matching.”
- [ ] “The Pi sends NMEA and debug telemetry to the laptop dashboard.”
- [ ] “VO handles short-term motion, stereo gives scale/altitude, and geo-match provides absolute correction.”
- [ ] “This version intentionally deprioritized celestial navigation because it was less defensible than the map-based path.”
- [ ] “Runtime matching on the Pi is classical and lightweight; learned embeddings are optional offline support.”

## What Not To Claim
- [ ] Do not call it production-ready autonomy.
- [ ] Do not claim perfect localization accuracy.
- [ ] Do not oversell celestial navigation.
- [ ] Do not pretend bad matches are good matches.

## If These Are True, Go Back To The Venue
- [ ] The system runs live on the Pi.
- [ ] The dashboard clearly shows pose, VO, stereo, geo-match, and NMEA.
- [ ] You have enough footage for a demo video.
- [ ] You have enough screenshots for slides.
- [ ] You can explain what is real, what is approximate, and why it is still technically interesting.

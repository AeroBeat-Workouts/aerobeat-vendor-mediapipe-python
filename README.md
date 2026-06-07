# AeroBeat Vendor MediaPipe Python

This repo hosts the first **vendor-owned MediaPipe Python backend/wrapper shell** for the AeroBeat camera-tracking lane.

The current slice is intentionally a **truthful narrow continuous runtime lane**, not a full end-to-end gameplay tracking delivery. It now launches a small repo-owned Python entrypoint for live-camera bootstrap, camera enumeration, runtime-health snapshots, and a short-lived active capture/inference loop that keeps producing repeated raw landmark frame updates while the session lives. The shared camera-tracking singleton remains the owner of lifecycle semantics, preview attachment, and normalized public tracking payloads; this repo owns the vendor-specific startup/shutdown seam, config translation, truthful live-camera runtime behavior, camera enumeration, runtime-health reporting, and minimal raw landmark extraction needed to keep the vendor lane honest.

## Current bootstrap scope

- `MediaPipePythonCameraTrackingBackend` contract-facing backend shell targeting `CameraTrackingBackend`
- `MediaPipePythonRuntimeBridge` truthful bridge for Python bootstrap/probe orchestration
- `MediaPipePythonConfig` translation helpers from public camera-tracking config into vendor runtime settings
- `MediaPipePythonCameraInventory` helpers for camera enumeration normalization
- `MediaPipePythonRuntimeHealth` helpers for vendor/runtime diagnostics
- `MediaPipePythonFrameMapper` helpers that normalize raw vendor frames toward the shared tracking-frame contract

## Canonical vendor runtime prep command

The official prep/install entrypoint for this vendor lane is:

```bash
python3 scripts/prepare_vendor_runtime.py --json
```

What it truthfully owns:

- creates or reuses a repo-local Python virtualenv at `/.venv`
- installs this repo's runtime dependencies from `runtime/requirements.txt`
- validates that the repo-owned Python entrypoint and default model asset exist
- verifies the prepared virtualenv can import the runtime modules this lane actually needs (`mediapipe`, `cv2`, `numpy`)
- returns a JSON payload with the prepared `python_executable`, `entrypoint`, `working_directory`, and default model path that downstream tooling can wire into vendor runtime config

What it intentionally does **not** own:

- GodotEnv addon restore/sync
- `.testbed` import or GUT execution
- downstream app lifecycle, bundle assembly, or consumer-specific config mutation

If you only want to inspect/report an existing prepared env without reinstalling, use `--skip-install`. If you need to recreate the env from scratch, use `--force`.

## MediaPipe package compatibility and model asset truth

This repo now supports both of these host package shapes for the sampled live-camera landmark pass:

- legacy `mediapipe.solutions.pose.Pose(...)`
- tasks-era `mediapipe.tasks` + `PoseLandmarker`

The tasks-era path requires a real `.task` pose-landmarker model asset. The vendor runtime now resolves the default repo-owned model by `runtime.model_complexity` using the same filename mapping as the legacy local sidecar lane:

- `0` -> `models/pose_landmarker_lite.task`
- `1` -> `models/pose_landmarker_full.task`
- `2` -> `models/pose_landmarker_heavy.task`

If a higher-complexity variant is requested, the runtime does not silently fall back to lite; it fails honestly unless that exact variant or an explicit override path is present.

You can also override the model path through vendor runtime config:

- `runtime.model_complexity`
- `runtime.pose_landmarker_model_path`
- `runtime.model_asset_path`
- `runtime.environment.AEROBEAT_MEDIAPIPE_POSE_LANDMARKER_MODEL_PATH`
- host env `MEDIAPIPE_POSE_LANDMARKER_MODEL_PATH`

Continuous runtime cadence and preview behavior are now controlled by the vendor-owned runtime caps instead of piggybacking on `health_poll_interval_ms`:

- `runtime.tracking_max_fps` — actual live/replay capture + inference cadence (`0` uncapped, default `15`)
- `runtime.state_update_max_fps` — snapshot/state write cap (default `15`)
- `runtime.preview_enabled` — enable/disable preview frame writes entirely (default `true`)
- `runtime.preview_max_fps` — preview image update cap (default `10`)
- `runtime.preview_width` / `runtime.preview_height` — preview downscale bounds (defaults `960x540`)
- `runtime.preview_quality` — JPEG quality for preview frame writes (default `75`)
- `runtime.live_camera_width` / `runtime.live_camera_height` — requested live-camera capture mode before inference (defaults mirror preview bounds)
- `runtime.live_camera_fps` — requested live-camera capture FPS during negotiation (defaults mirror tracking max FPS)
- `runtime.live_camera_fourcc` — preferred live-camera FOURCC for Linux/OpenCV negotiation (`MJPG` by default)

On Linux `/dev/video*` live-camera sessions the runtime now treats V4L2 enumeration as the canonical reported-options source when `v4l2-ctl` is available, ranks candidates using Derrick's policy (**framerate first, resolution second, then format/backend quality**), and probes only the top shortlist through the actual OpenCV capture path before choosing a mode. When V4L2 enumeration is unavailable, it falls back to a bounded sane probe sweep instead of pretending the camera supports an arbitrary request.

Hand-tracking raw vendor payloads are now also exposed for the next tracker slice:

- optional `raw_tracking_frame.hands[]` entries containing MediaPipe-detected hand samples (`label`, `score`, emitted `landmarks`, and derived normalized-frame `bbox` geometry)
- `tracking.hands.landmark_mode: lite|full` controls both the emitted landmark subset and which landmarks the vendor uses to derive bbox geometry
  - `lite` uses a compact wrist/palm/fingertip subset for cheaper transport and intentionally produces a smaller bbox than `full`
  - `full` emits all 21 landmarks and derives bbox geometry from the full set
- `raw_tracking_frame.vendor_hand_tracking` surfaces the requested cadence knobs and hand timing budget the tracker layer must honor upstream (`inference_interval_frames`, `max_stale_ms`, `reacquire_stable_ms`, backend/model availability, and API limits)

Important API truth for later slices:

- MediaPipe does **not** expose stable per-hand IDs here; handedness labels can swap across frames and must be associated upstream.
- Preview mirroring is presentation-only; raw hand coordinates stay camera-native and must be mirrored consistently with pose upstream.
- The tasks backend runs `HandLandmarker` in `IMAGE` mode in this slice, so there is no vendor-side interpolation or per-hand timestamp beyond the parent frame timestamp.
- If the host only exposes tasks-era MediaPipe and no hand `.task` asset is present, the vendor frame reports hand inference as unavailable instead of pretending stale/tracked semantics exist.

The runtime reports that truth back through `health.capture_mode` and `camera_options`, distinguishing:

- the original requested mode
- the reported options returned by V4L2 (when available)
- the successfully probed shortlist results
- the selected candidate mode
- the actual negotiated mode OpenCV delivered

`MediaPipePythonRuntimeBridge` and `MediaPipePythonCameraTrackingBackend` also expose a vendor-owned `describe_camera_options` / `get_camera_options` capability so higher layers can request the current camera's reported/proven combination options without talking to the Python entrypoint directly.

If the host only exposes the tasks-era MediaPipe API and no usable model asset is available, the runtime fails honestly with `mediapipe_model_missing` instead of pretending inference ran.

## Repository details

- **Type:** AeroBeat vendor package
- **License:** **Mozilla Public License 2.0 (MPL 2.0)**
- **Implementation status:** truthful narrow continuous live-camera slice for startup, camera enumeration, runtime-health reporting, repeated raw frame updates, and repeated minimal raw landmark payloads while the runtime session remains alive; richer public temporal semantics and downstream migration are still deferred
- **Primary contract dependency:** `aerobeat-tool-camera-tracking` at contract-shell commit `25f52da`

## GodotEnv development flow

This repo follows the AeroBeat GodotEnv package convention.

- Canonical dev/test manifest: `.testbed/addons.jsonc`
- Installed dev/test addons: `.testbed/addons/`
- GodotEnv cache: `.testbed/.addons/`
- Hidden workbench project: `.testbed/project.godot`
- Repo-local unit tests: `.testbed/tests/`
- Repo-root sharable source: `src/`

The repo root remains the package/published boundary for downstream consumers. `.testbed/` is only the proving surface. Do real sharable work at the repo root, not inside `.testbed/addons/` mirrors.

### Restore dev/test dependencies

From the repo root:

```bash
/home/derrick/.openclaw/workspace/scripts/godotenv-sync
cd .testbed
godotenv addons install
```

Use the sync helper first if the local toolchain or linked workspace packages need refreshing.

### Import smoke check

From the repo root:

```bash
godot --headless --path .testbed --import
```

### Run repo-local tests

From the repo root:

```bash
godot --headless --path .testbed --script addons/aerobeat-vendor-godot-unit-test/gut_cmdln.gd \
  -gdir=res://tests \
  -ginclude_subdirs \
  -gexit
```

## Notes for later slices

- the runtime now owns a short-lived truthful continuous subprocess loop behind `MediaPipePythonRuntimeBridge`, but broader public temporal semantics (`reacquiring`, loss handling, replay/video-file support, richer body/head outputs, and consumer migration) are still intentionally deferred
- public lifecycle semantics stay in `aerobeat-tool-camera-tracking`; this repo should not grow a competing singleton
- preview attachment ownership and normalized top-level tracking payload remain upstream contract concerns even when vendor-specific raw payloads evolve here

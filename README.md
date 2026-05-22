# AeroBeat Vendor MediaPipe Python

This repo hosts the first **vendor-owned MediaPipe Python backend/wrapper shell** for the AeroBeat camera-tracking lane.

The current slice is intentionally a **truthful minimal sampled-frame runtime lane**, not a full tracking delivery. It now launches a small repo-owned Python entrypoint for live-camera bootstrap/probe work, camera enumeration, runtime-health snapshots, capture of one truthful live-camera sample, and one truthful sampled pose-landmark inference pass without duplicating `aerobeat-tool-camera-tracking`'s public lifecycle contract. The shared camera-tracking singleton remains the owner of lifecycle semantics, preview attachment, and normalized public tracking payloads; this repo owns the vendor-specific startup/shutdown seam, config translation, truthful live-camera probe behavior, camera enumeration, runtime-health reporting, raw sampled landmark extraction, and raw-frame mapping needed to wire in a fuller MediaPipe Python process later.

## Current bootstrap scope

- `MediaPipePythonCameraTrackingBackend` contract-facing backend shell targeting `CameraTrackingBackend`
- `MediaPipePythonRuntimeBridge` truthful bridge for Python bootstrap/probe orchestration
- `MediaPipePythonConfig` translation helpers from public camera-tracking config into vendor runtime settings
- `MediaPipePythonCameraInventory` helpers for camera enumeration normalization
- `MediaPipePythonRuntimeHealth` helpers for vendor/runtime diagnostics
- `MediaPipePythonFrameMapper` helpers that normalize raw vendor frames toward the shared tracking-frame contract

## MediaPipe package compatibility and model asset truth

This repo now supports both of these host package shapes for the sampled live-camera landmark pass:

- legacy `mediapipe.solutions.pose.Pose(...)`
- tasks-era `mediapipe.tasks` + `PoseLandmarker`

The tasks-era path requires a real `.task` pose-landmarker model asset. By default the runtime now looks for a repo-owned model at:

- `models/pose_landmarker_lite.task`

You can also override the model path through vendor runtime config:

- `runtime.pose_landmarker_model_path`
- `runtime.model_asset_path`
- `runtime.environment.AEROBEAT_MEDIAPIPE_POSE_LANDMARKER_MODEL_PATH`
- host env `MEDIAPIPE_POSE_LANDMARKER_MODEL_PATH`

If the host only exposes the tasks-era MediaPipe API and no usable model asset is available, the runtime fails honestly with `mediapipe_model_missing` instead of pretending inference ran.

## Repository details

- **Type:** AeroBeat vendor package
- **License:** **Mozilla Public License 2.0 (MPL 2.0)**
- **Implementation status:** truthful minimal sampled-frame slice for live-camera startup, camera enumeration, runtime-health reporting, one non-empty raw sampled frame, and one sampled raw landmark payload when the sampled frame truly yields a pose; continuous MediaPipe tracking inference is still deferred
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
godot --headless --path .testbed --script addons/gut/gut_cmdln.gd \
  -gdir=res://tests \
  -ginclude_subdirs \
  -gexit
```

## Notes for later slices

- a real long-lived Python subprocess/native tracking bridge still needs to be implemented behind `MediaPipePythonRuntimeBridge`; this slice only performs truthful startup/probe work plus one sampled-frame capture and one sampled-frame landmark inference pass
- public lifecycle semantics stay in `aerobeat-tool-camera-tracking`; this repo should not grow a competing singleton
- preview attachment ownership and normalized top-level tracking payload remain upstream contract concerns even when vendor-specific raw payloads evolve here

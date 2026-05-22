# AeroBeat Vendor MediaPipe Python

This repo hosts the first **vendor-owned MediaPipe Python backend/wrapper shell** for the AeroBeat camera-tracking lane.

The current slice is intentionally a **bootstrap backend seam**, not a full runtime delivery. It establishes the repo-root structure that can sit behind `aerobeat-tool-camera-tracking` without duplicating that repo's public lifecycle contract. The shared camera-tracking singleton remains the owner of lifecycle semantics, preview attachment, and normalized public tracking payloads; this repo owns the vendor-specific startup/shutdown seam, config translation, camera enumeration seam, runtime-health seam, and raw-frame mapping seam needed to wire in a real MediaPipe Python process later.

## Current bootstrap scope

- `MediaPipePythonCameraTrackingBackend` contract-facing backend shell targeting `CameraTrackingBackend`
- `MediaPipePythonRuntimeBridge` seam for future Python process/bootstrap orchestration
- `MediaPipePythonConfig` translation helpers from public camera-tracking config into vendor runtime settings
- `MediaPipePythonCameraInventory` helpers for camera enumeration normalization
- `MediaPipePythonRuntimeHealth` helpers for vendor/runtime diagnostics
- `MediaPipePythonFrameMapper` helpers that normalize raw vendor frames toward the shared tracking-frame contract

## Repository details

- **Type:** AeroBeat vendor package
- **License:** **Mozilla Public License 2.0 (MPL 2.0)**
- **Implementation status:** bootstrap wrapper shell only; no real MediaPipe Python runtime is shipped in this slice
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

- a real Python subprocess/native bridge still needs to be implemented behind `MediaPipePythonRuntimeBridge`
- public lifecycle semantics stay in `aerobeat-tool-camera-tracking`; this repo should not grow a competing singleton
- preview attachment ownership and normalized top-level tracking payload remain upstream contract concerns even when vendor-specific raw payloads evolve here

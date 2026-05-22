# AeroBeat Vendor MediaPipe Python — Continuous Tracking Runtime Slice

**Date:** 2026-05-22  
**Status:** Draft  
**Agent:** Cookie 🍪

---

## Goal

Upgrade `aerobeat-vendor-mediapipe-python` from truthful sampled live-camera landmark snapshots into the first truthful **continuous live-camera runtime lane** that keeps producing raw landmark frame updates over time without stealing public lifecycle/state ownership from `aerobeat-tool-camera-tracking`.

---

## Overview

The minimal-real-landmark slice and the host compatibility repair are now complete. On this machine, the vendor repo can truthfully capture a real `/dev/video0` frame, run the tasks-era MediaPipe pose landmarker, and emit a minimal raw landmark payload with `id/x/y/z/visibility`. That spatial proof is no longer the blocker.

The blocker is temporal truth. The current runtime still launches one probe per `startup` or `reconfigure`, returns one snapshot, and exits. That leaves `process_active=false`, `tracking_active=false`, and no honest path for new frames to arrive after startup without another restart. The next narrowest honest slice is therefore not replay, not consumer migration, and not richer pose semantics. It is a long-lived vendor-owned runtime lane that keeps the selected live camera active and surfaces repeated raw frame updates through the existing bridge/backend seam.

This slice must keep the ownership boundary strict. `aerobeat-vendor-mediapipe-python` owns runtime process/session truth, MediaPipe inference cadence, raw frame update transport, raw landmark extraction, runtime health, and honest failure reporting. It does **not** own the public normalized frame schema, public lifecycle/state wording, preview/source coordination rules, or downstream gameplay-readiness claims.

---

## REFERENCES

| ID | Description | Path |
| --- | --- | --- |
| `REF-01` | Coordination plan for the continuous-tracking wave | `/workspace/projects/openclaw-cookie/.plans/aerobeat-architecture/2026-05-22-continuous-tracking-slice.md` |
| `REF-02` | Completed sampled landmark slice | `/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/.plans/2026-05-22-minimal-real-landmark-slice.md` |
| `REF-03` | Completed host MediaPipe compatibility repair | `/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/.plans/2026-05-22-host-mediapipe-compat-repair.md` |
| `REF-04` | Current runtime entrypoint that still behaves as a one-shot probe | `/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/runtime/mediapipe_runtime_probe.py` |
| `REF-05` | Current runtime bridge that only transports one-shot snapshots | `/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/src/MediaPipePythonRuntimeBridge.gd` |
| `REF-06` | Current vendor backend seam that consumes bridge snapshots | `/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/src/MediaPipePythonCameraTrackingBackend.gd` |
| `REF-07` | Current raw-frame mapper seam into the tool contract | `/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/src/MediaPipePythonFrameMapper.gd` |
| `REF-08` | Current tool public frame contract and normalization surface | `/workspace/projects/aerobeat/aerobeat-tool-camera-tracking/src/CameraTrackingFrame.gd` |
| `REF-09` | Current downstream input adapter assumptions | `/workspace/projects/aerobeat/aerobeat-input-camera-tracking/src/tracking_frame_adapter.gd` |

---

## Slice Boundaries

### In scope for this slice

- Keep support limited to `backend = mediapipe_python` + `source.kind = live_camera`.
- Replace the one-shot sampled runtime behavior with a vendor-owned long-lived runtime/session that keeps capturing frames and running pose inference until shutdown or reconfigure.
- Surface repeated raw frame updates through the existing vendor bridge/backend seam using the narrowest honest transport that works on this host.
- Strengthen runtime health truth so `process_active` and `tracking_active` can become truthfully `true` while the continuous lane is actually alive.
- Keep the raw vendor frame contract minimal: repeated frames may carry only vendor-provable fields (`timestamp_ms`, `source_kind`, `source_id`, `tracking_state`, `frame_size`, `landmarks[].id/x/y/z/visibility`).
- Add/adjust repo-local tests and docs only enough to prove real repeated-update behavior and honest stop/failure semantics.

### Explicitly out of scope for this slice

- Replay / `video_file` support.
- Multi-pose support.
- Public coordinate normalization or public frame-schema redesign.
- `reacquiring` / `lost` public tracking-state semantics.
- Skeleton, head pose, velocity, or aggregate confidence claims.
- Downstream `aerobeat-input-camera-tracking` migration work.

---

## Ownership Decisions Captured Here

### `aerobeat-vendor-mediapipe-python` owns in this slice

- long-lived runtime/session lifecycle truth for the vendor runtime implementation
- camera capture cadence and MediaPipe inference cadence
- raw repeated frame updates and raw landmark extraction
- runtime/session health facts such as whether a process/session is alive and whether continuous capture/inference is active
- honest failure/teardown semantics when the runtime cannot keep the lane alive

### `aerobeat-vendor-mediapipe-python` does **not** own in this slice

- public lifecycle state names beyond reporting raw vendor/runtime facts upward
- public preview/source coordination semantics
- the public normalized frame/state contract consumed by downstream tools
- gameplay-space coordinate meaning for landmarks
- downstream readiness claims for gesture/gameplay consumers

---

## Proposed Stronger Vendor Guarantees After This Slice

If this slice lands successfully, the vendor repo should be able to guarantee all of the following for `live_camera` continuous mode on this host:

1. `startup()` can establish a real long-lived runtime/session instead of only returning a one-shot probe snapshot.
2. While that session is alive, `health.process_active = true` is truthful.
3. While the continuous capture/inference loop is actively running, `health.tracking_active = true` is truthful even if an individual frame currently has `tracking_state = idle` because no pose is visible.
4. Repeated runtime polls/updates can deliver newer `raw_tracking_frame.timestamp_ms` values without requiring `reconfigure()`.
5. Per-frame raw payload shape remains minimal and honest:
   - top-level only `timestamp_ms`, `source_kind`, `source_id`, `tracking_state`, `frame_size`, `landmarks`
   - landmarks only `id`, `x`, `y`, `z`, `visibility`
6. `tracking_state` remains raw per-frame truth only:
   - `tracked` when that raw frame has landmarks
   - `idle` when that raw frame does not
7. `shutdown()` can tear the runtime/session down and return health to an honest inactive state.

---

## Still Provisional / Intentionally Deferred After This Slice

Even after this slice lands, these truths remain intentionally provisional or absent here:

- public `reacquiring` / `lost` semantics across time
- guaranteed frame rate, latency budget, or dropped-frame accounting
- multi-pose output
- aggregate `confidence` meaning
- `head_position`, `head_velocity`, `head_orientation`
- `skeleton`
- richer physical meaning or scale guarantees for landmark `z`
- replay / prerecorded source semantics

Important nuance: a continuous session may be healthy and active while the current raw frame still reports `tracking_state = idle`. Continuous-runtime truth and per-frame pose-detected truth are different guarantees.

---

## What Still Blocks Honest Downstream Consumption Even If This Lands

This slice alone still does **not** make `aerobeat-input-camera-tracking` honestly ready because:

1. the tool repo still has to lock the public continuous frame/state semantics on top of this raw lane;
2. downstream input migration has not yet been executed against that stronger public contract;
3. `TrackingFrameAdapter.tracking_state_is_active()` still recognizes `reacquiring`, but this wave still does not define or prove that temporal state;
4. replay / `video_file` proving remains deferred.

---

## Tasks

### Task 1: Implement vendor continuous tracking runtime slice

**Bead ID:** `avmp-anm`  
**SubAgent:** `primary`  
**Role:** `coder`  
**References:** `REF-01`, `REF-02`, `REF-03`, `REF-04`, `REF-05`, `REF-06`, `REF-07`, `REF-08`, `REF-09`  
**Prompt:** In `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python`, claim bead `avmp-anm` with `bd update avmp-anm --status in_progress --json` when you start. Implement the narrowest honest continuous-tracking runtime slice described in `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/.plans/2026-05-22-continuous-tracking-runtime-slice.md`. Required scope: convert the current one-shot sampled runtime into a long-lived live-camera runtime/session that can keep producing repeated raw landmark frame updates after startup; keep raw payload fields limited to `timestamp_ms`, `source_kind`, `source_id`, `tracking_state`, `frame_size`, and `landmarks[].id/x/y/z/visibility`; make `process_active` and `tracking_active` truthfully reflect the active runtime/session; preserve honest failure semantics and repo-root ownership; update repo-local tests/docs only as needed; do not broaden into replay, public contract redesign, `reacquiring` semantics, multi-pose, or downstream consumer migration.

**Folders Created/Deleted/Modified:**
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/runtime/`
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/runtime/tests/`
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/src/`
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/.testbed/tests/`

**Files Created/Deleted/Modified:**
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/runtime/mediapipe_runtime_probe.py`
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/runtime/tests/test_mediapipe_runtime_probe.py`
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/src/MediaPipePythonRuntimeBridge.gd`
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/src/MediaPipePythonCameraTrackingBackend.gd`
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/src/MediaPipePythonConfig.gd`
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/.testbed/tests/test_mediapipe_python_runtime_bridge.gd`
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/.testbed/tests/test_mediapipe_python_backend.gd`
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/README.md`

**Status:** ✅ Complete

**Results:** Implemented the narrowest honest vendor-side continuous live-camera runtime lane in owned repo source. `runtime/mediapipe_runtime_probe.py` now supports a short-lived long-lived session mode behind `--session-dir`: startup/reconfigure launches a continuous capture+inference loop that keeps rewriting the latest runtime snapshot while the session lives, advances raw `timestamp_ms` over time, preserves the minimal raw payload shape (`timestamp_ms`, `source_kind`, `source_id`, `tracking_state`, `frame_size`, `landmarks[id/x/y/z/visibility]`), and keeps `tracking_state=idle` honest on frames with no visible pose. `src/MediaPipePythonRuntimeBridge.gd` now launches and tracks that repo-owned Python process, waits for a readable startup snapshot, exposes `poll_snapshot()` / `poll_health()` against the live session, and makes `process_active` / `tracking_active` truthfully follow the active runtime instead of the old one-shot probe truth. `src/MediaPipePythonCameraTrackingBackend.gd` now refreshes from the live bridge snapshot while running so backend-side getters observe advancing raw frames and current runtime health without broadening into tool-owned lifecycle semantics.

Repo-local proving was updated only where needed: `.testbed/tests/test_mediapipe_python_runtime_bridge.gd` now proves startup leaves the session active, repeated polls advance timestamps without `reconfigure()`, idle no-pose frames still keep `tracking_active=true` while the loop lives, and shutdown returns to honest inactive state; `.testbed/tests/test_mediapipe_python_backend.gd` now proves backend refreshes from the live bridge snapshot and reports active runtime truth. `README.md` was updated to describe the repo as a narrow continuous runtime lane instead of a one-shot sampled lane.

Validation run from repo root:
- `python3 -m py_compile runtime/mediapipe_runtime_probe.py` ✅
- `python3 -m unittest runtime.tests.test_mediapipe_runtime_probe` ✅ (`Ran 5 tests in 0.001s`, `OK`)
- `godot --headless --path .testbed --import` ✅ (completed successfully; emitted the existing non-fatal `ObjectDB instances leaked at exit` warning)
- `godot --headless --path .testbed --script addons/gut/gut_cmdln.gd -gdir=res://tests -ginclude_subdirs -gexit` ✅ (`14/14` tests passed, `122` asserts)

Scope stayed locked to vendor-owned runtime/session/inference/raw-update/health truth. Replay, public normalized contract redesign, `reacquiring`, multi-pose, richer body/head semantics, and downstream consumer migration remain deferred for later slices.

---

### Task 2: QA vendor continuous tracking runtime slice

**Bead ID:** `avmp-v65`  
**SubAgent:** `primary`  
**Role:** `qa`  
**References:** `REF-03`, `REF-04`, `REF-05`, `REF-06`, `REF-07`  
**Prompt:** In `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python`, wait until bead `avmp-v65` is unblocked, then claim it with `bd update avmp-v65 --status in_progress --json`. QA the continuous-tracking runtime slice from `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/.plans/2026-05-22-continuous-tracking-runtime-slice.md`. You must verify both repo-local automated validation and direct host live-camera proof on this machine. At minimum: prove startup leaves a real runtime/session alive; prove `process_active=true` and `tracking_active=true` while the continuous lane is active; prove two or more successive raw updates arrive with advancing timestamps without calling `reconfigure()`; prove per-frame raw payload shape stays minimal; prove shutdown returns to an honest inactive state; and confirm missing-model / unsupported-source / inference-failure paths remain explicit. Record exact commands/results/gaps and leave the auditor bead open.

**Folders Created/Deleted/Modified:**
- validation-only use of repo-local temp/test folders as needed

**Files Created/Deleted/Modified:**
- none required unless a minimal QA artifact becomes necessary

**Status:** ⏳ Pending

**Results:** Pending.

---

### Task 3: Audit vendor continuous tracking runtime slice

**Bead ID:** `avmp-lgd`  
**SubAgent:** `primary`  
**Role:** `auditor`  
**References:** `REF-01`, `REF-03`, `REF-04`, `REF-05`, `REF-06`, `REF-07`, `REF-08`, `REF-09`  
**Prompt:** In `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python`, wait until bead `avmp-lgd` is unblocked, then claim it with `bd update avmp-lgd --status in_progress --json`. Independently audit the continuous-tracking runtime slice against this plan, the diff, coder evidence, and QA evidence. Reject completion unless the real host live-camera path now sustains repeated raw updates over time rather than only a startup snapshot. Verify the runtime/session and health facts are honest, verify raw frame shape stayed minimal, verify the work remained inside vendor runtime/raw-update ownership, and verify no addon mirrors were treated as owned source. If the slice passes, close `avmp-lgd` with an honest reason; if it fails, record the exact remaining blocker without broadening scope.

**Folders Created/Deleted/Modified:**
- none required

**Files Created/Deleted/Modified:**
- none required unless a minimal audit artifact is necessary

**Status:** ⏳ Pending

**Results:** Pending.

---

## Dependency Shape

- `avmp-anm` → first executable implementation bead
- `avmp-v65` depends on `avmp-anm`
- `avmp-lgd` depends on `avmp-v65`

---

## Final Results

**Status:** ⚠️ Coder complete / pending QA + audit

**What We Built:** The vendor repo now owns a truthful narrow continuous live-camera runtime lane instead of a one-shot sampled probe. Startup/reconfigure launches a repo-owned Python session that stays alive briefly, keeps producing repeated raw landmark frame updates, and reports honest runtime/session health while that session lives. The backend now refreshes from the live bridge snapshot so vendor-side getters can observe advancing raw updates and truthful active-session state.

**Reference Check:** The coder slice satisfied the planned ownership split: this repo now owns runtime/session/inference/raw-frame-update/health truth, while public lifecycle/state/preview/source coordination and normalized frame semantics remain upstream in `aerobeat-tool-camera-tracking`.

**Commits:**
- Pending coder commit.

**Lessons Learned:** The honest temporal step was not richer semantics; it was keeping the vendor runtime alive long enough to prove repeated raw updates and active-session truth without stealing public contract ownership from the tool repo.

---

*Prepared on 2026-05-22*

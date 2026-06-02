# AeroBeat Vendor MediaPipe Python — Gesture-Testbed Replay Runtime/Source Slice

**Date:** 2026-05-22  
**Status:** Stale  
**Agent:** Cookie 🍪

---

## Goal

Add the narrowest truthful replay runtime/source support needed for `camera_gesture_testbed` to run its `mediapipe_replay` lane through `aerobeat-vendor-mediapipe-python`.

---

## Overview

The vendor repo is already green for a continuous `live_camera` runtime lane, but the downstream parity audit was blunt: replay is still absent because the current runtime bridge rejects any non-live source kind. That is the vendor-owned blocker for the replay wave.

This slice stays strict on vendor ownership. `aerobeat-vendor-mediapipe-python` should add truthful `video_file` / replay runtime behavior, keep runtime/session health honest, preserve the minimal raw frame payload contract, and avoid broadening into tool-owned public schema changes or input-owned adapter compatibility.

This plan starts after the live-only wave is green enough to avoid mixing live and replay regressions at the same time.

---

## REFERENCES

| ID | Description | Path |
| --- | --- | --- |
| `REF-01` | Cross-repo coordination plan | `/workspace/projects/openclaw-cookie/.plans/aerobeat-architecture/2026-05-22-gesture-testbed-full-parity.md` |
| `REF-02` | Downstream parity audit | `/workspace/projects/openclaw-cookie/.plans/aerobeat-architecture/2026-05-22-downstream-testbed-parity-audit.md` |
| `REF-03` | Gesture testbed script | `/workspace/projects/aerobeat/aerobeat-tool-camera-gesture-control/.testbed/scripts/camera_gesture_testbed.gd` |
| `REF-04` | Current runtime bridge | `/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/src/MediaPipePythonRuntimeBridge.gd` |
| `REF-05` | Current vendor config | `/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/src/MediaPipePythonConfig.gd` |
| `REF-06` | Current runtime entrypoint | `/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/runtime/mediapipe_runtime_probe.py` |
| `REF-07` | Continuous runtime slice already green | `/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/.plans/2026-05-22-continuous-tracking-runtime-slice.md` |
| `REF-08` | Donor/runtime parity reminder | `/workspace/projects/openclaw-cookie/.plans/aerobeat-architecture/2026-05-22-donor-mediapipe-python-sidecar-inventory.md` |

---

## Slice Boundaries

### In scope

- add truthful `source.kind = video_file` support for the gesture testbed’s replay lane
- preserve honest runtime/session health for replay sessions (`process_active`, `tracking_active`, shutdown, failure truth)
- keep raw vendor payloads minimal and source-truthful
- support the runtime/source knobs the downstream replay lane actually depends on, including fixture video path handoff
- add/update repo-local tests and host/repo proving for replay runtime behavior

### Explicitly out of scope

- tool-owned public schema redesign
- input-addon session metadata or alias compatibility
- broader donor feature parity outside the replay lane the gesture testbed actually uses

---

## Tasks

### Task 1: Implement replay runtime/source support for gesture testbed

**Bead ID:** `avmp-224`  
**SubAgent:** `primary`  
**Role:** `coder`  
**References:** `REF-01`, `REF-02`, `REF-03`, `REF-04`, `REF-05`, `REF-06`, `REF-07`, `REF-08`  
**Prompt:** In `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python`, claim bead `avmp-224` with `bd update avmp-224 --status in_progress --json` when you start. Implement the narrowest honest replay slice from `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/.plans/2026-05-22-gesture-testbed-replay-runtime-source-slice.md`. Required outcomes: add truthful `source.kind = video_file` runtime/source support for the gesture testbed, keep runtime/session health honest for replay sessions, preserve the minimal raw frame payload contract, and validate replay startup/update/shutdown/failure behavior without broadening into tool-owned public schema work or input-owned adapter compatibility. Run relevant repo-local validation, include direct replay proof if available, commit, and push before handoff unless blocked.

**Folders Created/Deleted/Modified:**
- `/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/runtime/`
- `/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/src/`
- `/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/.testbed/`
- `/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/.plans/`

**Files Created/Deleted/Modified:**
- repo-owned runtime / bridge / config / tests as needed

**Status:** ✅ Complete

**Results:** Implemented the narrowest honest vendor-owned replay slice in repo-root source. `src/MediaPipePythonRuntimeBridge.gd` now accepts `source.kind = video_file`, resolves `source.path` into a real filesystem path, and fails early with truthful `video_file_path_missing` / `video_file_missing` errors instead of routing replay through live-camera semantics. `runtime/mediapipe_runtime_probe.py` now treats replay as a first-class vendor source: one-shot replay sampling returns `source_kind = video_file` + `source_id = <video path>`, continuous replay sessions emit successive raw frame updates while frames remain, and EOF now ends the runtime cleanly with `status = idle`, `process_active = false`, `tracking_active = false` instead of surfacing a fake runtime crash. Repo-local validation was expanded in both Python and Godot test surfaces to prove replay startup/update/EOF/failure truth without broadening into tool-owned public schema work or input-owned compatibility seams. Direct fixture-backed probe proof also returned `ok = true`, `selected_camera_id = <video path>`, `source_kind = video_file`, `source_id = <video path>`, `tracking_state = tracked`, and `frame_size = {x: 640, y: 360}`. Coder handoff commit: `61de6d8` (`Add truthful replay runtime source support`). Bead `avmp-224` was then closed as ready for QA.

---

### Task 2: QA replay runtime/source support for gesture testbed

**Bead ID:** `avmp-9f2`  
**SubAgent:** `primary`  
**Role:** `qa`  
**References:** `REF-02`, `REF-03`, `REF-04`, `REF-05`, `REF-06`, `REF-07`, `REF-08`  
**Prompt:** In `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python`, wait until bead `avmp-9f2` is unblocked, then claim it with `bd update avmp-9f2 --status in_progress --json`. Independently verify the replay vendor slice. Prove `video_file` startup works honestly, prove successive replay updates arrive without pretending live-camera behavior, prove `process_active` / `tracking_active` / shutdown / failure truth remain honest, and confirm raw payload shape stayed minimal. Record exact commands/results/gaps and leave the auditor bead open.

**Folders Created/Deleted/Modified:**
- validation-only use of repo-local proving surfaces / temp fixtures as needed

**Files Created/Deleted/Modified:**
- none required unless a minimal QA artifact is necessary

**Status:** ✅ Complete

**Results:** QA passed with both repo-local automated validation and direct replay probes. Exact commands run from the repo root: `python3 -m unittest runtime.tests.test_mediapipe_runtime_probe` ✅ (`7` tests passed); `godot --headless --path .testbed --import` ✅ (successful import; no blocking errors); `godot --headless --path .testbed --script addons/gut/gut_cmdln.gd -gdir=res://tests -ginclude_subdirs -gexit` ✅ (`15/15` tests passed, `140` asserts); `godot --headless --path .testbed --script /tmp/avmp_replay_qa_bridge_smoke.gd` ✅ (bridge-level replay smoke returned honest `video_file_path_missing` and `video_file_missing` failures, accepted `source.kind = video_file` startup, emitted `source_kind = video_file` raw frames, advanced replay timestamps across successive polls, and ended at EOF with `status = idle`, `process_active = false`, `tracking_active = false`, `raw_tracking_frame = {}`); `python3 /tmp/avmp_replay_probe_qa.py` ✅ (direct probe proof returned the same truthful failure codes, one-shot replay startup with `source_kind = video_file` / `frame_size = {x: 640, y: 360}`, then a continuous replay session with two running snapshots followed by an idle EOF snapshot and exit code `0`). Ownership/boundary check: `git diff --name-only 61de6d8~1 61de6d8` showed only `.plans/2026-05-22-gesture-testbed-replay-runtime-source-slice.md`, `.testbed/tests/test_mediapipe_python_backend.gd`, `.testbed/tests/test_mediapipe_python_runtime_bridge.gd`, `runtime/mediapipe_runtime_probe.py`, `runtime/tests/test_mediapipe_runtime_probe.py`, and `src/MediaPipePythonRuntimeBridge.gd`; `git diff --name-only 61de6d8~1 61de6d8 -- .testbed/addons .testbed/.addons` returned no addon-mirror edits; `git diff --name-only 61de6d8~1 61de6d8 -- src/MediaPipePythonCameraTrackingBackend.gd` returned no backend-shell/public-lifecycle drift. QA conclusion: replay/video-file support is truthful and remains inside vendor-owned runtime/source boundaries.

---

### Task 3: Audit replay runtime/source support for gesture testbed

**Bead ID:** `avmp-7uq`  
**SubAgent:** `primary`  
**Role:** `auditor`  
**References:** `REF-01`, `REF-02`, `REF-03`, `REF-04`, `REF-05`, `REF-06`, `REF-07`, `REF-08`  
**Prompt:** In `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python`, wait until bead `avmp-7uq` is unblocked, then claim it with `bd update avmp-7uq --status in_progress --json`. Independently audit the replay vendor slice against this plan, the diff, coder evidence, and QA evidence. Close the bead only if replay runtime/source behavior is genuinely proven, health truth stayed honest, payloads stayed minimal, and the work remained fully inside vendor-owned boundaries.

**Folders Created/Deleted/Modified:**
- audit notes only if needed

**Files Created/Deleted/Modified:**
- none required unless a minimal audit artifact is necessary

**Status:** ✅ Complete

**Results:** Auditor independently verified bead readiness, claimed `avmp-7uq`, and re-ran the replay/runtime proof instead of relying on coder or QA summary alone. Exact checks: `bd show avmp-7uq --json` confirmed QA dependency `avmp-9f2` was closed before claim; `bd update avmp-7uq --status in_progress --json` claimed the audit bead; `git diff --stat 61de6d8~1 61de6d8` / `git diff --name-only 61de6d8~1 61de6d8` confirmed the implementation touched only the plan, repo-local tests, `runtime/mediapipe_runtime_probe.py`, and `src/MediaPipePythonRuntimeBridge.gd`; `python3 -m unittest runtime.tests.test_mediapipe_runtime_probe` passed (`7` tests); `godot --headless --path .testbed --import` completed; `godot --headless --path .testbed --script addons/gut/gut_cmdln.gd -gdir=res://tests -ginclude_subdirs -gexit` passed (`15/15` tests, `140` asserts). Independent direct probe evidence: a fresh Python harness against `runtime/mediapipe_runtime_probe.py` returned truthful `video_file_path_missing` and `video_file_missing` errors, returned one-shot replay success with `raw_tracking_frame.source_kind = video_file`, `source_id = <fixture path>`, and `tracking_state = tracked`, then launched a continuous replay session that produced one running snapshot, then a later running snapshot with a newer timestamp in the same session, and finally an idle EOF snapshot with `process_active = false`, `tracking_active = false`, `raw_tracking_frame = {}`, and process exit code `0`. Boundary audit: no production diff touched `src/MediaPipePythonCameraTrackingBackend.gd`, addon mirrors, or tool-owned public schema surfaces, so the slice stayed inside the planned vendor-owned runtime/source boundary. Auditor verdict: the replay runtime/source slice is genuinely complete for its planned scope, so bead `avmp-7uq` was closed.

---

## Dependency Shape

- `avmp-224` → coder implementation bead
- `avmp-9f2` depends on `avmp-224`
- `avmp-7uq` depends on `avmp-9f2`

Cross-repo coordination note: this replay vendor slice should begin after the live-only wave is audited green. The tool replay slice should start after `avmp-7uq` closes.

---

## Final Results

**Status:** ✅ Complete

**What We Built:** The vendor repo now owns the planned replay/runtime source slice needed for gesture-testbed `mediapipe_replay` startup and continuous replay truth: replay/video-file configs are accepted at the bridge, replay paths are resolved/validated before Python launch, the runtime emits truthful replay raw frames with `source_kind = video_file` and advancing timestamps while frames remain in one continuous session, and replay EOF shuts the runtime down cleanly to idle/non-active without pretending a live-camera or runtime crash.

**Reference Check:** `REF-04`, `REF-05`, and `REF-06` satisfy the planned replay/runtime source scope: vendor config shape is accepted honestly, the runtime bridge keeps replay behavior vendor-owned, and the Python runtime probe reports truthful replay source and health state. `REF-03` remains satisfied only at the vendor boundary for this slice; tool-owned public replay service semantics and downstream adapter/session compatibility still belong to later slices rather than this vendor runtime/source change.

**Commits:**
- `61de6d8` - `Add truthful replay runtime source support`

**Lessons Learned:** The replay blocker really was vendor-owned runtime/source behavior. Once the bridge and probe handle `video_file` truthfully, the remaining work cleanly stays in tool/input-owned layers instead of forcing vendor code to impersonate them. An independent audit pass mattered here because the key truth conditions were behavioral — accepted config, truthful missing-path failures, continuous session advancement, and clean EOF idle settlement — not just static diff shape.

---

*Prepared on 2026-05-22*

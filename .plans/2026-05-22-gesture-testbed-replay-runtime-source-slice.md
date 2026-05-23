# AeroBeat Vendor MediaPipe Python — Gesture-Testbed Replay Runtime/Source Slice

**Date:** 2026-05-22  
**Status:** In Progress  
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

**Results:** Implemented the narrowest honest vendor-owned replay slice in repo-root source. `src/MediaPipePythonRuntimeBridge.gd` now accepts `source.kind = video_file`, resolves `source.path` into a real filesystem path, and fails early with truthful `video_file_path_missing` / `video_file_missing` errors instead of routing replay through live-camera semantics. `runtime/mediapipe_runtime_probe.py` now treats replay as a first-class vendor source: one-shot replay sampling returns `source_kind = video_file` + `source_id = <video path>`, continuous replay sessions emit successive raw frame updates while frames remain, and EOF now ends the runtime cleanly with `status = idle`, `process_active = false`, `tracking_active = false` instead of surfacing a fake runtime crash. Repo-local validation was expanded in both Python and Godot test surfaces to prove replay startup/update/EOF/failure truth without broadening into tool-owned public schema work or input-owned compatibility seams.

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

**Status:** ⏳ Pending

**Results:** Pending.

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

**Status:** ⏳ Pending

**Results:** Pending.

---

## Dependency Shape

- `avmp-224` → coder implementation bead
- `avmp-9f2` depends on `avmp-224`
- `avmp-7uq` depends on `avmp-9f2`

Cross-repo coordination note: this replay vendor slice should begin after the live-only wave is audited green. The tool replay slice should start after `avmp-7uq` closes.

---

## Final Results

**Status:** ⚠️ Partial

**What We Built:** The vendor repo now owns the narrow replay/runtime source slice needed for gesture-testbed `mediapipe_replay` startup and continuous replay truth: replay/video-file configs are accepted at the bridge, replay paths are resolved/validated before Python launch, the runtime emits truthful replay raw frames while frames are available, and replay EOF shuts the runtime down cleanly without pretending a live-camera fault.

**Reference Check:** `REF-04` and `REF-06` are now satisfied for the planned replay/runtime source scope. `REF-03`’s replay expectations are covered only at the vendor boundary for now; tool-owned public replay service semantics and downstream adapter/session compatibility remain for later QA/audit and follow-up slices.

**Commits:**
- Pending coder commit.

**Lessons Learned:** The replay blocker really was vendor-owned runtime/source behavior. Once the bridge and probe handle `video_file` truthfully, the remaining work cleanly stays in tool/input-owned layers instead of forcing vendor code to impersonate them.

---

*Prepared on 2026-05-22*

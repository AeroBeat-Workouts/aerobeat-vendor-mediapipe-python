# AeroBeat Vendor MediaPipe Python — First Truthful Runtime Slice

**Date:** 2026-05-22  
**Status:** In Progress  
**Agent:** Cookie 🍪

---

## Goal

Turn the current `MediaPipePythonRuntimeBridge` from a declared unimplemented stub into a real but narrow vendor-owned runtime path that truthfully boots Python, reports health, and returns camera/runtime facts without taking lifecycle/public contract ownership away from `aerobeat-tool-camera-tracking`.

---

## Overview

The bootstrap seam is already landed in this repo: the README explicitly says the current state is only a bootstrap backend shell, `MediaPipePythonCameraTrackingBackend` already consumes bridge startup/shutdown/reconfigure/list-cameras snapshots, and `MediaPipePythonRuntimeBridge` is the remaining hard truth gap because it always reports `runtime_bridge_unimplemented`. That means the next honest slice is not another scaffolding pass; it is a runtime truth pass focused on making the bridge actually do something narrow and real.

The narrowest truthful slice is a **runtime bootstrap/probe lane**, not full live tracking. This repo should become capable of launching a repo-owned Python entrypoint, exchanging a small structured bootstrap result, surfacing real runtime-health facts, and enumerating available camera candidates through that vendor-owned path. The backend can then enter `running` based on a real boot/probe success instead of a fake test double, while still emitting the normalized contract-owned shape already defined upstream. The tracking-frame payload can remain empty/default in this slice because normalized lifecycle/output ownership still belongs to `aerobeat-tool-camera-tracking`; this repo only needs to provide a truthful runtime path and vendor diagnostics.

This keeps the ownership boundary clean. `aerobeat-tool-camera-tracking` stays the public owner of lifecycle semantics, signals, preview attachment, and normalized frame contract. `aerobeat-vendor-mediapipe-python` owns Python bootstrap mechanics, vendor runtime configuration, camera enumeration/probe behavior, runtime-health snapshots, and vendor error translation. If this slice uncovers public contract changes, that becomes follow-up work upstream rather than silent scope drift here.

---

## REFERENCES

| ID | Description | Path |
| --- | --- | --- |
| `REF-01` | Prior vendor bootstrap plan | `/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/.plans/2026-05-21-vendor-wrapper-bootstrap.md` |
| `REF-02` | Current runtime-bridge truth: startup/reconfigure always fail as unimplemented, list/poll return empty/unavailable | `/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/src/MediaPipePythonRuntimeBridge.gd` |
| `REF-03` | Current backend seam that already consumes startup/shutdown/reconfigure/list-cameras snapshots and maps them into upstream lifecycle/detail state | `/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/src/MediaPipePythonCameraTrackingBackend.gd` |
| `REF-04` | Current repo README truth stating bootstrap-only status and deferring the real Python process behind `MediaPipePythonRuntimeBridge` | `/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/README.md` |
| `REF-05` | Upstream camera-tracking contract shell README | `/workspace/projects/aerobeat/aerobeat-tool-camera-tracking/README.md` |
| `REF-06` | Upstream first-pass camera-tracking API sketch and ownership boundary | `/workspace/projects/aerobeat/aerobeat-tool-camera-tracking/.plans/bootstrap-architecture/CAMERA-TRACKING-API.md` |
| `REF-07` | Current repo-local backend tests proving the seam is still validated mostly through a fake bridge, not the real runtime bridge | `/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/.testbed/tests/test_mediapipe_python_backend.gd` |
| `REF-08` | Repo observation from this planning pass: there are no repo-owned Python runtime files yet; only vendored GUT docs contain `.py` files | `find . -path './.beads' -prune -o -name '*.py' -print` in `/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python` |

Use these references during implementation and audit instead of hand-waving the current seam truth.

---

## First Truthful Runtime Slice Boundaries

### In scope for this slice

- Replace the bridge's hardcoded `runtime_bridge_unimplemented` startup path with a real repo-owned bootstrap/probe flow.
- Add a repo-owned Python entrypoint plus minimal protocol/output shape that the GDScript bridge can invoke.
- Teach `MediaPipePythonRuntimeBridge` to:
  - validate runtime config needed for boot/probe
  - launch the Python entrypoint for bootstrap/probe work
  - capture stdout/stderr/exit status/timeouts into vendor health/error info
  - return truthful `startup`, `reconfigure`, `shutdown`, `list_cameras`, and `poll_health` snapshots
- Support truthful **live-camera probe** behavior first: camera enumeration, selected camera declaration, runtime availability, and runtime-health facts.
- Keep `MediaPipePythonCameraTrackingBackend` using the upstream contract shell while wiring it to the real bridge outputs.
- Add repo-local tests for the real bridge behavior, especially config validation, subprocess/probe success/failure translation, and camera/health snapshot mapping.
- Update README/docs only enough to describe the new runtime-probe truth and the still-deferred work.

### Explicitly out of scope for this slice

- Real MediaPipe live tracking inference or landmark streaming.
- A long-lived streaming subprocess protocol if a simpler truthful probe/bootstrap path suffices.
- Replacing upstream ownership of `CameraTracking` lifecycle semantics, preview attachment rules, or normalized top-level frame contract.
- Broad replay/video-file integration; if `video_file` cannot be supported honestly in this slice, fail clearly instead of pretending.
- Editing `.testbed/addons/` or other addon mirrors as owned source.

### Expected boundary after this slice

- `MediaPipePythonRuntimeBridge.startup()` can succeed or fail based on real Python/bootstrap behavior rather than a baked-in stub.
- `MediaPipePythonRuntimeBridge.list_cameras()` and `poll_health()` report truthful vendor/runtime data.
- `MediaPipePythonCameraTrackingBackend` can reach `running` from a real bridge boot/probe success while still exposing the upstream normalized contract shape.
- `get_tracking_frame()` may still be empty/default when live tracking is not yet implemented, but the runtime path itself is no longer fake.

---

## Key Scope Decisions

1. **Truthful does not mean full tracking yet.** The first honest runtime slice is a real Python bootstrap/probe lane, not end-to-end landmark streaming.
2. **Live camera first, replay later.** The bridge may explicitly reject or defer `source.kind = video_file` if supporting it now would blur the public lifecycle boundary.
3. **Health and camera facts are the primary payload.** This slice should prioritize runtime availability, process/probe diagnostics, and camera enumeration over non-truthful dummy tracking frames.
4. **Normalized contract stays upstream.** Any bridge-returned tracking-frame data remains optional/minimal and must continue to flow through the existing mapper/backend shell rather than redefining public payload semantics here.
5. **Repo-owned Python surface must become real.** This repo currently has no owned Python runtime code, so the implementation must add a small repo-root Python surface rather than keeping the bridge purely declarative.

---

## Candidate Repo Surfaces

Expected owned implementation surfaces for this slice likely include:

- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/src/MediaPipePythonRuntimeBridge.gd`
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/src/MediaPipePythonConfig.gd`
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/src/MediaPipePythonRuntimeHealth.gd`
- a new repo-root Python runtime/probe folder such as `python/` or `runtime/`
- repo-local tests under `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/.testbed/tests/`
- `README.md` if the runtime truth statement needs updating

Exact file layout is up to the coder as long as sharable owned source stays at the repo root and `.testbed/` remains only the proving surface.

---

## Tasks

### Task 1: Implement the first truthful MediaPipe runtime slice

**Bead ID:** `avmp-5wv`  
**SubAgent:** `primary`  
**Role:** `coder`  
**References:** `REF-01`, `REF-02`, `REF-03`, `REF-04`, `REF-05`, `REF-06`, `REF-07`, `REF-08`  
**Prompt:** In `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python`, claim bead `avmp-5wv` with `bd update avmp-5wv --status in_progress --json` when you start. Implement the first truthful MediaPipe runtime slice described in `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/.plans/2026-05-22-first-truthful-runtime-slice.md`. Required scope: convert `src/MediaPipePythonRuntimeBridge.gd` from the current unimplemented stub into a real repo-owned runtime bootstrap/probe path; add the minimal repo-owned Python entrypoint/protocol needed for truthful startup, reconfigure, list-cameras, and health snapshots; keep support narrow and honest, prioritizing live-camera runtime availability/camera enumeration/health over full tracking inference; preserve `aerobeat-tool-camera-tracking` ownership of lifecycle/public normalized contract semantics; and add/adjust repo-local tests plus docs only as needed. Do not edit `.testbed/addons/` or other addon mirrors as owned source. Run the relevant repo-local validation you can support and report exact files changed, commands run, and remaining deferred work. Leave downstream beads open.

**Folders Created/Deleted/Modified:**
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/src/`
- new repo-root Python/runtime folder if needed
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/.testbed/tests/`

**Files Created/Deleted/Modified:**
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/src/MediaPipePythonRuntimeBridge.gd`
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/src/MediaPipePythonConfig.gd` if runtime config defaults/validation need tightening
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/src/MediaPipePythonRuntimeHealth.gd` if health shape grows
- new repo-root Python/runtime files
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/.testbed/tests/*`
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/README.md` if the truth statement changes

**Status:** ✅ Complete

**Results:** Implemented the first truthful runtime slice in repo-owned source. `src/MediaPipePythonRuntimeBridge.gd` now resolves runtime config honestly, rejects unsupported non-`live_camera` source modes up front, launches a repo-root Python probe entrypoint, captures subprocess exit/output into runtime health/error state, returns truthful startup/reconfigure/list-cameras snapshots, and keeps shutdown/poll health statefully honest without claiming long-lived tracking inference ownership. Added repo-root Python entrypoint `runtime/mediapipe_runtime_probe.py` to enumerate camera candidates and emit structured bootstrap/health payloads; updated `src/MediaPipePythonConfig.gd` to default runtime entrypoint resolution; added `.testbed/tests/test_mediapipe_python_runtime_bridge.gd` to prove startup success, camera enumeration, unsupported-source failure, and missing-camera failure through the real bridge path; and updated `README.md` to describe the new truthful bootstrap/probe status while explicitly deferring full tracking inference. Validation run: `godot --headless --path .testbed --import`; `godot --headless --path .testbed --script addons/gut/gut_cmdln.gd -gdir=res://tests -ginclude_subdirs -gexit`; direct probe sanity check with `python3 runtime/mediapipe_runtime_probe.py --request-file <tmp.json>` returned enumerated `/dev/video*` candidates and idle runtime-health payload. References validated: `REF-02`, `REF-03`, `REF-04`, `REF-07`, `REF-08` with boundary preserved against `REF-05` and `REF-06`.

---

### Task 2: QA the first truthful MediaPipe runtime slice

**Bead ID:** `avmp-tv0`  
**SubAgent:** `primary`  
**Role:** `qa`  
**References:** `REF-02`, `REF-03`, `REF-04`, `REF-05`, `REF-06`, `REF-08`  
**Prompt:** In `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python`, wait until bead `avmp-tv0` is unblocked, then claim it with `bd update avmp-tv0 --status in_progress --json`. Verify the first truthful MediaPipe runtime slice using the highest-fidelity repo-local validation available. At minimum: confirm the real bridge no longer hardcodes `runtime_bridge_unimplemented` for normal configured startup; run the repo-local tests; exercise the runtime/probe path enough to prove camera enumeration and health snapshots come from the real bridge implementation; confirm any unsupported source modes fail honestly; and verify `.testbed/` remained the proving surface rather than the ownership surface. Record exact commands, results, and gaps. Do not close the auditor bead.

**Folders Created/Deleted/Modified:**
- validation-only use of `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/.testbed/`

**Files Created/Deleted/Modified:**
- none required unless a minimal QA artifact is needed

**Status:** ⏳ Pending

**Results:** Pending.

---

### Task 3: Audit the first truthful MediaPipe runtime slice against ownership boundaries

**Bead ID:** `avmp-gii`  
**SubAgent:** `primary`  
**Role:** `auditor`  
**References:** `REF-01`, `REF-02`, `REF-03`, `REF-04`, `REF-05`, `REF-06`, `REF-07`, `REF-08`  
**Prompt:** In `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python`, wait until bead `avmp-gii` is unblocked, then claim it with `bd update avmp-gii --status in_progress --json`. Independently audit the finished first truthful MediaPipe runtime slice against this plan, the repo diff, coder evidence, and QA evidence. Verify the bridge is now genuinely doing vendor-owned runtime/bootstrap/probe work; verify camera enumeration and runtime-health facts come from that real path; verify unsupported work is deferred honestly instead of being faked; and verify `aerobeat-tool-camera-tracking` still owns public lifecycle semantics, preview attachment behavior, and normalized contract truth. If the slice passes, close bead `avmp-gii` with an honest reason; if not, report the exact gap and keep the lane active.

**Folders Created/Deleted/Modified:**
- none required

**Files Created/Deleted/Modified:**
- none required unless a minimal audit artifact becomes necessary

**Status:** ⏳ Pending

**Results:** Pending.

---

## Dependency Shape

- `avmp-5wv` → first executable implementation bead
- `avmp-tv0` depends on `avmp-5wv`
- `avmp-gii` depends on `avmp-tv0`

This enforces the serialized coder → QA → auditor lane in the owning repo.

---

## Final Results

**Status:** ⚠️ Partial — coder complete, QA/audit pending

**What We Built:** Landed the first truthful repo-owned MediaPipe runtime slice: the bridge now launches a real Python bootstrap/probe entrypoint, reports runtime health, enumerates cameras, preserves the upstream lifecycle/normalized contract boundary, and fails unsupported source kinds honestly instead of hardcoding `runtime_bridge_unimplemented`.

**Reference Check:** `REF-02`, `REF-03`, `REF-04`, `REF-07`, and `REF-08` are now satisfied by implementation rather than planning-only scaffolding. Ownership boundaries from `REF-05` and `REF-06` remain intact because the public lifecycle/normalized contract still flows through `MediaPipePythonCameraTrackingBackend` and upstream camera-tracking APIs.

**Commits:**
- Pending coder commit for this slice.

**Lessons Learned:**
- The narrowest truthful runtime step was a short-lived Python bootstrap/probe lane, not premature long-lived tracking inference.
- Keeping probe logic in a repo-root Python surface plus stateful bridge health/error translation gives QA something real to validate without stealing upstream lifecycle ownership.
- Runtime enumeration/probe tests need a deterministic fixture path; the bridge now supports that through runtime environment overrides used only by the proving surface.

---

*Prepared on 2026-05-22*

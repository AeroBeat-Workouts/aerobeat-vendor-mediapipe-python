# AeroBeat Vendor MediaPipe Python — Minimal Real Frame Slice

**Date:** 2026-05-22  
**Status:** Draft  
**Agent:** Cookie 🍪

---

## Goal

Upgrade `aerobeat-vendor-mediapipe-python` from truthful runtime bootstrap/probe into the first truthful **sampled live-camera frame** path that emits a non-empty `raw_tracking_frame` payload without overclaiming pose/landmark inference.

---

## Overview

The current vendor runtime seam is now honest about startup, camera enumeration, selected camera choice, runtime health, and unsupported source kinds. But it still returns `raw_tracking_frame = {}` from the repo-owned Python runtime probe, which means the public tool contract can only expose a truthful default frame. The next vendor-owned gap is therefore not lifecycle or camera selection anymore. It is frame truth.

The narrowest honest move is **not** to jump straight to full MediaPipe pose inference. That would broaden scope into landmark schema decisions, tracking-state semantics, coordinate-space guarantees, confidence semantics, and downstream consumer expectations that are still intentionally unsettled. The narrowest honest move is to capture one real live-camera sample through the vendor-owned Python runtime, extract a minimal set of frame facts from that sample, and surface them as a non-empty `raw_tracking_frame`.

That keeps ownership strict. This repo owns runtime/bootstrap/config/health/camera access and vendor-side raw frame extraction. It should emit only the raw fields it can actually prove from a captured sample. The public normalized contract and default-fill behavior remain upstream in `aerobeat-tool-camera-tracking`.

---

## REFERENCES

| ID | Description | Path |
| --- | --- | --- |
| `REF-01` | Current truthful runtime/bootstrap vendor slice | `/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/.plans/2026-05-22-first-truthful-runtime-slice.md` |
| `REF-02` | Current runtime probe entrypoint still returning empty `raw_tracking_frame` | `/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/runtime/mediapipe_runtime_probe.py` |
| `REF-03` | Current vendor runtime bridge that already transports `raw_tracking_frame` through snapshots | `/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/src/MediaPipePythonRuntimeBridge.gd` |
| `REF-04` | Current vendor backend that maps raw frame payloads through the tool-facing backend seam | `/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/src/MediaPipePythonCameraTrackingBackend.gd` |
| `REF-05` | Public camera-tracking frame contract shell that still receives only the default/empty frame in this live path | `/workspace/projects/aerobeat/aerobeat-tool-camera-tracking/src/CameraTrackingFrame.gd` |
| `REF-06` | Current minimal-real-frame coordination plan | `/workspace/projects/openclaw-cookie/.plans/aerobeat-architecture/2026-05-22-minimal-real-frame-slice.md` |

---

## Slice Boundaries

### In scope for this slice

- Keep support limited to `backend = mediapipe_python` + `source.kind = live_camera`.
- Extend the repo-owned Python runtime entrypoint so a successful startup/reconfigure path also captures **one real frame sample** from the selected camera.
- Return a non-empty vendor `raw_tracking_frame` payload containing only fields that can be proven from that one captured sample.
- Preserve truthful camera/runtime health reporting and honest failure for unsupported modes or unreadable cameras.
- Add/adjust repo-local tests and docs only enough to prove the new raw-frame truth.

### Explicitly out of scope for this slice

- Full MediaPipe pose/landmark inference.
- Streaming subprocess protocols or long-lived frame pumping.
- Replay / `video_file` support.
- Public normalized contract changes owned by `aerobeat-tool-camera-tracking`.
- Claims that downstream input/gameplay consumers can already consume the result.

---

## Ownership Decisions Captured Here

### `aerobeat-vendor-mediapipe-python` owns in this slice

- opening the selected live camera through the repo-owned Python runtime path
- capturing one truthful frame sample
- deriving vendor-side sample metadata such as timestamp and pixel dimensions
- surfacing vendor-owned failure modes when sampling fails
- returning the raw frame payload through the existing bridge/backend seam

### `aerobeat-vendor-mediapipe-python` does **not** own in this slice

- public lifecycle semantics
- public preview attachment semantics
- final normalized frame guarantee language
- consumer-facing gameplay landmark expectations

---

## Proposed Minimal Raw Frame Contract From Vendor

On a successful sampled live-camera startup/reconfigure path, the vendor payload should be allowed to populate only these raw fields:

```gdscript
{
  "timestamp_ms": <capture timestamp>,
  "source_kind": "live_camera",
  "source_id": <selected camera id>,
  "tracking_state": "idle",
  "frame_size": {"x": <pixel width>, "y": <pixel height>}
}
```

Important honesty rules:

- `tracking_state` should stay non-claiming (`idle`) until this repo actually performs pose inference or other stronger tracking work.
- `confidence` should remain absent here unless the vendor can truthfully define what it means.
- `landmarks`, `skeleton`, `head_position`, `head_velocity`, and `head_orientation` should remain absent from the raw vendor payload until they are genuinely produced.
- If no real sample can be captured, fail honestly rather than fabricating dimensions/timestamps.

---

## Expected Boundary After This Slice

After this vendor slice lands, the upstream tool repo should be able to expose a public frame that is still conservative but no longer purely default/empty: it should at least carry a real sample timestamp, selected source identity, and real frame dimensions from the live camera path.

That is intentionally **not yet enough** for `aerobeat-input-camera-tracking` gameplay consumption. It only proves transport truth for a real sampled frame.

---

## Tasks

### Task 1: Implement vendor minimal real live-camera frame sampling

**Bead ID:** `avmp-58h`  
**SubAgent:** `primary`  
**Role:** `coder`  
**References:** `REF-01`, `REF-02`, `REF-03`, `REF-04`, `REF-05`, `REF-06`  
**Prompt:** In `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python`, claim bead `avmp-58h` with `bd update avmp-58h --status in_progress --json` when you start. Implement the narrowest honest minimal-real-frame slice described in `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/.plans/2026-05-22-minimal-real-frame-slice.md`. Required scope: extend the repo-owned Python runtime path so successful `live_camera` startup/reconfigure captures one truthful sample from the selected camera and returns a non-empty `raw_tracking_frame` containing only vendor-provable sample facts (at minimum real `timestamp_ms`, `source_kind`, `source_id`, and `frame_size`); preserve truthful runtime/camera health behavior and honest failures; keep sharable source at repo root and do not edit addon mirrors; add/adjust repo-local validation and docs only as needed. Do not broaden into landmark inference, replay support, or public normalized-contract redesign. Leave downstream beads open.

**Folders Created/Deleted/Modified:**
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/runtime/`
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/src/`
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/.testbed/tests/`

**Files Created/Deleted/Modified:**
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/runtime/mediapipe_runtime_probe.py`
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/src/MediaPipePythonRuntimeBridge.gd`
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/src/MediaPipePythonCameraTrackingBackend.gd` only if mapping changes are strictly needed
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/.testbed/tests/*`
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/README.md` only if the truth statement changes

**Status:** ✅ Complete

**Results:** Implemented the vendor-side minimal-real-frame slice in repo-owned source. `runtime/mediapipe_runtime_probe.py` now captures one truthful live-camera sample on successful `startup`/`reconfigure` and returns a non-empty raw vendor payload containing only vendor-provable fields: `timestamp_ms`, `source_kind`, `source_id`, `tracking_state`, and `frame_size`. The probe keeps `tracking_state = "idle"` and still omits richer pose/body/head/landmark claims. It also preserves truthful failure for unsupported source kinds, missing cameras, OpenCV import failure, camera open failure, camera read failure, and invalid sampled frame geometry.

Implementation details kept the ownership boundary intact: no public lifecycle/state/preview contract logic moved out of `aerobeat-tool-camera-tracking`; `src/MediaPipePythonRuntimeBridge.gd` stayed the existing bridge seam and was narrowed further by removing fragile shell-level `env` wrapping, with runtime override values now consumed through the existing request payload instead. Added/updated repo-local tests to prove the new raw frame truth through the real bridge path, including a fixture-backed success path and an honest sample-capture failure path. Updated `README.md` to describe the new truthful minimal sampled-frame status.

Validation run from the repo root:
- `python3 -m py_compile runtime/mediapipe_runtime_probe.py` ✅
- `godot --headless --path .testbed --import` ✅ (completed successfully; emitted the pre-existing non-fatal `ObjectDB instances leaked at exit` warning on shutdown)
- `godot --headless --path .testbed --script addons/gut/gut_cmdln.gd -gdir=res://tests -ginclude_subdirs -gexit` ✅ (`11/11` tests passed)
- direct real-camera probe: `python3 runtime/mediapipe_runtime_probe.py --request-file <startup-/dev/video0.json>` ✅ returned `ok=true` with `raw_tracking_frame.frame_size = {x: 640, y: 480}`, `source_id = /dev/video0`, `source_kind = live_camera`, `tracking_state = idle`, and truthful runtime health (`camera_accessible=true`, `tracking_active=false`, `process_active=false`)
- direct bridge smoke: `godot --headless --path .testbed --script /tmp/avmp_live_bridge_smoke.gd` ✅ returned the same non-empty raw frame through `MediaPipePythonRuntimeBridge.gd`

References validated: `REF-02`, `REF-03`, `REF-04`, and `REF-06`, with public-contract ownership intentionally still deferred per `REF-05`.

---

### Task 2: QA vendor minimal real live-camera frame sampling

**Bead ID:** `avmp-ew1`  
**SubAgent:** `primary`  
**Role:** `qa`  
**References:** `REF-02`, `REF-03`, `REF-04`, `REF-05`  
**Prompt:** In `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python`, wait until bead `avmp-ew1` is unblocked, then claim it with `bd update avmp-ew1 --status in_progress --json`. Verify the minimal-real-frame slice using the highest-fidelity repo-local validation available. At minimum: prove the runtime path no longer returns `{}` for successful live-camera `raw_tracking_frame`; prove the emitted frame facts come from a real sample rather than defaults; rerun repo-local import/tests; verify unsupported `video_file` still fails honestly; and confirm addon mirrors were not treated as owned source. Record exact commands/results/gaps and leave the auditor bead open.

**Folders Created/Deleted/Modified:**
- validation-only use of `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/.testbed/`

**Files Created/Deleted/Modified:**
- none required unless a minimal QA artifact is needed

**Status:** ⏳ Pending

**Results:** Pending.

---

### Task 3: Audit vendor minimal real live-camera frame sampling

**Bead ID:** `avmp-mtv`  
**SubAgent:** `primary`  
**Role:** `auditor`  
**References:** `REF-01`, `REF-02`, `REF-03`, `REF-04`, `REF-05`, `REF-06`  
**Prompt:** In `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python`, wait until bead `avmp-mtv` is unblocked, then claim it with `bd update avmp-mtv --status in_progress --json`. Independently audit the minimal-real-frame slice against this plan, the repo diff, coder evidence, and QA evidence. Verify the repo now truthfully captures a real sample frame through the vendor runtime path; verify the emitted raw frame only contains facts the vendor can actually prove; verify pose inference and richer tracking fields are still deferred honestly; and verify ownership boundaries remain intact. If the slice passes, close bead `avmp-mtv` with an honest reason; if not, report the exact gap and keep the lane active.

**Folders Created/Deleted/Modified:**
- none required

**Files Created/Deleted/Modified:**
- none required unless a minimal audit artifact becomes necessary

**Status:** ⏳ Pending

**Results:** Pending.

---

## Dependency Shape

- `avmp-58h` → first executable implementation bead
- `avmp-ew1` depends on `avmp-58h`
- `avmp-mtv` depends on `avmp-ew1`

---

## Final Results

**Status:** ⚠️ Partial / coder complete, QA + audit pending

**What We Built:** The repo now has the first truthful vendor-owned sampled-frame path for `backend = mediapipe_python` + `source.kind = live_camera`. Successful startup/reconfigure captures one real camera sample through the existing vendor runtime path and returns a minimal non-empty raw frame without overclaiming richer tracking semantics.

**Reference Check:** Coder implementation satisfies the vendor-owned runtime/raw-frame scope in `REF-01` through `REF-04` and `REF-06` while intentionally preserving public lifecycle/state/preview/normalized contract ownership upstream per `REF-05`.

**Commits:**
- Pending coder commit.

**Lessons Learned:** The next honest vendor step after truthful bootstrap was not “pretend tracking exists.” It was “capture one real sample, expose only the facts we can prove, and leave everything else explicitly default/deferred.”

---

*Prepared on 2026-05-22*

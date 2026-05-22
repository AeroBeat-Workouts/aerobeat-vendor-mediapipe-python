# AeroBeat Vendor MediaPipe Python — Minimal Real Landmark Slice

**Date:** 2026-05-22  
**Status:** In Progress  
**Agent:** Cookie 🍪

---

## Goal

Upgrade `aerobeat-vendor-mediapipe-python` from truthful sampled live-camera frame metadata into the first truthful **sampled live-camera landmark payload** that emits raw pose landmarks without overclaiming continuous tracking.

---

## Overview

The completed minimal-real-frame slice proved an important truth boundary: this repo can now select a real camera, capture one real sample on `startup` / `reconfigure`, and return a non-empty `raw_tracking_frame` containing real timestamp/source/frame-size facts. But the payload is still spatially empty. There are no landmarks yet, which means the upstream tool repo still has no honest way to expose real pose content.

The next narrowest honest move is still **sample-based**, not stream-based. This repo should extend the existing sampled live-camera path so that the same truthful captured frame is also passed through the narrowest real MediaPipe pose inference path available, then return only the raw landmark facts that the vendor runtime can actually prove from that one sampled frame. That keeps the scope honest: one real frame, one real inference result, one raw landmark payload.

This slice must keep ownership boundaries strict. `aerobeat-vendor-mediapipe-python` owns runtime dependency truth, frame capture, MediaPipe invocation, raw-landmark extraction, raw inference-state truth, and honest runtime/health failures. It does **not** own the public normalized frame contract, public preview/lifecycle semantics, gameplay coordinate normalization, or downstream input readiness claims.

---

## REFERENCES

| ID | Description | Path |
| --- | --- | --- |
| `REF-01` | Completed truthful sampled-frame vendor slice | `/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/.plans/2026-05-22-minimal-real-frame-slice.md` |
| `REF-02` | Current vendor runtime probe that now captures one real sample but still emits no landmarks | `/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/runtime/mediapipe_runtime_probe.py` |
| `REF-03` | Current runtime bridge that already transports `raw_tracking_frame` snapshots | `/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/src/MediaPipePythonRuntimeBridge.gd` |
| `REF-04` | Current raw-frame mapper seam into the tool contract | `/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/src/MediaPipePythonFrameMapper.gd` |
| `REF-05` | Completed tool minimal-real-frame normalization slice | `/workspace/projects/aerobeat/aerobeat-tool-camera-tracking/.plans/2026-05-22-minimal-real-frame-normalization-slice.md` |
| `REF-06` | Public frame shell that will receive the next landmark payload upstream | `/workspace/projects/aerobeat/aerobeat-tool-camera-tracking/src/CameraTrackingFrame.gd` |
| `REF-07` | Current input tracking-frame adapter expectations | `/workspace/projects/aerobeat/aerobeat-input-camera-tracking/src/tracking_frame_adapter.gd` |
| `REF-08` | Landmark-driven input provider still downstream of stronger upstream truth | `/workspace/projects/aerobeat/aerobeat-input-camera-tracking/src/providers/camera_tracking_provider.gd` |

---

## Slice Boundaries

### In scope for this slice

- Keep support limited to `backend = mediapipe_python` + `source.kind = live_camera`.
- Extend the repo-owned Python runtime entrypoint so successful `startup` / `reconfigure` captures one truthful frame sample **and** runs the narrowest real pose-landmark inference pass on that sampled frame.
- Return a raw vendor `raw_tracking_frame` payload that includes only vendor-provable fields from that single sample, including landmark data when a pose is actually detected.
- Keep runtime/health truth honest for missing MediaPipe, missing OpenCV, unreadable cameras, inference failures, and no-pose-detected cases.
- Add/adjust repo-local tests and docs only enough to prove the new raw landmark truth.

### Explicitly out of scope for this slice

- Long-lived tracking subprocesses or frame streaming.
- Replay / `video_file` support.
- Multi-pose support.
- Public coordinate normalization or preview semantics owned by `aerobeat-tool-camera-tracking`.
- Skeleton/body graph synthesis, head pose, or consumer gameplay promises.

---

## Ownership Decisions Captured Here

### `aerobeat-vendor-mediapipe-python` owns in this slice

- importing/configuring the MediaPipe runtime dependency truthfully
- running pose-landmark inference against the sampled live-camera frame
- deciding raw snapshot-level inference truth such as whether this sampled frame produced landmarks
- extracting raw landmark entries from MediaPipe results
- surfacing honest failure or degraded-state facts when runtime dependencies or inference are unavailable
- preserving truthful runtime health while still reporting `process_active=false` / `tracking_active=false` for this sample-only slice

### `aerobeat-vendor-mediapipe-python` does **not** own in this slice

- public lifecycle/state/preview semantics
- the public normalized landmark schema consumed by downstream tools
- gameplay-space coordinate transforms for consumers
- downstream detector readiness claims

---

## Proposed Minimal Raw Landmark Contract From Vendor

On a successful sampled live-camera startup/reconfigure path, the vendor payload may now populate only these raw fields when they are actually proven:

```gdscript
{
  "timestamp_ms": <capture timestamp>,
  "source_kind": "live_camera",
  "source_id": <selected camera id>,
  "tracking_state": "tracked" | "idle",
  "frame_size": {"x": <pixel width>, "y": <pixel height>},
  "landmarks": [
    {
      "id": <mediapipe pose landmark id>,
      "x": <raw normalized x>,
      "y": <raw normalized y>,
      "z": <raw mediapipe z>,
      "visibility": <raw mediapipe visibility>
    }
  ]
}
```

Important honesty rules:

- `tracking_state = "tracked"` is only allowed when this sampled frame actually produced a non-empty landmark result.
- `tracking_state = "idle"` remains the honest state for successful sample capture with no detected pose.
- `reacquiring` and richer temporal states remain out of scope because there is still no continuous stream in this slice.
- `confidence`, `skeleton`, `head_position`, `head_velocity`, and `head_orientation` remain absent until they are genuinely produced and defined.
- Landmark coordinates in this raw vendor payload are still vendor/raw inference output, not yet the tool-owned public gameplay-space contract.

---

## Guaranteed vs Provisional Truth After This Slice

### Guaranteed raw vendor facts after this slice

For successful `live_camera` startup/change in this repo:

- `timestamp_ms`, `source_kind`, `source_id`, and `frame_size.{x,y}` still come from a real sampled frame.
- `landmarks` is now a real raw array field in the vendor payload rather than an implied future concept.
- each emitted raw landmark entry is guaranteed to include numeric `id`, `x`, `y`, `z`, and `visibility`.
- `tracking_state` is snapshot-truthful at the sample level: `tracked` when landmarks are emitted for the sample, otherwise `idle`.

### Still provisional / intentionally deferred here

- continuous tracking semantics across time
- `reacquiring` / `lost` style temporal states
- multi-pose guarantees
- confidence aggregation semantics beyond per-landmark visibility
- skeleton/head/body higher-level derived outputs
- public coordinate-space meaning for consumers

---

## Remaining Blockers Even If This Vendor Slice Lands

This slice alone does **not** make downstream gameplay consumption honest yet because:

1. it is still a **sample-only** path (`startup` / `reconfigure` snapshot), not a streaming tracking path
2. public landmark normalization still belongs upstream in `aerobeat-tool-camera-tracking`
3. downstream input migration still needs an execution wave after the upstream public contract is stronger

---

## Tasks

### Task 1: Implement vendor minimal real landmark sampling

**Bead ID:** `avmp-r1z`  
**SubAgent:** `primary`  
**Role:** `coder`  
**References:** `REF-01`, `REF-02`, `REF-03`, `REF-04`, `REF-05`, `REF-06`, `REF-07`, `REF-08`  
**Prompt:** In `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python`, claim bead `avmp-r1z` with `bd update avmp-r1z --status in_progress --json` when you start. Implement the narrowest honest minimal-real-landmark slice described in `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/.plans/2026-05-22-minimal-real-landmark-slice.md`. Required scope: extend the repo-owned Python runtime path so successful `live_camera` startup/reconfigure captures one truthful sample frame and runs the narrowest real MediaPipe landmark inference pass on that sample; return a raw non-empty landmark payload only when the sample actually produces landmarks; keep runtime/dependency/camera/inference health truthful; preserve `process_active=false` / `tracking_active=false` for this sample-only slice; keep sharable source at repo root and do not edit addon mirrors; add/adjust repo-local validation and docs only as needed. Do not broaden into streaming, replay support, public contract redesign, or downstream consumer migration. Leave downstream beads open.

**Folders Created/Deleted/Modified:**
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/runtime/`
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/.testbed/tests/`

**Files Created/Deleted/Modified:**
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/runtime/mediapipe_runtime_probe.py`
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/.testbed/tests/test_mediapipe_python_runtime_bridge.gd`
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/.testbed/tests/test_mediapipe_python_backend.gd`
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/README.md`

**Status:** ✅ Complete

**Results:** Implemented the vendor-side minimal-real-landmark slice in `runtime/mediapipe_runtime_probe.py` without broadening into streaming or public-contract ownership. The sampled live-camera startup/reconfigure path now runs one sampled landmark inference pass and only marks `raw_tracking_frame.tracking_state = "tracked"` when a non-empty landmark array truly exists for that sampled frame; otherwise it stays `"idle"`. The raw vendor payload now truthfully emits only `landmarks[].id`, `x`, `y`, `z`, and `visibility` when landmarks exist, while leaving richer fields such as `confidence`, `skeleton`, `head_position`, `head_velocity`, and `head_orientation` absent.

Implemented honest failure handling for inference-stage problems as part of the same vendor-owned runtime seam: fixture-backed proving now covers truthful no-pose idle behavior and truthful landmark-inference failure behavior, while the real runtime path now fails honestly on missing MediaPipe import, OpenCV conversion/import problems, or MediaPipe inference exceptions after a real sample frame is captured. `process_active=false` and `tracking_active=false` remain preserved for this sample-only slice.

Updated repo-local tests in `.testbed/tests/test_mediapipe_python_runtime_bridge.gd` and `.testbed/tests/test_mediapipe_python_backend.gd` to prove tracked-vs-idle raw snapshot truth, raw landmark field shape, truthful inference failure handling, and backend contract transport. Updated `README.md` to reflect that the repo now owns one sampled-frame landmark inference pass but still does not claim continuous tracking.

---

### Task 2: QA vendor minimal real landmark sampling

**Bead ID:** `avmp-pn1`  
**SubAgent:** `primary`  
**Role:** `qa`  
**References:** `REF-02`, `REF-03`, `REF-04`, `REF-07`  
**Prompt:** In `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python`, wait until bead `avmp-pn1` is unblocked, then claim it with `bd update avmp-pn1 --status in_progress --json`. Verify the minimal-real-landmark slice using the highest-fidelity repo-local validation available. At minimum: prove the runtime path now emits raw landmarks when the sampled frame actually contains a pose; prove `tracking_state` is only `tracked` when landmarks are present and otherwise stays honest; rerun repo-local import/tests; verify missing MediaPipe / missing OpenCV / unsupported `video_file` / no-pose / bad-camera paths stay truthful; and confirm addon mirrors were not treated as owned source. Record exact commands/results/gaps and leave the auditor bead open.

**Folders Created/Deleted/Modified:**
- validation-only use of `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/.testbed/`

**Files Created/Deleted/Modified:**
- none required unless a minimal QA artifact becomes necessary

**Status:** ⏳ Pending

**Results:** Pending.

---

### Task 3: Audit vendor minimal real landmark sampling

**Bead ID:** `avmp-3r1`  
**SubAgent:** `primary`  
**Role:** `auditor`  
**References:** `REF-01`, `REF-02`, `REF-03`, `REF-04`, `REF-05`, `REF-06`, `REF-07`, `REF-08`  
**Prompt:** In `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python`, wait until bead `avmp-3r1` is unblocked, then claim it with `bd update avmp-3r1 --status in_progress --json`. Independently audit the minimal-real-landmark slice against this plan, the repo diff, coder evidence, and QA evidence. Verify the repo now truthfully extracts raw landmarks from the sampled live-camera frame; verify `tracking_state` is not overclaimed beyond sample-level truth; verify raw landmark fields are limited to facts this repo can actually prove; and verify ownership boundaries remain intact. If the slice passes, close bead `avmp-3r1` with an honest reason; if not, report the exact gap and keep the lane active.

**Folders Created/Deleted/Modified:**
- none required

**Files Created/Deleted/Modified:**
- none required unless a minimal audit artifact becomes necessary

**Status:** ⏳ Pending

**Results:** Pending.

---

## Dependency Shape

- `avmp-r1z` → first executable implementation bead
- `avmp-pn1` depends on `avmp-r1z`
- `avmp-3r1` depends on `avmp-pn1`

---

## Final Results

**Status:** ⚠️ Planned / ready for execution

**What We Built:** A repo-local execution plan plus serialized coder → QA → auditor beads for the first truthful raw landmark payload slice in `aerobeat-vendor-mediapipe-python`.

**Reference Check:** This plan preserves the ownership boundary from the completed sampled-frame wave: the vendor repo grows runtime/dependency/inference/raw-landmark truth, while public normalized contract work stays upstream.

**Commits:**
- Pending.

**Lessons Learned:** The next honest landmark move is still restraint. This repo should prove “one real sampled frame can produce one real raw landmark payload” before anyone claims continuous tracking or gameplay readiness.

---

*Prepared on 2026-05-22*

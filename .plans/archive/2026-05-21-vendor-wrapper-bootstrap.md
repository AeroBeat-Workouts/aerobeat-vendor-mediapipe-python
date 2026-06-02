# AeroBeat Vendor MediaPipe Python — Vendor-Wrapper Bootstrap

**Date:** 2026-05-21  
**Status:** Stale  
**Agent:** Cookie 🍪

---

## Goal

Create the first execution-ready repo-local plan and serialized Beads for turning this repo from a fresh tool template into the vendor-specific MediaPipe Python wrapper/backend home behind the `aerobeat-tool-camera-tracking` contract.

---

## Overview

This repo is still effectively a fresh AeroBeat tool template, so the first safe slice is not a full MediaPipe runtime integration. Instead, the first implementation slice should establish the repo-root vendor-wrapper scaffolding that can plug into `aerobeat-tool-camera-tracking` without redefining that repo's lifecycle contract. The shared camera-tracking singleton should remain the public owner of lifecycle semantics, preview ownership, and normalized frame shape; this repo should become the home for vendor-specific startup/shutdown mechanics, config translation, camera enumeration, raw runtime health reporting, and frame normalization inputs.

The implementation should therefore aim for a thin-but-real backend seam rather than a second singleton. The slice should replace template-only naming and tests with vendor-wrapper-specific source and tests at the repo root, use `.testbed/` only as the proving surface, and avoid editing `.testbed/addons/` as if it were owned code. If local dependency refresh is needed, use `/home/derrick/.openclaw/workspace/scripts/godotenv-sync` and then normal GodotEnv restore flow.

Execution is serialized through repo-local Beads. The coder lane creates the first backend bootstrap slice, QA validates it through `.testbed/`, and the auditor independently checks that the boundary with `aerobeat-tool-camera-tracking` stayed clean and that vendor-owned concerns remained local to this repo.

---

## REFERENCES

| ID | Description | Path |
| --- | --- | --- |
| `REF-01` | Current repo template truth and `.testbed/` workflow | `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/README.md` |
| `REF-02` | Current template singleton stub still present in this repo | `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/src/AeroToolManager.gd` |
| `REF-03` | Current repo-local test baseline showing template-only coverage | `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/.testbed/tests/test_AeroToolManager.gd` |
| `REF-04` | Current plugin metadata still branded as tool template | `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/plugin.cfg` |
| `REF-05` | Upstream camera-tracking contract shell README | `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-tool-camera-tracking/README.md` |
| `REF-06` | Upstream first-pass camera-tracking API sketch | `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-tool-camera-tracking/.plans/bootstrap-architecture/CAMERA-TRACKING-API.md` |
| `REF-07` | Upstream contract-shell execution plan for comparison and handoff shape | `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-tool-camera-tracking/.plans/2026-05-21-contract-shell-slice.md` |

Use these references during implementation and audit instead of hand-waving the contract boundary from memory.

---

## First Safe Implementation Slice Boundaries

The first implementation slice should do **just enough** to make this repo the obvious vendor-wrapper home without pretending the real MediaPipe runtime is already solved.

### In scope for slice 1

- Replace template-only naming/surfaces with vendor-wrapper-specific repo-root code.
- Introduce a backend-facing seam that targets the upstream `CameraTrackingBackend` expectations from `REF-05` and `REF-06`.
- Add vendor-owned config translation helpers that map the upstream camera-tracking config shape into repo-local MediaPipe Python/runtime settings.
- Add vendor-owned camera-enumeration and runtime-health seams/stubs so later subprocess/native integration has a real home.
- Add a repo-local frame normalization mapper/stub that explicitly targets the upstream normalized tracking-frame shape rather than leaking raw vendor payloads directly.
- Add or replace repo-local tests in `.testbed/tests/` that prove the boundary and translation behavior.

### Explicitly out of scope for slice 1

- Shipping the full real Python subprocess/runtime orchestration if that would force re-inventing the tool-owned lifecycle state machine.
- Duplicating the `CameraTracking` singleton contract or redefining its public signals/state model here.
- Treating `.testbed/addons/` as an owned edit surface.
- Editing unrelated `/addons/` mirrors or consumer-installed copies.
- Broad replay/video-player work that belongs to `aerobeat-tool-camera-tracking` coordination.

### Expected boundary after slice 1

- `aerobeat-tool-camera-tracking` remains the public lifecycle and normalized-output owner.
- `aerobeat-vendor-mediapipe-python` becomes the vendor-specific backend/wrapper home that can later power the contract shell through a clean seam.
- Raw vendor/runtime details stay local here; only normalized and contract-approved shapes cross outward.

---

## Repo Conventions

- Use `.testbed/` as the canonical proving surface, not as the package ownership boundary.
- Keep sharable source at the repo root under `src/` or other repo-root-owned folders.
- Do **not** edit `/addons/` mirrors as if they are source of truth, including `.testbed/addons/`.
- If dependencies or linked workspace packages need refresh, use `/home/derrick/.openclaw/workspace/scripts/godotenv-sync` before normal restore/install flow.
- Preserve the root-owned package shape so downstream consumers can install from `/` cleanly.

---

## Coordination Notes with `aerobeat-tool-camera-tracking`

- Plan against upstream contract commit `25f52da` as the current public boundary.
- Treat the upstream repo as the owner of:
  - lifecycle/state semantics
  - public signals
  - preview attachment ownership model
  - normalized tracking-frame contract
  - public config shape consumed by downstream callers
- Treat this repo as the owner of:
  - MediaPipe Python process/bootstrap details
  - vendor-specific startup/shutdown mechanics
  - config translation into vendor/runtime knobs
  - camera enumeration specifics
  - vendor health checks and raw diagnostics
  - raw frame-to-normalized-frame mapping inputs
- If the vendor wrapper needs new capabilities that affect public lifecycle or payload semantics, coordinate back into `aerobeat-tool-camera-tracking` instead of silently expanding this repo's public contract.
- Do not duplicate tool-owned lifecycle semantics here; if state transitions are needed locally, they should support the backend implementation and roll up into the upstream contract rather than competing with it.

---

## Tasks

### Task 1: Implement first vendor-wrapper bootstrap slice behind the contract shell

**Bead ID:** `avmp-294`  
**SubAgent:** `primary`  
**Role:** `coder`  
**References:** `REF-01`, `REF-02`, `REF-03`, `REF-04`, `REF-05`, `REF-06`, `REF-07`  
**Prompt:** In `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python`, claim bead `avmp-294` with `bd update avmp-294 --status in_progress --json` when you start. Implement the first safe vendor-wrapper bootstrap slice for this repo behind the `aerobeat-tool-camera-tracking` contract from commit `25f52da`. Required scope: replace template-only repo-root surfaces with vendor-wrapper-specific code; add backend-facing scaffolding that clearly targets the upstream camera-tracking contract without duplicating singleton lifecycle ownership; add vendor-owned config translation helpers, camera-enumeration seam/stub, runtime health seam/stub, and normalized-frame mapping seam/stub; add or replace repo-local tests under `.testbed/tests/`; and update repo metadata/docs only as needed to match the new vendor-wrapper truth. Keep sharable implementation code/assets at the repo root, use `.testbed/` only as the proving surface, do not treat `.testbed/addons/` or other `/addons/` mirrors as owning edit surfaces, and use `/home/derrick/.openclaw/workspace/scripts/godotenv-sync` if dependency refresh is needed. Run the relevant repo-local validation you can support, and report exact files changed plus commands/results. Leave downstream beads open.

**Folders Created/Deleted/Modified:**
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/src/`
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/.testbed/tests/`
- optional repo-root support folders if needed for vendor-wrapper source organization

**Files Created/Deleted/Modified:**
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/src/*`
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/.testbed/tests/*`
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/plugin.cfg` if branding/entrypoint metadata must change
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/README.md` if repo truth/usage notes must change

**Status:** ⏳ Pending

**Results:** Pending.

---

### Task 2: QA the vendor-wrapper bootstrap slice in `.testbed`

**Bead ID:** `avmp-p1m`  
**SubAgent:** `primary`  
**Role:** `qa`  
**References:** `REF-01`, `REF-03`, `REF-05`, `REF-06`  
**Prompt:** In `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python`, wait until bead `avmp-p1m` is unblocked, then claim it with `bd update avmp-p1m --status in_progress --json`. Verify the vendor-wrapper bootstrap slice using the highest-fidelity repo-local validation available in `.testbed/`. At minimum, confirm imports are healthy, run the relevant automated tests for the vendor-wrapper scaffolding and config/frame-boundary helpers, and verify the implementation did not rely on editing `.testbed/addons/` or other `/addons/` mirrors as owned source. If dependency refresh is needed, use or note `/home/derrick/.openclaw/workspace/scripts/godotenv-sync`. Record exact commands, results, and any gaps. Do not close the auditor bead.

**Folders Created/Deleted/Modified:**
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/.testbed/` (validation-only; no owning-source edits inside `addons/`)

**Files Created/Deleted/Modified:**
- None required; QA should prefer evidence gathering over source edits.

**Status:** ⏳ Pending

**Results:** Pending.

---

### Task 3: Audit the vendor-wrapper bootstrap slice against contract and QA evidence

**Bead ID:** `avmp-b9n`  
**SubAgent:** `primary`  
**Role:** `auditor`  
**References:** `REF-01`, `REF-02`, `REF-03`, `REF-04`, `REF-05`, `REF-06`, `REF-07`  
**Prompt:** In `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python`, wait until bead `avmp-b9n` is unblocked, then claim it with `bd update avmp-b9n --status in_progress --json`. Independently audit the finished vendor-wrapper bootstrap slice against this plan, the repo diff, the tests, and QA evidence. Verify the slice really established this repo as the vendor-specific backend/wrapper home for MediaPipe Python without duplicating `aerobeat-tool-camera-tracking` lifecycle semantics. Specifically verify vendor-owned startup/shutdown/config translation/health seams exist here, normalized output targets the upstream contract from commit `25f52da`, sharable source stayed at the repo root, `.testbed/` remained only the proving surface, and no `/addons/` mirrors were treated as owned source. If the slice passes, close bead `avmp-b9n`; if not, report the exact gap and keep the lane active.

**Folders Created/Deleted/Modified:**
- None required.

**Files Created/Deleted/Modified:**
- None required; audit should only add files if a minimal audit artifact becomes necessary.

**Status:** ⏳ Pending

**Results:** Pending.

---

## Dependency Shape

- `avmp-294` → first executable implementation bead
- `avmp-p1m` depends on `avmp-294`
- `avmp-b9n` depends on `avmp-p1m`

This enforces the serialized coder → QA → auditor lane in the owning repo.

---

## Final Results

**Status:** ⚠️ Partial

**What We Built:** Created the first execution-ready repo-local vendor-wrapper bootstrap plan and the serialized repo-local Beads for coder → QA → auditor execution. Implementation itself has not started yet.

**Reference Check:** Planning aligns to the current repo template state in `REF-01` through `REF-04` and to the upstream camera-tracking contract shell in `REF-05` through `REF-07`.

**Commits:**
- None in this planning pass.

**Lessons Learned:**
- This repo is still at the untouched template stage: template branding, `AeroToolManager`, and template-only tests remain in place.
- Despite the repo name, there is currently no tracked Python implementation surface in the repo root yet; the first slice must create the vendor-wrapper home before it can reorganize real runtime code.
- Repo-local Beads required initialization before planning could create execution beads.

---

*Prepared on 2026-05-21*

# AeroBeat Vendor MediaPipe Python — Host MediaPipe Compatibility Repair

**Date:** 2026-05-22  
**Status:** Complete  
**Agent:** Cookie 🍪

---

## Goal

Repair the vendor runtime so the actual host-installed MediaPipe package shape on this machine can truthfully produce a sampled live-camera landmark payload, instead of failing after frame capture because the runtime assumes the legacy `mediapipe.solutions` API.

---

## Overview

The failed audit narrowed the real blocker cleanly. The repo already proves fixture-backed landmark transport, truthful no-pose behavior, and honest inference failure reporting. What it does **not** yet prove is a successful non-fixture landmark inference pass on this host. The blocker is not camera capture; `/dev/video0` can be sampled. The blocker is the inference adapter immediately after capture.

On this machine, `python3` imports `mediapipe 0.10.32` from `/home/derrick/.local/lib/python3.14/site-packages/mediapipe`, and that package exposes only `Image`, `ImageFormat`, and `tasks` at the top level. It does **not** expose `mediapipe.solutions`. The current runtime implementation in `runtime/mediapipe_runtime_probe.py` hard-requires `mp.solutions.pose.Pose(static_image_mode=True)`, so the live host path fails honestly with `mediapipe_inference_failed` before any real landmark payload can be emitted.

The narrowest honest repair is therefore a **vendor code compatibility repair for the installed tasks-era package shape**, not an environment-only workaround. An environment downgrade would require changing interpreter/package strategy on a Python 3.14 host where `pip index versions mediapipe` currently exposes only `0.10.30+`, which is already in the tasks-only line. That is a broader host packaging intervention than this slice needs. The repair wave should instead teach the runtime to support the actual installed package shape and make the model-asset requirement explicit and repo-owned/configurable so QA can prove a real host sampled landmark payload end to end.

---

## REFERENCES

| ID | Description | Path |
| --- | --- | --- |
| `REF-01` | Coordination plan that spawned this repair wave | `/workspace/projects/openclaw-cookie/.plans/aerobeat-architecture/2026-05-22-vendor-mediapipe-host-compat-repair.md` |
| `REF-02` | Failed vendor landmark audit and current bead chain | `/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/.plans/2026-05-22-minimal-real-landmark-slice.md` |
| `REF-03` | Current runtime implementation that hard-requires `mediapipe.solutions.pose.Pose` | `/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/runtime/mediapipe_runtime_probe.py` |
| `REF-04` | Current Godot bridge/runtime seam | `/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/src/MediaPipePythonRuntimeBridge.gd` |
| `REF-05` | Host package inspection performed for this planning pass (`mediapipe 0.10.32`, no `solutions`, has `tasks`) | planning evidence from 2026-05-22 task execution |
| `REF-06` | `pip index versions mediapipe` on this host only offers `0.10.30+` for the current interpreter line | planning evidence from 2026-05-22 task execution |
| `REF-07` | MediaPipe Tasks pose landmarker docs require an explicit `.task` model asset path | https://developers.google.com/mediapipe/solutions/vision/pose_landmarker/python |

---

## Blocker Truth

1. **Real frame capture is already working enough to reach inference.** The failure happens after a truthful sampled frame is captured from the live camera.
2. **The installed MediaPipe package shape is tasks-era, not legacy-solutions-era.** `import mediapipe as mp` succeeds, but `hasattr(mp, "solutions") == False` and `hasattr(mp, "tasks") == True`.
3. **The current runtime path assumes the wrong API surface for this host.** It directly calls `mp.solutions.pose.Pose(...)` and therefore cannot succeed on the installed package.
4. **Tasks-era pose inference requires a model asset.** A narrow compatibility repair must account for a `.task` pose landmarker asset path/bundle instead of pretending the package alone is enough.
5. **This is not honestly complete until the non-fixture host path returns landmarks.** Fixture-backed proof and failure truth are valuable, but the slice remains blocked until a real sampled live-camera request on this host returns `ok=true` with a non-empty `raw_tracking_frame.landmarks` array.

---

## Scope Decisions

### In scope

- Keep the repair inside `aerobeat-vendor-mediapipe-python`.
- Adapt the runtime probe to support the actual installed MediaPipe API shape on this machine.
- Preserve honest fallback behavior if neither legacy `solutions` nor tasks-based pose inference is usable.
- Introduce the narrowest repo-owned/configurable model-asset handling required for tasks-based pose inference.
- Add/adjust repo-local tests and docs only enough to prove the compatibility repair and the real host success path.

### Out of scope

- Replay / `video_file` support.
- Continuous tracking or long-lived subprocesses.
- Consumer/public contract redesign in upstream tool repos.
- Host-wide Python version replacement, alternate interpreter bootstrapping, or broad packaging redesign unless the code repair proves impossible.

---

## Repair Strategy

1. **Runtime compatibility branch**
   - Detect the available MediaPipe API shape at runtime.
   - If `mp.solutions.pose.Pose` exists, keep supporting that path.
   - If only `mediapipe.tasks.python.vision.PoseLandmarker` is available, use that path instead.
2. **Model asset truth**
   - Add a narrow runtime configuration seam for the required pose landmarker `.task` asset path or repo-owned bundled asset.
   - Fail honestly with a specific missing-model error if the tasks path is selected but no usable model asset is available.
3. **Raw payload continuity**
   - Keep the existing raw landmark output contract (`id/x/y/z/visibility`) and snapshot-truthful `tracking_state` semantics.
4. **Host-proof validation**
   - QA must verify both fixture-backed compatibility coverage and one direct host live-camera probe using the actual installed package shape.
   - Auditor must reject completion if host validation still depends only on fixtures or shims.

---

## Success Criteria

The vendor compatibility slice is only complete when all of the following are true:

1. A direct non-fixture request against the actual host live-camera path on this machine returns `ok=true`.
2. That successful response includes a non-empty `raw_tracking_frame.landmarks` array with entries limited to `id`, `x`, `y`, `z`, and `visibility`.
3. `raw_tracking_frame.tracking_state` is `"tracked"` only when that non-empty landmark array exists, and otherwise remains `"idle"`.
4. Repo-local automated validation still passes.
5. Missing-model / unsupported-package / inference-failure paths remain explicit and honest.
6. The repair stays within vendor runtime ownership and does not broaden into tool/consumer migration work.

---

## Tasks

### Task 1: Implement host MediaPipe compatibility repair

**Bead ID:** `avmp-i8g`  
**SubAgent:** `primary`  
**Role:** `coder`  
**References:** `REF-01`, `REF-02`, `REF-03`, `REF-04`, `REF-05`, `REF-06`, `REF-07`  
**Prompt:** In `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python`, claim bead `avmp-i8g` with `bd update avmp-i8g --status in_progress --json` when you start. Repair the runtime for the actual installed host MediaPipe package shape described in `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/.plans/2026-05-22-host-mediapipe-compat-repair.md`. Keep the slice narrow: adapt `runtime/mediapipe_runtime_probe.py` so sampled live-camera inference can work on a tasks-era MediaPipe package that has `mediapipe.tasks` but no `mediapipe.solutions`; preserve support for the legacy path if it exists; add the narrowest honest repo-owned/configurable `.task` model-asset handling required for `PoseLandmarker`; keep failure truth explicit when model/API/inference requirements are missing; update repo-local tests/docs only as needed; do not broaden into streaming, replay, tool repo work, or host packaging redesign.

**Folders Created/Deleted/Modified:**
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/runtime/`
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/.testbed/tests/`
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/models/`

**Files Created/Deleted/Modified:**
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/runtime/mediapipe_runtime_probe.py`
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/src/MediaPipePythonConfig.gd`
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/.testbed/tests/test_mediapipe_python_backend.gd`
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/runtime/tests/test_mediapipe_runtime_probe.py`
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/README.md`
- `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/models/pose_landmarker_lite.task`

**Status:** ✅ Complete

**Results:** Implemented the narrow host-compatibility repair in repo-owned vendor code. `runtime/mediapipe_runtime_probe.py` now detects the available MediaPipe API surface at runtime, preserves the legacy `mediapipe.solutions.pose.Pose(...)` path when present, and falls back to tasks-era `mediapipe.tasks.python.vision.PoseLandmarker` when the host package exposes `mediapipe.tasks` but not `mediapipe.solutions`. Added explicit pose-landmarker model-asset resolution with honest failure semantics: the tasks path now checks `runtime.pose_landmarker_model_path`, `runtime.model_asset_path`, `runtime.environment.AEROBEAT_MEDIAPIPE_POSE_LANDMARKER_MODEL_PATH`, host env `MEDIAPIPE_POSE_LANDMARKER_MODEL_PATH`, and repo-owned defaults. If no usable `.task` file exists, the runtime now fails explicitly with `mediapipe_model_missing`; if neither legacy nor tasks APIs are usable, it fails with `mediapipe_package_unsupported`; inference exceptions still surface as `mediapipe_inference_failed`.

Bundled a repo-owned default model asset at `models/pose_landmarker_lite.task` so the installed tasks-era host package can actually run the real non-fixture camera path on this machine. Kept the raw payload minimal and truthful: successful raw landmark output still only emits `id`, `x`, `y`, `z`, and `visibility` entries inside `raw_tracking_frame.landmarks`, and `tracking_state` only flips to `tracked` when that landmark array is non-empty.

Validation completed during the coder pass:
- `python3 -m unittest runtime.tests.test_mediapipe_runtime_probe` → 5 tests passed
- `godot --headless --path .testbed --import` → exit 0
- `godot --headless --path .testbed --script addons/gut/gut_cmdln.gd -gdir=res://tests -ginclude_subdirs -gexit` → 13/13 passed
- direct non-fixture host runtime probe against `/dev/video0` via `python3 runtime/mediapipe_runtime_probe.py --request-file <tempfile>` → `ok=true`, `tracking_state="tracked"`, `landmark_count=33`, frame size `640x480`, and the raw payload only exposed `frame_size`, `landmarks`, `source_id`, `source_kind`, `timestamp_ms`, and `tracking_state`; each landmark only exposed `id`, `x`, `y`, `z`, and `visibility`

QA can now verify the real host path directly on the installed tasks-era package shape.

---

### Task 2: QA host MediaPipe compatibility repair

**Bead ID:** `avmp-ywz`  
**SubAgent:** `primary`  
**Role:** `qa`  
**References:** `REF-02`, `REF-03`, `REF-05`, `REF-07`  
**Prompt:** In `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python`, wait until bead `avmp-ywz` is unblocked, then claim it with `bd update avmp-ywz --status in_progress --json`. QA the host MediaPipe compatibility repair from `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/.plans/2026-05-22-host-mediapipe-compat-repair.md`. You must verify both repo-local automated validation and a direct non-fixture host live-camera runtime probe using the actual installed MediaPipe package shape on this machine. Confirm the success path returns `ok=true` with a non-empty raw landmark payload, confirm `tracking_state` truth stays honest, and confirm missing-model / unsupported-package / inference-failure paths remain explicit. If validation still relies only on fixtures or shims, record that as a QA gap and do not overclaim completion.

**Folders Created/Deleted/Modified:**
- validation-only use of repo-local temp/test folders as needed

**Files Created/Deleted/Modified:**
- none required unless a minimal QA artifact is necessary

**Status:** ✅ Complete

**Results:** QA independently re-ran the repo-local validation stack and the direct host path on commit `32f08f5`.

Exact commands/results:
- `python3 -m unittest runtime.tests.test_mediapipe_runtime_probe` → passed (`Ran 5 tests in 0.001s`, `OK`)
- `godot --headless --path .testbed --import` → exit 0
- `godot --headless --path .testbed --script addons/gut/gut_cmdln.gd -gdir=res://tests -ginclude_subdirs -gexit` → passed (`13/13`)
- direct host live-camera probe via `python3 runtime/mediapipe_runtime_probe.py --request-file <temp startup request for /dev/video0>` → `ok=true`, `selected_camera_id="/dev/video0"`, `raw_tracking_frame.tracking_state="tracked"`, `landmark_count=33`, `frame_size={"x":640,"y":480}`
- raw payload shape check on that live response → `raw_tracking_frame` only exposed `frame_size`, `landmarks`, `source_id`, `source_kind`, `timestamp_ms`, and `tracking_state`; each landmark only exposed `id`, `x`, `y`, `z`, and `visibility`
- failure-path spot check via Python import/mocks against `runtime/mediapipe_runtime_probe.py` → preserved honest codes: `mediapipe_model_missing`, `mediapipe_package_unsupported`, and `mediapipe_inference_failed`
- source-ownership check via `git show --name-only --format='' 32f08f5` → changed files stayed in repo-owned paths; no `/addons` or `.testbed/addons` mirror paths were modified

QA notes:
- The real non-fixture host path succeeded on this machine using the tasks-era MediaPipe package shape and the repo-owned model asset at `models/pose_landmarker_lite.task`.
- Legacy `mediapipe.solutions.pose` support was not directly runnable on this host package shape, but repo-local unit coverage still exercises and passes that compatibility branch.
- The live probe emitted some stderr noise from V4L2 / TensorFlow Lite (`ioctl(VIDIOC_QBUF): Bad file descriptor` and MediaPipe warnings), but the probe still returned a truthful success payload with `health.last_error={}`. No QA evidence showed the warnings corrupting payload truth.

---

### Task 3: Audit host MediaPipe compatibility repair

**Bead ID:** `avmp-hnw`  
**SubAgent:** `primary`  
**Role:** `auditor`  
**References:** `REF-01`, `REF-02`, `REF-03`, `REF-04`, `REF-05`, `REF-06`, `REF-07`  
**Prompt:** In `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python`, wait until bead `avmp-hnw` is unblocked, then claim it with `bd update avmp-hnw --status in_progress --json`. Independently audit the host MediaPipe compatibility repair against the plan, diff, coder evidence, and QA evidence. Reject completion unless the actual host live-camera runtime path on this machine now returns a truthful sampled landmark payload with the installed MediaPipe package shape. If it passes, close `avmp-hnw` with an honest reason and explicitly note the host proof. If it fails, record the exact remaining blocker without broadening scope.

**Folders Created/Deleted/Modified:**
- none required

**Files Created/Deleted/Modified:**
- none required unless a minimal audit artifact is necessary

**Status:** ✅ Complete

**Results:** Audit independently re-ran the critical proof on commit `32f08f5` and found the planned slice complete for its stated scope.

Exact commands/results:
- `python3 - <<'PY' ... import mediapipe as mp ... PY` → host package confirmed as `{'version': '0.10.32', 'has_solutions': False, 'has_tasks': True, 'has_Image': True, 'has_ImageFormat': True}`
- `python3 -m unittest runtime.tests.test_mediapipe_runtime_probe` → passed (`Ran 5 tests in 0.001s`, `OK`)
- `godot --headless --path .testbed --import` → exit 0 (editor import completed; only a non-failing ObjectDB leak warning at exit)
- `godot --headless --path .testbed --script addons/gut/gut_cmdln.gd -gdir=res://tests -ginclude_subdirs -gexit` → passed (`13/13`, `105` asserts)
- direct host live-camera probe via `python3 runtime/mediapipe_runtime_probe.py --request-file <temp startup request for /dev/video0>` → `ok=true`, `selected_camera_id="/dev/video0"`, `health.last_error={}`, `raw_tracking_frame.tracking_state="tracked"`, `landmark_count=33`, `frame_size={"x":640,"y":480}`
- raw payload shape check on that live response → `raw_tracking_frame` only exposed `frame_size`, `landmarks`, `source_id`, `source_kind`, `timestamp_ms`, and `tracking_state`; first landmark only exposed `id`, `x`, `y`, `z`, and `visibility`
- focused failure-path spot check via Python import/mocks against `runtime/mediapipe_runtime_probe.py` → preserved honest codes `{missing_model: mediapipe_model_missing, inference_failure: mediapipe_inference_failed, unsupported_package: mediapipe_package_unsupported}`
- source-ownership check via `git show --name-only --format='' 32f08f5` → changed files stayed in repo-owned paths; no `/addons` or `.testbed/addons` mirror paths were modified

Audit notes:
- The real non-fixture host path does succeed on this machine now, and it is succeeding through the tasks-era MediaPipe branch, not a fixture shortcut.
- The repo-owned model asset actually used in the live probe was `/home/derrick/.openclaw/workspace/projects/aerobeat/aerobeat-vendor-mediapipe-python/models/pose_landmarker_lite.task`.
- The live probe still emits V4L2 / TensorFlow Lite stderr warnings (`ioctl(VIDIOC_QBUF): Bad file descriptor` plus MediaPipe/TFLite warnings), but they did not flip the response into a false success: the returned payload stayed truthful and `health.last_error` remained empty.
- Legacy `mediapipe.solutions.pose` support is not runnable on this installed host package shape, but unit coverage still exercises that compatibility branch and passed.
- No evidence showed contract drift, payload bloat, dishonest failure masking, or work being landed into consumer/addon mirrors.

---

## Dependency Shape

- `avmp-i8g` → first executable implementation bead
- `avmp-ywz` depends on `avmp-i8g`
- `avmp-hnw` depends on `avmp-ywz`

---

## Final Results

**Status:** ✅ Complete

**What We Built:** The vendor runtime repair now has independent audit proof on this machine, not just coder and QA claims. Repo-local validation still passes, the real non-fixture host live-camera path succeeds against the installed tasks-era MediaPipe package shape, and the repo-owned model asset at `models/pose_landmarker_lite.task` is actually sufficient for the sampled pose-landmarker path.

**Reference Check:** `REF-03`, `REF-05`, `REF-06`, and `REF-07` are satisfied in the completed audit. The runtime no longer assumes `mediapipe.solutions` on this tasks-only host package, the direct host probe returned `ok=true` with `tracking_state="tracked"` and `33` raw landmarks, the raw payload stayed minimal (`raw_tracking_frame` only `frame_size`, `landmarks`, `source_id`, `source_kind`, `timestamp_ms`, `tracking_state`; landmarks only `id/x/y/z/visibility`), honest failure semantics remained explicit for missing model / unsupported package / inference failure, and no `/addons` mirror paths were treated as owned source.

**Commits:**
- `32f08f5` - Support tasks-era MediaPipe host landmarks

**Lessons Learned:** For this slice, QA and audit both needed the same hard proof: unit coverage to preserve legacy/failure semantics plus a real host `/dev/video0` run to confirm the tasks-era compatibility branch works on the actual installed package rather than only in fixtures or mocks.

---

*Prepared on 2026-05-22*

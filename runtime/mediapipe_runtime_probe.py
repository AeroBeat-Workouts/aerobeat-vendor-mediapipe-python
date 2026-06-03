#!/usr/bin/env python3
import argparse
import glob
import json
import math
import os
import platform
import re
import signal
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

_DEFAULT_MODEL_COMPLEXITY = 1
_MODEL_FILENAMES = {
    0: "pose_landmarker_lite.task",
    1: "pose_landmarker_full.task",
    2: "pose_landmarker_heavy.task",
}
_HAND_LANDMARKER_MODEL_FILENAMES = ("hand_landmarker.task", "hand_landmarker.task")
_HAND_LANDMARK_MODE_DEFAULT = "lite"
_LITE_HAND_LANDMARK_IDS = (0, 1, 5, 9, 13, 17, 4, 8, 12, 16, 20)
_FULL_HAND_LANDMARK_IDS = tuple(range(21))

_SESSION_SNAPSHOT_FILENAME = "runtime_snapshot.json"
_SESSION_PREVIEW_FRAME_FILENAME = "preview_frame.jpg"
_SESSION_STOP_FILENAME = "stop"
_SESSION_REQUEST_FILENAME = "request.json"

_DEFAULT_TRACKING_MAX_FPS = 30
_DEFAULT_STATE_UPDATE_MAX_FPS = 30
_DEFAULT_PREVIEW_MAX_FPS = 30
_DEFAULT_PREVIEW_WIDTH = 960
_DEFAULT_PREVIEW_HEIGHT = 540
_DEFAULT_PREVIEW_QUALITY = 75

_PR_SET_PDEATHSIG = 1
_RUNTIME_SHUTDOWN_REQUESTED = False
_RUNTIME_SHUTDOWN_REASON = ""
_OWNER_PARENT_PID: Optional[int] = None
_OWNER_PARENT_DEATH_SIGNAL_ARMED = False


def _reset_runtime_shutdown_state() -> None:
    global _RUNTIME_SHUTDOWN_REQUESTED, _RUNTIME_SHUTDOWN_REASON, _OWNER_PARENT_PID, _OWNER_PARENT_DEATH_SIGNAL_ARMED
    _RUNTIME_SHUTDOWN_REQUESTED = False
    _RUNTIME_SHUTDOWN_REASON = ""
    _OWNER_PARENT_PID = None
    _OWNER_PARENT_DEATH_SIGNAL_ARMED = False


def _request_runtime_shutdown(reason: str) -> None:
    global _RUNTIME_SHUTDOWN_REQUESTED, _RUNTIME_SHUTDOWN_REASON
    _RUNTIME_SHUTDOWN_REQUESTED = True
    _RUNTIME_SHUTDOWN_REASON = str(reason).strip() or "signal"


def _runtime_shutdown_reason() -> str:
    return _RUNTIME_SHUTDOWN_REASON if _RUNTIME_SHUTDOWN_REQUESTED else ""


def _handle_runtime_shutdown_signal(signum: int, _frame: Any) -> None:
    current_parent_pid = os.getppid()
    if _OWNER_PARENT_DEATH_SIGNAL_ARMED and _OWNER_PARENT_PID not in (None, 0) and current_parent_pid != _OWNER_PARENT_PID:
        _request_runtime_shutdown("owner_process_disappeared")
        return
    _request_runtime_shutdown(f"signal_{int(signum)}")


def _arm_owner_orphan_protection() -> Dict[str, Any]:
    global _OWNER_PARENT_PID, _OWNER_PARENT_DEATH_SIGNAL_ARMED

    _reset_runtime_shutdown_state()
    _OWNER_PARENT_PID = os.getppid()
    signal.signal(signal.SIGTERM, _handle_runtime_shutdown_signal)

    if platform.system() != "Linux":
        return {
            "ok": False,
            "code": "owner_orphan_protection_unsupported_platform",
            "message": "Owner orphan protection is only armed on Linux hosts.",
            "parent_pid": _OWNER_PARENT_PID,
        }

    try:
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        prctl = getattr(libc, "prctl", None)
        if prctl is None:
            return {
                "ok": False,
                "code": "owner_orphan_protection_unavailable",
                "message": "libc prctl is unavailable; cannot arm Linux parent-death signal.",
                "parent_pid": _OWNER_PARENT_PID,
            }
        prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
        prctl.restype = ctypes.c_int
        if prctl(_PR_SET_PDEATHSIG, int(signal.SIGTERM), 0, 0, 0) != 0:
            errno_value = ctypes.get_errno()
            return {
                "ok": False,
                "code": "owner_orphan_protection_arm_failed",
                "message": os.strerror(errno_value) if errno_value else "Failed to arm Linux parent-death signal.",
                "errno": errno_value,
                "parent_pid": _OWNER_PARENT_PID,
            }
    except Exception as exc:
        return {
            "ok": False,
            "code": "owner_orphan_protection_exception",
            "message": str(exc),
            "parent_pid": _OWNER_PARENT_PID,
        }

    _OWNER_PARENT_DEATH_SIGNAL_ARMED = True
    if os.getppid() != _OWNER_PARENT_PID:
        _request_runtime_shutdown("owner_process_disappeared")
    return {
        "ok": True,
        "parent_pid": _OWNER_PARENT_PID,
        "signal": "SIGTERM",
        "signal_number": int(signal.SIGTERM),
    }


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _now_ms() -> int:
    return int(time.time() * 1000)


def _normalize_nonnegative_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(parsed, 0)


def _normalize_positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _normalize_jpeg_quality(value: Any, default: int = _DEFAULT_PREVIEW_QUALITY) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(parsed, 1), 100)


def _normalized_fps_cap(value: Any, default: int) -> int:
    return _normalize_nonnegative_int(value, default)


def _fps_interval_seconds(value: Any, default: int) -> float:
    fps = _normalized_fps_cap(value, default)
    if fps <= 0:
        return 0.0
    return 1.0 / float(fps)


def _preview_runtime_config(preview: Dict[str, Any], runtime: Dict[str, Any]) -> Dict[str, Any]:
    enabled = bool(runtime.get("preview_enabled", preview.get("enabled", True)))
    return {
        "enabled": enabled,
        "surface_mode": str(preview.get("surface_mode", "attach")),
        "flip_horizontal": bool(preview.get("flip_horizontal", True)),
        "max_fps": _normalized_fps_cap(runtime.get("preview_max_fps", preview.get("max_fps", _DEFAULT_PREVIEW_MAX_FPS)), _DEFAULT_PREVIEW_MAX_FPS),
        "width": _normalize_positive_int(runtime.get("preview_width", preview.get("width", _DEFAULT_PREVIEW_WIDTH)), _DEFAULT_PREVIEW_WIDTH),
        "height": _normalize_positive_int(runtime.get("preview_height", preview.get("height", _DEFAULT_PREVIEW_HEIGHT)), _DEFAULT_PREVIEW_HEIGHT),
        "quality": _normalize_jpeg_quality(runtime.get("preview_quality", preview.get("quality", _DEFAULT_PREVIEW_QUALITY))),
    }


_REDUCED_TRACKING_LANDMARK_IDS = {
    0,
    11, 12,
    13, 14,
    15, 16,
    23, 24,
    25, 26,
    27, 28,
}
_ONE_EURO_MIN_CUTOFF = 1.0
_ONE_EURO_BETA = 0.15
_ONE_EURO_DERIVATE_CUTOFF = 1.0


def _normalize_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _normalize_tracking_overlay_mode(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized == "full":
        return "full"
    if normalized in {"simple", "optimized"}:
        return "optimized"
    if normalized in {"off", "none", "hidden"}:
        return "off"
    return "optimized"


def _normalize_tracking_quality(value: Any, overlay_mode: Any = "optimized") -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"simple", "optimized"}:
        return "optimized"
    if normalized in {"full", "raw"}:
        return "full"
    overlay = _normalize_tracking_overlay_mode(overlay_mode)
    return "full" if overlay == "full" else "optimized"


def _tracking_semantics(request: Dict[str, Any]) -> Dict[str, Any]:
    runtime = request.get("runtime", {}) if isinstance(request.get("runtime", {}), dict) else {}
    tracking = request.get("tracking", {}) if isinstance(request.get("tracking", {}), dict) else {}
    overlay_mode = _normalize_tracking_overlay_mode(tracking.get("overlay_mode", "optimized"))
    quality = _normalize_tracking_quality(tracking.get("quality", "optimized"), overlay_mode)

    filter_enabled = True
    if "no_filter" in runtime:
        filter_enabled = not _normalize_bool(runtime.get("no_filter"), False)
    elif "filter_enabled" in runtime:
        filter_enabled = _normalize_bool(runtime.get("filter_enabled"), True)
    else:
        tracking_filter = tracking.get("filter", {}) if isinstance(tracking.get("filter", {}), dict) else {}
        tracking_smoothing = tracking.get("smoothing", {}) if isinstance(tracking.get("smoothing", {}), dict) else {}
        if "enabled" in tracking_filter:
            filter_enabled = _normalize_bool(tracking_filter.get("enabled"), True)
        elif "enabled" in tracking_smoothing:
            filter_enabled = _normalize_bool(tracking_smoothing.get("enabled"), True)

    return {
        "overlay_mode": overlay_mode,
        "quality": quality,
        "point_mode": "reduced" if quality == "optimized" else "full",
        "filter_enabled": filter_enabled,
    }


def _one_euro_alpha(cutoff: float, delta_seconds: float) -> float:
    if delta_seconds <= 0.0:
        return 1.0
    tau = 1.0 / (2.0 * math.pi * max(cutoff, 1e-6))
    return 1.0 / (1.0 + tau / delta_seconds)


def _one_euro_filter_value(value: float, state: Dict[str, Any], timestamp_ms: int) -> float:
    previous_value = state.get("value")
    previous_timestamp_ms = state.get("timestamp_ms")
    previous_derivative = float(state.get("derivative", 0.0))
    if previous_value is None or previous_timestamp_ms is None:
        state["value"] = value
        state["timestamp_ms"] = timestamp_ms
        state["derivative"] = 0.0
        return value

    delta_seconds = max((int(timestamp_ms) - int(previous_timestamp_ms)) / 1000.0, 1e-6)
    derivative = (value - float(previous_value)) / delta_seconds
    derivative_alpha = _one_euro_alpha(_ONE_EURO_DERIVATE_CUTOFF, delta_seconds)
    filtered_derivative = derivative_alpha * derivative + (1.0 - derivative_alpha) * previous_derivative
    cutoff = _ONE_EURO_MIN_CUTOFF + _ONE_EURO_BETA * abs(filtered_derivative)
    value_alpha = _one_euro_alpha(cutoff, delta_seconds)
    filtered_value = value_alpha * value + (1.0 - value_alpha) * float(previous_value)
    state["value"] = filtered_value
    state["timestamp_ms"] = timestamp_ms
    state["derivative"] = filtered_derivative
    return filtered_value


def _filter_landmarks(landmarks: List[Dict[str, Any]], timestamp_ms: int, filter_state: Dict[str, Any]) -> List[Dict[str, Any]]:
    filtered: List[Dict[str, Any]] = []
    seen_ids = set()
    for landmark in landmarks:
        landmark_id = int(landmark.get("id", -1))
        seen_ids.add(landmark_id)
        landmark_state = filter_state.setdefault(landmark_id, {})
        filtered_landmark = dict(landmark)
        for key in ("x", "y", "z", "visibility"):
            if key in landmark:
                filtered_landmark[key] = _one_euro_filter_value(float(landmark[key]), landmark_state.setdefault(key, {}), timestamp_ms)
        filtered.append(filtered_landmark)
    stale_ids = [landmark_id for landmark_id in filter_state.keys() if landmark_id not in seen_ids]
    for landmark_id in stale_ids:
        filter_state.pop(landmark_id, None)
    return filtered


def _apply_tracking_semantics(raw_tracking_frame: Dict[str, Any], semantics: Dict[str, Any], filter_state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    frame = raw_tracking_frame.copy()
    landmarks = frame.get("landmarks")
    if not isinstance(landmarks, list) or len(landmarks) == 0:
        if filter_state is not None:
            filter_state.clear()
        frame.pop("landmarks", None)
        frame["tracking_state"] = "idle"
        frame["vendor_tracking_semantics"] = {
            "quality": semantics.get("quality", "optimized"),
            "overlay_mode": semantics.get("overlay_mode", "optimized"),
            "filter_enabled": bool(semantics.get("filter_enabled", True)),
            "landmark_count_before": 0,
            "landmark_count_after": 0,
        }
        return frame

    processed = [dict(landmark) for landmark in landmarks if isinstance(landmark, dict)]
    landmark_count_before = len(processed)
    if semantics.get("point_mode") == "reduced":
        processed = [landmark for landmark in processed if int(landmark.get("id", -1)) in _REDUCED_TRACKING_LANDMARK_IDS]
    timestamp_ms = int(frame.get("timestamp_ms", _now_ms()))
    if bool(semantics.get("filter_enabled", True)) and filter_state is not None:
        processed = _filter_landmarks(processed, timestamp_ms, filter_state)
    elif filter_state is not None:
        filter_state.clear()

    if processed:
        frame["landmarks"] = processed
        frame["tracking_state"] = "tracked"
    else:
        frame.pop("landmarks", None)
        frame["tracking_state"] = "idle"
    frame["vendor_tracking_semantics"] = {
        "quality": semantics.get("quality", "optimized"),
        "overlay_mode": semantics.get("overlay_mode", "optimized"),
        "filter_enabled": bool(semantics.get("filter_enabled", True)),
        "landmark_count_before": landmark_count_before,
        "landmark_count_after": len(processed),
    }
    return frame


def _read_request(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _runtime_env(runtime: Dict[str, Any]) -> Dict[str, Any]:
    environment = runtime.get("environment", {})
    return environment if isinstance(environment, dict) else {}


def _working_directory(runtime: Dict[str, Any]) -> str:
    working_directory = str(runtime.get("working_directory", "")).strip()
    if working_directory != "":
        return os.path.abspath(working_directory)
    return os.getcwd()


def _resolve_runtime_path(runtime: Dict[str, Any], candidate: str) -> str:
    if candidate == "":
        return ""
    expanded = os.path.expanduser(candidate)
    if os.path.isabs(expanded):
        return os.path.abspath(expanded)
    return os.path.abspath(os.path.join(_working_directory(runtime), expanded))


def _camera_root(runtime: Dict[str, Any]) -> str:
    environment = _runtime_env(runtime)
    return str(environment.get("AEROBEAT_CAMERA_ROOT", os.environ.get("AEROBEAT_CAMERA_ROOT", "/dev")))


def _camera_pattern(runtime: Dict[str, Any]) -> str:
    environment = _runtime_env(runtime)
    return str(environment.get("AEROBEAT_CAMERA_PATTERN", os.environ.get("AEROBEAT_CAMERA_PATTERN", "video*")))


def _enumerate_cameras(runtime: Dict[str, Any]) -> List[Dict[str, Any]]:
    root = _camera_root(runtime)
    pattern = _camera_pattern(runtime)
    candidates = sorted(glob.glob(os.path.join(root, pattern)))
    cameras: List[Dict[str, Any]] = []
    for path in candidates:
        cameras.append(
            {
                "id": path,
                "camera_id": path,
                "label": os.path.basename(path) or path,
                "backend": "mediapipe_python",
                "source_kind": "live_camera",
                "available": os.path.exists(path),
                "metadata": {
                    "device_path": path,
                    "root": root,
                    "pattern": pattern,
                    "probe_mode": "filesystem_glob",
                },
            }
        )
    return cameras


def _base_health(operation: str, runtime: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "status": "idle" if operation == "list_cameras" else "running",
        "backend": "mediapipe_python",
        "runtime_available": True,
        "bridge_connected": True,
        "process_active": False,
        "camera_accessible": False,
        "tracking_active": False,
        "healthy": operation == "list_cameras",
        "last_error": {},
        "notes": [
            "Runtime now supports truthful continuous live-camera and replay/video-file raw frame updates; broader public temporal semantics remain upstream-owned."
        ],
        "probe_operation": operation,
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "working_directory": runtime.get("working_directory", ""),
        "probed_at": _now_iso(),
    }


def _sample_fixture_map(runtime: Dict[str, Any]) -> Dict[str, Any]:
    environment = _runtime_env(runtime)
    raw = str(environment.get("AEROBEAT_CAMERA_SAMPLE_FIXTURES_JSON", os.environ.get("AEROBEAT_CAMERA_SAMPLE_FIXTURES_JSON", ""))).strip()
    if raw == "":
        return {}
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, dict) else {}


def _normalize_fixture_landmark(camera_id: str, landmark: Any, index: int) -> Dict[str, float]:
    if not isinstance(landmark, dict):
        raise ValueError(f"Camera sample fixture for '{camera_id}' landmark {index} must be an object")
    landmark_id = int(landmark.get("id", index))
    return {
        "id": landmark_id,
        "x": float(landmark.get("x", 0.0)),
        "y": float(landmark.get("y", 0.0)),
        "z": float(landmark.get("z", 0.0)),
        "visibility": float(landmark.get("visibility", 0.0)),
    }


def _normalize_hand_landmark_mode(tracking: Dict[str, Any], runtime: Optional[Dict[str, Any]] = None) -> str:
    runtime = runtime or {}
    hands = tracking.get("hands", {}) if isinstance(tracking.get("hands", {}), dict) else {}
    candidate = str(runtime.get("hand_landmark_mode", hands.get("landmark_mode", _HAND_LANDMARK_MODE_DEFAULT))).strip().lower()
    return "full" if candidate == "full" else _HAND_LANDMARK_MODE_DEFAULT


def _hand_tracking_request(tracking: Dict[str, Any], runtime: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    runtime = runtime or {}
    hands = tracking.get("hands", {}) if isinstance(tracking.get("hands", {}), dict) else {}
    validity = hands.get("validity", {}) if isinstance(hands.get("validity", {}), dict) else {}
    bbox = hands.get("bbox", {}) if isinstance(hands.get("bbox", {}), dict) else {}
    return {
        "enabled": bool(runtime.get("hand_tracking_enabled", hands.get("enabled", False))),
        "landmark_mode": _normalize_hand_landmark_mode(tracking, runtime),
        "bbox_enabled": bool(runtime.get("hand_bbox_enabled", bbox.get("enabled", True))),
        "inference_interval_frames": max(1, int(runtime.get("hand_inference_interval_frames", hands.get("inference_interval_frames", 1)) or 1)),
        "bbox_recompute_interval_frames": max(1, int(runtime.get("hand_bbox_recompute_interval_frames", hands.get("bbox_recompute_interval_frames", 1)) or 1)),
        "max_stale_frames": max(0, int(runtime.get("hand_max_stale_frames", validity.get("max_stale_frames", 2)) or 0)),
        "reacquire_stable_frames": max(1, int(runtime.get("hand_reacquire_stable_frames", validity.get("reacquire_stable_frames", 2)) or 1)),
    }


def _hand_tracking_constraints(request: Dict[str, Any], backend: str, hand_available: bool = True) -> List[str]:
    mode = str(request.get("landmark_mode", _HAND_LANDMARK_MODE_DEFAULT))
    constraints = [
        f"Hand landmark mode '{mode}' derives bbox geometry from the same emitted landmark subset, so lite mode intentionally under-bounds compared with full mode.",
        "MediaPipe does not expose stable per-hand track IDs in this slice; higher layers must not assume handedness labels remain bound across frames.",
        "Preview mirroring is a presentation transform only; raw hand coordinates stay camera-native and must be mirrored consistently upstream alongside pose.",
        f"This vendor slice surfaces requested hand cadence only (inference every {int(request.get('inference_interval_frames', 1))} frame(s), bbox recompute every {int(request.get('bbox_recompute_interval_frames', 1))} frame(s)); actual stale/reacquire semantics remain an upstream responsibility.",
    ]
    if backend == "mediapipe_tasks_hand_landmarker":
        constraints.append("MediaPipe tasks hand inference runs in IMAGE mode here, so each frame is an independent detection with no vendor-side interpolation or per-hand timestamps.")
    elif backend == "mediapipe_solutions_hands":
        constraints.append("MediaPipe legacy Hands exposes landmarks and handedness per frame but still does not provide durable hand IDs or vendor-side stale counters.")
    elif not hand_available:
        constraints.append("Hand inference was requested but the installed MediaPipe package/model assets could not provide it on this host; upstream should treat hand lanes as unavailable, not stale.")
    return constraints


def _selected_hand_landmark_ids(mode: str) -> Sequence[int]:
    return _FULL_HAND_LANDMARK_IDS if mode == "full" else _LITE_HAND_LANDMARK_IDS


def _normalize_handedness_label(label: Any) -> str:
    normalized = str(label).strip().lower()
    if normalized in ("left", "right"):
        return normalized
    return "unknown"


def _handedness_from_legacy_results(results: Any, index: int) -> Dict[str, Any]:
    multi_handedness = getattr(results, "multi_handedness", None)
    if not isinstance(multi_handedness, list) or index >= len(multi_handedness):
        return {"label": "unknown", "score": 0.0}
    candidate = multi_handedness[index]
    classifications = getattr(candidate, "classification", None)
    if isinstance(classifications, list) and classifications:
        top = classifications[0]
        return {
            "label": _normalize_handedness_label(getattr(top, "label", getattr(top, "category_name", "unknown"))),
            "score": float(getattr(top, "score", 0.0)),
        }
    return {"label": "unknown", "score": 0.0}


def _handedness_from_tasks_result(result: Any, index: int) -> Dict[str, Any]:
    handedness = getattr(result, "handedness", None)
    if not isinstance(handedness, list) or index >= len(handedness):
        return {"label": "unknown", "score": 0.0}
    candidate = handedness[index]
    if isinstance(candidate, list) and candidate:
        top = candidate[0]
    else:
        top = candidate
    return {
        "label": _normalize_handedness_label(getattr(top, "category_name", getattr(top, "display_name", getattr(top, "label", "unknown")))),
        "score": float(getattr(top, "score", 0.0)),
    }


def _hand_landmarks_from_source(landmarks_source: Any) -> List[Dict[str, float]]:
    landmarks: List[Dict[str, float]] = []
    if landmarks_source is None:
        return landmarks
    for landmark in landmarks_source:
        landmarks.append({
            "id": len(landmarks),
            "x": float(getattr(landmark, "x", 0.0)),
            "y": float(getattr(landmark, "y", 0.0)),
            "z": float(getattr(landmark, "z", 0.0)),
            "visibility": float(getattr(landmark, "visibility", 1.0)),
        })
    return landmarks


def _normalize_hand_detection(hand: Dict[str, Any], mode: str, bbox_enabled: bool) -> Dict[str, Any]:
    full_landmarks = [dict(landmark) for landmark in hand.get("landmarks", []) if isinstance(landmark, dict)]
    selected_ids = set(_selected_hand_landmark_ids(mode))
    landmarks = [landmark for landmark in full_landmarks if int(landmark.get("id", -1)) in selected_ids]
    normalized = {
        "index": int(hand.get("index", 0)),
        "label": _normalize_handedness_label(hand.get("label", "unknown")),
        "score": float(hand.get("score", 0.0)),
        "landmark_mode": mode,
        "landmark_count_before": len(full_landmarks),
        "landmark_count_after": len(landmarks),
        "landmarks": landmarks,
    }
    if bbox_enabled and landmarks:
        xs = [max(0.0, min(1.0, float(landmark.get("x", 0.0)))) for landmark in landmarks]
        ys = [max(0.0, min(1.0, float(landmark.get("y", 0.0)))) for landmark in landmarks]
        min_x = min(xs)
        max_x = max(xs)
        min_y = min(ys)
        max_y = max(ys)
        width = max(0.0, max_x - min_x)
        height = max(0.0, max_y - min_y)
        normalized["bbox"] = {
            "x": min_x,
            "y": min_y,
            "width": width,
            "height": height,
            "area": width * height,
            "landmark_mode": mode,
            "landmark_count": len(landmarks),
            "landmark_ids": [int(landmark.get("id", -1)) for landmark in landmarks],
            "coordinate_space": "normalized_frame",
            "area_unit": "normalized_frame_area",
        }
    return normalized


def _normalize_fixture_hand(camera_id: str, hand: Any, index: int) -> Dict[str, Any]:
    if not isinstance(hand, dict):
        raise ValueError(f"Camera sample fixture for '{camera_id}' hand {index} must be an object")
    landmarks_raw = hand.get("landmarks", [])
    if not isinstance(landmarks_raw, list):
        raise ValueError(f"Camera sample fixture for '{camera_id}' hand {index} landmarks must be an array")
    return {
        "index": int(hand.get("index", index)),
        "label": _normalize_handedness_label(hand.get("label", "unknown")),
        "score": float(hand.get("score", 0.0)),
        "landmarks": [_normalize_fixture_landmark(camera_id, landmark, landmark_index) for landmark_index, landmark in enumerate(landmarks_raw)],
    }


def _raw_tracking_frame_base(source_kind: str, source_id: str, width: int, height: int, timestamp_ms: int) -> Dict[str, Any]:
    return {
        "timestamp_ms": timestamp_ms,
        "source_kind": source_kind,
        "source_id": source_id,
        "tracking_state": "idle",
        "frame_size": {"x": width, "y": height},
    }


def _normalize_fixture_sample(source_id: str, fixture: Dict[str, Any], sample_index: int = 0, dynamic_timestamp: bool = False, source_kind: str = "live_camera") -> Dict[str, Any]:
    width = int(fixture.get("width", 0))
    height = int(fixture.get("height", 0))
    if width <= 0 or height <= 0:
        raise ValueError(f"Camera sample fixture for '{source_id}' must provide positive width/height")

    timestamp_ms = int(fixture.get("timestamp_ms", _now_ms()))
    if dynamic_timestamp:
        if fixture.get("timestamp_step_ms") is not None:
            timestamp_ms += int(fixture.get("timestamp_step_ms", 0)) * max(0, sample_index)
        else:
            timestamp_ms = _now_ms()

    raw_tracking_frame = _raw_tracking_frame_base(source_kind, source_id, width, height, timestamp_ms)
    notes = [f"Captured sample frame for '{source_id}' via configured fixture dimensions {width}x{height}."]

    if fixture.get("inference_error") is not None:
        error_info = fixture.get("inference_error")
        if not isinstance(error_info, dict):
            raise ValueError(f"Camera sample fixture for '{source_id}' inference_error must be an object")
        return {
            "raw_tracking_frame": raw_tracking_frame,
            "fixture_inference_error": {
                "code": str(error_info.get("code", "mediapipe_inference_failed")),
                "message": str(error_info.get("message", f"Fixture inference failed for '{source_id}'")),
            },
            "notes": notes,
        }

    landmarks_raw = fixture.get("landmarks")
    if isinstance(landmarks_raw, list):
        landmarks = [_normalize_fixture_landmark(source_id, landmark, index) for index, landmark in enumerate(landmarks_raw)]
        if landmarks:
            raw_tracking_frame["tracking_state"] = "tracked"
            raw_tracking_frame["landmarks"] = landmarks
            notes.append(f"Fixture supplied {len(landmarks)} pose landmark(s) for '{source_id}'.")
        else:
            notes.append(f"Fixture supplied an empty landmark array for '{source_id}'; tracking remains idle.")

    hands_raw = fixture.get("hands")
    if isinstance(hands_raw, list):
        hands = [_normalize_fixture_hand(source_id, hand, index) for index, hand in enumerate(hands_raw)]
        if hands:
            raw_tracking_frame["hands"] = hands
            notes.append(f"Fixture supplied {len(hands)} raw hand sample(s) for '{source_id}'.")
        else:
            notes.append(f"Fixture supplied an empty hand array for '{source_id}'.")

    return {
        "raw_tracking_frame": raw_tracking_frame,
        "notes": notes,
        "fixture_used": True,
    }


def _sample_from_fixture(source_id: str, runtime: Dict[str, Any], sample_index: int = 0, dynamic_timestamp: bool = False, source_kind: str = "live_camera") -> Optional[Dict[str, Any]]:
    fixtures = _sample_fixture_map(runtime)
    fixture = fixtures.get(source_id)
    if not isinstance(fixture, dict):
        return None

    sequence = fixture.get("sequence")
    if isinstance(sequence, list):
        if not sequence:
            return None
        if sample_index >= len(sequence):
            return {"fixture_eof": True}
        chosen = sequence[sample_index]
        if not isinstance(chosen, dict):
            raise ValueError(f"Camera sample fixture sequence for '{source_id}' must contain objects")
        return _normalize_fixture_sample(source_id, chosen, sample_index=sample_index, dynamic_timestamp=dynamic_timestamp, source_kind=source_kind)

    return _normalize_fixture_sample(source_id, fixture, sample_index=sample_index, dynamic_timestamp=dynamic_timestamp, source_kind=source_kind)


def _camera_device_index(camera_id: str) -> Optional[int]:
    if os.path.dirname(camera_id) != "/dev":
        return None
    basename = os.path.basename(camera_id)
    if basename.startswith("video") and basename[5:].isdigit():
        return int(basename[5:])
    return None


def _live_camera_capture_request(runtime: Dict[str, Any]) -> Dict[str, Any]:
    requested_width = _normalize_positive_int(runtime.get("live_camera_width", runtime.get("preview_width", _DEFAULT_PREVIEW_WIDTH)), _DEFAULT_PREVIEW_WIDTH)
    requested_height = _normalize_positive_int(runtime.get("live_camera_height", runtime.get("preview_height", _DEFAULT_PREVIEW_HEIGHT)), _DEFAULT_PREVIEW_HEIGHT)
    requested_fps = _normalized_fps_cap(runtime.get("live_camera_fps", runtime.get("tracking_max_fps", _DEFAULT_TRACKING_MAX_FPS)), _DEFAULT_TRACKING_MAX_FPS)
    preferred_fourcc = str(runtime.get("live_camera_fourcc", "MJPG") or "").strip().upper()
    if preferred_fourcc == "":
        preferred_fourcc = "MJPG"
    return {
        "width": requested_width,
        "height": requested_height,
        "fps": requested_fps,
        "fourcc": preferred_fourcc,
        "preferred_fourcc": preferred_fourcc,
    }


def _preferred_live_camera_backend_name(cv2: Any, camera_id: str) -> str:
    if platform.system() == "Linux" and _camera_device_index(camera_id) is not None and hasattr(cv2, "CAP_V4L2"):
        return "CAP_V4L2"
    return "default"


def _capture_backend_value(cv2: Any, backend_name: str) -> Optional[int]:
    if backend_name == "CAP_V4L2" and hasattr(cv2, "CAP_V4L2"):
        return int(getattr(cv2, "CAP_V4L2"))
    return None


def _safe_capture_set(capture: Any, prop: Any, value: Any) -> bool:
    try:
        return bool(capture.set(prop, value))
    except Exception:
        return False


def _safe_capture_get(capture: Any, prop: Any, default: float = 0.0) -> float:
    try:
        value = capture.get(prop)
    except Exception:
        return default
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _encode_fourcc(cv2: Any, fourcc: str) -> Optional[int]:
    if fourcc == "" or hasattr(cv2, "VideoWriter_fourcc") == False:
        return None
    try:
        return int(cv2.VideoWriter_fourcc(*fourcc[:4]))
    except Exception:
        return None


def _decode_fourcc(value: float) -> str:
    try:
        parsed = int(round(value))
    except (TypeError, ValueError):
        return ""
    if parsed <= 0:
        return ""
    chars: List[str] = []
    for shift in range(4):
        code = (parsed >> (8 * shift)) & 0xFF
        if code == 0:
            continue
        chars.append(chr(code))
    decoded = "".join(chars)
    return decoded if decoded.isprintable() else ""


def _is_linux_video_device(camera_id: str) -> bool:
    return platform.system() == "Linux" and _camera_device_index(camera_id) is not None


def _live_camera_backend_score(backend_name: str, preferred_backend_name: str) -> int:
    if backend_name == preferred_backend_name:
        return 2
    if backend_name == "CAP_V4L2":
        return 1
    return 0


def _live_camera_format_score(fourcc: str, preferred_fourcc: str) -> int:
    normalized = str(fourcc or "").strip().upper()
    preferred = str(preferred_fourcc or "").strip().upper()
    if normalized != "" and normalized == preferred:
        return 4
    if normalized == "MJPG":
        return 3
    if normalized in {"YUYV", "YUY2"}:
        return 2
    if normalized != "":
        return 1
    return 0


def _live_camera_resolution_delta(mode: Dict[str, Any], requested: Dict[str, Any]) -> int:
    return abs(int(mode.get("width", 0)) - int(requested.get("width", 0))) + abs(int(mode.get("height", 0)) - int(requested.get("height", 0)))


def _live_camera_fps_sort_key(mode_fps: float, requested_fps: int) -> Tuple[int, float, float]:
    if requested_fps <= 0:
        return (0, -mode_fps, 0.0)
    if mode_fps >= float(requested_fps):
        return (0, mode_fps - float(requested_fps), -mode_fps)
    return (1, float(requested_fps) - mode_fps, -mode_fps)


def _live_camera_mode_rank_key(mode: Dict[str, Any], requested: Dict[str, Any], preferred_backend_name: str) -> Tuple[Any, ...]:
    fps = float(mode.get("fps", 0.0) or 0.0)
    return (
        *_live_camera_fps_sort_key(fps, int(requested.get("fps", 0))),
        _live_camera_resolution_delta(mode, requested),
        -_live_camera_format_score(str(mode.get("fourcc", "")), str(requested.get("preferred_fourcc", ""))),
        -_live_camera_backend_score(str(mode.get("backend_name", preferred_backend_name)), preferred_backend_name),
        -int(mode.get("width", 0) or 0) * max(int(mode.get("height", 0) or 0), 1),
    )


def _dedupe_live_camera_modes(modes: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    seen = set()
    for mode in modes:
        signature = (
            int(mode.get("width", 0) or 0),
            int(mode.get("height", 0) or 0),
            round(float(mode.get("fps", 0.0) or 0.0), 3),
            str(mode.get("fourcc", "") or "").strip().upper(),
            str(mode.get("backend_name", "") or ""),
            str(mode.get("candidate_source", "") or ""),
        )
        if signature in seen:
            continue
        normalized = dict(mode)
        normalized["width"] = int(mode.get("width", 0) or 0)
        normalized["height"] = int(mode.get("height", 0) or 0)
        normalized["fps"] = round(float(mode.get("fps", 0.0) or 0.0), 3)
        normalized["fourcc"] = str(mode.get("fourcc", "") or "").strip().upper()
        deduped.append(normalized)
        seen.add(signature)
    return deduped


def _rank_live_camera_modes(modes: Sequence[Dict[str, Any]], requested: Dict[str, Any], preferred_backend_name: str) -> List[Dict[str, Any]]:
    ranked = _dedupe_live_camera_modes(modes)
    ranked.sort(key=lambda mode: _live_camera_mode_rank_key(mode, requested, preferred_backend_name))
    return ranked


def _live_camera_capture_sources(camera_id: str, backend_name: str) -> List[Tuple[Any, str]]:
    device_index = _camera_device_index(camera_id)
    sources: List[Tuple[Any, str]] = [(camera_id, "device path")]
    if device_index is not None:
        sources.append((device_index, f"device index fallback {device_index}"))
    return sources


def _v4l2_reported_live_camera_modes(camera_id: str, requested: Dict[str, Any], preferred_backend_name: str) -> Dict[str, Any]:
    if not _is_linux_video_device(camera_id):
        return {"available": False, "source": "unavailable", "reported_modes": [], "notes": []}
    try:
        command = ["v4l2-ctl", "--device", camera_id, "--list-formats-ext"]
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=5)
    except FileNotFoundError:
        return {
            "available": False,
            "source": "v4l2_missing",
            "reported_modes": [],
            "notes": ["v4l2-ctl is unavailable on this host; falling back to bounded OpenCV probing."],
        }
    except Exception as exc:
        return {
            "available": False,
            "source": "v4l2_failed",
            "reported_modes": [],
            "notes": [f"v4l2-ctl failed for '{camera_id}': {exc}; falling back to bounded OpenCV probing."],
        }

    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        note = f"v4l2-ctl could not enumerate '{camera_id}'"
        if stderr != "":
            note += f": {stderr}"
        note += "; falling back to bounded OpenCV probing."
        return {"available": False, "source": "v4l2_failed", "reported_modes": [], "notes": [note]}

    reported_modes: List[Dict[str, Any]] = []
    current_fourcc = ""
    current_description = ""
    current_size: Optional[Tuple[int, int]] = None
    for raw_line in completed.stdout.splitlines():
        line = raw_line.strip()
        format_match = re.match(r"\[\d+\]: '([^']+)'(?: \((.*)\))?", line)
        if format_match:
            current_fourcc = str(format_match.group(1) or "").strip().upper()
            current_description = str(format_match.group(2) or "").strip()
            current_size = None
            continue
        size_match = re.search(r"Size:\s+Discrete\s+(\d+)x(\d+)", line)
        if size_match:
            current_size = (int(size_match.group(1)), int(size_match.group(2)))
            continue
        interval_match = re.search(r"Interval:\s+Discrete\s+[0-9.]+s\s+\(([0-9.]+)\s+fps\)", line)
        if interval_match and current_size is not None:
            reported_modes.append({
                "width": current_size[0],
                "height": current_size[1],
                "fps": round(float(interval_match.group(1)), 3),
                "fourcc": current_fourcc,
                "format_description": current_description,
                "backend_name": preferred_backend_name,
                "candidate_source": "reported_v4l2",
                "report_kind": "reported",
            })

    reported_modes = _rank_live_camera_modes(reported_modes, requested, preferred_backend_name)
    notes = [f"Enumerated {len(reported_modes)} reported live-camera mode(s) for '{camera_id}' via v4l2-ctl."] if reported_modes else [f"v4l2-ctl returned no discrete reported modes for '{camera_id}'; falling back to bounded OpenCV probing."]
    return {
        "available": len(reported_modes) > 0,
        "source": "reported_v4l2" if reported_modes else "v4l2_empty",
        "reported_modes": reported_modes,
        "notes": notes,
    }


def _fallback_live_camera_probe_modes(requested: Dict[str, Any], preferred_backend_name: str) -> List[Dict[str, Any]]:
    widths = [int(requested.get("width", _DEFAULT_PREVIEW_WIDTH)), 1920, 1600, 1280, 1024, 960, 848, 800, 640, 320]
    heights = [int(requested.get("height", _DEFAULT_PREVIEW_HEIGHT)), 1080, 900, 720, 576, 540, 480, 450, 360, 240]
    fps_values = [int(requested.get("fps", _DEFAULT_TRACKING_MAX_FPS)), 60, 30, 24, 20, 15, 10, 5]
    fourccs = [str(requested.get("preferred_fourcc", "MJPG")), "MJPG", "YUYV", ""]
    size_pairs = list(dict.fromkeys((max(width, 1), max(height, 1)) for width, height in zip(widths, heights)))
    if (int(requested.get("width", 0)), int(requested.get("height", 0))) not in size_pairs:
        size_pairs.insert(0, (int(requested.get("width", _DEFAULT_PREVIEW_WIDTH)), int(requested.get("height", _DEFAULT_PREVIEW_HEIGHT))))
    modes: List[Dict[str, Any]] = []
    for width, height in size_pairs[:8]:
        for fps in list(dict.fromkeys(fps_values))[:6]:
            for fourcc in list(dict.fromkeys(str(code or "").strip().upper() for code in fourccs))[:3]:
                modes.append({
                    "width": width,
                    "height": height,
                    "fps": round(float(max(fps, 0)), 3),
                    "fourcc": fourcc,
                    "backend_name": preferred_backend_name,
                    "candidate_source": "fallback_probe_sweep",
                    "report_kind": "fallback_candidate",
                })
    return _rank_live_camera_modes(modes, requested, preferred_backend_name)[:24]


def _live_camera_reported_mode_summary(camera_id: str, runtime: Dict[str, Any], preferred_backend_name: str) -> Dict[str, Any]:
    requested = _live_camera_capture_request(runtime)
    v4l2_summary = _v4l2_reported_live_camera_modes(camera_id, requested, preferred_backend_name)
    if bool(v4l2_summary.get("available", False)):
        ranked_candidates = list(v4l2_summary.get("reported_modes", []))
        return {
            "requested": requested,
            "reported_source": str(v4l2_summary.get("source", "reported_v4l2")),
            "reported_options": ranked_candidates,
            "ranked_candidates": ranked_candidates,
            "probe_strategy": "reported_v4l2_ranked_shortlist",
            "notes": list(v4l2_summary.get("notes", [])),
        }

    ranked_candidates = _fallback_live_camera_probe_modes(requested, preferred_backend_name)
    notes = list(v4l2_summary.get("notes", []))
    notes.append(f"Prepared {len(ranked_candidates)} bounded fallback candidate mode(s) for OpenCV probing.")
    return {
        "requested": requested,
        "reported_source": "fallback_probe_sweep",
        "reported_options": [],
        "ranked_candidates": ranked_candidates,
        "probe_strategy": "bounded_probe_sweep",
        "notes": notes,
    }


def _build_live_camera_attempt(camera_id: str, requested_mode: Dict[str, Any], candidate_mode: Dict[str, Any], backend_name: str, capture_source: Any, source_label: str, rank_index: int) -> Dict[str, Any]:
    return {
        "camera_id": camera_id,
        "capture_source": capture_source,
        "source_label": source_label,
        "backend_name": backend_name,
        "requested_mode": {
            "width": int(requested_mode.get("width", 0)),
            "height": int(requested_mode.get("height", 0)),
            "fps": int(requested_mode.get("fps", 0)),
            "fourcc": str(requested_mode.get("fourcc", requested_mode.get("preferred_fourcc", "")) or "").strip().upper(),
        },
        "candidate_mode": {
            "width": int(candidate_mode.get("width", 0)),
            "height": int(candidate_mode.get("height", 0)),
            "fps": round(float(candidate_mode.get("fps", 0.0) or 0.0), 3),
            "fourcc": str(candidate_mode.get("fourcc", "") or "").strip().upper(),
            "candidate_source": str(candidate_mode.get("candidate_source", "reported_v4l2")),
            "report_kind": str(candidate_mode.get("report_kind", "reported")),
            "rank_index": rank_index,
        },
    }


def _live_camera_probe_attempts(cv2: Any, camera_id: str, mode_summary: Dict[str, Any], probe_limit: int = 8) -> List[Dict[str, Any]]:
    requested = mode_summary.get("requested", {}) if isinstance(mode_summary.get("requested", {}), dict) else _live_camera_capture_request({})
    preferred_backend_name = _preferred_live_camera_backend_name(cv2, camera_id)
    ranked_candidates = list(mode_summary.get("ranked_candidates", []))
    attempts: List[Dict[str, Any]] = []
    seen = set()
    backend_order = [preferred_backend_name]
    if preferred_backend_name != "default":
        backend_order.append("default")
    else:
        if _is_linux_video_device(camera_id) and hasattr(cv2, "CAP_V4L2"):
            backend_order.append("CAP_V4L2")

    for rank_index, candidate_mode in enumerate(ranked_candidates[:max(probe_limit, 1)]):
        for backend_name in backend_order:
            if backend_name == "CAP_V4L2" and hasattr(cv2, "CAP_V4L2") == False:
                continue
            for capture_source, source_label in _live_camera_capture_sources(camera_id, backend_name):
                attempt = _build_live_camera_attempt(camera_id, requested, candidate_mode, backend_name, capture_source, source_label, rank_index)
                signature = (
                    attempt["backend_name"],
                    str(attempt["capture_source"]),
                    attempt["candidate_mode"]["width"],
                    attempt["candidate_mode"]["height"],
                    attempt["candidate_mode"]["fps"],
                    attempt["candidate_mode"]["fourcc"],
                )
                if signature in seen:
                    continue
                seen.add(signature)
                attempts.append(attempt)
    return attempts


def _open_opencv_capture(cv2: Any, capture_source: Any, backend_name: str) -> Any:
    backend_value = _capture_backend_value(cv2, backend_name)
    if backend_value is None:
        return cv2.VideoCapture(capture_source)
    return cv2.VideoCapture(capture_source, backend_value)


def _shape_dimensions(frame: Any) -> Tuple[int, int]:
    shape = getattr(frame, "shape", None)
    if shape is None or len(shape) < 2:
        return (0, 0)
    return (int(shape[1]), int(shape[0]))


def _measure_live_camera_runtime_burst(camera_id: str, capture: Any, source_label: str, sample_count: int = 8) -> Dict[str, Any]:
    if sample_count <= 0:
        return {"ok": True, "observed_fps": 0.0}

    started_at = time.monotonic()
    ok_frames = 0
    last_frame = None
    last_width = 0
    last_height = 0
    for _ in range(sample_count):
        read_result = _read_capture_frame(camera_id, capture, source_label, 1, 0.0)
        if not bool(read_result.get("ok", False)):
            break
        ok_frames += 1
        last_frame = read_result.get("frame_bgr")
        last_width = int(read_result.get("width", 0) or 0)
        last_height = int(read_result.get("height", 0) or 0)

    elapsed = max(0.0, time.monotonic() - started_at)
    observed_fps = round(float(ok_frames) / elapsed, 3) if ok_frames >= 2 and elapsed > 0.0 else 0.0
    return {
        "ok": True,
        "observed_fps": observed_fps,
        "frame_bgr": last_frame,
        "width": last_width,
        "height": last_height,
        "sampled_frames": ok_frames,
    }


def _actual_live_camera_mode(cv2: Any, capture: Any, frame: Any, observed_fps: float = 0.0) -> Dict[str, Any]:
    width, height = _shape_dimensions(frame)
    if width <= 0 and hasattr(cv2, "CAP_PROP_FRAME_WIDTH"):
        width = int(round(_safe_capture_get(capture, cv2.CAP_PROP_FRAME_WIDTH, 0.0)))
    if height <= 0 and hasattr(cv2, "CAP_PROP_FRAME_HEIGHT"):
        height = int(round(_safe_capture_get(capture, cv2.CAP_PROP_FRAME_HEIGHT, 0.0)))
    reported_fps = _safe_capture_get(capture, getattr(cv2, "CAP_PROP_FPS", -1), 0.0) if hasattr(cv2, "CAP_PROP_FPS") else 0.0
    actual_fps = observed_fps if observed_fps > 0.0 else reported_fps
    fourcc = _decode_fourcc(_safe_capture_get(capture, getattr(cv2, "CAP_PROP_FOURCC", -1), 0.0)) if hasattr(cv2, "CAP_PROP_FOURCC") else ""
    actual_mode = {
        "width": max(width, 0),
        "height": max(height, 0),
        "fps": round(actual_fps, 3) if actual_fps > 0.0 else 0.0,
        "fourcc": fourcc,
    }
    if observed_fps > 0.0:
        actual_mode["observed_fps"] = round(observed_fps, 3)
    if reported_fps > 0.0:
        actual_mode["reported_fps"] = round(reported_fps, 3)
    return actual_mode


def _live_camera_negotiation_result(camera_id: str, attempt: Dict[str, Any], actual_mode: Dict[str, Any]) -> Dict[str, Any]:
    requested = attempt.get("requested_mode", {}) if isinstance(attempt.get("requested_mode", {}), dict) else {}
    selected = attempt.get("candidate_mode", {}) if isinstance(attempt.get("candidate_mode", {}), dict) else {}
    selected_fourcc = str(selected.get("fourcc", "") or "").strip().upper()
    actual_fourcc = str(actual_mode.get("fourcc", "") or "").strip().upper()
    selected_fps = float(selected.get("fps", 0.0) or 0.0)
    actual_fps = float(actual_mode.get("fps", 0.0) or 0.0)
    width_matches = int(actual_mode.get("width", 0)) == int(selected.get("width", 0))
    height_matches = int(actual_mode.get("height", 0)) == int(selected.get("height", 0))
    fps_matches = selected_fps <= 0.0 or (actual_fps > 0.0 and abs(actual_fps - selected_fps) <= max(1.0, selected_fps * 0.2))
    fourcc_matches = selected_fourcc == "" or actual_fourcc == selected_fourcc
    backend_name = str(attempt.get("backend_name", "default"))
    preferred_backend_name = "CAP_V4L2" if _is_linux_video_device(camera_id) else "default"
    requested_fps_key = _live_camera_fps_sort_key(actual_fps, int(requested.get("fps", 0)))
    score = 0
    score -= requested_fps_key[0] * 100000
    score -= int(round(requested_fps_key[1] * 1000.0)) * 100
    score -= _live_camera_resolution_delta(actual_mode, requested)
    score += _live_camera_format_score(actual_fourcc, str(requested.get("preferred_fourcc", requested.get("fourcc", "")))) * 1000
    score += _live_camera_backend_score(backend_name, preferred_backend_name) * 100
    return {
        "camera_id": camera_id,
        "backend": backend_name,
        "source_label": str(attempt.get("source_label", "device path")),
        "capture_source": attempt.get("capture_source"),
        "requested": {
            "width": int(requested.get("width", 0)),
            "height": int(requested.get("height", 0)),
            "fps": int(requested.get("fps", 0)),
            "fourcc": str(requested.get("fourcc", requested.get("preferred_fourcc", "")) or "").strip().upper(),
        },
        "selected": {
            "width": int(selected.get("width", 0)),
            "height": int(selected.get("height", 0)),
            "fps": round(float(selected.get("fps", 0.0) or 0.0), 3),
            "fourcc": selected_fourcc,
            "candidate_source": str(selected.get("candidate_source", "reported_v4l2")),
            "report_kind": str(selected.get("report_kind", "reported")),
            "rank_index": int(selected.get("rank_index", -1)),
            "backend": backend_name,
            "source_label": str(attempt.get("source_label", "device path")),
            "capture_source": attempt.get("capture_source"),
        },
        "actual": {
            "width": int(actual_mode.get("width", 0)),
            "height": int(actual_mode.get("height", 0)),
            "fps": actual_fps,
            "fourcc": actual_fourcc,
            "observed_fps": round(float(actual_mode.get("observed_fps", 0.0) or 0.0), 3),
            "reported_fps": round(float(actual_mode.get("reported_fps", 0.0) or 0.0), 3),
            "backend": backend_name,
            "source_label": str(attempt.get("source_label", "device path")),
            "capture_source": attempt.get("capture_source"),
        },
        "matched": {
            "width": width_matches,
            "height": height_matches,
            "fps": fps_matches,
            "fourcc": fourcc_matches,
        },
        "requested_fourcc_applied": selected_fourcc != "" and fourcc_matches,
        "preferred_backend": backend_name == preferred_backend_name,
        "score": score,
    }


def _live_camera_negotiation_note(negotiation: Dict[str, Any]) -> str:
    requested = negotiation.get("requested", {}) if isinstance(negotiation.get("requested", {}), dict) else {}
    selected = negotiation.get("selected", {}) if isinstance(negotiation.get("selected", {}), dict) else {}
    actual = negotiation.get("actual", {}) if isinstance(negotiation.get("actual", {}), dict) else {}
    requested_desc = f"{requested.get('width', 0)}x{requested.get('height', 0)}@{requested.get('fps', 0)}"
    if str(requested.get("fourcc", "")) != "":
        requested_desc += f" {requested.get('fourcc', '')}"
    selected_desc = f"{selected.get('width', 0)}x{selected.get('height', 0)}@{selected.get('fps', 0)}"
    if str(selected.get("fourcc", "")) != "":
        selected_desc += f" {selected.get('fourcc', '')}"
    actual_desc = f"{actual.get('width', 0)}x{actual.get('height', 0)}"
    actual_fps = float(actual.get("fps", 0.0) or 0.0)
    if actual_fps > 0.0:
        actual_desc += f"@{actual_fps:.3f}"
    actual_fourcc = str(actual.get("fourcc", "") or "")
    if actual_fourcc != "":
        actual_desc += f" {actual_fourcc}"
    observed_fps = float(actual.get("observed_fps", 0.0) or 0.0)
    reported_fps = float(actual.get("reported_fps", 0.0) or 0.0)
    actual_suffix = ""
    if observed_fps > 0.0 and reported_fps > 0.0 and abs(observed_fps - reported_fps) > 0.5:
        actual_suffix = f" (runtime observed ~{observed_fps:.3f} FPS after OpenCV reported {reported_fps:.3f} FPS)"
    backend = str(negotiation.get("backend", "default"))
    source_label = str(negotiation.get("source_label", "device path"))
    selection_source = str(selected.get("candidate_source", "reported_v4l2"))
    matches = negotiation.get("matched", {}) if isinstance(negotiation.get("matched", {}), dict) else {}
    if all(bool(matches.get(key, False)) for key in ("width", "height", "fps", "fourcc")):
        return f"Live camera requested {requested_desc}; selected {selected_desc} from {selection_source} via {backend}/{source_label}; actual mode is {actual_desc}{actual_suffix}."
    return f"Live camera requested {requested_desc}; selected {selected_desc} from {selection_source} via {backend}/{source_label}, but actual mode negotiated as {actual_desc}{actual_suffix}."


def _read_capture_frame(camera_id: str, capture: Any, source_label: str, read_retries: int, retry_sleep_seconds: float) -> Dict[str, Any]:
    frame = None
    for attempt in range(read_retries):
        ok, candidate = capture.read()
        if ok and candidate is not None:
            frame = candidate
            break
        if attempt < (read_retries - 1):
            time.sleep(retry_sleep_seconds)

    if frame is None:
        return {
            "ok": False,
            "error_info": {
                "code": "camera_read_failed",
                "message": f"OpenCV could not read a frame from selected camera '{camera_id}' via {source_label}",
            },
        }

    width, height = _shape_dimensions(frame)
    if width <= 0 or height <= 0:
        return {
            "ok": False,
            "error_info": {
                "code": "camera_frame_invalid",
                "message": f"OpenCV returned non-positive frame dimensions for selected camera '{camera_id}' via {source_label}",
            },
        }

    return {"ok": True, "frame_bgr": frame, "width": width, "height": height}


def _apply_live_camera_candidate_settings(cv2: Any, capture: Any, candidate_mode: Dict[str, Any]) -> None:
    if hasattr(cv2, "CAP_PROP_FRAME_WIDTH"):
        _safe_capture_set(capture, cv2.CAP_PROP_FRAME_WIDTH, int(candidate_mode.get("width", 0)))
    if hasattr(cv2, "CAP_PROP_FRAME_HEIGHT"):
        _safe_capture_set(capture, cv2.CAP_PROP_FRAME_HEIGHT, int(candidate_mode.get("height", 0)))
    if float(candidate_mode.get("fps", 0.0) or 0.0) > 0.0 and hasattr(cv2, "CAP_PROP_FPS"):
        _safe_capture_set(capture, cv2.CAP_PROP_FPS, float(candidate_mode.get("fps", 0.0)))
    encoded_fourcc = _encode_fourcc(cv2, str(candidate_mode.get("fourcc", "")))
    if encoded_fourcc is not None and hasattr(cv2, "CAP_PROP_FOURCC"):
        _safe_capture_set(capture, cv2.CAP_PROP_FOURCC, encoded_fourcc)


def _probe_live_camera_attempt(cv2: Any, camera_id: str, attempt: Dict[str, Any], purpose: str, measure_runtime_fps: bool = False) -> Dict[str, Any]:
    capture = _open_opencv_capture(cv2, attempt["capture_source"], str(attempt.get("backend_name", "default")))
    if not capture.isOpened():
        try:
            capture.release()
        except Exception:
            pass
        return {
            "ok": False,
            "error_info": {
                "code": "camera_open_failed",
                "message": f"OpenCV could not open selected camera '{camera_id}' via {attempt['backend_name']}/{attempt['source_label']} for {purpose}",
            },
        }

    try:
        _apply_live_camera_candidate_settings(cv2, capture, attempt.get("candidate_mode", {}))
        capture_path_label = f"{attempt['backend_name']}/{attempt['source_label']}"
        read_result = _read_capture_frame(camera_id, capture, capture_path_label, 5, 0.1 if purpose == "sample capture" else 0.02)
        if not bool(read_result.get("ok", False)):
            return read_result
        observed_fps = 0.0
        measured_frame = read_result.get("frame_bgr")
        measured_width = int(read_result.get("width", 0) or 0)
        measured_height = int(read_result.get("height", 0) or 0)
        if measure_runtime_fps:
            measured = _measure_live_camera_runtime_burst(camera_id, capture, capture_path_label)
            observed_fps = float(measured.get("observed_fps", 0.0) or 0.0)
            if measured.get("frame_bgr") is not None and int(measured.get("width", 0) or 0) > 0 and int(measured.get("height", 0) or 0) > 0:
                measured_frame = measured.get("frame_bgr")
                measured_width = int(measured.get("width", 0) or 0)
                measured_height = int(measured.get("height", 0) or 0)
        actual_mode = _actual_live_camera_mode(cv2, capture, measured_frame, observed_fps=observed_fps)
        negotiation = _live_camera_negotiation_result(camera_id, attempt, actual_mode)
        return {
            "ok": True,
            "cv2": cv2,
            "capture": capture,
            "source_label": capture_path_label,
            "capture_negotiation": negotiation,
            "notes": [_live_camera_negotiation_note(negotiation)],
            "initial_frame_bgr": measured_frame,
            "initial_frame_width": measured_width,
            "initial_frame_height": measured_height,
        }
    except Exception:
        try:
            capture.release()
        except Exception:
            pass
        raise


def _mode_summary_reported_payload(mode_summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    payload: List[Dict[str, Any]] = []
    for mode in mode_summary.get("reported_options", []):
        if not isinstance(mode, dict):
            continue
        payload.append({
            "width": int(mode.get("width", 0) or 0),
            "height": int(mode.get("height", 0) or 0),
            "fps": round(float(mode.get("fps", 0.0) or 0.0), 3),
            "fourcc": str(mode.get("fourcc", "") or "").strip().upper(),
            "candidate_source": str(mode.get("candidate_source", mode_summary.get("reported_source", "reported_v4l2"))),
            "report_kind": str(mode.get("report_kind", "reported")),
        })
    return payload


def _camera_options_payload(mode_summary: Dict[str, Any], probed_options: Sequence[Dict[str, Any]], selected: Optional[Dict[str, Any]] = None, actual: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "selection_policy": "framerate_first_resolution_second_format_backend",
        "requested": dict(mode_summary.get("requested", {})),
        "reported_source": str(mode_summary.get("reported_source", "fallback_probe_sweep")),
        "probe_strategy": str(mode_summary.get("probe_strategy", "bounded_probe_sweep")),
        "reported_options": _mode_summary_reported_payload(mode_summary),
        "probed_options": [probe_result.get("capture_negotiation", {}).copy() for probe_result in probed_options if isinstance(probe_result, dict) and isinstance(probe_result.get("capture_negotiation", {}), dict)],
        "selected": selected.copy() if isinstance(selected, dict) else {},
        "actual": actual.copy() if isinstance(actual, dict) else {},
        "notes": list(mode_summary.get("notes", [])),
    }


def _select_live_camera_capture_session(camera_id: str, runtime: Dict[str, Any], purpose: str, include_camera_options: bool = True) -> Dict[str, Any]:
    try:
        import cv2  # type: ignore
    except Exception as exc:
        return {
            "ok": False,
            "error_info": {
                "code": "opencv_unavailable",
                "message": f"OpenCV import failed while opening camera '{camera_id}': {exc}",
            },
        }

    preferred_backend_name = _preferred_live_camera_backend_name(cv2, camera_id)
    mode_summary = _live_camera_reported_mode_summary(camera_id, runtime, preferred_backend_name)
    attempts = _live_camera_probe_attempts(cv2, camera_id, mode_summary)
    measure_runtime_fps = str(mode_summary.get("reported_source", "reported_v4l2")) == "fallback_probe_sweep"
    probe_results: List[Dict[str, Any]] = []
    best_session: Optional[Dict[str, Any]] = None
    last_failure = {
        "ok": False,
        "error_info": {
            "code": "camera_open_failed",
            "message": f"OpenCV could not open selected camera '{camera_id}' for {purpose}",
        },
    }

    for attempt in attempts:
        result = _probe_live_camera_attempt(cv2, camera_id, attempt, purpose, measure_runtime_fps=measure_runtime_fps)
        if not bool(result.get("ok", False)):
            last_failure = result
            continue
        probe_results.append({
            "capture_negotiation": result.get("capture_negotiation", {}).copy(),
            "notes": list(result.get("notes", [])),
        })
        if best_session is None or int(result.get("capture_negotiation", {}).get("score", -1)) > int(best_session.get("capture_negotiation", {}).get("score", -1)):
            if best_session is not None:
                try:
                    best_session["capture"].release()
                except Exception:
                    pass
            best_session = result
        else:
            try:
                result["capture"].release()
            except Exception:
                pass

        matched = result.get("capture_negotiation", {}).get("matched", {}) if isinstance(result.get("capture_negotiation", {}).get("matched", {}), dict) else {}
        if all(bool(matched.get(key, False)) for key in ("width", "height", "fps", "fourcc")):
            break

    if best_session is None:
        return last_failure

    selected_mode = best_session.get("capture_negotiation", {}).get("selected", {}) if isinstance(best_session.get("capture_negotiation", {}).get("selected", {}), dict) else {}
    actual_mode = best_session.get("capture_negotiation", {}).get("actual", {}) if isinstance(best_session.get("capture_negotiation", {}).get("actual", {}), dict) else {}
    camera_options = _camera_options_payload(mode_summary, probe_results, selected=selected_mode, actual=actual_mode) if include_camera_options else {}
    best_session["camera_options"] = camera_options
    negotiation = best_session.get("capture_negotiation", {}).copy()
    negotiation["selection_policy"] = camera_options.get("selection_policy", "framerate_first_resolution_second_format_backend")
    negotiation["reported_source"] = camera_options.get("reported_source", "fallback_probe_sweep")
    negotiation["reported_options"] = camera_options.get("reported_options", [])
    negotiation["probed_options"] = camera_options.get("probed_options", [])
    best_session["capture_negotiation"] = negotiation
    best_session["notes"] = list(mode_summary.get("notes", [])) + list(best_session.get("notes", []))
    return best_session


def _capture_frame_with_opencv_source(cv2: Any, camera_id: str, capture_source: Any, source_label: str) -> Dict[str, Any]:
    capture = cv2.VideoCapture(capture_source)
    try:
        if not capture.isOpened():
            return {
                "ok": False,
                "error_info": {
                    "code": "camera_open_failed",
                    "message": f"OpenCV could not open selected camera '{camera_id}' via {source_label} for sample capture",
                },
            }

        read_result = _read_capture_frame(camera_id, capture, source_label, 5, 0.1)
        if not bool(read_result.get("ok", False)):
            return read_result

        width = int(read_result.get("width", 0))
        height = int(read_result.get("height", 0))
        timestamp_ms = _now_ms()
        note = f"Captured one live sample frame from '{camera_id}' with dimensions {width}x{height}."
        if source_label != "device path":
            note = f"Captured one live sample frame from '{camera_id}' with dimensions {width}x{height} via {source_label}."

        return {
            "ok": True,
            "frame_bgr": read_result.get("frame_bgr"),
            "raw_tracking_frame": _raw_tracking_frame_base("live_camera", camera_id, width, height, timestamp_ms),
            "notes": [note],
        }
    finally:
        capture.release()


def _capture_live_camera_sample(camera_id: str, runtime: Dict[str, Any], sample_index: int = 0, dynamic_timestamp: bool = False) -> Dict[str, Any]:
    fixture_sample = _sample_from_fixture(camera_id, runtime, sample_index=sample_index, dynamic_timestamp=dynamic_timestamp, source_kind="live_camera")
    if fixture_sample is not None:
        if fixture_sample.get("fixture_eof"):
            return {
                "ok": False,
                "error_info": {
                    "code": "fixture_sequence_exhausted",
                    "message": f"Fixture sequence exhausted for live camera '{camera_id}'",
                },
            }
        return {"ok": True, **fixture_sample}

    capture_session = _select_live_camera_capture_session(camera_id, runtime, "sample capture")
    if not bool(capture_session.get("ok", False)):
        return capture_session

    try:
        frame = capture_session.get("initial_frame_bgr")
        width = int(capture_session.get("initial_frame_width", 0))
        height = int(capture_session.get("initial_frame_height", 0))
        if frame is None or width <= 0 or height <= 0:
            followup = _read_capture_frame(camera_id, capture_session.get("capture"), str(capture_session.get("source_label", "device path")), 5, 0.1)
            if not bool(followup.get("ok", False)):
                return followup
            frame = followup.get("frame_bgr")
            width = int(followup.get("width", 0))
            height = int(followup.get("height", 0))

        timestamp_ms = _now_ms()
        source_label = str(capture_session.get("source_label", "device path"))
        note = f"Captured one live sample frame from '{camera_id}' with dimensions {width}x{height}."
        if source_label != "device path":
            note = f"Captured one live sample frame from '{camera_id}' with dimensions {width}x{height} via {source_label}."
        notes = list(capture_session.get("notes", [])) + [note]
        return {
            "ok": True,
            "frame_bgr": frame,
            "raw_tracking_frame": _raw_tracking_frame_base("live_camera", camera_id, width, height, timestamp_ms),
            "notes": notes,
            "capture_negotiation": capture_session.get("capture_negotiation", {}),
            "camera_options": capture_session.get("camera_options", {}),
        }
    finally:
        _close_live_camera_capture_session(capture_session)


def _capture_video_file_sample(video_path: str, runtime: Dict[str, Any], sample_index: int = 0, dynamic_timestamp: bool = False) -> Dict[str, Any]:
    fixture_sample = _sample_from_fixture(video_path, runtime, sample_index=sample_index, dynamic_timestamp=dynamic_timestamp, source_kind="video_file")
    if fixture_sample is not None:
        if fixture_sample.get("fixture_eof"):
            return {
                "ok": False,
                "error_info": {
                    "code": "video_file_eof",
                    "message": f"Replay video '{video_path}' reached EOF before producing another frame",
                },
            }
        return {"ok": True, **fixture_sample}

    try:
        import cv2  # type: ignore
    except Exception as exc:
        return {
            "ok": False,
            "error_info": {
                "code": "opencv_unavailable",
                "message": f"OpenCV import failed while sampling replay video '{video_path}': {exc}",
            },
        }

    result = _capture_frame_with_opencv_source(cv2, video_path, video_path, "video file")
    if not bool(result.get("ok", False)):
        error_info = result.get("error_info", {
            "code": "video_file_read_failed",
            "message": f"Failed to read replay video '{video_path}'",
        })
        if error_info.get("code") == "camera_open_failed":
            error_info = {
                "code": "video_file_open_failed",
                "message": f"OpenCV could not open replay video '{video_path}' for sample capture",
            }
        elif error_info.get("code") == "camera_read_failed":
            error_info = {
                "code": "video_file_read_failed",
                "message": f"OpenCV could not read a frame from replay video '{video_path}'",
            }
        return {"ok": False, "error_info": error_info}

    raw_tracking_frame = result.get("raw_tracking_frame", {}).copy()
    raw_tracking_frame["source_kind"] = "video_file"
    raw_tracking_frame["source_id"] = video_path
    return {
        "ok": True,
        "frame_bgr": result.get("frame_bgr"),
        "raw_tracking_frame": raw_tracking_frame,
        "notes": [f"Captured one replay frame from '{video_path}' via video file source."],
    }


def _replay_eof_snapshot(request: Dict[str, Any], selected_source_id: str, loop_started_ms: int, sample_index: int, notes: Optional[List[str]] = None) -> Dict[str, Any]:
    runtime = request.get("runtime", {}) if isinstance(request.get("runtime", {}), dict) else {}
    base_notes = list(notes or [])
    base_notes.append(f"Replay source '{selected_source_id}' reached EOF and stopped cleanly.")
    return {
        "ok": True,
        "cameras": _enumerate_cameras(runtime),
        "selected_camera_id": selected_source_id,
        "health": {
            **_base_health("startup", runtime),
            "status": "idle",
            "runtime_available": True,
            "bridge_connected": True,
            "process_active": False,
            "camera_accessible": True,
            "tracking_active": False,
            "healthy": True,
            "loop_iteration": sample_index,
            "loop_started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(loop_started_ms / 1000.0)),
            "probed_at": _now_iso(),
            "selected_camera_id": selected_source_id,
            "notes": base_notes,
        },
        "preview_descriptor": _preview_descriptor(request.get("preview", {}), runtime),
        "raw_tracking_frame": {},
    }


def _rewind_replay_capture(capture: Any, cv2: Any, replay_start_time_sec: float) -> bool:
    target_msec = max(replay_start_time_sec, 0.0) * 1000.0
    try:
        rewound = capture.set(cv2.CAP_PROP_POS_MSEC, target_msec)
    except Exception:
        rewound = False
    return bool(rewound)


def _run_video_file_session(request: Dict[str, Any], session_dir: str) -> int:
    _arm_owner_orphan_protection()
    os.makedirs(session_dir, exist_ok=True)
    _write_json_atomic(_session_request_path(session_dir), request)
    runtime = request.get("runtime", {}) if isinstance(request.get("runtime", {}), dict) else {}
    source = request.get("source", {}) if isinstance(request.get("source", {}), dict) else {}
    preview = request.get("preview", {}) if isinstance(request.get("preview", {}), dict) else {}
    preview_config = _preview_runtime_config(preview, runtime)
    tracking = request.get("tracking", {}) if isinstance(request.get("tracking", {}), dict) else {}
    tracking_semantics = _tracking_semantics(request)
    tracking_filter_state: Optional[Dict[str, Any]] = {} if bool(tracking_semantics.get('filter_enabled', True)) else None
    video_path = str(source.get("path", "")).strip()
    tracking_interval = _fps_interval_seconds(runtime.get("tracking_max_fps", _DEFAULT_TRACKING_MAX_FPS), _DEFAULT_TRACKING_MAX_FPS)
    state_interval = _fps_interval_seconds(runtime.get("state_update_max_fps", _DEFAULT_STATE_UPDATE_MAX_FPS), _DEFAULT_STATE_UPDATE_MAX_FPS)
    preview_interval = _fps_interval_seconds(preview_config.get("max_fps", _DEFAULT_PREVIEW_MAX_FPS), _DEFAULT_PREVIEW_MAX_FPS)
    loop_started_ms = _now_ms()
    sample_index = 0
    fixture_map = _sample_fixture_map(runtime)
    use_fixture_sequence = isinstance(fixture_map.get(video_path), dict)
    replay_start_time_sec = max(0.0, float(source.get("start_time_sec", 0.0) or 0.0))
    replay_loop_start_raw = source.get("loop_start_time_sec", replay_start_time_sec)
    replay_loop_start_time_sec = max(0.0, float(replay_loop_start_raw if replay_loop_start_raw is not None else replay_start_time_sec))
    loop_enabled = bool(source.get("loop", False))
    fixture_frame_index = 0
    duration_sec = 0.0
    last_state_write_at: Optional[float] = None
    last_preview_write_at: Optional[float] = None
    last_preview_descriptor = _preview_descriptor(preview, runtime)

    capture = None
    cv2 = None
    if not use_fixture_sequence:
        try:
            import cv2 as _cv2  # type: ignore
            cv2 = _cv2
        except Exception as exc:
            snapshot = _continuous_error_snapshot(request, {
                "error_info": {
                    "code": "opencv_unavailable",
                    "message": f"OpenCV import failed while opening replay video '{video_path}': {exc}",
                },
                "selected_camera_id": video_path,
            }, sample_index, loop_started_ms)
            _write_session_snapshot(session_dir, snapshot)
            return 1
        capture = cv2.VideoCapture(video_path)
        if not capture.isOpened():
            snapshot = _continuous_error_snapshot(request, {
                "error_info": {
                    "code": "video_file_open_failed",
                    "message": f"OpenCV could not open replay video '{video_path}'",
                },
                "selected_camera_id": video_path,
            }, sample_index, loop_started_ms)
            _write_session_snapshot(session_dir, snapshot)
            return 1
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        frame_count = float(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
        if fps > 0.0 and frame_count > 0.0:
            duration_sec = frame_count / fps
        if replay_start_time_sec > 0.0:
            capture.set(cv2.CAP_PROP_POS_MSEC, replay_start_time_sec * 1000.0)

    inference_session: Optional[Dict[str, Any]] = None
    if not use_fixture_sequence:
        inference_session = _create_inference_session(runtime, tracking)
        if not bool(inference_session.get("ok", False)):
            snapshot = _continuous_error_snapshot(request, {
                "error_info": inference_session.get("error_info", {
                    "code": "mediapipe_inference_failed",
                    "message": f"Failed to initialize continuous pose inference for replay source '{video_path}'",
                }),
                "selected_camera_id": video_path,
                "health": {"camera_accessible": True},
            }, sample_index, loop_started_ms)
            _write_session_snapshot(session_dir, snapshot)
            if capture is not None:
                capture.release()
            return 1

    try:
        while True:
            iteration_started_at = time.monotonic()
            if os.path.exists(_session_stop_path(session_dir)):
                shutdown_snapshot = {
                    "ok": True,
                    "cameras": _enumerate_cameras(runtime),
                    "selected_camera_id": video_path,
                    "health": {
                        **_base_health("shutdown", runtime),
                        "status": "idle",
                        "runtime_available": True,
                        "bridge_connected": True,
                        "process_active": False,
                        "camera_accessible": True,
                        "tracking_active": False,
                        "healthy": True,
                        "selected_camera_id": video_path,
                        "notes": [f"Replay session for '{video_path}' stopped cleanly."],
                    },
                    "preview_descriptor": last_preview_descriptor.copy(),
                    "playback_status": _playback_status(video_path, replay_start_time_sec, duration_sec, "paused", True),
                    "raw_tracking_frame": {},
                }
                _write_session_snapshot(session_dir, shutdown_snapshot)
                return 0
            if _runtime_shutdown_reason() != "":
                shutdown_note = f"Replay session for '{video_path}' exited because its owner process disappeared unexpectedly."
                if _runtime_shutdown_reason() != "owner_process_disappeared":
                    shutdown_note = f"Replay session for '{video_path}' exited after receiving {_runtime_shutdown_reason()}."
                shutdown_snapshot = {
                    "ok": True,
                    "cameras": _enumerate_cameras(runtime),
                    "selected_camera_id": video_path,
                    "health": {
                        **_base_health(_runtime_shutdown_reason(), runtime),
                        "status": "idle",
                        "runtime_available": True,
                        "bridge_connected": True,
                        "process_active": False,
                        "camera_accessible": True,
                        "tracking_active": False,
                        "healthy": True,
                        "selected_camera_id": video_path,
                        "notes": [shutdown_note],
                    },
                    "preview_descriptor": last_preview_descriptor.copy(),
                    "playback_status": _playback_status(video_path, replay_start_time_sec, duration_sec, "paused", True),
                    "raw_tracking_frame": {},
                }
                _write_session_snapshot(session_dir, shutdown_snapshot)
                return 0

            if use_fixture_sequence:
                sampled = _capture_video_file_sample(video_path, runtime, sample_index=fixture_frame_index, dynamic_timestamp=True)
                if not bool(sampled.get("ok", False)) and sampled.get("error_info", {}).get("code") == "video_file_eof":
                    if loop_enabled:
                        fixture_frame_index = 0
                        continue
                    eof_snapshot = _replay_eof_snapshot(request, video_path, loop_started_ms, sample_index)
                    eof_snapshot["preview_descriptor"] = last_preview_descriptor.copy()
                    _write_session_snapshot(session_dir, eof_snapshot)
                    return 0
            else:
                assert capture is not None
                ok, frame = capture.read()
                if not ok or frame is None:
                    if loop_enabled and _rewind_replay_capture(capture, cv2, replay_loop_start_time_sec):
                        continue
                    eof_snapshot = _replay_eof_snapshot(request, video_path, loop_started_ms, sample_index)
                    eof_snapshot["preview_descriptor"] = last_preview_descriptor.copy()
                    eof_snapshot["playback_status"] = _playback_status(video_path, duration_sec, duration_sec, "ended", True)
                    _write_session_snapshot(session_dir, eof_snapshot)
                    return 0
                shape = getattr(frame, "shape", None)
                if shape is None or len(shape) < 2:
                    snapshot = _continuous_error_snapshot(request, {
                        "error_info": {
                            "code": "video_file_frame_invalid",
                            "message": f"OpenCV returned an invalid replay frame shape for '{video_path}'",
                        },
                        "selected_camera_id": video_path,
                    }, sample_index, loop_started_ms)
                    _write_session_snapshot(session_dir, snapshot)
                    return 1
                height = int(shape[0])
                width = int(shape[1])
                sampled = {
                    "ok": True,
                    "frame_bgr": frame,
                    "raw_tracking_frame": _raw_tracking_frame_base("video_file", video_path, width, height, _now_ms()),
                    "notes": [f"Captured replay frame {sample_index} from '{video_path}'."],
                }

            if not bool(sampled.get("ok", False)):
                snapshot = _continuous_error_snapshot(request, {
                    **sampled,
                    "selected_camera_id": video_path,
                }, sample_index, loop_started_ms)
                _write_session_snapshot(session_dir, snapshot)
                return 1

            inferred = _infer_pose_landmarks(sampled, runtime, tracking=tracking, inference_session=inference_session, tracking_semantics=tracking_semantics, filter_state=tracking_filter_state)
            if not bool(inferred.get("ok", False)):
                snapshot = _continuous_error_snapshot(request, {
                    "error_info": inferred.get("error_info", {
                        "code": "mediapipe_inference_failed",
                        "message": f"Failed to infer pose landmarks from replay source '{video_path}'",
                    }),
                    "raw_tracking_frame": inferred.get("raw_tracking_frame", {}),
                    "selected_camera_id": video_path,
                    "health": {
                        "camera_accessible": True,
                    },
                }, sample_index, loop_started_ms)
                _write_session_snapshot(session_dir, snapshot)
                return 1

            raw_tracking_frame = inferred.get("raw_tracking_frame", {}).copy()
            landmarks = raw_tracking_frame.get("landmarks")
            health = {
                **_base_health("startup", runtime),
                "status": "running",
                "runtime_available": True,
                "bridge_connected": True,
                "process_active": True,
                "camera_accessible": True,
                "tracking_active": True,
                "healthy": True,
                "loop_iteration": sample_index,
                "loop_started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(loop_started_ms / 1000.0)),
                "probed_at": _now_iso(),
                "selected_camera_id": video_path,
                "selected_camera_label": os.path.basename(video_path) or video_path,
                "notes": list(inferred.get("notes", [])) + ["Continuous replay runtime loop remains alive while replay frames are available."],
            }
            if isinstance(landmarks, list) and landmarks:
                health["notes"].append(f"Returning {len(landmarks)} raw replay pose landmark(s).")
            else:
                health["notes"].append("Returning no raw landmarks because the replay frame did not produce a pose.")
            current_time_sec = replay_start_time_sec
            if capture is not None and cv2 is not None:
                current_time_sec = max(0.0, float(capture.get(cv2.CAP_PROP_POS_MSEC) or 0.0) / 1000.0)

            sampled_snapshot = {
                "ok": True,
                "cameras": _enumerate_cameras(runtime),
                "selected_camera_id": video_path,
                "health": health,
                "preview_descriptor": last_preview_descriptor.copy(),
                "playback_status": _playback_status(video_path, current_time_sec, duration_sec),
                "raw_tracking_frame": raw_tracking_frame,
                "frame_bgr": sampled.get("frame_bgr"),
            }

            now = time.monotonic()
            should_write_state = last_state_write_at is None or state_interval <= 0.0 or (now - last_state_write_at) >= state_interval
            include_preview = bool(preview_config.get("enabled", True)) and should_write_state and (last_preview_write_at is None or preview_interval <= 0.0 or (now - last_preview_write_at) >= preview_interval)
            if should_write_state:
                snapshot = _continuous_success_snapshot(request, sampled_snapshot, sample_index, loop_started_ms, session_dir, include_preview_frame=include_preview, existing_preview_descriptor=last_preview_descriptor)
                last_preview_descriptor = snapshot.get("preview_descriptor", last_preview_descriptor).copy()
                _write_session_snapshot(session_dir, snapshot)
                last_state_write_at = now
                if include_preview:
                    last_preview_write_at = now

            sample_index += 1
            if use_fixture_sequence:
                fixture_frame_index += 1
            if tracking_interval > 0.0:
                sleep_seconds = max(0.0, tracking_interval - (time.monotonic() - iteration_started_at))
                if sleep_seconds > 0.0:
                    time.sleep(sleep_seconds)
    finally:
        if inference_session is not None:
            _close_inference_session(inference_session)
        if capture is not None:
            capture.release()


def _landmarks_from_legacy_results(results: Any) -> List[Dict[str, float]]:
    pose_landmarks = getattr(results, "pose_landmarks", None)
    landmarks_source = getattr(pose_landmarks, "landmark", None) if pose_landmarks is not None else None
    landmarks: List[Dict[str, float]] = []
    if landmarks_source is not None:
        for index, landmark in enumerate(landmarks_source):
            landmarks.append(
                {
                    "id": index,
                    "x": float(getattr(landmark, "x", 0.0)),
                    "y": float(getattr(landmark, "y", 0.0)),
                    "z": float(getattr(landmark, "z", 0.0)),
                    "visibility": float(getattr(landmark, "visibility", 0.0)),
                }
            )
    return landmarks


def _landmarks_from_tasks_result(result: Any) -> List[Dict[str, float]]:
    pose_landmarks = getattr(result, "pose_landmarks", None)
    if not isinstance(pose_landmarks, list) or len(pose_landmarks) == 0:
        return []

    first_pose = pose_landmarks[0]
    if not isinstance(first_pose, list):
        return []

    landmarks: List[Dict[str, float]] = []
    for index, landmark in enumerate(first_pose):
        landmarks.append(
            {
                "id": index,
                "x": float(getattr(landmark, "x", 0.0)),
                "y": float(getattr(landmark, "y", 0.0)),
                "z": float(getattr(landmark, "z", 0.0)),
                "visibility": float(getattr(landmark, "visibility", 0.0)),
            }
        )
    return landmarks


def _normalize_model_complexity(runtime: Dict[str, Any]) -> int:
    raw = runtime.get("model_complexity", _DEFAULT_MODEL_COMPLEXITY)
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_MODEL_COMPLEXITY
    if parsed < 0 or parsed > 2:
        return _DEFAULT_MODEL_COMPLEXITY
    return parsed


def _default_pose_landmarker_model_paths(runtime: Dict[str, Any]) -> Sequence[str]:
    model_filename = _MODEL_FILENAMES.get(_normalize_model_complexity(runtime), _MODEL_FILENAMES[_DEFAULT_MODEL_COMPLEXITY])
    return (
        f"models/{model_filename}",
        f"runtime/models/{model_filename}",
    )


def _resolve_pose_landmarker_model_path(runtime: Dict[str, Any]) -> str:
    environment = _runtime_env(runtime)
    candidate_values = [
        str(runtime.get("pose_landmarker_model_path", "")).strip(),
        str(runtime.get("model_asset_path", "")).strip(),
        str(environment.get("AEROBEAT_MEDIAPIPE_POSE_LANDMARKER_MODEL_PATH", "")).strip(),
        str(environment.get("MEDIAPIPE_POSE_LANDMARKER_MODEL_PATH", os.environ.get("MEDIAPIPE_POSE_LANDMARKER_MODEL_PATH", ""))).strip(),
    ]

    for candidate in candidate_values:
        if candidate == "":
            continue
        resolved = _resolve_runtime_path(runtime, candidate)
        if os.path.isfile(resolved):
            return resolved

    for candidate in _default_pose_landmarker_model_paths(runtime):
        resolved = _resolve_runtime_path(runtime, candidate)
        if os.path.isfile(resolved):
            return resolved

    return ""


def _default_hand_landmarker_model_paths(_runtime: Dict[str, Any]) -> Sequence[str]:
    return (
        f"models/{_HAND_LANDMARKER_MODEL_FILENAMES[0]}",
        f"runtime/models/{_HAND_LANDMARKER_MODEL_FILENAMES[1]}",
    )


def _resolve_hand_landmarker_model_path(runtime: Dict[str, Any]) -> str:
    environment = _runtime_env(runtime)
    candidate_values = [
        str(runtime.get("hand_landmarker_model_path", "")).strip(),
        str(environment.get("AEROBEAT_MEDIAPIPE_HAND_LANDMARKER_MODEL_PATH", "")).strip(),
        str(environment.get("MEDIAPIPE_HAND_LANDMARKER_MODEL_PATH", os.environ.get("MEDIAPIPE_HAND_LANDMARKER_MODEL_PATH", ""))).strip(),
    ]

    for candidate in candidate_values:
        if candidate == "":
            continue
        resolved = _resolve_runtime_path(runtime, candidate)
        if os.path.isfile(resolved):
            return resolved

    for candidate in _default_hand_landmarker_model_paths(runtime):
        resolved = _resolve_runtime_path(runtime, candidate)
        if os.path.isfile(resolved):
            return resolved

    return ""


def _open_live_camera_capture_session(camera_id: str, runtime: Dict[str, Any]) -> Dict[str, Any]:
    fixture_sample = _sample_from_fixture(camera_id, runtime, sample_index=0, dynamic_timestamp=False, source_kind="live_camera")
    if fixture_sample is not None:
        return {"ok": True, "fixture_only": True}
    return _select_live_camera_capture_session(camera_id, runtime, "continuous capture")


def _close_live_camera_capture_session(capture_session: Dict[str, Any]) -> None:
    capture = capture_session.get("capture")
    if capture is None:
        return
    try:
        capture.release()
    except Exception:
        pass


def _capture_live_camera_session_sample(camera_id: str, runtime: Dict[str, Any], capture_session: Dict[str, Any], sample_index: int = 0, dynamic_timestamp: bool = False) -> Dict[str, Any]:
    fixture_sample = _sample_from_fixture(camera_id, runtime, sample_index=sample_index, dynamic_timestamp=dynamic_timestamp, source_kind="live_camera")
    if fixture_sample is not None:
        if fixture_sample.get("fixture_eof"):
            return {
                "ok": False,
                "error_info": {
                    "code": "fixture_sequence_exhausted",
                    "message": f"Fixture sequence exhausted for live camera '{camera_id}'",
                },
            }
        return {"ok": True, **fixture_sample}

    capture = capture_session.get("capture")
    source_label = str(capture_session.get("source_label", "device path"))
    if capture is None:
        return {
            "ok": False,
            "error_info": {
                "code": "camera_open_failed",
                "message": f"Continuous capture session for '{camera_id}' is not open",
            },
        }

    frame = capture_session.pop("initial_frame_bgr", None)
    width = int(capture_session.pop("initial_frame_width", 0) or 0)
    height = int(capture_session.pop("initial_frame_height", 0) or 0)
    if frame is None or width <= 0 or height <= 0:
        read_result = _read_capture_frame(camera_id, capture, source_label, 5, 0.02)
        if not bool(read_result.get("ok", False)):
            return read_result
        frame = read_result.get("frame_bgr")
        width = int(read_result.get("width", 0))
        height = int(read_result.get("height", 0))

    note = f"Captured live session frame {sample_index} from '{camera_id}' with dimensions {width}x{height}."
    if source_label != "device path":
        note = f"Captured live session frame {sample_index} from '{camera_id}' with dimensions {width}x{height} via {source_label}."
    notes = list(capture_session.get("notes", [])) + [note]
    return {
        "ok": True,
        "frame_bgr": frame,
        "raw_tracking_frame": _raw_tracking_frame_base("live_camera", camera_id, width, height, _now_ms()),
        "notes": notes,
        "capture_negotiation": capture_session.get("capture_negotiation", {}),
        "camera_options": capture_session.get("camera_options", {}),
    }


def _create_legacy_hand_inference_session(mp: Any, hand_request: Dict[str, Any]) -> Dict[str, Any]:
    if not bool(hand_request.get("enabled", False)):
        return {"enabled": False}
    if not hasattr(mp, "solutions") or not hasattr(mp.solutions, "hands"):
        return {
            "enabled": True,
            "error_info": {
                "code": "mediapipe_package_unsupported",
                "message": "Installed MediaPipe package does not expose mediapipe.solutions.hands for legacy hand inference",
            },
        }
    try:
        hands = mp.solutions.hands.Hands(static_image_mode=False, max_num_hands=2)
    except Exception as exc:
        return {
            "enabled": True,
            "error_info": {
                "code": "mediapipe_inference_failed",
                "message": f"MediaPipe legacy hands session could not be created: {exc}",
            },
        }
    return {
        "enabled": True,
        "backend": "mediapipe_solutions_hands",
        "processor": hands,
    }


def _create_tasks_hand_inference_session(mp: Any, runtime: Dict[str, Any], hand_request: Dict[str, Any]) -> Dict[str, Any]:
    if not bool(hand_request.get("enabled", False)):
        return {"enabled": False}
    model_path = _resolve_hand_landmarker_model_path(runtime)
    if model_path == "":
        return {
            "enabled": True,
            "error_info": {
                "code": "mediapipe_model_missing",
                "message": "MediaPipe tasks hand inference requires a hand landmarker .task model asset, but none was found. Checked runtime.hand_landmarker_model_path, AEROBEAT_MEDIAPIPE_HAND_LANDMARKER_MODEL_PATH, MEDIAPIPE_HAND_LANDMARKER_MODEL_PATH, and repo default hand_landmarker.task locations.",
            },
        }
    try:
        from mediapipe.tasks.python import vision  # type: ignore
        from mediapipe.tasks.python.core.base_options import BaseOptions  # type: ignore
        options = vision.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=model_path),
            running_mode=vision.RunningMode.IMAGE,
            num_hands=2,
        )
        hand_landmarker = vision.HandLandmarker.create_from_options(options)
    except Exception as exc:
        return {
            "enabled": True,
            "error_info": {
                "code": "mediapipe_package_unsupported",
                "message": f"Installed MediaPipe package exposes mediapipe.tasks but could not create a reusable HandLandmarker on this host: {exc}",
            },
        }
    return {
        "enabled": True,
        "backend": "mediapipe_tasks_hand_landmarker",
        "processor": hand_landmarker,
        "model_asset_path": model_path,
    }


def _create_inference_session(runtime: Dict[str, Any], tracking: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    tracking = tracking or {}
    hand_request = _hand_tracking_request(tracking, runtime)
    try:
        import cv2  # type: ignore
    except Exception as exc:
        return {
            "ok": False,
            "error_info": {
                "code": "opencv_unavailable",
                "message": f"OpenCV import failed while preparing continuous MediaPipe inference: {exc}",
            },
        }

    try:
        import mediapipe as mp  # type: ignore
    except Exception as exc:
        return {
            "ok": False,
            "error_info": {
                "code": "mediapipe_unavailable",
                "message": f"MediaPipe import failed while preparing continuous pose inference: {exc}",
            },
        }

    has_legacy_pose = hasattr(mp, "solutions") and hasattr(mp.solutions, "pose")
    has_tasks_api = hasattr(mp, "tasks") and hasattr(mp, "Image") and hasattr(mp, "ImageFormat")

    if has_legacy_pose:
        try:
            pose = mp.solutions.pose.Pose(static_image_mode=False)
        except Exception as exc:
            return {
                "ok": False,
                "error_info": {
                    "code": "mediapipe_inference_failed",
                    "message": f"MediaPipe legacy pose session could not be created: {exc}",
                },
            }
        hand_session = _create_legacy_hand_inference_session(mp, hand_request)
        session = {
            "ok": True,
            "backend": "mediapipe_solutions_pose",
            "cv2": cv2,
            "processor": pose,
            "pose_processor": pose,
            "hand_request": hand_request,
        }
        if hand_session.get("backend"):
            session["hand_backend"] = hand_session.get("backend")
            session["hand_processor"] = hand_session.get("processor")
        if hand_session.get("model_asset_path"):
            session["hand_model_asset_path"] = hand_session.get("model_asset_path")
        if hand_session.get("error_info"):
            session["hand_error_info"] = hand_session.get("error_info")
        return session

    if has_tasks_api:
        model_path = _resolve_pose_landmarker_model_path(runtime)
        if model_path == "":
            return {
                "ok": False,
                "error_info": {
                    "code": "mediapipe_model_missing",
                    "message": "MediaPipe tasks pose inference requires a pose landmarker .task model asset, but none was found. Checked runtime.pose_landmarker_model_path, runtime.model_asset_path, runtime.model_complexity-selected default repo model locations, AEROBEAT_MEDIAPIPE_POSE_LANDMARKER_MODEL_PATH, and MEDIAPIPE_POSE_LANDMARKER_MODEL_PATH.",
                },
            }
        try:
            from mediapipe.tasks.python import vision  # type: ignore
            from mediapipe.tasks.python.core.base_options import BaseOptions  # type: ignore
            options = vision.PoseLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=model_path),
                running_mode=vision.RunningMode.IMAGE,
                num_poses=1,
            )
            landmarker = vision.PoseLandmarker.create_from_options(options)
        except Exception as exc:
            return {
                "ok": False,
                "error_info": {
                    "code": "mediapipe_package_unsupported",
                    "message": f"Installed MediaPipe package exposes mediapipe.tasks but could not create a reusable PoseLandmarker on this host: {exc}",
                },
            }
        hand_session = _create_tasks_hand_inference_session(mp, runtime, hand_request)
        session = {
            "ok": True,
            "backend": "mediapipe_tasks_pose_landmarker",
            "cv2": cv2,
            "mp": mp,
            "processor": landmarker,
            "pose_processor": landmarker,
            "model_asset_path": model_path,
            "hand_request": hand_request,
        }
        if hand_session.get("backend"):
            session["hand_backend"] = hand_session.get("backend")
            session["hand_processor"] = hand_session.get("processor")
        if hand_session.get("model_asset_path"):
            session["hand_model_asset_path"] = hand_session.get("model_asset_path")
        if hand_session.get("error_info"):
            session["hand_error_info"] = hand_session.get("error_info")
        return session

    return {
        "ok": False,
        "error_info": {
            "code": "mediapipe_package_unsupported",
            "message": "Installed MediaPipe package exposes neither mediapipe.solutions.pose nor a usable mediapipe.tasks vision PoseLandmarker path",
        },
    }


def _close_inference_session(inference_session: Dict[str, Any]) -> None:
    processors: List[Any] = []
    for key in ("processor", "pose_processor", "hand_processor"):
        processor = inference_session.get(key)
        if processor is not None and processor not in processors:
            processors.append(processor)
    for processor in processors:
        close = getattr(processor, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass


def _infer_pose_landmarks_from_session(frame_bgr: Any, inference_session: Dict[str, Any]) -> Dict[str, Any]:
    cv2 = inference_session.get("cv2")
    if cv2 is None:
        return {
            "ok": False,
            "error_info": {
                "code": "opencv_unavailable",
                "message": "Continuous inference session is missing OpenCV bindings",
            },
        }

    try:
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    except Exception as exc:
        return {
            "ok": False,
            "error_info": {
                "code": "mediapipe_inference_failed",
                "message": f"OpenCV could not convert the sampled frame for MediaPipe inference: {exc}",
            },
        }

    backend = str(inference_session.get("backend", ""))
    processor = inference_session.get("pose_processor", inference_session.get("processor"))
    if backend == "mediapipe_solutions_pose":
        try:
            results = processor.process(frame_rgb)
        except Exception as exc:
            return {
                "ok": False,
                "error_info": {
                    "code": "mediapipe_inference_failed",
                    "message": f"MediaPipe legacy pose inference failed for the sampled frame: {exc}",
                },
            }
        return {
            "ok": True,
            "landmarks": _landmarks_from_legacy_results(results),
            "inference_backend": backend,
        }

    if backend == "mediapipe_tasks_pose_landmarker":
        mp = inference_session.get("mp")
        if mp is None:
            return {
                "ok": False,
                "error_info": {
                    "code": "mediapipe_package_unsupported",
                    "message": "Continuous inference session is missing MediaPipe tasks bindings",
                },
            }
        try:
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)
            result = processor.detect(mp_image)
        except Exception as exc:
            return {
                "ok": False,
                "error_info": {
                    "code": "mediapipe_inference_failed",
                    "message": f"MediaPipe tasks pose inference failed for the sampled frame: {exc}",
                },
            }
        return {
            "ok": True,
            "landmarks": _landmarks_from_tasks_result(result),
            "inference_backend": backend,
            "model_asset_path": inference_session.get("model_asset_path", ""),
        }

    return {
        "ok": False,
        "error_info": {
            "code": "mediapipe_package_unsupported",
            "message": f"Continuous inference session backend '{backend}' is unsupported",
        },
    }


def _hands_from_legacy_results(results: Any) -> List[Dict[str, Any]]:
    multi_hand_landmarks = getattr(results, "multi_hand_landmarks", None)
    if not isinstance(multi_hand_landmarks, list):
        return []
    hands: List[Dict[str, Any]] = []
    for index, hand_landmarks in enumerate(multi_hand_landmarks):
        hands.append({
            "index": index,
            **_handedness_from_legacy_results(results, index),
            "landmarks": _hand_landmarks_from_source(getattr(hand_landmarks, "landmark", None)),
        })
    return hands


def _hands_from_tasks_result(result: Any) -> List[Dict[str, Any]]:
    hand_landmarks = getattr(result, "hand_landmarks", None)
    if not isinstance(hand_landmarks, list):
        return []
    hands: List[Dict[str, Any]] = []
    for index, landmarks in enumerate(hand_landmarks):
        hands.append({
            "index": index,
            **_handedness_from_tasks_result(result, index),
            "landmarks": _hand_landmarks_from_source(landmarks),
        })
    return hands


def _infer_hands_from_session(frame_rgb: Any, inference_session: Dict[str, Any]) -> Dict[str, Any]:
    hand_request = inference_session.get("hand_request", {}) if isinstance(inference_session.get("hand_request", {}), dict) else {}
    if not bool(hand_request.get("enabled", False)):
        return {
            "ok": True,
            "hands": [],
            "inference_backend": "disabled",
            "available": False,
            "constraints": _hand_tracking_constraints(hand_request, "disabled", hand_available=False),
        }
    if isinstance(inference_session.get("hand_error_info"), dict):
        return {
            "ok": True,
            "hands": [],
            "inference_backend": str(inference_session.get("hand_backend", "unavailable")),
            "available": False,
            "error_info": inference_session.get("hand_error_info"),
            "constraints": _hand_tracking_constraints(hand_request, str(inference_session.get("hand_backend", "unavailable")), hand_available=False),
        }

    backend = str(inference_session.get("hand_backend", ""))
    processor = inference_session.get("hand_processor")
    if processor is None or backend == "":
        return {
            "ok": True,
            "hands": [],
            "inference_backend": "unavailable",
            "available": False,
            "constraints": _hand_tracking_constraints(hand_request, "unavailable", hand_available=False),
        }

    if backend == "mediapipe_solutions_hands":
        try:
            results = processor.process(frame_rgb)
        except Exception as exc:
            return {
                "ok": False,
                "error_info": {
                    "code": "mediapipe_inference_failed",
                    "message": f"MediaPipe legacy hands inference failed for the sampled frame: {exc}",
                },
            }
        return {
            "ok": True,
            "hands": _hands_from_legacy_results(results),
            "inference_backend": backend,
            "available": True,
            "constraints": _hand_tracking_constraints(hand_request, backend),
        }

    if backend == "mediapipe_tasks_hand_landmarker":
        mp = inference_session.get("mp")
        if mp is None:
            return {
                "ok": False,
                "error_info": {
                    "code": "mediapipe_package_unsupported",
                    "message": "Continuous inference session is missing MediaPipe tasks bindings for hand inference",
                },
            }
        try:
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)
            result = processor.detect(mp_image)
        except Exception as exc:
            return {
                "ok": False,
                "error_info": {
                    "code": "mediapipe_inference_failed",
                    "message": f"MediaPipe tasks hand inference failed for the sampled frame: {exc}",
                },
            }
        return {
            "ok": True,
            "hands": _hands_from_tasks_result(result),
            "inference_backend": backend,
            "available": True,
            "constraints": _hand_tracking_constraints(hand_request, backend),
            "model_asset_path": inference_session.get("hand_model_asset_path", ""),
        }

    return {
        "ok": False,
        "error_info": {
            "code": "mediapipe_package_unsupported",
            "message": f"Continuous hand inference session backend '{backend}' is unsupported",
        },
    }



def _infer_pose_landmarks_legacy(mp: Any, frame_rgb: Any) -> Dict[str, Any]:
    if not hasattr(mp, "solutions") or not hasattr(mp.solutions, "pose"):
        return {
            "ok": False,
            "error_info": {
                "code": "mediapipe_package_unsupported",
                "message": "Installed MediaPipe package does not expose mediapipe.solutions.pose for legacy pose inference",
            },
        }

    with mp.solutions.pose.Pose(static_image_mode=True) as pose:
        results = pose.process(frame_rgb)

    return {
        "ok": True,
        "landmarks": _landmarks_from_legacy_results(results),
        "inference_backend": "mediapipe_solutions_pose",
    }


def _infer_pose_landmarks_tasks(mp: Any, runtime: Dict[str, Any], frame_rgb: Any) -> Dict[str, Any]:
    model_path = _resolve_pose_landmarker_model_path(runtime)
    if model_path == "":
        return {
            "ok": False,
            "error_info": {
                "code": "mediapipe_model_missing",
                "message": "MediaPipe tasks pose inference requires a pose landmarker .task model asset, but none was found. Checked runtime.pose_landmarker_model_path, runtime.model_asset_path, runtime.model_complexity-selected default repo model locations, AEROBEAT_MEDIAPIPE_POSE_LANDMARKER_MODEL_PATH, and MEDIAPIPE_POSE_LANDMARKER_MODEL_PATH.",
            },
        }

    try:
        from mediapipe.tasks.python import vision  # type: ignore
        from mediapipe.tasks.python.core.base_options import BaseOptions  # type: ignore
    except Exception as exc:
        return {
            "ok": False,
            "error_info": {
                "code": "mediapipe_package_unsupported",
                "message": f"Installed MediaPipe package exposes mediapipe.tasks but does not provide PoseLandmarker imports usable on this host: {exc}",
            },
        }

    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)
    options = vision.PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=model_path),
        running_mode=vision.RunningMode.IMAGE,
        num_poses=1,
    )

    with vision.PoseLandmarker.create_from_options(options) as landmarker:
        result = landmarker.detect(mp_image)

    return {
        "ok": True,
        "landmarks": _landmarks_from_tasks_result(result),
        "inference_backend": "mediapipe_tasks_pose_landmarker",
        "model_asset_path": model_path,
    }


def _infer_hands_legacy(mp: Any, frame_rgb: Any, hand_request: Dict[str, Any]) -> Dict[str, Any]:
    if not bool(hand_request.get("enabled", False)):
        return {
            "ok": True,
            "hands": [],
            "inference_backend": "disabled",
            "available": False,
            "constraints": _hand_tracking_constraints(hand_request, "disabled", hand_available=False),
        }
    if not hasattr(mp, "solutions") or not hasattr(mp.solutions, "hands"):
        return {
            "ok": True,
            "hands": [],
            "inference_backend": "unavailable",
            "available": False,
            "error_info": {
                "code": "mediapipe_package_unsupported",
                "message": "Installed MediaPipe package does not expose mediapipe.solutions.hands for legacy hand inference",
            },
            "constraints": _hand_tracking_constraints(hand_request, "unavailable", hand_available=False),
        }

    with mp.solutions.hands.Hands(static_image_mode=True, max_num_hands=2) as hands:
        results = hands.process(frame_rgb)

    return {
        "ok": True,
        "hands": _hands_from_legacy_results(results),
        "inference_backend": "mediapipe_solutions_hands",
        "available": True,
        "constraints": _hand_tracking_constraints(hand_request, "mediapipe_solutions_hands"),
    }


def _infer_hands_tasks(mp: Any, runtime: Dict[str, Any], frame_rgb: Any, hand_request: Dict[str, Any]) -> Dict[str, Any]:
    if not bool(hand_request.get("enabled", False)):
        return {
            "ok": True,
            "hands": [],
            "inference_backend": "disabled",
            "available": False,
            "constraints": _hand_tracking_constraints(hand_request, "disabled", hand_available=False),
        }

    model_path = _resolve_hand_landmarker_model_path(runtime)
    if model_path == "":
        return {
            "ok": True,
            "hands": [],
            "inference_backend": "unavailable",
            "available": False,
            "error_info": {
                "code": "mediapipe_model_missing",
                "message": "MediaPipe tasks hand inference requires a hand landmarker .task model asset, but none was found. Checked runtime.hand_landmarker_model_path, AEROBEAT_MEDIAPIPE_HAND_LANDMARKER_MODEL_PATH, MEDIAPIPE_HAND_LANDMARKER_MODEL_PATH, and repo default hand_landmarker.task locations.",
            },
            "constraints": _hand_tracking_constraints(hand_request, "unavailable", hand_available=False),
        }

    try:
        from mediapipe.tasks.python import vision  # type: ignore
        from mediapipe.tasks.python.core.base_options import BaseOptions  # type: ignore
    except Exception as exc:
        return {
            "ok": True,
            "hands": [],
            "inference_backend": "unavailable",
            "available": False,
            "error_info": {
                "code": "mediapipe_package_unsupported",
                "message": f"Installed MediaPipe package exposes mediapipe.tasks but does not provide HandLandmarker imports usable on this host: {exc}",
            },
            "constraints": _hand_tracking_constraints(hand_request, "unavailable", hand_available=False),
        }

    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)
    options = vision.HandLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=model_path),
        running_mode=vision.RunningMode.IMAGE,
        num_hands=2,
    )

    with vision.HandLandmarker.create_from_options(options) as hand_landmarker:
        result = hand_landmarker.detect(mp_image)

    return {
        "ok": True,
        "hands": _hands_from_tasks_result(result),
        "inference_backend": "mediapipe_tasks_hand_landmarker",
        "available": True,
        "constraints": _hand_tracking_constraints(hand_request, "mediapipe_tasks_hand_landmarker"),
        "model_asset_path": model_path,
    }


def _infer_pose_landmarks_with_mediapipe(runtime: Dict[str, Any], frame_bgr: Any) -> Dict[str, Any]:
    try:
        import cv2  # type: ignore
    except Exception as exc:
        return {
            "ok": False,
            "error_info": {
                "code": "opencv_unavailable",
                "message": f"OpenCV import failed while converting the sampled frame for inference: {exc}",
            },
        }

    try:
        import mediapipe as mp  # type: ignore
    except Exception as exc:
        return {
            "ok": False,
            "error_info": {
                "code": "mediapipe_unavailable",
                "message": f"MediaPipe import failed while inferring pose landmarks from the sampled frame: {exc}",
            },
        }

    try:
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    except Exception as exc:
        return {
            "ok": False,
            "error_info": {
                "code": "mediapipe_inference_failed",
                "message": f"OpenCV could not convert the sampled frame for MediaPipe inference: {exc}",
            },
        }

    has_legacy_pose = hasattr(mp, "solutions") and hasattr(mp.solutions, "pose")
    has_tasks_api = hasattr(mp, "tasks") and hasattr(mp, "Image") and hasattr(mp, "ImageFormat")

    if has_legacy_pose:
        try:
            return _infer_pose_landmarks_legacy(mp, frame_rgb)
        except Exception as exc:
            return {
                "ok": False,
                "error_info": {
                    "code": "mediapipe_inference_failed",
                    "message": f"MediaPipe legacy pose inference failed for the sampled frame: {exc}",
                },
            }

    if has_tasks_api:
        try:
            return _infer_pose_landmarks_tasks(mp, runtime, frame_rgb)
        except Exception as exc:
            return {
                "ok": False,
                "error_info": {
                    "code": "mediapipe_inference_failed",
                    "message": f"MediaPipe tasks pose inference failed for the sampled frame: {exc}",
                },
            }

    return {
        "ok": False,
        "error_info": {
            "code": "mediapipe_package_unsupported",
            "message": "Installed MediaPipe package exposes neither mediapipe.solutions.pose nor a usable mediapipe.tasks vision PoseLandmarker path",
        },
    }


def _infer_hands_with_mediapipe(runtime: Dict[str, Any], tracking: Dict[str, Any], frame_bgr: Any) -> Dict[str, Any]:
    hand_request = _hand_tracking_request(tracking, runtime)
    try:
        import cv2  # type: ignore
    except Exception as exc:
        return {
            "ok": False,
            "error_info": {
                "code": "opencv_unavailable",
                "message": f"OpenCV import failed while converting the sampled frame for hand inference: {exc}",
            },
        }

    try:
        import mediapipe as mp  # type: ignore
    except Exception as exc:
        return {
            "ok": False,
            "error_info": {
                "code": "mediapipe_unavailable",
                "message": f"MediaPipe import failed while inferring hands from the sampled frame: {exc}",
            },
        }

    try:
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    except Exception as exc:
        return {
            "ok": False,
            "error_info": {
                "code": "mediapipe_inference_failed",
                "message": f"OpenCV could not convert the sampled frame for MediaPipe hand inference: {exc}",
            },
        }

    has_legacy_pose = hasattr(mp, "solutions") and hasattr(mp.solutions, "pose")
    has_tasks_api = hasattr(mp, "tasks") and hasattr(mp, "Image") and hasattr(mp, "ImageFormat")
    if has_legacy_pose:
        try:
            return _infer_hands_legacy(mp, frame_rgb, hand_request)
        except Exception as exc:
            return {
                "ok": False,
                "error_info": {
                    "code": "mediapipe_inference_failed",
                    "message": f"MediaPipe legacy hand inference failed for the sampled frame: {exc}",
                },
            }

    if has_tasks_api:
        try:
            return _infer_hands_tasks(mp, runtime, frame_rgb, hand_request)
        except Exception as exc:
            return {
                "ok": False,
                "error_info": {
                    "code": "mediapipe_inference_failed",
                    "message": f"MediaPipe tasks hand inference failed for the sampled frame: {exc}",
                },
            }

    return {
        "ok": True,
        "hands": [],
        "inference_backend": "unavailable",
        "available": False,
        "error_info": {
            "code": "mediapipe_package_unsupported",
            "message": "Installed MediaPipe package exposes neither mediapipe.solutions.hands nor a usable mediapipe.tasks vision HandLandmarker path",
        },
        "constraints": _hand_tracking_constraints(hand_request, "unavailable", hand_available=False),
    }


def _apply_hand_tracking(raw_tracking_frame: Dict[str, Any], tracking: Dict[str, Any], runtime: Dict[str, Any], hands_result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    frame = raw_tracking_frame.copy()
    hand_request = _hand_tracking_request(tracking, runtime)
    if hands_result is None and frame.get("hands") is None:
        frame["vendor_hand_tracking"] = {
            **hand_request,
            "available": False,
            "count": 0,
            "constraints": _hand_tracking_constraints(hand_request, "unavailable", hand_available=False),
        }
        return frame

    if hands_result is None:
        hands_result = {
            "ok": True,
            "hands": frame.get("hands", []),
            "inference_backend": "fixture",
            "available": bool(frame.get("hands")),
            "constraints": _hand_tracking_constraints(hand_request, "fixture", hand_available=bool(frame.get("hands"))),
        }

    if not bool(hand_request.get("enabled", False)):
        frame.pop("hands", None)
        frame["vendor_hand_tracking"] = {
            **hand_request,
            "available": False,
            "count": 0,
            "inference_backend": str(hands_result.get("inference_backend", "disabled")),
            "constraints": _hand_tracking_constraints(hand_request, str(hands_result.get("inference_backend", "disabled")), hand_available=False),
        }
        return frame

    hands = hands_result.get("hands", []) if isinstance(hands_result.get("hands", []), list) else []
    processed_hands = [_normalize_hand_detection(hand, str(hand_request.get("landmark_mode", _HAND_LANDMARK_MODE_DEFAULT)), bool(hand_request.get("bbox_enabled", True))) for hand in hands if isinstance(hand, dict)]
    if processed_hands:
        frame["hands"] = processed_hands
    else:
        frame.pop("hands", None)
    frame["vendor_hand_tracking"] = {
        **hand_request,
        "available": bool(hands_result.get("available", bool(processed_hands))),
        "count": len(processed_hands),
        "inference_backend": str(hands_result.get("inference_backend", "unavailable")),
        "constraints": hands_result.get("constraints", _hand_tracking_constraints(hand_request, str(hands_result.get("inference_backend", "unavailable")), hand_available=bool(hands_result.get("available", bool(processed_hands))))),
    }
    if isinstance(hands_result.get("error_info"), dict):
        frame["vendor_hand_tracking"]["error_info"] = hands_result.get("error_info")
    if hands_result.get("model_asset_path"):
        frame["vendor_hand_tracking"]["model_asset_path"] = hands_result.get("model_asset_path")
    return frame


def _infer_pose_landmarks(sampled: Dict[str, Any], runtime: Dict[str, Any], tracking: Optional[Dict[str, Any]] = None, inference_session: Optional[Dict[str, Any]] = None, tracking_semantics: Optional[Dict[str, Any]] = None, filter_state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    tracking = tracking or {}
    raw_tracking_frame = sampled.get("raw_tracking_frame", {}).copy()
    notes = list(sampled.get("notes", []))
    semantics = tracking_semantics or {"quality": "optimized", "overlay_mode": "optimized", "point_mode": "reduced", "filter_enabled": True}

    fixture_error = sampled.get("fixture_inference_error")
    if isinstance(fixture_error, dict):
        return {
            "ok": False,
            "error_info": fixture_error,
            "raw_tracking_frame": raw_tracking_frame,
            "notes": notes + [fixture_error.get("message", "Fixture inference failed")],
        }

    if bool(sampled.get("fixture_used", False)):
        landmarks = raw_tracking_frame.get("landmarks")
        if isinstance(landmarks, list) and len(landmarks) > 0:
            raw_tracking_frame["tracking_state"] = "tracked"
            raw_tracking_frame = _apply_tracking_semantics(raw_tracking_frame, semantics, filter_state)
            semantics_meta = raw_tracking_frame.get("vendor_tracking_semantics", {})
            notes.append(
                f"Applied vendor tracking semantics to fixture landmarks: quality={semantics_meta.get('quality', 'optimized')}, filter_enabled={semantics_meta.get('filter_enabled', True)}, kept {semantics_meta.get('landmark_count_after', 0)} of {semantics_meta.get('landmark_count_before', 0)} landmark(s)."
            )
        else:
            raw_tracking_frame.pop("landmarks", None)
            raw_tracking_frame["tracking_state"] = "idle"
            notes.append("Fixture sample did not supply pose landmarks; tracking remains idle.")
        raw_tracking_frame = _apply_hand_tracking(raw_tracking_frame, tracking, runtime)
        hand_meta = raw_tracking_frame.get("vendor_hand_tracking", {})
        if hand_meta.get("available"):
            notes.append(f"Fixture surfaced {int(hand_meta.get('count', 0))} raw hand sample(s) in {hand_meta.get('landmark_mode', _HAND_LANDMARK_MODE_DEFAULT)} mode.")
        elif isinstance(hand_meta.get("error_info"), dict):
            notes.append(str(hand_meta.get("error_info", {}).get("message", "Hand inference unavailable")))
        return {
            "ok": True,
            "raw_tracking_frame": raw_tracking_frame,
            "notes": notes,
        }

    frame_bgr = sampled.get("frame_bgr")
    if frame_bgr is None:
        return {
            "ok": False,
            "error_info": {
                "code": "sample_frame_missing",
                "message": "MediaPipe landmark inference requires a sampled frame, but no frame pixels were available",
            },
            "raw_tracking_frame": raw_tracking_frame,
            "notes": notes,
        }

    inferred = _infer_pose_landmarks_from_session(frame_bgr, inference_session) if inference_session is not None else _infer_pose_landmarks_with_mediapipe(runtime, frame_bgr)
    if not bool(inferred.get("ok", False)):
        return {
            "ok": False,
            "error_info": inferred.get("error_info", {
                "code": "mediapipe_inference_failed",
                "message": "MediaPipe pose inference failed for the sampled frame",
            }),
            "raw_tracking_frame": raw_tracking_frame,
            "notes": notes,
        }

    landmarks = inferred.get("landmarks", [])
    if isinstance(landmarks, list) and landmarks:
        raw_tracking_frame["tracking_state"] = "tracked"
        raw_tracking_frame["landmarks"] = landmarks
        raw_tracking_frame = _apply_tracking_semantics(raw_tracking_frame, semantics, filter_state)
        semantics_meta = raw_tracking_frame.get("vendor_tracking_semantics", {})
        notes.append(f"MediaPipe pose inference produced {len(landmarks)} landmark(s) from the sampled frame via {inferred.get('inference_backend', 'mediapipe')}.")
        notes.append(
            f"Applied vendor tracking semantics: quality={semantics_meta.get('quality', 'optimized')}, filter_enabled={semantics_meta.get('filter_enabled', True)}, kept {semantics_meta.get('landmark_count_after', 0)} of {semantics_meta.get('landmark_count_before', 0)} landmark(s)."
        )
    else:
        raw_tracking_frame.pop("landmarks", None)
        raw_tracking_frame["tracking_state"] = "idle"
        if filter_state is not None:
            filter_state.clear()
        notes.append(f"MediaPipe pose inference via {inferred.get('inference_backend', 'mediapipe')} found no landmarks in the sampled frame; tracking remains idle.")

    if inferred.get("model_asset_path"):
        notes.append(f"MediaPipe tasks pose landmarker used model asset '{inferred['model_asset_path']}'.")

    try:
        if inference_session is not None:
            cv2 = inference_session.get("cv2")
            frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB) if cv2 is not None else frame_bgr
            hands_result = _infer_hands_from_session(frame_rgb, inference_session)
        else:
            hands_result = _infer_hands_with_mediapipe(runtime, tracking, frame_bgr)
    except Exception as exc:
        hands_result = {
            "ok": False,
            "error_info": {
                "code": "mediapipe_inference_failed",
                "message": f"MediaPipe hand inference failed for the sampled frame: {exc}",
            },
        }
    if not bool(hands_result.get("ok", False)):
        return {
            "ok": False,
            "error_info": hands_result.get("error_info", {
                "code": "mediapipe_inference_failed",
                "message": "MediaPipe hand inference failed for the sampled frame",
            }),
            "raw_tracking_frame": raw_tracking_frame,
            "notes": notes,
        }
    raw_tracking_frame = _apply_hand_tracking(raw_tracking_frame, tracking, runtime, hands_result)
    hand_meta = raw_tracking_frame.get("vendor_hand_tracking", {})
    if hand_meta.get("available"):
        notes.append(f"MediaPipe hand inference produced {int(hand_meta.get('count', 0))} hand sample(s) via {hand_meta.get('inference_backend', 'mediapipe')} in {hand_meta.get('landmark_mode', _HAND_LANDMARK_MODE_DEFAULT)} mode.")
    elif isinstance(hand_meta.get("error_info"), dict):
        notes.append(str(hand_meta.get("error_info", {}).get("message", "Hand inference unavailable")))
    elif bool(hand_meta.get("enabled", False)):
        notes.append(f"MediaPipe hand inference via {hand_meta.get('inference_backend', 'mediapipe')} found no hands in the sampled frame.")
    if hand_meta.get("model_asset_path"):
        notes.append(f"MediaPipe hand landmarker used model asset '{hand_meta['model_asset_path']}'.")

    return {
        "ok": True,
        "raw_tracking_frame": raw_tracking_frame,
        "notes": notes,
    }



def _preview_descriptor(preview: Dict[str, Any], runtime: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    preview_config = _preview_runtime_config(preview, runtime or {})
    return {
        "enabled": preview_config["enabled"],
        "surface_mode": preview_config["surface_mode"],
        "attached": False,
        "flip_horizontal": preview_config["flip_horizontal"],
        "maintain_aspect_ratio": True,
        "max_fps": preview_config["max_fps"],
        "width": preview_config["width"],
        "height": preview_config["height"],
        "quality": preview_config["quality"],
        "backend": "mediapipe_python",
    }


def _select_source(request: Dict[str, Any]) -> Dict[str, Any]:
    operation = str(request.get("operation", "startup"))
    runtime = request.get("runtime", {}) if isinstance(request.get("runtime", {}), dict) else {}
    source = request.get("source", {}) if isinstance(request.get("source", {}), dict) else {}
    cameras = _enumerate_cameras(runtime)
    health = _base_health(operation, runtime)

    source_kind = str(source.get("kind", "live_camera"))
    if source_kind == "video_file":
        video_path = str(source.get("path", "")).strip()
        if video_path == "":
            error_info = {
                "code": "video_file_path_missing",
                "message": "Replay video_file sessions require source.path",
            }
            return {"ok": False, "cameras": cameras, "health": {**health, "status": "error", "healthy": False, "last_error": error_info}, "error_info": error_info}
        if not os.path.isfile(video_path):
            error_info = {
                "code": "video_file_missing",
                "message": f"Replay video source not found at '{video_path}'",
            }
            return {"ok": False, "cameras": cameras, "health": {**health, "status": "error", "healthy": False, "last_error": error_info}, "error_info": error_info}
        health.update({
            "camera_accessible": True,
            "healthy": True,
            "selected_camera_id": video_path,
            "selected_camera_label": os.path.basename(video_path) or video_path,
            "notes": health["notes"] + [f"Selected replay source '{video_path}' for truthful frame capture."],
        })
        return {"ok": True, "runtime": runtime, "source": source, "selected": {"path": video_path, "available": True}, "selected_camera_id": video_path, "cameras": cameras, "health": health}

    if source_kind != "live_camera":
        error_info = {
            "code": "unsupported_source_kind",
            "message": f"MediaPipe Python probe only supports live_camera or video_file in this slice, got '{source_kind}'",
        }
        return {"ok": False, "cameras": cameras, "health": {**health, "status": "error", "healthy": False, "last_error": error_info}, "error_info": error_info}

    selected_camera_id = str(source.get("camera_id", "")).strip()
    if not cameras:
        error_info = {
            "code": "no_live_cameras_found",
            "message": "No live camera candidates were found during MediaPipe Python probe",
        }
        return {
            "ok": False,
            "cameras": [],
            "health": {
                **health,
                "status": "error",
                "healthy": False,
                "last_error": error_info,
                "notes": health["notes"] + ["Camera glob returned no candidates."],
            },
            "error_info": error_info,
        }

    if selected_camera_id:
        selected = next((camera for camera in cameras if camera["camera_id"] == selected_camera_id), None)
        if selected is None:
            error_info = {
                "code": "camera_not_found",
                "message": f"Requested camera '{selected_camera_id}' was not found during MediaPipe Python probe",
            }
            return {"ok": False, "cameras": cameras, "health": {**health, "status": "error", "healthy": False, "last_error": error_info}, "error_info": error_info}
    else:
        selected = cameras[0]
        selected_camera_id = selected["camera_id"]

    health.update({
        "camera_accessible": bool(selected.get("available", False)),
        "healthy": bool(selected.get("available", False)),
        "selected_camera_id": selected_camera_id,
        "selected_camera_label": selected.get("label", selected_camera_id),
        "notes": health["notes"] + [f"Selected camera candidate '{selected_camera_id}' for truthful sample capture."],
    })
    return {"ok": True, "runtime": runtime, "source": source, "selected": selected, "selected_camera_id": selected_camera_id, "cameras": cameras, "health": health}


def _describe_live_camera_options(request: Dict[str, Any]) -> Dict[str, Any]:
    selection = _select_source(request)
    if not bool(selection.get("ok", False)):
        return selection

    runtime: Dict[str, Any] = selection["runtime"]
    selected_camera_id = str(selection["selected_camera_id"])
    capture_session = _select_live_camera_capture_session(selected_camera_id, runtime, "describe camera options")
    if not bool(capture_session.get("ok", False)):
        error_info = capture_session.get("error_info", {
            "code": "camera_open_failed",
            "message": f"Failed to probe camera options for selected camera '{selected_camera_id}'",
        })
        health = selection["health"].copy()
        health.update({
            "status": "error",
            "healthy": False,
            "camera_accessible": False,
            "last_error": error_info,
            "notes": list(health.get("notes", [])) + [error_info.get("message", "Camera options probe failed")],
        })
        return {
            "ok": False,
            "cameras": selection.get("cameras", []),
            "selected_camera_id": selected_camera_id,
            "health": health,
            "preview_descriptor": {},
            "raw_tracking_frame": {},
            "error_info": error_info,
        }

    try:
        camera_options = capture_session.get("camera_options", {}).copy() if isinstance(capture_session.get("camera_options", {}), dict) else {}
        capture_negotiation = capture_session.get("capture_negotiation", {}).copy() if isinstance(capture_session.get("capture_negotiation", {}), dict) else {}
        health = selection["health"].copy()
        health["status"] = "idle"
        health["healthy"] = True
        health["camera_accessible"] = True
        health["notes"] = list(health.get("notes", [])) + list(capture_session.get("notes", []))
        health["capture_mode"] = {
            "requested": camera_options.get("requested", {}),
            "reported_source": camera_options.get("reported_source", capture_negotiation.get("reported_source", "fallback_probe_sweep")),
            "selection_policy": camera_options.get("selection_policy", capture_negotiation.get("selection_policy", "framerate_first_resolution_second_format_backend")),
            "reported_options": camera_options.get("reported_options", []),
            "probed_options": camera_options.get("probed_options", []),
            "selected": camera_options.get("selected", capture_negotiation.get("selected", {})),
            "actual": camera_options.get("actual", capture_negotiation.get("actual", {})),
        }
        return {
            "ok": True,
            "cameras": selection.get("cameras", []),
            "selected_camera_id": selected_camera_id,
            "health": health,
            "preview_descriptor": {},
            "raw_tracking_frame": {},
            "camera_options": camera_options,
        }
    finally:
        _close_live_camera_capture_session(capture_session)


def _sample_once(request: Dict[str, Any], sample_index: int = 0, dynamic_timestamp: bool = False) -> Dict[str, Any]:
    selection = _select_source(request)
    if not bool(selection.get("ok", False)):
        return selection

    runtime: Dict[str, Any] = selection["runtime"]
    source: Dict[str, Any] = selection["source"]
    preview = request.get("preview", {}) if isinstance(request.get("preview", {}), dict) else {}
    tracking = request.get("tracking", {}) if isinstance(request.get("tracking", {}), dict) else {}
    tracking_semantics = _tracking_semantics(request)
    selected_camera_id = str(selection["selected_camera_id"])
    cameras = selection["cameras"]
    health = selection["health"]

    source_kind = str(source.get("kind", "live_camera"))
    sampled = _capture_video_file_sample(selected_camera_id, runtime, sample_index=sample_index, dynamic_timestamp=dynamic_timestamp) if source_kind == "video_file" else _capture_live_camera_sample(selected_camera_id, runtime, sample_index=sample_index, dynamic_timestamp=dynamic_timestamp)
    if not bool(sampled.get("ok", False)):
        error_info = sampled.get("error_info", {
            "code": "camera_sample_failed",
            "message": f"Failed to capture a sample frame from selected camera '{selected_camera_id}'",
        })
        return {
            "ok": False,
            "cameras": cameras,
            "selected_camera_id": selected_camera_id,
            "health": {
                **health,
                "status": "error",
                "healthy": False,
                "camera_accessible": False,
                "last_error": error_info,
                "notes": health["notes"] + [error_info.get("message", "Camera sample capture failed")],
            },
            "error_info": error_info,
        }

    inferred = _infer_pose_landmarks(sampled, runtime, tracking=tracking, tracking_semantics=tracking_semantics, filter_state={} if bool(tracking_semantics.get('filter_enabled', True)) else None)
    if not bool(inferred.get("ok", False)):
        error_info = inferred.get("error_info", {
            "code": "mediapipe_inference_failed",
            "message": f"Failed to infer pose landmarks from selected camera '{selected_camera_id}'",
        })
        return {
            "ok": False,
            "cameras": cameras,
            "selected_camera_id": selected_camera_id,
            "health": {
                **health,
                "status": "error",
                "healthy": False,
                "camera_accessible": True,
                "tracking_active": False,
                "last_error": error_info,
                "notes": health["notes"] + inferred.get("notes", []) + [error_info.get("message", "Landmark inference failed")],
            },
            "error_info": error_info,
        }

    raw_tracking_frame = inferred.get("raw_tracking_frame", {}).copy()
    landmarks = raw_tracking_frame.get("landmarks")
    capture_negotiation = sampled.get("capture_negotiation", {}) if isinstance(sampled.get("capture_negotiation", {}), dict) else {}
    health.update({
        "camera_accessible": True,
        "healthy": True,
        "tracking_active": False,
        "notes": health["notes"] + inferred.get("notes", []),
    })
    if capture_negotiation:
        health["capture_mode"] = capture_negotiation
    if isinstance(landmarks, list) and len(landmarks) > 0:
        health["notes"].append(f"Returning {len(landmarks)} raw sampled pose landmark(s).")
    else:
        health["notes"].append("Returning no raw landmarks because the sampled frame did not produce a pose.")

    return {
        "ok": True,
        "cameras": cameras,
        "selected_camera_id": selected_camera_id,
        "health": health,
        "preview_descriptor": _preview_descriptor(preview, runtime),
        "raw_tracking_frame": raw_tracking_frame,
        "camera_options": sampled.get("camera_options", {}).copy() if isinstance(sampled.get("camera_options", {}), dict) else {},
    }


def _write_json_atomic(path: str, payload: Dict[str, Any]) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
    os.replace(temp_path, path)


def _session_preview_frame_path(session_dir: str) -> str:
    return os.path.join(session_dir, _SESSION_PREVIEW_FRAME_FILENAME)


def _resize_preview_frame(cv2: Any, frame_bgr: Any, max_width: int, max_height: int) -> Any:
    shape = getattr(frame_bgr, "shape", None)
    if shape is None or len(shape) < 2:
        return frame_bgr
    source_height = int(shape[0])
    source_width = int(shape[1])
    if source_width <= 0 or source_height <= 0:
        return frame_bgr
    if source_width <= max_width and source_height <= max_height:
        return frame_bgr
    scale = min(float(max_width) / float(source_width), float(max_height) / float(source_height))
    if scale >= 1.0:
        return frame_bgr
    target_width = max(1, int(math.floor(source_width * scale)))
    target_height = max(1, int(math.floor(source_height * scale)))
    return cv2.resize(frame_bgr, (target_width, target_height))


def _write_preview_frame(session_dir: str, frame_bgr: Any, preview: Dict[str, Any], runtime: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if session_dir == "" or frame_bgr is None:
        return {}
    preview_config = _preview_runtime_config(preview, runtime or {})
    if not preview_config["enabled"]:
        return {}
    try:
        import cv2  # type: ignore
    except Exception:
        return {}
    preview_path = _session_preview_frame_path(session_dir)
    prepared_frame = _resize_preview_frame(cv2, frame_bgr, preview_config["width"], preview_config["height"])
    params: List[int] = []
    if hasattr(cv2, "IMWRITE_JPEG_QUALITY"):
        params = [int(cv2.IMWRITE_JPEG_QUALITY), preview_config["quality"]]
    wrote = cv2.imwrite(preview_path, prepared_frame, params) if params else cv2.imwrite(preview_path, prepared_frame)
    if not wrote:
        return {}
    output_shape = getattr(prepared_frame, "shape", None)
    output_height = int(output_shape[0]) if output_shape is not None and len(output_shape) >= 2 else preview_config["height"]
    output_width = int(output_shape[1]) if output_shape is not None and len(output_shape) >= 2 else preview_config["width"]
    return {
        "image_path": preview_path,
        "image_revision": int(time.time() * 1000),
        "image_format": "jpg",
        "image_width": output_width,
        "image_height": output_height,
    }


def _with_preview_frame(session_dir: str, preview: Dict[str, Any], frame_bgr: Any, runtime: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    descriptor = _preview_descriptor(preview, runtime)
    descriptor.update(_write_preview_frame(session_dir, frame_bgr, preview, runtime))
    return descriptor


def _playback_status(
    source_path: str,
    current_time_sec: float,
    duration_sec: float,
    state: str = "playing",
    paused: bool = False,
) -> Dict[str, Any]:
    safe_duration = max(duration_sec, 0.0)
    safe_position = max(current_time_sec, 0.0)
    progress = 0.0
    if safe_duration > 0.0:
        progress = min(max(safe_position / safe_duration, 0.0), 1.0)
    return {
        "source": source_path,
        "state": state,
        "paused": paused,
        "current_time_sec": safe_position,
        "duration_sec": safe_duration,
        "progress": progress,
        "is_file_source": True,
        "can_seek": True,
        "can_pause": True,
    }


def _session_snapshot_path(session_dir: str) -> str:
    return os.path.join(session_dir, _SESSION_SNAPSHOT_FILENAME)


def _session_stop_path(session_dir: str) -> str:
    return os.path.join(session_dir, _SESSION_STOP_FILENAME)


def _session_request_path(session_dir: str) -> str:
    return os.path.join(session_dir, _SESSION_REQUEST_FILENAME)


def _write_session_snapshot(session_dir: str, payload: Dict[str, Any]) -> None:
    _write_json_atomic(_session_snapshot_path(session_dir), payload)


def _continuous_shutdown_snapshot(request: Dict[str, Any], runtime: Dict[str, Any], selected_camera_id: str, selected: Dict[str, Any], capture_session: Dict[str, Any], last_preview_descriptor: Dict[str, Any], note: str, note_code: str = "shutdown") -> Dict[str, Any]:
    return {
        "ok": True,
        "cameras": _enumerate_cameras(runtime),
        "selected_camera_id": selected_camera_id,
        "health": {
            **_base_health(note_code, runtime),
            "status": "idle",
            "runtime_available": True,
            "bridge_connected": True,
            "process_active": False,
            "camera_accessible": bool(selected.get("available", False)),
            "tracking_active": False,
            "healthy": True,
            "selected_camera_id": selected_camera_id,
            "selected_camera_label": selected.get("label", selected_camera_id),
            "notes": list(capture_session.get("notes", [])) + [note],
            "capture_mode": capture_session.get("capture_negotiation", {}),
        },
        "preview_descriptor": last_preview_descriptor.copy(),
        "raw_tracking_frame": {},
        "camera_options": capture_session.get("camera_options", {}).copy() if isinstance(capture_session.get("camera_options", {}), dict) else {},
    }


def _continuous_success_snapshot(request: Dict[str, Any], sampled: Dict[str, Any], sample_index: int, loop_started_ms: int, session_dir: str = "", include_preview_frame: bool = True, existing_preview_descriptor: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    snapshot = sampled.copy()
    health = snapshot.get("health", {}).copy()
    health.update({
        "status": "running",
        "runtime_available": True,
        "bridge_connected": True,
        "process_active": True,
        "camera_accessible": True,
        "tracking_active": True,
        "healthy": True,
        "loop_iteration": sample_index,
        "loop_started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(loop_started_ms / 1000.0)),
        "probed_at": _now_iso(),
    })
    notes = list(health.get("notes", []))
    notes.append("Continuous runtime loop remains alive and may return idle raw frames when no pose is currently visible.")
    health["notes"] = notes
    snapshot["health"] = health
    preview = request.get("preview", {}) if isinstance(request.get("preview", {}), dict) else {}
    runtime = request.get("runtime", {}) if isinstance(request.get("runtime", {}), dict) else {}
    if include_preview_frame:
        snapshot["preview_descriptor"] = _with_preview_frame(session_dir, preview, sampled.get("frame_bgr"), runtime)
    else:
        snapshot["preview_descriptor"] = (existing_preview_descriptor or _preview_descriptor(preview, runtime)).copy()
    snapshot.pop("frame_bgr", None)
    snapshot["ok"] = True
    return snapshot


def _continuous_error_snapshot(request: Dict[str, Any], failure: Dict[str, Any], sample_index: int, loop_started_ms: int) -> Dict[str, Any]:
    runtime = request.get("runtime", {}) if isinstance(request.get("runtime", {}), dict) else {}
    health = _base_health("startup", runtime)
    existing = failure.get("health", {}) if isinstance(failure.get("health", {}), dict) else {}
    health.update(existing)
    error_info = failure.get("error_info", {"code": "runtime_loop_failed", "message": "Continuous MediaPipe runtime loop failed"})
    health.update({
        "status": "error",
        "runtime_available": True,
        "bridge_connected": True,
        "process_active": False,
        "tracking_active": False,
        "healthy": False,
        "last_error": error_info,
        "loop_iteration": sample_index,
        "loop_started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(loop_started_ms / 1000.0)),
        "probed_at": _now_iso(),
    })
    return {
        "ok": False,
        "cameras": failure.get("cameras", []),
        "selected_camera_id": failure.get("selected_camera_id", ""),
        "health": health,
        "preview_descriptor": _preview_descriptor(request.get("preview", {}), runtime),
        "raw_tracking_frame": failure.get("raw_tracking_frame", {}),
        "error_info": error_info,
    }


def _run_continuous_session(request: Dict[str, Any], session_dir: str) -> int:
    source = request.get("source", {}) if isinstance(request.get("source", {}), dict) else {}
    if str(source.get("kind", "live_camera")) == "video_file":
        return _run_video_file_session(request, session_dir)

    os.makedirs(session_dir, exist_ok=True)
    _write_json_atomic(_session_request_path(session_dir), request)
    runtime = request.get("runtime", {}) if isinstance(request.get("runtime", {}), dict) else {}
    preview = request.get("preview", {}) if isinstance(request.get("preview", {}), dict) else {}
    preview_config = _preview_runtime_config(preview, runtime)
    tracking = request.get("tracking", {}) if isinstance(request.get("tracking", {}), dict) else {}
    tracking_semantics = _tracking_semantics(request)
    tracking_filter_state: Optional[Dict[str, Any]] = {} if bool(tracking_semantics.get('filter_enabled', True)) else None
    tracking_interval = _fps_interval_seconds(runtime.get("tracking_max_fps", _DEFAULT_TRACKING_MAX_FPS), _DEFAULT_TRACKING_MAX_FPS)
    state_interval = _fps_interval_seconds(runtime.get("state_update_max_fps", _DEFAULT_STATE_UPDATE_MAX_FPS), _DEFAULT_STATE_UPDATE_MAX_FPS)
    preview_interval = _fps_interval_seconds(preview_config.get("max_fps", _DEFAULT_PREVIEW_MAX_FPS), _DEFAULT_PREVIEW_MAX_FPS)
    loop_started_ms = _now_ms()
    sample_index = 0
    last_state_write_at: Optional[float] = None
    last_preview_write_at: Optional[float] = None
    last_preview_descriptor = _preview_descriptor(preview, runtime)
    _arm_owner_orphan_protection()

    selection = _select_source(request)
    if not bool(selection.get("ok", False)):
        snapshot = _continuous_error_snapshot(request, selection, sample_index, loop_started_ms)
        _write_session_snapshot(session_dir, snapshot)
        return 1

    selected_camera_id = str(selection.get("selected_camera_id", ""))
    selected = selection.get("selected", {}) if isinstance(selection.get("selected", {}), dict) else {}
    capture_session = _open_live_camera_capture_session(selected_camera_id, runtime)
    if not bool(capture_session.get("ok", False)):
        snapshot = _continuous_error_snapshot(request, {
            "error_info": capture_session.get("error_info", {
                "code": "camera_open_failed",
                "message": f"Failed to open selected camera '{selected_camera_id}' for continuous capture",
            }),
            "cameras": selection.get("cameras", []),
            "selected_camera_id": selected_camera_id,
            "health": {"camera_accessible": False},
        }, sample_index, loop_started_ms)
        _write_session_snapshot(session_dir, snapshot)
        return 1

    inference_session: Optional[Dict[str, Any]] = None
    if not bool(capture_session.get("fixture_only", False)):
        inference_session = _create_inference_session(runtime, tracking)
        if not bool(inference_session.get("ok", False)):
            _close_live_camera_capture_session(capture_session)
            snapshot = _continuous_error_snapshot(request, {
                "error_info": inference_session.get("error_info", {
                    "code": "mediapipe_inference_failed",
                    "message": f"Failed to initialize continuous pose inference for camera '{selected_camera_id}'",
                }),
                "cameras": selection.get("cameras", []),
                "selected_camera_id": selected_camera_id,
                "health": {"camera_accessible": True},
            }, sample_index, loop_started_ms)
            _write_session_snapshot(session_dir, snapshot)
            return 1

    try:
        while True:
            iteration_started_at = time.monotonic()
            if os.path.exists(_session_stop_path(session_dir)):
                shutdown_snapshot = _continuous_shutdown_snapshot(
                    request,
                    runtime,
                    selected_camera_id,
                    selected,
                    capture_session,
                    last_preview_descriptor,
                    "Continuous MediaPipe runtime session stopped cleanly.",
                )
                _write_session_snapshot(session_dir, shutdown_snapshot)
                return 0
            if _runtime_shutdown_reason() != "":
                shutdown_note = "Continuous MediaPipe runtime session exited because its owner process disappeared unexpectedly."
                if _runtime_shutdown_reason() != "owner_process_disappeared":
                    shutdown_note = f"Continuous MediaPipe runtime session exited after receiving {_runtime_shutdown_reason()}."
                shutdown_snapshot = _continuous_shutdown_snapshot(
                    request,
                    runtime,
                    selected_camera_id,
                    selected,
                    capture_session,
                    last_preview_descriptor,
                    shutdown_note,
                    _runtime_shutdown_reason(),
                )
                _write_session_snapshot(session_dir, shutdown_snapshot)
                return 0

            sampled = _capture_live_camera_session_sample(selected_camera_id, runtime, capture_session, sample_index=sample_index, dynamic_timestamp=True)
            if not bool(sampled.get("ok", False)):
                snapshot = _continuous_error_snapshot(request, {
                    **sampled,
                    "cameras": _enumerate_cameras(runtime),
                    "selected_camera_id": selected_camera_id,
                }, sample_index, loop_started_ms)
                _write_session_snapshot(session_dir, snapshot)
                return 1

            inferred = _infer_pose_landmarks(sampled, runtime, tracking=tracking, inference_session=inference_session, tracking_semantics=tracking_semantics, filter_state=tracking_filter_state)
            if not bool(inferred.get("ok", False)):
                snapshot = _continuous_error_snapshot(request, {
                    "error_info": inferred.get("error_info", {
                        "code": "mediapipe_inference_failed",
                        "message": f"Failed to infer pose landmarks from selected camera '{selected_camera_id}'",
                    }),
                    "raw_tracking_frame": inferred.get("raw_tracking_frame", {}),
                    "cameras": _enumerate_cameras(runtime),
                    "selected_camera_id": selected_camera_id,
                    "health": {
                        "camera_accessible": True,
                    },
                }, sample_index, loop_started_ms)
                _write_session_snapshot(session_dir, snapshot)
                return 1

            raw_tracking_frame = inferred.get("raw_tracking_frame", {}).copy()
            landmarks = raw_tracking_frame.get("landmarks")
            health = selection.get("health", {}).copy() if isinstance(selection.get("health", {}), dict) else _base_health("startup", runtime)
            base_notes = list(health.get("notes", []))
            capture_negotiation = capture_session.get("capture_negotiation", {}) if isinstance(capture_session.get("capture_negotiation", {}), dict) else {}
            health.update({
                "camera_accessible": True,
                "healthy": True,
                "tracking_active": True,
                "process_active": True,
                "status": "running",
                "loop_iteration": sample_index,
                "loop_started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(loop_started_ms / 1000.0)),
                "probed_at": _now_iso(),
                "selected_camera_id": selected_camera_id,
                "selected_camera_label": selected.get("label", selected_camera_id),
                "notes": base_notes + inferred.get("notes", []),
            })
            if capture_negotiation:
                health["capture_mode"] = capture_negotiation
            if isinstance(landmarks, list) and len(landmarks) > 0:
                health["notes"].append(f"Returning {len(landmarks)} raw sampled pose landmark(s).")
            else:
                health["notes"].append("Returning no raw landmarks because the sampled frame did not produce a pose.")

            sampled_snapshot = {
                "ok": True,
                "cameras": _enumerate_cameras(runtime),
                "selected_camera_id": selected_camera_id,
                "health": health,
                "preview_descriptor": last_preview_descriptor.copy(),
                "raw_tracking_frame": raw_tracking_frame,
                "frame_bgr": sampled.get("frame_bgr"),
                "camera_options": sampled.get("camera_options", {}).copy() if isinstance(sampled.get("camera_options", {}), dict) else {},
            }

            now = time.monotonic()
            should_write_state = last_state_write_at is None or state_interval <= 0.0 or (now - last_state_write_at) >= state_interval
            include_preview = bool(preview_config.get("enabled", True)) and should_write_state and (last_preview_write_at is None or preview_interval <= 0.0 or (now - last_preview_write_at) >= preview_interval)
            if should_write_state:
                snapshot = _continuous_success_snapshot(request, sampled_snapshot, sample_index, loop_started_ms, session_dir, include_preview_frame=include_preview, existing_preview_descriptor=last_preview_descriptor)
                last_preview_descriptor = snapshot.get("preview_descriptor", last_preview_descriptor).copy()
                _write_session_snapshot(session_dir, snapshot)
                last_state_write_at = now
                if include_preview:
                    last_preview_write_at = now

            sample_index += 1
            if tracking_interval > 0.0:
                sleep_seconds = max(0.0, tracking_interval - (time.monotonic() - iteration_started_at))
                if sleep_seconds > 0.0:
                    time.sleep(sleep_seconds)
    finally:
        if inference_session is not None:
            _close_inference_session(inference_session)
        _close_live_camera_capture_session(capture_session)


def _success_response(request: Dict[str, Any]) -> Dict[str, Any]:
    operation = str(request.get("operation", "startup"))
    runtime = request.get("runtime", {}) if isinstance(request.get("runtime", {}), dict) else {}
    if operation == "list_cameras":
        cameras = _enumerate_cameras(runtime)
        health = _base_health(operation, runtime)
        health["notes"].append(f"Enumerated {len(cameras)} camera candidate(s).")
        return {
            "ok": True,
            "cameras": cameras,
            "health": health,
            "preview_descriptor": {},
            "raw_tracking_frame": {},
        }
    if operation == "describe_camera_options":
        return _describe_live_camera_options(request)
    return _sample_once(request)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request-file", required=True)
    parser.add_argument("--session-dir", default="")
    args = parser.parse_args()

    started = time.time()
    try:
        request = _read_request(args.request_file)
        operation = str(request.get("operation", "startup"))
        session_dir = str(args.session_dir).strip()
        if session_dir != "" and operation in ("startup", "reconfigure"):
            return _run_continuous_session(request, session_dir)
        response = _success_response(request)
    except Exception as exc:  # pragma: no cover
        response = {
            "ok": False,
            "cameras": [],
            "health": {
                "status": "error",
                "backend": "mediapipe_python",
                "runtime_available": False,
                "bridge_connected": True,
                "process_active": False,
                "camera_accessible": False,
                "tracking_active": False,
                "healthy": False,
                "last_error": {"code": "runtime_probe_exception", "message": str(exc)},
                "notes": ["Python runtime probe raised an exception."],
                "probed_at": _now_iso(),
                "python_executable": sys.executable,
                "python_version": platform.python_version(),
            },
            "error_info": {"code": "runtime_probe_exception", "message": str(exc)},
        }

    response.setdefault("health", {})["probe_duration_ms"] = int((time.time() - started) * 1000)
    print(json.dumps(response, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

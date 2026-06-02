#!/usr/bin/env python3
import argparse
import glob
import json
import math
import os
import platform
import sys
import time
from typing import Any, Dict, List, Optional, Sequence

_DEFAULT_MODEL_COMPLEXITY = 1
_MODEL_FILENAMES = {
    0: "pose_landmarker_lite.task",
    1: "pose_landmarker_full.task",
    2: "pose_landmarker_heavy.task",
}

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

        frame = None
        for attempt in range(5):
            ok, candidate = capture.read()
            if ok and candidate is not None:
                frame = candidate
                break
            if attempt < 4:
                time.sleep(0.1)

        if frame is None:
            return {
                "ok": False,
                "error_info": {
                    "code": "camera_read_failed",
                    "message": f"OpenCV could not read a frame from selected camera '{camera_id}' via {source_label}",
                },
            }

        shape = getattr(frame, "shape", None)
        if shape is None or len(shape) < 2:
            return {
                "ok": False,
                "error_info": {
                    "code": "camera_frame_invalid",
                    "message": f"OpenCV returned an invalid frame shape for selected camera '{camera_id}' via {source_label}",
                },
            }

        height = int(shape[0])
        width = int(shape[1])
        if width <= 0 or height <= 0:
            return {
                "ok": False,
                "error_info": {
                    "code": "camera_frame_invalid",
                    "message": f"OpenCV returned non-positive frame dimensions for selected camera '{camera_id}' via {source_label}",
                },
            }

        timestamp_ms = _now_ms()
        note = f"Captured one live sample frame from '{camera_id}' with dimensions {width}x{height}."
        if source_label != "device path":
            note = f"Captured one live sample frame from '{camera_id}' with dimensions {width}x{height} via {source_label}."

        return {
            "ok": True,
            "frame_bgr": frame,
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

    try:
        import cv2  # type: ignore
    except Exception as exc:
        return {
            "ok": False,
            "error_info": {
                "code": "opencv_unavailable",
                "message": f"OpenCV import failed while sampling camera '{camera_id}': {exc}",
            },
        }

    attempts = [(camera_id, "device path")]
    device_index = _camera_device_index(camera_id)
    if device_index is not None:
        attempts.append((device_index, f"device index fallback {device_index}"))

    last_failure = {
        "ok": False,
        "error_info": {
            "code": "camera_sample_failed",
            "message": f"Failed to capture a sample frame from selected camera '{camera_id}'",
        },
    }
    for capture_source, source_label in attempts:
        result = _capture_frame_with_opencv_source(cv2, camera_id, capture_source, source_label)
        if bool(result.get("ok", False)):
            return result
        last_failure = result

    return last_failure


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


def _run_video_file_session(request: Dict[str, Any], session_dir: str) -> int:
    os.makedirs(session_dir, exist_ok=True)
    _write_json_atomic(_session_request_path(session_dir), request)
    runtime = request.get("runtime", {}) if isinstance(request.get("runtime", {}), dict) else {}
    source = request.get("source", {}) if isinstance(request.get("source", {}), dict) else {}
    preview = request.get("preview", {}) if isinstance(request.get("preview", {}), dict) else {}
    preview_config = _preview_runtime_config(preview, runtime)
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
    start_time_sec = max(0.0, float(source.get("start_time_sec", 0.0) or 0.0))
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
        if start_time_sec > 0.0:
            capture.set(cv2.CAP_PROP_POS_MSEC, start_time_sec * 1000.0)

    inference_session: Optional[Dict[str, Any]] = None
    if not use_fixture_sequence:
        inference_session = _create_inference_session(runtime)
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
                    "playback_status": _playback_status(video_path, start_time_sec, duration_sec, "paused", True),
                    "raw_tracking_frame": {},
                }
                _write_session_snapshot(session_dir, shutdown_snapshot)
                return 0

            if use_fixture_sequence:
                sampled = _capture_video_file_sample(video_path, runtime, sample_index=sample_index, dynamic_timestamp=True)
                if not bool(sampled.get("ok", False)) and sampled.get("error_info", {}).get("code") == "video_file_eof":
                    eof_snapshot = _replay_eof_snapshot(request, video_path, loop_started_ms, sample_index)
                    eof_snapshot["preview_descriptor"] = last_preview_descriptor.copy()
                    _write_session_snapshot(session_dir, eof_snapshot)
                    return 0
            else:
                assert capture is not None
                ok, frame = capture.read()
                if not ok or frame is None:
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

            inferred = _infer_pose_landmarks(sampled, runtime, inference_session=inference_session, tracking_semantics=tracking_semantics, filter_state=tracking_filter_state)
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
            current_time_sec = start_time_sec
            if capture is not None and cv2 is not None:
                current_time_sec = max(start_time_sec, float(capture.get(cv2.CAP_PROP_POS_MSEC) or 0.0) / 1000.0)

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


def _open_live_camera_capture_session(camera_id: str, runtime: Dict[str, Any]) -> Dict[str, Any]:
    fixture_sample = _sample_from_fixture(camera_id, runtime, sample_index=0, dynamic_timestamp=False, source_kind="live_camera")
    if fixture_sample is not None:
        return {"ok": True, "fixture_only": True}

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

    attempts = [(camera_id, "device path")]
    device_index = _camera_device_index(camera_id)
    if device_index is not None:
        attempts.append((device_index, f"device index fallback {device_index}"))

    last_failure = {
        "ok": False,
        "error_info": {
            "code": "camera_open_failed",
            "message": f"OpenCV could not open selected camera '{camera_id}' for continuous capture",
        },
    }
    for capture_source, source_label in attempts:
        capture = cv2.VideoCapture(capture_source)
        if capture.isOpened():
            return {
                "ok": True,
                "fixture_only": False,
                "cv2": cv2,
                "capture": capture,
                "source_label": source_label,
            }
        capture.release()
        last_failure = {
            "ok": False,
            "error_info": {
                "code": "camera_open_failed",
                "message": f"OpenCV could not open selected camera '{camera_id}' via {source_label} for continuous capture",
            },
        }
    return last_failure


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

    frame = None
    for attempt in range(5):
        ok, candidate = capture.read()
        if ok and candidate is not None:
            frame = candidate
            break
        if attempt < 4:
            time.sleep(0.02)

    if frame is None:
        return {
            "ok": False,
            "error_info": {
                "code": "camera_read_failed",
                "message": f"OpenCV could not read a frame from selected camera '{camera_id}' via {source_label}",
            },
        }

    shape = getattr(frame, "shape", None)
    if shape is None or len(shape) < 2:
        return {
            "ok": False,
            "error_info": {
                "code": "camera_frame_invalid",
                "message": f"OpenCV returned an invalid frame shape for selected camera '{camera_id}' via {source_label}",
            },
        }

    height = int(shape[0])
    width = int(shape[1])
    if width <= 0 or height <= 0:
        return {
            "ok": False,
            "error_info": {
                "code": "camera_frame_invalid",
                "message": f"OpenCV returned non-positive frame dimensions for selected camera '{camera_id}' via {source_label}",
            },
        }

    note = f"Captured live session frame {sample_index} from '{camera_id}' with dimensions {width}x{height}."
    if source_label != "device path":
        note = f"Captured live session frame {sample_index} from '{camera_id}' with dimensions {width}x{height} via {source_label}."
    return {
        "ok": True,
        "frame_bgr": frame,
        "raw_tracking_frame": _raw_tracking_frame_base("live_camera", camera_id, width, height, _now_ms()),
        "notes": [note],
    }


def _create_inference_session(runtime: Dict[str, Any]) -> Dict[str, Any]:
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
        return {
            "ok": True,
            "backend": "mediapipe_solutions_pose",
            "cv2": cv2,
            "processor": pose,
        }

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
        return {
            "ok": True,
            "backend": "mediapipe_tasks_pose_landmarker",
            "cv2": cv2,
            "mp": mp,
            "processor": landmarker,
            "model_asset_path": model_path,
        }

    return {
        "ok": False,
        "error_info": {
            "code": "mediapipe_package_unsupported",
            "message": "Installed MediaPipe package exposes neither mediapipe.solutions.pose nor a usable mediapipe.tasks vision PoseLandmarker path",
        },
    }


def _close_inference_session(inference_session: Dict[str, Any]) -> None:
    processor = inference_session.get("processor")
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
    processor = inference_session.get("processor")
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


def _infer_pose_landmarks(sampled: Dict[str, Any], runtime: Dict[str, Any], inference_session: Optional[Dict[str, Any]] = None, tracking_semantics: Optional[Dict[str, Any]] = None, filter_state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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


def _sample_once(request: Dict[str, Any], sample_index: int = 0, dynamic_timestamp: bool = False) -> Dict[str, Any]:
    selection = _select_source(request)
    if not bool(selection.get("ok", False)):
        return selection

    runtime: Dict[str, Any] = selection["runtime"]
    source: Dict[str, Any] = selection["source"]
    preview = request.get("preview", {}) if isinstance(request.get("preview", {}), dict) else {}
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

    inferred = _infer_pose_landmarks(sampled, runtime, tracking_semantics=tracking_semantics, filter_state={} if bool(tracking_semantics.get('filter_enabled', True)) else None)
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
    health.update({
        "camera_accessible": True,
        "healthy": True,
        "tracking_active": False,
        "notes": health["notes"] + inferred.get("notes", []),
    })
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
        "frame_bgr": sampled.get("frame_bgr"),
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
        inference_session = _create_inference_session(runtime)
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
                shutdown_snapshot = {
                    "ok": True,
                    "cameras": _enumerate_cameras(runtime),
                    "selected_camera_id": selected_camera_id,
                    "health": {
                        **_base_health("shutdown", runtime),
                        "status": "idle",
                        "runtime_available": True,
                        "bridge_connected": True,
                        "process_active": False,
                        "camera_accessible": bool(selected.get("available", False)),
                        "tracking_active": False,
                        "healthy": True,
                        "selected_camera_id": selected_camera_id,
                        "selected_camera_label": selected.get("label", selected_camera_id),
                        "notes": ["Continuous MediaPipe runtime session stopped cleanly."],
                    },
                    "preview_descriptor": last_preview_descriptor.copy(),
                    "raw_tracking_frame": {},
                }
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

            inferred = _infer_pose_landmarks(sampled, runtime, inference_session=inference_session, tracking_semantics=tracking_semantics, filter_state=tracking_filter_state)
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

#!/usr/bin/env python3
import argparse
import glob
import json
import os
import platform
import sys
import time
from typing import Any, Dict, List, Optional


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _now_ms() -> int:
    return int(time.time() * 1000)


def _read_request(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _runtime_env(runtime: Dict[str, Any]) -> Dict[str, Any]:
    environment = runtime.get("environment", {})
    return environment if isinstance(environment, dict) else {}


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
            "Runtime probe captures a single truthful live-camera sample; full tracking inference is not implemented yet."
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



def _sample_from_fixture(camera_id: str, runtime: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    fixtures = _sample_fixture_map(runtime)
    fixture = fixtures.get(camera_id)
    if not isinstance(fixture, dict):
        return None

    width = int(fixture.get("width", 0))
    height = int(fixture.get("height", 0))
    timestamp_ms = int(fixture.get("timestamp_ms", _now_ms()))
    if width <= 0 or height <= 0:
        raise ValueError(f"Camera sample fixture for '{camera_id}' must provide positive width/height")

    return {
        "raw_tracking_frame": {
            "timestamp_ms": timestamp_ms,
            "source_kind": "live_camera",
            "source_id": camera_id,
            "tracking_state": "idle",
            "frame_size": {"x": width, "y": height},
        },
        "notes": [
            f"Captured sample frame for '{camera_id}' via configured fixture dimensions {width}x{height}."
        ],
    }



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

        note = f"Captured one live sample frame from '{camera_id}' with dimensions {width}x{height}."
        if source_label != "device path":
            note = f"Captured one live sample frame from '{camera_id}' with dimensions {width}x{height} via {source_label}."

        return {
            "ok": True,
            "raw_tracking_frame": {
                "timestamp_ms": _now_ms(),
                "source_kind": "live_camera",
                "source_id": camera_id,
                "tracking_state": "idle",
                "frame_size": {"x": width, "y": height},
            },
            "notes": [note],
        }
    finally:
        capture.release()



def _capture_live_camera_sample(camera_id: str, runtime: Dict[str, Any]) -> Dict[str, Any]:
    fixture_sample = _sample_from_fixture(camera_id, runtime)
    if fixture_sample is not None:
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



def _success_response(request: Dict[str, Any]) -> Dict[str, Any]:
    operation = str(request.get("operation", "startup"))
    runtime = request.get("runtime", {}) if isinstance(request.get("runtime", {}), dict) else {}
    source = request.get("source", {}) if isinstance(request.get("source", {}), dict) else {}
    preview = request.get("preview", {}) if isinstance(request.get("preview", {}), dict) else {}
    cameras = _enumerate_cameras(runtime)
    health = _base_health(operation, runtime)

    if operation == "list_cameras":
        health["notes"].append(f"Enumerated {len(cameras)} camera candidate(s).")
        return {
            "ok": True,
            "cameras": cameras,
            "health": health,
            "preview_descriptor": {},
            "raw_tracking_frame": {},
        }

    source_kind = str(source.get("kind", "live_camera"))
    if source_kind != "live_camera":
        return {
            "ok": False,
            "cameras": cameras,
            "health": {
                **health,
                "status": "error",
                "healthy": False,
                "last_error": {
                    "code": "unsupported_source_kind",
                    "message": f"MediaPipe Python probe only supports live_camera in this slice, got '{source_kind}'",
                },
            },
            "error_info": {
                "code": "unsupported_source_kind",
                "message": f"MediaPipe Python probe only supports live_camera in this slice, got '{source_kind}'",
            },
        }

    selected_camera_id = str(source.get("camera_id", "")).strip()
    if not cameras:
        return {
            "ok": False,
            "cameras": [],
            "health": {
                **health,
                "status": "error",
                "healthy": False,
                "last_error": {
                    "code": "no_live_cameras_found",
                    "message": "No live camera candidates were found during MediaPipe Python probe",
                },
                "notes": health["notes"] + ["Camera glob returned no candidates."],
            },
            "error_info": {
                "code": "no_live_cameras_found",
                "message": "No live camera candidates were found during MediaPipe Python probe",
            },
        }

    if selected_camera_id:
        selected = next((camera for camera in cameras if camera["camera_id"] == selected_camera_id), None)
        if selected is None:
            return {
                "ok": False,
                "cameras": cameras,
                "health": {
                    **health,
                    "status": "error",
                    "healthy": False,
                    "last_error": {
                        "code": "camera_not_found",
                        "message": f"Requested camera '{selected_camera_id}' was not found during MediaPipe Python probe",
                    },
                },
                "error_info": {
                    "code": "camera_not_found",
                    "message": f"Requested camera '{selected_camera_id}' was not found during MediaPipe Python probe",
                },
            }
    else:
        selected = cameras[0]
        selected_camera_id = selected["camera_id"]

    health.update(
        {
            "camera_accessible": bool(selected.get("available", False)),
            "healthy": bool(selected.get("available", False)),
            "selected_camera_id": selected_camera_id,
            "selected_camera_label": selected.get("label", selected_camera_id),
            "notes": health["notes"]
            + [f"Selected camera candidate '{selected_camera_id}' for truthful sample capture."],
        }
    )

    sampled = _capture_live_camera_sample(selected_camera_id, runtime)
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

    health.update(
        {
            "camera_accessible": True,
            "healthy": True,
            "tracking_active": False,
            "notes": health["notes"] + sampled.get("notes", []),
        }
    )

    return {
        "ok": True,
        "cameras": cameras,
        "selected_camera_id": selected_camera_id,
        "health": health,
        "preview_descriptor": {
            "enabled": bool(preview.get("enabled", True)),
            "surface_mode": str(preview.get("surface_mode", "attach")),
            "attached": False,
            "flip_horizontal": bool(preview.get("flip_horizontal", True)),
            "maintain_aspect_ratio": True,
            "backend": "mediapipe_python",
        },
        "raw_tracking_frame": sampled.get("raw_tracking_frame", {}).copy(),
    }



def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request-file", required=True)
    args = parser.parse_args()

    started = time.time()
    try:
        request = _read_request(args.request_file)
        response = _success_response(request)
    except Exception as exc:  # pragma: no cover - fallback path
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
                "last_error": {
                    "code": "runtime_probe_exception",
                    "message": str(exc),
                },
                "notes": ["Python runtime probe raised an exception."],
                "probed_at": _now_iso(),
                "python_executable": sys.executable,
                "python_version": platform.python_version(),
            },
            "error_info": {
                "code": "runtime_probe_exception",
                "message": str(exc),
            },
        }

    response.setdefault("health", {})["probe_duration_ms"] = int((time.time() - started) * 1000)
    print(json.dumps(response, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

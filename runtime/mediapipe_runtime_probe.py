#!/usr/bin/env python3
import argparse
import glob
import json
import os
import platform
import sys
import time
from typing import Any, Dict, List


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _read_request(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _camera_root() -> str:
    return os.environ.get("AEROBEAT_CAMERA_ROOT", "/dev")


def _camera_pattern() -> str:
    return os.environ.get("AEROBEAT_CAMERA_PATTERN", "video*")


def _enumerate_cameras() -> List[Dict[str, Any]]:
    root = _camera_root()
    pattern = _camera_pattern()
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
            "Bootstrap/probe slice only; live tracking inference is not implemented yet."
        ],
        "probe_operation": operation,
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "working_directory": runtime.get("working_directory", ""),
        "probed_at": _now_iso(),
    }


def _success_response(request: Dict[str, Any]) -> Dict[str, Any]:
    operation = str(request.get("operation", "startup"))
    runtime = request.get("runtime", {}) if isinstance(request.get("runtime", {}), dict) else {}
    source = request.get("source", {}) if isinstance(request.get("source", {}), dict) else {}
    preview = request.get("preview", {}) if isinstance(request.get("preview", {}), dict) else {}
    cameras = _enumerate_cameras()
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
            + [f"Selected camera candidate '{selected_camera_id}' for truthful bootstrap/probe."],
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
        "raw_tracking_frame": {},
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

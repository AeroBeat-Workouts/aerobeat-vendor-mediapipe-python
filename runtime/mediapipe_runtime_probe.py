#!/usr/bin/env python3
import argparse
import glob
import json
import os
import platform
import sys
import time
from typing import Any, Dict, List, Optional, Sequence


_DEFAULT_POSE_LANDMARKER_MODEL_PATHS: Sequence[str] = (
    "models/pose_landmarker_lite.task",
    "runtime/models/pose_landmarker_lite.task",
)


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
            "Runtime probe captures one truthful live-camera sample and runs one sampled pose-landmark inference pass; continuous tracking is not implemented yet."
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



def _raw_tracking_frame_base(camera_id: str, width: int, height: int, timestamp_ms: int) -> Dict[str, Any]:
    return {
        "timestamp_ms": timestamp_ms,
        "source_kind": "live_camera",
        "source_id": camera_id,
        "tracking_state": "idle",
        "frame_size": {"x": width, "y": height},
    }



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

    raw_tracking_frame = _raw_tracking_frame_base(camera_id, width, height, timestamp_ms)
    notes = [f"Captured sample frame for '{camera_id}' via configured fixture dimensions {width}x{height}."]

    if fixture.get("inference_error") is not None:
        error_info = fixture.get("inference_error")
        if not isinstance(error_info, dict):
            raise ValueError(f"Camera sample fixture for '{camera_id}' inference_error must be an object")
        return {
            "raw_tracking_frame": raw_tracking_frame,
            "fixture_inference_error": {
                "code": str(error_info.get("code", "mediapipe_inference_failed")),
                "message": str(error_info.get("message", f"Fixture inference failed for '{camera_id}'")),
            },
            "notes": notes,
        }

    landmarks_raw = fixture.get("landmarks")
    if isinstance(landmarks_raw, list):
        landmarks = [_normalize_fixture_landmark(camera_id, landmark, index) for index, landmark in enumerate(landmarks_raw)]
        if landmarks:
            raw_tracking_frame["tracking_state"] = "tracked"
            raw_tracking_frame["landmarks"] = landmarks
            notes.append(f"Fixture supplied {len(landmarks)} pose landmark(s) for '{camera_id}'.")
        else:
            notes.append(f"Fixture supplied an empty landmark array for '{camera_id}'; tracking remains idle.")

    return {
        "raw_tracking_frame": raw_tracking_frame,
        "notes": notes,
        "fixture_used": True,
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

        timestamp_ms = _now_ms()
        note = f"Captured one live sample frame from '{camera_id}' with dimensions {width}x{height}."
        if source_label != "device path":
            note = f"Captured one live sample frame from '{camera_id}' with dimensions {width}x{height} via {source_label}."

        return {
            "ok": True,
            "frame_bgr": frame,
            "raw_tracking_frame": _raw_tracking_frame_base(camera_id, width, height, timestamp_ms),
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

    for candidate in _DEFAULT_POSE_LANDMARKER_MODEL_PATHS:
        resolved = _resolve_runtime_path(runtime, candidate)
        if os.path.isfile(resolved):
            return resolved

    return ""



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
                "message": "MediaPipe tasks pose inference requires a pose landmarker .task model asset, but none was found. Checked runtime.pose_landmarker_model_path, runtime.model_asset_path, AEROBEAT_MEDIAPIPE_POSE_LANDMARKER_MODEL_PATH, MEDIAPIPE_POSE_LANDMARKER_MODEL_PATH, and default repo model locations.",
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



def _infer_pose_landmarks(sampled: Dict[str, Any], runtime: Dict[str, Any]) -> Dict[str, Any]:
    raw_tracking_frame = sampled.get("raw_tracking_frame", {}).copy()
    notes = list(sampled.get("notes", []))

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

    inferred = _infer_pose_landmarks_with_mediapipe(runtime, frame_bgr)
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
        notes.append(f"MediaPipe pose inference produced {len(landmarks)} landmark(s) from the sampled frame via {inferred.get('inference_backend', 'mediapipe') }.")
    else:
        raw_tracking_frame.pop("landmarks", None)
        raw_tracking_frame["tracking_state"] = "idle"
        notes.append(f"MediaPipe pose inference via {inferred.get('inference_backend', 'mediapipe')} found no landmarks in the sampled frame; tracking remains idle.")

    if inferred.get("model_asset_path"):
        notes.append(f"MediaPipe tasks pose landmarker used model asset '{inferred['model_asset_path']}'.")

    return {
        "ok": True,
        "raw_tracking_frame": raw_tracking_frame,
        "notes": notes,
    }



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

    inferred = _infer_pose_landmarks(sampled, runtime)
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

    health.update(
        {
            "camera_accessible": True,
            "healthy": True,
            "tracking_active": False,
            "notes": health["notes"] + inferred.get("notes", []),
        }
    )

    if isinstance(landmarks, list) and len(landmarks) > 0:
        health["notes"].append(f"Returning {len(landmarks)} raw sampled pose landmark(s).")
    else:
        health["notes"].append("Returning no raw landmarks because the sampled frame did not produce a pose.")

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
        "raw_tracking_frame": raw_tracking_frame,
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

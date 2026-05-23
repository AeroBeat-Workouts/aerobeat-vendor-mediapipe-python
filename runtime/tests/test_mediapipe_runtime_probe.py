import importlib.util
import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


_MODULE_PATH = Path(__file__).resolve().parents[1] / "mediapipe_runtime_probe.py"
_SPEC = importlib.util.spec_from_file_location("mediapipe_runtime_probe", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
probe = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(probe)


class _FakeCv2:
    COLOR_BGR2RGB = 1

    @staticmethod
    def cvtColor(frame_bgr, color_code):
        if color_code != _FakeCv2.COLOR_BGR2RGB:
            raise AssertionError("unexpected color conversion code")
        return frame_bgr


class _FakeLandmark:
    def __init__(self, x, y, z, visibility):
        self.x = x
        self.y = y
        self.z = z
        self.visibility = visibility


class _FakeLegacyPose:
    def __init__(self, static_image_mode=True):
        self.static_image_mode = static_image_mode

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def process(self, frame_rgb):
        return types.SimpleNamespace(
            pose_landmarks=types.SimpleNamespace(
                landmark=[_FakeLandmark(0.25, 0.5, -0.1, 0.9), _FakeLandmark(0.6, 0.4, -0.2, 0.8)]
            )
        )


class _FakeImage:
    def __init__(self, image_format, data):
        self.image_format = image_format
        self.data = data


class _FakeBaseOptions:
    def __init__(self, model_asset_path):
        self.model_asset_path = model_asset_path


class _FakePoseLandmarkerOptions:
    def __init__(self, base_options, running_mode, num_poses=1, **_kwargs):
        self.base_options = base_options
        self.running_mode = running_mode
        self.num_poses = num_poses


class _FakePoseLandmarker:
    last_options = None

    def __init__(self, options):
        self.options = options

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def detect(self, image):
        return types.SimpleNamespace(
            pose_landmarks=[
                [_FakeLandmark(0.11, 0.22, -0.33, 0.44), _FakeLandmark(0.55, 0.66, -0.77, 0.88)]
            ]
        )

    @classmethod
    def create_from_options(cls, options):
        cls.last_options = options
        return cls(options)


def _fake_tasks_mediapipe_module():
    vision_module = types.SimpleNamespace(
        PoseLandmarker=_FakePoseLandmarker,
        PoseLandmarkerOptions=_FakePoseLandmarkerOptions,
        RunningMode=types.SimpleNamespace(IMAGE="IMAGE"),
    )
    tasks_module = types.SimpleNamespace()
    mp_module = types.SimpleNamespace(
        tasks=tasks_module,
        Image=_FakeImage,
        ImageFormat=types.SimpleNamespace(SRGB="SRGB"),
    )
    modules = {
        "mediapipe": mp_module,
        "mediapipe.tasks": tasks_module,
        "mediapipe.tasks.python": types.SimpleNamespace(vision=vision_module),
        "mediapipe.tasks.python.vision": vision_module,
        "mediapipe.tasks.python.core": types.SimpleNamespace(base_options=types.SimpleNamespace(BaseOptions=_FakeBaseOptions)),
        "mediapipe.tasks.python.core.base_options": types.SimpleNamespace(BaseOptions=_FakeBaseOptions),
    }
    return modules


def _fake_legacy_mediapipe_module():
    pose_namespace = types.SimpleNamespace(Pose=_FakeLegacyPose)
    solutions_namespace = types.SimpleNamespace(pose=pose_namespace)
    mp_module = types.SimpleNamespace(solutions=solutions_namespace)
    return {"mediapipe": mp_module}


class MediaPipeRuntimeProbeTests(unittest.TestCase):
    def test_resolve_pose_landmarker_model_path_prefers_explicit_runtime_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            explicit_model = Path(temp_dir) / "explicit.task"
            explicit_model.write_bytes(b"model")
            runtime = {
                "working_directory": temp_dir,
                "pose_landmarker_model_path": str(explicit_model),
            }
            self.assertEqual(probe._resolve_pose_landmarker_model_path(runtime), str(explicit_model))

    def test_tasks_path_fails_honestly_when_model_is_missing(self):
        runtime = {"working_directory": tempfile.gettempdir()}
        with mock.patch.dict("sys.modules", {"cv2": _FakeCv2, **_fake_tasks_mediapipe_module()}, clear=False):
            result = probe._infer_pose_landmarks_with_mediapipe(runtime, frame_bgr=[[0]])
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_info"]["code"], "mediapipe_model_missing")

    def test_tasks_path_emits_minimal_landmarks_when_model_is_available(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            model_path = Path(temp_dir) / "pose_landmarker_lite.task"
            model_path.write_bytes(b"model")
            runtime = {
                "working_directory": temp_dir,
                "pose_landmarker_model_path": str(model_path),
            }
            with mock.patch.dict("sys.modules", {"cv2": _FakeCv2, **_fake_tasks_mediapipe_module()}, clear=False):
                result = probe._infer_pose_landmarks_with_mediapipe(runtime, frame_bgr=[[0]])
            self.assertTrue(result["ok"])
            self.assertEqual(result["inference_backend"], "mediapipe_tasks_pose_landmarker")
            self.assertEqual(result["model_asset_path"], str(model_path))
            self.assertEqual(result["landmarks"], [
                {"id": 0, "x": 0.11, "y": 0.22, "z": -0.33, "visibility": 0.44},
                {"id": 1, "x": 0.55, "y": 0.66, "z": -0.77, "visibility": 0.88},
            ])
            self.assertEqual(_FakePoseLandmarker.last_options.base_options.model_asset_path, str(model_path))

    def test_legacy_path_still_supported_when_solutions_pose_exists(self):
        runtime = {"working_directory": os.getcwd()}
        with mock.patch.dict("sys.modules", {"cv2": _FakeCv2, **_fake_legacy_mediapipe_module()}, clear=False):
            result = probe._infer_pose_landmarks_with_mediapipe(runtime, frame_bgr=[[0]])
        self.assertTrue(result["ok"])
        self.assertEqual(result["inference_backend"], "mediapipe_solutions_pose")
        self.assertEqual(result["landmarks"], [
            {"id": 0, "x": 0.25, "y": 0.5, "z": -0.1, "visibility": 0.9},
            {"id": 1, "x": 0.6, "y": 0.4, "z": -0.2, "visibility": 0.8},
        ])

    def test_runtime_reports_unsupported_package_when_neither_legacy_nor_tasks_api_exists(self):
        runtime = {"working_directory": os.getcwd()}
        with mock.patch.dict("sys.modules", {"cv2": _FakeCv2, "mediapipe": types.SimpleNamespace()}, clear=False):
            result = probe._infer_pose_landmarks_with_mediapipe(runtime, frame_bgr=[[0]])
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_info"]["code"], "mediapipe_package_unsupported")

    def test_video_file_sample_uses_fixture_sequence_with_truthful_source_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = Path(temp_dir) / "fixture.mp4"
            video_path.write_bytes(b"fixture-video")
            runtime = {
                "working_directory": temp_dir,
                "environment": {
                    "AEROBEAT_CAMERA_SAMPLE_FIXTURES_JSON": json.dumps({
                        str(video_path): {
                            "sequence": [
                                {"width": 960, "height": 540, "timestamp_ms": 101, "landmarks": [{"id": 4, "x": 0.2, "y": 0.3, "z": -0.1, "visibility": 0.9}]},
                                {"width": 960, "height": 540, "timestamp_ms": 202}
                            ]
                        }
                    })
                }
            }
            request = {
                "operation": "startup",
                "runtime": runtime,
                "source": {"kind": "video_file", "path": str(video_path)},
                "preview": {"enabled": True},
            }
            first = probe._sample_once(request, sample_index=0, dynamic_timestamp=False)
            self.assertTrue(first["ok"])
            self.assertEqual(first["selected_camera_id"], str(video_path))
            self.assertEqual(first["raw_tracking_frame"]["source_kind"], "video_file")
            self.assertEqual(first["raw_tracking_frame"]["source_id"], str(video_path))
            self.assertEqual(first["raw_tracking_frame"]["tracking_state"], "tracked")
            self.assertEqual(first["raw_tracking_frame"]["frame_size"], {"x": 960, "y": 540})
            self.assertEqual(first["raw_tracking_frame"]["landmarks"][0]["id"], 4)

            second = probe._sample_once(request, sample_index=1, dynamic_timestamp=False)
            self.assertTrue(second["ok"])
            self.assertEqual(second["raw_tracking_frame"]["tracking_state"], "idle")
            self.assertEqual(second["raw_tracking_frame"]["source_kind"], "video_file")
            self.assertFalse("landmarks" in second["raw_tracking_frame"])

    def test_run_continuous_video_file_session_writes_idle_snapshot_after_fixture_eof(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = Path(temp_dir) / "fixture.mp4"
            video_path.write_bytes(b"fixture-video")
            session_dir = Path(temp_dir) / "session"
            request = {
                "operation": "startup",
                "runtime": {
                    "working_directory": temp_dir,
                    "health_poll_interval_ms": 30,
                    "environment": {
                        "AEROBEAT_CAMERA_SAMPLE_FIXTURES_JSON": json.dumps({
                            str(video_path): {
                                "sequence": [
                                    {"width": 640, "height": 360, "timestamp_ms": 10},
                                    {"width": 640, "height": 360, "timestamp_ms": 20}
                                ]
                            }
                        })
                    }
                },
                "source": {"kind": "video_file", "path": str(video_path)},
                "preview": {"enabled": True},
            }
            with mock.patch.object(probe.time, "sleep", return_value=None):
                exit_code = probe._run_continuous_session(request, str(session_dir))
            self.assertEqual(exit_code, 0)
            snapshot_path = session_dir / "runtime_snapshot.json"
            self.assertTrue(snapshot_path.exists())
            snapshot = json.loads(snapshot_path.read_text())
            self.assertTrue(snapshot["ok"])
            self.assertEqual(snapshot["selected_camera_id"], str(video_path))
            self.assertEqual(snapshot["health"]["status"], "idle")
            self.assertFalse(snapshot["health"]["process_active"])
            self.assertFalse(snapshot["health"]["tracking_active"])
            self.assertEqual(snapshot["raw_tracking_frame"], {})


if __name__ == "__main__":
    unittest.main()

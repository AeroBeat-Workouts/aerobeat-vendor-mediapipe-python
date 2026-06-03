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


class _FakeNegotiatedCapture:
    def __init__(self, profile):
        self.profile = profile
        self._released = False

    def isOpened(self):
        return bool(self.profile.get("opened", True))

    def read(self):
        if not self.isOpened():
            return (False, None)
        width = int(self.profile.get("width", 0))
        height = int(self.profile.get("height", 0))
        frame = types.SimpleNamespace(shape=(height, width, 3))
        return (True, frame)

    def release(self):
        self._released = True

    def set(self, _prop, _value):
        return True

    def get(self, prop):
        if prop == _FakeNegotiationCv2.CAP_PROP_FRAME_WIDTH:
            return float(self.profile.get("width", 0))
        if prop == _FakeNegotiationCv2.CAP_PROP_FRAME_HEIGHT:
            return float(self.profile.get("height", 0))
        if prop == _FakeNegotiationCv2.CAP_PROP_FPS:
            return float(self.profile.get("fps", 0.0))
        if prop == _FakeNegotiationCv2.CAP_PROP_FOURCC:
            fourcc = str(self.profile.get("fourcc", "") or "")
            return float(_FakeNegotiationCv2.VideoWriter_fourcc(*fourcc[:4])) if fourcc else 0.0
        return 0.0


class _FakeNegotiationCv2(_FakeCv2):
    CAP_V4L2 = 200
    CAP_PROP_FRAME_WIDTH = 3
    CAP_PROP_FRAME_HEIGHT = 4
    CAP_PROP_FPS = 5
    CAP_PROP_FOURCC = 6
    PROFILES = {}

    @staticmethod
    def VideoWriter_fourcc(*chars):
        padded = list(chars[:4]) + ["\0"] * max(0, 4 - len(chars[:4]))
        return sum(ord(ch) << (8 * idx) for idx, ch in enumerate(padded[:4]))

    @classmethod
    def VideoCapture(cls, source, backend=None):
        backend_name = "CAP_V4L2" if backend == cls.CAP_V4L2 else "default"
        profile = cls.PROFILES.get((source, backend_name), {"opened": False})
        return _FakeNegotiatedCapture(profile)


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


class _FakeCompletedProcess:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


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

    def test_resolve_pose_landmarker_model_path_uses_model_complexity_specific_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            models_dir = Path(temp_dir) / "models"
            models_dir.mkdir()
            full_model = models_dir / "pose_landmarker_full.task"
            full_model.write_bytes(b"model")
            runtime = {
                "working_directory": temp_dir,
                "model_complexity": 1,
            }
            self.assertEqual(probe._resolve_pose_landmarker_model_path(runtime), str(full_model))

    def test_resolve_pose_landmarker_model_path_does_not_silently_fallback_to_lite_for_higher_complexity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            models_dir = Path(temp_dir) / "models"
            models_dir.mkdir()
            (models_dir / "pose_landmarker_lite.task").write_bytes(b"model")
            runtime = {
                "working_directory": temp_dir,
                "model_complexity": 2,
            }
            self.assertEqual(probe._resolve_pose_landmarker_model_path(runtime), "")

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
                                {"width": 960, "height": 540, "timestamp_ms": 101, "landmarks": [{"id": 15, "x": 0.2, "y": 0.3, "z": -0.1, "visibility": 0.9}]},
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
            self.assertEqual(first["raw_tracking_frame"]["landmarks"][0]["id"], 15)

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

    def test_preview_descriptor_uses_runtime_preview_knobs(self):
        descriptor = probe._preview_descriptor(
            {"enabled": True, "surface_mode": "attach", "flip_horizontal": False},
            {
                "preview_enabled": False,
                "preview_max_fps": 60,
                "preview_width": 640,
                "preview_height": 360,
                "preview_quality": 80,
            },
        )
        self.assertFalse(descriptor["enabled"])
        self.assertEqual(descriptor["max_fps"], 60)
        self.assertEqual(descriptor["width"], 640)
        self.assertEqual(descriptor["height"], 360)
        self.assertEqual(descriptor["quality"], 80)
        self.assertFalse(descriptor["flip_horizontal"])

    def test_video_file_session_tracking_sleep_uses_tracking_max_fps_instead_of_health_poll_interval(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = Path(temp_dir) / "fixture.mp4"
            video_path.write_bytes(b"fixture-video")
            session_dir = Path(temp_dir) / "session"
            request = {
                "operation": "startup",
                "runtime": {
                    "working_directory": temp_dir,
                    "health_poll_interval_ms": 250,
                    "tracking_max_fps": 60,
                    "state_update_max_fps": 60,
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
            sleeps = []

            def _fake_sleep(duration):
                sleeps.append(duration)
                return None

            with mock.patch.object(probe.time, "sleep", side_effect=_fake_sleep):
                exit_code = probe._run_continuous_session(request, str(session_dir))

            self.assertEqual(exit_code, 0)
            self.assertTrue(any(duration < 0.05 for duration in sleeps), sleeps)
            self.assertFalse(any(abs(duration - 0.25) < 0.001 for duration in sleeps), sleeps)

    def test_sample_once_prefers_v4l2_mjpg_and_reports_negotiated_mode_truthfully(self):
        request = {
            "operation": "startup",
            "runtime": {
                "working_directory": os.getcwd(),
                "live_camera_width": 1280,
                "live_camera_height": 720,
                "live_camera_fps": 30,
                "live_camera_fourcc": "MJPG",
                "pose_landmarker_model_path": "unused-for-fake-legacy-path",
                "environment": {
                    "AEROBEAT_CAMERA_ROOT": "/dev",
                    "AEROBEAT_CAMERA_PATTERN": "video0",
                },
            },
            "tracking": {"quality": "full", "overlay_mode": "full"},
            "source": {"kind": "live_camera", "camera_id": "/dev/video0"},
            "preview": {"enabled": True},
        }
        _FakeNegotiationCv2.PROFILES = {
            ("/dev/video0", "CAP_V4L2"): {"opened": True, "width": 1280, "height": 720, "fps": 30.0, "fourcc": "MJPG"},
            ("/dev/video0", "default"): {"opened": True, "width": 1920, "height": 1080, "fps": 5.0, "fourcc": "YUYV"},
        }
        with mock.patch.object(probe.platform, "system", return_value="Linux"):
            with mock.patch.dict("sys.modules", {"cv2": _FakeNegotiationCv2, **_fake_legacy_mediapipe_module()}, clear=False):
                result = probe._sample_once(request, sample_index=0, dynamic_timestamp=False)
        self.assertTrue(result["ok"])
        capture_mode = result["health"]["capture_mode"]
        self.assertEqual(capture_mode["backend"], "CAP_V4L2")
        self.assertEqual(capture_mode["requested"]["fourcc"], "MJPG")
        self.assertEqual(capture_mode["actual"]["fourcc"], "MJPG")
        self.assertEqual(capture_mode["actual"]["width"], 1280)
        self.assertEqual(capture_mode["actual"]["height"], 720)
        self.assertTrue(any("requested 1280x720@30 MJPG; selected 1280x720@30.0 MJPG" in note for note in result["health"]["notes"]))
        self.assertEqual(capture_mode["selected"]["fourcc"], "MJPG")
        self.assertEqual(capture_mode["reported_source"], "fallback_probe_sweep")
        self.assertTrue("camera_options" in result)

    def test_sample_once_falls_back_when_preferred_linux_mode_is_not_really_negotiated(self):
        request = {
            "operation": "startup",
            "runtime": {
                "working_directory": os.getcwd(),
                "live_camera_width": 1280,
                "live_camera_height": 720,
                "live_camera_fps": 30,
                "live_camera_fourcc": "MJPG",
                "pose_landmarker_model_path": "unused-for-fake-legacy-path",
                "environment": {
                    "AEROBEAT_CAMERA_ROOT": "/dev",
                    "AEROBEAT_CAMERA_PATTERN": "video0",
                },
            },
            "tracking": {"quality": "full", "overlay_mode": "full"},
            "source": {"kind": "live_camera", "camera_id": "/dev/video0"},
            "preview": {"enabled": True},
        }
        _FakeNegotiationCv2.PROFILES = {
            ("/dev/video0", "CAP_V4L2"): {"opened": True, "width": 1920, "height": 1080, "fps": 5.0, "fourcc": "YUYV"},
            ("/dev/video0", "default"): {"opened": True, "width": 1280, "height": 720, "fps": 30.0, "fourcc": "MJPG"},
        }
        with mock.patch.object(probe.platform, "system", return_value="Linux"):
            with mock.patch.dict("sys.modules", {"cv2": _FakeNegotiationCv2, **_fake_legacy_mediapipe_module()}, clear=False):
                result = probe._sample_once(request, sample_index=0, dynamic_timestamp=False)
        self.assertTrue(result["ok"])
        capture_mode = result["health"]["capture_mode"]
        self.assertEqual(capture_mode["backend"], "default")
        self.assertEqual(capture_mode["actual"]["width"], 1280)
        self.assertEqual(capture_mode["actual"]["height"], 720)
        self.assertEqual(capture_mode["actual"]["fps"], 30.0)
        self.assertEqual(capture_mode["actual"]["fourcc"], "MJPG")
        self.assertTrue(any("actual mode is 1280x720@30.000 MJPG" in note for note in result["health"]["notes"]))
        self.assertEqual(capture_mode["selected"]["fps"], 30.0)

    def test_sample_once_reduces_optimized_landmark_sets_instead_of_only_hiding_them(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            camera_path = Path(temp_dir) / "video0"
            camera_path.write_bytes(b"fixture")
            request = {
                "operation": "startup",
                "runtime": {
                    "working_directory": temp_dir,
                    "environment": {
                        "AEROBEAT_CAMERA_ROOT": temp_dir,
                        "AEROBEAT_CAMERA_PATTERN": "video*",
                        "AEROBEAT_CAMERA_SAMPLE_FIXTURES_JSON": json.dumps({
                            str(camera_path): {
                                "width": 1280,
                                "height": 720,
                                "timestamp_ms": 111,
                                "landmarks": [
                                    {"id": 0, "x": 0.20, "y": 0.40, "z": -0.10, "visibility": 0.90},
                                    {"id": 2, "x": 0.21, "y": 0.39, "z": -0.10, "visibility": 0.85},
                                    {"id": 11, "x": 0.35, "y": 0.50, "z": -0.08, "visibility": 0.95},
                                    {"id": 15, "x": 0.42, "y": 0.58, "z": -0.12, "visibility": 0.93},
                                ],
                            }
                        })
                    },
                },
                "tracking": {"quality": "optimized", "overlay_mode": "optimized"},
                "source": {"kind": "live_camera", "camera_id": str(camera_path)},
                "preview": {"enabled": True},
            }
            result = probe._sample_once(request, sample_index=0, dynamic_timestamp=False)
        self.assertTrue(result["ok"])
        landmark_ids = [landmark["id"] for landmark in result["raw_tracking_frame"]["landmarks"]]
        self.assertEqual(landmark_ids, [0, 11, 15])
        semantics = result["raw_tracking_frame"]["vendor_tracking_semantics"]
        self.assertEqual(semantics["quality"], "optimized")
        self.assertEqual(semantics["landmark_count_before"], 4)
        self.assertEqual(semantics["landmark_count_after"], 3)

    def test_fixture_inference_path_applies_filter_state_when_enabled(self):
        semantics = {"quality": "optimized", "overlay_mode": "optimized", "point_mode": "reduced", "filter_enabled": True}
        filter_state = {}
        first = probe._infer_pose_landmarks(
            {
                "fixture_used": True,
                "raw_tracking_frame": {
                    "timestamp_ms": 100,
                    "landmarks": [{"id": 15, "x": 0.0, "y": 0.5, "z": -0.1, "visibility": 0.9}],
                },
            },
            {},
            tracking_semantics=semantics,
            filter_state=filter_state,
        )
        second = probe._infer_pose_landmarks(
            {
                "fixture_used": True,
                "raw_tracking_frame": {
                    "timestamp_ms": 200,
                    "landmarks": [{"id": 15, "x": 1.0, "y": 0.5, "z": -0.1, "visibility": 0.9}],
                },
            },
            {},
            tracking_semantics=semantics,
            filter_state=filter_state,
        )
        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"])
        self.assertEqual(first["raw_tracking_frame"]["landmarks"][0]["x"], 0.0)
        self.assertLess(second["raw_tracking_frame"]["landmarks"][0]["x"], 1.0)
        self.assertGreater(second["raw_tracking_frame"]["landmarks"][0]["x"], 0.0)

    def test_tracking_semantics_honors_legacy_no_filter_flag(self):
        semantics = probe._tracking_semantics({
            "runtime": {"no_filter": True},
            "tracking": {"quality": "simple", "overlay_mode": "simple"},
        })
        self.assertEqual(semantics["quality"], "optimized")
        self.assertEqual(semantics["overlay_mode"], "optimized")
        self.assertFalse(semantics["filter_enabled"])
        self.assertEqual(semantics["point_mode"], "reduced")

    def test_describe_camera_options_uses_v4l2_reported_modes_as_canonical_source(self):
        request = {
            "operation": "describe_camera_options",
            "runtime": {
                "working_directory": os.getcwd(),
                "live_camera_width": 960,
                "live_camera_height": 540,
                "live_camera_fps": 30,
                "live_camera_fourcc": "MJPG",
                "environment": {
                    "AEROBEAT_CAMERA_ROOT": "/dev",
                    "AEROBEAT_CAMERA_PATTERN": "video0",
                },
            },
            "source": {"kind": "live_camera", "camera_id": "/dev/video0"},
        }
        stdout = """
[0]: 'YUYV' (YUYV 4:2:2)
	Size: Discrete 640x480
		Interval: Discrete 0.067s (15.000 fps)
[1]: 'MJPG' (Motion-JPEG)
	Size: Discrete 1280x720
		Interval: Discrete 0.033s (30.000 fps)
	Size: Discrete 960x540
		Interval: Discrete 0.033s (30.000 fps)
"""
        with mock.patch.object(probe.platform, "system", return_value="Linux"):
            with mock.patch.object(probe.subprocess, "run", return_value=_FakeCompletedProcess(stdout=stdout)):
                result = probe._success_response(request)
        self.assertTrue(result["ok"])
        self.assertEqual(result["camera_options"]["reported_source"], "reported_v4l2")
        self.assertEqual(result["camera_options"]["probe_strategy"], "reported_v4l2_ranked_shortlist")
        self.assertEqual(result["camera_options"]["reported_options"][0]["fps"], 30.0)
        self.assertEqual(result["camera_options"]["reported_options"][0]["fourcc"], "MJPG")
        self.assertEqual(result["health"]["capture_mode"]["reported_options"][0]["fourcc"], "MJPG")

    def test_sample_once_chooses_higher_fps_candidate_over_closer_resolution_when_v4l2_reports_choices(self):
        request = {
            "operation": "startup",
            "runtime": {
                "working_directory": os.getcwd(),
                "live_camera_width": 960,
                "live_camera_height": 540,
                "live_camera_fps": 30,
                "live_camera_fourcc": "MJPG",
                "pose_landmarker_model_path": "unused-for-fake-legacy-path",
                "environment": {
                    "AEROBEAT_CAMERA_ROOT": "/dev",
                    "AEROBEAT_CAMERA_PATTERN": "video0",
                },
            },
            "tracking": {"quality": "full", "overlay_mode": "full"},
            "source": {"kind": "live_camera", "camera_id": "/dev/video0"},
            "preview": {"enabled": True},
        }
        stdout = """
[0]: 'MJPG' (Motion-JPEG)
	Size: Discrete 960x540
		Interval: Discrete 0.067s (15.000 fps)
	Size: Discrete 1280x720
		Interval: Discrete 0.033s (30.000 fps)
"""
        _FakeNegotiationCv2.PROFILES = {
            ("/dev/video0", "CAP_V4L2"): {"opened": True, "width": 1280, "height": 720, "fps": 30.0, "fourcc": "MJPG"},
        }
        with mock.patch.object(probe.platform, "system", return_value="Linux"):
            with mock.patch.object(probe.subprocess, "run", return_value=_FakeCompletedProcess(stdout=stdout)):
                with mock.patch.dict("sys.modules", {"cv2": _FakeNegotiationCv2, **_fake_legacy_mediapipe_module()}, clear=False):
                    result = probe._sample_once(request, sample_index=0, dynamic_timestamp=False)
        self.assertTrue(result["ok"])
        capture_mode = result["health"]["capture_mode"]
        self.assertEqual(capture_mode["reported_source"], "reported_v4l2")
        self.assertEqual(capture_mode["selected"]["width"], 1280)
        self.assertEqual(capture_mode["selected"]["height"], 720)
        self.assertEqual(capture_mode["selected"]["fps"], 30.0)
        self.assertEqual(capture_mode["actual"]["fps"], 30.0)
        self.assertEqual(result["camera_options"]["reported_options"][0]["width"], 1280)

    def test_describe_camera_options_falls_back_to_bounded_probe_sweep_when_v4l2_is_unavailable(self):
        request = {
            "operation": "describe_camera_options",
            "runtime": {
                "working_directory": os.getcwd(),
                "live_camera_width": 960,
                "live_camera_height": 540,
                "live_camera_fps": 30,
                "live_camera_fourcc": "MJPG",
                "environment": {
                    "AEROBEAT_CAMERA_ROOT": "/dev",
                    "AEROBEAT_CAMERA_PATTERN": "video0",
                },
            },
            "source": {"kind": "live_camera", "camera_id": "/dev/video0"},
        }
        with mock.patch.object(probe.platform, "system", return_value="Linux"):
            with mock.patch.object(probe.subprocess, "run", side_effect=FileNotFoundError()):
                result = probe._success_response(request)
        self.assertTrue(result["ok"])
        self.assertEqual(result["camera_options"]["reported_source"], "fallback_probe_sweep")
        self.assertEqual(result["camera_options"]["probe_strategy"], "bounded_probe_sweep")
        self.assertEqual(result["camera_options"]["reported_options"], [])
        self.assertGreater(len(result["camera_options"]["notes"]), 0)


if __name__ == "__main__":
    unittest.main()

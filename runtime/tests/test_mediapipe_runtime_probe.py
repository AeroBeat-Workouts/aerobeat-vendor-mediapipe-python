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


class _FakePreviewWriteCv2(_FakeCv2):
    IMWRITE_JPEG_QUALITY = 1
    write_calls = []

    @classmethod
    def reset(cls):
        cls.write_calls = []

    @classmethod
    def imwrite(cls, path, _frame, params=None):
        cls.write_calls.append((path, list(params or [])))
        Path(path).write_bytes(b"fake-jpeg")
        return True


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


class _FakeReplayCapture:
    def __init__(self, frames, fps=30.0):
        self.frames = list(frames)
        self.fps = float(fps)
        self.frame_count = len(self.frames)
        self.cursor = 0
        self.last_pos_msec = 0.0
        self.released = False
        self.set_calls = []

    def isOpened(self):
        return True

    def read(self):
        if self.cursor >= len(self.frames):
            self.last_pos_msec = (len(self.frames) / self.fps) * 1000.0 if self.fps > 0.0 else 0.0
            return (False, None)
        frame = self.frames[self.cursor]
        self.cursor += 1
        self.last_pos_msec = (self.cursor / self.fps) * 1000.0 if self.fps > 0.0 else 0.0
        return (True, frame)

    def release(self):
        self.released = True

    def set(self, prop, value):
        self.set_calls.append((prop, value))
        if prop == _FakeReplayCv2.CAP_PROP_POS_MSEC:
            if self.fps > 0.0:
                self.cursor = max(0, min(int(round((float(value) / 1000.0) * self.fps)), len(self.frames)))
            else:
                self.cursor = 0
            self.last_pos_msec = float(value)
            return True
        return False

    def get(self, prop):
        if prop == _FakeReplayCv2.CAP_PROP_FPS:
            return self.fps
        if prop == _FakeReplayCv2.CAP_PROP_FRAME_COUNT:
            return float(self.frame_count)
        if prop == _FakeReplayCv2.CAP_PROP_POS_MSEC:
            return float(self.last_pos_msec)
        return 0.0


class _FakeReplayCv2(_FakeCv2):
    CAP_PROP_FPS = 5
    CAP_PROP_FRAME_COUNT = 7
    CAP_PROP_POS_MSEC = 8
    FRAMES = []
    FPS = 30.0
    LAST_CAPTURE = None

    @classmethod
    def VideoCapture(cls, _source, backend=None):
        del backend
        cls.LAST_CAPTURE = _FakeReplayCapture(cls.FRAMES, fps=cls.FPS)
        return cls.LAST_CAPTURE


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


class _FakeHandLandmarkerOptions:
    def __init__(self, base_options, running_mode, num_hands=2, **_kwargs):
        self.base_options = base_options
        self.running_mode = running_mode
        self.num_hands = num_hands


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


class _FakeLegacyClassification:
    def __init__(self, label, score):
        self.label = label
        self.score = score


class _FakeLegacyHands:
    def __init__(self, static_image_mode=True, max_num_hands=2):
        self.static_image_mode = static_image_mode
        self.max_num_hands = max_num_hands

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def process(self, frame_rgb):
        return types.SimpleNamespace(
            multi_hand_landmarks=[
                types.SimpleNamespace(landmark=[
                    _FakeLandmark(0.10, 0.20, -0.01, 1.0),
                    _FakeLandmark(0.20, 0.30, -0.02, 1.0),
                    _FakeLandmark(0.30, 0.40, -0.03, 1.0),
                    _FakeLandmark(0.40, 0.50, -0.04, 1.0),
                    _FakeLandmark(0.50, 0.60, -0.05, 1.0),
                    _FakeLandmark(0.15, 0.25, -0.06, 1.0),
                    _FakeLandmark(0.25, 0.35, -0.07, 1.0),
                    _FakeLandmark(0.35, 0.45, -0.08, 1.0),
                    _FakeLandmark(0.45, 0.55, -0.09, 1.0),
                    _FakeLandmark(0.55, 0.65, -0.10, 1.0),
                    _FakeLandmark(0.12, 0.22, -0.11, 1.0),
                    _FakeLandmark(0.22, 0.32, -0.12, 1.0),
                    _FakeLandmark(0.32, 0.42, -0.13, 1.0),
                    _FakeLandmark(0.42, 0.52, -0.14, 1.0),
                    _FakeLandmark(0.52, 0.62, -0.15, 1.0),
                    _FakeLandmark(0.18, 0.28, -0.16, 1.0),
                    _FakeLandmark(0.28, 0.38, -0.17, 1.0),
                    _FakeLandmark(0.38, 0.48, -0.18, 1.0),
                    _FakeLandmark(0.48, 0.58, -0.19, 1.0),
                    _FakeLandmark(0.58, 0.68, -0.20, 1.0),
                    _FakeLandmark(0.60, 0.70, -0.21, 1.0),
                ])
            ],
            multi_handedness=[types.SimpleNamespace(classification=[_FakeLegacyClassification("Left", 0.91)])],
        )


class _FakeHandLandmarker:
    last_options = None

    def __init__(self, options):
        self.options = options

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def detect(self, image):
        return types.SimpleNamespace(
            hand_landmarks=[[
                _FakeLandmark(0.10, 0.20, -0.01, 1.0),
                _FakeLandmark(0.20, 0.30, -0.02, 1.0),
                _FakeLandmark(0.30, 0.40, -0.03, 1.0),
                _FakeLandmark(0.40, 0.50, -0.04, 1.0),
                _FakeLandmark(0.50, 0.60, -0.05, 1.0),
                _FakeLandmark(0.15, 0.25, -0.06, 1.0),
                _FakeLandmark(0.25, 0.35, -0.07, 1.0),
                _FakeLandmark(0.35, 0.45, -0.08, 1.0),
                _FakeLandmark(0.45, 0.55, -0.09, 1.0),
                _FakeLandmark(0.55, 0.65, -0.10, 1.0),
                _FakeLandmark(0.12, 0.22, -0.11, 1.0),
                _FakeLandmark(0.22, 0.32, -0.12, 1.0),
                _FakeLandmark(0.32, 0.42, -0.13, 1.0),
                _FakeLandmark(0.42, 0.52, -0.14, 1.0),
                _FakeLandmark(0.52, 0.62, -0.15, 1.0),
                _FakeLandmark(0.18, 0.28, -0.16, 1.0),
                _FakeLandmark(0.28, 0.38, -0.17, 1.0),
                _FakeLandmark(0.38, 0.48, -0.18, 1.0),
                _FakeLandmark(0.48, 0.58, -0.19, 1.0),
                _FakeLandmark(0.58, 0.68, -0.20, 1.0),
                _FakeLandmark(0.60, 0.70, -0.21, 1.0),
            ]],
            handedness=[[types.SimpleNamespace(category_name="Right", score=0.87)]],
        )

    @classmethod
    def create_from_options(cls, options):
        cls.last_options = options
        return cls(options)


def _fake_tasks_mediapipe_module():
    vision_module = types.SimpleNamespace(
        PoseLandmarker=_FakePoseLandmarker,
        PoseLandmarkerOptions=_FakePoseLandmarkerOptions,
        HandLandmarker=_FakeHandLandmarker,
        HandLandmarkerOptions=_FakeHandLandmarkerOptions,
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
    hands_namespace = types.SimpleNamespace(Hands=_FakeLegacyHands)
    solutions_namespace = types.SimpleNamespace(pose=pose_namespace, hands=hands_namespace)
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

    def test_tasks_hand_path_emits_lite_bbox_payload_when_model_is_available(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pose_model_path = Path(temp_dir) / "pose_landmarker_lite.task"
            pose_model_path.write_bytes(b"pose-model")
            hand_model_path = Path(temp_dir) / "hand_landmarker.task"
            hand_model_path.write_bytes(b"hand-model")
            runtime = {
                "working_directory": temp_dir,
                "pose_landmarker_model_path": str(pose_model_path),
                "hand_landmarker_model_path": str(hand_model_path),
            }
            tracking = {"hands": {"enabled": True, "landmark_mode": "lite", "bbox": {"enabled": True}}}
            with mock.patch.dict("sys.modules", {"cv2": _FakeCv2, **_fake_tasks_mediapipe_module()}, clear=False):
                hands_result = probe._infer_hands_with_mediapipe(runtime, tracking, frame_bgr=[[0]])
                frame = probe._apply_hand_tracking({"timestamp_ms": 1}, tracking, runtime, hands_result)
            self.assertTrue(hands_result["ok"])
            self.assertEqual(hands_result["inference_backend"], "mediapipe_tasks_hand_landmarker")
            self.assertEqual(frame["vendor_hand_tracking"]["count"], 1)
            self.assertEqual(frame["vendor_hand_tracking"]["landmark_mode"], "lite")
            self.assertEqual(frame["hands"][0]["label"], "right")
            self.assertEqual(frame["hands"][0]["landmark_count_before"], 21)
            self.assertEqual(frame["hands"][0]["landmark_count_after"], 11)
            self.assertEqual(frame["hands"][0]["bbox"]["landmark_mode"], "lite")
            self.assertAlmostEqual(frame["hands"][0]["bbox"]["x"], 0.10, places=6)
            self.assertAlmostEqual(frame["hands"][0]["bbox"]["y"], 0.20, places=6)
            self.assertAlmostEqual(frame["hands"][0]["bbox"]["width"], 0.50, places=6)
            self.assertAlmostEqual(frame["hands"][0]["bbox"]["height"], 0.50, places=6)
            self.assertAlmostEqual(frame["hands"][0]["bbox"]["area"], 0.25, places=6)
            self.assertEqual(_FakeHandLandmarker.last_options.base_options.model_asset_path, str(hand_model_path))

    def test_apply_hand_tracking_emits_ms_timing_contract(self):
        runtime = {
            "working_directory": tempfile.gettempdir(),
            "hand_tracking_enabled": True,
            "hand_max_stale_ms": 80,
            "hand_reacquire_stable_ms": 40,
        }
        tracking = {
            "hands": {
                "enabled": True,
                "landmark_mode": "lite",
                "bbox": {"enabled": True},
                "validity": {
                    "max_stale_ms": 80,
                    "reacquire_stable_ms": 40,
                },
            }
        }
        frame = probe._apply_hand_tracking({"timestamp_ms": 1}, tracking, runtime, {
            "ok": True,
            "hands": [],
            "available": False,
            "inference_backend": "fixture",
            "constraints": [],
        })
        self.assertEqual(frame["vendor_hand_tracking"]["max_stale_ms"], 80)
        self.assertEqual(frame["vendor_hand_tracking"]["reacquire_stable_ms"], 40)
        self.assertNotIn("max_stale_frames", frame["vendor_hand_tracking"])
        self.assertNotIn("reacquire_stable_frames", frame["vendor_hand_tracking"])

    def test_fixture_hands_are_normalized_with_full_landmark_mode(self):
        runtime = {"working_directory": tempfile.gettempdir()}
        tracking = {"hands": {"enabled": True, "landmark_mode": "full", "bbox": {"enabled": True}}}
        sampled = {
            "fixture_used": True,
            "raw_tracking_frame": {
                "timestamp_ms": 1,
                "source_kind": "live_camera",
                "source_id": "/dev/video0",
                "tracking_state": "idle",
                "frame_size": {"x": 640, "y": 480},
                "hands": [{
                    "index": 0,
                    "label": "Left",
                    "score": 0.9,
                    "landmarks": [
                        {"id": i, "x": 0.1 + (0.02 * i), "y": 0.2 + (0.01 * i), "z": -0.01 * i, "visibility": 1.0}
                        for i in range(21)
                    ],
                }],
            },
            "notes": [],
        }
        result = probe._infer_pose_landmarks(sampled, runtime, tracking=tracking, tracking_semantics={"quality": "optimized", "overlay_mode": "optimized", "point_mode": "reduced", "filter_enabled": True}, filter_state={})
        self.assertTrue(result["ok"])
        hand = result["raw_tracking_frame"]["hands"][0]
        self.assertEqual(hand["landmark_count_after"], 21)
        self.assertEqual(hand["bbox"]["landmark_mode"], "full")
        self.assertGreater(hand["bbox"]["area"], 0.0)
        self.assertEqual(result["raw_tracking_frame"]["vendor_hand_tracking"]["count"], 1)

    def test_pose_enabled_false_omits_pose_landmarks_but_surfaces_disabled_state(self):
        runtime = {"working_directory": tempfile.gettempdir()}
        tracking = {"pose": {"enabled": False}, "hands": {"enabled": False}}
        sampled = {
            "fixture_used": True,
            "raw_tracking_frame": {
                "timestamp_ms": 1,
                "frame_index": 0,
                "source_kind": "live_camera",
                "source_id": "/dev/video0",
                "tracking_state": "idle",
                "landmarks": [{"id": 0, "x": 0.25, "y": 0.50, "z": -0.1, "visibility": 0.9}],
            },
            "notes": [],
        }

        result = probe._infer_pose_landmarks(sampled, runtime, tracking=tracking, tracking_semantics={"quality": "optimized", "overlay_mode": "optimized", "point_mode": "reduced", "filter_enabled": True}, filter_state={})
        self.assertTrue(result["ok"])
        frame = result["raw_tracking_frame"]
        self.assertEqual(frame["tracking_state"], "disabled")
        self.assertNotIn("landmarks", frame)
        self.assertEqual(frame["vendor_pose_tracking"]["enabled"], False)
        self.assertEqual(frame["vendor_pose_tracking"]["inference_ran"], False)

    def test_pose_inference_interval_frames_carries_forward_last_pose_sample(self):
        runtime = {"working_directory": tempfile.gettempdir()}
        tracking = {"pose": {"enabled": True, "inference_interval_frames": 2}, "hands": {"enabled": False}}
        inference_session = {}
        first = probe._infer_pose_landmarks({
            "fixture_used": True,
            "raw_tracking_frame": {
                "timestamp_ms": 1,
                "frame_index": 0,
                "source_kind": "live_camera",
                "source_id": "/dev/video0",
                "tracking_state": "idle",
                "landmarks": [{"id": 0, "x": 0.25, "y": 0.50, "z": -0.1, "visibility": 0.9}],
            },
            "notes": [],
        }, runtime, tracking=tracking, inference_session=inference_session, tracking_semantics={"quality": "optimized", "overlay_mode": "optimized", "point_mode": "reduced", "filter_enabled": True}, filter_state={})
        self.assertTrue(first["ok"])
        first_frame = first["raw_tracking_frame"]
        self.assertEqual(first_frame["vendor_pose_tracking"]["inference_ran"], True)
        self.assertEqual(first_frame["vendor_pose_tracking"]["carried_forward"], False)

        second = probe._infer_pose_landmarks({
            "fixture_used": True,
            "raw_tracking_frame": {
                "timestamp_ms": 41,
                "frame_index": 1,
                "source_kind": "live_camera",
                "source_id": "/dev/video0",
                "tracking_state": "idle",
                "landmarks": [{"id": 0, "x": 0.75, "y": 0.20, "z": -0.5, "visibility": 0.7}],
            },
            "notes": [],
        }, runtime, tracking=tracking, inference_session=inference_session, tracking_semantics={"quality": "optimized", "overlay_mode": "optimized", "point_mode": "reduced", "filter_enabled": True}, filter_state={})
        self.assertTrue(second["ok"])
        second_frame = second["raw_tracking_frame"]
        self.assertEqual(second_frame["frame_index"], 1)
        self.assertEqual(second_frame["tracking_state"], "tracked")
        self.assertEqual(second_frame["landmarks"], first_frame["landmarks"])
        self.assertEqual(second_frame["vendor_pose_tracking"]["inference_ran"], False)
        self.assertEqual(second_frame["vendor_pose_tracking"]["carried_forward"], True)
        self.assertEqual(second_frame["vendor_pose_tracking"]["source_frame_index"], 0)

    def test_hand_inference_interval_frames_carries_forward_last_hand_sample(self):
        runtime = {"working_directory": tempfile.gettempdir()}
        tracking = {"pose": {"enabled": True, "inference_interval_frames": 1}, "hands": {"enabled": True, "landmark_mode": "lite", "inference_interval_frames": 2, "bbox": {"enabled": True}, "validity": {"max_stale_ms": 80, "reacquire_stable_ms": 0}}}
        inference_session = {}
        first = probe._infer_pose_landmarks({
            "fixture_used": True,
            "raw_tracking_frame": {
                "timestamp_ms": 1,
                "frame_index": 0,
                "source_kind": "live_camera",
                "source_id": "/dev/video0",
                "tracking_state": "idle",
                "hands": [{
                    "label": "Left",
                    "score": 0.91,
                    "landmarks": [{"id": 0, "x": 0.25, "y": 0.50, "z": -0.1, "visibility": 0.9}],
                    "bbox": {"x": 0.20, "y": 0.40, "width": 0.10, "height": 0.20},
                }],
            },
            "notes": [],
        }, runtime, tracking=tracking, inference_session=inference_session, tracking_semantics={"quality": "optimized", "overlay_mode": "optimized", "point_mode": "reduced", "filter_enabled": True}, filter_state={})
        self.assertTrue(first["ok"])
        first_frame = first["raw_tracking_frame"]
        self.assertEqual(first_frame["vendor_hand_tracking"]["inference_ran"], True)
        self.assertEqual(first_frame["vendor_hand_tracking"]["carried_forward"], False)
        self.assertEqual(first_frame["vendor_hand_tracking"]["source_frame_index"], 0)
        self.assertEqual(len(first_frame.get("hands", [])), 1)

        second = probe._infer_pose_landmarks({
            "fixture_used": True,
            "raw_tracking_frame": {
                "timestamp_ms": 41,
                "frame_index": 1,
                "source_kind": "live_camera",
                "source_id": "/dev/video0",
                "tracking_state": "idle",
                "hands": [{
                    "label": "Left",
                    "score": 0.33,
                    "landmarks": [{"id": 0, "x": 0.75, "y": 0.10, "z": -0.4, "visibility": 0.2}],
                    "bbox": {"x": 0.60, "y": 0.10, "width": 0.20, "height": 0.15},
                }],
            },
            "notes": [],
        }, runtime, tracking=tracking, inference_session=inference_session, tracking_semantics={"quality": "optimized", "overlay_mode": "optimized", "point_mode": "reduced", "filter_enabled": True}, filter_state={})
        self.assertTrue(second["ok"])
        second_frame = second["raw_tracking_frame"]
        self.assertEqual(second_frame["frame_index"], 1)
        self.assertEqual(second_frame["timestamp_ms"], 41)
        self.assertEqual(second_frame.get("hands"), first_frame.get("hands"))
        self.assertEqual(second_frame["vendor_hand_tracking"]["inference_ran"], False)
        self.assertEqual(second_frame["vendor_hand_tracking"]["carried_forward"], True)
        self.assertEqual(second_frame["vendor_hand_tracking"]["source_frame_index"], 0)

    def test_hand_landmarks_from_source_tolerates_none_numeric_fields(self):
        landmarks = probe._hand_landmarks_from_source([
            types.SimpleNamespace(x=None, y=0.25, z=None, visibility=None),
            types.SimpleNamespace(x=0.5, y=None, z=-0.75, visibility=0.6),
        ])
        self.assertEqual(len(landmarks), 2)
        self.assertEqual(landmarks[0]["id"], 0)
        self.assertEqual(landmarks[1]["id"], 1)
        self.assertEqual(landmarks[0]["x"], 0.0)
        self.assertEqual(landmarks[0]["y"], 0.25)
        self.assertEqual(landmarks[0]["z"], 0.0)
        self.assertEqual(landmarks[0]["visibility"], 1.0)
        self.assertEqual(landmarks[1]["x"], 0.5)
        self.assertEqual(landmarks[1]["y"], 0.0)
        self.assertEqual(landmarks[1]["z"], -0.75)
        self.assertEqual(landmarks[1]["visibility"], 0.6)

    def test_tasks_hand_path_surfaces_unavailable_when_model_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = {"working_directory": temp_dir}
            tracking = {"hands": {"enabled": True, "landmark_mode": "lite", "bbox": {"enabled": True}}}
            with mock.patch.dict("sys.modules", {"cv2": _FakeCv2, **_fake_tasks_mediapipe_module()}, clear=False):
                hands_result = probe._infer_hands_with_mediapipe(runtime, tracking, frame_bgr=[[0]])
                frame = probe._apply_hand_tracking({"timestamp_ms": 1}, tracking, runtime, hands_result)
            self.assertTrue(hands_result["ok"])
            self.assertFalse(frame["vendor_hand_tracking"]["available"])
            self.assertEqual(frame["vendor_hand_tracking"]["error_info"]["code"], "mediapipe_model_missing")
            self.assertFalse("hands" in frame)

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

    def test_sample_once_omits_non_json_frame_payload_from_response(self):
        request = {
            "operation": "startup",
            "runtime": {"working_directory": os.getcwd()},
            "source": {"kind": "live_camera", "camera_id": "/dev/video0"},
            "preview": {"enabled": True},
        }
        non_json_frame = object()
        with mock.patch.object(probe, "_select_source", return_value={
            "ok": True,
            "runtime": request["runtime"],
            "source": request["source"],
            "selected_camera_id": "/dev/video0",
            "cameras": [{"id": "/dev/video0", "label": "Camera 0"}],
            "health": {"notes": [], "status": "ok"},
        }):
            with mock.patch.object(probe, "_capture_live_camera_sample", return_value={
                "ok": True,
                "frame_bgr": non_json_frame,
                "raw_tracking_frame": {"source_kind": "live_camera", "source_id": "/dev/video0", "tracking_state": "idle"},
                "camera_options": {},
            }):
                with mock.patch.object(probe, "_infer_pose_landmarks", return_value={
                    "ok": True,
                    "notes": ["No landmarks for this sample."],
                    "raw_tracking_frame": {"source_kind": "live_camera", "source_id": "/dev/video0", "tracking_state": "idle"},
                }):
                    result = probe._sample_once(request, sample_index=0, dynamic_timestamp=False)
        self.assertTrue(result["ok"])
        self.assertNotIn("frame_bgr", result)
        self.assertEqual(json.loads(json.dumps(result))["selected_camera_id"], "/dev/video0")

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
                "source": {"kind": "video_file", "path": str(video_path), "loop": False},
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

    def test_run_continuous_video_file_session_loops_fixture_sequence_when_enabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = Path(temp_dir) / "fixture.mp4"
            video_path.write_bytes(b"fixture-video")
            session_dir = Path(temp_dir) / "session"
            request = {
                "operation": "startup",
                "runtime": {
                    "working_directory": temp_dir,
                    "tracking_max_fps": 0,
                    "state_update_max_fps": 0,
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
                "source": {"kind": "video_file", "path": str(video_path), "loop": True},
                "preview": {"enabled": False},
            }
            snapshots = []

            def _fake_infer(sampled, _runtime, **_kwargs):
                return {
                    "ok": True,
                    "notes": ["fixture replay frame"],
                    "raw_tracking_frame": dict(sampled.get("raw_tracking_frame", {})),
                }

            def _capture_snapshot(path, payload):
                snapshots.append(payload)
                if payload.get("health", {}).get("tracking_active") and payload.get("health", {}).get("loop_iteration", -1) >= 2:
                    Path(probe._session_stop_path(path)).write_text("stop")
                probe._write_json_atomic(probe._session_snapshot_path(path), payload)

            with mock.patch.object(probe, "_infer_pose_landmarks", side_effect=_fake_infer):
                with mock.patch.object(probe, "_write_session_snapshot", side_effect=_capture_snapshot):
                    with mock.patch.object(probe.time, "sleep", return_value=None):
                        exit_code = probe._run_continuous_session(request, str(session_dir))

            self.assertEqual(exit_code, 0)
            tracking_iterations = [
                payload["health"]["loop_iteration"]
                for payload in snapshots
                if payload.get("health", {}).get("tracking_active")
            ]
            self.assertEqual(tracking_iterations[:3], [0, 1, 2])
            self.assertGreaterEqual(len(tracking_iterations), 3)

    def test_run_continuous_video_file_session_rewinds_opencv_capture_when_loop_enabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = Path(temp_dir) / "fixture.mp4"
            video_path.write_bytes(b"fixture-video")
            session_dir = Path(temp_dir) / "session"
            request = {
                "operation": "startup",
                "runtime": {
                    "working_directory": temp_dir,
                    "tracking_max_fps": 0,
                    "state_update_max_fps": 0,
                },
                "source": {"kind": "video_file", "path": str(video_path), "loop": True},
                "preview": {"enabled": False},
            }
            snapshots = []
            _FakeReplayCv2.FRAMES = [
                types.SimpleNamespace(shape=(360, 640, 3)),
                types.SimpleNamespace(shape=(360, 640, 3)),
            ]
            _FakeReplayCv2.FPS = 30.0
            _FakeReplayCv2.LAST_CAPTURE = None

            def _fake_infer(sampled, _runtime, **_kwargs):
                return {
                    "ok": True,
                    "notes": ["opencv replay frame"],
                    "raw_tracking_frame": dict(sampled.get("raw_tracking_frame", {})),
                }

            def _capture_snapshot(path, payload):
                snapshots.append(payload)
                if payload.get("health", {}).get("tracking_active") and payload.get("health", {}).get("loop_iteration", -1) >= 2:
                    Path(probe._session_stop_path(path)).write_text("stop")
                probe._write_json_atomic(probe._session_snapshot_path(path), payload)

            with mock.patch.dict("sys.modules", {"cv2": _FakeReplayCv2}, clear=False):
                with mock.patch.object(probe, "_create_inference_session", return_value={"ok": True}):
                    with mock.patch.object(probe, "_close_inference_session", return_value=None):
                        with mock.patch.object(probe, "_infer_pose_landmarks", side_effect=_fake_infer):
                            with mock.patch.object(probe, "_write_session_snapshot", side_effect=_capture_snapshot):
                                with mock.patch.object(probe.time, "sleep", return_value=None):
                                    exit_code = probe._run_continuous_session(request, str(session_dir))

            self.assertEqual(exit_code, 0)
            self.assertIsNotNone(_FakeReplayCv2.LAST_CAPTURE)
            self.assertTrue(any(prop == _FakeReplayCv2.CAP_PROP_POS_MSEC and value == 0.0 for prop, value in _FakeReplayCv2.LAST_CAPTURE.set_calls))
            tracking_iterations = [
                payload["health"]["loop_iteration"]
                for payload in snapshots
                if payload.get("health", {}).get("tracking_active")
            ]
            self.assertEqual(tracking_iterations[:3], [0, 1, 2])

    def test_run_continuous_video_file_session_resume_start_rewinds_to_original_loop_origin(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = Path(temp_dir) / "fixture.mp4"
            video_path.write_bytes(b"fixture-video")
            session_dir = Path(temp_dir) / "session"
            request = {
                "operation": "startup",
                "runtime": {
                    "working_directory": temp_dir,
                    "tracking_max_fps": 0,
                    "state_update_max_fps": 0,
                },
                "source": {
                    "kind": "video_file",
                    "path": str(video_path),
                    "loop": True,
                    "start_time_sec": 1.0,
                    "loop_start_time_sec": 0.0,
                },
                "preview": {"enabled": False},
            }
            snapshots = []
            _FakeReplayCv2.FRAMES = [
                types.SimpleNamespace(shape=(360, 640, 3)),
                types.SimpleNamespace(shape=(360, 640, 3)),
                types.SimpleNamespace(shape=(360, 640, 3)),
            ]
            _FakeReplayCv2.FPS = 2.0
            _FakeReplayCv2.LAST_CAPTURE = None

            def _fake_infer(sampled, _runtime, **_kwargs):
                return {
                    "ok": True,
                    "notes": ["opencv replay frame"],
                    "raw_tracking_frame": dict(sampled.get("raw_tracking_frame", {})),
                }

            def _capture_snapshot(path, payload):
                snapshots.append(payload)
                if payload.get("health", {}).get("tracking_active") and payload.get("health", {}).get("loop_iteration", -1) >= 2:
                    Path(probe._session_stop_path(path)).write_text("stop")
                probe._write_json_atomic(probe._session_snapshot_path(path), payload)

            with mock.patch.dict("sys.modules", {"cv2": _FakeReplayCv2}, clear=False):
                with mock.patch.object(probe, "_create_inference_session", return_value={"ok": True}):
                    with mock.patch.object(probe, "_close_inference_session", return_value=None):
                        with mock.patch.object(probe, "_infer_pose_landmarks", side_effect=_fake_infer):
                            with mock.patch.object(probe, "_write_session_snapshot", side_effect=_capture_snapshot):
                                with mock.patch.object(probe.time, "sleep", return_value=None):
                                    exit_code = probe._run_continuous_session(request, str(session_dir))

            self.assertEqual(exit_code, 0)
            self.assertIsNotNone(_FakeReplayCv2.LAST_CAPTURE)
            self.assertTrue(any(prop == _FakeReplayCv2.CAP_PROP_POS_MSEC and value == 1000.0 for prop, value in _FakeReplayCv2.LAST_CAPTURE.set_calls))
            self.assertTrue(any(prop == _FakeReplayCv2.CAP_PROP_POS_MSEC and value == 0.0 for prop, value in _FakeReplayCv2.LAST_CAPTURE.set_calls))
            tracking_times = [
                payload["playback_status"]["current_time_sec"]
                for payload in snapshots
                if payload.get("health", {}).get("tracking_active")
            ]
            self.assertEqual(tracking_times[:3], [1.5, 0.5, 1.0])

    def test_run_continuous_video_file_session_stops_at_opencv_eof_when_loop_disabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = Path(temp_dir) / "fixture.mp4"
            video_path.write_bytes(b"fixture-video")
            session_dir = Path(temp_dir) / "session"
            request = {
                "operation": "startup",
                "runtime": {
                    "working_directory": temp_dir,
                    "tracking_max_fps": 60,
                    "state_update_max_fps": 60,
                },
                "source": {"kind": "video_file", "path": str(video_path), "loop": False},
                "preview": {"enabled": False},
            }
            _FakeReplayCv2.FRAMES = [types.SimpleNamespace(shape=(360, 640, 3))]
            _FakeReplayCv2.FPS = 30.0
            _FakeReplayCv2.LAST_CAPTURE = None

            def _fake_infer(sampled, _runtime, **_kwargs):
                return {
                    "ok": True,
                    "notes": ["opencv replay frame"],
                    "raw_tracking_frame": dict(sampled.get("raw_tracking_frame", {})),
                }

            with mock.patch.dict("sys.modules", {"cv2": _FakeReplayCv2}, clear=False):
                with mock.patch.object(probe, "_create_inference_session", return_value={"ok": True}):
                    with mock.patch.object(probe, "_close_inference_session", return_value=None):
                        with mock.patch.object(probe, "_infer_pose_landmarks", side_effect=_fake_infer):
                            with mock.patch.object(probe.time, "sleep", return_value=None):
                                exit_code = probe._run_continuous_session(request, str(session_dir))

            self.assertEqual(exit_code, 0)
            snapshot = json.loads((session_dir / "runtime_snapshot.json").read_text())
            self.assertEqual(snapshot["playback_status"]["state"], "ended")
            self.assertFalse(any(prop == _FakeReplayCv2.CAP_PROP_POS_MSEC for prop, _value in _FakeReplayCv2.LAST_CAPTURE.set_calls))

    def test_run_continuous_video_file_session_uses_capture_source_timestamp_for_raw_replay_frame(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = Path(temp_dir) / "fixture.mp4"
            video_path.write_bytes(b"fixture-video")
            session_dir = Path(temp_dir) / "session"
            request = {
                "operation": "startup",
                "runtime": {
                    "working_directory": temp_dir,
                    "tracking_max_fps": 60,
                    "state_update_max_fps": 60,
                },
                "source": {"kind": "video_file", "path": str(video_path), "loop": False},
                "preview": {"enabled": False},
            }
            _FakeReplayCv2.FRAMES = [types.SimpleNamespace(shape=(360, 640, 3))]
            _FakeReplayCv2.FPS = 2.0
            _FakeReplayCv2.LAST_CAPTURE = None
            snapshots = []

            def _fake_infer(sampled, _runtime, **_kwargs):
                return {
                    "ok": True,
                    "notes": ["opencv replay frame"],
                    "raw_tracking_frame": dict(sampled.get("raw_tracking_frame", {})),
                }

            def _capture_snapshot(path, payload):
                snapshots.append(payload)
                probe._write_json_atomic(probe._session_snapshot_path(path), payload)

            with mock.patch.dict("sys.modules", {"cv2": _FakeReplayCv2}, clear=False):
                with mock.patch.object(probe, "_create_inference_session", return_value={"ok": True}):
                    with mock.patch.object(probe, "_close_inference_session", return_value=None):
                        with mock.patch.object(probe, "_infer_pose_landmarks", side_effect=_fake_infer):
                            with mock.patch.object(probe, "_write_session_snapshot", side_effect=_capture_snapshot):
                                with mock.patch.object(probe.time, "sleep", return_value=None):
                                    exit_code = probe._run_continuous_session(request, str(session_dir))

            self.assertEqual(exit_code, 0)
            tracking_snapshots = [payload for payload in snapshots if payload.get("health", {}).get("tracking_active")]
            self.assertGreaterEqual(len(tracking_snapshots), 1)
            self.assertEqual(tracking_snapshots[0]["raw_tracking_frame"]["timestamp_ms"], 500)
            self.assertEqual(tracking_snapshots[0]["playback_status"]["current_time_sec"], 0.5)

    def test_run_continuous_video_file_session_uses_replay_source_time_for_state_write_cadence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = Path(temp_dir) / "fixture.mp4"
            video_path.write_bytes(b"fixture-video")
            session_dir = Path(temp_dir) / "session"
            request = {
                "operation": "startup",
                "runtime": {
                    "working_directory": temp_dir,
                    "tracking_max_fps": 120,
                    "state_update_max_fps": 30,
                },
                "source": {"kind": "video_file", "path": str(video_path), "loop": False},
                "preview": {"enabled": False},
            }
            _FakeReplayCv2.FRAMES = [
                types.SimpleNamespace(shape=(360, 640, 3)),
                types.SimpleNamespace(shape=(360, 640, 3)),
                types.SimpleNamespace(shape=(360, 640, 3)),
            ]
            _FakeReplayCv2.FPS = 30.0
            _FakeReplayCv2.LAST_CAPTURE = None
            snapshots = []

            def _fake_infer(sampled, _runtime, **_kwargs):
                return {
                    "ok": True,
                    "notes": ["opencv replay frame"],
                    "raw_tracking_frame": dict(sampled.get("raw_tracking_frame", {})),
                }

            def _capture_snapshot(path, payload):
                snapshots.append(payload)
                probe._write_json_atomic(probe._session_snapshot_path(path), payload)

            with mock.patch.dict("sys.modules", {"cv2": _FakeReplayCv2}, clear=False):
                with mock.patch.object(probe, "_create_inference_session", return_value={"ok": True}):
                    with mock.patch.object(probe, "_close_inference_session", return_value=None):
                        with mock.patch.object(probe, "_infer_pose_landmarks", side_effect=_fake_infer):
                            with mock.patch.object(probe, "_write_session_snapshot", side_effect=_capture_snapshot):
                                with mock.patch.object(probe.time, "monotonic", return_value=0.0):
                                    with mock.patch.object(probe.time, "sleep", return_value=None):
                                        exit_code = probe._run_continuous_session(request, str(session_dir))

            self.assertEqual(exit_code, 0)
            tracking_iterations = [
                payload["health"]["loop_iteration"]
                for payload in snapshots
                if payload.get("health", {}).get("tracking_active")
            ]
            self.assertEqual(tracking_iterations, [0, 1, 2])

    def test_preview_descriptor_uses_reduced_runtime_defaults_when_no_overrides_are_provided(self):
        descriptor = probe._preview_descriptor({}, {})
        self.assertTrue(descriptor["enabled"])
        self.assertEqual(descriptor["max_fps"], 10)
        self.assertEqual(descriptor["width"], 960)
        self.assertEqual(descriptor["height"], 540)
        self.assertEqual(descriptor["quality"], 75)

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

    def test_write_preview_frame_writes_temp_file_then_atomically_replaces_final_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            _FakePreviewWriteCv2.reset()
            frame = types.SimpleNamespace(shape=(240, 320, 3))
            preview = {"enabled": True, "width": 320, "height": 240, "quality": 77}

            with mock.patch.dict("sys.modules", {"cv2": _FakePreviewWriteCv2}, clear=False):
                descriptor = probe._write_preview_frame(temp_dir, frame, preview)

            preview_path = Path(temp_dir) / "preview_frame.jpg"
            preview_path_str = str(preview_path)
            self.assertEqual(descriptor["image_path"], preview_path_str)
            self.assertTrue(preview_path.exists())
            self.assertEqual(preview_path.read_bytes(), b"fake-jpeg")
            self.assertEqual(len(_FakePreviewWriteCv2.write_calls), 1)
            temp_write_path, temp_write_params = _FakePreviewWriteCv2.write_calls[0]
            self.assertNotEqual(temp_write_path, preview_path_str)
            self.assertTrue(temp_write_path.startswith(f"{preview_path_str[:-4]}."), temp_write_path)
            self.assertTrue(temp_write_path.endswith(".jpg"), temp_write_path)
            self.assertFalse(Path(temp_write_path).exists())
            self.assertEqual(temp_write_params, [int(_FakePreviewWriteCv2.IMWRITE_JPEG_QUALITY), 77])

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
            with mock.patch.object(probe, "_enumerate_cameras", return_value=[{"camera_id": "/dev/video0", "id": "/dev/video0", "label": "video0", "available": True}]):
                with mock.patch.object(probe, "_measure_live_camera_runtime_burst", return_value={"ok": True, "observed_fps": 30.0}):
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
            with mock.patch.object(probe, "_enumerate_cameras", return_value=[{"camera_id": "/dev/video0", "id": "/dev/video0", "label": "video0", "available": True}]):
                with mock.patch.object(probe, "_measure_live_camera_runtime_burst", return_value={"ok": True, "observed_fps": 30.0}):
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
        _FakeNegotiationCv2.PROFILES = {
            ("/dev/video0", "CAP_V4L2"): {"opened": True, "width": 1280, "height": 720, "fps": 30.0, "fourcc": "MJPG"},
        }
        with mock.patch.object(probe.platform, "system", return_value="Linux"):
            with mock.patch.object(probe, "_enumerate_cameras", return_value=[{"camera_id": "/dev/video0", "id": "/dev/video0", "label": "video0", "available": True}]):
                with mock.patch.object(probe.subprocess, "run", return_value=_FakeCompletedProcess(stdout=stdout)):
                    with mock.patch.dict("sys.modules", {"cv2": _FakeNegotiationCv2}, clear=False):
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
            with mock.patch.object(probe, "_enumerate_cameras", return_value=[{"camera_id": "/dev/video0", "id": "/dev/video0", "label": "video0", "available": True}]):
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
        _FakeNegotiationCv2.PROFILES = {
            ("/dev/video0", "CAP_V4L2"): {"opened": True, "width": 960, "height": 540, "fps": 30.0, "fourcc": "MJPG"},
            ("/dev/video0", "default"): {"opened": True, "width": 640, "height": 480, "fps": 15.0, "fourcc": "YUYV"},
        }
        with mock.patch.object(probe.platform, "system", return_value="Linux"):
            with mock.patch.object(probe, "_enumerate_cameras", return_value=[{"camera_id": "/dev/video0", "id": "/dev/video0", "label": "video0", "available": True}]):
                with mock.patch.object(probe.subprocess, "run", side_effect=FileNotFoundError()):
                    with mock.patch.object(probe, "_measure_live_camera_runtime_burst", return_value={"ok": True, "observed_fps": 15.0}):
                        with mock.patch.dict("sys.modules", {"cv2": _FakeNegotiationCv2}, clear=False):
                            result = probe._success_response(request)
        self.assertTrue(result["ok"])
        self.assertEqual(result["camera_options"]["reported_source"], "fallback_probe_sweep")
        self.assertEqual(result["camera_options"]["probe_strategy"], "bounded_probe_sweep")
        self.assertEqual(result["camera_options"]["reported_options"], [])
        self.assertGreater(len(result["camera_options"]["probed_options"]), 0)
        self.assertEqual(result["camera_options"]["selected"]["width"], 960)
        self.assertEqual(result["camera_options"]["selected"]["height"], 540)
        self.assertEqual(result["camera_options"]["selected"]["fps"], 30.0)
        self.assertEqual(result["camera_options"]["selected"]["fourcc"], "MJPG")
        self.assertEqual(result["camera_options"]["actual"]["width"], 960)
        self.assertEqual(result["camera_options"]["actual"]["height"], 540)
        self.assertEqual(result["camera_options"]["actual"]["fps"], 15.0)
        self.assertEqual(result["camera_options"]["actual"]["reported_fps"], 30.0)
        self.assertEqual(result["camera_options"]["actual"]["observed_fps"], 15.0)
        self.assertEqual(result["camera_options"]["actual"]["fourcc"], "MJPG")
        self.assertEqual(result["health"]["capture_mode"]["selected"]["width"], 960)
        self.assertEqual(result["health"]["capture_mode"]["actual"]["fps"], 15.0)
        self.assertGreater(len(result["camera_options"]["notes"]), 0)
        self.assertTrue(any("runtime observed ~15.000 FPS after OpenCV reported 30.000 FPS" in note for note in result["health"]["notes"]))

    def test_fallback_capture_session_prefers_higher_observed_runtime_fps_path(self):
        runtime = {
            "working_directory": os.getcwd(),
            "live_camera_width": 960,
            "live_camera_height": 540,
            "live_camera_fps": 30,
            "live_camera_fourcc": "MJPG",
            "environment": {
                "AEROBEAT_CAMERA_ROOT": "/dev",
                "AEROBEAT_CAMERA_PATTERN": "video0",
            },
        }
        _FakeNegotiationCv2.PROFILES = {
            ("/dev/video0", "CAP_V4L2"): {"opened": True, "width": 960, "height": 540, "fps": 30.0, "fourcc": "MJPG"},
            (0, "CAP_V4L2"): {"opened": True, "width": 960, "height": 540, "fps": 30.0, "fourcc": "MJPG"},
        }

        def _fake_runtime_burst(_camera_id, capture, source_label, sample_count=8):
            del sample_count
            observed = 22.5 if str(source_label).endswith("device index fallback 0") else 15.0
            width = int(capture.profile.get("width", 0))
            height = int(capture.profile.get("height", 0))
            return {
                "ok": True,
                "observed_fps": observed,
                "frame_bgr": types.SimpleNamespace(shape=(height, width, 3)),
                "width": width,
                "height": height,
                "sampled_frames": 8,
            }

        with mock.patch.object(probe.platform, "system", return_value="Linux"):
            with mock.patch.object(probe.subprocess, "run", side_effect=FileNotFoundError()):
                with mock.patch.object(probe, "_measure_live_camera_runtime_burst", side_effect=_fake_runtime_burst):
                    with mock.patch.dict("sys.modules", {"cv2": _FakeNegotiationCv2}, clear=False):
                        capture_session = probe._open_live_camera_capture_session("/dev/video0", runtime)
        self.assertTrue(capture_session["ok"])
        self.assertEqual(capture_session["source_label"], "CAP_V4L2/device index fallback 0")
        self.assertEqual(capture_session["capture_negotiation"]["selected"]["source_label"], "device index fallback 0")
        self.assertEqual(capture_session["capture_negotiation"]["selected"]["capture_source"], 0)
        self.assertEqual(capture_session["capture_negotiation"]["actual"]["fps"], 22.5)
        self.assertEqual(capture_session["capture_negotiation"]["actual"]["reported_fps"], 30.0)
        self.assertEqual(capture_session["capture_negotiation"]["actual"]["source_label"], "device index fallback 0")
        self.assertTrue(any("runtime observed ~22.500 FPS after OpenCV reported 30.000 FPS" in note for note in capture_session["notes"]))
        probe._close_live_camera_capture_session(capture_session)

    def test_arm_owner_orphan_protection_uses_linux_parent_death_signal(self):
        class _FakePrctl:
            def __init__(self):
                self.calls = []
                self.argtypes = None
                self.restype = None

            def __call__(self, option, signal_number, arg3, arg4, arg5):
                self.calls.append((option, signal_number, arg3, arg4, arg5))
                return 0

        fake_prctl = _FakePrctl()
        fake_libc = types.SimpleNamespace(prctl=fake_prctl)
        fake_ctypes = types.SimpleNamespace(CDLL=lambda *_args, **_kwargs: fake_libc, c_int=int, c_ulong=int, get_errno=lambda: 0)
        with mock.patch.object(probe, "_reset_runtime_shutdown_state") as reset_mock:
            with mock.patch.object(probe.os, "getppid", side_effect=[4242, 4242]):
                with mock.patch.object(probe.platform, "system", return_value="Linux"):
                    with mock.patch.object(probe.signal, "signal") as signal_mock:
                        with mock.patch.dict("sys.modules", {"ctypes": fake_ctypes}):
                            result = probe._arm_owner_orphan_protection()
        reset_mock.assert_called_once_with()
        signal_mock.assert_called_once_with(probe.signal.SIGTERM, probe._handle_runtime_shutdown_signal)
        self.assertTrue(result["ok"])
        self.assertEqual(result["parent_pid"], 4242)
        self.assertEqual(fake_prctl.calls, [(probe._PR_SET_PDEATHSIG, int(probe.signal.SIGTERM), 0, 0, 0)])

    def test_arm_owner_orphan_protection_requests_shutdown_if_parent_already_disappeared(self):
        class _FakePrctl:
            argtypes = None
            restype = None

            def __call__(self, option, signal_number, arg3, arg4, arg5):
                self.last_call = (option, signal_number, arg3, arg4, arg5)
                return 0

        fake_libc = types.SimpleNamespace(prctl=_FakePrctl())
        fake_ctypes = types.SimpleNamespace(CDLL=lambda *_args, **_kwargs: fake_libc, c_int=int, c_ulong=int, get_errno=lambda: 0)
        probe._reset_runtime_shutdown_state()
        with mock.patch.object(probe.os, "getppid", side_effect=[4242, 1]):
            with mock.patch.object(probe.platform, "system", return_value="Linux"):
                with mock.patch.object(probe.signal, "signal"):
                    with mock.patch.dict("sys.modules", {"ctypes": fake_ctypes}):
                        result = probe._arm_owner_orphan_protection()
        self.assertTrue(result["ok"])
        self.assertEqual(probe._runtime_shutdown_reason(), "owner_process_disappeared")

    def test_run_continuous_session_exits_cleanly_when_owner_disappears(self):
        request = {
            "runtime": {},
            "preview": {},
            "source": {"kind": "live_camera", "camera_id": "/dev/video0"},
        }
        selection = {
            "ok": True,
            "selected_camera_id": "/dev/video0",
            "selected": {"available": True, "label": "Fake Camera"},
            "cameras": [{"camera_id": "/dev/video0"}],
            "health": {"notes": []},
        }
        capture_session = {
            "ok": True,
            "fixture_only": True,
            "notes": ["Capture session opened."],
            "capture_negotiation": {"selected": {"width": 640, "height": 480}},
            "camera_options": {"reported_source": "fixture"},
        }
        snapshots = []
        with tempfile.TemporaryDirectory() as session_dir:
            with mock.patch.object(probe, "_arm_owner_orphan_protection", side_effect=lambda: probe._request_runtime_shutdown("owner_process_disappeared")):
                with mock.patch.object(probe, "_select_source", return_value=selection):
                    with mock.patch.object(probe, "_open_live_camera_capture_session", return_value=capture_session):
                        with mock.patch.object(probe, "_capture_live_camera_session_sample", side_effect=AssertionError("capture should not run after orphan shutdown request")):
                            with mock.patch.object(probe, "_enumerate_cameras", return_value=[{"camera_id": "/dev/video0"}]):
                                with mock.patch.object(probe, "_write_session_snapshot", side_effect=lambda _session_dir, payload: snapshots.append(payload)):
                                    exit_code = probe._run_continuous_session(request, session_dir)
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0]["health"]["status"], "idle")
        self.assertFalse(snapshots[0]["health"]["process_active"])
        self.assertIn("owner process disappeared unexpectedly", snapshots[0]["health"]["notes"][-1])


if __name__ == "__main__":
    unittest.main()

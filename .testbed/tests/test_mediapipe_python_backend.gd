extends GutTest

const MediaPipePythonCameraTrackingBackend = preload("res://../src/MediaPipePythonCameraTrackingBackend.gd")
const MediaPipePythonConfig = preload("res://../src/MediaPipePythonConfig.gd")
const MediaPipePythonCameraInventory = preload("res://../src/MediaPipePythonCameraInventory.gd")
const MediaPipePythonFrameMapper = preload("res://../src/MediaPipePythonFrameMapper.gd")
const MediaPipePythonRuntimeHealth = preload("res://../src/MediaPipePythonRuntimeHealth.gd")
const CameraTracking = preload("res://addons/aerobeat-tool-camera-tracking/src/CameraTracking.gd")

class FakeRuntimeBridge extends "res://../src/MediaPipePythonRuntimeBridge.gd":
	var startup_configs: Array = []
	var stop_calls: int = 0
	var cameras := [
		"/dev/video0",
		{
			"id": "/dev/video1",
			"label": "Wide Camera",
			"available": false,
			"metadata": {"position": "front"}
		}
	]
	var preview_descriptor := {
		"enabled": true,
		"surface_mode": "attach",
		"attached": false,
		"surface_path": NodePath(),
		"flip_horizontal": true,
		"maintain_aspect_ratio": true
	}
	var raw_tracking_frame := {
		"timestamp_ms": 123,
		"source_kind": "live_camera",
		"source_id": "/dev/video0",
		"tracking_state": "tracked",
		"frame_size": {"x": 1280, "y": 720},
		"landmarks": [
			{"id": 0, "x": 0.25, "y": 0.4, "z": -0.15, "visibility": 0.95},
			{"id": 12, "x": 0.61, "y": 0.52, "z": -0.09, "visibility": 0.88}
		]
	}
	var health := MediaPipePythonRuntimeHealth.running({
		"camera_accessible": true,
		"tracking_active": true,
		"process_active": true
	})
	var playback_status := {
		"source": "",
		"state": "paused",
		"paused": true,
		"current_time_sec": 0.0,
		"duration_sec": 0.0,
		"progress": 0.0,
		"is_file_source": false,
	}

	func startup(vendor_config: Dictionary) -> Dictionary:
		startup_configs.append(vendor_config.duplicate(true))
		var snapshot_frame := raw_tracking_frame.duplicate(true)
		var source: Dictionary = vendor_config.get("source", {})
		var source_kind := str(source.get("kind", "live_camera"))
		if source_kind == "video_file":
			snapshot_frame["source_kind"] = "video_file"
			snapshot_frame["source_id"] = str(source.get("path", ""))
		else:
			snapshot_frame["source_kind"] = "live_camera"
			snapshot_frame["source_id"] = str(source.get("camera_id", snapshot_frame.get("source_id", "/dev/video0")))
		raw_tracking_frame = snapshot_frame.duplicate(true)
		var snapshot_playback_status := playback_status.duplicate(true)
		snapshot_playback_status["source"] = snapshot_frame.get("source_id", "")
		snapshot_playback_status["is_file_source"] = source_kind == "video_file"
		return {
			"ok": true,
			"health": health.duplicate(true),
			"cameras": cameras.duplicate(true),
			"preview_descriptor": preview_descriptor.duplicate(true),
			"raw_tracking_frame": snapshot_frame,
			"playback_status": snapshot_playback_status,
		}

	func shutdown() -> Dictionary:
		stop_calls += 1
		return {
			"ok": true,
			"health": MediaPipePythonRuntimeHealth.idle({
				"bridge_connected": true,
				"runtime_available": true
			})
		}

	func reconfigure(vendor_config: Dictionary) -> Dictionary:
		return startup(vendor_config)

	func list_cameras() -> Array:
		return cameras.duplicate(true)

	func poll_health() -> Dictionary:
		return health.duplicate(true)

	func poll_snapshot() -> Dictionary:
		return {
			"ok": true,
			"health": health.duplicate(true),
			"cameras": cameras.duplicate(true),
			"preview_descriptor": preview_descriptor.duplicate(true),
			"raw_tracking_frame": raw_tracking_frame.duplicate(true),
			"playback_status": playback_status.duplicate(true),
		}

func test_vendor_runtime_config_translation_keeps_public_shape_and_vendor_overrides() -> void:
	var vendor_config := MediaPipePythonConfig.make_vendor_runtime_config({
		"source": {
			"camera_id": "/dev/video0"
		},
		"tracking": {
			"min_visibility": 0.6,
			"hands": {
				"enabled": true,
				"landmark_mode": "full",
				"inference_interval_frames": 2,
				"bbox_recompute_interval_frames": 3,
				"bbox": {"enabled": true},
				"validity": {
					"max_stale_frames": 4,
					"reacquire_stable_frames": 5
				}
			}
		},
		"runtime": {
			"python_executable": "python3.13",
			"entrypoint": "scripts/run_backend.py",
			"model_complexity": 2,
			"pose_landmarker_model_path": "models/pose_landmarker_heavy.task",
			"hand_landmarker_model_path": "models/hand_landmarker.task"
		}
	})

	assert_eq(vendor_config["backend"], "mediapipe_python")
	assert_eq(vendor_config.get("source", {}).get("kind", ""), "live_camera")
	assert_eq(vendor_config["source"]["camera_id"], "/dev/video0")
	assert_eq(vendor_config["tracking"]["min_visibility"], 0.6)
	assert_eq(vendor_config["runtime"]["python_executable"], "python3.13")
	assert_eq(vendor_config["runtime"]["entrypoint"], "scripts/run_backend.py")
	assert_eq(int(vendor_config["runtime"]["model_complexity"]), 2)
	assert_eq(vendor_config["runtime"]["pose_landmarker_model_path"], "models/pose_landmarker_heavy.task")
	assert_eq(vendor_config["runtime"]["hand_landmarker_model_path"], "models/hand_landmarker.task")
	assert_true(bool(vendor_config["tracking"]["hands"].get("enabled", false)))
	assert_eq(String(vendor_config["tracking"]["hands"].get("landmark_mode", "")), "full")
	assert_eq(int(vendor_config["runtime"].get("hand_inference_interval_frames", 0)), 2)
	assert_eq(int(vendor_config["runtime"].get("hand_bbox_recompute_interval_frames", 0)), 3)
	assert_eq(int(vendor_config["runtime"].get("hand_max_stale_frames", 0)), 4)
	assert_eq(int(vendor_config["runtime"].get("hand_reacquire_stable_frames", 0)), 5)
	assert_true(bool(vendor_config["runtime"].get("hand_bbox_enabled", false)))
	assert_true(bool(vendor_config["runtime"].get("filter_enabled", false)))
	assert_false(bool(vendor_config["runtime"].get("no_filter", true)))
	assert_eq(MediaPipePythonConfig.get_required_model_filename(2), "pose_landmarker_heavy.task")

func test_vendor_runtime_config_normalizes_simple_overlay_and_legacy_no_filter_truthfully() -> void:
	var vendor_config := MediaPipePythonConfig.make_vendor_runtime_config({
		"tracking": {
			"quality": "simple",
			"overlay_mode": "simple"
		},
		"runtime": {
			"no_filter": true
		}
	})

	assert_eq(String(vendor_config["tracking"].get("quality", "")), "optimized")
	assert_eq(String(vendor_config["tracking"].get("overlay_mode", "")), "optimized")
	assert_false(bool(vendor_config["runtime"].get("filter_enabled", true)))
	assert_true(bool(vendor_config["runtime"].get("no_filter", false)))

func test_inventory_and_frame_mapper_normalize_vendor_payloads() -> void:
	var cameras := MediaPipePythonCameraInventory.normalize([
		"/dev/video0",
		{"id": "/dev/video1", "label": "USB Camera", "available": false}
	])
	assert_eq(cameras.size(), 2)
	assert_eq(cameras[0]["camera_id"], "/dev/video0")
	assert_eq(cameras[1]["label"], "USB Camera")
	assert_false(cameras[1]["available"])

	var frame := MediaPipePythonFrameMapper.map_raw_frame({
		"timestamp_ms": 42,
		"tracking_state": "tracked",
		"frame_size": {"x": 640, "y": 480},
		"landmarks": [
			{"id": 1, "x": 0.2, "y": 0.3, "z": -0.1, "visibility": 0.9}
		],
		"hands": [
			{
				"index": 0,
				"label": "left",
				"score": 0.9,
				"landmark_mode": "lite",
				"landmarks": [{"id": 0, "x": 0.1, "y": 0.2, "z": 0.0, "visibility": 1.0}],
				"bbox": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4, "area": 0.12}
			}
		],
		"vendor_hand_tracking": {
			"enabled": true,
			"landmark_mode": "lite",
			"count": 1
		}
	}, {
		"source": {"camera_id": "/dev/video0"},
		"preview": {"flip_horizontal": false}
	})
	assert_eq(frame["backend"], "mediapipe_python")
	assert_eq(frame.get("backend_request"), "camera_tracking_default")
	assert_eq(frame.get("backend_impl"), "mediapipe_python")
	assert_eq(frame["source_id"], "/dev/video0")
	assert_false(frame["preview_transform"]["flip_horizontal"])
	assert_eq(frame["tracking_state"], "tracked")
	assert_eq(frame["confidence"], 0.0)
	assert_eq(frame["landmarks"].size(), 1)
	assert_eq(int(frame["landmarks"][0]["id"]), 1)
	assert_eq(float(frame["landmarks"][0]["visibility"]), 0.9)
	assert_eq(frame["hands"].size(), 1)
	assert_eq(String(frame["hands"][0].get("label", "")), "left")
	assert_eq(float(frame["hands"][0].get("bbox", {}).get("area", 0.0)), 0.12)
	assert_true(frame.has("vendor_hand_tracking"))
	assert_eq(int(frame.get("vendor_hand_tracking", {}).get("count", 0)), 1)

func test_backend_bootstrap_shell_tracks_runtime_health_and_contract_shape() -> void:
	var bridge := FakeRuntimeBridge.new()
	var backend = MediaPipePythonCameraTrackingBackend.new()
	backend.set_runtime_bridge(bridge)

	var observed_states: Array = []
	var observed_preview_events: Array = []
	var observed_tracking_events: Array = []
	backend.state_changed.connect(func(state: String, detail: Dictionary) -> void:
		observed_states.append({"state": state, "detail": detail.duplicate(true)})
	)
	backend.preview_changed.connect(func(descriptor: Dictionary) -> void:
		observed_preview_events.append(descriptor.duplicate(true))
	)
	backend.tracking_updated.connect(func(frame: Dictionary) -> void:
		observed_tracking_events.append(frame.duplicate(true))
	)

	bridge.playback_status = {
		"source": "/dev/video0",
		"state": "playing",
		"paused": false,
		"current_time_sec": 1.25,
		"duration_sec": 5.0,
		"progress": 0.25,
		"is_file_source": false,
	}
	backend.start({
		"source": {"camera_id": "/dev/video0"},
		"runtime": {"entrypoint": "python/main.py"}
	})
	assert_eq(observed_states[0]["state"], CameraTracking.STATE_STARTING)
	assert_eq(backend.get_state()["state"], CameraTracking.STATE_RUNNING)
	assert_true(backend.get_state()["detail"][CameraTracking.DETAIL_BACKEND_READY])
	assert_true(backend.get_state()["detail"][CameraTracking.DETAIL_TRACKING_READY])
	assert_true(backend.get_runtime_health()["process_active"])
	assert_true(backend.get_runtime_health()["tracking_active"])
	assert_eq(backend.get_tracking_frame()["backend"], "mediapipe_python")
	assert_eq(backend.get_tracking_frame()["tracking_state"], "tracked")
	assert_eq(backend.get_tracking_frame()["frame_size"]["x"], 1280)
	assert_eq(backend.get_tracking_frame()["confidence"], 0.0)
	assert_eq(backend.get_tracking_frame()["landmarks"].size(), 2)
	assert_eq(backend.get_preview_descriptor()["backend"], "mediapipe_python")
	assert_eq(backend.get_playback_status().get("current_time_sec"), 1.25)
	assert_eq(backend.get_playback_status().get("progress"), 0.25)
	assert_eq(backend.list_cameras()[0]["camera_id"], "/dev/video0")
	assert_eq(bridge.startup_configs[0]["runtime"]["entrypoint"], "python/main.py")
	assert_eq(observed_preview_events.size(), 1)
	assert_eq(observed_tracking_events.size(), 1)

	bridge.raw_tracking_frame["timestamp_ms"] = 456
	bridge.raw_tracking_frame["tracking_state"] = "idle"
	bridge.preview_descriptor["image_path"] = "user://preview-frame.jpg"
	bridge.preview_descriptor["image_revision"] = 2
	bridge.playback_status["current_time_sec"] = 2.5
	bridge.playback_status["progress"] = 0.5
	var refreshed := backend.get_tracking_frame()
	assert_eq(int(refreshed["timestamp_ms"]), 456)
	assert_eq(refreshed["tracking_state"], "idle")
	assert_eq(backend.get_playback_status().get("current_time_sec"), 2.5)
	assert_eq(backend.get_playback_status().get("progress"), 0.5)
	assert_eq(observed_tracking_events.size(), 2)
	assert_eq(observed_preview_events.size(), 2)
	assert_eq(observed_preview_events.back()["image_path"], "user://preview-frame.jpg")
	assert_eq(int(observed_preview_events.back()["image_revision"]), 2)

	backend.change({
		"source": {"kind": "video_file", "path": "res://clips/demo.mp4"},
		"preview": {"enabled": false}
	})
	assert_eq(backend.get_state()["state"], CameraTracking.STATE_RUNNING)
	assert_eq(bridge.startup_configs.size(), 2)
	assert_eq(backend.get_tracking_frame()["source_kind"], "video_file")
	assert_eq(backend.get_tracking_frame()["source_id"], "res://clips/demo.mp4")

	backend.stop()
	assert_eq(backend.get_state()["state"], CameraTracking.STATE_IDLE)
	assert_eq(bridge.stop_calls, 1)

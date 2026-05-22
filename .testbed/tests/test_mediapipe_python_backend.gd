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
		"confidence": 0.91,
		"frame_size": {"x": 1280, "y": 720},
		"head_position": {"x": 0.25, "y": -0.1, "z": 0.5},
		"head_velocity": {"x": 0.0, "y": 0.0, "z": 0.0},
		"head_orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
		"landmarks": [{"name": "nose"}],
		"skeleton": {"spine": "ok"}
	}
	var health := MediaPipePythonRuntimeHealth.running({
		"camera_accessible": true,
		"tracking_active": true
	})

	func startup(vendor_config: Dictionary) -> Dictionary:
		startup_configs.append(vendor_config.duplicate(true))
		return {
			"ok": true,
			"health": health.duplicate(true),
			"cameras": cameras.duplicate(true),
			"preview_descriptor": preview_descriptor.duplicate(true),
			"raw_tracking_frame": raw_tracking_frame.duplicate(true)
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

func test_vendor_runtime_config_translation_keeps_public_shape_and_vendor_overrides() -> void:
	var vendor_config := MediaPipePythonConfig.make_vendor_runtime_config({
		"source": {
			"camera_id": "/dev/video0"
		},
		"tracking": {
			"min_visibility": 0.6
		},
		"runtime": {
			"python_executable": "python3.13",
			"entrypoint": "scripts/run_backend.py"
		}
	})

	assert_eq(vendor_config["backend"], "mediapipe_python")
	assert_eq(vendor_config["source"]["camera_id"], "/dev/video0")
	assert_eq(vendor_config["tracking"]["min_visibility"], 0.6)
	assert_eq(vendor_config["runtime"]["python_executable"], "python3.13")
	assert_eq(vendor_config["runtime"]["entrypoint"], "scripts/run_backend.py")

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
		"confidence": 0.5,
		"frame_size": {"x": 640, "y": 480}
	}, {
		"source": {"camera_id": "/dev/video0"},
		"preview": {"flip_horizontal": false}
	})
	assert_eq(frame["backend"], "mediapipe_python")
	assert_eq(frame["source_id"], "/dev/video0")
	assert_false(frame["preview_transform"]["flip_horizontal"])
	assert_eq(frame["tracking_state"], "tracked")

func test_backend_bootstrap_shell_tracks_runtime_health_and_contract_shape() -> void:
	var bridge := FakeRuntimeBridge.new()
	var backend = MediaPipePythonCameraTrackingBackend.new()
	backend.set_runtime_bridge(bridge)

	var observed_states: Array = []
	backend.state_changed.connect(func(state: String, detail: Dictionary) -> void:
		observed_states.append({"state": state, "detail": detail.duplicate(true)})
	)

	backend.start({
		"source": {"camera_id": "/dev/video0"},
		"runtime": {"entrypoint": "python/main.py"}
	})
	assert_eq(observed_states[0]["state"], CameraTracking.STATE_STARTING)
	assert_eq(backend.get_state()["state"], CameraTracking.STATE_RUNNING)
	assert_true(backend.get_state()["detail"][CameraTracking.DETAIL_BACKEND_READY])
	assert_true(backend.get_state()["detail"][CameraTracking.DETAIL_TRACKING_READY])
	assert_true(backend.get_runtime_health()["process_active"])
	assert_eq(backend.get_tracking_frame()["backend"], "mediapipe_python")
	assert_eq(backend.get_preview_descriptor()["backend"], "mediapipe_python")
	assert_eq(backend.list_cameras()[0]["camera_id"], "/dev/video0")
	assert_eq(bridge.startup_configs[0]["runtime"]["entrypoint"], "python/main.py")

	backend.change({
		"source": {"kind": "video_file", "path": "res://clips/demo.mp4"},
		"preview": {"enabled": false}
	})
	assert_eq(backend.get_state()["state"], CameraTracking.STATE_RUNNING)
	assert_eq(bridge.startup_configs.size(), 2)
	assert_eq(backend.get_tracking_frame()["source_kind"], "live_camera")

	backend.stop()
	assert_eq(backend.get_state()["state"], CameraTracking.STATE_IDLE)
	assert_eq(bridge.stop_calls, 1)

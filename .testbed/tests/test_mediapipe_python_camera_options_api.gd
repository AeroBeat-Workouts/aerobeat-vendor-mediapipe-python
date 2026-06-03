extends GutTest

const MediaPipePythonRuntimeBridge = preload("res://../src/MediaPipePythonRuntimeBridge.gd")
const MediaPipePythonCameraTrackingBackend = preload("res://../src/MediaPipePythonCameraTrackingBackend.gd")
const MediaPipePythonConfig = preload("res://../src/MediaPipePythonConfig.gd")
const MediaPipePythonRuntimeHealth = preload("res://../src/MediaPipePythonRuntimeHealth.gd")

class DescribeBridge extends MediaPipePythonRuntimeBridge:
	var last_operation := ""
	var last_vendor_config: Dictionary = {}
	var response := {
		"ok": true,
		"health": MediaPipePythonRuntimeHealth.idle({
			"notes": ["camera options ready"]
		}),
		"camera_options": {
			"selection_policy": "framerate_first_resolution_second_format_backend",
			"requested": {"width": 960, "height": 540, "fps": 30, "fourcc": "MJPG"},
			"reported_source": "reported_v4l2",
			"probe_strategy": "reported_v4l2_ranked_shortlist",
			"reported_options": [
				{"width": 1280, "height": 720, "fps": 30.0, "fourcc": "MJPG"}
			],
			"probed_options": [],
			"selected": {},
			"actual": {},
			"notes": ["reported options captured"]
		}
	}

	func _run_runtime_operation(operation: String, vendor_config: Dictionary) -> Dictionary:
		last_operation = operation
		last_vendor_config = vendor_config.duplicate(true)
		return response.duplicate(true)

class BackendBridge extends "res://../src/MediaPipePythonRuntimeBridge.gd":
	var describe_calls: Array = []
	var startup_snapshot := {
		"ok": true,
		"health": MediaPipePythonRuntimeHealth.running({
			"camera_accessible": true,
			"tracking_active": true,
			"process_active": true
		}),
		"cameras": ["/dev/video0"],
		"preview_descriptor": {"enabled": true, "backend": "mediapipe_python"},
		"raw_tracking_frame": {
			"timestamp_ms": 1,
			"source_kind": "live_camera",
			"source_id": "/dev/video0",
			"tracking_state": "idle",
			"frame_size": {"x": 640, "y": 480}
		},
		"camera_options": {
			"selection_policy": "framerate_first_resolution_second_format_backend",
			"requested": {"width": 960, "height": 540, "fps": 30, "fourcc": "MJPG"},
			"reported_source": "reported_v4l2",
			"probe_strategy": "reported_v4l2_ranked_shortlist",
			"reported_options": [
				{"width": 1280, "height": 720, "fps": 30.0, "fourcc": "MJPG"}
			],
			"probed_options": [],
			"selected": {"width": 1280, "height": 720, "fps": 30.0, "fourcc": "MJPG"},
			"actual": {"width": 1280, "height": 720, "fps": 30.0, "fourcc": "MJPG"},
			"notes": []
		}
	}

	func startup(_vendor_config: Dictionary) -> Dictionary:
		return startup_snapshot.duplicate(true)

	func shutdown() -> Dictionary:
		return {"ok": true, "health": MediaPipePythonRuntimeHealth.idle()}

	func reconfigure(vendor_config: Dictionary) -> Dictionary:
		return startup(vendor_config)

	func list_cameras() -> Array:
		return ["/dev/video0"]

	func poll_snapshot() -> Dictionary:
		return startup_snapshot.duplicate(true)

	func describe_camera_options(camera_id: String = "") -> Dictionary:
		describe_calls.append(camera_id)
		var snapshot := startup_snapshot.duplicate(true)
		snapshot["camera_options"]["requested"]["camera_id"] = camera_id
		return snapshot

func test_runtime_bridge_describe_camera_options_routes_through_runtime_operation() -> void:
	var bridge := DescribeBridge.new()
	var snapshot := bridge.describe_camera_options("/dev/video2")
	assert_true(snapshot["ok"])
	assert_eq(bridge.last_operation, "describe_camera_options")
	assert_eq(String(bridge.last_vendor_config.get("source", {}).get("camera_id", "")), "/dev/video2")
	assert_eq(snapshot["camera_options"]["reported_source"], "reported_v4l2")

func test_backend_exposes_camera_options_from_runtime_bridge() -> void:
	var bridge := BackendBridge.new()
	var backend := MediaPipePythonCameraTrackingBackend.new()
	backend.set_runtime_bridge(bridge)
	backend.start({
		"source": {"camera_id": "/dev/video0"}
	})
	var cached := backend.get_camera_options()
	assert_eq(cached["reported_source"], "reported_v4l2")
	assert_eq(cached["selected"]["width"], 1280)
	var explicit := backend.get_camera_options("/dev/video2")
	assert_eq(explicit["requested"]["camera_id"], "/dev/video2")
	assert_eq(bridge.describe_calls[-1], "/dev/video2")

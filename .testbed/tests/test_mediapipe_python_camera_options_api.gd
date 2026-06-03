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

class RunningSnapshotBridge extends MediaPipePythonRuntimeBridge:
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
			"reported_source": "fallback_probe_sweep",
			"probe_strategy": "bounded_probe_sweep",
			"reported_options": [],
			"probed_options": [
				{"width": 960, "height": 540, "fps": 30.0, "fourcc": "MJPG"}
			],
			"selected": {"width": 960, "height": 540, "fps": 30.0, "fourcc": "MJPG"},
			"actual": {"width": 960, "height": 540, "fps": 15.0, "fourcc": "MJPG"},
			"notes": ["running snapshot includes camera options"]
		}
	}
	var runtime_snapshot := {
		"ok": true,
		"health": MediaPipePythonRuntimeHealth.idle({
			"camera_accessible": true,
			"tracking_active": true,
			"process_active": false
		}),
		"cameras": ["/dev/video0"],
		"preview_descriptor": {"enabled": true, "backend": "mediapipe_python"},
		"raw_tracking_frame": {
			"timestamp_ms": 2,
			"source_kind": "live_camera",
			"source_id": "/dev/video0",
			"tracking_state": "idle",
			"frame_size": {"x": 640, "y": 480}
		},
		"camera_options": {
			"selection_policy": "framerate_first_resolution_second_format_backend",
			"requested": {"width": 960, "height": 540, "fps": 30, "fourcc": "MJPG"},
			"reported_source": "fallback_probe_sweep",
			"probe_strategy": "bounded_probe_sweep",
			"reported_options": [],
			"probed_options": [
				{"width": 960, "height": 540, "fps": 30.0, "fourcc": "MJPG"}
			],
			"selected": {"width": 960, "height": 540, "fps": 30.0, "fourcc": "MJPG"},
			"actual": {"width": 960, "height": 540, "fps": 15.0, "fourcc": "MJPG"},
			"notes": ["running snapshot includes camera options"]
		}
	}

	func startup(_vendor_config: Dictionary) -> Dictionary:
		_last_vendor_config = MediaPipePythonConfig.vendor_defaults()
		_sync_from_snapshot(startup_snapshot)
		_session_dir = "user://running-snapshot-bridge"
		_session_pid = OS.create_process("/bin/sleep", PackedStringArray(["60"]))
		return startup_snapshot.duplicate(true)

	func shutdown() -> Dictionary:
		if _session_pid > 0 and OS.is_process_running(_session_pid):
			OS.kill(_session_pid)
		_session_pid = -1
		_session_dir = ""
		return {"ok": true, "health": MediaPipePythonRuntimeHealth.idle()}

	func _read_session_snapshot(_session_dir_path: String) -> Dictionary:
		return runtime_snapshot.duplicate(true)

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

func test_runtime_bridge_running_poll_snapshot_returns_camera_options() -> void:
	var bridge := RunningSnapshotBridge.new()
	var startup := bridge.startup({})
	assert_eq(startup["camera_options"]["selected"]["width"], 960)
	var running := bridge.poll_snapshot()
	assert_true(running.has("camera_options"))
	assert_eq(running["camera_options"]["reported_source"], "fallback_probe_sweep")
	assert_eq(running["camera_options"]["selected"]["width"], 960)
	assert_eq(running["camera_options"]["actual"]["fps"], 15.0)
	bridge.shutdown()

func test_backend_running_snapshot_refresh_does_not_clobber_camera_options_cache() -> void:
	var bridge := RunningSnapshotBridge.new()
	var backend := MediaPipePythonCameraTrackingBackend.new()
	backend.set_runtime_bridge(bridge)
	backend.start({
		"source": {"camera_id": "/dev/video0"}
	})
	var before_refresh := backend.get_camera_options()
	assert_eq(before_refresh["selected"]["width"], 960)
	var frame := backend.get_tracking_frame()
	assert_eq(frame["source_id"], "/dev/video0")
	var after_refresh := backend.get_camera_options()
	assert_eq(after_refresh["reported_source"], "fallback_probe_sweep")
	assert_eq(after_refresh["selected"]["width"], 960)
	assert_eq(after_refresh["actual"]["fps"], 15.0)
	backend.stop()

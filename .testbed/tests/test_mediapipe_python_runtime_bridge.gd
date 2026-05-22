extends GutTest

const MediaPipePythonConfig = preload("res://../src/MediaPipePythonConfig.gd")
const MediaPipePythonRuntimeBridge = preload("res://../src/MediaPipePythonRuntimeBridge.gd")
const MediaPipePythonRuntimeHealth = preload("res://../src/MediaPipePythonRuntimeHealth.gd")

var _fixture_root := ""

func before_each() -> void:
	_fixture_root = ProjectSettings.globalize_path("user://runtime-bridge-fixture-%s" % str(Time.get_unix_time_from_system()))
	DirAccess.make_dir_recursive_absolute(_fixture_root)
	_write_fixture_camera("video0")
	_write_fixture_camera("video2")

func after_each() -> void:
	if _fixture_root != "":
		var dir := DirAccess.open(_fixture_root)
		if dir != null:
			dir.list_dir_begin()
			var entry := dir.get_next()
			while entry != "":
				if dir.current_is_dir() == false:
					dir.remove(entry)
				entry = dir.get_next()
			dir.list_dir_end()
		DirAccess.remove_absolute(_fixture_root)

func test_startup_captures_truthful_minimal_live_camera_sample_and_updates_health() -> void:
	var bridge = MediaPipePythonRuntimeBridge.new()
	var snapshot := bridge.startup(_make_runtime_config())

	assert_true(snapshot["ok"])
	assert_eq(snapshot["cameras"].size(), 2)
	assert_eq(snapshot["cameras"][0]["camera_id"], _fixture_root.path_join("video0"))
	assert_eq(snapshot["preview_descriptor"]["backend"], "mediapipe_python")
	assert_eq(snapshot["raw_tracking_frame"]["source_kind"], "live_camera")
	assert_eq(snapshot["raw_tracking_frame"]["source_id"], _fixture_root.path_join("video0"))
	assert_eq(snapshot["raw_tracking_frame"]["tracking_state"], "idle")
	assert_eq(int(snapshot["raw_tracking_frame"]["frame_size"]["x"]), 1280)
	assert_eq(int(snapshot["raw_tracking_frame"]["frame_size"]["y"]), 720)
	assert_true(int(snapshot["raw_tracking_frame"]["timestamp_ms"]) > 0)
	assert_false(snapshot["raw_tracking_frame"].has("confidence"))
	assert_false(snapshot["raw_tracking_frame"].has("landmarks"))
	assert_eq(bridge.poll_health()["status"], MediaPipePythonRuntimeHealth.STATUS_RUNNING)
	assert_true(bridge.poll_health()["runtime_available"])
	assert_true(bridge.poll_health()["camera_accessible"])
	assert_false(bridge.poll_health()["process_active"])
	assert_false(bridge.poll_health()["tracking_active"])
	assert_eq(bridge.poll_health()["selected_camera_id"], _fixture_root.path_join("video0"))

func test_list_cameras_enumerates_runtime_surface_using_last_runtime_config() -> void:
	var bridge = MediaPipePythonRuntimeBridge.new()
	var startup := bridge.startup(_make_runtime_config())
	assert_true(startup["ok"])

	var cameras := bridge.list_cameras()
	assert_eq(cameras.size(), 2)
	assert_eq(cameras[1]["camera_id"], _fixture_root.path_join("video2"))
	assert_eq(bridge.poll_health()["status"], MediaPipePythonRuntimeHealth.STATUS_IDLE)
	assert_true(bridge.poll_health()["healthy"])
	assert_eq(bridge.poll_health()["probe_operation"], "list_cameras")

func test_startup_rejects_unsupported_video_file_mode_honestly() -> void:
	var bridge = MediaPipePythonRuntimeBridge.new()
	var snapshot := bridge.startup(_make_runtime_config({
		"source": {
			"kind": "video_file",
			"path": "res://clips/demo.mp4"
		}
	}))

	assert_false(snapshot["ok"])
	assert_eq(snapshot["error_info"]["code"], "unsupported_source_kind")
	assert_eq(bridge.poll_health()["status"], MediaPipePythonRuntimeHealth.STATUS_ERROR)
	assert_false(bridge.poll_health()["runtime_available"])

func test_startup_fails_honestly_when_requested_camera_is_missing() -> void:
	var bridge = MediaPipePythonRuntimeBridge.new()
	var snapshot := bridge.startup(_make_runtime_config({
		"source": {
			"camera_id": _fixture_root.path_join("video9")
		}
	}))

	assert_false(snapshot["ok"])
	assert_eq(snapshot["error_info"]["code"], "camera_not_found")
	assert_eq(snapshot["cameras"].size(), 2)
	assert_eq(bridge.poll_health()["status"], MediaPipePythonRuntimeHealth.STATUS_ERROR)

func test_startup_fails_honestly_when_camera_sample_cannot_be_captured() -> void:
	var bridge = MediaPipePythonRuntimeBridge.new()
	var snapshot := bridge.startup(_make_runtime_config({}, false))

	assert_false(snapshot["ok"])
	assert_eq(snapshot["error_info"]["code"], "camera_open_failed")
	assert_eq(bridge.poll_health()["selected_camera_id"], _fixture_root.path_join("video0"))
	assert_eq(bridge.poll_health()["status"], MediaPipePythonRuntimeHealth.STATUS_ERROR)
	assert_false(bridge.poll_health()["camera_accessible"])

func _make_runtime_config(overrides: Dictionary = {}, include_sample_fixture: bool = true) -> Dictionary:
	var environment := {
		"AEROBEAT_CAMERA_ROOT": _fixture_root,
		"AEROBEAT_CAMERA_PATTERN": "video*"
	}
	if include_sample_fixture:
		environment["AEROBEAT_CAMERA_SAMPLE_FIXTURES_JSON"] = JSON.stringify({
			_fixture_root.path_join("video0"): {"width": 1280, "height": 720, "timestamp_ms": 1710000000123},
			_fixture_root.path_join("video2"): {"width": 640, "height": 480, "timestamp_ms": 1710000000456}
		})

	var config := MediaPipePythonConfig.make_vendor_runtime_config({
		"runtime": {
			"environment": environment
		}
	})
	_deep_merge(config, overrides)
	return config

func _write_fixture_camera(name: String) -> void:
	var file := FileAccess.open(_fixture_root.path_join(name), FileAccess.WRITE)
	file.store_string("fixture")
	file.close()

func _deep_merge(base: Dictionary, incoming: Dictionary) -> void:
	for key in incoming.keys():
		var incoming_value: Variant = incoming[key]
		if base.has(key) and base[key] is Dictionary and incoming_value is Dictionary:
			_deep_merge(base[key], incoming_value)
		else:
			base[key] = incoming_value

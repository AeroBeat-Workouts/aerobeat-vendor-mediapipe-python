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

func test_startup_emits_real_minimal_landmark_payload_when_sampled_landmarks_exist() -> void:
	var bridge = MediaPipePythonRuntimeBridge.new()
	var snapshot := bridge.startup(_make_runtime_config())

	assert_true(snapshot["ok"])
	assert_eq(snapshot["cameras"].size(), 2)
	assert_eq(snapshot["cameras"][0]["camera_id"], _fixture_root.path_join("video0"))
	assert_eq(snapshot["preview_descriptor"]["backend"], "mediapipe_python")
	assert_eq(snapshot["raw_tracking_frame"]["source_kind"], "live_camera")
	assert_eq(snapshot["raw_tracking_frame"]["source_id"], _fixture_root.path_join("video0"))
	assert_eq(snapshot["raw_tracking_frame"]["tracking_state"], "tracked")
	assert_eq(int(snapshot["raw_tracking_frame"]["frame_size"]["x"]), 1280)
	assert_eq(int(snapshot["raw_tracking_frame"]["frame_size"]["y"]), 720)
	assert_true(int(snapshot["raw_tracking_frame"]["timestamp_ms"]) > 0)
	assert_false(snapshot["raw_tracking_frame"].has("confidence"))
	assert_true(snapshot["raw_tracking_frame"].has("landmarks"))
	assert_eq(snapshot["raw_tracking_frame"]["landmarks"].size(), 2)
	assert_eq(int(snapshot["raw_tracking_frame"]["landmarks"][0]["id"]), 0)
	assert_eq(float(snapshot["raw_tracking_frame"]["landmarks"][0]["x"]), 0.25)
	assert_eq(float(snapshot["raw_tracking_frame"]["landmarks"][0]["y"]), 0.4)
	assert_eq(float(snapshot["raw_tracking_frame"]["landmarks"][0]["z"]), -0.15)
	assert_eq(float(snapshot["raw_tracking_frame"]["landmarks"][0]["visibility"]), 0.95)
	assert_eq(int(snapshot["raw_tracking_frame"]["landmarks"][1]["id"]), 12)
	assert_eq(bridge.poll_health()["status"], MediaPipePythonRuntimeHealth.STATUS_RUNNING)
	assert_true(bridge.poll_health()["runtime_available"])
	assert_true(bridge.poll_health()["camera_accessible"])
	assert_true(bridge.poll_health()["process_active"])
	assert_true(bridge.poll_health()["tracking_active"])
	assert_eq(bridge.poll_health()["selected_camera_id"], _fixture_root.path_join("video0"))

	var second := bridge.poll_snapshot()
	assert_true(second["ok"])
	assert_true(int(second["raw_tracking_frame"]["timestamp_ms"]) >= int(snapshot["raw_tracking_frame"]["timestamp_ms"]))
	assert_eq(second["raw_tracking_frame"]["tracking_state"], "tracked")

	var shutdown := bridge.shutdown()
	assert_true(shutdown["ok"])
	assert_false(bridge.poll_health()["process_active"])
	assert_false(bridge.poll_health()["tracking_active"])
	assert_eq(bridge.poll_health()["status"], MediaPipePythonRuntimeHealth.STATUS_IDLE)

func test_continuous_runtime_advances_timestamps_without_reconfigure() -> void:
	var bridge = MediaPipePythonRuntimeBridge.new()
	var snapshot := bridge.startup(_make_runtime_config())
	assert_true(snapshot["ok"])
	var first_timestamp := int(snapshot["raw_tracking_frame"]["timestamp_ms"])
	OS.delay_msec(350)
	var second := bridge.poll_snapshot()
	OS.delay_msec(350)
	var third := bridge.poll_snapshot()
	assert_true(second["ok"])
	assert_true(third["ok"])
	assert_true(int(second["raw_tracking_frame"]["timestamp_ms"]) > first_timestamp)
	assert_true(int(third["raw_tracking_frame"]["timestamp_ms"]) > int(second["raw_tracking_frame"]["timestamp_ms"]))
	assert_true(bridge.poll_health()["process_active"])
	assert_true(bridge.poll_health()["tracking_active"])
	bridge.shutdown()

func test_startup_keeps_tracking_idle_when_sampled_frame_has_no_pose_landmarks_but_loop_stays_active() -> void:
	var bridge = MediaPipePythonRuntimeBridge.new()
	var snapshot := bridge.startup(_make_runtime_config({
		"runtime": {
			"health_poll_interval_ms": 150,
			"environment": {
				"AEROBEAT_CAMERA_SAMPLE_FIXTURES_JSON": JSON.stringify({
					_fixture_root.path_join("video0"): {"width": 800, "height": 600},
					_fixture_root.path_join("video2"): {"width": 640, "height": 480}
				})
			}
		}
	}))

	assert_true(snapshot["ok"])
	assert_eq(snapshot["raw_tracking_frame"]["tracking_state"], "idle")
	assert_false(snapshot["raw_tracking_frame"].has("landmarks"))
	assert_true(bridge.poll_health()["tracking_active"])
	assert_true(bridge.poll_health()["process_active"])
	assert_true(bridge.poll_health()["healthy"])
	bridge.shutdown()

func test_list_cameras_enumerates_runtime_surface_using_last_runtime_config() -> void:
	var bridge = MediaPipePythonRuntimeBridge.new()
	var startup := bridge.startup(_make_runtime_config())
	assert_true(startup["ok"])

	var cameras := bridge.list_cameras()
	assert_eq(cameras.size(), 2)
	assert_eq(cameras[1]["camera_id"], _fixture_root.path_join("video2"))
	assert_eq(bridge.poll_health()["status"], MediaPipePythonRuntimeHealth.STATUS_RUNNING)
	assert_true(bridge.poll_health()["healthy"])
	bridge.shutdown()

func test_startup_supports_replay_video_file_source_and_keeps_runtime_alive_until_fixture_eof() -> void:
	var replay_path := _write_fixture_video("gesture_replay.mp4")
	var bridge = MediaPipePythonRuntimeBridge.new()
	var snapshot := bridge.startup(_make_runtime_config({
		"source": {
			"kind": "video_file",
			"path": replay_path
		},
		"preview": {
			"flip_horizontal": false
		},
		"runtime": {
			"environment": {
				"AEROBEAT_CAMERA_ROOT": _fixture_root,
				"AEROBEAT_CAMERA_PATTERN": "video*",
				"AEROBEAT_CAMERA_SAMPLE_FIXTURES_JSON": JSON.stringify({
					replay_path: {
						"sequence": [
							{
								"width": 960,
								"height": 540,
								"timestamp_ms": 101,
								"landmarks": [
									{"id": 15, "x": 0.2, "y": 0.3, "z": -0.1, "visibility": 0.9}
								]
							},
							{
								"width": 960,
								"height": 540,
								"timestamp_ms": 202
							},
							{
								"width": 960,
								"height": 540,
								"timestamp_ms": 303
							}
						]
					}
				})
			}
		}
	}))

	assert_true(snapshot["ok"])
	assert_eq(snapshot["raw_tracking_frame"]["source_kind"], "video_file")
	assert_eq(snapshot["raw_tracking_frame"]["source_id"], replay_path)
	assert_eq(snapshot["raw_tracking_frame"]["tracking_state"], "tracked")
	assert_eq(int(snapshot["raw_tracking_frame"]["frame_size"]["x"]), 960)
	assert_eq(bridge.poll_health()["status"], MediaPipePythonRuntimeHealth.STATUS_RUNNING)
	assert_true(bridge.poll_health()["process_active"])
	assert_true(bridge.poll_health()["tracking_active"])
	assert_eq(bridge.poll_health()["selected_camera_id"], replay_path)

	OS.delay_msec(220)
	var second := bridge.poll_snapshot()
	assert_true(second["ok"])
	var second_frame: Dictionary = second.get("raw_tracking_frame", {})
	if second_frame.is_empty():
		assert_false(bridge.poll_health()["process_active"])
	else:
		assert_eq(second_frame["source_kind"], "video_file")
		assert_true(int(second_frame["timestamp_ms"]) >= 202)

	OS.delay_msec(500)
	var third := bridge.poll_snapshot()
	assert_true(third["ok"])
	assert_false(bridge.poll_health()["process_active"])
	assert_false(bridge.poll_health()["tracking_active"])
	assert_eq(bridge.poll_health()["status"], MediaPipePythonRuntimeHealth.STATUS_IDLE)

	var shutdown := bridge.shutdown()
	assert_true(shutdown["ok"])

func test_startup_rejects_missing_replay_video_file_honestly() -> void:
	var bridge = MediaPipePythonRuntimeBridge.new()
	var snapshot := bridge.startup(_make_runtime_config({
		"source": {
			"kind": "video_file",
			"path": _fixture_root.path_join("missing_replay.mp4")
		}
	}))

	assert_false(snapshot["ok"])
	assert_eq(snapshot["error_info"]["code"], "video_file_missing")
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

func test_startup_fails_honestly_when_landmark_inference_fails() -> void:
	var bridge = MediaPipePythonRuntimeBridge.new()
	var snapshot := bridge.startup(_make_runtime_config({
		"runtime": {
			"environment": {
				"AEROBEAT_CAMERA_SAMPLE_FIXTURES_JSON": JSON.stringify({
					_fixture_root.path_join("video0"): {
						"width": 1280,
						"height": 720,
						"inference_error": {
							"code": "mediapipe_inference_failed",
							"message": "Fixture landmark inference exploded honestly"
						}
					},
					_fixture_root.path_join("video2"): {"width": 640, "height": 480}
				})
			}
		}
	}))

	assert_false(snapshot["ok"])
	assert_eq(snapshot["error_info"]["code"], "mediapipe_inference_failed")
	assert_eq(bridge.poll_health()["status"], MediaPipePythonRuntimeHealth.STATUS_ERROR)
	assert_true(bridge.poll_health()["camera_accessible"])
	assert_false(bridge.poll_health()["tracking_active"])

func test_startup_fails_honestly_when_camera_sample_cannot_be_captured() -> void:
	var bridge = MediaPipePythonRuntimeBridge.new()
	var snapshot := bridge.startup(_make_runtime_config({}, false))
	var error_code := str(snapshot.get("error_info", {}).get("code", ""))

	assert_false(snapshot["ok"])
	assert_true(["opencv_unavailable", "camera_open_failed"].has(error_code))
	assert_eq(bridge.poll_health()["selected_camera_id"], _fixture_root.path_join("video0"))
	assert_eq(bridge.poll_health()["status"], MediaPipePythonRuntimeHealth.STATUS_ERROR)
	assert_false(bridge.poll_health()["camera_accessible"])
	assert_false(bridge.poll_health()["healthy"])

func _make_runtime_config(overrides: Dictionary = {}, include_sample_fixture: bool = true) -> Dictionary:
	var environment := {
		"AEROBEAT_CAMERA_ROOT": _fixture_root,
		"AEROBEAT_CAMERA_PATTERN": "video*"
	}
	if include_sample_fixture:
		environment["AEROBEAT_CAMERA_SAMPLE_FIXTURES_JSON"] = JSON.stringify({
			_fixture_root.path_join("video0"): {
				"width": 1280,
				"height": 720,
				"landmarks": [
					{"id": 0, "x": 0.25, "y": 0.4, "z": -0.15, "visibility": 0.95},
					{"id": 12, "x": 0.61, "y": 0.52, "z": -0.09, "visibility": 0.88}
				]
			},
			_fixture_root.path_join("video2"): {"width": 640, "height": 480}
		})

	var config := MediaPipePythonConfig.make_vendor_runtime_config({
		"runtime": {
			"environment": environment,
			"health_poll_interval_ms": 100
		}
	})
	_deep_merge(config, overrides)
	return config

func _write_fixture_camera(name: String) -> void:
	var file := FileAccess.open(_fixture_root.path_join(name), FileAccess.WRITE)
	file.store_string("fixture")
	file.close()

func _write_fixture_video(name: String) -> String:
	var path := _fixture_root.path_join(name)
	var file := FileAccess.open(path, FileAccess.WRITE)
	file.store_string("fixture-video")
	file.close()
	return path

func _deep_merge(base: Dictionary, incoming: Dictionary) -> void:
	for key in incoming.keys():
		var incoming_value: Variant = incoming[key]
		if base.has(key) and base[key] is Dictionary and incoming_value is Dictionary:
			_deep_merge(base[key], incoming_value)
		else:
			base[key] = incoming_value

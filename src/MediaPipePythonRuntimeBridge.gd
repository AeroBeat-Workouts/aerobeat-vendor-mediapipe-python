extends RefCounted

const MediaPipePythonCameraInventory = preload("MediaPipePythonCameraInventory.gd")
const MediaPipePythonConfig = preload("MediaPipePythonConfig.gd")
const MediaPipePythonRuntimeHealth = preload("MediaPipePythonRuntimeHealth.gd")

const _TIMEOUT_EXIT_CODE := 124
const _DEFAULT_RUNTIME_ENTRYPOINT := "runtime/mediapipe_runtime_probe.py"
const _SESSION_SNAPSHOT_FILENAME := "runtime_snapshot.json"
const _SESSION_STOP_FILENAME := "stop"

var _last_vendor_config: Dictionary = {}
var _last_health: Dictionary = MediaPipePythonRuntimeHealth.unavailable()
var _last_cameras: Array = []
var _last_preview_descriptor: Dictionary = {}
var _last_playback_status: Dictionary = {}
var _last_raw_tracking_frame: Dictionary = {}
var _last_camera_options: Dictionary = {}
var _last_selected_camera_id: String = ""
var _last_error_info: Dictionary = {}
var _session_dir: String = ""
var _session_pid: int = -1

func startup(vendor_config: Dictionary) -> Dictionary:
	var prepared := _prepare_vendor_config(vendor_config)
	if bool(prepared.get("ok", false)) == false:
		return _remember_failure(prepared.get("error_info", {}), prepared.get("health", {}))
	return _start_runtime_session("startup", prepared.get("config", {}))

func shutdown() -> Dictionary:
	if _session_dir == "" or _session_pid <= 0:
		var notes: Array = ["MediaPipe Python runtime bridge is idle; no active continuous runtime session exists."]
		if _last_selected_camera_id != "":
			notes.append("Last selected camera was '%s'." % _last_selected_camera_id)
		_last_health = MediaPipePythonRuntimeHealth.idle({
			"bridge_connected": true,
			"runtime_available": bool(_last_health.get("runtime_available", true)),
			"process_active": false,
			"camera_accessible": false,
			"tracking_active": false,
			"healthy": true,
			"notes": notes
		})
		_last_preview_descriptor = {}
		_last_playback_status = {}
		_last_raw_tracking_frame = {}
		_last_camera_options = {}
		return {
			"ok": true,
			"health": _last_health.duplicate(true),
			"cameras": _last_cameras.duplicate(true),
			"preview_descriptor": {},
			"playback_status": _last_playback_status.duplicate(true),
			"raw_tracking_frame": {},
			"camera_options": _last_camera_options.duplicate(true)
		}

	var stop_path := _session_dir.path_join(_SESSION_STOP_FILENAME)
	var stop_file := FileAccess.open(stop_path, FileAccess.WRITE)
	if stop_file != null:
		stop_file.store_string("stop")
		stop_file.close()

	var timeout_ms := int(_last_vendor_config.get("runtime", {}).get("shutdown_timeout_ms", MediaPipePythonConfig.DEFAULT_SHUTDOWN_TIMEOUT_MS))
	var started_ms := Time.get_ticks_msec()
	while Time.get_ticks_msec() - started_ms < timeout_ms:
		if OS.is_process_running(_session_pid) == false:
			break
		OS.delay_msec(50)

	if OS.is_process_running(_session_pid):
		OS.execute("/bin/kill", PackedStringArray(["-TERM", str(_session_pid)]), [], true)
		var grace_started_ms := Time.get_ticks_msec()
		while Time.get_ticks_msec() - grace_started_ms < 1500:
			if OS.is_process_running(_session_pid) == false:
				break
			OS.delay_msec(50)
		if OS.is_process_running(_session_pid):
			OS.execute("/bin/kill", PackedStringArray(["-KILL", str(_session_pid)]), [], true)

	var snapshot := _read_session_snapshot(_session_dir)
	_cleanup_session_files()
	_last_preview_descriptor = {}
	_last_playback_status = {}
	_last_raw_tracking_frame = {}
	_last_camera_options = {}
	_last_health = MediaPipePythonRuntimeHealth.idle({
		"bridge_connected": true,
		"runtime_available": true,
		"process_active": false,
		"camera_accessible": false,
		"tracking_active": false,
		"healthy": true,
		"notes": ["Continuous MediaPipe runtime session stopped."]
	})
	if bool(snapshot.get("ok", false)) or not snapshot.is_empty():
		var health_from_snapshot: Dictionary = MediaPipePythonRuntimeHealth.make(snapshot.get("health", {}))
		health_from_snapshot["process_active"] = false
		health_from_snapshot["tracking_active"] = false
		health_from_snapshot["status"] = MediaPipePythonRuntimeHealth.STATUS_IDLE
		_last_health = health_from_snapshot
		_last_cameras = MediaPipePythonCameraInventory.normalize(snapshot.get("cameras", []))
	return {
		"ok": true,
		"health": _last_health.duplicate(true),
		"cameras": _last_cameras.duplicate(true),
		"preview_descriptor": {},
		"playback_status": _last_playback_status.duplicate(true),
		"raw_tracking_frame": {},
		"camera_options": _last_camera_options.duplicate(true)
	}

func reconfigure(vendor_config: Dictionary) -> Dictionary:
	var prepared := _prepare_vendor_config(vendor_config)
	if bool(prepared.get("ok", false)) == false:
		return _remember_failure(prepared.get("error_info", {}), prepared.get("health", {}))
	shutdown()
	return _start_runtime_session("reconfigure", prepared.get("config", {}))

func list_cameras() -> Array:
	var config := _last_vendor_config.duplicate(true)
	if config.is_empty():
		config = MediaPipePythonConfig.vendor_defaults()
	var prepared := _prepare_vendor_config(config, false)
	if bool(prepared.get("ok", false)) == false:
		_remember_failure(prepared.get("error_info", {}), prepared.get("health", {}))
		return _last_cameras.duplicate(true)
	var snapshot := _run_runtime_operation("list_cameras", prepared.get("config", {}))
	if bool(snapshot.get("ok", false)):
		return snapshot.get("cameras", []).duplicate(true)
	return _last_cameras.duplicate(true)

func get_last_playback_status() -> Dictionary:
	return _last_playback_status.duplicate(true)

func get_last_camera_options() -> Dictionary:
	return _last_camera_options.duplicate(true)

func describe_camera_options(camera_id: String = "") -> Dictionary:
	var config := _last_vendor_config.duplicate(true)
	if config.is_empty():
		config = MediaPipePythonConfig.vendor_defaults()
	if camera_id != "":
		var source: Dictionary = config.get("source", {}).duplicate(true)
		source["camera_id"] = camera_id
		config["source"] = source
	var prepared := _prepare_vendor_config(config, false)
	if bool(prepared.get("ok", false)) == false:
		return _remember_failure(prepared.get("error_info", {}), prepared.get("health", {}))
	return _run_runtime_operation("describe_camera_options", prepared.get("config", {}))

func poll_health() -> Dictionary:
	if _session_dir != "" and _session_pid > 0:
		poll_snapshot()
	return _last_health.duplicate(true)

func poll_snapshot() -> Dictionary:
	if _session_dir == "" or _session_pid <= 0:
		return {
			"ok": true,
			"health": _last_health.duplicate(true),
			"cameras": _last_cameras.duplicate(true),
			"preview_descriptor": _last_preview_descriptor.duplicate(true),
			"playback_status": _last_playback_status.duplicate(true),
			"raw_tracking_frame": _last_raw_tracking_frame.duplicate(true),
			"camera_options": _last_camera_options.duplicate(true)
		}

	var snapshot := _read_session_snapshot(_session_dir)
	if snapshot.is_empty():
		if OS.is_process_running(_session_pid):
			return {
				"ok": true,
				"health": _last_health.duplicate(true),
				"cameras": _last_cameras.duplicate(true),
				"preview_descriptor": _last_preview_descriptor.duplicate(true),
				"playback_status": _last_playback_status.duplicate(true),
				"raw_tracking_frame": _last_raw_tracking_frame.duplicate(true),
				"camera_options": _last_camera_options.duplicate(true)
			}
		return _remember_failure({
			"code": "runtime_session_snapshot_missing",
			"message": "Continuous MediaPipe runtime session ended before a readable snapshot was available"
		}, MediaPipePythonRuntimeHealth.errored({
			"code": "runtime_session_snapshot_missing",
			"message": "Continuous MediaPipe runtime session ended before a readable snapshot was available"
		}, {
			"runtime_available": false,
			"process_active": false,
			"tracking_active": false
		}))

	_sync_from_snapshot(snapshot)
	if OS.is_process_running(_session_pid) == false:
		_last_health["process_active"] = false
		_last_health["tracking_active"] = false
		if str(_last_health.get("status", "")) == MediaPipePythonRuntimeHealth.STATUS_RUNNING:
			_last_health["status"] = MediaPipePythonRuntimeHealth.STATUS_ERROR
			_last_health["healthy"] = false
			_last_health["last_error"] = {
				"code": "runtime_session_exited",
				"message": "Continuous MediaPipe runtime session exited unexpectedly"
			}
	return {
		"ok": bool(snapshot.get("ok", true)),
		"health": _last_health.duplicate(true),
		"cameras": _last_cameras.duplicate(true),
		"preview_descriptor": _last_preview_descriptor.duplicate(true),
		"playback_status": _last_playback_status.duplicate(true),
		"raw_tracking_frame": _last_raw_tracking_frame.duplicate(true),
		"error_info": snapshot.get("error_info", {}).duplicate(true)
	}

func _start_runtime_session(operation: String, vendor_config: Dictionary) -> Dictionary:
	_cleanup_session_files()
	var request_path := _write_request_payload(operation, vendor_config)
	if request_path == "":
		return _remember_failure({
			"code": "runtime_request_write_failed",
			"message": "Failed to write MediaPipe Python runtime request payload"
		}, MediaPipePythonRuntimeHealth.errored({
			"code": "runtime_request_write_failed",
			"message": "Failed to write MediaPipe Python runtime request payload"
		}))

	_session_dir = _make_session_dir()
	DirAccess.make_dir_recursive_absolute(_session_dir)
	var runtime: Dictionary = vendor_config.get("runtime", {})
	var command_spec := _build_command_spec(runtime, request_path, _session_dir)
	var pid := OS.create_process(command_spec.get("command", ""), command_spec.get("args", PackedStringArray()))
	if pid <= 0:
		_cleanup_session_files()
		return _remember_failure({
			"code": "runtime_session_launch_failed",
			"message": "Failed to launch continuous MediaPipe runtime session",
			"python_executable": str(runtime.get("python_executable", "")),
			"entrypoint": str(runtime.get("entrypoint", ""))
		}, MediaPipePythonRuntimeHealth.errored({
			"code": "runtime_session_launch_failed",
			"message": "Failed to launch continuous MediaPipe runtime session"
		}, {
			"runtime_available": false,
			"process_active": false,
			"tracking_active": false
		}))

	_session_pid = pid
	_last_vendor_config = vendor_config.duplicate(true)
	var timeout_ms := int(runtime.get("boot_timeout_ms", MediaPipePythonConfig.DEFAULT_BOOT_TIMEOUT_MS))
	var started_ms := Time.get_ticks_msec()
	while Time.get_ticks_msec() - started_ms < timeout_ms:
		var snapshot := _read_session_snapshot(_session_dir)
		if not snapshot.is_empty():
			_sync_from_snapshot(snapshot)
			if bool(snapshot.get("ok", false)) == false:
				_cleanup_session_files()
				return _remember_failure(snapshot.get("error_info", {}), _last_health, snapshot.get("cameras", []))
			_last_health["process_active"] = OS.is_process_running(_session_pid)
			_last_health["tracking_active"] = _last_health["process_active"]
			return {
				"ok": true,
				"health": _last_health.duplicate(true),
				"cameras": _last_cameras.duplicate(true),
				"preview_descriptor": _last_preview_descriptor.duplicate(true),
				"playback_status": _last_playback_status.duplicate(true),
				"raw_tracking_frame": _last_raw_tracking_frame.duplicate(true),
				"camera_options": _last_camera_options.duplicate(true)
			}
		if OS.is_process_running(_session_pid) == false:
			break
		OS.delay_msec(50)

	_cleanup_session_files()
	return _remember_failure({
		"code": "runtime_session_start_timeout",
		"message": "Continuous MediaPipe runtime session did not become ready before startup timed out",
		"timeout_ms": timeout_ms
	}, MediaPipePythonRuntimeHealth.errored({
		"code": "runtime_session_start_timeout",
		"message": "Continuous MediaPipe runtime session did not become ready before startup timed out"
	}, {
		"runtime_available": false,
		"process_active": false,
		"tracking_active": false
	}))

func _run_runtime_operation(operation: String, vendor_config: Dictionary) -> Dictionary:
	var request_path := _write_request_payload(operation, vendor_config)
	if request_path == "":
		return _remember_failure({
			"code": "runtime_request_write_failed",
			"message": "Failed to write MediaPipe Python runtime probe request payload"
		}, MediaPipePythonRuntimeHealth.errored({
			"code": "runtime_request_write_failed",
			"message": "Failed to write MediaPipe Python runtime probe request payload"
		}))

	var runtime: Dictionary = vendor_config.get("runtime", {})
	var command_spec := _build_blocking_command_spec(runtime, request_path)
	var output: Array = []
	var start_ms := Time.get_ticks_msec()
	var exit_code := OS.execute(command_spec.get("command", ""), command_spec.get("args", []), output, true)
	var duration_ms := Time.get_ticks_msec() - start_ms
	DirAccess.remove_absolute(request_path)

	var parsed := _parse_probe_output(output)
	if exit_code != 0:
		var failure := _runtime_execution_failure(operation, vendor_config, exit_code, duration_ms, output, parsed)
		return _remember_failure(failure.get("error_info", {}), failure.get("health", {}), failure.get("cameras", []))
	if bool(parsed.get("ok", false)) == false:
		var error_info: Dictionary = parsed.get("error_info", {
			"code": "runtime_probe_failed",
			"message": "MediaPipe Python runtime probe reported failure"
		})
		var health := MediaPipePythonRuntimeHealth.errored(error_info, parsed.get("health", {}))
		health["probe_duration_ms"] = duration_ms
		health["process_active"] = false
		return _remember_failure(error_info, health, parsed.get("cameras", []))

	_last_vendor_config = vendor_config.duplicate(true)
	_sync_from_snapshot(parsed)
	_last_health["bridge_connected"] = true
	_last_health["runtime_available"] = true
	_last_health["process_active"] = false
	_last_health["probe_duration_ms"] = duration_ms
	if operation == "list_cameras" and _last_health.get("status", "") == MediaPipePythonRuntimeHealth.STATUS_IDLE:
		_last_health["healthy"] = true

	return {
		"ok": true,
		"health": _last_health.duplicate(true),
		"cameras": _last_cameras.duplicate(true),
		"preview_descriptor": _last_preview_descriptor.duplicate(true),
		"raw_tracking_frame": _last_raw_tracking_frame.duplicate(true),
		"camera_options": _last_camera_options.duplicate(true)
	}

func _sync_from_snapshot(snapshot: Dictionary) -> void:
	_last_cameras = MediaPipePythonCameraInventory.normalize(snapshot.get("cameras", []))
	_last_preview_descriptor = snapshot.get("preview_descriptor", {}).duplicate(true)
	_last_playback_status = snapshot.get("playback_status", {}).duplicate(true)
	_last_raw_tracking_frame = snapshot.get("raw_tracking_frame", {}).duplicate(true)
	_last_camera_options = snapshot.get("camera_options", {}).duplicate(true)
	_last_selected_camera_id = str(snapshot.get("selected_camera_id", _last_selected_camera_id))
	_last_error_info = snapshot.get("error_info", {}).duplicate(true)
	_last_health = MediaPipePythonRuntimeHealth.make(snapshot.get("health", {}))
	_last_health["selected_camera_id"] = _last_selected_camera_id

func _prepare_vendor_config(vendor_config: Dictionary, validate_source: bool = true) -> Dictionary:
	var merged := MediaPipePythonConfig.vendor_defaults()
	_deep_merge(merged, vendor_config)
	merged["backend"] = MediaPipePythonConfig.BACKEND_ID

	var runtime: Dictionary = merged.get("runtime", {})
	var python_executable := str(runtime.get("python_executable", MediaPipePythonConfig.DEFAULT_PYTHON_EXECUTABLE)).strip_edges()
	if python_executable == "":
		return _config_failure("python_executable_missing", "MediaPipe Python runtime requires a python_executable")

	var entrypoint_raw := str(runtime.get("entrypoint", "")).strip_edges()
	var entrypoint_path := _resolve_entrypoint_path(entrypoint_raw)
	if entrypoint_path == "":
		return _config_failure("runtime_entrypoint_missing", "MediaPipe Python runtime entrypoint could not be resolved")
	if FileAccess.file_exists(entrypoint_path) == false:
		return _config_failure("runtime_entrypoint_missing", "MediaPipe Python runtime entrypoint not found at '%s'" % entrypoint_path)

	var source: Dictionary = merged.get("source", {})
	var source_kind := str(source.get("kind", MediaPipePythonConfig.DEFAULT_SOURCE_KIND))
	if validate_source:
		if source_kind == MediaPipePythonConfig.DEFAULT_SOURCE_KIND:
			pass
		elif source_kind == "video_file":
			var source_path := _resolve_source_path(str(source.get("path", "")))
			if source_path == "":
				return _config_failure("video_file_path_missing", "MediaPipe Python replay runtime requires source.path for video_file sessions")
			if FileAccess.file_exists(source_path) == false:
				return _config_failure("video_file_missing", "MediaPipe Python replay source not found at '%s'" % source_path)
			source["path"] = source_path
			merged["source"] = source
		else:
			return _config_failure(
				"unsupported_source_kind",
				"MediaPipe Python runtime bridge only supports '%s' or 'video_file' in this slice, got '%s'" % [MediaPipePythonConfig.DEFAULT_SOURCE_KIND, source_kind]
			)

	runtime["python_executable"] = python_executable
	runtime["entrypoint"] = entrypoint_path
	runtime["working_directory"] = _resolve_working_directory(str(runtime.get("working_directory", "")))
	merged["runtime"] = runtime
	return {"ok": true, "config": merged}

func _config_failure(code: String, message: String) -> Dictionary:
	var error_info := {"code": code, "message": message, "backend": MediaPipePythonConfig.BACKEND_ID}
	var health := MediaPipePythonRuntimeHealth.errored(error_info, {
		"bridge_connected": true,
		"runtime_available": false,
		"process_active": false,
		"camera_accessible": false,
		"tracking_active": false
	})
	return {"ok": false, "error_info": error_info, "health": health}

func _write_request_payload(operation: String, vendor_config: Dictionary) -> String:
	var runtime_dir := ProjectSettings.globalize_path("user://mediapipe_python_runtime_bridge")
	DirAccess.make_dir_recursive_absolute(runtime_dir)
	var request_path := runtime_dir.path_join("%s-%s.json" % [operation, str(Time.get_ticks_usec())])
	var file := FileAccess.open(request_path, FileAccess.WRITE)
	if file == null:
		return ""
	var payload := {
		"operation": operation,
		"backend": MediaPipePythonConfig.BACKEND_ID,
		"source": vendor_config.get("source", {}).duplicate(true),
		"tracking": vendor_config.get("tracking", {}).duplicate(true),
		"preview": vendor_config.get("preview", {}).duplicate(true),
		"runtime": vendor_config.get("runtime", {}).duplicate(true),
		"diagnostics": vendor_config.get("diagnostics", {}).duplicate(true)
	}
	file.store_string(JSON.stringify(payload))
	file.close()
	return request_path

func _build_blocking_command_spec(runtime: Dictionary, request_path: String) -> Dictionary:
	var python_executable := str(runtime.get("python_executable", MediaPipePythonConfig.DEFAULT_PYTHON_EXECUTABLE))
	var args := PackedStringArray([str(runtime.get("entrypoint", _resolve_entrypoint_path(""))), "--request-file", request_path])
	var timeout_ms := int(runtime.get("boot_timeout_ms", MediaPipePythonConfig.DEFAULT_BOOT_TIMEOUT_MS))
	var command := python_executable
	if timeout_ms > 0:
		args = PackedStringArray([_format_timeout_seconds(timeout_ms), command]) + args
		command = "timeout"
	return {"command": command, "args": args}

func _build_command_spec(runtime: Dictionary, request_path: String, session_dir: String) -> Dictionary:
	var python_executable := str(runtime.get("python_executable", MediaPipePythonConfig.DEFAULT_PYTHON_EXECUTABLE))
	var args := PackedStringArray([
		str(runtime.get("entrypoint", _resolve_entrypoint_path(""))),
		"--request-file", request_path,
		"--session-dir", session_dir,
	])
	return {"command": python_executable, "args": args}

func _parse_probe_output(output: Array) -> Dictionary:
	var lines: Array = []
	for chunk in output:
		var text := str(chunk)
		for line in text.split("
"):
			var trimmed := line.strip_edges()
			if trimmed != "":
				lines.append(trimmed)
	for index in range(lines.size() - 1, -1, -1):
		var candidate = JSON.parse_string(lines[index])
		if candidate is Dictionary:
			return candidate
	return {
		"ok": false,
		"error_info": {"code": "runtime_probe_invalid_output", "message": "MediaPipe Python runtime probe did not emit valid JSON"},
		"health": MediaPipePythonRuntimeHealth.errored({"code": "runtime_probe_invalid_output", "message": "MediaPipe Python runtime probe did not emit valid JSON"})
	}

func _read_session_snapshot(session_dir: String) -> Dictionary:
	var snapshot_path := session_dir.path_join(_SESSION_SNAPSHOT_FILENAME)
	if FileAccess.file_exists(snapshot_path) == false:
		return {}
	var file := FileAccess.open(snapshot_path, FileAccess.READ)
	if file == null:
		return {}
	var text := file.get_as_text()
	file.close()
	var parsed = JSON.parse_string(text)
	if parsed is Dictionary:
		return parsed
	return {}

func _runtime_execution_failure(operation: String, vendor_config: Dictionary, exit_code: int, duration_ms: int, output: Array, parsed: Dictionary) -> Dictionary:
	var timed_out := exit_code == _TIMEOUT_EXIT_CODE
	var output_text := ""
	for chunk in output:
		output_text += str(chunk)
	var error_info: Dictionary = parsed.get("error_info", {
		"code": "runtime_probe_timeout" if timed_out else "runtime_probe_process_failed",
		"message": "MediaPipe Python runtime probe timed out" if timed_out else "MediaPipe Python runtime probe process exited unsuccessfully",
		"backend": MediaPipePythonConfig.BACKEND_ID
	})
	error_info["backend"] = MediaPipePythonConfig.BACKEND_ID
	error_info["operation"] = operation
	error_info["exit_code"] = exit_code
	error_info["python_executable"] = str(vendor_config.get("runtime", {}).get("python_executable", ""))
	error_info["entrypoint"] = str(vendor_config.get("runtime", {}).get("entrypoint", ""))
	if output_text.strip_edges() != "":
		error_info["output"] = output_text.strip_edges()

	var health := MediaPipePythonRuntimeHealth.errored(error_info, parsed.get("health", {}))
	health["bridge_connected"] = true
	health["runtime_available"] = false if timed_out else bool(health.get("runtime_available", false))
	health["process_active"] = false
	health["probe_duration_ms"] = duration_ms
	return {"error_info": error_info, "health": health, "cameras": parsed.get("cameras", [])}

func _remember_failure(error_info: Dictionary, health: Dictionary, cameras: Array = []) -> Dictionary:
	_last_error_info = error_info.duplicate(true)
	_last_health = MediaPipePythonRuntimeHealth.errored(_last_error_info, health)
	if not cameras.is_empty():
		_last_cameras = MediaPipePythonCameraInventory.normalize(cameras)
	_last_preview_descriptor = {}
	_last_playback_status = {}
	_last_raw_tracking_frame = {}
	_last_camera_options = {}
	return {
		"ok": false,
		"health": _last_health.duplicate(true),
		"cameras": _last_cameras.duplicate(true),
		"preview_descriptor": {},
		"raw_tracking_frame": {},
		"error_info": _last_error_info.duplicate(true)
	}

func _resolve_entrypoint_path(entrypoint_raw: String) -> String:
	var candidate := entrypoint_raw if entrypoint_raw != "" else _DEFAULT_RUNTIME_ENTRYPOINT
	if candidate.begins_with("res://") or candidate.begins_with("user://"):
		return ProjectSettings.globalize_path(candidate)
	if candidate.is_absolute_path():
		return candidate
	return _repo_root_path().path_join(candidate)

func _resolve_working_directory(working_directory_raw: String) -> String:
	if working_directory_raw == "":
		return _repo_root_path()
	if working_directory_raw.begins_with("res://") or working_directory_raw.begins_with("user://"):
		return ProjectSettings.globalize_path(working_directory_raw)
	if working_directory_raw.is_absolute_path():
		return working_directory_raw
	return _repo_root_path().path_join(working_directory_raw)

func _resolve_source_path(source_path_raw: String) -> String:
	if source_path_raw == "":
		return ""
	if source_path_raw.begins_with("res://") or source_path_raw.begins_with("user://"):
		return ProjectSettings.globalize_path(source_path_raw)
	if source_path_raw.is_absolute_path():
		return source_path_raw
	return _repo_root_path().path_join(source_path_raw)

func _repo_root_path() -> String:
	var script_path := str(get_script().resource_path)
	return ProjectSettings.globalize_path(script_path.get_base_dir().path_join(".."))

func _make_session_dir() -> String:
	var base_dir := ProjectSettings.globalize_path("user://mediapipe_python_runtime_bridge/sessions")
	DirAccess.make_dir_recursive_absolute(base_dir)
	return base_dir.path_join("session-%s-%s" % [str(Time.get_unix_time_from_system()), str(Time.get_ticks_usec())])

func _cleanup_session_files() -> void:
	if _session_dir != "":
		var snapshot_path := _session_dir.path_join(_SESSION_SNAPSHOT_FILENAME)
		var stop_path := _session_dir.path_join(_SESSION_STOP_FILENAME)
		DirAccess.remove_absolute(snapshot_path)
		DirAccess.remove_absolute(stop_path)
		DirAccess.remove_absolute(_session_dir.path_join("request.json"))
		DirAccess.remove_absolute(_session_dir)
	_session_dir = ""
	_session_pid = -1

func _format_timeout_seconds(timeout_ms: int) -> String:
	var seconds := maxf(0.001, float(timeout_ms) / 1000.0)
	return "%.3f" % seconds

func _deep_merge(base: Dictionary, incoming: Dictionary) -> void:
	for key in incoming.keys():
		var incoming_value: Variant = incoming[key]
		if base.has(key) and base[key] is Dictionary and incoming_value is Dictionary:
			_deep_merge(base[key], incoming_value)
		else:
			base[key] = incoming_value

extends RefCounted

const MediaPipePythonCameraInventory = preload("MediaPipePythonCameraInventory.gd")
const MediaPipePythonConfig = preload("MediaPipePythonConfig.gd")
const MediaPipePythonRuntimeHealth = preload("MediaPipePythonRuntimeHealth.gd")

const _TIMEOUT_EXIT_CODE := 124
const _DEFAULT_RUNTIME_ENTRYPOINT := "runtime/mediapipe_runtime_probe.py"

var _last_vendor_config: Dictionary = {}
var _last_health: Dictionary = MediaPipePythonRuntimeHealth.unavailable()
var _last_cameras: Array = []
var _last_preview_descriptor: Dictionary = {}
var _last_raw_tracking_frame: Dictionary = {}
var _last_selected_camera_id: String = ""
var _last_error_info: Dictionary = {}

func startup(vendor_config: Dictionary) -> Dictionary:
	var prepared := _prepare_vendor_config(vendor_config)
	if bool(prepared.get("ok", false)) == false:
		return _remember_failure(prepared.get("error_info", {}), prepared.get("health", {}))
	return _run_runtime_operation("startup", prepared.get("config", {}))

func shutdown() -> Dictionary:
	var notes: Array = ["MediaPipe Python runtime bridge is idle; bootstrap/probe subprocess is not kept alive in this slice."]
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
	_last_raw_tracking_frame = {}
	return {
		"ok": true,
		"health": _last_health.duplicate(true),
		"cameras": _last_cameras.duplicate(true),
		"preview_descriptor": {},
		"raw_tracking_frame": {}
	}

func reconfigure(vendor_config: Dictionary) -> Dictionary:
	var prepared := _prepare_vendor_config(vendor_config)
	if bool(prepared.get("ok", false)) == false:
		return _remember_failure(prepared.get("error_info", {}), prepared.get("health", {}))
	return _run_runtime_operation("reconfigure", prepared.get("config", {}))

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

func poll_health() -> Dictionary:
	return _last_health.duplicate(true)

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
	var command_spec := _build_command_spec(runtime, request_path)
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
	_last_cameras = MediaPipePythonCameraInventory.normalize(parsed.get("cameras", []))
	_last_preview_descriptor = parsed.get("preview_descriptor", {}).duplicate(true)
	_last_raw_tracking_frame = parsed.get("raw_tracking_frame", {}).duplicate(true)
	_last_selected_camera_id = str(parsed.get("selected_camera_id", _last_selected_camera_id))
	_last_error_info = {}

	var health := MediaPipePythonRuntimeHealth.make(parsed.get("health", {}))
	health["bridge_connected"] = true
	health["runtime_available"] = true
	health["process_active"] = false
	health["probe_duration_ms"] = duration_ms
	if operation == "list_cameras" and health.get("status", "") == MediaPipePythonRuntimeHealth.STATUS_IDLE:
		health["healthy"] = true
	_last_health = health

	return {
		"ok": true,
		"health": _last_health.duplicate(true),
		"cameras": _last_cameras.duplicate(true),
		"preview_descriptor": _last_preview_descriptor.duplicate(true),
		"raw_tracking_frame": _last_raw_tracking_frame.duplicate(true)
	}

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
	if validate_source and source_kind != MediaPipePythonConfig.DEFAULT_SOURCE_KIND:
		return _config_failure(
			"unsupported_source_kind",
			"MediaPipe Python runtime bridge only supports '%s' in this slice, got '%s'" % [MediaPipePythonConfig.DEFAULT_SOURCE_KIND, source_kind]
		)

	runtime["python_executable"] = python_executable
	runtime["entrypoint"] = entrypoint_path
	runtime["working_directory"] = _resolve_working_directory(str(runtime.get("working_directory", "")))
	merged["runtime"] = runtime
	return {
		"ok": true,
		"config": merged
	}

func _config_failure(code: String, message: String) -> Dictionary:
	var error_info := {
		"code": code,
		"message": message,
		"backend": MediaPipePythonConfig.BACKEND_ID
	}
	var health := MediaPipePythonRuntimeHealth.errored(error_info, {
		"bridge_connected": true,
		"runtime_available": false,
		"process_active": false,
		"camera_accessible": false,
		"tracking_active": false
	})
	return {
		"ok": false,
		"error_info": error_info,
		"health": health
	}

func _write_request_payload(operation: String, vendor_config: Dictionary) -> String:
	var runtime_dir := ProjectSettings.globalize_path("user://mediapipe_python_runtime_bridge")
	DirAccess.make_dir_recursive_absolute(runtime_dir)
	var request_path := runtime_dir.path_join("%s-%s.json" % [operation, str(Time.get_unix_time_from_system())])
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

func _build_command_spec(runtime: Dictionary, request_path: String) -> Dictionary:
	var python_executable := str(runtime.get("python_executable", MediaPipePythonConfig.DEFAULT_PYTHON_EXECUTABLE))
	var args: Array = [str(runtime.get("entrypoint", _resolve_entrypoint_path(""))), "--request-file", request_path]
	var timeout_ms := int(runtime.get("boot_timeout_ms", MediaPipePythonConfig.DEFAULT_BOOT_TIMEOUT_MS))
	var command := python_executable

	if timeout_ms > 0:
		args = [_format_timeout_seconds(timeout_ms), command] + args
		command = "timeout"

	return {
		"command": command,
		"args": args
	}

func _parse_probe_output(output: Array) -> Dictionary:
	var lines: Array = []
	for chunk in output:
		var text := str(chunk)
		for line in text.split("\n"):
			var trimmed := line.strip_edges()
			if trimmed != "":
				lines.append(trimmed)
	for index in range(lines.size() - 1, -1, -1):
		var candidate = JSON.parse_string(lines[index])
		if candidate is Dictionary:
			return candidate
	return {
		"ok": false,
		"error_info": {
			"code": "runtime_probe_invalid_output",
			"message": "MediaPipe Python runtime probe did not emit valid JSON"
		},
		"health": MediaPipePythonRuntimeHealth.errored({
			"code": "runtime_probe_invalid_output",
			"message": "MediaPipe Python runtime probe did not emit valid JSON"
		})
	}

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
	return {
		"error_info": error_info,
		"health": health,
		"cameras": parsed.get("cameras", [])
	}

func _remember_failure(error_info: Dictionary, health: Dictionary, cameras: Array = []) -> Dictionary:
	_last_error_info = error_info.duplicate(true)
	_last_health = MediaPipePythonRuntimeHealth.errored(_last_error_info, health)
	if not cameras.is_empty():
		_last_cameras = MediaPipePythonCameraInventory.normalize(cameras)
	_last_preview_descriptor = {}
	_last_raw_tracking_frame = {}
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

func _repo_root_path() -> String:
	var script_path := str(get_script().resource_path)
	return ProjectSettings.globalize_path(script_path.get_base_dir().path_join(".."))

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

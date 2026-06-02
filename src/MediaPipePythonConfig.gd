extends RefCounted

const BACKEND_ID := "mediapipe_python"
const DEFAULT_SOURCE_KIND := "live_camera"
const DEFAULT_TRACKING_QUALITY := "optimized"
const DEFAULT_OVERLAY_MODE := "optimized"
const DEFAULT_MIN_VISIBILITY := 0.35
const DEFAULT_GESTURE_EVAL_INTERVAL_FRAMES := 1
const DEFAULT_SURFACE_MODE := "attach"
const DEFAULT_PYTHON_EXECUTABLE := "python3"
const DEFAULT_RUNTIME_ENTRYPOINT := "runtime/mediapipe_runtime_probe.py"
const DEFAULT_BOOT_TIMEOUT_MS := 8000
const DEFAULT_SHUTDOWN_TIMEOUT_MS := 5000
const DEFAULT_HEALTH_POLL_INTERVAL_MS := 250
const DEFAULT_MODEL_COMPLEXITY := 1
const DEFAULT_TRACKING_MAX_FPS := 30
const DEFAULT_STATE_UPDATE_MAX_FPS := 30
const DEFAULT_PREVIEW_MAX_FPS := 30
const DEFAULT_PREVIEW_WIDTH := 960
const DEFAULT_PREVIEW_HEIGHT := 540
const DEFAULT_PREVIEW_QUALITY := 75

static func public_defaults() -> Dictionary:
	return {
		"backend": BACKEND_ID,
		"source": {
			"kind": DEFAULT_SOURCE_KIND,
			"camera_id": "",
			"path": ""
		},
		"tracking": {
			"quality": DEFAULT_TRACKING_QUALITY,
			"overlay_mode": DEFAULT_OVERLAY_MODE,
			"gesture_eval_interval_frames": DEFAULT_GESTURE_EVAL_INTERVAL_FRAMES,
			"min_visibility": DEFAULT_MIN_VISIBILITY,
			"max_fps": DEFAULT_TRACKING_MAX_FPS
		},
		"preview": {
			"enabled": true,
			"surface_mode": DEFAULT_SURFACE_MODE,
			"flip_horizontal": true,
			"max_fps": DEFAULT_PREVIEW_MAX_FPS,
			"width": DEFAULT_PREVIEW_WIDTH,
			"height": DEFAULT_PREVIEW_HEIGHT,
			"quality": DEFAULT_PREVIEW_QUALITY
		}
	}

static func vendor_defaults() -> Dictionary:
	return {
		"backend": BACKEND_ID,
		"source": {
			"kind": DEFAULT_SOURCE_KIND,
			"camera_id": "",
			"path": ""
		},
		"tracking": {
			"quality": DEFAULT_TRACKING_QUALITY,
			"overlay_mode": DEFAULT_OVERLAY_MODE,
			"gesture_eval_interval_frames": DEFAULT_GESTURE_EVAL_INTERVAL_FRAMES,
			"min_visibility": DEFAULT_MIN_VISIBILITY,
			"max_fps": DEFAULT_TRACKING_MAX_FPS
		},
		"preview": {
			"enabled": true,
			"surface_mode": DEFAULT_SURFACE_MODE,
			"flip_horizontal": true,
			"max_fps": DEFAULT_PREVIEW_MAX_FPS,
			"width": DEFAULT_PREVIEW_WIDTH,
			"height": DEFAULT_PREVIEW_HEIGHT,
			"quality": DEFAULT_PREVIEW_QUALITY
		},
		"runtime": {
			"python_executable": DEFAULT_PYTHON_EXECUTABLE,
			"entrypoint": DEFAULT_RUNTIME_ENTRYPOINT,
			"working_directory": "",
			"arguments": [],
			"environment": {},
			"model_complexity": DEFAULT_MODEL_COMPLEXITY,
			"pose_landmarker_model_path": "",
			"boot_timeout_ms": DEFAULT_BOOT_TIMEOUT_MS,
			"shutdown_timeout_ms": DEFAULT_SHUTDOWN_TIMEOUT_MS,
			"health_poll_interval_ms": DEFAULT_HEALTH_POLL_INTERVAL_MS,
			"tracking_max_fps": DEFAULT_TRACKING_MAX_FPS,
			"state_update_max_fps": DEFAULT_STATE_UPDATE_MAX_FPS,
			"preview_enabled": true,
			"preview_max_fps": DEFAULT_PREVIEW_MAX_FPS,
			"preview_width": DEFAULT_PREVIEW_WIDTH,
			"preview_height": DEFAULT_PREVIEW_HEIGHT,
			"preview_quality": DEFAULT_PREVIEW_QUALITY
		},
		"diagnostics": {
			"emit_raw_vendor_payloads": false,
			"record_runtime_health": true
		}
	}

static func normalize_public_config(config: Dictionary = {}) -> Dictionary:
	var normalized := public_defaults()
	_deep_merge(normalized, config)
	normalized["backend"] = BACKEND_ID
	normalized["tracking"]["max_fps"] = _normalize_nonnegative_int(
		normalized.get("tracking", {}).get("max_fps", DEFAULT_TRACKING_MAX_FPS),
		DEFAULT_TRACKING_MAX_FPS
	)
	normalized["preview"]["enabled"] = bool(normalized.get("preview", {}).get("enabled", true))
	normalized["preview"]["max_fps"] = _normalize_nonnegative_int(
		normalized.get("preview", {}).get("max_fps", DEFAULT_PREVIEW_MAX_FPS),
		DEFAULT_PREVIEW_MAX_FPS
	)
	normalized["preview"]["width"] = _normalize_positive_int(
		normalized.get("preview", {}).get("width", DEFAULT_PREVIEW_WIDTH),
		DEFAULT_PREVIEW_WIDTH
	)
	normalized["preview"]["height"] = _normalize_positive_int(
		normalized.get("preview", {}).get("height", DEFAULT_PREVIEW_HEIGHT),
		DEFAULT_PREVIEW_HEIGHT
	)
	normalized["preview"]["quality"] = _normalize_quality(
		normalized.get("preview", {}).get("quality", DEFAULT_PREVIEW_QUALITY),
		DEFAULT_PREVIEW_QUALITY
	)
	return normalized

static func make_vendor_runtime_config(public_config: Dictionary = {}) -> Dictionary:
	var normalized_public := normalize_public_config(public_config)
	var vendor_config := vendor_defaults()
	vendor_config["source"] = normalized_public.get("source", {}).duplicate(true)
	vendor_config["tracking"] = normalized_public.get("tracking", {}).duplicate(true)
	vendor_config["preview"] = normalized_public.get("preview", {}).duplicate(true)
	vendor_config["backend"] = BACKEND_ID

	if public_config.get("runtime", {}) is Dictionary:
		_deep_merge(vendor_config["runtime"], public_config.get("runtime", {}))
	if public_config.get("diagnostics", {}) is Dictionary:
		_deep_merge(vendor_config["diagnostics"], public_config.get("diagnostics", {}))
	if public_config.get("vendor", {}) is Dictionary:
		_deep_merge(vendor_config, public_config.get("vendor", {}))

	var tracking: Dictionary = vendor_config.get("tracking", {})
	var preview: Dictionary = vendor_config.get("preview", {})
	var runtime: Dictionary = vendor_config.get("runtime", {})
	var incoming_runtime: Dictionary = public_config.get("runtime", {}) if public_config.get("runtime", {}) is Dictionary else {}

	runtime["model_complexity"] = _normalize_model_complexity(runtime.get("model_complexity", DEFAULT_MODEL_COMPLEXITY))
	runtime["tracking_max_fps"] = _normalize_nonnegative_int(
		runtime.get("tracking_max_fps", tracking.get("max_fps", DEFAULT_TRACKING_MAX_FPS)),
		DEFAULT_TRACKING_MAX_FPS
	)
	runtime["state_update_max_fps"] = _normalize_nonnegative_int(
		runtime.get("state_update_max_fps", DEFAULT_STATE_UPDATE_MAX_FPS),
		DEFAULT_STATE_UPDATE_MAX_FPS
	)
	if incoming_runtime.has("preview_enabled"):
		preview["enabled"] = bool(runtime.get("preview_enabled", true))
	else:
		runtime["preview_enabled"] = bool(preview.get("enabled", true))
	preview["enabled"] = bool(runtime.get("preview_enabled", preview.get("enabled", true)))
	runtime["preview_max_fps"] = _normalize_nonnegative_int(
		runtime.get("preview_max_fps", preview.get("max_fps", DEFAULT_PREVIEW_MAX_FPS)),
		DEFAULT_PREVIEW_MAX_FPS
	)
	runtime["preview_width"] = _normalize_positive_int(
		runtime.get("preview_width", preview.get("width", DEFAULT_PREVIEW_WIDTH)),
		DEFAULT_PREVIEW_WIDTH
	)
	runtime["preview_height"] = _normalize_positive_int(
		runtime.get("preview_height", preview.get("height", DEFAULT_PREVIEW_HEIGHT)),
		DEFAULT_PREVIEW_HEIGHT
	)
	runtime["preview_quality"] = _normalize_quality(
		runtime.get("preview_quality", preview.get("quality", DEFAULT_PREVIEW_QUALITY)),
		DEFAULT_PREVIEW_QUALITY
	)
	tracking["max_fps"] = int(runtime.get("tracking_max_fps", DEFAULT_TRACKING_MAX_FPS))
	preview["max_fps"] = int(runtime.get("preview_max_fps", DEFAULT_PREVIEW_MAX_FPS))
	preview["width"] = int(runtime.get("preview_width", DEFAULT_PREVIEW_WIDTH))
	preview["height"] = int(runtime.get("preview_height", DEFAULT_PREVIEW_HEIGHT))
	preview["quality"] = int(runtime.get("preview_quality", DEFAULT_PREVIEW_QUALITY))
	preview["enabled"] = bool(runtime.get("preview_enabled", true))
	vendor_config["tracking"] = tracking
	vendor_config["preview"] = preview
	vendor_config["runtime"] = runtime
	vendor_config["backend"] = BACKEND_ID
	return vendor_config

static func get_required_model_filename(model_complexity: int) -> String:
	match model_complexity:
		2:
			return "pose_landmarker_heavy.task"
		1:
			return "pose_landmarker_full.task"
		_:
			return "pose_landmarker_lite.task"

static func _normalize_model_complexity(value: Variant) -> int:
	var parsed := int(value)
	if parsed < 0 or parsed > 2:
		return DEFAULT_MODEL_COMPLEXITY
	return parsed

static func _normalize_nonnegative_int(value: Variant, default_value: int) -> int:
	var parsed := int(value)
	if parsed < 0:
		return default_value
	return parsed

static func _normalize_positive_int(value: Variant, default_value: int) -> int:
	var parsed := int(value)
	if parsed <= 0:
		return default_value
	return parsed

static func _normalize_quality(value: Variant, default_value: int) -> int:
	var parsed := int(value)
	if parsed < 1 or parsed > 100:
		return default_value
	return parsed

static func _deep_merge(base: Dictionary, incoming: Dictionary) -> void:
	for key in incoming.keys():
		var incoming_value: Variant = incoming[key]
		if base.has(key) and base[key] is Dictionary and incoming_value is Dictionary:
			_deep_merge(base[key], incoming_value)
		else:
			base[key] = incoming_value

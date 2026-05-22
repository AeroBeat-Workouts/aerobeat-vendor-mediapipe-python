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
			"min_visibility": DEFAULT_MIN_VISIBILITY
		},
		"preview": {
			"enabled": true,
			"surface_mode": DEFAULT_SURFACE_MODE,
			"flip_horizontal": true
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
			"min_visibility": DEFAULT_MIN_VISIBILITY
		},
		"preview": {
			"enabled": true,
			"surface_mode": DEFAULT_SURFACE_MODE,
			"flip_horizontal": true
		},
		"runtime": {
			"python_executable": DEFAULT_PYTHON_EXECUTABLE,
			"entrypoint": DEFAULT_RUNTIME_ENTRYPOINT,
			"working_directory": "",
			"arguments": [],
			"environment": {},
			"boot_timeout_ms": DEFAULT_BOOT_TIMEOUT_MS,
			"shutdown_timeout_ms": DEFAULT_SHUTDOWN_TIMEOUT_MS,
			"health_poll_interval_ms": DEFAULT_HEALTH_POLL_INTERVAL_MS
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

	vendor_config["backend"] = BACKEND_ID
	return vendor_config

static func _deep_merge(base: Dictionary, incoming: Dictionary) -> void:
	for key in incoming.keys():
		var incoming_value: Variant = incoming[key]
		if base.has(key) and base[key] is Dictionary and incoming_value is Dictionary:
			_deep_merge(base[key], incoming_value)
		else:
			base[key] = incoming_value

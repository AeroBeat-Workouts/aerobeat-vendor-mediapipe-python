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
const DEFAULT_TRACKING_MAX_FPS := 15
const DEFAULT_STATE_UPDATE_MAX_FPS := 15
const DEFAULT_PREVIEW_MAX_FPS := 10
const DEFAULT_PREVIEW_WIDTH := 960
const DEFAULT_PREVIEW_HEIGHT := 540
const DEFAULT_PREVIEW_QUALITY := 75
const DEFAULT_LIVE_CAMERA_FOURCC := "MJPG"
const DEFAULT_HAND_LANDMARK_MODE := "lite"
const DEFAULT_HAND_INFERENCE_INTERVAL_FRAMES := 1
const DEFAULT_HAND_VALIDITY_MAX_STALE_MS := 80
const DEFAULT_HAND_VALIDITY_REACQUIRE_STABLE_MS := 40

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
			"max_fps": DEFAULT_TRACKING_MAX_FPS,
			"hands": {
				"enabled": false,
				"landmark_mode": DEFAULT_HAND_LANDMARK_MODE,
				"inference_interval_frames": DEFAULT_HAND_INFERENCE_INTERVAL_FRAMES,
				"bbox": {
					"enabled": true
				},
				"validity": {
					"max_stale_ms": DEFAULT_HAND_VALIDITY_MAX_STALE_MS,
					"reacquire_stable_ms": DEFAULT_HAND_VALIDITY_REACQUIRE_STABLE_MS
				}
			}
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
			"max_fps": DEFAULT_TRACKING_MAX_FPS,
			"hands": {
				"enabled": false,
				"landmark_mode": DEFAULT_HAND_LANDMARK_MODE,
				"inference_interval_frames": DEFAULT_HAND_INFERENCE_INTERVAL_FRAMES,
				"bbox": {
					"enabled": true
				},
				"validity": {
					"max_stale_ms": DEFAULT_HAND_VALIDITY_MAX_STALE_MS,
					"reacquire_stable_ms": DEFAULT_HAND_VALIDITY_REACQUIRE_STABLE_MS
				}
			}
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
			"hand_landmarker_model_path": "",
			"hand_tracking_enabled": false,
			"hand_landmark_mode": DEFAULT_HAND_LANDMARK_MODE,
			"hand_inference_interval_frames": DEFAULT_HAND_INFERENCE_INTERVAL_FRAMES,
			"hand_bbox_enabled": true,
			"hand_max_stale_ms": DEFAULT_HAND_VALIDITY_MAX_STALE_MS,
			"hand_reacquire_stable_ms": DEFAULT_HAND_VALIDITY_REACQUIRE_STABLE_MS,
			"boot_timeout_ms": DEFAULT_BOOT_TIMEOUT_MS,
			"shutdown_timeout_ms": DEFAULT_SHUTDOWN_TIMEOUT_MS,
			"health_poll_interval_ms": DEFAULT_HEALTH_POLL_INTERVAL_MS,
			"tracking_max_fps": DEFAULT_TRACKING_MAX_FPS,
			"state_update_max_fps": DEFAULT_STATE_UPDATE_MAX_FPS,
			"filter_enabled": true,
			"no_filter": false,
			"preview_enabled": true,
			"preview_max_fps": DEFAULT_PREVIEW_MAX_FPS,
			"preview_width": DEFAULT_PREVIEW_WIDTH,
			"preview_height": DEFAULT_PREVIEW_HEIGHT,
			"preview_quality": DEFAULT_PREVIEW_QUALITY,
			"live_camera_width": DEFAULT_PREVIEW_WIDTH,
			"live_camera_height": DEFAULT_PREVIEW_HEIGHT,
			"live_camera_fps": DEFAULT_TRACKING_MAX_FPS,
			"live_camera_fourcc": DEFAULT_LIVE_CAMERA_FOURCC
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
	var tracking: Dictionary = normalized.get("tracking", {})
	var incoming_tracking: Dictionary = config["tracking"] if config.has("tracking") else {}
	tracking["quality"] = _normalize_tracking_quality(
		tracking.get("quality", DEFAULT_TRACKING_QUALITY),
		tracking.get("overlay_mode", DEFAULT_OVERLAY_MODE)
	)
	tracking["overlay_mode"] = _normalize_overlay_mode(
		tracking.get("overlay_mode", DEFAULT_OVERLAY_MODE)
	)
	tracking["max_fps"] = _normalize_nonnegative_int(
		tracking.get("max_fps", DEFAULT_TRACKING_MAX_FPS),
		DEFAULT_TRACKING_MAX_FPS
	)
	tracking["hands"] = _normalize_hands_config(incoming_tracking["hands"] if incoming_tracking.has("hands") else tracking.get("hands", {}))
	normalized["tracking"] = tracking
	var preview: Dictionary = normalized.get("preview", {})
	preview["enabled"] = bool(preview.get("enabled", true))
	preview["max_fps"] = _normalize_nonnegative_int(
		preview.get("max_fps", DEFAULT_PREVIEW_MAX_FPS),
		DEFAULT_PREVIEW_MAX_FPS
	)
	preview["width"] = _normalize_positive_int(
		preview.get("width", DEFAULT_PREVIEW_WIDTH),
		DEFAULT_PREVIEW_WIDTH
	)
	preview["height"] = _normalize_positive_int(
		preview.get("height", DEFAULT_PREVIEW_HEIGHT),
		DEFAULT_PREVIEW_HEIGHT
	)
	preview["quality"] = _normalize_quality(
		preview.get("quality", DEFAULT_PREVIEW_QUALITY),
		DEFAULT_PREVIEW_QUALITY
	)
	normalized["preview"] = preview
	return normalized

static func make_vendor_runtime_config(public_config: Dictionary = {}) -> Dictionary:
	var normalized_public := normalize_public_config(public_config)
	var vendor_config := vendor_defaults()
	vendor_config["source"] = normalized_public.get("source", {}).duplicate(true)
	vendor_config["tracking"] = normalized_public.get("tracking", {}).duplicate(true)
	vendor_config["preview"] = normalized_public.get("preview", {}).duplicate(true)
	vendor_config["backend"] = BACKEND_ID

	if public_config.has("tracking"):
		_deep_merge(vendor_config["tracking"], public_config["tracking"])
	if public_config.has("runtime"):
		_deep_merge(vendor_config["runtime"], public_config["runtime"])
	if public_config.has("diagnostics"):
		_deep_merge(vendor_config["diagnostics"], public_config["diagnostics"])
	if public_config.has("vendor"):
		_deep_merge(vendor_config, public_config["vendor"])

	var tracking: Dictionary = vendor_config.get("tracking", {})
	var preview: Dictionary = vendor_config.get("preview", {})
	var runtime: Dictionary = vendor_config.get("runtime", {})
	var incoming_tracking: Dictionary = public_config["tracking"] if public_config.has("tracking") else {}
	var incoming_runtime: Dictionary = public_config["runtime"] if public_config.has("runtime") else {}

	runtime["model_complexity"] = _normalize_model_complexity(runtime.get("model_complexity", DEFAULT_MODEL_COMPLEXITY))
	tracking["quality"] = _normalize_tracking_quality(
		tracking.get("quality", DEFAULT_TRACKING_QUALITY),
		tracking.get("overlay_mode", DEFAULT_OVERLAY_MODE)
	)
	tracking["overlay_mode"] = _normalize_overlay_mode(tracking.get("overlay_mode", DEFAULT_OVERLAY_MODE))
	tracking["hands"] = _normalize_hands_config(incoming_tracking["hands"] if incoming_tracking.has("hands") else tracking.get("hands", {}))
	var hands: Dictionary = tracking.get("hands", {})
	if incoming_runtime.has("hand_tracking_enabled"):
		runtime["hand_tracking_enabled"] = bool(incoming_runtime.get("hand_tracking_enabled", false))
	else:
		runtime["hand_tracking_enabled"] = bool(hands.get("enabled", false))
	if incoming_runtime.has("hand_landmark_mode"):
		runtime["hand_landmark_mode"] = _normalize_hand_landmark_mode(incoming_runtime.get("hand_landmark_mode", DEFAULT_HAND_LANDMARK_MODE))
	else:
		runtime["hand_landmark_mode"] = _normalize_hand_landmark_mode(hands.get("landmark_mode", DEFAULT_HAND_LANDMARK_MODE))
	runtime["hand_inference_interval_frames"] = _normalize_positive_int(
		incoming_runtime.get("hand_inference_interval_frames", hands.get("inference_interval_frames", DEFAULT_HAND_INFERENCE_INTERVAL_FRAMES)),
		DEFAULT_HAND_INFERENCE_INTERVAL_FRAMES
	)
	runtime.erase("hand_bbox_recompute_interval_frames")
	if incoming_runtime.has("hand_bbox_enabled"):
		runtime["hand_bbox_enabled"] = bool(incoming_runtime.get("hand_bbox_enabled", true))
	else:
		runtime["hand_bbox_enabled"] = bool(hands.get("bbox", {}).get("enabled", true))
	runtime["hand_max_stale_ms"] = _normalize_nonnegative_int(
		incoming_runtime.get("hand_max_stale_ms", incoming_runtime.get("hand_max_stale_frames", hands.get("validity", {}).get("max_stale_ms", hands.get("validity", {}).get("max_stale_frames", DEFAULT_HAND_VALIDITY_MAX_STALE_MS)))),
		DEFAULT_HAND_VALIDITY_MAX_STALE_MS
	)
	runtime["hand_reacquire_stable_ms"] = _normalize_nonnegative_int(
		incoming_runtime.get("hand_reacquire_stable_ms", incoming_runtime.get("hand_reacquire_stable_frames", hands.get("validity", {}).get("reacquire_stable_ms", hands.get("validity", {}).get("reacquire_stable_frames", DEFAULT_HAND_VALIDITY_REACQUIRE_STABLE_MS)))),
		DEFAULT_HAND_VALIDITY_REACQUIRE_STABLE_MS
	)
	runtime.erase("hand_max_stale_frames")
	runtime.erase("hand_reacquire_stable_frames")
	hands["enabled"] = bool(runtime.get("hand_tracking_enabled", false))
	hands["landmark_mode"] = String(runtime.get("hand_landmark_mode", DEFAULT_HAND_LANDMARK_MODE))
	hands["inference_interval_frames"] = int(runtime.get("hand_inference_interval_frames", DEFAULT_HAND_INFERENCE_INTERVAL_FRAMES))
	hands.erase("bbox_recompute_interval_frames")
	hands["bbox"] = {"enabled": bool(runtime.get("hand_bbox_enabled", true))}
	hands["validity"] = {
		"max_stale_ms": int(runtime.get("hand_max_stale_ms", DEFAULT_HAND_VALIDITY_MAX_STALE_MS)),
		"reacquire_stable_ms": int(runtime.get("hand_reacquire_stable_ms", DEFAULT_HAND_VALIDITY_REACQUIRE_STABLE_MS))
	}
	tracking["hands"] = hands
	if incoming_runtime.has("no_filter"):
		runtime["filter_enabled"] = not bool(incoming_runtime.get("no_filter", false))
	else:
		runtime["filter_enabled"] = bool(runtime.get("filter_enabled", true))
	runtime["no_filter"] = not bool(runtime.get("filter_enabled", true))
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
	runtime["live_camera_width"] = _normalize_positive_int(
		runtime.get("live_camera_width", runtime.get("preview_width", preview.get("width", DEFAULT_PREVIEW_WIDTH))),
		DEFAULT_PREVIEW_WIDTH
	)
	runtime["live_camera_height"] = _normalize_positive_int(
		runtime.get("live_camera_height", runtime.get("preview_height", preview.get("height", DEFAULT_PREVIEW_HEIGHT))),
		DEFAULT_PREVIEW_HEIGHT
	)
	runtime["live_camera_fps"] = _normalize_nonnegative_int(
		runtime.get("live_camera_fps", runtime.get("tracking_max_fps", tracking.get("max_fps", DEFAULT_TRACKING_MAX_FPS))),
		DEFAULT_TRACKING_MAX_FPS
	)
	runtime["live_camera_fourcc"] = str(runtime.get("live_camera_fourcc", DEFAULT_LIVE_CAMERA_FOURCC)).strip_edges().to_upper()
	if runtime["live_camera_fourcc"] == "":
		runtime["live_camera_fourcc"] = DEFAULT_LIVE_CAMERA_FOURCC
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

static func _normalize_tracking_quality(value: Variant, overlay_mode: Variant = DEFAULT_OVERLAY_MODE) -> String:
	var normalized := str(value).strip_edges().to_lower()
	match normalized:
		"simple", "optimized":
			return "optimized"
		"full":
			return "full"
		"raw":
			return "full"
		"off":
			return _normalize_tracking_quality(DEFAULT_TRACKING_QUALITY, DEFAULT_OVERLAY_MODE)
		_:
			var overlay_normalized := str(overlay_mode).strip_edges().to_lower()
			if overlay_normalized == "full":
				return "full"
			if ["simple", "optimized"].has(overlay_normalized):
				return "optimized"
			return DEFAULT_TRACKING_QUALITY

static func _normalize_overlay_mode(value: Variant) -> String:
	var normalized := str(value).strip_edges().to_lower()
	match normalized:
		"full":
			return "full"
		"simple", "optimized":
			return "optimized"
		"off", "none", "hidden":
			return "off"
		_:
			return DEFAULT_OVERLAY_MODE

static func _normalize_hand_landmark_mode(value: Variant) -> String:
	var normalized := str(value).strip_edges().to_lower()
	match normalized:
		"full":
			return "full"
		_:
			return DEFAULT_HAND_LANDMARK_MODE

static func _normalize_hands_config(value: Variant) -> Dictionary:
	var defaults: Dictionary = {}
	var default_tracking: Dictionary = public_defaults().get("tracking", {})
	if typeof(default_tracking.get("hands", {})) == TYPE_DICTIONARY:
		defaults = default_tracking.get("hands", {}).duplicate(true)
	if typeof(value) == TYPE_DICTIONARY:
		_deep_merge(defaults, value)
	defaults["enabled"] = bool(defaults.get("enabled", false))
	defaults["landmark_mode"] = _normalize_hand_landmark_mode(defaults.get("landmark_mode", DEFAULT_HAND_LANDMARK_MODE))
	defaults["inference_interval_frames"] = _normalize_positive_int(
		defaults.get("inference_interval_frames", DEFAULT_HAND_INFERENCE_INTERVAL_FRAMES),
		DEFAULT_HAND_INFERENCE_INTERVAL_FRAMES
	)
	defaults.erase("bbox_recompute_interval_frames")
	if not (defaults.get("bbox", {}) is Dictionary):
		defaults["bbox"] = {"enabled": true}
	defaults["bbox"]["enabled"] = bool(defaults.get("bbox", {}).get("enabled", true))
	if not (defaults.get("validity", {}) is Dictionary):
		defaults["validity"] = {}
	defaults["validity"]["max_stale_ms"] = _normalize_nonnegative_int(
		defaults.get("validity", {}).get("max_stale_ms", defaults.get("validity", {}).get("max_stale_frames", DEFAULT_HAND_VALIDITY_MAX_STALE_MS)),
		DEFAULT_HAND_VALIDITY_MAX_STALE_MS
	)
	defaults["validity"]["reacquire_stable_ms"] = _normalize_nonnegative_int(
		defaults.get("validity", {}).get("reacquire_stable_ms", defaults.get("validity", {}).get("reacquire_stable_frames", DEFAULT_HAND_VALIDITY_REACQUIRE_STABLE_MS)),
		DEFAULT_HAND_VALIDITY_REACQUIRE_STABLE_MS
	)
	defaults["validity"].erase("max_stale_frames")
	defaults["validity"].erase("reacquire_stable_frames")
	return defaults

static func _deep_merge(base: Dictionary, incoming: Dictionary) -> void:
	for key in incoming.keys():
		var incoming_value: Variant = incoming[key]
		if base.has(key) and base[key] is Dictionary and incoming_value is Dictionary:
			_deep_merge(base[key], incoming_value)
		else:
			base[key] = incoming_value

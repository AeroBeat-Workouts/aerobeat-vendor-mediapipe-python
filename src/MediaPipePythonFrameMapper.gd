extends RefCounted

const CameraTrackingFrame = preload("res://addons/aerobeat-tool-camera-tracking/src/CameraTrackingFrame.gd")
const MediaPipePythonConfig = preload("MediaPipePythonConfig.gd")
const DEFAULT_BACKEND_REQUEST := "camera_tracking_default"

static func empty(config: Dictionary = {}) -> Dictionary:
	var frame := CameraTrackingFrame.empty(config)
	frame["backend"] = MediaPipePythonConfig.BACKEND_ID
	frame["backend_request"] = _normalize_requested_backend(config.get("backend", DEFAULT_BACKEND_REQUEST))
	frame["backend_impl"] = MediaPipePythonConfig.BACKEND_ID
	return frame

static func map_raw_frame(raw_frame: Dictionary, config: Dictionary = {}) -> Dictionary:
	var frame := empty(config)
	for key in raw_frame.keys():
		frame[key] = raw_frame[key]
	if raw_frame.has("frame_index") == false:
		frame.erase("frame_index")
	if raw_frame.has("timestamp_seconds") == false:
		frame.erase("timestamp_seconds")
	frame["backend"] = MediaPipePythonConfig.BACKEND_ID
	frame["backend_request"] = _normalize_requested_backend(config.get("backend", DEFAULT_BACKEND_REQUEST))
	frame["backend_impl"] = MediaPipePythonConfig.BACKEND_ID
	if raw_frame.has("preview_transform") == false:
		frame["preview_transform"] = frame.get("preview_transform", {}).duplicate(true)
		frame["preview_transform"]["flip_horizontal"] = bool(
			MediaPipePythonConfig.normalize_public_config(config).get("preview", {}).get("flip_horizontal", true)
		)
	return frame

static func _normalize_requested_backend(backend_id: Variant) -> String:
	var normalized := str(backend_id).strip_edges()
	return normalized if normalized != "" else DEFAULT_BACKEND_REQUEST

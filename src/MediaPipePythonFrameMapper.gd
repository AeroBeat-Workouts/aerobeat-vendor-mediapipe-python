extends RefCounted

const CameraTrackingFrame = preload("res://addons/aerobeat-tool-camera-tracking/src/CameraTrackingFrame.gd")
const MediaPipePythonConfig = preload("MediaPipePythonConfig.gd")

static func empty(config: Dictionary = {}) -> Dictionary:
	var frame := CameraTrackingFrame.empty(MediaPipePythonConfig.normalize_public_config(config))
	frame["backend"] = MediaPipePythonConfig.BACKEND_ID
	return frame

static func map_raw_frame(raw_frame: Dictionary, config: Dictionary = {}) -> Dictionary:
	var frame := empty(config)
	for key in raw_frame.keys():
		frame[key] = raw_frame[key]
	frame["backend"] = MediaPipePythonConfig.BACKEND_ID
	if raw_frame.has("preview_transform") == false:
		frame["preview_transform"] = frame.get("preview_transform", {}).duplicate(true)
		frame["preview_transform"]["flip_horizontal"] = bool(
			MediaPipePythonConfig.normalize_public_config(config).get("preview", {}).get("flip_horizontal", true)
		)
	return frame

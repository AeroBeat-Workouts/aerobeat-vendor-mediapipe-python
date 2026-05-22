extends RefCounted

const MediaPipePythonConfig = preload("MediaPipePythonConfig.gd")

static func normalize(raw_cameras: Array, backend: String = MediaPipePythonConfig.BACKEND_ID) -> Array:
	var normalized: Array = []
	for raw_camera in raw_cameras:
		normalized.append(_normalize_camera(raw_camera, backend))
	return normalized

static func _normalize_camera(raw_camera: Variant, backend: String) -> Dictionary:
	if raw_camera is Dictionary:
		var camera: Dictionary = raw_camera.duplicate(true)
		camera["camera_id"] = str(camera.get("camera_id", camera.get("id", "")))
		camera["label"] = str(camera.get("label", camera["camera_id"]))
		camera["backend"] = str(camera.get("backend", backend))
		camera["source_kind"] = str(camera.get("source_kind", "live_camera"))
		camera["available"] = bool(camera.get("available", true))
		if camera.has("metadata") == false:
			camera["metadata"] = {}
		return camera
	return {
		"camera_id": str(raw_camera),
		"label": str(raw_camera),
		"backend": backend,
		"source_kind": "live_camera",
		"available": true,
		"metadata": {}
	}

extends RefCounted

const MediaPipePythonRuntimeHealth = preload("MediaPipePythonRuntimeHealth.gd")

func startup(_vendor_config: Dictionary) -> Dictionary:
	return {
		"ok": false,
		"health": MediaPipePythonRuntimeHealth.unavailable(),
		"cameras": [],
		"preview_descriptor": {},
		"raw_tracking_frame": {},
		"error_info": {
			"code": "runtime_bridge_unimplemented",
			"message": "MediaPipe Python runtime bridge is not implemented yet"
		}
	}

func shutdown() -> Dictionary:
	return {
		"ok": true,
		"health": MediaPipePythonRuntimeHealth.idle({
			"process_active": false,
			"camera_accessible": false,
			"tracking_active": false
		})
	}

func reconfigure(vendor_config: Dictionary) -> Dictionary:
	return startup(vendor_config)

func list_cameras() -> Array:
	return []

func poll_health() -> Dictionary:
	return MediaPipePythonRuntimeHealth.unavailable()

extends "res://addons/aerobeat-tool-camera-tracking/src/CameraTrackingBackend.gd"

const CameraTracking = preload("res://addons/aerobeat-tool-camera-tracking/src/CameraTracking.gd")
const CameraTrackingConfig = preload("res://addons/aerobeat-tool-camera-tracking/src/CameraTrackingConfig.gd")
const CameraTrackingPreview = preload("res://addons/aerobeat-tool-camera-tracking/src/CameraTrackingPreview.gd")
const MediaPipePythonConfig = preload("MediaPipePythonConfig.gd")
const MediaPipePythonRuntimeBridge = preload("MediaPipePythonRuntimeBridge.gd")
const MediaPipePythonRuntimeHealth = preload("MediaPipePythonRuntimeHealth.gd")
const MediaPipePythonFrameMapper = preload("MediaPipePythonFrameMapper.gd")
const MediaPipePythonCameraInventory = preload("MediaPipePythonCameraInventory.gd")

var _bridge = null
var _state: String = CameraTracking.STATE_IDLE
var _detail: Dictionary = CameraTrackingConfig.make_state_detail()
var _active_config: Dictionary = CameraTrackingConfig.defaults()
var _vendor_runtime_config: Dictionary = MediaPipePythonConfig.make_vendor_runtime_config()
var _tracking_frame: Dictionary = MediaPipePythonFrameMapper.empty(_active_config)
var _preview_descriptor: Dictionary = _make_preview_descriptor({})
var _playback_status: Dictionary = {}
var _runtime_health: Dictionary = MediaPipePythonRuntimeHealth.unavailable()
var _cameras: Array = []

func set_runtime_bridge(bridge) -> void:
	_bridge = bridge
	_runtime_health = MediaPipePythonRuntimeHealth.make({
		"status": MediaPipePythonRuntimeHealth.STATUS_IDLE if bridge != null else MediaPipePythonRuntimeHealth.STATUS_UNAVAILABLE,
		"bridge_connected": bridge != null,
		"runtime_available": bridge != null,
		"notes": [] if bridge != null else ["No MediaPipe Python runtime bridge attached"]
	})

func get_vendor_runtime_config() -> Dictionary:
	return _vendor_runtime_config.duplicate(true)

func get_runtime_health() -> Dictionary:
	_refresh_runtime_snapshot_if_running()
	return _runtime_health.duplicate(true)

func start(config: Dictionary) -> void:
	_active_config = CameraTrackingConfig.normalize(config)
	_vendor_runtime_config = MediaPipePythonConfig.make_vendor_runtime_config(_active_config)
	_tracking_frame = MediaPipePythonFrameMapper.empty(_active_config)
	_preview_descriptor = _make_preview_descriptor({})
	_state = CameraTracking.STATE_STARTING
	_detail = CameraTrackingConfig.make_state_detail()
	emit_signal("state_changed", _state, _detail.duplicate(true))
	if _bridge == null:
		_fail_with({
			"code": "runtime_bridge_missing",
			"message": "No MediaPipe Python runtime bridge has been attached",
			"backend": MediaPipePythonConfig.BACKEND_ID
		})
		return
	_runtime_health = MediaPipePythonRuntimeHealth.starting()
	_apply_runtime_snapshot(_bridge.startup(_vendor_runtime_config), CameraTracking.STATE_RUNNING)

func stop() -> void:
	_state = CameraTracking.STATE_STOPPING
	_detail = _make_state_detail()
	emit_signal("state_changed", _state, _detail.duplicate(true))
	var snapshot: Dictionary = _bridge.shutdown() if _bridge != null else {
		"ok": true,
		"health": MediaPipePythonRuntimeHealth.idle({
			"bridge_connected": false,
			"runtime_available": false
		})
	}
	_runtime_health = MediaPipePythonRuntimeHealth.make(snapshot.get("health", {}))
	_tracking_frame = MediaPipePythonFrameMapper.empty(_active_config)
	_preview_descriptor = _make_preview_descriptor({})
	_playback_status = {}
	_state = CameraTracking.STATE_IDLE
	_detail = CameraTrackingConfig.make_state_detail()
	emit_signal("preview_changed", _preview_descriptor.duplicate(true))
	emit_signal("state_changed", _state, _detail.duplicate(true))

func change(config: Dictionary) -> void:
	_active_config = CameraTrackingConfig.normalize(config)
	_vendor_runtime_config = MediaPipePythonConfig.make_vendor_runtime_config(_active_config)
	_tracking_frame = MediaPipePythonFrameMapper.empty(_active_config)
	_preview_descriptor = _make_preview_descriptor({})
	_state = CameraTracking.STATE_RESTARTING
	_detail = CameraTrackingConfig.make_state_detail({
		CameraTracking.DETAIL_SOURCE_READY: _source_declared()
	})
	emit_signal("state_changed", _state, _detail.duplicate(true))
	if _bridge == null:
		_fail_with({
			"code": "runtime_bridge_missing",
			"message": "No MediaPipe Python runtime bridge has been attached",
			"backend": MediaPipePythonConfig.BACKEND_ID
		})
		return
	_runtime_health = MediaPipePythonRuntimeHealth.starting()
	_apply_runtime_snapshot(_bridge.reconfigure(_vendor_runtime_config), CameraTracking.STATE_RUNNING)

func list_cameras() -> Array:
	_refresh_runtime_snapshot_if_running()
	if _bridge != null and _cameras.is_empty():
		_cameras = MediaPipePythonCameraInventory.normalize(_bridge.list_cameras())
	return _cameras.duplicate(true)

func get_state() -> Dictionary:
	_refresh_runtime_snapshot_if_running()
	return {
		"state": _state,
		"detail": _detail.duplicate(true)
	}

func get_tracking_frame() -> Dictionary:
	_refresh_runtime_snapshot_if_running()
	return _tracking_frame.duplicate(true)

func get_preview_descriptor() -> Dictionary:
	_refresh_runtime_snapshot_if_running()
	return _preview_descriptor.duplicate(true)

func get_playback_status() -> Dictionary:
	_refresh_runtime_snapshot_if_running()
	return _playback_status.duplicate(true)

func _refresh_runtime_snapshot_if_running() -> void:
	if _bridge == null:
		return
	if _state != CameraTracking.STATE_RUNNING:
		return
	if not _bridge.has_method("poll_snapshot"):
		return
	var snapshot: Dictionary = _bridge.poll_snapshot()
	if snapshot.is_empty():
		return
	if bool(snapshot.get("ok", false)) == false:
		var error_info: Dictionary = snapshot.get("error_info", {
			"code": "runtime_poll_failed",
			"message": "MediaPipe Python runtime poll failed",
			"backend": MediaPipePythonConfig.BACKEND_ID
		})
		_runtime_health = MediaPipePythonRuntimeHealth.errored(error_info, snapshot.get("health", {}))
		_detail = _make_state_detail()
		_state = CameraTracking.STATE_ERROR
		return
	_runtime_health = MediaPipePythonRuntimeHealth.make(snapshot.get("health", {}))
	_cameras = MediaPipePythonCameraInventory.normalize(snapshot.get("cameras", []))
	_tracking_frame = MediaPipePythonFrameMapper.map_raw_frame(snapshot.get("raw_tracking_frame", {}), _active_config)
	_preview_descriptor = _make_preview_descriptor(snapshot.get("preview_descriptor", {}))
	_playback_status = snapshot.get("playback_status", {}).duplicate(true)
	_detail = _make_state_detail()

func _apply_runtime_snapshot(snapshot: Dictionary, success_state: String) -> void:
	if bool(snapshot.get("ok", false)) == false:
		var error_info: Dictionary = snapshot.get("error_info", {
			"code": "runtime_start_failed",
			"message": "MediaPipe Python runtime bootstrap failed",
			"backend": MediaPipePythonConfig.BACKEND_ID
		})
		_runtime_health = MediaPipePythonRuntimeHealth.errored(error_info, snapshot.get("health", {}))
		_fail_with(error_info)
		return

	_runtime_health = MediaPipePythonRuntimeHealth.make(snapshot.get("health", {}))
	_cameras = MediaPipePythonCameraInventory.normalize(snapshot.get("cameras", []))
	_tracking_frame = MediaPipePythonFrameMapper.map_raw_frame(snapshot.get("raw_tracking_frame", {}), _active_config)
	_preview_descriptor = _make_preview_descriptor(snapshot.get("preview_descriptor", {}))
	_playback_status = snapshot.get("playback_status", {}).duplicate(true)
	_detail = _make_state_detail()
	_state = success_state
	emit_signal("preview_changed", _preview_descriptor.duplicate(true))
	emit_signal("tracking_updated", _tracking_frame.duplicate(true))
	emit_signal("cameras_changed", _cameras.duplicate(true))
	emit_signal("state_changed", _state, _detail.duplicate(true))

func _fail_with(error_info: Dictionary) -> void:
	_state = CameraTracking.STATE_ERROR
	_detail = _make_state_detail()
	emit_signal("state_changed", _state, _detail.duplicate(true))
	emit_signal("error_raised", error_info.duplicate(true))

func _make_preview_descriptor(overrides: Dictionary) -> Dictionary:
	var descriptor := CameraTrackingPreview.detached(_active_config)
	descriptor["backend"] = MediaPipePythonConfig.BACKEND_ID
	for key in overrides.keys():
		descriptor[key] = overrides[key]
	return descriptor

func _make_state_detail() -> Dictionary:
	var preview_enabled := bool(_active_config.get("preview", {}).get("enabled", true))
	return CameraTrackingConfig.make_state_detail({
		CameraTracking.DETAIL_BACKEND_READY: bool(_runtime_health.get("bridge_connected", false)) and bool(_runtime_health.get("runtime_available", false)),
		CameraTracking.DETAIL_PREVIEW_READY: preview_enabled and bool(_preview_descriptor.get("enabled", preview_enabled)),
		CameraTracking.DETAIL_TRACKING_READY: bool(_runtime_health.get("tracking_active", false)),
		CameraTracking.DETAIL_SOURCE_READY: _source_ready()
	})

func _source_ready() -> bool:
	var source: Dictionary = _active_config.get("source", {})
	if str(source.get("kind", MediaPipePythonConfig.DEFAULT_SOURCE_KIND)) == "video_file":
		return str(source.get("path", "")) != ""
	return bool(_runtime_health.get("camera_accessible", false)) or not _cameras.is_empty()

func _source_declared() -> bool:
	var source: Dictionary = _active_config.get("source", {})
	if str(source.get("kind", MediaPipePythonConfig.DEFAULT_SOURCE_KIND)) == "video_file":
		return str(source.get("path", "")) != ""
	return str(source.get("camera_id", "")) != ""

extends RefCounted

const STATUS_IDLE := "idle"
const STATUS_STARTING := "starting"
const STATUS_RUNNING := "running"
const STATUS_STOPPING := "stopping"
const STATUS_ERROR := "error"
const STATUS_UNAVAILABLE := "unavailable"

static func make(overrides: Dictionary = {}) -> Dictionary:
	var health := {
		"status": STATUS_IDLE,
		"backend": MediaPipePythonConfig.BACKEND_ID,
		"runtime_available": false,
		"bridge_connected": false,
		"process_active": false,
		"camera_accessible": false,
		"tracking_active": false,
		"healthy": false,
		"last_error": {},
		"notes": []
	}
	_deep_merge(health, overrides)
	if not health.has("healthy") or overrides.has("healthy") == false:
		health["healthy"] = health.get("status", STATUS_IDLE) == STATUS_RUNNING and bool(health.get("runtime_available", false))
	return health

static func idle(overrides: Dictionary = {}) -> Dictionary:
	var next := make({
		"status": STATUS_IDLE,
		"bridge_connected": true,
		"runtime_available": true
	})
	_deep_merge(next, overrides)
	return next

static func starting(overrides: Dictionary = {}) -> Dictionary:
	var next := make({
		"status": STATUS_STARTING,
		"bridge_connected": true,
		"runtime_available": true
	})
	_deep_merge(next, overrides)
	return next

static func running(overrides: Dictionary = {}) -> Dictionary:
	var next := make({
		"status": STATUS_RUNNING,
		"bridge_connected": true,
		"runtime_available": true,
		"process_active": true,
		"healthy": true
	})
	_deep_merge(next, overrides)
	return next

static func stopping(overrides: Dictionary = {}) -> Dictionary:
	var next := make({
		"status": STATUS_STOPPING,
		"bridge_connected": true,
		"runtime_available": true,
		"process_active": true
	})
	_deep_merge(next, overrides)
	return next

static func unavailable(overrides: Dictionary = {}) -> Dictionary:
	var next := make({
		"status": STATUS_UNAVAILABLE,
		"notes": ["No MediaPipe Python runtime bridge attached"]
	})
	_deep_merge(next, overrides)
	return next

static func errored(error_info: Dictionary, overrides: Dictionary = {}) -> Dictionary:
	var next := make({
		"status": STATUS_ERROR,
		"last_error": error_info.duplicate(true),
		"notes": [error_info.get("message", "MediaPipe Python runtime error")]
	})
	_deep_merge(next, overrides)
	return next

static func _deep_merge(base: Dictionary, incoming: Dictionary) -> void:
	for key in incoming.keys():
		var incoming_value: Variant = incoming[key]
		if base.has(key) and base[key] is Dictionary and incoming_value is Dictionary:
			_deep_merge(base[key], incoming_value)
		else:
			base[key] = incoming_value

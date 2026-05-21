## Base template for a Tool Manager.
##
## This class serves as the main entry point for the tool service.
## It is intended to be used as an Autoload (Singleton) or a static helper.
class_name AeroToolManager
extends Node

#region SIGNALS
## Emitted when the tool has finished initializing.
signal initialized
#endregion

#region ENUMS & CONSTANTS
const VERSION: String = "0.0.1"
#endregion

#region EXPORTS
@export var is_active: bool = true
#endregion

#region PRIVATE VARIABLES
var _is_initialized: bool = false
#endregion

#region LIFECYCLE
func _ready() -> void:
	_initialize()

func _initialize() -> void:
	if _is_initialized:
		return
	
	# TODO: Add initialization logic here
	_is_initialized = true
	initialized.emit()
	print("AeroToolManager initialized.")
#endregion
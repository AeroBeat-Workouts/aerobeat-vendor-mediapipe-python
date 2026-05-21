extends GutTest

func test_tool_manager_defaults_stay_template_safe() -> void:
	var manager := AeroToolManager.new()
	assert_eq(AeroToolManager.VERSION, "0.0.1", "Template stub version should stay explicit")
	assert_true(manager.is_active, "Template stub should default to active")
	assert_false(manager._is_initialized, "Template stub should start uninitialized before setup runs")
	manager.free()

func test_tool_manager_initialize_marks_initialized() -> void:
	var manager := AeroToolManager.new()
	manager._initialize()
	assert_true(manager._is_initialized, "Template stub initialize path should mark the tool initialized")
	manager.free()

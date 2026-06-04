extends GutTest

const README_PATH := "../README.md"
const PLUGIN_CFG_PATH := "../plugin.cfg"
const ADDONS_MANIFEST_PATH := "addons.jsonc"
const EXPECTED_PLUGIN_NAME := "AeroBeat Vendor MediaPipe Python"

func _read_repo_file(relative_path: String) -> String:
	var absolute_path := ProjectSettings.globalize_path("res://%s" % relative_path)
	assert_true(FileAccess.file_exists(absolute_path), "Expected repo file to exist: %s" % absolute_path)
	var file := FileAccess.open(absolute_path, FileAccess.READ)
	assert_true(file != null, "Expected repo file to open: %s" % absolute_path)
	return file.get_as_text()

func test_readme_states_vendor_wrapper_truth() -> void:
	var readme_text := _read_repo_file(README_PATH)
	assert_true(readme_text.contains("vendor-owned MediaPipe Python backend/wrapper shell"), "README should describe the vendor-wrapper shell truth")
	assert_true(readme_text.contains("aerobeat-tool-camera-tracking"), "README should name the upstream contract owner")
	assert_true(readme_text.contains("startup/shutdown seam"), "README should describe vendor-owned startup/shutdown seams")
	assert_true(readme_text.contains("normalized public tracking payloads"), "README should keep normalized payload ownership upstream")

func test_plugin_cfg_is_vendor_specific() -> void:
	var config := ConfigFile.new()
	var error := config.load(ProjectSettings.globalize_path("res://%s" % PLUGIN_CFG_PATH))
	assert_eq(error, OK, "plugin.cfg should parse cleanly")
	assert_eq(config.get_value("plugin", "name", ""), EXPECTED_PLUGIN_NAME, "plugin.cfg name should match the vendor package")
	assert_true(
		str(config.get_value("plugin", "description", "")).contains("startup, shutdown, config translation, camera enumeration, runtime health, and frame normalization"),
		"plugin.cfg description should describe the bootstrap seam"
	)

func test_addons_manifest_pins_camera_tracking_contract_for_repo_local_validation() -> void:
	var manifest_text := _read_repo_file(ADDONS_MANIFEST_PATH)
	var block_start := manifest_text.find('"aerobeat-tool-camera-tracking": {')
	var next_block_start := manifest_text.find('"aerobeat-tool-core": {')
	assert_true(block_start >= 0, "addons manifest should pin aerobeat-tool-camera-tracking for backend validation")
	assert_true(next_block_start > block_start, "camera-tracking manifest block should end before aerobeat-tool-core")
	var camera_tracking_block := manifest_text.substr(block_start, next_block_start - block_start)
	assert_true(camera_tracking_block.contains('"git@github.com:AeroBeat-Workouts/aerobeat-tool-camera-tracking.git"'), "addons manifest should point camera tracking at the SSH git remote")
	assert_true(camera_tracking_block.contains('"checkout": "25f52da"'), "addons manifest should pin the approved contract-shell commit")
	assert_false(camera_tracking_block.contains('"url": "../../aerobeat-tool-camera-tracking"'), "addons manifest should not use a local camera-tracking path for repo-local validation")
	assert_false(camera_tracking_block.contains('"source": "symlink"'), "addons manifest should not symlink the pinned camera-tracking contract dependency")
	assert_true(manifest_text.contains('"aerobeat-tool-core"'), "addons manifest should keep aerobeat-tool-core available")
	assert_true(manifest_text.contains('"aerobeat-vendor-godot-unit-test"'), "addons manifest should keep the vendor unit-test addon available")

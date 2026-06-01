import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


_MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "prepare_vendor_runtime.py"
_SPEC = importlib.util.spec_from_file_location("prepare_vendor_runtime", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
prep = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(prep)


class PrepareVendorRuntimeTests(unittest.TestCase):
    def test_prepare_vendor_runtime_reports_repo_owned_runtime_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            venv_dir = Path(temp_dir) / ".venv"

            with mock.patch.object(prep.venv.EnvBuilder, "create") as create_mock, \
                 mock.patch.object(prep, "_ensure_runtime_pip_available") as ensure_pip_mock, \
                 mock.patch.object(prep, "_install_requirements") as install_mock, \
                 mock.patch.object(prep, "_validate_prepared_runtime", return_value=[]) as validate_mock:
                result = prep.prepare_vendor_runtime(venv_dir=venv_dir)

            create_mock.assert_called_once_with(venv_dir)
            ensure_pip_mock.assert_called_once()
            install_mock.assert_called_once()
            validate_mock.assert_called_once()
            self.assertTrue(result["ok"])
            self.assertTrue(result["created_venv"])
            self.assertTrue(result["installed_requirements"])
            self.assertEqual(result["runtime_config"]["working_directory"], str(prep.REPO_ROOT))
            self.assertEqual(result["runtime_config"]["entrypoint"], str(prep.DEFAULT_ENTRYPOINT))
            self.assertEqual(result["runtime_config"]["pose_landmarker_model_path"], str(prep.DEFAULT_MODEL))
            self.assertEqual(result["canonical_command"], "python3 scripts/prepare_vendor_runtime.py --json")

    def test_prepare_vendor_runtime_can_skip_install_and_validation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            venv_dir = Path(temp_dir) / ".venv"
            venv_dir.mkdir()

            with mock.patch.object(prep, "_ensure_runtime_pip_available") as ensure_pip_mock, \
                 mock.patch.object(prep, "_install_requirements") as install_mock, \
                 mock.patch.object(prep, "_validate_prepared_runtime") as validate_mock:
                result = prep.prepare_vendor_runtime(
                    venv_dir=venv_dir,
                    install_requirements=False,
                    validate=False,
                )

            ensure_pip_mock.assert_called_once()
            install_mock.assert_not_called()
            validate_mock.assert_not_called()
            self.assertFalse(result["created_venv"])
            self.assertFalse(result["installed_requirements"])
            self.assertIn("Skipped dependency installation", result["warnings"][0])
            self.assertIn("Skipped validation", result["warnings"][1])

    def test_validate_prepared_runtime_requires_repo_artifacts_and_installed_imports(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            python_path = Path(temp_dir) / "python"
            python_path.write_text("#!/bin/sh\n", encoding="utf-8")
            completed = subprocess.CompletedProcess(args=[str(python_path)], returncode=0, stdout="ok\n", stderr="")
            real_exists = Path.exists

            def fake_exists(path_self):
                if path_self in (prep.DEFAULT_ENTRYPOINT, prep.DEFAULT_REQUIREMENTS, prep.DEFAULT_MODEL, python_path):
                    return True
                return real_exists(path_self)

            with mock.patch("pathlib.Path.exists", autospec=True, side_effect=fake_exists), \
                 mock.patch.object(prep.subprocess, "run", return_value=completed) as run_mock:
                errors = prep._validate_prepared_runtime(python_executable=python_path, require_import_check=True)

            self.assertEqual(errors, [])
            run_mock.assert_called_once()

    def test_validate_prepared_runtime_reports_import_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            python_path = Path(temp_dir) / "python"
            python_path.write_text("#!/bin/sh\n", encoding="utf-8")
            failed = subprocess.CompletedProcess(args=[str(python_path)], returncode=1, stdout="", stderr="No module named mediapipe")
            real_exists = Path.exists

            def fake_exists(path_self):
                if path_self in (prep.DEFAULT_ENTRYPOINT, prep.DEFAULT_REQUIREMENTS, prep.DEFAULT_MODEL, python_path):
                    return True
                return real_exists(path_self)

            with mock.patch("pathlib.Path.exists", autospec=True, side_effect=fake_exists), \
                 mock.patch.object(prep.subprocess, "run", return_value=failed):
                errors = prep._validate_prepared_runtime(python_executable=python_path, require_import_check=True)

            self.assertEqual(len(errors), 1)
            self.assertIn("mediapipe", errors[0])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import venv
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VENV_DIR = REPO_ROOT / ".venv"
DEFAULT_ENTRYPOINT = REPO_ROOT / "runtime" / "mediapipe_runtime_probe.py"
DEFAULT_REQUIREMENTS = REPO_ROOT / "runtime" / "requirements.txt"
DEFAULT_MODEL = REPO_ROOT / "models" / "pose_landmarker_lite.task"
DEFAULT_IMPORT_CHECK = ("mediapipe", "cv2", "numpy")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare the repo-owned AeroBeat vendor MediaPipe Python runtime. "
            "This helper only owns the vendor lane's local Python environment, "
            "entrypoint, and model/dependency readiness."
        )
    )
    parser.add_argument(
        "--venv-dir",
        default=str(DEFAULT_VENV_DIR),
        help="Repo-local virtualenv path to create/use (default: .venv at the repo root).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Remove and recreate the target virtualenv before installing requirements.",
    )
    parser.add_argument(
        "--skip-install",
        action="store_true",
        help="Skip requirement installation and only validate/report the prepared runtime shape.",
    )
    parser.add_argument(
        "--skip-validate",
        action="store_true",
        help="Skip validation checks after preparation.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the result payload as JSON.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = prepare_vendor_runtime(
        venv_dir=Path(args.venv_dir).expanduser(),
        force=args.force,
        install_requirements=not args.skip_install,
        validate=not args.skip_validate,
    )

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Prepared vendor runtime at {result['venv_dir']}")
        print(f"Python executable: {result['python_executable']}")
        print(f"Runtime entrypoint: {result['entrypoint']}")
        print(f"Model asset: {result['default_model_asset_path']}")
        for note in result["notes"]:
            print(f"NOTE: {note}")
        for warning in result["warnings"]:
            print(f"WARNING: {warning}")
        if result["validation_errors"]:
            print("Validation errors:")
            for error in result["validation_errors"]:
                print(f"- {error}")

    return 1 if result["validation_errors"] else 0


def prepare_vendor_runtime(*, venv_dir: Path, force: bool = False, install_requirements: bool = True, validate: bool = True) -> dict[str, Any]:
    venv_dir = venv_dir.resolve()
    warnings: list[str] = []
    notes: list[str] = []

    if force and venv_dir.exists():
        shutil.rmtree(venv_dir)
        notes.append(f"Removed existing virtualenv at {venv_dir}.")

    created_venv = False
    if not venv_dir.exists():
        venv.EnvBuilder(with_pip=True).create(venv_dir)
        created_venv = True
        notes.append(f"Created repo-local virtualenv at {venv_dir}.")
    else:
        notes.append(f"Reusing repo-local virtualenv at {venv_dir}.")

    python_executable = _venv_python_path(venv_dir)
    _ensure_runtime_pip_available(python_executable)

    installed_requirements = False
    if install_requirements:
        _install_requirements(python_executable)
        installed_requirements = True
        notes.append(f"Installed runtime requirements from {DEFAULT_REQUIREMENTS}.")
    else:
        warnings.append("Skipped dependency installation; existing environment contents were left unchanged.")

    validation_errors = _validate_prepared_runtime(
        python_executable=python_executable,
        require_import_check=install_requirements,
    ) if validate else []

    if not validate:
        warnings.append("Skipped validation; runtime readiness was not verified in this pass.")

    result = {
        "ok": not validation_errors,
        "repo_root": str(REPO_ROOT),
        "venv_dir": str(venv_dir),
        "python_executable": str(python_executable),
        "entrypoint": str(DEFAULT_ENTRYPOINT),
        "requirements_file": str(DEFAULT_REQUIREMENTS),
        "default_model_asset_path": str(DEFAULT_MODEL),
        "created_venv": created_venv,
        "installed_requirements": installed_requirements,
        "validated": validate,
        "notes": notes,
        "warnings": warnings,
        "validation_errors": validation_errors,
        "runtime_config": {
            "python_executable": str(python_executable),
            "entrypoint": str(DEFAULT_ENTRYPOINT),
            "working_directory": str(REPO_ROOT),
            "pose_landmarker_model_path": str(DEFAULT_MODEL),
        },
        "canonical_command": "python3 scripts/prepare_vendor_runtime.py --json",
    }
    return result


def _install_requirements(python_executable: Path) -> None:
    subprocess.run(
        [str(python_executable), "-m", "pip", "install", "-r", str(DEFAULT_REQUIREMENTS)],
        cwd=REPO_ROOT,
        check=True,
    )


def _ensure_runtime_pip_available(python_executable: Path) -> None:
    if _runtime_pip_available(python_executable):
        return

    subprocess.run(
        [str(python_executable), "-m", "ensurepip", "--upgrade"],
        cwd=REPO_ROOT,
        check=True,
    )

    if _runtime_pip_available(python_executable):
        return

    raise SystemExit(
        "Repo-local virtualenv exists but pip is unavailable even after 'python -m ensurepip --upgrade'. "
        "Recreate the virtualenv with '--force' and try again."
    )


def _runtime_pip_available(python_executable: Path) -> bool:
    result = subprocess.run(
        [str(python_executable), "-m", "pip", "--version"],
        cwd=REPO_ROOT,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _validate_prepared_runtime(*, python_executable: Path, require_import_check: bool) -> list[str]:
    errors: list[str] = []

    if not DEFAULT_ENTRYPOINT.exists():
        errors.append(f"Missing runtime entrypoint: {DEFAULT_ENTRYPOINT}")
    if not DEFAULT_REQUIREMENTS.exists():
        errors.append(f"Missing runtime requirements file: {DEFAULT_REQUIREMENTS}")
    if not DEFAULT_MODEL.exists():
        errors.append(f"Missing default model asset: {DEFAULT_MODEL}")
    if not python_executable.exists():
        errors.append(f"Missing virtualenv Python executable: {python_executable}")

    if require_import_check and not errors:
        import_result = subprocess.run(
            [
                str(python_executable),
                "-c",
                (
                    "import importlib; "
                    f"mods = {list(DEFAULT_IMPORT_CHECK)!r}; "
                    "missing = [name for name in mods if importlib.import_module(name) is None]; "
                    "print('ok' if not missing else ','.join(missing))"
                ),
            ],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        if import_result.returncode != 0:
            details = (import_result.stderr or import_result.stdout).strip()
            errors.append(
                "Prepared virtualenv could not import required runtime modules "
                f"({', '.join(DEFAULT_IMPORT_CHECK)}): {details or 'unknown import failure'}"
            )

    return errors


def _venv_python_path(venv_dir: Path) -> Path:
    if sys.platform.startswith("win"):
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


if __name__ == "__main__":
    sys.exit(main())

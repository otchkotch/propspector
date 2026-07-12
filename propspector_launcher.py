from __future__ import annotations

import ctypes
import json
import subprocess
import sys
from pathlib import Path


MANIFEST_NAME = "PropSpector.update.json"
APP_TITLE = "PropSpector"


def main() -> int:
    launcher_path = Path(sys.executable).resolve()
    install_dir = launcher_path.parent
    manifest_path = install_dir / MANIFEST_NAME

    try:
        target_path = _target_from_manifest(install_dir, manifest_path, launcher_path)
    except Exception as exc:
        _show_error(str(exc))
        return 1

    try:
        subprocess.Popen([str(target_path), *sys.argv[1:]], cwd=str(target_path.parent))
    except Exception as exc:
        _show_error(f"PropSpector could not be started.\n\n{target_path}\n\n{exc}")
        return 1

    return 0


def _target_from_manifest(install_dir: Path, manifest_path: Path, launcher_path: Path) -> Path:
    if not manifest_path.exists():
        raise RuntimeError(
            f"Update manifest was not found.\n\nExpected:\n{manifest_path}\n\n"
            "Please contact CDA software support."
        )

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Update manifest is not valid JSON.\n\n{manifest_path}\n\n{exc}") from exc

    latest_exe = str(manifest.get("latest_exe", "")).strip()
    if not latest_exe:
        raise RuntimeError(f"Update manifest does not define latest_exe.\n\n{manifest_path}")

    target_path = Path(latest_exe)
    if not target_path.is_absolute():
        target_path = install_dir / target_path
    target_path = target_path.resolve()

    if target_path == launcher_path:
        raise RuntimeError("Update manifest points back to the launcher. This would create a launch loop.")

    if not target_path.exists():
        version = str(manifest.get("latest_version", "unknown")).strip() or "unknown"
        raise RuntimeError(
            f"PropSpector version {version} was not found.\n\nExpected:\n{target_path}\n\n"
            "Please confirm the L: drive is connected and contact CDA software support."
        )

    return target_path


def _show_error(message: str) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(None, message, APP_TITLE, 0x10)
    except Exception:
        print(message, file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())

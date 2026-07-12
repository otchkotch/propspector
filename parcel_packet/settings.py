from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


APP_DIR = Path.home() / "AppData" / "Local" / "Parcel Environmental Packet"
SETTINGS_PATH = APP_DIR / "settings.json"


@dataclass
class AppSettings:
    last_destination: str = ""
    project_prefix: str = "TP"
    browser_channel: str = "msedge"
    important_pause_seconds: int = 20
    settle_pause_seconds: int = 5
    assisted_layers: bool = True


def load_settings() -> AppSettings:
    if not SETTINGS_PATH.exists():
        return AppSettings()
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return AppSettings()
    defaults = AppSettings()
    return AppSettings(
        last_destination=str(data.get("last_destination", defaults.last_destination)),
        project_prefix=str(data.get("project_prefix", defaults.project_prefix)),
        browser_channel=str(data.get("browser_channel", defaults.browser_channel)),
        important_pause_seconds=int(data.get("important_pause_seconds", defaults.important_pause_seconds)),
        settle_pause_seconds=int(data.get("settle_pause_seconds", defaults.settle_pause_seconds)),
        assisted_layers=bool(data.get("assisted_layers", defaults.assisted_layers)),
    )


def save_settings(settings: AppSettings) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(
        json.dumps(settings.__dict__, indent=2),
        encoding="utf-8",
    )

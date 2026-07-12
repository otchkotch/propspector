from __future__ import annotations

import ctypes
import logging
from pathlib import Path


LOGGER = logging.getLogger("parcel_packet.fonts")
ROOT = Path(__file__).resolve().parents[1]
NUNITO_FONT_PATH = ROOT / "assets" / "fonts" / "NunitoSans.ttf"


def load_bundled_fonts() -> None:
    if not NUNITO_FONT_PATH.exists():
        LOGGER.warning("Bundled Nunito font not found at %s", NUNITO_FONT_PATH)
        return
    try:
        ctypes.windll.gdi32.AddFontResourceExW(str(NUNITO_FONT_PATH), 0x10, 0)
        LOGGER.info("Loaded bundled font %s", NUNITO_FONT_PATH)
    except Exception:
        LOGGER.exception("Could not load bundled Nunito font")

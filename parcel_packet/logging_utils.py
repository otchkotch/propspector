from __future__ import annotations

import logging
import sys
from pathlib import Path

from .settings import APP_DIR


LOG_PATH = APP_DIR / "packet.log"


def configure_logging() -> Path:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=LOG_PATH,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        encoding="utf-8",
    )

    def handle_exception(exc_type, exc, tb):
        logging.getLogger("parcel_packet").exception("Unhandled exception", exc_info=(exc_type, exc, tb))
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = handle_exception
    logging.getLogger("parcel_packet").info("Application logging started")
    return LOG_PATH

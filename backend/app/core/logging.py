import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config import get_settings


def setup_logging() -> None:
    settings = get_settings()
    Path(settings.log_dir).mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    root = logging.getLogger()
    root.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))

    if not root.handlers:
        file_handler = RotatingFileHandler(
            filename=str(Path(settings.log_dir) / "thlpro.log"),
            maxBytes=2_000_000,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)

        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(fmt)
        root.addHandler(stream_handler)

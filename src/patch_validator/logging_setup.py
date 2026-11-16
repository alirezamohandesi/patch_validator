"""Logging configuration.

A single place sets up logging so every module can simply call
``logging.getLogger(__name__)``.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_FORMAT = "%(asctime)s %(levelname)-7s %(name)-34s %(message)s"
_DATEFMT = "%H:%M:%S"


class _ColourFormatter(logging.Formatter):
    """Adds ANSI colour to the level name when stderr is a terminal."""

    _COLOURS = {
        logging.DEBUG: "\033[2m",
        logging.INFO: "\033[36m",
        logging.WARNING: "\033[33m",
        logging.ERROR: "\033[31m",
        logging.CRITICAL: "\033[1;31m",
    }
    _RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        colour = self._COLOURS.get(record.levelno, "")
        original = record.levelname
        record.levelname = f"{colour}{original}{self._RESET}"
        try:
            return super().format(record)
        finally:
            record.levelname = original


def setup_logging(verbosity: int = 0, *, log_file: Path | None = None) -> None:
    """Configure the root logger.

    ``verbosity`` 0 is INFO, 1 and above is DEBUG, negative is WARNING.
    """
    level = logging.INFO
    if verbosity >= 1:
        level = logging.DEBUG
    elif verbosity < 0:
        level = logging.WARNING

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    stream = logging.StreamHandler(sys.stderr)
    stream.setLevel(level)
    use_colour = hasattr(sys.stderr, "isatty") and sys.stderr.isatty()
    formatter = _ColourFormatter if use_colour else logging.Formatter
    stream.setFormatter(formatter(_FORMAT, datefmt=_DATEFMT))
    root.addHandler(stream)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATEFMT))
        root.addHandler(file_handler)

"""Application entry point for the minilogue xd MIDI diagnostic GUI."""

from __future__ import annotations

import logging
import os
from pathlib import Path
import sys
import tkinter as tk

from app.app_paths import log_path
from app.main_window import MainWindow


WINDOW_TITLE = "minilogue xd Librarian"
MIN_WINDOW_SIZE = (980, 680)
DEFAULT_WINDOW_GEOMETRY = "1180x780"
DEFAULT_LOG_LEVEL = logging.INFO


def configure_logging() -> None:
    """Initialize console and file logging before the GUI starts."""
    level = logging.DEBUG if os.getenv("DEBUG") else _configured_log_level()
    try:
        handlers: list[logging.Handler] = [
            logging.StreamHandler(),
            logging.FileHandler(log_path(), encoding="utf-8"),
        ]
    except OSError as exc:
        print(f"[WARNING] Log file could not be created: {exc}", file=sys.stderr)
        handlers = [logging.StreamHandler()]

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


def _configured_log_level() -> int:
    configured = os.getenv("MINILOGUE_XD_LOG_LEVEL", "").strip().upper()
    if not configured:
        return DEFAULT_LOG_LEVEL
    return getattr(logging, configured, DEFAULT_LOG_LEVEL)


def configure_root(root: tk.Tk) -> None:
    """Apply root window settings that belong to the app shell."""
    root.title(WINDOW_TITLE)
    root.geometry(DEFAULT_WINDOW_GEOMETRY)
    root.minsize(*MIN_WINDOW_SIZE)
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    icon_path = bundle_root / "assets" / "icon.ico"
    if icon_path.exists():
        try:
            root.iconbitmap(str(icon_path))
        except tk.TclError:
            pass


def main() -> None:
    """Start the Tkinter application."""
    configure_logging()
    logger = logging.getLogger(__name__)

    try:
        root = tk.Tk()
        root.withdraw()
        configure_root(root)

        app = MainWindow(root)
        root.protocol("WM_DELETE_WINDOW", app.on_close)

        root.deiconify()
        logger.info("GUI started.")
        root.mainloop()
    except tk.TclError as exc:
        logger.critical("Tkinter initialization failed: %s", exc)
        print(f"[ERROR] Tkinter initialization failed: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception:
        logger.exception("Application startup failed.")
        print("[ERROR] Application startup failed. See the log file for details.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

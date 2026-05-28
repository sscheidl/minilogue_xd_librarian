"""Application entry point for the minilogue xd MIDI diagnostic GUI."""

from __future__ import annotations

import logging
import sys
import tkinter as tk

from app.app_paths import log_path
from app.main_window import MainWindow


WINDOW_TITLE = "minilogue xd Librarian - MIDI Test"
MIN_WINDOW_SIZE = (980, 680)


def configure_logging() -> None:
    """Initialize console and file logging before the GUI starts."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_path(), encoding="utf-8"),
        ],
    )


def main() -> None:
    """Start the Tkinter application."""
    configure_logging()
    logger = logging.getLogger(__name__)

    try:
        root = tk.Tk()
        root.withdraw()
        root.title(WINDOW_TITLE)
        root.minsize(*MIN_WINDOW_SIZE)

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

"""Application entry point for the minilogue xd MIDI diagnostic GUI."""

from __future__ import annotations

import tkinter as tk

from app.main_window import MainWindow


def main() -> None:
    root = tk.Tk()
    MainWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Simple MIDI/SysEx GUI for minilogue xd troubleshooting."""

from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

PROJECT_ROOT = Path(__file__).resolve().parents[1]
import sys

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import mido
except Exception as exc:  # pragma: no cover
    mido = None
    MIDO_IMPORT_ERROR = exc
else:
    MIDO_IMPORT_ERROR = None

from devices.korg_minilogue_xd.sysex import classify_xd_sysex
from midi.engine3 import ENGINE3_LABEL, detect_engine3_runtime
from xd_formats.sysex_codec import split_sysex_stream_ignoring_realtime

REALTIME_TYPES = {"clock", "start", "stop", "continue", "active_sensing", "reset"}


def is_xd_port(name: str) -> bool:
    return "minilogue xd" in name.lower()


def port_sort_key(name: str) -> tuple[int, str]:
    low = name.lower().strip()
    is_port2 = "midiin2" in low or "midiout2" in low or low.endswith(" 2") or low.endswith(") 2")
    if is_xd_port(name):
        return (1 if is_port2 else 0, low)
    return (9, low)


def hex_line(raw: bytes, max_len: int = 120) -> str:
    text = " ".join(f"{byte:02X}" for byte in raw[:max_len])
    if len(raw) > max_len:
        text += f" ... ({len(raw)} bytes)"
    return text


class MidiSysexGui:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("minilogue xd MIDI/SysEx Tool")
        self.root.geometry("1400x840")

        self.midi_in_var = tk.StringVar(value="")
        self.midi_out_var = tk.StringVar(value="")
        self.engine_var = tk.StringVar(value=ENGINE3_LABEL)
        self.delay_ms_var = tk.StringVar(value="35")
        self.status_var = tk.StringVar(value="Bereit")

        self.show_realtime = tk.BooleanVar(value=False)
        self.auto_scroll = tk.BooleanVar(value=True)
        self.verbose_engine_log = tk.BooleanVar(value=False)
        self.engine_status = detect_engine3_runtime()

        self.loaded_path: Path | None = None
        self.loaded_messages: list[bytes] = []

        self._in_port = None
        self._out_port = None
        self._incoming: "queue.Queue[tuple[str, str, bytes]]" = queue.Queue()
        self._stop_send = threading.Event()
        self._send_thread: threading.Thread | None = None
        self._monitor_enabled = False

        self._build_menu()
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(50, self._process_incoming)
        self.refresh_ports()

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="SYSEX laden", command=self.load_sysex)
        file_menu.add_command(label="Log speichern", command=self.save_log)
        file_menu.add_separator()
        file_menu.add_command(label="Beenden", command=self._on_close)
        menubar.add_cascade(label="FILE", menu=file_menu)

        edit_menu = tk.Menu(menubar, tearoff=0)
        edit_menu.add_command(label="Log leeren", command=self.clear_log)
        edit_menu.add_command(label="Alles kopieren", command=self.copy_all_log)
        menubar.add_cascade(label="EDIT", menu=edit_menu)

        midi_menu = tk.Menu(menubar, tearoff=0)
        midi_menu.add_command(label="Ports aktualisieren", command=self.refresh_ports)
        midi_menu.add_command(label="Verbinden", command=self.connect_ports)
        midi_menu.add_command(label="Trennen", command=self.disconnect_ports)
        midi_menu.add_separator()
        midi_menu.add_command(label="Monitor Start", command=self.start_monitor)
        midi_menu.add_command(label="Monitor Stop", command=self.stop_monitor)
        midi_menu.add_command(label="SYSEX senden", command=self.send_sysex)
        menubar.add_cascade(label="MIDI", menu=midi_menu)

        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_checkbutton(label="Auto Scroll", variable=self.auto_scroll)
        view_menu.add_checkbutton(label="Realtime anzeigen", variable=self.show_realtime)
        view_menu.add_checkbutton(label="Verbose Engine Log", variable=self.verbose_engine_log)
        menubar.add_cascade(label="VIEW", menu=view_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Info", command=self.show_help)
        menubar.add_cascade(label="HELP", menu=help_menu)

        self.root.config(menu=menubar)

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)

        toolbar = ttk.Frame(self.root, padding=8)
        toolbar.grid(row=0, column=0, sticky="ew")

        ttk.Button(toolbar, text="Ports", command=self.refresh_ports).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(toolbar, text="Verbinden", command=self.connect_ports).grid(row=0, column=1, padx=(0, 6))
        ttk.Button(toolbar, text="Trennen", command=self.disconnect_ports).grid(row=0, column=2, padx=(0, 18))
        ttk.Button(toolbar, text="SYSEX laden", command=self.load_sysex).grid(row=0, column=3, padx=(0, 6))
        ttk.Button(toolbar, text="SYSEX senden", command=self.send_sysex).grid(row=0, column=4, padx=(0, 18))
        ttk.Button(toolbar, text="Monitor Start", command=self.start_monitor).grid(row=0, column=5, padx=(0, 6))
        ttk.Button(toolbar, text="Monitor Stop", command=self.stop_monitor).grid(row=0, column=6, padx=(0, 6))
        ttk.Button(toolbar, text="Log leeren", command=self.clear_log).grid(row=0, column=7, padx=(0, 6))
        ttk.Button(toolbar, text="Stop Senden", command=self.stop_sending).grid(row=0, column=8, padx=(0, 6))

        controls = ttk.LabelFrame(self.root, text="MIDI Einstellungen", padding=10)
        controls.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))
        controls.columnconfigure(1, weight=1)
        controls.columnconfigure(3, weight=1)

        ttk.Label(controls, text="MIDI IN").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=(0, 8))
        self.in_combo = ttk.Combobox(controls, textvariable=self.midi_in_var, state="readonly")
        self.in_combo.grid(row=0, column=1, sticky="ew", pady=(0, 8))

        ttk.Label(controls, text="MIDI OUT").grid(row=0, column=2, sticky="w", padx=(16, 8), pady=(0, 8))
        self.out_combo = ttk.Combobox(controls, textvariable=self.midi_out_var, state="readonly")
        self.out_combo.grid(row=0, column=3, sticky="ew", pady=(0, 8))

        ttk.Label(controls, text="Engine").grid(row=1, column=0, sticky="w", padx=(0, 8))
        ttk.Label(
            controls,
            textvariable=self.engine_var,
        ).grid(row=1, column=1, sticky="w")

        ttk.Label(controls, text="Delay zwischen Chunks (ms)").grid(row=1, column=2, sticky="w", padx=(16, 8))
        ttk.Entry(controls, textvariable=self.delay_ms_var, width=10).grid(row=1, column=3, sticky="w")

        status_frame = ttk.Frame(self.root, padding=(8, 0, 8, 8))
        status_frame.grid(row=3, column=0, sticky="ew")
        status_frame.columnconfigure(0, weight=1)
        ttk.Label(status_frame, textvariable=self.status_var).grid(row=0, column=0, sticky="w")

        log_frame = ttk.Frame(self.root, padding=(8, 0, 8, 0))
        log_frame.grid(row=2, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log = scrolledtext.ScrolledText(log_frame, wrap=tk.NONE, font=("Consolas", 11))
        self.log.grid(row=0, column=0, sticky="nsew")
        self.refresh_engine_status()

    def _append(self, text: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.log.insert(tk.END, f"[{stamp}] {text}\n")
        if self.auto_scroll.get():
            self.log.see(tk.END)

    def _set_status(self, text: str) -> None:
        self.status_var.set(text)

    def refresh_engine_status(self) -> None:
        self.engine_status = detect_engine3_runtime()
        self._append(self.engine_status.status_text)
        if not self.engine_status.available:
            self._set_status("Engine 3 runtime missing")

    def _engine3_ready(self) -> bool:
        self.engine_status = detect_engine3_runtime()
        if self.engine_status.available:
            if self.verbose_engine_log.get():
                self._append(self.engine_status.status_text)
            return True
        message = self.engine_status.status_text
        self._append(f"ERROR: {message}")
        self._set_status("Engine 3 runtime missing")
        messagebox.showerror("Engine 3 runtime missing", message)
        return False

    def refresh_ports(self) -> None:
        self.engine_status = detect_engine3_runtime()
        if self.verbose_engine_log.get() or not self.engine_status.available:
            self._append(self.engine_status.status_text)
        if mido is None:
            messagebox.showerror("MIDI Fehler", f"mido konnte nicht geladen werden:\n{MIDO_IMPORT_ERROR}")
            return
        inputs = sorted(mido.get_input_names(), key=port_sort_key)
        outputs = sorted(mido.get_output_names(), key=port_sort_key)
        self.in_combo["values"] = inputs
        self.out_combo["values"] = outputs

        if not self.midi_in_var.get() and inputs:
            preferred = [name for name in inputs if is_xd_port(name)]
            self.midi_in_var.set(preferred[0] if preferred else inputs[0])
        if not self.midi_out_var.get() and outputs:
            preferred = [name for name in outputs if is_xd_port(name)]
            self.midi_out_var.set(preferred[0] if preferred else outputs[0])

        self._append("MIDI Ports aktualisiert:")
        if inputs:
            for idx, port in enumerate(inputs, start=1):
                self._append(f"  IN  {idx:02d}: {port}")
        else:
            self._append("  IN  -- keine Ports")
        if outputs:
            for idx, port in enumerate(outputs, start=1):
                self._append(f"  OUT {idx:02d}: {port}")
        else:
            self._append("  OUT -- keine Ports")
        self._set_status("Ports aktualisiert")

    def connect_ports(self) -> None:
        if not self._engine3_ready():
            return
        if mido is None:
            messagebox.showerror("MIDI Fehler", f"mido konnte nicht geladen werden:\n{MIDO_IMPORT_ERROR}")
            return
        in_name = self.midi_in_var.get().strip()
        out_name = self.midi_out_var.get().strip()
        if not in_name or not out_name:
            messagebox.showwarning("Auswahl fehlt", "Bitte MIDI IN und MIDI OUT auswaehlen.")
            return
        self.disconnect_ports(silent=True)
        try:
            self._in_port = mido.open_input(in_name, callback=lambda msg: self._on_midi_message(in_name, msg))
            self._out_port = mido.open_output(out_name)
        except Exception as exc:
            self._in_port = None
            self._out_port = None
            messagebox.showerror("Verbindung fehlgeschlagen", str(exc))
            self._append(f"Verbindung fehlgeschlagen: {exc}")
            self._set_status("Fehler")
            return
        self._append(f"Verbunden: IN='{in_name}' OUT='{out_name}'")
        self._set_status("Verbunden")

    def disconnect_ports(self, silent: bool = False) -> None:
        in_name = self.midi_in_var.get().strip()
        out_name = self.midi_out_var.get().strip()
        if self._in_port is not None:
            try:
                self._in_port.close()
            except Exception:
                pass
            self._in_port = None
        if self._out_port is not None:
            try:
                self._out_port.close()
            except Exception:
                pass
            self._out_port = None
        self._monitor_enabled = False
        if not silent:
            self._append(f"Getrennt: IN='{in_name}' OUT='{out_name}'")
        self._set_status("Getrennt")

    def _on_midi_message(self, port_name: str, msg) -> None:
        try:
            raw = bytes(msg.bytes())
        except Exception:
            raw = b""
        msg_type = getattr(msg, "type", "unknown")
        self._incoming.put((port_name, msg_type, raw))

    def _process_incoming(self) -> None:
        while True:
            try:
                port_name, msg_type, raw = self._incoming.get_nowait()
            except queue.Empty:
                break

            if msg_type in REALTIME_TYPES and not self.show_realtime.get():
                continue
            if not self._monitor_enabled and msg_type in REALTIME_TYPES:
                continue

            if raw and raw[0] == 0xF0:
                info = classify_xd_sysex(raw)
                self._append(
                    f"RX SYSEX [{port_name}] cmd={f'0x{info.command:02X}' if info.command is not None else 'none'} "
                    f"type={info.label} len={len(raw)}"
                )
                self._append(f"  {hex_line(raw)}")
            elif msg_type in REALTIME_TYPES:
                self._append(f"RX REALTIME [{port_name}] {msg_type}")
            else:
                self._append(f"RX MIDI [{port_name}] {msg_type}: {hex_line(raw)}")

        self.root.after(50, self._process_incoming)

    def start_monitor(self) -> None:
        if self._in_port is None:
            self.connect_ports()
            if self._in_port is None:
                return
        self._monitor_enabled = True
        self._append("Monitor gestartet")
        self._set_status("Monitor aktiv")

    def stop_monitor(self) -> None:
        self._monitor_enabled = False
        self._append("Monitor gestoppt")
        self._set_status("Monitor gestoppt")

    def _parse_delay_ms(self) -> int | None:
        try:
            delay = int(self.delay_ms_var.get().strip())
        except ValueError:
            messagebox.showerror("Ungueltiger Wert", "Delay muss eine ganze Zahl in ms sein.")
            return None
        if delay < 0:
            messagebox.showerror("Ungueltiger Wert", "Delay darf nicht negativ sein.")
            return None
        return delay

    def load_sysex(self) -> None:
        selected = filedialog.askopenfilename(
            title="SYSEX Datei auswaehlen",
            filetypes=[("SysEx files", "*.syx *.txt *.bin *.mid"), ("All files", "*.*")],
        )
        if not selected:
            return
        path = Path(selected)
        try:
            messages = self._load_messages_with_engine(path)
        except Exception as exc:
            messagebox.showerror("Laden fehlgeschlagen", str(exc))
            self._append(f"SYSEX Laden fehlgeschlagen: {exc}")
            return
        if not messages:
            messagebox.showwarning("Keine Daten", "Keine gueltigen SysEx Nachrichten gefunden.")
            self._append(f"SYSEX geladen, aber leer: {path}")
            return
        self.loaded_path = path
        self.loaded_messages = messages
        total_bytes = sum(len(msg) for msg in messages)
        self._append(
            f"SYSEX geladen: {path.name} | Engine={self.engine_var.get()} | Messages={len(messages)} | Bytes={total_bytes}"
        )
        for idx, msg in enumerate(messages[:3], start=1):
            self._append(f"  Msg {idx:02d}: {hex_line(msg)}")
        if len(messages) > 3:
            self._append(f"  ... weitere {len(messages) - 3} Nachrichten")
        self._set_status(f"SYSEX geladen ({len(messages)} Nachrichten)")

    def _load_messages_with_engine(self, path: Path) -> list[bytes]:
        return self._load_engine3(path)

    def _load_engine1(self, path: Path) -> list[bytes]:
        if mido is None:
            raise RuntimeError(f"mido konnte nicht geladen werden: {MIDO_IMPORT_ERROR}")
        messages = []
        try:
            for msg in mido.read_syx_file(str(path)):
                raw = bytes(msg.bytes())
                if raw and raw[0] == 0xF0:
                    messages.append(raw)
        except Exception:
            # Fallback auf Byte-Parser fuer Rohdumps/Hex-Text
            return self._load_engine2(path)
        return messages

    def _load_engine2(self, path: Path) -> list[bytes]:
        return self._load_engine3(path)

    def _load_engine3(self, path: Path) -> list[bytes]:
        raw = path.read_bytes()
        if raw.count(0xF0) == 0 and raw.count(0xF7) == 0:
            text = raw.decode("utf-8", errors="ignore")
            import re

            tokens = re.findall(r"\b[0-9A-Fa-f]{2}\b", text)
            if tokens:
                raw = bytes(int(token, 16) for token in tokens)
        return split_sysex_stream_ignoring_realtime(raw)

    def send_sysex(self) -> None:
        if not self._engine3_ready():
            return
        if self._out_port is None:
            self.connect_ports()
            if self._out_port is None:
                return
        if not self.loaded_messages:
            messagebox.showwarning("Keine Datei", "Bitte erst eine SYSEX-Datei laden.")
            return
        delay_ms = self._parse_delay_ms()
        if delay_ms is None:
            return
        if self._send_thread is not None and self._send_thread.is_alive():
            messagebox.showwarning("Schon aktiv", "Es laeuft bereits ein Sendevorgang.")
            return

        self._stop_send.clear()
        self._send_thread = threading.Thread(target=self._send_worker, args=(delay_ms,), daemon=True)
        self._send_thread.start()

    def _send_worker(self, delay_ms: int) -> None:
        out_name = self.midi_out_var.get().strip()
        total = len(self.loaded_messages)
        self._append(
            f"Senden gestartet: {total} Nachricht(en), Delay={delay_ms} ms, Engine={self.engine_var.get()}, OUT={out_name}"
        )
        self._set_status("Senden aktiv")
        sent = 0
        for idx, raw in enumerate(self.loaded_messages, start=1):
            if self._stop_send.is_set():
                self._append(f"Senden abgebrochen bei Nachricht {idx}/{total}")
                self._set_status("Senden abgebrochen")
                return
            try:
                assert self._out_port is not None
                self._out_port.send(mido.Message.from_bytes(list(raw)))
            except Exception as exc:
                self._append(f"Senden fehlgeschlagen bei Nachricht {idx}: {exc}")
                self._set_status("Senden fehlgeschlagen")
                return
            sent += 1
            info = classify_xd_sysex(raw)
            self._append(
                f"TX {idx:04d}/{total}: cmd={f'0x{info.command:02X}' if info.command is not None else 'none'} "
                f"type={info.label} len={len(raw)}"
            )
            if delay_ms > 0 and idx < total:
                time.sleep(delay_ms / 1000.0)
        self._append(f"Senden fertig: {sent}/{total} Nachricht(en)")
        self._set_status("Senden fertig")

    def stop_sending(self) -> None:
        if self._send_thread is None or not self._send_thread.is_alive():
            return
        self._stop_send.set()
        self._append("Stop angefordert")

    def save_log(self) -> None:
        target = filedialog.asksaveasfilename(
            title="Log speichern",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not target:
            return
        try:
            Path(target).write_text(self.log.get("1.0", tk.END), encoding="utf-8")
            self._append(f"Log gespeichert: {target}")
        except Exception as exc:
            messagebox.showerror("Speichern fehlgeschlagen", str(exc))

    def clear_log(self) -> None:
        self.log.delete("1.0", tk.END)

    def copy_all_log(self) -> None:
        text = self.log.get("1.0", tk.END)
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self._append("Log in Zwischenablage kopiert")

    def show_help(self) -> None:
        messagebox.showinfo(
            "Info",
            "1) Ports aktualisieren\n"
            "2) MIDI IN/OUT waehlen\n"
            "3) Verbinden\n"
            "4) SYSEX laden\n"
            "5) SYSEX senden\n\n"
            "Monitor zeigt eingehende MIDI/SysEx Daten im grossen Logfenster.",
        )

    def _on_close(self) -> None:
        self.stop_sending()
        self.disconnect_ports(silent=True)
        self.root.destroy()


def main() -> int:
    root = tk.Tk()
    MidiSysexGui(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

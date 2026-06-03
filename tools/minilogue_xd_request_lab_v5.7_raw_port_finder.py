#!/usr/bin/env python3
"""
minilogue_xd_request_lab_v5.7_raw_port_finder.py

Focused diagnostic GUI for Korg minilogue xd SysEx troubleshooting on Windows 11.

Purpose of v5.7:
- Determine on which logical XD input port the real manual Program Dump (cmd 0x40) arrives.
- Avoid hiding the result by opening the wrong/all ports unintentionally.
- Provide explicit RX modes: Port 1 only, Port 2 only, or Both.
- Provide a 30 s raw manual monitor with per-port counters.
- Keep minimal request tests for Global 0x0E and split PC->Current.
- Import Pocket MIDI hex text from the clipboard for parser checks.

Requirements:
    pip install mido python-rtmidi
"""
from __future__ import annotations

import queue
import re
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Optional

try:
    import mido
except Exception as exc:  # pragma: no cover
    mido = None
    MIDO_IMPORT_ERROR = exc
else:
    MIDO_IMPORT_ERROR = None

KORG_ID = 0x42
XD_TAIL = [0x00, 0x01, 0x51]
CMD_REQ_CURRENT = 0x10
CMD_REQ_GLOBAL = 0x0E
CMD_RX_CURRENT = 0x40
CMD_RX_PROGRAM = 0x4C
CMD_RX_GLOBAL = 0x51
REALTIME_TYPES = {"clock", "start", "stop", "continue", "active_sensing", "reset"}


def korg_xd_header(channel: int = 0) -> list[int]:
    return [0xF0, KORG_ID, 0x30 | (channel & 0x0F), *XD_TAIL]


def request_global_data(channel: int = 0) -> bytes:
    return bytes(korg_xd_header(channel) + [CMD_REQ_GLOBAL, 0xF7])


def request_current_program(channel: int = 0, trailing_zero: bool = True) -> bytes:
    body = [CMD_REQ_CURRENT]
    if trailing_zero:
        body.append(0x00)
    return bytes(korg_xd_header(channel) + body + [0xF7])


def slot_to_program_change(slot_index: int) -> tuple[int, int]:
    if not 0 <= slot_index <= 499:
        raise ValueError(f"slot_index must be 0..499, got {slot_index!r}")
    return slot_index // 100, slot_index % 100


def program_change_messages(slot_index: int, channel: int = 0) -> list[bytes]:
    bank, prog = slot_to_program_change(slot_index)
    ch = channel & 0x0F
    return [
        bytes([0xB0 | ch, 0x00, 0x00]),  # CC0 Bank Select MSB
        bytes([0xB0 | ch, 0x20, bank]),  # CC32 Bank Select LSB
        bytes([0xC0 | ch, prog]),         # Program Change
    ]


def is_xd_port(name: str) -> bool:
    return "minilogue xd" in name.lower()


def is_port2(name: str) -> bool:
    low = name.lower()
    return "midiin2" in low or "midiout2" in low or low.rstrip().endswith(" 2") or low.rstrip().endswith(") 2")


def port_sort_key(name: str) -> tuple[int, str]:
    if is_xd_port(name):
        return (1 if is_port2(name) else 0, name.lower())
    return (9, name.lower())


def hex_line(raw: bytes, max_len: int = 96) -> str:
    text = " ".join(f"{b:02X}" for b in raw[:max_len])
    if len(raw) > max_len:
        text += f" ... ({len(raw)} bytes)"
    return text


def split_sysex_stream(data: bytes) -> list[bytes]:
    messages: list[bytes] = []
    start: Optional[int] = None
    for idx, value in enumerate(data):
        if value == 0xF0:
            start = idx
        elif value == 0xF7 and start is not None:
            messages.append(data[start:idx + 1])
            start = None
    return messages


def classify_xd_sysex(raw: bytes) -> tuple[Optional[int], str]:
    if len(raw) < 2 or raw[0] != 0xF0 or raw[-1] != 0xF7:
        return None, "not-sysex"
    if len(raw) < 7:
        return None, "short-sysex"
    if raw[1] != KORG_ID:
        return None, "non-korg"
    if raw[3:6] != bytes(XD_TAIL):
        return None, "korg-unknown-family"
    cmd = raw[6]
    labels = {
        CMD_RX_CURRENT: "current-program-dump-0x40",
        CMD_RX_PROGRAM: "program-dump-0x4C",
        0x44: "program-bank-index-0x44",
        0x45: "sequencer-index-0x45",
        CMD_RX_GLOBAL: "global-data-0x51",
    }
    return cmd, labels.get(cmd, f"unknown-xd-cmd-0x{cmd:02X}")


def extract_program_name(raw: bytes) -> str:
    """Best-effort XD program name extraction from real 0x40/0x4C dumps."""
    candidates: list[str] = []
    if len(raw) >= 24 and raw[8:12] == b"PROG":
        # Real manual 0x40 dump starts: ... 40 00 50 52 4F 47 <name bytes...>
        chunk = raw[12:24]
        text = "".join(chr(b) for b in chunk if 32 <= b <= 126).strip()
        if text:
            candidates.append(text)
    for start in (12, 10, 9, 8, 7):
        if len(raw) >= start + 12:
            chunk = raw[start:start + 12]
            text = "".join(chr(b) for b in chunk if 32 <= b <= 126).strip()
            if text and text not in {"@", "L", "PROG"} and not text.startswith("PROG"):
                candidates.append(text)
    return candidates[0] if candidates else "name unknown"


def parse_hex_text(text: str) -> bytes:
    tokens = re.findall(r"\b[0-9A-Fa-f]{2}\b", text)
    return bytes(int(t, 16) for t in tokens)


@dataclass
class ProgramRecord:
    slot_index: Optional[int]
    name: str
    raw: bytes
    source: str
    command: int

    @property
    def display_slot(self) -> str:
        return "?" if self.slot_index is None else f"{self.slot_index + 1:03d}"


class MidiWorker:
    def __init__(self, incoming: "queue.Queue[tuple[str, object]]") -> None:
        self.incoming = incoming
        self.inports: dict[str, object] = {}
        self.outports: dict[str, object] = {}
        self.lock = threading.RLock()

    def close(self) -> None:
        with self.lock:
            for name, port in list(self.inports.items()):
                try:
                    port.close()
                except Exception as exc:
                    self.incoming.put(("log", f"Close input failed {name!r}: {exc}"))
            for name, port in list(self.outports.items()):
                try:
                    port.close()
                except Exception as exc:
                    self.incoming.put(("log", f"Close output failed {name!r}: {exc}"))
            self.inports.clear()
            self.outports.clear()

    def open_many(self, input_names: list[str], output_names: list[str]) -> None:
        if mido is None:
            raise RuntimeError(f"mido import failed: {MIDO_IMPORT_ERROR}")
        self.close()
        with self.lock:
            for in_name in input_names:
                self.inports[in_name] = mido.open_input(
                    in_name,
                    callback=lambda msg, port_name=in_name: self._on_message(port_name, msg),
                )
            for out_name in output_names:
                self.outports[out_name] = mido.open_output(out_name)

    def send_to(self, raw: bytes, output_names: list[str], gap_s: float = 0.035) -> list[str]:
        if mido is None:
            raise RuntimeError(f"mido import failed: {MIDO_IMPORT_ERROR}")
        if not output_names:
            raise RuntimeError("No MIDI OUT target selected/open")
        sent: list[str] = []
        with self.lock:
            for idx, out_name in enumerate(output_names):
                port = self.outports.get(out_name)
                if port is None:
                    raise RuntimeError(f"MIDI OUT port is not open: {out_name!r}")
                port.send(mido.Message.from_bytes(list(raw)))
                sent.append(out_name)
                if gap_s > 0 and idx < len(output_names) - 1:
                    time.sleep(gap_s)
        return sent

    def open_input_names(self) -> list[str]:
        return list(self.inports.keys())

    def open_output_names(self) -> list[str]:
        return list(self.outports.keys())

    def _on_message(self, port_name: str, msg) -> None:
        try:
            raw = bytes(msg.bytes())
        except Exception:
            raw = bytes()
        self.incoming.put(("midi", (port_name, getattr(msg, "type", "unknown"), raw)))


class RequestLab:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("minilogue xd Request Lab v5.7 - Raw Port Finder")
        self.root.geometry("1220x760")

        self.queue: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self.midi = MidiWorker(self.queue)
        self.input_ports: list[str] = []
        self.output_ports: list[str] = []
        self.capture: list[bytes] = []
        self.records: dict[int, ProgramRecord] = {}
        self.expected_mode = "idle"
        self.expected_slot: Optional[int] = None

        self.slot_var = tk.StringVar(value="1")
        self.status_var = tk.StringVar(value="Refresh ports, then open RX P1 or RX P2 for manual dump test.")
        self.progress_var = tk.StringVar(value="Idle")

        self.monitor_active = False
        self.monitor_end = 0.0
        self.monitor_counts: dict[str, dict[str, int]] = {}

        self._build_gui()
        self._log("v5.7 Raw Port Finder. Do not run Pocket MIDI in parallel with this tool.")
        self.refresh_ports()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(50, self.process_queue)

    def _build_gui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(3, weight=1)

        top = ttk.LabelFrame(self.root, text="MIDI port opening")
        top.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        top.columnconfigure(9, weight=1)
        ttk.Button(top, text="Refresh", command=self.refresh_ports).grid(row=0, column=0, padx=4, pady=6)
        ttk.Button(top, text="RX P1 only", command=lambda: self.open_xd("p1", "none")).grid(row=0, column=1, padx=4, pady=6)
        ttk.Button(top, text="RX P2 only", command=lambda: self.open_xd("p2", "none")).grid(row=0, column=2, padx=4, pady=6)
        ttk.Button(top, text="RX both", command=lambda: self.open_xd("both", "none")).grid(row=0, column=3, padx=4, pady=6)
        ttk.Button(top, text="RX P1 + TX all", command=lambda: self.open_xd("p1", "all")).grid(row=0, column=4, padx=4, pady=6)
        ttk.Button(top, text="RX P2 + TX all", command=lambda: self.open_xd("p2", "all")).grid(row=0, column=5, padx=4, pady=6)
        ttk.Button(top, text="RX both + TX all", command=lambda: self.open_xd("both", "all")).grid(row=0, column=6, padx=4, pady=6)
        ttk.Button(top, text="Close", command=self.close_ports).grid(row=0, column=7, padx=4, pady=6)
        ttk.Label(top, textvariable=self.status_var).grid(row=1, column=0, columnspan=10, sticky="ew", padx=4, pady=(0, 6))

        req = ttk.LabelFrame(self.root, text="Tests")
        req.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))
        ttk.Label(req, text="Slot").grid(row=0, column=0, padx=(4, 2), pady=6, sticky="w")
        ttk.Entry(req, textvariable=self.slot_var, width=7).grid(row=0, column=1, padx=(2, 12), pady=6, sticky="w")
        ttk.Button(req, text="Manual monitor 30s", command=self.start_manual_monitor).grid(row=0, column=2, padx=4, pady=6)
        ttk.Button(req, text="Listen manual", command=self.listen_manual).grid(row=0, column=3, padx=4, pady=6)
        ttk.Button(req, text="Global P1", command=lambda: self.send_global("p1")).grid(row=0, column=4, padx=4, pady=6)
        ttk.Button(req, text="Global P2", command=lambda: self.send_global("p2")).grid(row=0, column=5, padx=4, pady=6)
        ttk.Button(req, text="Current P1 10 00", command=lambda: self.send_current("p1", True)).grid(row=0, column=6, padx=4, pady=6)
        ttk.Button(req, text="Current P2 10 00", command=lambda: self.send_current("p2", True)).grid(row=0, column=7, padx=4, pady=6)
        ttk.Button(req, text="PC P2 → SX P1", command=lambda: self.send_split("p1", True)).grid(row=1, column=4, padx=4, pady=6)
        ttk.Button(req, text="PC P2 → SX P2", command=lambda: self.send_split("p2", True)).grid(row=1, column=5, padx=4, pady=6)
        ttk.Button(req, text="PC P2 → SX P1 no00", command=lambda: self.send_split("p1", False)).grid(row=1, column=6, padx=4, pady=6)
        ttk.Button(req, text="PC P2 → SX P2 no00", command=lambda: self.send_split("p2", False)).grid(row=1, column=7, padx=4, pady=6)

        files = ttk.LabelFrame(self.root, text="Capture / offline parser")
        files.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 8))
        ttk.Button(files, text="Load .syx", command=self.load_syx).grid(row=0, column=0, padx=4, pady=6)
        ttk.Button(files, text="Save capture .syx", command=self.save_capture).grid(row=0, column=1, padx=4, pady=6)
        ttk.Button(files, text="Import Pocket hex from clipboard", command=self.import_hex_clipboard).grid(row=0, column=2, padx=4, pady=6)
        ttk.Label(files, textvariable=self.progress_var).grid(row=0, column=3, sticky="w", padx=8)

        body = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        body.grid(row=3, column=0, sticky="nsew", padx=8, pady=(0, 8))
        left = ttk.Frame(body)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        body.add(left, weight=1)
        self.tree = ttk.Treeview(left, columns=("slot", "name", "cmd", "source", "bytes"), show="headings", selectmode="browse")
        for col, label, width in [("slot", "Slot", 60), ("name", "Name", 190), ("cmd", "Cmd", 70), ("source", "Source", 230), ("bytes", "Bytes", 80)]:
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, anchor=tk.W)
        self.tree.grid(row=0, column=0, sticky="nsew")
        right = ttk.Frame(body)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        body.add(right, weight=2)
        self.log = scrolledtext.ScrolledText(right, wrap=tk.NONE, font=("Consolas", 10))
        self.log.grid(row=0, column=0, sticky="nsew")

    def refresh_ports(self) -> None:
        if mido is None:
            messagebox.showerror("mido missing", f"mido import failed: {MIDO_IMPORT_ERROR}")
            return
        try:
            self.input_ports = sorted(list(mido.get_input_names()), key=port_sort_key)
            self.output_ports = sorted(list(mido.get_output_names()), key=port_sort_key)
        except Exception as exc:
            self._log(f"Port refresh failed: {exc}")
            messagebox.showerror("Port refresh failed", str(exc))
            return
        self._log(
            f"Ports refreshed: {len(self.input_ports)} input, {len(self.output_ports)} output; "
            f"XD inputs={self.xd_inputs()}; XD outputs={self.xd_outputs()}"
        )

    def xd_inputs(self) -> list[str]:
        return sorted([p for p in self.input_ports if is_xd_port(p)], key=port_sort_key)

    def xd_outputs(self) -> list[str]:
        return sorted([p for p in self.output_ports if is_xd_port(p)], key=port_sort_key)

    def ports_for_mode(self, ports: list[str], mode: str) -> list[str]:
        if mode == "none":
            return []
        if mode == "both" or mode == "all":
            return ports
        if mode == "p1":
            return [p for p in ports if not is_port2(p)]
        if mode == "p2":
            return [p for p in ports if is_port2(p)]
        return []

    def open_xd(self, rx_mode: str, tx_mode: str) -> None:
        if not self.input_ports and not self.output_ports:
            self.refresh_ports()
        ins = self.ports_for_mode(self.xd_inputs(), rx_mode)
        outs = self.ports_for_mode(self.xd_outputs(), tx_mode)
        try:
            self.midi.open_many(ins, outs)
        except Exception as exc:
            self._log(f"Open failed: {exc}")
            messagebox.showerror("Open failed", str(exc))
            return
        self.status_var.set(f"Opened RX={ins}, TX={outs}")
        self._log(self.status_var.get())

    def close_ports(self) -> None:
        self.midi.close()
        self.status_var.set("Ports closed.")
        self._log("Ports closed.")

    def slot_index(self) -> int:
        display_slot = int(self.slot_var.get())
        if not 1 <= display_slot <= 500:
            raise ValueError("slot must be 1..500")
        return display_slot - 1

    def tx_targets(self, mode: str) -> list[str]:
        opened = self.midi.open_output_names()
        return self.ports_for_mode(sorted([p for p in opened if is_xd_port(p)], key=port_sort_key), mode)

    def send_global(self, tx_mode: str) -> None:
        self.capture.clear()
        raw = request_global_data(0)
        targets = self.tx_targets(tx_mode)
        self._send(raw, targets, f"Global 0x0E to {tx_mode}")

    def send_current(self, tx_mode: str, trailing_zero: bool) -> None:
        self.capture.clear()
        raw = request_current_program(0, trailing_zero)
        targets = self.tx_targets(tx_mode)
        self.expected_mode = "current"
        self.expected_slot = None
        self._send(raw, targets, f"Current 0x10{' 00' if trailing_zero else ''} to {tx_mode}")

    def send_split(self, sysex_mode: str, trailing_zero: bool) -> None:
        try:
            slot = self.slot_index()
        except Exception as exc:
            messagebox.showerror("Invalid slot", str(exc))
            return
        pc_targets = self.tx_targets("p2")
        sx_targets = self.tx_targets(sysex_mode)
        if not pc_targets or not sx_targets:
            self._log(f"Split needs TX P2 and TX {sysex_mode}. Open RX + TX all first. pc={pc_targets}, sx={sx_targets}")
            return
        self.capture.clear()
        self.expected_mode = "slot_via_pc"
        self.expected_slot = slot
        self._log(
            f"Split slot {slot + 1:03d}: PC->P2 {pc_targets}; "
            f"Current-> {sysex_mode} {sx_targets}; trailing00={trailing_zero}; RX={self.midi.open_input_names()}"
        )
        try:
            for msg in program_change_messages(slot, 0):
                self._log(f"TX PC-prep: {hex_line(msg)}")
                self.midi.send_to(msg, pc_targets, gap_s=0.0)
            time.sleep(0.250)
            raw = request_current_program(0, trailing_zero)
            self._send(raw, sx_targets, "Current after PC")
        except Exception as exc:
            self._log(f"Split failed: {exc}")
            messagebox.showerror("Split failed", str(exc))

    def _send(self, raw: bytes, targets: list[str], label: str) -> None:
        if not targets:
            self._log(f"No TX targets for {label}. Open RX + TX all or correct TX mode first.")
            return
        try:
            self._log(f"TX {label}: {hex_line(raw)}")
            self._log(f"TX targets={targets}; RX open={self.midi.open_input_names()}")
            sent = self.midi.send_to(raw, targets)
            self._log(f"TX sent on {len(sent)} output(s): {sent}")
        except Exception as exc:
            self._log(f"TX failed {label}: {exc}")
            messagebox.showerror("TX failed", str(exc))

    def listen_manual(self) -> None:
        self.expected_mode = "manual"
        self.expected_slot = None
        self.capture.clear()
        self._log(f"Manual listener active. RX open={self.midi.open_input_names()}. Trigger Program Dump on XD.")

    def start_manual_monitor(self) -> None:
        self.expected_mode = "manual"
        self.expected_slot = None
        self.capture.clear()
        self.monitor_counts = {name: {"total": 0, "realtime": 0, "sysex": 0, "other": 0, "bytes": 0} for name in self.midi.open_input_names()}
        self.monitor_active = True
        self.monitor_end = time.time() + 30.0
        self._log(f"Manual raw monitor started for 30 s. RX open={self.midi.open_input_names()}")
        self._log("Now trigger PROGRAM EDIT -> DUMP -> Program Dump -> WRITE on the XD.")
        self.root.after(30000, self.finish_monitor)

    def finish_monitor(self) -> None:
        if not self.monitor_active:
            return
        self.monitor_active = False
        self._log("Manual raw monitor finished. Summary:")
        for port, c in self.monitor_counts.items():
            self._log(
                f"  {port!r}: total={c['total']}, realtime={c['realtime']}, "
                f"sysex={c['sysex']}, other={c['other']}, bytes={c['bytes']}"
            )
        self.progress_var.set("Monitor finished")

    def process_queue(self) -> None:
        while True:
            try:
                kind, payload = self.queue.get_nowait()
            except queue.Empty:
                break
            if kind == "midi":
                port_name, msg_type, raw = payload
                self._count_monitor(port_name, msg_type, raw)
                if raw and raw[0] == 0xF0:
                    self._handle_sysex(raw, source=f"live:{port_name}")
                elif msg_type not in REALTIME_TYPES:
                    self._log(f"MIDI IN {port_name!r} {msg_type}: {hex_line(raw)}")
            elif kind == "log":
                self._log(str(payload))
        self.root.after(50, self.process_queue)

    def _count_monitor(self, port_name: str, msg_type: str, raw: bytes) -> None:
        if not self.monitor_active:
            return
        c = self.monitor_counts.setdefault(port_name, {"total": 0, "realtime": 0, "sysex": 0, "other": 0, "bytes": 0})
        c["total"] += 1
        c["bytes"] += len(raw)
        if raw and raw[0] == 0xF0:
            c["sysex"] += 1
        elif msg_type in REALTIME_TYPES:
            c["realtime"] += 1
        else:
            c["other"] += 1

    def _handle_sysex(self, raw: bytes, source: str) -> None:
        self.capture.append(raw)
        cmd, label = classify_xd_sysex(raw)
        self._log(f"RX SysEx source={source} len={len(raw)} cmd={'none' if cmd is None else f'0x{cmd:02X}'} type={label}")
        self._log(f"RX bytes: {hex_line(raw)}")
        if cmd in (CMD_RX_CURRENT, CMD_RX_PROGRAM):
            slot = None if self.expected_mode == "manual" else self.expected_slot
            name = extract_program_name(raw)
            key = slot if slot is not None else -1
            rec = ProgramRecord(slot, name, raw, source, cmd)
            self.records[key] = rec
            self._update_tree_record(key, rec)
            self._log(f"Decoded program: slot={rec.display_slot} name={rec.name!r} cmd=0x{cmd:02X}")
            self.progress_var.set(f"Program dump received: {rec.name}, {len(raw)} bytes from {source}")
        elif cmd == CMD_RX_GLOBAL:
            self._log("Global data received. This is diagnostic data, not a program dump.")

    def _update_tree_record(self, key: int, record: ProgramRecord) -> None:
        iid = str(key)
        values = (record.display_slot, record.name, f"0x{record.command:02X}", record.source, len(record.raw))
        if self.tree.exists(iid):
            self.tree.item(iid, values=values)
        else:
            self.tree.insert("", tk.END, iid=iid, values=values)

    def load_syx(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("SysEx", "*.syx"), ("All files", "*.*")])
        if not path:
            return
        data = Path(path).read_bytes()
        messages = split_sysex_stream(data)
        self._log(f"Loaded {len(messages)} SysEx message(s) from {path}")
        for msg in messages:
            self._handle_sysex(msg, source=f"file:{Path(path).name}")

    def save_capture(self) -> None:
        if not self.capture:
            messagebox.showinfo("No capture", "No SysEx captured.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".syx", filetypes=[("SysEx", "*.syx")])
        if path:
            Path(path).write_bytes(b"".join(self.capture))
            self._log(f"Saved capture: {path}")

    def import_hex_clipboard(self) -> None:
        try:
            text = self.root.clipboard_get()
        except Exception as exc:
            messagebox.showerror("Clipboard", str(exc))
            return
        data = parse_hex_text(text)
        if not data:
            messagebox.showinfo("No hex", "Clipboard contains no hex bytes.")
            return
        messages = split_sysex_stream(data)
        self._log(f"Imported clipboard hex: {len(data)} byte(s), {len(messages)} SysEx message(s).")
        if data.count(0xF8):
            self._log(f"Clipboard contains {data.count(0xF8)} MIDI clock F8 byte(s); ignored outside SysEx.")
        for msg in messages:
            self._handle_sysex(msg, source="clipboard_hex")

    def _log(self, text: str) -> None:
        self.log.insert(tk.END, f"[{time.strftime('%H:%M:%S')}] {text}\n")
        self.log.see(tk.END)

    def on_close(self) -> None:
        try:
            self.midi.close()
        finally:
            self.root.destroy()


def main() -> int:
    root = tk.Tk()
    RequestLab(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

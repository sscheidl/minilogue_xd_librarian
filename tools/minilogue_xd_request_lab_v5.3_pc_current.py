#!/usr/bin/env python3
"""
minilogue_xd_request_lab_v5.3_pc_current.py

Standalone diagnostic GUI for Korg minilogue xd SysEx request/read/write tests.

Scope:
- Request Global Diagnostic (0x0E -> expected 0x51)
- Request Current Program (0x10, with optional trailing 00)
- Request Single Slot (0x1C pp PP, with optional trailing 00)
- Sequential Full Bank request (500 single-slot requests, wait per slot)
- Manual dump capture
- Write selected single program dump
- Write loaded/captured bank program dumps

v5.2 multiport startup:
- auto-refreshes MIDI ports after GUI init
- auto-opens all minilogue xd input/output ports by default
- listens on all XD inputs simultaneously
- sends requests according to TX mode: selected, XD Port 1, XD Port 2, or all XD outputs

v5.3 PC+Current:
- adds Slot via PC+Current: Bank Select LSB + Program Change, wait 80 ms, then Current Request 0x10
- Full Bank Sequential now uses PC+Current instead of direct 0x1C slot requests
- default inter-slot delay is 200 ms

Requirements:
    pip install mido python-rtmidi

v4.1 fixes:
- Full-bank loop reads trailing_slot_var, not the old trailing_zero_slot_var name.
- Uses CMD_RX_PROGRAM consistently for received 0x4C dumps.
- Keeps Thread construction syntactically explicit and safe.
- Simplifies preferred Port-2 marker handling.
"""
from __future__ import annotations

import queue
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
CMD_REQ_PROGRAM = 0x1C
CMD_REQ_GLOBAL = 0x0E
CMD_RX_CURRENT = 0x40
CMD_RX_PROGRAM = 0x4C
CMD_RX_GLOBAL = 0x51

REALTIME_TYPES = {"clock", "start", "stop", "continue", "active_sensing", "reset"}


def korg_xd_header(channel: int = 0) -> list[int]:
    if not 0 <= channel <= 15:
        raise ValueError(f"channel must be 0..15, got {channel!r}")
    return [0xF0, KORG_ID, 0x30 | (channel & 0x0F), *XD_TAIL]


def request_global_data(channel: int = 0) -> bytes:
    return bytes(korg_xd_header(channel) + [CMD_REQ_GLOBAL, 0xF7])


def request_current_program(channel: int = 0, trailing_zero: bool = True) -> bytes:
    body = [CMD_REQ_CURRENT]
    if trailing_zero:
        body.append(0x00)
    return bytes(korg_xd_header(channel) + body + [0xF7])


def slot_to_lsb_msb(slot_index: int) -> tuple[int, int]:
    if not 0 <= slot_index <= 499:
        raise ValueError(f"slot_index must be 0..499, got {slot_index!r}")
    return slot_index & 0x7F, (slot_index >> 7) & 0x7F


def request_program_slot(slot_index: int, channel: int = 0, trailing_zero: bool = True) -> bytes:
    lsb, msb = slot_to_lsb_msb(slot_index)
    body = [CMD_REQ_PROGRAM, lsb, msb]
    if trailing_zero:
        body.append(0x00)
    return bytes(korg_xd_header(channel) + body + [0xF7])


def slot_to_program_change(slot_index: int) -> tuple[int, int]:
    """Korg XD: 500 slots in 5 banks of 100 programs."""
    if not 0 <= slot_index <= 499:
        raise ValueError(f"slot_index must be 0..499, got {slot_index!r}")
    return slot_index // 100, slot_index % 100


def program_change_messages(slot_index: int, channel: int = 0) -> list[bytes]:
    """Bank Select LSB (CC 32) + Program Change before Current Program Request."""
    bank, prog = slot_to_program_change(slot_index)
    ch = channel & 0x0F
    return [
        bytes([0xB0 | ch, 0x20, bank]),  # CC 32 Bank Select LSB
        bytes([0xC0 | ch, prog]),         # Program Change
    ]


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
    label = {
        CMD_RX_CURRENT: "current-program-dump-0x40",
        CMD_RX_PROGRAM: "program-dump-0x4C",
        0x44: "program-bank-index-0x44",
        0x45: "sequencer-index-0x45",
        CMD_RX_GLOBAL: "global-data-0x51",
    }.get(cmd, f"unknown-xd-cmd-0x{cmd:02X}")
    return cmd, label


def hex_line(raw: bytes, max_len: int = 96) -> str:
    text = " ".join(f"{b:02X}" for b in raw[:max_len])
    if len(raw) > max_len:
        text += f" ... ({len(raw)} bytes)"
    return text


def extract_program_name(raw: bytes) -> str:
    """Best-effort name extraction. Returns 'name unknown' if uncertain."""
    candidates: list[str] = []
    for start in (8, 9, 10, 7, 6):
        if len(raw) >= start + 12:
            chunk = raw[start:start + 12]
            text = chunk.split(b"\x00", 1)[0].decode("ascii", errors="ignore").strip()
            text = "".join(ch for ch in text if 32 <= ord(ch) <= 126).strip()
            if text and text not in {"@", "L"}:
                candidates.append(text)
    return candidates[0] if candidates else "name unknown"


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


def is_xd_port(name: str) -> bool:
    return "minilogue xd" in name.lower()


def is_port2(name: str) -> bool:
    low = name.lower()
    return "midiin2" in low or "midiout2" in low or low.rstrip().endswith(" 2") or low.rstrip().endswith(") 2")


def port_sort_key(name: str) -> tuple[int, str]:
    """Sort XD Port 1 before XD Port 2, then everything else."""
    low = name.lower()
    if is_xd_port(name):
        return (1 if is_port2(name) else 0, low)
    return (9, low)


class MidiWorker:
    """MIDI I/O helper with multiple open input and output ports.

    v5.2 deliberately supports listening on all minilogue xd inputs at once.
    Outputs are opened as a pool; requests can be sent to selected, Port 1,
    Port 2, or all opened XD outputs.
    """

    def __init__(self, incoming: "queue.Queue[tuple[str, object]]") -> None:
        self.incoming = incoming
        self.inports: dict[str, object] = {}
        self.outports: dict[str, object] = {}
        self.lock = threading.RLock()

    def open(self, in_name: Optional[str], out_name: Optional[str]) -> None:
        if mido is None:
            raise RuntimeError(f"mido import failed: {MIDO_IMPORT_ERROR}")
        self.close()
        if in_name:
            self.inports[in_name] = mido.open_input(
                in_name,
                callback=lambda msg, port_name=in_name: self._on_message(port_name, msg),
            )
        if out_name:
            self.outports[out_name] = mido.open_output(out_name)

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
        self.root.title("minilogue xd Request Lab v5.3 - PC+Current")
        self.root.geometry("1180x780")

        self.queue: "queue.Queue[tuple[str, object]]" = queue.Queue()
        # Receives slot numbers whenever the GUI thread has decoded a 0x4C program dump.
        # Full-bank worker waits on this queue after each individual slot request.
        self.program_response_queue: "queue.Queue[int]" = queue.Queue()
        self.midi = MidiWorker(self.queue)
        self.input_ports: list[str] = []
        self.output_ports: list[str] = []
        self.records: dict[int, ProgramRecord] = {}
        self.capture: list[bytes] = []
        self.expected_mode = "idle"
        self.expected_slot: Optional[int] = None
        self.cancel_event = threading.Event()
        self.probe_found_event = threading.Event()
        self.last_program_response: tuple[int, int] | None = None  # (cmd, slot_or_minus1)
        self.operation_thread: Optional[threading.Thread] = None

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.tx_mode_var = tk.StringVar(value="All XD outputs")
        self.auto_open_var = tk.BooleanVar(value=True)
        self.channel_var = tk.StringVar(value="0")
        self.slot_var = tk.StringVar(value="1")
        self.timeout_var = tk.StringVar(value="3.0")
        self.delay_var = tk.StringVar(value="200")
        self.trailing_current_var = tk.BooleanVar(value=True)
        self.trailing_slot_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="Safe startup: MIDI ports are not scanned yet.")
        self.progress_var = tk.StringVar(value="Idle")

        self._build_gui()
        self._log("v5.3: auto-open all XD ports; adds Slot via PC+Current strategy.")
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(50, self.process_queue)
        root.after(500, self.auto_open_all_xd_startup)

    def _build_gui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(3, weight=1)

        top = ttk.LabelFrame(self.root, text="MIDI Ports")
        top.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        top.columnconfigure(1, weight=1)
        top.columnconfigure(3, weight=1)
        ttk.Label(top, text="MIDI IN").grid(row=0, column=0, padx=4, pady=4, sticky="w")
        self.in_combo = ttk.Combobox(top, textvariable=self.input_var, state="readonly")
        self.in_combo.grid(row=0, column=1, padx=4, pady=4, sticky="ew")
        ttk.Label(top, text="MIDI OUT").grid(row=0, column=2, padx=4, pady=4, sticky="w")
        self.out_combo = ttk.Combobox(top, textvariable=self.output_var, state="readonly")
        self.out_combo.grid(row=0, column=3, padx=4, pady=4, sticky="ew")
        ttk.Button(top, text="Refresh Ports", command=self.refresh_ports).grid(row=0, column=4, padx=4)
        ttk.Button(top, text="Open Selected", command=self.open_ports).grid(row=0, column=5, padx=4)
        ttk.Button(top, text="Open All XD", command=self.open_all_xd_ports).grid(row=0, column=6, padx=4)
        ttk.Button(top, text="Close Ports", command=self.close_ports).grid(row=0, column=7, padx=4)
        ttk.Label(top, text="TX mode").grid(row=1, column=0, padx=4, pady=4, sticky="w")
        self.tx_mode_combo = ttk.Combobox(
            top,
            textvariable=self.tx_mode_var,
            state="readonly",
            width=18,
            values=("Selected output", "XD Port 1", "XD Port 2", "All XD outputs"),
        )
        self.tx_mode_combo.grid(row=1, column=1, padx=4, pady=4, sticky="w")
        ttk.Checkbutton(top, text="Auto-open all XD at startup", variable=self.auto_open_var).grid(row=1, column=2, columnspan=2, padx=4, pady=4, sticky="w")
        ttk.Label(top, textvariable=self.status_var).grid(row=2, column=0, columnspan=8, padx=4, pady=4, sticky="ew")

        req = ttk.LabelFrame(self.root, text="Requests")
        req.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))
        for col, (label, var, width) in enumerate([
            ("Channel", self.channel_var, 5),
            ("Slot 1-500", self.slot_var, 7),
            ("Timeout s", self.timeout_var, 7),
            ("Delay ms", self.delay_var, 7),
        ]):
            ttk.Label(req, text=label).grid(row=0, column=col * 2, padx=4, pady=4)
            ttk.Entry(req, textvariable=var, width=width).grid(row=0, column=col * 2 + 1, padx=4, pady=4)
        ttk.Checkbutton(req, text="Current trailing 00", variable=self.trailing_current_var).grid(row=1, column=0, columnspan=2, sticky="w", padx=4)
        ttk.Checkbutton(req, text="Slot trailing 00", variable=self.trailing_slot_var).grid(row=1, column=2, columnspan=2, sticky="w", padx=4)
        ttk.Button(req, text="Request Global 0x0E", command=self.request_global).grid(row=2, column=0, padx=4, pady=6)
        ttk.Button(req, text="Request Current", command=self.request_current).grid(row=2, column=1, padx=4, pady=6)
        ttk.Button(req, text="Request Slot", command=self.request_slot).grid(row=2, column=2, padx=4, pady=6)
        ttk.Button(req, text="Probe Current/Slot", command=self.probe_current_slot).grid(row=2, column=3, padx=4, pady=6)
        ttk.Button(req, text="Slot via PC+Current", command=self.request_slot_via_pc).grid(row=2, column=4, padx=4, pady=6)
        ttk.Button(req, text="Full Bank Sequential", command=self.request_full_bank).grid(row=2, column=5, padx=4, pady=6)
        ttk.Button(req, text="Listen Manual Dump", command=self.listen_manual).grid(row=2, column=6, padx=4, pady=6)
        ttk.Button(req, text="Cancel", command=self.cancel_operation).grid(row=2, column=7, padx=4, pady=6)

        write = ttk.LabelFrame(self.root, text="Load / Save / Write")
        write.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 8))
        ttk.Button(write, text="Load .syx", command=self.load_syx).grid(row=0, column=0, padx=4, pady=6)
        ttk.Button(write, text="Save Capture .syx", command=self.save_capture).grid(row=0, column=1, padx=4, pady=6)
        ttk.Button(write, text="Write Selected Single", command=self.write_selected_single).grid(row=0, column=2, padx=4, pady=6)
        ttk.Button(write, text="Write Loaded/Captured Bank", command=self.write_bank).grid(row=0, column=3, padx=4, pady=6)
        ttk.Label(write, textvariable=self.progress_var).grid(row=0, column=4, sticky="w", padx=8)

        body = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        body.grid(row=3, column=0, sticky="nsew", padx=8, pady=(0, 8))
        left = ttk.Frame(body)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        body.add(left, weight=1)
        self.tree = ttk.Treeview(left, columns=("slot", "name", "cmd", "source", "bytes"), show="headings", selectmode="browse")
        for col, label, width in [("slot", "Slot", 60), ("name", "Name", 180), ("cmd", "Cmd", 70), ("source", "Source", 220), ("bytes", "Bytes", 80)]:
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
        self.in_combo["values"] = self.input_ports
        self.out_combo["values"] = self.output_ports
        self.input_var.set(self._preferred(self.input_ports))
        self.output_var.set(self._preferred(self.output_ports))
        xd_inputs = [p for p in self.input_ports if is_xd_port(p)]
        xd_outputs = [p for p in self.output_ports if is_xd_port(p)]
        self._log(
            f"Ports refreshed: {len(self.input_ports)} input, {len(self.output_ports)} output; "
            f"XD inputs={xd_inputs}; XD outputs={xd_outputs}"
        )

    @staticmethod
    def _preferred(ports: list[str]) -> str:
        """Prefer minilogue xd Port 1, not MIDIIN2/MIDIOUT2."""
        if not ports:
            return ""
        xd = sorted([port for port in ports if is_xd_port(port)], key=port_sort_key)
        return xd[0] if xd else ports[0]

    def xd_input_ports(self) -> list[str]:
        return sorted([port for port in self.input_ports if is_xd_port(port)], key=port_sort_key)

    def xd_output_ports(self) -> list[str]:
        return sorted([port for port in self.output_ports if is_xd_port(port)], key=port_sort_key)

    def auto_open_all_xd_startup(self) -> None:
        if not self.auto_open_var.get():
            self._log("Auto-open all XD at startup disabled.")
            return
        try:
            self.refresh_ports()
            if self.xd_input_ports() or self.xd_output_ports():
                self.open_all_xd_ports()
            else:
                self._log("Auto-open: no minilogue xd ports found.")
        except Exception as exc:
            self._log(f"Auto-open all XD failed: {exc}")

    def open_ports(self) -> None:
        try:
            self.midi.open(self.input_var.get() or None, self.output_var.get() or None)
        except Exception as exc:
            self._log(f"Open selected ports failed: {exc}")
            messagebox.showerror("Open selected ports failed", str(exc))
            return
        self.status_var.set(f"Selected ports opened: IN={self.input_var.get()!r}, OUT={self.output_var.get()!r}")
        self._log(self.status_var.get())

    def open_all_xd_ports(self) -> None:
        if not self.input_ports and not self.output_ports:
            self.refresh_ports()
        ins = self.xd_input_ports()
        outs = self.xd_output_ports()
        if not ins and not outs:
            self._log("Open All XD: no minilogue xd ports found.")
            messagebox.showwarning("No XD ports", "No minilogue xd input/output ports found.")
            return
        try:
            self.midi.open_many(ins, outs)
        except Exception as exc:
            self._log(f"Open all XD ports failed: {exc}")
            messagebox.showerror("Open all XD ports failed", str(exc))
            return
        if ins and not self.input_var.get():
            self.input_var.set(ins[0])
        if outs and not self.output_var.get():
            self.output_var.set(outs[0])
        self.status_var.set(f"All XD ports opened: IN={ins}, OUT={outs}")
        self._log(self.status_var.get())

    def close_ports(self) -> None:
        self.midi.close()
        self.status_var.set("Ports closed.")
        self._log("Ports closed.")

    def _target_output_names(self) -> list[str]:
        mode = self.tx_mode_var.get()
        opened = self.midi.open_output_names()
        xd_opened = sorted([p for p in opened if is_xd_port(p)], key=port_sort_key)
        if mode == "All XD outputs":
            return xd_opened
        if mode == "XD Port 1":
            return [p for p in xd_opened if not is_port2(p)]
        if mode == "XD Port 2":
            return [p for p in xd_opened if is_port2(p)]
        selected = self.output_var.get()
        return [selected] if selected in opened else []

    def channel(self) -> int:
        return int(self.channel_var.get())

    def slot_index(self) -> int:
        display_slot = int(self.slot_var.get())
        if not 1 <= display_slot <= 500:
            raise ValueError("slot must be 1..500")
        return display_slot - 1

    def timeout_s(self) -> float:
        return float(self.timeout_var.get())

    def delay_s(self) -> float:
        return max(0.0, int(self.delay_var.get()) / 1000.0)

    def request_global(self) -> None:
        raw = request_global_data(self.channel())
        self.expected_mode = "global"
        self.expected_slot = None
        self._send_request(raw, "Request Global Diagnostic", CMD_RX_GLOBAL)

    def request_current(self) -> None:
        raw = request_current_program(self.channel(), self.trailing_current_var.get())
        self.expected_mode = "current"
        self.expected_slot = None
        self._send_request(raw, "Request Current", CMD_RX_CURRENT)

    def request_slot(self) -> None:
        slot = self.slot_index()
        raw = request_program_slot(slot, self.channel(), self.trailing_slot_var.get())
        self.expected_mode = "slot"
        self.expected_slot = slot
        self._send_request(raw, f"Request Slot {slot + 1:03d}", CMD_RX_PROGRAM)

    def request_slot_via_pc(self) -> None:
        """Bank Select + Program Change, then Request Current Program (0x10).

        This is a diagnostic strategy for devices that ignore direct 0x1C slot
        requests but answer a Current Program Request after the requested slot
        has been selected with normal MIDI messages.
        """
        try:
            slot = self.slot_index()
            ch = self.channel()
            pc_msgs = program_change_messages(slot, ch)
            sysex = request_current_program(ch, self.trailing_current_var.get())
            targets = self._target_output_names()
        except Exception as exc:
            messagebox.showerror("Request Slot via PC", str(exc))
            return

        self.expected_mode = "slot_via_pc"
        self.expected_slot = slot
        self.capture.clear()

        if not targets:
            self._log("No TX targets open.")
            return

        try:
            self._log(
                f"TX Slot via PC+Current slot {slot + 1:03d}: "
                f"channel={ch}, targets={targets}, listening on inputs={self.midi.open_input_names()}"
            )
            for msg_bytes in pc_msgs:
                self._log(f"TX PC-prep: {hex_line(msg_bytes)}")
                sent = self.midi.send_to(msg_bytes, targets, gap_s=0.0)
                self._log(f"TX PC-prep sent on outputs: {sent}")
            time.sleep(0.080)
            self._log(f"TX Request Current after PC: {hex_line(sysex)}")
            self._log(f"Waiting for cmd=0x40 up to {self.timeout_s()} s")
            sent = self.midi.send_to(sysex, targets)
            self._log(f"TX sent on {len(sent)} output(s): {sent}")
        except Exception as exc:
            self._log(f"Request Slot via PC failed: {exc}")
            messagebox.showerror("Request Slot via PC", str(exc))

    def _send_request(self, raw: bytes, label: str, expected: int) -> None:
        try:
            self.capture.clear()
            targets = self._target_output_names()
            self._log(f"TX {label}: {hex_line(raw)}")
            self._log(f"TX mode={self.tx_mode_var.get()!r}; targets={targets}")
            self._log(f"Listening on inputs={self.midi.open_input_names()}")
            self._log(f"Waiting for cmd=0x{expected:02X} up to {self.timeout_s()} s")
            sent = self.midi.send_to(raw, targets)
            self._log(f"TX sent on {len(sent)} output(s): {sent}")
        except Exception as exc:
            self._log(f"{label} failed: {exc}")
            messagebox.showerror(label, str(exc))

    def probe_current_slot(self) -> None:
        """Probe all Korg SysEx channel/device IDs and request variants.

        Tests 16 channel/device IDs:
        - Current Program with trailing 00 ON/OFF
        - Selected Slot Program with trailing 00 ON/OFF

        Stops as soon as a 0x40 or 0x4C response is decoded.
        """
        if self.operation_thread and self.operation_thread.is_alive():
            messagebox.showwarning("Busy", "An operation is already running.")
            return

        try:
            slot = self.slot_index()
            timeout_s = self.timeout_s()
        except Exception as exc:
            messagebox.showerror("Invalid settings", str(exc))
            return

        if not messagebox.askyesno(
            "Probe Current/Slot",
            "Probe channels 0..15 and request variants?\n\n"
            "For each channel this sends:\n"
            "- Current with trailing 00 ON/OFF\n"
            "- Selected Slot with trailing 00 ON/OFF\n\n"
            "The probe stops at the first 0x40 or 0x4C response.\n"
            f"Selected slot: {slot + 1:03d}\n"
            f"Timeout per request: {timeout_s:.1f} s",
        ):
            return

        self.cancel_event.clear()
        self.probe_found_event.clear()
        self.last_program_response = None
        self.progress_var.set("Probe starting...")
        targets = self._target_output_names()
        if not targets:
            messagebox.showerror("No TX targets", "No output targets are open for the selected TX mode.")
            return
        self._log(f"Probe targets: {targets}; listening on inputs={self.midi.open_input_names()}")
        self.operation_thread = threading.Thread(
            target=self._probe_worker,
            args=(slot, timeout_s, targets),
            daemon=True,
            name="probe-current-slot-worker",
        )
        self.operation_thread.start()

    def _probe_worker(self, slot: int, timeout_s: float, target_names: list[str]) -> None:
        """Worker for Probe Current/Slot. Never touches Tk directly."""
        variants: list[tuple[str, bool, int]] = [
            ("Current trailing00=ON", True, CMD_RX_CURRENT),
            ("Current trailing00=OFF", False, CMD_RX_CURRENT),
            ("Slot trailing00=ON", True, CMD_RX_PROGRAM),
            ("Slot trailing00=OFF", False, CMD_RX_PROGRAM),
        ]

        for channel in range(16):
            if self.cancel_event.is_set():
                self.queue.put(("log", "Probe cancelled."))
                self.queue.put(("progress", "Probe cancelled."))
                return

            for label, trailing_zero, expected_cmd in variants:
                if self.cancel_event.is_set():
                    self.queue.put(("log", "Probe cancelled."))
                    self.queue.put(("progress", "Probe cancelled."))
                    return

                self.probe_found_event.clear()
                self.last_program_response = None

                if expected_cmd == CMD_RX_CURRENT:
                    raw = request_current_program(channel, trailing_zero)
                    self.expected_mode = "probe_current"
                    self.expected_slot = None
                else:
                    raw = request_program_slot(slot, channel, trailing_zero)
                    self.expected_mode = "probe_slot"
                    self.expected_slot = slot

                self.queue.put((
                    "log",
                    f"PROBE TX ch={channel} header=0x{0x30 | channel:02X} {label}: {hex_line(raw)}",
                ))
                self.queue.put((
                    "progress",
                    f"Probe ch {channel:02d}/15: {label}, waiting {timeout_s:.1f} s",
                ))

                try:
                    sent = self.midi.send_to(raw, target_names)
                    self.queue.put(("log", f"PROBE sent on outputs: {sent}"))
                except Exception as exc:
                    self.queue.put(("log", f"Probe send failed on channel {channel}, {label}: {exc}"))
                    continue

                if self.probe_found_event.wait(timeout=timeout_s):
                    response = self.last_program_response
                    cmd_text = "unknown" if response is None else f"0x{response[0]:02X}"
                    slot_text = "" if response is None or response[1] < 0 else f", slot={response[1] + 1:03d}"
                    self.queue.put((
                        "log",
                        f"FOUND RESPONSE: channel={channel}, header=0x{0x30 | channel:02X}, "
                        f"request={label}, response={cmd_text}{slot_text}",
                    ))
                    self.queue.put((
                        "progress",
                        f"Found response: channel {channel}, {label}, response {cmd_text}{slot_text}",
                    ))
                    self.queue.put(("set_probe_result", (channel, label, trailing_zero, expected_cmd)))
                    return

                self.queue.put(("log", f"Probe timeout: channel={channel}, {label}"))

        self.expected_mode = "idle"
        self.expected_slot = None
        self.queue.put(("log", "Probe finished: no 0x40/0x4C response found."))
        self.queue.put(("progress", "Probe finished: no response found."))

    def request_full_bank(self) -> None:
        """Request all 500 program slots sequentially.

        This deliberately does NOT use 0x0E and never sends a 500-message burst.
        It sends one Program Dump Request, waits for a 0x4C response or timeout,
        then continues with the next slot.
        """
        if self.operation_thread and self.operation_thread.is_alive():
            messagebox.showwarning("Busy", "An operation is already running.")
            return

        try:
            channel = self.channel()
            timeout_s = self.timeout_s()
            delay_s = self.delay_s()
            trailing_zero = self.trailing_slot_var.get()
        except Exception as exc:
            messagebox.showerror("Invalid settings", str(exc))
            return

        if not messagebox.askyesno(
            "Full Bank Sequential Request",
            "Request all 500 slots one by one?\n\n"
            "This is non-destructive but may take several minutes.\n"
            "It sends exactly one Program Dump Request, waits for 0x4C/timeout,\n"
            "then continues with the next slot.\n\n"
            f"Request format uses trailing 00: {trailing_zero}\n"
            f"Timeout per slot: {timeout_s:.1f} s\n"
            f"Delay after each slot: {int(delay_s * 1000)} ms",
        ):
            return

        self.cancel_event.clear()
        self.progress_var.set("Full bank request starting...")
        targets = self._target_output_names()
        if not targets:
            messagebox.showerror("No TX targets", "No output targets are open for the selected TX mode.")
            return
        self._log(f"Full bank targets: {targets}; listening on inputs={self.midi.open_input_names()}")
        self.operation_thread = threading.Thread(
            target=self._full_bank_worker,
            args=(channel, trailing_zero, timeout_s, delay_s, targets),
            daemon=True,
            name="full-bank-request-worker",
        )
        self.operation_thread.start()

    def _drain_program_response_queue(self) -> None:
        while True:
            try:
                self.program_response_queue.get_nowait()
            except queue.Empty:
                return

    def _full_bank_worker(
        self,
        channel: int,
        trailing_zero: bool,
        timeout_s: float,
        delay_s: float,
        target_names: list[str],
    ) -> None:
        """Sequentially select slots and wait for each 0x40/0x4C response."""
        received = 0
        timeouts = 0
        mismatches = 0

        for slot in range(500):
            if self.cancel_event.is_set():
                self.queue.put(("log", "Full bank request cancelled."))
                break

            self._drain_program_response_queue()

            # Used by the GUI receive handler to map the next 0x40/0x4C to the requested slot.
            self.expected_mode = "bank"
            self.expected_slot = slot

            self.queue.put(("log", f"TX FullBank slot {slot + 1:03d} via PC+Current"))
            self.queue.put(("progress", f"Requesting patch {slot + 1:03d}/500"))

            try:
                for msg_bytes in program_change_messages(slot, channel):
                    self.queue.put(("log", f"TX FullBank PC-prep slot {slot + 1:03d}: {hex_line(msg_bytes)}"))
                    sent = self.midi.send_to(msg_bytes, target_names, gap_s=0.0)
                    self.queue.put(("log", f"TX FullBank PC-prep sent on outputs: {sent}"))
                time.sleep(0.080)
                raw = request_current_program(channel, trailing_zero)
                self.queue.put(("log", f"TX FullBank Current slot {slot + 1:03d}: {hex_line(raw)}"))
                sent = self.midi.send_to(raw, target_names)
                self.queue.put(("log", f"TX FullBank Current sent on outputs: {sent}"))
            except Exception as exc:
                self.queue.put(("log", f"Full bank send failed at slot {slot + 1:03d}: {exc}"))
                break

            response_slot = None
            wait_started = time.time()
            next_tick = wait_started
            deadline = wait_started + timeout_s

            while time.time() < deadline and not self.cancel_event.is_set():
                remaining = max(0.0, deadline - time.time())
                elapsed = time.time() - wait_started

                # Update the GUI about 5 times per second while waiting for the next 0x4C.
                if time.time() >= next_tick:
                    self.queue.put(
                        (
                            "progress",
                            f"Receiving patch {slot + 1:03d}/500 "
                            f"(received={received}, timeouts={timeouts}, mismatches={mismatches}; "
                            f"waiting {elapsed:.1f}/{timeout_s:.1f} s)",
                        )
                    )
                    next_tick = time.time() + 0.2

                try:
                    response_slot = self.program_response_queue.get(timeout=0.05)
                    break
                except queue.Empty:
                    pass

            if self.cancel_event.is_set():
                self.queue.put(("log", "Full bank request cancelled while waiting for response."))
                break

            if response_slot is None:
                timeouts += 1
                self.queue.put(("log", f"Timeout waiting for 0x40/0x4C slot {slot + 1:03d}; continuing."))
            else:
                if response_slot == slot:
                    received += 1
                    self.queue.put(("log", f"RX OK slot {slot + 1:03d} ({received}/500 received)."))
                else:
                    received += 1
                    mismatches += 1
                    self.queue.put(
                        (
                            "log",
                            "RX slot mismatch: requested "
                            f"{slot + 1:03d}, stored/decoded {response_slot + 1:03d}; continuing.",
                        )
                    )

            self.queue.put(
                (
                    "progress",
                    f"Processed patch {slot + 1:03d}/500, received={received}, "
                    f"timeouts={timeouts}, mismatches={mismatches}",
                )
            )

            if delay_s > 0:
                time.sleep(delay_s)

        self.expected_mode = "idle"
        self.expected_slot = None
        self.queue.put(
            (
                "progress",
                f"Full bank done. received={received}, timeouts={timeouts}, mismatches={mismatches}",
            )
        )
        self.queue.put(
            (
                "log",
                f"Full bank finished: received={received}, timeouts={timeouts}, mismatches={mismatches}",
            )
        )

    def listen_manual(self) -> None:
        self.expected_mode = "manual"
        self.expected_slot = None
        self.capture.clear()
        self._log("Manual dump listener active. Trigger Program Dump or All Dump on the XD.")

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

    def write_selected_single(self) -> None:
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("No selection", "Select one program first.")
            return
        rec = self.records.get(int(selection[0]))
        if not rec:
            return
        if rec.command not in (CMD_RX_PROGRAM, CMD_RX_CURRENT):
            messagebox.showwarning("Not a program", "Selected item is not a program dump.")
            return
        if not messagebox.askyesno("Write single to XD", f"Send selected program to XD?\n\nSlot: {rec.display_slot}\nName: {rec.name}\nBytes: {len(rec.raw)}\n\nThis may overwrite data on the device."):
            return
        try:
            targets = self._target_output_names()
            self._log(f"WRITE single: slot={rec.display_slot} name={rec.name}: {hex_line(rec.raw)}")
            self._log(f"WRITE single targets={targets}")
            sent = self.midi.send_to(rec.raw, targets)
            self._log(f"WRITE single sent on outputs: {sent}")
        except Exception as exc:
            messagebox.showerror("Write failed", str(exc))
            self._log(f"Write single failed: {exc}")

    def write_bank(self) -> None:
        records = [record for _, record in sorted(self.records.items()) if record.command == CMD_RX_PROGRAM]
        if not records:
            messagebox.showinfo("No bank data", "No 0x4C program dumps are loaded/captured.")
            return
        if self.operation_thread and self.operation_thread.is_alive():
            messagebox.showwarning("Busy", "An operation is already running.")
            return
        if not messagebox.askyesno("Write bank to XD", f"Send {len(records)} program dump(s) sequentially?\n\nThis may overwrite program slots on the device."):
            return
        targets = self._target_output_names()
        if not targets:
            messagebox.showerror("No TX targets", "No output targets are open for the selected TX mode.")
            return
        self.cancel_event.clear()
        self.operation_thread = threading.Thread(target=lambda: self._write_bank_worker(records, targets), daemon=True)
        self.operation_thread.start()

    def _write_bank_worker(self, records: list[ProgramRecord], target_names: list[str]) -> None:
        sent = 0
        for rec in records:
            if self.cancel_event.is_set():
                self.queue.put(("log", "Write bank cancelled."))
                break
            try:
                sent_outputs = self.midi.send_to(rec.raw, target_names)
                sent += 1
                self.queue.put(("log", f"WRITE {sent}/{len(records)} slot={rec.display_slot} name={rec.name} outputs={sent_outputs}"))
                self.queue.put(("progress", f"Write bank: sent {sent}/{len(records)}"))
            except Exception as exc:
                self.queue.put(("log", f"Write bank failed at {sent + 1}: {exc}"))
                break
            time.sleep(self.delay_s())
        self.queue.put(("progress", f"Write bank finished: sent {sent}/{len(records)}"))

    def cancel_operation(self) -> None:
        self.cancel_event.set()
        self.progress_var.set("Cancel requested.")
        self._log("Cancel requested.")

    def process_queue(self) -> None:
        while True:
            try:
                kind, payload = self.queue.get_nowait()
            except queue.Empty:
                break
            if kind == "midi":
                port_name, msg_type, raw = payload
                if raw and raw[0] == 0xF0:
                    self._handle_sysex(raw, source=f"live:{port_name}")
                elif msg_type not in REALTIME_TYPES:
                    self._log(f"MIDI IN {port_name!r} {msg_type}: {hex_line(raw)}")
            elif kind == "log":
                self._log(str(payload))
            elif kind == "progress":
                self.progress_var.set(str(payload))
            elif kind == "set_probe_result":
                channel, label, trailing_zero, expected_cmd = payload
                self.channel_var.set(str(channel))
                if expected_cmd == CMD_RX_CURRENT:
                    self.trailing_current_var.set(trailing_zero)
                else:
                    self.trailing_slot_var.set(trailing_zero)
                self.progress_var.set(
                    f"Probe applied: channel={channel}, {label}, trailing00={trailing_zero}"
                )
        self.root.after(50, self.process_queue)

    def _handle_sysex(self, raw: bytes, source: str) -> None:
        self.capture.append(raw)
        cmd, label = classify_xd_sysex(raw)
        self._log(f"RX SysEx len={len(raw)} cmd={'none' if cmd is None else f'0x{cmd:02X}'} type={label}")
        self._log(f"RX bytes: {hex_line(raw)}")
        if cmd == CMD_RX_GLOBAL:
            self._log("Global data received. This is diagnostic data, not a program dump.")
            return
        if cmd in (CMD_RX_PROGRAM, CMD_RX_CURRENT):
            if cmd == CMD_RX_PROGRAM:
                slot = self.expected_slot
            else:
                slot = None if self.expected_mode == "manual" else (self.expected_slot or 0)
            name = extract_program_name(raw)
            key = slot if slot is not None else -1
            record = ProgramRecord(slot, name, raw, source, cmd)
            self.records[key] = record
            self._update_tree_record(key, record)
            self._log(f"Decoded program: slot={record.display_slot} name={record.name} cmd=0x{cmd:02X}")
            if slot is not None and (cmd == CMD_RX_PROGRAM or (cmd == CMD_RX_CURRENT and self.expected_mode in {"slot_via_pc", "bank"})):
                self.program_response_queue.put(slot)
            if cmd in (CMD_RX_CURRENT, CMD_RX_PROGRAM):
                self.last_program_response = (cmd, -1 if slot is None else slot)
                self.probe_found_event.set()
            return
        self._log("Received non-program SysEx. Raw preserved in capture.")

    def _update_tree_record(self, key: int, record: ProgramRecord) -> None:
        iid = str(key)
        values = (record.display_slot, record.name, f"0x{record.command:02X}", record.source, len(record.raw))
        if self.tree.exists(iid):
            self.tree.item(iid, values=values)
        else:
            self.tree.insert("", tk.END, iid=iid, values=values)

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

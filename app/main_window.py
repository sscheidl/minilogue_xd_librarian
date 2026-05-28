"""Tkinter main window for the minilogue xd librarian."""

from __future__ import annotations

import json
import logging
import os
import platform
import sys
import time
import tkinter as tk
import zipfile
from pathlib import Path
from queue import Empty, Queue
from tkinter import filedialog, messagebox, simpledialog, scrolledtext, ttk

from app.app_paths import (
    dumps_dir,
    load_settings,
    log_path,
    save_settings,
    settings_path,
    user_data_dir,
    user_units_dir,
)
from devices.korg_minilogue_xd.slot_mapping import map_slot
from librarian.bank_workspace import OfflineBank
from librarian.models import SysexRecord
from librarian.sysex_tools import (
    build_records,
    read_sysex_file,
    records_to_bytes,
    report_dict,
    report_text,
    split_sysex_stream,
    write_report_files,
)
from librarian.import_validation import COMPATIBLE, PROBABLY_COMPATIBLE, validate_import_path
from librarian.user_units import import_user_unit, scan_user_units
from midi.diagnostics import MidiMessageInfo, analyze_raw_message
from midi.filters import (
    MidiFilterSettings,
    is_realtime_message,
    should_log_message,
)
from midi.ports import get_input_ports, get_output_ports
from midi.receiver import MidiReceiver, QueuedMidiError, QueuedMidiMessage
from midi.sysex_requests import request_current_program, request_program_slot
from midi.sysex_buffer import SysexBuffer
from utils.hexview import format_hex
from utils.logger import append_to_file, log_line
from xd_formats.filename_utils import safe_filename
from xd_formats import (
    XDLibrary,
    encode_program_dump,
    import_sysex_programs,
    load_mnlgxdlib,
    load_mnlgxdprog,
    save_mnlgxdlib,
    save_mnlgxdprog,
    write_sysex_programs,
)

_APP_VERSION = "0.4.0"
_BANK_COLUMNS = ("slot", "name", "source", "status", "hash", "notes")
_BANK_COLUMN_TITLES = {
    "slot": "Slot",
    "name": "Program Name",
    "source": "Source",
    "status": "Status",
    "hash": "Hash",
    "notes": "Notes",
}
_BANK_COLUMN_WIDTHS = {
    "slot": 80,
    "name": 190,
    "source": 240,
    "status": 180,
    "hash": 110,
    "notes": 360,
}


class MainWindow:
    """Tabbed librarian GUI with safe raw SysEx workflows."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.app_title = "minilogue xd Librarian"

        self.message_queue: Queue[QueuedMidiMessage | QueuedMidiError] = Queue()
        self.receiver = MidiReceiver(self.message_queue)
        self.sysex_buffer = SysexBuffer()
        self.settings = load_settings()

        empty_info = MidiMessageInfo("none", 0, False, False, False, None, False)
        self.last_midi_info = empty_info
        self.last_sysex_info = empty_info
        self.total_messages = 0
        self.total_sysex_messages = 0
        self.total_sysex_bytes = 0
        self.realtime_messages = 0
        self.clock_messages = 0
        self.last_sysex_received_at: float | None = None

        self.input_port_map: dict[str, str] = {}
        self.output_port_map: dict[str, str] = {}
        self.input_combos: list[ttk.Combobox] = []
        self.output_combos: list[ttk.Combobox] = []
        self.loaded_records: list[SysexRecord] = []
        self.loaded_source_path = ""
        self.preset_records: list[SysexRecord] = []
        self.bank = OfflineBank()
        self.current_sender = None
        self.bank_drag_start_index: int | None = None
        self.listen_active = False
        self.listen_started_at: float | None = None
        self.listen_saw_midi = False
        self.listen_saw_clock = False
        self.listen_saw_sysex = False
        self.receive_mode = "raw"
        self.dirty = False
        self.change_log: list[str] = []
        self.last_error = ""
        self.logger = logging.getLogger(__name__)
        self.bank_sort_column: str | None = None
        self.bank_sort_reverse = False

        self.input_port_var = tk.StringVar()
        self.output_port_var = tk.StringVar()
        self.receive_mode_var = tk.StringVar(value="Raw SysEx Capture")
        self.show_sysex_only_var = tk.BooleanVar(value=self.settings.get("show_sysex_only", True))
        self.hide_midi_clock_var = tk.BooleanVar(value=self.settings.get("hide_midi_clock", True))
        self.show_realtime_var = tk.BooleanVar(value=self.settings.get("show_realtime", False))
        self.show_note_controller_var = tk.BooleanVar(
            value=self.settings.get("show_note_controller", False)
        )
        self.auto_detect_korg_var = tk.BooleanVar(value=True)
        self.inactivity_ms_var = tk.StringVar(value=str(self.settings.get("inactivity_ms", 500)))
        self.max_timeout_s_var = tk.StringVar(value=str(self.settings.get("max_timeout_s", 10)))
        self.send_delay_var = tk.StringVar(value=str(self.settings.get("send_delay_ms", 80)))
        self.status_var = tk.StringVar()
        self.sysex_summary_var = tk.StringVar()
        self.port_hint_var = tk.StringVar()
        self.listen_status_var = tk.StringVar(value="Port test: idle")
        self.settings_status_var = tk.StringVar()
        self.bottom_status_var = tk.StringVar()
        self.analyzer_status_var = tk.StringVar(value="No SysEx file loaded.")
        self.bank_count_var = tk.StringVar(value="500 / 500 shown")

        self._build_layout()
        self.refresh_ports()
        self.refresh_bank_tree()
        self.refresh_user_units_trees()
        self.update_status()

        self.root.after(50, self.process_queue)
        self.root.after(100, self.check_capture_timeouts)

    def _build_layout(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        self._build_menu()
        self._configure_notebook_style()
        self.tabs = ttk.Notebook(self.root)
        self.tabs.grid(row=0, column=0, sticky="nsew")

        self.banks_tab = ttk.Frame(self.tabs, padding=10)
        self.midi_tab = ttk.Frame(self.tabs, padding=10)
        self.user_osc_tab = ttk.Frame(self.tabs, padding=10)
        self.user_fx_tab = ttk.Frame(self.tabs, padding=10)
        self.settings_tab = ttk.Frame(self.tabs, padding=10)

        self.tabs.add(self.banks_tab, text="Programs / Banks")
        self.tabs.add(self.midi_tab, text="Transfer / SysEx")
        self.tabs.add(self.user_osc_tab, text="User OSC")
        self.tabs.add(self.user_fx_tab, text="User FX")
        self.tabs.add(self.settings_tab, text="Options")

        self._build_banks_tab()
        self._build_midi_tab()
        self._build_user_unit_placeholder_tab(self.user_osc_tab, "User OSC")
        self._build_user_unit_placeholder_tab(self.user_fx_tab, "User FX")
        self._build_settings_tab()
        ttk.Label(
            self.root,
            textvariable=self.bottom_status_var,
            anchor="w",
            relief=tk.SUNKEN,
            padding=(6, 3),
        ).grid(row=1, column=0, sticky="ew")

    def _build_menu(self) -> None:
        menu_bar = tk.Menu(self.root)
        file_menu = tk.Menu(menu_bar, tearoff=False)
        file_menu.add_command(label="Open Bank...", command=self.open_bank)
        file_menu.add_command(label="Open Preset...", command=self.open_preset_into_bank)
        file_menu.add_command(label="Save Bank / Export As...", command=self.save_bank_copy)
        file_menu.add_separator()
        file_menu.add_command(label="Create Full Backup...", command=self.save_capture_backup)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_close)
        menu_bar.add_cascade(label="File", menu=file_menu)
        self.root.configure(menu=menu_bar)

    @staticmethod
    def _configure_notebook_style() -> None:
        style = ttk.Style()
        style.configure("TNotebook.Tab", padding=(12, 6), background="#d6d8db")
        style.map(
            "TNotebook.Tab",
            background=[("selected", "#f7f7f7"), ("!selected", "#d6d8db")],
            foreground=[("selected", "#111111"), ("!selected", "#404040")],
        )

    def _build_midi_tab(self) -> None:
        self.midi_tab.columnconfigure(0, weight=1)
        self.midi_tab.rowconfigure(4, weight=1)

        ports = ttk.Frame(self.midi_tab)
        ports.grid(row=0, column=0, sticky="ew")
        ports.columnconfigure(1, weight=1)
        ports.columnconfigure(3, weight=1)

        ttk.Label(ports, text="MIDI IN").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.input_combo = ttk.Combobox(ports, textvariable=self.input_port_var, state="readonly")
        self.input_combo.grid(row=0, column=1, sticky="ew", padx=(0, 12))
        self.input_combos.append(self.input_combo)
        ttk.Label(ports, text="MIDI OUT").grid(row=0, column=2, sticky="w", padx=(0, 6))
        self.output_combo = ttk.Combobox(ports, textvariable=self.output_port_var, state="readonly")
        self.output_combo.grid(row=0, column=3, sticky="ew")
        self.output_combos.append(self.output_combo)
        ttk.Label(ports, textvariable=self.port_hint_var, foreground="#5f6368").grid(
            row=1, column=0, columnspan=4, sticky="ew", pady=(6, 0)
        )

        buttons = ttk.Frame(self.midi_tab)
        buttons.grid(row=1, column=0, sticky="ew", pady=(8, 8))
        button_specs = [
            ("Refresh Ports", self.refresh_ports),
            ("Open Ports", self.open_ports),
            ("Request Current", self.request_current_from_xd),
            ("Request Slot", self.request_selected_slot_from_xd),
            ("Request Full Bank", self.request_full_bank_from_xd),
            ("Raw Capture", lambda: self.start_receive_mode("raw")),
            ("Close Ports", self.close_ports),
            ("Clear Log", self.clear_log),
            ("Save Capture", self.save_sysex_dump),
            ("Load .syx", self.load_sysex_file),
            ("Analyze", self.export_analyzer_report),
            ("Send Loaded", self.send_loaded_records),
            ("Send Capture", self.send_capture),
            ("Cancel Send", self.cancel_send),
        ]
        for index, (text, command) in enumerate(button_specs):
            ttk.Button(buttons, text=text, command=command).grid(row=0, column=index, padx=(0, 5))

        options = ttk.LabelFrame(self.midi_tab, text="Transfer / Capture")
        options.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(options, text="Inactivity finalize (ms)").grid(row=0, column=0, padx=(8, 0))
        ttk.Entry(options, textvariable=self.inactivity_ms_var, width=7).grid(
            row=0, column=1, padx=(5, 10)
        )
        ttk.Label(options, text="Max dump timeout (s)").grid(row=0, column=2)
        ttk.Entry(options, textvariable=self.max_timeout_s_var, width=6).grid(
            row=0, column=3, padx=(5, 10)
        )
        ttk.Label(options, text="Send delay (ms)").grid(row=0, column=4)
        ttk.Entry(options, textvariable=self.send_delay_var, width=6).grid(
            row=0, column=5, padx=(5, 8)
        )

        status = ttk.Frame(self.midi_tab)
        status.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        status.columnconfigure(0, weight=1)
        ttk.Label(status, textvariable=self.status_var).grid(row=0, column=0, sticky="ew")
        ttk.Label(status, textvariable=self.listen_status_var, foreground="#1a73e8").grid(
            row=1, column=0, sticky="ew"
        )
        self.rx_indicator = tk.Label(
            status,
            text="RX",
            width=8,
            relief=tk.SUNKEN,
            bg="#9e9e9e",
            fg="white",
        )
        self.rx_indicator.grid(row=0, column=1, rowspan=2, padx=(10, 0))

        pane = ttk.PanedWindow(self.midi_tab, orient=tk.HORIZONTAL)
        pane.grid(row=4, column=0, sticky="nsew")
        self.log_text = scrolledtext.ScrolledText(pane, wrap=tk.NONE, font=("Consolas", 10))
        pane.add(self.log_text, weight=4)
        summary_frame = ttk.Frame(pane)
        summary_frame.columnconfigure(0, weight=1)
        pane.add(summary_frame, weight=1)
        ttk.Label(
            summary_frame,
            textvariable=self.sysex_summary_var,
            justify=tk.LEFT,
            anchor="w",
        ).grid(row=0, column=0, sticky="new")
        ttk.Label(
            summary_frame,
            textvariable=self.analyzer_status_var,
            justify=tk.LEFT,
            anchor="w",
        ).grid(row=1, column=0, sticky="new", pady=(12, 0))
        ttk.Label(
            summary_frame,
            textvariable=self.settings_status_var,
            wraplength=320,
            foreground="#5f6368",
        ).grid(row=2, column=0, sticky="sew", pady=(12, 0))

    def _build_presets_tab(self) -> None:
        """Build the optional preset workspace tab.

        This tab is currently not wired into the main notebook. Keep the method
        harmless if it is called before ``self.presets_tab`` exists.
        """
        if not hasattr(self, "presets_tab"):
            return
        self.presets_tab.columnconfigure(0, weight=1)
        self.presets_tab.rowconfigure(1, weight=1)

        controls = ttk.Frame(self.presets_tab)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        for index, (text, command) in enumerate(
            [
                ("Open Single/Raw", self.load_presets),
                ("Export Selected", self.export_selected_preset),
                ("Duplicate", self.duplicate_selected_preset),
                ("Rename Display", self.rename_selected_preset),
                ("Delete from Workspace", self.delete_selected_preset),
                ("Send Selected", self.send_selected_preset),
            ]
        ):
            ttk.Button(controls, text=text, command=command).grid(row=0, column=index, padx=(0, 6))
        ttk.Label(controls, text="Search").grid(row=0, column=7)
        self.preset_search_var = tk.StringVar()
        ttk.Entry(controls, textvariable=self.preset_search_var, width=22).grid(
            row=0, column=8, padx=(5, 6)
        )
        ttk.Button(controls, text="Filter", command=self.refresh_preset_tree).grid(
            row=0, column=9
        )

        self.preset_tree = ttk.Treeview(
            self.presets_tab,
            columns=("index", "name", "type", "length", "hash", "source"),
            show="headings",
            selectmode="extended",
        )
        self._setup_tree(
            self.preset_tree,
            [
                ("index", "#", 60),
                ("name", "Name", 180),
                ("type", "Type", 180),
                ("length", "Bytes", 80),
                ("hash", "Hash", 110),
                ("source", "Source", 260),
            ],
        )
        self.preset_tree.grid(row=1, column=0, sticky="nsew")

    def _build_banks_tab(self) -> None:
        self.banks_tab.columnconfigure(0, weight=1)
        self.banks_tab.rowconfigure(1, weight=1)

        controls = ttk.Frame(self.banks_tab)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        group_specs = [
            ("File", [("Open Bank", self.open_bank), ("Open Preset", self.open_preset_into_bank), ("Save Bank", self.save_bank_copy), ("Save Bank As", self.save_bank_copy)]),
            ("Receive", [("Request Current", self.request_current_from_xd), ("Request Slot", self.request_selected_slot_from_xd), ("Request Full Bank", self.request_full_bank_from_xd)]),
            ("Send", [("Send Selected", self.send_selected_bank_slots), ("Send to Buffer", self.send_selected_to_buffer), ("Write Bank to XD", self.write_bank_to_xd)]),
            ("Edit", [("Cut", self.cut_bank_slot), ("Copy", self.copy_bank_slot), ("Paste", self.paste_bank_slot), ("Move To", self.move_bank_slot), ("Rename", self.rename_bank_slot), ("Duplicate", self.duplicate_bank_slot), ("Delete", self.clear_bank_slot), ("Clear / Init", self.clear_bank_slot), ("Undo", self.undo_bank), ("Change Log", self.show_change_log)]),
        ]
        for column, (title, buttons) in enumerate(group_specs):
            group = ttk.LabelFrame(controls, text=title)
            group.grid(row=0, column=column, sticky="nw", padx=(0, 8), pady=(0, 4))
            for index, (text, command) in enumerate(buttons):
                ttk.Button(group, text=text, command=command).grid(row=index // 4, column=index % 4, padx=3, pady=3)

        self.bank_search_var = tk.StringVar()
        self.bank_search_var.trace_add("write", lambda *_: self.refresh_bank_tree())
        search_group = ttk.LabelFrame(controls, text="Search")
        search_group.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(4, 0))
        search_group.columnconfigure(1, weight=1)
        ttk.Label(search_group, text="Search").grid(row=0, column=0, sticky="w", padx=(8, 5), pady=5)
        ttk.Entry(search_group, textvariable=self.bank_search_var, width=34).grid(row=0, column=1, sticky="ew", pady=5)
        ttk.Button(search_group, text="Clear", command=self.clear_bank_search).grid(row=0, column=2, sticky="w", padx=5, pady=5)
        ttk.Label(search_group, textvariable=self.bank_count_var, foreground="#5f6368").grid(row=0, column=3, sticky="e", padx=8, pady=5)
        ttk.Label(
            controls,
            text="No bank loaded. Open a bank, load presets, or receive data from the minilogue xd.",
            foreground="#5f6368",
        ).grid(row=2, column=0, columnspan=4, sticky="ew", pady=(5, 0))

        self.bank_tree = ttk.Treeview(
            self.banks_tab,
            columns=_BANK_COLUMNS,
            show="headings",
            selectmode="extended",
        )
        self._setup_bank_tree()
        self.bank_tree.grid(row=1, column=0, sticky="nsew")
        self.bank_tree.bind("<ButtonPress-1>", self.on_bank_drag_start)
        self.bank_tree.bind("<ButtonRelease-1>", self.on_bank_drag_release)
        self.bank_tree.bind("<Double-1>", self.on_bank_double_click)
        self.bank_tree.bind("<Button-3>", self.show_bank_context_menu)
        self.bank_context_menu = self._build_bank_context_menu()

    def _build_user_unit_placeholder_tab(self, parent: ttk.Frame, label: str) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        controls = ttk.Frame(parent)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        button_specs = [
            ("Read from XD", self.user_unit_send_not_implemented, tk.DISABLED),
            ("Load Unit", self.import_user_units, tk.NORMAL),
            ("Save Unit", self.user_unit_send_not_implemented, tk.DISABLED),
            ("Rename", self.user_unit_send_not_implemented, tk.DISABLED),
            ("Move To", self.user_unit_send_not_implemented, tk.DISABLED),
            ("Delete / Clear", self.remove_selected_user_units, tk.NORMAL),
            ("Send to XD", self.user_unit_send_not_implemented, tk.DISABLED),
            ("Refresh", self.refresh_user_units_trees, tk.NORMAL),
        ]
        for index, (text, command, state) in enumerate(button_specs):
            ttk.Button(controls, text=text, command=command, state=state).grid(row=0, column=index, padx=(0, 6))
        ttk.Label(
            controls,
            text=f"{label} slots are local inventory only until hardware transfer is verified.",
            foreground="#5f6368",
        ).grid(row=1, column=0, columnspan=8, sticky="w", pady=(6, 0))

        tree = ttk.Treeview(
            parent,
            columns=("slot", "name", "type", "compatibility", "status", "source", "notes"),
            show="headings",
            selectmode="extended",
        )
        self._setup_tree(
            tree,
            [
                ("slot", "Slot", 70),
                ("name", "Name", 170),
                ("type", "Type", 110),
                ("compatibility", "Compatibility", 170),
                ("status", "Status", 150),
                ("source", "Source", 260),
                ("notes", "Notes", 260),
            ],
        )
        tree.grid(row=1, column=0, sticky="nsew")
        if label == "User OSC":
            self.user_osc_tree = tree
        else:
            self.user_fx_tree = tree

    def _build_settings_tab(self) -> None:
        self.settings_tab.columnconfigure(0, weight=1)

        midi_frame = ttk.LabelFrame(self.settings_tab, text="MIDI Settings")
        midi_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        midi_frame.columnconfigure(1, weight=1)
        midi_frame.columnconfigure(3, weight=1)

        ttk.Label(midi_frame, text="MIDI IN").grid(row=0, column=0, sticky="w", padx=(8, 6), pady=(8, 4))
        self.options_input_combo = ttk.Combobox(midi_frame, textvariable=self.input_port_var, state="readonly")
        self.options_input_combo.grid(row=0, column=1, sticky="ew", pady=(8, 4), padx=(0, 10))
        self.input_combos.append(self.options_input_combo)
        ttk.Label(midi_frame, text="MIDI OUT").grid(row=0, column=2, sticky="w", padx=(0, 6), pady=(8, 4))
        self.options_output_combo = ttk.Combobox(midi_frame, textvariable=self.output_port_var, state="readonly")
        self.options_output_combo.grid(row=0, column=3, sticky="ew", pady=(8, 4), padx=(0, 8))
        self.output_combos.append(self.options_output_combo)

        for index, (text, command) in enumerate(
            [
                ("Refresh Ports", self.refresh_ports),
                ("Open Ports", self.open_ports),
                ("Close Ports", self.close_ports),
                ("Save Port Combination", self.save_current_port_combination),
                ("Open Log Folder", self.open_log_folder),
                ("Copy Diagnostic Report", self.copy_diagnostic_report),
                ("About", self.show_about),
                ("Clear communication status", self.clear_communication_status),
            ]
        ):
            ttk.Button(midi_frame, text=text, command=command).grid(
                row=1, column=index, sticky="w", padx=(8 if index == 0 else 0, 5), pady=(4, 8)
            )

        ttk.Label(midi_frame, textvariable=self.port_hint_var, foreground="#5f6368").grid(
            row=2, column=0, columnspan=6, sticky="ew", padx=8, pady=(0, 6)
        )
        ttk.Label(midi_frame, textvariable=self.listen_status_var, foreground="#1a73e8").grid(
            row=3, column=0, columnspan=6, sticky="ew", padx=8, pady=(0, 8)
        )

        filters = ttk.LabelFrame(self.settings_tab, text="MIDI Filters")
        filters.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        ttk.Checkbutton(filters, text="Show SysEx only", variable=self.show_sysex_only_var).grid(row=0, column=0, sticky="w", padx=8, pady=6)
        ttk.Checkbutton(filters, text="Hide MIDI Clock", variable=self.hide_midi_clock_var).grid(row=0, column=1, sticky="w", padx=8, pady=6)
        ttk.Checkbutton(filters, text="Show MIDI realtime messages", variable=self.show_realtime_var).grid(row=0, column=2, sticky="w", padx=8, pady=6)
        ttk.Checkbutton(filters, text="Show note/controller messages", variable=self.show_note_controller_var).grid(row=0, column=3, sticky="w", padx=8, pady=6)

        transfer = ttk.LabelFrame(self.settings_tab, text="Transfer Settings")
        transfer.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(transfer, text="Inactivity finalize (ms)").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        ttk.Entry(transfer, textvariable=self.inactivity_ms_var, width=8).grid(row=0, column=1, sticky="w", padx=(0, 12), pady=6)
        ttk.Label(transfer, text="Max dump timeout (s)").grid(row=0, column=2, sticky="w", padx=8, pady=6)
        ttk.Entry(transfer, textvariable=self.max_timeout_s_var, width=8).grid(row=0, column=3, sticky="w", padx=(0, 12), pady=6)
        ttk.Label(transfer, text="Send delay (ms)").grid(row=0, column=4, sticky="w", padx=8, pady=6)
        ttk.Entry(transfer, textvariable=self.send_delay_var, width=8).grid(row=0, column=5, sticky="w", padx=(0, 12), pady=6)

        saved = ttk.LabelFrame(self.settings_tab, text="Saved Port Defaults")
        saved.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        saved.columnconfigure(1, weight=1)

        ttk.Label(saved, text="Default MIDI IN").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        self.default_in_var = tk.StringVar(value=self.settings.get("last_successful_midi_in", ""))
        ttk.Entry(saved, textvariable=self.default_in_var).grid(
            row=0, column=1, sticky="ew", padx=(8, 8), pady=4
        )
        ttk.Label(saved, text="Default MIDI OUT").grid(row=1, column=0, sticky="w", padx=8, pady=4)
        self.default_out_var = tk.StringVar(value=self.settings.get("last_successful_midi_out", ""))
        ttk.Entry(saved, textvariable=self.default_out_var).grid(
            row=1, column=1, sticky="ew", padx=(8, 8), pady=4
        )
        ttk.Button(saved, text="Save Settings", command=self.save_settings_from_tab).grid(
            row=2, column=0, sticky="w", padx=8, pady=(8, 8)
        )

        paths = ttk.LabelFrame(self.settings_tab, text="Paths")
        paths.grid(row=4, column=0, sticky="ew")
        paths.columnconfigure(1, weight=1)
        path_rows = [
            ("Dump folder", str(dumps_dir())),
            ("Backup folder", str(user_data_dir() / "backups")),
            ("Settings file", str(settings_path())),
            ("Log file", str(log_path())),
            ("User data folder", str(user_data_dir())),
        ]
        for row, (label, value) in enumerate(path_rows):
            ttk.Label(paths, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=3)
            ttk.Label(paths, text=value).grid(row=row, column=1, sticky="w", padx=(8, 8), pady=3)
        ttk.Label(
            paths,
            text="Batch cancel enabled. First-send warning is always shown before raw SysEx transfer.",
            foreground="#5f6368",
        ).grid(row=len(path_rows), column=0, columnspan=2, sticky="w", padx=8, pady=(8, 6))

    @staticmethod
    def _setup_tree(tree: ttk.Treeview, columns: list[tuple[str, str, int]]) -> None:
        for column, text, width in columns:
            tree.heading(column, text=text)
            tree.column(column, width=width, anchor=tk.W)

    def _setup_bank_tree(self) -> None:
        for column in _BANK_COLUMNS:
            self.bank_tree.column(column, width=_BANK_COLUMN_WIDTHS[column], anchor=tk.W)
        self.update_bank_headings()

    def update_bank_headings(self) -> None:
        for column in _BANK_COLUMNS:
            title = _BANK_COLUMN_TITLES[column]
            if self.bank_sort_column == column:
                title += " " + ("v" if self.bank_sort_reverse else "^")
            self.bank_tree.heading(column, text=title, command=lambda col=column: self.set_bank_sort(col))

    def set_bank_sort(self, column: str) -> None:
        if self.bank_sort_column == column:
            self.bank_sort_reverse = not self.bank_sort_reverse
        else:
            self.bank_sort_column = column
            self.bank_sort_reverse = False
        self.update_bank_headings()
        self.refresh_bank_tree()

    def _build_bank_context_menu(self) -> tk.Menu:
        menu = tk.Menu(self.root, tearoff=False)
        self.bank_context_rules: list[str] = []
        entries = [
            ("Cut", self.cut_bank_slot, "selection"),
            ("Copy", self.copy_bank_slot, "selection"),
            ("Paste", self.paste_bank_slot, "clipboard"),
            ("Move To...", self.move_bank_slot, "single"),
            ("Rename", self.rename_bank_slot, "single"),
            ("Duplicate", self.duplicate_bank_slot, "single"),
            ("Delete", self.clear_bank_slot, "selection"),
            ("Clear / Init", self.clear_bank_slot, "selection"),
            ("Create Init Program", self.create_init_program_slot, "disabled"),
            ("Save as minilogue xd Program...", self.save_selected_as_mnlgxdprog, "data"),
            ("Save as SysEx...", self.save_selected_as_sysex, "data"),
            ("Send selected to XD buffer", self.send_selected_to_buffer, "data"),
            ("Send selected to XD slot", self.send_selected_bank_slots, "data"),
            ("Request this slot from XD", self.request_selected_slot_from_xd, "single"),
        ]
        for label, command, rule in entries:
            menu.add_command(label=label, command=command)
            menu.entryconfig(label, state=tk.DISABLED if rule == "disabled" else tk.NORMAL)
            self.bank_context_rules.append(rule)
        return menu

    def show_bank_context_menu(self, event: tk.Event) -> None:
        item = self.bank_tree.identify_row(event.y)
        if item and item.isdigit() and item not in self.bank_tree.selection():
            self.bank_tree.selection_set(item)
        self.update_bank_context_menu()
        self.bank_context_menu.tk_popup(event.x_root, event.y_root)

    def update_bank_context_menu(self) -> None:
        selection = self.selected_bank_indices()
        has_selection = bool(selection)
        has_single = len(selection) == 1
        has_data = any(self.bank.slots[index].raw or self.bank.slots[index].prog_bin for index in selection)
        has_clipboard = self.bank.clipboard is not None
        for index, rule in enumerate(self.bank_context_rules):
            enabled = (
                (rule == "selection" and has_selection)
                or (rule == "single" and has_single)
                or (rule == "data" and has_data)
                or (rule == "clipboard" and has_clipboard and has_single)
            )
            if rule == "disabled":
                enabled = False
            self.bank_context_menu.entryconfig(index, state=tk.NORMAL if enabled else tk.DISABLED)

    def refresh_ports(self) -> None:
        try:
            input_ports = get_input_ports()
            output_ports = get_output_ports()
        except Exception as exc:
            self.append_log(log_line(f"Port refresh failed: {exc}"))
            input_ports = []
            output_ports = []

        input_labels, self.input_port_map = self.build_port_labels(input_ports)
        output_labels, self.output_port_map = self.build_port_labels(output_ports)
        for combo in self.input_combos:
            combo["values"] = input_labels
        for combo in self.output_combos:
            combo["values"] = output_labels
        self.select_port_label(self.input_port_var, self.input_port_map, self.settings.get("last_successful_midi_in"), input_labels)
        self.select_port_label(self.output_port_var, self.output_port_map, self.settings.get("last_successful_midi_out"), output_labels)

        self.update_port_hint(input_ports, output_ports)
        self.append_log(log_line(f"Ports refreshed: {len(input_ports)} input, {len(output_ports)} output"))
        self.update_status()

    @staticmethod
    def build_port_labels(ports: list[str]) -> tuple[list[str], dict[str, str]]:
        labels = []
        mapping = {}
        for index, port in enumerate(ports, start=1):
            suffix = "  [possible SysEx/Librarian port]" if MainWindow.is_sysex_candidate(port) else ""
            label = f"{index}. {port}{suffix}"
            labels.append(label)
            mapping[label] = port
        return labels, mapping

    @staticmethod
    def is_sysex_candidate(port: str) -> bool:
        lowered = port.lower()
        return "minilogue xd" in lowered and (
            "midiin2" in lowered or "midiout2" in lowered or lowered.endswith(" 2") or lowered.endswith(") 2")
        )

    @staticmethod
    def select_port_label(
        variable: tk.StringVar,
        mapping: dict[str, str],
        preferred: str | None,
        labels: list[str],
    ) -> None:
        """Select the best visible combobox label while preserving valid choices."""
        if preferred:
            for label, port in mapping.items():
                if port == preferred:
                    variable.set(label)
                    return
        if variable.get() in mapping:
            return
        current_port = mapping.get(variable.get(), variable.get())
        if current_port:
            for label, port in mapping.items():
                if port == current_port:
                    variable.set(label)
                    return
        variable.set(labels[0] if labels else "")

    def selected_input_port(self) -> str | None:
        selected = self.input_port_var.get().strip()
        return self.input_port_map.get(selected, selected) or None

    def selected_output_port(self) -> str | None:
        selected = self.output_port_var.get().strip()
        return self.output_port_map.get(selected, selected) or None

    def update_port_hint(self, input_ports: list[str], output_ports: list[str]) -> None:
        candidates = [port for port in input_ports + output_ports if self.is_sysex_candidate(port)]
        if candidates:
            self.port_hint_var.set("SysEx hint: Port-2 candidates are marked, but selection is never forced.")
        else:
            self.port_hint_var.set("SysEx hint: all ports are shown; no Port-2 candidate detected.")

    def open_ports(self) -> None:
        input_name = self.selected_input_port()
        output_name = self.selected_output_port()
        if input_name is None and output_name is None:
            messagebox.showwarning("No ports selected", "Select at least one MIDI port.")
            return
        self.receiver.open_ports(input_name, output_name)
        if self.receiver.is_open:
            self.settings["last_midi_in"] = input_name
            self.settings["last_midi_out"] = output_name
            self.persist_settings()
            self.append_log(log_line("Ports opened. Send actions require explicit confirmation."))
        self.update_status()

    def close_ports(self) -> None:
        self.receiver.close_ports()
        self.append_log(log_line("Ports closed."))
        self.update_status()

    def save_current_port_combination(self) -> None:
        self.settings["last_successful_midi_in"] = self.selected_input_port()
        self.settings["last_successful_midi_out"] = self.selected_output_port()
        self.default_in_var.set(self.settings.get("last_successful_midi_in") or "")
        self.default_out_var.set(self.settings.get("last_successful_midi_out") or "")
        self.persist_settings()
        self.append_log(log_line("Saved current MIDI port combination."))
        self.update_status()

    def clear_communication_status(self) -> None:
        self.listen_active = False
        self.listen_started_at = None
        self.listen_saw_midi = False
        self.listen_saw_clock = False
        self.listen_saw_sysex = False
        self.listen_status_var.set("Port test: idle")
        self.realtime_messages = 0
        self.clock_messages = 0
        self.update_status()

    def listen_for_sysex(self) -> None:
        if not self.selected_input_port():
            messagebox.showwarning("No MIDI IN selected", "Select a MIDI IN port first.")
            return
        if not self.receiver.is_open:
            self.open_ports()
        if not self.receiver.is_open:
            return
        self.listen_active = True
        self.listen_started_at = time.time()
        self.listen_saw_midi = False
        self.listen_saw_clock = False
        self.listen_saw_sysex = False
        self.listen_status_var.set("Port test: listening for SysEx on selected IN port...")
        self.append_log(log_line(f"Listening for SysEx on MIDI IN: {self.selected_input_port()}"))

    def process_queue(self) -> None:
        while True:
            try:
                item = self.message_queue.get_nowait()
            except Empty:
                break
            if isinstance(item, QueuedMidiError):
                self.append_log(log_line(item.message))
                self.flash_rx("error")
            else:
                self.handle_midi_message(item)
        self.root.after(50, self.process_queue)

    def handle_midi_message(self, item: QueuedMidiMessage) -> None:
        now = time.time()
        info = analyze_raw_message(item.raw, item.message_type)
        self.last_midi_info = info
        is_realtime = is_realtime_message(info.message_type)
        if is_realtime:
            self.realtime_messages += 1
            if info.message_type == "clock":
                self.clock_messages += 1
                if self.listen_active:
                    self.listen_saw_clock = True
        else:
            self.total_messages += 1
        if self.listen_active:
            self.listen_saw_midi = True

        if info.is_sysex:
            self.last_sysex_info = info
            self.last_sysex_received_at = now
            sysex_message = self.sysex_buffer.add_message(item.raw, now)
            self.total_sysex_messages += 1
            self.total_sysex_bytes += sysex_message.length
            self.flash_rx("sysex")
            self.append_sysex_log(now, item.raw, info)
            if self.listen_active:
                self.listen_saw_sysex = True
                self.listen_status_var.set(f"{self.receive_mode_var.get()}: SysEx received on selected IN port")
            if info.is_korg:
                self.save_successful_sysex_ports(now)
                if self.listen_active:
                    self.listen_status_var.set(f"{self.receive_mode_var.get()}: Korg SysEx detected")
        else:
            if self.listen_active and not self.listen_saw_sysex:
                if info.message_type == "clock":
                    self.listen_status_var.set("Port test: MIDI clock received, no SysEx yet")
                else:
                    self.listen_status_var.set("Port test: MIDI data received, but no SysEx")
            settings = self.current_filter_settings()
            if not is_realtime or should_log_message(info.message_type, info.is_sysex, settings):
                self.flash_rx("midi")
            if should_log_message(info.message_type, info.is_sysex, settings):
                self.append_log(log_line(f"MIDI {info.message_type}: {format_hex(item.raw)}"))
        self.update_status()

    def current_filter_settings(self) -> MidiFilterSettings:
        return MidiFilterSettings(
            show_sysex_only=self.show_sysex_only_var.get(),
            hide_midi_clock=self.hide_midi_clock_var.get(),
            show_realtime=self.show_realtime_var.get(),
            show_note_controller=self.show_note_controller_var.get(),
        )

    def append_sysex_log(self, timestamp: float, raw: bytes, info: MidiMessageInfo) -> None:
        manufacturer = f"0x{info.manufacturer_id:02X}" if info.manufacturer_id is not None else "none"
        self.append_log(
            f"[{time.strftime('%H:%M:%S', time.localtime(timestamp))}] SysEx "
            f"length={info.length} manufacturer={manufacturer} korg={info.is_korg}\n"
            f"{format_hex(raw)}\n"
        )

    def check_capture_timeouts(self) -> None:
        result = self.sysex_buffer.check_timeouts(
            time.time(),
            self.read_int(self.inactivity_ms_var.get(), 500),
            self.read_int(self.max_timeout_s_var.get(), 10),
        )
        if result:
            self.append_log(log_line(f"Capture finalized by {result}."))
        self.check_listen_timeout()
        self.update_status()
        self.root.after(100, self.check_capture_timeouts)

    def check_listen_timeout(self) -> None:
        if not self.listen_active or self.listen_started_at is None:
            return
        if self.listen_saw_sysex:
            return
        if time.time() - self.listen_started_at < 10:
            return
        self.listen_active = False
        if self.listen_saw_midi:
            if self.listen_saw_clock:
                self.listen_status_var.set("Port test: MIDI clock received, no SysEx yet")
            else:
                self.listen_status_var.set("Port test: MIDI data received, but no SysEx")
        else:
            self.listen_status_var.set("Port test: No MIDI data received on selected port")

    def load_sysex_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Open SysEx or raw Korg file",
            filetypes=[
                ("Korg / SysEx files", "*.syx *.mnlgxdprog *.mnlgxdlib"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        try:
            self.loaded_records = read_sysex_file(Path(path))
        except OSError as exc:
            messagebox.showerror("Open failed", str(exc))
            return
        self.loaded_source_path = path
        self.analyzer_status_var.set(report_text(path, self.loaded_records))
        self.append_log(log_line(f"Loaded {len(self.loaded_records)} SysEx message(s) from {path}"))

    def export_analyzer_report(self) -> None:
        if not self.loaded_records:
            messagebox.showinfo("No loaded data", "Load a .syx file first.")
            return
        path = filedialog.asksaveasfilename(
            title="Save analyzer report",
            defaultextension=".txt",
            filetypes=[("Text report", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        write_report_files(Path(path), self.loaded_source_path, self.loaded_records)
        self.append_log(log_line(f"Analyzer report written next to {path}"))

    def save_sysex_dump(self) -> None:
        data = self.sysex_buffer.to_bytes()
        if not data:
            messagebox.showinfo("No SysEx data", "No SysEx capture is available to save.")
            return
        path = filedialog.asksaveasfilename(
            title="Save SysEx Dump",
            initialdir=dumps_dir(),
            initialfile=time.strftime("minilogue_xd_capture_%Y%m%d_%H%M%S.syx"),
            defaultextension=".syx",
            filetypes=[("SysEx dump", "*.syx"), ("All files", "*.*")],
        )
        if not path:
            return
        if self.sysex_buffer.capture and self.sysex_buffer.capture.is_active:
            self.sysex_buffer.finalize("manual", time.time())
        Path(path).write_bytes(data)
        self.append_log(log_line(f"Saved SysEx dump: {path} ({len(data)} bytes)"))

    def send_loaded_records(self) -> None:
        self.send_records(self.loaded_records, "loaded SysEx file")

    def send_capture(self) -> None:
        records = build_records(self.sysex_buffer.to_bytes())
        self.send_records(records, "current capture")

    def send_records(self, records: list[SysexRecord], label: str) -> None:
        if not records:
            messagebox.showinfo("Nothing to send", f"No SysEx messages in {label}.")
            return
        invalid = [
            record.index
            for record in records
            if not (record.raw.startswith(b"\xF0") and record.raw.endswith(b"\xF7"))
        ]
        if invalid:
            messagebox.showwarning(
                "Cannot send raw file",
                "Only complete SysEx messages can be sent. "
                f"Invalid record(s): {', '.join(map(str, invalid[:10]))}",
            )
            return
        if not self.receiver.is_open or not self.selected_output_port():
            messagebox.showwarning("No MIDI OUT", "Open the selected MIDI OUT port first.")
            return
        total_bytes = sum(len(record.raw) for record in records)
        warning = ""
        if len(records) >= 500:
            warning = "\n\nWarning: This may overwrite the complete program bank on the device."
        elif len(records) > 1:
            warning = "\n\nWarning: This may overwrite multiple program slots on the device."
        preview_names = [record.notes for record in records if getattr(record, "notes", "")]
        preview = ", ".join(preview_names[:5]) if preview_names else label
        if len(preview_names) > 5:
            preview += ", ..."
        if not messagebox.askyesno(
            "Confirm SysEx send",
            "You are about to send "
            f"{len(records)} SysEx message(s) to the minilogue xd.\n\n"
            f"Target MIDI OUT:\n{self.selected_output_port()}\n\n"
            f"Source / program(s):\n{preview}\n\n"
            f"Message count: {len(records)}\n"
            f"Total bytes: {total_bytes}\n"
            f"{warning}\n\n"
            "This may overwrite data on the device. Continue?",
        ):
            return
        sender = self.receiver.make_sender()
        self.current_sender = sender
        delay_ms = self.read_int(self.send_delay_var.get(), 80)
        sent = 0
        try:
            sent = sender.send_messages(
                [record.raw for record in records],
                delay_ms,
                lambda index, total, length: self.append_log(
                    log_line(f"Sent SysEx {index}/{total} ({length} bytes)")
                ),
            )
        except Exception as exc:
            self.last_error = str(exc)
            self.logger.exception("Send failed.")
            self.append_log(log_line(f"Send failed: {exc}"))
            messagebox.showerror("Send failed", str(exc))
            self.flash_rx("error")
        else:
            self.append_log(log_line(f"Send complete: {sent}/{len(records)} message(s)."))
        finally:
            self.current_sender = None

    def cancel_send(self) -> None:
        if self.current_sender is not None:
            self.current_sender.cancel()
            self.append_log(log_line("Cancel requested for current send."))

    def load_presets(self) -> None:
        path = filedialog.askopenfilename(
            title="Open single preset or SysEx file",
            filetypes=[("Korg / SysEx files", "*.syx *.mnlgxdprog"), ("All files", "*.*")],
        )
        if not path:
            return
        source_path = Path(path)
        validation = validate_import_path(source_path)
        if validation.status not in {COMPATIBLE, PROBABLY_COMPATIBLE}:
            messagebox.showwarning("Import blocked", f"{validation.status}: {validation.message}")
            return
        if source_path.suffix.lower() == ".mnlgxdprog":
            try:
                program = load_mnlgxdprog(source_path)
                records = [self.program_to_record(program, 1)]
            except (OSError, ValueError, zipfile.BadZipFile) as exc:
                messagebox.showerror("Open failed", str(exc))
                return
        elif source_path.suffix.lower() == ".syx":
            programs = import_sysex_programs(source_path)
            records = [self.program_to_record(program, index + 1) for index, program in enumerate(programs)]
            if not records:
                records = read_sysex_file(source_path)
        else:
            records = read_sysex_file(source_path)
        self.preset_records.extend(records)
        self.loaded_source_path = path
        if hasattr(self, "preset_tree"):
            self.refresh_preset_tree()

    def open_preset_into_bank(self) -> None:
        path = filedialog.askopenfilename(
            title="Open preset or SysEx file into bank workspace",
            filetypes=[("Korg / SysEx files", "*.syx *.mnlgxdprog"), ("All files", "*.*")],
        )
        if not path:
            return
        source_path = Path(path)
        validation = validate_import_path(source_path)
        if validation.status not in {COMPATIBLE, PROBABLY_COMPATIBLE}:
            messagebox.showwarning("Import blocked", f"{validation.status}: {validation.message}")
            return
        empty_indices = [i for i, slot in enumerate(self.bank.slots) if not slot.raw]
        try:
            if source_path.suffix.lower() == ".mnlgxdprog":
                programs = [load_mnlgxdprog(source_path)]
            elif source_path.suffix.lower() == ".syx":
                programs = import_sysex_programs(source_path)
            else:
                programs = []
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            messagebox.showerror("Open failed", str(exc))
            return
        if programs:
            self.bank.remember()
            for program, index in zip(programs, empty_indices):
                slot = self.bank.slots[index]
                raw = self.program_to_record(program, index + 1).raw
                slot.name = program.name
                slot.source = path
                slot.raw = raw
                slot.prog_bin = program.prog_bin
                slot.sha256 = self.bank.hash_raw(program.prog_bin)
                slot.status = program.source_type or source_path.suffix.lower().lstrip(".")
                slot.notes = "Decoded minilogue xd program data."
            self.bank.mark_duplicates()
            self.mark_dirty(f"Imported {len(programs)} decoded program(s) into bank workspace")
            self.refresh_bank_tree()
            return

        records = read_sysex_file(source_path)
        self.bank.remember()
        for record, index in zip(records, empty_indices):
            slot = self.bank.slots[index]
            slot.name = f"Program {index + 1:03d}"
            slot.source = path
            slot.raw = record.raw
            slot.prog_bin = b""
            slot.sha256 = record.sha256
            slot.status = record.dump_type
            slot.notes = "Loaded as preset into offline bank workspace."
        self.bank.mark_duplicates()
        self.mark_dirty(f"Imported {len(records)} raw record(s) into bank workspace")
        self.refresh_bank_tree()

    def refresh_preset_tree(self) -> None:
        query = self.preset_search_var.get().lower() if hasattr(self, "preset_search_var") else ""
        self.preset_tree.delete(*self.preset_tree.get_children())
        for index, record in enumerate(self.preset_records):
            name = f"Program {record.index:03d}"
            if query and query not in name.lower() and query not in record.dump_type.lower():
                continue
            self.preset_tree.insert(
                "",
                tk.END,
                iid=str(index),
                values=(record.index, name, record.dump_type, record.length, record.short_hash, self.loaded_source_path),
            )

    def selected_preset_records(self) -> list[SysexRecord]:
        indices = []
        for item in self.preset_tree.selection():
            try:
                indices.append(int(item))
            except ValueError:
                pass
        return [self.preset_records[index] for index in indices if 0 <= index < len(self.preset_records)]

    def export_selected_preset(self) -> None:
        records = self.selected_preset_records()
        if not records:
            return
        path = filedialog.asksaveasfilename(defaultextension=".syx", filetypes=[("SysEx", "*.syx")])
        if path:
            Path(path).write_bytes(records_to_bytes(records))

    def duplicate_selected_preset(self) -> None:
        records = self.selected_preset_records()
        for record in records:
            self.preset_records.append(
                SysexRecord(
                    index=len(self.preset_records) + 1,
                    raw=record.raw,
                    length=record.length,
                    manufacturer_id=record.manufacturer_id,
                    is_korg=record.is_korg,
                    dump_type=record.dump_type,
                    sha256=record.sha256,
                    notes="Duplicated in preset workspace.",
                )
            )
        self.refresh_preset_tree()

    def rename_selected_preset(self) -> None:
        messagebox.showinfo("Display rename", "Preset name decoding is not verified yet; rename is kept as a bank display override after loading into a bank.")

    def delete_selected_preset(self) -> None:
        indices = {
            int(item)
            for item in self.preset_tree.selection()
            if item.isdigit()
        }
        self.preset_records = [
            record for index, record in enumerate(self.preset_records) if index not in indices
        ]
        self.refresh_preset_tree()

    def send_selected_preset(self) -> None:
        self.send_records(self.selected_preset_records(), "selected preset")

    def open_bank(self) -> None:
        path = filedialog.askopenfilename(
            title="Open bank/library/raw file",
            filetypes=[("Korg / SysEx files", "*.syx *.mnlgxdlib"), ("All files", "*.*")],
        )
        if not path:
            return
        source_path = Path(path)
        validation = validate_import_path(source_path)
        if validation.status not in {COMPATIBLE, PROBABLY_COMPATIBLE}:
            messagebox.showwarning("Import blocked", f"{validation.status}: {validation.message}")
            return
        if source_path.suffix.lower() == ".mnlgxdlib":
            try:
                library = load_mnlgxdlib(source_path)
            except (OSError, ValueError, zipfile.BadZipFile) as exc:
                messagebox.showerror("Open failed", str(exc))
                return
            self.bank.load_programs(library.programs, path, "mnlgxdlib")
            self.clear_dirty_state()
            self.change_log.clear()
            self.refresh_bank_tree()
            self.append_log(log_line(f"Loaded {len(library.programs)} decoded program(s) from {path}"))
            return
        if source_path.suffix.lower() == ".syx":
            programs = import_sysex_programs(source_path)
            if programs:
                self.bank.load_programs(programs, path, "syx")
                self.clear_dirty_state()
                self.change_log.clear()
                self.refresh_bank_tree()
                self.append_log(log_line(f"Loaded {len(programs)} decoded SysEx program dump(s) from {path}"))
                return
        records = read_sysex_file(source_path)
        self.bank.load_records(records, path)
        self.clear_dirty_state()
        self.change_log.clear()
        self.refresh_bank_tree()

    def refresh_bank_tree(self) -> None:
        if not hasattr(self, "bank_tree"):
            return
        self.bank_tree.delete(*self.bank_tree.get_children())
        visible_indices = [
            index for index, slot in enumerate(self.bank.slots) if self.bank_slot_matches_filter(index, slot)
        ]
        if self.bank_sort_column:
            visible_indices.sort(
                key=lambda index: self.bank_sort_value(index, self.bank_sort_column or "slot"),
                reverse=self.bank_sort_reverse,
            )
        for index in visible_indices:
            slot = self.bank.slots[index]
            self.bank_tree.insert(
                "",
                tk.END,
                iid=str(index),
                values=(
                    map_slot(index).display_number_text,
                    slot.name or "Empty",
                    slot.source,
                    slot.status or "empty",
                    slot.short_hash,
                    slot.notes,
                ),
            )
        self.bank_count_var.set(f"{len(visible_indices)} / {len(self.bank.slots)} shown")

    def bank_slot_matches_filter(self, index: int, slot) -> bool:
        query = self.bank_search_var.get().strip().lower() if hasattr(self, "bank_search_var") else ""
        if not query:
            return True
        slot_mapping = map_slot(index)
        searchable = " ".join(
            [
                slot_mapping.display_number_text,
                slot.name or "",
                slot.source or "",
                slot.status or "",
                slot.short_hash or "",
                slot.notes or "",
            ]
        ).lower()
        return query in searchable

    def bank_sort_value(self, index: int, column: str):
        slot = self.bank.slots[index]
        values = {
            "slot": index + 1,
            "name": (slot.name or "").casefold(),
            "source": (slot.source or "").casefold(),
            "status": (slot.status or "").casefold(),
            "hash": (slot.short_hash or "").casefold(),
            "notes": (slot.notes or "").casefold(),
        }
        return values.get(column, index)

    def clear_bank_search(self) -> None:
        self.bank_search_var.set("")
        self.refresh_bank_tree()

    def selected_bank_indices(self) -> list[int]:
        return [int(item) for item in self.bank_tree.selection()]

    def save_bank_copy(self) -> None:
        if not any(slot.raw or slot.prog_bin for slot in self.bank.slots):
            messagebox.showinfo("Empty bank", "No raw bank data is loaded.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".mnlgxdlib",
            filetypes=[
                ("minilogue xd Library", "*.mnlgxdlib"),
                ("SysEx", "*.syx"),
            ],
        )
        if path:
            target = Path(path)
            programs = self.bank.export_programs()
            if target.suffix.lower() == ".mnlgxdlib":
                if len(programs) != 500:
                    messagebox.showwarning(
                        "Incomplete library",
                        f"A .mnlgxdlib export needs 500 decoded programs; found {len(programs)}.",
                    )
                    return
                save_mnlgxdlib(XDLibrary(programs=programs), target)
            elif programs:
                write_sysex_programs(programs, target)
            else:
                target.write_bytes(b"".join(slot.raw for slot in self.bank.slots if slot.raw))
            self.clear_dirty_state()
            self.append_log(log_line(f"Saved bank/export: {target}"))

    def export_selected_bank_slots(self) -> None:
        indices = self.selected_bank_indices()
        programs = self.bank.export_programs(indices)
        data = self.bank.export_selected_bytes(indices)
        if not data and not programs:
            return
        path = filedialog.asksaveasfilename(defaultextension=".syx", filetypes=[("SysEx", "*.syx")])
        if path:
            if programs:
                write_sysex_programs(programs, path)
            else:
                Path(path).write_bytes(data)
            self.append_log(log_line(f"Exported selected bank slot(s): {path}"))

    def send_selected_bank_slots(self) -> None:
        records = [
            SysexRecord(i + 1, self.bank.slots[i].raw, len(self.bank.slots[i].raw), None, False, "bank-slot", self.bank.slots[i].sha256)
            for i in self.selected_bank_indices()
            if self.bank.slots[i].raw
        ]
        self.send_records(records, "selected bank slots")

    def rename_bank_slot(self) -> None:
        indices = self.selected_bank_indices()
        if not indices:
            return
        name = simpledialog.askstring(
            "Rename program",
            "New program name:",
            initialvalue=self.bank.slots[indices[0]].name,
        )
        if name is not None:
            old_name = self.bank.slots[indices[0]].name
            self.bank.rename(indices[0], name)
            self.mark_dirty(f'Renamed {map_slot(indices[0]).bank_slot_text}: "{old_name}" -> "{name}"')
            self.refresh_bank_tree()

    def copy_bank_slot(self) -> None:
        indices = self.selected_bank_indices()
        if indices:
            self.bank.copy(indices[0])
            slot = self.bank.slots[indices[0]]
            self.append_log(log_line(f"Copied slot {indices[0] + 1:03d}: {slot.name or 'Empty'}"))

    def cut_bank_slot(self) -> None:
        indices = self.selected_bank_indices()
        if not indices:
            return
        self.bank.copy(indices[0])
        self.bank.clear_slot(indices[0])
        self.mark_dirty(f"Cut slot {map_slot(indices[0]).display_number_text}")
        self.refresh_bank_tree()

    def duplicate_bank_slot(self) -> None:
        indices = self.selected_bank_indices()
        if not indices:
            return
        self.bank.copy(indices[0])
        empty_indices = [i for i, slot in enumerate(self.bank.slots) if not slot.raw]
        if empty_indices:
            self.bank.paste(empty_indices[0])
            self.mark_dirty(f'Duplicated {map_slot(indices[0]).bank_slot_text} into {map_slot(empty_indices[0]).bank_slot_text}')
            self.refresh_bank_tree()

    def paste_bank_slot(self) -> None:
        indices = self.selected_bank_indices()
        if indices:
            target = self.bank.slots[indices[0]]
            if target.raw or target.prog_bin or target.name:
                if not messagebox.askyesno(
                    "Overwrite slot",
                    f"Slot {indices[0] + 1:03d} is not empty. Overwrite it?",
                ):
                    return
            self.bank.paste(indices[0])
            self.mark_dirty(f'Pasted into {map_slot(indices[0]).bank_slot_text}')
            self.refresh_bank_tree()

    def move_bank_slot(self) -> None:
        indices = self.selected_bank_indices()
        if not indices:
            return
        target = simpledialog.askinteger("Move to slot", "Target slot 1-500:", minvalue=1, maxvalue=500)
        if target:
            self.bank.move(indices[0], target - 1)
            self.mark_dirty(f'Moved {map_slot(indices[0]).bank_slot_text} -> {map_slot(target - 1).bank_slot_text}')
            self.refresh_bank_tree()

    def swap_bank_slots(self) -> None:
        indices = self.selected_bank_indices()
        if len(indices) == 2:
            self.bank.swap(indices[0], indices[1])
            self.mark_dirty(f'Swapped {map_slot(indices[0]).bank_slot_text} <-> {map_slot(indices[1]).bank_slot_text}')
            self.refresh_bank_tree()

    def clear_bank_slot(self) -> None:
        cleared = self.selected_bank_indices()
        occupied = [index for index in cleared if self.bank.slots[index].raw or self.bank.slots[index].prog_bin or self.bank.slots[index].name]
        if occupied and not messagebox.askyesno(
            "Clear selected slot(s)",
            f"Clear {len(occupied)} occupied slot(s) in the local workspace?",
        ):
            return
        for index in cleared:
            self.bank.clear_slot(index)
        if cleared:
            self.mark_dirty("Cleared " + ", ".join(map_slot(index).bank_slot_text for index in cleared[:10]))
        self.refresh_bank_tree()

    def create_init_program_slot(self) -> None:
        messagebox.showinfo(
            "Init program template required",
            "Create Init Program needs a verified init template from an imported bank. "
            "Use Clear / Init to empty the local workspace slot for now.",
        )

    def save_selected_as_mnlgxdprog(self) -> None:
        indices = self.selected_bank_indices()
        if len(indices) != 1:
            messagebox.showinfo("Select one program", "Select exactly one decoded program.")
            return
        slot = self.bank.slots[indices[0]]
        programs = self.bank.export_programs(indices)
        if not programs:
            messagebox.showinfo("No decoded program", "The selected slot has no decoded minilogue xd program data.")
            return
        default_stem = safe_filename(slot.name.strip(), fallback=f"Slot_{indices[0] + 1:03d}")
        default_name = default_stem + ".mnlgxdprog"
        path = filedialog.asksaveasfilename(
            title="Save as minilogue xd Program",
            initialfile=default_name,
            defaultextension=".mnlgxdprog",
            filetypes=[("minilogue xd Program", "*.mnlgxdprog")],
        )
        if path:
            save_mnlgxdprog(programs[0], Path(path))
            self.append_log(log_line(f"Saved single program: {path}"))

    def save_selected_as_sysex(self) -> None:
        data = self.bank.export_selected_bytes(self.selected_bank_indices())
        if not data:
            messagebox.showinfo("No SysEx data", "The selected slot has no sendable SysEx data.")
            return
        path = filedialog.asksaveasfilename(
            title="Save selected as SysEx",
            defaultextension=".syx",
            filetypes=[("SysEx", "*.syx")],
        )
        if path:
            Path(path).write_bytes(data)
            self.append_log(log_line(f"Saved selected SysEx: {path}"))

    def sort_bank(self, reverse: bool) -> None:
        self.bank.sort_by_name(reverse)
        self.mark_dirty("Sorted bank Z-A" if reverse else "Sorted bank A-Z")
        self.refresh_bank_tree()

    def undo_bank(self) -> None:
        self.bank.undo()
        self.mark_dirty("Undo bank operation")
        self.refresh_bank_tree()

    def on_bank_drag_start(self, event: tk.Event) -> None:
        item = self.bank_tree.identify_row(event.y)
        if item and item.isdigit():
            self.bank_drag_start_index = int(item)
        else:
            self.bank_drag_start_index = None

    def on_bank_drag_release(self, event: tk.Event) -> None:
        if self.bank_drag_start_index is None:
            return
        item = self.bank_tree.identify_row(event.y)
        if item and item.isdigit():
            target = int(item)
            if target != self.bank_drag_start_index:
                source = self.bank_drag_start_index
                self.bank.move(source, target)
                self.mark_dirty(f"Moved {map_slot(source).bank_slot_text} -> {map_slot(target).bank_slot_text} by drag")
                self.refresh_bank_tree()
                self.append_log(
                    log_line(
                        f"Moved bank slot {source + 1} to {target + 1} by drag."
                    )
                )
        self.bank_drag_start_index = None

    def on_bank_double_click(self, event: tk.Event) -> None:
        region = self.bank_tree.identify_region(event.x, event.y)
        column = self.bank_tree.identify_column(event.x)
        item = self.bank_tree.identify_row(event.y)
        if region != "cell" or column != "#2" or not item.isdigit():
            return
        self.bank_tree.selection_set(item)
        self.rename_bank_slot()

    @staticmethod
    def program_to_record(program, index: int) -> SysexRecord:
        raw = encode_program_dump(program, index - 1)
        return SysexRecord(
            index=index,
            raw=raw,
            length=len(raw),
            manufacturer_id=0x42,
            is_korg=True,
            dump_type=program.source_type or "program-dump",
            sha256=OfflineBank.hash_raw(program.prog_bin),
            notes=program.name,
        )

    def save_capture_backup(self) -> None:
        data = self.sysex_buffer.to_bytes()
        if not data:
            messagebox.showinfo("No capture", "Receive or load SysEx data first.")
            return
        backup_dir = user_data_dir() / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        syx_path = backup_dir / f"backup_{stamp}.syx"
        manifest_path = backup_dir / f"backup_{stamp}.json"
        zip_path = backup_dir / f"backup_{stamp}.zip"
        records = build_records(data)
        syx_path.write_bytes(data)
        manifest = report_dict(str(syx_path), records)
        manifest["notes"] = simpledialog.askstring("Backup note", "Optional note:") or ""
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(syx_path, syx_path.name)
            archive.write(manifest_path, manifest_path.name)
        self.append_log(log_line(f"Created backup bundle: {zip_path}"))

    def refresh_user_units_trees(self) -> None:
        units = scan_user_units(user_units_dir())
        for tree_name, wanted_kind, slot_count in (
            ("user_osc_tree", "user-osc", 16),
            ("user_fx_tree", "user-fx", 32),
        ):
            if not hasattr(self, tree_name):
                continue
            tree = getattr(self, tree_name)
            tree.delete(*tree.get_children())
            visible = [unit for unit in units if unit.kind == wanted_kind]
            for slot_index in range(slot_count):
                unit = visible[slot_index] if slot_index < len(visible) else None
                if unit is None:
                    tree.insert(
                        "",
                        tk.END,
                        iid=f"{tree_name}:{slot_index}",
                        values=(f"{slot_index + 1:02d}", "Empty", "", "", "empty", "", ""),
                    )
                    continue
                tree.insert(
                    "",
                    tk.END,
                    iid=str(unit.path),
                    values=(
                        f"{slot_index + 1:02d}",
                        unit.name,
                        unit.module,
                        unit.compatibility,
                        unit.status,
                        unit.path.name,
                        unit.notes or f"{unit.size} bytes | {unit.short_hash}",
                    ),
                )

    def import_user_units(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Import User OSC / User FX files",
            filetypes=[("User unit files", "*.mnlgxdunit *.logueunit *.prlgunit *.zip *.bin *.wav"), ("All files", "*.*")],
        )
        for path in paths:
            try:
                unit = import_user_unit(Path(path), user_units_dir())
                self.append_log(
                    log_line(
                        f"Imported user unit: {unit.path.name} | {unit.kind} | "
                        f"{unit.compatibility} | {unit.status}"
                    )
                )
            except OSError as exc:
                self.append_log(log_line(f"Could not import user unit {path}: {exc}"))
        self.refresh_user_units_trees()

    def remove_selected_user_units(self) -> None:
        selected = []
        for tree_name in ("user_osc_tree", "user_fx_tree"):
            if hasattr(self, tree_name):
                for item in getattr(self, tree_name).selection():
                    path = Path(item)
                    if path.is_file():
                        selected.append(path)
        if not selected:
            return
        if not messagebox.askyesno(
            "Remove from library",
            "Remove selected user-unit file(s) from the local library folder? This does not touch the synth.",
        ):
            return
        for path in selected:
            try:
                if path.is_file() and path.parent == user_units_dir():
                    path.unlink()
                    self.append_log(log_line(f"Removed user unit from library: {path.name}"))
            except OSError as exc:
                self.append_log(log_line(f"Could not remove {path}: {exc}"))
        self.refresh_user_units_trees()

    def user_unit_send_not_implemented(self) -> None:
        messagebox.showinfo(
            "Not implemented yet",
            "User OSC / User FX transfer is intentionally not implemented yet.",
        )

    def export_user_units_manifest(self) -> None:
        messagebox.showinfo(
            "Manifest export removed",
            "User OSC / FX now uses slot-based inventory. Manifest export is no longer part of the normal workflow.",
        )

    def view_selected_user_unit_manifest(self) -> None:
        """Show the manifest or basic metadata for the selected user unit."""
        selected: list[Path] = []
        for tree_name in ("user_osc_tree", "user_fx_tree"):
            if hasattr(self, tree_name):
                selected.extend(Path(item) for item in getattr(self, tree_name).selection())
        if not selected:
            messagebox.showinfo("No user unit selected", "Select a User OSC or User FX file first.")
            return
        path = selected[0]
        try:
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
                manifest_name = next(
                    (name for name in names if name.endswith("manifest.json")),
                    None,
                )
                if manifest_name:
                    content = archive.read(manifest_name).decode("utf-8", errors="replace")
                else:
                    content = "No manifest.json found.\n\nArchive contents:\n" + "\n".join(sorted(names))
        except zipfile.BadZipFile:
            try:
                content = (
                    f"File: {path.name}\n"
                    f"Size: {path.stat().st_size} bytes\n"
                    "This file is not a ZIP-based .mnlgxdunit archive."
                )
            except OSError as exc:
                messagebox.showerror("Manifest view failed", str(exc))
                return
        except OSError as exc:
            messagebox.showerror("Manifest view failed", str(exc))
            return
        self.show_text_dialog(f"Manifest - {path.name}", content)

    def show_about(self) -> None:
        messagebox.showinfo(
            "About minilogue xd Librarian",
            "minilogue xd Librarian\n\n"
            "Purpose:\n"
            "Local librarian, SysEx, backup and diagnostic tool for Korg minilogue xd.\n\n"
            "Supported formats:\n"
            ".mnlgxdprog\n"
            ".mnlgxdlib\n"
            ".syx\n"
            ".mnlgxdunit\n\n"
            "Not an official Korg product.",
        )

    def open_log_folder(self) -> None:
        """Open the folder containing the application log."""
        folder = log_path().parent
        try:
            folder.mkdir(parents=True, exist_ok=True)
            if sys.platform.startswith("win"):
                os.startfile(folder)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                import subprocess

                subprocess.Popen(["open", str(folder)])
            else:
                import subprocess

                subprocess.Popen(["xdg-open", str(folder)])
        except Exception as exc:
            self.last_error = str(exc)
            self.logger.exception("Could not open log folder.")
            messagebox.showerror(
                "Could not open log folder",
                f"Could not open log folder:\n{folder}\n\n{exc}",
            )

    def copy_diagnostic_report(self) -> None:
        report = self.build_diagnostic_report()
        self.root.clipboard_clear()
        self.root.clipboard_append(report)
        self.append_log(log_line("Diagnostic report copied to clipboard."))
        messagebox.showinfo("Diagnostic Report", "Diagnostic report copied to clipboard.")

    def build_diagnostic_report(self) -> str:
        try:
            input_ports = get_input_ports()
        except Exception as exc:
            input_ports = [f"<error: {exc}>"]
        try:
            output_ports = get_output_ports()
        except Exception as exc:
            output_ports = [f"<error: {exc}>"]
        return "\n".join(
            [
                "minilogue xd Librarian Diagnostic Report",
                f"Version: {_APP_VERSION}",
                f"OS: {platform.platform()}",
                f"Python: {platform.python_version()}",
                f"Executable: {sys.executable}",
                f"App data path: {user_data_dir()}",
                f"Log file: {log_path()}",
                f"Log level: {logging.getLevelName(logging.getLogger().getEffectiveLevel())}",
                "Available MIDI IN ports:",
                *(f"  - {port}" for port in input_ports),
                "Available MIDI OUT ports:",
                *(f"  - {port}" for port in output_ports),
                f"Selected MIDI IN: {self.selected_input_port() or 'none'}",
                f"Selected MIDI OUT: {self.selected_output_port() or 'none'}",
                f"Last loaded bank: {self.loaded_source_path or 'unknown'}",
                f"Unsaved changes: {'yes' if self.dirty else 'no'}",
                f"Last error: {self.last_error or 'none'}",
            ]
        )

    def midi_connection_test(self) -> None:
        """Start a non-destructive MIDI connection test using the existing listener."""
        self.start_receive_mode("test")

    def start_receive_mode(self, mode: str) -> None:
        labels = {
            "single": "Receive Single Program",
            "bank": "Receive Full Bank / All Programs",
            "raw": "Raw SysEx Capture",
            "test": "MIDI Connection Test",
        }
        self.receive_mode = mode
        self.receive_mode_var.set(labels.get(mode, mode))
        self.listen_for_sysex()
        if mode == "bank":
            self.append_log(
                log_line(
                    "Receive mode: Full Bank / All Programs. Existing SysEx capture logic is used; hardware verification required."
                )
            )
        elif mode == "single":
            self.append_log(log_line("Receive mode: Single Program. Waiting for one program SysEx dump."))
        elif mode == "test":
            self.append_log(log_line("MIDI Connection Test: waiting for non-destructive incoming SysEx."))
        else:
            self.append_log(log_line("Receive mode: Raw SysEx Capture."))

    def request_current_from_xd(self) -> None:
        self.start_receive_mode("single")
        self.send_request_sysex(request_current_program(), "Request Current Preset")

    def request_selected_slot_from_xd(self) -> None:
        indices = self.selected_bank_indices()
        slot_index = indices[0] if indices else simpledialog.askinteger(
            "Request slot",
            "Slot 001-500:",
            minvalue=1,
            maxvalue=500,
        )
        if slot_index is None:
            return
        if isinstance(slot_index, int) and slot_index >= 1 and not indices:
            slot_index -= 1
        self.start_receive_mode("single")
        self.send_request_sysex(
            request_program_slot(slot_index),
            f"Request Slot {slot_index + 1:03d}",
        )

    def request_full_bank_from_xd(self) -> None:
        if not messagebox.askyesno(
            "Request full bank",
            "Request all 500 program slots one by one from the minilogue xd?\n\n"
            "This is non-destructive, but can take a while and needs hardware verification.",
        ):
            return
        self.start_receive_mode("bank")
        requests = [request_program_slot(index) for index in range(500)]
        self.send_request_sysex_batch(requests, "Request Full Bank")

    def send_request_sysex(self, raw: bytes, label: str) -> None:
        self.send_request_sysex_batch([raw], label)

    def send_request_sysex_batch(self, messages: list[bytes], label: str) -> None:
        if not self.receiver.is_open or not self.selected_output_port():
            messagebox.showwarning("No MIDI OUT", "Open the selected MIDI OUT port first.")
            return
        sender = self.receiver.make_sender()
        self.current_sender = sender
        try:
            sent = sender.send_messages(
                messages,
                self.read_int(self.send_delay_var.get(), 80),
                lambda index, total, length: self.listen_status_var.set(
                    f"{label}: sent {index}/{total} request(s)"
                ),
            )
        except Exception as exc:
            self.last_error = str(exc)
            self.logger.exception("%s failed.", label)
            messagebox.showerror(label, str(exc))
            self.flash_rx("error")
        else:
            self.append_log(log_line(f"{label}: sent {sent}/{len(messages)} request(s)."))
        finally:
            self.current_sender = None

    def send_selected_to_buffer(self) -> None:
        messagebox.showinfo(
            "Send to buffer",
            "Sending selected programs to the edit buffer is not verified yet. Use Send Selected for explicit slot SysEx transfer.",
        )

    def write_bank_to_xd(self) -> None:
        if not messagebox.askyesno(
            "Backup recommended",
            "It is recommended to create a full backup before overwriting the minilogue xd.\n\n"
            "Continue to send all populated bank slots without creating a backup now?",
        ):
            return
        indices = [index for index, slot in enumerate(self.bank.slots) if slot.raw]
        if not indices:
            messagebox.showinfo("Nothing to send", "No sendable bank slots are loaded.")
            return
        self.bank_tree.selection_set([str(index) for index in indices])
        self.send_selected_bank_slots()

    def mark_dirty(self, description: str) -> None:
        self.dirty = True
        if description:
            self.change_log.append(description)
            self.append_log(log_line(description))
        self.update_window_title()

    def clear_dirty_state(self) -> None:
        self.dirty = False
        self.update_window_title()

    def update_window_title(self) -> None:
        marker = " *" if self.dirty else ""
        self.root.title(f"{self.app_title}{marker}")

    def show_change_log(self) -> None:
        if not self.change_log:
            messagebox.showinfo("Change Log", "No bank changes recorded in this session.")
            return
        self.show_text_dialog("Change Log", "\n".join(self.change_log))

    def show_text_dialog(self, title: str, content: str) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.geometry("720x480")
        dialog.transient(self.root)
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(0, weight=1)
        text_widget = scrolledtext.ScrolledText(dialog, wrap=tk.WORD, font=("Consolas", 10))
        text_widget.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        text_widget.insert("1.0", content)
        text_widget.configure(state=tk.DISABLED)
        ttk.Button(dialog, text="Close", command=dialog.destroy).grid(row=1, column=0, pady=(0, 8))


    def update_status(self) -> None:
        ports_open = "yes" if self.receiver.is_open else "no"
        self.status_var.set(
            f"Ports open: {ports_open} | Last MIDI: {self.last_midi_info.message_type} "
            f"({self.last_midi_info.length} bytes) | Last SysEx: {self.last_sysex_info.length} bytes | "
            f"Relevant MIDI: {self.total_messages} | SysEx: {self.total_sysex_messages} | "
            f"SysEx bytes: {self.total_sysex_bytes}"
        )
        capture = self.sysex_buffer.capture
        capture_count = len(capture.messages) if capture else 0
        capture_bytes = capture.total_bytes if capture else 0
        capture_state = "idle" if capture is None else ("active" if capture.is_active else "finalized")
        finalized_by = "none" if capture is None else (capture.finalized_by or "none")
        manufacturer = (
            f"0x{self.last_sysex_info.manufacturer_id:02X}"
            if self.last_sysex_info.manufacturer_id is not None
            else "none"
        )
        korg = "disabled"
        if self.auto_detect_korg_var.get():
            korg = "yes" if self.last_sysex_info.is_korg else "no"
        self.sysex_summary_var.set(
            "Last SysEx summary\n"
            f"Starts with F0: {'yes' if self.last_sysex_info.starts_with_f0 else 'no'}\n"
            f"Ends with F7: {'yes' if self.last_sysex_info.ends_with_f7 else 'no'}\n"
            f"Manufacturer ID: {manufacturer}\n"
            f"Korg 0x42 detected: {korg}\n\n"
            "Current capture\n"
            f"Messages: {capture_count}\n"
            f"Bytes: {capture_bytes}\n"
            f"State: {capture_state}\n"
            f"Finalized by: {finalized_by}"
        )
        self.settings_status_var.set(
            f"Settings: {settings_path()} | Last successful IN: "
            f"{self.settings.get('last_successful_midi_in', 'none')} | OUT: "
            f"{self.settings.get('last_successful_midi_out', 'none')} | SysEx: "
            f"{self.settings.get('last_successful_sysex_received_at', 'never')}"
        )
        self.bottom_status_var.set(
            f"MIDI: {ports_open} | IN: {self.selected_input_port() or 'none'} | "
            f"OUT: {self.selected_output_port() or 'none'} | "
            f"Last SysEx: {'yes' if self.total_sysex_messages else 'no'} | "
            f"Realtime hidden: {'yes' if self.hide_midi_clock_var.get() else 'no'} | "
            f"Capture: {capture_state}"
        )

    def save_successful_sysex_ports(self, timestamp: float) -> None:
        if self.selected_input_port():
            self.settings["last_successful_midi_in"] = self.selected_input_port()
        if self.selected_output_port():
            self.settings["last_successful_midi_out"] = self.selected_output_port()
        self.settings["last_successful_sysex_received_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
        self.persist_settings()

    def _collect_settings(self) -> None:
        """Copy current GUI settings into the persisted settings dictionary."""
        self.settings["inactivity_ms"] = self.read_int(self.inactivity_ms_var.get(), 500)
        self.settings["max_timeout_s"] = self.read_int(self.max_timeout_s_var.get(), 10)
        self.settings["send_delay_ms"] = self.read_int(self.send_delay_var.get(), 80)
        self.settings["show_sysex_only"] = self.show_sysex_only_var.get()
        self.settings["hide_midi_clock"] = self.hide_midi_clock_var.get()
        self.settings["show_realtime"] = self.show_realtime_var.get()
        self.settings["show_note_controller"] = self.show_note_controller_var.get()

    def save_settings_from_tab(self) -> None:
        self._collect_settings()
        self.settings["last_successful_midi_in"] = self.default_in_var.get()
        self.settings["last_successful_midi_out"] = self.default_out_var.get()
        self.persist_settings()
        self.update_status()

    def persist_settings(self) -> None:
        try:
            save_settings(self.settings)
        except OSError as exc:
            self.append_log(log_line(f"Could not save settings: {exc}"))

    def clear_log(self) -> None:
        self.log_text.delete("1.0", tk.END)
        self.append_log(log_line("Log cleared. Current capture is preserved."))

    def append_log(self, text: str) -> None:
        self.log_text.insert(tk.END, text.rstrip() + "\n")
        self.log_text.see(tk.END)
        try:
            append_to_file(log_path(), text)
        except OSError:
            pass

    def flash_rx(self, mode: str) -> None:
        color = {"midi": "#2e7d32", "sysex": "#f9a825", "error": "#c62828"}.get(mode, "#2e7d32")
        self.rx_indicator.configure(bg=color)
        self.root.after(180, lambda: self.rx_indicator.configure(bg="#9e9e9e"))

    @staticmethod
    def read_int(value: str, default: int) -> int:
        try:
            return max(0, int(value))
        except ValueError:
            return default

    def on_close(self) -> None:
        """Close MIDI resources, persist settings and destroy the root window."""
        unsaved_items = []
        if self.dirty:
            unsaved_items.append("the current bank has unsaved changes")
        if self.sysex_buffer.to_bytes():
            unsaved_items.append("there is an unsaved SysEx capture")
        if unsaved_items:
            if not messagebox.askyesno(
                "Unsaved changes",
                "Unsaved data is present:\n\n"
                + "\n".join(f"- {item}" for item in unsaved_items)
                + "\n\nClose anyway?",
            ):
                return
        self._collect_settings()
        self.settings["last_midi_in"] = self.selected_input_port()
        self.settings["last_midi_out"] = self.selected_output_port()
        self.persist_settings()
        self.receiver.close_ports()
        self.root.destroy()

    def close(self) -> None:
        """Backward-compatible alias used by tests and older entry points."""
        self.on_close()

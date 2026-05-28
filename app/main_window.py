"""Tkinter main window for the minilogue xd librarian."""

from __future__ import annotations

import json
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
from librarian.user_units import export_manifest, import_user_unit, scan_user_units
from midi.diagnostics import MidiMessageInfo, analyze_raw_message
from midi.filters import (
    MidiFilterSettings,
    is_realtime_message,
    should_log_message,
)
from midi.ports import get_input_ports, get_output_ports
from midi.receiver import MidiReceiver, QueuedMidiError, QueuedMidiMessage
from midi.sysex_buffer import SysexBuffer
from utils.hexview import format_hex
from utils.logger import append_to_file, log_line


class MainWindow:
    """Tabbed librarian GUI with safe raw SysEx workflows."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("minilogue xd Librarian - MIDI Test")
        self.root.geometry("1180x780")
        self.root.minsize(980, 680)

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

        self.input_port_var = tk.StringVar()
        self.output_port_var = tk.StringVar()
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
        self.backup_status_var = tk.StringVar(value="No backup selected.")

        self._build_layout()
        self.refresh_ports()
        self.refresh_bank_tree()
        self.refresh_backup_list()
        self.refresh_user_units_trees()
        self.update_status()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(50, self.process_queue)
        self.root.after(100, self.check_capture_timeouts)

    def _build_layout(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        self.tabs = ttk.Notebook(self.root)
        self.tabs.grid(row=0, column=0, sticky="nsew")

        self.banks_tab = ttk.Frame(self.tabs, padding=10)
        self.midi_tab = ttk.Frame(self.tabs, padding=10)
        self.backups_tab = ttk.Frame(self.tabs, padding=10)
        self.user_osc_tab = ttk.Frame(self.tabs, padding=10)
        self.user_fx_tab = ttk.Frame(self.tabs, padding=10)
        self.settings_tab = ttk.Frame(self.tabs, padding=10)

        self.tabs.add(self.banks_tab, text="Programs / Banks")
        self.tabs.add(self.midi_tab, text="Transfer / SysEx")
        self.tabs.add(self.backups_tab, text="Backups")
        self.tabs.add(self.user_osc_tab, text="User OSC")
        self.tabs.add(self.user_fx_tab, text="User FX")
        self.tabs.add(self.settings_tab, text="Options")

        self._build_banks_tab()
        self._build_midi_tab()
        self._build_backups_tab()
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
            ("Listen for SysEx", self.listen_for_sysex),
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
        bank_buttons = [
            ("Open Bank", self.open_bank),
            ("Open Preset", self.open_preset_into_bank),
            ("Save Bank", self.save_bank_copy),
            ("Save Bank As", self.save_bank_copy),
            ("Export Selected", self.export_selected_bank_slots),
            ("Receive from XD", self.listen_for_sysex),
            ("Send Selected", self.send_selected_bank_slots),
            ("Rename", self.rename_bank_slot),
            ("Duplicate", self.duplicate_bank_slot),
            ("Delete from Workspace", self.clear_bank_slot),
            ("Copy", self.copy_bank_slot),
            ("Paste", self.paste_bank_slot),
            ("Move To", self.move_bank_slot),
            ("Swap", self.swap_bank_slots),
            ("Clear / Init", self.clear_bank_slot),
            ("Sort A-Z", lambda: self.sort_bank(False)),
            ("Sort Z-A", lambda: self.sort_bank(True)),
            ("Undo", self.undo_bank),
        ]
        for index, (text, command) in enumerate(bank_buttons):
            ttk.Button(controls, text=text, command=command).grid(row=index // 8, column=index % 8, padx=(0, 5), pady=(0, 4))
        self.bank_search_var = tk.StringVar()
        self.show_duplicates_var = tk.BooleanVar(value=False)
        ttk.Label(controls, text="Search").grid(row=2, column=0, sticky="w")
        ttk.Entry(controls, textvariable=self.bank_search_var, width=24).grid(row=2, column=1, sticky="w")
        ttk.Checkbutton(controls, text="Duplicates", variable=self.show_duplicates_var).grid(
            row=2, column=2, sticky="w"
        )
        ttk.Button(controls, text="Find / Filter", command=self.refresh_bank_tree).grid(row=2, column=3, sticky="w")
        ttk.Label(
            controls,
            text="No bank loaded. Open a bank, load presets, or receive data from the minilogue xd.",
            foreground="#5f6368",
        ).grid(row=3, column=0, columnspan=8, sticky="ew", pady=(5, 0))

        self.bank_tree = ttk.Treeview(
            self.banks_tab,
            columns=("linear", "bank_slot", "name", "source", "status", "hash", "notes"),
            show="headings",
            selectmode="extended",
        )
        self._setup_tree(
            self.bank_tree,
            [
                ("linear", "Linear Slot", 80),
                ("bank_slot", "Bank Slot", 80),
                ("name", "Program Name", 170),
                ("source", "Source", 230),
                ("status", "Status", 180),
                ("hash", "Hash", 110),
                ("notes", "Notes", 300),
            ],
        )
        self.bank_tree.grid(row=1, column=0, sticky="nsew")
        self.bank_tree.bind("<ButtonPress-1>", self.on_bank_drag_start)
        self.bank_tree.bind("<ButtonRelease-1>", self.on_bank_drag_release)

    def _build_backups_tab(self) -> None:
        self.backups_tab.columnconfigure(0, weight=1)
        self.backups_tab.rowconfigure(2, weight=1)

        controls = ttk.Frame(self.backups_tab)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        for index, (text, command) in enumerate(
            [
                ("Save Capture Backup", self.save_capture_backup),
                ("Refresh", self.refresh_backup_list),
                ("Load Selected", self.load_selected_backup),
                ("Send Selected", self.send_selected_backup),
                ("Compare Two", self.compare_backups),
            ]
        ):
            ttk.Button(controls, text=text, command=command).grid(row=0, column=index, padx=(0, 6))
        ttk.Label(self.backups_tab, textvariable=self.backup_status_var).grid(
            row=1, column=0, sticky="ew", pady=(0, 8)
        )
        self.backup_tree = ttk.Treeview(
            self.backups_tab,
            columns=("name", "messages", "bytes", "created", "notes"),
            show="headings",
            selectmode="extended",
        )
        self._setup_tree(
            self.backup_tree,
            [
                ("name", "Name", 260),
                ("messages", "Messages", 90),
                ("bytes", "Bytes", 100),
                ("created", "Created", 150),
                ("notes", "Notes", 360),
            ],
        )
        self.backup_tree.grid(row=2, column=0, sticky="nsew")

    def _build_user_unit_placeholder_tab(self, parent: ttk.Frame, label: str) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        controls = ttk.Frame(parent)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        for index, (text, command) in enumerate(
            [
                ("Import Files", self.import_user_units),
                ("Remove From Library", self.remove_selected_user_units),
                ("Export Manifest", self.export_user_units_manifest),
                ("Refresh", self.refresh_user_units_trees),
                ("Send", self.user_unit_send_not_implemented),
            ]
        ):
            ttk.Button(controls, text=text, command=command).grid(row=0, column=index, padx=(0, 6))
        ttk.Label(
            controls,
            text=f"{label} transfer is not implemented yet. Files are kept separate from programs and banks.",
            foreground="#5f6368",
        ).grid(row=1, column=0, columnspan=5, sticky="w", pady=(6, 0))

        tree = ttk.Treeview(
            parent,
            columns=("file", "kind", "size", "hash", "modified"),
            show="headings",
            selectmode="extended",
        )
        self._setup_tree(
            tree,
            [
                ("file", "File", 320),
                ("kind", "Kind", 110),
                ("size", "Bytes", 90),
                ("hash", "Hash", 120),
                ("modified", "Modified", 160),
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
                ("Test selected ports", self.listen_for_sysex),
                ("Save Port Combination", self.save_current_port_combination),
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
    def select_port_label(variable: tk.StringVar, mapping: dict[str, str], preferred: str | None, labels: list[str]) -> None:
        for candidate in (preferred, mapping.get(variable.get(), variable.get())):
            if not candidate:
                continue
            for label, port in mapping.items():
                if port == candidate:
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
        self.total_messages += 1
        is_realtime = is_realtime_message(info.message_type)
        if is_realtime:
            self.realtime_messages += 1
            if info.message_type == "clock":
                self.clock_messages += 1
                if self.listen_active:
                    self.listen_saw_clock = True
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
                self.listen_status_var.set("Port test: SysEx received on selected IN port")
            if info.is_korg:
                self.save_successful_sysex_ports(now)
                if self.listen_active:
                    self.listen_status_var.set("Port test: Korg SysEx detected")
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
        if not messagebox.askyesno(
            "Confirm SysEx send",
            f"Send {len(records)} raw SysEx message(s) to:\n{self.selected_output_port()}\n\n"
            "This is an explicit transfer action. Continue?",
        ):
            return
        sender = self.receiver.make_sender()
        self.current_sender = sender
        delay_ms = self.read_int(self.send_delay_var.get(), 80)
        try:
            sent = sender.send_messages(
                [record.raw for record in records],
                delay_ms,
                lambda index, total, length: self.append_log(
                    log_line(f"Sent SysEx {index}/{total} ({length} bytes)")
                ),
            )
        except Exception as exc:
            messagebox.showerror("Send failed", str(exc))
            self.flash_rx("error")
            return
        finally:
            self.current_sender = None
        self.append_log(log_line(f"Send complete: {sent}/{len(records)} message(s)."))

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
        records = read_sysex_file(Path(path))
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
        records = read_sysex_file(Path(path))
        empty_indices = [i for i, slot in enumerate(self.bank.slots) if not slot.raw]
        self.bank.remember()
        for record, index in zip(records, empty_indices):
            slot = self.bank.slots[index]
            slot.name = f"Program {index + 1:03d}"
            slot.source = path
            slot.raw = record.raw
            slot.sha256 = record.sha256
            slot.status = record.dump_type
            slot.notes = "Loaded as preset into offline bank workspace."
        self.bank.mark_duplicates()
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
        records = read_sysex_file(Path(path))
        self.bank.load_records(records, path)
        self.refresh_bank_tree()

    def refresh_bank_tree(self) -> None:
        if not hasattr(self, "bank_tree"):
            return
        query = self.bank_search_var.get().lower() if hasattr(self, "bank_search_var") else ""
        duplicates_only = self.show_duplicates_var.get() if hasattr(self, "show_duplicates_var") else False
        self.bank_tree.delete(*self.bank_tree.get_children())
        for index, slot in enumerate(self.bank.slots):
            if query and query not in slot.name.lower() and query not in slot.status.lower():
                continue
            if duplicates_only and "duplicate" not in slot.status:
                continue
            self.bank_tree.insert(
                "",
                tk.END,
                iid=str(index),
                values=(
                    map_slot(index).display_number_text,
                    map_slot(index).bank_slot_text,
                    slot.name or "Empty",
                    slot.source,
                    slot.status or "empty",
                    slot.short_hash,
                    slot.notes,
                ),
            )

    def selected_bank_indices(self) -> list[int]:
        return [int(item) for item in self.bank_tree.selection()]

    def save_bank_copy(self) -> None:
        data = b"".join(slot.raw for slot in self.bank.slots if slot.raw)
        if not data:
            messagebox.showinfo("Empty bank", "No raw bank data is loaded.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".syx", filetypes=[("SysEx", "*.syx")])
        if path:
            Path(path).write_bytes(data)

    def export_selected_bank_slots(self) -> None:
        data = self.bank.export_selected_bytes(self.selected_bank_indices())
        if not data:
            return
        path = filedialog.asksaveasfilename(defaultextension=".syx", filetypes=[("SysEx", "*.syx")])
        if path:
            Path(path).write_bytes(data)

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
        name = simpledialog.askstring("Rename display name", "New display name:")
        if name is not None:
            self.bank.rename(indices[0], name)
            self.refresh_bank_tree()

    def copy_bank_slot(self) -> None:
        indices = self.selected_bank_indices()
        if indices:
            self.bank.copy(indices[0])

    def duplicate_bank_slot(self) -> None:
        indices = self.selected_bank_indices()
        if not indices:
            return
        self.bank.copy(indices[0])
        empty_indices = [i for i, slot in enumerate(self.bank.slots) if not slot.raw]
        if empty_indices:
            self.bank.paste(empty_indices[0])
            self.refresh_bank_tree()

    def paste_bank_slot(self) -> None:
        indices = self.selected_bank_indices()
        if indices:
            self.bank.paste(indices[0])
            self.refresh_bank_tree()

    def move_bank_slot(self) -> None:
        indices = self.selected_bank_indices()
        if not indices:
            return
        target = simpledialog.askinteger("Move to slot", "Target slot 1-500:", minvalue=1, maxvalue=500)
        if target:
            self.bank.move(indices[0], target - 1)
            self.refresh_bank_tree()

    def swap_bank_slots(self) -> None:
        indices = self.selected_bank_indices()
        if len(indices) == 2:
            self.bank.swap(indices[0], indices[1])
            self.refresh_bank_tree()

    def clear_bank_slot(self) -> None:
        for index in self.selected_bank_indices():
            self.bank.clear_slot(index)
        self.refresh_bank_tree()

    def sort_bank(self, reverse: bool) -> None:
        self.bank.sort_by_name(reverse)
        self.refresh_bank_tree()

    def undo_bank(self) -> None:
        self.bank.undo()
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
                self.bank.move(self.bank_drag_start_index, target)
                self.refresh_bank_tree()
                self.append_log(
                    log_line(
                        f"Moved bank slot {self.bank_drag_start_index + 1} to {target + 1} by drag."
                    )
                )
        self.bank_drag_start_index = None

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
        self.refresh_backup_list()

    def refresh_backup_list(self) -> None:
        if not hasattr(self, "backup_tree"):
            return
        self.backup_tree.delete(*self.backup_tree.get_children())
        backup_dir = user_data_dir() / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        for manifest_path in sorted(backup_dir.glob("backup_*.json"), reverse=True):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            source = Path(manifest.get("source", ""))
            self.backup_tree.insert(
                "",
                tk.END,
                iid=str(manifest_path),
                values=(
                    source.name,
                    manifest.get("message_count", 0),
                    manifest.get("total_bytes", 0),
                    manifest_path.stem.replace("backup_", ""),
                    manifest.get("notes", ""),
                ),
            )

    def selected_backup_paths(self) -> list[Path]:
        paths = []
        for item in self.backup_tree.selection():
            try:
                manifest = json.loads(Path(item).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            paths.append(Path(manifest["source"]))
        return paths

    def load_selected_backup(self) -> None:
        paths = self.selected_backup_paths()
        if not paths:
            return
        self.loaded_records = read_sysex_file(paths[0])
        self.loaded_source_path = str(paths[0])
        self.analyzer_status_var.set(report_text(str(paths[0]), self.loaded_records))
        self.tabs.select(self.midi_tab)

    def send_selected_backup(self) -> None:
        paths = self.selected_backup_paths()
        if paths:
            self.send_records(read_sysex_file(paths[0]), "selected backup")

    def compare_backups(self) -> None:
        paths = self.selected_backup_paths()
        if len(paths) != 2:
            messagebox.showinfo("Select two backups", "Select exactly two backups to compare.")
            return
        first = build_records(paths[0].read_bytes())
        second = build_records(paths[1].read_bytes())
        same = [a.sha256 == b.sha256 for a, b in zip(first, second)]
        self.backup_status_var.set(
            f"Compare: {paths[0].name} vs {paths[1].name} | "
            f"messages {len(first)} / {len(second)} | matching positions {sum(same)}"
        )

    def refresh_user_units_trees(self) -> None:
        units = scan_user_units(user_units_dir())
        for tree_name, wanted_kind in (("user_osc_tree", "osc"), ("user_fx_tree", "fx")):
            if not hasattr(self, tree_name):
                continue
            tree = getattr(self, tree_name)
            tree.delete(*tree.get_children())
            for unit in units:
                if wanted_kind not in unit.kind:
                    continue
                tree.insert(
                    "",
                    tk.END,
                    iid=str(unit.path),
                    values=(unit.path.name, unit.kind, unit.size, unit.short_hash, unit.modified),
                )

    def import_user_units(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Import User OSC / User FX files",
            filetypes=[("User unit files", "*.mnlgxdunit *.logueunit *.prlgunit *.zip *.bin *.wav"), ("All files", "*.*")],
        )
        for path in paths:
            try:
                unit = import_user_unit(Path(path), user_units_dir())
                self.append_log(log_line(f"Imported user unit: {unit.path.name} ({unit.kind})"))
            except OSError as exc:
                self.append_log(log_line(f"Could not import user unit {path}: {exc}"))
        self.refresh_user_units_trees()

    def remove_selected_user_units(self) -> None:
        selected = []
        for tree_name in ("user_osc_tree", "user_fx_tree"):
            if hasattr(self, tree_name):
                selected.extend(Path(item) for item in getattr(self, tree_name).selection())
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
        units = scan_user_units(user_units_dir())
        if not units:
            messagebox.showinfo("No user units", "No user-unit files are in the local library.")
            return
        path = filedialog.asksaveasfilename(
            title="Export User Units Manifest",
            defaultextension=".json",
            filetypes=[("JSON manifest", "*.json")],
        )
        if path:
            export_manifest(Path(path), units)
            self.append_log(log_line(f"Exported user-units manifest: {path}"))

    def update_status(self) -> None:
        ports_open = "yes" if self.receiver.is_open else "no"
        self.status_var.set(
            f"Ports open: {ports_open} | Last MIDI: {self.last_midi_info.message_type} "
            f"({self.last_midi_info.length} bytes) | Last SysEx: {self.last_sysex_info.length} bytes | "
            f"Total MIDI: {self.total_messages} | SysEx: {self.total_sysex_messages} | "
            f"SysEx bytes: {self.total_sysex_bytes} | Clock ignored: {self.clock_messages}"
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
            f"Clock ignored: {'yes' if self.hide_midi_clock_var.get() else 'no'} "
            f"({self.clock_messages}) | Capture: {capture_state}"
        )

    def save_successful_sysex_ports(self, timestamp: float) -> None:
        if self.selected_input_port():
            self.settings["last_successful_midi_in"] = self.selected_input_port()
        if self.selected_output_port():
            self.settings["last_successful_midi_out"] = self.selected_output_port()
        self.settings["last_successful_sysex_received_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
        self.persist_settings()

    def save_settings_from_tab(self) -> None:
        self.settings["last_successful_midi_in"] = self.default_in_var.get()
        self.settings["last_successful_midi_out"] = self.default_out_var.get()
        self.settings["inactivity_ms"] = self.read_int(self.inactivity_ms_var.get(), 500)
        self.settings["max_timeout_s"] = self.read_int(self.max_timeout_s_var.get(), 10)
        self.settings["send_delay_ms"] = self.read_int(self.send_delay_var.get(), 80)
        self.settings["show_sysex_only"] = self.show_sysex_only_var.get()
        self.settings["hide_midi_clock"] = self.hide_midi_clock_var.get()
        self.settings["show_realtime"] = self.show_realtime_var.get()
        self.settings["show_note_controller"] = self.show_note_controller_var.get()
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
        self.settings["last_midi_in"] = self.selected_input_port()
        self.settings["last_midi_out"] = self.selected_output_port()
        self.settings["inactivity_ms"] = self.read_int(self.inactivity_ms_var.get(), 500)
        self.settings["max_timeout_s"] = self.read_int(self.max_timeout_s_var.get(), 10)
        self.settings["send_delay_ms"] = self.read_int(self.send_delay_var.get(), 80)
        self.settings["show_sysex_only"] = self.show_sysex_only_var.get()
        self.settings["hide_midi_clock"] = self.hide_midi_clock_var.get()
        self.settings["show_realtime"] = self.show_realtime_var.get()
        self.settings["show_note_controller"] = self.show_note_controller_var.get()
        self.persist_settings()
        self.receiver.close_ports()
        self.root.destroy()

    def close(self) -> None:
        """Backward-compatible alias used by tests and older entry points."""
        self.on_close()

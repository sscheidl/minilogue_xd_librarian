#!/usr/bin/env python3
"""CLI diagnostics for minilogue xd MIDI/SysEx import and export issues.

This tool focuses on the Windows 11 + Microsoft MIDI driver setup where
port routing and SysEx command classes can look "partially working":
for example receiving 0x51/0x44/0x45 but never 0x40/0x4C.
"""

from __future__ import annotations

import argparse
import json
import queue
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from devices.korg_minilogue_xd.sysex import classify_xd_sysex
from midi.sysex_requests import request_current_program, request_global_data, request_program_slot
from xd_formats.sysex_codec import split_sysex_stream_ignoring_realtime

try:
    import mido
except Exception as exc:  # pragma: no cover - import depends on host environment
    mido = None
    MIDO_IMPORT_ERROR = exc
else:
    MIDO_IMPORT_ERROR = None

REALTIME_TYPES = {"clock", "start", "stop", "continue", "active_sensing", "reset"}


@dataclass(frozen=True)
class LiveEvent:
    timestamp: float
    port: str
    message_type: str
    raw: bytes


@dataclass(frozen=True)
class ProbeResult:
    request_name: str
    channel: int
    trailing_zero: bool | None
    output_ports: list[str]
    response_found: bool
    response_command: int | None
    response_label: str | None
    response_port: str | None
    response_len: int | None


def is_xd_port(name: str) -> bool:
    return "minilogue xd" in name.lower()


def is_port2(name: str) -> bool:
    low = name.lower().strip()
    return "midiin2" in low or "midiout2" in low or low.endswith(" 2") or low.endswith(") 2")


def port_sort_key(name: str) -> tuple[int, str]:
    if is_xd_port(name):
        return (1 if is_port2(name) else 0, name.lower())
    return (9, name.lower())


def hex_line(raw: bytes, max_len: int = 72) -> str:
    text = " ".join(f"{byte:02X}" for byte in raw[:max_len])
    if len(raw) > max_len:
        text += f" ... ({len(raw)} bytes)"
    return text


def format_command(command: int | None) -> str:
    return "none" if command is None else f"0x{command:02X}"


class MidiSession:
    def __init__(self, input_ports: Sequence[str], output_ports: Sequence[str]) -> None:
        self._input_ports = list(input_ports)
        self._output_ports = list(output_ports)
        self._events: "queue.Queue[LiveEvent]" = queue.Queue()
        self._in_handles: list[object] = []
        self._out_handles: dict[str, object] = {}

    @property
    def output_port_names(self) -> list[str]:
        return list(self._out_handles.keys())

    def __enter__(self) -> "MidiSession":
        if mido is None:
            raise RuntimeError(f"mido import failed: {MIDO_IMPORT_ERROR}")
        for in_name in self._input_ports:
            handle = mido.open_input(in_name, callback=lambda msg, port=in_name: self._on_message(port, msg))
            self._in_handles.append(handle)
        for out_name in self._output_ports:
            self._out_handles[out_name] = mido.open_output(out_name)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        for handle in self._in_handles:
            try:
                handle.close()
            except Exception:
                pass
        for handle in self._out_handles.values():
            try:
                handle.close()
            except Exception:
                pass
        self._in_handles.clear()
        self._out_handles.clear()

    def _on_message(self, port: str, msg) -> None:
        try:
            raw = bytes(msg.bytes())
        except Exception:
            raw = bytes()
        self._events.put(LiveEvent(time.time(), port, getattr(msg, "type", "unknown"), raw))

    def send(self, raw: bytes, port_names: Sequence[str], gap_s: float = 0.04) -> None:
        if not port_names:
            raise RuntimeError("No MIDI output ports selected.")
        if mido is None:
            raise RuntimeError(f"mido import failed: {MIDO_IMPORT_ERROR}")
        for index, port in enumerate(port_names):
            handle = self._out_handles.get(port)
            if handle is None:
                raise RuntimeError(f"Output port is not open: {port!r}")
            handle.send(mido.Message.from_bytes(list(raw)))
            if index < len(port_names) - 1 and gap_s > 0:
                time.sleep(gap_s)

    def drain_events(self) -> list[LiveEvent]:
        events: list[LiveEvent] = []
        while True:
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                return events

    def wait_for_response(self, timeout_s: float, wanted_commands: Iterable[int]) -> tuple[LiveEvent | None, list[LiveEvent]]:
        deadline = time.time() + max(0.05, timeout_s)
        wanted = set(wanted_commands)
        seen: list[LiveEvent] = []
        while time.time() < deadline:
            try:
                event = self._events.get(timeout=0.05)
            except queue.Empty:
                continue
            seen.append(event)
            if not event.raw or event.raw[0] != 0xF0 or event.message_type in REALTIME_TYPES:
                continue
            info = classify_xd_sysex(event.raw)
            if info.command in wanted:
                return event, seen
        return None, seen


def select_ports(ports: Sequence[str], mode: str) -> list[str]:
    ordered = sorted([port for port in ports if is_xd_port(port)], key=port_sort_key)
    if mode == "all":
        return ordered
    if mode == "both":
        return ordered
    if mode == "p1":
        return [port for port in ordered if not is_port2(port)]
    if mode == "p2":
        return [port for port in ordered if is_port2(port)]
    if mode == "auto":
        port2 = [port for port in ordered if is_port2(port)]
        return port2 if port2 else ordered
    raise ValueError(f"unsupported mode: {mode}")


def scan_stream_structure(raw: bytes) -> dict[str, int]:
    open_packets = 0
    truncated = 0
    for byte in raw:
        if byte == 0xF0:
            if open_packets > 0:
                truncated += 1
            open_packets = 1
        elif byte == 0xF7 and open_packets > 0:
            open_packets = 0
    if open_packets > 0:
        truncated += 1
    return {
        "bytes_total": len(raw),
        "f0_count": raw.count(0xF0),
        "f7_count": raw.count(0xF7),
        "realtime_count": sum(raw.count(byte) for byte in (0xF8, 0xF9, 0xFA, 0xFB, 0xFC, 0xFD, 0xFE)),
        "truncated_sysex_segments": truncated,
    }


def summarize_sysex_messages(messages: Sequence[bytes]) -> dict[str, object]:
    labels: Counter[str] = Counter()
    commands: Counter[str] = Counter()
    per_length: Counter[int] = Counter()
    program_candidates = 0
    for msg in messages:
        info = classify_xd_sysex(msg)
        labels[info.label] += 1
        commands[format_command(info.command)] += 1
        per_length[len(msg)] += 1
        if info.command in {0x40, 0x4C}:
            program_candidates += 1
    return {
        "total_messages": len(messages),
        "labels": dict(labels),
        "commands": dict(commands),
        "unique_lengths": len(per_length),
        "program_dump_candidates": program_candidates,
    }


def build_recommendations(commands: dict[str, int], truncated: int) -> list[str]:
    has_40 = commands.get("0x40", 0) > 0
    has_4c = commands.get("0x4C", 0) > 0
    has_44 = commands.get("0x44", 0) > 0
    has_45 = commands.get("0x45", 0) > 0
    has_51 = commands.get("0x51", 0) > 0

    tips: list[str] = []
    if has_51 and not (has_40 or has_4c):
        tips.append("0x51 kommt an, aber keine Program Dumps. Das ist typisch fuer Global/Diagnostic Dump statt Program Dump.")
    if (has_44 or has_45) and not (has_40 or has_4c):
        tips.append("Nur 0x44/0x45 gesehen: Das deutet auf Index/Sequencer-Infos, nicht auf Programmdaten.")
    if truncated > 0:
        tips.append("Unvollstaendige SysEx-Segmente erkannt. Das kann auf Treiber-/Port-Konflikte oder parallele MIDI-Apps hinweisen.")
    if not commands:
        tips.append("Keine SysEx erkannt. Bitte RX-Portwahl pruefen (insb. MIDIIN2 vs normaler Port).")
    if not tips:
        tips.append("Keine offensichtliche Struktur-Anomalie erkannt.")
    tips.append("Beim Test alle anderen MIDI-Programme schliessen (DAW, MIDI-OX, Librarian), um Port-Locks zu vermeiden.")
    return tips


def analyze_file(path: Path) -> dict[str, object]:
    raw_original = path.read_bytes()
    raw = raw_original
    parse_mode = "bytes"

    if raw.count(0xF0) == 0 and raw.count(0xF7) == 0:
        text = raw_original.decode("utf-8", errors="ignore")
        tokens = re.findall(r"\b[0-9A-Fa-f]{2}\b", text)
        if len(tokens) >= 16:
            parsed = bytes(int(token, 16) for token in tokens)
            if parsed.count(0xF0) or parsed.count(0xF7):
                raw = parsed
                parse_mode = "hex-text"

    structure = scan_stream_structure(raw)
    messages = split_sysex_stream_ignoring_realtime(raw)
    summary = summarize_sysex_messages(messages)
    recommendations = build_recommendations(
        summary.get("commands", {}), structure.get("truncated_sysex_segments", 0)
    )
    return {
        "source": str(path),
        "parse_mode": parse_mode,
        "structure": structure,
        "summary": summary,
        "recommendations": recommendations,
    }


def run_monitor(inputs: list[str], outputs: list[str], seconds: float) -> dict[str, object]:
    stats: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "sysex": 0, "realtime": 0, "other": 0, "bytes": 0})
    captured_sysex: list[bytes] = []
    print(f"[monitor] RX={inputs}")
    print(f"[monitor] TX={outputs} (not used in passive monitor)")
    with MidiSession(inputs, outputs) as session:
        end = time.time() + seconds
        while time.time() < end:
            for event in session.drain_events():
                stats[event.port]["total"] += 1
                stats[event.port]["bytes"] += len(event.raw)
                if event.message_type in REALTIME_TYPES:
                    stats[event.port]["realtime"] += 1
                elif event.raw and event.raw[0] == 0xF0:
                    stats[event.port]["sysex"] += 1
                    captured_sysex.append(event.raw)
                else:
                    stats[event.port]["other"] += 1
            time.sleep(0.05)
        for event in session.drain_events():
            stats[event.port]["total"] += 1
            stats[event.port]["bytes"] += len(event.raw)
            if event.message_type in REALTIME_TYPES:
                stats[event.port]["realtime"] += 1
            elif event.raw and event.raw[0] == 0xF0:
                stats[event.port]["sysex"] += 1
                captured_sysex.append(event.raw)
            else:
                stats[event.port]["other"] += 1
    summary = summarize_sysex_messages(captured_sysex)
    return {"mode": "monitor", "seconds": seconds, "port_stats": dict(stats), "summary": summary}


def run_probe(
    inputs: list[str],
    outputs: list[str],
    slot_display: int,
    response_timeout: float,
    include_slot_requests: bool,
) -> dict[str, object]:
    slot_index = slot_display - 1
    results: list[ProbeResult] = []
    seen_sysex: list[bytes] = []

    print(f"[probe] RX={inputs}")
    print(f"[probe] TX={outputs}")
    print(f"[probe] slot={slot_display:03d} (index {slot_index})")

    with MidiSession(inputs, outputs) as session:
        pending = session.drain_events()
        if pending:
            print(f"[probe] dropped {len(pending)} stale event(s) before starting")

        for request_name, channel, trailing, payload, wanted in build_probe_plan(slot_index, include_slot_requests):
            print(
                f"[probe] TX {request_name} ch={channel} "
                f"{'trailing00=ON' if trailing is True else 'trailing00=OFF' if trailing is False else ''} "
                f"{hex_line(payload)}"
            )
            session.send(payload, outputs)
            hit, seen = session.wait_for_response(response_timeout, wanted)
            for event in seen:
                if event.raw and event.raw[0] == 0xF0:
                    seen_sysex.append(event.raw)
            if hit is None:
                print(f"[probe] timeout ({response_timeout:.2f}s)")
                results.append(
                    ProbeResult(request_name, channel, trailing, list(outputs), False, None, None, None, None)
                )
                continue
            hit_info = classify_xd_sysex(hit.raw)
            print(
                f"[probe] hit on {hit.port}: cmd={format_command(hit_info.command)} "
                f"label={hit_info.label} len={len(hit.raw)}"
            )
            results.append(
                ProbeResult(
                    request_name=request_name,
                    channel=channel,
                    trailing_zero=trailing,
                    output_ports=list(outputs),
                    response_found=True,
                    response_command=hit_info.command,
                    response_label=hit_info.label,
                    response_port=hit.port,
                    response_len=len(hit.raw),
                )
            )
            time.sleep(0.06)

    summary = summarize_sysex_messages(seen_sysex)
    commands = summary.get("commands", {})
    recommendations = build_recommendations(commands if isinstance(commands, dict) else {}, 0)
    return {
        "mode": "probe",
        "slot_display": slot_display,
        "inputs": inputs,
        "outputs": outputs,
        "results": [asdict(item) for item in results],
        "summary": summary,
        "recommendations": recommendations,
    }


def build_probe_plan(slot_index: int, include_slot_requests: bool) -> list[tuple[str, int, bool | None, bytes, list[int]]]:
    plan: list[tuple[str, int, bool | None, bytes, list[int]]] = [
        ("global", 0, None, request_global_data(0), [0x51]),
    ]
    for channel in range(16):
        for trailing in (True, False):
            plan.append(
                (
                    "current",
                    channel,
                    trailing,
                    request_current_program(channel=channel, trailing_zero=trailing),
                    [0x40, 0x4C],
                )
            )
    if include_slot_requests:
        for channel in range(16):
            for trailing in (True, False):
                plan.append(
                    (
                        "slot",
                        channel,
                        trailing,
                        request_program_slot(slot_index=slot_index, channel=channel, trailing_zero=trailing),
                        [0x4C, 0x40],
                    )
                )
    return plan


def print_json_or_human(report: dict[str, object], json_out: Path | None) -> None:
    text = json.dumps(report, indent=2, ensure_ascii=True)
    if json_out is not None:
        json_out.write_text(text + "\n", encoding="utf-8")
        print(f"[report] wrote {json_out}")
    print(text)


def list_ports() -> dict[str, list[str]]:
    if mido is None:
        raise RuntimeError(f"mido import failed: {MIDO_IMPORT_ERROR}")
    inputs = sorted(mido.get_input_names(), key=port_sort_key)
    outputs = sorted(mido.get_output_names(), key=port_sort_key)
    return {"inputs": inputs, "outputs": outputs}


def require_mido() -> None:
    if mido is None:
        raise RuntimeError(f"mido import failed: {MIDO_IMPORT_ERROR}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="minilogue xd MIDI/SysEx diagnostics")

    sub = parser.add_subparsers(dest="command", required=True)

    list_ports_parser = sub.add_parser("list-ports", help="list visible MIDI ports")
    list_ports_parser.add_argument("--json-out", type=Path, help="write report JSON to this path")

    analyze = sub.add_parser("analyze-file", help="analyze a .syx/.mid raw byte stream")
    analyze.add_argument("path", type=Path, help="path to .syx/.mid/.bin capture file")
    analyze.add_argument("--json-out", type=Path, help="write report JSON to this path")

    monitor = sub.add_parser("monitor", help="passive live monitor without sending requests")
    monitor.add_argument("--seconds", type=float, default=30.0, help="monitor duration")
    monitor.add_argument("--rx-mode", choices=["auto", "p1", "p2", "both", "all"], default="auto")
    monitor.add_argument("--tx-mode", choices=["auto", "p1", "p2", "both", "all"], default="auto")
    monitor.add_argument("--json-out", type=Path, help="write report JSON to this path")

    probe = sub.add_parser("probe", help="active request probe across channels and trailing-byte variants")
    probe.add_argument("--slot", type=int, default=1, help="display slot number 1..500 for slot-request tests")
    probe.add_argument("--response-timeout", type=float, default=1.2, help="seconds to wait for each request")
    probe.add_argument("--rx-mode", choices=["auto", "p1", "p2", "both", "all"], default="auto")
    probe.add_argument("--tx-mode", choices=["auto", "p1", "p2", "both", "all"], default="auto")
    probe.add_argument("--skip-slot-requests", action="store_true", help="only test global/current requests")
    probe.add_argument("--json-out", type=Path, help="write report JSON to this path")

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    json_out: Path | None = getattr(args, "json_out", None)

    if args.command == "analyze-file":
        report = analyze_file(args.path)
        print_json_or_human(report, json_out)
        return 0

    require_mido()
    ports = list_ports()

    if args.command == "list-ports":
        report = {"mode": "list-ports", **ports}
        print_json_or_human(report, json_out)
        return 0

    rx = select_ports(ports["inputs"], args.rx_mode)
    tx = select_ports(ports["outputs"], args.tx_mode)
    if not rx:
        raise RuntimeError("No minilogue xd RX input ports selected. Use list-ports and check driver/USB routing.")
    if args.command == "probe" and not tx:
        raise RuntimeError("No minilogue xd TX output ports selected. Use list-ports and check driver/USB routing.")

    if args.command == "monitor":
        report = run_monitor(rx, tx, args.seconds)
        print_json_or_human(report, json_out)
        return 0

    if not 1 <= args.slot <= 500:
        raise ValueError("--slot must be within 1..500")
    report = run_probe(
        inputs=rx,
        outputs=tx,
        slot_display=args.slot,
        response_timeout=max(0.1, args.response_timeout),
        include_slot_requests=not args.skip_slot_requests,
    )
    print_json_or_human(report, json_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

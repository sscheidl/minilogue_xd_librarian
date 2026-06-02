import unittest
from queue import Queue

from midi.capture_events import RawCaptureEvent
from midi.engine3_capture import Engine3SysexCaptureWorker
from midi.engine3_native import MidiInputDevice, resolve_input_device


class Engine3CaptureTest(unittest.TestCase):
    def make_worker(self):
        return Engine3SysexCaptureWorker("MIDIIN2 (minilogue xd)", Queue[RawCaptureEvent]())

    def test_extracts_complete_frames_from_native_byte_stream(self):
        worker = self.make_worker()

        frames = worker._extract_frames(bytes.fromhex("F0 42 30 00 01 51 4C F7 F0 7D 01 F7"))

        self.assertEqual(
            frames,
            [
                bytes.fromhex("F0 42 30 00 01 51 4C F7"),
                bytes.fromhex("F0 7D 01 F7"),
            ],
        )

    def test_extract_frames_ignores_realtime_bytes(self):
        worker = self.make_worker()

        frames = worker._extract_frames(bytes.fromhex("F0 42 F8 30 00 01 51 4C F7"))

        self.assertEqual(frames, [bytes.fromhex("F0 42 30 00 01 51 4C F7")])

    def test_extract_frames_warns_when_incomplete_frame_is_replaced(self):
        queue: Queue[RawCaptureEvent] = Queue()
        worker = Engine3SysexCaptureWorker("MIDIIN2 (minilogue xd)", queue)

        frames = worker._extract_frames(bytes.fromhex("F0 42 30 F0 7D 01 F7"))

        self.assertEqual(frames, [bytes.fromhex("F0 7D 01 F7")])
        warning = queue.get_nowait()
        self.assertEqual(warning.kind, "warning")
        self.assertIn("Incomplete SysEx frame discarded", warning.message)

    def test_resolve_input_device_accepts_backend_alias(self):
        device = resolve_input_device(
            "MIDIIN2 (minilogue xd)",
            [
                MidiInputDevice(index=0, name="USB Audio Device"),
                MidiInputDevice(index=2, name="minilogue xd"),
            ],
        )

        self.assertEqual(device.index, 2)


if __name__ == "__main__":
    unittest.main()

import unittest

from midi.filters import MidiFilterSettings, should_log_message


class MidiFiltersTest(unittest.TestCase):
    def test_clock_hidden_by_default(self):
        self.assertFalse(should_log_message("clock", False, MidiFilterSettings()))

    def test_realtime_can_be_shown_when_clock_not_hidden(self):
        settings = MidiFilterSettings(
            show_sysex_only=True,
            hide_midi_clock=False,
            show_realtime=True,
        )
        self.assertTrue(should_log_message("clock", False, settings))

    def test_sysex_always_logs(self):
        self.assertTrue(should_log_message("sysex", True, MidiFilterSettings()))


if __name__ == "__main__":
    unittest.main()

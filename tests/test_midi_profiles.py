import tempfile
import unittest
from pathlib import Path

from midi.profiles import builtin_generic_profile, load_midi_profiles


class MidiProfilesTest(unittest.TestCase):
    def test_load_bundled_profiles_includes_generic_and_korg(self):
        profiles, warnings = load_midi_profiles()

        self.assertIn("generic_midi", profiles)
        self.assertIn("korg_minilogue_xd", profiles)
        self.assertEqual(profiles["generic_midi"].control_changes[7].name, "Channel Volume")
        self.assertEqual(profiles["generic_midi"].control_changes[91].name, "Reverb Send Level")
        self.assertEqual(profiles["korg_minilogue_xd"].control_changes[43].name, "Filter Cutoff")
        self.assertTrue(profiles["generic_midi"].program_mapping.uses_bank_select)
        self.assertEqual(profiles["korg_minilogue_xd"].program_mapping.program_count, 500)
        self.assertEqual(profiles["korg_minilogue_xd"].program_mapping.banks[1].name, "B")
        self.assertEqual(warnings, [])

    def test_invalid_json_falls_back_to_builtin_generic(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            (temp_path / "broken.json").write_text("{ invalid json", encoding="utf-8")

            profiles, warnings = load_midi_profiles(temp_path)

        self.assertIn("generic_midi", profiles)
        self.assertEqual(profiles["generic_midi"].display_name, builtin_generic_profile().display_name)
        self.assertTrue(warnings)


if __name__ == "__main__":
    unittest.main()

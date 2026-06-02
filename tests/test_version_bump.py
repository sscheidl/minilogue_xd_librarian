import unittest

from tools.bump_build_version import bump_version_text


class VersionBumpTest(unittest.TestCase):
    def test_bump_version_text_increments_patch_component(self):
        updated, old_version, new_version = bump_version_text('APP_VERSION = "0.8.9"\n')

        self.assertEqual(old_version, "0.8.9")
        self.assertEqual(new_version, "0.8.10")
        self.assertEqual(updated, 'APP_VERSION = "0.8.10"\n')


if __name__ == "__main__":
    unittest.main()

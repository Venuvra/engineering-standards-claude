import unittest

import vstd


class SmokeTest(unittest.TestCase):
    def test_version_is_pep440_like(self):
        self.assertRegex(vstd.__version__, r"^\d+\.\d+\.\d+(\.dev\d+)?$")


if __name__ == "__main__":
    unittest.main()

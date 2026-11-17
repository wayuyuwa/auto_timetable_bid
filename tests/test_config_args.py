"""Chromium arguments must start with "--" (without it Chromium reads them as a page to open).

    venv\\Scripts\\python -m unittest tests/test_config_args.py
"""

import unittest

from src.utils import config


class ChromiumArgsTests(unittest.TestCase):
    def test_built_in_default_options_have_dashes(self):
        options = config.create_default_config()["Playwright"]["options"].split(",")
        self.assertTrue(options and all(o.startswith("--") for o in options), options)

    def test_launch_arguments_all_have_dashes(self):
        self.assertTrue(config.PLAYWRIGHT_ARGS)
        self.assertTrue(all(a.startswith("--") for a in config.PLAYWRIGHT_ARGS), config.PLAYWRIGHT_ARGS)

    def test_config_ini_is_found_in_the_bundle_folder(self):
        import os
        import sys
        from unittest import mock

        folder = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with mock.patch.object(sys, "_MEIPASS", folder, create=True), \
                mock.patch.object(os, "getcwd", return_value=os.path.join(folder, "nowhere")), \
                mock.patch.object(sys, "executable", os.path.join(folder, "nowhere", "x.exe")), \
                mock.patch.object(config, "__file__", os.path.join(folder, "nowhere", "a", "b", "c.py")):
            loaded = config.load_config()
        self.assertEqual(loaded["Playwright"]["wait_time_long"], "3")


if __name__ == "__main__":
    unittest.main()

# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class DistributionScriptTests(unittest.TestCase):
    def test_explicit_dist_directory_does_not_fall_back_to_checkout_artifacts(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    str(root / "scripts" / "check_distribution.py"),
                    "--dist-dir",
                    directory,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn(
            f"Expected exactly one *.whl in {directory}, found 0", result.stderr
        )
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()

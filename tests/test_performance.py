# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

import subprocess
import sys
import unittest
from pathlib import Path


class PerformanceHarnessTests(unittest.TestCase):
    def run_benchmark(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "scripts.benchmark_scan", *args],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
        )

    def test_small_workload_is_reproducible_and_checks_all_formats(self):
        first = self.run_benchmark("--files", "1", "--cells", "2")
        second = self.run_benchmark("--files", "1", "--cells", "2")
        for result in (first, second):
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Files: 3", result.stdout)
            self.assertIn("Findings per scan: 18", result.stdout)
            self.assertIn("Samples: 5", result.stdout)
        def hashes(text):
            return [line for line in text.splitlines() if "SHA-256:" in line]
        self.assertEqual(hashes(first.stdout), hashes(second.stdout))
        for flag in ("--files", "--cells", "--samples"):
            self.assertEqual(self.run_benchmark(flag, "0").returncode, 2)

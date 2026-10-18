# Copyright 2026 Kyle Bush
# SPDX-License-Identifier: Apache-2.0

import re
import subprocess
import sys
import unittest
from pathlib import Path


class DocumentationTests(unittest.TestCase):
    def test_generated_catalog_matches_metadata_and_has_curated_guides(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, "-m", "scripts.generate_rule_docs", "--check"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_user_documentation_relative_file_links_resolve(self):
        root = Path(__file__).resolve().parents[1]
        pages = [root / "README.md", root / "CONTRIBUTING.md"]
        pages.extend((root / "docs").rglob("*.md"))
        pages.extend((root / "benchmarks").rglob("*.md"))
        for page in pages:
            for target in re.findall(
                r"\]\(([^\s)]+)\)", page.read_text(encoding="utf-8")
            ):
                if ":" in target or target.startswith("#"):
                    continue
                with self.subTest(page=page.relative_to(root), target=target):
                    self.assertTrue((page.parent / target.split("#", 1)[0]).is_file())


if __name__ == "__main__":
    unittest.main()

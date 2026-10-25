"""Drafting check commands from a repository's own files (vstd rollout's project section)."""

import json
import tempfile
import unittest
from pathlib import Path

from vstd.commands import detect_commands, project_section


class DetectCommandsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)

    def write(self, rel, text):
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def test_npm_scripts_in_check_order_and_dev_scripts_left_out(self):
        self.write("package.json", json.dumps({"scripts": {"build": "x", "dev": "x", "test": "x", "lint": "x"}}))
        self.assertEqual(detect_commands(self.repo), [("package.json", ["npm run lint", "npm test", "npm run build"])])

    def test_lockfile_picks_the_package_manager_in_subfolders(self):
        self.write("web/package.json", json.dumps({"scripts": {"typecheck": "tsc"}}))
        self.write("web/pnpm-lock.yaml", "")
        self.assertEqual(detect_commands(self.repo), [("web/package.json", ["pnpm typecheck"])])
        self.assertIn("From `web/package.json` (run in `web/`):", project_section(detect_commands(self.repo)))

    def test_makefile_targets_and_pyproject_tools(self):
        self.write("Makefile", "VAR := 1\nlint:\n\truff check .\ntest: lint\n\tpytest\nrelease:\n\ttrue\n")
        self.write("pyproject.toml", "[tool.ruff]\nline-length = 100\n[tool.pytest.ini_options]\naddopts = '-q'\n")
        self.assertEqual(detect_commands(self.repo), [
            ("Makefile", ["make lint", "make test"]),
            ("pyproject.toml", ["ruff format --check .", "ruff check .", "pytest"]),
        ])

    def test_ci_run_lines_skip_blocks_expressions_and_the_standards_workflow(self):
        self.write(".github/workflows/ci.yml",
                   "steps:\n  - run: npm ci\n  - run: |\n      multi\n  - run: echo ${{ secrets.X }}\n  - name: t\n    run: 'npm test'\n  - run: npm ci\n")
        self.write(".github/workflows/standards.yml", "steps:\n  - run: python3 -I .vstd/vstd/main.py check --repo .\n")
        self.assertEqual(detect_commands(self.repo), [("CI workflows", ["npm ci", "npm test"])])

    def test_broken_files_contribute_nothing(self):
        self.write("package.json", "{not json")
        self.write("pyproject.toml", "[tool\n")
        self.assertEqual(detect_commands(self.repo), [])

    def test_nothing_found_says_so(self):
        text = project_section([])
        self.assertIn("No build or test commands were found", text)
        self.assertIn("Drafted by `vstd rollout`", text)


if __name__ == "__main__":
    unittest.main()

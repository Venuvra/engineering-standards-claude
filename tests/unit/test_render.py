"""Renderer tests (AC-02, AC-03, AC-04, AC-07).

Golden files live in tests/golden/. To update them after an intended change,
run with VSTD_UPDATE_GOLDEN=1 and review the diff in the PR.
"""

import datetime as dt
import os
import unittest
from pathlib import Path

from vstd.config import Config, Override
from vstd.markers import MarkerError, find_block
from vstd.render import CLAUDE_MD, render_block, render_new_agents_md
from vstd.rules import load_rules

ROOT = Path(__file__).resolve().parents[2]
RULES = load_rules(ROOT / "rules")
GOLDEN = ROOT / "tests" / "golden"
SHA = "0" * 40

OVERRIDE = Override(
    rule="TS-001", scope="legacy/**", replacement="strict is off under legacy/ until the migration lands",
    reason="Pre-TypeScript code", approved_by="kurtrusselsilla", approved_on=dt.date(2026, 10, 30),
    expires=dt.date(2027, 3, 31),
)

FIXTURES = {
    "empty": Config(version="0.1.0", commit=SHA, stacks=()),
    "typescript": Config(version="0.1.0", commit=SHA, stacks=("typescript",)),
    "python": Config(version="0.1.0", commit=SHA, stacks=("python",)),
    "multi-stack-overrides": Config(version="0.1.0", commit=SHA, stacks=("typescript", "python"), overrides=(OVERRIDE,)),
}


class GoldenTest(unittest.TestCase):
    def test_golden_files(self):
        update = os.environ.get("VSTD_UPDATE_GOLDEN") == "1"
        for name, cfg in FIXTURES.items():
            with self.subTest(fixture=name):
                path = GOLDEN / f"{name}.AGENTS.md"
                actual = render_new_agents_md(RULES, cfg)
                if update:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(actual, encoding="utf-8", newline="\n")
                self.assertEqual(path.read_text(encoding="utf-8"), actual)

    def test_claude_md_golden(self):
        path = GOLDEN / "CLAUDE.md"
        if os.environ.get("VSTD_UPDATE_GOLDEN") == "1":
            path.write_text(CLAUDE_MD, encoding="utf-8", newline="\n")
        self.assertEqual(path.read_text(encoding="utf-8"), CLAUDE_MD)


class RenderPropertiesTest(unittest.TestCase):
    def test_deterministic(self):
        cfg = FIXTURES["multi-stack-overrides"]
        self.assertEqual(render_block(RULES, cfg).encode(), render_block(RULES, cfg).encode())

    def test_stack_order_does_not_matter(self):
        a = Config(version="0.1.0", commit=SHA, stacks=("typescript", "python"))
        b = Config(version="0.1.0", commit=SHA, stacks=("python", "typescript"))
        self.assertEqual(render_block(RULES, a), render_block(RULES, b))

    def test_lf_only_and_trailing_newline(self):
        out = render_new_agents_md(RULES, FIXTURES["typescript"])
        self.assertNotIn("\r", out)
        self.assertTrue(out.endswith("\n") and not out.endswith("\n\n"))

    def test_hash_stamp_verifies(self):
        block = find_block(render_block(RULES, FIXTURES["multi-stack-overrides"]))
        self.assertTrue(block.intact)
        self.assertEqual(block.version, "0.1.0")

    def test_claude_md_imports_agents_first(self):
        self.assertEqual(CLAUDE_MD.splitlines()[0], "@AGENTS.md")
        self.assertEqual(sum(l.strip().startswith("@") for l in CLAUDE_MD.splitlines()), 1)

    def test_agents_md_imports_nothing(self):
        out = render_new_agents_md(RULES, FIXTURES["multi-stack-overrides"])
        self.assertFalse(any(l.startswith("@") for l in out.splitlines()))

    def test_stack_isolation(self):
        ts = render_block(RULES, FIXTURES["typescript"])
        self.assertIn("[TS-001 ", ts)
        self.assertNotIn("[PY-", ts)
        core = render_block(RULES, FIXTURES["empty"])
        self.assertNotIn("[TS-", core)
        self.assertNotIn("[PY-", core)
        self.assertIn("[SEC-001 MUST]", core)

    def test_override_rendered_in_block(self):
        block = render_block(RULES, FIXTURES["multi-stack-overrides"])
        self.assertIn("- TS-001 (SHOULD) in `legacy/**`: strict is off", block)
        self.assertIn("Approved by @kurtrusselsilla on 2026-10-30, expires 2027-03-31.", block)
        self.assertIn("None.", render_block(RULES, FIXTURES["typescript"]))

    def test_block_within_budget(self):
        block = render_block(RULES, FIXTURES["multi-stack-overrides"])
        self.assertLessEqual(len(block.encode()), 16 * 1024)


class MarkerTest(unittest.TestCase):
    def test_absent(self):
        self.assertIsNone(find_block("# Project\n"))

    def test_tampered_body_not_intact(self):
        text = render_block(RULES, FIXTURES["typescript"]).replace("MUST] Never commit", "MUST] Maybe commit")
        self.assertFalse(find_block(text).intact)

    def test_duplicate_markers(self):
        block = render_block(RULES, FIXTURES["typescript"])
        with self.assertRaises(MarkerError):
            find_block(block + block)

    def test_missing_end(self):
        block = render_block(RULES, FIXTURES["typescript"]).replace("<!-- END venuvra-standards -->\n", "")
        with self.assertRaises(MarkerError):
            find_block(block)

    def test_malformed_begin(self):
        with self.assertRaises(MarkerError):
            find_block("<!-- BEGIN venuvra-standards vX -->\nbody\n<!-- END venuvra-standards -->\n")


if __name__ == "__main__":
    unittest.main()

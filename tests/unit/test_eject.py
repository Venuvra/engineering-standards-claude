"""vstd eject: round trip from init, content kept, check then reports 'not managed'."""

import tempfile
import unittest
from pathlib import Path

from vstd.check import check
from vstd.eject import eject
from vstd.init import WORKFLOW_PATH, init
from vstd.rules import load_rules

ROOT = Path(__file__).resolve().parents[2]
RULES = load_rules(ROOT / "rules")


class EjectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        (self.repo / "AGENTS.md").write_text("# Project notes\n\nRun make test.\n")
        init(self.repo, RULES, version="0.1.0", commit="a" * 40, standards_root=ROOT, stacks=("typescript",))
        self.before = (self.repo / "AGENTS.md").read_text()

    def test_round_trip_keeps_content_and_removes_markers(self):
        result = eject(self.repo)
        agents = (self.repo / "AGENTS.md").read_text()
        self.assertNotIn("<!-- BEGIN venuvra-standards", agents)
        self.assertNotIn("<!-- END venuvra-standards", agents)
        for line in self.before.splitlines():
            if "venuvra-standards" not in line:
                self.assertIn(line, agents)
        self.assertIn("TS-001", agents)
        self.assertTrue(agents.endswith("# Project notes\n\nRun make test.\n"))
        self.assertEqual(sorted(result.removed), sorted([".venuvra/standards.toml", WORKFLOW_PATH]))
        self.assertFalse((self.repo / ".venuvra").exists())
        self.assertTrue((self.repo / "CLAUDE.md").read_text().startswith("@AGENTS.md\n"))

    def test_check_reports_not_managed_after_eject(self):
        eject(self.repo)
        report = check(self.repo, RULES, "0.1.0")
        self.assertFalse(report.ok)
        self.assertTrue(any("not managed" in f.problem for f in report.errors), report.format())

    def test_foreign_workflow_is_kept(self):
        (self.repo / WORKFLOW_PATH).write_text("name: ours\n")
        result = eject(self.repo)
        self.assertEqual(result.kept, [WORKFLOW_PATH])
        self.assertTrue((self.repo / WORKFLOW_PATH).exists())

    def test_eject_twice_is_a_no_op(self):
        eject(self.repo)
        snapshot = (self.repo / "AGENTS.md").read_text()
        result = eject(self.repo)
        self.assertEqual((result.written, result.removed), ([], []))
        self.assertEqual((self.repo / "AGENTS.md").read_text(), snapshot)


if __name__ == "__main__":
    unittest.main()

"""The CI template (TST-007..009): runner dropdown, forks kept off self-hosted runners."""

import re
import unittest
from pathlib import Path

from vstd.lint import lint_paths

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "templates" / "ci" / "ci.yml"
WORKFLOW = PATH.read_text(encoding="utf-8")


class CiTemplateTest(unittest.TestCase):
    def test_passes_workflow_lint(self):
        self.assertEqual(lint_paths([PATH]), [])

    def test_runner_is_a_dropdown(self):
        self.assertRegex(WORKFLOW, r"\n      runner:\n(?:        .*\n)*?        type: choice\n")
        for option in ("default", "local", "oci", "github"):
            self.assertIn(f"          - {option}\n", WORKFLOW)

    def test_forks_never_reach_self_hosted_runners(self):
        runs_on = re.search(r"^    runs-on: (.*)$", WORKFLOW, re.M).group(1)
        self.assertIn("github.event.pull_request.head.repo.full_name == github.repository", runs_on)
        self.assertTrue(runs_on.endswith("|| 'ubuntu-24.04' }}"), "falls back to GitHub-hosted")
        self.assertNotRegex(WORKFLOW, r"\n    if:", "a job-level if would skip CI for forks")

    def test_service_port_is_not_fixed(self):
        self.assertIn('ports: ["5432"]', WORKFLOW)
        self.assertNotRegex(WORKFLOW, r"ports: \[.?\d+:\d+")

    def test_only_pull_requests_cancel(self):
        self.assertIn("cancel-in-progress: ${{ github.event_name == 'pull_request' }}", WORKFLOW)

    def test_read_only_token(self):
        self.assertIn("permissions:\n  contents: read\n", WORKFLOW)
        self.assertNotIn("write", WORKFLOW)


if __name__ == "__main__":
    unittest.main()

"""The rollout workflow: started by hand, dry run by default, never merges, checks its inputs."""

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from vstd.lint import lint_paths

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / ".github" / "workflows" / "rollout.yml"
WORKFLOW = PATH.read_text(encoding="utf-8")
# The Python heredoc of the "Check the inputs" step, with its YAML indentation removed.
PLAN = "\n".join(line[10:] for line in re.search(r"<<'EOF'\n(.*?)\n\s*EOF\n", WORKFLOW, re.S).group(1).splitlines())


def plan(repos: str, release: str = "v0.7.1", skip: str = "") -> tuple[int, str, dict[str, str]]:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        out.touch()
        env = {"PATH": os.environ.get("PATH", ""), "RELEASE": release, "REPOS": repos, "SKIP": skip,
               "OWNER": "Acme", "GITHUB_OUTPUT": str(out)}
        proc = subprocess.run([sys.executable, "-I", "-c", PLAN], env=env, capture_output=True, text=True, timeout=30)
        outputs = dict(line.split("=", 1) for line in out.read_text(encoding="utf-8").splitlines())
    return proc.returncode, proc.stdout, outputs


class RolloutWorkflowTest(unittest.TestCase):
    def test_passes_workflow_lint(self):
        self.assertEqual(lint_paths([PATH]), [])

    def test_started_by_hand_only(self):
        triggers = re.search(r"^on:\n((?:  .*\n)+)", WORKFLOW, re.M).group(1)
        self.assertEqual(re.findall(r"^  (\w+):", triggers, re.M), ["workflow_dispatch"])

    def test_options_are_dropdowns_and_default_to_doing_least(self):
        self.assertRegex(WORKFLOW, r"\n      mode:\n(?:        .*\n)*?        type: choice\n(?:        .*\n|          .*\n)*?        default: dry-run\n")
        self.assertRegex(WORKFLOW, r"\n      actions_pr_setting:\n(?:        .*\n)*?        type: choice\n(?:        .*\n|          .*\n)*?        default: \"no\"\n")
        self.assertNotIn("type: boolean", WORKFLOW)

    def test_never_merges_and_stays_on_github_hosted(self):
        code = "\n".join(l for l in WORKFLOW.splitlines() if not l.lstrip().startswith("#"))
        self.assertNotRegex(code, r"\bmerge\b|auto-merge|--admin")
        self.assertIn("runs-on: ubuntu-24.04\n", WORKFLOW)
        self.assertNotIn("venuvra-", WORKFLOW)

    def test_own_token_is_read_only_and_secrets_sit_in_an_environment(self):
        self.assertIn("permissions:\n  contents: read\n", WORKFLOW)
        self.assertIn("    environment: rollout\n", WORKFLOW)

    def test_runs_the_checked_release_tag(self):
        # The tag is checked against the published releases before checkout, never used raw.
        self.assertIn("ref: refs/tags/${{ steps.release.outputs.tag }}", WORKFLOW)
        self.assertNotIn("refs/tags/${{ inputs.release }}", WORKFLOW)
        self.assertLess(WORKFLOW.index("name: Find the release"), WORKFLOW.index("uses: actions/checkout@"))

    def test_every_input_is_a_dropdown(self):
        inputs = WORKFLOW[WORKFLOW.index("    inputs:\n"):WORKFLOW.index("\npermissions:")]
        names = re.findall(r"^      (\w+):\n", inputs, re.M)
        self.assertEqual(names, ["release", "mode", "actions_pr_setting"])
        self.assertEqual(inputs.count("type: choice"), len(names))
        self.assertNotIn("type: string", inputs)

    def test_release_dropdown_offers_latest_and_the_newest_release(self):
        # A release PR adds "## vX.Y.Z" to the changelog; this fails until the dropdown lists it too.
        block = re.search(r"\n      release:\n(?:        .*\n)*?        options:\n((?:          - .*\n)+)        default: latest\n", WORKFLOW)
        self.assertIsNotNone(block)
        options = re.findall(r"- (\S+)", block.group(1))
        self.assertEqual(options[0], "latest")
        for tag in options[1:]:
            self.assertRegex(tag, r"^v\d+\.\d+\.\d+$")
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        newest = re.search(r"^## (v\d+\.\d+\.\d+)$", changelog, re.M).group(1)
        self.assertEqual(options[1], newest, "add the new release to the rollout dropdown, newest first")

    def test_repositories_come_from_the_environment_variable(self):
        self.assertIn("REPOS: ${{ vars.ROLLOUT_REPOS }}", WORKFLOW)
        self.assertNotIn("inputs.repos", WORKFLOW)

    def test_plan_accepts_latest(self):
        code, out, outputs = plan("one", release="latest")
        self.assertEqual(code, 0, out)
        self.assertEqual(outputs["repos"], "Acme/one")

    def test_plan_accepts_names_and_drops_duplicates(self):
        code, out, outputs = plan("Acme/one, two\nacme/ONE  three")
        self.assertEqual(code, 0, out)
        self.assertEqual(outputs, {"repos": "Acme/one,Acme/two,Acme/three", "names": "one,two,three"})

    def test_plan_skips_listed_repositories(self):
        code, out, outputs = plan("one,two", skip="Acme/two")
        self.assertEqual(code, 0, out)
        self.assertEqual(outputs["repos"], "Acme/one")
        self.assertIn("SKIPPED  Acme/two", out)

    def test_plan_refuses_bad_input(self):
        for repos, release, fragment in [
            ("one", "0.7.1", "vMAJOR.MINOR.PATCH"),
            ("one", "v0.7", "vMAJOR.MINOR.PATCH"),
            ("one", "newest", "vMAJOR.MINOR.PATCH"),
            ("Other/one", "v0.7.1", "outside Acme"),
            ("one;rm", "v0.7.1", "not a repository name"),
            ("", "v0.7.1", "ROLLOUT_REPOS variable"),
            (" , ", "v0.7.1", "ROLLOUT_REPOS variable"),
        ]:
            with self.subTest(repos=repos, release=release):
                code, out, outputs = plan(repos, release)
                self.assertEqual(code, 1)
                self.assertIn(fragment, out)
                self.assertEqual(outputs, {})

    def test_plan_fails_when_everything_is_skipped(self):
        code, out, _ = plan("one", skip="one")
        self.assertEqual(code, 1)
        self.assertIn("no repositories left", out)


if __name__ == "__main__":
    unittest.main()

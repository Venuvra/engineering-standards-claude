"""The delivery templates (DLV-001..008): one script does the work, pipelines only call it."""

import re
import unittest
from pathlib import Path

from vstd.lint import lint_paths

ROOT = Path(__file__).resolve().parents[2]
DIR = ROOT / "templates" / "delivery"
WORKFLOW = (DIR / "deploy.yml").read_text(encoding="utf-8")
JENKINSFILE = (DIR / "Jenkinsfile").read_text(encoding="utf-8")
SCRIPT = (DIR / "deploy.ps1").read_text(encoding="utf-8")


def switch_branch(name: str) -> str:
    m = re.search(rf"^    '{re.escape(name)}' \{{\n(.*?)^    \}}", SCRIPT, re.M | re.S)
    assert m, f"deploy.ps1 has no '{name}' branch"
    return m.group(1)


class WorkflowTest(unittest.TestCase):
    def test_passes_workflow_lint(self):
        self.assertEqual(lint_paths([DIR / "deploy.yml"]), [])

    def test_manual_only(self):
        on = WORKFLOW[WORKFLOW.index("\non:"):WORKFLOW.index("\npermissions:")]
        self.assertNotRegex(on, r"\n  (push|pull_request|schedule)\b", "DLV-003: never on push or schedule")

    def test_target_and_action_are_dropdowns(self):
        for name in ("target", "action"):
            self.assertRegex(WORKFLOW, rf"\n      {name}:\n(?:        .*\n)*?        type: choice\n", name)

    def test_every_run_step_calls_the_script(self):
        runs = re.findall(r"^        run: (.*)$", WORKFLOW, re.M)
        self.assertTrue(runs)
        for run in runs:
            self.assertTrue(run.startswith("./scripts/deploy.ps1 "), run)

    def test_apply_uses_the_saved_plan(self):
        self.assertIn("name: tfplan", WORKFLOW[WORKFLOW.index("upload-artifact"):])
        self.assertIn("name: tfplan", WORKFLOW[WORKFLOW.index("download-artifact"):])


class JenkinsfileTest(unittest.TestCase):
    def test_parameters_are_choices(self):
        self.assertIn("choice(name: 'TARGET'", JENKINSFILE)
        self.assertIn("choice(name: 'ACTION'", JENKINSFILE)

    def test_shell_steps_call_the_script_without_interpolation(self):
        steps = re.findall(r"^\s*sh (.*)$", JENKINSFILE, re.M)
        self.assertEqual(len(steps), 2)
        for step in steps:
            # Single quotes: Groovy never splices a parameter into the command text.
            self.assertRegex(step, r"^'pwsh -NoProfile -File scripts/deploy\.ps1 [^']*'$")

    def test_approval_before_cloud_or_destroy(self):
        self.assertLess(JENKINSFILE.index("stage('Approve')"), JENKINSFILE.index("stage('Run')"))
        self.assertIn("params.TARGET == 'cloud' || params.ACTION == 'destroy'", JENKINSFILE)


class ScriptTest(unittest.TestCase):
    def test_destroy_and_cloud_deploy_need_confirmation(self):
        self.assertIn('Assert-Confirmed "destroy $App"', switch_branch("local/destroy"))
        self.assertIn('Assert-Confirmed "destroy $App"', switch_branch("cloud/destroy"))
        self.assertIn('Assert-Confirmed "deploy $App"', switch_branch("cloud/deploy"))

    def test_cloud_deploy_applies_only_a_saved_plan(self):
        body = switch_branch("cloud/deploy")
        self.assertIn("No saved plan", body)
        self.assertIn("'apply', '-input=false', $planFile", body)

    def test_local_destroy_keeps_volumes_unless_purge(self):
        self.assertIn("if ($Purge) { $down += '--volumes' }", switch_branch("local/destroy"))

    def test_tools_get_argument_arrays(self):
        self.assertNotIn("Invoke-Expression", SCRIPT)
        self.assertNotRegex(SCRIPT, r"\biex\b")


if __name__ == "__main__":
    unittest.main()

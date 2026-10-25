"""The workflow template's manual-run form: every option is a dropdown, and the default changes nothing."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = (ROOT / "templates" / "standards.yml").read_text(encoding="utf-8")


def dispatch_inputs(text: str) -> dict[str, dict[str, str]]:
    """Each workflow_dispatch input's scalar fields (type, default, description)."""
    block = re.search(r"^  workflow_dispatch:\n    inputs:\n((?:      .*\n|\n)*)", text, re.M)
    inputs: dict[str, dict[str, str]] = {}
    name = None
    for line in (block.group(1) if block else "").splitlines():
        if m := re.match(r"^      ([a-z_-]+):\s*$", line):
            name = m.group(1)
            inputs[name] = {}
        elif name and (m := re.match(r"^        ([a-z_]+):\s*(\S.*)$", line)):
            inputs[name][m.group(1)] = m.group(2)
    return inputs


class DispatchFormTest(unittest.TestCase):
    def test_every_input_is_a_dropdown(self):
        inputs = dispatch_inputs(TEMPLATE)
        self.assertTrue(inputs, "template has no workflow_dispatch inputs")
        for name, fields in inputs.items():
            self.assertEqual(fields.get("type"), "choice", f"input {name} must be a dropdown")

    def test_mode_defaults_to_diff_only(self):
        mode = dispatch_inputs(TEMPLATE)["mode"]
        self.assertEqual(mode["default"], "diff-only")
        self.assertIn("inputs.mode != 'open-pr'", TEMPLATE, "anything but open-pr must stay a dry run")


class PushSyncTest(unittest.TestCase):
    def test_sync_runs_on_push_only_when_the_config_changed(self):
        sync = TEMPLATE[TEMPLATE.index("  sync:"):]
        self.assertIn("github.event_name == 'push'", sync.split("runs-on:")[0])
        self.assertIn("git diff --name-only HEAD^ HEAD -- .venuvra/standards.toml", sync)
        self.assertIn("fetch-depth: 2", sync)
        # Every step after the gate is skipped when the push didn't touch the config.
        after_gate = sync[sync.index("id: gate"):].split("\n      - ")[1:]
        self.assertEqual(len(after_gate), 3)
        for step in after_gate:
            self.assertIn("if: steps.gate.outputs.run == 'true'", step)


if __name__ == "__main__":
    unittest.main()

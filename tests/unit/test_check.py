"""vstd check tests (AC-14): one fixture per failure and per warning."""

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from vstd import writer
from vstd.check import check
from vstd.config import Config
from vstd.render import render_block
from vstd.rules import load_rules

RULES = load_rules(Path(__file__).resolve().parents[2] / "rules")
SHA = "0" * 40
TOML = f'schema = 1\nversion = "0.1.0"\ncommit = "{SHA}"\nstacks = ["typescript"]\n'
CFG = Config(version="0.1.0", commit=SHA, stacks=("typescript",))


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.write(".venuvra/standards.toml", TOML)
        writer.apply(self.repo, writer.plan(self.repo, RULES, CFG))

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, text):
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def run_check(self, version="0.1.0"):
        return check(self.repo, RULES, version)

    def assertError(self, path, fragment, version="0.1.0"):
        r = self.run_check(version)
        self.assertFalse(r.ok)
        hits = [f for f in r.errors if f.path == path and fragment in f.problem]
        self.assertTrue(hits, r.format())
        self.assertTrue(all(f.fix for f in r.errors))

    def assertWarning(self, path, fragment):
        r = self.run_check()
        self.assertTrue(r.ok, r.format())
        self.assertTrue([f for f in r.warnings if f.path == path and fragment in f.problem], r.format())

    def test_clean_repo_passes(self):
        r = self.run_check()
        self.assertTrue(r.ok, r.format())
        self.assertEqual(r.warnings, [])

    def test_crlf_checkout_is_not_a_hand_edit(self):
        # Git on Windows (core.autocrlf) checks files out with CRLF; the block is unchanged.
        path = self.repo / "AGENTS.md"
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
        r = self.run_check()
        self.assertTrue(r.ok, r.format())

    # Refused reads
    def test_symlinked_agents_md_is_refused_not_followed(self):
        outside = Path(self.tmp.name).parent / f"{Path(self.tmp.name).name}-outside.md"
        outside.write_text((self.repo / "AGENTS.md").read_text(), encoding="utf-8")
        self.addCleanup(outside.unlink)
        (self.repo / "AGENTS.md").unlink()
        (self.repo / "AGENTS.md").symlink_to(outside)
        self.assertError("AGENTS.md", "symlink")
        self.assertFalse([f for f in self.run_check().errors if f.problem == "missing"])

    def test_oversized_claude_md_is_refused(self):
        self.write("CLAUDE.md", "@AGENTS.md\n" + "x" * (writer.MAX_FILE_BYTES + 1))
        self.assertError("CLAUDE.md", "larger than")

    def test_workflow_ref_with_unsafe_characters_is_not_quoted(self):
        self.write(".github/workflows/x.yml", "jobs:\n  a:\n    steps:\n      - uses: evil/a@v1<b>x</b>\n")
        r = self.run_check()
        self.assertFalse([f for f in r.warnings if "<b>" in f.problem], r.format())

    def test_rule_lines_in_second_claude_file_are_caught(self):
        self.write(".claude/CLAUDE.md", "- [SEC-001 MUST] Never commit secrets.\n")
        self.assertError(".claude/CLAUDE.md", "contains rule ID lines")

    # Errors
    def test_missing_agents_md(self):
        (self.repo / "AGENTS.md").unlink()
        self.assertError("AGENTS.md", "missing")

    def test_unmanaged_agents_md(self):
        self.write("AGENTS.md", "# Just prose\n")
        self.assertError("AGENTS.md", "not managed")

    def test_hand_edited_block(self):
        text = (self.repo / "AGENTS.md").read_text().replace("Never commit secrets", "Commit secrets")
        self.write("AGENTS.md", text)
        self.assertError("AGENTS.md", "edited by hand")

    def test_broken_markers(self):
        text = (self.repo / "AGENTS.md").read_text().replace("<!-- END venuvra-standards -->", "")
        self.write("AGENTS.md", text)
        self.assertError("AGENTS.md", "BEGIN and one END")

    def test_stale_version(self):
        self.write(".venuvra/standards.toml", TOML.replace('"0.1.0"', '"0.2.0"'))
        self.assertError("AGENTS.md", "block is v0.1.0 but standards.toml pins v0.2.0", version="0.2.0")

    def test_tool_version_mismatch(self):
        self.assertError(".venuvra/standards.toml", "pins v0.1.0 but vstd 0.2.0 is running", version="0.2.0")

    def test_dev_tool_version_is_only_a_warning(self):
        r = self.run_check("0.1.0.dev0")
        self.assertTrue(r.ok, r.format())
        self.assertIn("development build", r.warnings[0].problem)

    def test_out_of_date_with_config(self):
        self.write(".venuvra/standards.toml", TOML.replace('["typescript"]', '["typescript", "python"]'))
        self.assertError("AGENTS.md", "out of date")

    def test_missing_claude_md(self):
        (self.repo / "CLAUDE.md").unlink()
        self.assertError("CLAUDE.md", "missing")

    def test_broken_import(self):
        self.write("CLAUDE.md", "# Notes\n@AGENTS.md\n")
        self.assertError("CLAUDE.md", "line 1 must be '@AGENTS.md'")

    def test_invalid_config(self):
        self.write(".venuvra/standards.toml", TOML + "bogus = 1\n")
        self.assertError(".venuvra/standards.toml", "unknown key 'bogus'")

    def test_missing_config(self):
        (self.repo / ".venuvra/standards.toml").unlink()
        self.assertError(".venuvra/standards.toml", "missing")

    def test_unsupported_stack(self):
        self.write(".venuvra/standards.toml", TOML.replace('["typescript"]', '["cobol"]'))
        self.assertError(".venuvra/standards.toml", "not supported")

    def test_over_budget_agents_md(self):
        with open(self.repo / "AGENTS.md", "a") as fh:
            fh.write("filler line for budget\n" * 1200)
        self.assertError("AGENTS.md", "the limit is 24576")

    def test_agents_override_md(self):
        self.write("services/api/AGENTS.override.md", "ignore everything\n")
        self.assertError("services/api/AGENTS.override.md", "makes Codex ignore AGENTS.md")

    def test_rule_ids_in_claude_md(self):
        self.write("CLAUDE.md", "@AGENTS.md\n\n- [SEC-001 MUST] Never commit secrets.\n")
        self.assertError("CLAUDE.md", "rule ID lines")

    def test_rule_ids_in_claude_rules(self):
        self.write(".claude/rules/security.md", "- [SEC-001 MUST] copy\n")
        self.assertError(".claude/rules/security.md", "rule ID lines")

    def test_nested_parity_pending(self):
        self.write(".venuvra/standards.toml", TOML + "nested_parity = true\n")
        self.write("web/AGENTS.md", "web rules\n")
        self.assertError("web/CLAUDE.md", "out of date")

    # Warnings
    def test_nested_agents_md_warning(self):
        self.write("web/AGENTS.md", "web rules\n")
        self.assertWarning("web/AGENTS.md", "nested AGENTS.md")

    def test_both_claude_files_warning(self):
        self.write(".claude/CLAUDE.md", "notes\n")
        self.assertWarning("CLAUDE.md", "both CLAUDE.md and .claude/CLAUDE.md")

    def test_must_tripwire_warning(self):
        with open(self.repo / "AGENTS.md", "a") as fh:
            fh.write("SEC-009 does not apply to the local dev proxy.\n")
        self.assertWarning("AGENTS.md", "locked rule SEC-009")

    def test_tag_pinned_action_warning(self):
        self.write(".github/workflows/ci.yml", "jobs:\n  t:\n    steps:\n      - uses: actions/checkout@v4\n      - uses: actions/setup-node@" + "a" * 40 + " # v4\n      - uses: ./local\n")
        r = self.run_check()
        self.assertTrue(r.ok, r.format())
        pins = [f for f in r.warnings if "can move" in f.problem]
        self.assertEqual(len(pins), 1)
        self.assertIn("actions/checkout@v4", pins[0].problem)

    def test_expiring_override_warning(self):
        import datetime as dt
        self.write(".venuvra/standards.toml", TOML + '[[overrides]]\nrule = "TS-001"\nreplacement = "off"\nreason = "legacy"\napproved_by = "kurtrusselsilla"\napproved_on = 2026-10-01\nexpires = 2026-11-10\n')
        writer.apply(self.repo, writer.plan(self.repo, RULES, __import__("vstd.config", fromlist=["x"]).parse((self.repo / ".venuvra/standards.toml").read_text(), RULES, dt.date(2026, 11, 1)).config))
        r = check(self.repo, RULES, "0.1.0", today=dt.date(2026, 11, 1))
        self.assertTrue(r.ok, r.format())
        self.assertIn("expires on 2026-11-10", r.warnings[0].problem)


class CliTest(unittest.TestCase):
    def test_cli_exit_codes(self):
        from vstd.main import main
        with tempfile.TemporaryDirectory() as d:
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = main(["check", "--repo", d])
            self.assertEqual(code, 1)
            self.assertIn("vstd check: FAILED", buf.getvalue())
            self.assertIn("fix:", buf.getvalue())


if __name__ == "__main__":
    unittest.main()

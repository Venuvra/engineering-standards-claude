"""Safe writer tests (AC-05, AC-08) and refusal cases."""

import os
import tempfile
import unittest
from pathlib import Path

from vstd import writer
from vstd.config import Config
from vstd.render import CLAUDE_MD, render_block
from vstd.rules import load_rules

RULES = load_rules(Path(__file__).resolve().parents[2] / "rules")
V1 = Config(version="0.1.0", commit="0" * 40, stacks=("typescript",))
V2 = Config(version="0.2.0", commit="1" * 40, stacks=("typescript", "python"))


class _RepoCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, text):
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("utf-8"))

    def read(self, rel):
        return (self.repo / rel).read_bytes().decode("utf-8")

    def sync(self, cfg=V1):
        changes = writer.plan(self.repo, RULES, cfg)
        writer.apply(self.repo, changes)
        return changes


class WriterTest(_RepoCase):
    def test_empty_repo_gets_both_files(self):
        changes = self.sync()
        self.assertEqual(sorted(c.path for c in changes), ["AGENTS.md", "CLAUDE.md"])
        self.assertTrue(self.read("AGENTS.md").startswith("<!-- BEGIN venuvra-standards v0.1.0"))
        self.assertEqual(self.read("CLAUDE.md"), CLAUDE_MD)

    def test_second_run_changes_nothing(self):
        self.sync()
        self.assertEqual(writer.plan(self.repo, RULES, V1), [])

    def test_existing_agents_md_is_preserved_below_block(self):
        project = "# Backend rules\r\n\r\nRun `npm test`. Ünïcödé stays.\r\n"
        self.write("AGENTS.md", project)
        self.sync()
        text = self.read("AGENTS.md")
        self.assertTrue(text.endswith("\n" + project))
        self.assertTrue(text.startswith(render_block(RULES, V1)))

    def test_project_section_byte_identical_across_upgrade_and_rollback(self):
        project = "\n# Project instructions\r\n\nKeep CRLF\r\nand trailing spaces   \n"
        self.write("AGENTS.md", project)
        self.sync(V1)
        after_v1 = self.read("AGENTS.md")
        self.sync(V2)
        after_v2 = self.read("AGENTS.md")
        self.assertIn("[PY-001 ", after_v2)
        self.sync(V1)
        self.assertEqual(self.read("AGENTS.md"), after_v1)
        for text in (after_v1, after_v2):
            self.assertTrue(text.endswith(project))

    def test_text_above_block_is_preserved(self):
        self.write("AGENTS.md", "Intro kept above.\n\n" + render_block(RULES, V1) + "\nBelow.\n")
        self.sync(V2)
        text = self.read("AGENTS.md")
        self.assertTrue(text.startswith("Intro kept above.\n\n<!-- BEGIN venuvra-standards v0.2.0"))
        self.assertTrue(text.endswith("<!-- END venuvra-standards -->\n\nBelow.\n"))

    def test_existing_claude_md_keeps_content(self):
        self.write("CLAUDE.md", "# Working rules\n\nRead docs/architecture.md first.\n")
        self.sync()
        self.assertEqual(self.read("CLAUDE.md"), "@AGENTS.md\n\n# Working rules\n\nRead docs/architecture.md first.\n")

    def test_claude_md_with_import_untouched(self):
        self.write("CLAUDE.md", "@AGENTS.md\n\nMy notes.\n")
        changes = self.sync()
        self.assertNotIn("CLAUDE.md", [c.path for c in changes])

    def test_dot_claude_claude_md_used_when_root_absent(self):
        self.write(".claude/CLAUDE.md", "Notes.\n")
        self.sync()
        self.assertFalse((self.repo / "CLAUDE.md").exists())
        self.assertEqual(self.read(".claude/CLAUDE.md"), "@../AGENTS.md\n\nNotes.\n")

    def test_nested_parity(self):
        self.write("web/AGENTS.md", "<!-- BEGIN:nextjs-agent-rules -->\nx\n<!-- END:nextjs-agent-rules -->\n")
        self.write("node_modules/pkg/AGENTS.md", "ignored\n")
        cfg = Config(version="0.1.0", commit="0" * 40, stacks=("typescript",), nested_parity=True)
        changes = self.sync(cfg)
        self.assertIn("web/CLAUDE.md", [c.path for c in changes])
        self.assertEqual(self.read("web/CLAUDE.md"), "@AGENTS.md\n")
        self.assertFalse((self.repo / "node_modules/pkg/CLAUDE.md").exists())
        self.assertEqual(self.read("web/AGENTS.md").count("nextjs"), 2)

    def test_nested_parity_off_by_default(self):
        self.write("web/AGENTS.md", "x\n")
        self.sync()
        self.assertFalse((self.repo / "web/CLAUDE.md").exists())


class ReviewRegressionTest(_RepoCase):
    def test_apply_keeps_existing_file_mode(self):
        self.write("AGENTS.md", "# notes\n")
        os.chmod(self.repo / "AGENTS.md", 0o644)
        writer.apply(self.repo, writer.plan(self.repo, RULES, V1))
        self.assertEqual(os.stat(self.repo / "AGENTS.md").st_mode & 0o777, 0o644)

    def test_new_files_are_not_private(self):
        writer.apply(self.repo, writer.plan(self.repo, RULES, V1))
        mode = os.stat(self.repo / "CLAUDE.md").st_mode & 0o777
        self.assertEqual(mode, 0o666 & ~writer._umask())

    def test_symlinked_dot_claude_is_ignored_when_root_claude_exists(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        (Path(outside.name) / "CLAUDE.md").write_text("shared\n")
        (self.repo / ".claude").symlink_to(outside.name)
        self.write("CLAUDE.md", "notes\n")
        paths = [c.path for c in writer.plan(self.repo, RULES, V1)]
        self.assertIn("CLAUDE.md", paths)
        self.assertNotIn(".claude/CLAUDE.md", paths)


class RefusalTest(_RepoCase):
    def assertRefuses(self, fragment, cfg=V1):
        with self.assertRaises(writer.WriterError) as ctx:
            writer.plan(self.repo, RULES, cfg)
        self.assertIn(fragment, str(ctx.exception))

    def test_hand_edited_block(self):
        self.write("AGENTS.md", render_block(RULES, V1).replace("Never commit secrets", "Commit secrets"))
        self.assertRefuses("edited by hand")

    def test_missing_end_marker(self):
        self.write("AGENTS.md", render_block(RULES, V1).replace("<!-- END venuvra-standards -->\n", ""))
        self.assertRefuses("BEGIN and one END")

    def test_duplicate_markers(self):
        block = render_block(RULES, V1)
        self.write("AGENTS.md", block + block)
        self.assertRefuses("BEGIN and one END")

    def test_symlinked_agents_md(self):
        self.write("elsewhere.md", "x\n")
        (self.repo / "AGENTS.md").symlink_to(self.repo / "elsewhere.md")
        self.assertRefuses("symlink")

    def test_symlinked_parent_directory(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        (Path(outside.name) / "AGENTS.md").write_text("x\n")
        (self.repo / "web").symlink_to(outside.name)
        cfg = Config(version="0.1.0", commit="0" * 40, stacks=(), nested_parity=True)
        changes = writer.plan(self.repo, RULES, cfg)
        self.assertNotIn("web/CLAUDE.md", [c.path for c in changes])

    def test_oversized_file(self):
        self.write("AGENTS.md", "x" * (65 * 1024))
        self.assertRefuses("larger than")

    def test_path_traversal_rejected(self):
        with self.assertRaises(writer.WriterError):
            writer._safe_path(self.repo, "../AGENTS.md")

    def test_apply_refuses_if_file_changed_meanwhile(self):
        changes = writer.plan(self.repo, RULES, V1)
        self.write("AGENTS.md", "someone else wrote this\n")
        with self.assertRaises(writer.WriterError):
            writer.apply(self.repo, changes)
        self.assertEqual(self.read("AGENTS.md"), "someone else wrote this\n")


if __name__ == "__main__":
    unittest.main()

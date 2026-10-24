"""vstd init (AC-18): stack detection, init on empty and existing repos, no overwrite without --force."""

import tempfile
import unittest
from pathlib import Path

from vstd import config as config_mod
from vstd.check import check
from vstd.init import WORKFLOW_PATH, InitError, detect_stacks, init
from vstd.lint import lint_text
from vstd.rules import load_rules

ROOT = Path(__file__).resolve().parents[2]
RULES = load_rules(ROOT / "rules")
SHA = "a" * 40


class _Repo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)

    def write(self, rel, text=""):
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def init(self, **kw):
        args = dict(version="0.1.0", commit=SHA, standards_root=ROOT)
        args.update(kw)
        return init(self.repo, RULES, **args)


class DetectTest(_Repo):
    def test_each_manifest_type(self):
        for name, stack in (
            ("package.json", "typescript"), ("tsconfig.json", "typescript"), ("pnpm-lock.yaml", "typescript"),
            ("pyproject.toml", "python"), ("setup.py", "python"), ("setup.cfg", "python"), ("Pipfile", "python"),
            ("requirements.txt", "python"), ("requirements-dev.txt", "python"), ("uv.lock", "python"), ("poetry.lock", "python"),
        ):
            with self.subTest(name), tempfile.TemporaryDirectory() as d:
                (Path(d) / name).write_text("")
                self.assertEqual(detect_stacks(Path(d), RULES), (stack,))

    def test_one_level_down_and_skip_dirs(self):
        self.write("web/package.json")
        self.write("backend/pyproject.toml")
        self.write("node_modules/x/pyproject.toml")
        self.write("a/b/setup.py")
        self.assertEqual(detect_stacks(self.repo, RULES), ("python", "typescript"))

    def test_skipped_and_deep_manifests_are_ignored(self):
        self.write("node_modules/package.json")
        self.write("a/b/pyproject.toml")
        self.assertEqual(detect_stacks(self.repo, RULES), ())

    def test_empty_repo_has_no_stacks(self):
        self.assertEqual(detect_stacks(self.repo, RULES), ())


class InitTest(_Repo):
    def test_init_on_empty_repo(self):
        result = self.init()
        self.assertEqual(result.stacks, ())
        self.assertEqual(sorted(result.written), sorted([".venuvra/standards.toml", WORKFLOW_PATH, "AGENTS.md", "CLAUDE.md"]))
        cfg = config_mod.load(self.repo, RULES)
        self.assertTrue(cfg.ok, cfg.errors)
        self.assertEqual((cfg.config.version, cfg.config.commit, cfg.config.stacks), ("0.1.0", SHA, ()))
        report = check(self.repo, RULES, "0.1.0")
        self.assertTrue(report.ok, report.format())
        self.assertEqual(report.warnings, [])

    def test_workflow_passes_lint_and_uses_the_default_branch(self):
        self.init(default_branch="trunk")
        wf = (self.repo / WORKFLOW_PATH).read_text()
        self.assertIn('    branches: ["trunk"]\n', wf)
        self.assertEqual(lint_text(WORKFLOW_PATH, wf), [])

    def test_bad_branch_name_is_refused_before_writing(self):
        with self.assertRaises(InitError):
            self.init(default_branch="main]\n  evil: [x")
        self.assertEqual(list(self.repo.iterdir()), [])

    def test_init_on_existing_repo_keeps_content(self):
        self.write("package.json", "{}")
        self.write("AGENTS.md", "# Our notes\n\nRun pnpm test.\n")
        self.write("CLAUDE.md", "Use pnpm.\n")
        result = self.init()
        self.assertEqual(result.stacks, ("typescript",))
        agents = (self.repo / "AGENTS.md").read_text()
        self.assertIn("TS-001", agents)
        self.assertTrue(agents.endswith("# Our notes\n\nRun pnpm test.\n"))
        self.assertEqual((self.repo / "CLAUDE.md").read_text(), "@AGENTS.md\n\nUse pnpm.\n")
        self.assertTrue(check(self.repo, RULES, "0.1.0").ok)

    def test_existing_config_and_workflow_are_kept_without_force(self):
        self.write(".venuvra/standards.toml", f'schema = 1\nversion = "0.1.0"\ncommit = "{"b" * 40}"\nstacks = ["python"]\n')
        self.write(WORKFLOW_PATH, "name: ours\n")
        result = self.init(stacks=("typescript",))
        self.assertEqual(sorted(result.kept), sorted([".venuvra/standards.toml", WORKFLOW_PATH]))
        self.assertEqual((self.repo / WORKFLOW_PATH).read_text(), "name: ours\n")
        self.assertIn("PY-001", (self.repo / "AGENTS.md").read_text(), "renders from the kept config")

    def test_numeric_branch_name_stays_a_string(self):
        self.init(default_branch="123")
        self.assertIn('    branches: ["123"]\n', (self.repo / WORKFLOW_PATH).read_text())

    def test_kept_config_for_another_release_is_refused_before_writing(self):
        self.write(".venuvra/standards.toml", f'schema = 1\nversion = "0.2.0"\ncommit = "{"b" * 40}"\nstacks = []\n')
        with self.assertRaisesRegex(InitError, "pins v0.2.0 but this is v0.1.0"):
            self.init()
        self.assertFalse((self.repo / WORKFLOW_PATH).exists())
        self.assertFalse((self.repo / "AGENTS.md").exists())

    def test_force_replaces_config_and_workflow(self):
        self.write(".venuvra/standards.toml", "junk")
        self.write(WORKFLOW_PATH, "name: ours\n")
        result = self.init(force=True, stacks=("python",))
        self.assertIn(WORKFLOW_PATH, result.written)
        self.assertIn('stacks = ["python"]', (self.repo / ".venuvra/standards.toml").read_text())

    def test_explicit_stacks_and_unknown_stack(self):
        self.assertEqual(self.init(stacks=("typescript", "python")).stacks, ("python", "typescript"))
        with self.assertRaisesRegex(InitError, "unknown stack"):
            self.init(stacks=("cobol",), force=True)

    def test_invalid_commit_writes_nothing(self):
        with self.assertRaises(InitError):
            self.init(commit="not-a-sha")
        self.assertEqual(list(self.repo.iterdir()), [])

    def test_symlinked_workflow_dir_is_refused(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        (self.repo / ".github").mkdir()
        (self.repo / ".github" / "workflows").symlink_to(outside.name)
        from vstd.writer import WriterError
        with self.assertRaises(WriterError):
            self.init()
        self.assertEqual(list(Path(outside.name).iterdir()), [])


class CliTest(_Repo):
    def test_cli_refuses_a_development_build(self):
        import io
        from contextlib import redirect_stdout
        from vstd import __version__
        from vstd.main import main

        if ".dev" not in __version__:
            self.skipTest("only meaningful on a development build")
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(main(["init", "--repo", str(self.repo)]), 1)
        self.assertIn("development build", buf.getvalue())
        self.assertEqual(list(self.repo.iterdir()), [])


if __name__ == "__main__":
    unittest.main()

"""Workflow lint (AC-15): our workflows and template pass; each bad fixture fails for its reason."""

import unittest
from pathlib import Path

from vstd.lint import lint_paths, lint_text

ROOT = Path(__file__).resolve().parents[2]
BAD = ROOT / "tests" / "data" / "workflows_bad"
SHA = "3d3c42e5aac5ba805825da76410c181273ba90b1"
OK_HEAD = "on: pull_request\npermissions:\n  contents: read\njobs:\n  a:\n    runs-on: ubuntu-24.04\n    steps:\n"


class LintTest(unittest.TestCase):
    def test_shipped_workflows_and_template_pass(self):
        paths = [ROOT / ".github" / "workflows", ROOT / "templates" / "standards.yml"]
        self.assertEqual([str(e) for e in lint_paths(paths)], [])

    def test_each_bad_fixture_fails_for_its_reason(self):
        expected = {
            "pull_request_target.yml": "pull_request_target",
            "workflow_run.yml": "workflow_run",
            "missing_permissions.yml": "no top-level 'permissions:'",
            "tag_pinned.yml": "'actions/checkout@v7' is not pinned",
            "write_all.yml": "write-all",
            "expression_in_run.yml": "inside a run: script",
        }
        self.assertEqual(sorted(p.name for p in BAD.glob("*.yml")), sorted(expected))
        for name, fragment in expected.items():
            with self.subTest(name):
                errors = lint_paths([BAD / name])
                self.assertTrue(errors, name)
                self.assertTrue(any(fragment in e.message for e in errors), [str(e) for e in errors])

    def test_expression_in_inline_run_even_after_shell_comment(self):
        text = OK_HEAD + '      - run: echo ok # ${{ github.head_ref }}\n'
        self.assertTrue(any("run: script" in e.message for e in lint_text("x.yml", text)))

    def test_expressions_in_env_and_with_are_fine(self):
        text = OK_HEAD + (
            f"      - uses: actions/checkout@{SHA} # v7.0.1\n"
            "        with:\n          ref: ${{ github.sha }}\n"
            "      - env:\n          TITLE: ${{ github.event.pull_request.title }}\n"
            '        run: |\n          echo "$TITLE"\n'
            "      - run: echo done\n"
        )
        self.assertEqual(lint_text("x.yml", text), [])

    def test_run_block_ends_at_dedent(self):
        text = OK_HEAD + "      - run: |\n          echo a\n      - uses: actions/checkout@main\n"
        errors = lint_text("x.yml", text)
        self.assertEqual([e.line for e in errors], [10])

    def test_local_actions_and_docker_digests_are_allowed(self):
        text = OK_HEAD + "      - uses: ./.github/actions/x\n      - uses: docker://alpine@sha256:" + "a" * 64 + "\n"
        self.assertEqual(lint_text("x.yml", text), [])

    def test_docker_tag_is_not_pinned(self):
        text = OK_HEAD + "      - uses: docker://alpine:3.20\n"
        self.assertTrue(lint_text("x.yml", text))

    def test_cli(self):
        from vstd.main import main
        import io
        from contextlib import redirect_stdout

        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["lint-workflows", str(BAD)]), 1)
            self.assertEqual(main(["lint-workflows", str(ROOT / "templates" / "standards.yml")]), 0)


if __name__ == "__main__":
    unittest.main()

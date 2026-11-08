"""ci's tag job: tags main only for a release version with notes, never twice, then calls release.yml."""

import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from vstd.lint import lint_paths

ROOT = Path(__file__).resolve().parents[2]
CI = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
RELEASE = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
# The Python heredoc of the "Create the release tag" step, with its YAML indentation removed.
SCRIPT = "\n".join(line[10:] for line in re.search(r"<<'EOF'\n(.*?)\n\s*EOF\n", CI, re.S).group(1).splitlines())
# Stands in for gh: logs its arguments and answers the matching-refs lookup from EXISTING_REFS.
FAKE_GH = """#!/bin/sh
echo "$*" >> "$GH_LOG"
case "$*" in
  *matching-refs*) printf '%s' "$EXISTING_REFS" ;;
esac
"""


def run(version: str, changelog: str, existing: str = "[]") -> tuple[int, str, str, list[str]]:
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "repo"
        (work / "vstd").mkdir(parents=True)
        (work / "vstd" / "__init__.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")
        (work / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
        bin_dir = Path(tmp) / "bin"
        bin_dir.mkdir()
        gh = bin_dir / "gh"
        gh.write_text(FAKE_GH, encoding="utf-8")
        gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
        out, log = Path(tmp) / "out", Path(tmp) / "gh.log"
        out.touch()
        log.touch()
        env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}", "GITHUB_OUTPUT": str(out),
               "GITHUB_REPOSITORY": "acme/standards", "GITHUB_SHA": "a" * 40, "GH_LOG": str(log),
               "EXISTING_REFS": existing}
        proc = subprocess.run([sys.executable, "-I", "-c", SCRIPT], cwd=work, env=env, capture_output=True, text=True, timeout=30)
        return proc.returncode, proc.stdout, out.read_text(encoding="utf-8"), log.read_text(encoding="utf-8").splitlines()


class AutoTagTest(unittest.TestCase):
    def test_workflows_pass_lint(self):
        self.assertEqual(lint_paths([ROOT / ".github" / "workflows"]), [])

    def test_dev_version_is_not_tagged(self):
        code, out, outputs, calls = run("0.8.1.dev0", "## Unreleased\n")
        self.assertEqual((code, outputs, calls), (0, "", []))
        self.assertIn("not a release version", out)

    def test_release_without_changelog_section_fails(self):
        code, out, outputs, calls = run("0.9.0", "## Unreleased\n\n## v0.8.0\n")
        self.assertEqual((code, outputs, calls), (1, "", []))
        self.assertIn("no '## v0.9.0' section", out)

    def test_existing_tag_is_left_alone(self):
        code, out, outputs, calls = run("0.9.0", "## v0.9.0 (notes)\n", '[{"ref": "refs/tags/v0.9.0"}]')
        self.assertEqual((code, outputs), (0, ""))
        self.assertIn("already exists", out)
        self.assertFalse([c for c in calls if "POST" in c])

    def test_new_release_is_tagged_on_this_commit(self):
        # matching-refs is a prefix match, so v0.9.0 must not be mistaken for v0.9.0x.
        code, out, outputs, calls = run("0.9.0", "## Unreleased\n\n## v0.9.0\n", '[{"ref": "refs/tags/v0.9.01"}]')
        self.assertEqual(code, 0, out)
        self.assertEqual(outputs, "tag=v0.9.0\n")
        posts = [c for c in calls if "POST" in c]
        self.assertEqual(len(posts), 1)
        self.assertIn("repos/acme/standards/git/refs -f ref=refs/tags/v0.9.0 -f sha=" + "a" * 40, posts[0])

    def test_tag_job_runs_only_after_ci_on_main_pushes(self):
        job = re.search(r"\n  tag:\n((?:    .*\n|\n)+?)(?=\n  \w)", CI).group(1)
        self.assertIn("    needs: ci\n", job)
        self.assertIn("    if: github.event_name == 'push' && github.ref == 'refs/heads/main'\n", job)
        self.assertIn("      contents: write # create the tag ref only\n", job)

    def test_publish_calls_release_with_the_new_tag(self):
        self.assertIn("    uses: ./.github/workflows/release.yml\n    with:\n      tag: ${{ needs.tag.outputs.tag }}\n", CI)
        self.assertIn("    if: needs.tag.outputs.tag != ''\n", CI)
        self.assertIn("  workflow_call:\n", RELEASE)
        self.assertNotIn("TAG: ${{ github.ref_name }}", RELEASE)

    def test_main_runs_are_never_cancelled(self):
        self.assertIn("cancel-in-progress: ${{ github.event_name == 'pull_request' }}", CI)


if __name__ == "__main__":
    unittest.main()

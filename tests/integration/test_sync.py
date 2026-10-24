"""vstd sync against local bare Git repos and a stub GitHub API (AC-09, AC-10, AC-11, AC-13 offline)."""

import json
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from vstd import github, sync

PROJECT = Path(__file__).resolve().parents[2]
GIT_ID = ["-c", "user.name=Test", "-c", "user.email=test@example.com", "-c", "init.defaultBranch=main"]
TOKEN = "test-token-not-real"


def git(*args, cwd=None):
    out = subprocess.run(["git", *GIT_ID, *args], cwd=cwd, capture_output=True, text=True, check=True)
    return out.stdout.strip()


class StubGitHub:
    """Just enough of the REST API: list/create/update pulls and commit statuses."""

    def __init__(self):
        self.requests = []
        self.pulls = []
        self.refuse_create = None  # a GitHub error message to answer POST /pulls with
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _reply(self, code, data):
                raw = json.dumps(data).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _handle(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length)) if length else None
                stub.requests.append({"method": self.command, "path": self.path, "body": body, "auth": self.headers.get("Authorization")})
                if self.command == "GET" and "/pulls?" in self.path:
                    return self._reply(200, [p for p in stub.pulls if p["state"] == "open"])
                if self.command == "POST" and self.path.endswith("/pulls") and stub.refuse_create:
                    return self._reply(403, {"message": stub.refuse_create})
                if self.command == "POST" and self.path.endswith("/pulls"):
                    pr = {"number": len(stub.pulls) + 1, "html_url": f"https://example.test/pull/{len(stub.pulls) + 1}", "state": "open", **body}
                    stub.pulls.append(pr)
                    return self._reply(201, pr)
                if self.command == "PATCH" and "/pulls/" in self.path:
                    pr = stub.pulls[int(self.path.rsplit("/", 1)[1]) - 1]
                    pr.update(body)
                    return self._reply(200, pr)
                if self.command == "POST" and "/statuses/" in self.path:
                    return self._reply(201, {})
                return self._reply(404, {"message": "not stubbed"})

            do_GET = do_POST = do_PATCH = do_PUT = _handle

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def writes(self):
        return [r for r in self.requests if r["method"] != "GET"]

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class Central:
    """A bare central repo with releases v0.1.0, v0.1.1 (wording), v0.2.0 (new SHOULD rule), v1.0.0 (major)."""

    def __init__(self, root: Path):
        self.bare = root / "central.git"
        src = root / "central-src"
        git("init", "-q", "--bare", str(self.bare))
        git("init", "-q", str(src))
        for name in ("vstd", "rules"):
            shutil.copytree(PROJECT / name, src / name, ignore=shutil.ignore_patterns("__pycache__"))
        self.sha = {}
        log = "# Changelog\n"
        ts = src / "rules" / "stacks" / "typescript.md"
        for version, note, change in (
            ("0.1.0", "- First release.", None),
            ("0.1.1", "- TS-001 wording clarified.", lambda t: t.replace("[TS-001 SHOULD] ", "[TS-001 SHOULD] Always: ", 1)),
            ("0.2.0", "- Added TS-013 (SHOULD).", lambda t: t.rstrip("\n") + "\n- [TS-013 SHOULD] Prefer `unknown` over `any` for untrusted input.\n"),
            ("1.0.0", "- BREAKING: config schema 2.", None),
        ):
            if change:
                ts.write_text(change(ts.read_text()))
            (src / "vstd" / "__init__.py").write_text(f'__version__ = "{version}"\n')
            log = log.replace("# Changelog\n", f"# Changelog\n\n## v{version}\n\n{note}\n", 1)
            (src / "CHANGELOG.md").write_text(log)
            git("add", "-A", cwd=src)
            git("commit", "-q", "-m", f"v{version}", cwd=src)
            if version == "0.2.0":
                git("tag", "-a", "-m", "annotated", f"v{version}", cwd=src)
            else:
                git("tag", f"v{version}", cwd=src)
            self.sha[version] = git("rev-parse", "HEAD", cwd=src)
        git("push", "-q", str(self.bare), "main", "--tags", cwd=src)
        self.url = str(self.bare)


class SyncTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.central = Central(root)
        cls.v010 = sync.fetch_release(cls.central.url, (0, 1, 0), cls.central.sha["0.1.0"], root / "v010")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.case = tempfile.TemporaryDirectory()
        self.root = Path(self.case.name)
        self.origin = self.root / "origin.git"
        self.repo = self.root / "consumer"
        self.api = StubGitHub()
        self.addCleanup(self.case.cleanup)
        self.addCleanup(self.api.close)

    def tearDown(self):
        merges = [r for r in self.api.requests if "/merge" in r["path"] or r["method"] == "PUT"]
        self.assertEqual(merges, [], "sync must never merge")
        for r in self.api.requests:
            self.assertEqual(r["auth"], f"Bearer {TOKEN}")
            self.assertNotIn(TOKEN, json.dumps(r["body"]) + r["path"])

    def make_consumer(self, upgrade="minor", commit=None, stacks='["typescript"]'):
        git("init", "-q", "--bare", str(self.origin))
        git("init", "-q", str(self.repo))
        (self.repo / ".venuvra").mkdir()
        (self.repo / ".venuvra" / "standards.toml").write_text(
            f'schema = 1\nversion = "0.1.0"\ncommit = "{commit or self.central.sha["0.1.0"]}"\n'
            f'upgrade = "{upgrade}"\nstacks = {stacks}\n'
        )
        (self.repo / "README.md").write_text("# consumer\n")
        out = sync.tool(self.v010, "sync", "--local", "--repo", str(self.repo))
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        git("add", "-A", cwd=self.repo)
        git("commit", "-q", "-m", "init", cwd=self.repo)
        git("push", "-q", str(self.origin), "main", cwd=self.repo)

    def snapshot(self):
        return {p.relative_to(self.repo).as_posix(): p.read_bytes() for p in self.repo.rglob("*") if p.is_file() and ".git" not in p.parts}

    def sync(self, **kw):
        args = dict(
            standards_root=self.v010, tool_version="0.1.0", github_repo="Venuvra/fixture", token=TOKEN,
            central_url=self.central.url, push_url=str(self.origin), api_url=self.api.url,
        )
        args.update(kw)
        return sync.run(self.repo, **args)

    def remote_branch(self):
        out = git("ls-remote", str(self.origin), f"refs/heads/{sync.BRANCH}")
        return out.split("\t")[0] or None

    def remote_file(self, rel):
        return git("--git-dir", str(self.origin), "show", f"{sync.BRANCH}:{rel}")

    # AC-09: pin hold and upgrade policies
    def test_manual_policy_holds_the_pin(self):
        self.make_consumer(upgrade="manual")
        before = self.snapshot()
        r = self.sync()
        self.assertEqual(r.target, (0, 1, 0))
        self.assertEqual(r.changes, {})
        self.assertIsNone(self.remote_branch())
        self.assertEqual(self.api.requests, [])
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(any("v1.0.0 is available" in m for m in r.messages))

    def test_patch_policy_takes_newest_patch_only(self):
        self.make_consumer(upgrade="patch")
        r = self.sync()
        self.assertEqual(r.target, (0, 1, 1))
        toml = self.remote_file(".venuvra/standards.toml")
        self.assertIn('version = "0.1.1"', toml)
        self.assertIn(f'commit = "{self.central.sha["0.1.1"]}"', toml)
        self.assertIn("Always: ", self.remote_file("AGENTS.md"))

    def test_minor_policy_never_proposes_a_major(self):
        self.make_consumer(upgrade="minor")
        before = self.snapshot()
        r = self.sync()
        self.assertEqual(r.target, (0, 2, 0))
        self.assertIn('version = "0.2.0"', self.remote_file(".venuvra/standards.toml"))
        self.assertIn("TS-013", self.remote_file("AGENTS.md"))
        (pr,) = self.api.pulls
        self.assertEqual(pr["head"], sync.BRANCH)
        self.assertEqual(pr["base"], "main")
        self.assertIn("added: TS-013", pr["body"])
        self.assertIn("changed: TS-001", pr["body"])
        self.assertIn("v1.0.0 is available", pr["body"])
        self.assertIn("Added TS-013", pr["body"])
        self.assertNotIn("BREAKING", pr["body"])
        self.assertEqual(self.snapshot(), before, "the working tree is never written")

    def test_upgrade_sets_standards_check_status_on_branch_head(self):
        self.make_consumer()
        r = self.sync()
        (status,) = [x for x in self.api.requests if "/statuses/" in x["path"]]
        self.assertTrue(status["path"].endswith(f"/statuses/{r.pushed}"))
        self.assertEqual(status["body"]["context"], "standards/check")
        self.assertEqual(status["body"]["state"], "success")
        self.assertEqual(r.pushed, self.remote_branch())

    # AC-10: idempotent
    def test_second_run_writes_nothing_and_opens_no_pr(self):
        self.make_consumer()
        self.sync()
        branch, writes, before = self.remote_branch(), len(self.api.writes()), self.snapshot()
        r = self.sync()
        self.assertIsNone(r.pushed)
        self.assertEqual(self.remote_branch(), branch)
        self.assertEqual(len(self.api.writes()), writes)
        self.assertEqual(len(self.api.pulls), 1)
        self.assertEqual(self.snapshot(), before)

    def test_rerun_after_a_refused_pr_reuses_the_pushed_branch(self):
        # ES-12 live run: the push worked, PR creation got 403 until a setting changed.
        self.make_consumer()
        self.api.refuse_create = "GitHub Actions is not permitted to create or approve pull requests."
        with self.assertRaisesRegex(github.GitHubError, "HTTP 403: GitHub Actions is not permitted"):
            self.sync()
        branch = self.remote_branch()
        self.assertIsNotNone(branch)
        self.api.refuse_create = None
        r = self.sync()
        self.assertIsNone(r.pushed, "the branch already had the changes")
        self.assertEqual(self.remote_branch(), branch)
        self.assertEqual(len(self.api.pulls), 1)
        (status,) = [x for x in self.api.requests if "/statuses/" in x["path"]]
        self.assertTrue(status["path"].endswith(f"/statuses/{branch}"))

    def test_up_to_date_repo_does_nothing(self):
        self.make_consumer(upgrade="manual")
        self.sync()
        self.sync()
        self.assertEqual(self.api.requests, [])
        self.assertIsNone(self.remote_branch())

    def test_branch_moves_forward_without_force_when_base_changes(self):
        self.make_consumer()
        first = self.sync().pushed
        (self.repo / "NEW.md").write_text("new\n")
        git("add", "NEW.md", cwd=self.repo)
        git("commit", "-q", "-m", "base moved", cwd=self.repo)
        second = self.sync().pushed
        self.assertNotEqual(first, second)
        subprocess.run(["git", "--git-dir", str(self.origin), "merge-base", "--is-ancestor", first, second], check=True)
        self.assertEqual(len(self.api.pulls), 1)

    # AC-11: dry run
    def test_dry_run_shows_diff_and_changes_nothing(self):
        self.make_consumer()
        before = self.snapshot()
        r = self.sync(dry_run=True, github_repo=None, token=None)
        self.assertIn('+version = "0.2.0"', r.diff)
        self.assertIn("TS-013", r.diff)
        self.assertEqual(self.api.requests, [])
        self.assertIsNone(self.remote_branch())
        self.assertEqual(self.snapshot(), before)

    def test_config_change_rerenders_same_version(self):
        self.make_consumer(upgrade="manual")
        cfg = self.repo / ".venuvra" / "standards.toml"
        cfg.write_text(cfg.read_text().replace('["typescript"]', '["python", "typescript"]'))
        git("commit", "-q", "-am", "add python", cwd=self.repo)
        r = self.sync()
        self.assertEqual(sorted(r.changes), ["AGENTS.md"])
        self.assertTrue(self.api.pulls[0]["title"].startswith("Re-sync"))

    # Refusals
    def test_pin_mismatch_fails(self):
        self.make_consumer(commit=self.central.sha["0.1.1"])
        with self.assertRaisesRegex(sync.SyncError, "pin mismatch"):
            self.sync()
        self.assertEqual(self.api.requests, [])

    def test_running_the_wrong_release_fails(self):
        self.make_consumer()
        with self.assertRaisesRegex(sync.SyncError, "check out the pinned commit"):
            self.sync(tool_version="0.2.0")

    def test_missing_repository_slug_fails_before_pushing(self):
        self.make_consumer()
        with self.assertRaisesRegex(sync.SyncError, "GITHUB_REPOSITORY"):
            self.sync(github_repo=None)
        self.assertIsNone(self.remote_branch())


class UnitTest(unittest.TestCase):
    def test_choose_target(self):
        rel = {(0, 1, 0): "a", (0, 1, 3): "b", (0, 4, 0): "c", (1, 0, 0): "d"}
        self.assertEqual(sync.choose_target((0, 1, 0), rel, "manual"), ((0, 1, 0), (1, 0, 0)))
        self.assertEqual(sync.choose_target((0, 1, 0), rel, "patch"), ((0, 1, 3), (1, 0, 0)))
        self.assertEqual(sync.choose_target((0, 1, 0), rel, "minor"), ((0, 4, 0), (1, 0, 0)))
        self.assertEqual(sync.choose_target((1, 0, 0), rel, "minor"), ((1, 0, 0), None))

    def test_set_pin_needs_exactly_one_line(self):
        text = 'version = "0.1.0"\ncommit = "x"\n'
        self.assertEqual(sync.set_pin(text, (0, 2, 0), "y"), 'version = "0.2.0"\ncommit = "y"\n')
        with self.assertRaises(sync.SyncError):
            sync.set_pin(text + 'version = "9.9.9"\n', (0, 2, 0), "y")

    def test_child_env_drops_tokens(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {"GH_TOKEN": "a", "GITHUB_TOKEN": "b", "GIT_DIR": "/x", "KEEP": "1"}):
            env = sync.child_env()
        self.assertNotIn("GH_TOKEN", env)
        self.assertNotIn("GITHUB_TOKEN", env)
        self.assertNotIn("GIT_DIR", env)
        self.assertEqual(env["KEEP"], "1")

    def test_git_auth_is_scoped_to_github(self):
        env = sync.git_auth_env("tok")
        self.assertEqual(env["GIT_CONFIG_KEY_0"], "http.https://github.com/.extraheader")
        self.assertNotIn("tok", env["GIT_CONFIG_VALUE_0"])

    def test_changelog_excerpt_and_breaking_notes(self):
        log = "# Changelog\n\n## v1.0.0\n\n- BREAKING: schema 2.\n\n## v0.2.0\n\n- Added X.\n\n## v0.1.0\n\n- First.\n"
        excerpt = sync.changelog_excerpt(log, (0, 1, 0), (1, 0, 0))
        self.assertIn("## v0.2.0", excerpt)
        self.assertNotIn("First.", excerpt)
        body = sync.pr_body((0, 1, 0), (1, 0, 0), None, {"AGENTS.md": b""}, excerpt, None, True)
        self.assertIn("**BREAKING:**\n- BREAKING: schema 2.", body)

    def test_owned_paths(self):
        for rel in (".venuvra/standards.toml", "AGENTS.md", "CLAUDE.md", ".claude/CLAUDE.md", "web/CLAUDE.md"):
            self.assertTrue(sync.owned(rel), rel)
        for rel in ("README.md", ".github/workflows/x.yml", "standards.toml"):
            self.assertFalse(sync.owned(rel), rel)


if __name__ == "__main__":
    unittest.main()

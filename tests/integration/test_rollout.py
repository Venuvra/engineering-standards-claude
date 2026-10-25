"""vstd rollout against local bare Git repos and a stub GitHub API: opens PRs, skips, never merges."""

import base64
import json
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VERSION = "0.1.0"  # a release; the package version is a .dev build between releases
from vstd.rollout import BRANCH, parse_repo_list, rollout
from vstd.rules import load_rules

PROJECT = Path(__file__).resolve().parents[2]
RULES = load_rules(PROJECT / "rules")
GIT_ID = ["-c", "user.name=Test", "-c", "user.email=test@example.com"]
TOKEN = "test-token-not-real"
SHA = "b" * 40


def git(*args, cwd=None):
    out = subprocess.run(["git", *GIT_ID, *args], cwd=cwd, capture_output=True, text=True, check=True)
    return out.stdout.strip()


class StubGitHub:
    """Repository metadata, file contents and pulls for several repositories."""

    def __init__(self):
        self.requests = []
        self.repos = {}  # "owner/name" -> {"default_branch": ..., "files": {path: text}, "archived": bool}
        self.pulls = []
        self.refuse_create = 0  # answer this many POST /pulls with a 422
        self.check_runs = []  # what GET commits/{sha}/check-runs returns
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
                parts = self.path.split("?", 1)[0].split("/")  # ['', 'repos', owner, name, ...]
                slug = "/".join(parts[2:4])
                meta = stub.repos.get(slug)
                if meta is None:
                    return self._reply(404, {"message": "Not Found"})
                if self.command == "GET" and len(parts) == 4:
                    return self._reply(200, {"default_branch": meta["default_branch"], "archived": meta.get("archived", False)})
                if self.command == "GET" and parts[4] == "contents":
                    text = meta.get("files", {}).get("/".join(parts[5:]))
                    if text is None:
                        return self._reply(404, {"message": "Not Found"})
                    return self._reply(200, {"encoding": "base64", "content": base64.b64encode(text.encode()).decode()})
                if parts[4:7] == ["actions", "permissions", "workflow"]:
                    perms = meta.setdefault("workflow", {"default_workflow_permissions": "read", "can_approve_pull_request_reviews": False})
                    if meta.get("lock_actions"):
                        return self._reply(409, {"message": "organization policy prevents this"})
                    if self.command == "PUT":
                        perms.update(body)
                        return self._reply(204, {})
                    return self._reply(200, perms)
                if self.command == "GET" and parts[4] == "commits" and parts[6] == "check-runs":
                    return self._reply(200, {"check_runs": stub.check_runs})
                if self.command == "GET" and parts[4] == "pulls":
                    return self._reply(200, [p for p in stub.pulls if p["repo"] == slug and p["state"] == "open"])
                if self.command == "POST" and parts[4] == "pulls" and stub.refuse_create:
                    stub.refuse_create -= 1
                    return self._reply(422, {"message": "Validation Failed"})
                if self.command == "POST" and parts[4] == "pulls":
                    n = len(stub.pulls) + 1
                    pr = {"number": n, "html_url": f"https://example.test/{slug}/pull/{n}", "state": "open", "repo": slug, **body}
                    stub.pulls.append(pr)
                    return self._reply(201, pr)
                return self._reply(404, {"message": "not stubbed"})

            do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = _handle

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class RolloutTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.api = StubGitHub()
        self.addCleanup(self.api.close)
        self.origins = {}
        self.allow = False

    def tearDown(self):
        # The one setting rollout may change is the Actions PR permission, and only with the flag.
        bad = [r for r in self.api.requests if "/merge" in r["path"] or r["method"] in ("PATCH", "DELETE")
               or (r["method"] == "PUT" and not (self.allow and r["path"].endswith("/actions/permissions/workflow")))]
        self.assertEqual(bad, [], "rollout must never merge or change other settings")
        for r in self.api.requests:
            self.assertEqual(r["auth"], f"Bearer {TOKEN}")
            self.assertNotIn(TOKEN, json.dumps(r["body"]) + r["path"])

    def make_repo(self, slug, branch="main", files=None, **meta):
        """A bare origin with one commit on ``branch``, registered in the stub."""
        origin = self.root / f"{slug.replace('/', '__')}.git"
        src = self.root / f"{slug.replace('/', '__')}-src"
        git("init", "-q", "--bare", str(origin))
        git("init", "-q", "-b", branch, str(src))
        for rel, text in (files or {"README.md": "# demo\n"}).items():
            (src / rel).parent.mkdir(parents=True, exist_ok=True)
            (src / rel).write_text(text)
        git("add", "-A", cwd=src)
        git("commit", "-q", "-m", "initial", cwd=src)
        git("push", "-q", str(origin), branch, cwd=src)
        self.api.repos[slug] = {"default_branch": branch, **meta}
        self.origins[slug] = origin
        return origin

    def run_rollout(self, repos, dry_run=False, allow=False):
        self.allow = self.allow or allow
        # One call per repo because each has its own local origin; real runs derive the GitHub URL.
        results = []
        for repo in repos:
            results += rollout([repo], RULES, version=VERSION, commit=SHA, standards_root=PROJECT, token=TOKEN,
                               author=("Test", "test@example.com"), dry_run=dry_run, api_url=self.api.url, allow_actions_prs=allow,
                               clone_url=str(self.origins.get(repo, self.root / "missing.git")))
        return results

    def branches(self, slug):
        out = git("for-each-ref", "--format=%(refname:short)", "refs/heads", cwd=self.origins[slug])
        return sorted(out.split())

    def test_opens_pr_against_non_main_default_branch(self):
        self.make_repo("acme/app", branch="milestone-1", files={"package.json": "{}\n"})
        [r] = self.run_rollout(["acme/app"])
        self.assertEqual(r.outcome, "opened", r.detail)
        self.assertEqual(r.stacks, ("typescript",))
        self.assertEqual(self.branches("acme/app"), sorted(["milestone-1", BRANCH]))
        [pr] = self.api.pulls
        self.assertEqual((pr["head"], pr["base"]), (BRANCH, "milestone-1"))
        self.assertIn("Confirm the check commands drafted in the project section", pr["body"])
        self.assertIn("allow GitHub Actions to create and approve pull requests", pr["body"])
        workflow = git("show", f"{BRANCH}:.github/workflows/standards.yml", cwd=self.origins["acme/app"])
        self.assertIn("milestone-1", workflow)
        log = git("log", "--format=%an %s", BRANCH, cwd=self.origins["acme/app"]).splitlines()
        self.assertEqual(log[0], f"Test Adopt Venuvra engineering standards v{VERSION}")
        self.assertEqual(git("rev-list", "--count", "milestone-1", cwd=self.origins["acme/app"]), "1", "default branch untouched")

    def test_rerun_after_failed_pr_reuses_pushed_branch(self):
        self.make_repo("acme/retry")
        self.api.refuse_create = 1
        [first] = self.run_rollout(["acme/retry"])
        self.assertEqual(first.outcome, "failed")
        pushed = git("rev-parse", BRANCH, cwd=self.origins["acme/retry"])
        time.sleep(1.1)  # a new commit would now get a different timestamp, so a different SHA
        [second] = self.run_rollout(["acme/retry"])
        self.assertEqual(second.outcome, "opened", second.detail)
        self.assertEqual(git("rev-parse", BRANCH, cwd=self.origins["acme/retry"]), pushed, "branch not rewritten")
        self.assertEqual(len(self.api.pulls), 1)

    def test_existing_branch_with_other_content_fails(self):
        origin = self.make_repo("acme/clash")
        src = self.root / "clash-other"
        git("clone", "-q", str(origin), str(src))
        (src / "AGENTS.md").write_text("someone else's work\n")
        git("add", "-A", cwd=src)
        git("commit", "-q", "-m", "other", cwd=src)
        git("push", "-q", "origin", f"HEAD:refs/heads/{BRANCH}", cwd=src)
        before = git("rev-parse", BRANCH, cwd=origin)
        [r] = self.run_rollout(["acme/clash"])
        self.assertEqual(r.outcome, "failed")
        self.assertIn(BRANCH, r.detail)
        self.assertEqual(git("rev-parse", BRANCH, cwd=origin), before)
        self.assertEqual(self.api.pulls, [])

    def test_drafts_project_section_from_repo_files(self):
        self.make_repo("acme/web", files={
            "package.json": json.dumps({"scripts": {"lint": "eslint .", "test": "vitest", "dev": "next dev"}}),
            "pnpm-lock.yaml": "lockfileVersion: 9\n",
            ".github/workflows/ci.yml": "jobs:\n  t:\n    steps:\n      - run: pnpm install --frozen-lockfile\n      - run: echo ${{ github.sha }}\n",
        })
        [r] = self.run_rollout(["acme/web"])
        self.assertEqual(r.outcome, "opened", r.detail)
        agents = git("show", f"{BRANCH}:AGENTS.md", cwd=self.origins["acme/web"])
        self.assertIn("## Checks", agents)
        self.assertIn("- `pnpm lint`", agents)
        self.assertIn("- `pnpm test`", agents)
        self.assertIn("- `pnpm install --frozen-lockfile`", agents)
        self.assertNotIn("next dev", agents)
        self.assertNotIn("github.sha", agents)
        self.assertNotIn("Add build and test commands", agents)
        self.assertIn("Confirm the check commands drafted", self.api.pulls[0]["body"])

    def test_existing_agents_md_gets_no_draft(self):
        self.make_repo("acme/own", files={"AGENTS.md": "Run make test.\n", "Makefile": "test:\n\techo ok\n"})
        [r] = self.run_rollout(["acme/own"])
        self.assertEqual(r.outcome, "opened", r.detail)
        agents = git("show", f"{BRANCH}:AGENTS.md", cwd=self.origins["acme/own"])
        self.assertNotIn("## Checks", agents)
        self.assertIn("Fill in the project section", self.api.pulls[0]["body"])

    def test_allow_actions_prs_ticks_only_that_setting(self):
        self.make_repo("acme/auto")
        [r] = self.run_rollout(["acme/auto"], allow=True)
        self.assertEqual(r.outcome, "opened", r.detail)
        [put] = [q for q in self.api.requests if q["method"] == "PUT"]
        self.assertEqual(put["body"], {"default_workflow_permissions": "read", "can_approve_pull_request_reviews": True})
        self.assertIn("was turned on by `vstd rollout`", self.api.pulls[0]["body"])

    def test_without_flag_settings_are_untouched(self):
        self.make_repo("acme/manual")
        [r] = self.run_rollout(["acme/manual"])
        self.assertEqual(r.outcome, "opened", r.detail)
        self.assertFalse([q for q in self.api.requests if "actions/permissions" in q["path"]])
        self.assertIn("allow GitHub Actions to create and approve pull requests", self.api.pulls[0]["body"])

    def test_locked_setting_is_a_warning_not_a_failure(self):
        self.make_repo("acme/locked", lock_actions=True)
        [r] = self.run_rollout(["acme/locked"], allow=True)
        self.assertEqual(r.outcome, "opened", r.detail)
        self.assertTrue(any("could not turn on the Actions PR setting" in w for w in r.warnings), r.warnings)
        self.assertIn("allow GitHub Actions to create and approve pull requests", self.api.pulls[0]["body"])

    def test_dry_run_with_flag_changes_no_setting(self):
        self.make_repo("acme/drysetting")
        [r] = self.run_rollout(["acme/drysetting"], dry_run=True, allow=True)
        self.assertEqual(r.outcome, "ready", r.detail)
        self.assertEqual([q for q in self.api.requests if q["method"] != "GET"], [])

    def test_open_pr_reports_its_check_state(self):
        self.make_repo("acme/state")
        self.api.pulls.append({"number": 9, "html_url": "https://example.test/acme/state/pull/9", "state": "open",
                               "repo": "acme/state", "title": "t", "body": "b", "head": {"sha": "c" * 40}, "base": "main"})
        self.api.check_runs = [{"status": "completed", "conclusion": "success"}, {"status": "completed", "conclusion": "skipped"}]
        [r] = self.run_rollout(["acme/state"])
        self.assertEqual((r.outcome, r.checks), ("skipped", "green"))
        self.api.check_runs = [{"status": "completed", "conclusion": "failure"}]
        [r] = self.run_rollout(["acme/state"])
        self.assertEqual(r.checks, "failing")

    def test_skips_already_onboarded_repo(self):
        self.make_repo("acme/done", files={"README.md": "x\n"})
        self.api.repos["acme/done"]["files"] = {".venuvra/standards.toml": "version = \"0.1.1\"\n"}
        [r] = self.run_rollout(["acme/done"])
        self.assertEqual(r.outcome, "skipped")
        self.assertIn("already onboarded", r.detail)
        self.assertEqual(self.branches("acme/done"), ["main"])

    def test_skips_when_onboarding_pr_open(self):
        self.make_repo("acme/pending")
        self.api.pulls.append({"number": 7, "html_url": "https://example.test/acme/pending/pull/7", "state": "open",
                               "repo": "acme/pending", "title": "t", "body": "b", "head": BRANCH, "base": "main"})
        [r] = self.run_rollout(["acme/pending"])
        self.assertEqual((r.outcome, r.pr_url), ("skipped", "https://example.test/acme/pending/pull/7"))
        self.assertEqual(self.branches("acme/pending"), ["main"])

    def test_dry_run_pushes_nothing(self):
        self.make_repo("acme/dry", files={"pyproject.toml": "[project]\nname='x'\n"})
        [r] = self.run_rollout(["acme/dry"], dry_run=True)
        self.assertEqual(r.outcome, "ready", r.detail)
        self.assertEqual(r.stacks, ("python",))
        self.assertEqual(self.branches("acme/dry"), ["main"])
        self.assertEqual([q for q in self.api.requests if q["method"] != "GET"], [])

    def test_failure_in_one_repo_does_not_stop_the_rest(self):
        self.make_repo("acme/one")
        self.make_repo("acme/archived", archived=True)
        self.make_repo("acme/three")
        results = self.run_rollout(["acme/one", "acme/archived", "acme/unknown", "acme/three"])
        self.assertEqual([r.outcome for r in results], ["opened", "failed", "failed", "opened"])
        self.assertIn("archived", results[1].detail)
        self.assertIn("404", results[2].detail)
        self.assertNotIn(TOKEN, " ".join(r.detail for r in results))

    def test_keeps_existing_agents_text(self):
        self.make_repo("acme/docs", files={"AGENTS.md": "Run make test before pushing.\n"})
        [r] = self.run_rollout(["acme/docs"])
        self.assertEqual(r.outcome, "opened", r.detail)
        agents = git("show", f"{BRANCH}:AGENTS.md", cwd=self.origins["acme/docs"])
        self.assertIn("Run make test before pushing.", agents)

    def test_rejects_bad_slugs_before_touching_anything(self):
        with self.assertRaises(ValueError):
            rollout(["acme/ok", "not-a-slug"], RULES, version=VERSION, commit=SHA, standards_root=PROJECT,
                    token=TOKEN, author=("Test", "test@example.com"), api_url=self.api.url)
        self.assertEqual(self.api.requests, [])


class CommandLineTest(unittest.TestCase):
    def run_cli(self, *args, env=None):
        return subprocess.run(["python3", "-I", str(PROJECT / "vstd" / "main.py"), "rollout", *args],
                              capture_output=True, text=True, env=env or {"PATH": "/usr/bin:/bin"})

    def test_needs_repositories(self):
        out = self.run_cli("--repos", " # none")
        self.assertEqual(out.returncode, 1)
        self.assertIn("name the repositories", out.stdout)

    def test_rejects_unreadable_repo_file(self):
        out = self.run_cli("--repos-file", str(PROJECT / "no-such-file.txt"))
        self.assertEqual(out.returncode, 1)
        self.assertIn("can't read", out.stdout)


class ParseRepoListTest(unittest.TestCase):
    def test_lines_commas_comments_and_duplicates(self):
        text = "acme/a, acme/b\n# skipped for now\nacme/c  # pilot\n\nacme/a\n"
        self.assertEqual(parse_repo_list(text), ["acme/a", "acme/b", "acme/c"])

    def test_empty(self):
        self.assertEqual(parse_repo_list("\n# nothing\n"), [])


if __name__ == "__main__":
    unittest.main()

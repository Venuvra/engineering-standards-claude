"""vstd rollout against local bare Git repos and a stub GitHub API: opens PRs, skips, never merges."""

import base64
import json
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from vstd import __version__
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
                if self.command == "GET" and parts[4] == "pulls":
                    return self._reply(200, [p for p in stub.pulls if p["repo"] == slug and p["state"] == "open"])
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

    def tearDown(self):
        bad = [r for r in self.api.requests if "/merge" in r["path"] or r["method"] in ("PUT", "PATCH", "DELETE")]
        self.assertEqual(bad, [], "rollout must never merge or change settings")
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

    def run_rollout(self, repos, dry_run=False):
        # One call per repo because each has its own local origin; real runs derive the GitHub URL.
        results = []
        for repo in repos:
            results += rollout([repo], RULES, version=__version__, commit=SHA, standards_root=PROJECT, token=TOKEN,
                               author=("Test", "test@example.com"), dry_run=dry_run, api_url=self.api.url,
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
        self.assertIn("Fill in the project section", pr["body"])
        self.assertIn("allow GitHub Actions to create and approve pull requests", pr["body"])
        workflow = git("show", f"{BRANCH}:.github/workflows/standards.yml", cwd=self.origins["acme/app"])
        self.assertIn("milestone-1", workflow)
        log = git("log", "--format=%an %s", BRANCH, cwd=self.origins["acme/app"]).splitlines()
        self.assertEqual(log[0], f"Test Adopt Venuvra engineering standards v{__version__}")
        self.assertEqual(git("rev-list", "--count", "milestone-1", cwd=self.origins["acme/app"]), "1", "default branch untouched")

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
            rollout(["acme/ok", "not-a-slug"], RULES, version=__version__, commit=SHA, standards_root=PROJECT,
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

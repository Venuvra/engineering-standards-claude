"""The few GitHub REST calls sync needs, with the standard library only.

The host is fixed to api.github.com; tests pass a local stub through
``api_url``, which the command line doesn't expose. The token is sent only in
the Authorization header and never appears in errors or logs. There is no
merge call: sync and rollout open pull requests and stop there. The only
setting it changes is the Actions pull-request permission, and only when rollout
is run with ``--allow-actions-prs``.
"""

from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

API_URL = "https://api.github.com"
STATUS_CONTEXT = "standards/check"
TIMEOUT_SECONDS = 30
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_ERROR_BYTES = 16 * 1024
MAX_ERROR_CHARS = 300
_REPO_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class GitHubError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _api_message(exc: urllib.error.HTTPError) -> str:
    """GitHub's own explanation (its JSON "message"), so a 403 says which setting is missing."""
    try:
        data = json.loads(exc.read(MAX_ERROR_BYTES))
    except (OSError, ValueError):
        return ""  # no usable body; the caller still reports the status code
    message = data.get("message") if isinstance(data, dict) else None
    if not isinstance(message, str) or not message.strip():
        return ""
    # One printable line, bounded, so the API can't inject log lines or annotations.
    message = " ".join("".join(c if c.isprintable() else " " for c in message).split())
    return f": {message[:MAX_ERROR_CHARS]}"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect could carry the Authorization header to another host; refuse it."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise GitHubError(f"{req.get_method()} refused a redirect (HTTP {code})")


_OPENER = urllib.request.build_opener(_NoRedirect)


def valid_repo(slug: str) -> bool:
    return bool(_REPO_RE.match(slug)) and ".." not in slug


@dataclass(frozen=True)
class PullRequest:
    number: int
    url: str
    title: str
    body: str
    head_sha: str = ""


class Client:
    def __init__(self, repo: str, token: str, api_url: str = API_URL):
        if not valid_repo(repo):
            raise GitHubError(f"'{repo}' is not an owner/name repository slug")
        if not token:
            raise GitHubError("GH_TOKEN is not set")
        self.repo = repo
        self._token = token
        self._api = api_url.rstrip("/")

    def __repr__(self) -> str:  # keep the token out of tracebacks and debug output
        return f"Client(repo={self.repo!r})"

    def _call(self, method: str, path: str, body: dict | None = None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(f"{self._api}{path}", data=data, method=method)
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        req.add_header("User-Agent", "vstd")
        req.add_header("Authorization", f"Bearer {self._token}")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with _OPENER.open(req, timeout=TIMEOUT_SECONDS) as resp:
                raw = resp.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            raise GitHubError(f"{method} {path} failed with HTTP {exc.code}{_api_message(exc)}", exc.code) from None
        except (urllib.error.URLError, TimeoutError) as exc:
            raise GitHubError(f"{method} {path} failed: {getattr(exc, 'reason', exc)}") from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise GitHubError(f"{method} {path}: response too large")
        return json.loads(raw) if raw else None

    @staticmethod
    def _pr(data: dict) -> PullRequest:
        head = data.get("head") if isinstance(data.get("head"), dict) else {}
        return PullRequest(int(data["number"]), str(data["html_url"]), str(data.get("title") or ""), str(data.get("body") or ""),
                           str(head.get("sha") or ""))

    def find_open_pr(self, head: str, base: str) -> PullRequest | None:
        _check_branch(head)
        _check_branch(base)
        owner = self.repo.split("/", 1)[0]
        query = urllib.parse.urlencode({"state": "open", "head": f"{owner}:{head}", "base": base})
        found = self._call("GET", f"/repos/{self.repo}/pulls?{query}") or []
        return self._pr(found[0]) if found else None

    def create_pr(self, head: str, base: str, title: str, body: str) -> PullRequest:
        _check_branch(head)
        _check_branch(base)
        data = self._call("POST", f"/repos/{self.repo}/pulls", {"title": title, "head": head, "base": base, "body": body, "maintainer_can_modify": True})
        return self._pr(data)

    def update_pr(self, number: int, title: str, body: str) -> PullRequest:
        return self._pr(self._call("PATCH", f"/repos/{self.repo}/pulls/{int(number)}", {"title": title, "body": body}))

    def default_branch(self) -> str:
        data = self._call("GET", f"/repos/{self.repo}") or {}
        if data.get("archived"):
            raise GitHubError(f"{self.repo} is archived")
        branch = str(data.get("default_branch") or "")
        _check_branch(branch)
        return branch

    def file_text(self, path: str, ref: str) -> str | None:
        """A file's text on ``ref``, or None when it doesn't exist there."""
        _check_branch(ref)
        query = urllib.parse.urlencode({"ref": ref})
        try:
            data = self._call("GET", f"/repos/{self.repo}/contents/{urllib.parse.quote(path)}?{query}")
        except GitHubError as exc:
            if exc.status == 404:
                return None
            raise
        if not isinstance(data, dict) or data.get("encoding") != "base64":
            raise GitHubError(f"{path} on {ref} is not a file")
        return base64.b64decode(data.get("content") or "").decode("utf-8", "replace")

    def check_state(self, sha: str) -> str:
        """Summary of the check runs on a commit: green, running, failing or no checks."""
        if not _SHA_RE.match(sha):
            raise GitHubError(f"'{sha}' is not a commit SHA")
        runs = (self._call("GET", f"/repos/{self.repo}/commits/{sha}/check-runs?per_page=100") or {}).get("check_runs") or []
        if not runs:
            return "no checks"
        if any(r.get("status") != "completed" for r in runs):
            return "running"
        if all(r.get("conclusion") in ("success", "neutral", "skipped") for r in runs):
            return "green"
        return "failing"

    def allow_actions_prs(self) -> str:
        """Tick "Allow GitHub Actions to create and approve pull requests", keeping the
        default token permission as it is. Returns that permission ("read" or "write")."""
        current = self._call("GET", f"/repos/{self.repo}/actions/permissions/workflow") or {}
        default = current.get("default_workflow_permissions")
        if default not in ("read", "write"):
            raise GitHubError(f"{self.repo}: unexpected workflow permissions {default!r}")
        if not current.get("can_approve_pull_request_reviews"):
            self._call("PUT", f"/repos/{self.repo}/actions/permissions/workflow",
                       {"default_workflow_permissions": default, "can_approve_pull_request_reviews": True})
        return default

    def set_status(self, sha: str, state: str, description: str, target_url: str | None = None) -> None:
        if not _SHA_RE.match(sha):
            raise GitHubError(f"'{sha}' is not a commit SHA")
        if state not in ("success", "failure", "error", "pending"):
            raise GitHubError(f"unknown status state '{state}'")
        body = {"state": state, "context": STATUS_CONTEXT, "description": description[:140]}
        if target_url:
            body["target_url"] = target_url
        self._call("POST", f"/repos/{self.repo}/statuses/{sha}", body)


def _check_branch(name: str) -> None:
    if not _BRANCH_RE.match(name) or ".." in name or name.startswith("-"):
        raise GitHubError(f"'{name}' is not a branch name vstd will use")

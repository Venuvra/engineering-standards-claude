"""Sync a repository with the central standards through one pull request.

The flow, run from a checkout of the pinned release:

1. Read ``.venuvra/standards.toml`` and list the central release tags.
2. Check the pin: tag ``v<version>`` must point at ``commit``.
3. Pick the newest release the ``upgrade`` policy allows. A major is never
   chosen; it is mentioned in the PR body instead.
4. Render into a scratch copy of the repository with the target release's own
   ``vstd`` (fetched into a temp dir when upgrading). The real working tree
   is never written.
5. If nothing changed, stop: no branch, no PR. Otherwise commit only the owned
   files to ``standards/update`` (fast-forward only, never force), open or
   update one PR, and set the ``standards/check`` commit status. Never merge.

``--dry-run`` stops after step 4 and prints the diff.
"""

from __future__ import annotations

import base64
import difflib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from vstd import config as config_mod
from vstd import github
from vstd.rules import RuleError, RuleSet, load_rules
from vstd.writer import SKIP_DIRS, WRITABLE_NAMES

CENTRAL_URL = "https://github.com/Venuvra/engineering-standards-claude.git"
BRANCH = "standards/update"
BOT_NAME = "github-actions[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"
GIT_TIMEOUT_SECONDS = 300
MAX_CHANGELOG_BYTES = 8 * 1024
_TAG_RE = re.compile(r"^refs/tags/v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(\^\{\})?$")
_CHANGELOG_HEADING = re.compile(r"^## v?(\d+)\.(\d+)\.(\d+)\b", re.M)
_PIN_LINE = {key: re.compile(rf'^{key}\s*=\s*"[^"\n]*"[ \t]*$', re.M) for key in ("version", "commit")}

Version = tuple[int, int, int]


class SyncError(RuntimeError):
    pass


def fmt(v: Version) -> str:
    return ".".join(map(str, v))


def parse_version(text: str) -> Version:
    parts = text.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise SyncError(f"'{text}' is not a MAJOR.MINOR.PATCH version")
    return int(parts[0]), int(parts[1]), int(parts[2])


# --- git -------------------------------------------------------------------

def child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """The environment for git and for the target release's vstd: no tokens, no inherited git settings."""
    env = {k: v for k, v in os.environ.items() if "TOKEN" not in k.upper() and not k.startswith("GIT_")}
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.update(extra or {})
    return env


def git_auth_env(token: str | None) -> dict[str, str]:
    """Credentials for github.com only, passed through the environment so they never appear in argv."""
    if not token:
        return {}
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
        "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}",
    }


def git(args: list[str], cwd: Path | None = None, env: dict[str, str] | None = None, stdin: bytes | None = None) -> str:
    try:
        proc = subprocess.run(
            ["git", *args], cwd=cwd, env=child_env(env), input=stdin, capture_output=True, timeout=GIT_TIMEOUT_SECONDS
        )
    except subprocess.TimeoutExpired:
        raise SyncError(f"git {args[0]} timed out") from None
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        raise SyncError(f"git {args[0]} failed: {detail[-1] if detail else 'exit ' + str(proc.returncode)}")
    return proc.stdout.decode("utf-8", "replace").strip()


def list_releases(url: str) -> dict[Version, str]:
    """Release tags vX.Y.Z and the commit each points at (annotated tags are peeled)."""
    out = git(["ls-remote", "--tags", url, "refs/tags/v*"])
    found: dict[Version, str] = {}
    peeled: dict[Version, str] = {}
    for line in out.splitlines():
        sha, _, ref = line.partition("\t")
        m = _TAG_RE.match(ref)
        if not m:
            continue
        v = (int(m[1]), int(m[2]), int(m[3]))
        (peeled if m[4] else found)[v] = sha
    found.update(peeled)
    return found


def choose_target(current: Version, releases: dict[Version, str], policy: str) -> tuple[Version, Version | None]:
    """Return (target, newest major that needs a manual upgrade or None)."""
    newer_major = max((v for v in releases if v[0] > current[0]), default=None)
    if policy == "manual":
        return current, newer_major
    if policy == "patch":
        allowed = [v for v in releases if v[:2] == current[:2] and v >= current]
    else:  # minor
        allowed = [v for v in releases if v[0] == current[0] and v >= current]
    return max(allowed, default=current), newer_major


def fetch_release(url: str, version: Version, sha: str, dest: Path) -> Path:
    tag = f"v{fmt(version)}"
    git(["init", "-q", str(dest)])
    git(["fetch", "-q", "--depth", "1", "--no-tags", url, f"refs/tags/{tag}:refs/tags/{tag}"], cwd=dest)
    got = git(["rev-parse", f"refs/tags/{tag}^{{commit}}"], cwd=dest)
    if got != sha:
        raise SyncError(f"{tag} resolved to {got} on fetch but {sha} when listed; refusing")
    git(["-c", "advice.detachedHead=false", "checkout", "-q", "--detach", sha], cwd=dest)
    if not (dest / "vstd" / "main.py").is_file():
        raise SyncError(f"{tag} has no vstd/main.py")
    return dest


# --- rendering in a scratch copy -------------------------------------------

def set_pin(text: str, version: Version, commit: str) -> str:
    for key, value in (("version", fmt(version)), ("commit", commit)):
        pattern = _PIN_LINE[key]
        if len(pattern.findall(text)) != 1:
            raise SyncError(f"{config_mod.CONFIG_PATH}: expected exactly one '{key} = \"...\"' line to update")
        text = pattern.sub(f'{key} = "{value}"', text)
    return text


def owned(rel: str) -> bool:
    return rel == config_mod.CONFIG_PATH.as_posix() or Path(rel).name in WRITABLE_NAMES


def _files(root: Path) -> dict[str, Path]:
    out = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in filenames:
            p = Path(dirpath) / name
            if p.is_file() and not p.is_symlink():
                out[p.relative_to(root).as_posix()] = p
    return out


def changed_files(original: Path, work: Path) -> dict[str, bytes]:
    changes = {}
    for rel, path in _files(work).items():
        new = path.read_bytes()
        old_path = original / rel
        old = old_path.read_bytes() if old_path.is_file() and not old_path.is_symlink() else None
        if new != old:
            if not owned(rel):
                raise SyncError(f"the release wrote {rel}, which vstd doesn't own; refusing")
            changes[rel] = new
    return changes


def tool(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-I", str(root / "vstd" / "main.py"), *args],
        env=child_env(),
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
    )


def render_diff(original: Path, changes: dict[str, bytes]) -> str:
    out = []
    for rel, new in sorted(changes.items()):
        old_path = original / rel
        old = old_path.read_text(encoding="utf-8", errors="replace") if old_path.is_file() else ""
        out.extend(
            difflib.unified_diff(
                old.splitlines(keepends=True), new.decode("utf-8", "replace").splitlines(keepends=True), f"a/{rel}", f"b/{rel}"
            )
        )
    return "".join(out)


# --- PR body ---------------------------------------------------------------

def rule_changes(old: RuleSet, new: RuleSet) -> dict[str, list[str]]:
    a, b = old.rules, new.rules
    return {
        "added": sorted(set(b) - set(a)),
        "removed": sorted(set(a) - set(b)),
        "changed": sorted(i for i in set(a) & set(b) if (a[i].level, a[i].text) != (b[i].level, b[i].text)),
    }


def changelog_excerpt(text: str, current: Version, target: Version) -> str:
    heads = list(_CHANGELOG_HEADING.finditer(text))
    parts = []
    for i, m in enumerate(heads):
        v = (int(m[1]), int(m[2]), int(m[3]))
        if current < v <= target:
            end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
            parts.append(text[m.start() : end].strip())
    excerpt = "\n\n".join(parts)
    if len(excerpt.encode()) > MAX_CHANGELOG_BYTES:
        excerpt = excerpt.encode()[:MAX_CHANGELOG_BYTES].decode("utf-8", "ignore") + "\n\n(truncated; see CHANGELOG.md)"
    return excerpt


def pr_body(current: Version, target: Version, newer_major: Version | None, changes: dict[str, bytes],
            excerpt: str, rules: dict[str, list[str]] | None, check_ok: bool) -> str:
    lines = []
    if target == current:
        lines.append(f"Re-renders Venuvra standards v{fmt(current)} to match `.venuvra/standards.toml`.")
    else:
        lines.append(f"Upgrades Venuvra standards from v{fmt(current)} to v{fmt(target)}.")
    lines += ["", "Files:"] + [f"- `{rel}`" for rel in sorted(changes)]
    if rules is not None and target != current:
        lines += ["", "Rule IDs:"]
        for kind in ("added", "changed", "removed"):
            lines.append(f"- {kind}: {', '.join(rules[kind]) if rules[kind] else 'none'}")
    breaking = [ln.strip() for ln in excerpt.splitlines() if "BREAKING" in ln]
    if breaking:
        lines += ["", "**BREAKING:**"] + [f"- {ln.lstrip('-* ').strip()}" for ln in breaking]
    if excerpt:
        lines += ["", "<details><summary>Changelog</summary>", "", excerpt, "", "</details>"]
    if newer_major:
        lines += ["", f"v{fmt(newer_major)} is available. Majors are never proposed automatically; change `version` and `commit` by hand to adopt it."]
    lines += [
        "",
        f"`vstd check` on this branch: {'passed' if check_ok else 'FAILED, see the standards/check status'}.",
        "This PR was opened with the workflow's GITHUB_TOKEN, so other workflows don't run on it; "
        "the `standards/check` status reports the result instead. Review it and merge it by hand; vstd never merges.",
    ]
    return "\n".join(lines) + "\n"


# --- the run ---------------------------------------------------------------

@dataclass
class Result:
    current: Version
    target: Version
    changes: dict[str, bytes] = field(default_factory=dict)
    diff: str = ""
    check_ok: bool = True
    pushed: str | None = None
    pr: github.PullRequest | None = None
    messages: list[str] = field(default_factory=list)


def run(
    repo: Path | str,
    *,
    standards_root: Path,
    tool_version: str,
    dry_run: bool = False,
    github_repo: str | None = None,
    token: str | None = None,
    base: str | None = None,
    central_url: str = CENTRAL_URL,
    push_url: str | None = None,
    api_url: str = github.API_URL,
    target_url: str | None = None,
) -> Result:
    repo = Path(repo).resolve()
    standards_root = Path(standards_root)
    current_rules = load_rules(standards_root / "rules")
    loaded = config_mod.load(repo, current_rules)
    if not loaded.ok:
        raise SyncError("; ".join(loaded.errors))
    cfg = loaded.config
    if cfg.version != tool_version and ".dev" not in tool_version:
        raise SyncError(f"standards.toml pins v{cfg.version} but vstd {tool_version} is running; check out the pinned commit")

    current = parse_version(cfg.version)
    releases = list_releases(central_url)
    if current not in releases:
        raise SyncError(f"v{cfg.version} is not a release of {central_url}")
    if releases[current] != cfg.commit:
        raise SyncError(f"pin mismatch: v{cfg.version} is {releases[current]} but standards.toml says {cfg.commit}")
    target, newer_major = choose_target(current, releases, cfg.upgrade)
    result = Result(current, target)

    with tempfile.TemporaryDirectory(prefix="vstd-sync-") as tmp:
        tmp = Path(tmp)
        work = tmp / "work"
        shutil.copytree(repo, work, symlinks=True, ignore=shutil.ignore_patterns(*SKIP_DIRS))
        renderer = standards_root
        if target != current:
            renderer = fetch_release(central_url, target, releases[target], tmp / "release")
            cfg_path = work / config_mod.CONFIG_PATH
            cfg_path.write_text(set_pin(cfg_path.read_text(encoding="utf-8"), target, releases[target]), encoding="utf-8")

        proc = tool(renderer, "sync", "--local", "--repo", str(work))
        if proc.returncode != 0:
            raise SyncError(f"v{fmt(target)} could not render this repository:\n{(proc.stdout + proc.stderr).strip()}")
        result.changes = changed_files(repo, work)
        result.check_ok = tool(renderer, "check", "--repo", str(work)).returncode == 0
        result.diff = render_diff(repo, result.changes)

        if not result.changes:
            result.messages.append(f"Up to date with v{fmt(target)}; nothing to do.")
            if newer_major:
                result.messages.append(f"v{fmt(newer_major)} is available but majors need a manual upgrade.")
            return result
        if dry_run:
            result.messages.append(f"Dry run: {len(result.changes)} file(s) would change; nothing was written.")
            return result

        rules = None
        excerpt = ""
        if target != current:
            try:
                rules = rule_changes(current_rules, load_rules(renderer / "rules"))
            except RuleError:
                rules = None
            log = renderer / "CHANGELOG.md"
            if log.is_file() and not log.is_symlink():
                excerpt = changelog_excerpt(log.read_bytes()[: 64 * 1024].decode("utf-8", "replace"), current, target)
        body = pr_body(current, target, newer_major, result.changes, excerpt, rules, result.check_ok)
        title = f"Update Venuvra standards to v{fmt(target)}" if target != current else f"Re-sync Venuvra standards v{fmt(target)}"
        _publish(repo, tmp, result, title, body, github_repo, token, base, push_url, api_url, target_url)
    return result


def _publish(repo, tmp, result, title, body, github_repo, token, base, push_url, api_url, target_url) -> None:
    if not github_repo or not github.valid_repo(github_repo):
        raise SyncError("GITHUB_REPOSITORY must be set to owner/name to open a PR (or use --dry-run)")
    client = github.Client(github_repo, token or "", api_url)
    push_url = push_url or f"https://github.com/{github_repo}.git"
    auth = git_auth_env(token) if push_url.startswith("https://github.com/") else {}
    base = base or git(["symbolic-ref", "--short", "HEAD"], cwd=repo)

    # Build the commit in a private index: the working tree and real index stay untouched.
    index = {"GIT_INDEX_FILE": str(tmp / "index")}
    head = git(["rev-parse", "HEAD"], cwd=repo)
    git(["read-tree", head], cwd=repo, env=index)
    for rel, data in sorted(result.changes.items()):
        blob = git(["hash-object", "-w", "--stdin"], cwd=repo, stdin=data)
        git(["update-index", "--add", "--cacheinfo", f"100644,{blob},{rel}"], cwd=repo, env=index)
    tree = git(["write-tree"], cwd=repo, env=index)

    remote = git(["ls-remote", push_url, f"refs/heads/{BRANCH}"], cwd=repo, env=auth).split("\t", 1)[0] or None
    if remote:
        git(["fetch", "-q", "--no-tags", push_url, f"refs/heads/{BRANCH}"], cwd=repo, env=auth)
    if remote and git(["rev-parse", f"{remote}^{{tree}}"], cwd=repo) == tree:
        sha = remote
        result.messages.append(f"{BRANCH} already has these changes.")
    else:
        parents = []
        if remote:
            parents += ["-p", remote]
        if not remote or subprocess.run(["git", "merge-base", "--is-ancestor", head, remote], cwd=repo, env=child_env()).returncode != 0:
            parents += ["-p", head]
        who = {"GIT_AUTHOR_NAME": BOT_NAME, "GIT_AUTHOR_EMAIL": BOT_EMAIL, "GIT_COMMITTER_NAME": BOT_NAME, "GIT_COMMITTER_EMAIL": BOT_EMAIL}
        sha = git(["commit-tree", tree, *parents, "-m", title], cwd=repo, env=who)
        git(["push", "-q", push_url, f"{sha}:refs/heads/{BRANCH}"], cwd=repo, env=auth)  # fast-forward only
        result.pushed = sha

    pr = client.find_open_pr(BRANCH, base)
    created = pr is None
    if created:
        pr = client.create_pr(BRANCH, base, title, body)
        result.messages.append(f"Opened {pr.url}")
    elif (pr.title, pr.body) != (title, body):
        pr = client.update_pr(pr.number, title, body)
        result.messages.append(f"Updated {pr.url}")
    else:
        result.messages.append(f"{pr.url} is already up to date.")
    result.pr = pr
    if result.pushed or created:
        state = "success" if result.check_ok else "failure"
        client.set_status(sha, state, "vstd check passed" if result.check_ok else "vstd check found problems", target_url)

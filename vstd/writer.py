"""Apply rendered standards to a repository without touching project content.

``plan()`` is pure: it reads the repo and returns the exact new bytes for each
file it would change. ``apply()`` writes them atomically. Only AGENTS.md and
CLAUDE.md files are ever written, never through a symlink.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from vstd.config import Config
from vstd.markers import MarkerError, find_block
from vstd.render import CLAUDE_IMPORT, CLAUDE_MD, render_block, render_new_agents_md
from vstd.rules import RuleSet

MAX_FILE_BYTES = 64 * 1024
WRITABLE_NAMES = ("AGENTS.md", "CLAUDE.md")
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "vendor", "dist", "build", ".next", "__pycache__", ".vstd", ".terraform"}
CLAUDE_FILES = ("CLAUDE.md", ".claude/CLAUDE.md", "CLAUDE.local.md")


class WriterError(ValueError):
    pass


@dataclass(frozen=True)
class Change:
    path: str  # relative to the repo, POSIX style
    old: str | None
    new: str

    @property
    def created(self) -> bool:
        return self.old is None


def _safe_path(repo: Path, rel: str) -> Path:
    if rel.startswith("/") or ".." in Path(rel).parts:
        raise WriterError(f"{rel}: refusing a path outside the repository")
    path = repo / rel
    current = repo
    for part in Path(rel).parts:
        current = current / part
        if current.is_symlink():
            raise WriterError(f"{rel}: refusing to write through a symlink")
    if not path.resolve().is_relative_to(repo.resolve()):
        raise WriterError(f"{rel}: refusing a path outside the repository")
    return path


def _read(repo: Path, rel: str) -> str | None:
    path = _safe_path(repo, rel)
    if not path.exists():
        return None
    if not path.is_file():
        raise WriterError(f"{rel}: expected a regular file")
    data = path.read_bytes()
    if len(data) > MAX_FILE_BYTES:
        raise WriterError(f"{rel}: file is larger than {MAX_FILE_BYTES} bytes; refusing to rewrite it")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise WriterError(f"{rel}: not valid UTF-8; refusing to rewrite it") from None


def _with_import(existing: str, import_line: str) -> str:
    first = existing.splitlines()[0].strip() if existing else ""
    if first == import_line:
        return existing
    return f"{import_line}\n\n{existing}" if existing else f"{import_line}\n"


def plan_agents_md(repo: Path, ruleset: RuleSet, config: Config) -> Change | None:
    old = _read(repo, "AGENTS.md")
    if old is None:
        return Change("AGENTS.md", None, render_new_agents_md(ruleset, config))
    try:
        block = find_block(old)
    except MarkerError as exc:
        raise WriterError(f"AGENTS.md: {exc}; fix the markers by hand or restore the file from Git") from None
    new_block = render_block(ruleset, config)
    if block is None:
        new = new_block + "\n" + old
    else:
        if not block.intact:
            raise WriterError(
                "AGENTS.md: the managed block was edited by hand (hash mismatch); "
                "move project rules below the END marker, then restore the block with 'git checkout' or delete it and re-run"
            )
        new = old[: block.start] + new_block + old[block.end :]
    return None if new == old else Change("AGENTS.md", old, new)


def plan_claude_md(repo: Path) -> Change | None:
    root = _read(repo, "CLAUDE.md")
    if root is None:
        # Only look at .claude/ when it is the file we'd change; a symlinked .claude
        # next to a real CLAUDE.md is none of our business.
        dot = _read(repo, ".claude/CLAUDE.md")
        if dot is not None:
            new = _with_import(dot, "@../AGENTS.md")
            return None if new == dot else Change(".claude/CLAUDE.md", dot, new)
        return Change("CLAUDE.md", None, CLAUDE_MD)
    new = _with_import(root, CLAUDE_IMPORT)
    return None if new == root else Change("CLAUDE.md", root, new)


def nested_agents_dirs(repo: Path) -> list[str]:
    """Directories (relative, POSIX) below the root that hold an AGENTS.md."""
    found = []
    for dirpath, dirnames, filenames in os.walk(repo, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        rel = Path(dirpath).relative_to(repo)
        if rel != Path(".") and "AGENTS.md" in filenames:
            found.append(rel.as_posix())
    return found


def plan_nested_parity(repo: Path) -> list[Change]:
    changes = []
    for d in nested_agents_dirs(repo):
        if any((repo / d / name).exists() for name in (".claude/CLAUDE.md", "CLAUDE.local.md")):
            continue
        rel = f"{d}/CLAUDE.md"
        old = _read(repo, rel)
        new = _with_import(old or "", CLAUDE_IMPORT)
        if new != old:
            changes.append(Change(rel, old, new))
    return changes


def _umask() -> int:
    current = os.umask(0)
    os.umask(current)
    return current


def plan(repo: Path | str, ruleset: RuleSet, config: Config) -> list[Change]:
    repo = Path(repo)
    changes = [c for c in (plan_agents_md(repo, ruleset, config), plan_claude_md(repo)) if c]
    if config.nested_parity:
        changes += plan_nested_parity(repo)
    for c in changes:
        if Path(c.path).name not in WRITABLE_NAMES:
            raise WriterError(f"{c.path}: not a file vstd may write")
        if len(c.new.encode("utf-8")) > MAX_FILE_BYTES:
            raise WriterError(f"{c.path}: result would exceed {MAX_FILE_BYTES} bytes")
    return changes


def apply(repo: Path | str, changes: list[Change]) -> None:
    repo = Path(repo)
    for c in changes:
        path = _safe_path(repo, c.path)
        current = path.read_bytes().decode("utf-8") if path.exists() else None
        if current != c.old:
            raise WriterError(f"{c.path}: changed since it was read; re-run")
        path.parent.mkdir(parents=True, exist_ok=True)
        # mkstemp creates 0600; keep an existing file's mode, else use the umask default.
        mode = path.stat().st_mode & 0o777 if path.exists() else 0o666 & ~_umask()
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".vstd-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
                fh.write(c.new)
            os.chmod(tmp, mode)
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

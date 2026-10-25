"""Draft a repository's check commands from its own files, for the project section.

Only commands the repository already declares are listed: package.json scripts,
Makefile targets, tools configured in pyproject.toml, and one-line ``run:`` steps
in its CI workflows. Nothing is guessed or executed. The result is a draft that
a reviewer confirms in the onboarding PR.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

MAX_FILE_BYTES = 256 * 1024
MAX_CI_COMMANDS = 12
# package.json scripts and Makefile targets worth listing, in this order.
CHECK_NAMES = ("format", "fmt", "lint", "typecheck", "type-check", "check", "test", "test:unit", "test:e2e", "e2e", "build")
_MAKE_TARGET_RE = re.compile(r"^([A-Za-z0-9_.:-]+)\s*:(?!=)")
_RUN_RE = re.compile(r"^\s*(?:-\s+)?run:\s*(\S.*?)\s*$")


def _text(path: Path) -> str | None:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_FILE_BYTES:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None  # unreadable files simply contribute no commands


def _package_manager(folder: Path) -> str:
    for lock, tool in (("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"), ("bun.lockb", "bun"), ("bun.lock", "bun")):
        if (folder / lock).is_file():
            return tool
    return "npm"


def _from_package_json(folder: Path) -> list[str]:
    text = _text(folder / "package.json")
    try:
        scripts = (json.loads(text) if text else {}).get("scripts") or {}
    except (ValueError, AttributeError):
        return []  # not valid JSON or not an object: nothing to list
    if not isinstance(scripts, dict):
        return []
    pm = _package_manager(folder)
    out = []
    for name in CHECK_NAMES:
        if name in scripts:
            if pm == "npm" and name not in ("test",):
                out.append(f"npm run {name}")
            else:
                out.append(f"{pm} {name}")
    return out


def _from_makefile(folder: Path) -> list[str]:
    text = _text(folder / "Makefile")
    targets = {m.group(1) for line in (text or "").splitlines() if (m := _MAKE_TARGET_RE.match(line))}
    return [f"make {name}" for name in CHECK_NAMES if name in targets]


def _from_pyproject(folder: Path) -> list[str]:
    text = _text(folder / "pyproject.toml")
    try:
        tool = (tomllib.loads(text) if text else {}).get("tool") or {}
    except tomllib.TOMLDecodeError:
        return []  # invalid TOML: nothing to list
    out = []
    if "ruff" in tool:
        out += ["ruff format --check .", "ruff check ."]
    if "mypy" in tool:
        out.append("mypy")
    if "pytest" in tool:
        out.append("pytest")
    return out


def _from_workflows(repo: Path, skip: str) -> list[str]:
    out: list[str] = []
    folder = repo / ".github" / "workflows"
    if not folder.is_dir():
        return out
    for path in sorted(folder.glob("*.y*ml")):
        if path.name == skip:
            continue
        for line in (_text(path) or "").splitlines():
            m = _RUN_RE.match(line)
            # Block scalars (| or >) and expressions are CI plumbing, not commands a person runs.
            if not m or m.group(1)[0] in "|>" or "${{" in m.group(1):
                continue
            cmd = m.group(1).strip("'\"")
            if cmd not in out:
                out.append(cmd)
    return out[:MAX_CI_COMMANDS]


def detect_commands(repo: Path | str, workflow_name: str = "standards.yml") -> list[tuple[str, list[str]]]:
    """(source, commands) pairs, root first, then one level of subfolders, then CI."""
    repo = Path(repo)
    folders = [repo] + sorted(p for p in repo.iterdir() if p.is_dir() and not p.is_symlink() and not p.name.startswith(".")
                              and p.name not in ("node_modules", "vendor", "dist", "build"))
    found: list[tuple[str, list[str]]] = []
    for folder in folders:
        rel = folder.relative_to(repo).as_posix()
        where = "" if rel == "." else f"{rel}/"
        for name, reader in (("package.json", _from_package_json), ("Makefile", _from_makefile), ("pyproject.toml", _from_pyproject)):
            cmds = reader(folder)
            if cmds:
                found.append((f"{where}{name}", cmds))
    ci = _from_workflows(repo, workflow_name)
    if ci:
        found.append(("CI workflows", ci))
    return found


def project_section(found: list[tuple[str, list[str]]]) -> str:
    """Markdown for the project section: the drafted commands, or a note that none were found."""
    lines = ["## Checks", "", "Drafted by `vstd rollout` from this repository's own files. Confirm or correct them when reviewing.", ""]
    if not found:
        lines.append("No build or test commands were found in package.json, Makefile, pyproject.toml or the CI workflows. Add them here.")
        return "\n".join(lines) + "\n"
    for source, cmds in found:
        folder = source.rsplit("/", 1)[0] + "/" if "/" in source else ""
        lines.append(f"From `{source}`" + (f" (run in `{folder}`)" if folder else "") + ":")
        lines += [f"- `{c}`" for c in cmds]
        lines.append("")
    return "\n".join(lines)

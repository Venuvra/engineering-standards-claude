"""Onboard a repository (``vstd init``).

Writes ``.venuvra/standards.toml``, ``.github/workflows/standards.yml`` and the
first-run AGENTS.md / CLAUDE.md into the working tree, for a human to review
and push as a PR. GITHUB_TOKEN can't create workflow files, so this first PR
is always pushed by a person. Existing config or workflow files are kept unless
``--force`` is given; AGENTS.md and CLAUDE.md are merged, never replaced.
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from string import Template

from vstd import config as config_mod
from vstd import writer
from vstd.rules import RuleSet

WORKFLOW_PATH = ".github/workflows/standards.yml"
WORKFLOW_HEADER = "# Venuvra engineering standards. Installed by `vstd init`; don't edit by hand."
DETECT_DEPTH = 2  # the root and one level of subfolders, e.g. web/ and backend/
_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,100}$")

# Manifest file name -> stack. Only stacks the ruleset defines are suggested.
MANIFESTS = {
    "package.json": "typescript",
    "tsconfig.json": "typescript",
    "pnpm-lock.yaml": "typescript",
    "pyproject.toml": "python",
    "setup.py": "python",
    "setup.cfg": "python",
    "Pipfile": "python",
    "requirements.txt": "python",
    "uv.lock": "python",
    "poetry.lock": "python",
}


class InitError(ValueError):
    pass


@dataclass
class InitResult:
    stacks: tuple[str, ...]
    written: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)


def detect_stacks(repo: Path, ruleset: RuleSet) -> tuple[str, ...]:
    found = set()
    repo = Path(repo)
    for dirpath, dirnames, filenames in os.walk(repo, followlinks=False):
        depth = len(Path(dirpath).relative_to(repo).parts)
        if depth + 1 >= DETECT_DEPTH:
            dirnames[:] = []
        else:
            dirnames[:] = sorted(d for d in dirnames if d not in writer.SKIP_DIRS and not d.startswith("."))
        for name in filenames:
            if name in MANIFESTS:
                found.add(MANIFESTS[name])
            elif name.startswith("requirements") and name.endswith(".txt"):
                found.add("python")
    return tuple(sorted(s for s in found if s in ruleset.stacks))


def render_config(version: str, commit: str, stacks: tuple[str, ...], template: str) -> str:
    return Template(template).substitute(version=version, commit=commit, stacks=", ".join(f'"{s}"' for s in stacks))


def render_workflow(template: str, default_branch: str) -> str:
    if not _BRANCH_RE.match(default_branch) or ".." in default_branch:
        raise InitError(f"'{default_branch}' is not a branch name init will write into a workflow")
    if template.count("    branches: [main]\n") != 1 or not template.startswith(WORKFLOW_HEADER):
        raise InitError("the workflow template is not the expected shape")
    return template.replace("    branches: [main]\n", f"    branches: [{default_branch}]\n")


def _write(repo: Path, rel: str, text: str) -> None:
    path = writer._safe_path(repo, rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    writer._safe_path(repo, rel)  # re-check now that parents exist
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".vstd-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def init(
    repo: Path | str,
    ruleset: RuleSet,
    *,
    version: str,
    commit: str,
    standards_root: Path,
    stacks: tuple[str, ...] | None = None,
    default_branch: str = "main",
    force: bool = False,
) -> InitResult:
    repo = Path(repo)
    stacks = tuple(sorted(set(stacks))) if stacks is not None else detect_stacks(repo, ruleset)
    unknown = [s for s in stacks if s not in ruleset.stacks]
    if unknown:
        raise InitError(f"unknown stack(s): {', '.join(unknown)}; available: {', '.join(ruleset.stacks)}")
    result = InitResult(stacks)

    cfg_rel = config_mod.CONFIG_PATH.as_posix()
    cfg_text = render_config(version, commit, stacks, (standards_root / "templates" / "standards.toml").read_text(encoding="utf-8"))
    wf_text = render_workflow((standards_root / "templates" / "standards.yml").read_text(encoding="utf-8"), default_branch)

    # Validate before writing anything, so a bad version or commit leaves the repo untouched.
    parsed = config_mod.parse(cfg_text, ruleset)
    if not parsed.ok:
        raise InitError("; ".join(parsed.errors))

    for rel, text in ((cfg_rel, cfg_text), (WORKFLOW_PATH, wf_text)):
        path = writer._safe_path(repo, rel)
        if path.exists() and not force:
            result.kept.append(rel)
            continue
        _write(repo, rel, text)
        result.written.append(rel)

    # Render from the config actually on disk, which may be one the repo already had.
    loaded = config_mod.load(repo, ruleset)
    if not loaded.ok:
        raise InitError("; ".join(loaded.errors))
    changes = writer.plan(repo, ruleset, loaded.config)
    writer.apply(repo, changes)
    result.written += [c.path for c in changes]
    return result

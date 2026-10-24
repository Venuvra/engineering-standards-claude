"""A line-based lint for the workflows this repository ships (``vstd lint-workflows``).

Python's standard library has no YAML parser, so this checks known patterns
line by line instead of parsing. It is written for our own templates and
workflows, which keep to a plain block style; it is not a general YAML
linter. The rules (AC-15):

- no ``pull_request_target`` or ``workflow_run`` trigger;
- an explicit top-level ``permissions:``, and never ``write-all``;
- every ``uses:`` pinned to a full commit SHA (local ``./`` actions and
  ``docker://...@sha256:`` images excepted);
- no ``${{ ... }}`` expression inside a ``run:`` script; pass values through
  ``env:`` instead, so untrusted text never becomes shell code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

MAX_BYTES = 256 * 1024
_FORBIDDEN_TRIGGERS = re.compile(r"\b(pull_request_target|workflow_run)\b")
_TOP_PERMISSIONS = re.compile(r"^permissions\s*:")
_WRITE_ALL = re.compile(r"^\s*permissions\s*:\s*['\"]?write-all\b")
_USES = re.compile(r"^\s*(?:-\s+)?uses\s*:\s*['\"]?(?P<ref>[^\s'\"#]+)")
_SHA_REF = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_./-]+)?@[0-9a-f]{40}$")
_DOCKER_DIGEST = re.compile(r"^docker://[^@\s]+@sha256:[0-9a-f]{64}$")
_RUN = re.compile(r"^(?P<indent>\s*)(?:-\s+)?run\s*:\s*(?P<rest>.*)$")
_EXPR = re.compile(r"\$\{\{")


@dataclass(frozen=True)
class LintError:
    path: str
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.message}"


def _strip_comment(line: str) -> str:
    """Drop a trailing YAML comment. Good enough for our own files, which don't put '#' in quoted strings."""
    if line.lstrip().startswith("#"):
        return ""
    m = re.search(r"\s#", line)
    return line[: m.start()] if m else line


def lint_text(path: str, text: str) -> list[LintError]:
    errors: list[LintError] = []
    lines = text.splitlines()
    has_top_permissions = False
    run_indent: int | None = None  # indentation of the current block-scalar run: key

    for n, raw in enumerate(lines, start=1):
        # Inside a multi-line run: script, everything more indented than the key is shell.
        if run_indent is not None:
            if raw.strip() == "" or len(raw) - len(raw.lstrip()) > run_indent:
                if _EXPR.search(raw):
                    errors.append(LintError(path, n, "'${{' inside a run: script; pass the value through env: instead"))
                continue
            run_indent = None

        line = _strip_comment(raw)
        if not line.strip():
            continue
        if _FORBIDDEN_TRIGGERS.search(line):
            errors.append(LintError(path, n, f"'{_FORBIDDEN_TRIGGERS.search(line)[1]}' runs with secrets on untrusted code; it is not allowed"))
        if _TOP_PERMISSIONS.match(line):
            has_top_permissions = True
        if _WRITE_ALL.match(line):
            errors.append(LintError(path, n, "permissions: write-all; grant each scope explicitly"))
        m = _USES.match(line)
        if m:
            ref = m["ref"]
            if not (ref.startswith("./") or _SHA_REF.match(ref) or _DOCKER_DIGEST.match(ref)):
                errors.append(LintError(path, n, f"'{ref}' is not pinned to a full commit SHA"))
        m = _RUN.match(line)
        if m:
            rest = m["rest"].strip()
            if rest[:1] in ("|", ">"):
                # The column of the run key itself; script lines are indented further.
                run_indent = len(raw) - len(raw.lstrip()) + (2 if raw.lstrip().startswith("- ") else 0)
            elif _EXPR.search(raw):  # raw: Actions expands ${{ }} even after a shell '#'
                errors.append(LintError(path, n, "'${{' inside a run: script; pass the value through env: instead"))

    if not has_top_permissions:
        errors.append(LintError(path, 1, "no top-level 'permissions:'; set it explicitly (usually contents: read)"))
    return errors


def lint_paths(paths: list[Path]) -> list[LintError]:
    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            files += sorted(f for f in p.iterdir() if f.suffix in (".yml", ".yaml") and f.is_file() and not f.is_symlink())
        else:
            files.append(p)
    errors: list[LintError] = []
    for f in files:
        data = f.read_bytes()
        if len(data) > MAX_BYTES:
            errors.append(LintError(str(f), 1, f"larger than {MAX_BYTES} bytes"))
            continue
        errors += lint_text(f.as_posix(), data.decode("utf-8", "replace"))
    return errors

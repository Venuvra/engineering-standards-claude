"""Drift detection for a repository using the standards (``vstd check``).

Every finding names the file, the problem and a one-line fix. Errors fail the
check; warnings are reported but don't.
"""

from __future__ import annotations

import datetime as dt
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from vstd import config as config_mod
from vstd import writer
from vstd.markers import MarkerError, find_block
from vstd.rules import RuleSet

BLOCK_BUDGET = 16 * 1024
AGENTS_BUDGET = 24 * 1024
_SYNC_FIX = "run the standards workflow manually, or 'vstd sync' locally, and merge the PR"
_TRIPWIRE = re.compile(r"\b(ignore|ignored|skip|skipped|disable|disabled|except|exempt|override|overridden|does not apply|doesn't apply|n/a)\b", re.I)
_USES = re.compile(r"^\s*(?:-\s*)?uses:\s*['\"]?(?P<ref>[A-Za-z0-9._/@:-]+)")
_SHA = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class Finding:
    path: str
    problem: str
    fix: str

    def format(self, level: str) -> str:
        return f"{level} {self.path}: {self.problem}\n  fix: {self.fix}"


@dataclass
class Report:
    errors: list[Finding] = field(default_factory=list)
    warnings: list[Finding] = field(default_factory=list)
    refused: set[str] = field(default_factory=set)

    @property
    def ok(self) -> bool:
        return not self.errors

    def error(self, path, problem, fix):
        self.errors.append(Finding(path, problem, fix))

    def warn(self, path, problem, fix):
        self.warnings.append(Finding(path, problem, fix))

    def format(self) -> str:
        lines = [f.format("ERROR") for f in self.errors] + [f.format("WARN ") for f in self.warnings]
        status = "FAILED" if self.errors else "OK"
        lines.append(f"vstd check: {status} ({len(self.errors)} error(s), {len(self.warnings)} warning(s))")
        return "\n".join(lines)


def _read(repo: Path, rel: str, report: Report) -> str | None:
    """Read a file the way the writer would; a refused file becomes an error finding."""
    try:
        return writer._read(repo, rel)
    except writer.WriterError as exc:
        report.error(rel, str(exc).split(": ", 1)[-1], "replace it with a regular UTF-8 file inside the repository")
        report.refused.add(rel)
        return None


def _walk(repo: Path):
    for dirpath, dirnames, filenames in os.walk(repo, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in writer.SKIP_DIRS)
        rel = Path(dirpath).relative_to(repo)
        yield rel, filenames


def _rule_line_re(ruleset: RuleSet) -> re.Pattern:
    prefixes = "|".join(sorted({p.prefix for p in ruleset.profiles.values()}))
    return re.compile(rf"\[(?:{prefixes})-\d{{3}} (?:MUST|SHOULD)\]")


def check(repo: Path | str, ruleset: RuleSet, tool_version: str, today: dt.date | None = None) -> Report:
    repo = Path(repo)
    report = Report()

    result = config_mod.load(repo, ruleset, today)
    for e in result.errors:
        report.error(str(config_mod.CONFIG_PATH), e.split(": ", 1)[-1], "fix the value named above; see docs/overrides.md")
    for w in result.warnings:
        report.warn(str(config_mod.CONFIG_PATH), w.split(": ", 1)[-1], "renew or remove the override before it expires")
    cfg = result.config

    if cfg and cfg.version != tool_version:
        if ".dev" in tool_version:
            report.warn(str(config_mod.CONFIG_PATH), f"pins v{cfg.version} but a development build of vstd ({tool_version}) is running", "ignore for local development")
        else:
            report.error(str(config_mod.CONFIG_PATH), f"pins v{cfg.version} but vstd {tool_version} is running", "the workflow must check out the commit named in standards.toml")

    rule_line = _rule_line_re(ruleset)
    must_ids = {r.id for r in ruleset.rules.values() if r.locked}

    # AGENTS.md and its managed block.
    agents = _read(repo, "AGENTS.md", report)
    block = None
    if agents is None:
        if "AGENTS.md" not in report.refused:
            report.error("AGENTS.md", "missing", _SYNC_FIX)
    else:
        try:
            block = find_block(agents)
        except MarkerError as exc:
            report.error("AGENTS.md", str(exc), "restore the markers from Git history, or delete the broken block and re-sync")
        else:
            if block is None:
                report.error("AGENTS.md", "has no venuvra-standards block (not managed)", _SYNC_FIX)
            elif not block.intact:
                report.error("AGENTS.md", "the managed block was edited by hand (hash mismatch)", "move project rules below the END marker and restore the block from Git, then re-sync")
            else:
                if len((block.body).encode()) > BLOCK_BUDGET:
                    report.error("AGENTS.md", f"managed block is {len(block.body.encode())} bytes; the limit is {BLOCK_BUDGET}", "list fewer stacks or raise it centrally")
                if cfg and block.version != cfg.version:
                    report.error("AGENTS.md", f"block is v{block.version} but standards.toml pins v{cfg.version}", _SYNC_FIX)
        size = len(agents.encode())
        if size > AGENTS_BUDGET:
            report.error("AGENTS.md", f"is {size} bytes; the limit is {AGENTS_BUDGET} so Codex's 32 KiB default still loads nested files", "move detail into docs and link to it")
        outside = agents if block is None else agents[: block.start] + agents[block.end :]
        _tripwire(report, "AGENTS.md", outside, must_ids)

    # CLAUDE.md wrapper.
    root_claude = _read(repo, "CLAUDE.md", report)
    dot_claude = _read(repo, ".claude/CLAUDE.md", report)
    if root_claude is not None and dot_claude is not None:
        report.warn("CLAUDE.md", "both CLAUDE.md and .claude/CLAUDE.md exist; Claude Code loads both", "merge them into one file")
    if root_claude is None and dot_claude is None and not report.refused & {"CLAUDE.md", ".claude/CLAUDE.md"}:
        report.error("CLAUDE.md", "missing, so Claude Code gets no shared rules", _SYNC_FIX)
    for rel, text, expected in (("CLAUDE.md", root_claude, "@AGENTS.md"), (".claude/CLAUDE.md", dot_claude, "@../AGENTS.md")):
        if text is None:
            continue
        # The import is required only in the wrapper vstd manages; content checks apply to every file Claude loads.
        first = text.splitlines()[0].strip() if text.strip() else ""
        if first != expected and not (rel == ".claude/CLAUDE.md" and root_claude is not None):
            report.error(rel, f"line 1 must be '{expected}' so Claude Code loads the shared rules", _SYNC_FIX)
        if rule_line.search(text):
            report.error(rel, "contains rule ID lines; shared rules belong only in the AGENTS.md block", "delete those lines; Claude Code already gets them through the import")
        _tripwire(report, rel, text, must_ids)

    # Files Codex or Claude Code would read differently.
    for rel, filenames in _walk(repo):
        here = "" if rel == Path(".") else rel.as_posix() + "/"
        if "AGENTS.override.md" in filenames:
            report.error(f"{here}AGENTS.override.md", "makes Codex ignore AGENTS.md in this directory (Claude Code never reads it)", "delete it; keep personal overrides in ~/.codex")
        if here and "AGENTS.md" in filenames:
            report.warn(f"{here}AGENTS.md", "nested AGENTS.md (project-owned; Codex loads it only when started in this directory)", "set nested_parity = true so Claude Code loads it too")
        if rel.parts[:2] == (".claude", "rules"):
            for name in filenames:
                if name.endswith(".md") and rule_line.search(_read(repo, f"{here}{name}", report) or ""):
                    report.error(f"{here}{name}", "contains rule ID lines; Codex has no equivalent of .claude/rules", "keep shared rules in the AGENTS.md block only")

    # Anything sync would still change (stacks, overrides, nested parity, import).
    if cfg and block is not None and block.intact and block.version == cfg.version:
        try:
            pending = writer.plan(repo, ruleset, cfg)
        except writer.WriterError as exc:
            report.error("AGENTS.md", str(exc), _SYNC_FIX)
        else:
            reported = {f.path for f in report.errors}
            for c in pending:
                if c.path not in reported:
                    report.error(c.path, "is out of date with .venuvra/standards.toml", _SYNC_FIX)

    _check_workflow_pins(repo, report)
    return report


def _tripwire(report: Report, rel: str, text: str, must_ids: set[str]) -> None:
    for n, line in enumerate(text.splitlines(), start=1):
        ids = [i for i in must_ids if i in line]
        if ids and _TRIPWIRE.search(line):
            report.warn(rel, f"line {n} mentions locked rule {', '.join(sorted(ids))} next to an exception word", "MUST rules can't be relaxed locally; reword or raise it centrally")


def _check_workflow_pins(repo: Path, report: Report) -> None:
    wf = repo / ".github" / "workflows"
    if not wf.is_dir():
        return
    for path in sorted(wf.iterdir()):
        if path.suffix not in (".yml", ".yaml") or path.is_symlink() or not path.is_file():
            continue
        text = _read(repo, f".github/workflows/{path.name}", report)
        for n, line in enumerate((text or "").splitlines(), start=1):
            m = _USES.match(line)
            if not m:
                continue
            ref = m["ref"]
            if ref.startswith(("./", "docker://")) or "@" not in ref:
                continue
            if not _SHA.match(ref.rsplit("@", 1)[1]):
                report.warn(f".github/workflows/{path.name}", f"line {n}: '{ref}' is pinned to a tag or branch that can move", "pin it to a full commit SHA with a '# vX.Y.Z' comment")

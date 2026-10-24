"""Stop using the central standards (``vstd eject``), keeping every rule as plain text.

AGENTS.md keeps the block's content with the markers removed, so Codex and
Claude Code read the same rules as before, now owned by the repository.
CLAUDE.md keeps its ``@AGENTS.md`` import, which is plain Claude Code syntax.
The config and the standards workflow are removed; a workflow that doesn't
carry the ``vstd init`` header is left alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from vstd import config as config_mod
from vstd import writer
from vstd.init import WORKFLOW_HEADER, WORKFLOW_PATH
from vstd.markers import MarkerError, find_block


class EjectError(ValueError):
    pass


@dataclass
class EjectResult:
    written: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)


def eject(repo: Path | str) -> EjectResult:
    repo = Path(repo)
    result = EjectResult()

    agents = writer._read(repo, "AGENTS.md")
    if agents is not None:
        try:
            block = find_block(agents)
        except MarkerError as exc:
            raise EjectError(f"AGENTS.md: {exc}; fix the markers by hand first") from None
        if block is not None:
            new = agents[: block.start] + block.body + agents[block.end :]
            writer.apply(repo, [writer.Change("AGENTS.md", agents, new)])
            result.written.append("AGENTS.md")

    for rel in (config_mod.CONFIG_PATH.as_posix(), WORKFLOW_PATH):
        path = writer._safe_path(repo, rel)
        if not path.exists():
            continue
        if rel == WORKFLOW_PATH and not writer._read(repo, rel).startswith(WORKFLOW_HEADER):
            result.kept.append(rel)
            continue
        path.unlink()
        result.removed.append(rel)

    venuvra = repo / ".venuvra"
    if venuvra.is_dir() and not venuvra.is_symlink() and not any(venuvra.iterdir()):
        venuvra.rmdir()
    return result

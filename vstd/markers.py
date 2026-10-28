"""Find and parse the venuvra-standards managed block in AGENTS.md."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

BEGIN_PREFIX = "<!-- BEGIN venuvra-standards "
END_LINE = "<!-- END venuvra-standards -->"
_BEGIN_RE = re.compile(
    r"^<!-- BEGIN venuvra-standards v(?P<version>\d+\.\d+\.\d+) sha256=(?P<hash>[0-9a-f]{64}) .*-->$"
)


class MarkerError(ValueError):
    pass


@dataclass(frozen=True)
class Block:
    version: str
    hash: str
    body: str  # text between the marker lines, each line ending in "\n"
    start: int  # character offset of the BEGIN line
    end: int  # character offset just past the END line's newline

    @property
    def intact(self) -> bool:
        # A Windows checkout (core.autocrlf) turns LF into CRLF; that is not an edit.
        return body_hash(self.body.replace("\r\n", "\n")) == self.hash


def body_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def find_block(text: str) -> Block | None:
    """Return the managed block, ``None`` if absent, or raise on broken markers."""
    lines = text.splitlines(keepends=True)
    begins = [i for i, l in enumerate(lines) if l.startswith(BEGIN_PREFIX)]
    ends = [i for i, l in enumerate(lines) if l.rstrip("\r\n") == END_LINE]
    if not begins and not ends:
        return None
    if len(begins) != 1 or len(ends) != 1:
        raise MarkerError(f"expected exactly one BEGIN and one END venuvra-standards marker, found {len(begins)} and {len(ends)}")
    b, e = begins[0], ends[0]
    if e < b:
        raise MarkerError("END venuvra-standards marker comes before BEGIN")
    m = _BEGIN_RE.match(lines[b].rstrip("\r\n"))
    if not m:
        raise MarkerError("BEGIN venuvra-standards marker is malformed")
    start = sum(len(l) for l in lines[:b])
    end = sum(len(l) for l in lines[: e + 1])
    body = "".join(lines[b + 1 : e])
    return Block(m["version"], m["hash"], body, start, end)

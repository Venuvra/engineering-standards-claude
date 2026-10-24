"""Parse and validate rule files under ``rules/``.

A rule file is TOML frontmatter between ``+++`` lines, followed by rule lines:

    - [SEC-001 MUST] Never commit secrets ...
      why: Optional rationale for humans; never rendered into repos.

Anything else after the frontmatter (apart from blank lines) is an error, so a
typo can't silently drop a rule.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

MAX_FILE_BYTES = 64 * 1024
MAX_RULE_CHARS = 160
LEVELS = ("MUST", "SHOULD")

# Core profiles render in this order; stacks follow, sorted by name.
CORE_ORDER = (
    "agent-conduct",
    "engineering",
    "security",
    "testing",
    "documentation",
    "git-workflow",
)

_RULE_RE = re.compile(
    r"^- \[(?P<id>(?P<prefix>[A-Z]+)-(?P<num>\d{3})) (?P<level>[A-Z]+)\] (?P<text>\S.*)$"
)
_WHY_RE = re.compile(r"^  why: (?P<why>\S.*)$")
_FRONTMATTER_KEYS = {"profile", "title", "prefix"}
_FORBIDDEN_IN_TEXT = ("<!--", "-->")


class RuleError(ValueError):
    """A rule file is malformed. ``str()`` names the file and line."""

    def __init__(self, path: Path | str, line: int | None, message: str):
        self.path = str(path)
        self.line = line
        self.message = message
        where = f"{self.path}:{line}" if line else self.path
        super().__init__(f"{where}: {message}")


@dataclass(frozen=True)
class Rule:
    id: str
    level: str
    text: str
    profile: str
    why: str | None = None
    path: str = ""
    line: int = 0

    @property
    def locked(self) -> bool:
        return self.level == "MUST"


@dataclass(frozen=True)
class Profile:
    name: str  # "core/security" or "stacks/typescript"
    title: str
    prefix: str
    rules: tuple[Rule, ...]
    path: str = ""

    @property
    def kind(self) -> str:
        return self.name.split("/", 1)[0]

    @property
    def short_name(self) -> str:
        return self.name.split("/", 1)[1]


@dataclass(frozen=True)
class RuleSet:
    profiles: dict[str, Profile]
    retired: frozenset[str]

    @property
    def rules(self) -> dict[str, Rule]:
        return {r.id: r for p in self.profiles.values() for r in p.rules}

    @property
    def stacks(self) -> tuple[str, ...]:
        return tuple(sorted(p.short_name for p in self.profiles.values() if p.kind == "stacks"))

    def core_profiles(self) -> list[Profile]:
        return [self.profiles[f"core/{n}"] for n in CORE_ORDER if f"core/{n}" in self.profiles]

    def stack_profile(self, stack: str) -> Profile:
        return self.profiles[f"stacks/{stack}"]

    def stack_of(self, rule_id: str) -> str | None:
        """Return the stack a rule belongs to, or None for core rules."""
        for p in self.profiles.values():
            if p.kind == "stacks" and any(r.id == rule_id for r in p.rules):
                return p.short_name
        return None


def _read_text(path: Path) -> str:
    if path.is_symlink():
        raise RuleError(path, None, "rule files must not be symlinks")
    data = path.read_bytes()
    if len(data) > MAX_FILE_BYTES:
        raise RuleError(path, None, f"file is larger than {MAX_FILE_BYTES} bytes")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuleError(path, None, f"not valid UTF-8: {exc}") from None
    # A Windows checkout may convert line endings; parse and render the same either way.
    return text.replace("\r\n", "\n")


def parse_profile(path: Path | str, text: str, expected_name: str | None = None) -> Profile:
    """Parse one rule file's text. ``expected_name`` is derived from its path."""
    lines = text.split("\n")
    if not lines or lines[0] != "+++":
        raise RuleError(path, 1, "file must start with a '+++' frontmatter line")
    try:
        end = lines.index("+++", 1)
    except ValueError:
        raise RuleError(path, 1, "frontmatter is not closed with '+++'") from None

    try:
        meta = tomllib.loads("\n".join(lines[1:end]))
    except tomllib.TOMLDecodeError as exc:
        raise RuleError(path, 2, f"invalid frontmatter: {exc}") from None
    unknown = set(meta) - _FRONTMATTER_KEYS
    if unknown:
        raise RuleError(path, 2, f"unknown frontmatter key(s): {', '.join(sorted(unknown))}")
    for key in sorted(_FRONTMATTER_KEYS):
        if not isinstance(meta.get(key), str) or not meta[key]:
            raise RuleError(path, 2, f"frontmatter needs a non-empty string '{key}'")
    name, title, prefix = meta["profile"], meta["title"], meta["prefix"]
    if not re.fullmatch(r"(core|stacks)/[a-z0-9-]+", name):
        raise RuleError(path, 2, f"profile '{name}' must look like core/<name> or stacks/<name>")
    if expected_name is not None and name != expected_name:
        raise RuleError(path, 2, f"profile '{name}' does not match its path (expected '{expected_name}')")
    if not re.fullmatch(r"[A-Z]{2,5}", prefix):
        raise RuleError(path, 2, f"prefix '{prefix}' must be 2-5 capital letters")

    rules: list[Rule] = []
    previous_was_rule = False
    for index in range(end + 1, len(lines)):
        lineno = index + 1
        line = lines[index]
        if line.strip() == "":
            previous_was_rule = False
            continue
        m = _RULE_RE.match(line)
        if m:
            if m["level"] not in LEVELS:
                raise RuleError(path, lineno, f"level '{m['level']}' must be MUST or SHOULD")
            if m["prefix"] != prefix:
                raise RuleError(path, lineno, f"{m['id']} does not use this file's prefix '{prefix}'")
            if m["num"] == "000":
                raise RuleError(path, lineno, f"{m['id']}: rule numbers start at 001")
            body = m["text"].rstrip()
            if len(body) > MAX_RULE_CHARS:
                raise RuleError(path, lineno, f"{m['id']} is {len(body)} characters; the limit is {MAX_RULE_CHARS}")
            if any(t in body for t in _FORBIDDEN_IN_TEXT):
                raise RuleError(path, lineno, f"{m['id']} must not contain HTML comment markers")
            rules.append(Rule(m["id"], m["level"], body, name, None, str(path), lineno))
            previous_was_rule = True
            continue
        w = _WHY_RE.match(line)
        if w and previous_was_rule:
            last = rules[-1]
            rules[-1] = Rule(last.id, last.level, last.text, last.profile, w["why"].rstrip(), last.path, last.line)
            previous_was_rule = False
            continue
        if line.lstrip().startswith("- ["):
            raise RuleError(path, lineno, "malformed rule line; expected '- [PREFIX-NNN MUST|SHOULD] text'")
        raise RuleError(path, lineno, "unexpected text; only rule lines, 'why:' lines and blank lines are allowed")

    seen: set[str] = set()
    for r in rules:
        if r.id in seen:
            raise RuleError(path, r.line, f"duplicate rule ID {r.id}")
        seen.add(r.id)
    return Profile(name, title, prefix, tuple(rules), str(path))


def load_retired(path: Path) -> frozenset[str]:
    if not path.exists():
        return frozenset()
    try:
        data = tomllib.loads(_read_text(path))
    except tomllib.TOMLDecodeError as exc:
        raise RuleError(path, None, f"invalid TOML: {exc}") from None
    unknown = set(data) - {"retired"}
    if unknown:
        raise RuleError(path, None, f"unknown key(s): {', '.join(sorted(unknown))}")
    ids = set()
    for entry in data.get("retired", []):
        if not isinstance(entry, dict) or set(entry) - {"id", "removed_in", "reason"} or not isinstance(entry.get("id"), str):
            raise RuleError(path, None, "each [[retired]] entry needs 'id' and may have 'removed_in' and 'reason'")
        ids.add(entry["id"])
    return frozenset(ids)


def load_rules(root: Path | str) -> RuleSet:
    """Load every profile under ``root`` (the ``rules/`` directory)."""
    root = Path(root)
    profiles: dict[str, Profile] = {}
    owner: dict[str, str] = {}
    prefixes: dict[str, str] = {}
    for kind in ("core", "stacks"):
        folder = root / kind
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir()):
            if path.suffix != ".md":
                raise RuleError(path, None, "only .md rule files belong here")
            if kind == "core" and path.stem not in CORE_ORDER:
                raise RuleError(path, None, f"unknown core profile '{path.stem}'; core profiles are {', '.join(CORE_ORDER)}")
            profile = parse_profile(path, _read_text(path), f"{kind}/{path.stem}")
            if profile.prefix in prefixes:
                raise RuleError(path, 2, f"prefix '{profile.prefix}' is already used by {prefixes[profile.prefix]}")
            prefixes[profile.prefix] = profile.name
            for rule in profile.rules:
                if rule.id in owner:
                    raise RuleError(path, rule.line, f"duplicate rule ID {rule.id} (also in {owner[rule.id]})")
                owner[rule.id] = str(path)
            profiles[profile.name] = profile
    retired = load_retired(root / "retired.toml")
    for rule_id in sorted(set(owner) & retired):
        raise RuleError(owner[rule_id], None, f"{rule_id} is retired and must not be reused")
    return RuleSet(profiles, retired)

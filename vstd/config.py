"""Load and validate a repository's ``.venuvra/standards.toml``.

All problems are collected and reported together, so one run shows everything
that needs fixing. Errors make the config unusable; warnings don't.
"""

from __future__ import annotations

import datetime as dt
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from vstd.rules import RuleSet

CONFIG_PATH = Path(".venuvra/standards.toml")
MAX_CONFIG_BYTES = 64 * 1024
SCHEMA = 1
UPGRADE_POLICIES = ("patch", "minor", "manual")
EXPIRY_WARNING_DAYS = 30

_TOP_KEYS = {"schema", "version", "commit", "upgrade", "stacks", "nested_parity", "overrides"}
_REQUIRED_TOP = ("schema", "version", "commit", "stacks")
_OVERRIDE_KEYS = {"rule", "scope", "replacement", "reason", "approved_by", "approved_on", "expires"}
_REQUIRED_OVERRIDE = ("rule", "replacement", "reason", "approved_by", "approved_on")
_VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")


@dataclass(frozen=True)
class Override:
    rule: str
    replacement: str
    reason: str
    approved_by: str
    approved_on: dt.date
    scope: str | None = None
    expires: dt.date | None = None


@dataclass(frozen=True)
class Config:
    version: str
    commit: str
    stacks: tuple[str, ...]
    upgrade: str = "minor"
    nested_parity: bool = False
    overrides: tuple[Override, ...] = ()
    schema: int = SCHEMA


@dataclass
class ConfigResult:
    config: Config | None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


class ConfigError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def _type_name(value) -> str:
    return type(value).__name__


def validate(data: dict, ruleset: RuleSet, today: dt.date | None = None) -> ConfigResult:
    """Validate parsed TOML ``data`` against ``ruleset``."""
    today = today or dt.date.today()
    errors: list[str] = []
    warnings: list[str] = []

    for key in sorted(set(data) - _TOP_KEYS):
        errors.append(f"unknown key '{key}'")
    for key in _REQUIRED_TOP:
        if key not in data:
            errors.append(f"missing required key '{key}'")

    schema = data.get("schema", SCHEMA)
    if not isinstance(schema, int) or isinstance(schema, bool) or schema != SCHEMA:
        errors.append(f"'schema' must be {SCHEMA}")

    version = data.get("version", "")
    if not isinstance(version, str) or not _VERSION_RE.match(version):
        errors.append(f"'version' must be an exact release like \"0.1.0\", got {version!r}")

    commit = data.get("commit", "")
    if not isinstance(commit, str) or not _COMMIT_RE.match(commit):
        errors.append("'commit' must be a full 40-character lowercase hex commit SHA")

    upgrade = data.get("upgrade", "minor")
    if upgrade not in UPGRADE_POLICIES:
        errors.append(f"'upgrade' must be one of {', '.join(UPGRADE_POLICIES)}, got {upgrade!r}")

    nested_parity = data.get("nested_parity", False)
    if not isinstance(nested_parity, bool):
        errors.append(f"'nested_parity' must be true or false, got {_type_name(nested_parity)}")

    stacks = data.get("stacks", [])
    stack_list: list[str] = []
    if not isinstance(stacks, list) or not all(isinstance(s, str) for s in stacks):
        errors.append("'stacks' must be a list of strings")
    else:
        for s in stacks:
            if s in stack_list:
                errors.append(f"stack '{s}' is listed twice")
            elif s not in ruleset.stacks:
                supported = ", ".join(ruleset.stacks) or "none"
                errors.append(f"stack '{s}' is not supported by this standards version (supported: {supported})")
            stack_list.append(s)

    overrides: list[Override] = []
    raw_overrides = data.get("overrides", [])
    if not isinstance(raw_overrides, list):
        errors.append("'overrides' must be an array of tables ([[overrides]])")
        raw_overrides = []
    rules = ruleset.rules
    seen: set[tuple[str, str | None]] = set()
    for i, raw in enumerate(raw_overrides, start=1):
        where = f"overrides[{i}]"
        if not isinstance(raw, dict):
            errors.append(f"{where} must be a table")
            continue
        for key in sorted(set(raw) - _OVERRIDE_KEYS):
            errors.append(f"{where}: unknown key '{key}'")
        missing = [k for k in _REQUIRED_OVERRIDE if k not in raw]
        for key in missing:
            errors.append(f"{where}: missing required key '{key}'")
        rule_id = raw.get("rule")
        label = f"{where} ({rule_id})" if isinstance(rule_id, str) else where
        for key in ("rule", "replacement", "reason", "approved_by"):
            if key in raw and (not isinstance(raw[key], str) or not raw[key].strip()):
                errors.append(f"{label}: '{key}' must be a non-empty string")
        if "scope" in raw and (not isinstance(raw["scope"], str) or not raw["scope"].strip()):
            errors.append(f"{label}: 'scope' must be a non-empty glob string")
        for key in ("approved_on", "expires"):
            if key in raw and (not isinstance(raw[key], dt.date) or isinstance(raw[key], dt.datetime)):
                errors.append(f"{label}: '{key}' must be a TOML date like 2026-11-02")
        if isinstance(raw.get("approved_by"), str) and raw["approved_by"].strip() and not _LOGIN_RE.match(raw["approved_by"]):
            errors.append(f"{label}: 'approved_by' must be a GitHub login")
        for key in ("replacement", "reason"):
            if isinstance(raw.get(key), str) and ("<!--" in raw[key] or "-->" in raw[key] or "\n" in raw[key]):
                errors.append(f"{label}: '{key}' must be one line without HTML comment markers")

        if isinstance(rule_id, str):
            if rule_id in ruleset.retired:
                errors.append(f"{label}: {rule_id} is retired; remove this override")
            elif rule_id not in rules:
                errors.append(f"{label}: unknown rule ID {rule_id}")
            else:
                rule = rules[rule_id]
                if rule.locked:
                    errors.append(f"{label}: {rule_id} is a MUST rule and is locked; change it centrally in engineering-standards")
                stack = ruleset.stack_of(rule_id)
                if stack is not None and stack not in stack_list:
                    errors.append(f"{label}: {rule_id} belongs to stack '{stack}', which this repo does not list")
            key = (rule_id, raw.get("scope"))
            if key in seen:
                errors.append(f"{label}: duplicate override for the same rule and scope")
            seen.add(key)

        expires = raw.get("expires")
        if isinstance(expires, dt.date) and not isinstance(expires, dt.datetime):
            if expires < today:
                errors.append(f"{label}: expired on {expires.isoformat()}; renew it or remove it")
            elif (expires - today).days <= EXPIRY_WARNING_DAYS:
                warnings.append(f"{label}: expires on {expires.isoformat()}")

        if not any(e.startswith(where) for e in errors):
            overrides.append(Override(
                rule=rule_id, replacement=raw["replacement"].strip(), reason=raw["reason"].strip(),
                approved_by=raw["approved_by"], approved_on=raw["approved_on"],
                scope=raw.get("scope"), expires=expires,
            ))

    if errors:
        return ConfigResult(None, errors, warnings)
    config = Config(
        version=version, commit=commit, stacks=tuple(stack_list), upgrade=upgrade,
        nested_parity=nested_parity, overrides=tuple(overrides), schema=schema,
    )
    return ConfigResult(config, errors, warnings)


def parse(text: str, ruleset: RuleSet, today: dt.date | None = None) -> ConfigResult:
    if len(text.encode("utf-8")) > MAX_CONFIG_BYTES:
        return ConfigResult(None, [f"config is larger than {MAX_CONFIG_BYTES} bytes"])
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        return ConfigResult(None, [f"invalid TOML: {exc}"])
    return validate(data, ruleset, today)


def load(repo: Path | str, ruleset: RuleSet, today: dt.date | None = None) -> ConfigResult:
    """Load ``.venuvra/standards.toml`` from ``repo``."""
    path = Path(repo) / CONFIG_PATH
    if not path.exists():
        return ConfigResult(None, [f"{CONFIG_PATH} is missing; run 'vstd init' to create it"])
    if path.is_symlink():
        return ConfigResult(None, [f"{CONFIG_PATH} must not be a symlink"])
    data = path.read_bytes()
    if len(data) > MAX_CONFIG_BYTES:
        return ConfigResult(None, [f"{CONFIG_PATH} is larger than {MAX_CONFIG_BYTES} bytes"])
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return ConfigResult(None, [f"{CONFIG_PATH} is not valid UTF-8"])
    result = parse(text, ruleset, today)
    result.errors = [f"{CONFIG_PATH}: {e}" for e in result.errors]
    result.warnings = [f"{CONFIG_PATH}: {w}" for w in result.warnings]
    return result

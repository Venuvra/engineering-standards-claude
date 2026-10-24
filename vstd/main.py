"""Command-line entry point: ``python3 -I path/to/vstd/main.py <command>``.

Run with ``-I`` so the target repository's files can't shadow stdlib modules.
That also stops Python adding this script's folder to ``sys.path``, so the
standards checkout is added explicitly below.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

STANDARDS_ROOT = Path(__file__).resolve().parent.parent
if str(STANDARDS_ROOT) not in sys.path:
    sys.path.insert(0, str(STANDARDS_ROOT))

from vstd import __version__  # noqa: E402
from vstd.check import check  # noqa: E402
from vstd.rules import RuleError, load_rules  # noqa: E402


def _summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"### vstd\n\n```text\n{text}\n```\n")


def cmd_check(args) -> int:
    ruleset = load_rules(STANDARDS_ROOT / "rules")
    report = check(Path(args.repo), ruleset, __version__)
    out = report.format()
    print(out)
    _summary(out)
    return 0 if report.ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vstd", description="Venuvra engineering standards")
    parser.add_argument("--version", action="version", version=f"vstd {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("check", help="detect drift and invalid configuration")
    p.add_argument("--repo", default=".", help="repository root (default: current directory)")
    p.set_defaults(func=cmd_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except RuleError as exc:
        print(f"ERROR standards rules are invalid: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

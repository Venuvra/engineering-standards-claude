"""Keep the public repo free of secrets and private Venuvra details (ES-11).

Scans what other repos and readers see: rules, docs, templates and the
top-level Markdown. Private repository names are stored as truncated SHA-256
hashes so this public file doesn't list them; add a name by appending
``sha256(name.lower())[:16]``, for the bare name when it is distinctive and
always for ``venuvra/<name>``.
"""

import hashlib
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCANNED_DIRS = ("rules", "docs", "templates")
SCANNED_FILES = ("README.md", "CHANGELOG.md", "AGENTS.md", "CLAUDE.md", ".venuvra/standards.toml")

PRIVATE_NAME_HASHES = {
    "615fe4619045fc85", "6c42a85075d8a891", "02ca275c89dd043f", "89143bb48b8faa5c", "c4bb736e765491dc",
    "5b3c7e0a01e33aba", "1b5f0e8b67c25561", "5c603eb2c3a65e7d", "09c6cdc1f2270e7c",
}

SECRET_PATTERNS = {
    "AWS access key ID": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})\b"),
    "Slack token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    "API secret key": re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}\b"),
    "private key": re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----"),
    "credential assignment": re.compile(r"(?i)\b(?:password|passwd|secret|api_?key|token)\s*[:=]\s*['\"][^'\"\s]{8,}['\"]"),
    "credentials in URL": re.compile(r"\b[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@"),
}
_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)?")


def _hash(token: str) -> str:
    return hashlib.sha256(token.lower().encode()).hexdigest()[:16]


def scan_text(rel: str, text: str) -> list[str]:
    problems = []
    for n, line in enumerate(text.splitlines(), start=1):
        for name, pattern in SECRET_PATTERNS.items():
            if pattern.search(line):
                problems.append(f"{rel}:{n}: looks like a {name}")
        for token in _WORD.findall(line):
            candidates = {token.rstrip(".")}
            candidates.update(token.split("/"))
            if any(_hash(c) in PRIVATE_NAME_HASHES for c in candidates if c):
                problems.append(f"{rel}:{n}: names a private Venuvra repository")
    return problems


def scanned_files() -> list[Path]:
    files = [ROOT / f for f in SCANNED_FILES if (ROOT / f).is_file()]
    for d in SCANNED_DIRS:
        files += sorted(p for p in (ROOT / d).rglob("*") if p.is_file())
    return files


class ContentScanTest(unittest.TestCase):
    def test_public_content_is_clean(self):
        problems = []
        for path in scanned_files():
            problems += scan_text(path.relative_to(ROOT).as_posix(), path.read_text(encoding="utf-8", errors="replace"))
        self.assertEqual(problems, [])

    def test_scanner_catches_secret_shapes(self):
        # Built at runtime so this file holds no secret-shaped literals.
        samples = [
            "AKIA" + "A" * 16,
            "ghp_" + "a1" * 18,
            "xoxb-" + "1234567890-abc",
            "sk-" + "x" * 24,
            "-----BEGIN RSA " + "PRIVATE KEY-----",
            'password = "' + "hunter2hunter2" + '"',
            "https://user:" + "pw" + "@example.com/x",
        ]
        for sample in samples:
            with self.subTest(sample[:12]):
                self.assertTrue(scan_text("x.md", sample), sample)

    def test_scanner_catches_private_names_but_not_ordinary_words(self):
        self.assertTrue(scan_text("x.md", "See " + "Venuvra/" + "launch" + "pad for deploys."))
        self.assertTrue(scan_text("x.md", "the " + "infra" + "forge API"))
        self.assertEqual(scan_text("x.md", "Run the backend tests; a launchpad of ideas; MongoDB Atlas."), [])

    def test_scan_covers_rules_and_docs(self):
        rels = {p.relative_to(ROOT).as_posix() for p in scanned_files()}
        self.assertIn("rules/core/security.md", rels)
        self.assertIn("docs/adopting.md", rels)
        self.assertIn("templates/standards.yml", rels)


if __name__ == "__main__":
    unittest.main()

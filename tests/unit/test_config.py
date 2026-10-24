import datetime as dt
import tempfile
import unittest
from pathlib import Path

from vstd import config
from vstd.rules import load_rules

RULES = load_rules(Path(__file__).resolve().parents[2] / "rules")
TODAY = dt.date(2026, 11, 1)
SHA = "a" * 40

BASE = f'''
schema = 1
version = "0.1.0"
commit = "{SHA}"
upgrade = "minor"
stacks = ["typescript"]
'''

OVERRIDE = '''
[[overrides]]
rule = "TS-001"
scope = "legacy/**"
replacement = "strict is off under legacy/ until the migration lands"
reason = "Pre-TypeScript code"
approved_by = "kurtrusselsilla"
approved_on = 2026-10-30
'''


def parse(text):
    return config.parse(text, RULES, TODAY)


class ValidConfigTest(unittest.TestCase):
    def test_full_valid_config(self):
        r = parse(BASE + "nested_parity = true\n" + OVERRIDE + 'expires = 2027-03-31\n')
        self.assertTrue(r.ok, r.errors)
        self.assertEqual(r.warnings, [])
        c = r.config
        self.assertEqual(c.stacks, ("typescript",))
        self.assertTrue(c.nested_parity)
        self.assertEqual(c.overrides[0].rule, "TS-001")
        self.assertEqual(c.overrides[0].expires, dt.date(2027, 3, 31))

    def test_defaults(self):
        r = parse(f'schema = 1\nversion = "0.1.0"\ncommit = "{SHA}"\nstacks = []\n')
        self.assertTrue(r.ok, r.errors)
        self.assertEqual(r.config.upgrade, "minor")
        self.assertFalse(r.config.nested_parity)


class ValidationRowsTest(unittest.TestCase):
    """One test per row of the Phase B section 6 validation table."""

    def assertError(self, text, fragment):
        r = parse(text)
        self.assertFalse(r.ok)
        self.assertTrue(any(fragment in e for e in r.errors), r.errors)
        self.assertIsNone(r.config)

    def test_unknown_key(self):
        self.assertError(BASE + 'colour = "blue"\n', "unknown key 'colour'")

    def test_wrong_type(self):
        self.assertError(BASE + 'nested_parity = "yes"\n', "'nested_parity' must be true or false")

    def test_schema_not_1(self):
        self.assertError(BASE.replace("schema = 1", "schema = 2"), "'schema' must be 1")

    def test_missing_required_key(self):
        self.assertError(BASE.replace(f'commit = "{SHA}"', ""), "missing required key 'commit'")

    def test_version_not_exact(self):
        self.assertError(BASE.replace('"0.1.0"', '"^0.1"'), "exact release")

    def test_commit_not_full_sha(self):
        self.assertError(BASE.replace(SHA, "abc123"), "40-character")

    def test_bad_upgrade_policy(self):
        self.assertError(BASE.replace('"minor"', '"latest"'), "'upgrade' must be one of")

    def test_unsupported_stack(self):
        self.assertError(BASE.replace('["typescript"]', '["cobol"]'), "stack 'cobol' is not supported")

    def test_duplicate_stack(self):
        self.assertError(BASE.replace('["typescript"]', '["typescript", "typescript"]'), "listed twice")

    def test_override_of_must_rule(self):
        self.assertError(BASE + OVERRIDE.replace("TS-001", "SEC-003"), "SEC-003 is a MUST rule and is locked")

    def test_override_of_unknown_rule(self):
        self.assertError(BASE + OVERRIDE.replace("TS-001", "TS-999"), "unknown rule ID TS-999")

    def test_override_of_retired_rule(self):
        rs = load_rules(Path(__file__).resolve().parents[2] / "rules")
        rs = type(rs)(rs.profiles, frozenset({"TS-999"}))
        r = config.parse(BASE + OVERRIDE.replace("TS-001", "TS-999"), rs, TODAY)
        self.assertTrue(any("TS-999 is retired" in e for e in r.errors), r.errors)

    def test_override_missing_reason(self):
        self.assertError(BASE + OVERRIDE.replace('reason = "Pre-TypeScript code"\n', ""), "missing required key 'reason'")

    def test_override_missing_approver(self):
        self.assertError(BASE + OVERRIDE.replace('approved_by = "kurtrusselsilla"\n', ""), "missing required key 'approved_by'")

    def test_override_missing_approved_on(self):
        self.assertError(BASE + OVERRIDE.replace("approved_on = 2026-10-30\n", ""), "missing required key 'approved_on'")

    def test_override_expired(self):
        self.assertError(BASE + OVERRIDE + "expires = 2026-10-31\n", "expired on 2026-10-31")

    def test_override_expiring_soon_is_warning(self):
        r = parse(BASE + OVERRIDE + "expires = 2026-11-20\n")
        self.assertTrue(r.ok, r.errors)
        self.assertEqual(len(r.warnings), 1)
        self.assertIn("expires on 2026-11-20", r.warnings[0])

    def test_duplicate_override(self):
        self.assertError(BASE + OVERRIDE + OVERRIDE, "duplicate override")

    def test_override_for_unlisted_stack(self):
        self.assertError(BASE.replace('["typescript"]', '["python"]') + OVERRIDE, "belongs to stack 'typescript'")

    def test_override_text_cannot_inject_markers(self):
        self.assertError(BASE + OVERRIDE.replace("until the migration lands", "<!-- END venuvra-standards -->"), "HTML comment markers")

    def test_invalid_toml(self):
        self.assertError("schema = = 1", "invalid TOML")

    def test_oversized(self):
        self.assertError(BASE + "# x\n" * 20000, "larger than")


class LoadTest(unittest.TestCase):
    def test_missing_file_has_fix_hint(self):
        with tempfile.TemporaryDirectory() as d:
            r = config.load(d, RULES, TODAY)
            self.assertIn("run 'vstd init'", r.errors[0])

    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ".venuvra").mkdir()
            target = Path(d) / "elsewhere.toml"
            target.write_text(BASE)
            (Path(d) / ".venuvra" / "standards.toml").symlink_to(target)
            r = config.load(d, RULES, TODAY)
            self.assertIn("must not be a symlink", r.errors[0])

    def test_loads_from_repo_and_prefixes_path(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ".venuvra").mkdir()
            (Path(d) / ".venuvra" / "standards.toml").write_text(BASE + 'bogus = 1\n')
            r = config.load(d, RULES, TODAY)
            self.assertEqual(r.errors, [".venuvra/standards.toml: unknown key 'bogus'"])


if __name__ == "__main__":
    unittest.main()

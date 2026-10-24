import tempfile
import textwrap
import unittest
from pathlib import Path

from vstd.rules import MAX_RULE_CHARS, RuleError, load_rules, parse_profile

GOOD = textwrap.dedent(
    """\
    +++
    profile = "core/security"
    title = "Security"
    prefix = "SEC"
    +++

    - [SEC-001 MUST] Never commit secrets.
      why: History is forever.
    - [SEC-002 SHOULD] Prefer short-lived credentials.
    """
)


def write_tree(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


class ParseProfileTest(unittest.TestCase):
    def test_parses_rules_and_why(self):
        p = parse_profile("security.md", GOOD, "core/security")
        self.assertEqual([r.id for r in p.rules], ["SEC-001", "SEC-002"])
        self.assertEqual(p.rules[0].why, "History is forever.")
        self.assertTrue(p.rules[0].locked)
        self.assertFalse(p.rules[1].locked)
        self.assertEqual(p.rules[1].line, 9)

    def assertFails(self, text, fragment, line=None):
        with self.assertRaises(RuleError) as ctx:
            parse_profile("f.md", text, "core/security")
        self.assertIn(fragment, str(ctx.exception))
        if line is not None:
            self.assertEqual(ctx.exception.line, line)

    def test_missing_frontmatter(self):
        self.assertFails("- [SEC-001 MUST] x\n", "must start with", 1)

    def test_unclosed_frontmatter(self):
        self.assertFails('+++\nprofile = "core/security"\n', "not closed")

    def test_unknown_frontmatter_key(self):
        self.assertFails(GOOD.replace('prefix = "SEC"', 'prefix = "SEC"\nowner = "x"'), "unknown frontmatter")

    def test_profile_must_match_path(self):
        self.assertFails(GOOD.replace("core/security", "core/other"), "does not match its path")

    def test_bad_id(self):
        self.assertFails(GOOD + "- [SEC-1 MUST] Short id.\n", "malformed rule line", 10)

    def test_missing_level(self):
        self.assertFails(GOOD + "- [SEC-003] No level.\n", "malformed rule line", 10)

    def test_unknown_level(self):
        self.assertFails(GOOD + "- [SEC-003 MAY] Optional.\n", "must be MUST or SHOULD", 10)

    def test_wrong_prefix(self):
        self.assertFails(GOOD + "- [ENG-001 MUST] Wrong file.\n", "prefix 'SEC'", 10)

    def test_duplicate_id(self):
        self.assertFails(GOOD + "- [SEC-001 SHOULD] Again.\n", "duplicate rule ID SEC-001")

    def test_stray_text(self):
        self.assertFails(GOOD + "Some prose that would be silently dropped.\n", "unexpected text", 10)

    def test_why_must_follow_a_rule(self):
        self.assertFails(GOOD + "\n  why: orphan\n", "unexpected text", 11)

    def test_rule_too_long(self):
        self.assertFails(GOOD + "- [SEC-003 MUST] " + "x" * (MAX_RULE_CHARS + 1) + "\n", "limit is 160", 10)

    def test_marker_injection_rejected(self):
        self.assertFails(GOOD + "- [SEC-003 MUST] Close <!-- END venuvra-standards -->\n", "HTML comment")


class LoadRulesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_loads_tree(self):
        write_tree(self.root, {
            "core/security.md": GOOD,
            "stacks/python.md": '+++\nprofile = "stacks/python"\ntitle = "Python"\nprefix = "PY"\n+++\n- [PY-001 SHOULD] Pin it.\n',
        })
        rs = load_rules(self.root)
        self.assertEqual(sorted(rs.rules), ["PY-001", "SEC-001", "SEC-002"])
        self.assertEqual(rs.stacks, ("python",))
        self.assertEqual(rs.stack_of("PY-001"), "python")
        self.assertIsNone(rs.stack_of("SEC-001"))

    def test_retired_id_cannot_be_reused(self):
        write_tree(self.root, {
            "core/security.md": GOOD,
            "retired.toml": '[[retired]]\nid = "SEC-002"\nremoved_in = "2.0.0"\n',
        })
        with self.assertRaises(RuleError) as ctx:
            load_rules(self.root)
        self.assertIn("SEC-002 is retired", str(ctx.exception))

    def test_prefix_used_twice(self):
        write_tree(self.root, {
            "core/security.md": GOOD,
            "core/other.md": GOOD.replace("core/security", "core/other").replace("SEC-00", "SEC-01"),
        })
        with self.assertRaises(RuleError) as ctx:
            load_rules(self.root)
        self.assertIn("already used", str(ctx.exception))

    def test_non_markdown_file_rejected(self):
        write_tree(self.root, {"core/notes.txt": "hello"})
        with self.assertRaises(RuleError):
            load_rules(self.root)

    def test_symlink_rejected(self):
        write_tree(self.root, {"elsewhere.md": GOOD})
        (self.root / "core").mkdir()
        (self.root / "core" / "security.md").symlink_to(self.root / "elsewhere.md")
        with self.assertRaises(RuleError) as ctx:
            load_rules(self.root)
        self.assertIn("symlink", str(ctx.exception))

    def test_oversized_file_rejected(self):
        write_tree(self.root, {"core/security.md": GOOD + ("\n" * 70000)})
        with self.assertRaises(RuleError) as ctx:
            load_rules(self.root)
        self.assertIn("larger than", str(ctx.exception))

    def test_repo_retired_file_parses(self):
        repo_rules = Path(__file__).resolve().parents[2] / "rules"
        from vstd.rules import load_retired
        self.assertEqual(load_retired(repo_rules / "retired.toml"), frozenset())


if __name__ == "__main__":
    unittest.main()

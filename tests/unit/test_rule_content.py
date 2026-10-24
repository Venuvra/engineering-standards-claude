"""Guards for the committed rule content (AC-01)."""

import unittest
from pathlib import Path

from vstd.rules import load_rules

RULES = Path(__file__).resolve().parents[2] / "rules"

# Rendered-size budgets from the Phase B design. A rule renders as
# "- [ID LEVEL] text\n"; headings add a little, so budget on the raw lines.
CORE_BUDGET = 8 * 1024
STACK_BUDGET = 3 * 1024


def rendered_bytes(profile) -> int:
    lines = [f"## {profile.title}\n"] + [f"- [{r.id} {r.level}] {r.text}\n" for r in profile.rules]
    return len("".join(lines).encode("utf-8"))


class RuleContentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rs = load_rules(RULES)

    def test_core_profiles_present_in_order(self):
        names = [p.short_name for p in self.rs.core_profiles()]
        self.assertEqual(names, ["agent-conduct", "engineering", "security", "testing", "documentation", "git-workflow"])

    def test_counts_match_approved_standards(self):
        core = [r for p in self.rs.core_profiles() for r in p.rules]
        self.assertEqual(len(core), 45)
        self.assertEqual(sum(r.locked for r in core), 22)
        self.assertEqual(len(self.rs.stack_profile("typescript").rules), 12)
        self.assertEqual(len(self.rs.stack_profile("python").rules), 13)
        self.assertEqual(self.rs.stacks, ("python", "typescript"))

    def test_core_fits_budget(self):
        size = sum(rendered_bytes(p) for p in self.rs.core_profiles())
        self.assertLessEqual(size, CORE_BUDGET, f"core renders to {size} bytes")

    def test_each_stack_fits_budget(self):
        for stack in self.rs.stacks:
            size = rendered_bytes(self.rs.stack_profile(stack))
            self.assertLessEqual(size, STACK_BUDGET, f"{stack} renders to {size} bytes")

    def test_ids_are_sequential_per_profile(self):
        for p in self.rs.profiles.values():
            nums = [int(r.id.split("-")[1]) for r in p.rules]
            self.assertEqual(nums, list(range(1, len(nums) + 1)), p.name)


if __name__ == "__main__":
    unittest.main()

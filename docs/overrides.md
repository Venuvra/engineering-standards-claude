# Overrides

A repository can replace a **SHOULD** rule for a reason. **MUST** rules are locked:
`vstd check` rejects any override of one, and a MUST change happens centrally, in a MAJOR release.

```toml
[[overrides]]
rule = "TS-004"                    # a SHOULD rule ID from the pinned release
scope = "legacy/"                  # optional: where it applies (default: whole repo)
replacement = "legacy/ still uses npm until the pnpm migration lands."
reason = "Migration tracked in issue 123"
approved_by = "github-login"       # who approved it (a GitHub login)
approved_on = 2026-10-24
expires = 2027-01-31               # optional; check warns 30 days before and fails after
```

The override appears in the managed block under "Project overrides", so Codex and Claude
Code both see the replacement next to the rule it changes.

`vstd check` and sync refuse an override that:

- names a MUST rule, an unknown or retired rule ID, or a rule from a stack the repo doesn't list;
- repeats a rule and scope that is already overridden;
- has expired;
- is missing `rule`, `replacement`, `reason`, `approved_by` or `approved_on`, or has an unknown key;
- puts a newline or an HTML comment marker in its text, which could break out of the block.

Writing "ignore SEC-001" in the project section doesn't override anything. `check` warns
when project text puts a locked rule ID next to words like "ignore", "skip" or "exempt".
To change a MUST rule, open a PR here.

# Venuvra engineering standards

Central source of truth for the engineering rules that Venuvra repositories give to
AI coding assistants. Codex reads them from each repo's `AGENTS.md`; Claude Code reads
the same file through a one-line `@AGENTS.md` import in `CLAUDE.md`.

The generator and checker, `vstd`, use the Python 3.11+ standard library only.

## Status

Under construction (milestone M1). See the issues for the plan.

## Development

```sh
python3 -m unittest discover -s tests -t .
```

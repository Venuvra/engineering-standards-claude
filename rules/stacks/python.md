+++
profile = "stacks/python"
title = "Python"
prefix = "PY"
+++

- [PY-001 SHOULD] Target the version in `requires-python` and run CI on it.
- [PY-002 SHOULD] Declare dependencies in pyproject.toml with a lockfile or hashed requirements; no unpinned installs in CI.
- [PY-003 SHOULD] Type-annotate public functions and run the configured type checker in CI.
- [PY-004 SHOULD] Format and lint with the configured tool (ruff by default); don't hand-format.
- [PY-005 MUST] Never use `eval`, `exec`, `pickle` or `yaml.load` on untrusted data; use `yaml.safe_load`.
- [PY-006 MUST] Call `subprocess` with an argument list and `shell=False`.
- [PY-007 SHOULD] Raise specific exceptions; no bare `except:`; catch broad `Exception` only at a boundary that logs it.
- [PY-008 SHOULD] Use module-level loggers from `logging` (or the configured library); no `print` in library code.
- [PY-009 SHOULD] Validate external data at boundaries with pydantic or explicit checks.
- [PY-010 SHOULD] Use pytest with fixtures instead of global state; mark slow and integration tests.
- [PY-011 SHOULD] Change schemas only through migrations (for example Alembic); never edit a merged migration.
- [PY-012 SHOULD] Use timezone-aware UTC datetimes.
- [PY-013 SHOULD] Follow PEP 8 naming: snake_case functions and modules, PascalCase classes, UPPER_CASE constants.

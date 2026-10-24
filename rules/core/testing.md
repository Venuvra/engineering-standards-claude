+++
profile = "core/testing"
title = "Testing"
prefix = "TST"
+++

- [TST-001 MUST] Ship every behavior change with tests that fail without it.
- [TST-002 MUST] Include a regression test that reproduces the bug in every bug fix.
- [TST-003 SHOULD] Test persistence against the real database engine (for example Testcontainers); mock only third parties.
- [TST-004 SHOULD] Keep tests deterministic: control time, randomness and network.
- [TST-005 SHOULD] Run the project's check commands (see Project instructions) before opening a PR.
- [TST-006 MUST] Label evidence honestly as mocked, local, CI or deployed; never present one as another.

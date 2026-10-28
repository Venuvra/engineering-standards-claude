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
- [TST-007 SHOULD] Give every deployable project one command that runs all its checks (lint, types, tests, build) in a container with real services; that is the primary test gate.
- [TST-008 SHOULD] Build that test container to match the cloud deploy target: same base image, OS, CPU architecture, runtime and database versions; change both together.
- [TST-009 SHOULD] Treat hosted CI such as GitHub Actions as optional; where it runs, call the same container command, and report that command's result in every PR.

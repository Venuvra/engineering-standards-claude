+++
profile = "core/engineering"
title = "Engineering"
prefix = "ENG"
+++

- [ENG-001 SHOULD] Choose the simplest design that meets the requirement; add no speculative abstraction or infrastructure.
- [ENG-002 SHOULD] Follow the existing conventions of the module you edit over personal preference.
- [ENG-003 MUST] Handle every error explicitly; never swallow an exception or ignore an error result without a comment saying why.
- [ENG-004 SHOULD] Return safe, documented errors at API boundaries; keep internal details in server-side logs.
- [ENG-005 SHOULD] Log structured events with a correlation ID; never log to stdout ad hoc in library code.
- [ENG-006 SHOULD] Make retried operations idempotent: jobs, webhooks and creating requests.
- [ENG-007 SHOULD] Read configuration from environment or config files; never hard-code per-environment values.
- [ENG-008 SHOULD] Commit a lockfile and pin dependency versions; add a dependency only when it clearly earns its weight.
- [ENG-009 SHOULD] Record significant design decisions as an ADR in docs/adr/; supersede, never edit, an accepted ADR.

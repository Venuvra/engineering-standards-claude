+++
profile = "core/security"
title = "Security"
prefix = "SEC"
+++

- [SEC-001 MUST] Never commit secrets, tokens, keys or credentials; reference them from a secret store or CI secrets.
- [SEC-002 MUST] Never log secrets, tokens, passwords, session IDs or unmasked personal data.
- [SEC-003 MUST] Validate all external input at the trust boundary against a schema; reject unknown fields.
- [SEC-004 MUST] Never build SQL, shell commands or HTML by concatenating untrusted input; use parameters or safe APIs.
- [SEC-005 MUST] Run subprocesses with argument arrays, never through a shell with untrusted input.
- [SEC-006 MUST] Enforce authorization on the server for every request; UI checks are never authorization.
- [SEC-007 MUST] In multi-tenant code, scope every query by the tenant from the verified identity, never from client input.
- [SEC-008 MUST] Grant least privilege to tokens, IAM roles and CI jobs; no wildcard permissions without a recorded exception.
- [SEC-009 MUST] Never disable TLS verification, certificate checks or SSH host-key checking.
- [SEC-010 MUST] Never weaken authentication, CSRF, CORS or security headers without a recorded decision.
- [SEC-011 SHOULD] Prefer short-lived credentials (OIDC, assumed roles) over long-lived keys.
- [SEC-012 SHOULD] Before adding a dependency, check its maintenance, license and known vulnerabilities.

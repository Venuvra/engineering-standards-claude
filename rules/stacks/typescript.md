+++
profile = "stacks/typescript"
title = "TypeScript and Node.js"
prefix = "TS"
+++

- [TS-001 SHOULD] In TypeScript, keep `strict` enabled in tsconfig.
- [TS-002 SHOULD] Avoid `any`; use `unknown` and narrow. Use `@ts-expect-error` only with a reason, never `@ts-ignore`.
- [TS-003 SHOULD] Types are not runtime validation: parse external data with a schema library before use.
- [TS-004 SHOULD] Use the package manager the lockfile names, never mix them; install with the frozen-lockfile command in CI.
- [TS-005 SHOULD] Await, return or explicitly handle every promise; no floating promises.
- [TS-006 SHOULD] Throw `Error` subclasses, never strings; pass `cause` when wrapping an error.
- [TS-007 SHOULD] Follow the module system the package declares; don't mix `require` and `import`.
- [TS-008 SHOULD] Use the project's structured logger in server code; no committed `console.log` there.
- [TS-009 SHOULD] Pin the Node version (`.node-version` or `engines`) and use the same one in CI.
- [TS-010 MUST] Only explicitly public env vars (such as `NEXT_PUBLIC_`, `VITE_`) may reach browser bundles; never expose server secrets.
- [TS-011 MUST] Never use `eval`, `new Function`, `innerHTML` or `dangerouslySetInnerHTML` with untrusted content.
- [TS-012 SHOULD] Name values in camelCase and types or components in PascalCase; follow framework file-naming rules.

# Container test gate

Rules TST-007 to TST-009. Every project that deploys a service ships one command that runs
all of its checks in a container built like the production environment. That command is the
test gate for every PR. Hosted CI such as GitHub Actions is optional: useful when it is
available, never the only place the checks can run.

Why: hosted CI minutes can stop (billing, outages, quota), and "passes in CI" says little when
CI runs a different OS, architecture or database version than production. A container that
matches the deploy target gives the same result on a laptop, in a cloud session and in CI.

## What the gate must do

- Run with one command from a clean checkout, for example `docker compose -f compose.test.yml run --rm test`
  (wrap it in `make test-docker` or an npm script if you like). Name it in the project
  instructions of `AGENTS.md`.
- Run everything CI would: install from the lockfile, lint, type-check, unit and integration
  tests, the production build, and end-to-end tests where the project has them.
- Start real dependencies (database, cache, queue) as services in the same compose file, never
  mocks of them (see TST-003).
- Exit non-zero on any failure and leave nothing running (`--rm`, `down -v`).

## Matching the deploy target (TST-008)

Write the target down once in the project instructions, then build the test image from it:

| Item | Match it by |
| --- | --- |
| Base image and OS | If production runs a container, the test stage starts `FROM` the same base image and tag as the production stage of the same Dockerfile. If production runs on a VM, use that VM's OS image (for example `oraclelinux:9`, `ubuntu:24.04`). |
| CPU architecture | Pin `platform:` to the target, for example `linux/arm64` for Arm compute shapes such as OCI Ampere A1 or AWS Graviton. On another architecture Docker emulates it; slower, but it catches native-module and image problems. |
| Runtime | Same Node, Python or JDK version as production, from one source (`.node-version`, `requires-python`, a build arg) used by both stages. |
| Database and services | Same engine and major version as the managed service, for example `postgres:16` when the cloud database runs PostgreSQL 16. Enable the same extensions. |
| Configuration | Same environment variable names as production, with test values from a committed `.env.test` that holds no secrets (SEC-001). |

When the target changes (new region shape, database upgrade, new runtime), change the
production image and the test image in the same PR.

## Example layout

A Node service deployed as a container to an Arm compute shape with managed PostgreSQL 16:

```dockerfile
# Dockerfile
ARG NODE_VERSION=22.11.0
FROM node:${NODE_VERSION}-bookworm-slim AS base
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM base AS test
COPY . .
CMD ["sh", "-c", "npm run lint && npm run typecheck && npm test && npm run build"]

FROM base AS build
COPY . .
RUN npm run build

FROM node:${NODE_VERSION}-bookworm-slim AS production
# ... copy the build output from the build stage
```

```yaml
# compose.test.yml
services:
  db:
    image: postgres:16
    platform: linux/arm64
    environment:
      POSTGRES_PASSWORD: test
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "postgres"]
      interval: 2s
      retries: 30
  test:
    build: { context: ., target: test }
    platform: linux/arm64
    env_file: .env.test
    depends_on:
      db: { condition: service_healthy }
```

## Hosted CI is optional (TST-009)

GitHub Actions, or any other hosted CI, may run the gate, but only by calling the same
command, so the two can never drift. When hosted CI is off or unavailable, the PR body
carries the evidence instead: the command, where it ran and its result, labelled honestly as
local (TST-006). A repository whose branch ruleset requires a CI check keeps that check until a
maintainer changes the ruleset; GIT-003 still forbids merging with failing required checks.

Repositories that don't deploy anything, such as libraries and tooling, can skip TST-007 and
TST-008, or record an override (see [overrides](overrides.md)) when the rule reads as if it applies.

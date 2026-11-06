# Project CI (the CI template)

The standards install only `standards.yml`, which checks and syncs the standards. A project's own
build and test workflow stays the project's. `templates/ci/ci.yml` is a starting point for it
that follows TST-007 to TST-009 and runs on the same runners as the standards workflow. Nothing
installs or checks it: copy it once, then it is yours to change.

## Use it

1. Copy `templates/ci/ci.yml` from the release you pin to `.github/workflows/ci.yml`.
2. Set `branches:` under `push:` to the default branch.
3. Replace `./scripts/check.sh` in the Check step with the project's one check command, the same
   one people run locally (TST-007), for example `npm ci && npm run check`.
4. Keep the Postgres service and its port step if the tests need a database. The step sets the
   standard `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD` and `PGDATABASE` variables, which most
   Postgres clients read; if the tests want a URL, build it from them. Otherwise delete both. Use
   the database version the deploy target runs (TST-008).

## Runners

| Run | Runs on |
| --- | --- |
| Push or same-repository PR, `RUNNER_TARGET` unset | GitHub-hosted `ubuntu-24.04` |
| Push or same-repository PR, `RUNNER_TARGET` = `local` or `oci` | `venuvra-local` or `venuvra-oci` |
| PR from a fork | Always GitHub-hosted |
| Actions → ci → Run workflow, runner `default` | As `RUNNER_TARGET` above |
| Run workflow, runner `local`, `oci` or `github` | That runner, whatever `RUNNER_TARGET` says |

Set `RUNNER_TARGET` as a repository variable; see [no-actions.md](no-actions.md) for the
runners, their capacity, and the arm64 note for `oci`. Unlike the standards workflow, where an
unset variable also means GitHub-hosted, a project can make `local` its default by setting the
variable: then CI waits whenever that runner is offline, so pick `oci` before it goes offline.

## Choices in the template

- **Fork guard in `runs-on`, not a job `if`.** Fork PRs still get CI, on a GitHub-hosted runner,
  and their code never reaches a self-hosted one.
- **Random service port.** `ports: ["5432"]` lets Docker pick the host port, and a step reads it
  from `job.services.postgres.ports`. A runner host that runs two jobs at once would clash on a
  fixed `5432:5432`.
- **Only PR runs cancel each other.** A newer push never cuts a default-branch build short.
- **Read-only token.** CI needs no write scope; anything that publishes belongs in its own job or
  workflow.

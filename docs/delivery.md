# Deploy and destroy (the `delivery` profile)

The `delivery` profile (DLV-001 to DLV-008, all SHOULD) asks a project that deploys anything to
deploy and destroy every environment, local and cloud, from committed automation that GitHub
Actions and Jenkins share. It is opt-in: add it to `stacks` in `.venuvra/standards.toml` and
merge the next sync PR.

```toml
stacks = ["typescript", "delivery"]
```

`vstd init` never adds it on its own, and nothing fails `vstd check` if a project hasn't adopted
the templates yet: the rules tell people and agents what to build.

## The templates

Copy them from `templates/delivery/` in the release you pin:

| Template | Copy to | What it does |
| --- | --- | --- |
| `deploy.ps1` | `scripts/deploy.ps1` | The one entry point: `-Target local\|cloud -Action plan\|deploy\|destroy` |
| `deploy.yml` | `.github/workflows/deploy.yml` | Manual run with dropdowns; plan job, then the run job |
| `Jenkinsfile` | `Jenkinsfile` | The same stages: Plan, Approve, Run |

Both pipelines call `scripts/deploy.ps1` and nothing else, so a run from your own machine, from
Actions and from Jenkins does the same thing.

- **Local** uses Docker Compose (`compose.yaml`). `destroy` needs `-Confirm 'destroy <app>'` and
  keeps volumes unless `-Purge` is given.
- **Cloud** uses Terraform (or OpenTofu with `-Iac tofu`) in `infra/`, with remote, locked
  state. `plan -For deploy` or `plan -For destroy` saves the plan (`infra/tfplan` or
  `infra/tfplan-destroy`) and prints it. `deploy` and `destroy` apply only that saved plan, so
  what was approved is what runs; they need `-Confirm 'deploy <app>'` or `-Confirm 'destroy <app>'`.
- `<app>` defaults to the repository folder name in lower case; pass `-App` to set it.

From PowerShell on your own machine:

```powershell
./scripts/deploy.ps1 -Target local -Action deploy
./scripts/deploy.ps1 -Target local -Action destroy -Confirm 'destroy myapp'
./scripts/deploy.ps1 -Target cloud -Action plan
./scripts/deploy.ps1 -Target cloud -Action deploy -Confirm 'deploy myapp'
./scripts/deploy.ps1 -Target cloud -Action plan -For destroy
./scripts/deploy.ps1 -Target cloud -Action destroy -Confirm 'destroy myapp'
```

## GitHub Actions

Run it from Actions → deploy → Run workflow and pick the target and action. The plan job prints
the plan for the chosen action, a destroy included. The run job starts only for `deploy` or
`destroy`, applies the plan the first job saved, and uses the `production` environment for
anything that touches the cloud or destroys.

- Add required reviewers to the `production` environment where your GitHub plan allows it. On
  GitHub Free, private repositories have no environment reviewers, so the typed confirmation is
  the gate.
- The jobs run on your own runners when the repository variable `RUNNER_TARGET` is set (see
  [no-actions.md](no-actions.md)). `local` needs a runner with Docker.
- Cloud login uses OIDC (`id-token: write`); add your provider's login step before the script, or
  use the organisation's shared reusable deploy workflows for cloud jobs where they exist
  (DLV-006). Don't store cloud keys as secrets.
- The saved plan travels between jobs as an artifact kept for one day, because a plan file can hold
  sensitive values.

## Jenkins

Create a Pipeline job from SCM pointing at the repository's `Jenkinsfile`, then use Build with
Parameters. The agent needs PowerShell 7 (`pwsh`), plus Docker for `local` and Terraform or
OpenTofu for `cloud`. Cloud credentials come from a credentials binding or the agent's own
short-lived identity, never from the repository. The Approve stage stops for a person before any
cloud deploy or any destroy, after the plan is in the console log.

The `sh` steps use single-quoted Groovy, so parameters reach the script as quoted environment
variables and are never spliced into the command. On a Windows agent, replace `sh 'pwsh ...'`
with `pwsh '...'` from the PowerShell plugin.

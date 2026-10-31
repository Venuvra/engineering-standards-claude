+++
profile = "stacks/delivery"
title = "Deployment and infrastructure"
prefix = "DLV"
+++

- [DLV-001 SHOULD] Deploy and destroy every environment, local and cloud, from committed automation; never by hand in a console.
- [DLV-002 SHOULD] Keep one entry point, `scripts/deploy.ps1 -Target local|cloud -Action plan|deploy|destroy`; Actions and Jenkins call it and add no deploy logic.
- [DLV-003 SHOULD] Gate each cloud deploy and each destroy on a person typing `deploy <app>` or `destroy <app>` (plus approval where available); never on push or schedule.
- [DLV-004 SHOULD] Declare cloud infrastructure in Terraform or OpenTofu with remote, locked state; apply only the saved plan that was shown before approval.
- [DLV-005 SHOULD] Give pipelines cloud access through short-lived credentials (OIDC or a secret store), never stored keys.
- [DLV-006 SHOULD] On GitHub, use the organisation's shared reusable deploy workflows for cloud jobs where they exist; on Jenkins, mirror the same stages in a `Jenkinsfile`.
- [DLV-007 SHOULD] Run the local environment with Docker Compose; a local destroy keeps volumes unless `-Purge` is given.
- [DLV-008 SHOULD] Offer target and action as dropdowns on manual runs: `workflow_dispatch` choice inputs in Actions, `choice` parameters in Jenkins.

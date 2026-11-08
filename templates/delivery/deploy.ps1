#requires -Version 7.2
<#
.SYNOPSIS
  The one entry point for deploying and destroying this project (DLV-002).

.DESCRIPTION
  Copy to scripts/deploy.ps1. GitHub Actions (deploy.yml) and Jenkins (Jenkinsfile) call this
  file and nothing else, so a run from a laptop, Actions or Jenkins does the same thing.

    local  Docker Compose (DLV-007). destroy keeps volumes unless -Purge.
    k8s    Docker Desktop's Kubernetes (DLV-007): the kustomization in -K8sDir, in the
           namespace named after the app, on the docker-desktop context only. deploy builds
           the image Docker Desktop's cluster runs from Docker's own image store. destroy
           keeps persistent volume claims unless -Purge.
    cloud  Terraform or OpenTofu in -InfraDir with remote, locked state (DLV-004).
           plan -For deploy|destroy writes and prints a saved plan; deploy and destroy apply
           only that saved plan, so what a person approved is exactly what runs.
           Both need -Confirm.

  Cloud credentials come from the environment (OIDC in Actions, a credentials binding in
  Jenkins); this script never reads or stores keys (DLV-005).

.EXAMPLE
  ./scripts/deploy.ps1 -Target local -Action deploy
  ./scripts/deploy.ps1 -Target k8s -Action deploy
  ./scripts/deploy.ps1 -Target k8s -Action destroy -Confirm 'destroy myapp'
  ./scripts/deploy.ps1 -Target cloud -Action plan
  ./scripts/deploy.ps1 -Target cloud -Action deploy -Confirm 'deploy myapp'
  ./scripts/deploy.ps1 -Target cloud -Action plan -For destroy
  ./scripts/deploy.ps1 -Target cloud -Action destroy -Confirm 'destroy myapp'
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('local', 'k8s', 'cloud')][string]$Target,
    [Parameter(Mandatory)][ValidateSet('plan', 'deploy', 'destroy')][string]$Action,
    # With -Action plan: what the plan is for. Pipelines pass their action here unchanged.
    [ValidateSet('plan', 'deploy', 'destroy')][string]$For = 'deploy',
    [ValidatePattern('^[a-z0-9][a-z0-9-]*$')][string]$App = (Split-Path -Leaf (Get-Location)).ToLowerInvariant(),
    [string]$Confirm = '',
    [switch]$Purge,
    [string]$InfraDir = 'infra',
    [string]$ComposeFile = 'compose.yaml',
    [string]$K8sDir = 'deploy/k8s',
    # Only Docker Desktop's cluster: this target never reaches a shared or cloud cluster.
    [ValidateSet('docker-desktop')][string]$KubeContext = 'docker-desktop',
    # The image the manifests reference; keep imagePullPolicy Never or IfNotPresent for it.
    [string]$Image = "$((Split-Path -Leaf (Get-Location)).ToLowerInvariant()):local",
    [ValidateSet('terraform', 'tofu')][string]$Iac = 'terraform'
)

$ErrorActionPreference = 'Stop'
# A failing docker or terraform call stops the script instead of carrying on (PowerShell 7.3+).
$PSNativeCommandUseErrorActionPreference = $true

function Invoke-Tool {
    # Argument arrays only, never a command string, so no value is re-read by a shell.
    param([string]$Name, [string[]]$Arguments)
    Write-Host "> $Name $($Arguments -join ' ')"
    & $Name @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Name exited with $LASTEXITCODE" }
}

function Assert-Confirmed([string]$Expected) {
    if ($Confirm -cne $Expected) { throw "This needs -Confirm '$Expected' (DLV-003)." }
}

# A destroy plan gets its own file, so a deploy can never apply one by mistake or the reverse.
$planFor = if ($Action -eq 'plan') { $For } else { $Action }
$planFile = if ($planFor -eq 'destroy') { 'tfplan-destroy' } else { 'tfplan' }

function Invoke-Kubectl([string[]]$Arguments) {
    Invoke-Tool kubectl (@('--context', $KubeContext) + $Arguments)
}

function Invoke-SavedPlan([string]$Verb) {
    Assert-Confirmed "$Verb $App"
    if (-not (Test-Path (Join-Path $InfraDir $planFile))) {
        throw "No saved $Verb plan in $InfraDir; run -Action plan -For $Verb and review it first (DLV-004)."
    }
    Invoke-Tool $Iac @("-chdir=$InfraDir", 'init', '-input=false')
    Invoke-Tool $Iac @("-chdir=$InfraDir", 'apply', '-input=false', $planFile)
}

switch ("$Target/$Action") {
    'local/plan' {
        Invoke-Tool docker @('compose', '-f', $ComposeFile, 'config', '--quiet')
    }
    'local/deploy' {
        Invoke-Tool docker @('compose', '-f', $ComposeFile, 'up', '--build', '--detach', '--wait')
    }
    'local/destroy' {
        Assert-Confirmed "destroy $App"
        $down = @('compose', '-f', $ComposeFile, 'down', '--remove-orphans')
        if ($Purge) { $down += '--volumes' }
        Invoke-Tool docker $down
    }
    'k8s/plan' {
        $existing = & kubectl --context $KubeContext get namespace $App --ignore-not-found -o name
        if ($LASTEXITCODE -ne 0) { throw "kubectl get namespace exited with $LASTEXITCODE" }
        if ($planFor -eq 'destroy') {
            $scope = if ($Purge) { "namespace '$App' and its data" } else { "the workloads in '$App' (volumes kept)" }
            Write-Host "destroy would remove ${scope}:"
            if ($existing) { Invoke-Kubectl @('-n', $App, 'get', 'all,pvc') }
        } elseif (-not $existing) {
            # kubectl diff can't dry-run objects whose namespace doesn't exist yet.
            Write-Host "First deploy: everything below would be created."
            Invoke-Tool kubectl @('kustomize', $K8sDir)
        } else {
            # diff exits 1 when there are differences, a normal plan result, so don't throw on it.
            $PSNativeCommandUseErrorActionPreference = $false
            & kubectl --context $KubeContext diff -k $K8sDir
            if ($LASTEXITCODE -gt 1) { throw "kubectl diff exited with $LASTEXITCODE" }
        }
    }
    'k8s/deploy' {
        Invoke-Tool docker @('build', '--tag', $Image, '.')
        Invoke-Kubectl @('apply', '-k', $K8sDir)
        # The tag stays the same on every build, so restart to run the new image.
        foreach ($name in (& kubectl --context $KubeContext -n $App get deployment -o name)) {
            Invoke-Kubectl @('-n', $App, 'rollout', 'restart', $name)
            Invoke-Kubectl @('-n', $App, 'rollout', 'status', $name, '--timeout=300s')
        }
    }
    'k8s/destroy' {
        Assert-Confirmed "destroy $App"
        if ($Purge) {
            Invoke-Kubectl @('delete', 'namespace', $App, '--ignore-not-found', '--wait=true')
        } else {
            # Persistent volume claims and secrets stay, so the next deploy finds the data.
            Invoke-Kubectl @('-n', $App, 'delete', 'deployment,statefulset,service,ingress,cronjob,job', '--all', '--ignore-not-found')
        }
    }
    'cloud/plan' {
        Invoke-Tool $Iac @("-chdir=$InfraDir", 'init', '-input=false')
        $plan = @("-chdir=$InfraDir", 'plan', '-input=false', "-out=$planFile")
        if ($planFor -eq 'destroy') { $plan += '-destroy' }
        Invoke-Tool $Iac $plan
        Invoke-Tool $Iac @("-chdir=$InfraDir", 'show', '-no-color', $planFile)
    }
    'cloud/deploy' {
        Invoke-SavedPlan 'deploy'
    }
    'cloud/destroy' {
        Invoke-SavedPlan 'destroy'
    }
}

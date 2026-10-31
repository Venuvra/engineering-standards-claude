#requires -Version 7.2
<#
.SYNOPSIS
  The one entry point for deploying and destroying this project (DLV-002).

.DESCRIPTION
  Copy to scripts/deploy.ps1. GitHub Actions (deploy.yml) and Jenkins (Jenkinsfile) call this
  file and nothing else, so a run from a laptop, Actions or Jenkins does the same thing.

    local  Docker Compose (DLV-007). destroy keeps volumes unless -Purge.
    cloud  Terraform or OpenTofu in -InfraDir with remote, locked state (DLV-004).
           plan -For deploy|destroy writes and prints a saved plan; deploy and destroy apply
           only that saved plan, so what a person approved is exactly what runs.
           Both need -Confirm.

  Cloud credentials come from the environment (OIDC in Actions, a credentials binding in
  Jenkins); this script never reads or stores keys (DLV-005).

.EXAMPLE
  ./scripts/deploy.ps1 -Target local -Action deploy
  ./scripts/deploy.ps1 -Target cloud -Action plan
  ./scripts/deploy.ps1 -Target cloud -Action deploy -Confirm 'deploy myapp'
  ./scripts/deploy.ps1 -Target cloud -Action plan -For destroy
  ./scripts/deploy.ps1 -Target cloud -Action destroy -Confirm 'destroy myapp'
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('local', 'cloud')][string]$Target,
    [Parameter(Mandatory)][ValidateSet('plan', 'deploy', 'destroy')][string]$Action,
    # With -Action plan: what the plan is for. Pipelines pass their action here unchanged.
    [ValidateSet('plan', 'deploy', 'destroy')][string]$For = 'deploy',
    [ValidatePattern('^[a-z0-9][a-z0-9-]*$')][string]$App = (Split-Path -Leaf (Get-Location)).ToLowerInvariant(),
    [string]$Confirm = '',
    [switch]$Purge,
    [string]$InfraDir = 'infra',
    [string]$ComposeFile = 'compose.yaml',
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

<#
.SYNOPSIS
  Take Ask Washington offline: stop only its containers and remove only its nginx site.

.DESCRIPTION
  Runs on the server in one ssh -t session (sudo password once):
  - docker compose -p ask-washington down (the database volume is kept unless -Purge);
  - removes /etc/nginx/sites-enabled/ask.inmersoft.com (the file in sites-available and the
    certificate are kept, so a later deploy can re-enable it);
  - runs nginx -t and reloads nginx only if the test passes.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File deploy\rollback.ps1
  powershell -ExecutionPolicy Bypass -File deploy\rollback.ps1 -Purge   # also delete the data volume
#>
[CmdletBinding()]
param(
    [switch]$Purge,
    [string]$ConfigPath
)

$ErrorActionPreference = "Stop"
# Computed in the body: Windows PowerShell 5.1 leaves $PSScriptRoot empty in param() defaults.
$ScriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$LocalConfig = if ($ConfigPath) { $ConfigPath } else { Join-Path $ScriptDir ".deploy.local" }
if (-not (Test-Path $LocalConfig)) { throw "Missing $LocalConfig with DEPLOY_HOST=user@host." }

$DeployHost = $null
foreach ($line in [System.IO.File]::ReadAllLines($LocalConfig)) {
    if ($line -match '^\s*DEPLOY_HOST\s*=\s*(\S+)\s*$') { $DeployHost = $Matches[1] }
}
if (-not $DeployHost -or $DeployHost -notmatch '^[^@\s]+@[^@\s]+$') {
    throw "DEPLOY_HOST in deploy/.deploy.local must look like user@host."
}

$volumes = if ($Purge) { "-v" } else { "" }
$remote = @(
    "set -e",
    "sudo -v",
    "APP_DIR=/var/www/ask-washington",
    "if [ -f `$APP_DIR/docker-compose.prod.yml ]; then sudo docker compose -p ask-washington -f `$APP_DIR/docker-compose.prod.yml --project-directory `$APP_DIR down $volumes; else echo 'no compose file, skipping containers'; fi",
    "sudo rm -f /etc/nginx/sites-enabled/ask.inmersoft.com",
    "if sudo nginx -t; then sudo systemctl reload nginx; echo 'nginx reloaded'; else echo 'nginx -t failed: NOT reloading nginx' >&2; exit 1; fi",
    "echo 'Ask Washington is offline.'"
) -join "; "

# The remote login shell runs the command list directly (no extra quoting layer).
ssh -t $DeployHost $remote
if ($LASTEXITCODE -ne 0) { throw "Rollback failed (exit code $LASTEXITCODE)." }

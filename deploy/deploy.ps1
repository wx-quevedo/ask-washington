<#
.SYNOPSIS
  Deploy Ask Washington to the server in one command.

.DESCRIPTION
  1. Reads DEPLOY_HOST (user@host) and APP_PORT from deploy/.deploy.local (ignored by git).
  2. Reads ANTHROPIC_API_KEY from the local .env without printing it.
  3. Packages HEAD with git archive, dumps the vector store tables from the local database,
     writes a production .env, and uploads the three files with scp.
  4. Runs deploy/remote-deploy.sh on the server in one ssh -t session (sudo password once):
     containers, health check, data restore, nginx site and certbot.
  5. Prints the result of https://ask.inmersoft.com/health.

  Safe to run again: it updates the same Compose project and keeps the certbot-managed
  nginx site unless -ForceNginx is given.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File deploy\deploy.ps1

.EXAMPLE
  # Local check only: build the package, the dump and the .env, then stop before ssh/scp.
  powershell -ExecutionPolicy Bypass -File deploy\deploy.ps1 -DryRun -AllowDirty
#>
[CmdletBinding()]
param(
    [switch]$ForceNginx,
    [switch]$AllowDirty,
    [switch]$DryRun,
    [string]$ConfigPath = (Join-Path $PSScriptRoot ".deploy.local")
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Domain = "ask.inmersoft.com"
$CertbotEmail = "waxshoxp@gmail.com"
$RemoteStage = "ask-washington-deploy"   # relative to the remote user's home

$Root = Split-Path $PSScriptRoot -Parent
$LocalConfig = $ConfigPath
$Utf8NoBom = New-Object System.Text.UTF8Encoding $false

function Read-KeyValueFile([string]$Path) {
    $values = [ordered]@{}
    foreach ($line in [System.IO.File]::ReadAllLines($Path)) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') {
            $values[$Matches[1]] = $Matches[2]
        }
    }
    return $values
}

function New-Secret([int]$Length = 32) {
    $chars = [char[]]"ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    $bytes = New-Object byte[] $Length
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return -join ($bytes | ForEach-Object { $chars[$_ % $chars.Length] })
}

# Windows PowerShell 5.1 turns any stderr line of a native program into an error when
# ErrorActionPreference is Stop (ssh prints "Connection closed" there, for example).
# Judge native commands by their exit code instead.
function Invoke-Native([string]$What, [scriptblock]$Command) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $Command } finally { $ErrorActionPreference = $previous }
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit code $LASTEXITCODE)." }
}

function Get-NativeOutput([scriptblock]$Command) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { $output = & $Command 2>$null } finally { $ErrorActionPreference = $previous }
    return [pscustomobject]@{ Output = $output; ExitCode = $LASTEXITCODE }
}

# ------------------------------------------------------------------ settings
if (-not (Test-Path $LocalConfig)) {
    throw "Missing deploy/.deploy.local. Copy deploy/.deploy.local.example and set DEPLOY_HOST=user@host."
}
$config = Read-KeyValueFile $LocalConfig
if (-not $config.Contains("DEPLOY_HOST") -or $config["DEPLOY_HOST"] -notmatch '^[^@\s]+@[^@\s]+$') {
    throw "DEPLOY_HOST in deploy/.deploy.local must look like user@host."
}
$DeployHost = $config["DEPLOY_HOST"]
$AppPort = if ($config.Contains("APP_PORT") -and $config["APP_PORT"]) { $config["APP_PORT"] } else { "8710" }
if ($AppPort -notmatch '^\d{4,5}$') { throw "APP_PORT must be a number." }
$DbContainer = if ($config.Contains("LOCAL_DB_CONTAINER") -and $config["LOCAL_DB_CONTAINER"]) { $config["LOCAL_DB_CONTAINER"] } else { "ask-washington-db" }

# Secrets generated once and reused, so redeploys keep the same database password.
$added = @()
foreach ($name in "POSTGRES_PASSWORD", "IP_HASH_SALT") {
    if (-not $config.Contains($name) -or -not $config[$name]) {
        $config[$name] = New-Secret
        $added += "$name=$($config[$name])"
    }
}
if ($added.Count -gt 0) {
    [System.IO.File]::AppendAllText($LocalConfig, "`n" + ($added -join "`n") + "`n", $Utf8NoBom)
    Write-Host "Generated $($added.Count) secret(s) and saved them in deploy/.deploy.local."
}

$localEnv = Read-KeyValueFile (Join-Path $Root ".env")
if (-not $localEnv.Contains("ANTHROPIC_API_KEY") -or -not $localEnv["ANTHROPIC_API_KEY"]) {
    throw "ANTHROPIC_API_KEY is not set in the local .env."
}

Push-Location $Root
$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("askw-deploy-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tmp | Out-Null
try {
    # -------------------------------------------------------------- package
    $dirty = (Get-NativeOutput { git status --porcelain --untracked-files=no }).Output
    if ($dirty -and -not $AllowDirty) {
        throw "There are uncommitted changes. git archive deploys HEAD only: commit first, or use -AllowDirty to deploy HEAD anyway."
    }
    $head = (git rev-parse --short HEAD).Trim()
    Write-Host "Packaging HEAD ($head) with git archive"
    # core.autocrlf=true (common on Windows) would make git archive emit CRLF, which breaks
    # shell scripts and Dockerfile line continuations on the server.
    Invoke-Native "git archive" { git -c core.autocrlf=false archive --format=tar.gz -o (Join-Path $tmp "app.tar.gz") HEAD }
    $shown = Get-NativeOutput { git show "HEAD:deploy/remote-deploy.sh" }
    $remoteScript = $shown.Output
    if ($shown.ExitCode -ne 0) {
        if (-not $DryRun) { throw "deploy/remote-deploy.sh is not committed." }
        Write-Warning "deploy/remote-deploy.sh is not in HEAD yet; the dry run uses the working tree copy."
        $remoteScript = [System.IO.File]::ReadAllLines((Join-Path $PSScriptRoot "remote-deploy.sh"))
    }
    [System.IO.File]::WriteAllText((Join-Path $tmp "remote-deploy.sh"), (($remoteScript -join "`n") + "`n"), $Utf8NoBom)

    # ----------------------------------------------------------------- dump
    $runtime = if (Get-Command podman -ErrorAction SilentlyContinue) { "podman" } elseif (Get-Command docker -ErrorAction SilentlyContinue) { "docker" } else { throw "Neither podman nor docker is available to dump the local database." }
    Write-Host "Dumping data_chunks and ingested_documents from $DbContainer ($runtime)"
    Invoke-Native "pg_dump" { & $runtime exec $DbContainer pg_dump -U askw -d ask_washington -Fc -t data_chunks -t ingested_documents -f /tmp/askw.dump }
    Invoke-Native "copy dump" { & $runtime cp "${DbContainer}:/tmp/askw.dump" (Join-Path $tmp "data.dump") }
    Get-NativeOutput { & $runtime exec $DbContainer rm -f /tmp/askw.dump } | Out-Null
    $dumpSize = (Get-Item (Join-Path $tmp "data.dump")).Length
    Write-Host ("Dump size: {0:N0} bytes" -f $dumpSize)

    # ------------------------------------------------------- production .env
    $envLines = @(
        "POSTGRES_USER=askw",
        "POSTGRES_PASSWORD=$($config['POSTGRES_PASSWORD'])",
        "POSTGRES_DB=ask_washington",
        "APP_PORT=$AppPort",
        "ANTHROPIC_API_KEY=$($localEnv['ANTHROPIC_API_KEY'])",
        "LLM_PROVIDER=anthropic",
        "LLM_MODEL=claude-haiku-5-5",
        "LLM_MAX_TOKENS=600",
        "RETRIEVAL_MODE=hybrid",
        "RETRIEVAL_TOP_K=6",
        "LLM_PRICE_INPUT_PER_MTOK=0.10",
        "LLM_PRICE_OUTPUT_PER_MTOK=0.50",
        "DAILY_BUDGET_USD=1.00",
        "RATE_LIMIT_PER_MINUTE=10/minute",
        "RATE_LIMIT_PER_DAY=100/day",
        "IP_HASH_SALT=$($config['IP_HASH_SALT'])"
    )
    [System.IO.File]::WriteAllText((Join-Path $tmp "env.production"), (($envLines -join "`n") + "`n"), $Utf8NoBom)
    $envLines = $null

    if ($DryRun) {
        Write-Host "`nDry run: these files would be uploaded to ${RemoteStage}/ (nothing was sent):"
        Get-ChildItem $tmp | ForEach-Object { Write-Host ("  {0,-18} {1,12:N0} bytes" -f $_.Name, $_.Length) }
        $names = [System.IO.File]::ReadAllLines((Join-Path $tmp "env.production")) | ForEach-Object { ($_ -split "=", 2)[0] }
        Write-Host "  env.production variables: $($names -join ', ')"
        Write-Host "  remote command: bash $RemoteStage/remote-deploy.sh $RemoteStage $AppPort <email> $(if ($ForceNginx) { 1 } else { 0 })"
        return
    }

    # --------------------------------------------------------------- upload
    Write-Host "Uploading the package, the dump and the production .env"
    Invoke-Native "ssh (prepare)" { ssh $DeployHost "umask 077 && mkdir -p $RemoteStage && chmod 700 $RemoteStage" }
    $files = "app.tar.gz", "data.dump", "env.production", "remote-deploy.sh" | ForEach-Object { Join-Path $tmp $_ }
    Invoke-Native "scp" { scp -q @files "${DeployHost}:$RemoteStage/" }

    # ---------------------------------------------------------------- deploy
    Write-Host "Running the server-side deploy (you will be asked for the sudo password once)"
    $force = if ($ForceNginx) { "1" } else { "0" }
    Invoke-Native "remote deploy" { ssh -t $DeployHost "chmod 600 $RemoteStage/env.production && bash $RemoteStage/remote-deploy.sh $RemoteStage $AppPort $CertbotEmail $force" }
}
finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
    Pop-Location
}

# --------------------------------------------------------------------- result
if ($DryRun) { exit 0 }
Write-Host "`ncurl https://$Domain/health"
try {
    $health = Invoke-RestMethod -Uri "https://$Domain/health" -TimeoutSec 20
    $health | ConvertTo-Json -Compress
}
catch {
    Write-Warning "https://$Domain/health did not answer yet: $($_.Exception.Message)"
    exit 1
}

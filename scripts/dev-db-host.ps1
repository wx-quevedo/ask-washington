# Point DATABASE_URL in the local .env at the current Podman machine IP.
#
# Needed on Windows with a rootful Podman machine, where published container ports
# are not forwarded to localhost. The machine IP changes when it restarts, so run
# this before starting the app. With Docker or on Linux, keep localhost instead.
#
# Usage (from the repo root): powershell -ExecutionPolicy Bypass -File scripts\dev-db-host.ps1

$ErrorActionPreference = "Stop"

$envPath = Join-Path (Split-Path $PSScriptRoot -Parent) ".env"
if (-not (Test-Path $envPath)) {
    throw ".env not found at $envPath. Copy .env.example to .env first."
}

$addr = podman machine ssh "ip -4 -o addr show eth0" 2>$null
if ($LASTEXITCODE -ne 0 -or -not $addr) {
    throw "Could not read the Podman machine IP. Is the machine running? (podman machine start)"
}
$match = [regex]::Match(($addr -join " "), "inet (\d{1,3}(\.\d{1,3}){3})/")
if (-not $match.Success) {
    throw "Unexpected output from the Podman machine: $addr"
}
$ip = $match.Groups[1].Value

$raw = [System.IO.File]::ReadAllText($envPath)
$newline = if ($raw.Contains("`r`n")) { "`r`n" } else { "`n" }
$lines = $raw -split "`r?`n"
$found = $false
$newUrl = $null
for ($i = 0; $i -lt $lines.Length; $i++) {
    if ($lines[$i] -match "^DATABASE_URL=(.*)$") {
        # Keep scheme, credentials, port and database; replace only the host.
        $newUrl = $Matches[1] -replace "@[^:/]+", "@$ip"
        $lines[$i] = "DATABASE_URL=$newUrl"
        $found = $true
    }
}
if (-not $found) {
    throw "No DATABASE_URL line in $envPath."
}

# Keep the file's original line endings and the other variables untouched.
[System.IO.File]::WriteAllText($envPath, ($lines -join $newline), (New-Object System.Text.UTF8Encoding $false))

$masked = $newUrl -replace "(://[^:/@]+:)[^@]*@", '$1****@'
Write-Output "DATABASE_URL=$masked"

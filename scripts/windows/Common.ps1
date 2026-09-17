$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$script:DefaultVersion = '0.1.0-preview.1'
$script:DefaultRepository = 'mcxianyujun/maintune'

function Stop-WithError([string]$Message) { throw $Message }
function Get-DefaultInstallRoot { Join-Path $env:LOCALAPPDATA 'Maintune' }

function Assert-Docker {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Stop-WithError 'Docker Desktop is required. Install it with the WSL2 backend, then retry.' }
    & docker version *> $null
    if ($LASTEXITCODE -ne 0) { Stop-WithError 'Docker Desktop is installed but its daemon is unavailable.' }
    & docker compose version *> $null
    if ($LASTEXITCODE -ne 0) { Stop-WithError 'Docker Compose v2 is required.' }
}

function Invoke-Compose([string]$InstallRoot, [string]$VersionDirectory, [string[]]$Arguments) {
    $project = if ($env:MAINTAINER_COMPOSE_PROJECT) { $env:MAINTAINER_COMPOSE_PROJECT } else { 'ai-maintainer' }
    & docker compose --project-name $project --env-file (Join-Path $InstallRoot '.env') -f (Join-Path $VersionDirectory 'compose.yaml') @Arguments
    if ($LASTEXITCODE -ne 0) { Stop-WithError "Docker Compose failed: $($Arguments -join ' ')" }
}

function Get-EnvValue([string]$File, [string]$Name) {
    $line = Get-Content -LiteralPath $File | Where-Object { $_.StartsWith("$Name=") } | Select-Object -First 1
    if (-not $line) { return '' }
    $value = $line.Substring($Name.Length + 1).Trim()
    if ($value.StartsWith('"') -and $value.EndsWith('"')) { $value = $value.Substring(1, $value.Length - 2) }
    return $value
}

function Set-EnvValue([string]$File, [string]$Name, [string]$Value) {
    $lines = @(Get-Content -LiteralPath $File)
    $found = $false
    $updated = foreach ($line in $lines) {
        if ($line.StartsWith("$Name=")) { $found = $true; "$Name=$Value" } else { $line }
    }
    if (-not $found) { $updated += "$Name=$Value" }
    $updated | Set-Content -Encoding ascii -LiteralPath $File
}

function Wait-MaintainerHealth([int]$Port, [int]$Attempts = 60) {
    $url = "http://127.0.0.1:$Port/healthz"
    for ($i = 0; $i -lt $Attempts; $i++) {
        try { return Invoke-RestMethod -Uri $url -TimeoutSec 3 } catch { Start-Sleep -Seconds 2 }
    }
    Stop-WithError "Health check timed out: $url"
}

function Get-CurrentVersionDirectory([string]$InstallRoot) {
    $versionFile = Join-Path $InstallRoot 'current-version'
    if (-not (Test-Path -LiteralPath $versionFile)) { Stop-WithError "No installation found in $InstallRoot" }
    $version = (Get-Content -Raw -LiteralPath $versionFile).Trim()
    $directory = Join-Path $InstallRoot "versions\$version"
    if (-not (Test-Path -LiteralPath (Join-Path $directory 'compose.yaml'))) { Stop-WithError "Installed bundle is incomplete: $version" }
    return $directory
}

function ConvertTo-UrlBase64([byte[]]$Bytes) { [Convert]::ToBase64String($Bytes).Replace('+','-').Replace('/','_') }
function New-RandomValue([int]$ByteCount) { $bytes = New-Object byte[] $ByteCount; [Security.Cryptography.RandomNumberGenerator]::Fill($bytes); ConvertTo-UrlBase64 $bytes }

function Protect-PrivateFile([string]$Path) {
    if (Get-Command icacls.exe -ErrorAction SilentlyContinue) {
        & icacls.exe $Path /inheritance:r /grant:r "$($env:USERNAME):(R,W)" *> $null
    }
}

function Copy-ReleaseBundle([string]$Source, [string]$Destination) {
    if (-not (Test-Path -LiteralPath (Join-Path $Source 'release.json'))) { Stop-WithError 'Source directory is not a release bundle.' }
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    $excluded = @('.git', '.env', 'data', 'backups', '.venv', 'node_modules', '.pnpm-store', 'test-results')
    Get-ChildItem -Force -LiteralPath $Source | Where-Object { $excluded -notcontains $_.Name } | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $Destination -Recurse -Force
    }
}

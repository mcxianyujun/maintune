[CmdletBinding()]
param(
    [string]$Version = '0.1.0-preview.1',
    [ValidateRange(1,65535)][int]$Port = 8000,
    [string]$InstallDirectory = '',
    [string]$DataDirectory = '',
    [string]$SourceDirectory = '',
    [string]$Repository = 'mcxianyujun/maintune',
    [ValidateSet('Repair','Rebuild','Reconfigure','Abort')][string]$ExistingAction = 'Abort',
    [switch]$NoOpenBrowser,
    [switch]$NonInteractive
)
$ErrorActionPreference = 'Stop'; Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'Common.ps1')

if (-not [Runtime.InteropServices.RuntimeInformation]::IsOSPlatform([Runtime.InteropServices.OSPlatform]::Windows)) { Stop-WithError 'This installer supports Windows 11 only.' }
$os = Get-CimInstance Win32_OperatingSystem
if ([version]$os.Version -lt [version]'10.0.22000') { Stop-WithError 'Windows 11 or newer is required.' }
if ($Version -notmatch '^[0-9A-Za-z][0-9A-Za-z.-]+$') { Stop-WithError 'Invalid version.' }
if ($Repository -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') { Stop-WithError 'Invalid GitHub repository.' }
Assert-Docker

if (-not $InstallDirectory) { $InstallDirectory = Get-DefaultInstallRoot }
$InstallDirectory = [IO.Path]::GetFullPath($InstallDirectory)
if (-not $DataDirectory) { $DataDirectory = Join-Path $InstallDirectory 'data' }
$DataDirectory = [IO.Path]::GetFullPath($DataDirectory)
New-Item -ItemType Directory -Force -Path (Join-Path $InstallDirectory 'versions'), $DataDirectory, (Join-Path $InstallDirectory 'backups') | Out-Null

$currentFile = Join-Path $InstallDirectory 'current-version'
if (Test-Path -LiteralPath $currentFile) {
    $current = (Get-Content -Raw -LiteralPath $currentFile).Trim()
    if (-not $NonInteractive -and $ExistingAction -eq 'Abort') {
        $choice = Read-Host "Existing installation $current found. Enter Repair, Rebuild, Reconfigure, or Abort [Abort]"
        if ($choice) { $ExistingAction = $choice }
    }
    switch ($ExistingAction.ToLowerInvariant()) {
        'repair' {}
        'rebuild' {}
        'reconfigure' { Write-Host 'Existing configuration will be preserved. Re-run Setup Wizard after startup.' }
        default { Stop-WithError 'Installation left unchanged.' }
    }
}

$versionDirectory = Join-Path $InstallDirectory "versions\$Version"
$staging = Join-Path $InstallDirectory ".staging-$Version"
if (Test-Path -LiteralPath $staging) { Stop-WithError "Staging path already exists: $staging" }
New-Item -ItemType Directory -Path $staging | Out-Null
try {
    if (-not $SourceDirectory) {
        $candidate = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
        if ((Test-Path -LiteralPath (Join-Path $candidate 'release.json')) -and ((Get-Content -Raw -LiteralPath (Join-Path $candidate 'release.json')) -match [regex]::Escape('"version": "' + $Version + '"'))) { $SourceDirectory = $candidate }
    }
    if ($SourceDirectory) {
        Copy-ReleaseBundle ([IO.Path]::GetFullPath($SourceDirectory)) $staging
    } else {
        $base = "https://github.com/$Repository/releases/download/v$Version"
        $archiveName = "maintune-v$Version.zip"
        $archive = Join-Path $staging $archiveName; $checksums = Join-Path $staging 'SHA256SUMS'
        Invoke-WebRequest -Uri "$base/$archiveName" -OutFile $archive
        Invoke-WebRequest -Uri "$base/SHA256SUMS" -OutFile $checksums
        $entry = Get-Content -LiteralPath $checksums | Where-Object { $_ -match "^[a-fA-F0-9]{64}\s+\*?$([regex]::Escape($archiveName))$" } | Select-Object -First 1
        if (-not $entry) { Stop-WithError 'Release checksum entry is missing.' }
        $expected = ($entry -split '\s+')[0].ToLowerInvariant(); $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash.ToLowerInvariant()
        if ($actual -ne $expected) { Stop-WithError 'Release checksum verification failed.' }
        $extract = Join-Path $staging 'extracted'; Expand-Archive -LiteralPath $archive -DestinationPath $extract
        $root = Get-ChildItem -LiteralPath $extract -Directory | Select-Object -First 1
        Copy-ReleaseBundle $root.FullName (Join-Path $staging 'bundle')
        Remove-Item -LiteralPath $archive, $checksums -Force
        Get-ChildItem -Force -LiteralPath (Join-Path $staging 'bundle') | Move-Item -Destination $staging
        Remove-Item -LiteralPath $extract, (Join-Path $staging 'bundle') -Recurse -Force
    }
    if (-not (Test-Path -LiteralPath (Join-Path $staging 'requirements.lock'))) { Stop-WithError 'Release bundle is incomplete.' }
    if (Test-Path -LiteralPath $versionDirectory) {
        $expectedParent = [IO.Path]::GetFullPath((Join-Path $InstallDirectory 'versions')) + [IO.Path]::DirectorySeparatorChar
        if (-not ([IO.Path]::GetFullPath($versionDirectory)).StartsWith($expectedParent, [StringComparison]::OrdinalIgnoreCase)) { Stop-WithError 'Refusing to replace a path outside versions.' }
        Remove-Item -LiteralPath $versionDirectory -Recurse -Force
    }
    Move-Item -LiteralPath $staging -Destination $versionDirectory
} finally {
    if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
}

$envFile = Join-Path $InstallDirectory '.env'
$dataForCompose = $DataDirectory.Replace('\','/'); $envForCompose = $envFile.Replace('\','/')
if (-not (Test-Path -LiteralPath $envFile)) {
    @(
        'MAINTAINER_ADMIN_TOKEN=' + (New-RandomValue 36)
        'MAINTAINER_ENCRYPTION_KEY=' + (New-RandomValue 32)
        "MAINTAINER_VERSION=$Version"
        "MAINTAINER_PORT=$Port"
        'MAINTAINER_BIND_ADDRESS=127.0.0.1'
        "MAINTAINER_DATA_DIR=`"$dataForCompose`""
        "MAINTAINER_ENV_FILE=`"$envForCompose`""
    ) | Set-Content -Encoding ascii -LiteralPath $envFile
    Protect-PrivateFile $envFile
} else {
    Set-EnvValue $envFile 'MAINTAINER_VERSION' $Version
    Set-EnvValue $envFile 'MAINTAINER_PORT' $Port
    if (-not (Get-EnvValue $envFile 'MAINTAINER_BIND_ADDRESS')) { Set-EnvValue $envFile 'MAINTAINER_BIND_ADDRESS' '127.0.0.1' }
    Set-EnvValue $envFile 'MAINTAINER_DATA_DIR' "`"$dataForCompose`""
    Set-EnvValue $envFile 'MAINTAINER_ENV_FILE' "`"$envForCompose`""
}

Write-Host "Building Maintune $Version locally. Internet access to official package sources is required."
Invoke-Compose $InstallDirectory $versionDirectory @('build','--pull')
Invoke-Compose $InstallDirectory $versionDirectory @('run','--rm','--no-deps','maintainer','pip','check')
Invoke-Compose $InstallDirectory $versionDirectory @('up','-d','--wait','--wait-timeout','120')
$health = Wait-MaintainerHealth $Port
$Version | Set-Content -Encoding ascii -LiteralPath $currentFile
Write-Host "Maintune $($health.version) is running at http://127.0.0.1:$Port"
Write-Host 'Open the Web UI and continue with the first-run Setup Wizard. The administrator token remains in the private .env file.'
if (-not $NoOpenBrowser) { Start-Process "http://127.0.0.1:$Port" }

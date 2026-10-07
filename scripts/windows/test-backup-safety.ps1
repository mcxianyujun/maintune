# Exercise the actual backup entrypoint with local health/Compose substitutes.
$ErrorActionPreference = 'Stop'
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('maintune-backup-safety-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRoot | Out-Null
try {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'backup.ps1') -Destination $testRoot
    @'
$ErrorActionPreference='Stop'
function Assert-Docker {}
function Get-CurrentVersionDirectory($root) { Join-Path $root 'versions/0.1.0-preview.3' }
function Get-EnvValue($file,$key) { if($key -eq 'MAINTAINER_DATA_DIR'){Join-Path (Split-Path $file) 'data'}else{'18000'} }
function Invoke-Compose($root,$version,$arguments) { $global:BackupTestOperations += $arguments[0] }
function Stop-WithError($message) { throw $message }
function Protect-PrivateFile($file) {}
'@ | Set-Content -Encoding utf8 -LiteralPath (Join-Path $testRoot 'Common.ps1')
    function Invoke-RestMethod { @{schema=4} }
    $install = Join-Path $testRoot 'installation'
    New-Item -ItemType Directory -Path $install | Out-Null
    'TEST_ONLY_ENV=1' | Set-Content -LiteralPath (Join-Path $install '.env')
    $stage = Join-Path $install '.backup-staging'
    New-Item -ItemType Directory -Path $stage | Out-Null
    $global:BackupTestOperations = @()
    $failed=$false
    try { & (Join-Path $testRoot 'backup.ps1') -InstallDirectory $install } catch { $failed=$true }
    if(-not $failed -or $global:BackupTestOperations.Count -ne 0){throw 'Existing staging directory must fail before service stop'}
    Remove-Item -LiteralPath $stage
    $global:BackupTestOperations = @()
    $failed=$false
    try { & (Join-Path $testRoot 'backup.ps1') -InstallDirectory $install } catch { $failed=$true }
    if(-not $failed -or ($global:BackupTestOperations -join ',') -ne 'stop,start'){throw 'Copy failure must restart service'}
    if(Test-Path -LiteralPath $stage){throw 'Failed backup staging was not cleaned'}
    'Windows backup safety: PASS (preflight / stop-start recovery)'
} finally {
    $resolved=[IO.Path]::GetFullPath($testRoot)
    $temporaryRoot=[IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    if(-not $resolved.StartsWith($temporaryRoot,[StringComparison]::OrdinalIgnoreCase) -or (Split-Path $resolved -Leaf) -notlike 'maintune-backup-safety-*'){throw 'Unsafe cleanup target'}
    Remove-Item -LiteralPath $resolved -Recurse -Force
    Remove-Variable BackupTestOperations -Scope Global -ErrorAction SilentlyContinue
}

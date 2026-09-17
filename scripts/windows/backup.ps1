[CmdletBinding()] param([string]$InstallDirectory = '', [string]$OutputDirectory = '')
$ErrorActionPreference='Stop'; Set-StrictMode -Version Latest; . (Join-Path $PSScriptRoot 'Common.ps1')
if (-not $InstallDirectory) { $InstallDirectory=Get-DefaultInstallRoot }; $InstallDirectory=[IO.Path]::GetFullPath($InstallDirectory)
Assert-Docker; $versionDirectory=Get-CurrentVersionDirectory $InstallDirectory; $version=Split-Path $versionDirectory -Leaf
$envFile=Join-Path $InstallDirectory '.env'; $data=Get-EnvValue $envFile 'MAINTAINER_DATA_DIR'; $port=[int](Get-EnvValue $envFile 'MAINTAINER_PORT')
if (-not $OutputDirectory) { $OutputDirectory=Join-Path $InstallDirectory 'backups' }; New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$health=Invoke-RestMethod -Uri "http://127.0.0.1:$port/healthz" -TimeoutSec 5; $stamp=(Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ'); $base=Join-Path $OutputDirectory "ai-maintainer-$version-$stamp"; $archive="$base.zip"
Invoke-Compose $InstallDirectory $versionDirectory @('stop','maintainer')
$stage=Join-Path $InstallDirectory '.backup-staging'; if(Test-Path $stage){Stop-WithError 'Backup staging path already exists'}; New-Item -ItemType Directory $stage | Out-Null
try { Copy-Item -LiteralPath $envFile -Destination (Join-Path $stage '.env'); Copy-Item -LiteralPath $data -Destination (Join-Path $stage 'data') -Recurse; Add-Type -AssemblyName System.IO.Compression.FileSystem; [IO.Compression.ZipFile]::CreateFromDirectory($stage,$archive,[IO.Compression.CompressionLevel]::Optimal,$false) }
finally { if(Test-Path $stage){Remove-Item -LiteralPath $stage -Recurse -Force}; Invoke-Compose $InstallDirectory $versionDirectory @('start','maintainer') }
$hash=(Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash.ToLowerInvariant(); @{timestamp=$stamp;app_version=$version;schema_version=$health.schema;sha256=$hash;contains_secrets=$true}|ConvertTo-Json -Compress|Set-Content -Encoding ascii -LiteralPath "$base.manifest.json"; Protect-PrivateFile $archive; Protect-PrivateFile "$base.manifest.json"
Write-Host "Backup created: $archive"; Write-Host 'This backup contains encrypted configuration and internal secrets; store it as sensitive data.'

[CmdletBinding()] param([Parameter(Mandatory)][string]$Version,[string]$InstallDirectory='',[string]$SourceDirectory='',[string]$Repository='mcxianyujun/maintune')
$ErrorActionPreference='Stop'; if(-not $InstallDirectory){. (Join-Path $PSScriptRoot 'Common.ps1');$InstallDirectory=Get-DefaultInstallRoot}
& (Join-Path $PSScriptRoot 'backup.ps1') -InstallDirectory $InstallDirectory
$args=@{Version=$Version;InstallDirectory=$InstallDirectory;ExistingAction='Rebuild';NoOpenBrowser=$true;NonInteractive=$true;Repository=$Repository}; if($SourceDirectory){$args.SourceDirectory=$SourceDirectory}
try { & (Join-Path $PSScriptRoot 'install.ps1') @args } catch { Write-Error 'Update failed. The prior bundle, image and backup remain available. Run restore.ps1 with the newest backup if recovery is required.'; throw }

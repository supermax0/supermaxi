$ErrorActionPreference = 'SilentlyContinue'

$localAppData = [Environment]::GetFolderPath('LocalApplicationData')
$installDir = Join-Path $localAppData 'Finora\Superadmin'
$resolvedLocal = [System.IO.Path]::GetFullPath($localAppData).TrimEnd('\') + '\'
$resolvedInstall = [System.IO.Path]::GetFullPath($installDir).TrimEnd('\') + '\'

if (-not $resolvedInstall.StartsWith($resolvedLocal, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Unsafe uninstall target.'
}

Get-Process -Name 'FinoraSuperadmin' -ErrorAction SilentlyContinue | Stop-Process -Force
Remove-Item -LiteralPath (Join-Path ([Environment]::GetFolderPath('DesktopDirectory')) 'Finora Superadmin.lnk') -Force
Remove-Item -LiteralPath (Join-Path ([Environment]::GetFolderPath('Programs')) 'Finora\Finora Superadmin.lnk') -Force
Remove-Item -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\FinoraSuperadmin' -Recurse -Force
Remove-Item -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\App Paths\FinoraSuperadmin.exe' -Recurse -Force

Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden -ArgumentList @(
    '-NoProfile',
    '-Command',
    "Start-Sleep -Seconds 2; Remove-Item -LiteralPath '$installDir' -Recurse -Force"
)

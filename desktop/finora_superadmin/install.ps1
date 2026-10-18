param(
    [string]$ExePath = (Join-Path $PSScriptRoot 'dist\FinoraSuperadmin.exe'),
    [switch]$Launch
)

$ErrorActionPreference = 'Stop'
$localAppData = [Environment]::GetFolderPath('LocalApplicationData')
$installDir = Join-Path $localAppData 'Finora\Superadmin'
$installedExe = Join-Path $installDir 'FinoraSuperadmin.exe'
$installedUninstaller = Join-Path $installDir 'uninstall.ps1'
$desktopShortcut = Join-Path ([Environment]::GetFolderPath('DesktopDirectory')) 'Finora Superadmin.lnk'
$startMenuDir = Join-Path ([Environment]::GetFolderPath('Programs')) 'Finora'
$startMenuShortcut = Join-Path $startMenuDir 'Finora Superadmin.lnk'

if (-not (Test-Path -LiteralPath $ExePath)) {
    throw 'FinoraSuperadmin.exe was not found. Run build.ps1 first.'
}

New-Item -ItemType Directory -Path $installDir -Force | Out-Null
New-Item -ItemType Directory -Path $startMenuDir -Force | Out-Null
Copy-Item -LiteralPath $ExePath -Destination $installedExe -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'uninstall.ps1') -Destination $installedUninstaller -Force

$shell = New-Object -ComObject WScript.Shell
foreach ($shortcutPath in @($desktopShortcut, $startMenuShortcut)) {
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $installedExe
    $shortcut.WorkingDirectory = $installDir
    $shortcut.IconLocation = "$installedExe,0"
    $shortcut.Description = 'Finora Superadmin Desktop'
    $shortcut.Save()
}

$uninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\FinoraSuperadmin'
New-Item -Path $uninstallKey -Force | Out-Null
Set-ItemProperty -Path $uninstallKey -Name DisplayName -Value 'Finora Superadmin'
Set-ItemProperty -Path $uninstallKey -Name DisplayVersion -Value '1.0.0'
Set-ItemProperty -Path $uninstallKey -Name Publisher -Value 'Finora'
Set-ItemProperty -Path $uninstallKey -Name DisplayIcon -Value $installedExe
Set-ItemProperty -Path $uninstallKey -Name InstallLocation -Value $installDir
Set-ItemProperty -Path $uninstallKey -Name UninstallString -Value "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$installedUninstaller`""
Set-ItemProperty -Path $uninstallKey -Name NoModify -Value 1 -Type DWord
Set-ItemProperty -Path $uninstallKey -Name NoRepair -Value 1 -Type DWord

$appPathKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\App Paths\FinoraSuperadmin.exe'
New-Item -Path $appPathKey -Force | Out-Null
Set-Item -Path $appPathKey -Value $installedExe

if ($Launch) {
    Start-Process -FilePath $installedExe
}

Write-Output $installedExe

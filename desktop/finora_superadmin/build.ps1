$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$pythonPath = Join-Path $projectRoot 'venv\Scripts\python.exe'
$iconPath = Join-Path $PSScriptRoot 'finora-superadmin.ico'
$logoPath = Join-Path $projectRoot 'static\branding\finora-superadmin-mark.png'
$distPath = Join-Path $PSScriptRoot 'dist'
$workPath = Join-Path $PSScriptRoot 'build'
$specPath = Join-Path $PSScriptRoot 'spec'

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Python environment was not found.'
}

& $pythonPath -c "from PIL import Image; image=Image.open(r'$logoPath').convert('RGBA'); image.save(r'$iconPath', format='ICO', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])"

& $pythonPath -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name FinoraSuperadmin `
    --icon $iconPath `
    --add-data "$iconPath;." `
    --version-file (Join-Path $PSScriptRoot 'version_info.txt') `
    --distpath $distPath `
    --workpath $workPath `
    --specpath $specPath `
    --collect-all webview `
    (Join-Path $PSScriptRoot 'launcher.py')

$builtExe = Join-Path $distPath 'FinoraSuperadmin.exe'
if (-not (Test-Path -LiteralPath $builtExe)) {
    throw 'Desktop executable was not created.'
}

Write-Output $builtExe

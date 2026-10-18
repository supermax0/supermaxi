#Requires -Version 5.1
<#
.SYNOPSIS
  Build Delivery Agent APK and copy it to static/downloads/finora-delivery-agent.apk

  Usage:
    .\build_apk.ps1
    .\build_apk.ps1 -Variant debug
#>
param(
    [ValidateSet("release", "debug")]
    [string]$Variant = "release"
)

$ErrorActionPreference = "Stop"

function Test-AsciiOnlyPath([string]$p) {
    foreach ($ch in $p.ToCharArray()) {
        if ([int]$ch -gt 127) { return $false }
    }
    return $true
}

$projectRoot = $PSScriptRoot
$repoRoot = Resolve-Path (Join-Path $projectRoot "..\..")
$buildRoot = $projectRoot

if (-not (Test-AsciiOnlyPath $projectRoot)) {
    $buildRoot = Join-Path $env:TEMP "finora_delivery_agent_build"
    Write-Host "Non-ASCII path - copying project to: $buildRoot"
    if (Test-Path $buildRoot) {
        Remove-Item $buildRoot -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $buildRoot | Out-Null
    robocopy $projectRoot $buildRoot /E /XD .gradle build app\build /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
    if ($LASTEXITCODE -ge 8) {
        throw "robocopy failed (code $LASTEXITCODE)"
    }
}

if (-not $env:JAVA_HOME) {
    $candidates = @(
        "$env:USERPROFILE\Desktop\APK Lab\runtime\jdk-17",
        "$env:USERPROFILE\Desktop\APK Lab\APK_Lab_IDE\runtime\jdk-17",
        "$env:ProgramFiles\Android\Android Studio\jbr",
        "$env:LOCALAPPDATA\Programs\Android\Android Studio\jbr"
    )
    foreach ($j in $candidates) {
        if (Test-Path (Join-Path $j "bin\java.exe")) {
            $env:JAVA_HOME = $j
            break
        }
    }
}
if (-not $env:JAVA_HOME -or -not (Test-Path (Join-Path $env:JAVA_HOME "bin\java.exe"))) {
    throw "JAVA_HOME not found. Set it to the JBR folder inside Android Studio."
}

if (-not $env:ANDROID_HOME) {
    $env:ANDROID_HOME = Join-Path $env:LOCALAPPDATA "Android\Sdk"
}
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME

$gradleTask = if ($Variant -eq "release") { "assembleRelease" } else { "assembleDebug" }

Push-Location $buildRoot
try {
    Write-Host "Building ($gradleTask)..."
    & .\gradlew.bat --no-daemon $gradleTask
    if ($LASTEXITCODE -ne 0) {
        throw "Gradle failed (exit $LASTEXITCODE)"
    }
}
finally {
    Pop-Location
}

$apkName = if ($Variant -eq "release") { "app-release.apk" } else { "app-debug.apk" }
$apk = Join-Path $buildRoot "app\build\outputs\apk\$Variant\$apkName"
if (-not (Test-Path $apk)) {
    $legacy = Join-Path $buildRoot "app\build\outputs\apk\$Variant\app-release-unsigned.apk"
    if (($Variant -eq "release") -and (Test-Path $legacy)) {
        throw "Found unsigned APK only ($legacy). Rebuild after enabling release signingConfig."
    }
    throw "APK not found: $apk"
}

$downloadsDir = Join-Path $repoRoot "static\downloads"
New-Item -ItemType Directory -Force -Path $downloadsDir | Out-Null
$dest = Join-Path $downloadsDir "finora-delivery-agent.apk"
Copy-Item -Force $apk $dest
Write-Host ""
Write-Host "APK copied to: $dest"

#Requires -Version 5.1
<#
.SYNOPSIS
  بناء تطبيق Finora POS (debug) وتثبيته على الهاتف عبر USB باستخدام adb.

  قبل التشغيل:
  - فعّل "خيارات المطوّر" ثم "تصحيح أخطاء USB" على الهاتف.
  - وصّل الهاتف بالكمبيوتر واقبل طلب "السماح بتصحيح USB".
  - ثبّت Android SDK Platform-Tools (يأتي مع Android Studio).

  الاستخدام (من PowerShell داخل هذا المجلد):
    .\install_via_usb.ps1
#>
$ErrorActionPreference = "Stop"

function Test-AsciiOnlyPath([string]$p) {
    foreach ($ch in $p.ToCharArray()) {
        if ([int]$ch -gt 127) { return $false }
    }
    return $true
}

$projectRoot = $PSScriptRoot
$buildRoot = $projectRoot
if (-not (Test-AsciiOnlyPath $projectRoot)) {
    $buildRoot = Join-Path $env:TEMP "finora_pos_usb_build"
    Write-Host "المسار يحتوي أحرف غير لاتينية — نسخ المشروع مؤقتاً إلى: $buildRoot"
    if (Test-Path $buildRoot) {
        Remove-Item $buildRoot -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $buildRoot | Out-Null
    robocopy $projectRoot $buildRoot /E /XD .gradle build app\build /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
    if ($LASTEXITCODE -ge 8) {
        throw "فشل النسخ (robocopy code $LASTEXITCODE)"
    }
}

if (-not $env:JAVA_HOME) {
    $candidates = @(
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
    throw "لم يُعثر على JAVA_HOME. عيّنه يدوياً إلى مجلد JBR داخل Android Studio، مثال:`n  `$env:JAVA_HOME = 'C:\Program Files\Android\Android Studio\jbr'"
}

if (-not $env:ANDROID_HOME) {
    $env:ANDROID_HOME = Join-Path $env:LOCALAPPDATA "Android\Sdk"
}
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME

$adb = Join-Path $env:ANDROID_HOME "platform-tools\adb.exe"
if (-not (Test-Path $adb)) {
    throw "adb غير موجود في: $adb — ثبّت Android SDK Platform-Tools من Android Studio (SDK Manager)."
}

Push-Location $buildRoot
try {
    Write-Host "جاري البناء (assembleDebug)..."
    & .\gradlew.bat --no-daemon assembleDebug
    if ($LASTEXITCODE -ne 0) {
        throw "فشل Gradle (exit $LASTEXITCODE)"
    }
}
finally {
    Pop-Location
}

$apk = Join-Path $buildRoot "app\build\outputs\apk\debug\app-debug.apk"
if (-not (Test-Path $apk)) {
    throw "لم يُوجد الملف: $apk"
}

$outCopy = Join-Path $projectRoot "app-debug.apk"
Copy-Item -Force $apk $outCopy
Write-Host "نسخة الـ APK محفوظة أيضاً عند: $outCopy"

Write-Host "`nالأجهزة المتصلة:"
& $adb devices
$lines = & $adb devices 2>$null | Where-Object { $_ -match "`tdevice$" }
if (-not $lines) {
    Write-Warning "لا يوجد جهاز في وضع device. وصّل الهاتف بالUSB، فعّل تصحيح USB، واقبل التفويض على الشاشة."
    exit 1
}

Write-Host "`nجاري التثبيت على الهاتف..."
& $adb install -r $apk
if ($LASTEXITCODE -ne 0) {
    throw "فشل adb install (exit $LASTEXITCODE)"
}
Write-Host "`nتم التثبيت بنجاح. افتح تطبيق Finora POS على الهاتف."

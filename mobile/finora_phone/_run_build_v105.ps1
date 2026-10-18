$ErrorActionPreference = "Continue"
$env:JAVA_HOME = "C:\Users\msi\.jdks\ms-17.0.17"
$env:PATH = "$env:JAVA_HOME\bin;C:\flutter\bin;" + $env:PATH
Set-Location "C:\finora_phone_build"
$log = "C:\finora_phone_build\build_out_v105.txt"
$start = Get-Date -Format o
@(
  "=== START $start ==="
  (Select-String -Path pubspec.yaml -Pattern "^version:").Line
) | Set-Content $log -Encoding utf8
& C:\flutter\bin\flutter.bat pub get 2>&1 | Add-Content $log -Encoding utf8
Add-Content $log "pub_exit=$LASTEXITCODE" -Encoding utf8
& C:\flutter\bin\flutter.bat build apk --flavor staging --release --dart-define=FLAVOR=staging --dart-define=API_BASE_URL=https://www.finora.company --dart-define=TENANT_SLUG=super 2>&1 | Add-Content $log -Encoding utf8
Add-Content $log "build_exit=$LASTEXITCODE" -Encoding utf8
$apk = "C:\finora_phone_build\build\app\outputs\flutter-apk\app-staging-release.apk"
if (Test-Path $apk) {
  $item = Get-Item $apk
  Add-Content $log "apk_size=$($item.Length)" -Encoding utf8
  Add-Content $log "apk_time=$($item.LastWriteTime.ToString('o'))" -Encoding utf8
} else {
  Add-Content $log "apk_missing=1" -Encoding utf8
}
Add-Content $log "=== END $(Get-Date -Format o) ===" -Encoding utf8

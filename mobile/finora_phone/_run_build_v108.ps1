$ErrorActionPreference = "Continue"
$env:JAVA_HOME = "C:\Users\msi\.jdks\ms-17.0.17"
$env:PATH = "$env:JAVA_HOME\bin;C:\flutter\bin;" + $env:PATH
Set-Location C:\finora_phone_build
$log = "C:\finora_phone_build\build_out_v108.txt"
"=== START $(Get-Date -Format o) ===" | Out-File $log -Encoding utf8
Select-String -Path pubspec.yaml -Pattern "^version:" | Out-File $log -Append -Encoding utf8
& C:\flutter\bin\flutter.bat analyze --no-fatal-infos --no-fatal-warnings 2>&1 | Out-File $log -Append -Encoding utf8
"analyze_exit=$LASTEXITCODE" | Out-File $log -Append -Encoding utf8
& C:\flutter\bin\flutter.bat build apk --flavor staging --release --dart-define=FLAVOR=staging --dart-define=API_BASE_URL=https://www.finora.company --dart-define=TENANT_SLUG=super 2>&1 | Out-File $log -Append -Encoding utf8
"build_exit=$LASTEXITCODE" | Out-File $log -Append -Encoding utf8
$apk = "C:\finora_phone_build\build\app\outputs\flutter-apk\app-staging-release.apk"
if (Test-Path $apk) {
  $item = Get-Item $apk
  "apk_size=$($item.Length)" | Out-File $log -Append -Encoding utf8
  "apk_time=$($item.LastWriteTime.ToString('o'))" | Out-File $log -Append -Encoding utf8
} else {
  "apk_missing=1" | Out-File $log -Append -Encoding utf8
}
"=== END $(Get-Date -Format o) ===" | Out-File $log -Append -Encoding utf8

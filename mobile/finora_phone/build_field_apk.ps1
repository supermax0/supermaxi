$ErrorActionPreference = "Continue"
$env:JAVA_HOME = "C:\Users\msi\.jdks\ms-17.0.17"
$env:PATH = "$env:JAVA_HOME\bin;C:\flutter\bin;" + $env:PATH
Set-Location C:\finora_phone_build
$log = "C:\finora_phone_build\build_out.txt"
"=== START $(Get-Date -Format o) ===" | Out-File $log -Encoding utf8
java -version 2>&1 | Out-File $log -Append -Encoding utf8
& C:\flutter\bin\flutter.bat pub get 2>&1 | Out-File $log -Append -Encoding utf8
$pubExit = $LASTEXITCODE
"pub_exit=$pubExit" | Out-File $log -Append -Encoding utf8
& C:\flutter\bin\flutter.bat build apk --flavor staging --release --dart-define=FLAVOR=staging --dart-define=API_BASE_URL=https://www.finora.company --dart-define=TENANT_SLUG=super 2>&1 | Out-File $log -Append -Encoding utf8
$buildExit = $LASTEXITCODE
"build_exit=$buildExit" | Out-File $log -Append -Encoding utf8
"=== END $(Get-Date -Format o) ===" | Out-File $log -Append -Encoding utf8
exit $buildExit

param(
    [string]$ServerSsh = "root@187.124.29.5",
    [string]$ServerProject = "/var/www/finora/supermaxi",
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$BackupRoot = "",
    [ValidateRange(1, 3650)]
    [int]$RetentionDays = 30
)

$ErrorActionPreference = "Stop"
if ($ServerSsh -notmatch '^[A-Za-z0-9._-]+@[A-Za-z0-9.-]+$') {
    throw "عنوان SSH غير صالح."
}
if ($ServerProject -notmatch '^/[A-Za-z0-9._/-]+$') {
    throw "مسار المشروع على السيرفر غير صالح."
}

$resolvedProject = (Resolve-Path -LiteralPath $ProjectRoot).Path
if (-not $BackupRoot) {
    $BackupRoot = Join-Path $resolvedProject "backups\server-daily"
}
New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null
$resolvedBackup = (Resolve-Path -LiteralPath $BackupRoot).Path

$ssh = Join-Path $env:WINDIR "System32\OpenSSH\ssh.exe"
$scp = Join-Path $env:WINDIR "System32\OpenSSH\scp.exe"
if (-not (Test-Path -LiteralPath $ssh -PathType Leaf) -or -not (Test-Path -LiteralPath $scp -PathType Leaf)) {
    throw "أدوات SSH الخاصة بويندوز غير موجودة."
}

$stamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$token = [Guid]::NewGuid().ToString("N")
$remoteFile = "/tmp/finora-company-backup-$token.tar.zst"
$remoteScript = "/tmp/finora-company-backup-$token.sh"
$temporaryFile = Join-Path ([IO.Path]::GetTempPath()) ("finora-company-backup-$token.tar.zst")
$targetFile = Join-Path $resolvedBackup ("finora_companies_$stamp.tar.zst")
$logFile = Join-Path $resolvedBackup "backup.log"

$localServerScript = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "create_server_company_backup.sh")).Path

try {
    & $scp -q -o BatchMode=yes -o ConnectTimeout=20 $localServerScript "${ServerSsh}:$remoteScript"
    if ($LASTEXITCODE -ne 0) {
        throw "فشل إرسال برنامج النسخ الآمن إلى السيرفر برمز خروج $LASTEXITCODE"
    }

    & $ssh -o BatchMode=yes -o ConnectTimeout=20 $ServerSsh "bash '$remoteScript' '$ServerProject' '$remoteFile'"
    if ($LASTEXITCODE -ne 0) {
        throw "فشل إنشاء حزمة الشركات على السيرفر برمز خروج $LASTEXITCODE"
    }

    $remoteSource = "${ServerSsh}:$remoteFile"
    & $scp -q -o BatchMode=yes -o ConnectTimeout=20 $remoteSource $temporaryFile
    if ($LASTEXITCODE -ne 0) {
        throw "فشل تنزيل النسخة من السيرفر برمز خروج $LASTEXITCODE"
    }

    $temporaryBackup = Get-Item -LiteralPath $temporaryFile
    if ($temporaryBackup.Length -le 0) {
        throw "النسخة المنزلة من السيرفر فارغة."
    }

    Move-Item -LiteralPath $temporaryFile -Destination $targetFile
} finally {
    & $ssh -o BatchMode=yes -o ConnectTimeout=10 $ServerSsh "rm -f -- '$remoteFile' '$remoteScript'" 2>$null
    Remove-Item -LiteralPath $temporaryFile -Force -ErrorAction SilentlyContinue
}

$backupFile = Get-Item -LiteralPath $targetFile
$cutoff = (Get-Date).AddDays(-$RetentionDays)
Get-ChildItem -LiteralPath $resolvedBackup -File -Filter "*.tar.zst" |
    Where-Object { $_.LastWriteTime -lt $cutoff -and $_.FullName.StartsWith($resolvedBackup, [StringComparison]::OrdinalIgnoreCase) } |
    Remove-Item -Force

$message = "{0} COMPANIES_OK file={1} size={2:N0} bytes retention={3}d" -f `
    (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $backupFile.Name, $backupFile.Length, $RetentionDays
Add-Content -LiteralPath $logFile -Value $message -Encoding UTF8
Write-Output $message

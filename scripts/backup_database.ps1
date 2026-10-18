param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$BackupRoot = "",
    [ValidateRange(1, 3650)]
    [int]$RetentionDays = 30
)

$ErrorActionPreference = "Stop"
$resolvedProject = (Resolve-Path -LiteralPath $ProjectRoot).Path
if (-not $BackupRoot) {
    $BackupRoot = Join-Path $resolvedProject "backups\daily"
}
New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null
$resolvedBackup = (Resolve-Path -LiteralPath $BackupRoot).Path
$logFile = Join-Path $resolvedBackup "backup.log"
$statusFile = Join-Path $resolvedBackup "last_backup_status.json"

function Write-BackupStatus {
    param(
        [ValidateSet("SUCCESS", "FAIL")]
        [string]$Status,
        [string]$Message = "",
        [string]$FileName = "",
        [int64]$SizeBytes = 0,
        [string]$Database = ""
    )
    $payload = @{
        status = $Status
        at = (Get-Date).ToUniversalTime().ToString("o")
        message = $Message
        file = $FileName
        size_bytes = $SizeBytes
        retention_days = $RetentionDays
        database = $Database
    }
    $payload | ConvertTo-Json | Set-Content -LiteralPath $statusFile -Encoding UTF8
    $line = "{0} {1} {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Status, $Message
    Add-Content -LiteralPath $logFile -Value $line -Encoding UTF8
}

try {
    $envFile = Join-Path $resolvedProject ".env"
    if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
        throw "ملف .env غير موجود: $envFile"
    }

    $databaseLine = Get-Content -LiteralPath $envFile | Where-Object {
        $_ -match '^\s*DATABASE_URL\s*='
    } | Select-Object -First 1
    if (-not $databaseLine) {
        throw "DATABASE_URL غير موجود داخل ملف .env"
    }

    $databaseUrl = ($databaseLine -split '=', 2)[1].Trim().Trim('"').Trim("'")
    if ($databaseUrl -notmatch '^postgres(?:ql)?://') {
        throw "النسخ اليومي الحالي يدعم PostgreSQL فقط. نوع قاعدة البيانات غير مدعوم."
    }

    $uri = [Uri]$databaseUrl
    $credentials = $uri.UserInfo -split ':', 2
    $databaseUser = [Uri]::UnescapeDataString($credentials[0])
    $databasePassword = if ($credentials.Count -gt 1) {
        [Uri]::UnescapeDataString($credentials[1])
    } else { "" }
    $databaseName = [Uri]::UnescapeDataString($uri.AbsolutePath.TrimStart('/'))
    $databasePort = if ($uri.Port -gt 0) { $uri.Port } else { 5432 }
    $safeDatabaseName = $databaseName -replace '[^A-Za-z0-9_-]', '_'

    $pgDumpCandidates = @(
        (Get-Command pg_dump.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1),
        "C:\Program Files\PostgreSQL\18\bin\pg_dump.exe",
        "C:\Program Files\PostgreSQL\17\bin\pg_dump.exe",
        "C:\Program Files\PostgreSQL\16\bin\pg_dump.exe",
        "C:\Program Files\PostgreSQL\15\bin\pg_dump.exe"
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) }
    $pgDump = $pgDumpCandidates | Select-Object -First 1
    if (-not $pgDump) {
        throw "لم يتم العثور على pg_dump.exe. ثبّت أدوات PostgreSQL أولاً."
    }

    $stamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
    $targetFile = Join-Path $resolvedBackup ("{0}_{1}.dump" -f $safeDatabaseName, $stamp)
    $temporaryFile = Join-Path ([IO.Path]::GetTempPath()) ("finora-backup-{0}.dump" -f ([Guid]::NewGuid().ToString("N")))

    try {
        $env:PGPASSWORD = $databasePassword
        & $pgDump `
            --format=custom `
            --compress=6 `
            --no-owner `
            --no-privileges `
            --host=$($uri.Host) `
            --port=$databasePort `
            --username=$databaseUser `
            --file=$temporaryFile `
            $databaseName
        if ($LASTEXITCODE -ne 0) {
            Remove-Item -LiteralPath $temporaryFile -Force -ErrorAction SilentlyContinue
            throw "فشل pg_dump برمز خروج $LASTEXITCODE"
        }
    } finally {
        Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    }

    $temporaryBackup = Get-Item -LiteralPath $temporaryFile
    if ($temporaryBackup.Length -le 0) {
        Remove-Item -LiteralPath $temporaryFile -Force -ErrorAction SilentlyContinue
        throw "تم إنشاء ملف نسخة فارغ."
    }

    $pgRestore = Join-Path (Split-Path -Parent $pgDump) "pg_restore.exe"
    if (Test-Path -LiteralPath $pgRestore -PathType Leaf) {
        & $pgRestore --list $temporaryFile | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Remove-Item -LiteralPath $temporaryFile -Force -ErrorAction SilentlyContinue
            throw "فشل التحقق من سلامة النسخة الاحتياطية."
        }
    }

    Move-Item -LiteralPath $temporaryFile -Destination $targetFile
    $backupFile = Get-Item -LiteralPath $targetFile
    if ($backupFile.Length -le 0) {
        throw "تم إنشاء ملف نسخة فارغ."
    }

    $cutoff = (Get-Date).AddDays(-$RetentionDays)
    Get-ChildItem -LiteralPath $resolvedBackup -File -Filter "*.dump" |
        Where-Object { $_.LastWriteTime -lt $cutoff -and $_.FullName.StartsWith($resolvedBackup, [StringComparison]::OrdinalIgnoreCase) } |
        Remove-Item -Force

    $message = "OK file={0} size={1:N0} bytes retention={2}d" -f $backupFile.Name, $backupFile.Length, $RetentionDays
    Write-BackupStatus -Status "SUCCESS" -Message $message -FileName $backupFile.Name -SizeBytes ([int64]$backupFile.Length) -Database $safeDatabaseName
    Write-Output ("{0} SUCCESS {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $message)
}
catch {
    $err = $_.Exception.Message
    Write-BackupStatus -Status "FAIL" -Message $err
    Write-Error $err
    exit 1
}

# push_to_github.ps1 - Push updates to GitHub (PowerShell)
# Usage: .\scripts\push_to_github.ps1 ["commit message"]

param(
    [string]$Message = "Update: sync latest changes"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $root ".git"))) {
    $root = Get-Location
}
Set-Location $root

Write-Host "Git status..." -ForegroundColor Cyan
git status

$status = git status --porcelain
if ([string]::IsNullOrWhiteSpace($status)) {
    Write-Host "No changes to push." -ForegroundColor Yellow
    exit 0
}

Write-Host "`nAdding changes..." -ForegroundColor Cyan
git add -A
git reset HEAD -- .env 2>$null
git status --short

Write-Host "`nCommit: $Message" -ForegroundColor Cyan
git commit -m $Message
if ($LASTEXITCODE -ne 0) {
    Write-Host "Commit failed or nothing to commit." -ForegroundColor Yellow
    exit 0
}

Write-Host "`nPushing to origin main..." -ForegroundColor Cyan
git push origin main
if ($LASTEXITCODE -eq 0) {
    Write-Host "`nPushed to GitHub successfully." -ForegroundColor Green
} else {
    Write-Host "`nPush failed. Check remote and permissions (git remote -v)." -ForegroundColor Red
    exit 1
}

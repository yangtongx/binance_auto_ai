# Write secrets/telegram_bot_token and secrets/telegram_chat_id from deploy/telegram.credentials
# Usage:
#   1) Edit deploy\telegram.credentials (line1=token, line2=chat_id) — only once
#   2) .\scripts\install-telegram-secrets.ps1
#   3) docker compose up -d --build

param(
    [string]$CredentialsFile = ""
)

$Repo = Split-Path $PSScriptRoot -Parent
if (-not $CredentialsFile) {
    $CredentialsFile = Join-Path $Repo "deploy\telegram.credentials"
}

if (-not (Test-Path $CredentialsFile)) {
    Copy-Item (Join-Path $Repo "deploy\telegram.credentials.example") $CredentialsFile
    Write-Host "Created $CredentialsFile — paste your bot token on line 1, then run this script again."
    exit 1
}

$lines = @(Get-Content $CredentialsFile | ForEach-Object { $_.Trim() } | Where-Object { $_ -and -not $_.StartsWith("#") })
if ($lines.Count -lt 2) {
    Write-Error "Need 2 lines in $CredentialsFile : token, then chat_id"
    exit 1
}

$token = $lines[0]
$chatId = $lines[1]
if ($token -match "PASTE|REPLACE|YOUR") {
    Write-Error "Replace line 1 in $CredentialsFile with your real token from @BotFather"
    exit 1
}
if ($token -notmatch '^\d+:[A-Za-z0-9_-]+$') {
    Write-Warning "Token format looks unusual (expected 123456:ABC...). Continuing anyway."
}

$secretsDir = Join-Path $Repo "secrets"
New-Item -ItemType Directory -Force $secretsDir | Out-Null
$tokenPath = Join-Path $secretsDir "telegram_bot_token"
$chatPath = Join-Path $secretsDir "telegram_chat_id"
[System.IO.File]::WriteAllText($tokenPath, $token)
[System.IO.File]::WriteAllText($chatPath, $chatId)
Write-Host "Wrote secrets\telegram_bot_token and secrets\telegram_chat_id"
Write-Host "Local test: .\scripts\telegram-test.ps1  (reads from secrets via env if you set it)"
Write-Host "Docker: docker compose up -d --build"

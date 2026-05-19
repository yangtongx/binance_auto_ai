# Upload Telegram secret files to server (no editing .env).
# Prerequisite: .\scripts\install-telegram-secrets.ps1
#
# Usage:
#   .\scripts\upload-telegram-secrets.ps1
#   .\scripts\upload-telegram-secrets.ps1 -Server root@43.167.237.252 -RemotePath /opt/futures_llm_bot

param(
    [string]$Server = "root@43.167.237.252",
    [string]$RemotePath = "/opt/futures_llm_bot"
)

$Repo = Split-Path $PSScriptRoot -Parent
$tokenLocal = Join-Path $Repo "secrets\telegram_bot_token"
$chatLocal = Join-Path $Repo "secrets\telegram_chat_id"

foreach ($f in @($tokenLocal, $chatLocal)) {
    if (-not (Test-Path $f)) {
        Write-Error "Missing $f — run .\scripts\install-telegram-secrets.ps1 first"
        exit 1
    }
}

$remoteSecrets = "${Server}:${RemotePath}/secrets"
Write-Host "Creating remote secrets dir..."
ssh $Server "mkdir -p $RemotePath/secrets"
Write-Host "scp telegram secrets -> $remoteSecrets/"
scp $tokenLocal "${remoteSecrets}/telegram_bot_token"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
scp $chatLocal "${remoteSecrets}/telegram_chat_id"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "Done. On server: cd $RemotePath && docker compose up -d --build"

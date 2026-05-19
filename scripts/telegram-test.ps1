# Send a test message via Telegram Bot API (verify token + chat_id).
# Usage:
#   $env:TELEGRAM_BOT_TOKEN = "123:ABC..."
#   $env:TELEGRAM_CHAT_ID = "123456789"
#   .\scripts\telegram-test.ps1

$Repo = Split-Path $PSScriptRoot -Parent
$token = $env:TELEGRAM_BOT_TOKEN
$chatId = $env:TELEGRAM_CHAT_ID
$tokenFile = Join-Path $Repo "secrets\telegram_bot_token"
$chatFile = Join-Path $Repo "secrets\telegram_chat_id"
if (-not $token -and (Test-Path $tokenFile)) { $token = (Get-Content $tokenFile -Raw).Trim() }
if (-not $chatId -and (Test-Path $chatFile)) { $chatId = (Get-Content $chatFile -Raw).Trim() }
if (-not $token -or -not $chatId) {
    Write-Error "Set env vars or run .\scripts\install-telegram-secrets.ps1 first."
    exit 1
}

$body = @{
    chat_id = $chatId
    text    = "futures-llm-bot telegram test OK"
} | ConvertTo-Json -Compress

$uri = "https://api.telegram.org/bot$token/sendMessage"
try {
    $resp = Invoke-RestMethod -Uri $uri -Method Post -ContentType "application/json" -Body $body
    if ($resp.ok) {
        Write-Host "OK: message sent to chat $chatId"
    } else {
        Write-Error "API returned ok=false: $($resp | ConvertTo-Json -Compress)"
        exit 1
    }
} catch {
    Write-Error $_
    exit 1
}

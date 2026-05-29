# 从 Windows 上传 .env 到服务器（无需在 Linux 上 nano）
# 用法：
#   .\scripts\upload-env.ps1
#   .\scripts\upload-env.ps1 -Server root@43.167.237.252 -RemotePath /root/futures_llm_bot
#   .\scripts\upload-env.ps1 -UseServerTemplate   # 上传 deploy\server.env 而非本地 .env

param(
    [string]$Server = "root@43.167.237.252",
    [string]$RemotePath = "/root/futures_llm_bot",
    [switch]$UseServerTemplate
)

$Repo = Split-Path $PSScriptRoot -Parent

if ($UseServerTemplate) {
    $LocalFile = Join-Path $Repo "deploy\server.env"
} else {
    $LocalFile = Join-Path $Repo ".env"
    if (-not (Test-Path $LocalFile)) {
        $LocalFile = Join-Path $Repo "deploy\server.env"
        Write-Host "No local .env — using deploy\server.env"
    }
}

if (-not (Test-Path $LocalFile)) {
    Write-Error "File not found: $LocalFile"
    exit 1
}

$Remote = "${Server}:${RemotePath}/.env"
Write-Host "scp $LocalFile -> $Remote"
scp $LocalFile $Remote
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "Done. On server: cd $RemotePath && docker compose up -d --build"

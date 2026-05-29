# 裁剪 Docker 容器日志为近 N 小时（默认 2）
param(
    [string]$ContainerName = "binance-auto-ai",
    [double]$Hours = 2,
    [string]$Service = "bot"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "docker not found"
}
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "python not found"
}

$logPath = docker inspect --format='{{.LogPath}}' $ContainerName 2>$null
if (-not $logPath -or -not (Test-Path $logPath)) {
    Write-Error "log file not found for container $ContainerName"
}

$before = (Get-Item $logPath).Length
$filtered = Join-Path $env:TEMP "binance-auto-ai-log-trim.json"
python "$Root\scripts\trim_docker_logs.py" $logPath $filtered --hours $Hours

Push-Location $Root
try {
    Write-Host "stopping $Service ..."
    docker compose stop $Service
    Copy-Item -Force $filtered $logPath
    Write-Host "starting $Service ..."
    docker compose start $Service
}
finally {
    Pop-Location
    Remove-Item -Force $filtered -ErrorAction SilentlyContinue
}

$after = (Get-Item $logPath).Length
Write-Host "OK: $ContainerName log ${before}B -> ${after}B (keep ${Hours}h)"

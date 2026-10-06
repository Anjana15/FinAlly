# Start FinAlly in Docker (Windows PowerShell). Idempotent: safe to run repeatedly.
#
# Usage: .\scripts\start_windows.ps1 [-Build] [-NoOpen]
#   -Build   rebuild the image even if it already exists
#   -NoOpen  don't open the browser
param(
    [switch]$Build,
    [switch]$NoOpen
)

# 'Continue' so native docker stderr never throws; failures are checked via $LASTEXITCODE.
$ErrorActionPreference = 'Continue'

$Image = 'finally'
$Container = 'finally'
$Volume = 'finally-data'
$Port = if ($env:FINALLY_PORT) { $env:FINALLY_PORT } else { '8000' }
$Url = "http://localhost:$Port"

$RootDir = Split-Path -Parent $PSScriptRoot
Set-Location $RootDir

function Open-App {
    if (-not $NoOpen) { Start-Process $Url | Out-Null }
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host 'Error: docker is not installed or not on PATH.'
    exit 1
}
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Error: The Docker daemon is not running (start Docker Desktop and retry).'
    exit 1
}

# .env is required by `docker run --env-file`.
if (-not (Test-Path '.env')) {
    if (Test-Path '.env.example') {
        Copy-Item '.env.example' '.env'
        Write-Host 'Notice: created .env from .env.example. Add your OPENROUTER_API_KEY to .env for AI chat'
        Write-Host '        (or set LLM_MOCK=true), then restart: .\scripts\stop_windows.ps1; .\scripts\start_windows.ps1'
    } else {
        Write-Host 'Error: .env and .env.example are both missing.'
        exit 1
    }
}

# Build the image if it's missing or a rebuild was requested.
docker image inspect $Image *> $null
$imageExists = ($LASTEXITCODE -eq 0)
if ($Build -or -not $imageExists) {
    Write-Host "Building image '$Image'..."
    docker build -t $Image .
    if ($LASTEXITCODE -ne 0) { Write-Host 'Error: docker build failed.'; exit 1 }
    if ($Build) {
        docker container inspect $Container *> $null
        if ($LASTEXITCODE -eq 0) {
            Write-Host 'Replacing existing container with the new image...'
            docker rm -f $Container *> $null
        }
    }
}

$running = (docker container inspect -f '{{.State.Running}}' $Container 2>$null)
$containerExists = ($LASTEXITCODE -eq 0)
if ($containerExists -and $running -eq 'true') {
    Write-Host "FinAlly is already running at $Url"
    Open-App
    exit 0
}

# Remove a stale stopped container, if any.
if ($containerExists) {
    docker rm -f $Container *> $null
}

Write-Host "Starting container '$Container'..."
docker run -d --name $Container -v "${Volume}:/app/db" -p "${Port}:8000" --env-file .env $Image | Out-Null
if ($LASTEXITCODE -ne 0) {
    docker rm -f $Container *> $null
    Write-Host "Error: could not start the container. If port $Port is already in use, free it or set `$env:FINALLY_PORT (e.g. 8001) and rerun."
    exit 1
}

Write-Host -NoNewline 'Waiting for the app to become healthy'
$healthy = $false
for ($i = 0; $i -lt 60; $i++) {
    try {
        $resp = Invoke-WebRequest -Uri "$Url/api/health" -UseBasicParsing -TimeoutSec 2
        if ($resp.StatusCode -eq 200) { $healthy = $true; break }
    } catch { }
    $state = (docker container inspect -f '{{.State.Running}}' $Container 2>$null)
    if ($state -ne 'true') { break }
    Write-Host -NoNewline '.'
    Start-Sleep -Seconds 1
}
Write-Host ''

if (-not $healthy) {
    Write-Host 'Error: FinAlly did not become healthy. Recent logs:'
    docker logs --tail 40 $Container
    exit 1
}

Write-Host "FinAlly is running at $Url"
Open-App

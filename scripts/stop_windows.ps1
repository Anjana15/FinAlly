# Stop FinAlly (Windows PowerShell). Idempotent. Keeps the 'finally-data' volume,
# so your portfolio persists across restarts.
# 'Continue' so native docker stderr never throws; failures are checked via $LASTEXITCODE.
$ErrorActionPreference = 'Continue'

$Container = 'finally'

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host 'Error: docker is not installed or not on PATH.'
    exit 1
}

docker container inspect $Container *> $null
if ($LASTEXITCODE -eq 0) {
    Write-Host "Stopping container '$Container'..."
    docker stop $Container *> $null
    docker rm $Container *> $null
    Write-Host "FinAlly stopped. Data volume 'finally-data' was kept."
} else {
    Write-Host 'FinAlly is not running.'
}

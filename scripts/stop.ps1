# Aegis-1 Stop Script for Windows PowerShell

Write-Host "Stopping Aegis-1 services..." -ForegroundColor Yellow
docker compose down

Write-Host "Services stopped." -ForegroundColor Green

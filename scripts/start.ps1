# Aegis-1 Startup Script for Windows PowerShell

param(
    [Parameter(Position=0)]
    [ValidateSet("up", "down", "restart", "logs", "build", "status", "clean")]
    [string]$Action = "up",
    
    [Parameter(Position=1)]
    [string]$Service = ""
)

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Aegis-1 Trading System" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

# Check for .env file
if (-not (Test-Path ".env")) {
    Write-Host "Creating .env from env.example..." -ForegroundColor Yellow
    Copy-Item "env.example" ".env"
    Write-Host "Please configure your .env file with API keys before starting." -ForegroundColor Red
    exit 1
}

# Check Docker
try {
    docker --version | Out-Null
} catch {
    Write-Host "Docker is not installed. Please install Docker Desktop first." -ForegroundColor Red
    exit 1
}

switch ($Action) {
    "up" {
        Write-Host "Starting Aegis-1 services..." -ForegroundColor Green
        docker compose up -d
        Write-Host ""
        Write-Host "Services started! Access points:" -ForegroundColor Green
        Write-Host "  - Frontend:  http://localhost:3000" -ForegroundColor White
        Write-Host "  - API:       http://localhost:8000" -ForegroundColor White
        Write-Host "  - API Docs:  http://localhost:8000/docs" -ForegroundColor White
        Write-Host "  - RabbitMQ:  http://localhost:15672" -ForegroundColor White
        Write-Host ""
        Write-Host "View logs with: .\scripts\start.ps1 logs" -ForegroundColor Cyan
    }
    "down" {
        Write-Host "Stopping Aegis-1 services..." -ForegroundColor Yellow
        docker compose down
    }
    "restart" {
        Write-Host "Restarting Aegis-1 services..." -ForegroundColor Yellow
        docker compose restart
    }
    "logs" {
        if ($Service) {
            docker compose logs -f $Service
        } else {
            docker compose logs -f
        }
    }
    "build" {
        Write-Host "Building Aegis-1 images..." -ForegroundColor Green
        docker compose build --no-cache
    }
    "status" {
        docker compose ps
    }
    "clean" {
        Write-Host "Stopping and removing all containers, volumes, and images..." -ForegroundColor Red
        docker compose down -v --rmi local
    }
}

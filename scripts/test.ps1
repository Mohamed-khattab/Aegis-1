# Aegis-1 Test Runner Script for Windows PowerShell

param(
    [Parameter(Position=0)]
    [ValidateSet("all", "backend", "frontend", "unit", "integration", "e2e", "coverage")]
    [string]$TestType = "all",
    
    [Parameter()]
    [switch]$Verbose
)

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Aegis-1 Test Suite" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

$ProjectRoot = Split-Path -Parent $PSScriptRoot

function Run-BackendTests {
    param([string]$Pattern = "")
    
    Write-Host "Running Backend Tests..." -ForegroundColor Yellow
    Push-Location "$ProjectRoot/backend"
    
    $pytestArgs = @("-v", "--tb=short")
    if ($Pattern) {
        $pytestArgs += "-k"
        $pytestArgs += $Pattern
    }
    
    python -m pytest $pytestArgs
    $exitCode = $LASTEXITCODE
    
    Pop-Location
    return $exitCode
}

function Run-FrontendTests {
    Write-Host "Running Frontend Tests..." -ForegroundColor Yellow
    Push-Location "$ProjectRoot/frontend"
    
    npm run test:run
    $exitCode = $LASTEXITCODE
    
    Pop-Location
    return $exitCode
}

function Run-CoverageTests {
    Write-Host "Running Coverage Tests..." -ForegroundColor Yellow
    
    # Backend coverage
    Push-Location "$ProjectRoot/backend"
    python -m pytest --cov=. --cov-report=html --cov-report=term-missing
    Pop-Location
    
    # Frontend coverage
    Push-Location "$ProjectRoot/frontend"
    npm run test:coverage
    Pop-Location
}

$exitCode = 0

switch ($TestType) {
    "all" {
        $backendResult = Run-BackendTests
        $frontendResult = Run-FrontendTests
        $exitCode = [Math]::Max($backendResult, $frontendResult)
    }
    "backend" {
        $exitCode = Run-BackendTests
    }
    "frontend" {
        $exitCode = Run-FrontendTests
    }
    "unit" {
        $exitCode = Run-BackendTests -Pattern "not integration and not e2e"
    }
    "integration" {
        $exitCode = Run-BackendTests -Pattern "integration"
    }
    "e2e" {
        $exitCode = Run-BackendTests -Pattern "e2e"
    }
    "coverage" {
        Run-CoverageTests
    }
}

Write-Host ""
if ($exitCode -eq 0) {
    Write-Host "All tests passed!" -ForegroundColor Green
} else {
    Write-Host "Some tests failed." -ForegroundColor Red
}

exit $exitCode

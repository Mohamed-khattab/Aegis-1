#!/bin/bash

# Aegis-1 Test Runner Script for Linux/macOS

set -e

TEST_TYPE=${1:-all}
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "=========================================="
echo "  Aegis-1 Test Suite"
echo "=========================================="
echo ""

run_backend_tests() {
    local pattern=${1:-""}
    
    echo "Running Backend Tests..."
    cd "$PROJECT_ROOT/backend"
    
    if [ -n "$pattern" ]; then
        python -m pytest -v --tb=short -k "$pattern"
    else
        python -m pytest -v --tb=short
    fi
}

run_frontend_tests() {
    echo "Running Frontend Tests..."
    cd "$PROJECT_ROOT/frontend"
    npm run test:run
}

run_coverage_tests() {
    echo "Running Coverage Tests..."
    
    # Backend coverage
    cd "$PROJECT_ROOT/backend"
    python -m pytest --cov=. --cov-report=html --cov-report=term-missing
    
    # Frontend coverage
    cd "$PROJECT_ROOT/frontend"
    npm run test:coverage
}

case $TEST_TYPE in
    all)
        run_backend_tests
        run_frontend_tests
        ;;
    backend)
        run_backend_tests
        ;;
    frontend)
        run_frontend_tests
        ;;
    unit)
        run_backend_tests "not integration and not e2e"
        ;;
    integration)
        run_backend_tests "integration"
        ;;
    e2e)
        run_backend_tests "e2e"
        ;;
    coverage)
        run_coverage_tests
        ;;
    *)
        echo "Usage: $0 {all|backend|frontend|unit|integration|e2e|coverage}"
        exit 1
        ;;
esac

echo ""
echo "Tests completed!"

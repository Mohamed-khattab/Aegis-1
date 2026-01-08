#!/bin/bash

# Aegis-1 Startup Script for Linux/macOS

set -e

ACTION=${1:-up}
SERVICE=${2:-}

echo "=========================================="
echo "  Aegis-1 Trading System"
echo "=========================================="

# Check for .env file
if [ ! -f ".env" ]; then
    echo "Creating .env from env.example..."
    cp env.example .env
    echo "Please configure your .env file with API keys before starting."
    exit 1
fi

# Check Docker
if ! command -v docker &> /dev/null; then
    echo "Docker is not installed. Please install Docker first."
    exit 1
fi

case $ACTION in
    up)
        echo "Starting Aegis-1 services..."
        docker compose up -d
        echo ""
        echo "Services started! Access points:"
        echo "  - Frontend:  http://localhost:3000"
        echo "  - API:       http://localhost:8000"
        echo "  - API Docs:  http://localhost:8000/docs"
        echo "  - RabbitMQ:  http://localhost:15672"
        echo ""
        echo "View logs with: ./scripts/start.sh logs"
        ;;
    down)
        echo "Stopping Aegis-1 services..."
        docker compose down
        ;;
    restart)
        echo "Restarting Aegis-1 services..."
        docker compose restart
        ;;
    logs)
        if [ -n "$SERVICE" ]; then
            docker compose logs -f "$SERVICE"
        else
            docker compose logs -f
        fi
        ;;
    build)
        echo "Building Aegis-1 images..."
        docker compose build --no-cache
        ;;
    status)
        docker compose ps
        ;;
    clean)
        echo "Stopping and removing all containers, volumes, and images..."
        docker compose down -v --rmi local
        ;;
    *)
        echo "Usage: $0 {up|down|restart|logs|build|status|clean} [service]"
        exit 1
        ;;
esac

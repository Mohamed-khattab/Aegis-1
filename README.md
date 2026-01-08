# Aegis-1: Multi-Layer Agentic Trading System

A high-maturity, modular, agentic trading system using a Blackboard Architecture to allow multiple specialized "plugs" to contribute to high-confidence trading decisions.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     DATA FEED LAYER                              │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐   │
│  │ Market   │ │ News     │ │Historical│ │ Alternative Data │   │
│  │ Feed     │ │ Feed     │ │ Feed     │ │ Feed             │   │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────────┬─────────┘   │
└───────┼────────────┼────────────┼────────────────┼──────────────┘
        │            │            │                │
        v            v            v                v
┌─────────────────────────────────────────────────────────────────┐
│                   INTELLIGENCE LAYER (Plugs)                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐   │
│  │ News     │ │ Gemini   │ │ Quant    │ │ Risk Analyst     │   │
│  │ Sentry   │ │ Vector   │ │ Engine   │ │ (Veto Power)     │   │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────────┬─────────┘   │
└───────┼────────────┼────────────┼────────────────┼──────────────┘
        │            │            │                │
        v            v            v                v
┌─────────────────────────────────────────────────────────────────┐
│                    BLACKBOARD LAYER                              │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │              Core Orchestrator (LangGraph)                  │ │
│  │  • Consensus Resolution (<100ms)                           │ │
│  │  • Dynamic Weighting (Plug Performance Ledger)             │ │
│  │  • Adversarial Debating (Bull/Bear Agents)                 │ │
│  └────────────────────────────────────────────────────────────┘ │
│                           │                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │    Redis     │  │  TimescaleDB │  │      Pinecone        │  │
│  │   (State)    │  │  (Signals)   │  │     (Vectors)        │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                            │
                            v
┌─────────────────────────────────────────────────────────────────┐
│                      OUTPUT LAYER                                │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────┐ │
│  │ Webhook  │ │ Email    │ │ Database │ │ RabbitMQ │ │  UI   │ │
│  │ Output   │ │ Output   │ │ Log      │ │ Output   │ │(WS)   │ │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └───────┘ │
└─────────────────────────────────────────────────────────────────┘
```

## Key Features

- **Modular Plug Architecture**: Hot-swappable intelligence plugs with automatic weight adjustment
- **Multi-Asset Support**: Crypto (Binance, Coinbase) and Stocks (Alpaca, Polygon)
- **Real-Time Processing**: <1.2s end-to-end latency for AI trades, <100ms for emergency exits
- **Risk Management**: VaR-based position sizing, max drawdown limits, kill switch
- **Audit Trail**: Full blackboard snapshot at every trade for post-mortem analysis
- **Multiple Output Channels**: Webhook, Email, Database, Message Queue, WebSocket

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Python 3.11+
- Node.js 18+

### Setup

1. Clone the repository:
```bash
git clone https://github.com/yourusername/aegis-1.git
cd aegis-1
```

2. Copy environment variables:
```bash
cp .env.example .env
```

3. Configure your API keys in `.env`:
- `GOOGLE_API_KEY` - Google AI (Gemini) API key
- `PINECONE_API_KEY` - Pinecone vector database key
- `BINANCE_API_KEY` / `BINANCE_SECRET_KEY` - Binance exchange credentials
- `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` - Alpaca trading credentials

4. Start the system:
```bash
docker-compose up -d
```

5. Access the dashboard:
- UI: http://localhost:3000
- API: http://localhost:8000
- API Docs: http://localhost:8000/docs
- RabbitMQ Management: http://localhost:15672

## Project Structure

```
aegis-1/
├── backend/
│   ├── config/          # Configuration management
│   ├── core/            # Orchestrator and blackboard
│   ├── plugs/           # Intelligence plugs
│   ├── feeds/           # Data feed integrations
│   ├── outputs/         # Output plugins
│   ├── models/          # Data models
│   ├── db/              # Database clients
│   ├── api/             # REST and WebSocket API
│   └── utils/           # Utilities (circuit breaker, audit)
├── frontend/
│   └── src/
│       ├── components/  # React UI components
│       ├── hooks/       # Custom React hooks
│       ├── services/    # API services
│       └── types/       # TypeScript types
└── docs/                # Documentation
```

## Intelligence Plugs

| Plug | Function | Output |
|------|----------|--------|
| News Sentry | NLP sentiment analysis of news/social | Impact Score [-1.0, 1.0] |
| Gemini Vector | RAG over historical market patterns | Direction + Confidence |
| Quant Engine | Technical indicators (VWAP, OFI, Vol) | Mathematical signals |
| Risk Analyst | VaR, drawdown checks | EXECUTE/ABORT decision |

## Acceptance Criteria

- **AC-01**: Consensus resolution in <100ms
- **AC-02**: Full signal traceability with contribution percentages
- **AC-03**: Gemini Vector fails safe below 0.6 similarity
- **AC-04**: Risk veto hardware-locks the execution gateway
- **AC-05**: Auto-reduce Quant weight when volatility > 2x 30-day MA

## Configuration

Key settings in `.env`:

| Variable | Description | Default |
|----------|-------------|---------|
| `MAX_DRAWDOWN_PERCENT` | Max drawdown before reducing exposure | 5.0% |
| `KILL_SWITCH_LOSS_PERCENT` | Loss threshold for kill switch | 2.0% |
| `PINECONE_SIMILARITY_THRESHOLD` | Min similarity for vector matches | 0.6 |

## Development

### Running Tests

Use the provided test scripts for convenience:

```bash
# Windows PowerShell
.\scripts\test.ps1 all        # Run all tests
.\scripts\test.ps1 backend    # Backend tests only
.\scripts\test.ps1 frontend   # Frontend tests only
.\scripts\test.ps1 unit       # Unit tests only
.\scripts\test.ps1 integration # Integration tests
.\scripts\test.ps1 e2e        # End-to-end tests
.\scripts\test.ps1 coverage   # Run with coverage reports

# Linux/macOS
./scripts/test.sh all
./scripts/test.sh backend
./scripts/test.sh frontend
```

Or run directly:

```bash
# Backend tests
cd backend
python -m pytest -v
python -m pytest --cov=. --cov-report=html  # With coverage

# Frontend tests
cd frontend
npm run test        # Watch mode
npm run test:run    # Single run
npm run test:coverage
```

### Test Categories

| Category | Description | Files |
|----------|-------------|-------|
| Unit | Individual component tests | `test_models.py`, `test_plugs.py` |
| Integration | Component interaction tests | `test_integration.py`, `test_orchestrator.py` |
| End-to-End | Full pipeline tests | `test_e2e.py` |
| API | REST endpoint tests | `test_api.py` |
| Database | DB client tests | `test_database.py` |
| Risk | Risk management tests | `test_risk.py` |

### Code Quality

```bash
# Backend
cd backend
black .              # Format
ruff check .         # Lint
mypy .               # Type check

# Frontend
cd frontend
npm run lint         # Lint
npm run format       # Format
```

## License

MIT License - see LICENSE file for details.

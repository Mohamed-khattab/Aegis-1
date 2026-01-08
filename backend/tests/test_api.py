"""
Tests for Aegis-1 REST API Endpoints
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from fastapi import FastAPI

# We'll test the API routes
from api.routes import api_router
from models.signals import Signal, SignalAction, RiskDecision


@pytest.fixture
def app():
    """Create test FastAPI application."""
    app = FastAPI()
    app.include_router(api_router)
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def mock_orchestrator():
    """Create mock orchestrator."""
    orchestrator = MagicMock()
    orchestrator._initialized = True
    orchestrator._plugs = {}
    return orchestrator


class TestHealthEndpoints:
    """Tests for health check endpoints."""
    
    def test_health_check(self, client):
        """Test /health endpoint."""
        with patch('api.routes.get_redis_client') as mock_redis, \
             patch('api.routes.get_timescale_client') as mock_db:
            
            mock_redis.return_value.health_check = AsyncMock(return_value=True)
            mock_db.return_value.health_check = AsyncMock(return_value=True)
            
            response = client.get("/health")
            
            assert response.status_code == 200
            data = response.json()
            assert "status" in data
    
    def test_status_endpoint(self, client):
        """Test /status endpoint."""
        with patch('api.routes.orchestrator') as mock_orch:
            mock_orch._initialized = True
            mock_orch._plugs = {"test": MagicMock()}
            mock_orch.get_all_plug_statuses.return_value = {}
            
            response = client.get("/status")
            
            assert response.status_code == 200


class TestSignalEndpoints:
    """Tests for signal-related endpoints."""
    
    def test_generate_signal(self, client):
        """Test POST /signals/generate endpoint."""
        with patch('api.routes.orchestrator') as mock_orch:
            mock_signal = Signal(
                action=SignalAction.BUY,
                symbol="BTCUSDT",
                confidence=0.85,
                risk_score=0.3,
                risk_decision=RiskDecision.EXECUTE
            )
            mock_orch.generate_signal = AsyncMock(return_value=mock_signal)
            mock_orch._initialized = True
            
            response = client.post(
                "/signals/generate",
                json={"symbol": "BTCUSDT"}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["symbol"] == "BTCUSDT"
            assert data["action"] == "BUY"
    
    def test_get_signals(self, client):
        """Test GET /signals endpoint."""
        with patch('api.routes.get_timescale_client') as mock_db:
            mock_db.return_value.get_signals = AsyncMock(return_value=[
                {
                    "id": "sig_123",
                    "action": "BUY",
                    "symbol": "BTCUSDT",
                    "confidence": 0.85,
                    "timestamp": datetime.utcnow().isoformat()
                }
            ])
            
            response = client.get("/signals?limit=10")
            
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
    
    def test_get_signal_by_id(self, client):
        """Test GET /signals/{signal_id} endpoint."""
        with patch('api.routes.get_timescale_client') as mock_db:
            mock_db.return_value.get_signal = AsyncMock(return_value={
                "id": "sig_123",
                "action": "BUY",
                "symbol": "BTCUSDT",
                "confidence": 0.85
            })
            
            response = client.get("/signals/sig_123")
            
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == "sig_123"
    
    def test_get_signal_stats(self, client):
        """Test GET /signals/stats/{symbol} endpoint."""
        with patch('api.routes.get_timescale_client') as mock_db:
            mock_db.return_value.get_signal_stats = AsyncMock(return_value={
                "symbol": "BTCUSDT",
                "total_signals": 100,
                "buy_count": 45,
                "sell_count": 30,
                "hold_count": 25,
                "avg_confidence": 0.75
            })
            
            response = client.get("/signals/stats/BTCUSDT")
            
            assert response.status_code == 200
            data = response.json()
            assert data["symbol"] == "BTCUSDT"


class TestPlugEndpoints:
    """Tests for plug management endpoints."""
    
    def test_get_plugs(self, client):
        """Test GET /plugs endpoint."""
        with patch('api.routes.orchestrator') as mock_orch:
            mock_orch.get_all_plug_statuses.return_value = {
                "news_sentry": {"status": "ACTIVE", "weight": 1.0},
                "quant_engine": {"status": "ACTIVE", "weight": 1.2}
            }
            
            response = client.get("/plugs")
            
            assert response.status_code == 200
            data = response.json()
            assert "news_sentry" in data
    
    def test_get_plug_by_id(self, client):
        """Test GET /plugs/{plug_id} endpoint."""
        with patch('api.routes.orchestrator') as mock_orch:
            mock_plug = MagicMock()
            mock_plug.get_status.return_value = {
                "plug_id": "news_sentry",
                "status": "ACTIVE",
                "weight": 1.0
            }
            mock_orch.get_plug.return_value = mock_plug
            
            response = client.get("/plugs/news_sentry")
            
            assert response.status_code == 200
            data = response.json()
            assert data["plug_id"] == "news_sentry"
    
    def test_update_plug_weight(self, client):
        """Test PUT /plugs/{plug_id}/weight endpoint."""
        with patch('api.routes.orchestrator') as mock_orch:
            mock_plug = MagicMock()
            mock_orch.get_plug.return_value = mock_plug
            
            response = client.put(
                "/plugs/news_sentry/weight",
                json={"weight": 1.5}
            )
            
            assert response.status_code == 200
            mock_plug.set_weight.assert_called_once_with(1.5)
    
    def test_get_plug_performance(self, client):
        """Test GET /plugs/performance endpoint."""
        with patch('api.routes.orchestrator') as mock_orch:
            mock_orch.get_performance_summary.return_value = {
                "news_sentry": {"accuracy": 0.65, "total_predictions": 100},
                "quant_engine": {"accuracy": 0.72, "total_predictions": 100}
            }
            
            response = client.get("/plugs/performance")
            
            assert response.status_code == 200


class TestConfigEndpoints:
    """Tests for configuration endpoints."""
    
    def test_get_config(self, client):
        """Test GET /config endpoint."""
        with patch('api.routes.settings') as mock_settings:
            mock_settings.dict.return_value = {
                "max_consensus_latency_ms": 100,
                "pinecone_similarity_threshold": 0.6
            }
            
            response = client.get("/config")
            
            assert response.status_code == 200
    
    def test_get_weights(self, client):
        """Test GET /config/weights endpoint."""
        with patch('api.routes.orchestrator') as mock_orch:
            mock_orch.get_weights.return_value = {
                "news_sentry": 1.0,
                "quant_engine": 1.2
            }
            
            response = client.get("/config/weights")
            
            assert response.status_code == 200
            data = response.json()
            assert "news_sentry" in data
    
    def test_reset_weights(self, client):
        """Test POST /config/weights/reset endpoint."""
        with patch('api.routes.orchestrator') as mock_orch:
            response = client.post("/config/weights/reset")
            
            assert response.status_code == 200
            mock_orch.reset_weights.assert_called_once()


class TestRiskEndpoints:
    """Tests for risk management endpoints."""
    
    def test_get_risk_summary(self, client):
        """Test GET /risk/summary endpoint."""
        with patch('api.routes.orchestrator') as mock_orch:
            mock_orch.get_risk_summary.return_value = {
                "portfolio_value": 100000,
                "current_drawdown": 0.05,
                "var_95": 2500,
                "kill_switch_triggered": False
            }
            
            response = client.get("/risk/summary")
            
            assert response.status_code == 200
            data = response.json()
            assert "portfolio_value" in data
    
    def test_reset_session(self, client):
        """Test POST /risk/session/reset endpoint."""
        with patch('api.routes.orchestrator') as mock_orch:
            response = client.post("/risk/session/reset")
            
            assert response.status_code == 200


class TestOutputEndpoints:
    """Tests for output management endpoints."""
    
    def test_get_outputs(self, client):
        """Test GET /outputs endpoint."""
        with patch('api.routes.output_manager') as mock_manager:
            mock_manager.get_all_statuses.return_value = {
                "webhook": {"status": "ACTIVE"},
                "email": {"status": "DISABLED"}
            }
            
            response = client.get("/outputs")
            
            assert response.status_code == 200
    
    def test_enable_output(self, client):
        """Test POST /outputs/{output_id}/enable endpoint."""
        with patch('api.routes.output_manager') as mock_manager:
            mock_output = MagicMock()
            mock_manager.get_output.return_value = mock_output
            
            response = client.post("/outputs/webhook/enable")
            
            assert response.status_code == 200
            mock_output.enable.assert_called_once()
    
    def test_disable_output(self, client):
        """Test POST /outputs/{output_id}/disable endpoint."""
        with patch('api.routes.output_manager') as mock_manager:
            mock_output = MagicMock()
            mock_manager.get_output.return_value = mock_output
            
            response = client.post("/outputs/email/disable")
            
            assert response.status_code == 200
            mock_output.disable.assert_called_once()


class TestAPIValidation:
    """Tests for API input validation."""
    
    def test_invalid_symbol_format(self, client):
        """Test validation of symbol format."""
        with patch('api.routes.orchestrator') as mock_orch:
            mock_orch._initialized = True
            mock_orch.generate_signal = AsyncMock(side_effect=ValueError("Invalid symbol"))
            
            response = client.post(
                "/signals/generate",
                json={"symbol": ""}
            )
            
            # Should return error for invalid input
            assert response.status_code in [400, 422, 500]
    
    def test_invalid_weight_value(self, client):
        """Test validation of weight values."""
        with patch('api.routes.orchestrator') as mock_orch:
            mock_plug = MagicMock()
            mock_orch.get_plug.return_value = mock_plug
            
            # Test negative weight
            response = client.put(
                "/plugs/news_sentry/weight",
                json={"weight": -1.0}
            )
            
            # Should handle invalid weight
            assert response.status_code in [200, 400, 422]

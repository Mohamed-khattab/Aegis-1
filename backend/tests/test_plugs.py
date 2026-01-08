"""
Tests for Aegis-1 Intelligence Plugs
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from models.signals import PlugSignal
from models.market_data import MarketDataBundle, OHLCV, NewsItem
from models.market_data import Exchange, AssetClass
from plugs.base import BasePlug, PlugStatus


class MockPlug(BasePlug):
    """Mock plug for testing base functionality."""
    
    def __init__(self, plug_id: str = "mock_plug"):
        super().__init__(plug_id)
        self._signal_to_return = PlugSignal(
            origin=plug_id,
            direction=0.5,
            confidence=0.8,
            logic="Test signal"
        )
    
    async def generate_signal(self, market_data: MarketDataBundle) -> PlugSignal:
        return self._signal_to_return
    
    async def initialize(self) -> None:
        self.status = PlugStatus.ACTIVE
    
    async def shutdown(self) -> None:
        self.status = PlugStatus.INACTIVE


@pytest.fixture
def mock_plug():
    return MockPlug()


@pytest.fixture
def market_data():
    """Create sample market data bundle."""
    return MarketDataBundle(
        symbol="BTCUSDT",
        timestamp=datetime.utcnow(),
        ohlcv=[
            OHLCV(
                timestamp=datetime.utcnow(),
                symbol="BTCUSDT",
                open=50000.0,
                high=51000.0,
                low=49000.0,
                close=50500.0,
                volume=1000.0,
                exchange=Exchange.BINANCE,
                asset_class=AssetClass.CRYPTO
            )
        ]
    )


class TestBasePlug:
    """Tests for BasePlug functionality."""
    
    @pytest.mark.asyncio
    async def test_plug_initialization(self, mock_plug):
        """Test plug initializes correctly."""
        await mock_plug.initialize()
        assert mock_plug.status == PlugStatus.ACTIVE
        assert mock_plug.weight == 1.0
    
    @pytest.mark.asyncio
    async def test_generate_signal(self, mock_plug, market_data):
        """Test signal generation."""
        await mock_plug.initialize()
        signal = await mock_plug.safe_generate_signal(market_data)
        
        assert signal.origin == "mock_plug"
        assert signal.direction == 0.5
        assert signal.confidence == 0.8
    
    @pytest.mark.asyncio
    async def test_plug_isolation(self, mock_plug):
        """Test plug isolation mechanism."""
        await mock_plug.initialize()
        
        mock_plug._isolate_plug("Test isolation")
        
        assert mock_plug.status == PlugStatus.ISOLATED
        assert mock_plug.metrics.isolation_count == 1
    
    @pytest.mark.asyncio
    async def test_plug_reactivation(self, mock_plug):
        """Test plug reactivation after isolation."""
        await mock_plug.initialize()
        
        mock_plug._isolate_plug("Test isolation")
        assert mock_plug.status == PlugStatus.ISOLATED
        
        mock_plug.reactivate()
        assert mock_plug.status == PlugStatus.ACTIVE
    
    @pytest.mark.asyncio
    async def test_weight_adjustment(self, mock_plug):
        """Test weight adjustment."""
        await mock_plug.initialize()
        
        mock_plug.set_weight(1.5)
        assert mock_plug.weight == 1.5
        
        # Test bounds
        mock_plug.set_weight(3.0)
        assert mock_plug.weight == 2.0  # Capped at max
        
        mock_plug.set_weight(-1.0)
        assert mock_plug.weight == 0.0  # Capped at min
    
    @pytest.mark.asyncio
    async def test_degraded_status_on_low_weight(self, mock_plug):
        """Test that low weight triggers degraded status."""
        await mock_plug.initialize()
        
        mock_plug.set_weight(0.3)
        assert mock_plug.status == PlugStatus.DEGRADED
    
    @pytest.mark.asyncio
    async def test_metrics_tracking(self, mock_plug, market_data):
        """Test that metrics are tracked correctly."""
        await mock_plug.initialize()
        
        # Generate multiple signals
        for _ in range(5):
            await mock_plug.safe_generate_signal(market_data)
        
        assert mock_plug.metrics.total_signals == 5
        assert mock_plug.metrics.avg_confidence > 0
    
    @pytest.mark.asyncio
    async def test_get_status(self, mock_plug):
        """Test status reporting."""
        await mock_plug.initialize()
        
        status = mock_plug.get_status()
        
        assert status["plug_id"] == "mock_plug"
        assert status["status"] == "ACTIVE"
        assert "metrics" in status


class TestPlugSignal:
    """Tests for PlugSignal dataclass."""
    
    def test_valid_signal_creation(self):
        """Test creating a valid signal."""
        signal = PlugSignal(
            origin="test",
            direction=0.5,
            confidence=0.8,
            logic="Test"
        )
        
        assert signal.direction == 0.5
        assert signal.confidence == 0.8
    
    def test_invalid_direction_raises(self):
        """Test that invalid direction raises error."""
        with pytest.raises(ValueError):
            PlugSignal(
                origin="test",
                direction=2.0,  # Invalid
                confidence=0.8,
                logic="Test"
            )
    
    def test_invalid_confidence_raises(self):
        """Test that invalid confidence raises error."""
        with pytest.raises(ValueError):
            PlugSignal(
                origin="test",
                direction=0.5,
                confidence=1.5,  # Invalid
                logic="Test"
            )
    
    def test_null_signal_creation(self):
        """Test null signal factory method."""
        signal = PlugSignal.null_signal("test_plug", "No signal")
        
        assert signal.direction == 0.0
        assert signal.confidence == 0.0
        assert "No signal" in signal.logic
    
    def test_to_dict(self):
        """Test signal serialization."""
        signal = PlugSignal(
            origin="test",
            direction=0.5,
            confidence=0.8,
            logic="Test"
        )
        
        data = signal.to_dict()
        
        assert data["origin"] == "test"
        assert data["direction"] == 0.5
        assert "timestamp" in data

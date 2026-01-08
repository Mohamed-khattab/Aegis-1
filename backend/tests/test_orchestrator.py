"""
Tests for Aegis-1 Core Orchestrator
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from models.signals import Signal, SignalAction, RiskDecision
from models.market_data import MarketDataBundle


class TestCoreOrchestrator:
    """Tests for CoreOrchestrator functionality."""
    
    @pytest.mark.asyncio
    async def test_orchestrator_initialization(self):
        """Test orchestrator initializes correctly."""
        from core.orchestrator import CoreOrchestrator
        
        orchestrator = CoreOrchestrator()
        
        # Mock database connections
        with patch('core.orchestrator.get_redis_client') as mock_redis, \
             patch('core.orchestrator.get_timescale_client') as mock_db:
            
            mock_redis.return_value.connect = AsyncMock()
            mock_redis.return_value.health_check = AsyncMock(return_value=True)
            mock_db.return_value.connect = AsyncMock()
            mock_db.return_value.health_check = AsyncMock(return_value=True)
            
            # Initialize with mocked plug initialization
            with patch.object(orchestrator, '_initialize_plugs', new_callable=AsyncMock):
                await orchestrator.initialize()
            
            assert orchestrator._initialized is True
    
    @pytest.mark.asyncio
    async def test_signal_generation_flow(self):
        """Test the signal generation workflow."""
        from core.orchestrator import CoreOrchestrator
        from models.signals import PlugSignal
        
        orchestrator = CoreOrchestrator()
        orchestrator._initialized = True
        
        # Mock plug signals
        mock_signals = {
            "news_sentry": PlugSignal(
                origin="news_sentry",
                direction=0.5,
                confidence=0.7,
                logic="Bullish sentiment"
            ),
            "quant_engine": PlugSignal(
                origin="quant_engine",
                direction=0.3,
                confidence=0.8,
                logic="Technical buy signal"
            ),
            "risk_analyst": PlugSignal(
                origin="risk_analyst",
                direction=0.0,
                confidence=0.9,
                logic="Risk acceptable",
                metadata={"decision": "EXECUTE", "risk_score": 0.3}
            )
        }
        
        # Mock the gather method
        orchestrator._gather_plug_signals = AsyncMock(return_value=mock_signals)
        orchestrator._store_signal = AsyncMock()
        orchestrator._notify_signal = AsyncMock()
        
        market_data = MarketDataBundle(symbol="BTCUSDT")
        
        signal = await orchestrator.generate_signal("BTCUSDT", market_data)
        
        assert signal.symbol == "BTCUSDT"
        assert signal.action in [SignalAction.BUY, SignalAction.SELL, SignalAction.HOLD]
    
    def test_plug_management(self):
        """Test plug enable/disable functionality."""
        from core.orchestrator import CoreOrchestrator
        from plugs.base import BasePlug, PlugStatus
        
        orchestrator = CoreOrchestrator()
        
        # Create mock plug
        mock_plug = MagicMock(spec=BasePlug)
        mock_plug.status = PlugStatus.ACTIVE
        mock_plug.plug_id = "test_plug"
        
        orchestrator._plugs["test_plug"] = mock_plug
        
        # Get plug
        plug = orchestrator.get_plug("test_plug")
        assert plug is not None
        
        # Get non-existent plug
        plug = orchestrator.get_plug("nonexistent")
        assert plug is None


class TestDynamicWeighting:
    """Tests for Dynamic Weighting system."""
    
    def test_weight_initialization(self):
        """Test weight initialization."""
        from core.dynamic_weighting import DynamicWeighting
        
        dw = DynamicWeighting()
        
        weight = dw.get_weight("test_plug")
        assert weight == 1.0  # Default weight
    
    def test_weight_adjustment(self):
        """Test manual weight adjustment."""
        from core.dynamic_weighting import DynamicWeighting
        
        dw = DynamicWeighting()
        
        dw.set_weight("test_plug", 1.5)
        assert dw.get_weight("test_plug") == 1.5
        
        # Test bounds
        dw.set_weight("test_plug", 3.0)
        assert dw.get_weight("test_plug") == 2.0
        
        dw.set_weight("test_plug", -1.0)
        assert dw.get_weight("test_plug") == 0.1  # MIN_WEIGHT
    
    def test_prediction_recording(self):
        """Test prediction recording."""
        from core.dynamic_weighting import DynamicWeighting
        
        dw = DynamicWeighting()
        
        # Record prediction
        dw.record_prediction(
            plug_id="test_plug",
            predicted_direction=0.5,
            confidence=0.8,
            current_weight=1.0
        )
        
        ledger = dw.get_ledger("test_plug")
        assert ledger.plug_id == "test_plug"
    
    def test_outcome_recording(self):
        """Test outcome recording and accuracy calculation."""
        from core.dynamic_weighting import DynamicWeighting
        
        dw = DynamicWeighting()
        
        # Record prediction
        dw.record_prediction(
            plug_id="test_plug",
            predicted_direction=0.5,
            confidence=0.8,
            current_weight=1.0
        )
        
        # Record correct outcome
        dw.record_outcome("test_plug", actual_direction=0.3)
        
        ledger = dw.get_ledger("test_plug")
        assert len(ledger.records) == 1
        assert ledger.records[0].was_correct is True
    
    def test_performance_summary(self):
        """Test performance summary generation."""
        from core.dynamic_weighting import DynamicWeighting
        
        dw = DynamicWeighting()
        
        # Add some data
        dw.set_weight("plug_a", 1.2)
        dw.set_weight("plug_b", 0.8)
        
        summary = dw.get_performance_summary()
        
        assert "plug_a" in summary
        assert "plug_b" in summary


class TestBlackboard:
    """Tests for Blackboard functionality."""
    
    @pytest.mark.asyncio
    async def test_signal_write_and_read(self):
        """Test writing and reading signals."""
        from core.blackboard import Blackboard
        from models.signals import PlugSignal
        
        blackboard = Blackboard()
        
        signal = PlugSignal(
            origin="test_plug",
            direction=0.5,
            confidence=0.8,
            logic="Test signal"
        )
        
        await blackboard.write_signal("test_plug", signal)
        
        # Should be in local state at minimum
        assert "test_plug" in blackboard._local_state["signals"]
    
    @pytest.mark.asyncio
    async def test_weight_management(self):
        """Test weight setting and retrieval."""
        from core.blackboard import Blackboard
        
        blackboard = Blackboard()
        
        await blackboard.set_weight("test_plug", 1.5)
        
        weights = await blackboard.get_weights()
        assert weights.get("test_plug") == 1.5
    
    @pytest.mark.asyncio
    async def test_snapshot_creation(self):
        """Test blackboard snapshot creation."""
        from core.blackboard import Blackboard
        from models.signals import Signal, SignalAction, RiskDecision
        
        blackboard = Blackboard()
        
        signal = Signal(
            action=SignalAction.BUY,
            symbol="BTCUSDT",
            confidence=0.8,
            risk_score=0.3,
            risk_decision=RiskDecision.EXECUTE
        )
        
        snapshot = await blackboard.create_snapshot(signal)
        
        assert snapshot.signal == signal
        assert "orchestrator_weights" in snapshot.to_dict()

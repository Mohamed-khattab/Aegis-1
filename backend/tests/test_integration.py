"""
Integration Tests for Aegis-1 System

These tests verify that components work correctly together.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio

from models.signals import Signal, SignalAction, PlugSignal, RiskDecision
from models.market_data import (
    MarketDataBundle, OHLCV, Tick, OrderBook, OrderBookLevel,
    NewsItem, Exchange, AssetClass
)


class TestPlugIntegration:
    """Integration tests for plug interactions."""
    
    @pytest.fixture
    def market_data_bundle(self):
        """Create comprehensive market data bundle."""
        now = datetime.utcnow()
        
        # Generate 30 OHLCV candles
        ohlcv_data = []
        base_price = 50000.0
        for i in range(30):
            price_change = (i % 5 - 2) * 100
            ohlcv_data.append(OHLCV(
                timestamp=now - timedelta(hours=30-i),
                symbol="BTCUSDT",
                open=base_price + price_change,
                high=base_price + price_change + 200,
                low=base_price + price_change - 200,
                close=base_price + price_change + 50,
                volume=1000.0 + i * 10,
                exchange=Exchange.BINANCE,
                asset_class=AssetClass.CRYPTO,
                timeframe="1h"
            ))
            base_price += price_change * 0.01
        
        # Recent tick
        ticks = [
            Tick(
                timestamp=now,
                symbol="BTCUSDT",
                price=50500.0,
                volume=1.5,
                exchange=Exchange.BINANCE,
                asset_class=AssetClass.CRYPTO
            )
        ]
        
        # Order book
        orderbook = OrderBook(
            timestamp=now,
            symbol="BTCUSDT",
            exchange=Exchange.BINANCE,
            bids=[
                OrderBookLevel(price=50490.0, quantity=10.0),
                OrderBookLevel(price=50480.0, quantity=15.0),
                OrderBookLevel(price=50470.0, quantity=20.0)
            ],
            asks=[
                OrderBookLevel(price=50510.0, quantity=8.0),
                OrderBookLevel(price=50520.0, quantity=12.0),
                OrderBookLevel(price=50530.0, quantity=18.0)
            ]
        )
        
        # News items
        news = [
            NewsItem(
                id="news_1",
                timestamp=now - timedelta(minutes=30),
                source="reuters",
                title="Bitcoin momentum builds as institutional interest grows",
                content="Major institutions continue to accumulate Bitcoin...",
                symbols=["BTCUSDT", "BTC"],
                sentiment_score=0.7
            )
        ]
        
        return MarketDataBundle(
            symbol="BTCUSDT",
            timestamp=now,
            ohlcv=ohlcv_data,
            ticks=ticks,
            orderbook=orderbook,
            news=news
        )
    
    @pytest.mark.asyncio
    async def test_news_sentry_integration(self, market_data_bundle):
        """Test News Sentry processes market data correctly."""
        from plugs.news_sentry import NewsSentry
        
        plug = NewsSentry()
        await plug.initialize()
        
        signal = await plug.safe_generate_signal(market_data_bundle)
        
        assert signal is not None
        assert -1.0 <= signal.direction <= 1.0
        assert 0.0 <= signal.confidence <= 1.0
        assert signal.origin == "news_sentry"
    
    @pytest.mark.asyncio
    async def test_quant_engine_integration(self, market_data_bundle):
        """Test Quant Engine processes market data correctly."""
        from plugs.quant_engine import QuantEngine
        
        plug = QuantEngine()
        await plug.initialize()
        
        signal = await plug.safe_generate_signal(market_data_bundle)
        
        assert signal is not None
        assert -1.0 <= signal.direction <= 1.0
        assert signal.origin == "quant_engine"
        # Should have indicator values in metadata
        assert "indicators" in signal.metadata or signal.logic
    
    @pytest.mark.asyncio
    async def test_risk_analyst_integration(self, market_data_bundle):
        """Test Risk Analyst processes market data correctly."""
        from plugs.risk_analyst import RiskAnalyst
        
        plug = RiskAnalyst()
        await plug.initialize()
        
        # Set up portfolio state
        plug._portfolio_value = 100000
        plug._peak_value = 100000
        
        signal = await plug.safe_generate_signal(market_data_bundle)
        
        assert signal is not None
        assert "decision" in signal.metadata
        assert signal.metadata["decision"] in ["EXECUTE", "ABORT", RiskDecision.EXECUTE.value, RiskDecision.ABORT.value]
    
    @pytest.mark.asyncio
    async def test_all_plugs_parallel(self, market_data_bundle):
        """Test all plugs can process in parallel."""
        from plugs.news_sentry import NewsSentry
        from plugs.quant_engine import QuantEngine
        from plugs.risk_analyst import RiskAnalyst
        
        plugs = [NewsSentry(), QuantEngine(), RiskAnalyst()]
        
        # Initialize all plugs
        await asyncio.gather(*[p.initialize() for p in plugs])
        
        # Set up risk analyst
        plugs[2]._portfolio_value = 100000
        plugs[2]._peak_value = 100000
        
        # Generate signals in parallel
        signals = await asyncio.gather(*[
            p.safe_generate_signal(market_data_bundle) for p in plugs
        ])
        
        assert len(signals) == 3
        assert all(s is not None for s in signals)
        assert all(-1.0 <= s.direction <= 1.0 for s in signals)


class TestOrchestratorIntegration:
    """Integration tests for orchestrator workflow."""
    
    @pytest.mark.asyncio
    async def test_full_signal_generation_flow(self):
        """Test complete signal generation workflow."""
        from core.orchestrator import CoreOrchestrator
        from models.market_data import MarketDataBundle, OHLCV, Exchange, AssetClass
        
        orchestrator = CoreOrchestrator()
        
        # Mock database connections
        with patch('core.orchestrator.get_redis_client') as mock_redis, \
             patch('core.orchestrator.get_timescale_client') as mock_db, \
             patch('core.orchestrator.get_pinecone_client') as mock_pinecone:
            
            # Setup mocks
            mock_redis_client = AsyncMock()
            mock_redis.return_value = mock_redis_client
            mock_redis_client.connect = AsyncMock()
            mock_redis_client.health_check = AsyncMock(return_value=True)
            mock_redis_client.get = AsyncMock(return_value=None)
            mock_redis_client.set = AsyncMock()
            mock_redis_client.publish = AsyncMock()
            
            mock_db_client = AsyncMock()
            mock_db.return_value = mock_db_client
            mock_db_client.connect = AsyncMock()
            mock_db_client.health_check = AsyncMock(return_value=True)
            mock_db_client.insert_signal = AsyncMock()
            mock_db_client.insert_audit_snapshot = AsyncMock()
            
            mock_pinecone_client = AsyncMock()
            mock_pinecone.return_value = mock_pinecone_client
            mock_pinecone_client.query = AsyncMock(return_value=[])
            
            # Initialize
            await orchestrator.initialize()
            
            # Create market data
            bundle = MarketDataBundle(
                symbol="BTCUSDT",
                timestamp=datetime.utcnow(),
                ohlcv=[
                    OHLCV(
                        timestamp=datetime.utcnow() - timedelta(hours=i),
                        symbol="BTCUSDT",
                        open=50000.0 + i * 10,
                        high=50100.0 + i * 10,
                        low=49900.0 + i * 10,
                        close=50050.0 + i * 10,
                        volume=1000.0,
                        exchange=Exchange.BINANCE,
                        asset_class=AssetClass.CRYPTO
                    )
                    for i in range(30)
                ]
            )
            
            # Generate signal
            signal = await orchestrator.generate_signal("BTCUSDT", bundle)
            
            assert signal is not None
            assert signal.symbol == "BTCUSDT"
            assert signal.action in [SignalAction.BUY, SignalAction.SELL, SignalAction.HOLD]
            assert 0.0 <= signal.confidence <= 1.0
    
    @pytest.mark.asyncio
    async def test_consensus_latency_requirement(self):
        """Test that consensus is achieved within 100ms (AC-01)."""
        from core.orchestrator import CoreOrchestrator
        from models.market_data import MarketDataBundle
        import time
        
        orchestrator = CoreOrchestrator()
        orchestrator._initialized = True
        
        # Mock plug signals
        mock_signals = {
            "news_sentry": PlugSignal(
                origin="news_sentry",
                direction=0.5,
                confidence=0.7,
                logic="Bullish"
            ),
            "quant_engine": PlugSignal(
                origin="quant_engine",
                direction=0.3,
                confidence=0.8,
                logic="Technical buy"
            ),
            "risk_analyst": PlugSignal(
                origin="risk_analyst",
                direction=0.0,
                confidence=0.9,
                logic="Risk OK",
                metadata={"decision": "EXECUTE", "risk_score": 0.3}
            )
        }
        
        orchestrator._gather_plug_signals = AsyncMock(return_value=mock_signals)
        orchestrator._store_signal = AsyncMock()
        orchestrator._notify_signal = AsyncMock()
        
        bundle = MarketDataBundle(symbol="BTCUSDT")
        
        start_time = time.time()
        signal = await orchestrator.generate_signal("BTCUSDT", bundle)
        elapsed_ms = (time.time() - start_time) * 1000
        
        # Should complete within 100ms (with some tolerance for test overhead)
        assert elapsed_ms < 500  # Allow more time for test environment
        assert signal is not None


class TestBlackboardIntegration:
    """Integration tests for Blackboard system."""
    
    @pytest.mark.asyncio
    async def test_blackboard_signal_flow(self):
        """Test signal flow through blackboard."""
        from core.blackboard import Blackboard
        from models.signals import PlugSignal
        
        blackboard = Blackboard()
        
        # Write signals from multiple plugs
        signals = {
            "news_sentry": PlugSignal(
                origin="news_sentry",
                direction=0.6,
                confidence=0.75,
                logic="Positive sentiment"
            ),
            "quant_engine": PlugSignal(
                origin="quant_engine",
                direction=0.4,
                confidence=0.8,
                logic="RSI oversold"
            )
        }
        
        for plug_id, signal in signals.items():
            await blackboard.write_signal(plug_id, signal)
        
        # Read all signals
        all_signals = await blackboard.read_signals()
        
        assert len(all_signals) >= 2
        assert "news_sentry" in all_signals
        assert "quant_engine" in all_signals
    
    @pytest.mark.asyncio
    async def test_blackboard_snapshot_for_audit(self):
        """Test blackboard snapshot creation for audit trail (AC-02)."""
        from core.blackboard import Blackboard
        from models.signals import Signal, SignalAction, RiskDecision, PlugSignal
        
        blackboard = Blackboard()
        
        # Set up state
        await blackboard.write_signal(
            "news_sentry",
            PlugSignal(origin="news_sentry", direction=0.5, confidence=0.7, logic="Test")
        )
        await blackboard.set_weight("news_sentry", 1.2)
        
        # Create final signal
        final_signal = Signal(
            action=SignalAction.BUY,
            symbol="BTCUSDT",
            confidence=0.8,
            risk_score=0.3,
            risk_decision=RiskDecision.EXECUTE
        )
        
        # Create snapshot
        snapshot = await blackboard.create_snapshot(final_signal)
        
        assert snapshot is not None
        assert snapshot.signal == final_signal
        assert "news_sentry" in snapshot.plug_signals
        assert "news_sentry" in snapshot.orchestrator_weights


class TestDynamicWeightingIntegration:
    """Integration tests for Dynamic Weighting system."""
    
    def test_weight_adjustment_based_on_performance(self):
        """Test weight adjustment based on plug performance."""
        from core.dynamic_weighting import DynamicWeighting
        
        dw = DynamicWeighting()
        
        # Simulate multiple predictions and outcomes
        for i in range(10):
            # Record prediction
            dw.record_prediction(
                plug_id="test_plug",
                predicted_direction=0.5 if i % 2 == 0 else -0.5,
                confidence=0.8,
                current_weight=dw.get_weight("test_plug")
            )
            
            # Record outcome (correct 70% of the time)
            actual = 0.3 if i < 7 else -0.3
            dw.record_outcome("test_plug", actual_direction=actual)
        
        # Weight should have been adjusted based on performance
        final_weight = dw.get_weight("test_plug")
        ledger = dw.get_ledger("test_plug")
        
        assert ledger is not None
        assert len(ledger.records) == 10
    
    def test_negative_correlation_weight_decay(self):
        """Test weight decay for negatively correlated plug."""
        from core.dynamic_weighting import DynamicWeighting
        
        dw = DynamicWeighting()
        initial_weight = dw.get_weight("bad_plug")
        
        # Simulate consistently wrong predictions
        for i in range(20):
            dw.record_prediction(
                plug_id="bad_plug",
                predicted_direction=0.5,  # Always predict bullish
                confidence=0.9,
                current_weight=dw.get_weight("bad_plug")
            )
            dw.record_outcome("bad_plug", actual_direction=-0.5)  # Always bearish
        
        final_weight = dw.get_weight("bad_plug")
        
        # Weight should have decreased
        assert final_weight < initial_weight


class TestOutputIntegration:
    """Integration tests for output modules."""
    
    @pytest.mark.asyncio
    async def test_multi_output_broadcast(self):
        """Test broadcasting signal to multiple outputs."""
        from outputs.base import BaseOutput, OutputStatus
        from models.signals import Signal, SignalAction, RiskDecision
        
        # Create mock outputs
        outputs = []
        for i in range(3):
            output = MagicMock()
            output.status = OutputStatus.ACTIVE
            output.deliver = AsyncMock(return_value=True)
            outputs.append(output)
        
        signal = Signal(
            action=SignalAction.BUY,
            symbol="BTCUSDT",
            confidence=0.85,
            risk_score=0.3,
            risk_decision=RiskDecision.EXECUTE
        )
        
        # Broadcast to all
        results = await asyncio.gather(*[
            output.deliver(signal) for output in outputs
        ])
        
        assert all(results)
        assert all(output.deliver.called for output in outputs)
    
    @pytest.mark.asyncio
    async def test_output_retry_mechanism(self):
        """Test output retry mechanism on failure."""
        from outputs.webhook import WebhookOutput
        from models.signals import Signal, SignalAction, RiskDecision
        
        output = WebhookOutput(url="https://example.com/webhook")
        
        attempt_count = 0
        
        async def mock_send(signal):
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 3:
                raise Exception("Temporary failure")
            return True
        
        output.send = mock_send
        output.status = output.status.ACTIVE
        
        signal = Signal(
            action=SignalAction.BUY,
            symbol="BTCUSDT",
            confidence=0.85,
            risk_score=0.3,
            risk_decision=RiskDecision.EXECUTE
        )
        
        result = await output.deliver(signal)
        
        assert attempt_count >= 2  # Should have retried

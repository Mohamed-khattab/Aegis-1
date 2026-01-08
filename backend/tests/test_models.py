"""
Tests for Aegis-1 Data Models
"""

import pytest
from datetime import datetime, timedelta
from models.signals import (
    PlugSignal, Signal, SignalAction, RiskDecision, 
    MarketRegime, BlackboardSnapshot
)
from models.market_data import (
    Tick, OHLCV, OrderBook, OrderBookLevel, NewsItem,
    MarketDataBundle, AssetClass, Exchange
)


class TestPlugSignal:
    """Tests for PlugSignal model."""
    
    def test_valid_creation(self):
        """Test creating valid PlugSignal."""
        signal = PlugSignal(
            origin="news_sentry",
            direction=0.75,
            confidence=0.85,
            logic="Strong bullish sentiment detected"
        )
        
        assert signal.origin == "news_sentry"
        assert signal.direction == 0.75
        assert signal.confidence == 0.85
        assert signal.timestamp is not None
    
    def test_direction_bounds(self):
        """Test direction must be in [-1.0, 1.0]."""
        # Valid bounds
        PlugSignal(origin="test", direction=-1.0, confidence=0.5, logic="test")
        PlugSignal(origin="test", direction=1.0, confidence=0.5, logic="test")
        PlugSignal(origin="test", direction=0.0, confidence=0.5, logic="test")
        
        # Invalid bounds
        with pytest.raises(ValueError):
            PlugSignal(origin="test", direction=1.5, confidence=0.5, logic="test")
        
        with pytest.raises(ValueError):
            PlugSignal(origin="test", direction=-1.5, confidence=0.5, logic="test")
    
    def test_confidence_bounds(self):
        """Test confidence must be in [0.0, 1.0]."""
        # Valid bounds
        PlugSignal(origin="test", direction=0.5, confidence=0.0, logic="test")
        PlugSignal(origin="test", direction=0.5, confidence=1.0, logic="test")
        
        # Invalid bounds
        with pytest.raises(ValueError):
            PlugSignal(origin="test", direction=0.5, confidence=1.5, logic="test")
        
        with pytest.raises(ValueError):
            PlugSignal(origin="test", direction=0.5, confidence=-0.1, logic="test")
    
    def test_null_signal(self):
        """Test null signal factory method."""
        signal = PlugSignal.null_signal("test_plug", "No data available")
        
        assert signal.origin == "test_plug"
        assert signal.direction == 0.0
        assert signal.confidence == 0.0
        assert "No data available" in signal.logic
    
    def test_to_dict(self):
        """Test serialization to dictionary."""
        signal = PlugSignal(
            origin="test",
            direction=0.5,
            confidence=0.8,
            logic="Test logic",
            metadata={"key": "value"}
        )
        
        data = signal.to_dict()
        
        assert data["origin"] == "test"
        assert data["direction"] == 0.5
        assert data["confidence"] == 0.8
        assert data["logic"] == "Test logic"
        assert data["metadata"] == {"key": "value"}
        assert "timestamp" in data


class TestSignal:
    """Tests for final Signal model."""
    
    def test_valid_creation(self):
        """Test creating valid Signal."""
        signal = Signal(
            action=SignalAction.BUY,
            symbol="BTCUSDT",
            confidence=0.85,
            risk_score=0.3,
            risk_decision=RiskDecision.EXECUTE,
            position_size=0.1,
            reasoning="Strong consensus from all plugs"
        )
        
        assert signal.action == SignalAction.BUY
        assert signal.symbol == "BTCUSDT"
        assert signal.id is not None
    
    def test_is_critical_property(self):
        """Test is_critical property."""
        # High confidence = critical
        signal = Signal(
            action=SignalAction.BUY,
            symbol="BTCUSDT",
            confidence=0.95,
            risk_score=0.3,
            risk_decision=RiskDecision.EXECUTE
        )
        assert signal.is_critical is True
        
        # Low confidence = not critical
        signal.confidence = 0.7
        assert signal.is_critical is False
    
    def test_is_actionable_property(self):
        """Test is_actionable property."""
        # BUY with EXECUTE = actionable
        signal = Signal(
            action=SignalAction.BUY,
            symbol="BTCUSDT",
            confidence=0.8,
            risk_score=0.3,
            risk_decision=RiskDecision.EXECUTE
        )
        assert signal.is_actionable is True
        
        # HOLD = not actionable
        signal.action = SignalAction.HOLD
        assert signal.is_actionable is False
        
        # BUY with ABORT = not actionable
        signal.action = SignalAction.BUY
        signal.risk_decision = RiskDecision.ABORT
        assert signal.is_actionable is False
    
    def test_plug_contributions(self):
        """Test plug contributions tracking."""
        signal = Signal(
            action=SignalAction.BUY,
            symbol="BTCUSDT",
            confidence=0.8,
            risk_score=0.3,
            risk_decision=RiskDecision.EXECUTE,
            plug_contributions={
                "news_sentry": {"direction": 0.5, "weight": 1.0},
                "quant_engine": {"direction": 0.7, "weight": 1.2}
            }
        )
        
        assert "news_sentry" in signal.plug_contributions
        assert signal.plug_contributions["quant_engine"]["weight"] == 1.2


class TestTick:
    """Tests for Tick market data model."""
    
    def test_valid_creation(self):
        """Test creating valid Tick."""
        tick = Tick(
            timestamp=datetime.utcnow(),
            symbol="BTCUSDT",
            price=50000.0,
            volume=1.5,
            exchange=Exchange.BINANCE,
            asset_class=AssetClass.CRYPTO
        )
        
        assert tick.symbol == "BTCUSDT"
        assert tick.price == 50000.0
    
    def test_latency_calculation(self):
        """Test latency_ms property."""
        past_time = datetime.utcnow() - timedelta(milliseconds=50)
        tick = Tick(
            timestamp=past_time,
            symbol="BTCUSDT",
            price=50000.0,
            volume=1.0,
            exchange=Exchange.BINANCE,
            asset_class=AssetClass.CRYPTO
        )
        
        # Latency should be approximately 50ms (with some tolerance)
        assert tick.latency_ms >= 45
        assert tick.latency_ms < 200


class TestOHLCV:
    """Tests for OHLCV market data model."""
    
    def test_valid_creation(self):
        """Test creating valid OHLCV."""
        ohlcv = OHLCV(
            timestamp=datetime.utcnow(),
            symbol="BTCUSDT",
            open=50000.0,
            high=51000.0,
            low=49000.0,
            close=50500.0,
            volume=1000.0,
            exchange=Exchange.BINANCE,
            asset_class=AssetClass.CRYPTO,
            timeframe="1h"
        )
        
        assert ohlcv.open == 50000.0
        assert ohlcv.close == 50500.0
    
    def test_is_bullish_property(self):
        """Test is_bullish property."""
        # Bullish candle (close > open)
        ohlcv = OHLCV(
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
        assert ohlcv.is_bullish is True
        
        # Bearish candle (close < open)
        ohlcv.close = 49500.0
        assert ohlcv.is_bullish is False
    
    def test_body_size(self):
        """Test body_size property."""
        ohlcv = OHLCV(
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
        
        assert ohlcv.body_size == 500.0  # |50500 - 50000|


class TestOrderBook:
    """Tests for OrderBook model."""
    
    def test_spread_calculation(self):
        """Test spread property."""
        orderbook = OrderBook(
            timestamp=datetime.utcnow(),
            symbol="BTCUSDT",
            exchange=Exchange.BINANCE,
            bids=[
                OrderBookLevel(price=49990.0, quantity=1.0),
                OrderBookLevel(price=49980.0, quantity=2.0)
            ],
            asks=[
                OrderBookLevel(price=50010.0, quantity=1.0),
                OrderBookLevel(price=50020.0, quantity=2.0)
            ]
        )
        
        assert orderbook.spread == 20.0  # 50010 - 49990
    
    def test_mid_price(self):
        """Test mid_price property."""
        orderbook = OrderBook(
            timestamp=datetime.utcnow(),
            symbol="BTCUSDT",
            exchange=Exchange.BINANCE,
            bids=[OrderBookLevel(price=49990.0, quantity=1.0)],
            asks=[OrderBookLevel(price=50010.0, quantity=1.0)]
        )
        
        assert orderbook.mid_price == 50000.0  # (49990 + 50010) / 2
    
    def test_order_flow_imbalance(self):
        """Test order flow imbalance calculation."""
        # More bid volume = positive imbalance
        orderbook = OrderBook(
            timestamp=datetime.utcnow(),
            symbol="BTCUSDT",
            exchange=Exchange.BINANCE,
            bids=[
                OrderBookLevel(price=49990.0, quantity=10.0),
                OrderBookLevel(price=49980.0, quantity=10.0)
            ],
            asks=[
                OrderBookLevel(price=50010.0, quantity=5.0),
                OrderBookLevel(price=50020.0, quantity=5.0)
            ]
        )
        
        ofi = orderbook.order_flow_imbalance(depth=2)
        assert ofi > 0  # More bid pressure
        
        # More ask volume = negative imbalance
        orderbook.bids = [OrderBookLevel(price=49990.0, quantity=5.0)]
        orderbook.asks = [OrderBookLevel(price=50010.0, quantity=20.0)]
        
        ofi = orderbook.order_flow_imbalance(depth=1)
        assert ofi < 0  # More ask pressure


class TestNewsItem:
    """Tests for NewsItem model."""
    
    def test_valid_creation(self):
        """Test creating valid NewsItem."""
        news = NewsItem(
            id="news_123",
            timestamp=datetime.utcnow(),
            source="reuters",
            title="Bitcoin Reaches New High",
            content="Bitcoin has reached a new all-time high...",
            symbols=["BTCUSDT", "BTC"],
            category="crypto"
        )
        
        assert news.source == "reuters"
        assert "BTCUSDT" in news.symbols
    
    def test_sentiment_score(self):
        """Test sentiment_score field."""
        news = NewsItem(
            id="news_123",
            timestamp=datetime.utcnow(),
            source="reuters",
            title="Test",
            content="Test content",
            sentiment_score=0.75
        )
        
        assert news.sentiment_score == 0.75


class TestMarketDataBundle:
    """Tests for MarketDataBundle model."""
    
    def test_valid_creation(self):
        """Test creating valid MarketDataBundle."""
        bundle = MarketDataBundle(
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
        
        assert bundle.symbol == "BTCUSDT"
        assert len(bundle.ohlcv) == 1
    
    def test_latest_price(self):
        """Test latest_price property."""
        bundle = MarketDataBundle(
            symbol="BTCUSDT",
            timestamp=datetime.utcnow(),
            ticks=[
                Tick(
                    timestamp=datetime.utcnow(),
                    symbol="BTCUSDT",
                    price=50500.0,
                    volume=1.0,
                    exchange=Exchange.BINANCE,
                    asset_class=AssetClass.CRYPTO
                )
            ]
        )
        
        assert bundle.latest_price == 50500.0


class TestBlackboardSnapshot:
    """Tests for BlackboardSnapshot model."""
    
    def test_creation(self):
        """Test creating BlackboardSnapshot."""
        signal = Signal(
            action=SignalAction.BUY,
            symbol="BTCUSDT",
            confidence=0.8,
            risk_score=0.3,
            risk_decision=RiskDecision.EXECUTE
        )
        
        snapshot = BlackboardSnapshot(
            signal=signal,
            plug_signals={
                "news_sentry": PlugSignal(
                    origin="news_sentry",
                    direction=0.5,
                    confidence=0.7,
                    logic="Bullish"
                )
            },
            orchestrator_weights={"news_sentry": 1.0}
        )
        
        assert snapshot.signal == signal
        assert "news_sentry" in snapshot.plug_signals
    
    def test_to_dict(self):
        """Test snapshot serialization."""
        signal = Signal(
            action=SignalAction.BUY,
            symbol="BTCUSDT",
            confidence=0.8,
            risk_score=0.3,
            risk_decision=RiskDecision.EXECUTE
        )
        
        snapshot = BlackboardSnapshot(
            signal=signal,
            plug_signals={},
            orchestrator_weights={"test": 1.0}
        )
        
        data = snapshot.to_dict()
        
        assert "signal" in data
        assert "plug_signals" in data
        assert "orchestrator_weights" in data
        assert "timestamp" in data

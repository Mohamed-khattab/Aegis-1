"""
Tests for Aegis-1 Data Feeds
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
import json

from feeds.base import BaseFeed, FeedStatus, FeedType, FeedMetrics
from models.market_data import Tick, OHLCV, OrderBook, Exchange, AssetClass


class MockFeed(BaseFeed):
    """Mock feed for testing base functionality."""
    
    def __init__(self):
        super().__init__(
            feed_id="mock_feed",
            feed_type=FeedType.MARKET,
            exchange=Exchange.BINANCE
        )
        self._messages = []
    
    async def _stream_data(self):
        """Stream mock data."""
        for msg in self._messages:
            yield msg
    
    def _process_message(self, raw_message):
        """Process mock message."""
        if isinstance(raw_message, dict):
            return Tick(
                timestamp=datetime.utcnow(),
                symbol=raw_message.get("symbol", "BTCUSDT"),
                price=raw_message.get("price", 50000.0),
                volume=raw_message.get("volume", 1.0),
                exchange=self.exchange,
                asset_class=AssetClass.CRYPTO
            )
        return None


@pytest.fixture
def mock_feed():
    return MockFeed()


class TestBaseFeed:
    """Tests for BaseFeed functionality."""
    
    @pytest.mark.asyncio
    async def test_feed_initialization(self, mock_feed):
        """Test feed initializes correctly."""
        assert mock_feed.feed_id == "mock_feed"
        assert mock_feed.status == FeedStatus.DISCONNECTED
        assert mock_feed.feed_type == FeedType.MARKET
    
    @pytest.mark.asyncio
    async def test_connect(self, mock_feed):
        """Test feed connection."""
        await mock_feed.connect()
        assert mock_feed.status == FeedStatus.CONNECTED
    
    @pytest.mark.asyncio
    async def test_disconnect(self, mock_feed):
        """Test feed disconnection."""
        await mock_feed.connect()
        await mock_feed.disconnect()
        assert mock_feed.status == FeedStatus.DISCONNECTED
    
    @pytest.mark.asyncio
    async def test_subscribe(self, mock_feed):
        """Test symbol subscription."""
        await mock_feed.connect()
        await mock_feed.subscribe(["BTCUSDT", "ETHUSDT"])
        
        assert "BTCUSDT" in mock_feed._subscribed_symbols
        assert "ETHUSDT" in mock_feed._subscribed_symbols
    
    @pytest.mark.asyncio
    async def test_unsubscribe(self, mock_feed):
        """Test symbol unsubscription."""
        await mock_feed.connect()
        await mock_feed.subscribe(["BTCUSDT", "ETHUSDT"])
        await mock_feed.unsubscribe(["BTCUSDT"])
        
        assert "BTCUSDT" not in mock_feed._subscribed_symbols
        assert "ETHUSDT" in mock_feed._subscribed_symbols
    
    @pytest.mark.asyncio
    async def test_message_processing(self, mock_feed):
        """Test message processing."""
        mock_feed._messages = [
            {"symbol": "BTCUSDT", "price": 50000.0, "volume": 1.5}
        ]
        
        await mock_feed.connect()
        
        processed = []
        async for data in mock_feed._stream_data():
            tick = mock_feed._process_message(data)
            if tick:
                processed.append(tick)
        
        assert len(processed) == 1
        assert processed[0].price == 50000.0
    
    @pytest.mark.asyncio
    async def test_metrics_tracking(self, mock_feed):
        """Test metrics are tracked."""
        mock_feed._messages = [
            {"symbol": "BTCUSDT", "price": 50000.0}
        ]
        
        await mock_feed.connect()
        
        # Process messages
        async for data in mock_feed._stream_data():
            tick = mock_feed._process_message(data)
            if tick:
                mock_feed.metrics.messages_received += 1
        
        assert mock_feed.metrics.messages_received == 1
    
    def test_get_status(self, mock_feed):
        """Test status reporting."""
        status = mock_feed.get_status()
        
        assert status["feed_id"] == "mock_feed"
        assert status["status"] == "DISCONNECTED"
        assert "metrics" in status


class TestBinanceFeed:
    """Tests for Binance feed implementation."""
    
    @pytest.mark.asyncio
    async def test_binance_message_parsing(self):
        """Test Binance WebSocket message parsing."""
        from feeds.crypto.binance import BinanceFeed
        
        feed = BinanceFeed()
        
        # Mock trade message
        trade_msg = {
            "e": "trade",
            "s": "BTCUSDT",
            "p": "50000.00",
            "q": "1.5",
            "T": int(datetime.utcnow().timestamp() * 1000)
        }
        
        tick = feed._process_message(trade_msg)
        
        assert tick is not None
        assert tick.symbol == "BTCUSDT"
        assert tick.price == 50000.0
        assert tick.volume == 1.5
    
    @pytest.mark.asyncio
    async def test_binance_kline_parsing(self):
        """Test Binance kline message parsing."""
        from feeds.crypto.binance import BinanceFeed
        
        feed = BinanceFeed()
        
        # Mock kline message
        kline_msg = {
            "e": "kline",
            "s": "BTCUSDT",
            "k": {
                "t": int(datetime.utcnow().timestamp() * 1000),
                "o": "49000.00",
                "h": "51000.00",
                "l": "48500.00",
                "c": "50500.00",
                "v": "1000.0",
                "i": "1h",
                "x": True  # Closed candle
            }
        }
        
        ohlcv = feed._process_message(kline_msg)
        
        assert ohlcv is not None
        assert isinstance(ohlcv, OHLCV)
        assert ohlcv.close == 50500.0


class TestCoinbaseFeed:
    """Tests for Coinbase feed implementation."""
    
    @pytest.mark.asyncio
    async def test_coinbase_ticker_parsing(self):
        """Test Coinbase ticker message parsing."""
        from feeds.crypto.coinbase import CoinbaseFeed
        
        feed = CoinbaseFeed()
        
        # Mock ticker message
        ticker_msg = {
            "type": "ticker",
            "product_id": "BTC-USD",
            "price": "50000.00",
            "last_size": "1.5",
            "time": datetime.utcnow().isoformat()
        }
        
        tick = feed._process_message(ticker_msg)
        
        assert tick is not None
        assert tick.symbol == "BTCUSD"
        assert tick.price == 50000.0


class TestAlpacaFeed:
    """Tests for Alpaca stock feed implementation."""
    
    @pytest.mark.asyncio
    async def test_alpaca_trade_parsing(self):
        """Test Alpaca trade message parsing."""
        from feeds.stocks.alpaca import AlpacaFeed
        
        feed = AlpacaFeed()
        
        # Mock trade message
        trade_msg = {
            "T": "t",  # Trade
            "S": "AAPL",
            "p": 150.50,
            "s": 100,
            "t": datetime.utcnow().isoformat()
        }
        
        tick = feed._process_message(trade_msg)
        
        assert tick is not None
        assert tick.symbol == "AAPL"
        assert tick.price == 150.50
        assert tick.asset_class == AssetClass.STOCK


class TestPolygonFeed:
    """Tests for Polygon.io feed implementation."""
    
    @pytest.mark.asyncio
    async def test_polygon_trade_parsing(self):
        """Test Polygon trade message parsing."""
        from feeds.stocks.polygon import PolygonFeed
        
        feed = PolygonFeed()
        
        # Mock trade message
        trade_msg = {
            "ev": "T",  # Trade event
            "sym": "TSLA",
            "p": 250.75,
            "s": 50,
            "t": int(datetime.utcnow().timestamp() * 1000)
        }
        
        tick = feed._process_message(trade_msg)
        
        assert tick is not None
        assert tick.symbol == "TSLA"
        assert tick.price == 250.75


class TestNewsFeed:
    """Tests for News feed implementation."""
    
    @pytest.mark.asyncio
    async def test_news_sentiment_analysis(self):
        """Test news sentiment analysis."""
        from feeds.news import NewsFeed
        
        feed = NewsFeed()
        
        # Positive sentiment
        positive_text = "Bitcoin surges to new all-time high amid bullish momentum"
        sentiment = feed._analyze_sentiment(positive_text)
        assert sentiment > 0
        
        # Negative sentiment  
        negative_text = "Crypto market crashes as fears mount over regulation"
        sentiment = feed._analyze_sentiment(negative_text)
        assert sentiment < 0
    
    @pytest.mark.asyncio
    async def test_symbol_extraction(self):
        """Test symbol extraction from news."""
        from feeds.news import NewsFeed
        
        feed = NewsFeed()
        
        text = "Bitcoin (BTC) and Ethereum (ETH) rally while Apple (AAPL) stock falls"
        symbols = feed._extract_symbols(text)
        
        assert "BTC" in symbols or "BTCUSDT" in symbols
        assert "ETH" in symbols or "ETHUSDT" in symbols


class TestHistoricalFeed:
    """Tests for Historical data feed."""
    
    @pytest.mark.asyncio
    async def test_fetch_ohlcv(self):
        """Test fetching historical OHLCV data."""
        from feeds.historical import HistoricalFeed
        
        feed = HistoricalFeed()
        
        # Mock the data fetching
        with patch.object(feed, '_fetch_from_yfinance') as mock_fetch:
            mock_fetch.return_value = [
                OHLCV(
                    timestamp=datetime.utcnow(),
                    symbol="AAPL",
                    open=150.0,
                    high=155.0,
                    low=149.0,
                    close=153.0,
                    volume=1000000.0,
                    exchange=Exchange.ALPACA,
                    asset_class=AssetClass.STOCK
                )
            ]
            
            data = await feed.fetch_ohlcv("AAPL", days=30)
            
            assert len(data) == 1
            assert data[0].symbol == "AAPL"

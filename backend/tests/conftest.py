"""
Pytest configuration and fixtures for Aegis-1 tests.
"""

import pytest
import asyncio
from datetime import datetime
from typing import Generator

# Configure pytest-asyncio
pytest_plugins = ['pytest_asyncio']


@pytest.fixture(scope="session")
def event_loop() -> Generator:
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def sample_ohlcv_data():
    """Generate sample OHLCV data for testing."""
    from models.market_data import OHLCV, Exchange, AssetClass
    
    base_price = 50000.0
    data = []
    
    for i in range(30):
        price_change = (i % 5 - 2) * 100  # Oscillating price
        data.append(OHLCV(
            timestamp=datetime.utcnow(),
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
        base_price += price_change * 0.1
    
    return data


@pytest.fixture
def sample_news_items():
    """Generate sample news items for testing."""
    from models.market_data import NewsItem
    
    return [
        NewsItem(
            id="news_1",
            timestamp=datetime.utcnow(),
            source="reuters",
            title="Bitcoin surges past $50,000",
            content="Bitcoin has broken through the $50,000 resistance level...",
            symbols=["BTCUSDT", "BTC"],
            category="crypto"
        ),
        NewsItem(
            id="news_2",
            timestamp=datetime.utcnow(),
            source="bloomberg",
            title="Fed signals rate pause",
            content="The Federal Reserve indicated it may pause rate hikes...",
            symbols=["SPY", "QQQ"],
            category="macro"
        ),
    ]


@pytest.fixture
def sample_market_data(sample_ohlcv_data, sample_news_items):
    """Generate complete market data bundle for testing."""
    from models.market_data import MarketDataBundle
    
    return MarketDataBundle(
        symbol="BTCUSDT",
        timestamp=datetime.utcnow(),
        ohlcv=sample_ohlcv_data,
        news=sample_news_items
    )

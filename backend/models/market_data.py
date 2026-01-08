"""
Market Data Models for Aegis-1

Defines standardized data structures for market data feeds.
Based on PRD Section 4 specifications.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class AssetClass(str, Enum):
    """Supported asset classes."""
    CRYPTO = "CRYPTO"
    STOCK = "STOCK"
    FOREX = "FOREX"
    FUTURES = "FUTURES"


class Exchange(str, Enum):
    """Supported exchanges."""
    # Crypto
    BINANCE = "BINANCE"
    COINBASE = "COINBASE"
    KRAKEN = "KRAKEN"
    # Stocks
    ALPACA = "ALPACA"
    POLYGON = "POLYGON"
    NYSE = "NYSE"
    NASDAQ = "NASDAQ"


@dataclass
class Tick:
    """
    Real-time tick data from exchanges.
    
    Format: Standardized tick data with timestamp, symbol, price, volume, bid/ask spread.
    Latency Requirement: Feed latency must be <50ms from exchange to system ingestion.
    """
    
    timestamp: datetime
    symbol: str
    price: float
    volume: float
    bid: float
    ask: float
    exchange: Exchange
    asset_class: AssetClass
    
    # Optional extended data
    bid_size: Optional[float] = None
    ask_size: Optional[float] = None
    trade_id: Optional[str] = None
    
    # Ingestion tracking
    ingestion_timestamp: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self) -> None:
        """Validate tick data."""
        if self.price <= 0:
            raise ValueError(f"Price must be positive, got {self.price}")
        if self.volume < 0:
            raise ValueError(f"Volume cannot be negative, got {self.volume}")
        if self.bid > self.ask:
            raise ValueError(f"Bid ({self.bid}) cannot exceed ask ({self.ask})")
    
    @property
    def spread(self) -> float:
        """Calculate bid-ask spread."""
        return self.ask - self.bid
    
    @property
    def spread_percent(self) -> float:
        """Calculate spread as percentage of mid price."""
        mid = (self.bid + self.ask) / 2
        return (self.spread / mid) * 100 if mid > 0 else 0
    
    @property
    def latency_ms(self) -> float:
        """Calculate ingestion latency in milliseconds."""
        delta = self.ingestion_timestamp - self.timestamp
        return delta.total_seconds() * 1000
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "symbol": self.symbol,
            "price": self.price,
            "volume": self.volume,
            "bid": self.bid,
            "ask": self.ask,
            "exchange": self.exchange.value,
            "asset_class": self.asset_class.value,
            "bid_size": self.bid_size,
            "ask_size": self.ask_size,
            "spread": self.spread,
            "latency_ms": self.latency_ms,
        }


@dataclass
class OHLCV:
    """
    OHLCV (Open, High, Low, Close, Volume) candlestick data.
    
    Used for technical analysis and historical data feeds.
    """
    
    timestamp: datetime
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    exchange: Exchange
    asset_class: AssetClass
    
    # Timeframe (e.g., "1m", "5m", "1h", "1d")
    timeframe: str = "1m"
    
    # Number of trades in this candle
    trades: Optional[int] = None
    
    def __post_init__(self) -> None:
        """Validate OHLCV data."""
        if not (self.low <= self.open <= self.high):
            if not (self.low <= self.open):
                raise ValueError(f"Open ({self.open}) below low ({self.low})")
        if not (self.low <= self.close <= self.high):
            if not (self.low <= self.close):
                raise ValueError(f"Close ({self.close}) below low ({self.low})")
        if self.low > self.high:
            raise ValueError(f"Low ({self.low}) exceeds high ({self.high})")
    
    @property
    def is_bullish(self) -> bool:
        """Check if candle is bullish (close > open)."""
        return self.close > self.open
    
    @property
    def body_size(self) -> float:
        """Calculate candle body size."""
        return abs(self.close - self.open)
    
    @property
    def range_size(self) -> float:
        """Calculate full candle range."""
        return self.high - self.low
    
    @property
    def body_percent(self) -> float:
        """Calculate body as percentage of range."""
        if self.range_size == 0:
            return 0
        return (self.body_size / self.range_size) * 100
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "symbol": self.symbol,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "exchange": self.exchange.value,
            "asset_class": self.asset_class.value,
            "timeframe": self.timeframe,
            "trades": self.trades,
        }


@dataclass
class OrderBookLevel:
    """Single level in the order book."""
    
    price: float
    quantity: float
    orders: Optional[int] = None  # Number of orders at this level
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "price": self.price,
            "quantity": self.quantity,
            "orders": self.orders,
        }


@dataclass
class OrderBook:
    """
    Order book snapshot for order flow analysis.
    
    Used by the Quant Engine plug for Order Flow Imbalance calculations.
    """
    
    timestamp: datetime
    symbol: str
    exchange: Exchange
    bids: list[OrderBookLevel] = field(default_factory=list)
    asks: list[OrderBookLevel] = field(default_factory=list)
    
    @property
    def best_bid(self) -> Optional[float]:
        """Get best bid price."""
        return self.bids[0].price if self.bids else None
    
    @property
    def best_ask(self) -> Optional[float]:
        """Get best ask price."""
        return self.asks[0].price if self.asks else None
    
    @property
    def mid_price(self) -> Optional[float]:
        """Calculate mid price."""
        if self.best_bid and self.best_ask:
            return (self.best_bid + self.best_ask) / 2
        return None
    
    @property
    def spread(self) -> Optional[float]:
        """Calculate spread."""
        if self.best_bid and self.best_ask:
            return self.best_ask - self.best_bid
        return None
    
    def bid_depth(self, levels: int = 10) -> float:
        """Calculate total bid depth for N levels."""
        return sum(level.quantity for level in self.bids[:levels])
    
    def ask_depth(self, levels: int = 10) -> float:
        """Calculate total ask depth for N levels."""
        return sum(level.quantity for level in self.asks[:levels])
    
    def order_flow_imbalance(self, levels: int = 10) -> float:
        """
        Calculate Order Flow Imbalance (OFI).
        
        Returns value between -1 (ask heavy) and 1 (bid heavy).
        Used by Quant Engine plug.
        """
        bid_depth = self.bid_depth(levels)
        ask_depth = self.ask_depth(levels)
        total = bid_depth + ask_depth
        
        if total == 0:
            return 0.0
        
        return (bid_depth - ask_depth) / total
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "symbol": self.symbol,
            "exchange": self.exchange.value,
            "bids": [b.to_dict() for b in self.bids],
            "asks": [a.to_dict() for a in self.asks],
            "best_bid": self.best_bid,
            "best_ask": self.best_ask,
            "mid_price": self.mid_price,
            "spread": self.spread,
        }


@dataclass
class NewsItem:
    """
    News item for the News Sentry plug.
    
    Structured JSON with source, timestamp, content, sentiment metadata.
    """
    
    id: str
    timestamp: datetime
    source: str  # e.g., "Bloomberg", "Reuters", "Twitter"
    title: str
    content: str
    url: Optional[str] = None
    
    # Symbols mentioned in the article
    symbols: list[str] = field(default_factory=list)
    
    # Pre-computed sentiment (if available from source)
    raw_sentiment: Optional[float] = None  # -1 to 1
    
    # Metadata
    author: Optional[str] = None
    category: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    
    # Processing status
    processed: bool = False
    impact_score: Optional[float] = None  # Computed by News Sentry
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "title": self.title,
            "content": self.content,
            "url": self.url,
            "symbols": self.symbols,
            "raw_sentiment": self.raw_sentiment,
            "author": self.author,
            "category": self.category,
            "tags": self.tags,
            "processed": self.processed,
            "impact_score": self.impact_score,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NewsItem":
        """Create NewsItem from dictionary."""
        return cls(
            id=data["id"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            source=data["source"],
            title=data["title"],
            content=data["content"],
            url=data.get("url"),
            symbols=data.get("symbols", []),
            raw_sentiment=data.get("raw_sentiment"),
            author=data.get("author"),
            category=data.get("category"),
            tags=data.get("tags", []),
            processed=data.get("processed", False),
            impact_score=data.get("impact_score"),
        )


@dataclass
class MarketDataBundle:
    """
    Bundle of all market data for a symbol at a point in time.
    
    Passed to plugs for signal generation.
    """
    
    symbol: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    # Current tick
    tick: Optional[Tick] = None
    
    # Recent OHLCV history
    ohlcv: list[OHLCV] = field(default_factory=list)
    
    # Order book snapshot
    order_book: Optional[OrderBook] = None
    
    # Recent news
    news: list[NewsItem] = field(default_factory=list)
    
    # Additional context
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "tick": self.tick.to_dict() if self.tick else None,
            "ohlcv": [c.to_dict() for c in self.ohlcv],
            "order_book": self.order_book.to_dict() if self.order_book else None,
            "news": [n.to_dict() for n in self.news],
            "metadata": self.metadata,
        }

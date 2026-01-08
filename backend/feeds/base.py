"""
Base Feed Interface for Aegis-1

All data feeds must inherit from BaseFeed and implement
the required methods for data ingestion.
Based on PRD Section 4 specifications.
"""

from abc import ABC, abstractmethod
from asyncio import Queue
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, AsyncIterator, Callable, Optional
import logging

from models.market_data import Tick, OHLCV, NewsItem


class FeedStatus(str, Enum):
    """Feed operational status."""
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    RECONNECTING = "RECONNECTING"
    ERROR = "ERROR"


class FeedType(str, Enum):
    """Types of data feeds."""
    MARKET = "MARKET"  # Real-time price/volume
    NEWS = "NEWS"  # News and social media
    HISTORICAL = "HISTORICAL"  # Historical data
    ALTERNATIVE = "ALTERNATIVE"  # Alternative data sources


@dataclass
class FeedMetrics:
    """Performance metrics for a feed."""
    
    feed_id: str
    messages_received: int = 0
    messages_processed: int = 0
    errors: int = 0
    avg_latency_ms: float = 0.0
    last_message_time: Optional[datetime] = None
    reconnect_count: int = 0
    uptime_percent: float = 100.0
    
    # Latency tracking (PRD: Feed latency must be <50ms)
    max_latency_ms: float = 0.0
    latency_violations: int = 0  # Count of messages with >50ms latency


class BaseFeed(ABC):
    """
    Abstract base class for all data feeds.
    
    All feeds must:
    1. Provide real-time data streaming via async iterator
    2. Support hot-swapping (can be replaced at runtime)
    3. Track latency and report violations (>50ms threshold)
    4. Handle reconnection automatically
    
    From PRD Section 4:
    - Feed latency must be <50ms from exchange to system ingestion
    - All feeds must be pluggable and hot-swappable
    """
    
    # Maximum allowed latency in milliseconds (from PRD)
    MAX_LATENCY_MS = 50.0
    
    def __init__(
        self,
        feed_id: str,
        feed_type: FeedType,
        symbols: list[str] | None = None
    ):
        """
        Initialize the base feed.
        
        Args:
            feed_id: Unique identifier for this feed
            feed_type: Type of feed (MARKET, NEWS, etc.)
            symbols: List of symbols to subscribe to
        """
        self.feed_id = feed_id
        self.feed_type = feed_type
        self.symbols = symbols or []
        self.status = FeedStatus.DISCONNECTED
        self.metrics = FeedMetrics(feed_id=feed_id)
        self.logger = logging.getLogger(f"feed.{feed_id}")
        
        # Callbacks for data delivery
        self._callbacks: list[Callable] = []
        
        # Internal message queue
        self._queue: Queue = Queue()
        
        # Connection state
        self._connected = False
        self._should_reconnect = True
    
    @abstractmethod
    async def connect(self) -> None:
        """
        Establish connection to the data source.
        
        Must be implemented by subclasses to handle
        exchange-specific connection logic.
        """
        pass
    
    @abstractmethod
    async def disconnect(self) -> None:
        """
        Disconnect from the data source.
        
        Must cleanly close connections and release resources.
        """
        pass
    
    @abstractmethod
    async def subscribe(self, symbols: list[str]) -> None:
        """
        Subscribe to data for specific symbols.
        
        Args:
            symbols: List of symbols to subscribe to
        """
        pass
    
    @abstractmethod
    async def unsubscribe(self, symbols: list[str]) -> None:
        """
        Unsubscribe from specific symbols.
        
        Args:
            symbols: List of symbols to unsubscribe from
        """
        pass
    
    @abstractmethod
    async def _stream_data(self) -> AsyncIterator[Any]:
        """
        Internal method to stream raw data from the source.
        
        Yields raw data that will be processed by _process_message.
        """
        pass
    
    @abstractmethod
    async def _process_message(self, raw_data: Any) -> Tick | OHLCV | NewsItem | None:
        """
        Process raw data into standardized format.
        
        Args:
            raw_data: Raw data from the feed
        
        Returns:
            Standardized data object (Tick, OHLCV, or NewsItem)
        """
        pass
    
    async def stream(self) -> AsyncIterator[Tick | OHLCV | NewsItem]:
        """
        Stream processed data from the feed.
        
        This is the main interface for consuming feed data.
        Handles reconnection, error recovery, and latency tracking.
        
        Yields:
            Processed data objects (Tick, OHLCV, NewsItem)
        """
        while self._should_reconnect:
            try:
                if not self._connected:
                    await self.connect()
                
                async for raw_data in self._stream_data():
                    receive_time = datetime.utcnow()
                    self.metrics.messages_received += 1
                    
                    try:
                        processed = await self._process_message(raw_data)
                        if processed is None:
                            continue
                        
                        # Track latency
                        self._track_latency(processed, receive_time)
                        
                        self.metrics.messages_processed += 1
                        self.metrics.last_message_time = receive_time
                        
                        # Notify callbacks
                        for callback in self._callbacks:
                            await callback(processed)
                        
                        yield processed
                        
                    except Exception as e:
                        self.logger.error(f"Error processing message: {e}")
                        self.metrics.errors += 1
                        
            except Exception as e:
                self.logger.error(f"Feed stream error: {e}")
                self.status = FeedStatus.ERROR
                self.metrics.errors += 1
                
                if self._should_reconnect:
                    self.status = FeedStatus.RECONNECTING
                    self.metrics.reconnect_count += 1
                    self.logger.info(f"Attempting reconnection...")
                    await self._handle_reconnect()
    
    def _track_latency(
        self,
        data: Tick | OHLCV | NewsItem,
        receive_time: datetime
    ) -> None:
        """
        Track message latency and report violations.
        
        PRD Requirement: Feed latency must be <50ms
        
        Args:
            data: Processed data object
            receive_time: Time when message was received
        """
        # Calculate latency if timestamp is available
        if hasattr(data, 'timestamp'):
            latency_ms = (receive_time - data.timestamp).total_seconds() * 1000
            
            # Update metrics
            n = self.metrics.messages_processed
            if n > 0:
                prev_avg = self.metrics.avg_latency_ms
                self.metrics.avg_latency_ms = prev_avg + (latency_ms - prev_avg) / n
            
            self.metrics.max_latency_ms = max(
                self.metrics.max_latency_ms,
                latency_ms
            )
            
            # Check for latency violation
            if latency_ms > self.MAX_LATENCY_MS:
                self.metrics.latency_violations += 1
                self.logger.warning(
                    f"Latency violation: {latency_ms:.1f}ms > {self.MAX_LATENCY_MS}ms"
                )
    
    async def _handle_reconnect(self) -> None:
        """Handle reconnection with exponential backoff."""
        import asyncio
        
        backoff = 1.0
        max_backoff = 60.0
        
        while self._should_reconnect and not self._connected:
            try:
                await asyncio.sleep(backoff)
                await self.connect()
                self.logger.info("Reconnection successful")
                return
            except Exception as e:
                self.logger.error(f"Reconnection failed: {e}")
                backoff = min(backoff * 2, max_backoff)
    
    def add_callback(self, callback: Callable) -> None:
        """
        Add a callback to be notified of new data.
        
        Args:
            callback: Async function to call with each data item
        """
        self._callbacks.append(callback)
    
    def remove_callback(self, callback: Callable) -> None:
        """Remove a callback."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)
    
    async def get_latest(self, symbol: str) -> Tick | OHLCV | NewsItem | None:
        """
        Get the latest data for a symbol.
        
        Args:
            symbol: Symbol to get data for
        
        Returns:
            Latest data or None if not available
        """
        # Default implementation - subclasses may override
        return None
    
    def get_status(self) -> dict[str, Any]:
        """Get current feed status and metrics."""
        return {
            "feed_id": self.feed_id,
            "feed_type": self.feed_type.value,
            "status": self.status.value,
            "symbols": self.symbols,
            "metrics": {
                "messages_received": self.metrics.messages_received,
                "messages_processed": self.metrics.messages_processed,
                "errors": self.metrics.errors,
                "avg_latency_ms": self.metrics.avg_latency_ms,
                "max_latency_ms": self.metrics.max_latency_ms,
                "latency_violations": self.metrics.latency_violations,
                "reconnect_count": self.metrics.reconnect_count,
            },
        }
    
    async def health_check(self) -> bool:
        """
        Check if the feed is healthy.
        
        Returns:
            True if feed is connected and operating normally
        """
        if self.status != FeedStatus.CONNECTED:
            return False
        
        # Check if we've received data recently
        if self.metrics.last_message_time:
            elapsed = (datetime.utcnow() - self.metrics.last_message_time).total_seconds()
            if elapsed > 60:  # No data for 1 minute
                return False
        
        return True
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(id={self.feed_id}, status={self.status.value})"

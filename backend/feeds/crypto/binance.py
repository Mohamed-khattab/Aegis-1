"""
Binance WebSocket Feed for Aegis-1

Real-time market data from Binance exchange.
Latency requirement: <50ms from exchange to system ingestion.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, AsyncIterator, Optional

import websockets
from websockets.exceptions import ConnectionClosed

from feeds.base import BaseFeed, FeedStatus, FeedType
from models.market_data import Tick, OHLCV, OrderBook, OrderBookLevel, AssetClass, Exchange
from config.settings import settings


logger = logging.getLogger(__name__)


class BinanceFeed(BaseFeed):
    """
    Binance WebSocket feed for real-time crypto market data.
    
    Supports:
    - Real-time trade ticks
    - Order book updates
    - Kline/candlestick data
    
    From PRD Section 4: WebSocket connections to exchanges (Binance, Coinbase, Kraken)
    """
    
    # Binance WebSocket endpoints
    WS_BASE_URL = "wss://stream.binance.com:9443/ws"
    WS_COMBINED_URL = "wss://stream.binance.com:9443/stream?streams="
    
    def __init__(
        self,
        symbols: list[str] | None = None,
        streams: list[str] | None = None
    ):
        """
        Initialize Binance feed.
        
        Args:
            symbols: List of trading pairs (e.g., ["BTCUSDT", "ETHUSDT"])
            streams: List of stream types (e.g., ["trade", "depth", "kline_1m"])
        """
        super().__init__(
            feed_id="binance",
            feed_type=FeedType.MARKET,
            symbols=symbols or ["BTCUSDT", "ETHUSDT"]
        )
        
        self.streams = streams or ["trade", "bookTicker"]
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._last_ticks: dict[str, Tick] = {}
        self._order_books: dict[str, OrderBook] = {}
    
    def _build_stream_url(self) -> str:
        """Build the combined stream URL for all subscriptions."""
        stream_names = []
        
        for symbol in self.symbols:
            symbol_lower = symbol.lower()
            for stream in self.streams:
                if stream == "trade":
                    stream_names.append(f"{symbol_lower}@trade")
                elif stream == "bookTicker":
                    stream_names.append(f"{symbol_lower}@bookTicker")
                elif stream == "depth":
                    stream_names.append(f"{symbol_lower}@depth20@100ms")
                elif stream.startswith("kline"):
                    interval = stream.split("_")[1] if "_" in stream else "1m"
                    stream_names.append(f"{symbol_lower}@kline_{interval}")
        
        return f"{self.WS_COMBINED_URL}{'/'.join(stream_names)}"
    
    async def connect(self) -> None:
        """Establish WebSocket connection to Binance."""
        try:
            url = self._build_stream_url()
            self._ws = await websockets.connect(
                url,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=5
            )
            
            self._connected = True
            self.status = FeedStatus.CONNECTED
            logger.info(f"Connected to Binance WebSocket: {len(self.symbols)} symbols")
            
        except Exception as e:
            logger.error(f"Failed to connect to Binance: {e}")
            self.status = FeedStatus.ERROR
            raise
    
    async def disconnect(self) -> None:
        """Close WebSocket connection."""
        self._should_reconnect = False
        self._connected = False
        
        if self._ws:
            await self._ws.close()
            self._ws = None
        
        self.status = FeedStatus.DISCONNECTED
        logger.info("Disconnected from Binance")
    
    async def subscribe(self, symbols: list[str]) -> None:
        """Subscribe to additional symbols."""
        if not self._ws:
            raise RuntimeError("Not connected")
        
        # Add to symbol list
        for symbol in symbols:
            if symbol not in self.symbols:
                self.symbols.append(symbol)
        
        # Send subscription message
        subscribe_msg = {
            "method": "SUBSCRIBE",
            "params": [
                f"{symbol.lower()}@trade" for symbol in symbols
            ] + [
                f"{symbol.lower()}@bookTicker" for symbol in symbols
            ],
            "id": int(datetime.utcnow().timestamp() * 1000)
        }
        
        await self._ws.send(json.dumps(subscribe_msg))
        logger.info(f"Subscribed to {symbols}")
    
    async def unsubscribe(self, symbols: list[str]) -> None:
        """Unsubscribe from symbols."""
        if not self._ws:
            return
        
        # Remove from symbol list
        self.symbols = [s for s in self.symbols if s not in symbols]
        
        # Send unsubscription message
        unsubscribe_msg = {
            "method": "UNSUBSCRIBE",
            "params": [
                f"{symbol.lower()}@trade" for symbol in symbols
            ] + [
                f"{symbol.lower()}@bookTicker" for symbol in symbols
            ],
            "id": int(datetime.utcnow().timestamp() * 1000)
        }
        
        await self._ws.send(json.dumps(unsubscribe_msg))
        logger.info(f"Unsubscribed from {symbols}")
    
    async def _stream_data(self) -> AsyncIterator[dict[str, Any]]:
        """Stream raw data from Binance WebSocket."""
        if not self._ws:
            raise RuntimeError("Not connected")
        
        try:
            async for message in self._ws:
                data = json.loads(message)
                
                # Combined stream format
                if "stream" in data:
                    yield {
                        "stream": data["stream"],
                        "data": data["data"]
                    }
                # Single stream format
                elif "e" in data:
                    yield {"stream": None, "data": data}
                    
        except ConnectionClosed as e:
            logger.warning(f"WebSocket connection closed: {e}")
            self._connected = False
            self.status = FeedStatus.DISCONNECTED
            raise
    
    async def _process_message(
        self,
        raw_data: dict[str, Any]
    ) -> Tick | OHLCV | OrderBook | None:
        """Process raw Binance message into standardized format."""
        data = raw_data.get("data", raw_data)
        event_type = data.get("e")
        
        if event_type == "trade":
            return self._process_trade(data)
        elif event_type == "bookTicker":
            return self._process_book_ticker(data)
        elif event_type == "depthUpdate":
            return self._process_depth(data)
        elif event_type == "kline":
            return self._process_kline(data)
        
        return None
    
    def _process_trade(self, data: dict[str, Any]) -> Tick:
        """Process trade event into Tick."""
        symbol = data["s"]
        
        # Get current book ticker for bid/ask
        book = self._order_books.get(symbol)
        bid = float(book.best_bid) if book and book.best_bid else float(data["p"])
        ask = float(book.best_ask) if book and book.best_ask else float(data["p"])
        
        tick = Tick(
            timestamp=datetime.utcfromtimestamp(data["T"] / 1000),
            symbol=symbol,
            price=float(data["p"]),
            volume=float(data["q"]),
            bid=bid,
            ask=ask,
            exchange=Exchange.BINANCE,
            asset_class=AssetClass.CRYPTO,
            trade_id=str(data["t"])
        )
        
        self._last_ticks[symbol] = tick
        return tick
    
    def _process_book_ticker(self, data: dict[str, Any]) -> Tick:
        """Process book ticker event into Tick with bid/ask."""
        symbol = data["s"]
        
        # Get last trade price if available
        last_tick = self._last_ticks.get(symbol)
        price = last_tick.price if last_tick else (float(data["b"]) + float(data["a"])) / 2
        
        tick = Tick(
            timestamp=datetime.utcnow(),  # Book ticker doesn't have timestamp
            symbol=symbol,
            price=price,
            volume=0.0,  # Book ticker doesn't have volume
            bid=float(data["b"]),
            ask=float(data["a"]),
            bid_size=float(data["B"]),
            ask_size=float(data["A"]),
            exchange=Exchange.BINANCE,
            asset_class=AssetClass.CRYPTO
        )
        
        self._last_ticks[symbol] = tick
        return tick
    
    def _process_depth(self, data: dict[str, Any]) -> OrderBook:
        """Process depth update into OrderBook."""
        symbol = data["s"]
        
        bids = [
            OrderBookLevel(price=float(b[0]), quantity=float(b[1]))
            for b in data.get("b", [])
        ]
        
        asks = [
            OrderBookLevel(price=float(a[0]), quantity=float(a[1]))
            for a in data.get("a", [])
        ]
        
        order_book = OrderBook(
            timestamp=datetime.utcfromtimestamp(data["E"] / 1000),
            symbol=symbol,
            exchange=Exchange.BINANCE,
            bids=bids,
            asks=asks
        )
        
        self._order_books[symbol] = order_book
        return order_book
    
    def _process_kline(self, data: dict[str, Any]) -> OHLCV:
        """Process kline/candlestick into OHLCV."""
        kline = data["k"]
        
        return OHLCV(
            timestamp=datetime.utcfromtimestamp(kline["t"] / 1000),
            symbol=data["s"],
            open=float(kline["o"]),
            high=float(kline["h"]),
            low=float(kline["l"]),
            close=float(kline["c"]),
            volume=float(kline["v"]),
            exchange=Exchange.BINANCE,
            asset_class=AssetClass.CRYPTO,
            timeframe=kline["i"],
            trades=kline["n"]
        )
    
    async def get_latest(self, symbol: str) -> Tick | None:
        """Get the latest tick for a symbol."""
        return self._last_ticks.get(symbol)
    
    async def get_order_book(self, symbol: str) -> OrderBook | None:
        """Get the latest order book for a symbol."""
        return self._order_books.get(symbol)

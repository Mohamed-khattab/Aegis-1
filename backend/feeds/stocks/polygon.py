"""
Polygon.io WebSocket Feed for Aegis-1

Real-time stock market data from Polygon.io.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, AsyncIterator, Optional

import websockets
from websockets.exceptions import ConnectionClosed

from feeds.base import BaseFeed, FeedStatus, FeedType
from models.market_data import Tick, OHLCV, AssetClass, Exchange
from config.settings import settings


logger = logging.getLogger(__name__)


class PolygonFeed(BaseFeed):
    """
    Polygon.io WebSocket feed for real-time stock market data.
    
    Supports:
    - Real-time trades
    - Real-time quotes
    - Aggregate bars
    """
    
    WS_URL = "wss://socket.polygon.io/stocks"
    
    def __init__(
        self,
        symbols: list[str] | None = None,
        api_key: str | None = None
    ):
        """
        Initialize Polygon feed.
        
        Args:
            symbols: List of stock symbols (e.g., ["AAPL", "GOOGL"])
            api_key: Polygon API key
        """
        super().__init__(
            feed_id="polygon",
            feed_type=FeedType.MARKET,
            symbols=symbols or ["AAPL", "MSFT", "GOOGL"]
        )
        
        self.api_key = api_key or settings.polygon_api_key
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._last_ticks: dict[str, Tick] = {}
        self._last_quotes: dict[str, dict] = {}
    
    async def connect(self) -> None:
        """Establish WebSocket connection to Polygon."""
        if not self.api_key:
            raise RuntimeError("Polygon API key not configured")
        
        try:
            self._ws = await websockets.connect(
                self.WS_URL,
                ping_interval=20,
                ping_timeout=10
            )
            
            # Authenticate
            auth_msg = {"action": "auth", "params": self.api_key}
            await self._ws.send(json.dumps(auth_msg))
            
            # Wait for auth confirmation
            response = await self._ws.recv()
            data = json.loads(response)
            
            if isinstance(data, list) and any(
                m.get("status") == "connected" or m.get("status") == "auth_success"
                for m in data
            ):
                logger.info("Polygon authentication successful")
            else:
                logger.warning(f"Unexpected auth response: {data}")
            
            # Subscribe to streams
            symbols_str = ",".join(self.symbols)
            subscribe_msg = {
                "action": "subscribe",
                "params": f"T.{symbols_str},Q.{symbols_str},AM.{symbols_str}"
            }
            await self._ws.send(json.dumps(subscribe_msg))
            
            self._connected = True
            self.status = FeedStatus.CONNECTED
            logger.info(f"Connected to Polygon WebSocket: {len(self.symbols)} symbols")
            
        except Exception as e:
            logger.error(f"Failed to connect to Polygon: {e}")
            self.status = FeedStatus.ERROR
            raise
    
    async def disconnect(self) -> None:
        """Close WebSocket connection."""
        self._should_reconnect = False
        self._connected = False
        
        if self._ws:
            # Unsubscribe
            symbols_str = ",".join(self.symbols)
            unsubscribe_msg = {
                "action": "unsubscribe",
                "params": f"T.{symbols_str},Q.{symbols_str},AM.{symbols_str}"
            }
            try:
                await self._ws.send(json.dumps(unsubscribe_msg))
            except Exception:
                pass
            
            await self._ws.close()
            self._ws = None
        
        self.status = FeedStatus.DISCONNECTED
        logger.info("Disconnected from Polygon")
    
    async def subscribe(self, symbols: list[str]) -> None:
        """Subscribe to additional symbols."""
        if not self._ws:
            raise RuntimeError("Not connected")
        
        for symbol in symbols:
            if symbol not in self.symbols:
                self.symbols.append(symbol)
        
        symbols_str = ",".join(symbols)
        subscribe_msg = {
            "action": "subscribe",
            "params": f"T.{symbols_str},Q.{symbols_str},AM.{symbols_str}"
        }
        
        await self._ws.send(json.dumps(subscribe_msg))
        logger.info(f"Subscribed to {symbols}")
    
    async def unsubscribe(self, symbols: list[str]) -> None:
        """Unsubscribe from symbols."""
        if not self._ws:
            return
        
        self.symbols = [s for s in self.symbols if s not in symbols]
        
        symbols_str = ",".join(symbols)
        unsubscribe_msg = {
            "action": "unsubscribe",
            "params": f"T.{symbols_str},Q.{symbols_str},AM.{symbols_str}"
        }
        
        await self._ws.send(json.dumps(unsubscribe_msg))
        logger.info(f"Unsubscribed from {symbols}")
    
    async def _stream_data(self) -> AsyncIterator[dict[str, Any]]:
        """Stream raw data from Polygon WebSocket."""
        if not self._ws:
            raise RuntimeError("Not connected")
        
        try:
            async for message in self._ws:
                data = json.loads(message)
                
                # Polygon sends arrays of messages
                if isinstance(data, list):
                    for item in data:
                        yield item
                else:
                    yield data
                    
        except ConnectionClosed as e:
            logger.warning(f"WebSocket connection closed: {e}")
            self._connected = False
            self.status = FeedStatus.DISCONNECTED
            raise
    
    async def _process_message(
        self,
        raw_data: dict[str, Any]
    ) -> Tick | OHLCV | None:
        """Process raw Polygon message into standardized format."""
        ev_type = raw_data.get("ev")
        
        if ev_type == "T":  # Trade
            return self._process_trade(raw_data)
        elif ev_type == "Q":  # Quote
            return self._process_quote(raw_data)
        elif ev_type == "AM":  # Aggregate minute
            return self._process_aggregate(raw_data)
        elif ev_type == "status":
            logger.debug(f"Polygon status: {raw_data.get('message')}")
            return None
        
        return None
    
    def _process_trade(self, data: dict[str, Any]) -> Tick:
        """Process trade message into Tick."""
        symbol = data["sym"]
        
        # Get last quote for bid/ask
        quote = self._last_quotes.get(symbol, {})
        price = float(data["p"])
        
        tick = Tick(
            timestamp=datetime.utcfromtimestamp(data["t"] / 1000),
            symbol=symbol,
            price=price,
            volume=float(data["s"]),
            bid=quote.get("bid", price),
            ask=quote.get("ask", price),
            exchange=Exchange.POLYGON,
            asset_class=AssetClass.STOCK,
            trade_id=str(data.get("i", ""))
        )
        
        self._last_ticks[symbol] = tick
        return tick
    
    def _process_quote(self, data: dict[str, Any]) -> Tick:
        """Process quote message into Tick with bid/ask."""
        symbol = data["sym"]
        
        bid = float(data["bp"])
        ask = float(data["ap"])
        
        # Store quote for trade processing
        self._last_quotes[symbol] = {
            "bid": bid,
            "ask": ask,
            "bid_size": float(data["bs"]),
            "ask_size": float(data["as"])
        }
        
        # Get last trade price
        last_tick = self._last_ticks.get(symbol)
        price = last_tick.price if last_tick else (bid + ask) / 2
        
        tick = Tick(
            timestamp=datetime.utcfromtimestamp(data["t"] / 1000),
            symbol=symbol,
            price=price,
            volume=0.0,
            bid=bid,
            ask=ask,
            bid_size=float(data["bs"]),
            ask_size=float(data["as"]),
            exchange=Exchange.POLYGON,
            asset_class=AssetClass.STOCK
        )
        
        self._last_ticks[symbol] = tick
        return tick
    
    def _process_aggregate(self, data: dict[str, Any]) -> OHLCV:
        """Process aggregate minute bar into OHLCV."""
        return OHLCV(
            timestamp=datetime.utcfromtimestamp(data["s"] / 1000),
            symbol=data["sym"],
            open=float(data["o"]),
            high=float(data["h"]),
            low=float(data["l"]),
            close=float(data["c"]),
            volume=float(data["v"]),
            exchange=Exchange.POLYGON,
            asset_class=AssetClass.STOCK,
            timeframe="1m",
            trades=data.get("n")
        )
    
    async def get_latest(self, symbol: str) -> Tick | None:
        """Get the latest tick for a symbol."""
        return self._last_ticks.get(symbol)

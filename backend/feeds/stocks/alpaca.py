"""
Alpaca WebSocket Feed for Aegis-1

Real-time stock market data from Alpaca.
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


class AlpacaFeed(BaseFeed):
    """
    Alpaca WebSocket feed for real-time stock market data.
    
    Supports:
    - Real-time trades
    - Real-time quotes (NBBO)
    - Minute bars
    
    Note: Requires Alpaca API key for market data.
    """
    
    # Alpaca WebSocket endpoints
    WS_URL_IEX = "wss://stream.data.alpaca.markets/v2/iex"
    WS_URL_SIP = "wss://stream.data.alpaca.markets/v2/sip"
    
    def __init__(
        self,
        symbols: list[str] | None = None,
        use_sip: bool = False,
        api_key: str | None = None,
        secret_key: str | None = None
    ):
        """
        Initialize Alpaca feed.
        
        Args:
            symbols: List of stock symbols (e.g., ["AAPL", "GOOGL"])
            use_sip: Use SIP feed (paid) instead of IEX (free)
            api_key: Alpaca API key
            secret_key: Alpaca secret key
        """
        super().__init__(
            feed_id="alpaca",
            feed_type=FeedType.MARKET,
            symbols=symbols or ["AAPL", "MSFT", "GOOGL"]
        )
        
        self.use_sip = use_sip
        self.api_key = api_key or settings.alpaca_api_key
        self.secret_key = secret_key or settings.alpaca_secret_key
        
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._last_ticks: dict[str, Tick] = {}
        self._last_quotes: dict[str, dict] = {}
    
    @property
    def ws_url(self) -> str:
        """Get the appropriate WebSocket URL."""
        return self.WS_URL_SIP if self.use_sip else self.WS_URL_IEX
    
    async def connect(self) -> None:
        """Establish WebSocket connection to Alpaca."""
        if not self.api_key or not self.secret_key:
            raise RuntimeError("Alpaca API credentials not configured")
        
        try:
            self._ws = await websockets.connect(
                self.ws_url,
                ping_interval=20,
                ping_timeout=10
            )
            
            # Authenticate
            auth_msg = {
                "action": "auth",
                "key": self.api_key,
                "secret": self.secret_key
            }
            await self._ws.send(json.dumps(auth_msg))
            
            # Wait for auth confirmation
            response = await self._ws.recv()
            data = json.loads(response)
            
            if isinstance(data, list) and data[0].get("T") == "success":
                logger.info("Alpaca authentication successful")
            else:
                raise RuntimeError(f"Authentication failed: {data}")
            
            # Subscribe to streams
            subscribe_msg = {
                "action": "subscribe",
                "trades": self.symbols,
                "quotes": self.symbols,
                "bars": self.symbols
            }
            await self._ws.send(json.dumps(subscribe_msg))
            
            # Wait for subscription confirmation
            response = await self._ws.recv()
            data = json.loads(response)
            
            self._connected = True
            self.status = FeedStatus.CONNECTED
            logger.info(f"Connected to Alpaca WebSocket: {len(self.symbols)} symbols")
            
        except Exception as e:
            logger.error(f"Failed to connect to Alpaca: {e}")
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
        logger.info("Disconnected from Alpaca")
    
    async def subscribe(self, symbols: list[str]) -> None:
        """Subscribe to additional symbols."""
        if not self._ws:
            raise RuntimeError("Not connected")
        
        for symbol in symbols:
            if symbol not in self.symbols:
                self.symbols.append(symbol)
        
        subscribe_msg = {
            "action": "subscribe",
            "trades": symbols,
            "quotes": symbols,
            "bars": symbols
        }
        
        await self._ws.send(json.dumps(subscribe_msg))
        logger.info(f"Subscribed to {symbols}")
    
    async def unsubscribe(self, symbols: list[str]) -> None:
        """Unsubscribe from symbols."""
        if not self._ws:
            return
        
        self.symbols = [s for s in self.symbols if s not in symbols]
        
        unsubscribe_msg = {
            "action": "unsubscribe",
            "trades": symbols,
            "quotes": symbols,
            "bars": symbols
        }
        
        await self._ws.send(json.dumps(unsubscribe_msg))
        logger.info(f"Unsubscribed from {symbols}")
    
    async def _stream_data(self) -> AsyncIterator[dict[str, Any]]:
        """Stream raw data from Alpaca WebSocket."""
        if not self._ws:
            raise RuntimeError("Not connected")
        
        try:
            async for message in self._ws:
                data = json.loads(message)
                
                # Alpaca sends arrays of messages
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
        """Process raw Alpaca message into standardized format."""
        msg_type = raw_data.get("T")
        
        if msg_type == "t":  # Trade
            return self._process_trade(raw_data)
        elif msg_type == "q":  # Quote
            return self._process_quote(raw_data)
        elif msg_type == "b":  # Bar
            return self._process_bar(raw_data)
        elif msg_type in ("success", "subscription", "error"):
            # System messages
            if msg_type == "error":
                logger.error(f"Alpaca error: {raw_data}")
            return None
        
        return None
    
    def _process_trade(self, data: dict[str, Any]) -> Tick:
        """Process trade message into Tick."""
        symbol = data["S"]
        
        # Get last quote for bid/ask
        quote = self._last_quotes.get(symbol, {})
        price = float(data["p"])
        
        tick = Tick(
            timestamp=datetime.fromisoformat(data["t"].replace("Z", "+00:00")).replace(tzinfo=None),
            symbol=symbol,
            price=price,
            volume=float(data["s"]),
            bid=quote.get("bid", price),
            ask=quote.get("ask", price),
            exchange=Exchange.ALPACA,
            asset_class=AssetClass.STOCK,
            trade_id=str(data.get("i", ""))
        )
        
        self._last_ticks[symbol] = tick
        return tick
    
    def _process_quote(self, data: dict[str, Any]) -> Tick:
        """Process quote message into Tick with bid/ask."""
        symbol = data["S"]
        
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
            timestamp=datetime.fromisoformat(data["t"].replace("Z", "+00:00")).replace(tzinfo=None),
            symbol=symbol,
            price=price,
            volume=0.0,
            bid=bid,
            ask=ask,
            bid_size=float(data["bs"]),
            ask_size=float(data["as"]),
            exchange=Exchange.ALPACA,
            asset_class=AssetClass.STOCK
        )
        
        self._last_ticks[symbol] = tick
        return tick
    
    def _process_bar(self, data: dict[str, Any]) -> OHLCV:
        """Process bar message into OHLCV."""
        return OHLCV(
            timestamp=datetime.fromisoformat(data["t"].replace("Z", "+00:00")).replace(tzinfo=None),
            symbol=data["S"],
            open=float(data["o"]),
            high=float(data["h"]),
            low=float(data["l"]),
            close=float(data["c"]),
            volume=float(data["v"]),
            exchange=Exchange.ALPACA,
            asset_class=AssetClass.STOCK,
            timeframe="1m",
            trades=data.get("n")
        )
    
    async def get_latest(self, symbol: str) -> Tick | None:
        """Get the latest tick for a symbol."""
        return self._last_ticks.get(symbol)

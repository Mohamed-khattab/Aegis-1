"""
Coinbase WebSocket Feed for Aegis-1

Real-time market data from Coinbase exchange.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, AsyncIterator, Optional

import websockets
from websockets.exceptions import ConnectionClosed

from feeds.base import BaseFeed, FeedStatus, FeedType
from models.market_data import Tick, OrderBook, OrderBookLevel, AssetClass, Exchange
from config.settings import settings


logger = logging.getLogger(__name__)


class CoinbaseFeed(BaseFeed):
    """
    Coinbase WebSocket feed for real-time crypto market data.
    
    Supports:
    - Real-time trades (matches)
    - Level 2 order book updates
    - Ticker updates
    """
    
    WS_URL = "wss://ws-feed.exchange.coinbase.com"
    
    def __init__(
        self,
        symbols: list[str] | None = None,
        channels: list[str] | None = None
    ):
        """
        Initialize Coinbase feed.
        
        Args:
            symbols: List of product IDs (e.g., ["BTC-USD", "ETH-USD"])
            channels: List of channels to subscribe to
        """
        super().__init__(
            feed_id="coinbase",
            feed_type=FeedType.MARKET,
            symbols=symbols or ["BTC-USD", "ETH-USD"]
        )
        
        self.channels = channels or ["ticker", "matches"]
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._last_ticks: dict[str, Tick] = {}
        self._order_books: dict[str, OrderBook] = {}
    
    async def connect(self) -> None:
        """Establish WebSocket connection to Coinbase."""
        try:
            self._ws = await websockets.connect(
                self.WS_URL,
                ping_interval=20,
                ping_timeout=10
            )
            
            # Subscribe to channels
            subscribe_msg = {
                "type": "subscribe",
                "product_ids": self.symbols,
                "channels": self.channels
            }
            
            await self._ws.send(json.dumps(subscribe_msg))
            
            # Wait for subscription confirmation
            response = await self._ws.recv()
            data = json.loads(response)
            
            if data.get("type") == "subscriptions":
                self._connected = True
                self.status = FeedStatus.CONNECTED
                logger.info(f"Connected to Coinbase WebSocket: {len(self.symbols)} symbols")
            else:
                raise RuntimeError(f"Subscription failed: {data}")
                
        except Exception as e:
            logger.error(f"Failed to connect to Coinbase: {e}")
            self.status = FeedStatus.ERROR
            raise
    
    async def disconnect(self) -> None:
        """Close WebSocket connection."""
        self._should_reconnect = False
        self._connected = False
        
        if self._ws:
            # Unsubscribe before closing
            unsubscribe_msg = {
                "type": "unsubscribe",
                "product_ids": self.symbols,
                "channels": self.channels
            }
            try:
                await self._ws.send(json.dumps(unsubscribe_msg))
            except Exception:
                pass
            
            await self._ws.close()
            self._ws = None
        
        self.status = FeedStatus.DISCONNECTED
        logger.info("Disconnected from Coinbase")
    
    async def subscribe(self, symbols: list[str]) -> None:
        """Subscribe to additional symbols."""
        if not self._ws:
            raise RuntimeError("Not connected")
        
        # Add to symbol list
        for symbol in symbols:
            if symbol not in self.symbols:
                self.symbols.append(symbol)
        
        subscribe_msg = {
            "type": "subscribe",
            "product_ids": symbols,
            "channels": self.channels
        }
        
        await self._ws.send(json.dumps(subscribe_msg))
        logger.info(f"Subscribed to {symbols}")
    
    async def unsubscribe(self, symbols: list[str]) -> None:
        """Unsubscribe from symbols."""
        if not self._ws:
            return
        
        self.symbols = [s for s in self.symbols if s not in symbols]
        
        unsubscribe_msg = {
            "type": "unsubscribe",
            "product_ids": symbols,
            "channels": self.channels
        }
        
        await self._ws.send(json.dumps(unsubscribe_msg))
        logger.info(f"Unsubscribed from {symbols}")
    
    async def _stream_data(self) -> AsyncIterator[dict[str, Any]]:
        """Stream raw data from Coinbase WebSocket."""
        if not self._ws:
            raise RuntimeError("Not connected")
        
        try:
            async for message in self._ws:
                data = json.loads(message)
                msg_type = data.get("type")
                
                # Skip system messages
                if msg_type in ("subscriptions", "heartbeat"):
                    continue
                
                yield data
                    
        except ConnectionClosed as e:
            logger.warning(f"WebSocket connection closed: {e}")
            self._connected = False
            self.status = FeedStatus.DISCONNECTED
            raise
    
    async def _process_message(
        self,
        raw_data: dict[str, Any]
    ) -> Tick | OrderBook | None:
        """Process raw Coinbase message into standardized format."""
        msg_type = raw_data.get("type")
        
        if msg_type == "ticker":
            return self._process_ticker(raw_data)
        elif msg_type == "match" or msg_type == "last_match":
            return self._process_match(raw_data)
        elif msg_type == "l2update":
            return self._process_l2_update(raw_data)
        elif msg_type == "snapshot":
            return self._process_snapshot(raw_data)
        
        return None
    
    def _process_ticker(self, data: dict[str, Any]) -> Tick:
        """Process ticker message into Tick."""
        symbol = data["product_id"]
        
        tick = Tick(
            timestamp=datetime.fromisoformat(data["time"].replace("Z", "+00:00")).replace(tzinfo=None),
            symbol=symbol,
            price=float(data["price"]),
            volume=float(data.get("volume_24h", 0)),
            bid=float(data.get("best_bid", data["price"])),
            ask=float(data.get("best_ask", data["price"])),
            bid_size=float(data.get("best_bid_size", 0)) if data.get("best_bid_size") else None,
            ask_size=float(data.get("best_ask_size", 0)) if data.get("best_ask_size") else None,
            exchange=Exchange.COINBASE,
            asset_class=AssetClass.CRYPTO,
            trade_id=str(data.get("trade_id", ""))
        )
        
        self._last_ticks[symbol] = tick
        return tick
    
    def _process_match(self, data: dict[str, Any]) -> Tick:
        """Process match (trade) message into Tick."""
        symbol = data["product_id"]
        
        # Get current book for bid/ask
        last_tick = self._last_ticks.get(symbol)
        price = float(data["price"])
        
        tick = Tick(
            timestamp=datetime.fromisoformat(data["time"].replace("Z", "+00:00")).replace(tzinfo=None),
            symbol=symbol,
            price=price,
            volume=float(data["size"]),
            bid=last_tick.bid if last_tick else price,
            ask=last_tick.ask if last_tick else price,
            exchange=Exchange.COINBASE,
            asset_class=AssetClass.CRYPTO,
            trade_id=str(data["trade_id"])
        )
        
        self._last_ticks[symbol] = tick
        return tick
    
    def _process_snapshot(self, data: dict[str, Any]) -> OrderBook:
        """Process L2 snapshot into OrderBook."""
        symbol = data["product_id"]
        
        bids = [
            OrderBookLevel(price=float(b[0]), quantity=float(b[1]))
            for b in data.get("bids", [])[:20]  # Top 20 levels
        ]
        
        asks = [
            OrderBookLevel(price=float(a[0]), quantity=float(a[1]))
            for a in data.get("asks", [])[:20]
        ]
        
        order_book = OrderBook(
            timestamp=datetime.utcnow(),
            symbol=symbol,
            exchange=Exchange.COINBASE,
            bids=bids,
            asks=asks
        )
        
        self._order_books[symbol] = order_book
        return order_book
    
    def _process_l2_update(self, data: dict[str, Any]) -> OrderBook | None:
        """Process L2 update and return updated OrderBook."""
        symbol = data["product_id"]
        
        # Get existing order book or create new one
        order_book = self._order_books.get(symbol)
        if not order_book:
            return None
        
        # Apply changes
        for change in data.get("changes", []):
            side, price_str, size_str = change
            price = float(price_str)
            size = float(size_str)
            
            if side == "buy":
                # Update bids
                if size == 0:
                    order_book.bids = [b for b in order_book.bids if b.price != price]
                else:
                    # Update or insert
                    updated = False
                    for i, bid in enumerate(order_book.bids):
                        if bid.price == price:
                            order_book.bids[i] = OrderBookLevel(price=price, quantity=size)
                            updated = True
                            break
                    if not updated:
                        order_book.bids.append(OrderBookLevel(price=price, quantity=size))
                        order_book.bids.sort(key=lambda x: x.price, reverse=True)
            else:
                # Update asks
                if size == 0:
                    order_book.asks = [a for a in order_book.asks if a.price != price]
                else:
                    updated = False
                    for i, ask in enumerate(order_book.asks):
                        if ask.price == price:
                            order_book.asks[i] = OrderBookLevel(price=price, quantity=size)
                            updated = True
                            break
                    if not updated:
                        order_book.asks.append(OrderBookLevel(price=price, quantity=size))
                        order_book.asks.sort(key=lambda x: x.price)
        
        order_book.timestamp = datetime.fromisoformat(
            data["time"].replace("Z", "+00:00")
        ).replace(tzinfo=None)
        
        self._order_books[symbol] = order_book
        return order_book
    
    async def get_latest(self, symbol: str) -> Tick | None:
        """Get the latest tick for a symbol."""
        return self._last_ticks.get(symbol)
    
    async def get_order_book(self, symbol: str) -> OrderBook | None:
        """Get the latest order book for a symbol."""
        return self._order_books.get(symbol)

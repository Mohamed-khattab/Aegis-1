"""
Historical Data Feed for Aegis-1

Provides historical market data for backtesting and vector database population.
Based on PRD Section 4 - Feed 03: Historical Data Feed.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, AsyncIterator, Optional

import aiohttp
import pandas as pd

from feeds.base import BaseFeed, FeedStatus, FeedType
from models.market_data import OHLCV, AssetClass, Exchange
from config.settings import settings


logger = logging.getLogger(__name__)


class HistoricalFeed(BaseFeed):
    """
    Historical data feed for backtesting and analysis.
    
    Sources:
    - Yahoo Finance (free)
    - Alpha Vantage (requires API key)
    - Alpaca historical API
    
    From PRD Section 4:
    - Format: Time-series data compatible with TimescaleDB
    - Update Frequency: Daily batch updates for historical context
    """
    
    # Yahoo Finance URL template
    YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    
    def __init__(
        self,
        symbols: list[str] | None = None,
        default_lookback_days: int = 365
    ):
        """
        Initialize historical feed.
        
        Args:
            symbols: List of symbols to fetch data for
            default_lookback_days: Default days of history to fetch
        """
        super().__init__(
            feed_id="historical",
            feed_type=FeedType.HISTORICAL,
            symbols=symbols or []
        )
        
        self.default_lookback_days = default_lookback_days
        self._session: Optional[aiohttp.ClientSession] = None
        self._cache: dict[str, pd.DataFrame] = {}
    
    async def connect(self) -> None:
        """Initialize HTTP session."""
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=60)
        )
        
        self._connected = True
        self.status = FeedStatus.CONNECTED
        logger.info("Historical feed connected")
    
    async def disconnect(self) -> None:
        """Close HTTP session."""
        self._connected = False
        
        if self._session:
            await self._session.close()
            self._session = None
        
        self.status = FeedStatus.DISCONNECTED
        logger.info("Historical feed disconnected")
    
    async def subscribe(self, symbols: list[str]) -> None:
        """Add symbols to fetch history for."""
        for symbol in symbols:
            if symbol not in self.symbols:
                self.symbols.append(symbol)
    
    async def unsubscribe(self, symbols: list[str]) -> None:
        """Remove symbols."""
        self.symbols = [s for s in self.symbols if s not in symbols]
        # Clear cache for removed symbols
        for symbol in symbols:
            self._cache.pop(symbol, None)
    
    async def _stream_data(self) -> AsyncIterator[dict[str, Any]]:
        """Historical feed doesn't stream - use fetch methods instead."""
        # This is a pull-based feed, not streaming
        while self._connected:
            await asyncio.sleep(3600)  # Check hourly for updates
            yield {"type": "heartbeat"}
    
    async def _process_message(
        self,
        raw_data: dict[str, Any]
    ) -> OHLCV | None:
        """Process is not used for historical - use fetch methods."""
        return None
    
    async def fetch_ohlcv(
        self,
        symbol: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        interval: str = "1d",
        use_cache: bool = True
    ) -> list[OHLCV]:
        """
        Fetch OHLCV data for a symbol.
        
        Args:
            symbol: Stock/crypto symbol
            start_date: Start date (default: lookback_days ago)
            end_date: End date (default: now)
            interval: Data interval (1m, 5m, 15m, 1h, 1d, 1wk, 1mo)
            use_cache: Use cached data if available
        
        Returns:
            List of OHLCV objects
        """
        if not self._session:
            raise RuntimeError("Feed not connected")
        
        # Set defaults
        if end_date is None:
            end_date = datetime.utcnow()
        if start_date is None:
            start_date = end_date - timedelta(days=self.default_lookback_days)
        
        # Check cache
        cache_key = f"{symbol}_{interval}"
        if use_cache and cache_key in self._cache:
            df = self._cache[cache_key]
            mask = (df.index >= start_date) & (df.index <= end_date)
            if mask.any():
                return self._df_to_ohlcv(df[mask], symbol)
        
        # Fetch from Yahoo Finance
        try:
            data = await self._fetch_yahoo(symbol, start_date, end_date, interval)
            
            if data:
                # Cache the data
                df = pd.DataFrame(data)
                df.set_index("timestamp", inplace=True)
                self._cache[cache_key] = df
                
                return [
                    OHLCV(
                        timestamp=row["timestamp"],
                        symbol=symbol,
                        open=row["open"],
                        high=row["high"],
                        low=row["low"],
                        close=row["close"],
                        volume=row["volume"],
                        exchange=Exchange.NYSE,  # Simplified
                        asset_class=AssetClass.STOCK,
                        timeframe=interval
                    )
                    for row in data
                ]
            
        except Exception as e:
            logger.error(f"Error fetching historical data for {symbol}: {e}")
        
        return []
    
    async def _fetch_yahoo(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        interval: str
    ) -> list[dict[str, Any]]:
        """Fetch data from Yahoo Finance."""
        if not self._session:
            return []
        
        # Convert interval to Yahoo format
        yahoo_interval = {
            "1m": "1m",
            "5m": "5m",
            "15m": "15m",
            "1h": "1h",
            "1d": "1d",
            "1wk": "1wk",
            "1mo": "1mo"
        }.get(interval, "1d")
        
        # Yahoo Finance API parameters
        params = {
            "period1": int(start_date.timestamp()),
            "period2": int(end_date.timestamp()),
            "interval": yahoo_interval,
            "events": "history"
        }
        
        url = self.YAHOO_URL.format(symbol=symbol)
        
        async with self._session.get(url, params=params) as response:
            if response.status != 200:
                logger.warning(f"Yahoo Finance error for {symbol}: {response.status}")
                return []
            
            data = await response.json()
        
        # Parse response
        result = data.get("chart", {}).get("result", [])
        if not result:
            return []
        
        chart = result[0]
        timestamps = chart.get("timestamp", [])
        quote = chart.get("indicators", {}).get("quote", [{}])[0]
        
        ohlcv_data = []
        for i, ts in enumerate(timestamps):
            try:
                ohlcv_data.append({
                    "timestamp": datetime.utcfromtimestamp(ts),
                    "open": quote.get("open", [None])[i],
                    "high": quote.get("high", [None])[i],
                    "low": quote.get("low", [None])[i],
                    "close": quote.get("close", [None])[i],
                    "volume": quote.get("volume", [None])[i] or 0
                })
            except (IndexError, TypeError):
                continue
        
        return [d for d in ohlcv_data if d["close"] is not None]
    
    def _df_to_ohlcv(self, df: pd.DataFrame, symbol: str) -> list[OHLCV]:
        """Convert DataFrame to list of OHLCV objects."""
        result = []
        for idx, row in df.iterrows():
            result.append(OHLCV(
                timestamp=idx if isinstance(idx, datetime) else datetime.fromisoformat(str(idx)),
                symbol=symbol,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
                exchange=Exchange.NYSE,
                asset_class=AssetClass.STOCK,
                timeframe="1d"
            ))
        return result
    
    async def fetch_alpaca_history(
        self,
        symbol: str,
        start_date: datetime,
        end_date: Optional[datetime] = None,
        timeframe: str = "1Day"
    ) -> list[OHLCV]:
        """
        Fetch historical data from Alpaca.
        
        Args:
            symbol: Stock symbol
            start_date: Start date
            end_date: End date (default: now)
            timeframe: Alpaca timeframe (1Min, 5Min, 15Min, 1Hour, 1Day)
        
        Returns:
            List of OHLCV objects
        """
        if not self._session:
            raise RuntimeError("Feed not connected")
        
        if not settings.alpaca_api_key:
            logger.warning("Alpaca API key not configured")
            return []
        
        if end_date is None:
            end_date = datetime.utcnow()
        
        url = f"{settings.alpaca_base_url}/v2/stocks/{symbol}/bars"
        headers = {
            "APCA-API-KEY-ID": settings.alpaca_api_key,
            "APCA-API-SECRET-KEY": settings.alpaca_secret_key
        }
        params = {
            "start": start_date.isoformat() + "Z",
            "end": end_date.isoformat() + "Z",
            "timeframe": timeframe,
            "limit": 10000
        }
        
        try:
            async with self._session.get(url, headers=headers, params=params) as response:
                if response.status != 200:
                    logger.warning(f"Alpaca error for {symbol}: {response.status}")
                    return []
                
                data = await response.json()
            
            bars = data.get("bars", [])
            
            return [
                OHLCV(
                    timestamp=datetime.fromisoformat(bar["t"].replace("Z", "+00:00")).replace(tzinfo=None),
                    symbol=symbol,
                    open=float(bar["o"]),
                    high=float(bar["h"]),
                    low=float(bar["l"]),
                    close=float(bar["c"]),
                    volume=float(bar["v"]),
                    exchange=Exchange.ALPACA,
                    asset_class=AssetClass.STOCK,
                    timeframe=timeframe,
                    trades=bar.get("n")
                )
                for bar in bars
            ]
            
        except Exception as e:
            logger.error(f"Error fetching Alpaca history for {symbol}: {e}")
            return []
    
    async def get_price_history_df(
        self,
        symbol: str,
        days: int = 30,
        interval: str = "1d"
    ) -> pd.DataFrame:
        """
        Get price history as a pandas DataFrame.
        
        Convenient method for analysis and technical indicators.
        
        Args:
            symbol: Stock/crypto symbol
            days: Number of days of history
            interval: Data interval
        
        Returns:
            DataFrame with OHLCV columns
        """
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        ohlcv_list = await self.fetch_ohlcv(
            symbol, start_date, end_date, interval
        )
        
        if not ohlcv_list:
            return pd.DataFrame()
        
        data = [
            {
                "timestamp": o.timestamp,
                "open": o.open,
                "high": o.high,
                "low": o.low,
                "close": o.close,
                "volume": o.volume
            }
            for o in ohlcv_list
        ]
        
        df = pd.DataFrame(data)
        df.set_index("timestamp", inplace=True)
        df.sort_index(inplace=True)
        
        return df
    
    def clear_cache(self, symbol: Optional[str] = None) -> None:
        """Clear cached data."""
        if symbol:
            keys_to_remove = [k for k in self._cache.keys() if k.startswith(symbol)]
            for key in keys_to_remove:
                del self._cache[key]
        else:
            self._cache.clear()

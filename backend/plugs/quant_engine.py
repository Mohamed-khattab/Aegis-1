"""
Quant Engine Plug for Aegis-1

Deterministic calculation of technical indicators.
Based on PRD Section 3 - Plug 03: The Quant Engine (Hard Math).
"""

import logging
from datetime import datetime
from typing import Any, Optional

import numpy as np
import pandas as pd

from plugs.base import BasePlug, PlugStatus
from models.signals import PlugSignal
from models.market_data import MarketDataBundle, OHLCV, OrderBook
from config.settings import settings


logger = logging.getLogger(__name__)


class QuantEnginePlug(BasePlug):
    """
    Quant Engine plug for technical indicator calculations.
    
    From PRD:
    - Requirement: Deterministic calculation of technical indicators 
      (VWAP, Order Flow Imbalance, Volatility)
    - Function: Provides the "ground truth" for entries/exits to balance 
      the AI's qualitative reasoning
    
    From AC-05:
    - The system must automatically reduce the "Quant Plug" weight by 50% 
      if realized volatility exceeds the 30-day moving average by 2x
    """
    
    # Indicator weights for signal composition
    INDICATOR_WEIGHTS = {
        "vwap": 0.2,
        "ofi": 0.25,
        "rsi": 0.15,
        "macd": 0.15,
        "bb": 0.15,
        "trend": 0.1
    }
    
    def __init__(
        self,
        plug_id: str = "quant_engine",
        rsi_period: int = 14,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        bb_period: int = 20,
        bb_std: float = 2.0,
        volatility_lookback: int = 30
    ):
        """
        Initialize Quant Engine plug.
        
        Args:
            plug_id: Unique identifier
            rsi_period: RSI calculation period
            macd_fast: MACD fast EMA period
            macd_slow: MACD slow EMA period
            macd_signal: MACD signal line period
            bb_period: Bollinger Bands period
            bb_std: Bollinger Bands standard deviation
            volatility_lookback: Days for volatility calculation
        """
        super().__init__(plug_id)
        
        self.rsi_period = rsi_period
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.volatility_lookback = volatility_lookback
        
        # Track volatility for AC-05
        self._volatility_history: dict[str, list[float]] = {}
        self._weight_reduction_active: dict[str, bool] = {}
    
    async def initialize(self) -> None:
        """Initialize Quant Engine."""
        self.status = PlugStatus.ACTIVE
        logger.info("Quant Engine plug initialized")
    
    async def shutdown(self) -> None:
        """Shutdown plug."""
        self.status = PlugStatus.INACTIVE
        logger.info("Quant Engine plug shutdown")
    
    async def generate_signal(
        self,
        market_data: MarketDataBundle
    ) -> PlugSignal:
        """
        Generate signal from technical indicator analysis.
        
        Args:
            market_data: Market data bundle with OHLCV and order book
        
        Returns:
            PlugSignal with direction based on technical indicators
        """
        symbol = market_data.symbol
        
        # Need sufficient OHLCV data
        if not market_data.ohlcv or len(market_data.ohlcv) < self.macd_slow + self.macd_signal:
            return PlugSignal.null_signal(
                self.plug_id,
                f"Insufficient OHLCV data (need {self.macd_slow + self.macd_signal} bars)"
            )
        
        # Convert to DataFrame for calculations
        df = self._ohlcv_to_dataframe(market_data.ohlcv)
        
        # Calculate all indicators
        indicators = {}
        
        # VWAP signal
        indicators["vwap"] = self._calculate_vwap_signal(df)
        
        # Order Flow Imbalance (if order book available)
        if market_data.order_book:
            indicators["ofi"] = self._calculate_ofi_signal(market_data.order_book)
        else:
            indicators["ofi"] = 0.0
        
        # RSI signal
        indicators["rsi"] = self._calculate_rsi_signal(df)
        
        # MACD signal
        indicators["macd"] = self._calculate_macd_signal(df)
        
        # Bollinger Bands signal
        indicators["bb"] = self._calculate_bb_signal(df)
        
        # Trend strength
        indicators["trend"] = self._calculate_trend_signal(df)
        
        # Check volatility regime (AC-05)
        current_vol = self._calculate_volatility(df)
        self._check_volatility_regime(symbol, current_vol)
        
        # Calculate weighted signal
        direction = self._combine_indicators(indicators)
        
        # Calculate confidence based on indicator agreement
        confidence = self._calculate_confidence(indicators)
        
        # Apply weight reduction if volatility regime triggered (AC-05)
        if self._weight_reduction_active.get(symbol, False):
            confidence *= 0.5
            logger.info(f"AC-05: Reduced confidence due to high volatility for {symbol}")
        
        # Build reasoning
        reasoning = self._build_reasoning(indicators, current_vol)
        
        return PlugSignal(
            origin=self.plug_id,
            direction=direction,
            confidence=confidence,
            logic=reasoning,
            metadata={
                "indicators": indicators,
                "volatility": current_vol,
                "volatility_regime": self._weight_reduction_active.get(symbol, False)
            }
        )
    
    def _ohlcv_to_dataframe(self, ohlcv: list[OHLCV]) -> pd.DataFrame:
        """Convert OHLCV list to pandas DataFrame."""
        data = [
            {
                "timestamp": o.timestamp,
                "open": o.open,
                "high": o.high,
                "low": o.low,
                "close": o.close,
                "volume": o.volume
            }
            for o in sorted(ohlcv, key=lambda x: x.timestamp)
        ]
        
        df = pd.DataFrame(data)
        df.set_index("timestamp", inplace=True)
        return df
    
    def _calculate_vwap_signal(self, df: pd.DataFrame) -> float:
        """
        Calculate VWAP and generate signal.
        
        Returns signal in [-1, 1] based on price position relative to VWAP.
        """
        # Calculate VWAP
        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        vwap = (typical_price * df["volume"]).cumsum() / df["volume"].cumsum()
        
        current_price = df["close"].iloc[-1]
        current_vwap = vwap.iloc[-1]
        
        if current_vwap == 0:
            return 0.0
        
        # Price deviation from VWAP as percentage
        deviation = (current_price - current_vwap) / current_vwap
        
        # Convert to signal (capped at ±3% deviation)
        signal = max(-1.0, min(1.0, deviation / 0.03))
        
        return signal
    
    def _calculate_ofi_signal(self, order_book: OrderBook) -> float:
        """
        Calculate Order Flow Imbalance signal.
        
        Uses order book depth to determine buying/selling pressure.
        """
        ofi = order_book.order_flow_imbalance(levels=10)
        return ofi  # Already in [-1, 1]
    
    def _calculate_rsi_signal(self, df: pd.DataFrame) -> float:
        """
        Calculate RSI and generate signal.
        
        RSI < 30: Oversold (bullish)
        RSI > 70: Overbought (bearish)
        """
        # Calculate price changes
        delta = df["close"].diff()
        
        # Separate gains and losses
        gains = delta.where(delta > 0, 0)
        losses = (-delta).where(delta < 0, 0)
        
        # Calculate average gains/losses
        avg_gain = gains.rolling(window=self.rsi_period).mean()
        avg_loss = losses.rolling(window=self.rsi_period).mean()
        
        # Calculate RSI
        rs = avg_gain / avg_loss.replace(0, np.inf)
        rsi = 100 - (100 / (1 + rs))
        
        current_rsi = rsi.iloc[-1]
        
        # Convert to signal
        # RSI 30 -> 1.0 (oversold, bullish)
        # RSI 50 -> 0.0 (neutral)
        # RSI 70 -> -1.0 (overbought, bearish)
        if current_rsi <= 30:
            signal = (30 - current_rsi) / 30
        elif current_rsi >= 70:
            signal = (70 - current_rsi) / 30
        else:
            signal = (50 - current_rsi) / 40
        
        return max(-1.0, min(1.0, signal))
    
    def _calculate_macd_signal(self, df: pd.DataFrame) -> float:
        """
        Calculate MACD and generate signal.
        
        Signal based on MACD line crossing signal line.
        """
        # Calculate EMAs
        ema_fast = df["close"].ewm(span=self.macd_fast, adjust=False).mean()
        ema_slow = df["close"].ewm(span=self.macd_slow, adjust=False).mean()
        
        # MACD line
        macd_line = ema_fast - ema_slow
        
        # Signal line
        signal_line = macd_line.ewm(span=self.macd_signal, adjust=False).mean()
        
        # Histogram
        histogram = macd_line - signal_line
        
        # Current values
        current_hist = histogram.iloc[-1]
        prev_hist = histogram.iloc[-2] if len(histogram) > 1 else 0
        
        # Signal based on histogram and its change
        if current_hist > 0 and current_hist > prev_hist:
            signal = min(1.0, current_hist / df["close"].iloc[-1] * 100)
        elif current_hist < 0 and current_hist < prev_hist:
            signal = max(-1.0, current_hist / df["close"].iloc[-1] * 100)
        else:
            signal = current_hist / df["close"].iloc[-1] * 50
        
        return max(-1.0, min(1.0, signal))
    
    def _calculate_bb_signal(self, df: pd.DataFrame) -> float:
        """
        Calculate Bollinger Bands and generate signal.
        
        Price near lower band: bullish
        Price near upper band: bearish
        """
        # Middle band (SMA)
        middle = df["close"].rolling(window=self.bb_period).mean()
        
        # Standard deviation
        std = df["close"].rolling(window=self.bb_period).std()
        
        # Upper and lower bands
        upper = middle + (self.bb_std * std)
        lower = middle - (self.bb_std * std)
        
        current_price = df["close"].iloc[-1]
        current_upper = upper.iloc[-1]
        current_lower = lower.iloc[-1]
        current_middle = middle.iloc[-1]
        
        # Calculate %B (where price is in the bands)
        band_width = current_upper - current_lower
        if band_width == 0:
            return 0.0
        
        percent_b = (current_price - current_lower) / band_width
        
        # Convert to signal (0.5 = neutral, 0 = oversold/bullish, 1 = overbought/bearish)
        signal = -(percent_b - 0.5) * 2
        
        return max(-1.0, min(1.0, signal))
    
    def _calculate_trend_signal(self, df: pd.DataFrame) -> float:
        """
        Calculate trend strength using moving average slopes.
        """
        # Short and long SMAs
        sma_short = df["close"].rolling(window=10).mean()
        sma_long = df["close"].rolling(window=50).mean()
        
        if len(sma_long.dropna()) < 5:
            return 0.0
        
        # Trend direction (short MA vs long MA)
        current_short = sma_short.iloc[-1]
        current_long = sma_long.iloc[-1]
        
        if current_long == 0:
            return 0.0
        
        # Percentage difference
        diff = (current_short - current_long) / current_long
        
        # Trend strength
        signal = max(-1.0, min(1.0, diff * 10))
        
        return signal
    
    def _calculate_volatility(self, df: pd.DataFrame) -> float:
        """Calculate realized volatility (annualized)."""
        returns = df["close"].pct_change().dropna()
        
        if len(returns) < 5:
            return 0.0
        
        # Standard deviation of returns (annualized assuming daily data)
        volatility = returns.std() * np.sqrt(252)
        
        return volatility
    
    def _check_volatility_regime(self, symbol: str, current_vol: float) -> None:
        """
        Check volatility regime and apply weight reduction per AC-05.
        
        AC-05: The system must automatically reduce the "Quant Plug" weight 
        by 50% if realized volatility exceeds the 30-day moving average by 2x.
        """
        # Store volatility history
        if symbol not in self._volatility_history:
            self._volatility_history[symbol] = []
        
        self._volatility_history[symbol].append(current_vol)
        
        # Keep only last 30 days
        self._volatility_history[symbol] = self._volatility_history[symbol][-30:]
        
        # Calculate 30-day average
        history = self._volatility_history[symbol]
        if len(history) < 5:
            return
        
        avg_vol = sum(history) / len(history)
        
        # Check if current volatility exceeds 2x average
        threshold_multiplier = settings.volatility_threshold_multiplier  # Default 2.0
        
        if avg_vol > 0 and current_vol > avg_vol * threshold_multiplier:
            if not self._weight_reduction_active.get(symbol, False):
                logger.warning(
                    f"AC-05 triggered for {symbol}: "
                    f"volatility {current_vol:.2%} > {threshold_multiplier}x avg {avg_vol:.2%}"
                )
            self._weight_reduction_active[symbol] = True
        else:
            self._weight_reduction_active[symbol] = False
    
    def _combine_indicators(self, indicators: dict[str, float]) -> float:
        """Combine indicator signals using weights."""
        weighted_sum = 0.0
        total_weight = 0.0
        
        for name, signal in indicators.items():
            weight = self.INDICATOR_WEIGHTS.get(name, 0.1)
            weighted_sum += signal * weight
            total_weight += weight
        
        if total_weight == 0:
            return 0.0
        
        return weighted_sum / total_weight
    
    def _calculate_confidence(self, indicators: dict[str, float]) -> float:
        """
        Calculate confidence based on indicator agreement.
        
        Higher confidence when indicators agree on direction.
        """
        if not indicators:
            return 0.0
        
        signals = list(indicators.values())
        
        # Check if all signals have same sign
        positive = sum(1 for s in signals if s > 0.1)
        negative = sum(1 for s in signals if s < -0.1)
        neutral = len(signals) - positive - negative
        
        # Agreement ratio
        max_agreement = max(positive, negative)
        agreement = max_agreement / len(signals)
        
        # Strength of signals
        avg_strength = sum(abs(s) for s in signals) / len(signals)
        
        confidence = agreement * 0.6 + avg_strength * 0.4
        
        return min(1.0, confidence)
    
    def _build_reasoning(
        self,
        indicators: dict[str, float],
        volatility: float
    ) -> str:
        """Build human-readable reasoning string."""
        # Determine overall direction
        direction = self._combine_indicators(indicators)
        direction_str = "bullish" if direction > 0.1 else "bearish" if direction < -0.1 else "neutral"
        
        # Find strongest signals
        sorted_indicators = sorted(
            indicators.items(),
            key=lambda x: abs(x[1]),
            reverse=True
        )
        
        strong_signals = [
            f"{name.upper()}: {'+'if val > 0 else ''}{val:.2f}"
            for name, val in sorted_indicators[:3]
        ]
        
        return (
            f"Technical analysis: {direction_str} (score: {direction:.2f}). "
            f"Key indicators: {', '.join(strong_signals)}. "
            f"Volatility: {volatility:.1%}"
        )

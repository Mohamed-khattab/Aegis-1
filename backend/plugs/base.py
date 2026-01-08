"""
Base Plug Interface for Aegis-1

All intelligence plugs must inherit from BasePlug and implement
the generate_signal method. Based on AC Section 4 specifications.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
import logging

from models.signals import PlugSignal
from models.market_data import MarketDataBundle


class PlugStatus(str, Enum):
    """Plug operational status."""
    ACTIVE = "ACTIVE"
    ISOLATED = "ISOLATED"  # Disconnected due to out-of-range values
    DEGRADED = "DEGRADED"  # Operating with reduced weight
    INACTIVE = "INACTIVE"  # Manually disabled


@dataclass
class PlugMetrics:
    """Performance metrics for a plug."""
    
    plug_id: str
    total_signals: int = 0
    correct_signals: int = 0
    accuracy: float = 0.0
    avg_confidence: float = 0.0
    avg_latency_ms: float = 0.0
    last_signal_time: Optional[datetime] = None
    isolation_count: int = 0
    current_weight: float = 1.0
    
    def update_accuracy(self) -> None:
        """Recalculate accuracy from signal counts."""
        if self.total_signals > 0:
            self.accuracy = self.correct_signals / self.total_signals


class BasePlug(ABC):
    """
    Abstract base class for all intelligence plugs.
    
    All plugs must:
    1. Output values in the strict range of [-1.0, 1.0]
    2. Return a PlugSignal with direction, confidence, and logic
    3. Handle errors gracefully and return null signals on failure
    
    From Acceptance Criteria:
    - AC: Signal Normalization - Any value outside [-1.0, 1.0] triggers plug isolation
    """
    
    def __init__(self, plug_id: str):
        """
        Initialize the base plug.
        
        Args:
            plug_id: Unique identifier for this plug instance
        """
        self.plug_id = plug_id
        self.status = PlugStatus.ACTIVE
        self.weight = 1.0
        self.metrics = PlugMetrics(plug_id=plug_id)
        self.logger = logging.getLogger(f"plug.{plug_id}")
        self._last_error: Optional[str] = None
    
    @abstractmethod
    async def generate_signal(
        self,
        market_data: MarketDataBundle
    ) -> PlugSignal:
        """
        Generate a trading signal from market data.
        
        This method must be implemented by all plug subclasses.
        
        Args:
            market_data: Bundle of market data including ticks, OHLCV, 
                        order book, and news
        
        Returns:
            PlugSignal with:
                - direction: -1.0 (strong sell) to 1.0 (strong buy)
                - confidence: 0.0 to 1.0
                - logic: String explaining the reasoning
        
        Raises:
            ValueError: If generated signal is out of valid range
        """
        pass
    
    async def safe_generate_signal(
        self,
        market_data: MarketDataBundle
    ) -> PlugSignal:
        """
        Safely generate a signal with validation and error handling.
        
        Wraps generate_signal to:
        1. Catch and log exceptions
        2. Validate output ranges
        3. Isolate plug if values are out of range
        4. Track performance metrics
        
        Args:
            market_data: Market data bundle for signal generation
        
        Returns:
            PlugSignal (null signal on error)
        """
        start_time = datetime.utcnow()
        
        try:
            # Check if plug is isolated
            if self.status == PlugStatus.ISOLATED:
                self.logger.warning(f"Plug {self.plug_id} is isolated, returning null signal")
                return PlugSignal.null_signal(
                    self.plug_id, 
                    "Plug is isolated"
                )
            
            # Generate the signal
            signal = await self.generate_signal(market_data)
            
            # Validate the signal range (AC: Signal Normalization)
            if not self._validate_signal(signal):
                self._isolate_plug(f"Signal out of range: direction={signal.direction}")
                return PlugSignal.null_signal(
                    self.plug_id,
                    f"Invalid signal range - plug isolated"
                )
            
            # Update metrics
            end_time = datetime.utcnow()
            latency_ms = (end_time - start_time).total_seconds() * 1000
            self._update_metrics(signal, latency_ms)
            
            self._last_error = None
            return signal
            
        except Exception as e:
            self.logger.error(f"Error generating signal: {e}", exc_info=True)
            self._last_error = str(e)
            return PlugSignal.null_signal(
                self.plug_id,
                f"Error: {str(e)}"
            )
    
    def _validate_signal(self, signal: PlugSignal) -> bool:
        """
        Validate that signal values are within allowed ranges.
        
        From AC: Signal Normalization - All plugs must output values
        in the strict range of [-1.0, 1.0]. Any value outside this
        range must trigger immediate plug-isolation.
        
        Args:
            signal: The signal to validate
        
        Returns:
            True if valid, False if out of range
        """
        if not -1.0 <= signal.direction <= 1.0:
            self.logger.error(
                f"Direction {signal.direction} out of range [-1.0, 1.0]"
            )
            return False
        
        if not 0.0 <= signal.confidence <= 1.0:
            self.logger.error(
                f"Confidence {signal.confidence} out of range [0.0, 1.0]"
            )
            return False
        
        return True
    
    def _isolate_plug(self, reason: str) -> None:
        """
        Isolate the plug due to invalid behavior.
        
        Args:
            reason: Reason for isolation
        """
        self.status = PlugStatus.ISOLATED
        self.metrics.isolation_count += 1
        self.logger.critical(f"Plug ISOLATED: {reason}")
    
    def reactivate(self) -> None:
        """Reactivate an isolated plug (manual intervention)."""
        if self.status == PlugStatus.ISOLATED:
            self.status = PlugStatus.ACTIVE
            self.logger.info(f"Plug {self.plug_id} reactivated")
    
    def set_weight(self, weight: float) -> None:
        """
        Set the plug's weight in consensus calculation.
        
        Args:
            weight: New weight (0.0 to 2.0, default 1.0)
        """
        self.weight = max(0.0, min(2.0, weight))
        self.metrics.current_weight = self.weight
        
        if self.weight < 0.5:
            self.status = PlugStatus.DEGRADED
        elif self.status == PlugStatus.DEGRADED and self.weight >= 0.5:
            self.status = PlugStatus.ACTIVE
    
    def _update_metrics(self, signal: PlugSignal, latency_ms: float) -> None:
        """Update performance metrics after signal generation."""
        self.metrics.total_signals += 1
        self.metrics.last_signal_time = signal.timestamp
        
        # Update rolling average latency
        n = self.metrics.total_signals
        prev_avg = self.metrics.avg_latency_ms
        self.metrics.avg_latency_ms = prev_avg + (latency_ms - prev_avg) / n
        
        # Update rolling average confidence
        prev_conf = self.metrics.avg_confidence
        self.metrics.avg_confidence = prev_conf + (signal.confidence - prev_conf) / n
    
    def record_outcome(self, was_correct: bool) -> None:
        """
        Record whether a signal's prediction was correct.
        
        Used by the Dynamic Weighting system to adjust plug weights.
        
        Args:
            was_correct: True if the signal direction matched actual price movement
        """
        if was_correct:
            self.metrics.correct_signals += 1
        self.metrics.update_accuracy()
    
    def get_status(self) -> dict[str, Any]:
        """Get current plug status and metrics."""
        return {
            "plug_id": self.plug_id,
            "status": self.status.value,
            "weight": self.weight,
            "metrics": {
                "total_signals": self.metrics.total_signals,
                "accuracy": self.metrics.accuracy,
                "avg_confidence": self.metrics.avg_confidence,
                "avg_latency_ms": self.metrics.avg_latency_ms,
                "isolation_count": self.metrics.isolation_count,
            },
            "last_error": self._last_error,
        }
    
    @abstractmethod
    async def initialize(self) -> None:
        """
        Initialize the plug (load models, connect to services, etc.).
        
        Called once when the plug is first loaded.
        """
        pass
    
    @abstractmethod
    async def shutdown(self) -> None:
        """
        Gracefully shutdown the plug.
        
        Called when the system is shutting down.
        """
        pass
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(id={self.plug_id}, status={self.status.value})"

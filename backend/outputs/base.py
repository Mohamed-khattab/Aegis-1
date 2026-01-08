"""
Base Output Interface for Aegis-1

All output plugs must inherit from BaseOutput and implement
the required methods for signal delivery.
Based on PRD Section 5 specifications.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
import logging
import asyncio

from models.signals import Signal


class OutputStatus(str, Enum):
    """Output plug operational status."""
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"  # Operating with issues
    INACTIVE = "INACTIVE"  # Manually disabled
    ERROR = "ERROR"


class OutputPriority(str, Enum):
    """Signal priority levels for output routing."""
    CRITICAL = "CRITICAL"  # confidence > 0.8
    HIGH = "HIGH"  # confidence > 0.6
    NORMAL = "NORMAL"  # all other signals
    LOW = "LOW"  # confidence < 0.3


@dataclass
class OutputMetrics:
    """Performance metrics for an output plug."""
    
    output_id: str
    signals_sent: int = 0
    signals_failed: int = 0
    avg_delivery_time_ms: float = 0.0
    last_delivery_time: Optional[datetime] = None
    retry_count: int = 0
    
    @property
    def success_rate(self) -> float:
        """Calculate delivery success rate."""
        total = self.signals_sent + self.signals_failed
        if total == 0:
            return 1.0
        return self.signals_sent / total


class BaseOutput(ABC):
    """
    Abstract base class for all output plugs.
    
    All output plugs must:
    1. Implement send() to deliver signals
    2. Support priority-based filtering
    3. Implement retry logic for failed deliveries
    4. Track delivery metrics
    
    From PRD Section 5:
    - Multiple output plugs operate simultaneously
    - Failure isolation between plugs
    - Priority levels (confidence >0.8 = critical)
    - At-least-once delivery semantics
    """
    
    # Default retry configuration
    DEFAULT_RETRY_DELAYS = [1.0, 5.0, 30.0]  # seconds
    
    def __init__(
        self,
        output_id: str,
        min_priority: OutputPriority = OutputPriority.LOW
    ):
        """
        Initialize the base output.
        
        Args:
            output_id: Unique identifier for this output
            min_priority: Minimum signal priority to accept
        """
        self.output_id = output_id
        self.min_priority = min_priority
        self.status = OutputStatus.ACTIVE
        self.metrics = OutputMetrics(output_id=output_id)
        self.logger = logging.getLogger(f"output.{output_id}")
        self._enabled = True
        
        # Retry configuration
        self.retry_delays = self.DEFAULT_RETRY_DELAYS.copy()
    
    @abstractmethod
    async def send(self, signal: Signal) -> bool:
        """
        Send a signal through this output channel.
        
        Must be implemented by subclasses with channel-specific logic.
        
        Args:
            signal: The signal to send
        
        Returns:
            True if successful, False otherwise
        """
        pass
    
    async def deliver(self, signal: Signal) -> bool:
        """
        Deliver a signal with priority filtering and retry logic.
        
        This is the main interface for sending signals.
        Handles:
        - Priority filtering
        - Retry on failure
        - Metrics tracking
        
        Args:
            signal: The signal to deliver
        
        Returns:
            True if delivered successfully
        """
        # Check if output is enabled
        if not self._enabled or self.status == OutputStatus.INACTIVE:
            return False
        
        # Check priority
        signal_priority = self._get_priority(signal)
        if not self._meets_priority(signal_priority):
            self.logger.debug(
                f"Signal {signal.id} below min priority, skipping"
            )
            return True  # Not a failure, just filtered
        
        # Attempt delivery with retries
        start_time = datetime.utcnow()
        success = await self._deliver_with_retry(signal)
        end_time = datetime.utcnow()
        
        # Update metrics
        delivery_time_ms = (end_time - start_time).total_seconds() * 1000
        self._update_metrics(success, delivery_time_ms)
        
        return success
    
    async def _deliver_with_retry(self, signal: Signal) -> bool:
        """
        Attempt delivery with exponential backoff retry.
        
        From PRD: Reliability - Must implement queue-based delivery
        with at-least-once semantics. Failed deliveries are retried
        up to 3 times with 1-second, 5-second, and 30-second intervals.
        
        Args:
            signal: The signal to deliver
        
        Returns:
            True if delivered successfully
        """
        # First attempt
        try:
            if await self.send(signal):
                return True
        except Exception as e:
            self.logger.error(f"Initial delivery failed: {e}")
        
        # Retry attempts
        for i, delay in enumerate(self.retry_delays):
            self.metrics.retry_count += 1
            self.logger.info(
                f"Retry {i+1}/{len(self.retry_delays)} after {delay}s"
            )
            
            await asyncio.sleep(delay)
            
            try:
                if await self.send(signal):
                    return True
            except Exception as e:
                self.logger.error(f"Retry {i+1} failed: {e}")
        
        # All retries exhausted
        self.logger.error(
            f"All delivery attempts failed for signal {signal.id}"
        )
        self.status = OutputStatus.DEGRADED
        return False
    
    def _get_priority(self, signal: Signal) -> OutputPriority:
        """
        Determine the priority level of a signal.
        
        From PRD: Priority Levels - Critical signals (confidence >0.8)
        are sent to all plugs.
        
        Args:
            signal: The signal to evaluate
        
        Returns:
            OutputPriority level
        """
        if signal.confidence > 0.8:
            return OutputPriority.CRITICAL
        elif signal.confidence > 0.6:
            return OutputPriority.HIGH
        elif signal.confidence > 0.3:
            return OutputPriority.NORMAL
        else:
            return OutputPriority.LOW
    
    def _meets_priority(self, priority: OutputPriority) -> bool:
        """Check if signal meets minimum priority threshold."""
        priority_order = {
            OutputPriority.CRITICAL: 4,
            OutputPriority.HIGH: 3,
            OutputPriority.NORMAL: 2,
            OutputPriority.LOW: 1,
        }
        return priority_order[priority] >= priority_order[self.min_priority]
    
    def _update_metrics(self, success: bool, delivery_time_ms: float) -> None:
        """Update delivery metrics."""
        if success:
            self.metrics.signals_sent += 1
            self.metrics.last_delivery_time = datetime.utcnow()
            
            # Update rolling average
            n = self.metrics.signals_sent
            prev_avg = self.metrics.avg_delivery_time_ms
            self.metrics.avg_delivery_time_ms = (
                prev_avg + (delivery_time_ms - prev_avg) / n
            )
        else:
            self.metrics.signals_failed += 1
    
    def enable(self) -> None:
        """Enable the output plug."""
        self._enabled = True
        self.status = OutputStatus.ACTIVE
        self.logger.info(f"Output {self.output_id} enabled")
    
    def disable(self) -> None:
        """Disable the output plug."""
        self._enabled = False
        self.status = OutputStatus.INACTIVE
        self.logger.info(f"Output {self.output_id} disabled")
    
    def set_min_priority(self, priority: OutputPriority) -> None:
        """Set the minimum priority threshold."""
        self.min_priority = priority
    
    def get_status(self) -> dict[str, Any]:
        """Get current output status and metrics."""
        return {
            "output_id": self.output_id,
            "status": self.status.value,
            "enabled": self._enabled,
            "min_priority": self.min_priority.value,
            "metrics": {
                "signals_sent": self.metrics.signals_sent,
                "signals_failed": self.metrics.signals_failed,
                "success_rate": self.metrics.success_rate,
                "avg_delivery_time_ms": self.metrics.avg_delivery_time_ms,
                "retry_count": self.metrics.retry_count,
            },
        }
    
    @abstractmethod
    async def initialize(self) -> None:
        """
        Initialize the output (connect to services, etc.).
        
        Called once when the output is first loaded.
        """
        pass
    
    @abstractmethod
    async def shutdown(self) -> None:
        """
        Gracefully shutdown the output.
        
        Called when the system is shutting down.
        """
        pass
    
    async def health_check(self) -> bool:
        """
        Check if the output is healthy.
        
        Returns:
            True if output is operating normally
        """
        return self.status in (OutputStatus.ACTIVE, OutputStatus.DEGRADED)
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(id={self.output_id}, status={self.status.value})"

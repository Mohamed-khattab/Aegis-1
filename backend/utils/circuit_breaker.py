"""
Circuit Breaker and Kill Switch for Aegis-1

Emergency controls for risk management.
Based on PRD Section 9: Kill Switch - A hard-coded circuit breaker that 
shuts down all API connections if the realized loss exceeds 2% of total 
AUM in a single session.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Optional

from config.settings import settings


logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    """Circuit breaker states."""
    CLOSED = "CLOSED"  # Normal operation
    OPEN = "OPEN"  # Tripped - blocking operations
    HALF_OPEN = "HALF_OPEN"  # Testing if safe to resume


@dataclass
class CircuitBreaker:
    """
    Circuit breaker pattern implementation.
    
    Protects against cascading failures by temporarily blocking
    operations when failure rate exceeds threshold.
    """
    
    name: str
    failure_threshold: int = 5  # Failures before opening
    success_threshold: int = 2  # Successes to close from half-open
    timeout_seconds: int = 60  # Time in open state before half-open
    
    # State
    state: CircuitState = field(default=CircuitState.CLOSED)
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: Optional[datetime] = None
    last_state_change: datetime = field(default_factory=datetime.utcnow)
    
    def record_success(self) -> None:
        """Record a successful operation."""
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.success_threshold:
                self._close()
        elif self.state == CircuitState.CLOSED:
            self.failure_count = 0  # Reset on success
    
    def record_failure(self) -> None:
        """Record a failed operation."""
        self.last_failure_time = datetime.utcnow()
        
        if self.state == CircuitState.HALF_OPEN:
            self._open()
        elif self.state == CircuitState.CLOSED:
            self.failure_count += 1
            if self.failure_count >= self.failure_threshold:
                self._open()
    
    def can_execute(self) -> bool:
        """Check if operation can be executed."""
        if self.state == CircuitState.CLOSED:
            return True
        
        if self.state == CircuitState.OPEN:
            # Check if timeout has passed
            elapsed = (datetime.utcnow() - self.last_state_change).total_seconds()
            if elapsed >= self.timeout_seconds:
                self._half_open()
                return True
            return False
        
        if self.state == CircuitState.HALF_OPEN:
            return True
        
        return False
    
    def _open(self) -> None:
        """Open the circuit (block operations)."""
        self.state = CircuitState.OPEN
        self.last_state_change = datetime.utcnow()
        self.success_count = 0
        logger.warning(f"Circuit breaker '{self.name}' OPENED")
    
    def _close(self) -> None:
        """Close the circuit (allow operations)."""
        self.state = CircuitState.CLOSED
        self.last_state_change = datetime.utcnow()
        self.failure_count = 0
        self.success_count = 0
        logger.info(f"Circuit breaker '{self.name}' CLOSED")
    
    def _half_open(self) -> None:
        """Set circuit to half-open (testing)."""
        self.state = CircuitState.HALF_OPEN
        self.last_state_change = datetime.utcnow()
        self.success_count = 0
        logger.info(f"Circuit breaker '{self.name}' HALF-OPEN")
    
    def reset(self) -> None:
        """Manually reset the circuit breaker."""
        self._close()
        logger.info(f"Circuit breaker '{self.name}' manually reset")
    
    def get_status(self) -> dict[str, Any]:
        """Get current status."""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "last_failure": self.last_failure_time.isoformat() if self.last_failure_time else None,
            "last_state_change": self.last_state_change.isoformat()
        }


class KillSwitch:
    """
    Kill Switch for emergency shutdown.
    
    From PRD Section 9:
    A hard-coded circuit breaker that shuts down all API connections 
    if the realized loss exceeds 2% of total AUM in a single session.
    """
    
    def __init__(
        self,
        loss_threshold_percent: float = None,
        aum: float = 100000.0,
        auto_reset_hours: int = 24
    ):
        """
        Initialize Kill Switch.
        
        Args:
            loss_threshold_percent: Loss threshold to trigger (default from settings)
            aum: Assets Under Management
            auto_reset_hours: Hours until automatic reset (0 = no auto reset)
        """
        self.loss_threshold_percent = (
            loss_threshold_percent or settings.kill_switch_loss_percent
        )
        self.aum = aum
        self.auto_reset_hours = auto_reset_hours
        
        # State
        self._triggered = False
        self._trigger_time: Optional[datetime] = None
        self._trigger_reason: Optional[str] = None
        self._session_pnl: float = 0.0
        self._session_start: datetime = datetime.utcnow()
        
        # Callbacks for when kill switch triggers
        self._shutdown_callbacks: list[Callable] = []
    
    @property
    def is_triggered(self) -> bool:
        """Check if kill switch is currently triggered."""
        if not self._triggered:
            return False
        
        # Check for auto-reset
        if self.auto_reset_hours > 0 and self._trigger_time:
            elapsed = datetime.utcnow() - self._trigger_time
            if elapsed > timedelta(hours=self.auto_reset_hours):
                self._auto_reset()
                return False
        
        return True
    
    @property
    def loss_threshold(self) -> float:
        """Get absolute loss threshold."""
        return self.aum * (self.loss_threshold_percent / 100)
    
    def update_pnl(self, pnl_change: float) -> bool:
        """
        Update session P&L and check kill switch.
        
        Args:
            pnl_change: Change in P&L (positive = profit, negative = loss)
        
        Returns:
            True if kill switch triggered, False otherwise
        """
        self._session_pnl += pnl_change
        
        # Check if loss exceeds threshold
        if self._session_pnl <= -self.loss_threshold:
            self.trigger(
                f"Session loss {self._session_pnl:.2f} exceeds "
                f"threshold {-self.loss_threshold:.2f} "
                f"({self.loss_threshold_percent}% of AUM)"
            )
            return True
        
        return False
    
    def trigger(self, reason: str) -> None:
        """
        Manually trigger the kill switch.
        
        Args:
            reason: Reason for triggering
        """
        if self._triggered:
            return
        
        self._triggered = True
        self._trigger_time = datetime.utcnow()
        self._trigger_reason = reason
        
        logger.critical(f"KILL SWITCH TRIGGERED: {reason}")
        
        # Execute shutdown callbacks
        asyncio.create_task(self._execute_shutdown())
    
    async def _execute_shutdown(self) -> None:
        """Execute all registered shutdown callbacks."""
        for callback in self._shutdown_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback()
                else:
                    callback()
            except Exception as e:
                logger.error(f"Error in shutdown callback: {e}")
    
    def reset(self, new_aum: float = None) -> None:
        """
        Manually reset the kill switch.
        
        Should only be done after reviewing the situation.
        
        Args:
            new_aum: Updated AUM (if changed)
        """
        self._triggered = False
        self._trigger_time = None
        self._trigger_reason = None
        self._session_pnl = 0.0
        self._session_start = datetime.utcnow()
        
        if new_aum is not None:
            self.aum = new_aum
        
        logger.warning("Kill switch manually reset")
    
    def _auto_reset(self) -> None:
        """Automatically reset after timeout."""
        self._triggered = False
        self._trigger_reason = None
        self._session_pnl = 0.0
        self._session_start = datetime.utcnow()
        
        logger.info(f"Kill switch auto-reset after {self.auto_reset_hours} hours")
    
    def new_session(self) -> None:
        """Start a new trading session (resets session P&L)."""
        if self._triggered:
            logger.warning("Cannot start new session - kill switch is triggered")
            return
        
        self._session_pnl = 0.0
        self._session_start = datetime.utcnow()
        logger.info("New trading session started")
    
    def add_shutdown_callback(self, callback: Callable) -> None:
        """Add a callback to be called when kill switch triggers."""
        self._shutdown_callbacks.append(callback)
    
    def remove_shutdown_callback(self, callback: Callable) -> None:
        """Remove a shutdown callback."""
        if callback in self._shutdown_callbacks:
            self._shutdown_callbacks.remove(callback)
    
    def update_aum(self, new_aum: float) -> None:
        """Update the AUM value."""
        self.aum = new_aum
        logger.info(f"AUM updated to {new_aum}")
    
    def get_status(self) -> dict[str, Any]:
        """Get current kill switch status."""
        return {
            "triggered": self._triggered,
            "trigger_time": self._trigger_time.isoformat() if self._trigger_time else None,
            "trigger_reason": self._trigger_reason,
            "session_pnl": self._session_pnl,
            "session_start": self._session_start.isoformat(),
            "aum": self.aum,
            "loss_threshold_percent": self.loss_threshold_percent,
            "loss_threshold_absolute": self.loss_threshold,
            "remaining_loss_capacity": self.loss_threshold + self._session_pnl,
            "auto_reset_hours": self.auto_reset_hours
        }


# Global instances
_exchange_circuit_breaker = CircuitBreaker(name="exchange", failure_threshold=3)
_api_circuit_breaker = CircuitBreaker(name="api", failure_threshold=5)
_kill_switch = KillSwitch()


def get_exchange_circuit_breaker() -> CircuitBreaker:
    """Get the exchange circuit breaker."""
    return _exchange_circuit_breaker


def get_api_circuit_breaker() -> CircuitBreaker:
    """Get the API circuit breaker."""
    return _api_circuit_breaker


def get_kill_switch() -> KillSwitch:
    """Get the global kill switch."""
    return _kill_switch

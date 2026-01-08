"""
Audit Trail for Aegis-1

Comprehensive logging of all trading decisions for compliance and analysis.
Based on PRD Section 9: Audit Trail - Every trade must save the "Snapshot" 
of the Blackboard at the time of execution.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from uuid import UUID, uuid4

from models.signals import Signal, BlackboardSnapshot
from db.timescale import get_timescale_client


logger = logging.getLogger(__name__)


@dataclass
class AuditEntry:
    """
    Audit log entry for tracking system events.
    """
    
    id: UUID = field(default_factory=uuid4)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    event_type: str = ""
    severity: str = "INFO"  # INFO, WARNING, ERROR, CRITICAL
    source: str = ""  # Component that generated the event
    
    # Related entities
    signal_id: Optional[UUID] = None
    trade_id: Optional[UUID] = None
    symbol: Optional[str] = None
    
    # Event details
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    
    # User/system info
    user: Optional[str] = None
    system_state: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": str(self.id),
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type,
            "severity": self.severity,
            "source": self.source,
            "signal_id": str(self.signal_id) if self.signal_id else None,
            "trade_id": str(self.trade_id) if self.trade_id else None,
            "symbol": self.symbol,
            "message": self.message,
            "details": self.details,
            "user": self.user,
            "system_state": self.system_state
        }


class AuditLogger:
    """
    Audit logger for comprehensive event tracking.
    
    From PRD Section 9:
    Every trade must save the "Snapshot" of the Blackboard at the time 
    of execution. This allows for a "Post-Mortem" analysis: Why did the 
    AI think this was a good idea?
    """
    
    # Event types
    EVENT_SIGNAL_GENERATED = "SIGNAL_GENERATED"
    EVENT_TRADE_EXECUTED = "TRADE_EXECUTED"
    EVENT_TRADE_REJECTED = "TRADE_REJECTED"
    EVENT_RISK_VETO = "RISK_VETO"
    EVENT_KILL_SWITCH = "KILL_SWITCH"
    EVENT_PLUG_ISOLATED = "PLUG_ISOLATED"
    EVENT_CONFIG_CHANGED = "CONFIG_CHANGED"
    EVENT_SYSTEM_ERROR = "SYSTEM_ERROR"
    EVENT_WEIGHT_ADJUSTED = "WEIGHT_ADJUSTED"
    
    def __init__(self, persist_to_db: bool = True):
        """
        Initialize audit logger.
        
        Args:
            persist_to_db: Whether to persist entries to database
        """
        self.persist_to_db = persist_to_db
        self._entries: list[AuditEntry] = []
        self._max_memory_entries = 1000
    
    async def log(
        self,
        event_type: str,
        message: str,
        source: str = "system",
        severity: str = "INFO",
        signal_id: Optional[UUID] = None,
        trade_id: Optional[UUID] = None,
        symbol: Optional[str] = None,
        details: Optional[dict] = None,
        system_state: Optional[dict] = None
    ) -> AuditEntry:
        """
        Log an audit event.
        
        Args:
            event_type: Type of event
            message: Human-readable message
            source: Component that generated the event
            severity: Event severity (INFO, WARNING, ERROR, CRITICAL)
            signal_id: Related signal ID
            trade_id: Related trade ID
            symbol: Related symbol
            details: Additional event details
            system_state: System state at time of event
        
        Returns:
            Created AuditEntry
        """
        entry = AuditEntry(
            event_type=event_type,
            message=message,
            source=source,
            severity=severity,
            signal_id=signal_id,
            trade_id=trade_id,
            symbol=symbol,
            details=details or {},
            system_state=system_state or {}
        )
        
        # Log to standard logger
        log_level = getattr(logging, severity, logging.INFO)
        logger.log(log_level, f"[{event_type}] {message}")
        
        # Store in memory
        self._entries.append(entry)
        if len(self._entries) > self._max_memory_entries:
            self._entries = self._entries[-self._max_memory_entries:]
        
        # Persist to database if enabled
        if self.persist_to_db:
            await self._persist_entry(entry)
        
        return entry
    
    async def _persist_entry(self, entry: AuditEntry) -> None:
        """Persist audit entry to database."""
        try:
            db = get_timescale_client()
            # Store in alert_history table
            await db._pool.execute(
                """
                INSERT INTO alert_history (
                    id, timestamp, alert_type, severity, message,
                    signal_id, metadata
                ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                entry.id,
                entry.timestamp,
                entry.event_type,
                entry.severity,
                entry.message,
                entry.signal_id,
                json.dumps({
                    "source": entry.source,
                    "details": entry.details,
                    "system_state": entry.system_state
                })
            )
        except Exception as e:
            logger.error(f"Failed to persist audit entry: {e}")
    
    async def log_signal(
        self,
        signal: Signal,
        snapshot: Optional[BlackboardSnapshot] = None
    ) -> AuditEntry:
        """
        Log a signal generation event.
        
        Args:
            signal: Generated signal
            snapshot: Blackboard snapshot at generation time
        
        Returns:
            Created AuditEntry
        """
        details = {
            "action": signal.action.value,
            "confidence": signal.confidence,
            "risk_score": signal.risk_score,
            "risk_decision": signal.risk_decision.value,
            "plug_contributions": signal.plug_contributions
        }
        
        system_state = {}
        if snapshot:
            system_state = {
                "plug_states": snapshot.plug_states,
                "orchestrator_weights": snapshot.orchestrator_weights,
                "reasoning_path": snapshot.reasoning_path
            }
        
        return await self.log(
            event_type=self.EVENT_SIGNAL_GENERATED,
            message=f"Signal generated: {signal.action.value} {signal.symbol} "
                   f"(confidence: {signal.confidence:.2f})",
            source="orchestrator",
            signal_id=signal.id,
            symbol=signal.symbol,
            details=details,
            system_state=system_state
        )
    
    async def log_trade(
        self,
        trade_id: UUID,
        signal_id: UUID,
        symbol: str,
        action: str,
        quantity: float,
        price: float,
        status: str,
        details: Optional[dict] = None
    ) -> AuditEntry:
        """Log a trade execution event."""
        return await self.log(
            event_type=self.EVENT_TRADE_EXECUTED,
            message=f"Trade executed: {action} {quantity} {symbol} @ {price}",
            source="execution_gateway",
            signal_id=signal_id,
            trade_id=trade_id,
            symbol=symbol,
            details={
                "action": action,
                "quantity": quantity,
                "price": price,
                "status": status,
                **(details or {})
            }
        )
    
    async def log_risk_veto(
        self,
        signal_id: UUID,
        symbol: str,
        reason: str,
        risk_metrics: dict[str, Any]
    ) -> AuditEntry:
        """Log a risk veto event."""
        return await self.log(
            event_type=self.EVENT_RISK_VETO,
            message=f"Risk veto for {symbol}: {reason}",
            source="risk_analyst",
            severity="WARNING",
            signal_id=signal_id,
            symbol=symbol,
            details={
                "veto_reason": reason,
                "risk_metrics": risk_metrics
            }
        )
    
    async def log_kill_switch(
        self,
        reason: str,
        pnl: float,
        threshold: float
    ) -> AuditEntry:
        """Log a kill switch activation."""
        return await self.log(
            event_type=self.EVENT_KILL_SWITCH,
            message=f"KILL SWITCH ACTIVATED: {reason}",
            source="kill_switch",
            severity="CRITICAL",
            details={
                "session_pnl": pnl,
                "loss_threshold": threshold,
                "reason": reason
            }
        )
    
    async def log_plug_isolation(
        self,
        plug_id: str,
        reason: str,
        last_signal: Optional[dict] = None
    ) -> AuditEntry:
        """Log a plug isolation event."""
        return await self.log(
            event_type=self.EVENT_PLUG_ISOLATED,
            message=f"Plug isolated: {plug_id} - {reason}",
            source=plug_id,
            severity="WARNING",
            details={
                "plug_id": plug_id,
                "isolation_reason": reason,
                "last_signal": last_signal
            }
        )
    
    async def log_weight_adjustment(
        self,
        plug_id: str,
        old_weight: float,
        new_weight: float,
        reason: str
    ) -> AuditEntry:
        """Log a plug weight adjustment."""
        return await self.log(
            event_type=self.EVENT_WEIGHT_ADJUSTED,
            message=f"Weight adjusted for {plug_id}: {old_weight:.2f} -> {new_weight:.2f}",
            source="dynamic_weighting",
            details={
                "plug_id": plug_id,
                "old_weight": old_weight,
                "new_weight": new_weight,
                "reason": reason
            }
        )
    
    def get_recent_entries(
        self,
        count: int = 100,
        event_type: Optional[str] = None,
        severity: Optional[str] = None
    ) -> list[AuditEntry]:
        """
        Get recent audit entries.
        
        Args:
            count: Number of entries to return
            event_type: Filter by event type
            severity: Filter by severity
        
        Returns:
            List of matching entries
        """
        entries = self._entries.copy()
        
        if event_type:
            entries = [e for e in entries if e.event_type == event_type]
        
        if severity:
            entries = [e for e in entries if e.severity == severity]
        
        return entries[-count:]


# Global audit logger
_audit_logger = AuditLogger()


def get_audit_logger() -> AuditLogger:
    """Get the global audit logger."""
    return _audit_logger


async def audit_trade(
    trade_id: UUID,
    signal_id: UUID,
    symbol: str,
    action: str,
    quantity: float,
    price: float,
    status: str,
    **kwargs
) -> AuditEntry:
    """Convenience function to audit a trade."""
    return await _audit_logger.log_trade(
        trade_id=trade_id,
        signal_id=signal_id,
        symbol=symbol,
        action=action,
        quantity=quantity,
        price=price,
        status=status,
        details=kwargs
    )


async def create_audit_entry(
    event_type: str,
    message: str,
    **kwargs
) -> AuditEntry:
    """Convenience function to create an audit entry."""
    return await _audit_logger.log(
        event_type=event_type,
        message=message,
        **kwargs
    )

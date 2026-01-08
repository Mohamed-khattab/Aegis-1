"""
Signal Models for Aegis-1

Defines the standardized signal objects used throughout the system.
Based on PRD Section 5 and Section 7 specifications.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional
from uuid import UUID, uuid4


class SignalAction(str, Enum):
    """Possible signal actions."""
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class MarketRegime(str, Enum):
    """Market regime classifications."""
    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGING = "RANGING"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"


class RiskDecision(str, Enum):
    """Risk analyst decisions."""
    EXECUTE = "EXECUTE"
    ABORT = "ABORT"


@dataclass
class PlugSignal:
    """
    Signal output from an individual plug.
    
    All plugs must output values in the strict range of [-1.0, 1.0].
    Any value outside this range triggers plug isolation (AC: Signal Normalization).
    """
    
    origin: str  # Plug identifier
    direction: float  # -1.0 (strong sell) to 1.0 (strong buy)
    confidence: float  # 0.0 to 1.0
    logic: str  # Reasoning for audit trail
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self) -> None:
        """Validate signal values are in allowed ranges."""
        if not -1.0 <= self.direction <= 1.0:
            raise ValueError(
                f"Direction must be in [-1.0, 1.0], got {self.direction}"
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"Confidence must be in [0.0, 1.0], got {self.confidence}"
            )
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "origin": self.origin,
            "direction": self.direction,
            "confidence": self.confidence,
            "logic": self.logic,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }
    
    @classmethod
    def null_signal(cls, origin: str, reason: str = "No signal") -> "PlugSignal":
        """Create a null/neutral signal (used for fail-safe scenarios)."""
        return cls(
            origin=origin,
            direction=0.0,
            confidence=0.0,
            logic=reason,
        )


@dataclass
class Signal:
    """
    Standardized Signal Object from PRD Section 5.
    
    This is the final output from the Core Orchestrator,
    sent to all output plugs (Webhook, Email, UI, Database, MQ).
    """
    
    id: UUID = field(default_factory=uuid4)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    action: SignalAction = SignalAction.HOLD
    symbol: str = ""
    confidence: float = 0.0  # 0.0 to 1.0
    position_size: float = 0.0  # Calculated position size
    reasoning: str = ""  # Aggregated reasoning from all plugs
    risk_score: float = 0.0  # 0.0 to 1.0
    expiry: Optional[datetime] = None  # Signal validity window
    
    # Source tracking
    origin: str = "orchestrator"  # Source plug or "orchestrator" for consensus
    
    # Detailed breakdown
    plug_contributions: dict[str, float] = field(default_factory=dict)
    plug_signals: list[PlugSignal] = field(default_factory=list)
    
    # Risk analysis
    risk_decision: RiskDecision = RiskDecision.EXECUTE
    var_estimate: Optional[float] = None  # Value at Risk
    max_drawdown: Optional[float] = None
    
    # Market context
    market_regime: Optional[MarketRegime] = None
    
    # Metadata for audit
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self) -> None:
        """Validate signal values."""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"Confidence must be in [0.0, 1.0], got {self.confidence}"
            )
        if not 0.0 <= self.risk_score <= 1.0:
            raise ValueError(
                f"Risk score must be in [0.0, 1.0], got {self.risk_score}"
            )
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": str(self.id),
            "timestamp": self.timestamp.isoformat(),
            "action": self.action.value,
            "symbol": self.symbol,
            "confidence": self.confidence,
            "position_size": self.position_size,
            "reasoning": self.reasoning,
            "risk_score": self.risk_score,
            "expiry": self.expiry.isoformat() if self.expiry else None,
            "origin": self.origin,
            "plug_contributions": self.plug_contributions,
            "risk_decision": self.risk_decision.value,
            "var_estimate": self.var_estimate,
            "max_drawdown": self.max_drawdown,
            "market_regime": self.market_regime.value if self.market_regime else None,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Signal":
        """Create Signal from dictionary."""
        return cls(
            id=UUID(data["id"]) if "id" in data else uuid4(),
            timestamp=datetime.fromisoformat(data["timestamp"]) if "timestamp" in data else datetime.utcnow(),
            action=SignalAction(data.get("action", "HOLD")),
            symbol=data.get("symbol", ""),
            confidence=data.get("confidence", 0.0),
            position_size=data.get("position_size", 0.0),
            reasoning=data.get("reasoning", ""),
            risk_score=data.get("risk_score", 0.0),
            expiry=datetime.fromisoformat(data["expiry"]) if data.get("expiry") else None,
            origin=data.get("origin", "orchestrator"),
            plug_contributions=data.get("plug_contributions", {}),
            risk_decision=RiskDecision(data.get("risk_decision", "EXECUTE")),
            var_estimate=data.get("var_estimate"),
            max_drawdown=data.get("max_drawdown"),
            market_regime=MarketRegime(data["market_regime"]) if data.get("market_regime") else None,
            metadata=data.get("metadata", {}),
        )
    
    @property
    def is_critical(self) -> bool:
        """Check if signal is high-priority (confidence > 0.8)."""
        return self.confidence > 0.8
    
    @property
    def is_actionable(self) -> bool:
        """Check if signal should trigger a trade."""
        return (
            self.action != SignalAction.HOLD
            and self.risk_decision == RiskDecision.EXECUTE
            and self.confidence > 0.5
        )


@dataclass
class BlackboardSnapshot:
    """
    Snapshot of the blackboard state at trade execution time.
    
    Used for audit trail and post-mortem analysis (PRD Section 9).
    """
    
    id: UUID = field(default_factory=uuid4)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    signal: Signal = field(default_factory=Signal)
    plug_states: dict[str, dict[str, Any]] = field(default_factory=dict)
    market_data_snapshot: dict[str, Any] = field(default_factory=dict)
    orchestrator_weights: dict[str, float] = field(default_factory=dict)
    reasoning_path: str = ""
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "id": str(self.id),
            "timestamp": self.timestamp.isoformat(),
            "signal": self.signal.to_dict(),
            "plug_states": self.plug_states,
            "market_data_snapshot": self.market_data_snapshot,
            "orchestrator_weights": self.orchestrator_weights,
            "reasoning_path": self.reasoning_path,
        }

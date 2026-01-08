"""
Dynamic Weighting System for Aegis-1

Automatically adjusts plug weights based on performance.
Based on PRD Section 8.A: Dynamic Weighting (The "Ego" Filter).
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional
from collections import deque

from config.settings import settings


logger = logging.getLogger(__name__)


@dataclass
class PlugPerformanceRecord:
    """Record of a plug's prediction and outcome."""
    timestamp: datetime
    plug_id: str
    predicted_direction: float  # -1 to 1
    actual_direction: float  # -1 to 1 (based on price movement)
    confidence: float
    was_correct: bool
    weight_at_time: float


@dataclass
class PlugPerformanceLedger:
    """
    Performance ledger for a single plug.
    
    Tracks predictions and outcomes to calculate accuracy.
    """
    plug_id: str
    records: deque = field(default_factory=lambda: deque(maxlen=100))
    total_predictions: int = 0
    correct_predictions: int = 0
    current_weight: float = 1.0
    last_updated: Optional[datetime] = None
    
    # Rolling statistics
    rolling_accuracy: float = 0.5
    rolling_confidence: float = 0.5
    correlation: float = 0.0  # Direction correlation with price
    
    def add_record(self, record: PlugPerformanceRecord) -> None:
        """Add a new performance record."""
        self.records.append(record)
        self.total_predictions += 1
        if record.was_correct:
            self.correct_predictions += 1
        self.last_updated = datetime.utcnow()
        self._update_statistics()
    
    def _update_statistics(self) -> None:
        """Update rolling statistics from records."""
        if not self.records:
            return
        
        recent = list(self.records)[-20:]  # Last 20 predictions
        
        if recent:
            # Rolling accuracy
            correct = sum(1 for r in recent if r.was_correct)
            self.rolling_accuracy = correct / len(recent)
            
            # Rolling confidence
            self.rolling_confidence = sum(r.confidence for r in recent) / len(recent)
            
            # Direction correlation (simplified)
            if len(recent) >= 5:
                predicted = [r.predicted_direction for r in recent]
                actual = [r.actual_direction for r in recent]
                self.correlation = self._calculate_correlation(predicted, actual)
    
    def _calculate_correlation(
        self,
        predicted: list[float],
        actual: list[float]
    ) -> float:
        """Calculate Pearson correlation coefficient."""
        n = len(predicted)
        if n < 2:
            return 0.0
        
        mean_p = sum(predicted) / n
        mean_a = sum(actual) / n
        
        numerator = sum(
            (p - mean_p) * (a - mean_a)
            for p, a in zip(predicted, actual)
        )
        
        std_p = (sum((p - mean_p) ** 2 for p in predicted) / n) ** 0.5
        std_a = (sum((a - mean_a) ** 2 for a in actual) / n) ** 0.5
        
        if std_p == 0 or std_a == 0:
            return 0.0
        
        return numerator / (n * std_p * std_a)
    
    @property
    def overall_accuracy(self) -> float:
        """Get overall accuracy."""
        if self.total_predictions == 0:
            return 0.5
        return self.correct_predictions / self.total_predictions
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "plug_id": self.plug_id,
            "total_predictions": self.total_predictions,
            "correct_predictions": self.correct_predictions,
            "overall_accuracy": self.overall_accuracy,
            "rolling_accuracy": self.rolling_accuracy,
            "rolling_confidence": self.rolling_confidence,
            "correlation": self.correlation,
            "current_weight": self.current_weight,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None
        }


class DynamicWeighting:
    """
    Dynamic Weighting system for plug performance management.
    
    From PRD Section 8.A:
    The Orchestrator maintains a Plug Performance Ledger. If the "News Plug"
    sentiment has been negatively correlated with price for the last 10 trades,
    its weight in the final decision formula is automatically decayed.
    """
    
    # Weight bounds
    MIN_WEIGHT = 0.1
    MAX_WEIGHT = 2.0
    DEFAULT_WEIGHT = 1.0
    
    # Decay/boost parameters
    DECAY_RATE = 0.1  # How much to decay on poor performance
    BOOST_RATE = 0.05  # How much to boost on good performance
    CORRELATION_THRESHOLD = -0.3  # Negative correlation trigger
    
    def __init__(
        self,
        lookback_trades: int = 10,
        min_samples_for_adjustment: int = 5
    ):
        """
        Initialize Dynamic Weighting system.
        
        Args:
            lookback_trades: Number of trades for correlation calculation
            min_samples_for_adjustment: Minimum samples before adjusting weights
        """
        self.lookback_trades = lookback_trades
        self.min_samples_for_adjustment = min_samples_for_adjustment
        
        # Ledger for each plug
        self._ledgers: dict[str, PlugPerformanceLedger] = {}
    
    def get_ledger(self, plug_id: str) -> PlugPerformanceLedger:
        """Get or create ledger for a plug."""
        if plug_id not in self._ledgers:
            self._ledgers[plug_id] = PlugPerformanceLedger(plug_id=plug_id)
        return self._ledgers[plug_id]
    
    def record_prediction(
        self,
        plug_id: str,
        predicted_direction: float,
        confidence: float,
        current_weight: float
    ) -> None:
        """
        Record a plug's prediction (before outcome is known).
        
        Args:
            plug_id: Plug identifier
            predicted_direction: Predicted direction (-1 to 1)
            confidence: Prediction confidence
            current_weight: Weight at time of prediction
        """
        ledger = self.get_ledger(plug_id)
        
        # Create partial record (actual_direction will be updated later)
        record = PlugPerformanceRecord(
            timestamp=datetime.utcnow(),
            plug_id=plug_id,
            predicted_direction=predicted_direction,
            actual_direction=0.0,  # TBD
            confidence=confidence,
            was_correct=False,  # TBD
            weight_at_time=current_weight
        )
        
        # Store temporarily
        if not hasattr(self, '_pending_records'):
            self._pending_records = {}
        self._pending_records[plug_id] = record
    
    def record_outcome(
        self,
        plug_id: str,
        actual_direction: float
    ) -> None:
        """
        Record the actual outcome for a prediction.
        
        Args:
            plug_id: Plug identifier
            actual_direction: Actual price direction (-1 to 1)
        """
        if not hasattr(self, '_pending_records'):
            return
        
        record = self._pending_records.get(plug_id)
        if record is None:
            return
        
        # Update record with actual outcome
        record.actual_direction = actual_direction
        
        # Determine if prediction was correct
        # Correct if signs match (or both near zero)
        predicted = record.predicted_direction
        if (predicted > 0.1 and actual_direction > 0) or \
           (predicted < -0.1 and actual_direction < 0) or \
           (abs(predicted) <= 0.1 and abs(actual_direction) < 0.05):
            record.was_correct = True
        else:
            record.was_correct = False
        
        # Add to ledger
        ledger = self.get_ledger(plug_id)
        ledger.add_record(record)
        
        # Clean up pending
        del self._pending_records[plug_id]
        
        # Recalculate weight
        self._update_weight(plug_id)
    
    def _update_weight(self, plug_id: str) -> None:
        """
        Update plug weight based on performance.
        
        Implements the "Ego Filter" from PRD.
        """
        ledger = self.get_ledger(plug_id)
        
        # Need minimum samples
        if len(ledger.records) < self.min_samples_for_adjustment:
            return
        
        old_weight = ledger.current_weight
        new_weight = old_weight
        
        # Check for negative correlation (PRD requirement)
        if ledger.correlation < self.CORRELATION_THRESHOLD:
            # Decay weight due to negative correlation
            decay = self.DECAY_RATE * abs(ledger.correlation)
            new_weight = old_weight * (1 - decay)
            logger.warning(
                f"Plug {plug_id}: Negative correlation ({ledger.correlation:.2f}), "
                f"decaying weight {old_weight:.2f} -> {new_weight:.2f}"
            )
        
        # Also adjust based on rolling accuracy
        if ledger.rolling_accuracy < 0.4:
            # Poor accuracy - decay
            new_weight *= (1 - self.DECAY_RATE)
            logger.info(
                f"Plug {plug_id}: Low accuracy ({ledger.rolling_accuracy:.1%}), "
                f"decaying weight"
            )
        elif ledger.rolling_accuracy > 0.6:
            # Good accuracy - slight boost
            new_weight *= (1 + self.BOOST_RATE)
            logger.info(
                f"Plug {plug_id}: High accuracy ({ledger.rolling_accuracy:.1%}), "
                f"boosting weight"
            )
        
        # Clamp weight
        new_weight = max(self.MIN_WEIGHT, min(self.MAX_WEIGHT, new_weight))
        
        if new_weight != old_weight:
            ledger.current_weight = new_weight
            logger.info(
                f"Plug {plug_id}: Weight adjusted {old_weight:.2f} -> {new_weight:.2f}"
            )
    
    def get_weight(self, plug_id: str) -> float:
        """Get current weight for a plug."""
        ledger = self.get_ledger(plug_id)
        return ledger.current_weight
    
    def get_all_weights(self) -> dict[str, float]:
        """Get weights for all plugs."""
        return {
            plug_id: ledger.current_weight
            for plug_id, ledger in self._ledgers.items()
        }
    
    def set_weight(self, plug_id: str, weight: float) -> None:
        """Manually set weight for a plug."""
        weight = max(self.MIN_WEIGHT, min(self.MAX_WEIGHT, weight))
        ledger = self.get_ledger(plug_id)
        ledger.current_weight = weight
    
    def reset_weight(self, plug_id: str) -> None:
        """Reset plug weight to default."""
        ledger = self.get_ledger(plug_id)
        ledger.current_weight = self.DEFAULT_WEIGHT
    
    def reset_all_weights(self) -> None:
        """Reset all plug weights to default."""
        for ledger in self._ledgers.values():
            ledger.current_weight = self.DEFAULT_WEIGHT
    
    def get_performance_summary(self) -> dict[str, Any]:
        """Get performance summary for all plugs."""
        return {
            plug_id: ledger.to_dict()
            for plug_id, ledger in self._ledgers.items()
        }
    
    def get_plug_ranking(self) -> list[tuple[str, float]]:
        """
        Get plugs ranked by performance.
        
        Returns:
            List of (plug_id, score) tuples, sorted by score descending
        """
        rankings = []
        
        for plug_id, ledger in self._ledgers.items():
            # Score combines accuracy and correlation
            score = (ledger.rolling_accuracy * 0.6 + 
                    (ledger.correlation + 1) / 2 * 0.4)
            rankings.append((plug_id, score))
        
        return sorted(rankings, key=lambda x: x[1], reverse=True)
    
    def should_isolate_plug(self, plug_id: str) -> bool:
        """
        Determine if a plug should be isolated due to poor performance.
        
        Returns:
            True if plug should be isolated
        """
        ledger = self.get_ledger(plug_id)
        
        # Isolate if:
        # - Strong negative correlation
        # - Very low accuracy
        # - Weight has decayed to minimum
        return (
            ledger.correlation < -0.5 or
            ledger.rolling_accuracy < 0.3 or
            ledger.current_weight <= self.MIN_WEIGHT
        )

"""
Risk Analyst Plug for Aegis-1

Risk vetting, position sizing, and veto capability.
Based on PRD Section 3 - Plug 04: Risk Analyst (The Veto).
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

import numpy as np

from plugs.base import BasePlug, PlugStatus
from models.signals import PlugSignal, RiskDecision
from models.market_data import MarketDataBundle
from config.settings import settings


logger = logging.getLogger(__name__)


class RiskAnalystPlug(BasePlug):
    """
    Risk Analyst plug with veto power.
    
    From PRD:
    - Requirement: Mandatory check against Portfolio VaR (Value at Risk) 
      and Max Drawdown limits
    - Veto Power: This plug has a binary EXECUTE/ABORT capability that 
      overrides all other plugs
    
    From AC-04:
    - If the Risk Analyst Plug returns an ABORT signal, the Execution 
      Gateway must hardware-lock the order regardless of other plug signals
    """
    
    def __init__(
        self,
        plug_id: str = "risk_analyst",
        max_drawdown_pct: float = None,
        max_position_size_pct: float = 10.0,
        max_var_pct: float = 2.0,
        var_confidence: float = 0.95,
        lookback_days: int = 30
    ):
        """
        Initialize Risk Analyst plug.
        
        Args:
            plug_id: Unique identifier
            max_drawdown_pct: Maximum drawdown percentage
            max_position_size_pct: Maximum position size as % of portfolio
            max_var_pct: Maximum VaR as % of portfolio
            var_confidence: VaR confidence level
            lookback_days: Days of history for risk calculations
        """
        super().__init__(plug_id)
        
        self.max_drawdown_pct = max_drawdown_pct or settings.max_drawdown_percent
        self.max_position_size_pct = max_position_size_pct
        self.max_var_pct = max_var_pct
        self.var_confidence = var_confidence
        self.lookback_days = lookback_days
        
        # Portfolio state tracking
        self._portfolio_value: float = 100000.0  # Default starting value
        self._peak_value: float = 100000.0
        self._positions: dict[str, dict] = {}
        self._trade_history: list[dict] = []
        self._session_pnl: float = 0.0
        self._session_start: datetime = datetime.utcnow()
    
    async def initialize(self) -> None:
        """Initialize Risk Analyst."""
        self._session_start = datetime.utcnow()
        self._session_pnl = 0.0
        self.status = PlugStatus.ACTIVE
        logger.info("Risk Analyst plug initialized")
    
    async def shutdown(self) -> None:
        """Shutdown plug."""
        self.status = PlugStatus.INACTIVE
        logger.info("Risk Analyst plug shutdown")
    
    async def generate_signal(
        self,
        market_data: MarketDataBundle
    ) -> PlugSignal:
        """
        Perform risk analysis and determine EXECUTE/ABORT decision.
        
        Args:
            market_data: Market data bundle
        
        Returns:
            PlugSignal with risk assessment and EXECUTE/ABORT decision
        """
        symbol = market_data.symbol
        
        # Calculate risk metrics
        risk_metrics = self._calculate_risk_metrics(market_data)
        
        # Check all risk conditions
        risk_checks = self._perform_risk_checks(risk_metrics, symbol)
        
        # Determine decision (any failure = ABORT)
        veto_reasons = [
            check["reason"] for check in risk_checks.values()
            if not check["passed"]
        ]
        
        should_abort = len(veto_reasons) > 0
        decision = RiskDecision.ABORT if should_abort else RiskDecision.EXECUTE
        
        # Risk score (higher = more risk)
        risk_score = self._calculate_risk_score(risk_metrics)
        
        # Direction is neutral for risk plug (it doesn't suggest direction)
        # Confidence reflects certainty in risk assessment
        confidence = 0.9 if all(v["passed"] for v in risk_checks.values()) else 0.95
        
        # Calculate suggested position size
        position_size = self._calculate_position_size(risk_metrics, symbol)
        
        # Build reasoning
        reasoning = self._build_reasoning(
            risk_metrics, risk_checks, decision, position_size
        )
        
        return PlugSignal(
            origin=self.plug_id,
            direction=0.0,  # Risk plug is direction-neutral
            confidence=confidence,
            logic=reasoning,
            metadata={
                "decision": decision.value,
                "risk_score": risk_score,
                "risk_metrics": risk_metrics,
                "risk_checks": {k: v["passed"] for k, v in risk_checks.items()},
                "veto_reasons": veto_reasons,
                "suggested_position_size": position_size,
                "var_estimate": risk_metrics.get("var"),
                "current_drawdown": risk_metrics.get("drawdown")
            }
        )
    
    def _calculate_risk_metrics(
        self,
        market_data: MarketDataBundle
    ) -> dict[str, float]:
        """Calculate comprehensive risk metrics."""
        metrics = {}
        
        ohlcv = market_data.ohlcv
        if ohlcv and len(ohlcv) >= 5:
            # Convert to returns
            closes = [o.close for o in sorted(ohlcv, key=lambda x: x.timestamp)]
            returns = [
                (closes[i] - closes[i-1]) / closes[i-1]
                for i in range(1, len(closes))
            ]
            
            if returns:
                # Volatility
                metrics["volatility"] = np.std(returns) * np.sqrt(252)
                
                # VaR (Historical simulation)
                metrics["var"] = self._calculate_var(returns)
                
                # Maximum drawdown in sample
                metrics["sample_drawdown"] = self._calculate_max_drawdown(closes)
        
        # Portfolio metrics
        metrics["drawdown"] = self._calculate_portfolio_drawdown()
        metrics["session_loss"] = self._session_pnl / self._portfolio_value if self._portfolio_value > 0 else 0
        
        # Concentration risk
        metrics["concentration"] = self._calculate_concentration_risk(market_data.symbol)
        
        return metrics
    
    def _calculate_var(self, returns: list[float]) -> float:
        """
        Calculate Value at Risk using historical simulation.
        
        Args:
            returns: List of historical returns
        
        Returns:
            VaR as a positive percentage (loss)
        """
        if not returns:
            return 0.0
        
        # Sort returns (losses are negative)
        sorted_returns = sorted(returns)
        
        # Find the return at the confidence percentile
        index = int((1 - self.var_confidence) * len(sorted_returns))
        var_return = sorted_returns[index]
        
        # Return absolute value (VaR is expressed as positive loss)
        return abs(var_return) if var_return < 0 else 0.0
    
    def _calculate_max_drawdown(self, prices: list[float]) -> float:
        """Calculate maximum drawdown from price series."""
        if not prices:
            return 0.0
        
        peak = prices[0]
        max_dd = 0.0
        
        for price in prices:
            if price > peak:
                peak = price
            dd = (peak - price) / peak
            max_dd = max(max_dd, dd)
        
        return max_dd
    
    def _calculate_portfolio_drawdown(self) -> float:
        """Calculate current portfolio drawdown from peak."""
        if self._peak_value == 0:
            return 0.0
        return (self._peak_value - self._portfolio_value) / self._peak_value
    
    def _calculate_concentration_risk(self, symbol: str) -> float:
        """
        Calculate concentration risk for a symbol.
        
        Returns percentage of portfolio in this symbol.
        """
        position = self._positions.get(symbol, {})
        position_value = position.get("value", 0)
        
        if self._portfolio_value == 0:
            return 0.0
        
        return position_value / self._portfolio_value
    
    def _perform_risk_checks(
        self,
        metrics: dict[str, float],
        symbol: str
    ) -> dict[str, dict[str, Any]]:
        """
        Perform all risk checks.
        
        Each check returns dict with 'passed' and 'reason'.
        """
        checks = {}
        
        # Check 1: Maximum Drawdown
        current_dd = metrics.get("drawdown", 0)
        max_dd_decimal = self.max_drawdown_pct / 100
        checks["max_drawdown"] = {
            "passed": current_dd < max_dd_decimal,
            "reason": f"Drawdown {current_dd*100:.1f}% exceeds limit {self.max_drawdown_pct}%"
                if current_dd >= max_dd_decimal else None,
            "value": current_dd,
            "limit": max_dd_decimal
        }
        
        # Check 2: Session Loss (Kill Switch)
        session_loss = abs(metrics.get("session_loss", 0))
        kill_switch_decimal = settings.kill_switch_loss_percent / 100
        checks["kill_switch"] = {
            "passed": session_loss < kill_switch_decimal,
            "reason": f"Session loss {session_loss*100:.1f}% exceeds kill switch {settings.kill_switch_loss_percent}%"
                if session_loss >= kill_switch_decimal else None,
            "value": session_loss,
            "limit": kill_switch_decimal
        }
        
        # Check 3: VaR Limit
        var = metrics.get("var", 0)
        max_var_decimal = self.max_var_pct / 100
        checks["var_limit"] = {
            "passed": var < max_var_decimal,
            "reason": f"VaR {var*100:.1f}% exceeds limit {self.max_var_pct}%"
                if var >= max_var_decimal else None,
            "value": var,
            "limit": max_var_decimal
        }
        
        # Check 4: Concentration Risk
        concentration = metrics.get("concentration", 0)
        max_concentration = self.max_position_size_pct / 100
        checks["concentration"] = {
            "passed": concentration < max_concentration,
            "reason": f"Position concentration {concentration*100:.1f}% exceeds limit {self.max_position_size_pct}%"
                if concentration >= max_concentration else None,
            "value": concentration,
            "limit": max_concentration
        }
        
        # Check 5: Volatility regime
        volatility = metrics.get("volatility", 0)
        vol_limit = 0.5  # 50% annualized volatility limit
        checks["volatility_regime"] = {
            "passed": volatility < vol_limit,
            "reason": f"Volatility {volatility*100:.0f}% indicates extreme market conditions"
                if volatility >= vol_limit else None,
            "value": volatility,
            "limit": vol_limit
        }
        
        return checks
    
    def _calculate_risk_score(self, metrics: dict[str, float]) -> float:
        """
        Calculate overall risk score 0-1 (higher = more risk).
        """
        scores = []
        
        # Drawdown contribution
        dd = metrics.get("drawdown", 0)
        scores.append(min(1.0, dd / (self.max_drawdown_pct / 100)))
        
        # VaR contribution
        var = metrics.get("var", 0)
        scores.append(min(1.0, var / (self.max_var_pct / 100)))
        
        # Volatility contribution
        vol = metrics.get("volatility", 0)
        scores.append(min(1.0, vol / 0.5))
        
        # Concentration contribution
        conc = metrics.get("concentration", 0)
        scores.append(min(1.0, conc / (self.max_position_size_pct / 100)))
        
        # Weighted average
        return sum(scores) / len(scores) if scores else 0.0
    
    def _calculate_position_size(
        self,
        metrics: dict[str, float],
        symbol: str
    ) -> float:
        """
        Calculate recommended position size based on risk metrics.
        
        Uses volatility-based position sizing.
        """
        volatility = metrics.get("volatility", 0.2)
        
        if volatility == 0:
            volatility = 0.2  # Default assumption
        
        # Target risk per trade (1% of portfolio)
        target_risk = 0.01
        
        # Position size inversely proportional to volatility
        base_size = target_risk / volatility
        
        # Cap at maximum position size
        max_size = self.max_position_size_pct / 100
        position_size = min(base_size, max_size)
        
        # Reduce further if we're in drawdown
        drawdown = metrics.get("drawdown", 0)
        if drawdown > 0:
            reduction_factor = 1 - (drawdown / (self.max_drawdown_pct / 100))
            position_size *= max(0.5, reduction_factor)
        
        return position_size
    
    def _build_reasoning(
        self,
        metrics: dict[str, float],
        checks: dict[str, dict],
        decision: RiskDecision,
        position_size: float
    ) -> str:
        """Build human-readable reasoning string."""
        failed_checks = [
            name for name, check in checks.items()
            if not check["passed"]
        ]
        
        if decision == RiskDecision.ABORT:
            reasons = "; ".join(
                checks[name]["reason"] for name in failed_checks
            )
            return f"RISK VETO - Trade blocked: {reasons}"
        
        risk_score = self._calculate_risk_score(metrics)
        risk_level = "low" if risk_score < 0.3 else "moderate" if risk_score < 0.6 else "high"
        
        return (
            f"Risk analysis: {risk_level} risk (score: {risk_score:.2f}). "
            f"VaR: {metrics.get('var', 0)*100:.1f}%, "
            f"Drawdown: {metrics.get('drawdown', 0)*100:.1f}%. "
            f"Suggested position: {position_size*100:.1f}% of portfolio"
        )
    
    # ===================
    # Portfolio Management
    # ===================
    
    def update_portfolio_value(self, value: float) -> None:
        """Update current portfolio value."""
        self._portfolio_value = value
        self._peak_value = max(self._peak_value, value)
    
    def record_trade(
        self,
        symbol: str,
        action: str,
        quantity: float,
        price: float,
        pnl: float = 0
    ) -> None:
        """Record a trade execution."""
        self._trade_history.append({
            "timestamp": datetime.utcnow(),
            "symbol": symbol,
            "action": action,
            "quantity": quantity,
            "price": price,
            "pnl": pnl
        })
        
        # Update session P&L
        self._session_pnl += pnl
        
        # Update positions
        if symbol not in self._positions:
            self._positions[symbol] = {"quantity": 0, "value": 0}
        
        if action == "BUY":
            self._positions[symbol]["quantity"] += quantity
            self._positions[symbol]["value"] += quantity * price
        elif action == "SELL":
            self._positions[symbol]["quantity"] -= quantity
            self._positions[symbol]["value"] -= quantity * price
    
    def reset_session(self) -> None:
        """Reset session tracking (e.g., at start of trading day)."""
        self._session_start = datetime.utcnow()
        self._session_pnl = 0.0
        logger.info("Risk session reset")
    
    def get_risk_summary(self) -> dict[str, Any]:
        """Get current risk summary for dashboard."""
        return {
            "portfolio_value": self._portfolio_value,
            "peak_value": self._peak_value,
            "current_drawdown": self._calculate_portfolio_drawdown(),
            "max_drawdown_limit": self.max_drawdown_pct,
            "session_pnl": self._session_pnl,
            "session_pnl_percent": self._session_pnl / self._portfolio_value * 100 if self._portfolio_value > 0 else 0,
            "kill_switch_limit": settings.kill_switch_loss_percent,
            "positions": self._positions,
            "trade_count": len(self._trade_history)
        }

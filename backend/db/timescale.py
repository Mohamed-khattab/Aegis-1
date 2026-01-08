"""
TimescaleDB Client for Aegis-1

Handles time-series data storage for signals, trades, and audit logs.
"""

import logging
from datetime import datetime
from typing import Any, Optional
from functools import lru_cache
from uuid import UUID

import asyncpg
from asyncpg import Pool

from config.settings import settings
from models.signals import Signal, SignalAction, RiskDecision, BlackboardSnapshot


logger = logging.getLogger(__name__)


class TimescaleClient:
    """
    Async TimescaleDB client for Aegis-1.
    
    Used for:
    - Signal persistence (hypertable)
    - Trade logging with outcomes
    - Audit snapshots for post-mortem analysis
    - Performance metrics aggregation
    """
    
    def __init__(self, url: str | None = None):
        """
        Initialize TimescaleDB client.
        
        Args:
            url: Database connection URL (defaults to settings)
        """
        self.url = url or settings.database_url
        self._pool: Optional[Pool] = None
    
    async def connect(self) -> None:
        """Establish connection pool to TimescaleDB."""
        try:
            self._pool = await asyncpg.create_pool(
                self.url,
                min_size=5,
                max_size=20,
                command_timeout=60
            )
            logger.info("Connected to TimescaleDB")
            
        except Exception as e:
            logger.error(f"Failed to connect to TimescaleDB: {e}")
            raise
    
    async def disconnect(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            logger.info("Disconnected from TimescaleDB")
    
    async def health_check(self) -> bool:
        """Check if database connection is healthy."""
        try:
            if self._pool:
                async with self._pool.acquire() as conn:
                    await conn.execute("SELECT 1")
                    return True
        except Exception:
            pass
        return False
    
    # ===================
    # Signal Operations
    # ===================
    
    async def insert_signal(self, signal: Signal) -> UUID:
        """
        Insert a signal into the database.
        
        Args:
            signal: Signal to store
        
        Returns:
            UUID of the inserted signal
        """
        if not self._pool:
            raise RuntimeError("Database not connected")
        
        query = """
            INSERT INTO signals (
                id, timestamp, action, symbol, confidence, position_size,
                reasoning, risk_score, expiry, origin, plug_contributions,
                risk_decision, var_estimate, max_drawdown, market_regime, metadata
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16
            )
            RETURNING id
        """
        
        async with self._pool.acquire() as conn:
            result = await conn.fetchval(
                query,
                signal.id,
                signal.timestamp,
                signal.action.value,
                signal.symbol,
                signal.confidence,
                signal.position_size,
                signal.reasoning,
                signal.risk_score,
                signal.expiry,
                signal.origin,
                signal.plug_contributions,
                signal.risk_decision.value,
                signal.var_estimate,
                signal.max_drawdown,
                signal.market_regime.value if signal.market_regime else None,
                signal.metadata
            )
            
            return result
    
    async def get_signal(self, signal_id: UUID) -> Optional[Signal]:
        """Get a signal by ID."""
        if not self._pool:
            raise RuntimeError("Database not connected")
        
        query = """
            SELECT * FROM signals WHERE id = $1
        """
        
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, signal_id)
            if row:
                return self._row_to_signal(row)
            return None
    
    async def get_signals(
        self,
        symbol: Optional[str] = None,
        action: Optional[SignalAction] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        min_confidence: Optional[float] = None,
        limit: int = 100
    ) -> list[Signal]:
        """
        Query signals with filters.
        
        Args:
            symbol: Filter by symbol
            action: Filter by action type
            start_time: Filter by start time
            end_time: Filter by end time
            min_confidence: Filter by minimum confidence
            limit: Maximum results to return
        
        Returns:
            List of matching signals
        """
        if not self._pool:
            raise RuntimeError("Database not connected")
        
        conditions = []
        params = []
        param_idx = 1
        
        if symbol:
            conditions.append(f"symbol = ${param_idx}")
            params.append(symbol)
            param_idx += 1
        
        if action:
            conditions.append(f"action = ${param_idx}")
            params.append(action.value)
            param_idx += 1
        
        if start_time:
            conditions.append(f"timestamp >= ${param_idx}")
            params.append(start_time)
            param_idx += 1
        
        if end_time:
            conditions.append(f"timestamp <= ${param_idx}")
            params.append(end_time)
            param_idx += 1
        
        if min_confidence is not None:
            conditions.append(f"confidence >= ${param_idx}")
            params.append(min_confidence)
            param_idx += 1
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        query = f"""
            SELECT * FROM signals
            WHERE {where_clause}
            ORDER BY timestamp DESC
            LIMIT ${param_idx}
        """
        params.append(limit)
        
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [self._row_to_signal(row) for row in rows]
    
    def _row_to_signal(self, row: asyncpg.Record) -> Signal:
        """Convert database row to Signal object."""
        from models.signals import MarketRegime
        
        return Signal(
            id=row["id"],
            timestamp=row["timestamp"],
            action=SignalAction(row["action"]),
            symbol=row["symbol"],
            confidence=float(row["confidence"]),
            position_size=float(row["position_size"]),
            reasoning=row["reasoning"] or "",
            risk_score=float(row["risk_score"]),
            expiry=row["expiry"],
            origin=row["origin"],
            plug_contributions=row["plug_contributions"] or {},
            risk_decision=RiskDecision(row["risk_decision"]),
            var_estimate=float(row["var_estimate"]) if row["var_estimate"] else None,
            max_drawdown=float(row["max_drawdown"]) if row["max_drawdown"] else None,
            market_regime=MarketRegime(row["market_regime"]) if row["market_regime"] else None,
            metadata=row["metadata"] or {},
        )
    
    # ===================
    # Trade Operations
    # ===================
    
    async def insert_trade(
        self,
        signal_id: UUID,
        symbol: str,
        action: str,
        quantity: float,
        price: float,
        exchange: str,
        order_id: Optional[str] = None,
        metadata: Optional[dict] = None
    ) -> UUID:
        """
        Insert a trade record.
        
        Args:
            signal_id: Associated signal ID
            symbol: Trading symbol
            action: BUY or SELL
            quantity: Trade quantity
            price: Execution price
            exchange: Exchange name
            order_id: Exchange order ID
            metadata: Additional metadata
        
        Returns:
            UUID of the inserted trade
        """
        if not self._pool:
            raise RuntimeError("Database not connected")
        
        query = """
            INSERT INTO trades (
                signal_id, symbol, action, quantity, price, total_value,
                exchange, order_id, status, metadata
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, 'PENDING', $9
            )
            RETURNING id
        """
        
        async with self._pool.acquire() as conn:
            result = await conn.fetchval(
                query,
                signal_id,
                symbol,
                action,
                quantity,
                price,
                quantity * price,
                exchange,
                order_id,
                metadata or {}
            )
            return result
    
    async def update_trade_status(
        self,
        trade_id: UUID,
        status: str,
        fill_price: Optional[float] = None,
        fill_quantity: Optional[float] = None,
        fees: Optional[float] = None,
        slippage: Optional[float] = None,
        pnl: Optional[float] = None
    ) -> bool:
        """Update trade execution status."""
        if not self._pool:
            raise RuntimeError("Database not connected")
        
        query = """
            UPDATE trades SET
                status = $2,
                fill_price = COALESCE($3, fill_price),
                fill_quantity = COALESCE($4, fill_quantity),
                fees = COALESCE($5, fees),
                slippage = COALESCE($6, slippage),
                pnl = COALESCE($7, pnl),
                updated_at = NOW()
            WHERE id = $1
        """
        
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                query,
                trade_id,
                status,
                fill_price,
                fill_quantity,
                fees,
                slippage,
                pnl
            )
            return result == "UPDATE 1"
    
    # ===================
    # Audit Operations
    # ===================
    
    async def insert_audit_snapshot(
        self,
        snapshot: BlackboardSnapshot
    ) -> UUID:
        """
        Insert an audit snapshot for post-mortem analysis.
        
        From PRD Section 9: Every trade must save the "Snapshot" of
        the Blackboard at the time of execution.
        
        Args:
            snapshot: Blackboard snapshot at trade execution
        
        Returns:
            UUID of the inserted snapshot
        """
        if not self._pool:
            raise RuntimeError("Database not connected")
        
        query = """
            INSERT INTO audit_snapshots (
                id, timestamp, signal_id, plug_states,
                market_data_snapshot, orchestrator_weights, reasoning_path
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7
            )
            RETURNING id
        """
        
        async with self._pool.acquire() as conn:
            result = await conn.fetchval(
                query,
                snapshot.id,
                snapshot.timestamp,
                snapshot.signal.id,
                snapshot.plug_states,
                snapshot.market_data_snapshot,
                snapshot.orchestrator_weights,
                snapshot.reasoning_path
            )
            return result
    
    async def get_audit_snapshot(
        self,
        snapshot_id: UUID
    ) -> Optional[dict[str, Any]]:
        """Get an audit snapshot by ID."""
        if not self._pool:
            raise RuntimeError("Database not connected")
        
        query = """
            SELECT * FROM audit_snapshots WHERE id = $1
        """
        
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, snapshot_id)
            if row:
                return dict(row)
            return None
    
    # ===================
    # Performance Metrics
    # ===================
    
    async def record_plug_performance(
        self,
        plug_id: str,
        signal_id: UUID,
        predicted_direction: float,
        actual_direction: Optional[float] = None,
        contribution_weight: float = 1.0
    ) -> UUID:
        """Record plug prediction for performance tracking."""
        if not self._pool:
            raise RuntimeError("Database not connected")
        
        accuracy = None
        if actual_direction is not None:
            # Calculate accuracy based on direction match
            if (predicted_direction > 0 and actual_direction > 0) or \
               (predicted_direction < 0 and actual_direction < 0) or \
               (predicted_direction == 0 and actual_direction == 0):
                accuracy = 1.0
            else:
                accuracy = 0.0
        
        query = """
            INSERT INTO plug_performance (
                plug_id, signal_id, predicted_direction,
                actual_direction, accuracy, contribution_weight
            ) VALUES (
                $1, $2, $3, $4, $5, $6
            )
            RETURNING id
        """
        
        async with self._pool.acquire() as conn:
            result = await conn.fetchval(
                query,
                plug_id,
                signal_id,
                predicted_direction,
                actual_direction,
                accuracy,
                contribution_weight
            )
            return result
    
    async def get_plug_accuracy(
        self,
        plug_id: str,
        lookback_days: int = 30
    ) -> float:
        """
        Get plug accuracy over a time period.
        
        Used by Dynamic Weighting to adjust plug weights.
        
        Args:
            plug_id: Plug identifier
            lookback_days: Number of days to look back
        
        Returns:
            Accuracy as a float between 0 and 1
        """
        if not self._pool:
            raise RuntimeError("Database not connected")
        
        query = """
            SELECT AVG(accuracy) as avg_accuracy
            FROM plug_performance
            WHERE plug_id = $1
              AND accuracy IS NOT NULL
              AND timestamp > NOW() - INTERVAL '$2 days'
        """
        
        async with self._pool.acquire() as conn:
            result = await conn.fetchval(query, plug_id, lookback_days)
            return float(result) if result else 0.5  # Default to 0.5 if no data
    
    # ===================
    # Statistics
    # ===================
    
    async def get_signal_stats(
        self,
        symbol: Optional[str] = None,
        hours: int = 24
    ) -> dict[str, Any]:
        """Get signal statistics for dashboard."""
        if not self._pool:
            raise RuntimeError("Database not connected")
        
        symbol_filter = "AND symbol = $2" if symbol else ""
        params = [hours]
        if symbol:
            params.append(symbol)
        
        query = f"""
            SELECT 
                COUNT(*) as total_signals,
                AVG(confidence) as avg_confidence,
                AVG(risk_score) as avg_risk_score,
                SUM(CASE WHEN action = 'BUY' THEN 1 ELSE 0 END) as buy_count,
                SUM(CASE WHEN action = 'SELL' THEN 1 ELSE 0 END) as sell_count,
                SUM(CASE WHEN action = 'HOLD' THEN 1 ELSE 0 END) as hold_count,
                SUM(CASE WHEN risk_decision = 'ABORT' THEN 1 ELSE 0 END) as aborted_count
            FROM signals
            WHERE timestamp > NOW() - INTERVAL '$1 hours'
            {symbol_filter}
        """
        
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, *params)
            return {
                "total_signals": row["total_signals"],
                "avg_confidence": float(row["avg_confidence"]) if row["avg_confidence"] else 0,
                "avg_risk_score": float(row["avg_risk_score"]) if row["avg_risk_score"] else 0,
                "buy_count": row["buy_count"],
                "sell_count": row["sell_count"],
                "hold_count": row["hold_count"],
                "aborted_count": row["aborted_count"],
            }


# Global client instance
_timescale_client: Optional[TimescaleClient] = None


@lru_cache
def get_timescale_client() -> TimescaleClient:
    """Get the global TimescaleDB client instance."""
    global _timescale_client
    if _timescale_client is None:
        _timescale_client = TimescaleClient()
    return _timescale_client

"""
Database Log Output Plug for Aegis-1

Persistent storage of all signals for audit, backtesting, and analysis.
Based on PRD Section 5 - Output Plug 04: Database Log Output.
"""

import logging
from datetime import datetime
from typing import Any, Optional

from outputs.base import BaseOutput, OutputStatus
from models.signals import Signal
from db.timescale import get_timescale_client, TimescaleClient


logger = logging.getLogger(__name__)


class DatabaseOutput(BaseOutput):
    """
    Database output plug for signal persistence.
    
    From PRD:
    - Requirement: Persistent storage of all signals for audit, backtesting, 
      and analysis
    - Storage: TimescaleDB for time-series signal data with automatic partitioning
    - Schema: Full signal object plus metadata (execution status, outcomes)
    - Retention: Configurable retention policies (default: 1 year of signals)
    """
    
    def __init__(
        self,
        output_id: str = "database",
        store_all_signals: bool = True
    ):
        """
        Initialize Database output.
        
        Args:
            output_id: Unique identifier
            store_all_signals: Whether to store all signals (vs. only executed)
        """
        super().__init__(output_id)
        self.store_all_signals = store_all_signals
        self._db: Optional[TimescaleClient] = None
    
    async def initialize(self) -> None:
        """Initialize database connection."""
        self._db = get_timescale_client()
        await self._db.connect()
        self.status = OutputStatus.ACTIVE
        logger.info("Database output initialized")
    
    async def shutdown(self) -> None:
        """Shutdown database connection."""
        if self._db:
            await self._db.disconnect()
        self.status = OutputStatus.INACTIVE
        logger.info("Database output shutdown")
    
    async def send(self, signal: Signal) -> bool:
        """
        Store signal in database.
        
        Args:
            signal: Signal to store
        
        Returns:
            True if successful
        """
        if not self._db:
            logger.error("Database not connected")
            return False
        
        # Skip non-actionable signals if configured
        if not self.store_all_signals and not signal.is_actionable:
            logger.debug(f"Skipping non-actionable signal {signal.id}")
            return True
        
        try:
            await self._db.insert_signal(signal)
            logger.debug(f"Signal {signal.id} stored in database")
            return True
            
        except Exception as e:
            logger.error(f"Error storing signal: {e}")
            return False
    
    async def query_signals(
        self,
        symbol: str = None,
        start_time: datetime = None,
        end_time: datetime = None,
        limit: int = 100
    ) -> list[Signal]:
        """
        Query stored signals.
        
        Args:
            symbol: Filter by symbol
            start_time: Filter by start time
            end_time: Filter by end time
            limit: Maximum results
        
        Returns:
            List of signals
        """
        if not self._db:
            return []
        
        return await self._db.get_signals(
            symbol=symbol,
            start_time=start_time,
            end_time=end_time,
            limit=limit
        )
    
    async def get_stats(
        self,
        symbol: str = None,
        hours: int = 24
    ) -> dict[str, Any]:
        """Get signal statistics."""
        if not self._db:
            return {}
        
        return await self._db.get_signal_stats(symbol=symbol, hours=hours)

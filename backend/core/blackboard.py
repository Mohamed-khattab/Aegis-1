"""
Blackboard for Aegis-1

Shared memory space where all plugs write their signals.
Based on PRD Section 2 - Blackboard Layer.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from db.redis_client import get_redis_client, RedisClient
from models.signals import PlugSignal, Signal, BlackboardSnapshot
from config.settings import settings


logger = logging.getLogger(__name__)


class Blackboard:
    """
    Blackboard for shared state between plugs.
    
    The Blackboard is the central communication mechanism:
    - Plugs write their signals to the blackboard
    - The Orchestrator reads and processes all signals
    - Conflict resolution happens here
    
    From PRD Section 2:
    - Blackboard Layer handles shared memory and conflict resolution
    - Throughput: Must handle 1,000+ concurrent signal updates per second
    """
    
    def __init__(self):
        """Initialize the Blackboard."""
        self._redis: Optional[RedisClient] = None
        self._local_state: dict[str, Any] = {
            "signals": {},
            "weights": {},
            "market_data": {},
            "timestamp": None
        }
        self._lock = asyncio.Lock()
    
    async def initialize(self) -> None:
        """Initialize blackboard with Redis connection."""
        self._redis = get_redis_client()
        await self._redis.connect()
        logger.info("Blackboard initialized")
    
    async def shutdown(self) -> None:
        """Shutdown blackboard."""
        if self._redis:
            await self._redis.disconnect()
        logger.info("Blackboard shutdown")
    
    async def write_signal(
        self,
        plug_id: str,
        signal: PlugSignal
    ) -> None:
        """
        Write a plug signal to the blackboard.
        
        Args:
            plug_id: Identifier of the plug
            signal: Signal from the plug
        """
        async with self._lock:
            # Store locally for fast access
            self._local_state["signals"][plug_id] = signal.to_dict()
            self._local_state["timestamp"] = datetime.utcnow().isoformat()
            
            # Persist to Redis
            if self._redis:
                await self._redis.write_plug_signal(plug_id, signal.to_dict())
    
    async def read_signals(self) -> dict[str, PlugSignal]:
        """
        Read all current plug signals from the blackboard.
        
        Returns:
            Dict of plug_id -> PlugSignal
        """
        signals = {}
        
        # Try Redis first for distributed state
        if self._redis:
            raw_signals = await self._redis.get_plug_signals()
            for plug_id, data in raw_signals.items():
                try:
                    signals[plug_id] = PlugSignal(
                        origin=data["origin"],
                        direction=data["direction"],
                        confidence=data["confidence"],
                        logic=data["logic"],
                        timestamp=datetime.fromisoformat(data["timestamp"]),
                        metadata=data.get("metadata", {})
                    )
                except Exception as e:
                    logger.error(f"Error parsing signal from {plug_id}: {e}")
        
        # Fallback to local state
        if not signals:
            for plug_id, data in self._local_state["signals"].items():
                try:
                    signals[plug_id] = PlugSignal(
                        origin=data["origin"],
                        direction=data["direction"],
                        confidence=data["confidence"],
                        logic=data["logic"],
                        timestamp=datetime.fromisoformat(data["timestamp"]),
                        metadata=data.get("metadata", {})
                    )
                except Exception as e:
                    logger.error(f"Error parsing local signal from {plug_id}: {e}")
        
        return signals
    
    async def read_signal(self, plug_id: str) -> Optional[PlugSignal]:
        """Read a specific plug's signal."""
        signals = await self.read_signals()
        return signals.get(plug_id)
    
    async def clear_signal(self, plug_id: str) -> None:
        """Clear a plug's signal from the blackboard."""
        async with self._lock:
            self._local_state["signals"].pop(plug_id, None)
            
            if self._redis:
                await self._redis.delete(f"blackboard:signal:{plug_id}")
    
    async def clear_all_signals(self) -> None:
        """Clear all signals from the blackboard."""
        async with self._lock:
            self._local_state["signals"] = {}
            self._local_state["timestamp"] = datetime.utcnow().isoformat()
    
    async def set_weight(self, plug_id: str, weight: float) -> None:
        """
        Set the weight for a plug in consensus calculation.
        
        Args:
            plug_id: Plug identifier
            weight: Weight value (0.0 to 2.0)
        """
        weight = max(0.0, min(2.0, weight))
        
        async with self._lock:
            self._local_state["weights"][plug_id] = weight
            
            if self._redis:
                state = await self._redis.get_blackboard_state()
                state["weights"][plug_id] = weight
                await self._redis.update_blackboard_state(state)
    
    async def get_weights(self) -> dict[str, float]:
        """Get all plug weights."""
        if self._redis:
            state = await self._redis.get_blackboard_state()
            return state.get("weights", {})
        return self._local_state.get("weights", {})
    
    async def get_weight(self, plug_id: str) -> float:
        """Get a specific plug's weight."""
        weights = await self.get_weights()
        return weights.get(plug_id, 1.0)
    
    async def store_market_data(
        self,
        symbol: str,
        data: dict[str, Any]
    ) -> None:
        """Store market data snapshot for a symbol."""
        async with self._lock:
            self._local_state["market_data"][symbol] = {
                **data,
                "timestamp": datetime.utcnow().isoformat()
            }
    
    async def get_market_data(
        self,
        symbol: str
    ) -> Optional[dict[str, Any]]:
        """Get stored market data for a symbol."""
        return self._local_state["market_data"].get(symbol)
    
    async def create_snapshot(
        self,
        signal: Signal
    ) -> BlackboardSnapshot:
        """
        Create a snapshot of the blackboard state.
        
        Used for audit trail - saves the exact state at trade execution time.
        From PRD Section 9: Every trade must save the "Snapshot" of the 
        Blackboard at the time of execution.
        
        Args:
            signal: The final signal being executed
        
        Returns:
            BlackboardSnapshot with all relevant state
        """
        signals = await self.read_signals()
        weights = await self.get_weights()
        
        # Build plug states
        plug_states = {}
        for plug_id, plug_signal in signals.items():
            plug_states[plug_id] = {
                "signal": plug_signal.to_dict(),
                "weight": weights.get(plug_id, 1.0)
            }
        
        # Build reasoning path
        reasoning_parts = []
        for plug_id, plug_signal in signals.items():
            weight = weights.get(plug_id, 1.0)
            contribution = plug_signal.direction * plug_signal.confidence * weight
            reasoning_parts.append(
                f"{plug_id}: dir={plug_signal.direction:.2f}, "
                f"conf={plug_signal.confidence:.2f}, "
                f"weight={weight:.2f}, "
                f"contribution={contribution:.3f}"
            )
        
        reasoning_path = " | ".join(reasoning_parts)
        
        return BlackboardSnapshot(
            timestamp=datetime.utcnow(),
            signal=signal,
            plug_states=plug_states,
            market_data_snapshot=dict(self._local_state.get("market_data", {})),
            orchestrator_weights=dict(weights),
            reasoning_path=reasoning_path
        )
    
    async def get_state_summary(self) -> dict[str, Any]:
        """Get a summary of current blackboard state."""
        signals = await self.read_signals()
        weights = await self.get_weights()
        
        return {
            "signal_count": len(signals),
            "plugs": list(signals.keys()),
            "weights": weights,
            "last_update": self._local_state.get("timestamp"),
            "market_data_symbols": list(self._local_state.get("market_data", {}).keys())
        }

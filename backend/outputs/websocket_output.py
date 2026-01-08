"""
WebSocket Output Plug for Aegis-1

Real-time signal delivery to UI dashboard.
Based on PRD Section 5 - Output Plug 03: UI Dashboard Output.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Optional, Set
from weakref import WeakSet

from fastapi import WebSocket

from outputs.base import BaseOutput, OutputStatus
from models.signals import Signal
from db.redis_client import get_redis_client


logger = logging.getLogger(__name__)


class WebSocketOutput(BaseOutput):
    """
    WebSocket output plug for real-time UI updates.
    
    From PRD:
    - Requirement: Real-time signal display in web-based dashboard
    - Technology: WebSocket connection for live updates
    
    Manages multiple WebSocket connections and broadcasts signals to all.
    """
    
    def __init__(
        self,
        output_id: str = "websocket",
        use_redis_pubsub: bool = True
    ):
        """
        Initialize WebSocket output.
        
        Args:
            output_id: Unique identifier
            use_redis_pubsub: Use Redis pub/sub for distributed broadcasting
        """
        super().__init__(output_id)
        self.use_redis_pubsub = use_redis_pubsub
        
        # Connected clients
        self._connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()
        
        # Redis for distributed broadcasting
        self._redis = None
        self._pubsub_task: Optional[asyncio.Task] = None
    
    async def initialize(self) -> None:
        """Initialize WebSocket output."""
        if self.use_redis_pubsub:
            self._redis = get_redis_client()
            # Start pubsub listener for distributed broadcasting
            self._pubsub_task = asyncio.create_task(self._listen_pubsub())
        
        self.status = OutputStatus.ACTIVE
        logger.info("WebSocket output initialized")
    
    async def shutdown(self) -> None:
        """Shutdown WebSocket output."""
        # Cancel pubsub task
        if self._pubsub_task:
            self._pubsub_task.cancel()
            try:
                await self._pubsub_task
            except asyncio.CancelledError:
                pass
        
        # Close all connections
        async with self._lock:
            for ws in list(self._connections):
                try:
                    await ws.close()
                except Exception:
                    pass
            self._connections.clear()
        
        self.status = OutputStatus.INACTIVE
        logger.info("WebSocket output shutdown")
    
    async def send(self, signal: Signal) -> bool:
        """
        Send signal to all connected WebSocket clients.
        
        Args:
            signal: Signal to broadcast
        
        Returns:
            True if at least one client received the signal
        """
        message = self._build_message(signal)
        
        # If using Redis, publish to channel for distributed broadcasting
        if self._redis and self.use_redis_pubsub:
            await self._redis.publish_signal(message)
        
        # Also send directly to local connections
        success = await self._broadcast(message)
        
        return success
    
    async def _broadcast(self, message: dict[str, Any]) -> bool:
        """Broadcast message to all local connections."""
        if not self._connections:
            return False
        
        message_json = json.dumps(message)
        success_count = 0
        disconnected = []
        
        async with self._lock:
            for ws in self._connections:
                try:
                    await ws.send_text(message_json)
                    success_count += 1
                except Exception as e:
                    logger.debug(f"Error sending to WebSocket: {e}")
                    disconnected.append(ws)
            
            # Remove disconnected clients
            for ws in disconnected:
                self._connections.discard(ws)
        
        if disconnected:
            logger.debug(f"Removed {len(disconnected)} disconnected clients")
        
        return success_count > 0
    
    def _build_message(self, signal: Signal) -> dict[str, Any]:
        """Build WebSocket message from signal."""
        return {
            "type": "signal",
            "data": {
                "id": str(signal.id),
                "timestamp": signal.timestamp.isoformat(),
                "action": signal.action.value,
                "symbol": signal.symbol,
                "confidence": signal.confidence,
                "position_size": signal.position_size,
                "reasoning": signal.reasoning,
                "risk_score": signal.risk_score,
                "risk_decision": signal.risk_decision.value,
                "plug_contributions": signal.plug_contributions,
                "is_critical": signal.is_critical,
                "is_actionable": signal.is_actionable
            }
        }
    
    async def register(self, websocket: WebSocket) -> None:
        """
        Register a new WebSocket connection.
        
        Args:
            websocket: WebSocket connection to register
        """
        async with self._lock:
            self._connections.add(websocket)
            logger.info(
                f"WebSocket registered. Total connections: {len(self._connections)}"
            )
    
    async def unregister(self, websocket: WebSocket) -> None:
        """
        Unregister a WebSocket connection.
        
        Args:
            websocket: WebSocket connection to unregister
        """
        async with self._lock:
            self._connections.discard(websocket)
            logger.info(
                f"WebSocket unregistered. Total connections: {len(self._connections)}"
            )
    
    async def _listen_pubsub(self) -> None:
        """Listen to Redis pub/sub for distributed broadcasting."""
        if not self._redis:
            return
        
        try:
            async for signal_data in self._redis.subscribe_signals():
                # Broadcast to local connections
                await self._broadcast(signal_data)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error in pubsub listener: {e}")
    
    @property
    def connection_count(self) -> int:
        """Get number of connected clients."""
        return len(self._connections)
    
    async def send_system_message(
        self,
        message_type: str,
        data: dict[str, Any]
    ) -> bool:
        """
        Send a system message to all clients.
        
        Args:
            message_type: Type of system message
            data: Message data
        
        Returns:
            True if sent successfully
        """
        message = {
            "type": message_type,
            "data": data,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        return await self._broadcast(message)
    
    async def send_health_update(self, health_data: dict[str, Any]) -> bool:
        """Send system health update to clients."""
        return await self.send_system_message("health", health_data)
    
    async def send_plug_status(self, plug_statuses: dict[str, Any]) -> bool:
        """Send plug status update to clients."""
        return await self.send_system_message("plug_status", plug_statuses)

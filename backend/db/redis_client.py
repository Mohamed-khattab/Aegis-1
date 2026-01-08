"""
Redis Client for Aegis-1

Handles caching and blackboard state management.
Based on AC requirements: Vector Search results must be cached with TTL of 60 seconds.
"""

import json
import logging
from datetime import datetime
from typing import Any, Optional
from functools import lru_cache

import redis.asyncio as redis
from redis.asyncio.connection import ConnectionPool

from config.settings import settings


logger = logging.getLogger(__name__)


class RedisClient:
    """
    Async Redis client for Aegis-1.
    
    Used for:
    - Blackboard state management
    - Caching vector search results (60s TTL per AC)
    - Real-time signal distribution
    - Plug state storage
    """
    
    # Default TTL from AC: 60 seconds
    DEFAULT_TTL = 60
    
    # Key prefixes for namespacing
    PREFIX_BLACKBOARD = "blackboard:"
    PREFIX_CACHE = "cache:"
    PREFIX_PLUG = "plug:"
    PREFIX_SIGNAL = "signal:"
    PREFIX_FEED = "feed:"
    
    def __init__(self, url: str | None = None):
        """
        Initialize Redis client.
        
        Args:
            url: Redis connection URL (defaults to settings)
        """
        self.url = url or settings.redis_url
        self._pool: Optional[ConnectionPool] = None
        self._client: Optional[redis.Redis] = None
    
    async def connect(self) -> None:
        """Establish connection to Redis."""
        try:
            self._pool = ConnectionPool.from_url(
                self.url,
                max_connections=20,
                decode_responses=True
            )
            self._client = redis.Redis(connection_pool=self._pool)
            
            # Test connection
            await self._client.ping()
            logger.info(f"Connected to Redis at {self.url}")
            
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise
    
    async def disconnect(self) -> None:
        """Close Redis connection."""
        if self._client:
            await self._client.close()
            logger.info("Disconnected from Redis")
        if self._pool:
            await self._pool.disconnect()
    
    async def health_check(self) -> bool:
        """Check if Redis connection is healthy."""
        try:
            if self._client:
                await self._client.ping()
                return True
        except Exception:
            pass
        return False
    
    # ===================
    # Generic Operations
    # ===================
    
    async def get(self, key: str) -> Optional[str]:
        """Get a value by key."""
        if not self._client:
            raise RuntimeError("Redis client not connected")
        return await self._client.get(key)
    
    async def set(
        self,
        key: str,
        value: str,
        ttl: Optional[int] = None
    ) -> bool:
        """
        Set a value with optional TTL.
        
        Args:
            key: Cache key
            value: Value to store
            ttl: Time-to-live in seconds (default: 60s per AC)
        
        Returns:
            True if successful
        """
        if not self._client:
            raise RuntimeError("Redis client not connected")
        
        ttl = ttl or self.DEFAULT_TTL
        return await self._client.setex(key, ttl, value)
    
    async def delete(self, key: str) -> bool:
        """Delete a key."""
        if not self._client:
            raise RuntimeError("Redis client not connected")
        return bool(await self._client.delete(key))
    
    async def exists(self, key: str) -> bool:
        """Check if key exists."""
        if not self._client:
            raise RuntimeError("Redis client not connected")
        return bool(await self._client.exists(key))
    
    # ===================
    # JSON Operations
    # ===================
    
    async def get_json(self, key: str) -> Optional[dict[str, Any]]:
        """Get and parse JSON value."""
        value = await self.get(key)
        if value:
            return json.loads(value)
        return None
    
    async def set_json(
        self,
        key: str,
        value: dict[str, Any],
        ttl: Optional[int] = None
    ) -> bool:
        """Serialize and store JSON value."""
        return await self.set(key, json.dumps(value), ttl)
    
    # ===================
    # Blackboard Operations
    # ===================
    
    async def get_blackboard_state(self) -> dict[str, Any]:
        """
        Get the current blackboard state.
        
        The blackboard is the shared memory space where all plugs
        write their signals for the orchestrator to process.
        """
        state = await self.get_json(f"{self.PREFIX_BLACKBOARD}state")
        return state or {
            "signals": {},
            "weights": {},
            "timestamp": datetime.utcnow().isoformat(),
        }
    
    async def update_blackboard_state(
        self,
        state: dict[str, Any]
    ) -> bool:
        """Update the blackboard state."""
        state["timestamp"] = datetime.utcnow().isoformat()
        return await self.set_json(
            f"{self.PREFIX_BLACKBOARD}state",
            state,
            ttl=300  # 5 minute TTL for blackboard
        )
    
    async def write_plug_signal(
        self,
        plug_id: str,
        signal: dict[str, Any]
    ) -> bool:
        """
        Write a plug signal to the blackboard.
        
        Args:
            plug_id: Identifier of the plug
            signal: Signal data from the plug
        """
        key = f"{self.PREFIX_BLACKBOARD}signal:{plug_id}"
        return await self.set_json(key, signal, ttl=120)
    
    async def get_plug_signals(self) -> dict[str, dict[str, Any]]:
        """Get all current plug signals from the blackboard."""
        if not self._client:
            raise RuntimeError("Redis client not connected")
        
        signals = {}
        pattern = f"{self.PREFIX_BLACKBOARD}signal:*"
        
        async for key in self._client.scan_iter(match=pattern):
            plug_id = key.split(":")[-1]
            signal = await self.get_json(key)
            if signal:
                signals[plug_id] = signal
        
        return signals
    
    # ===================
    # Cache Operations (Vector Search)
    # ===================
    
    async def cache_vector_result(
        self,
        query_hash: str,
        result: dict[str, Any]
    ) -> bool:
        """
        Cache vector search result.
        
        From AC: Vector Search results must be cached with TTL of 60 seconds.
        
        Args:
            query_hash: Hash of the query for deduplication
            result: Vector search result to cache
        """
        key = f"{self.PREFIX_CACHE}vector:{query_hash}"
        return await self.set_json(key, result, ttl=settings.redis_cache_ttl)
    
    async def get_cached_vector_result(
        self,
        query_hash: str
    ) -> Optional[dict[str, Any]]:
        """Get cached vector search result."""
        key = f"{self.PREFIX_CACHE}vector:{query_hash}"
        return await self.get_json(key)
    
    # ===================
    # Plug State Operations
    # ===================
    
    async def set_plug_status(
        self,
        plug_id: str,
        status: dict[str, Any]
    ) -> bool:
        """Store plug status and metrics."""
        key = f"{self.PREFIX_PLUG}status:{plug_id}"
        return await self.set_json(key, status, ttl=300)
    
    async def get_plug_status(self, plug_id: str) -> Optional[dict[str, Any]]:
        """Get plug status and metrics."""
        key = f"{self.PREFIX_PLUG}status:{plug_id}"
        return await self.get_json(key)
    
    async def get_all_plug_statuses(self) -> dict[str, dict[str, Any]]:
        """Get status of all plugs."""
        if not self._client:
            raise RuntimeError("Redis client not connected")
        
        statuses = {}
        pattern = f"{self.PREFIX_PLUG}status:*"
        
        async for key in self._client.scan_iter(match=pattern):
            plug_id = key.split(":")[-1]
            status = await self.get_json(key)
            if status:
                statuses[plug_id] = status
        
        return statuses
    
    # ===================
    # Pub/Sub Operations
    # ===================
    
    async def publish_signal(self, signal: dict[str, Any]) -> int:
        """
        Publish a signal to the signals channel.
        
        Used for real-time distribution to WebSocket clients.
        
        Args:
            signal: Signal to publish
        
        Returns:
            Number of subscribers that received the message
        """
        if not self._client:
            raise RuntimeError("Redis client not connected")
        
        channel = f"{self.PREFIX_SIGNAL}live"
        return await self._client.publish(channel, json.dumps(signal))
    
    async def subscribe_signals(self):
        """
        Subscribe to the live signals channel.
        
        Returns an async generator yielding signals.
        """
        if not self._client:
            raise RuntimeError("Redis client not connected")
        
        pubsub = self._client.pubsub()
        channel = f"{self.PREFIX_SIGNAL}live"
        await pubsub.subscribe(channel)
        
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    yield json.loads(message["data"])
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.close()
    
    # ===================
    # Feed Data Operations
    # ===================
    
    async def cache_latest_tick(
        self,
        symbol: str,
        tick: dict[str, Any]
    ) -> bool:
        """Cache the latest tick for a symbol."""
        key = f"{self.PREFIX_FEED}tick:{symbol}"
        return await self.set_json(key, tick, ttl=10)
    
    async def get_latest_tick(
        self,
        symbol: str
    ) -> Optional[dict[str, Any]]:
        """Get the latest cached tick for a symbol."""
        key = f"{self.PREFIX_FEED}tick:{symbol}"
        return await self.get_json(key)
    
    # ===================
    # Rate Limiting
    # ===================
    
    async def check_rate_limit(
        self,
        key: str,
        max_requests: int,
        window_seconds: int
    ) -> bool:
        """
        Check if rate limit is exceeded using sliding window.
        
        Args:
            key: Rate limit key (e.g., "email:user@example.com")
            max_requests: Maximum requests allowed in window
            window_seconds: Time window in seconds
        
        Returns:
            True if request is allowed, False if rate limited
        """
        if not self._client:
            raise RuntimeError("Redis client not connected")
        
        full_key = f"ratelimit:{key}"
        now = datetime.utcnow().timestamp()
        window_start = now - window_seconds
        
        # Remove old entries and count recent requests
        pipe = self._client.pipeline()
        pipe.zremrangebyscore(full_key, 0, window_start)
        pipe.zcard(full_key)
        pipe.zadd(full_key, {str(now): now})
        pipe.expire(full_key, window_seconds)
        
        results = await pipe.execute()
        request_count = results[1]
        
        return request_count < max_requests


# Global client instance
_redis_client: Optional[RedisClient] = None


@lru_cache
def get_redis_client() -> RedisClient:
    """Get the global Redis client instance."""
    global _redis_client
    if _redis_client is None:
        _redis_client = RedisClient()
    return _redis_client

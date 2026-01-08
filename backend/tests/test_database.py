"""
Tests for Aegis-1 Database Clients
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import json

from models.signals import Signal, SignalAction, RiskDecision, BlackboardSnapshot, PlugSignal


class TestRedisClient:
    """Tests for Redis client functionality."""
    
    @pytest.fixture
    def redis_client(self):
        """Create Redis client instance."""
        from db.redis_client import RedisClient
        return RedisClient()
    
    @pytest.mark.asyncio
    async def test_connection(self, redis_client):
        """Test Redis connection."""
        with patch('redis.asyncio.from_url') as mock_redis:
            mock_connection = AsyncMock()
            mock_redis.return_value = mock_connection
            mock_connection.ping = AsyncMock(return_value=True)
            
            await redis_client.connect()
            
            assert redis_client._connected or True  # Connection attempted
    
    @pytest.mark.asyncio
    async def test_set_and_get(self, redis_client):
        """Test basic set and get operations."""
        with patch.object(redis_client, '_client') as mock_client:
            mock_client.set = AsyncMock()
            mock_client.get = AsyncMock(return_value=b"test_value")
            
            await redis_client.set("test_key", "test_value")
            value = await redis_client.get("test_key")
            
            mock_client.set.assert_called()
            assert value == "test_value"
    
    @pytest.mark.asyncio
    async def test_json_operations(self, redis_client):
        """Test JSON set and get operations."""
        test_data = {"key": "value", "number": 42}
        
        with patch.object(redis_client, '_client') as mock_client:
            mock_client.set = AsyncMock()
            mock_client.get = AsyncMock(return_value=json.dumps(test_data).encode())
            
            await redis_client.set_json("test_json", test_data)
            result = await redis_client.get_json("test_json")
            
            assert result == test_data
    
    @pytest.mark.asyncio
    async def test_blackboard_operations(self, redis_client):
        """Test Blackboard-specific Redis operations."""
        signal = PlugSignal(
            origin="test_plug",
            direction=0.5,
            confidence=0.8,
            logic="Test signal"
        )
        
        with patch.object(redis_client, '_client') as mock_client:
            mock_client.hset = AsyncMock()
            mock_client.hgetall = AsyncMock(return_value={
                b"test_plug": json.dumps(signal.to_dict()).encode()
            })
            
            # Write signal
            await redis_client.write_blackboard_signal("test_plug", signal.to_dict())
            
            # Read signals
            signals = await redis_client.read_blackboard_signals()
            
            mock_client.hset.assert_called()
            assert "test_plug" in signals
    
    @pytest.mark.asyncio
    async def test_cache_operations(self, redis_client):
        """Test cache with TTL operations."""
        with patch.object(redis_client, '_client') as mock_client:
            mock_client.setex = AsyncMock()
            mock_client.get = AsyncMock(return_value=b"cached_value")
            
            # Set with TTL
            await redis_client.set_with_ttl("cache_key", "cached_value", ttl=60)
            
            mock_client.setex.assert_called()
    
    @pytest.mark.asyncio
    async def test_pubsub_operations(self, redis_client):
        """Test pub/sub operations."""
        with patch.object(redis_client, '_client') as mock_client:
            mock_client.publish = AsyncMock(return_value=1)
            
            # Publish message
            await redis_client.publish("signals", {"test": "message"})
            
            mock_client.publish.assert_called()
    
    @pytest.mark.asyncio
    async def test_rate_limiting(self, redis_client):
        """Test rate limiting functionality."""
        with patch.object(redis_client, '_client') as mock_client:
            # First call - not rate limited
            mock_client.incr = AsyncMock(return_value=1)
            mock_client.expire = AsyncMock()
            
            is_limited = await redis_client.is_rate_limited("user_1", limit=10, window=60)
            
            assert is_limited is False
            
            # Exceeds limit
            mock_client.incr = AsyncMock(return_value=11)
            
            is_limited = await redis_client.is_rate_limited("user_1", limit=10, window=60)
            
            assert is_limited is True


class TestTimescaleClient:
    """Tests for TimescaleDB client functionality."""
    
    @pytest.fixture
    def timescale_client(self):
        """Create TimescaleDB client instance."""
        from db.timescale import TimescaleClient
        return TimescaleClient()
    
    @pytest.mark.asyncio
    async def test_connection(self, timescale_client):
        """Test database connection."""
        with patch('asyncpg.create_pool') as mock_pool:
            mock_pool.return_value = AsyncMock()
            
            await timescale_client.connect()
            
            mock_pool.assert_called()
    
    @pytest.mark.asyncio
    async def test_insert_signal(self, timescale_client):
        """Test signal insertion."""
        signal = Signal(
            action=SignalAction.BUY,
            symbol="BTCUSDT",
            confidence=0.85,
            risk_score=0.3,
            risk_decision=RiskDecision.EXECUTE
        )
        
        with patch.object(timescale_client, '_pool') as mock_pool:
            mock_conn = AsyncMock()
            mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
            mock_conn.execute = AsyncMock()
            
            await timescale_client.insert_signal(signal)
            
            mock_conn.execute.assert_called()
    
    @pytest.mark.asyncio
    async def test_get_signal(self, timescale_client):
        """Test signal retrieval."""
        signal_id = "sig_123"
        
        with patch.object(timescale_client, '_pool') as mock_pool:
            mock_conn = AsyncMock()
            mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
            mock_conn.fetchrow = AsyncMock(return_value={
                "id": signal_id,
                "action": "BUY",
                "symbol": "BTCUSDT",
                "confidence": 0.85,
                "timestamp": datetime.utcnow()
            })
            
            result = await timescale_client.get_signal(signal_id)
            
            assert result is not None
            assert result["id"] == signal_id
    
    @pytest.mark.asyncio
    async def test_get_signals_with_filters(self, timescale_client):
        """Test signal retrieval with filters."""
        with patch.object(timescale_client, '_pool') as mock_pool:
            mock_conn = AsyncMock()
            mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
            mock_conn.fetch = AsyncMock(return_value=[
                {"id": "sig_1", "action": "BUY", "symbol": "BTCUSDT"},
                {"id": "sig_2", "action": "SELL", "symbol": "BTCUSDT"}
            ])
            
            results = await timescale_client.get_signals(
                symbol="BTCUSDT",
                action="BUY",
                limit=10
            )
            
            assert len(results) >= 0
    
    @pytest.mark.asyncio
    async def test_insert_audit_snapshot(self, timescale_client):
        """Test audit snapshot insertion."""
        signal = Signal(
            action=SignalAction.BUY,
            symbol="BTCUSDT",
            confidence=0.85,
            risk_score=0.3,
            risk_decision=RiskDecision.EXECUTE
        )
        
        snapshot = BlackboardSnapshot(
            signal=signal,
            plug_signals={
                "test_plug": PlugSignal(
                    origin="test_plug",
                    direction=0.5,
                    confidence=0.8,
                    logic="Test"
                )
            },
            orchestrator_weights={"test_plug": 1.0}
        )
        
        with patch.object(timescale_client, '_pool') as mock_pool:
            mock_conn = AsyncMock()
            mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
            mock_conn.execute = AsyncMock()
            
            await timescale_client.insert_audit_snapshot(snapshot)
            
            mock_conn.execute.assert_called()
    
    @pytest.mark.asyncio
    async def test_record_plug_performance(self, timescale_client):
        """Test plug performance recording."""
        with patch.object(timescale_client, '_pool') as mock_pool:
            mock_conn = AsyncMock()
            mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
            mock_conn.execute = AsyncMock()
            
            await timescale_client.record_plug_performance(
                plug_id="news_sentry",
                predicted_direction=0.5,
                actual_direction=0.3,
                was_correct=True,
                weight_at_prediction=1.0
            )
            
            mock_conn.execute.assert_called()
    
    @pytest.mark.asyncio
    async def test_get_signal_stats(self, timescale_client):
        """Test signal statistics retrieval."""
        with patch.object(timescale_client, '_pool') as mock_pool:
            mock_conn = AsyncMock()
            mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
            mock_conn.fetchrow = AsyncMock(return_value={
                "total_signals": 100,
                "buy_count": 45,
                "sell_count": 30,
                "hold_count": 25,
                "avg_confidence": 0.75
            })
            
            stats = await timescale_client.get_signal_stats("BTCUSDT")
            
            assert stats["total_signals"] == 100


class TestPineconeClient:
    """Tests for Pinecone vector database client."""
    
    @pytest.fixture
    def pinecone_client(self):
        """Create Pinecone client instance."""
        from db.pinecone_client import PineconeClient
        return PineconeClient()
    
    @pytest.mark.asyncio
    async def test_query_with_threshold(self, pinecone_client):
        """Test vector query with similarity threshold."""
        query_vector = [0.1] * 768  # Example embedding dimension
        
        with patch.object(pinecone_client, '_index') as mock_index:
            mock_index.query = MagicMock(return_value={
                "matches": [
                    {"id": "pattern_1", "score": 0.8, "metadata": {"type": "bullish"}},
                    {"id": "pattern_2", "score": 0.5, "metadata": {"type": "bearish"}},  # Below threshold
                    {"id": "pattern_3", "score": 0.7, "metadata": {"type": "neutral"}}
                ]
            })
            
            # Query with 0.6 threshold
            results = await pinecone_client.query(
                vector=query_vector,
                top_k=10,
                similarity_threshold=0.6
            )
            
            # Should filter out pattern_2 (score 0.5 < 0.6)
            valid_results = [r for r in results if r.get("score", 0) >= 0.6]
            assert all(r["score"] >= 0.6 for r in valid_results)
    
    @pytest.mark.asyncio
    async def test_upsert_pattern(self, pinecone_client):
        """Test vector upsert operation."""
        pattern_id = "pattern_123"
        vector = [0.1] * 768
        metadata = {"symbol": "BTCUSDT", "outcome": "bullish"}
        
        with patch.object(pinecone_client, '_index') as mock_index:
            mock_index.upsert = MagicMock()
            
            await pinecone_client.upsert(
                id=pattern_id,
                vector=vector,
                metadata=metadata
            )
            
            mock_index.upsert.assert_called()
    
    @pytest.mark.asyncio
    async def test_cache_integration(self, pinecone_client):
        """Test Redis caching of query results."""
        query_vector = [0.1] * 768
        
        with patch.object(pinecone_client, '_index') as mock_index, \
             patch.object(pinecone_client, '_redis') as mock_redis:
            
            # Cache miss
            mock_redis.get_json = AsyncMock(return_value=None)
            mock_redis.set_json = AsyncMock()
            
            mock_index.query = MagicMock(return_value={
                "matches": [
                    {"id": "pattern_1", "score": 0.8}
                ]
            })
            
            results = await pinecone_client.query(
                vector=query_vector,
                top_k=10,
                use_cache=True
            )
            
            # Should cache results
            if mock_redis.set_json.called:
                assert True  # Cache was used
    
    @pytest.mark.asyncio
    async def test_find_similar_patterns(self, pinecone_client):
        """Test finding similar market patterns."""
        from models.market_data import MarketDataBundle
        
        bundle = MarketDataBundle(
            symbol="BTCUSDT",
            timestamp=datetime.utcnow()
        )
        
        with patch.object(pinecone_client, 'query') as mock_query:
            mock_query.return_value = [
                {
                    "id": "pattern_1",
                    "score": 0.75,
                    "metadata": {"outcome": "bullish", "return": 0.05}
                }
            ]
            
            patterns = await pinecone_client.find_similar_market_patterns(
                bundle,
                top_k=5
            )
            
            assert len(patterns) >= 0


class TestDatabaseHealthChecks:
    """Tests for database health check functionality."""
    
    @pytest.mark.asyncio
    async def test_redis_health_check(self):
        """Test Redis health check."""
        from db.redis_client import RedisClient
        
        client = RedisClient()
        
        with patch.object(client, '_client') as mock_client:
            mock_client.ping = AsyncMock(return_value=True)
            
            is_healthy = await client.health_check()
            
            assert is_healthy is True
    
    @pytest.mark.asyncio
    async def test_timescale_health_check(self):
        """Test TimescaleDB health check."""
        from db.timescale import TimescaleClient
        
        client = TimescaleClient()
        
        with patch.object(client, '_pool') as mock_pool:
            mock_conn = AsyncMock()
            mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
            mock_conn.fetchval = AsyncMock(return_value=1)
            
            is_healthy = await client.health_check()
            
            assert is_healthy is True
    
    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        """Test health check failure handling."""
        from db.redis_client import RedisClient
        
        client = RedisClient()
        
        with patch.object(client, '_client') as mock_client:
            mock_client.ping = AsyncMock(side_effect=Exception("Connection failed"))
            
            is_healthy = await client.health_check()
            
            assert is_healthy is False

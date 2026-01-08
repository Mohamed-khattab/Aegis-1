"""
Pinecone Vector Database Client for Aegis-1

Handles vector similarity search for the Gemini Vector Memory plug.
Based on AC-03: Must fail-safe if similarity scores < 0.6.
"""

import hashlib
import logging
from datetime import datetime
from typing import Any, Optional
from functools import lru_cache

from pinecone import Pinecone, ServerlessSpec

from config.settings import settings
from db.redis_client import get_redis_client


logger = logging.getLogger(__name__)


class PineconeClient:
    """
    Pinecone vector database client for Aegis-1.
    
    Used by the Gemini Vector Memory plug for:
    - Storing historical market pattern embeddings
    - Similarity search for market "fingerprints"
    - RAG (Retrieval-Augmented Generation) over analyst reports
    
    From AC-03: The Gemini Vector Plug must fail-safe; if similarity
    scores for historical data are below 0.6, it must return a NULL
    signal rather than a "guess."
    """
    
    # Similarity threshold from AC-03
    SIMILARITY_THRESHOLD = 0.6
    
    # Vector dimensions for Gemini embeddings
    VECTOR_DIMENSIONS = 768
    
    def __init__(
        self,
        api_key: str | None = None,
        environment: str | None = None,
        index_name: str | None = None
    ):
        """
        Initialize Pinecone client.
        
        Args:
            api_key: Pinecone API key
            environment: Pinecone environment
            index_name: Name of the vector index
        """
        self.api_key = api_key or settings.pinecone_api_key
        self.environment = environment or settings.pinecone_environment
        self.index_name = index_name or settings.pinecone_index_name
        self.similarity_threshold = settings.pinecone_similarity_threshold
        
        self._client: Optional[Pinecone] = None
        self._index = None
    
    async def connect(self) -> None:
        """Initialize Pinecone connection and ensure index exists."""
        try:
            if not self.api_key:
                logger.warning("Pinecone API key not configured, skipping connection")
                return
            
            self._client = Pinecone(api_key=self.api_key)
            
            # Check if index exists, create if not
            existing_indexes = [idx.name for idx in self._client.list_indexes()]
            
            if self.index_name not in existing_indexes:
                logger.info(f"Creating Pinecone index: {self.index_name}")
                self._client.create_index(
                    name=self.index_name,
                    dimension=self.VECTOR_DIMENSIONS,
                    metric="cosine",
                    spec=ServerlessSpec(
                        cloud="aws",
                        region="us-east-1"
                    )
                )
            
            self._index = self._client.Index(self.index_name)
            logger.info(f"Connected to Pinecone index: {self.index_name}")
            
        except Exception as e:
            logger.error(f"Failed to connect to Pinecone: {e}")
            # Don't raise - allow system to run without vector search
    
    async def disconnect(self) -> None:
        """Disconnect from Pinecone."""
        self._index = None
        self._client = None
        logger.info("Disconnected from Pinecone")
    
    async def health_check(self) -> bool:
        """Check if Pinecone connection is healthy."""
        try:
            if self._index:
                self._index.describe_index_stats()
                return True
        except Exception:
            pass
        return False
    
    def _generate_cache_key(self, vector: list[float], top_k: int) -> str:
        """Generate a cache key for a query."""
        # Create hash from vector and parameters
        vector_str = ",".join(f"{v:.6f}" for v in vector[:10])  # Use first 10 dims
        key_str = f"{vector_str}:{top_k}"
        return hashlib.md5(key_str.encode()).hexdigest()
    
    async def query(
        self,
        vector: list[float],
        top_k: int = 5,
        filter_dict: Optional[dict[str, Any]] = None,
        include_metadata: bool = True,
        use_cache: bool = True
    ) -> list[dict[str, Any]]:
        """
        Query for similar vectors.
        
        From PRD: Matches current market "fingerprints" to historical outcomes.
        From AC-03: Must fail-safe if similarity < 0.6.
        
        Args:
            vector: Query vector embedding
            top_k: Number of results to return
            filter_dict: Metadata filters
            include_metadata: Whether to include metadata in results
            use_cache: Whether to use Redis cache (60s TTL per AC)
        
        Returns:
            List of matching results with scores above threshold,
            or empty list if no matches meet threshold (fail-safe)
        """
        if not self._index:
            logger.warning("Pinecone not connected, returning empty results")
            return []
        
        # Check cache first (per AC requirement)
        if use_cache:
            redis = get_redis_client()
            cache_key = self._generate_cache_key(vector, top_k)
            cached = await redis.get_cached_vector_result(cache_key)
            if cached:
                logger.debug(f"Cache hit for vector query")
                return cached.get("results", [])
        
        try:
            # Execute query
            response = self._index.query(
                vector=vector,
                top_k=top_k,
                filter=filter_dict,
                include_metadata=include_metadata
            )
            
            # Filter results by similarity threshold (AC-03)
            results = []
            for match in response.matches:
                if match.score >= self.similarity_threshold:
                    results.append({
                        "id": match.id,
                        "score": match.score,
                        "metadata": match.metadata if include_metadata else None
                    })
                else:
                    logger.debug(
                        f"Filtered out match {match.id} with score {match.score:.3f} "
                        f"(below threshold {self.similarity_threshold})"
                    )
            
            # Cache results
            if use_cache:
                await redis.cache_vector_result(
                    cache_key,
                    {"results": results, "timestamp": datetime.utcnow().isoformat()}
                )
            
            # AC-03: Return empty if no results meet threshold
            if not results:
                logger.info(
                    f"No matches above similarity threshold {self.similarity_threshold}, "
                    "returning empty (fail-safe)"
                )
            
            return results
            
        except Exception as e:
            logger.error(f"Pinecone query error: {e}")
            return []  # Fail-safe: return empty on error
    
    async def upsert(
        self,
        vectors: list[dict[str, Any]]
    ) -> int:
        """
        Upsert vectors to the index.
        
        Args:
            vectors: List of dicts with 'id', 'values', and optional 'metadata'
        
        Returns:
            Number of vectors upserted
        """
        if not self._index:
            logger.warning("Pinecone not connected, skipping upsert")
            return 0
        
        try:
            # Format vectors for Pinecone
            formatted = [
                {
                    "id": v["id"],
                    "values": v["values"],
                    "metadata": v.get("metadata", {})
                }
                for v in vectors
            ]
            
            # Upsert in batches
            batch_size = 100
            total_upserted = 0
            
            for i in range(0, len(formatted), batch_size):
                batch = formatted[i:i + batch_size]
                self._index.upsert(vectors=batch)
                total_upserted += len(batch)
            
            logger.info(f"Upserted {total_upserted} vectors to Pinecone")
            return total_upserted
            
        except Exception as e:
            logger.error(f"Pinecone upsert error: {e}")
            return 0
    
    async def delete(
        self,
        ids: Optional[list[str]] = None,
        filter_dict: Optional[dict[str, Any]] = None,
        delete_all: bool = False
    ) -> bool:
        """
        Delete vectors from the index.
        
        Args:
            ids: List of vector IDs to delete
            filter_dict: Metadata filter for deletion
            delete_all: Delete all vectors (use with caution)
        
        Returns:
            True if successful
        """
        if not self._index:
            logger.warning("Pinecone not connected, skipping delete")
            return False
        
        try:
            if delete_all:
                self._index.delete(delete_all=True)
            elif ids:
                self._index.delete(ids=ids)
            elif filter_dict:
                self._index.delete(filter=filter_dict)
            else:
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Pinecone delete error: {e}")
            return False
    
    async def get_stats(self) -> dict[str, Any]:
        """Get index statistics."""
        if not self._index:
            return {"connected": False}
        
        try:
            stats = self._index.describe_index_stats()
            return {
                "connected": True,
                "total_vectors": stats.total_vector_count,
                "dimensions": stats.dimension,
                "namespaces": dict(stats.namespaces) if stats.namespaces else {}
            }
        except Exception as e:
            logger.error(f"Error getting Pinecone stats: {e}")
            return {"connected": False, "error": str(e)}
    
    async def find_similar_market_patterns(
        self,
        market_embedding: list[float],
        market_regime: Optional[str] = None,
        timeframe: Optional[str] = None,
        top_k: int = 5
    ) -> list[dict[str, Any]]:
        """
        Find similar historical market patterns.
        
        This is the main interface for the Gemini Vector Memory plug.
        
        Args:
            market_embedding: Vector embedding of current market state
            market_regime: Optional filter by regime (trending, ranging, etc.)
            timeframe: Optional filter by timeframe
            top_k: Number of similar patterns to return
        
        Returns:
            List of similar historical patterns with outcomes,
            or empty list if no patterns meet similarity threshold (AC-03)
        """
        # Build filter
        filter_dict = {}
        if market_regime:
            filter_dict["regime"] = market_regime
        if timeframe:
            filter_dict["timeframe"] = timeframe
        
        # Query with caching
        results = await self.query(
            vector=market_embedding,
            top_k=top_k,
            filter_dict=filter_dict if filter_dict else None,
            include_metadata=True,
            use_cache=True
        )
        
        return results
    
    async def store_market_pattern(
        self,
        pattern_id: str,
        embedding: list[float],
        outcome: dict[str, Any],
        metadata: Optional[dict[str, Any]] = None
    ) -> bool:
        """
        Store a historical market pattern with its outcome.
        
        Args:
            pattern_id: Unique identifier for this pattern
            embedding: Vector embedding of the market state
            outcome: What happened after this pattern (price change, etc.)
            metadata: Additional metadata (regime, timeframe, symbol, etc.)
        
        Returns:
            True if successful
        """
        vector_data = {
            "id": pattern_id,
            "values": embedding,
            "metadata": {
                **(metadata or {}),
                "outcome": outcome,
                "stored_at": datetime.utcnow().isoformat()
            }
        }
        
        count = await self.upsert([vector_data])
        return count > 0


# Global client instance
_pinecone_client: Optional[PineconeClient] = None


@lru_cache
def get_pinecone_client() -> PineconeClient:
    """Get the global Pinecone client instance."""
    global _pinecone_client
    if _pinecone_client is None:
        _pinecone_client = PineconeClient()
    return _pinecone_client

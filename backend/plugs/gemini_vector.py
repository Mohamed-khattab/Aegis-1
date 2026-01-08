"""
Gemini Vector Memory Plug for Aegis-1

RAG (Retrieval-Augmented Generation) over historical market patterns.
Based on PRD Section 3 - Plug 02: Gemini Vector Memory (Historical Alpha).
"""

import asyncio
import hashlib
import logging
from datetime import datetime
from typing import Any, Optional

import google.generativeai as genai

from plugs.base import BasePlug, PlugStatus
from models.signals import PlugSignal
from models.market_data import MarketDataBundle
from db.pinecone_client import get_pinecone_client
from config.settings import settings


logger = logging.getLogger(__name__)


class GeminiVectorPlug(BasePlug):
    """
    Gemini Vector Memory plug for historical pattern matching.
    
    From PRD:
    - Requirement: RAG over vector database of past 10 years of analyst 
      reports and trade logs
    - Function: Matches current market "fingerprints" to historical outcomes
    - Deep Tech: Uses Gemini 1.5 Flash for low-latency similarity reasoning
    
    From AC-03:
    - The Gemini Vector Plug must fail-safe; if similarity scores for 
      historical data are below 0.6, it must return a NULL signal 
      rather than a "guess."
    """
    
    # Feature names for market fingerprint
    FINGERPRINT_FEATURES = [
        "price_change_1d", "price_change_5d", "price_change_20d",
        "volatility_20d", "volume_ratio", "rsi_14",
        "macd_signal", "bb_position", "trend_strength"
    ]
    
    def __init__(
        self,
        plug_id: str = "gemini_vector",
        similarity_threshold: float = 0.6,
        top_k_patterns: int = 5,
        use_reasoning: bool = True
    ):
        """
        Initialize Gemini Vector plug.
        
        Args:
            plug_id: Unique identifier
            similarity_threshold: Minimum similarity for matches (AC-03)
            top_k_patterns: Number of historical patterns to retrieve
            use_reasoning: Whether to use Gemini for reasoning
        """
        super().__init__(plug_id)
        
        self.similarity_threshold = similarity_threshold
        self.top_k_patterns = top_k_patterns
        self.use_reasoning = use_reasoning
        
        self._gemini_model = None
        self._embedding_model = None
        self._pinecone = None
    
    async def initialize(self) -> None:
        """Initialize Gemini and Pinecone connections."""
        # Configure Gemini
        if settings.google_api_key:
            genai.configure(api_key=settings.google_api_key)
            
            self._gemini_model = genai.GenerativeModel(settings.gemini_model)
            
            # Use embedding model for vector generation
            self._embedding_model = "models/embedding-001"
            
            logger.info("Gemini models initialized")
        else:
            logger.warning("Google API key not configured")
        
        # Get Pinecone client
        self._pinecone = get_pinecone_client()
        await self._pinecone.connect()
        
        self.status = PlugStatus.ACTIVE
        logger.info("Gemini Vector plug initialized")
    
    async def shutdown(self) -> None:
        """Shutdown plug and release resources."""
        if self._pinecone:
            await self._pinecone.disconnect()
        
        self._gemini_model = None
        self._embedding_model = None
        self.status = PlugStatus.INACTIVE
        logger.info("Gemini Vector plug shutdown")
    
    async def generate_signal(
        self,
        market_data: MarketDataBundle
    ) -> PlugSignal:
        """
        Generate signal by matching current market state to historical patterns.
        
        Args:
            market_data: Current market data bundle
        
        Returns:
            PlugSignal based on historical pattern matching
        """
        symbol = market_data.symbol
        
        # Generate market fingerprint embedding
        fingerprint = await self._generate_fingerprint(market_data)
        if fingerprint is None:
            return PlugSignal.null_signal(
                self.plug_id,
                "Failed to generate market fingerprint"
            )
        
        # Query similar historical patterns
        similar_patterns = await self._find_similar_patterns(
            fingerprint,
            symbol=symbol
        )
        
        # AC-03: Fail-safe if no patterns meet similarity threshold
        if not similar_patterns:
            return PlugSignal.null_signal(
                self.plug_id,
                f"No historical patterns above similarity threshold {self.similarity_threshold}"
            )
        
        # Analyze patterns to generate signal
        if self.use_reasoning and self._gemini_model:
            direction, confidence, reasoning = await self._reason_with_gemini(
                market_data, similar_patterns
            )
        else:
            direction, confidence, reasoning = self._analyze_patterns(
                similar_patterns
            )
        
        return PlugSignal(
            origin=self.plug_id,
            direction=direction,
            confidence=confidence,
            logic=reasoning,
            metadata={
                "patterns_found": len(similar_patterns),
                "avg_similarity": sum(p["score"] for p in similar_patterns) / len(similar_patterns),
                "pattern_ids": [p["id"] for p in similar_patterns]
            }
        )
    
    async def _generate_fingerprint(
        self,
        market_data: MarketDataBundle
    ) -> Optional[list[float]]:
        """
        Generate embedding vector from market data.
        
        The "fingerprint" captures the current market state in a way
        that can be compared to historical patterns.
        """
        try:
            # Extract features from market data
            features = self._extract_features(market_data)
            
            # Convert features to text for embedding
            feature_text = self._features_to_text(features)
            
            # Generate embedding using Gemini
            if self._embedding_model:
                result = genai.embed_content(
                    model=self._embedding_model,
                    content=feature_text,
                    task_type="RETRIEVAL_QUERY"
                )
                return result["embedding"]
            else:
                # Fallback: use feature values directly as pseudo-embedding
                # This is not ideal but allows the system to work without API
                return self._features_to_vector(features)
                
        except Exception as e:
            logger.error(f"Error generating fingerprint: {e}")
            return None
    
    def _extract_features(self, market_data: MarketDataBundle) -> dict[str, float]:
        """Extract numerical features from market data."""
        features = {}
        
        ohlcv = market_data.ohlcv
        if not ohlcv:
            return features
        
        # Sort by timestamp
        ohlcv = sorted(ohlcv, key=lambda x: x.timestamp)
        
        if len(ohlcv) >= 2:
            # Price changes
            current = ohlcv[-1].close
            
            if len(ohlcv) >= 2:
                features["price_change_1d"] = (current - ohlcv[-2].close) / ohlcv[-2].close
            
            if len(ohlcv) >= 6:
                features["price_change_5d"] = (current - ohlcv[-6].close) / ohlcv[-6].close
            
            if len(ohlcv) >= 21:
                features["price_change_20d"] = (current - ohlcv[-21].close) / ohlcv[-21].close
            
            # Volatility (20-day)
            if len(ohlcv) >= 20:
                returns = [
                    (ohlcv[i].close - ohlcv[i-1].close) / ohlcv[i-1].close
                    for i in range(max(1, len(ohlcv)-20), len(ohlcv))
                ]
                if returns:
                    mean_return = sum(returns) / len(returns)
                    variance = sum((r - mean_return)**2 for r in returns) / len(returns)
                    features["volatility_20d"] = variance ** 0.5
            
            # Volume ratio (current vs average)
            if len(ohlcv) >= 20:
                avg_volume = sum(o.volume for o in ohlcv[-20:]) / 20
                if avg_volume > 0:
                    features["volume_ratio"] = ohlcv[-1].volume / avg_volume
            
            # RSI-14 approximation
            if len(ohlcv) >= 15:
                gains = []
                losses = []
                for i in range(len(ohlcv)-14, len(ohlcv)):
                    change = ohlcv[i].close - ohlcv[i-1].close
                    if change > 0:
                        gains.append(change)
                        losses.append(0)
                    else:
                        gains.append(0)
                        losses.append(abs(change))
                
                avg_gain = sum(gains) / 14
                avg_loss = sum(losses) / 14
                
                if avg_loss > 0:
                    rs = avg_gain / avg_loss
                    features["rsi_14"] = 100 - (100 / (1 + rs))
                else:
                    features["rsi_14"] = 100
                
                # Normalize to [-1, 1]
                features["rsi_14"] = (features["rsi_14"] - 50) / 50
        
        return features
    
    def _features_to_text(self, features: dict[str, float]) -> str:
        """Convert features to text description for embedding."""
        parts = []
        
        for name, value in features.items():
            if "price_change" in name:
                direction = "up" if value > 0 else "down"
                parts.append(f"Price {name.split('_')[-1]} {direction} {abs(value)*100:.1f}%")
            elif "volatility" in name:
                level = "high" if value > 0.02 else "low" if value < 0.01 else "moderate"
                parts.append(f"{level} volatility")
            elif "volume_ratio" in name:
                level = "high" if value > 1.5 else "low" if value < 0.5 else "normal"
                parts.append(f"{level} volume")
            elif "rsi" in name:
                level = "overbought" if value > 0.4 else "oversold" if value < -0.4 else "neutral"
                parts.append(f"RSI {level}")
        
        return ". ".join(parts) if parts else "neutral market conditions"
    
    def _features_to_vector(self, features: dict[str, float]) -> list[float]:
        """Convert features to fixed-length vector (fallback embedding)."""
        # Create consistent vector regardless of which features are present
        vector = []
        for feature_name in self.FINGERPRINT_FEATURES:
            value = features.get(feature_name, 0.0)
            # Normalize to reasonable range
            vector.append(max(-1.0, min(1.0, value)))
        
        # Pad to expected dimension
        target_dim = 768
        while len(vector) < target_dim:
            vector.append(0.0)
        
        return vector[:target_dim]
    
    async def _find_similar_patterns(
        self,
        fingerprint: list[float],
        symbol: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """
        Find similar historical patterns in vector database.
        
        AC-03: Only returns patterns with similarity >= threshold.
        """
        if not self._pinecone:
            return []
        
        # Build filter if symbol specified
        filter_dict = {"symbol": symbol} if symbol else None
        
        # Query Pinecone with similarity threshold enforced
        results = await self._pinecone.query(
            vector=fingerprint,
            top_k=self.top_k_patterns,
            filter_dict=filter_dict,
            include_metadata=True
        )
        
        # Results are already filtered by similarity threshold in Pinecone client
        return results
    
    def _analyze_patterns(
        self,
        patterns: list[dict[str, Any]]
    ) -> tuple[float, float, str]:
        """
        Analyze historical patterns to derive signal.
        
        Returns:
            Tuple of (direction, confidence, reasoning)
        """
        if not patterns:
            return 0.0, 0.0, "No patterns to analyze"
        
        # Extract outcomes from patterns
        outcomes = []
        for p in patterns:
            metadata = p.get("metadata", {})
            outcome = metadata.get("outcome", {})
            if isinstance(outcome, dict):
                direction = outcome.get("direction", 0)
                outcomes.append({
                    "direction": direction,
                    "similarity": p["score"],
                    "return": outcome.get("return_5d", 0)
                })
        
        if not outcomes:
            return 0.0, 0.0, "No outcome data in patterns"
        
        # Weight by similarity
        total_weight = sum(o["similarity"] for o in outcomes)
        if total_weight == 0:
            return 0.0, 0.0, "Zero total similarity weight"
        
        weighted_direction = sum(
            o["direction"] * o["similarity"] for o in outcomes
        ) / total_weight
        
        # Confidence based on agreement and similarity
        directions = [o["direction"] for o in outcomes]
        agreement = 1 - (max(directions) - min(directions)) / 2
        avg_similarity = total_weight / len(outcomes)
        
        confidence = agreement * avg_similarity
        
        # Build reasoning
        avg_return = sum(o["return"] for o in outcomes) / len(outcomes)
        direction_str = "bullish" if weighted_direction > 0 else "bearish" if weighted_direction < 0 else "neutral"
        
        reasoning = (
            f"Historical pattern analysis: {len(patterns)} similar patterns found. "
            f"Average similarity: {avg_similarity:.2f}. "
            f"Consensus: {direction_str} with avg 5-day return of {avg_return*100:.1f}%"
        )
        
        return weighted_direction, confidence, reasoning
    
    async def _reason_with_gemini(
        self,
        market_data: MarketDataBundle,
        patterns: list[dict[str, Any]]
    ) -> tuple[float, float, str]:
        """
        Use Gemini to reason about patterns and current market state.
        
        Returns:
            Tuple of (direction, confidence, reasoning)
        """
        if not self._gemini_model:
            return self._analyze_patterns(patterns)
        
        try:
            # Build prompt
            prompt = self._build_reasoning_prompt(market_data, patterns)
            
            # Generate response
            response = await asyncio.to_thread(
                self._gemini_model.generate_content,
                prompt
            )
            
            # Parse response
            return self._parse_gemini_response(response.text)
            
        except Exception as e:
            logger.error(f"Gemini reasoning error: {e}")
            return self._analyze_patterns(patterns)
    
    def _build_reasoning_prompt(
        self,
        market_data: MarketDataBundle,
        patterns: list[dict[str, Any]]
    ) -> str:
        """Build prompt for Gemini reasoning."""
        # Current market summary
        features = self._extract_features(market_data)
        current_state = self._features_to_text(features)
        
        # Historical patterns summary
        pattern_summaries = []
        for i, p in enumerate(patterns[:3]):  # Top 3
            metadata = p.get("metadata", {})
            outcome = metadata.get("outcome", {})
            pattern_summaries.append(
                f"Pattern {i+1} (similarity: {p['score']:.2f}): "
                f"resulted in {outcome.get('return_5d', 0)*100:.1f}% return over 5 days"
            )
        
        patterns_text = "\n".join(pattern_summaries)
        
        return f"""You are a quantitative trading analyst. Analyze the following market data and historical patterns to determine a trading signal.

Current Market State for {market_data.symbol}:
{current_state}

Similar Historical Patterns:
{patterns_text}

Based on this analysis, provide:
1. Direction: A number from -1.0 (strong sell) to 1.0 (strong buy)
2. Confidence: A number from 0.0 to 1.0
3. Brief reasoning (1-2 sentences)

Format your response exactly as:
DIRECTION: [number]
CONFIDENCE: [number]
REASONING: [text]"""
    
    def _parse_gemini_response(
        self,
        response: str
    ) -> tuple[float, float, str]:
        """Parse Gemini response into signal components."""
        direction = 0.0
        confidence = 0.5
        reasoning = "Unable to parse Gemini response"
        
        try:
            lines = response.strip().split("\n")
            for line in lines:
                if line.startswith("DIRECTION:"):
                    direction = float(line.split(":")[1].strip())
                    direction = max(-1.0, min(1.0, direction))
                elif line.startswith("CONFIDENCE:"):
                    confidence = float(line.split(":")[1].strip())
                    confidence = max(0.0, min(1.0, confidence))
                elif line.startswith("REASONING:"):
                    reasoning = line.split(":", 1)[1].strip()
        except Exception as e:
            logger.warning(f"Error parsing Gemini response: {e}")
        
        return direction, confidence, reasoning
    
    async def store_pattern(
        self,
        market_data: MarketDataBundle,
        outcome: dict[str, Any]
    ) -> bool:
        """
        Store a market pattern with its outcome for future reference.
        
        Args:
            market_data: Market data at pattern time
            outcome: What happened after (returns, etc.)
        
        Returns:
            True if stored successfully
        """
        if not self._pinecone:
            return False
        
        # Generate fingerprint
        fingerprint = await self._generate_fingerprint(market_data)
        if not fingerprint:
            return False
        
        # Create pattern ID
        pattern_id = hashlib.md5(
            f"{market_data.symbol}_{market_data.timestamp.isoformat()}".encode()
        ).hexdigest()
        
        # Store in Pinecone
        return await self._pinecone.store_market_pattern(
            pattern_id=pattern_id,
            embedding=fingerprint,
            outcome=outcome,
            metadata={
                "symbol": market_data.symbol,
                "timestamp": market_data.timestamp.isoformat(),
                "features": self._extract_features(market_data)
            }
        )

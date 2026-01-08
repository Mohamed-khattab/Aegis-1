"""
News Sentry Plug for Aegis-1

Real-time NLP analysis of news and social media feeds.
Based on PRD Section 3 - Plug 01: The News Sentry (Unstructured Data).
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from textblob import TextBlob

from plugs.base import BasePlug, PlugStatus
from models.signals import PlugSignal
from models.market_data import MarketDataBundle, NewsItem
from config.settings import settings


logger = logging.getLogger(__name__)


class NewsSentryPlug(BasePlug):
    """
    News Sentry plug for sentiment analysis.
    
    From PRD:
    - Requirement: Real-time NLP analysis of feeds (Bloomberg, Reuters, Twitter/X)
    - Success Metric: Sentiment correlation to price action within 5-minute window
    - Logic: Must output a normalized Impact Score [-1.0 to 1.0]
    """
    
    # Keywords that amplify sentiment impact
    BULLISH_KEYWORDS = {
        "surge", "soar", "rally", "breakthrough", "beat", "exceed",
        "upgrade", "bullish", "buy", "growth", "profit", "gains",
        "record", "high", "strong", "positive", "optimistic"
    }
    
    BEARISH_KEYWORDS = {
        "crash", "plunge", "fall", "miss", "decline", "downgrade",
        "bearish", "sell", "loss", "weak", "negative", "concern",
        "fear", "risk", "warning", "cut", "layoff", "recession"
    }
    
    # Source credibility weights
    SOURCE_WEIGHTS = {
        "bloomberg": 1.2,
        "reuters": 1.2,
        "reuters_business": 1.15,
        "reuters_markets": 1.15,
        "financial_times": 1.1,
        "wsj": 1.1,
        "cnbc": 1.0,
        "marketwatch": 1.0,
        "yahoo_finance": 0.9,
        "twitter": 0.7,
        "reddit": 0.6,
        "default": 0.8
    }
    
    def __init__(
        self,
        plug_id: str = "news_sentry",
        lookback_minutes: int = 30,
        min_news_items: int = 1,
        use_transformers: bool = False
    ):
        """
        Initialize News Sentry plug.
        
        Args:
            plug_id: Unique identifier
            lookback_minutes: Time window for news analysis
            min_news_items: Minimum news items required to generate signal
            use_transformers: Use transformer models for better accuracy
        """
        super().__init__(plug_id)
        
        self.lookback_minutes = lookback_minutes
        self.min_news_items = min_news_items
        self.use_transformers = use_transformers
        
        self._sentiment_model = None
        self._recent_sentiments: dict[str, list[tuple[datetime, float]]] = {}
    
    async def initialize(self) -> None:
        """Initialize NLP models."""
        if self.use_transformers:
            try:
                from transformers import pipeline
                self._sentiment_model = pipeline(
                    "sentiment-analysis",
                    model="ProsusAI/finbert",
                    device=-1  # CPU
                )
                logger.info("Loaded FinBERT sentiment model")
            except Exception as e:
                logger.warning(f"Failed to load transformer model: {e}")
                self._sentiment_model = None
        
        self.status = PlugStatus.ACTIVE
        logger.info(f"News Sentry plug initialized")
    
    async def shutdown(self) -> None:
        """Shutdown plug and release resources."""
        self._sentiment_model = None
        self.status = PlugStatus.INACTIVE
        logger.info("News Sentry plug shutdown")
    
    async def generate_signal(
        self,
        market_data: MarketDataBundle
    ) -> PlugSignal:
        """
        Generate signal from news sentiment analysis.
        
        Args:
            market_data: Market data bundle including news items
        
        Returns:
            PlugSignal with impact score [-1.0 to 1.0]
        """
        symbol = market_data.symbol
        news_items = market_data.news
        
        # Filter news by time window
        cutoff = datetime.utcnow() - timedelta(minutes=self.lookback_minutes)
        relevant_news = [
            n for n in news_items
            if n.timestamp >= cutoff and (not n.symbols or symbol in n.symbols or not n.symbols)
        ]
        
        # Not enough news - return neutral signal
        if len(relevant_news) < self.min_news_items:
            return PlugSignal.null_signal(
                self.plug_id,
                f"Insufficient news items ({len(relevant_news)} < {self.min_news_items})"
            )
        
        # Analyze sentiment for each news item
        sentiments = []
        for news in relevant_news:
            sentiment = await self._analyze_sentiment(news)
            if sentiment is not None:
                sentiments.append(sentiment)
        
        if not sentiments:
            return PlugSignal.null_signal(
                self.plug_id,
                "No valid sentiment scores computed"
            )
        
        # Calculate weighted average sentiment
        total_weight = sum(s["weight"] for s in sentiments)
        if total_weight == 0:
            return PlugSignal.null_signal(self.plug_id, "Zero total weight")
        
        weighted_sentiment = sum(
            s["score"] * s["weight"] for s in sentiments
        ) / total_weight
        
        # Calculate confidence based on agreement and volume
        sentiment_std = self._calculate_std([s["score"] for s in sentiments])
        agreement_factor = max(0, 1 - sentiment_std)
        volume_factor = min(1.0, len(sentiments) / 10)
        confidence = (agreement_factor * 0.6 + volume_factor * 0.4)
        
        # Store for correlation tracking
        self._store_sentiment(symbol, weighted_sentiment)
        
        # Build reasoning
        reasoning = self._build_reasoning(relevant_news, sentiments, weighted_sentiment)
        
        return PlugSignal(
            origin=self.plug_id,
            direction=weighted_sentiment,
            confidence=confidence,
            logic=reasoning,
            metadata={
                "news_count": len(relevant_news),
                "sentiment_scores": [s["score"] for s in sentiments],
                "sources": list(set(s["source"] for s in sentiments))
            }
        )
    
    async def _analyze_sentiment(self, news: NewsItem) -> Optional[dict[str, Any]]:
        """
        Analyze sentiment of a news item.
        
        Args:
            news: News item to analyze
        
        Returns:
            Dict with score, confidence, weight, and source
        """
        text = f"{news.title} {news.content}".strip()
        if not text:
            return None
        
        try:
            # Get base sentiment
            if self._sentiment_model:
                score, confidence = await self._transformer_sentiment(text)
            else:
                score, confidence = self._textblob_sentiment(text)
            
            # Apply keyword amplification
            score = self._apply_keyword_amplification(text, score)
            
            # Get source credibility weight
            source_weight = self.SOURCE_WEIGHTS.get(
                news.source.lower(),
                self.SOURCE_WEIGHTS["default"]
            )
            
            # Recency weight (more recent = higher weight)
            age_minutes = (datetime.utcnow() - news.timestamp).total_seconds() / 60
            recency_weight = max(0.5, 1 - (age_minutes / self.lookback_minutes))
            
            final_weight = source_weight * recency_weight * confidence
            
            return {
                "score": max(-1.0, min(1.0, score)),
                "confidence": confidence,
                "weight": final_weight,
                "source": news.source,
                "title": news.title[:100]
            }
            
        except Exception as e:
            logger.error(f"Error analyzing sentiment: {e}")
            return None
    
    async def _transformer_sentiment(self, text: str) -> tuple[float, float]:
        """
        Analyze sentiment using transformer model.
        
        Returns:
            Tuple of (score, confidence)
        """
        # Truncate text for model
        text = text[:512]
        
        # Run in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self._sentiment_model(text)[0]
        )
        
        label = result["label"].lower()
        confidence = result["score"]
        
        # Convert FinBERT labels to score
        if label == "positive":
            score = confidence
        elif label == "negative":
            score = -confidence
        else:  # neutral
            score = 0.0
            confidence = 0.5
        
        return score, confidence
    
    def _textblob_sentiment(self, text: str) -> tuple[float, float]:
        """
        Analyze sentiment using TextBlob (fallback).
        
        Returns:
            Tuple of (score, confidence)
        """
        blob = TextBlob(text)
        
        # TextBlob polarity is -1 to 1
        score = blob.sentiment.polarity
        
        # Subjectivity as proxy for confidence
        # More subjective text = higher confidence in sentiment
        subjectivity = blob.sentiment.subjectivity
        confidence = 0.3 + (subjectivity * 0.4)  # Base 0.3, max 0.7
        
        return score, confidence
    
    def _apply_keyword_amplification(self, text: str, base_score: float) -> float:
        """
        Amplify sentiment based on financial keywords.
        
        Args:
            text: Text to analyze
            base_score: Base sentiment score
        
        Returns:
            Amplified score
        """
        text_lower = text.lower()
        
        bullish_count = sum(1 for kw in self.BULLISH_KEYWORDS if kw in text_lower)
        bearish_count = sum(1 for kw in self.BEARISH_KEYWORDS if kw in text_lower)
        
        keyword_bias = (bullish_count - bearish_count) * 0.1
        
        # Amplify in the direction of base sentiment
        if base_score >= 0:
            amplified = base_score + keyword_bias * (1 - base_score)
        else:
            amplified = base_score + keyword_bias * (1 + base_score)
        
        return max(-1.0, min(1.0, amplified))
    
    def _calculate_std(self, values: list[float]) -> float:
        """Calculate standard deviation of values."""
        if len(values) < 2:
            return 0.0
        
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        return variance ** 0.5
    
    def _store_sentiment(self, symbol: str, sentiment: float) -> None:
        """Store sentiment for correlation tracking."""
        if symbol not in self._recent_sentiments:
            self._recent_sentiments[symbol] = []
        
        self._recent_sentiments[symbol].append((datetime.utcnow(), sentiment))
        
        # Keep only last hour
        cutoff = datetime.utcnow() - timedelta(hours=1)
        self._recent_sentiments[symbol] = [
            (ts, s) for ts, s in self._recent_sentiments[symbol]
            if ts >= cutoff
        ]
    
    def _build_reasoning(
        self,
        news: list[NewsItem],
        sentiments: list[dict],
        final_score: float
    ) -> str:
        """Build human-readable reasoning string."""
        direction = "bullish" if final_score > 0.1 else "bearish" if final_score < -0.1 else "neutral"
        
        # Get top sentiment contributors
        top_news = sorted(sentiments, key=lambda x: abs(x["score"]), reverse=True)[:3]
        
        headlines = "; ".join(s["title"][:50] for s in top_news)
        
        return (
            f"News sentiment is {direction} (score: {final_score:.2f}) "
            f"based on {len(news)} articles. "
            f"Key headlines: {headlines}"
        )
    
    def get_sentiment_history(
        self,
        symbol: str,
        minutes: int = 60
    ) -> list[tuple[datetime, float]]:
        """
        Get recent sentiment history for a symbol.
        
        Args:
            symbol: Symbol to get history for
            minutes: Lookback period
        
        Returns:
            List of (timestamp, sentiment) tuples
        """
        cutoff = datetime.utcnow() - timedelta(minutes=minutes)
        history = self._recent_sentiments.get(symbol, [])
        return [(ts, s) for ts, s in history if ts >= cutoff]

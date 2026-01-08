"""
News Feed Aggregator for Aegis-1

Aggregates news from multiple sources for the News Sentry plug.
Based on PRD Section 4 - Feed 02: News & Social Media Feed.
"""

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Any, AsyncIterator, Optional
from uuid import uuid4

import aiohttp
import feedparser

from feeds.base import BaseFeed, FeedStatus, FeedType
from models.market_data import NewsItem
from config.settings import settings


logger = logging.getLogger(__name__)


class NewsFeed(BaseFeed):
    """
    News feed aggregator for financial news and social media.
    
    Sources:
    - RSS feeds (Financial Times, Bloomberg, Reuters, etc.)
    - Twitter/X API (optional)
    - News API (optional)
    
    From PRD Section 4:
    - Format: Structured JSON with source, timestamp, content, sentiment metadata
    - Processing: Raw feeds are normalized and enriched with metadata
    """
    
    # Default RSS feeds for financial news
    DEFAULT_RSS_FEEDS = {
        "reuters_business": "https://feeds.reuters.com/reuters/businessNews",
        "reuters_markets": "https://feeds.reuters.com/reuters/marketsNews",
        "yahoo_finance": "https://finance.yahoo.com/news/rssindex",
        "cnbc": "https://www.cnbc.com/id/10001147/device/rss/rss.html",
        "marketwatch": "https://feeds.marketwatch.com/marketwatch/topstories",
    }
    
    def __init__(
        self,
        rss_feeds: dict[str, str] | None = None,
        symbols: list[str] | None = None,
        poll_interval: int = 60,
        twitter_enabled: bool = False,
        news_api_enabled: bool = False
    ):
        """
        Initialize news feed.
        
        Args:
            rss_feeds: Dict of feed_name -> RSS URL
            symbols: Symbols to filter news for
            poll_interval: Seconds between RSS polls
            twitter_enabled: Enable Twitter/X feed
            news_api_enabled: Enable News API feed
        """
        super().__init__(
            feed_id="news",
            feed_type=FeedType.NEWS,
            symbols=symbols or []
        )
        
        self.rss_feeds = rss_feeds or self.DEFAULT_RSS_FEEDS
        self.poll_interval = poll_interval
        self.twitter_enabled = twitter_enabled
        self.news_api_enabled = news_api_enabled
        
        self._session: Optional[aiohttp.ClientSession] = None
        self._seen_ids: set[str] = set()
        self._news_queue: asyncio.Queue[NewsItem] = asyncio.Queue()
        self._poll_task: Optional[asyncio.Task] = None
    
    async def connect(self) -> None:
        """Initialize HTTP session and start polling."""
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30)
        )
        
        self._connected = True
        self.status = FeedStatus.CONNECTED
        
        # Start polling task
        self._poll_task = asyncio.create_task(self._poll_loop())
        
        logger.info(f"News feed connected with {len(self.rss_feeds)} RSS sources")
    
    async def disconnect(self) -> None:
        """Stop polling and close session."""
        self._should_reconnect = False
        self._connected = False
        
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        
        if self._session:
            await self._session.close()
            self._session = None
        
        self.status = FeedStatus.DISCONNECTED
        logger.info("News feed disconnected")
    
    async def subscribe(self, symbols: list[str]) -> None:
        """Add symbols to filter news for."""
        for symbol in symbols:
            if symbol not in self.symbols:
                self.symbols.append(symbol)
    
    async def unsubscribe(self, symbols: list[str]) -> None:
        """Remove symbols from filter."""
        self.symbols = [s for s in self.symbols if s not in symbols]
    
    async def _poll_loop(self) -> None:
        """Background task to poll RSS feeds."""
        while self._connected:
            try:
                await self._poll_all_sources()
                await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in news poll loop: {e}")
                await asyncio.sleep(10)  # Brief pause before retry
    
    async def _poll_all_sources(self) -> None:
        """Poll all configured news sources."""
        tasks = []
        
        # RSS feeds
        for name, url in self.rss_feeds.items():
            tasks.append(self._fetch_rss(name, url))
        
        # Twitter (if enabled)
        if self.twitter_enabled and settings.twitter_bearer_token:
            tasks.append(self._fetch_twitter())
        
        # News API (if enabled)
        if self.news_api_enabled and settings.news_api_key:
            tasks.append(self._fetch_news_api())
        
        # Run all fetches concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"News fetch error: {result}")
    
    async def _fetch_rss(self, source_name: str, url: str) -> None:
        """Fetch and parse RSS feed."""
        if not self._session:
            return
        
        try:
            async with self._session.get(url) as response:
                if response.status != 200:
                    logger.warning(f"RSS fetch failed for {source_name}: {response.status}")
                    return
                
                content = await response.text()
            
            # Parse RSS
            feed = feedparser.parse(content)
            
            for entry in feed.entries:
                news_id = self._generate_id(entry.get("link", "") + entry.get("title", ""))
                
                # Skip if already seen
                if news_id in self._seen_ids:
                    continue
                
                self._seen_ids.add(news_id)
                
                # Parse timestamp
                timestamp = datetime.utcnow()
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    try:
                        timestamp = datetime(*entry.published_parsed[:6])
                    except Exception:
                        pass
                
                # Extract symbols mentioned
                mentioned_symbols = self._extract_symbols(
                    entry.get("title", "") + " " + entry.get("summary", "")
                )
                
                news_item = NewsItem(
                    id=news_id,
                    timestamp=timestamp,
                    source=source_name,
                    title=entry.get("title", ""),
                    content=entry.get("summary", entry.get("description", "")),
                    url=entry.get("link"),
                    symbols=mentioned_symbols,
                    category="rss",
                    tags=self._extract_tags(entry)
                )
                
                await self._news_queue.put(news_item)
                
        except Exception as e:
            logger.error(f"Error fetching RSS from {source_name}: {e}")
    
    async def _fetch_twitter(self) -> None:
        """Fetch tweets from Twitter/X API."""
        if not self._session or not settings.twitter_bearer_token:
            return
        
        try:
            # Twitter API v2 - Search recent tweets
            # Searching for cashtag mentions
            query_terms = [f"${s}" for s in self.symbols[:10]]  # Limit to 10 symbols
            if not query_terms:
                query_terms = ["$SPY", "$QQQ"]  # Default market ETFs
            
            query = " OR ".join(query_terms) + " -is:retweet lang:en"
            
            url = "https://api.twitter.com/2/tweets/search/recent"
            params = {
                "query": query,
                "max_results": 50,
                "tweet.fields": "created_at,author_id,text"
            }
            headers = {
                "Authorization": f"Bearer {settings.twitter_bearer_token}"
            }
            
            async with self._session.get(url, params=params, headers=headers) as response:
                if response.status != 200:
                    logger.warning(f"Twitter API error: {response.status}")
                    return
                
                data = await response.json()
            
            for tweet in data.get("data", []):
                news_id = f"twitter_{tweet['id']}"
                
                if news_id in self._seen_ids:
                    continue
                
                self._seen_ids.add(news_id)
                
                timestamp = datetime.fromisoformat(
                    tweet["created_at"].replace("Z", "+00:00")
                ).replace(tzinfo=None)
                
                news_item = NewsItem(
                    id=news_id,
                    timestamp=timestamp,
                    source="twitter",
                    title="",
                    content=tweet["text"],
                    symbols=self._extract_symbols(tweet["text"]),
                    category="social",
                    tags=["twitter"]
                )
                
                await self._news_queue.put(news_item)
                
        except Exception as e:
            logger.error(f"Error fetching Twitter: {e}")
    
    async def _fetch_news_api(self) -> None:
        """Fetch from News API."""
        if not self._session or not settings.news_api_key:
            return
        
        try:
            url = "https://newsapi.org/v2/top-headlines"
            params = {
                "category": "business",
                "country": "us",
                "apiKey": settings.news_api_key
            }
            
            async with self._session.get(url, params=params) as response:
                if response.status != 200:
                    logger.warning(f"News API error: {response.status}")
                    return
                
                data = await response.json()
            
            for article in data.get("articles", []):
                news_id = self._generate_id(article.get("url", str(uuid4())))
                
                if news_id in self._seen_ids:
                    continue
                
                self._seen_ids.add(news_id)
                
                timestamp = datetime.utcnow()
                if article.get("publishedAt"):
                    try:
                        timestamp = datetime.fromisoformat(
                            article["publishedAt"].replace("Z", "+00:00")
                        ).replace(tzinfo=None)
                    except Exception:
                        pass
                
                content = article.get("description", "") or article.get("content", "")
                
                news_item = NewsItem(
                    id=news_id,
                    timestamp=timestamp,
                    source=article.get("source", {}).get("name", "newsapi"),
                    title=article.get("title", ""),
                    content=content,
                    url=article.get("url"),
                    symbols=self._extract_symbols(
                        article.get("title", "") + " " + content
                    ),
                    author=article.get("author"),
                    category="news",
                    tags=["newsapi"]
                )
                
                await self._news_queue.put(news_item)
                
        except Exception as e:
            logger.error(f"Error fetching News API: {e}")
    
    def _generate_id(self, content: str) -> str:
        """Generate unique ID from content hash."""
        return hashlib.md5(content.encode()).hexdigest()
    
    def _extract_symbols(self, text: str) -> list[str]:
        """Extract stock symbols mentioned in text."""
        import re
        
        # Match cashtags ($AAPL) and common ticker patterns
        cashtags = re.findall(r'\$([A-Z]{1,5})\b', text.upper())
        
        # Filter to only our tracked symbols if we have any
        if self.symbols:
            cashtags = [s for s in cashtags if s in self.symbols]
        
        return list(set(cashtags))
    
    def _extract_tags(self, entry: Any) -> list[str]:
        """Extract tags/categories from RSS entry."""
        tags = []
        
        if hasattr(entry, "tags"):
            for tag in entry.tags:
                if hasattr(tag, "term"):
                    tags.append(tag.term.lower())
        
        return tags[:10]  # Limit to 10 tags
    
    async def _stream_data(self) -> AsyncIterator[dict[str, Any]]:
        """Stream news items from the queue."""
        while self._connected:
            try:
                news_item = await asyncio.wait_for(
                    self._news_queue.get(),
                    timeout=1.0
                )
                yield {"type": "news", "data": news_item}
            except asyncio.TimeoutError:
                continue
    
    async def _process_message(
        self,
        raw_data: dict[str, Any]
    ) -> NewsItem | None:
        """Process queued news item."""
        if raw_data.get("type") == "news":
            return raw_data.get("data")
        return None
    
    async def get_recent_news(
        self,
        symbol: Optional[str] = None,
        limit: int = 50,
        hours: int = 24
    ) -> list[NewsItem]:
        """
        Get recent news items.
        
        Args:
            symbol: Filter by symbol
            limit: Maximum items to return
            hours: Look back period in hours
        
        Returns:
            List of recent news items
        """
        # This would typically query from a database
        # For now, return items from the queue
        items = []
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        
        while not self._news_queue.empty() and len(items) < limit:
            try:
                item = self._news_queue.get_nowait()
                if item.timestamp >= cutoff:
                    if symbol is None or symbol in item.symbols:
                        items.append(item)
            except asyncio.QueueEmpty:
                break
        
        return items

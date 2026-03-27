"""
News Tool — Latest headlines from NewsAPI.org.
Search news by topic or get top headlines.
"""

import logging
import httpx
from typing import Optional, List
from app.tools.base import BaseTool, ToolResult
from app.config import settings

logger = logging.getLogger(__name__)

NEWS_URL = "https://newsapi.org/v2/everything"
HEADLINES_URL = "https://newsapi.org/v2/top-headlines"


class NewsTool(BaseTool):
    """Tool for fetching latest news and headlines"""

    @property
    def name(self) -> str:
        return "news"

    @property
    def description(self) -> str:
        return """Get latest news and headlines by topic or region.

Examples:
- "Latest news on AI"
- "What's trending in India?"
- "Show me top headlines on startups"
- "Any recent news on cryptocurrency?"
        """

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "News topic or search query (e.g., 'AI', 'startups', 'India')"
                },
                "country": {
                    "type": "string",
                    "description": "Optional country code for top headlines (e.g., 'in' for India, 'us' for USA)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of articles to return (1-10, default 5)"
                }
            },
            "required": ["query"]
        }

    async def execute(self, query: str, country: str = None,
                     limit: int = 5, **kwargs) -> ToolResult:
        """Fetch news articles"""
        try:
            limit = min(max(limit, 1), 10)  # Clamp to 1-10

            if country:
                # Use top headlines endpoint
                articles = await self._get_top_headlines(country, limit)
            else:
                # Use search endpoint
                articles = await self._search_news(query, limit)

            if not articles:
                return ToolResult(
                    tool_name=self.name,
                    success=False,
                    error=f"No news found for '{query}'"
                )

            return ToolResult(
                tool_name=self.name,
                success=True,
                data={
                    "query": query,
                    "count": len(articles),
                    "articles": articles
                }
            )

        except Exception as e:
            logger.error(f"News tool error: {e}")
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(e)
            )

    async def _search_news(self, query: str, limit: int = 5) -> Optional[List[dict]]:
        """Search news by topic"""
        if not settings.news_api_key:
            logger.error("NewsAPI key not configured")
            return None

        params = {
            "q": query,
            "apiKey": settings.news_api_key,
            "sortBy": "publishedAt",
            "pageSize": limit,
            "language": "en"
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(NEWS_URL, params=params, timeout=10.0)
                response.raise_for_status()

                data = response.json()

                if data["status"] != "ok":
                    logger.error(f"NewsAPI error: {data.get('message')}")
                    return None

                articles = []
                for article in data.get("articles", [])[:limit]:
                    articles.append({
                        "title": article["title"],
                        "source": article.get("source", {}).get("name", "Unknown"),
                        "published": article.get("publishedAt", "").split("T")[0],
                        "description": article.get("description", ""),
                        "url": article.get("url", "")
                    })

                return articles

        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch news: {e}")
            return None

    async def _get_top_headlines(self, country: str, limit: int = 5) -> Optional[List[dict]]:
        """Get top headlines for a country"""
        if not settings.news_api_key:
            return None

        params = {
            "country": country.lower(),
            "apiKey": settings.news_api_key,
            "pageSize": limit
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(HEADLINES_URL, params=params, timeout=10.0)
                response.raise_for_status()

                data = response.json()

                if data["status"] != "ok":
                    logger.error(f"NewsAPI error: {data.get('message')}")
                    return None

                articles = []
                for article in data.get("articles", [])[:limit]:
                    articles.append({
                        "title": article["title"],
                        "source": article.get("source", {}).get("name", "Unknown"),
                        "published": article.get("publishedAt", "").split("T")[0],
                        "description": article.get("description", ""),
                        "url": article.get("url", "")
                    })

                return articles

        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch headlines: {e}")
            return None

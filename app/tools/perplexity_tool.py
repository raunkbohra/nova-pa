"""
Perplexity Tool — Real-time web research via Perplexity AI.
Returns cited, up-to-date answers for any research query.
"""

import logging
import httpx
from app.tools.base import BaseTool, ToolResult
from app.config import settings

logger = logging.getLogger(__name__)

PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"


class PerplexityTool(BaseTool):
    """Tool for real-time web research via Perplexity AI"""

    @property
    def name(self) -> str:
        return "research"

    @property
    def description(self) -> str:
        return """Research any topic using real-time web search via Perplexity AI.
Use this for current events, company research, people, prices, facts, news, or anything requiring up-to-date information.

Examples:
- "Research Sequoia Capital's latest investments"
- "What is the current USD to INR rate?"
- "Who is Raj Mehta from XYZ Ventures?"
- "Latest news about OpenAI"
- "What does Stripe do?"
        """

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The research question or topic to search for"
                },
                "mode": {
                    "type": "string",
                    "enum": ["quick", "deep"],
                    "description": "quick = fast answer, deep = detailed research (default: quick)"
                }
            },
            "required": ["query"]
        }

    async def execute(self, query: str, mode: str = "quick", **kwargs) -> ToolResult:
        """Execute a Perplexity search"""
        api_key = getattr(settings, "perplexity_api_key", None)
        if not api_key:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error="Perplexity API key not configured"
            )

        model = "sonar" if mode == "quick" else "sonar-pro"

        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "Be precise and concise. Include key facts and cite sources where relevant."
                },
                {
                    "role": "user",
                    "content": query
                }
            ],
            "max_tokens": 1024,
            "return_citations": True
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    PERPLEXITY_URL,
                    json=payload,
                    headers=headers,
                    timeout=30.0
                )
                response.raise_for_status()
                data = response.json()

            answer = data["choices"][0]["message"]["content"]
            citations = data.get("citations", [])

            result = {"answer": answer, "query": query}
            if citations:
                result["sources"] = citations[:5]

            return ToolResult(
                tool_name=self.name,
                success=True,
                data=result
            )

        except httpx.HTTPError as e:
            logger.error(f"Perplexity API error: {e}")
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(e)
            )
        except Exception as e:
            logger.error(f"Perplexity tool error: {e}")
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(e)
            )

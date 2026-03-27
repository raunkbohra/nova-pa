"""
Cost Tool — Track Claude API token usage and estimate spend.
Uses logged usage data from the database.
"""

import logging
from app.tools.base import BaseTool, ToolResult
from app.memory import get_usage_stats, AsyncSessionLocal

logger = logging.getLogger(__name__)

# Haiku 4.5 pricing (USD per 1M tokens)
HAIKU_INPUT_COST_PER_M = 0.80
HAIKU_OUTPUT_COST_PER_M = 4.00


class CostTool(BaseTool):

    def __init__(self):
        pass

    @property
    def name(self) -> str:
        return "api_cost"

    @property
    def description(self) -> str:
        return """Check Claude API token usage and estimated cost.

Examples:
- "How much have I spent on API this month?"
- "What's my API cost today?"
- "Show me API usage for the last 7 days"
        """

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Number of days to look back (default 30, use 1 for today, 7 for this week)"
                }
            },
            "required": []
        }

    async def execute(self, days: int = 30, **kwargs) -> ToolResult:
        try:
            days = max(1, min(days, 365))
            async with AsyncSessionLocal() as session:
                stats = await get_usage_stats(session, days)

            input_cost = (stats["total_input"] / 1_000_000) * HAIKU_INPUT_COST_PER_M
            output_cost = (stats["total_output"] / 1_000_000) * HAIKU_OUTPUT_COST_PER_M
            total_cost = input_cost + output_cost

            return ToolResult(
                tool_name=self.name,
                success=True,
                data={
                    "days": days,
                    "total_requests": stats["total_requests"],
                    "input_tokens": stats["total_input"],
                    "output_tokens": stats["total_output"],
                    "input_cost_usd": round(input_cost, 4),
                    "output_cost_usd": round(output_cost, 4),
                    "total_cost_usd": round(total_cost, 4),
                    "model": "claude-haiku-4-5",
                    "pricing": f"${HAIKU_INPUT_COST_PER_M}/1M input, ${HAIKU_OUTPUT_COST_PER_M}/1M output"
                }
            )
        except Exception as e:
            logger.error(f"Cost tool error: {e}")
            return ToolResult(tool_name=self.name, success=False, error=str(e))

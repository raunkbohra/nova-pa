"""
Tool registry and initialization.
All available tools are registered here.
"""

import logging
from typing import Dict, List
from app.tools.base import BaseTool

logger = logging.getLogger(__name__)

# Tool registry - add tools here as they're implemented
TOOLS: Dict[str, BaseTool] = {}


def register_tool(tool: BaseTool):
    """Register a tool in the registry"""
    TOOLS[tool.name] = tool
    logger.info(f"Registered tool: {tool.name}")


def get_tools() -> List[BaseTool]:
    """Get all registered tools"""
    return list(TOOLS.values())


def get_tool(name: str) -> BaseTool:
    """Get a specific tool by name"""
    return TOOLS.get(name)


def get_claude_tools() -> List[dict]:
    """Get all tools in Claude API format"""
    return [tool.to_claude_tool() for tool in TOOLS.values()]


# Import and register tools
from app.tools.notes_tool import NotesTool
from app.tools.calendar_tool import CalendarTool
from app.tools.email_tool import EmailTool
from app.tools.reminder_tool import ReminderTool
from app.tools.weather_tool import WeatherTool
from app.tools.news_tool import NewsTool
from app.tools.perplexity_tool import PerplexityTool
from app.tools.whatsapp_tool import WhatsAppTool
from app.tools.contacts_tool import ContactsTool
from app.tools.cost_tool import CostTool
from app.tools.memory_tool import MemoryTool
from app.tools.sales_tool import SalesTool

register_tool(NotesTool())
register_tool(CalendarTool())
register_tool(EmailTool())
register_tool(ReminderTool())
register_tool(WeatherTool())
register_tool(NewsTool())
register_tool(PerplexityTool())
register_tool(WhatsAppTool())
register_tool(ContactsTool())
register_tool(CostTool())
register_tool(MemoryTool())
register_tool(SalesTool())

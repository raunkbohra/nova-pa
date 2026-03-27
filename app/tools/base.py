"""
Base tool class and result dataclass.
All tools inherit from BaseTool and return ToolResult.
"""

from dataclasses import dataclass
from typing import Any, Optional
from abc import ABC, abstractmethod


@dataclass
class ToolResult:
    """Result from a tool execution"""
    tool_name: str
    success: bool
    data: Any = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dict for Claude"""
        return {
            "type": "tool_result",
            "tool_use_id": self.tool_name,
            "content": str(self.data) if self.success else f"Error: {self.error}"
        }


class BaseTool(ABC):
    """Abstract base class for all tools"""

    @property
    @abstractmethod
    def name(self) -> str:
        """Tool name (used by Claude to identify it)"""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Tool description for Claude"""
        pass

    @property
    @abstractmethod
    def input_schema(self) -> dict:
        """JSON schema for tool inputs"""
        pass

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """Execute the tool"""
        pass

    def to_claude_tool(self) -> dict:
        """Convert to Claude tool format"""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema
        }

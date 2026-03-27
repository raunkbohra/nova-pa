"""
Weather Tool — Current weather and forecast via OpenWeatherMap.
Supports city names, coordinates, and IST timezone default.
"""

import logging
import httpx
from typing import Optional
from app.tools.base import BaseTool, ToolResult
from app.config import settings

logger = logging.getLogger(__name__)

OPENWEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"
FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"


class WeatherTool(BaseTool):
    """Tool for checking current weather and forecasts"""

    @property
    def name(self) -> str:
        return "weather"

    @property
    def description(self) -> str:
        return """Get current weather and forecasts for any location.

Examples:
- "What's the weather in Delhi?"
- "Show me the forecast for Mumbai this week"
- "Is it going to rain in Bangalore tomorrow?"
        """

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "City name or 'current' for IST timezone default (e.g., 'Delhi', 'current')"
                },
                "forecast": {
                    "type": "boolean",
                    "description": "Include 5-day forecast (optional, default false)"
                }
            },
            "required": ["location"]
        }

    async def execute(self, location: str, forecast: bool = False, **kwargs) -> ToolResult:
        """Get weather information"""
        try:
            # Default to India if 'current' specified
            if location.lower() == "current":
                location = "Delhi"

            # Fetch current weather
            current = await self._get_current_weather(location)
            if not current:
                return ToolResult(
                    tool_name=self.name,
                    success=False,
                    error=f"Could not find weather for {location}"
                )

            result = {
                "location": current["location"],
                "current": current["weather"]
            }

            # Optionally fetch forecast
            if forecast:
                forecast_data = await self._get_forecast(location)
                if forecast_data:
                    result["forecast"] = forecast_data

            return ToolResult(
                tool_name=self.name,
                success=True,
                data=result
            )

        except Exception as e:
            logger.error(f"Weather tool error: {e}")
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(e)
            )

    async def _get_current_weather(self, location: str) -> Optional[dict]:
        """Fetch current weather from OpenWeatherMap"""
        if not settings.openweather_api_key:
            logger.error("OpenWeatherMap API key not configured")
            return None

        params = {
            "q": location,
            "appid": settings.openweather_api_key,
            "units": "metric"
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(OPENWEATHER_URL, params=params, timeout=10.0)
                response.raise_for_status()

                data = response.json()

                return {
                    "location": f"{data['name']}, {data['sys']['country']}",
                    "weather": {
                        "description": data["weather"][0]["main"],
                        "details": data["weather"][0]["description"],
                        "temperature": f"{data['main']['temp']}°C",
                        "feels_like": f"{data['main']['feels_like']}°C",
                        "humidity": f"{data['main']['humidity']}%",
                        "wind_speed": f"{data['wind']['speed']} m/s",
                        "pressure": f"{data['main']['pressure']} hPa"
                    }
                }

        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch weather: {e}")
            return None

    async def _get_forecast(self, location: str) -> Optional[list]:
        """Fetch 5-day forecast from OpenWeatherMap"""
        if not settings.openweather_api_key:
            return None

        params = {
            "q": location,
            "appid": settings.openweather_api_key,
            "units": "metric",
            "cnt": 40  # 5 days * 8 (3-hour intervals)
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(FORECAST_URL, params=params, timeout=10.0)
                response.raise_for_status()

                data = response.json()
                forecasts = []

                # Parse forecast data
                for item in data["list"][::8]:  # Every 24 hours
                    forecasts.append({
                        "date": item["dt_txt"],
                        "temp": f"{item['main']['temp']}°C",
                        "description": item["weather"][0]["description"],
                        "humidity": f"{item['main']['humidity']}%"
                    })

                return forecasts[:5]  # Return 5 days

        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch forecast: {e}")
            return None

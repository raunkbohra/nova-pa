"""
Market Tool — Live stock and crypto prices.
Stocks: Yahoo Finance (NSE/BSE, no API key needed)
Crypto: CoinGecko public API (no API key needed)
"""

import logging
import httpx
from app.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# Common crypto name aliases → CoinGecko IDs
CRYPTO_ALIASES = {
    "btc": "bitcoin", "bitcoin": "bitcoin",
    "eth": "ethereum", "ethereum": "ethereum",
    "sol": "solana", "solana": "solana",
    "bnb": "binancecoin", "binance": "binancecoin",
    "xrp": "ripple", "ripple": "ripple",
    "usdt": "tether", "tether": "tether",
    "ada": "cardano", "cardano": "cardano",
    "doge": "dogecoin", "dogecoin": "dogecoin",
    "matic": "matic-network", "polygon": "matic-network",
    "dot": "polkadot", "polkadot": "polkadot",
    "avax": "avalanche-2", "avalanche": "avalanche-2",
    "link": "chainlink", "chainlink": "chainlink",
    "shib": "shiba-inu", "shiba": "shiba-inu",
    "ltc": "litecoin", "litecoin": "litecoin",
    "trx": "tron", "tron": "tron",
}

# Common Indian stock aliases → Yahoo Finance tickers
STOCK_ALIASES = {
    "reliance": "RELIANCE.NS",
    "tcs": "TCS.NS",
    "infosys": "INFY.NS", "infy": "INFY.NS",
    "hdfc": "HDFCBANK.NS", "hdfc bank": "HDFCBANK.NS",
    "icici": "ICICIBANK.NS", "icici bank": "ICICIBANK.NS",
    "wipro": "WIPRO.NS",
    "bajaj": "BAJFINANCE.NS", "bajaj finance": "BAJFINANCE.NS",
    "nifty": "^NSEI", "nifty50": "^NSEI",
    "sensex": "^BSESN",
    "tatamotors": "TATAMOTORS.NS", "tata motors": "TATAMOTORS.NS",
    "tatasteel": "TATASTEEL.NS", "tata steel": "TATASTEEL.NS",
    "sbi": "SBIN.NS",
    "airtel": "BHARTIARTL.NS", "bharti airtel": "BHARTIARTL.NS",
    "hul": "HINDUNILVR.NS", "hindustan unilever": "HINDUNILVR.NS",
    "ongc": "ONGC.NS",
    "adani": "ADANIENT.NS", "adani enterprises": "ADANIENT.NS",
    "lt": "LT.NS", "larsen": "LT.NS",
    "itc": "ITC.NS",
    "kotak": "KOTAKBANK.NS", "kotak bank": "KOTAKBANK.NS",
    "zomato": "ZOMATO.NS",
    "paytm": "PAYTM.NS",
    "nykaa": "NYKAA.NS",
}


class MarketTool(BaseTool):

    def __init__(self):
        pass

    @property
    def name(self) -> str:
        return "market"

    @property
    def description(self) -> str:
        return """Get live stock and cryptocurrency prices.

Actions:
- price: Get current price for one or more stocks/cryptos
- portfolio: Get prices for multiple symbols at once

Supports:
- Crypto: BTC, ETH, SOL, BNB, XRP, DOGE, MATIC, etc.
- Indian stocks: Reliance, TCS, Infosys, HDFC, Nifty, Sensex, etc.
- Any NSE stock: add .NS suffix (e.g. "ZOMATO.NS")
- Any BSE stock: add .BO suffix

Examples:
- "What's BTC at?" → price(symbols=["BTC"])
- "Check ETH and SOL" → price(symbols=["ETH", "SOL"])
- "How's Reliance doing?" → price(symbols=["Reliance"])
- "Check Nifty and Sensex" → price(symbols=["Nifty", "Sensex"])
- "BTC, ETH, Nifty prices" → price(symbols=["BTC", "ETH", "Nifty"])
        """

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["price"],
                    "description": "Always use 'price'"
                },
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of symbols to fetch, e.g. ['BTC', 'ETH', 'Reliance', 'Nifty']"
                }
            },
            "required": ["action", "symbols"]
        }

    async def execute(self, action: str, symbols: list = None, **kwargs) -> ToolResult:
        if not symbols:
            return ToolResult(tool_name=self.name, success=False, error="symbols list is required")
        try:
            results = []
            crypto_ids = []
            stock_tickers = []

            # Classify each symbol
            for sym in symbols:
                key = sym.strip().lower()
                if key in CRYPTO_ALIASES:
                    crypto_ids.append((sym, CRYPTO_ALIASES[key]))
                elif key in STOCK_ALIASES:
                    stock_tickers.append((sym, STOCK_ALIASES[key]))
                elif sym.upper().endswith(".NS") or sym.upper().endswith(".BO"):
                    stock_tickers.append((sym, sym.upper()))
                else:
                    # Try as a stock ticker on NSE
                    stock_tickers.append((sym, f"{sym.upper()}.NS"))

            # Fetch crypto prices in one batch call
            if crypto_ids:
                crypto_results = await self._fetch_crypto([cid for _, cid in crypto_ids])
                for original, cid in crypto_ids:
                    data = crypto_results.get(cid, {})
                    if data:
                        inr = data.get("inr", 0)
                        usd = data.get("usd", 0)
                        change_24h = data.get("inr_24h_change", None)
                        results.append({
                            "symbol": original.upper(),
                            "type": "crypto",
                            "price_inr": inr,
                            "price_usd": usd,
                            "change_24h_pct": round(change_24h, 2) if change_24h is not None else None,
                        })
                    else:
                        results.append({"symbol": original.upper(), "type": "crypto", "error": "not found"})

            # Fetch stock prices individually (Yahoo Finance)
            for original, ticker in stock_tickers:
                data = await self._fetch_stock(ticker)
                if data:
                    results.append({
                        "symbol": original.upper(),
                        "ticker": ticker,
                        "type": "stock",
                        "price_inr": data["price"],
                        "change_pct": data.get("change_pct"),
                        "exchange": data.get("exchange", "NSE"),
                    })
                else:
                    results.append({"symbol": original.upper(), "ticker": ticker,
                                    "type": "stock", "error": "not found or delisted"})

            return ToolResult(tool_name=self.name, success=True, data={"prices": results})

        except Exception as e:
            logger.error(f"Market tool error: {e}")
            return ToolResult(tool_name=self.name, success=False, error=str(e))

    async def _fetch_crypto(self, coin_ids: list) -> dict:
        """Fetch multiple crypto prices from CoinGecko in one request."""
        ids_param = ",".join(coin_ids)
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {
            "ids": ids_param,
            "vs_currencies": "inr,usd",
            "include_24hr_change": "true",
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()

    async def _fetch_stock(self, ticker: str) -> dict:
        """Fetch stock price from Yahoo Finance."""
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        params = {"interval": "1d", "range": "1d"}
        headers = {"User-Agent": "Mozilla/5.0"}
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params, headers=headers)
            if resp.status_code != 200:
                return None
            data = resp.json()

        try:
            meta = data["chart"]["result"][0]["meta"]
            price = meta.get("regularMarketPrice") or meta.get("previousClose")
            prev_close = meta.get("previousClose") or meta.get("chartPreviousClose")
            change_pct = ((price - prev_close) / prev_close * 100) if prev_close and price else None
            exchange = meta.get("exchangeName", "NSE")
            return {
                "price": price,
                "change_pct": round(change_pct, 2) if change_pct is not None else None,
                "exchange": exchange,
            }
        except (KeyError, IndexError, TypeError):
            return None

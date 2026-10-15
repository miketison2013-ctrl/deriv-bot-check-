"""
Multi-market scanner for the Deriv trading bot.

Fetches recent ticks from eligible markets and calculates
descriptive statistics using market_analyzer.py.
"""

from market_analyzer import analyse_market, rank_markets


class MarketScanner:
    def __init__(self, client):
        self.client = client
        self.last_results = []
        self.last_errors = {}

    @staticmethod
    def is_volatility_market(market):
        """Identify standard and 1-second Volatility indices."""
        name = str(
            market.get("display_name")
            or market.get("symbol")
            or ""
        ).lower()

        symbol = str(market.get("symbol") or "").upper()

        return (
            "volatility" in name
            or symbol.startswith("R_")
            or symbol.startswith("1HZ")
        )

    def scan(self, count=100, volatility_only=True):
        """
        Scan available markets using recent tick history.

        Returns market analyses and per-market errors.
        This method does not place trades.
        """
        self.last_results = []
        self.last_errors = {}

        markets = self.client.get_active_symbols()

        if volatility_only:
            markets = [
                market for market in markets
                if self.is_volatility_market(market)
            ]

        for market in markets:
            symbol = market.get("symbol")

            if not symbol:
                continue

            try:
                history = self.client.get_recent_ticks(
                    symbol,
                    count=count,
                )

                prices = history.get("prices", [])

                if len(prices) < 2:
                    self.last_errors[symbol] = (
                        "Not enough tick history."
                    )
                    continue

                analysis = analyse_market(
                    prices,
                    symbol=symbol,
                    window=count,
                )

                analysis["display_name"] = market.get(
                    "display_name",
                    symbol,
                )

                analysis["market_category"] = (
                    "1-second volatility"
                    if symbol.upper().startswith("1HZ")
                    else "standard/other volatility"
                )

                self.last_results.append(analysis)

            except Exception as exc:
                self.last_errors[symbol] = str(exc)

        self.last_results = rank_markets(self.last_results)

        for position, result in enumerate(
            self.last_results,
            start=1,
        ):
            result["movement_rank"] = position

        return {
            "markets_scanned": len(markets),
            "markets_analysed": len(self.last_results),
            "results": self.last_results,
            "errors": self.last_errors,
        }
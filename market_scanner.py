
"""
Automatic Volatility digit-market scanner.

Discovers active Volatility indices, checks available digit contracts,
collects tick history, and ranks markets using market_analyzer.py.

This module never purchases contracts.
"""

from market_analyzer import analyse_market, rank_markets


DIGIT_CONTRACTS = {
    "DIGITOVER",
    "DIGITUNDER",
    "DIGITMATCH",
    "DIGITDIFF",
    "DIGITEVEN",
    "DIGITODD",
}


class MarketScanner:
    def __init__(self, client):
        self.client = client
        self.last_results = []
        self.last_errors = {}

    @staticmethod
    def is_volatility_market(market):
        """Return True for likely standard or 1-second Volatility indices."""
        name = str(
            market.get("display_name")
            or market.get("name")
            or ""
        ).lower()
        symbol = str(market.get("symbol") or "").upper()

        return (
            "volatility" in name
            or symbol.startswith("R_")
            or symbol.startswith("1HZ")
        )

    @staticmethod
    def _supported_digit_contracts(contract_types):
        """Normalize the contract-type response from DerivClient."""
        supported = set()

        if isinstance(contract_types, dict):
            values = list(contract_types.values())
            values.extend(contract_types.keys())
        elif isinstance(contract_types, (list, tuple, set)):
            values = list(contract_types)
        else:
            values = []

        for item in values:
            if isinstance(item, dict):
                candidate = (
                    item.get("contract_type")
                    or item.get("contractType")
                    or item.get("value")
                    or item.get("name")
                    or ""
                )
            else:
                candidate = str(item)

            candidate = str(candidate).strip().upper()
            if candidate in DIGIT_CONTRACTS:
                supported.add(candidate)

        return sorted(supported)

    def scan(self, count=100, volatility_only=True):
        """
        Scan available markets.

        Returns:
            markets_scanned: number of candidate symbols discovered
            markets_analysed: number successfully analysed
            results: ranked market analyses
            errors: per-symbol failures

        No trades are opened by this method.
        """
        self.last_results = []
        self.last_errors = {}

        count = max(2, min(int(count), 500))
        markets = self.client.get_active_symbols() or []

        if volatility_only:
            markets = [
                market for market in markets
                if self.is_volatility_market(market)
            ]

        # Avoid duplicate symbols in the active-symbol response.
        unique_markets = []
        seen_symbols = set()

        for market in markets:
            if not isinstance(market, dict):
                continue

            symbol = str(market.get("symbol") or "").strip()
            if not symbol or symbol in seen_symbols:
                continue

            seen_symbols.add(symbol)
            unique_markets.append(market)

        for market in unique_markets:
            symbol = str(market.get("symbol") or "").strip()

            try:
                contract_types = self.client.get_contract_types(symbol)
                supported = self._supported_digit_contracts(
                    contract_types
                )

                if not supported:
                    self.last_errors[symbol] = (
                        "No supported digit contracts were returned."
                    )
                    continue

                history = self.client.get_recent_ticks(
                    symbol,
                    count=count,
                ) or {}

                prices = history.get("prices") or []

                if len(prices) < 2:
                    self.last_errors[symbol] = (
                        "Not enough tick history to analyse."
                    )
                    continue

                analysis = analyse_market(
                    prices,
                    symbol=symbol,
                    window=count,
                )

                analysis["display_name"] = (
                    market.get("display_name")
                    or market.get("name")
                    or symbol
                )
                analysis["market_category"] = (
                    "1-second volatility"
                    if symbol.upper().startswith("1HZ")
                    else "standard volatility"
                )
                analysis["supported_digit_contracts"] = supported
                analysis["has_sufficient_digit_sample"] = (
                    analysis.get("digits", {}).get("sample_size", 0) >= 50
                )

                self.last_results.append(analysis)

            except Exception as exc:
                self.last_errors[symbol] = str(exc)

        self.last_results = rank_markets(self.last_results)

        for position, result in enumerate(self.last_results, start=1):
            result["movement_rank"] = position

        return {
            "markets_scanned": len(unique_markets),
            "markets_analysed": len(self.last_results),
            "results": self.last_results,
            "errors": self.last_errors,
        }

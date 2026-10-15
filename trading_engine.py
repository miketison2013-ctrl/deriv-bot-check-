
"""Automatic Volatility digit-trading engine for Deriv.

Scans eligible Volatility indices, analyses last-digit samples,
ranks candidate digit contracts, validates live proposals, applies
risk limits, buys qualifying contracts, and monitors settlements.

A statistical ranking is not a guarantee of future outcomes.
Test on Demo before enabling real-money trading.
"""

from datetime import datetime, timezone
import time

from market_analyzer import analyse_market


DIGIT_CONTRACTS = {
    "DIGITOVER",
    "DIGITUNDER",
    "DIGITMATCH",
    "DIGITDIFF",
    "DIGITEVEN",
    "DIGITODD",
}


class TradingEngine:
    """Automatically select and trade eligible digit opportunities."""

    def __init__(self, client, journal):
        self.client = client
        self.journal = journal
        self.running = False

        self.last_trade_time = 0.0
        self.last_loss_time = 0.0
        self.last_signal = "WAIT"
        self.last_action = "Ready"
        self.last_error = ""

        self.last_scan = []
        self.last_scan_errors = {}
        self.last_candidates = []
        self.last_scan_time = None
        self.last_trade = None

    @staticmethod
    def _number(value, default=None):
        try:
            result = float(value)
            if result != result or abs(result) == float("inf"):
                return default
            return result
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _is_volatility_market(market):
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

    def _trades(self, account_type):
        return self.journal.list_trades(
            limit=1000,
            account_type=account_type,
        )

    def _open_trades(self, account_type):
        return [
            trade for trade in self._trades(account_type)
            if str(trade.get("status", "")).upper() == "OPEN"
        ]

    def _daily_net(self, account_type):
        today = datetime.now(timezone.utc).date()
        total = 0.0

        for trade in self._trades(account_type):
            if str(trade.get("status", "")).upper() not in (
                "WON", "LOST", "SOLD"
            ):
                continue

            stamp = trade.get("exit_time") or trade.get("updated_at")
            if not stamp:
                continue

            try:
                parsed = datetime.fromisoformat(
                    str(stamp).replace("Z", "+00:00")
                )
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)

                if parsed.astimezone(timezone.utc).date() == today:
                    total += self._number(
                        trade.get("profit_loss"), 0.0
                    )
            except (ValueError, TypeError, OverflowError, OSError):
                continue

        return total

    def monitor_open_trades(self, account_type):
        messages = []

        for trade in self._open_trades(account_type):
            contract_id = trade.get("contract_id")
            if not contract_id:
                continue

            try:
                details = self.client.get_open_contract(
                    account_type, contract_id
                )
            except Exception as exc:
                self.last_error = (
                    "Could not check contract {}: {}".format(
                        contract_id, exc
                    )
                )
                continue

            sold = details.get("is_sold") in (1, True, "1")
            status = str(details.get("status", "")).lower()

            if not sold and status not in (
                "won", "lost", "sold", "expired"
            ):
                continue

            profit = self._number(details.get("profit"))

            if profit is None:
                sell_price = self._number(details.get("sell_price"))
                buy_price = self._number(
                    details.get("buy_price", trade.get("buy_price"))
                )

                if sell_price is None or buy_price is None:
                    self.last_error = (
                        "Final profit is not confirmed for contract "
                        + str(contract_id)
                    )
                    continue

                profit = sell_price - buy_price

            final_status = (
                "WON" if profit > 0
                else "LOST" if profit < 0
                else "SOLD"
            )

            try:
                settled = self.journal.settle_trade(
                    str(contract_id),
                    status=final_status,
                    profit_loss=profit,
                    payout=self._number(details.get("payout")),
                    exit_spot=self._number(details.get("exit_tick")),
                    exit_time=datetime.now(timezone.utc).isoformat(),
                    raw_data=details,
                )
            except Exception as exc:
                self.last_error = (
                    "Could not record settlement for {}: {}".format(
                        contract_id, exc
                    )
                )
                continue

            if settled:
                if profit < 0:
                    self.last_loss_time = time.time()

                messages.append(
                    "{} {} P/L {:.2f}".format(
                        contract_id, final_status, profit
                    )
                )

        if messages:
            self.last_action = (
                "Settlement recorded: " + "; ".join(messages)
            )

        return messages

    def scan_markets(self, config):
        """Read-only scan; this method never buys a contract."""
        account_type = str(config.get("account_type", "")).lower()
        window = max(50, min(int(config.get("tick_sample_size", 150)), 500))
        minimum_samples = max(
            30, int(config.get("minimum_digit_samples", 80))
        )
        max_markets = max(
            1, min(int(config.get("max_scan_markets", 40)), 100)
        )

        self.last_scan = []
        self.last_scan_errors = {}
        self.last_candidates = []

        markets = self.client.get_active_symbols()
        markets = [
            market for market in markets
            if self._is_volatility_market(market)
            and market.get("symbol")
        ]

        # Scan a bounded list each cycle to limit API load.
        markets = markets[:max_markets]

        for market in markets:
            symbol = market["symbol"]

            try:
                tick_data = self.client.get_recent_ticks(
                    symbol, count=window
                )
                prices = tick_data.get("prices", [])

                if len(prices) < minimum_samples:
                    self.last_scan_errors[symbol] = (
                        "Insufficient tick sample: {} received, "
                        "{} required.".format(
                            len(prices), minimum_samples
                        )
                    )
                    continue

                analysis = analyse_market(
                    prices,
                    symbol=symbol,
                    window=window,
                )

                digit_data = analysis.get("digits", {})
                sample_size = int(digit_data.get("sample_size", 0))

                if sample_size < minimum_samples:
                    self.last_scan_errors[symbol] = (
                        "Insufficient valid last-digit samples."
                    )
                    continue

                available = self.client.get_contract_types(symbol)
                contract_types = set(available.values())

                rows = digit_data.get("counts", [])
                by_digit = {
                    int(row["digit"]): row
                    for row in rows
                    if row.get("digit") is not None
                }

                market_result = {
                    "symbol": symbol,
                    "display_name": market.get(
                        "display_name", symbol
                    ),
                    "market_category": (
                        "1-second Volatility"
                        if symbol.upper().startswith("1HZ")
                        else "Standard Volatility"
                    ),
                    "sample_size": sample_size,
                    "latest_price": analysis.get(
                        "price", {}
                    ).get("latest_price"),
                    "digit_counts": rows,
                    "supported_digit_contracts": sorted(
                        contract_types.intersection(DIGIT_CONTRACTS)
                    ),
                    "momentum": analysis.get(
                        "momentum", {}
                    ).get("signal", "UNKNOWN"),
                }

                self.last_scan.append(market_result)

                if not contract_types.intersection(DIGIT_CONTRACTS):
                    self.last_scan_errors[symbol] = (
                        "No supported digit contracts returned."
                    )
                    continue

                # Rank possible contracts using empirical frequencies.
                # These are descriptive estimates, not predictions.
                digit_rows = [
                    by_digit[d] for d in range(10)
                    if d in by_digit
                ]

                if len(digit_rows) != 10:
                    self.last_scan_errors[symbol] = (
                        "Could not calculate all ten digit frequencies."
                    )
                    continue

                counts = {
                    d: int(by_digit[d].get("count", 0))
                    for d in range(10)
                }

                def add_candidate(contract_type, barrier, observed,
                                  description):
                    if contract_type not in contract_types:
                        return
                    if not 0 < observed < 1:
                        return

                    self.last_candidates.append({
                        "symbol": symbol,
                        "contract_type": contract_type,
                        "barrier": barrier,
                        "observed_probability": observed,
                        "sample_size": sample_size,
                        "description": description,
                    })

                # Matches / differs, based on observed frequency.
                for digit in range(10):
                    observed = counts[digit] / sample_size
                    add_candidate(
                        "DIGITMATCH", digit, observed,
                        "Matches {}".format(digit),
                    )
                    add_candidate(
                        "DIGITDIFF", digit, 1.0 - observed,
                        "Differs {}".format(digit),
                    )

                # Over / under barriers; digit 0-9 is the final digit.
                for barrier in range(10):
                    over_count = sum(
                        counts[d] for d in range(barrier + 1, 10)
                    )
                    under_count = sum(
                        counts[d] for d in range(0, barrier)
                    )

                    add_candidate(
                        "DIGITOVER", barrier,
                        over_count / sample_size,
                        "Over {}".format(barrier),
                    )
                    add_candidate(
                        "DIGITUNDER", barrier,
                        under_count / sample_size,
                        "Under {}".format(barrier),
                    )

                even_count = sum(counts[d] for d in (0, 2, 4, 6, 8))
                odd_count = sample_size - even_count

                add_candidate(
                    "DIGITEVEN", None,
                    even_count / sample_size, "Even",
                )
                add_candidate(
                    "DIGITODD", None,
                    odd_count / sample_size, "Odd",
                )

            except Exception as exc:
                self.last_scan_errors[symbol] = str(exc)

        self.last_scan_time = datetime.now(timezone.utc).isoformat()

        # Rank by sample support and deviation from the fair baseline.
        # The live proposal's payout is checked before any purchase.
        self.last_candidates.sort(
            key=lambda item: (
                item["sample_size"],
                abs(item["observed_probability"] - 0.5),
            ),
            reverse=True,
        )

        return {
            "markets_analysed": len(self.last_scan),
            "candidate_count": len(self.last_candidates),
            "results": self.last_scan,
            "candidates": self.last_candidates,
            "errors": self.last_scan_errors,
            "scan_time": self.last_scan_time,
        }

    def run_cycle(self, config):
        """Monitor open contracts and optionally buy one ranked candidate."""
        account_type = str(config.get("account_type", "")).lower()

        if account_type not in ("demo", "real"):
            self.last_action = "Blocked: select Demo or Real"
            return {"action": self.last_action}

        try:
            self.monitor_open_trades(account_type)

            if not self.running:
                if not self.last_action.startswith("Settlement recorded:"):
                    self.last_action = "Stopped: monitoring open trades only"
                return {"action": self.last_action}

            if account_type == "real" and not config.get("allow_real", False):
                self.last_action = "Blocked: confirm Real-account trading"
                return {"action": self.last_action}

            stake = self._number(config.get("stake"))
            max_price = self._number(config.get("max_stake"))
            loss_limit = self._number(config.get("daily_loss_limit"))
            max_open = int(config.get("max_open_trades", 1))
            cooldown = int(config.get("cooldown_seconds", 60))
            loss_cooldown = int(config.get("loss_cooldown_seconds", 300))
            duration = int(config.get("duration", 1))
            duration_unit = str(config.get("duration_unit", "t"))
            currency = str(config.get("currency") or "")

            if (
                stake is None or max_price is None or loss_limit is None
                or stake <= 0 or max_price <= 0 or stake > max_price
            ):
                raise ValueError("Invalid stake, purchase-price, or loss-limit settings.")

            if not currency:
                raise ValueError("Account currency is missing.")

            if duration < 1 or duration_unit not in ("t", "s", "m"):
                raise ValueError("Invalid contract duration.")

            if self._daily_net(account_type) <= -loss_limit:
                self.last_action = "Blocked: daily loss limit reached"
                return {"action": self.last_action}

            if len(self._open_trades(account_type)) >= max_open:
                self.last_action = "Waiting: open-trade limit reached"
                return {"action": self.last_action}

            now = time.time()
            if now - self.last_trade_time < cooldown:
                self.last_action = "Waiting: entry cooldown"
                return {"action": self.last_action}

            if now - self.last_loss_time < loss_cooldown:
                self.last_action = "Waiting: loss cooldown"
                return {"action": self.last_action}

            balance = self.client.get_balance(account_type)
            if str(balance.get("currency", "")).upper() != currency.upper():
                raise ValueError("Selected account currency mismatch.")

            available_balance = self._number(balance.get("balance"), 0.0)
            if stake > available_balance:
                raise ValueError("Stake exceeds available balance.")

            scan = self.scan_markets(config)
            candidates = scan["candidates"]

            # Only test a bounded number of top candidates with live proposals.
            proposal_limit = max(
                1, min(int(config.get("proposal_checks_per_cycle", 8)), 20)
            )
            min_probability = float(
                config.get("minimum_observed_probability", 0.0)
            )

            best = None
            proposal_errors = []

            for candidate in candidates[:proposal_limit]:
                if candidate["observed_probability"] < min_probability:
                    continue

                try:
                    proposal = self.client.get_proposal(
                        account_type=account_type,
                        symbol=candidate["symbol"],
                        contract_type=candidate["contract_type"],
                        amount=stake,
                        currency=currency,
                        duration=duration,
                        duration_unit=duration_unit,
                        barrier=candidate["barrier"],
                    )

                    ask = self._number(proposal.get("ask_price"))
                    payout = self._number(proposal.get("payout"))
                    proposal_id = proposal.get("proposal_id")

                    if (
                        not proposal_id or ask is None or payout is None
                        or ask <= 0 or payout <= 0 or ask > max_price
                        or ask > available_balance
                    ):
                        continue

                    break_even = ask / payout
                    observed = candidate["observed_probability"]

                    # Use a conservative smoothing adjustment to avoid
                    # treating a small sample's raw frequency as certainty.
                    n = candidate["sample_size"]
                    adjusted = (
                        observed * n + 1.0
                    ) / (n + 2.0)

                    edge = adjusted - break_even
                    candidate_result = {
                        **candidate,
                        "proposal_id": proposal_id,
                        "ask_price": ask,
                        "payout": payout,
                        "break_even_probability": break_even,
                        "adjusted_probability": adjusted,
                        "estimated_edge": edge,
                    }

                    if best is None or edge > best["estimated_edge"]:
                        best = candidate_result

                except Exception as exc:
                    proposal_errors.append(
                        "{} {}: {}".format(
                            candidate["symbol"],
                            candidate["contract_type"],
                            exc,
                        )
                    )

            self.last_candidates = candidates

            if best is None:
                self.last_signal = "NO QUALIFYING PROPOSAL"
                self.last_action = (
                    "No eligible proposal passed the price and "
                    "availability checks; waiting."
                )
                if proposal_errors:
                    self.last_error = "; ".join(proposal_errors[:3])
                return {
                    "action": self.last_action,
                    "scan": scan,
                    "proposal_errors": proposal_errors,
                }

            # Require a positive estimated edge. This estimate is not
            # a guarantee and can be unreliable in non-stationary markets.
            if best["estimate
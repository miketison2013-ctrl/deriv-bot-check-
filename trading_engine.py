
"""Automatic Volatility digit-trading engine for Deriv.

Scans supported Volatility markets, estimates digit probabilities,
checks live proposals, applies risk controls, and records confirmed
purchases and actual settlements.

Historical frequencies are estimates, not reliable predictions.
Real-money trading carries a risk of loss.
"""

from datetime import datetime, timezone
import math
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
    def __init__(self, client, journal):
        self.client = client
        self.journal = journal
        self.running = False

        self.last_trade_time = 0.0
        self.last_loss_time = 0.0
        self.last_loss_key = None
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
            number = float(value)
            if not math.isfinite(number):
                return default
            return number
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _is_volatility_market(market):
        name = str(
            market.get("display_name")
            or market.get("underlying_symbol_name")
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
                    exit_spot=self._number(
                        details.get("exit_tick")
                        or details.get("exit_spot")
                    ),
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
                    self.last_loss_key = (
                        trade.get("symbol"),
                        trade.get("contract_type"),
                        trade.get("direction"),
                    )
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
        """Read-only scan. No purchases occur in this method."""
        window = max(
            50, min(int(config.get("tick_sample_size", 150)), 500)
        )
        minimum_samples = max(
            30, min(int(config.get("minimum_digit_samples", 80)), 500)
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

        # Put 1-second markets first, then scan a bounded number.
        markets.sort(
            key=lambda market: (
                not str(market.get("symbol", "")).upper().startswith("1HZ"),
                str(market.get("display_name", market.get("symbol", ""))).lower(),
            )
        )
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
                        "Insufficient ticks: {} received; {} required."
                        .format(len(prices), minimum_samples)
                    )
                    continue

                analysis = analyse_market(
                    prices, symbol=symbol, window=window
                )
                digit_data = analysis.get("digits", {})
                sample_size = int(digit_data.get("sample_size", 0))
                rows = digit_data.get("counts", [])

                if sample_size < minimum_samples:
                    self.last_scan_errors[symbol] = (
                        "Insufficient valid digit samples."
                    )
                    continue

                by_digit = {
                    int(row["digit"]): row
                    for row in rows
                    if row.get("digit") is not None
                }
                if len(by_digit) != 10:
                    self.last_scan_errors[symbol] = (
                        "Missing one or more digit frequencies."
                    )
                    continue

                available = self.client.get_contract_types(symbol)
                supported = set(available.values()).intersection(
                    DIGIT_CONTRACTS
                )

                result = {
                    "symbol": symbol,
                    "display_name": (
                        market.get("display_name")
                        or market.get("underlying_symbol_name")
                        or symbol
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
                    "supported_digit_contracts": sorted(supported),
                    "momentum": analysis.get(
                        "momentum", {}
                    ).get("signal", "UNKNOWN"),
                }
                self.last_scan.append(result)

                if not supported:
                    self.last_scan_errors[symbol] = (
                        "No supported digit contracts."
                    )
                    continue

                counts = {
                    digit: int(by_digit[digit].get("count", 0))
                    for digit in range(10)
                }

                def add(contract, barrier, count, description):
                    if contract not in supported:
                        return
                    probability = count / sample_size
                    if 0 < probability < 1:
                        self.last_candidates.append({
                            "symbol": symbol,
                            "contract_type": contract,
                            "barrier": barrier,
                            "observed_probability": probability,
                            "sample_size": sample_size,
                            "description": description,
                        })

                for digit in range(10):
                    add(
                        "DIGITMATCH", digit, counts[digit],
                        "Matches {}".format(digit)
                    )
                    add(
                        "DIGITDIFF", digit,
                        sample_size - counts[digit],
                        "Differs {}".format(digit)
                    )

                for barrier in range(10):
                    add(
                        "DIGITOVER", barrier,
                        sum(counts[d] for d in range(barrier + 1, 10)),
                        "Over {}".format(barrier)
                    )
                    add(
                        "DIGITUNDER", barrier,
                        sum(counts[d] for d in range(0, barrier)),
                        "Under {}".format(barrier)
                    )

                even_count = sum(counts[d] for d in (0, 2, 4, 6, 8))
                add("DIGITEVEN", None, even_count, "Even")
                add("DIGITODD", None, sample_size - even_count, "Odd")

            except Exception as exc:
                self.last_scan_errors[symbol] = str(exc)

        self.last_scan_time = datetime.now(timezone.utc).isoformat()

        # This ordering is for inspection only; it is not a prediction.
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
        """Monitor settlements and buy at most one qualifying contract."""
        account_type = str(
            config.get("account_type", "")
        ).lower()

        if account_type not in ("demo", "real"):
            self.last_action = "Blocked: select Demo or Real account"
            return {"action": self.last_action}

        try:
            self.monitor_open_trades(account_type)

            if not self.running:
                self.last_action = "Stopped: monitoring open trades only"
                return {"action": self.last_action}

            if account_type == "real" and not config.get("allow_real", False):
                self.last_action = "Blocked: confirm Real-account trading"
                return {"action": self.last_action}

            stake = self._number(config.get("stake"))
            max_price = self._number(config.get("max_stake"))
            loss_limit = self._number(config.get("daily_loss_limit"))
            if (
                stake is None or max_price is None or loss_limit is None
                or stake <= 0 or max_price <= 0 or loss_limit <= 0
                or stake > max_price
            ):
                raise ValueError("Invalid stake, maximum price, or loss limit.")

            currency = str(config.get("currency") or "").strip()
            if not currency:
                raise ValueError("Selected account currency is missing.")

            duration = int(config.get("duration", 1))
            duration_unit = str(config.get("duration_unit", "t"))
            if duration < 1 or duration_unit not in ("t", "s", "m"):
                raise ValueError("Invalid duration.")

            max_open = max(1, int(config.get("max_open_trades", 1)))
            cooldown = max(0, int(config.get("cooldown_seconds", 60)))
            loss_cooldown = max(
                0, int(config.get("loss_cooldown_seconds", 300))
            )

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
            proposal_limit = max(
                1, min(int(config.get("proposal_checks_per_cycle", 8)), 20)
            )
            minimum_probability = self._number(
                config.get("minimum_observed_probability"), 0.0
            )
            minimum_edge = self._number(
                config.get("minimum_estimated_edge"), 0.02
            )

            best = None
            proposal_errors = []

            for candidate in candidates[:proposal_limit]:
                observed = candidate["observed_probability"]
                if observed < minimum_probability:
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
                        or ask <= 0 or payout <= ask
                        or ask > max_price or ask > available_balance
                    ):
                        continue

                    # Approximate break-even win probability.
                    break_even = ask / payout
                    n = candidate["sample_size"]
                    adjusted = (observed * n + 1.0) / (n + 2.0)
                    edge = adjusted - break_even

                    checked = {
                        **candidate,
                        "proposal_id": proposal_id,
                        "ask_price": ask,
                        "payout": payout,
                        "break_even_probability": break_even,
                        "adjusted_probability": adjusted,
                        "estimated_edge": edge,
                    }

                    if best is None or edge > best["estimated_edge"]:
                        best = checked

                except Exception as exc:
                    proposal_errors.append(
                        "{} {}: {}".format(
                            candidate["symbol"],
                            candidate["contract_type"],
                            exc,
                        )
                    )

            self.last_candidates = candidates

            if best is None or best["estimated_edge"] < minimum_edge:
                self.last_signal = "WAIT"
                self.last_action = (
                    "No candidate passed proposal and minimum-edge checks."
                )
                if proposal_errors:
                    self.last_error = "; ".join(proposal_errors[:3])
                return {
                    "action": self.last_action,
                    "scan": scan,
                    "proposal_errors": proposal_errors,
                    "best_candidate": best,
                }

            # Do not immediately repeat the exact last losing setup.
            candidate_key = (
                best["symbol"],
                best["contract_type"],
                best.get("barrier"),
            )
            if self.last_loss_key and candidate_key == self.last_loss_key:
                self.last_action = "Waiting: last losing setup is blocked"
                return {"action": self.last_action, "scan": scan}

            # Refresh the proposal immediately before buying.
            proposal = self.client.get_proposal(
                account_type=account_type,
                symbol=best["symbol"],
                contract_type=best["contract_type"],
                amount=stake,
                currency=currency,
                duration=duration,
                duration_unit=duration_unit,
                barrier=best["barrier"],
            )
            proposal_id = proposal.get("proposal_id")
            ask = self._number(proposal.get("ask_price"))
            payout = self._number(proposal.get("payout"))

            if (
                not proposal_id or ask is None or payout is None
                or ask <= 0 or ask > max_price
                or ask > available_balance or payout <= ask
            ):
                raise ValueError("Refreshed proposal failed price checks.")

            # Recheck risk limits immediately before purchase.
            if self._daily_net(account_type) <= -loss_limit:
                raise ValueError("Daily loss limit reached before purchase.")
            if len(self._open_trades(account_type)) >= max_open:
                raise ValueError("Open-trade limit reached before purchase.")

            purchase = self.client.buy_contract(
                account_type=account_type,
                proposal_id=proposal_id,
                maximum_price=ask,
            )
            contract_id = purchase.get("contract_id")
            if not contract_id:
                raise ValueError("Purchase was not confirmed by Deriv.")

            buy_price = self._number(
                purchase.get("buy_price"), ask
            )
            entry_spot = self._number(
                purchase.get("spot") or best.get("spot")
            )
            purchase_time = purchase.get("purchase_time")
            if purchase_time is not None:
                try:
                    entry_time = datetime.fromtimestamp(
                        float(purchase_time), tz=timezone.utc
                    ).isoformat()
                except (ValueError, TypeError, OSError, OverflowError):
                    entry_time = datetime.now(timezone.utc).isoformat()
            else:
                entry_time = datetime.now(timezone.utc).isoformat()

            self.journal.record_open_trade(
                contract_id=str(contract_id),
                account_type=account_type,
                account_id=purchase.get("account_id"),
                transaction_id=(
                    str(purchase.get("transaction_id"))
                    if purchase.get("transaction_id") is not None
                    else None
                ),
                symbol=best["symbol"],
                contract_type=best["contract_type"],
                direction=best["description"],
                stake=stake,
                currency=currency,
                entry_spot=entry_spot,
                entry_time=entry_time,
                buy_price=buy_price,
                strategy="digit_frequency_proposal_filter",
                notes=(
                    "Estimated edge {:.4f}; not a guarantee."
                    .format(best["estimated_edge"])
                ),
                raw_data={
                    "candidate": best,
                    "purchase": purchase,
                },
            )

            self.last_trade_time = time.time()
            self.last_trade = {
                **best,
                "contract_id": str(contract_id),
                "buy_price": buy_price,
                "purchase": purchase,
            }
            self.last_signal = best["description"]
            self.last_action = (
                "Purchase confirmed: {} {} contract {}".format(
                    best["symbol"], best["description"], contract_id
                )
            )
            self.last_error = ""

            return {
                "action": self.last_action,
                "trade": self.last_trade,
                "scan": scan,
            }

        except Exception as exc:
            self.last_error = str(exc)
            self.last_action = "Cycle error: " + str(exc)
            return {
                "action": self.last_action,
                "error": self.last_error,
            }

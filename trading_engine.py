
"""Core execution engine for the Deriv trading bot.

The dashboard must call run_cycle() repeatedly while the bot is running.
The selected account is supplied by the dashboard on every cycle.
"""

from datetime import datetime, timezone
import time


class TradingEngine:
    def __init__(self, client, journal):
        self.client = client
        self.journal = journal
        self.running = False
        self.last_trade_time = 0.0
        self.last_loss_time = 0.0
        self.last_signal = "WAIT"
        self.last_action = "Ready"
        self.last_error = ""

    @staticmethod
    def _number(value, default=None):
        try:
            number = float(value)
            return number if number == number else default
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _direction_signal(prices, fast=5, slow=12):
        """Return CALL, PUT, or WAIT from a moving-average crossover."""
        prices = [TradingEngine._number(p) for p in prices]
        prices = [p for p in prices if p is not None]

        if len(prices) < slow + 1:
            return "WAIT"

        previous = prices[:-1]
        previous_fast = sum(previous[-fast:]) / fast
        previous_slow = sum(previous[-slow:]) / slow
        current_fast = sum(prices[-fast:]) / fast
        current_slow = sum(prices[-slow:]) / slow

        if previous_fast <= previous_slow and current_fast > current_slow:
            return "CALL"

        if previous_fast >= previous_slow and current_fast < current_slow:
            return "PUT"

        return "WAIT"

    def _trades(self, account_type):
        # Fail closed: an unavailable journal must never be treated
        # as proof that there are no open trades or losses.
        return self.journal.list_trades(
            limit=1000,
            account_type=account_type,
        )

    def _daily_net(self, account_type):
        today = datetime.now(timezone.utc).date()
        net = 0.0

        for trade in self._trades(account_type):
            status = str(trade.get("status", "")).upper()
            if status not in ("WON", "LOST", "SOLD"):
                continue

            stamp = (
                trade.get("exit_time")
                or trade.get("updated_at")
                or trade.get("created_at")
            )
            if not stamp:
                continue

            try:
                if isinstance(stamp, (int, float)):
                    trade_date = datetime.fromtimestamp(
                        stamp, timezone.utc
                    ).date()
                else:
                    parsed = datetime.fromisoformat(
                        str(stamp).replace("Z", "+00:00")
                    )
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    trade_date = parsed.astimezone(timezone.utc).date()
            except (ValueError, TypeError, OverflowError):
                continue

            if trade_date == today:
                net += self._number(trade.get("profit_loss"), 0.0)

        return net

    def _open_trades(self, account_type):
        return [
            trade for trade in self._trades(account_type)
            if str(trade.get("status", "")).upper() == "OPEN"
        ]

    def monitor_open_trades(self, account_type):
        """Update the journal only when Deriv confirms settlement."""
        for trade in self._open_trades(account_type):
            contract_id = trade.get("contract_id")
            if not contract_id:
                continue

            details = self.client.get_open_contract(
                account_type, contract_id
            )

            sold = details.get("is_sold") in (1, True, "1")
            status = str(details.get("status", "")).lower()

            if not sold and status not in (
                "won", "lost", "sold", "expired"
            ):
                continue

            profit = self._number(details.get("profit"))
            if profit is None:
                sell_price = self._number(details.get("sell_price"))
                buy_price = self._number(details.get("buy_price"))
                if sell_price is None or buy_price is None:
                    self.last_error = (
                        f"Cannot verify final P/L for {contract_id}."
                    )
                    continue
                profit = sell_price - buy_price

            final_status = (
                "WON" if profit > 0
                else "LOST" if profit < 0
                else "SOLD"
            )

            updated = self.journal.settle_trade(
                str(contract_id),
                status=final_status,
                profit_loss=profit,
                payout=self._number(details.get("payout")),
                exit_spot=details.get("exit_tick"),
                exit_time=datetime.now(timezone.utc).isoformat(),
                raw_data=details,
            )

            if updated and profit < 0:
                self.last_loss_time = time.time()

            self.last_action = (
                f"Contract {contract_id} settled; P/L {profit:.2f}"
            )

    def run_cycle(self, config):
        """Perform one safe analysis cycle. The app must call this repeatedly."""
        if not self.running:
            self.last_action = "Stopped: no new entries"
            return {"action": self.last_action}

        account_type = str(config.get("account_type", "")).lower()
        if account_type not in ("demo", "real"):
            self.last_action = "Blocked: choose Demo or Real account"
            return {"action": self.last_action}

        # Real is available when the user explicitly confirms it in the app.
        if account_type == "real" and not config.get("allow_real", False):
            self.last_action = "Blocked: confirm Real account trading in the app"
            return {"action": self.last_action}

        symbol = config.get("symbol")
        currency = config.get("currency")
        stake = self._number(config.get("stake"))
        max_stake = self._number(config.get("max_stake"))
        daily_loss_limit = self._number(
            config.get("daily_loss_limit")
        )
        max_open_trades = config.get("max_open_trades", 1)
        cooldown_seconds = config.get("cooldown_seconds", 60)
        loss_cooldown_seconds = config.get(
            "loss_cooldown_seconds", 300
        )
        duration = config.get("duration", 1)
        duration_unit = config.get("duration_unit", "t")
        contract_type = config.get("contract_type", "CALL")
        barrier = config.get("barrier")

        try:
            # Continue monitoring positions even when new entries are blocked.
            self.monitor_open_trades(account_type)

            if not symbol or not currency:
                raise ValueError("Market and account currency are required.")

            if stake is None or max_stake is None:
                raise ValueError("Stake and maximum stake must be valid numbers.")

            if stake <= 0 or stake > max_stake:
                self.last_action = "Blocked: stake exceeds the configured limit"
                return {"action": self.last_action}

            if daily_loss_limit is None or daily_loss_limit <= 0:
                raise ValueError("Daily loss limit must be greater than zero.")

            if self._daily_net(account_type) <= -daily_loss_limit:
                self.last_action = "Blocked: daily loss limit reached"
                return {"action": self.last_action}

            if len(self._open_trades(account_type)) >= int(max_open_trades):
                self.last_action = "Waiting: maximum open trades reached"
                return {"action": self.last_action}

            now = time.time()
            if now - self.last_trade_time < int(cooldown_seconds):
                self.last_action = "Waiting: entry cooldown"
                return {"action": self.last_action}

            if now - self.last_loss_time < int(loss_cooldown_seconds):
                self.last_action = "Waiting: cooldown after a loss"
                return {"action": self.last_action}

            # This first engine version automatically trades directional
            # crossover signals. Digit contracts are intentionally blocked
            # until their signal logic is connected and tested.
            if contract_type not in ("CALL", "PUT"):
                self.last_action = (
                    "Waiting: automatic signals for this contract "
                    "type are not implemented yet"
                )
                return {"action": self.last_action}

            tick_data = self.client.get_recent_ticks(symbol, count=60)
            prices = tick_data.get("prices", [])
            signal = self._direction_signal(prices)
            self.last_signal = signal

            if signal == "WAIT" or signal != contract_type:
                self.last_action = (
                    f"No matching signal for selected {contract_type} contract"
                )
                return {
                    "action": self.last_action,
                    "signal": signal,
                }

            # Verify selected account balance immediately before proposal.
            balance = self.client.get_balance(account_type)
            if balance.get("currency") != currency:
                raise ValueError(
                    "Selected currency does not match the account currency."
                )
            if stake > balance.get("balance", 0):
                raise ValueError("Stake exceeds the selected account balance.")

            proposal = self.client.get_proposal(
                account_type=account_type,
                symbol=symbol,
                contract_type=contract_type,
                amount=stake,
                currency=currency,
                duration=int(duration),
                duration_unit=duration_unit,
                barrier=barrier,
            )

            proposal_id = proposal.get("proposal_id")
            ask_price = self._number(proposal.get("ask_price"))

            if not proposal_id or ask_price is None:
                raise ValueError("Deriv did not return a valid proposal.")

            if ask_price <= 0 or ask_price > max_stake:
                self.last_action = "Blocked: proposal price exceeds the limit"
                return {"action": self.last_action}

            # Recheck balance and open-trade count just before buying.
            balance = self.client.get_balance(account_type)
            if ask_price > balance.get("balance", 0):
                raise ValueError("Insufficient selected-account balance.")

            if len(self._open_trades(account_type)) >= int(max_open_trades):
                self.last_action = "Blocked: open-trade limit reached"
                return {"action": self.last_action}

            bought = self.client.buy_contract(
                account_type=account_type,
                proposal_id=proposal_id,
                maximum_price=ask_price,
            )
            contract_id = bought.get("contract_id")

            if not contract_id:
                raise ValueError("Deriv did not confirm the purchase.")

            # Do not pass payout here: record_open_trade does not accept it.
            # Only write the journal after Deriv confirms a real contract ID.
            self.journal.record_open_trade(
                contract_id=str(contract_id),
                account_type=account_type,
                account_id=str(bought.get("account_id", "")),
                symbol=symbol,
                contract_type=contract_type,
                stake=ask_price,
                currency=currency,
                transaction_id=str(
                    bought.get("transaction_id", "")
                ) or None,
                entry_spot=proposal.get("spot"),
                buy_price=self._number(
                    bought.get("buy_price"), ask_price
                ),
                strategy="moving_average_crossover",
                notes=f"Automatic {contract_type} crossover",
                raw_data=bought.get("raw", bought),
            )

            self.last_trade_time = time.time()
            self.last_action = (
                f"Trade opened: {contract_type} {symbol}, "
                f"contract {contract_id}"
            )
            self.last_error = ""

            return {
                "action": self.last_action,
                "signal": signal,
                "contract_id": str(contract_id),
            }

        except Exception as exc:
            self.last_error = str(exc)
            self.last_action = f"Cycle error: {exc}"
            return {"action": self.last_action, "error": str(exc)}

    def start(self):
        self.running = True
        self.last_error = ""
        self.last_action = "Automation enabled"

    def stop(self):
        # Stop new entries. The dashboard must still call monitoring while
        # stopped so existing contracts can be recorded when they settle.
        self.running = False
        self.last_action = "Stopped: no new entries"

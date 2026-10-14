"""Deriv trading engine with risk controls and trade monitoring."""

from datetime import datetime, timezone
import time


class TradingEngine:
    """Manage automated entries and monitor existing contracts."""

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
            result = float(value)
            if result != result or abs(result) == float("inf"):
                return default
            return result
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _direction_signal(prices, fast=5, slow=12):
        values = [
            TradingEngine._number(price) for price in prices
        ]
        values = [value for value in values if value is not None]

        if fast < 1 or slow <= fast or len(values) < slow + 1:
            return "WAIT"

        previous = values[:-1]
        previous_fast = sum(previous[-fast:]) / fast
        previous_slow = sum(previous[-slow:]) / slow
        current_fast = sum(values[-fast:]) / fast
        current_slow = sum(values[-slow:]) / slow

        if previous_fast <= previous_slow and current_fast > current_slow:
            return "CALL"

        if previous_fast >= previous_slow and current_fast < current_slow:
            return "PUT"

        return "WAIT"

    def _trades(self, account_type):
        return self.journal.list_trades(
            limit=1000,
            account_type=account_type,
        )

    def _open_trades(self, account_type):
        return [
            trade
            for trade in self._trades(account_type)
            if str(trade.get("status", "")).upper() == "OPEN"
        ]

    def _daily_net(self, account_type):
        today = datetime.now(timezone.utc).date()
        total = 0.0

        for trade in self._trades(account_type):
            status = str(trade.get("status", "")).upper()
            if status not in ("WON", "LOST", "SOLD"):
                continue

            stamp = trade.get("exit_time") or trade.get("updated_at")
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
            except (ValueError, TypeError, OverflowError, OSError):
                continue

            if trade_date == today:
                total += self._number(
                    trade.get("profit_loss"), 0.0
                )

        return total

    def monitor_open_trades(self, account_type):
        messages = []

        for trade in self._open_trades(account_type):
            contract_id = trade.get("contract_id")
            if not contract_id:
                continue

            details = self.client.get_open_contract(
                account_type, contract_id
            )

            is_sold = details.get("is_sold") in (1, True, "1")
            status = str(details.get("status", "")).lower()

            if not is_sold and status not in (
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
                        "Cannot verify final profit or loss for "
                        + str(contract_id)
                    )
                    continue

                profit = sell_price - buy_price

            if profit > 0:
                final_status = "WON"
            elif profit < 0:
                final_status = "LOST"
            else:
                final_status = "SOLD"

            settled = self.journal.settle_trade(
                str(contract_id),
                status=final_status,
                profit_loss=profit,
                payout=self._number(details.get("payout")),
                exit_spot=details.get("exit_tick"),
                exit_time=datetime.now(timezone.utc).isoformat(),
                raw_data=details,
            )

            if settled:
                if profit < 0:
                    self.last_loss_time = time.time()

                messages.append(
                    "{}: {}, P/L {:.2f}".format(
                        contract_id, final_status, profit
                    )
                )

        if messages:
            self.last_action = "Settlement recorded: " + "; ".join(
                messages
            )

        return messages

    def run_cycle(self, config):
        account_type = str(
            config.get("account_type", "")
        ).lower()

        if account_type not in ("demo", "real"):
            self.last_action = "Blocked: select Demo or Real"
            return {"action": self.last_action}

        try:
            self.monitor_open_trades(account_type)

            if not self.running:
                if not self.last_action.startswith("Settlement recorded:"):
                    self.last_action = (
                        "Stopped: monitoring open trades only"
                    )
                return {"action": self.last_action}

            if account_type == "real" and not config.get(
                "allow_real", False
            ):
                self.last_action = (
                    "Blocked: confirm Real account trading"
                )
                return {"action": self.last_action}

            symbol = config.get("symbol")
            currency = config.get("currency")
            contract_type = str(
                config.get("contract_type", "CALL")
            ).upper()

            stake = self._number(config.get("stake"))
            max_stake = self._number(config.get("max_stake"))
            loss_limit = self._number(
                config.get("daily_loss_limit")
            )

            max_open = int(config.get("max_open_trades", 1))
            cooldown = int(config.get("cooldown_seconds", 60))
            loss_cooldown = int(
                config.get("loss_cooldown_seconds", 300)
            )
            duration = int(config.get("duration", 1))
            duration_unit = config.get("duration_unit", "t")
            barrier = config.get("barrier")

            if not symbol or not currency:
                raise ValueError("Select a market and currency.")

            if stake is None or max_stake is None:
                raise ValueError("Stake settings must be valid numbers.")

            if stake <= 0 or max_stake <= 0 or stake > max_stake:
                self.last_action = "Blocked: stake limit exceeded"
                return {"action": self.last_action}

            if loss_limit is None or loss_limit <= 0:
                raise ValueError("Daily loss limit must be positive.")

            if max_open < 1 or cooldown < 0 or loss_cooldown < 0:
                raise ValueError("Risk settings are invalid.")

            if duration < 1:
                raise ValueError("Duration must be at least one.")

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

            if contract_type not in ("CALL", "PUT"):
                self.last_action = (
                    "Waiting: this contract type has no implemented "
                    "automatic signal"
                )
                return {"action": self.last_action}

            tick_data = self.client.get_recent_ticks(
                symbol, count=60
            )
            signal = self._direction_signal(
                tick_data.get("prices", [])
            )
            self.last_signal = signal

            if signal == "WAIT" or signal != contract_type:
                self.last_action = (
                    "No matching signal; current signal: " + signal
                )
                return {
                    "action": self.last_action,
                    "signal": signal,
                }

            balance = self.client.get_balance(account_type)

            if str(balance.get("currency", "")).upper() != str(
                currency
            ).upper():
                raise ValueError("Account currency does not match.")

            available = self._number(balance.get("balance"), 0.0)
            if stake > available:
                raise ValueError("Stake exceeds available balance.")

            proposal = self.client.get_proposal(
                account_type=account_type,
                symbol=symbol,
                contract_type=contract_type,
                amount=stake,
                currency=currency,
                duration=duration,
                duration_unit=duration_unit,
                barrier=barrier,
            )

            proposal_id = proposal.get("proposal_id")
            ask_price = self._number(proposal.get("ask_price"))

            if not proposal_id or ask_price is None or ask_price <= 0:
                raise ValueError("Invalid proposal received from Deriv.")

            if ask_price > max_stake:
                self.last_action = (
                    "Blocked: purchase price exceeds maximum stake"
                )
                return {"action": self.last_action}

            balance = self.client.get_balance(account_type)
            available = self._number(balance.get("balance"), 0.0)

            if ask_price > available:
                raise ValueError("Insufficient account balance.")

            if len(self._open_trades(account_type)) >= max_open:
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

            self.journal.record_open_trade(
                contract_id=str(contract_id),
                account_type=account_type,
                account_id=str(bought.get("account_id", "")) or None,
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
                notes="Automatic {} crossover".format(contract_type),
                raw_data=bought.get("raw", bought),
            )

            self.last_trade_time = time.time()
            self.last_error = ""
            self.last_action = (
                "Trade opened: {} {}, contract {}".format(
                    contract_type, symbol, contract_id
                )
            )

            return {
                "action": self.last_action,
                "signal": signal,
                "contract_id": str(contract_id),
            }

        except Exception as exc:
            self.last_error = str(exc)
            self.last_action = "Cycle error: " + str(exc)
            return {
                "action": self.last_action,
                "error": str(exc),
            }

    def start(self):
        self.running = True
        self.last_error = ""
        self.last_action = "Automation enabled"

    def stop(self):
        self.running = False
        self.last_action = "Stopped: monitoring open trades only"
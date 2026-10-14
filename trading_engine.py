
"""
Deriv automated trading core.
Demo should be tested first. No strategy guarantees profit.
"""

from datetime import datetime, timezone
import time


class TradingEngine:
    def __init__(self, client, journal):
        self.client = client
        self.journal = journal
        self.running = False
        self.last_trade_time = 0
        self.last_loss_time = 0
        self.last_signal = None
        self.last_error = ""
        self.last_action = "Ready"
        self.seen_contracts = set()

    @staticmethod
    def _number(value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _nested(data, key):
        """Find a value inside common nested API response shapes."""
        if not isinstance(data, dict):
            return None
        if key in data:
            return data[key]
        for value in data.values():
            if isinstance(value, dict):
                found = TradingEngine._nested(value, key)
                if found is not None:
                    return found
        return None

    @staticmethod
    def _signal(prices, fast=5, slow=12):
        """Simple moving-average direction signal; not a profit guarantee."""
        if len(prices) < slow + 1:
            return None

        previous_fast = sum(prices[-fast-1:-1]) / fast
        previous_slow = sum(prices[-slow-1:-1]) / slow
        current_fast = sum(prices[-fast:]) / fast
        current_slow = sum(prices[-slow:]) / slow

        if previous_fast <= previous_slow and current_fast > current_slow:
            return "CALL"
        if previous_fast >= previous_slow and current_fast < current_slow:
            return "PUT"
        return None

    def _trades(self, account_type):
        try:
            return self.journal.list_trades(
                limit=1000, account_type=account_type
            )
        except Exception:
            return []

    def _daily_loss(self, account_type):
        today = datetime.now(timezone.utc).date()
        net = 0.0

        for trade in self._trades(account_type):
            status = str(trade.get("status", "")).lower()
            if status not in ("won", "lost", "sold", "settled"):
                continue

            stamp = (
                trade.get("exit_time")
                or trade.get("updated_at")
                or trade.get("created_at")
                or ""
            )
            if isinstance(stamp, (int, float)):
                trade_date = datetime.fromtimestamp(
                    stamp, timezone.utc
                ).date()
            else:
                try:
                    trade_date = datetime.fromisoformat(
                        str(stamp).replace("Z", "+00:00")
                    ).date()
                except (ValueError, TypeError):
                    continue

            if trade_date == today:
                net += self._number(
                    trade.get("profit_loss", trade.get("profit", 0))
                )

        return max(0.0, -net)

    def _open_trades(self, account_type):
        return [
            trade for trade in self._trades(account_type)
            if str(trade.get("status", "")).lower()
            in ("open", "pending")
        ]

    def monitor_open_trades(self, account_type):
        """Check open contracts and record their final result."""
        for trade in self._open_trades(account_type):
            contract_id = trade.get("contract_id")
            if not contract_id:
                continue

            try:
                response = self.client.get_open_contract(
                    account_type, contract_id
                )
                contract = self._nested(response, "proposal_open_contract")
                if not isinstance(contract, dict):
                    contract = response

                status = str(contract.get("status", "")).lower()
                sold = contract.get("is_sold") in (1, True, "1")
                if not sold and status not in (
                    "won", "lost", "sold", "expired"
                ):
                    continue

                profit = self._number(
                    contract.get("profit"),
                    self._number(contract.get("sell_price"))
                    - self._number(contract.get("buy_price")),
                )
                final_status = (
                    "won" if profit > 0 else "lost" if profit < 0
                    else "sold"
                )

                self.journal.settle_trade(
                    contract_id,
                    status=final_status,
                    profit_loss=profit,
                    payout=self._number(contract.get("payout")),
                    exit_spot=contract.get("exit_tick"),
                    exit_time=datetime.now(timezone.utc).isoformat(),
                    raw_data=contract,
                )

                if profit < 0:
                    self.last_loss_time = time.time()

                self.last_action = (
                    f"Contract {contract_id} settled: {profit:.2f}"
                )

            except Exception as exc:
                self.last_error = f"Monitoring: {exc}"

    def run_cycle(self, config):
        """
        Run one analysis/trading cycle.
        Call this repeatedly from the app while automation is enabled.

        Required config:
          account_type: "demo" or "real"
          symbol: Deriv symbol, e.g. "R_100"
          stake: trade amount
          currency: account currency, e.g. "USD"

        Optional config:
          max_stake=1.0, daily_loss_limit=5.0,
          max_open_trades=1, cooldown_seconds=60,
          loss_cooldown_seconds=300, duration=5,
          duration_unit="t", allow_real=False
        """
        if not self.running:
            self.last_action = "Stopped: no new trades"
            return {"action": self.last_action}

        account_type = str(config.get("account_type", "demo")).lower()
        symbol = config.get("symbol", "R_100")
        currency = config.get("currency", "USD")
        stake = self._number(config.get("stake", 1))
        max_stake = self._number(config.get("max_stake", 1))
        daily_limit = self._number(
            config.get("daily_loss_limit", 5)
        )
        max_open = int(config.get("max_open_trades", 1))
        cooldown = int(config.get("cooldown_seconds", 60))
        loss_cooldown = int(
            config.get("loss_cooldown_seconds", 300)
        )
        duration = int(config.get("duration", 5))
        duration_unit = config.get("duration_unit", "t")

        try:
            # Keep managing existing trades, even if risk limits block entries.
            self.monitor_open_trades(account_type)

            if account_type == "real" and not config.get(
                "allow_real", False
            ):
                self.last_action = "Real trading is disabled by safety lock"
                return {"action": self.last_action}

            if stake <= 0 or stake > max_stake:
                self.last_action = "Blocked: stake exceeds the allowed limit"
                return {"action": self.last_action}

            if self._daily_loss(account_type) >= daily_limit:
                self.last_action = "Blocked: daily loss limit reached"
                return {"action": self.last_action}

            if len(self._open_trades(account_type)) >= max_open:
                self.last_action = "Waiting: maximum open trades reached"
                return {"action": self.last_action}

            now = time.time()
            if now - self.last_trade_time < cooldown:
                self.last_action = "Waiting: entry cooldown"
                return {"action": self.last_action}

            if now - self.last_loss_time < loss_cooldown:
                self.last_action = "Waiting: cooldown after a loss"
                return {"action": self.last_action}

            tick_data = self.client.get_recent_ticks(symbol, count=60)
            prices = tick_data.get("prices", [])
            prices = [self._number(p) for p in prices]

            signal = self._signal(prices)
            self.last_signal = signal

            if signal not in ("CALL", "PUT"):
                self.last_action = "No clear moving-average signal"
                return {"action": self.last_action, "signal": signal}

            proposal_response = self.client.get_proposal(
                account_type=account_type,
                symbol=symbol,
                contract_type=signal,
                amount=stake,
                currency=currency,
                duration=duration,
                duration_unit=duration_unit,
            )

            proposal = self._nested(proposal_response, "proposal")
            if not isinstance(proposal, dict):
                proposal = proposal_response

            proposal_id = proposal.get("id")
            ask_price = self._number(
                proposal.get("ask_price"), stake
            )

            if not proposal_id or ask_price <= 0 or ask_price > max_stake:
                self.last_action = "Blocked: invalid proposal or price"
                return {"action": self.last_action}

            buy_response = self.client.buy_contract(
                account_type, proposal_id, ask_price
            )
            contract_id = self._nested(buy_response, "contract_id")

            if contract_id is None:
                self.last_action = "Buy not confirmed by Deriv"
                return {"action": self.last_action}

            self.journal.record_open_trade(
                contract_id=str(contract_id),
                account_type=account_type,
                symbol=symbol,
                contract_type=signal,
                stake=ask_price,
                currency=currency,
                buy_price=ask_price,
                strategy="moving_average_crossover",
                notes=f"Automatic signal: {signal}",
                raw_data=buy_response,
            )

            self.last_trade_time = time.time()
            self.last_action = (
                f"Trade opened: {signal} {symbol}, "
                f"contract {contract_id}"
            )
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
        # Prevent new entries; run_cycle can still monitor existing trades.
        self.running = False
        self.last_action = "Stopped: no new trades"

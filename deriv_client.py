import json
import websocket


class DerivAPIError(Exception):
    """Error returned by the Deriv API or connection."""


class DerivClient:
    def __init__(self, app_id, token=None):
        self.app_id = str(app_id or "").strip()
        self.token = (token or "").strip()

        if not self.app_id.isdigit():
            raise DerivAPIError("Enter a valid numeric Deriv App ID.")

        if not self.token:
            raise DerivAPIError("Enter the API token for the selected account.")

    def _open(self):
        url = f"wss://ws.derivws.com/websockets/v3?app_id={self.app_id}"

        try:
            return websocket.create_connection(url, timeout=20)
        except Exception as exc:
            raise DerivAPIError(f"Connection failed: {exc}") from exc

    def _request(self, ws, payload):
        req_id = payload.get("req_id")
        ws.send(json.dumps(payload))

        while True:
            try:
                raw = ws.recv()
                if not raw:
                    raise DerivAPIError("Deriv closed the connection.")
                response = json.loads(raw)
            except DerivAPIError:
                raise
            except Exception as exc:
                raise DerivAPIError(
                    f"Could not read Deriv response: {exc}"
                ) from exc

            if response.get("error"):
                error = response["error"]
                raise DerivAPIError(
                    error.get("message", "Deriv API error")
                )

            if req_id is None or response.get("req_id") == req_id:
                return response

    def _authenticated_request(self, payload):
        ws = self._open()

        try:
            auth = self._request(
                ws,
                {"authorize": self.token, "req_id": 1},
            )

            account = auth.get("authorize")

            if not account:
                raise DerivAPIError(
                    "Deriv did not confirm account authorization."
                )

            response = self._request(
                ws,
                {**payload, "req_id": 2},
            )

            return account, response

        finally:
            ws.close()

    def get_balance(self):
        account, response = self._authenticated_request(
            {"balance": 1}
        )

        details = response.get("balance", {})

        return {
            "loginid": account.get("loginid", "Unknown"),
            "currency": (
                details.get("currency")
                or account.get("currency", "")
            ),
            "balance": float(details.get("balance", 0)),
        }

    def get_active_symbols(self):
        # Public market-data request; no account token is needed.
        ws = self._open()

        try:
            response = self._request(
                ws,
                {"active_symbols": "brief", "req_id": 1},
            )
        finally:
            ws.close()

        markets = response.get("active_symbols", [])
        normalized = {}

        for market in markets:
            symbol = (
                market.get("underlying_symbol")
                or market.get("symbol")
            )

            name = (
                market.get("underlying_symbol_name")
                or market.get("display_name")
                or symbol
            )

            if symbol and name:
                normalized[symbol] = {
                    **market,
                    "symbol": symbol,
                    "display_name": name,
                }

        return sorted(
            normalized.values(),
            key=lambda item: item["display_name"].lower(),
        )

    def get_contract_types(self, symbol):
        # Market-data endpoint; authentication is not required.
        ws = self._open()

        try:
            response = self._request(
                ws,
                {"contracts_for": symbol, "req_id": 1},
            )
        finally:
            ws.close()

        contracts = response.get(
            "contracts_for", {}
        ).get("available", [])

        labels = {
            "DIGITOVER": "Over",
            "DIGITUNDER": "Under",
            "DIGITMATCH": "Matches",
            "DIGITDIFF": "Differs",
            "DIGITEVEN": "Even",
            "DIGITODD": "Odd",
        }

        supported = {}

        for contract in contracts:
            code = contract.get("contract_type")

            if code in labels:
                supported[labels[code]] = code

        return supported

    def get_recent_ticks(self, symbol, count=100):
        ws = self._open()

        try:
            response = self._request(
                ws,
                {
                    "ticks_history": symbol,
                    "count": max(10, min(int(count), 500)),
                    "end": "latest",
                    "style": "ticks",
                    "req_id": 1,
                },
            )
        finally:
            ws.close()

        history = response.get("history", {})

        return {
            "prices": [
                float(price)
                for price in history.get("prices", [])
            ],
            "times": history.get("times", []),
        }

    def get_open_positions(self):
        _, response = self._authenticated_request(
            {"portfolio": 1}
        )

        return response.get(
            "portfolio", {}
        ).get("contracts", [])

    def get_contract_status(self, contract_id):
        _, response = self._authenticated_request(
            {
                "proposal_open_contract": 1,
                "contract_id": int(contract_id),
            }
        )

        return response.get(
            "proposal_open_contract", {}
        )

    def get_statement(self, limit=25):
        _, response = self._authenticated_request(
            {
                "statement": 1,
                "description": 1,
                "limit": max(1, min(int(limit), 100)),
            }
        )

        return response.get(
            "statement", {}
        ).get("transactions", [])

    def buy_digit_contract(
        self,
        symbol,
        contract_type,
        stake,
        currency,
        duration_ticks=1,
        barrier=None,
    ):
        allowed = {
            "DIGITOVER",
            "DIGITUNDER",
            "DIGITMATCH",
            "DIGITDIFF",
            "DIGITEVEN",
            "DIGITODD",
        }

        if contract_type not in allowed:
            raise DerivAPIError("Unsupported digit contract type.")

        if not symbol:
            raise DerivAPIError("Select a market first.")

        stake = float(stake)
        duration_ticks = int(duration_ticks)
        currency = str(currency or "").strip().upper()

        if stake <= 0:
            raise DerivAPIError("Stake must be greater than zero.")

        if not 1 <= duration_ticks <= 10:
            raise DerivAPIError(
                "Duration must be between 1 and 10 ticks."
            )

        if not currency:
            raise DerivAPIError("Account currency is required.")

        needs_digit = contract_type in {
            "DIGITOVER",
            "DIGITUNDER",
            "DIGITMATCH",
            "DIGITDIFF",
        }

        if needs_digit:
            if barrier is None or not 0 <= int(barrier) <= 9:
                raise DerivAPIError(
                    "Enter a prediction digit from 0 to 9."
                )

        ws = self._open()

        try:
            auth = self._request(
                ws,
                {"authorize": self.token, "req_id": 1},
            )

            account = auth.get("authorize")

            if not account:
                raise DerivAPIError("Authorization failed.")

            # Check the account currency to avoid accidental mismatch.
            account_currency = str(
                account.get("currency", "")
            ).upper()

            if account_currency and currency != account_currency:
                raise DerivAPIError(
                    f"Selected currency {currency} does not match "
                    f"account currency {account_currency}."
                )

            proposal = {
                "proposal": 1,
                "amount": stake,
                "basis": "stake",
                "contract_type": contract_type,
                "currency": currency,
                "duration": duration_ticks,
                "duration_unit": "t",
                "underlying_symbol": symbol,
                "req_id": 2,
            }

            if needs_digit:
                proposal["barrier"] = str(int(barrier))

            proposal_response = self._request(ws, proposal)
            offer = proposal_response.get("proposal", {})

            proposal_id = offer.get("id")
            ask_price = offer.get("ask_price")

            if not proposal_id or ask_price is None:
                raise DerivAPIError(
                    "Deriv did not return a valid trade proposal."
                )

            purchase_response = self._request(
                ws,
                {
                    "buy": proposal_id,
                    "price": float(ask_price),
                    "req_id": 3,
                },
            )

            bought = purchase_response.get("buy", {})
            contract_id = bought.get("contract_id")

            if not contract_id:
                raise DerivAPIError(
                    "Deriv did not confirm the purchase."
                )

            return {
                "contract_id": contract_id,
                "buy_price": bought.get("buy_price"),
                "payout": bought.get("payout"),
                "longcode": bought.get("longcode", ""),
                "loginid": account.get("loginid", ""),
            }

        finally:
            ws.close()
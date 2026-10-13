import json
import websocket


class DerivAPIError(Exception):
    pass


class DerivClient:
    def __init__(self, app_id, token=None):
        self.app_id = str(app_id or "").strip()
        self.token = (token or "").strip()

        if not self.app_id.isdigit():
            raise DerivAPIError("Enter a valid numeric Deriv App ID.")

        if not self.token:
            raise DerivAPIError("Enter the API token for your selected account.")

    def _open(self):
        url = f"wss://ws.derivws.com/websockets/v3?app_id={self.app_id}"

        try:
            return websocket.create_connection(url, timeout=20)
        except Exception as exc:
            raise DerivAPIError(
                f"Could not connect to Deriv: {exc}"
            ) from exc

    def _send_receive(self, ws, payload):
        req_id = payload.get("req_id")
        ws.send(json.dumps(payload))

        while True:
            try:
                response = json.loads(ws.recv())
            except Exception as exc:
                raise DerivAPIError(
                    f"Invalid response from Deriv: {exc}"
                ) from exc

            if response.get("error"):
                raise DerivAPIError(
                    response["error"].get("message", "Deriv API error")
                )

            if req_id is None or response.get("req_id") == req_id:
                return response

    def _authenticated_request(self, payload):
        ws = self._open()

        try:
            auth_response = self._send_receive(
                ws,
                {"authorize": self.token, "req_id": 1},
            )

            account = auth_response.get("authorize")

            if not account:
                raise DerivAPIError(
                    "Deriv did not confirm account authorization."
                )

            response = self._send_receive(
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

        balance = response.get("balance", {})

        return {
            "loginid": account.get("loginid", "Unknown"),
            "currency": balance.get("currency")
            or account.get("currency", ""),
            "balance": float(balance.get("balance", 0)),
        }

    def get_active_symbols(self):
        _, response = self._authenticated_request(
            {
                "active_symbols": "brief",
                "product_type": "basic",
            }
        )

        markets = response.get("active_symbols", [])
        normalized = {}

        for market in markets:
            # Accept both older and newer market field names.
            symbol = (
                market.get("symbol")
                or market.get("underlying_symbol")
            )

            name = (
                market.get("display_name")
                or market.get("underlying_symbol_name")
                or market.get("underlying_symbol")
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
        _, response = self._authenticated_request(
            {"contracts_for": symbol}
        )

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

        if float(stake) <= 0:
            raise DerivAPIError("Stake must be greater than zero.")

        if not 1 <= int(duration_ticks) <= 10:
            raise DerivAPIError(
                "Duration must be between 1 and 10 ticks."
            )

        if not currency:
            raise DerivAPIError("Enter the account currency.")

        needs_digit = contract_type in {
            "DIGITOVER",
            "DIGITUNDER",
            "DIGITMATCH",
            "DIGITDIFF",
        }

        if needs_digit and (
            barrier is None or not 0 <= int(barrier) <= 9
        ):
            raise DerivAPIError(
                "Enter a prediction digit from 0 to 9."
            )

        ws = self._open()

        try:
            auth_response = self._send_receive(
                ws,
                {"authorize": self.token, "req_id": 1},
            )

            account = auth_response.get("authorize")

            if not account:
                raise DerivAPIError(
                    "Deriv authorization failed."
                )

            proposal = {
                "proposal": 1,
                "amount": float(stake),
                "basis": "stake",
                "contract_type": contract_type,
                "currency": currency,
                "duration": int(duration_ticks),
                "duration_unit": "t",
                "underlying_symbol": symbol,
                "req_id": 2,
            }

            if needs_digit:
                proposal["barrier"] = str(int(barrier))

            proposal_response = self._send_receive(
                ws, proposal
            )

            offer = proposal_response.get("proposal", {})
            proposal_id = offer.get("id")
            ask_price = offer.get("ask_price")

            if not proposal_id or ask_price is None:
                raise DerivAPIError(
                    "Deriv did not return a valid trade proposal."
                )

            purchase_response = self._send_receive(
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
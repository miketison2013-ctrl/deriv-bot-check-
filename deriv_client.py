
import json
import websocket


class DerivAPIError(Exception):
    pass


class DerivClient:
    def __init__(self, app_id, token=None):
        self.app_id = str(app_id).strip()
        self.token = (token or "").strip()

        if not self.app_id.isdigit():
            raise DerivAPIError("The Deriv App ID must be numeric.")

        if not self.token:
            raise DerivAPIError("Enter the API token for the selected account.")

    def _send_receive(self, ws, payload):
        ws.send(json.dumps(payload))

        while True:
            raw = ws.recv()
            data = json.loads(raw)

            if data.get("error"):
                message = data["error"].get("message", "Deriv API error")
                raise DerivAPIError(message)

            if data.get("req_id") == payload.get("req_id"):
                return data

    def _open(self):
        url = (
            "wss://ws.derivws.com/websockets/v3"
            f"?app_id={self.app_id}"
        )
        return websocket.create_connection(url, timeout=15)

    def _authenticated_request(self, payload):
        ws = self._open()

        try:
            auth = self._send_receive(
                ws,
                {"authorize": self.token, "req_id": 1},
            )

            if not auth.get("authorize"):
                raise DerivAPIError("Deriv authorization failed.")

            result = self._send_receive(
                ws,
                {**payload, "req_id": 2},
            )
            return auth["authorize"], result
        finally:
            ws.close()

    def get_balance(self):
        account, response = self._authenticated_request(
            {"balance": 1}
        )

        balance = response.get("balance", {})
        return {
            "loginid": account.get("loginid", "Unknown"),
            "currency": balance.get(
                "currency", account.get("currency", "")
            ),
            "balance": float(balance.get("balance", 0)),
        }

    def get_active_symbols(self):
        _, response = self._authenticated_request(
            {"active_symbols": "brief"}
        )

        symbols = response.get("active_symbols", [])

        return [
            item for item in symbols
            if item.get("symbol") and item.get("display_name")
        ]

    def get_contract_types(self, symbol):
        _, response = self._authenticated_request(
            {"contracts_for": symbol}
        )

        contracts = response.get("contracts_for", {}).get(
            "available", []
        )

        supported = {
            "DIGITOVER": "Over",
            "DIGITUNDER": "Under",
            "DIGITMATCH": "Matches",
            "DIGITDIFF": "Differs",
            "DIGITEVEN": "Even",
            "DIGITODD": "Odd",
        }

        result = {}

        for contract in contracts:
            code = contract.get("contract_type")
            if code in supported:
                result[supported[code]] = code

        return result

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

        if stake <= 0:
            raise DerivAPIError("Stake must be greater than zero.")

        if not 1 <= int(duration_ticks) <= 10:
            raise DerivAPIError("Duration must be between 1 and 10 ticks.")

        needs_digit = contract_type in {
            "DIGITOVER", "DIGITUNDER",
            "DIGITMATCH", "DIGITDIFF",
        }

        if needs_digit and (
            barrier is None or not 0 <= int(barrier) <= 9
        ):
            raise DerivAPIError(
                "This contract requires a prediction digit from 0 to 9."
            )

        ws = self._open()

        try:
            auth = self._send_receive(
                ws,
                {"authorize": self.token, "req_id": 1},
            )

            account = auth.get("authorize", {})
            if not account:
                raise DerivAPIError("Deriv authorization failed.")

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

            price_response = self._send_receive(ws, proposal)
            offer = price_response.get("proposal", {})
            proposal_id = offer.get("id")
            ask_price = float(offer.get("ask_price", 0))

            if not proposal_id or ask_price <= 0:
                raise DerivAPIError(
                    "Deriv did not return a valid trade proposal."
                )

            purchase = self._send_receive(
                ws,
                {
                    "buy": proposal_id,
                    "price": ask_price,
                    "req_id": 3,
                },
            )

            bought = purchase.get("buy", {})

            if not bought.get("contract_id"):
                raise DerivAPIError(
                    "Purchase confirmation was not received."
                )

            return {
                "contract_id": bought["contract_id"],
                "buy_price": bought.get("buy_price"),
                "payout": bought.get("payout"),
                "longcode": bought.get("longcode", ""),
                "loginid": account.get("loginid", ""),
            }
        finally:
            ws.close()

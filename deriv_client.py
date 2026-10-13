import json
import requests
import websocket


API_BASE = "https://api.derivws.com"
PUBLIC_WS = (
    "wss://api.derivws.com/"
    "trading/v1/options/ws/public"
)


class DerivAPIError(Exception):
    """Readable Deriv API error."""


class DerivClient:
    def __init__(self, app_id, token):
        self.app_id = str(app_id or "").strip()
        self.token = str(token or "").strip()

        if not self.app_id:
            raise DerivAPIError("Enter your Deriv App ID.")

        if not self.token:
            raise DerivAPIError(
                "Enter your Deriv Personal Access Token."
            )

        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.token}",
            "Deriv-App-ID": self.app_id,
            "Accept": "application/json",
        })

    def _rest(self, method, path):
        try:
            response = self.session.request(
                method,
                API_BASE + path,
                timeout=20,
            )

            try:
                result = response.json()
            except ValueError:
                result = {}

            if not response.ok:
                errors = result.get("errors", [])
                message = (
                    errors[0].get("message")
                    if errors and isinstance(errors[0], dict)
                    else result.get("message")
                )

                if response.status_code == 401:
                    message = (
                        "Authentication failed. Check your token."
                    )
                elif response.status_code == 403:
                    message = (
                        "Access denied. Check your token permissions "
                        "and App ID."
                    )

                raise DerivAPIError(
                    message
                    or f"Deriv REST error: HTTP {response.status_code}"
                )

            return result.get("data", result)

        except DerivAPIError:
            raise
        except requests.RequestException as exc:
            raise DerivAPIError(
                f"Could not reach Deriv: {exc}"
            ) from exc

    def get_accounts(self):
        result = self._rest(
            "GET",
            "/trading/v1/options/accounts",
        )

        if isinstance(result, dict):
            result = result.get(
                "accounts",
                result.get("items", [result]),
            )

        if not isinstance(result, list):
            raise DerivAPIError(
                "Unexpected account response from Deriv."
            )

        accounts = []

        for item in result:
            if not isinstance(item, dict):
                continue

            account_id = (
                item.get("account_id")
                or item.get("accountId")
                or item.get("id")
            )

            if not account_id:
                continue

            account_type = str(
                item.get("account_type")
                or item.get("type")
                or ""
            ).lower()

            if "demo" in account_type:
                account_type = "demo"
            elif "real" in account_type:
                account_type = "real"

            accounts.append({
                **item,
                "account_id": str(account_id),
                "account_type": account_type,
                "currency": item.get("currency", "USD"),
            })

        if not accounts:
            raise DerivAPIError(
                "No Options accounts were returned. "
                "Check your token permissions and account access."
            )

        return accounts

    def get_account(self, account_type):
        wanted = str(account_type).lower()

        matches = [
            account
            for account in self.get_accounts()
            if account.get("account_type") == wanted
        ]

        if not matches:
            raise DerivAPIError(
                f"No accessible {wanted} account was found."
            )

        return matches[0]

    def _get_ws_url(self, account_id):
        result = self._rest(
            "POST",
            f"/trading/v1/options/accounts/"
            f"{account_id}/otp",
        )

        url = result.get("url") if isinstance(result, dict) else None

        if not url:
            raise DerivAPIError(
                "Deriv did not return a WebSocket URL."
            )

        return url

    def _open_public(self):
        try:
            return websocket.create_connection(
                PUBLIC_WS,
                timeout=15,
                enable_multithread=True,
            )
        except Exception as exc:
            raise DerivAPIError(
                f"Public market connection failed: {exc}"
            ) from exc

    def _open_account(self, account_type):
        account = self.get_account(account_type)
        url = self._get_ws_url(account["account_id"])

        try:
            ws = websocket.create_connection(
                url,
                timeout=15,
                enable_multithread=True,
            )
            return account, ws
        except Exception as exc:
            raise DerivAPIError(
                f"Account WebSocket connection failed: {exc}"
            ) from exc

    def _request(self, ws, payload):
        req_id = payload.get("req_id")

        try:
            ws.send(json.dumps(payload))

            while True:
                raw = ws.recv()

                if not raw:
                    raise DerivAPIError(
                        "Deriv closed the connection."
                    )

                response = json.loads(raw)

                if response.get("error"):
                    error = response["error"]
                    raise DerivAPIError(
                        error.get("message", "Deriv API error")
                    )

                if (
                    req_id is None
                    or response.get("req_id") == req_id
                ):
                    return response

        except DerivAPIError:
            raise
        except Exception as exc:
            raise DerivAPIError(
                f"Could not read Deriv response: {exc}"
            ) from exc

    def get_balance(self, account_type):
        account, ws = self._open_account(account_type)

        try:
            result = self._request(
                ws,
                {"balance": 1, "req_id": 1},
            )
        finally:
            ws.close()

        balance = result.get("balance", {})

        return {
            "account_id": account["account_id"],
            "account_type": account_type,
            "currency": (
                balance.get("currency")
                or account.get("currency", "USD")
            ),
            "balance": float(balance.get("balance", 0)),
        }

    def get_active_symbols(self):
        ws = self._open_public()

        try:
            result = self._request(
                ws,
                {
                    "active_symbols": "brief",
                    "req_id": 1,
                },
            )
        finally:
            ws.close()

        symbols = result.get("active_symbols", [])
        markets = {}

        for item in symbols:
            symbol = (
                item.get("underlying_symbol")
                or item.get("symbol")
            )

            name = (
                item.get("underlying_symbol_name")
                or item.get("display_name")
                or symbol
            )

            if symbol and name:
                markets[symbol] = {
                    **item,
                    "symbol": symbol,
                    "display_name": name,
                }

        return sorted(
            markets.values(),
            key=lambda item: item["display_name"].lower(),
        )

    def get_recent_ticks(self, symbol, count=100):
        ws = self._open_public()

        try:
            result = self._request(
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

        history = result.get("history", {})

        return {
            "prices": [
                float(price)
                for price in history.get("prices", [])
            ],
            "times": history.get("times", []),
        }

    def get_latest_tick(self, symbol):
        ws = self._open_public()

        try:
            result = self._request(
                ws,
                {
                    "ticks": symbol,
                    "subscribe": 1,
                    "req_id": 1,
                },
            )

            tick = result.get("tick", {})

            if not tick or tick.get("quote") is None:
                raise DerivAPIError(
                    "Deriv did not return a current market price."
                )

            return {
                "symbol": symbol,
                "quote": float(tick["quote"]),
                "epoch": tick.get("epoch"),
            }

        finally:
            ws.close()

    def get_contract_types(self, symbol):
        ws = self._open_public()

        try:
            result = self._request(
                ws,
                {
                    "contracts_for": symbol,
                    "req_id": 1,
                },
            )
        finally:
            ws.close()

        available = result.get(
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

        return {
            labels[item["contract_type"]]: item["contract_type"]
            for item in available
            if item.get("contract_type") in labels
        }
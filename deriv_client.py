
"""Deriv API client for digit-contract trading."""

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Optional
from urllib.parse import urlencode

import requests
import websocket


class DerivAPIError(RuntimeError):
    """Raised when a Deriv API request fails."""


class DerivClient:
    REST_URL = "https://api.derivws.com"
    WS_BASE_URL = "wss://ws.derivws.com/websockets/v3"

    DIGIT_CONTRACTS = {
        "DIGITOVER",
        "DIGITUNDER",
        "DIGITMATCH",
        "DIGITDIFF",
        "DIGITEVEN",
        "DIGITODD",
    }

    def __init__(
        self,
        api_token: str,
        app_id: str,
        timeout: int = 15,
    ):
        self.api_token = (api_token or "").strip()
        self.app_id = (app_id or "").strip()
        self.timeout = max(5, int(timeout))

        if not self.api_token:
            raise DerivAPIError("Enter your Deriv API token.")

        if not self.app_id or not self.app_id.isalnum():
            raise DerivAPIError(
                "Enter a valid App ID containing letters or digits."
            )

        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_token}",
            "Deriv-App-ID": self.app_id,
            "Accept": "application/json",
            "Content-Type": "application/json",
        })

    @staticmethod
    def _number(value: Any, label: str) -> float:
        try:
            number = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            raise DerivAPIError(f"Invalid {label}.")

        if not number.is_finite():
            raise DerivAPIError(f"Invalid {label}.")

        return float(number)

    @staticmethod
    def _account_type(value: str) -> str:
        value = str(value or "").strip().lower()

        if value in ("demo", "virtual", "practice"):
            return "demo"

        if value in ("real", "live"):
            return "real"

        raise DerivAPIError("Account type must be Demo or Real.")

    def _rest(
        self,
        method: str,
        path: str,
        body: Optional[dict] = None,
    ) -> dict:
        try:
            response = self.session.request(
                method=method.upper(),
                url=self.REST_URL + path,
                json=body,
                timeout=self.timeout,
            )

            try:
                data = response.json()
            except ValueError:
                data = {}

            if not response.ok:
                if isinstance(data, dict):
                    error = data.get("error", {})
                    if isinstance(error, dict):
                        error = error.get("message", "")
                    message = (
                        data.get("message")
                        or error
                        or response.text[:300]
                        or f"HTTP {response.status_code}"
                    )
                else:
                    message = f"HTTP {response.status_code}"

                raise DerivAPIError(
                    f"Deriv REST error: {message}"
                )

            if not isinstance(data, dict):
                raise DerivAPIError(
                    "Unexpected Deriv REST response."
                )

            if data.get("error"):
                raise DerivAPIError(str(data["error"]))

            return data

        except DerivAPIError:
            raise
        except requests.RequestException as exc:
            raise DerivAPIError(
                f"Deriv connection failed: {exc}"
            ) from exc

    @staticmethod
    def _extract_data(response: dict) -> Any:
        return response.get("data", response)

    def get_accounts(self) -> list:
        response = self._rest(
            "GET",
            "/trading/v1/options/accounts",
        )
        data = self._extract_data(response)

        if isinstance(data, dict):
            accounts = data.get(
                "accounts",
                data.get("items", []),
            )
        elif isinstance(data, list):
            accounts = data
        else:
            accounts = []

        result = []

        for account in accounts:
            if not isinstance(account, dict):
                continue

            account_id = (
                account.get("account_id")
                or account.get("id")
                or account.get("loginid")
            )

            if not account_id:
                continue

            account_type = str(
                account.get("account_type")
                or account.get("type")
                or account.get("landing_company")
                or ""
            ).lower()

            result.append({
                **account,
                "account_id": str(account_id),
                "account_type": account_type,
                "currency": account.get("currency", ""),
            })

        return result

    @staticmethod
    def _account_matches(
        account: dict,
        wanted: str,
    ) -> bool:
        account_id = str(
            account.get("account_id")
            or account.get("loginid")
            or ""
        ).upper()

        description = " ".join([
            str(account.get("account_type", "")),
            str(account.get("type", "")),
            str(account.get("landing_company", "")),
        ]).lower()

        is_demo = (
            "demo" in description
            or "virtual" in description
            or "practice" in description
            or account_id.startswith("VRTC")
        )

        is_real = (
            "real" in description
            or "live" in description
            or account_id.startswith("CR")
        )

        return is_demo if wanted == "demo" else (
            is_real and not is_demo
        )

    def get_account(self, account_type: str) -> dict:
        wanted = self._account_type(account_type)

        matches = [
            account for account in self.get_accounts()
            if self._account_matches(account, wanted)
        ]

        if not matches:
            raise DerivAPIError(
                f"No {wanted.upper()} options account was found "
                "for this token."
            )

        return matches[0]

    def _get_ws_url(self, account_type: str) -> str:
        account = self.get_account(account_type)
        account_id = account["account_id"]

        response = self._rest(
            "POST",
            f"/trading/v1/options/accounts/{account_id}/otp",
        )

        data = self._extract_data(response)

        url = None
        if isinstance(data, dict):
            url = data.get("url") or data.get("ws_url")

        if not url or not str(url).startswith("wss://"):
            raise DerivAPIError(
                "Deriv did not return a valid authenticated "
                "WebSocket URL."
            )

        return str(url)

    def _request(self, ws, payload: dict) -> dict:
        req_id = payload.get("req_id")

        try:
            ws.send(json.dumps(payload))

            while True:
                raw = ws.recv()

                if not raw:
                    raise DerivAPIError(
                        "Deriv closed the WebSocket before replying."
                    )

                try:
                    response = json.loads(raw)
                except (TypeError, ValueError) as exc:
                    raise DerivAPIError(
                        "Deriv returned invalid JSON."
                    ) from exc

                if not isinstance(response, dict):
                    continue

                error = response.get("error")
                if error:
                    if isinstance(error, dict):
                        code = error.get("code", "APIError")
                        message = error.get(
                            "message",
                            "Request failed",
                        )
                        details = error.get("details")

                        message = (
                            f"Deriv API error [{code}]: {message}"
                        )
                        if details:
                            message += f" | Details: {details}"
                    else:
                        message = f"Deriv API error: {error}"

                    raise DerivAPIError(message)

                if (
                    req_id is None
                    or response.get("req_id") == req_id
                ):
                    return response

        except DerivAPIError:
            raise
        except Exception as exc:
            raise DerivAPIError(
                f"WebSocket request failed: {exc}"
            ) from exc

    def _ws_request(
        self,
        url: str,
        payload: dict,
    ) -> dict:
        ws = None

        try:
            ws = websocket.create_connection(
                url,
                timeout=self.timeout,
                enable_multithread=True,
            )
            return self._request(ws, payload)

        except DerivAPIError:
            raise
        except Exception as exc:
            raise DerivAPIError(
                f"Could not complete Deriv WebSocket request: {exc}"
            ) from exc
        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass

    def _public_request(self, payload: dict) -> dict:
        query = urlencode({"app_id": self.app_id})
        url = f"{self.WS_BASE_URL}?{query}"
        return self._ws_request(url, payload)

    def _account_request(
        self,
        account_type: str,
        payload: dict,
    ) -> dict:
        url = self._get_ws_url(account_type)
        return self._ws_request(url, payload)

    def get_balance(self, account_type: str) -> dict:
        response = self._account_request(
            account_type,
            {
                "balance": 1,
                "req_id": 201,
            },
        )

        data = response.get("balance") or response.get("data")

        if not isinstance(data, dict):
            raise DerivAPIError(
                "Deriv returned no balance data."
            )

        return data

    def get_active_symbols(self) -> list:
        response = self._public_request({
            "active_symbols": "brief",
            "req_id": 301,
        })

        symbols = response.get("active_symbols", [])
        result = []

        for item in symbols:
            if not isinstance(item, dict):
                continue

            symbol = (
                item.get("symbol")
                or item.get("underlying_symbol")
            )

            if not symbol:
                continue

            result.append({
                **item,
                "symbol": str(symbol),
                "name": (
                    item.get("display_name")
                    or item.get("underlying_symbol_name")
                    or str(symbol)
                ),
            })

        return result

    def get_recent_ticks(
        self,
        symbol: str,
        count: int = 150,
    ) -> list:
        count = max(2, min(int(count), 1000))

        response = self._public_request({
            "ticks_history": str(symbol),
            "count": count,
            "end": "latest",
            "style": "ticks",
            "req_id": 302,
        })

        history = response.get("history", {})
        if not isinstance(history, dict):
            raise DerivAPIError(
                f"Invalid tick history returned for {symbol}."
            )

        prices = history.get("prices", [])
        times = history.get("times", [])

        result = []

        for index, price in enumerate(prices):
            timestamp = (
                times[index] if index < len(times) else None
            )

            result.append({
                "quote": price,
                "price": self._number(price, "tick price"),
                "epoch": timestamp,
                "time": timestamp,
            })

        if not result:
            raise DerivAPIError(
                f"No recent ticks returned for {symbol}."
            )

        return result

    def get_latest_tick(self, symbol: str) -> dict:
        ticks = self.get_recent_ticks(symbol, count=2)
        return ticks[-1]

    def get_contract_types(self, symbol: str) -> list:
        response = self._public_request({
            "contracts_for": str(symbol),
            "req_id": 303,
        })

        data = response.get("contracts_for", {})
        if not isinstance(data, dict):
            return []

        available = data.get("available", [])

        labels = {
            "DIGITOVER": "Over",
            "DIGITUNDER": "Under",
            "DIGITMATCH": "Matches",
            "DIGITDIFF": "Differs",
            "DIGITEVEN": "Even",
            "DIGITODD": "Odd",
        }

        result = []

        for item in available:
            if not isinstance(item, dict):
                continue

            contract_type = str(
                item.get("contract_type", "")
            ).upper()

            if contract_type in labels:
                result.append({
                    **item,
                    "contract_type": contract_type,
                    "label": labels[contract_type],
                })

        return result

    def get_proposal(
        self,
        account_type: str,
        symbol: str,
        contract_type: str,
        amount: float,
        currency: str,
        duration: int = 1,
        duration_unit: str = "t",
        barrier: Optional[Any] = None,
    ) -> dict:
        """Request a digit-contract proposal from Deriv."""

        self._account_type(account_type)

        stake = self._number(amount, "stake")
        duration = int(duration)
        contract_type = str(contract_type).upper().strip()
        duration_unit = str(duration_unit).lower().strip()
        symbol = str(symbol).strip()
        currency = str(currency).strip().upper()

        if not symbol:
            raise DerivAPIError("A market symbol is required.")

        if stake <= 0:
            raise DerivAPIError(
                "Stake must be greater than zero."
            )

        if duration < 1:
            raise DerivAPIError(
                "Duration must be at least one."
            )

        if duration_unit not in ("t", "s", "m", "h", "d"):
            raise DerivAPIError(
                "Unsupported duration unit."
            )

        if contract_type not in self.DIGIT_CONTRACTS:
            raise DerivAPIError(
                f"Unsupported digit contract: {contract_type}"
            )

        payload = {
            "proposal": 1,
            "amount": stake,
            "basis": "stake",
            "contract_type": contract_type,
            "currency": currency,
            "duration": duration,
            "duration_unit": duration_unit,
            # Important: standard proposal requests use "symbol".
            "symbol": symbol,
            "req_id": 401,
        }

        if contract_type in (
            "DIGITOVER",
            "DIGITUNDER",
            "DIGITMATCH",
            "DIGITDIFF",
        ):
            if barrier is None:
                raise DerivAPIError(
                    f"{contract_type} requires a digit barrier."
                )

            try:
                digit = int(barrier)
            except (TypeError, ValueError) as exc:
                raise DerivAPIError(
                    "Digit barrier must be an integer from 0 to 9."
                ) from exc

            if not 0 <= digit <= 9:
                raise DerivAPIError(
                    "Digit barrier must be between 0 and 9."
                )

            if contract_type == "DIGITOVER" and digit > 8:
                raise DerivAPIError(
                    "Over barrier must be between 0 and 8."
                )

            if contract_type == "DIGITUNDER" and digit < 1:
                raise DerivAPIError(
                    "Under barrier must be between 1 and 9."
                )

            payload["barrier"] = str(digit)

        response = self._public_request(payload)
        proposal = response.get("proposal")

        if not isinstance(proposal, dict) or not proposal.get("id"):
            raise DerivAPIError(
                "Deriv returned no usable proposal ID."
            )

        return {
            "proposal_id": str(proposal["id"]),
            "id": str(proposal["id"]),
            "ask_price": self._number(
                proposal.get("ask_price", stake),
                "ask price",
            ),
            "payout": self._number(
                proposal.get("payout", 0),
                "payout",
            ),
            "spot": proposal.get("spot"),
            "spot_time": proposal.get("spot_time"),
            "longcode": proposal.get("longcode", ""),
            "contract_type": contract_type,
            "symbol": symbol,
            "barrier": barrier,
            "raw": proposal,
        }

    def buy_contract(
        self,
        account_type: str,
        proposal_id: str,
        maximum_price: float,
    ) -> dict:
        price = self._number(
            maximum_price,
            "maximum purchase price",
        )

        if price <= 0:
            raise DerivAPIError(
                "Maximum purchase price must be positive."
            )

        if not proposal_id:
            raise DerivAPIError("Missing proposal ID.")

        response = self._account_request(
            account_type,
            {
                "buy": str(proposal_id),
                "price": price,
                "req_id": 402,
            },
        )

        buy = response.get("buy")

        if not isinstance(buy, dict) or not buy.get("contract_id"):
            raise DerivAPIError(
                "Deriv did not confirm the contract purchase."
            )

        return {
            **buy,
            "contract_id": buy["contract_id"],
            "buy_price": buy.get("buy_price", price),
            "payout": buy.get("payout"),
            "longcode": buy.get("longcode", ""),
        }

    def get_open_contract(
        self,
        account_type: str,
        contract_id: Any,
    ) -> dict:
        try:
            contract_id = int(contract_id)
        except (TypeError, ValueError) as exc:
            raise DerivAPIError(
                "Invalid contract ID."
            ) from exc

        response = self._account_request(
            account_type,
            {
                "proposal_open_contract": 1,
                "contract_id": contract_id,
                "req_id": 403,
            },
        )

        contract = response.get("proposal_open_contract")

        if not isinstance(contract, dict):
            raise DerivAPIError(
                "Deriv returned no open-contract details."
            )

        return contract

    def sell_contract(
        self,
        account_type: str,
        contract_id: Any,
        price: float = 0,
    ) -> dict:
        try:
            contract_id = int(contract_id)
        except (TypeError, ValueError) as exc:
            raise DerivAPIError(
                "Invalid contract ID."
            ) from exc

        sell_price = self._number(price, "sell price")

        if sell_price < 0:
            raise DerivAPIError(
                "Sell price cannot be negative."
            )

        response = self._account_request(
            account_type,
            {
                "sell": contract_id,
                "price": sell_price,
                "req_id": 404,
            },
        )

        result = response.get("sell")

        if not isinstance(result, dict):
            raise DerivAPIError(
                "Deriv returned no sell confirmation."
            )

        return result

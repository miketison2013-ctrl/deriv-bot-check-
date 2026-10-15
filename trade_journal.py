
"""
Persistent trade journal for the Deriv bot.

Stores confirmed trades and actual settlement results in SQLite.
This module does not place trades or invent trade outcomes.
"""

import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_DATABASE = "trade_journal.db"


class TradeJournal:
    """Store and retrieve trade records using SQLite."""

    def __init__(self, database_path: str = DEFAULT_DATABASE):
        self.database_path = str(database_path)

        if self.database_path != ":memory:":
            Path(self.database_path).parent.mkdir(
                parents=True, exist_ok=True
            )

        self._create_tables()

    def _connect(self):
        connection = sqlite3.connect(
            self.database_path,
            timeout=10,
        )
        connection.row_factory = sqlite3.Row
        return connection

    def _create_tables(self):
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    contract_id TEXT UNIQUE,
                    transaction_id TEXT,
                    account_type TEXT NOT NULL,
                    account_id TEXT,
                    symbol TEXT NOT NULL,
                    contract_type TEXT NOT NULL,
                    direction TEXT,
                    stake REAL NOT NULL,
                    currency TEXT NOT NULL,
                    entry_spot REAL,
                    entry_time TEXT,
                    exit_spot REAL,
                    exit_time TEXT,
                    buy_price REAL,
                    payout REAL,
                    profit_loss REAL,
                    status TEXT NOT NULL DEFAULT 'OPEN',
                    strategy TEXT,
                    notes TEXT,
                    raw_data TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_trades_status "
                "ON trades(status)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_trades_created_at "
                "ON trades(created_at)"
            )

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _validate_amount(value, field_name, allow_zero=False):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{field_name} must be a number")

        value = float(value)

        if not math.isfinite(value):
            raise ValueError(f"{field_name} must be finite")

        if value < 0 or (value == 0 and not allow_zero):
            raise ValueError(f"{field_name} must be positive")

        return value

    @staticmethod
    def _validate_account_type(account_type):
        if account_type not in ("demo", "real"):
            raise ValueError("account_type must be 'demo' or 'real'")

    def record_open_trade(
        self,
        *,
        contract_id: str,
        account_type: str,
        symbol: str,
        contract_type: str,
        stake: float,
        currency: str,
        account_id: Optional[str] = None,
        transaction_id: Optional[str] = None,
        direction: Optional[str] = None,
        entry_spot: Optional[float] = None,
        entry_time: Optional[str] = None,
        buy_price: Optional[float] = None,
        strategy: Optional[str] = None,
        notes: Optional[str] = None,
        raw_data: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Record a trade only after Deriv confirms the purchase."""
        contract_id = str(contract_id).strip()
        self._validate_account_type(account_type)

        if not contract_id:
            raise ValueError("A real Deriv contract_id is required")

        if not symbol or not contract_type or not currency:
            raise ValueError(
                "symbol, contract_type and currency are required"
            )

        stake = self._validate_amount(stake, "stake")
        if buy_price is None:
            buy_price = stake
        else:
            buy_price = self._validate_amount(buy_price, "buy_price")

        now = self._now()
        raw_json = json.dumps(raw_data, default=str) if raw_data is not None else None

        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO trades (
                    contract_id, transaction_id, account_type, account_id,
                    symbol, contract_type, direction, stake, currency,
                    entry_spot, entry_time, buy_price, status, strategy,
                    notes, raw_data, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        'OPEN', ?, ?, ?, ?, ?)
                """,
                (
                    contract_id, transaction_id, account_type, account_id,
                    symbol, contract_type, direction, stake, currency,
                    entry_spot, entry_time, buy_price, strategy, notes,
                    raw_json, now, now,
                ),
            )
            return int(cursor.lastrowid)

    def settle_trade(
        self,
        contract_id: str,
        *,
        status: str,
        profit_loss: float,
        payout: Optional[float] = None,
        exit_spot: Optional[float] = None,
        exit_time: Optional[str] = None,
        raw_data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Record a confirmed WON, LOST, or SOLD settlement."""
        contract_id = str(contract_id).strip()
        status = status.upper()

        if not contract_id:
            raise ValueError("contract_id is required")
        if status not in ("WON", "LOST", "SOLD"):
            raise ValueError("status must be WON, LOST, or SOLD")

        if isinstance(profit_loss, bool) or not isinstance(profit_loss, (int, float)):
            raise ValueError("profit_loss must be a number")
        profit_loss = float(profit_loss)
        if not math.isfinite(profit_loss):
            raise ValueError("profit_loss must be finite")

        if payout is not None:
            payout = self._validate_amount(payout, "payout", allow_zero=True)

        now = self._now()
        raw_json = json.dumps(raw_data, default=str) if raw_data is not None else None

        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE trades
                SET status = ?,
                    profit_loss = ?,
                    payout = COALESCE(?, payout),
                    exit_spot = ?,
                    exit_time = ?,
                    raw_data = COALESCE(?, raw_data),
                    updated_at = ?
                WHERE contract_id = ? AND status = 'OPEN'
                """,
                (
                    status, profit_loss, payout, exit_spot, exit_time,
                    raw_json, now, contract_id,
                ),
            )
            return cursor.rowcount == 1

    def get_trade(self, contract_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM trades WHERE contract_id = ?",
                (str(contract_id),),
            ).fetchone()
        return dict(row) if row else None

    def list_trades(
        self,
        *,
        limit: int = 100,
        status: Optional[str] = None,
        account_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")

        query = "SELECT * FROM trades WHERE 1=1"
        parameters = []

        if status is not None:
            status = status.upper()
            if status not in ("OPEN", "WON", "LOST", "SOLD"):
                raise ValueError("Invalid trade status")
            query += " AND status = ?"
            parameters.append(status)

        if account_type is not None:
            self._validate_account_type(account_type)
            query += " AND account_type = ?"
            parameters.append(account_type)

        query += " ORDER BY id DESC LIMIT ?"
        parameters.append(limit)

        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()

        return [dict(row) for row in rows]

    def summary(
        self,
        account_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return safe zero-valued counters for an empty history."""
        query = """
            SELECT
                COUNT(*) AS total_trades,
                COALESCE(SUM(CASE WHEN status = 'OPEN' THEN 1 ELSE 0 END), 0)
                    AS open_trades,
                COALESCE(SUM(CASE WHEN status = 'WON' THEN 1 ELSE 0 END), 0)
                    AS wins,
                COALESCE(SUM(CASE WHEN status = 'LOST' THEN 1 ELSE 0 END), 0)
                    AS losses,
                COALESCE(SUM(CASE WHEN status = 'SOLD' THEN 1 ELSE 0 END), 0)
                    AS sold_trades,
                COALESCE(SUM(profit_loss), 0.0) AS total_profit_loss
            FROM trades
        """
        parameters = []

        if account_type is not None:
            self._validate_account_type(account_type)
            query += " WHERE account_type = ?"
            parameters.append(account_type)

        with self._connect() as connection:
            row = connection.execute(query, parameters).fetchone()

        result = dict(row)
        for key in (
            "total_trades", "open_trades", "wins", "losses", "sold_trades"
        ):
            result[key] = int(result.get(key) or 0)

        result["total_profit_loss"] = float(
            result.get("total_profit_loss") or 0.0
        )

        decided_trades = result["wins"] + result["losses"]
        result["win_rate_percent"] = (
            100.0 * result["wins"] / decided_trades
            if decided_trades > 0
            else None
        )
        return result

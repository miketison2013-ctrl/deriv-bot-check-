import tempfile
import unittest
from pathlib import Path

from trade_journal import TradeJournal


class TestTradeJournal(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database = Path(self.temp_dir.name) / "test_trades.db"
        self.journal = TradeJournal(str(database))

    def tearDown(self):
        self.temp_dir.cleanup()

    def add_trade(self, contract_id="12345"):
        return self.journal.record_open_trade(
            contract_id=contract_id,
            account_type="demo",
            account_id="DEMO_ACCOUNT",
            symbol="R_100",
            contract_type="DIGITOVER",
            stake=1.0,
            currency="USD",
            direction="Over 4",
            buy_price=1.0,
            strategy="test_strategy",
        )

    def test_record_open_trade(self):
        trade_id = self.add_trade()

        trade = self.journal.get_trade("12345")

        self.assertEqual(trade["id"], trade_id)
        self.assertEqual(trade["status"], "OPEN")
        self.assertEqual(trade["stake"], 1.0)
        self.assertEqual(trade["symbol"], "R_100")

    def test_settle_winning_trade(self):
        self.add_trade()

        updated = self.journal.settle_trade(
            "12345",
            status="WON",
            profit_loss=0.80,
            payout=1.80,
        )

        self.assertTrue(updated)

        trade = self.journal.get_trade("12345")

        self.assertEqual(trade["status"], "WON")
        self.assertAlmostEqual(trade["profit_loss"], 0.80)
        self.assertAlmostEqual(trade["payout"], 1.80)

    def test_settle_losing_trade(self):
        self.add_trade()

        updated = self.journal.settle_trade(
            "12345",
            status="LOST",
            profit_loss=-1.0,
            payout=0.0,
        )

        self.assertTrue(updated)

        trade = self.journal.get_trade("12345")

        self.assertEqual(trade["status"], "LOST")
        self.assertAlmostEqual(trade["profit_loss"], -1.0)

    def test_cannot_settle_same_trade_twice(self):
        self.add_trade()

        first = self.journal.settle_trade(
            "12345",
            status="WON",
            profit_loss=0.80,
        )

        second = self.journal.settle_trade(
            "12345",
            status="LOST",
            profit_loss=-1.0,
        )

        self.assertTrue(first)
        self.assertFalse(second)

        trade = self.journal.get_trade("12345")
        self.assertEqual(trade["status"], "WON")

    def test_summary(self):
        self.add_trade("100")
        self.add_trade("101")

        self.journal.settle_trade(
            "100",
            status="WON",
            profit_loss=0.80,
        )

        self.journal.settle_trade(
            "101",
            status="LOST",
            profit_loss=-1.0,
        )

        result = self.journal.summary(account_type="demo")

        self.assertEqual(result["total_trades"], 2)
        self.assertEqual(result["wins"], 1)
        self.assertEqual(result["losses"], 1)
        self.assertAlmostEqual(
            result["total_profit_loss"], -0.20
        )
        self.assertAlmostEqual(result["win_rate_percent"], 50.0)

    def test_list_open_trades(self):
        self.add_trade("200")
        self.add_trade("201")

        trades = self.journal.list_trades(status="OPEN")

        self.assertEqual(len(trades), 2)

    def test_duplicate_contract_id_is_rejected(self):
        self.add_trade("300")

        with self.assertRaises(Exception):
            self.add_trade("300")

    def test_invalid_account_type_is_rejected(self):
        with self.assertRaises(ValueError):
            self.journal.record_open_trade(
                contract_id="400",
                account_type="unknown",
                symbol="R_100",
                contract_type="DIGITOVER",
                stake=1.0,
                currency="USD",
            )


if __name__ == "__main__":
    unittest.main()
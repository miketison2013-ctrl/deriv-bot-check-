
import unittest
from unittest.mock import Mock

from trading_engine import TradingEngine


class TestTradingEngine(unittest.TestCase):

    def setUp(self):
        self.client = Mock()
        self.journal = Mock()
        self.engine = TradingEngine(self.client, self.journal)

    def test_engine_starts_stopped(self):
        self.assertFalse(self.engine.running)

    def test_engine_has_no_error_initially(self):
        self.assertEqual(self.engine.last_error, "")

    def test_engine_starts_with_wait_signal(self):
        self.assertEqual(self.engine.last_signal, "WAIT")

    def test_digit_contracts_are_supported(self):
        expected = {
            "DIGITOVER",
            "DIGITUNDER",
            "DIGITMATCH",
            "DIGITDIFF",
            "DIGITEVEN",
            "DIGITODD",
        }
        self.assertEqual(
            TradingEngine.__module__ and
            __import__("trading_engine").DIGIT_CONTRACTS,
            expected,
        )

    def test_invalid_number_uses_default(self):
        self.assertEqual(
            self.engine._number("not-a-number", default=7),
            7,
        )

    def test_non_finite_number_uses_default(self):
        self.assertEqual(
            self.engine._number(float("nan"), default=3),
            3,
        )

    def test_valid_number_is_converted(self):
        self.assertEqual(
            self.engine._number("12.5"),
            12.5,
        )

    def test_engine_has_empty_scan_at_start(self):
        self.assertEqual(self.engine.last_scan, [])
        self.assertEqual(self.engine.last_candidates, [])

    def test_engine_has_no_last_trade_at_start(self):
        self.assertIsNone(self.engine.last_trade)


if __name__ == "__main__":
    unittest.main()

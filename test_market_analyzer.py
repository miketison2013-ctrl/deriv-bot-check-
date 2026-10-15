import unittest

from market_analyzer import (
    digit_statistics,
    momentum_statistics,
    price_statistics,
    analyse_market,
    rank_markets,
)


class TestMarketAnalyzer(unittest.TestCase):

    def test_digit_counts(self):
        result = digit_statistics(
            ["100.12", "100.13", "100.12", "100.19"]
        )
        self.assertEqual(result["sample_size"], 4)
        self.assertEqual(result["counts"][2]["count"], 2)
        self.assertEqual(result["counts"][2]["percentage"], 50.0)

    def test_empty_digit_data(self):
        result = digit_statistics([])
        self.assertEqual(result["sample_size"], 0)
        self.assertIsNone(result["most_frequent"])

    def test_price_change(self):
        result = price_statistics(
            ["100.00", "100.50", "100.25"]
        )
        self.assertAlmostEqual(result["change"], 0.25)
        self.assertEqual(result["direction"], "UP")

    def test_insufficient_price_data(self):
        result = price_statistics(["100.00"])
        self.assertEqual(
            result["direction"], "INSUFFICIENT DATA"
        )

    def test_momentum_needs_enough_data(self):
        result = momentum_statistics(
            ["1.0", "1.1"], long_window=5
        )
        self.assertEqual(
            result["signal"], "INSUFFICIENT DATA"
        )

    def test_rising_momentum(self):
        prices = [str(100 + i) for i in range(30)]
        result = momentum_statistics(
            prices, short_window=5, long_window=10
        )
        self.assertEqual(
            result["signal"], "UPWARD MOMENTUM"
        )

    def test_combined_analysis(self):
        result = analyse_market(
            ["10.01", "10.02", "10.03"],
            symbol="TEST",
            window=3,
        )
        self.assertEqual(result["symbol"], "TEST")
        self.assertEqual(result["analysis_window"], 3)

    def test_market_ranking(self):
        results = rank_markets([
            {
                "symbol": "SLOW",
                "price": {
                    "mean_absolute_tick_change": 0.1
                },
            },
            {
                "symbol": "FAST",
                "price": {
                    "mean_absolute_tick_change": 2.0
                },
            },
        ])
        self.assertEqual(results[0]["symbol"], "FAST")


if __name__ == "__main__":
    unittest.main()
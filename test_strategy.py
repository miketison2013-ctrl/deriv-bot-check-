import unittest

from strategy import moving_average, crossover_signal


class StrategyTests(unittest.TestCase):
    def test_moving_average(self):
        self.assertEqual(
            moving_average([10, 20, 30, 40], 2),
            35,
        )

    def test_longer_moving_average(self):
        self.assertEqual(
            moving_average([10, 20, 30, 40], 3),
            30,
        )

    def test_insufficient_prices(self):
        self.assertIsNone(
            moving_average([10, 20], 3)
        )

    def test_invalid_moving_average_period(self):
        with self.assertRaises(ValueError):
            moving_average([1, 2, 3], 0)

    def test_crossover_waits_for_enough_prices(self):
        self.assertEqual(
            crossover_signal([1, 2, 3], 2, 4),
            "WAIT",
        )

    def test_fast_period_must_be_smaller(self):
        with self.assertRaises(ValueError):
            crossover_signal([1, 2, 3], 5, 3)


if __name__ == "__main__":
    unittest.main()
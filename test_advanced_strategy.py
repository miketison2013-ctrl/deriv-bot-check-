import unittest

from advanced_strategy import (
    DIGIT_CONTRACTS,
    beta_binomial_summary,
    digit_event,
    directional_features,
    expected_value_per_stake,
    last_digit_from_quote,
    rank_opportunity,
    rolling_digit_analysis,
    theoretical_probability,
)


class TestAdvancedStrategy(unittest.TestCase):

    def test_all_digit_contracts_exist(self):
        self.assertIn("Over 0", DIGIT_CONTRACTS)
        self.assertIn("Under 9", DIGIT_CONTRACTS)
        self.assertIn("Even", DIGIT_CONTRACTS)
        self.assertIn("Odd", DIGIT_CONTRACTS)
        self.assertIn("Matches 5", DIGIT_CONTRACTS)
        self.assertIn("Differs 5", DIGIT_CONTRACTS)

    def test_digit_contract_rules(self):
        self.assertTrue(digit_event("Over 4", 7))
        self.assertFalse(digit_event("Over 4", 4))

        self.assertTrue(digit_event("Under 5", 3))
        self.assertFalse(digit_event("Under 5", 5))

        self.assertTrue(digit_event("Even", 8))
        self.assertFalse(digit_event("Even", 7))

        self.assertTrue(digit_event("Odd", 7))
        self.assertFalse(digit_event("Odd", 8))

        self.assertTrue(digit_event("Matches 3", 3))
        self.assertFalse(digit_event("Matches 3", 4))

        self.assertTrue(digit_event("Differs 3", 4))
        self.assertFalse(digit_event("Differs 3", 3))

    def test_theoretical_probabilities(self):
        self.assertAlmostEqual(
            theoretical_probability("Over 4"), 0.5
        )
        self.assertAlmostEqual(
            theoretical_probability("Under 5"), 0.5
        )
        self.assertAlmostEqual(
            theoretical_probability("Even"), 0.5
        )
        self.assertAlmostEqual(
            theoretical_probability("Odd"), 0.5
        )
        self.assertAlmostEqual(
            theoretical_probability("Matches 3"), 0.1
        )
        self.assertAlmostEqual(
            theoretical_probability("Differs 3"), 0.9
        )

    def test_last_digit_extraction(self):
        self.assertEqual(
            last_digit_from_quote("123.450", 3), 0
        )
        self.assertEqual(
            last_digit_from_quote("123.457", 3), 7
        )
        self.assertEqual(
            last_digit_from_quote("123.457"), 7
        )
        self.assertIsNone(
            last_digit_from_quote("invalid", 3)
        )

    def test_probability_estimation(self):
        result = beta_binomial_summary(8, 2)

        self.assertAlmostEqual(
            result["estimated_probability"], 0.75
        )
        self.assertEqual(result["sample_size"], 10.0)
        self.assertLessEqual(result["lower_95"], result["upper_95"])

    def test_expected_value(self):
        self.assertAlmostEqual(
            expected_value_per_stake(0.5, 1.8), -0.1
        )
        self.assertAlmostEqual(
            expected_value_per_stake(0.6, 1.8), 0.08
        )

    def test_rolling_digit_analysis(self):
        result = rolling_digit_analysis(
            [1, 2, 3, 4, 5, 6, 7, 8, 9, 0],
            "Even",
        )

        self.assertEqual(result["sample_size"], 10)
        self.assertEqual(result["wins"], 5)
        self.assertAlmostEqual(
            result["observed_probability"], 0.5
        )

    def test_empty_digit_analysis(self):
        result = rolling_digit_analysis([], "Even")

        self.assertEqual(result["sample_size"], 0)
        self.assertIsNone(result["observed_probability"])

    def test_directional_signal(self):
        result = directional_features(
            list(range(1, 26)),
            short_window=5,
            long_window=20,
        )

        self.assertEqual(result["signal"], "UP")

    def test_insufficient_prices(self):
        result = directional_features(
            [1, 2, 3],
            short_window=2,
            long_window=5,
        )

        self.assertEqual(result["signal"], "WAIT")

    def test_opportunity_is_not_automatically_authorised(self):
        result = rank_opportunity(
            probability=0.7,
            payout_multiple=1.8,
            sample_size=200,
        )

        self.assertTrue(
            result["candidate_for_further_testing"]
        )
        self.assertFalse(result["trade_authorised"])

    def test_invalid_digit_contract_is_rejected(self):
        with self.assertRaises(ValueError):
            digit_event("Unknown", 5)

    def test_invalid_digit_is_rejected(self):
        with self.assertRaises(ValueError):
            digit_event("Even", 10)


if __name__ == "__main__":
    unittest.main()
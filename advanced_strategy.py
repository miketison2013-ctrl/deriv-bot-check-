"""
Advanced statistical tools for the Deriv trading bot.

Provides digit-contract analysis, probability estimates,
expected-value calculations, and basic directional indicators.

This module does not place trades or guarantee profits.
"""

from math import isfinite, sqrt
from statistics import mean
from typing import Any, Dict, List, Optional


DIGIT_CONTRACTS = {
    "Over 0": ("DIGITOVER", 0),
    "Over 1": ("DIGITOVER", 1),
    "Over 2": ("DIGITOVER", 2),
    "Over 3": ("DIGITOVER", 3),
    "Over 4": ("DIGITOVER", 4),
    "Under 5": ("DIGITUNDER", 5),
    "Under 6": ("DIGITUNDER", 6),
    "Under 7": ("DIGITUNDER", 7),
    "Under 8": ("DIGITUNDER", 8),
    "Under 9": ("DIGITUNDER", 9),
    "Even": ("DIGITEVEN", None),
    "Odd": ("DIGITODD", None),
    **{
        f"Matches {digit}": ("DIGITMATCH", digit)
        for digit in range(10)
    },
    **{
        f"Differs {digit}": ("DIGITDIFF", digit)
        for digit in range(10)
    },
}


def last_digit_from_quote(
    quote: Any,
    pip_size: Optional[int] = None,
) -> Optional[int]:
    """
    Extract the final displayed digit from a quote.

    Supply pip_size from the market metadata whenever possible.
    For example, 123.450 with pip_size=3 gives digit 0.
    """
    try:
        value = float(quote)

        if not isfinite(value):
            return None

        if pip_size is not None:
            precision = int(pip_size)

            if precision < 0 or precision > 10:
                return None

            formatted = f"{value:.{precision}f}"
            return int(formatted[-1])

        text = str(quote).strip()

        # Scientific notation does not reliably preserve the
        # original displayed precision.
        if "e" in text.lower():
            return None

        if not text:
            return None

        if "." in text:
            decimals = text.partition(".")[2]

            if not decimals.isdigit():
                return None

            return int(decimals[-1]) if decimals else None

        if text.isdigit():
            return int(text[-1])

        return None

    except (ValueError, TypeError, OverflowError):
        return None


def digit_event(label: str, digit: int) -> bool:
    """Check whether a digit satisfies a named digit contract."""
    if not isinstance(digit, int) or digit not in range(10):
        raise ValueError("digit must be an integer from 0 to 9")

    if label not in DIGIT_CONTRACTS:
        raise ValueError(f"Unsupported digit contract: {label}")

    contract_type, barrier = DIGIT_CONTRACTS[label]

    if contract_type == "DIGITOVER":
        return digit > barrier

    if contract_type == "DIGITUNDER":
        return digit < barrier

    if contract_type == "DIGITEVEN":
        return digit % 2 == 0

    if contract_type == "DIGITODD":
        return digit % 2 == 1

    if contract_type == "DIGITMATCH":
        return digit == barrier

    if contract_type == "DIGITDIFF":
        return digit != barrier

    return False


def theoretical_probability(label: str) -> float:
    """
    Return the equal-digit baseline probability.

    This is a mathematical baseline, not a prediction that
    the next outcome will have that probability.
    """
    if label not in DIGIT_CONTRACTS:
        raise ValueError(f"Unsupported digit contract: {label}")

    contract_type, barrier = DIGIT_CONTRACTS[label]

    if contract_type == "DIGITOVER":
        return (9 - barrier) / 10

    if contract_type == "DIGITUNDER":
        return barrier / 10

    if contract_type in ("DIGITEVEN", "DIGITODD"):
        return 0.5

    if contract_type == "DIGITMATCH":
        return 0.1

    if contract_type == "DIGITDIFF":
        return 0.9

    raise ValueError(f"Unsupported contract type: {contract_type}")


def beta_binomial_summary(
    wins: int,
    losses: int,
    prior_alpha: float = 1.0,
    prior_beta: float = 1.0,
) -> Dict[str, float]:
    """Estimate binary win probability with a Beta prior."""
    if (
        not isinstance(wins, int)
        or not isinstance(losses, int)
        or wins < 0
        or losses < 0
    ):
        raise ValueError("wins and losses must be non-negative integers")

    if (
        not isfinite(prior_alpha)
        or not isfinite(prior_beta)
        or prior_alpha <= 0
        or prior_beta <= 0
    ):
        raise ValueError("Prior parameters must be finite and positive")

    alpha = prior_alpha + wins
    beta = prior_beta + losses
    total = alpha + beta

    probability = alpha / total
    variance = (alpha * beta) / (total ** 2 * (total + 1))
    margin = 1.96 * sqrt(variance)

    return {
        "wins": float(wins),
        "losses": float(losses),
        "sample_size": float(wins + losses),
        "estimated_probability": probability,
        "lower_95": max(0.0, probability - margin),
        "upper_95": min(1.0, probability + margin),
    }


def expected_value_per_stake(
    probability: float,
    payout_multiple: float,
) -> float:
    """
    Estimate net expected return per unit staked.

    payout_multiple means total returned per unit staked
    on a win, including the stake itself.
    """
    if not isfinite(probability) or not 0 <= probability <= 1:
        raise ValueError("probability must be between 0 and 1")

    if not isfinite(payout_multiple) or payout_multiple < 0:
        raise ValueError("payout_multiple must be finite and non-negative")

    return probability * payout_multiple - 1.0


def rolling_digit_analysis(
    digits: List[int],
    contract_label: str,
) -> Dict[str, Any]:
    """Summarise observed digit-contract outcomes."""
    if contract_label not in DIGIT_CONTRACTS:
        raise ValueError(f"Unsupported digit contract: {contract_label}")

    clean_digits = []

    for digit in digits:
        if isinstance(digit, bool) or not isinstance(digit, int):
            continue

        if digit in range(10):
            clean_digits.append(digit)

    baseline = theoretical_probability(contract_label)

    if not clean_digits:
        return {
            "sample_size": 0,
            "wins": 0,
            "observed_probability": None,
            "baseline_probability": baseline,
            "estimated_probability": None,
            "warning": "No valid digit observations available.",
        }

    wins = sum(
        digit_event(contract_label, digit)
        for digit in clean_digits
    )

    sample_size = len(clean_digits)
    observed = wins / sample_size

    posterior = beta_binomial_summary(
        wins,
        sample_size - wins,
    )

    return {
        "sample_size": sample_size,
        "wins": wins,
        "observed_probability": observed,
        "baseline_probability": baseline,
        "estimated_probability": posterior["estimated_probability"],
        "lower_95": posterior["lower_95"],
        "upper_95": posterior["upper_95"],
        "warning": (
            "Past frequencies do not guarantee future outcomes. "
            "Test on unseen data and verify actual contract payouts."
        ),
    }


def directional_features(
    prices: List[float],
    short_window: int = 5,
    long_window: int = 20,
) -> Dict[str, Any]:
    """Calculate moving averages and a simple momentum indicator."""
    if (
        not isinstance(short_window, int)
        or not isinstance(long_window, int)
        or short_window < 1
        or long_window < 2
        or short_window >= long_window
    ):
        raise ValueError(
            "Use positive windows with short_window < long_window"
        )

    values = [float(price) for price in prices]

    if not all(isfinite(value) for value in values):
        raise ValueError("Prices must be finite numbers")

    if len(values) < long_window:
        return {
            "sample_size": len(values),
            "short_average": None,
            "long_average": None,
            "momentum": None,
            "signal": "WAIT",
            "warning": "Not enough prices for the selected windows.",
        }

    short_average = mean(values[-short_window:])
    long_average = mean(values[-long_window:])
    momentum = values[-1] - values[-short_window]

    if short_average > long_average and momentum > 0:
        signal = "UP"
    elif short_average < long_average and momentum < 0:
        signal = "DOWN"
    else:
        signal = "WAIT"

    return {
        "sample_size": len(values),
        "short_average": short_average,
        "long_average": long_average,
        "momentum": momentum,
        "signal": signal,
        "warning": (
            "This indicator is not a validated prediction and "
            "must not be used alone to authorise a trade."
        ),
    }


def rank_opportunity(
    probability: float,
    payout_multiple: float,
    sample_size: int,
    minimum_sample: int = 100,
) -> Dict[str, Any]:
    """Screen a candidate; never authorise a trade automatically."""
    if not isinstance(sample_size, int) or sample_size < 0:
        raise ValueError("sample_size must be a non-negative integer")

    if not isinstance(minimum_sample, int) or minimum_sample < 1:
        raise ValueError("minimum_sample must be a positive integer")

    ev = expected_value_per_stake(
        probability,
        payout_multiple,
    )

    sample_ok = sample_size >= minimum_sample

    return {
        "estimated_probability": probability,
        "payout_multiple": payout_multiple,
        "expected_value_per_stake": ev,
        "sample_size": sample_size,
        "minimum_sample": minimum_sample,
        "sample_requirement_met": sample_ok,
        "candidate_for_further_testing": sample_ok and ev > 0,
        "trade_authorised": False,
        "warning": (
            "Further out-of-sample testing, payout verification, "
            "and risk checks are required before any trade."
        ),
    }
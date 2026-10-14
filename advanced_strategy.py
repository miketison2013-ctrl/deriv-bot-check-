"""
Advanced statistical tools for the Deriv trading bot.

This module analyses digit contracts and directional price data.
It does not place trades or guarantee profitable predictions.
"""

from collections import Counter
from math import sqrt
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
    "Matches 0": ("DIGITMATCH", 0),
    "Matches 1": ("DIGITMATCH", 1),
    "Matches 2": ("DIGITMATCH", 2),
    "Matches 3": ("DIGITMATCH", 3),
    "Matches 4": ("DIGITMATCH", 4),
    "Matches 5": ("DIGITMATCH", 5),
    "Matches 6": ("DIGITMATCH", 6),
    "Matches 7": ("DIGITMATCH", 7),
    "Matches 8": ("DIGITMATCH", 8),
    "Matches 9": ("DIGITMATCH", 9),
    "Differs 0": ("DIGITDIFF", 0),
    "Differs 1": ("DIGITDIFF", 1),
    "Differs 2": ("DIGITDIFF", 2),
    "Differs 3": ("DIGITDIFF", 3),
    "Differs 4": ("DIGITDIFF", 4),
    "Differs 5": ("DIGITDIFF", 5),
    "Differs 6": ("DIGITDIFF", 6),
    "Differs 7": ("DIGITDIFF", 7),
    "Differs 8": ("DIGITDIFF", 8),
    "Differs 9": ("DIGITDIFF", 9),
}


def last_digit_from_quote(
    quote: Any,
    pip_size: Optional[int] = None,
) -> Optional[int]:
    """Extract the final displayed digit from a market quote."""
    try:
        if pip_size is not None:
            precision = int(pip_size)
            if precision < 0 or precision > 10:
                return None

            formatted = f"{float(quote):.{precision}f}"
            decimals = formatted.partition(".")[2]

            if precision == 0:
                return int(formatted[-1])

            return int(decimals[-1])

        text = str(quote).strip()

        if "e" in text.lower():
            text = format(float(text), ".10f").rstrip("0").rstrip(".")

        text = text.rstrip("0") if "." in text else text

        if "." not in text or not text:
            return int(text[-1]) if text else None

        decimals = text.partition(".")[2]
        return int(decimals[-1]) if decimals else None

    except (ValueError, TypeError, OverflowError):
        return None


def digit_event(label: str, digit: int) -> bool:
    """Return whether a digit satisfies a named digit-contract condition."""
    if digit not in range(10):
        raise ValueError("digit must be between 0 and 9")

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
    Calculate the simple equal-digit baseline probability.

    Actual outcomes and payouts must be verified for the selected market.
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
    """
    Estimate a binary strategy's win probability using a Beta prior.

    The interval is an approximate 95% interval, not a guarantee.
    """
    if wins < 0 or losses < 0:
        raise ValueError("wins and losses cannot be negative")

    if prior_alpha <= 0 or prior_beta <= 0:
        raise ValueError("prior parameters must be positive")

    alpha = prior_alpha + wins
    beta = prior_beta + losses
    total = alpha + beta

    probability = alpha / total
    variance = (alpha * beta) / (
        (total ** 2) * (total + 1)
    )
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

    payout_multiple means total amount returned on a win,
    including the original stake.

    Example: 0.80 means a winning trade returns 0.80
    units per 1 unit staked in total.
    """
    if not 0 <= probability <= 1:
        raise ValueError("probability must be between 0 and 1")

    if payout_multiple < 0:
        raise ValueError("payout_multiple cannot be negative")

    return (probability * payout_multiple) - 1.0


def rolling_digit_analysis(
    digits: List[int],
    contract_label: str,
) -> Dict[str, Any]:
    """Summarise recent digits against a simple theoretical baseline."""
    if contract_label not in DIGIT_CONTRACTS:
        raise ValueError(f"Unsupported digit contract: {contract_label}")

    clean_digits = [int(d) for d in digits if int(d) in range(10)]

    if not clean_digits:
        return {
            "sample_size": 0,
            "wins": 0,
            "observed_probability": None,
            "baseline_probability": theoretical_probability(
                contract_label
            ),
            "estimated_probability": None,
            "warning": "Not enough valid digit observations.",
        }

    wins = sum(
        1 for digit in clean_digits
        if digit_event(contract_label, digit)
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
        "baseline_probability": theoretical_probability(
            contract_label
        ),
        "estimated_probability": posterior[
            "estimated_probability"
        ],
        "lower_95": posterior["lower_95"],
        "upper_95": posterior["upper_95"],
        "warning": (
            "Past digit frequencies do not guarantee future outcomes. "
            "Validate on unseen data and use actual contract payouts."
        ),
    }


def directional_features(
    prices: List[float],
    short_window: int = 5,
    long_window: int = 20,
) -> Dict[str, Any]:
    """Calculate basic moving-average and momentum features."""
    if short_window < 1 or long_window < 2:
        raise ValueError("Moving-average windows must be positive")

    if short_window >= long_window:
        raise ValueError("short_window must be smaller than long_window")

    values = [float(price) for price in prices]

    if len(values) < long_window:
        return {
            "sample_size": len(values),
            "short_average": None,
            "long_average": None,
            "momentum": None,
            "signal": "WAIT",
            "warning": "Not enough prices for the requested windows.",
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
            "This is a basic indicator, not a validated prediction "
            "or a standalone reason to place a trade."
        ),
    }


def rank_opportunity(
    probability: float,
    payout_multiple: float,
    sample_size: int,
    minimum_sample: int = 100,
) -> Dict[str, Any]:
    """
    Screen a candidate using estimated probability and actual payout.

    A positive estimate alone is insufficient to authorise a trade.
    """
    if not 0 <= probability <= 1:
        raise ValueError("probability must be between 0 and 1")

    if payout_multiple < 0:
        raise ValueError("payout_multiple cannot be negative")

    if sample_size < 0 or minimum_sample < 1:
        raise ValueError("Invalid sample-size setting")

    ev = expected_value_per_stake(
        probability,
        payout_multiple,
    )

    validated_sample = sample_size >= minimum_sample
    candidate = validated_sample and ev > 0

    return {
        "estimated_probability": probability,
        "payout_multiple": payout_multiple,
        "expected_value_per_stake": ev,
        "sample_size": sample_size,
        "minimum_sample": minimum_sample,
        "sample_requirement_met": validated_sample,
        "candidate_for_further_testing": candidate,
        "trade_authorised": False,
        "warning": (
            "This screening result does not authorise a trade. "
            "Out-of-sample testing, payout verification, and risk "
            "checks are still required."
        ),
    }
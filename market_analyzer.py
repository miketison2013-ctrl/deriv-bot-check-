"""
Market analysis module for the Deriv adaptive trading bot.

Calculates descriptive statistics from actual tick prices.
It does not place trades or guarantee future outcomes.
"""

from collections import Counter
from math import isfinite, sqrt
from statistics import mean


DIGITS = list(range(10))


def _valid_prices(prices):
    """Return finite numeric prices only."""
    result = []

    for price in prices or []:
        try:
            value = float(price)
        except (TypeError, ValueError):
            continue

        if isfinite(value) and value > 0:
            result.append(value)

    return result


def _last_digit(price):
    """
    Extract the final displayed decimal digit.

    Note: accurate digit analysis depends on receiving prices
    with their original Deriv decimal precision.
    """
    text = str(price).strip()

    if "e" in text.lower():
        text = format(float(text), "f")

    if "." not in text:
        return int(text[-1]) if text else None

    decimals = text.split(".", 1)[1]
    decimals = "".join(
        character for character in decimals
        if character.isdigit()
    )

    if not decimals:
        return None

    return int(decimals[-1])


def digit_statistics(prices, window=100):
    """Calculate rolling last-digit frequencies and percentages."""
    prices = _valid_prices(prices)
    prices = prices[-max(1, int(window)):]

    digits = [
        _last_digit(price)
        for price in prices
    ]

    digits = [
        digit for digit in digits
        if digit is not None and 0 <= digit <= 9
    ]

    counts = Counter(digits)
    sample_size = len(digits)

    rows = []

    for digit in DIGITS:
        count = counts.get(digit, 0)
        percentage = (
            count / sample_size * 100
            if sample_size
            else 0.0
        )

        rows.append({
            "digit": digit,
            "count": count,
            "percentage": round(percentage, 2),
            "sample_size": sample_size,
        })

    ranked = sorted(
        rows,
        key=lambda row: (
            row["percentage"],
            row["count"],
        ),
        reverse=True,
    )

    return {
        "sample_size": sample_size,
        "counts": rows,
        "ranked_digits": ranked,
        "most_frequent": (
            ranked[0]["digit"] if sample_size else None
        ),
        "least_frequent": (
            ranked[-1]["digit"] if sample_size else None
        ),
    }


def price_statistics(prices):
    """Calculate descriptive price movement statistics."""
    prices = _valid_prices(prices)

    if len(prices) < 2:
        return {
            "sample_size": len(prices),
            "first_price": prices[0] if prices else None,
            "latest_price": prices[-1] if prices else None,
            "change": None,
            "change_percent": None,
            "direction": "INSUFFICIENT DATA",
            "mean_absolute_tick_change": None,
            "tick_change_stddev": None,
        }

    changes = [
        prices[index] - prices[index - 1]
        for index in range(1, len(prices))
    ]

    absolute_changes = [abs(change) for change in changes]

    average_absolute_change = mean(absolute_changes)

    average_change = mean(changes)

    variance = mean([
        (change - average_change) ** 2
        for change in changes
    ])

    first_price = prices[0]
    latest_price = prices[-1]
    total_change = latest_price - first_price

    change_percent = (
        total_change / first_price * 100
        if first_price
        else None
    )

    if total_change > 0:
        direction = "UP"
    elif total_change < 0:
        direction = "DOWN"
    else:
        direction = "FLAT"

    return {
        "sample_size": len(prices),
        "first_price": first_price,
        "latest_price": latest_price,
        "change": total_change,
        "change_percent": change_percent,
        "direction": direction,
        "mean_absolute_tick_change": average_absolute_change,
        "tick_change_stddev": sqrt(variance),
    }


def momentum_statistics(prices, short_window=10, long_window=30):
    """Compare short and long average prices."""
    prices = _valid_prices(prices)

    short_window = max(2, int(short_window))
    long_window = max(short_window, int(long_window))

    if len(prices) < long_window:
        return {
            "signal": "INSUFFICIENT DATA",
            "short_average": None,
            "long_average": None,
            "sample_size": len(prices),
        }

    short_average = mean(prices[-short_window:])
    long_average = mean(prices[-long_window:])

    if short_average > long_average:
        signal = "UPWARD MOMENTUM"
    elif short_average < long_average:
        signal = "DOWNWARD MOMENTUM"
    else:
        signal = "NEUTRAL"

    return {
        "signal": signal,
        "short_average": short_average,
        "long_average": long_average,
        "sample_size": len(prices),
    }


def analyse_market(prices, symbol="UNKNOWN", window=100):
    """Combine digit, price movement and momentum statistics."""
    prices = _valid_prices(prices)

    return {
        "symbol": str(symbol),
        "price": price_statistics(prices),
        "digits": digit_statistics(prices, window=window),
        "momentum": momentum_statistics(prices),
        "analysis_window": min(len(prices), max(1, int(window))),
    }


def rank_markets(market_analyses):
    """
    Rank markets by observed absolute price movement.

    This is a descriptive volatility ranking, not a trade signal.
    Markets with insufficient data are placed last.
    """
    analyses = list(market_analyses or [])

    def ranking_key(item):
        price_data = item.get("price", {})
        movement = price_data.get(
            "mean_absolute_tick_change"
        )

        if movement is None:
            return (0, 0.0)

        try:
            movement = float(movement)
        except (TypeError, ValueError):
            return (0, 0.0)

        if not isfinite(movement):
            return (0, 0.0)

        return (1, movement)

    return sorted(
        analyses,
        key=ranking_key,
        reverse=True,
    )


def rank_digits_across_markets(market_analyses):
    """Summarize each digit's frequency across analysed markets."""
    totals = {
        digit: {
            "digit": digit,
            "total_count": 0,
            "total_samples": 0,
            "markets_observed": 0,
        }
        for digit in DIGITS
    }

    for analysis in market_analyses or []:
        digit_data = analysis.get("digits", {})
        rows = digit_data.get("counts", [])

        for row in rows:
            digit = row.get("digit")

            if digit not in totals:
                continue

            count = int(row.get("count", 0))
            sample_size = int(row.get("sample_size", 0))

            totals[digit]["total_count"] += count
            totals[digit]["total_samples"] += sample_size

            if sample_size > 0:
                totals[digit]["markets_observed"] += 1

    results = []

    for digit, item in totals.items():
        samples = item["total_samples"]

        item["percentage"] = round(
            item["total_count"] / samples * 100,
            2,
        ) if samples else 0.0

        results.append(item)

    return sorted(
        results,
        key=lambda item: (
            item["percentage"],
            item["total_count"],
        ),
        reverse=True,
    )
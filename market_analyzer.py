
"""Statistical analysis for Deriv tick markets."""

from collections import Counter
from decimal import Decimal, InvalidOperation
from math import isfinite, sqrt
from statistics import mean

DIGITS = list(range(10))


def _price_texts(prices):
    """Keep valid original price text for last-digit extraction."""
    result = []
    for price in prices or []:
        text = str(price).strip()
        try:
            value = Decimal(text)
        except (InvalidOperation, ValueError):
            continue
        if value.is_finite() and value > 0:
            result.append(text)
    return result


def _numeric_prices(prices):
    """Convert valid prices to finite floats for movement analysis."""
    values = []
    for text in _price_texts(prices):
        try:
            value = float(Decimal(text))
        except (ValueError, OverflowError):
            continue
        if isfinite(value) and value > 0:
            values.append(value)
    return values


def _last_digit(price):
    """Extract the final displayed decimal digit."""
    text = str(price).strip()
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError):
        return None

    if not value.is_finite() or value <= 0:
        return None

    if "e" in text.lower():
        text = format(value, "f")

    if "." not in text:
        digits = "".join(char for char in text if char.isdigit())
        return int(digits[-1]) if digits else None

    decimals = "".join(
        char for char in text.split(".", 1)[1]
        if char.isdigit()
    )
    return int(decimals[-1]) if decimals else None


def digit_statistics(prices, window=100):
    """Return counts, percentages and rankings for digits 0–9."""
    window = max(1, int(window))
    texts = _price_texts(prices)[-window:]
    digits = [
        digit for digit in (_last_digit(price) for price in texts)
        if digit is not None and 0 <= digit <= 9
    ]

    counts = Counter(digits)
    sample_size = len(digits)
    rows = []

    for digit in DIGITS:
        count = counts.get(digit, 0)
        rows.append({
            "digit": digit,
            "count": count,
            "percentage": round(count / sample_size * 100, 2)
            if sample_size else 0.0,
            "sample_size": sample_size,
        })

    ranked = sorted(
        rows,
        key=lambda row: (row["percentage"], row["count"], -row["digit"]),
        reverse=True,
    )

    expected_percentage = 10.0
    for row in rows:
        row["difference_from_uniform"] = round(
            row["percentage"] - expected_percentage, 2
        )

    return {
        "sample_size": sample_size,
        "counts": rows,
        "ranked_digits": ranked,
        "most_frequent": ranked[0]["digit"] if sample_size else None,
        "least_frequent": ranked[-1]["digit"] if sample_size else None,
    }


def price_statistics(prices):
    """Calculate descriptive price movement statistics."""
    values = _numeric_prices(prices)

    if len(values) < 2:
        return {
            "sample_size": len(values),
            "first_price": values[0] if values else None,
            "latest_price": values[-1] if values else None,
            "change": None,
            "change_percent": None,
            "direction": "INSUFFICIENT DATA",
            "mean_absolute_tick_change": None,
            "tick_change_stddev": None,
        }

    changes = [
        values[index] - values[index - 1]
        for index in range(1, len(values))
    ]
    average_change = mean(changes)
    variance = mean((change - average_change) ** 2 for change in changes)
    first_price = values[0]
    latest_price = values[-1]
    total_change = latest_price - first_price

    direction = (
        "UP" if total_change > 0
        else "DOWN" if total_change < 0
        else "FLAT"
    )

    return {
        "sample_size": len(values),
        "first_price": first_price,
        "latest_price": latest_price,
        "change": total_change,
        "change_percent": total_change / first_price * 100
        if first_price else None,
        "direction": direction,
        "mean_absolute_tick_change": mean(abs(change) for change in changes),
        "tick_change_stddev": sqrt(variance),
    }


def momentum_statistics(prices, short_window=10, long_window=30):
    """Compare short and long moving averages."""
    values = _numeric_prices(prices)
    short_window = max(2, int(short_window))
    long_window = max(short_window, int(long_window))

    if len(values) < long_window:
        return {
            "signal": "INSUFFICIENT DATA",
            "short_average": None,
            "long_average": None,
            "sample_size": len(values),
        }

    short_average = mean(values[-short_window:])
    long_average = mean(values[-long_window:])
    signal = (
        "UPWARD MOMENTUM" if short_average > long_average
        else "DOWNWARD MOMENTUM" if short_average < long_average
        else "NEUTRAL"
    )

    return {
        "signal": signal,
        "short_average": short_average,
        "long_average": long_average,
        "sample_size": len(values),
    }


def analyse_market(prices, symbol="UNKNOWN", window=100):
    """Combine digit, price and momentum statistics."""
    window = max(1, int(window))
    selected = _price_texts(prices)[-window:]

    return {
        "symbol": str(symbol),
        "price": price_statistics(selected),
        "digits": digit_statistics(selected, window=window),
        "momentum": momentum_statistics(selected),
        "analysis_window": len(selected),
    }


def rank_markets(market_analyses):
    """Rank markets by observed mean absolute tick movement."""
    analyses = list(market_analyses or [])

    def ranking_key(item):
        movement = item.get("price", {}).get("mean_absolute_tick_change")
        try:
            movement = float(movement)
        except (TypeError, ValueError):
            return (0, 0.0)

        if not isfinite(movement):
            return (0, 0.0)

        return (1, movement)

    return sorted(analyses, key=ranking_key, reverse=True)


def rank_digits_across_markets(market_analyses):
    """Aggregate observed digit counts and samples across markets."""
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
        rows = analysis.get("digits", {}).get("counts", [])
        seen_in_market = set()

        for row in rows:
            digit = row.get("digit")
            if digit not in totals:
                continue

            try:
                count = max(0, int(row.get("count", 0) or 0))
                samples = max(0, int(row.get("sample_size", 0) or 0))
            except (TypeError, ValueError):
                continue

            totals[digit]["total_count"] += count

            # Each market contributes its sample size once per digit,
            # rather than repeatedly for duplicated rows.
            if digit not in seen_in_market:
                totals[digit]["total_samples"] += samples
                if samples > 0:
                    totals[digit]["markets_observed"] += 1
                seen_in_market.add(digit)

    results = []
    for item in totals.values():
        samples = item["total_samples"]
        item["percentage"] = round(
            item["total_count"] / samples * 100, 2
        ) if samples else 0.0
        item["difference_from_uniform"] = round(
            item["percentage"] - 10.0, 2
        )
        results.append(item)

    return sorted(
        results,
        key=lambda item: (
            item["percentage"], item["total_count"], -item["digit"]
        ),
        reverse=True,
    )

def moving_average(prices, period):
    if period <= 0:
        raise ValueError("Period must be greater than zero.")

    if len(prices) < period:
        return None

    return sum(prices[-period:]) / period


def crossover_signal(prices, fast_period=5, slow_period=10):
    if fast_period <= 0 or slow_period <= 0:
        raise ValueError("Periods must be positive.")

    if fast_period >= slow_period:
        raise ValueError(
            "Fast period must be smaller than slow period."
        )

    if len(prices) < slow_period + 1:
        return "WAIT"

    previous_prices = prices[:-1]

    previous_fast = moving_average(
        previous_prices, fast_period
    )
    previous_slow = moving_average(
        previous_prices, slow_period
    )

    current_fast = moving_average(
        prices, fast_period
    )
    current_slow = moving_average(
        prices, slow_period
    )

    if previous_fast <= previous_slow and current_fast > current_slow:
        return "UP"

    if previous_fast >= previous_slow and current_fast < current_slow:
        return "DOWN"

    return "WAIT"

def moving_average(prices, period):
    if len(prices) < period:
        return None

    return sum(prices[-period:]) / period


def test_moving_average():
    prices = [10, 20, 30, 40]

    assert moving_average(prices, 2) == 35
    assert moving_average(prices, 3) == 30
    assert moving_average(prices, 5) is None

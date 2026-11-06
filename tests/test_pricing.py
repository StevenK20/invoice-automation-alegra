import pytest

from invoice_bot.pricing import suggested_price


@pytest.mark.parametrize("cost,price", [(10000, 16000), (21000, 34000), (100, 1000), (0, 1000)])
def test_suggested_price(cost, price):
    assert suggested_price(cost) == price

"""Suggested retail price for new products: cost x margin x VAT, rounded to the thousand."""
from __future__ import annotations

DEFAULT_MARGIN = 1.35
DEFAULT_VAT = 1.19


def suggested_price(cost: float, margin: float = DEFAULT_MARGIN, vat: float = DEFAULT_VAT) -> int:
    """Round half-up to the nearest 1,000 COP (never below 1,000)."""
    value = cost * margin * vat
    thousands = int(value // 1000)
    if value - thousands * 1000 >= 500:
        thousands += 1
    return max(thousands, 1) * 1000

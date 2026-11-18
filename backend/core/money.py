"""Money arithmetic shared by selling, reports and analytics.

Every amount the shop sees is in TZS to the cent, and shelf prices are
VAT-inclusive, so the VAT on a standard-rated amount is its 18/118 share.
Keeping these in one place means the till, the Z-report and every report
round and split VAT the same way.
"""

from decimal import Decimal

CENT = Decimal('0.01')
ZERO = Decimal('0')
VAT_RATE = Decimal('0.18')


def money(value):
    """`value` (None counts as 0) rounded to the cent."""
    return Decimal(value or 0).quantize(CENT)


def vat_portion(amount):
    """The VAT inside a VAT-inclusive `amount`, unrounded: round the total
    of several portions with money(), not each one."""
    return amount * VAT_RATE / (1 + VAT_RATE)


def split(amount, weights):
    """`amount` shared out in proportion to `weights`, to the cent, with the
    last share taking the remainder so the shares always add up exactly."""
    total = sum(weights, ZERO)
    shares, left = [], money(amount)
    for i, weight in enumerate(weights):
        share = left if i == len(weights) - 1 else money(amount * weight / total)
        shares.append(share)
        left -= share
    return shares

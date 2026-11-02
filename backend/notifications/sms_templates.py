"""SMS template texts and strict filling-in.

Templates use Python {placeholder} syntax. A value that is missing, None
or empty raises MissingPlaceholder and the recipient is skipped, so a
literal {name} or "None" never reaches anyone's phone.

DEFAULT_TEMPLATES is the shipped text; `manage.py seed_sms_templates`
loads it for every shop (--force resets edited ones).
"""

import string

DAILY_SALES_SUMMARY = 'DAILY_SALES_SUMMARY'

TEMPLATE_KEYS = [
    (DAILY_SALES_SUMMARY, 'Daily sales summary'),
]

# Placeholders each key may use, with what they hold — shown to the owner
# next to the template editor.
PLACEHOLDERS = {
    DAILY_SALES_SUMMARY: {
        'shop': 'Business name',
        'store': 'Store name',
        'date': 'Day, e.g. 02/11',
        'sales_total': 'Total sales, e.g. 1,250,000',
        'sales_count': 'Number of sales',
        'by_method': 'Total per payment method, e.g. Cash 900,000, M-Pesa 350,000',
        'voids': 'Voided sales',
        'missing_efd': 'Sales without an EFD receipt number',
        'cash_diff': 'Cash difference at shift close, e.g. +2,000',
        'purchases': 'Supplier invoices received',
        'low_stock': 'Products low or out of stock',
        'expiring': 'Batches expiring within 30 days',
    },
}

DEFAULT_TEMPLATES = {
    (DAILY_SALES_SUMMARY, 'en'): (
        '{store} {date}: Sales TZS {sales_total} ({sales_count}). {by_method}. Voids {voids}. '
        'No EFD no: {missing_efd}. Cash diff {cash_diff}. Purchases {purchases}. '
        'Low stock {low_stock}, expiring 30d {expiring}.'
    ),
    (DAILY_SALES_SUMMARY, 'sw'): (
        '{store} {date}: Mauzo TZS {sales_total} ({sales_count}). {by_method}. Yaliyobatilishwa {voids}. '
        'Bila namba ya EFD: {missing_efd}. Tofauti ya fedha {cash_diff}. Manunuzi {purchases}. '
        'Stock ndogo {low_stock}, zinaisha muda siku 30 {expiring}.'
    ),
}


class MissingPlaceholder(Exception):
    pass


class TemplateSyntaxError(Exception):
    pass


def placeholders(body):
    """The {names} in a template; TemplateSyntaxError for unbalanced or
    malformed braces, or for attribute/index lookups like {a.b}."""
    try:
        names = [name for _text, name, _spec, _conv in string.Formatter().parse(body) if name is not None]
    except ValueError as exc:
        raise TemplateSyntaxError(str(exc)) from exc
    for name in names:
        if not name.isidentifier():
            raise TemplateSyntaxError(f'"{{{name}}}" is not a valid placeholder.')
    return names


def check_template(body, key):
    """Raises TemplateSyntaxError if the body won't fill in for this key."""
    unknown = [n for n in placeholders(body) if n not in PLACEHOLDERS.get(key, {})]
    if unknown:
        raise TemplateSyntaxError(f'Unknown placeholder: {{{unknown[0]}}}.')


def render(body, values):
    for name in placeholders(body):
        value = values.get(name)
        if value is None or str(value).strip() == '':
            raise MissingPlaceholder(name)
    return body.format(**{k: v for k, v in values.items() if v is not None})

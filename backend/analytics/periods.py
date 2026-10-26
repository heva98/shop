"""
Period ids and the relative-period resolver for the analytics query.

Concrete period ids, DHIS2 style, on the calendar in the shop's timezone
(settings.TIME_ZONE):

    DAY      20261026
    WEEK     2026W43     ISO week, Monday to Sunday
    MONTH    202610
    QUARTER  2026Q4
    YEAR     2026

Relative periods resolve to a list of those ids against "today". As in
DHIS2, `LAST_N_*` means the N whole periods *before* the current one; the
current one is `THIS_*` (or TODAY). Ids are returned oldest first.
"""
from __future__ import annotations

import calendar
import datetime
import re
from dataclasses import dataclass

from django.utils import timezone


class PeriodType:
    DAY = 'DAY'
    WEEK = 'WEEK'
    MONTH = 'MONTH'
    QUARTER = 'QUARTER'
    YEAR = 'YEAR'


PERIOD_TYPES = [
    (PeriodType.DAY, 'Day'),
    (PeriodType.WEEK, 'Week'),
    (PeriodType.MONTH, 'Month'),
    (PeriodType.QUARTER, 'Quarter'),
    (PeriodType.YEAR, 'Year'),
]

# (code, label, period type of the ids it resolves to, (last offset, count))
# An offset of 0 ends on the current period, -1 on the one before it. A
# count of None means "from the start of this year".
_RELATIVE = [
    ('TODAY', 'Today', PeriodType.DAY, (0, 1)),
    ('YESTERDAY', 'Yesterday', PeriodType.DAY, (-1, 1)),
    ('LAST_7_DAYS', 'Last 7 days', PeriodType.DAY, (-1, 7)),
    ('LAST_14_DAYS', 'Last 14 days', PeriodType.DAY, (-1, 14)),
    ('LAST_30_DAYS', 'Last 30 days', PeriodType.DAY, (-1, 30)),
    ('THIS_WEEK', 'This week', PeriodType.WEEK, (0, 1)),
    ('LAST_WEEK', 'Last week', PeriodType.WEEK, (-1, 1)),
    ('LAST_4_WEEKS', 'Last 4 weeks', PeriodType.WEEK, (-1, 4)),
    ('LAST_12_WEEKS', 'Last 12 weeks', PeriodType.WEEK, (-1, 12)),
    ('THIS_MONTH', 'This month', PeriodType.MONTH, (0, 1)),
    ('LAST_MONTH', 'Last month', PeriodType.MONTH, (-1, 1)),
    ('LAST_3_MONTHS', 'Last 3 months', PeriodType.MONTH, (-1, 3)),
    ('LAST_6_MONTHS', 'Last 6 months', PeriodType.MONTH, (-1, 6)),
    ('LAST_12_MONTHS', 'Last 12 months', PeriodType.MONTH, (-1, 12)),
    ('MONTHS_THIS_YEAR', 'Months this year', PeriodType.MONTH, (0, None)),
    ('THIS_QUARTER', 'This quarter', PeriodType.QUARTER, (0, 1)),
    ('LAST_QUARTER', 'Last quarter', PeriodType.QUARTER, (-1, 1)),
    ('LAST_4_QUARTERS', 'Last 4 quarters', PeriodType.QUARTER, (-1, 4)),
    ('QUARTERS_THIS_YEAR', 'Quarters this year', PeriodType.QUARTER, (0, None)),
    ('THIS_YEAR', 'This year', PeriodType.YEAR, (0, 1)),
    ('LAST_YEAR', 'Last year', PeriodType.YEAR, (-1, 1)),
    ('LAST_5_YEARS', 'Last 5 years', PeriodType.YEAR, (-1, 5)),
]
RELATIVE_PERIODS = [(code, label, ptype) for code, label, ptype, _ in _RELATIVE]
_RELATIVE_BY_CODE = {code: (ptype, span) for code, _, ptype, span in _RELATIVE}
RELATIVE_PERIOD_CODES = frozenset(_RELATIVE_BY_CODE)

_PERIOD_RE = re.compile(
    r'^(?:(?P<year>\d{4})'
    r'|(?P<q_year>\d{4})Q(?P<quarter>[1-4])'
    r'|(?P<w_year>\d{4})W(?P<week>\d{2})'
    r'|(?P<m_year>\d{4})(?P<month>0[1-9]|1[0-2])'
    r'|(?P<d_year>\d{4})(?P<d_month>0[1-9]|1[0-2])(?P<day>\d{2}))$'
)


@dataclass(frozen=True)
class Period:
    id: str
    type: str
    start: datetime.date
    end: datetime.date   # exclusive


def _next_month(year: int, month: int) -> datetime.date:
    return datetime.date(year + 1, 1, 1) if month == 12 else datetime.date(year, month + 1, 1)


def parse_period(period_id: str) -> Period:
    """Parse a concrete period id. Raises ValueError if it isn't one."""
    m = _PERIOD_RE.match(period_id or '')
    if not m:
        raise ValueError(f'Unknown period id: {period_id!r}')
    if m['year']:
        year = int(m['year'])
        return Period(period_id, PeriodType.YEAR, datetime.date(year, 1, 1), datetime.date(year + 1, 1, 1))
    if m['q_year']:
        year, q = int(m['q_year']), int(m['quarter'])
        start = datetime.date(year, 3 * (q - 1) + 1, 1)
        return Period(period_id, PeriodType.QUARTER, start, _next_month(year, 3 * q))
    if m['w_year']:
        # fromisocalendar rejects week 53 of a 52-week year, and week 0.
        start = datetime.date.fromisocalendar(int(m['w_year']), int(m['week']), 1)
        return Period(period_id, PeriodType.WEEK, start, start + datetime.timedelta(days=7))
    if m['m_year']:
        year, month = int(m['m_year']), int(m['month'])
        return Period(period_id, PeriodType.MONTH, datetime.date(year, month, 1), _next_month(year, month))
    start = datetime.date(int(m['d_year']), int(m['d_month']), int(m['day']))
    return Period(period_id, PeriodType.DAY, start, start + datetime.timedelta(days=1))


def period_id(ptype: str, day: datetime.date) -> str:
    """The id of the `ptype` period that contains `day`."""
    if ptype == PeriodType.DAY:
        return f'{day:%Y%m%d}'
    if ptype == PeriodType.WEEK:
        iso = day.isocalendar()
        return f'{iso.year}W{iso.week:02d}'
    if ptype == PeriodType.MONTH:
        return f'{day:%Y%m}'
    if ptype == PeriodType.QUARTER:
        return f'{day.year}Q{(day.month - 1) // 3 + 1}'
    return str(day.year)


# ── relative periods ───────────────────────────────────────────────────────
# Each period type is stepped through as an ordinal, so "the 12 months
# before this one" crosses year boundaries without special cases.

def _ordinal(ptype: str, day: datetime.date) -> int:
    if ptype == PeriodType.DAY:
        return day.toordinal()
    if ptype == PeriodType.WEEK:
        return (day - datetime.timedelta(days=day.weekday())).toordinal() // 7
    if ptype == PeriodType.MONTH:
        return day.year * 12 + day.month - 1
    if ptype == PeriodType.QUARTER:
        return day.year * 4 + (day.month - 1) // 3
    return day.year


def _from_ordinal(ptype: str, n: int) -> str:
    if ptype == PeriodType.DAY:
        return period_id(ptype, datetime.date.fromordinal(n))
    if ptype == PeriodType.WEEK:
        # Day 1 (1 Jan of year 1) is a Monday, so Mondays are 7n + 1.
        return period_id(ptype, datetime.date.fromordinal(n * 7 + 1))
    if ptype == PeriodType.MONTH:
        return f'{n // 12}{n % 12 + 1:02d}'
    if ptype == PeriodType.QUARTER:
        return f'{n // 4}Q{n % 4 + 1}'
    return str(n)


def resolve_relative_period(code: str, today: datetime.date | None = None) -> list[str]:
    """Resolve one relative period code to concrete period ids."""
    if code not in RELATIVE_PERIOD_CODES:
        raise ValueError(f'Unknown relative period: {code!r}')
    today = today or timezone.localdate()
    ptype, (offset, count) = _RELATIVE_BY_CODE[code]
    last = _ordinal(ptype, today) + offset
    if count is None:
        count = last - _ordinal(ptype, datetime.date(today.year, 1, 1)) + 1
    return [_from_ordinal(ptype, n) for n in range(last - count + 1, last + 1)]


def resolve_periods(items, today: datetime.date | None = None) -> list[str]:
    """Expand a mix of relative codes and concrete ids into concrete ids,
    de-duplicated in first-seen order. Raises ValueError on an unknown item."""
    ids: list[str] = []
    for item in items:
        if item in RELATIVE_PERIOD_CODES:
            new_ids = resolve_relative_period(item, today)
        else:
            new_ids = [parse_period(item).id]
        ids.extend(i for i in new_ids if i not in ids)
    return ids


# ── labels ─────────────────────────────────────────────────────────────────

def period_label(period: Period) -> str:
    if period.type == PeriodType.DAY:
        return f'{period.start.day} {calendar.month_abbr[period.start.month]} {period.start.year}'
    if period.type == PeriodType.WEEK:
        last = period.end - datetime.timedelta(days=1)
        return (f'Week {period.id[-2:].lstrip("0")} {period.id[:4]} '
                f'({period.start.day} {calendar.month_abbr[period.start.month]} – '
                f'{last.day} {calendar.month_abbr[last.month]})')
    if period.type == PeriodType.MONTH:
        return f'{calendar.month_name[period.start.month]} {period.start.year}'
    if period.type == PeriodType.QUARTER:
        return f'Q{period.id[-1]} {period.start.year}'
    return str(period.start.year)

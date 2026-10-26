"""
The aggregate query behind GET /api/analytics/query/, modelled on DHIS2's
/api/analytics:

    ?dimension=dx:sales.net;profit.gross
    &dimension=pe:LAST_12_MONTHS
    &dimension=ou:FIRM
    &filter=category:<id>
    &total=pe

`dimension` items become columns of the result rows; `filter` items only
restrict the facts. `dx` (metrics) must be a dimension and `pe` must be
given, as one or the other. A dynamic dimension given with no items is
broken down by every value found.

`total` (repeatable) asks for extra rows aggregated over the listed
dimensions, which then carry the item `__total`: `total=pe` adds, for every
other combination, the value over all the selected periods together. Each
total is its own query, so a margin or a distinct count is computed over
the whole group, never summed from the cells.

Every id is checked against the registry, as the caller's firm sees it,
before any fact is touched; an unknown or switched-off id is a 400. Facts
are always confined to the caller's firm and the stores they hold a role at.

Metrics defined on the same facts (same source, same fact queryset) are
evaluated together in one `.values(...).annotate(...)`, with each period,
store and dimension item a SQL group key, so no fact row passes through
Python. Periods of different types (a month and its days) overlap, so each
period type is grouped in its own query. A balance (stock on hand) counts
every fact up to the end of a period, so it takes one query per period.
"""
from __future__ import annotations

import datetime
import itertools
import logging
import operator
import time
from dataclasses import dataclass
from decimal import Decimal
from functools import reduce
from typing import Callable

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import CharField, DateField, F, Q, Value
from django.db.models.functions import Trunc, TruncDate
from django.utils import timezone

from .engine import Cell, Row, evaluate_many
from .periods import PeriodType, parse_period, period_id, period_label, resolve_periods
from .registry import (
    DIMENSIONS, FIRM, METRICS, SOURCES, Context, FactSource, Metric, as_expression, org_units,
    visible_dimensions, visible_metrics,
)

logger = logging.getLogger(__name__)

TOTAL = '__total'


def _max_cells() -> int:
    return getattr(settings, 'ANALYTICS_MAX_CELLS', 50_000)


def _slow_query_ms() -> int:
    return getattr(settings, 'ANALYTICS_SLOW_QUERY_MS', 1_000)


class QueryError(Exception):
    def __init__(self, detail: str, status: int = 400, **extra):
        super().__init__(detail)
        self.status = status
        self.body = {'detail': detail, **extra}


# ── request parsing ────────────────────────────────────────────────────────

@dataclass
class Spec:
    id: str
    items: list[str]
    is_filter: bool


def parse_specs(params) -> list[Spec]:
    specs, seen = [], set()
    for param, is_filter in (('dimension', False), ('filter', True)):
        for raw in params.getlist(param):
            dim_id, _, items = raw.partition(':')
            dim_id = dim_id.strip()
            if not dim_id:
                raise QueryError(f'Empty {param} parameter.')
            if dim_id in seen:
                raise QueryError(f"Dimension '{dim_id}' is given more than once.")
            seen.add(dim_id)
            ids = list(dict.fromkeys(i.strip() for i in items.split(';') if i.strip()))
            specs.append(Spec(dim_id, ids, is_filter))
    return specs


# ── field helpers ──────────────────────────────────────────────────────────

def _field_at(model, path: str) -> models.Field:
    meta = model._meta
    parts = path.split('__')
    for part in parts[:-1]:
        meta = meta.get_field(part).related_model._meta
    return meta.get_field(parts[-1])


def source_model(source: FactSource):
    # Every metric of a source is defined on the same model.
    return next(m for m in METRICS.values() if m.source == source.id).queryset().model


def _is_datetime(source: FactSource) -> bool:
    return isinstance(_field_at(source_model(source), source.date), models.DateTimeField)


def _item_id(value) -> str:
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return '' if value is None else str(value)


def _any(conditions) -> Q:
    return reduce(operator.or_, conditions, Q(pk__in=[]))


@dataclass
class Variant:
    """One way to group (or filter) one axis in one query: the facts it
    keeps, the SQL key (None for a filter), each key's result items (None:
    the key itself is the item) and how to turn a raw key into an item id."""
    condition: Q
    key: object = None
    items: dict[str, list[str]] | None = None
    normalize: Callable[[object], str] | None = None
    # A balance: the key is a period bucket, and each of these
    # (period id, end) is the running total of the buckets before its end.
    cumulate: list[tuple[str, datetime.date]] | None = None


# ── axes: one per dimension/filter other than dx ───────────────────────────

class Axis:
    dim_id: str
    label: str
    is_filter: bool
    item_ids: list[str]
    names: dict[str, str]

    def check(self, metric: Metric) -> None:
        """Raise QueryError if `metric` can't be broken down by this axis."""

    def prepare(self, qs, source: FactSource):
        return qs

    def variants(self, source: FactSource, as_filter: bool) -> list[Variant]:
        raise NotImplementedError

    def cell_count(self) -> int:
        return max(len(self.item_ids), 1)

    def _not_applicable(self, metric: Metric):
        verb = 'filtered' if self.is_filter else 'broken down'
        raise QueryError(f"'{metric.label}' cannot be {verb} by {self.label.lower()}.",
                         code='dimension_not_applicable')


def _merged(ranges):
    """Sorted, with touching or overlapping [start, end) ranges joined."""
    out = []
    for start, end in sorted(ranges):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


_TRUNC_KIND = {PeriodType.WEEK: 'week', PeriodType.MONTH: 'month',
               PeriodType.QUARTER: 'quarter', PeriodType.YEAR: 'year'}


class PeriodAxis(Axis):
    dim_id, label = 'pe', 'Period'

    def __init__(self, spec: Spec):
        if not spec.items:
            raise QueryError('pe needs at least one period, e.g. pe:LAST_30_DAYS.')
        try:
            ids = resolve_periods(spec.items)
        except ValueError as exc:
            raise QueryError(str(exc), code='unknown_item') from None
        self.is_filter = spec.is_filter
        self.periods = [parse_period(pid) for pid in ids]
        self.item_ids = [p.id for p in self.periods]
        self.names = {p.id: period_label(p) for p in self.periods}

    def _bound(self, source, day: datetime.date):
        if _is_datetime(source):
            return datetime.datetime.combine(day, datetime.time.min, tzinfo=timezone.get_current_timezone())
        return day

    def _range(self, source, start, end) -> Q:
        return Q(**{f'{source.date}__gte': self._bound(source, start),
                    f'{source.date}__lt': self._bound(source, end)})

    def check(self, metric):
        if SOURCES[metric.source].cumulative and metric.denominator is not None:
            raise QueryError(f"'{metric.label}' can't be a balance: only sums can be carried forward.")

    def _trunc(self, source, ptype):
        tz = timezone.get_current_timezone()
        if _is_datetime(source):
            if ptype == PeriodType.DAY:
                return TruncDate(source.date, tzinfo=tz)
            return Trunc(source.date, _TRUNC_KIND[ptype], tzinfo=tz)
        if ptype == PeriodType.DAY:
            return F(source.date)
        return Trunc(source.date, _TRUNC_KIND[ptype], output_field=DateField())

    def variants(self, source, as_filter):
        if source.cumulative:
            # Everything up to the end of the period. As a filter, several
            # periods mean "as of the end of the last one".
            if as_filter:
                end = max(p.end for p in self.periods)
                return [Variant(Q(**{f'{source.date}__lt': self._bound(source, end)}))]
            # One scan per period type, grouped into buckets of that type;
            # AnalyticsQuery.run turns the buckets into closing balances.
            by_type: dict[str, list] = {}
            for p in self.periods:
                by_type.setdefault(p.type, []).append(p)
            return [
                Variant(Q(**{f'{source.date}__lt': self._bound(source, max(p.end for p in periods))}),
                        self._trunc(source, ptype), {p.id: [p.id] for p in periods},
                        cumulate=[(p.id, p.end) for p in periods])
                for ptype, periods in by_type.items()
            ]

        if as_filter:
            return [Variant(_any(self._range(source, s, e)
                                 for s, e in _merged((p.start, p.end) for p in self.periods)))]
        by_type: dict[str, list] = {}
        for p in self.periods:
            by_type.setdefault(p.type, []).append(p)
        out = []
        for ptype, periods in by_type.items():
            def normalize(key, ptype=ptype):
                day = key.date() if isinstance(key, datetime.datetime) else key
                return period_id(ptype, day)
            out.append(Variant(
                _any(self._range(source, s, e) for s, e in _merged((p.start, p.end) for p in periods)),
                self._trunc(source, ptype), {p.id: [p.id] for p in periods}, normalize,
            ))
        return out


class OrgUnitAxis(Axis):
    dim_id, label = 'ou', 'Stores'

    def __init__(self, spec: Spec, ctx: Context):
        if not spec.items:
            raise QueryError('ou needs at least one store, e.g. ou:FIRM.')
        units = org_units(ctx)
        self.is_filter = spec.is_filter
        self.item_ids = [i.upper() if i.upper() == FIRM else i for i in spec.items]
        unknown = [i for i in self.item_ids if i not in units]
        if unknown:
            raise QueryError(f"Unknown or inaccessible store: {', '.join(unknown)}.", code='unknown_item')
        self.names = {i: units[i]['label'] for i in self.item_ids}
        self.stores = [i for i in self.item_ids if i != FIRM]

    def variants(self, source, as_filter):
        path = f'{source.store}_id'
        if as_filter:
            return [Variant(Q() if FIRM in self.item_ids else Q(**{f'{path}__in': self.stores}))]
        out = []
        if FIRM in self.item_ids:
            out.append(Variant(Q(), Value(FIRM, output_field=CharField()), {FIRM: [FIRM]}))
        if self.stores:
            out.append(Variant(Q(**{f'{path}__in': self.stores}), F(path),
                               {i: [i] for i in self.stores}, _item_id))
        return out


class DynamicAxis(Axis):
    def __init__(self, spec: Spec, dim, index: int, ctx: Context):
        self.dim_id, self.label, self.dim, self.ctx = dim.id, dim.label, dim, ctx
        self.is_filter = spec.is_filter
        if dim.filter_only and not spec.is_filter:
            raise QueryError(f"'{dim.label}' can only be used as a filter.")
        self.all_items = dim.all_items(ctx)
        if dim.items is not None:
            known = set(self.all_items) | {''}
            unknown = [i for i in spec.items if i not in known]
            if unknown:
                raise QueryError(f"Unknown {dim.label.lower()}: {', '.join(unknown)}.", code='unknown_item')
        if spec.is_filter and not spec.items:
            raise QueryError(f"Filter '{dim.label}' needs at least one item.")
        self.item_ids = list(spec.items)
        self.names = {}
        self.alias = f'd{index}'

    def cell_count(self):
        if self.item_ids:
            return len(self.item_ids)
        if self.all_items:
            return len(self.all_items) + 1
        return (self.dim.count(self.ctx) + 1) if self.dim.count else 1

    def check(self, metric):
        if metric.source not in self.dim.group_by:
            self._not_applicable(metric)

    def prepare(self, qs, source):
        return qs.alias(**{self.alias: as_expression(self.dim.field_for(source.id))})

    def _condition(self, source):
        if not self.item_ids:
            return Q()
        values = [i for i in self.item_ids if i != '']
        ref = self.dim.field_for(source.id)
        if isinstance(ref, str):
            fld = _field_at(source_model(source), ref)
            try:
                values = [fld.to_python(i) for i in values]
            except ValidationError:
                raise QueryError(f'Invalid {self.dim.label.lower()}.', code='unknown_item') from None
        cond = Q(**{f'{self.alias}__in': values})
        if '' in self.item_ids:   # "none": a walk-in customer, no category
            cond |= Q(**{f'{self.alias}__isnull': True})
            if isinstance(ref, str) and isinstance(_field_at(source_model(source), ref), models.CharField):
                cond |= Q(**{self.alias: ''})
        return cond

    def variants(self, source, as_filter):
        cond = self._condition(source)
        if as_filter:
            return [Variant(cond)]
        return [Variant(cond, F(self.alias))]

    def name(self, item) -> str:
        if item == '':
            return self.dim.blank_label
        return self.names.get(item) or self.all_items.get(item) or item


class StoreScope(Axis):
    """The caller's firm and the stores they hold a role at. Applied as a
    filter no caller can drop."""
    dim_id, label, is_filter, item_ids = 'store_scope', 'Store scope', True, []

    def __init__(self, ctx: Context):
        # The firm has a handful of stores: filter on their ids rather than
        # join every fact to core_store to check its firm, which cost a
        # third of a year-long query on two million sale lines.
        unrestricted = ctx.entity is None and ctx.store_ids is None
        self.store_ids = None if unrestricted else [str(i) for i in ctx.stores().values_list('id', flat=True)]

    def variants(self, source, as_filter):
        if self.store_ids is None:
            return [Variant(Q())]
        return [Variant(Q(**{f'{source.store}_id__in': self.store_ids}))]


# ── the query ──────────────────────────────────────────────────────────────

class AnalyticsQuery:
    def __init__(self, params, ctx: Context):
        self.ctx = ctx
        self.specs = parse_specs(params)
        specs = {s.id: s for s in self.specs}

        dx = specs.get('dx')
        if dx is None or dx.is_filter:
            raise QueryError('dx must be given as a dimension, e.g. dimension=dx:sales.net.')
        if not dx.items:
            raise QueryError('dx needs at least one metric.')
        self.metrics = self._metrics(dx.items)

        if 'pe' not in specs:
            raise QueryError('A period is required: add dimension=pe:… or filter=pe:….')

        visible = {d.id: d for d, _ in visible_dimensions(ctx)}
        self.axes: list[Axis] = []
        for i, spec in enumerate(self.specs):
            if spec.id == 'dx':
                continue
            if spec.id == 'pe':
                self.axes.append(PeriodAxis(spec))
            elif spec.id == 'ou':
                self.axes.append(OrgUnitAxis(spec, ctx))
            elif spec.id in visible:
                self.axes.append(DynamicAxis(spec, visible[spec.id], i, ctx))
            else:
                raise QueryError(f"Unknown dimension '{spec.id}'.", code='unknown_dimension')
        self.axes.append(StoreScope(ctx))

        for metric in self.metrics:
            for axis in self.axes:
                axis.check(metric)

        grouped = {a.dim_id for a in self.grouped_axes}
        self.totals: list[frozenset] = []
        for raw in params.getlist('total'):
            dims = frozenset(d.strip() for d in raw.split(';') if d.strip())
            bad = dims - grouped
            if not dims or bad:
                raise QueryError(f"total can only name dimensions that are broken down (not dx): {raw}.")
            if dims not in self.totals:
                self.totals.append(dims)

        self.cells = len(self.metrics)
        for axis in self.grouped_axes:
            self.cells *= axis.cell_count()
        if self.cells > _max_cells():
            raise QueryError(
                f'This query could return up to {self.cells:,} values; the limit is '
                f'{_max_cells():,}. Choose fewer items or move a dimension to Filter.',
                code='too_many_cells', cells=self.cells, max_cells=_max_cells(),
            )
        self.queries = 0

    def _metrics(self, ids) -> list[Metric]:
        enabled = {m.id for m in visible_metrics(self.ctx)}
        unknown = [i for i in ids if i not in enabled]
        if unknown:
            # A metric of a switched-off feature doesn't exist here.
            raise QueryError(f"Unknown data item: {', '.join(unknown)}.", code='unknown_item')
        return [METRICS[i] for i in ids]

    @property
    def grouped_axes(self) -> list[Axis]:
        return [a for a in self.axes if not a.is_filter]

    def _fact_sets(self):
        """Metrics grouped by the facts they're computed from, in dx order."""
        sets: dict[tuple, list[Metric]] = {}
        for metric in self.metrics:
            sets.setdefault((metric.source, metric.queryset), []).append(metric)
        return sets.items()

    def run(self) -> list[tuple[dict[str, str], Metric, object]]:
        """(item per axis, metric, value) for every non-empty cell, then for
        every non-empty total."""
        out = []
        for (source_id, queryset), metrics in self._fact_sets():
            source = SOURCES[source_id]
            qs = queryset()
            for axis in self.axes:
                qs = axis.prepare(qs, source)
            for collapsed in [frozenset(), *self.totals]:
                per_axis = [a.variants(source, a.is_filter or a.dim_id in collapsed) for a in self.axes]
                marks = {d: TOTAL for d in collapsed}
                for combo in itertools.product(*per_axis):
                    facts = qs.filter(*(v.condition for v in combo))
                    grouped = [(a, v) for a, v in zip(self.axes, combo) if v.key is not None]
                    rows = evaluate_many(metrics, facts, group_by=[v.key for _, v in grouped])
                    self.queries += 1
                    for index, (_, v) in enumerate(grouped):
                        if v.cumulate:
                            rows = _running_totals(rows, index, v.cumulate, metrics)
                    for row in rows:
                        keys = [(v.normalize or _item_id)(k) for (_, v), k in zip(grouped, row.keys)]
                        if any(v.items is not None and key not in v.items
                               for (_, v), key in zip(grouped, keys)):
                            continue  # a period or store that wasn't asked for
                        fans = [
                            [(a.dim_id, item) for item in (v.items[key] if v.items is not None else [key])]
                            for (a, v), key in zip(grouped, keys)
                        ]
                        for items in itertools.product(*fans):
                            for metric, cell in zip(metrics, row.cells):
                                if cell.value is not None:
                                    out.append(({**dict(items), **marks}, metric, cell.value))
        return out


def _running_totals(rows: list[Row], index: int, periods, metrics) -> list[Row]:
    """Closing balances from period buckets: for every combination of the
    other keys, each period's numerators are the sum of the buckets that
    start before the period ends. Buckets share the periods' type, so a
    bucket starting before the end lies wholly before it."""
    groups: dict[tuple, list] = {}
    for row in rows:
        day = row.keys[index]
        day = day.date() if isinstance(day, datetime.datetime) else day
        rest = row.keys[:index] + row.keys[index + 1:]
        groups.setdefault(rest, []).append((day, row.cells))
    out = []
    for rest, buckets in groups.items():
        for pid, end in periods:
            nums = [None] * len(metrics)
            for day, cells in buckets:
                if day < end:
                    for i, cell in enumerate(cells):
                        if cell.numerator is not None:
                            nums[i] = (nums[i] or 0) + Decimal(str(cell.numerator))
            if all(n is None for n in nums):
                continue
            keys = rest[:index] + (pid,) + rest[index:]
            out.append(Row(keys, tuple(Cell(n, None, m.compute(n)) for n, m in zip(nums, metrics))))
    return out


def _format(metric: Metric, value):
    if value is None:
        return None
    if metric.unit in ('count', 'qty') and value == int(value):
        return int(value)
    return round(float(value), 2)


def run_query(params, ctx: Context) -> dict:
    started = time.perf_counter()
    query = AnalyticsQuery(params, ctx)
    cells = query.run()

    columns = [s.id for s in query.specs if not s.is_filter]
    axes = {a.dim_id: a for a in query.axes if a.dim_id != 'store_scope'}

    # Lazy dimensions (products, customers) have no item list to name what a
    # query found, so look up just those.
    for axis in axes.values():
        if isinstance(axis, DynamicAxis) and axis.dim.lazy:
            seen = {items[axis.dim_id] for items, *_ in cells if axis.dim_id in items} | set(axis.item_ids)
            seen -= {'', TOTAL}
            axis.names = {i['id']: i['label'] for i in axis.dim.search(ctx, None, list(seen))}

    dimensions = {'dx': [m.id for m in query.metrics]}
    for dim_id, axis in axes.items():
        if axis.item_ids:
            dimensions[dim_id] = axis.item_ids
        else:
            seen = {items[dim_id] for items, *_ in cells if dim_id in items} - {TOTAL}
            known = list(axis.all_items) if isinstance(axis, DynamicAxis) else []
            order = {item: i for i, item in enumerate(known)}
            dimensions[dim_id] = sorted(
                seen, key=lambda i: (i == '', order.get(i, len(order)), axis.name(i).lower()))
    order = {d: {item: i for i, item in enumerate(ids)} for d, ids in dimensions.items()}

    rows = []
    for items, metric, value in cells:
        items = {**items, 'dx': metric.id}
        rows.append([items[c] for c in columns] + [_format(metric, value)])
    rows.sort(key=lambda r: [order[c].get(r[i], len(order[c])) for i, c in enumerate(columns)])

    # Item names are keyed by dimension: ids are only unique within one.
    items = {'dx': {'name': 'Data', 'items': {
        m.id: {'name': m.label, 'unit': m.unit} for m in query.metrics
    }}}
    totalled = set().union(*query.totals) if query.totals else set()
    for dim_id, axis in axes.items():
        names = {}
        for item in dimensions[dim_id]:
            names[item] = {'name': axis.name(item) if isinstance(axis, DynamicAxis) else axis.names.get(item, item)}
        if dim_id in totalled:
            names[TOTAL] = {'name': 'Total'}
        items[dim_id] = {'name': axis.label, 'items': names}

    headers = [
        {'name': c, 'column': 'Data' if c == 'dx' else axes[c].label, 'valueType': 'TEXT', 'meta': True}
        for c in columns
    ] + [{'name': 'value', 'column': 'Value', 'valueType': 'NUMBER', 'meta': False}]
    elapsed_ms = (time.perf_counter() - started) * 1000
    log = logger.warning if elapsed_ms > _slow_query_ms() else logger.info
    log('analytics query user=%s dx=%s dimensions=%s filters=%s totals=%s sql_queries=%d rows=%d time_ms=%.1f',
        ctx.user.pk, ';'.join(dimensions['dx']),
        [s.id for s in query.specs if not s.is_filter and s.id != 'dx'],
        [s.id for s in query.specs if s.is_filter], [sorted(t) for t in query.totals],
        query.queries, len(rows), elapsed_ms)
    return {
        'headers': headers,
        'metaData': {'items': items, 'dimensions': dimensions},
        'rows': rows,
        'height': len(rows),
        'width': len(headers),
    }

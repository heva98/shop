"""
Evaluates registry metrics over their facts, optionally grouped.

Numerator and denominator are aggregated in SQL at fact grain for every
output cell, then divided here, once. A total is a fresh query with less
grouping, never a combination of the cells' values, so ratios (average sale
value, margin) and distinct counts stay correct at every level.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from django.db.models import Count, Expression, QuerySet

from .registry import Metric


@dataclass(frozen=True)
class Cell:
    numerator: object
    denominator: object
    value: Decimal | None


@dataclass(frozen=True)
class Row:
    """One group: a Cell per metric, in the order the metrics were given."""
    keys: tuple
    cells: tuple[Cell, ...]


def evaluate_many(metrics: Sequence[Metric], queryset: QuerySet, *,
                  group_by: Sequence[Expression] = ()) -> list[Row]:
    """Every metric in one `.values(...).annotate(...)` over `queryset`,
    which must be the facts all of `metrics` are defined on.

    Groups with no facts produce no Row, grouped or not."""
    aggregates = {}
    for i, metric in enumerate(metrics):
        aggregates[f'num{i}'] = metric.numerator()
        if metric.denominator is not None:
            aggregates[f'den{i}'] = metric.denominator()

    keys = [f'g{i}' for i in range(len(group_by))]
    if keys:
        rows = (
            queryset.annotate(**dict(zip(keys, group_by)))
            .values(*keys)
            .annotate(**aggregates)
            .order_by(*keys)
        )
    else:
        row = queryset.aggregate(facts=Count('*'), **aggregates)
        rows = [row] if row['facts'] else []

    return [
        Row(
            keys=tuple(row[k] for k in keys),
            cells=tuple(
                Cell(
                    numerator=row[f'num{i}'],
                    denominator=row.get(f'den{i}'),
                    value=metric.compute(row[f'num{i}'], row.get(f'den{i}')),
                )
                for i, metric in enumerate(metrics)
            ),
        )
        for row in rows
    ]

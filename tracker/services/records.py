"""Records panel helpers: ORM-only summaries + list queries.

Pandas is NOT used here (sums/counts/max are plain SQL).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db.models import Sum

from tracker.categories import CATEGORY_ORDER
from tracker.services.dates import month_range


def _ordered_categories():
    from tracker.models import Category

    by_name = {c.name: c for c in Category.objects.all()}
    return [by_name[n] for n in CATEGORY_ORDER if n in by_name] + [
        c for c in by_name.values() if c.name not in CATEGORY_ORDER
    ]


def _cat_totals(qs):
    rows = qs.values('category__name').annotate(t=Sum('amount'))
    totals = {r['category__name']: r['t'] for r in rows}
    return {name: totals.get(name) or Decimal('0.00') for name in CATEGORY_ORDER}


def day_panel_data(day: date) -> dict:
    from tracker.models import Expense

    qs = Expense.objects.filter(date=day).select_related('category')
    totals = _cat_totals(qs)
    income = totals['Income']
    expense = sum((v for k, v in totals.items() if k != 'Income'), Decimal('0.00'))
    return {
        'scope': 'day',
        'period': day.isoformat(),
        'records': list(qs.order_by('id')),
        'totals': totals,
        'income': income,
        'expense': expense,
        'net': income - expense,
        'categories': list(_ordered_categories()),
    }


def month_panel_data(year: int, month: int) -> dict:
    from tracker.models import Expense

    qs = Expense.objects.filter(date__range=month_range(year, month)).select_related('category')
    totals = _cat_totals(qs)
    income = totals['Income']
    expense = sum((v for k, v in totals.items() if k != 'Income'), Decimal('0.00'))
    return {
        'scope': 'month',
        'period': f'{year:04d}-{month:02d}',
        'records': list(qs.order_by('date', 'id')),
        'totals': totals,
        'income': income,
        'expense': expense,
        'net': income - expense,
        'categories': list(_ordered_categories()),
    }

"""Records panel helpers: ORM-only summaries + list queries.

Pandas is NOT used here (sums/counts/max are plain SQL).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db.models import DecimalField, Sum
from django.db.models import Case, When

CATEGORY_ORDER = ['Income', 'Food', 'Transpo', 'Consumable', 'Ownership', 'Miscellaneous']


def _cat_totals(qs):
    rows = qs.values('category__name').annotate(t=Sum('amount'))
    totals = {r['category__name']: r['t'] for r in rows}
    return {name: totals.get(name) or Decimal('0.00') for name in CATEGORY_ORDER}


def day_panel_data(day: date) -> dict:
    from tracker.models import Category, Expense

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
        'categories': list(Category.objects.order_by('name')),
    }


def month_panel_data(year: int, month: int) -> dict:
    from tracker.models import Category, Expense

    qs = Expense.objects.filter(date__year=year, date__month=month).select_related('category')
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
        'categories': list(Category.objects.order_by('name')),
    }


def income_expense_for_day(day: date):
    """Lightweight per-day income/expense split (used by calendar, kept here for reuse)."""
    from tracker.models import Expense

    row = Expense.objects.filter(date=day).aggregate(
        income=Sum(Case(When(category__name='Income', then='amount'), output_field=DecimalField())),
        expense=Sum(
            Case(When(category__name='Income', then=None), default='amount', output_field=DecimalField())
        ),
    )
    return row

"""Insights aggregations: ORM-only. No Pandas here.

Conventions (per outline + user decisions):
- Day scope (period=YYYY-MM-DD)  -> parent MONTH context:
    line = daily expenses in month, pie = month category division,
    summary = category month totals, list = daily rows in month.
- Month scope (period=YYYY-MM)    -> parent YEAR context:
    line = monthly expenses in year, pie = year category division,
    summary = category year totals, list = monthly rows in year.
- Expense series exclude Income. Category division excludes Income.
- Cards: Highest Income = max single Income record;
  Top Food/Transpo = most frequent item name (COUNT);
  Most Costly X = single largest-amount record in that category.
"""
from __future__ import annotations

import calendar as cal_module
from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.db.models import Count, DecimalField, Max, Sum
from django.db.models import Case, When

CATEGORY_ORDER = ['Income', 'Food', 'Transpo', 'Consumable', 'Ownership', 'Miscellaneous']
EXPENSE_CATS = ['Food', 'Transpo', 'Consumable', 'Ownership', 'Miscellaneous']
SORTS = ('expense_desc', 'expense_asc', 'income_desc', 'income_asc')


def _cat_totals(qs) -> dict:
    rows = qs.values('category__name').annotate(t=Sum('amount'))
    totals = {r['category__name']: r['t'] for r in rows}
    return {n: totals.get(n) or Decimal('0.00') for n in CATEGORY_ORDER}


def _top_item(qs, category_name: str) -> dict:
    row = (
        qs.filter(category__name=category_name)
        .values('item')
        .annotate(n=Count('id'))
        .order_by('-n', 'item')
        .first()
    )
    if not row:
        return {'item': '–', 'count': 0}
    return {'item': row['item'], 'count': row['n']}


def _costliest(qs, category_name: str):
    return (
        qs.filter(category__name=category_name).select_related('category').order_by('-amount', '-date').first()
    )


def month_context(day_iso: str) -> dict:
    from tracker.models import Expense

    y, m, _ = map(int, day_iso.split('-'))
    qs = Expense.objects.filter(date__year=y, date__month=m)
    exp_qs = qs.exclude(category__name='Income')

    # daily expense series (line)
    per_day = (
        exp_qs.values('date').annotate(t=Sum('amount')).order_by('date')
    )
    by_day = {r['date'].day: float(r['t']) for r in per_day}
    ndays = cal_module.monthrange(y, m)[1]
    series = [{'x': d, 'y': round(by_day.get(d, 0.0), 2)} for d in range(1, ndays + 1)]

    # pie division (expense cats, month)
    pie_rows = exp_qs.values('category__name').annotate(t=Sum('amount')).order_by('-t')
    pie = [{'label': r['category__name'], 'value': float(r['t'])} for r in pie_rows if r['t']]

    totals = _cat_totals(qs)
    hi = qs.filter(category__name='Income').order_by('-amount', '-date').first()
    cards = {
        'highest_income': {'amount': hi.amount if hi else Decimal('0.00'), 'when': hi.date if hi else None},
        'top_food': _top_item(qs, 'Food'),
        'top_transpo': _top_item(qs, 'Transpo'),
        'costly_consumable': _costliest(qs, 'Consumable'),
        'costly_ownership': _costliest(qs, 'Ownership'),
        'costly_misc': _costliest(qs, 'Miscellaneous'),
    }
    return {
        'kind': 'month',
        'year': y,
        'month': m,
        'label': date(y, m, 1).strftime('%B %Y'),
        'series': series,
        'pie': pie,
        'totals': totals,
        'net': totals['Income'] - sum((v for k, v in totals.items() if k != 'Income'), Decimal('0.00')),
        'cards': cards,
    }


def year_context(ym: str) -> dict:
    from tracker.models import Expense

    y = int(ym.split('-')[0])
    qs = Expense.objects.filter(date__year=y)
    exp_qs = qs.exclude(category__name='Income')

    per_month = exp_qs.values('date__month').annotate(t=Sum('amount')).order_by('date__month')
    by_m = {r['date__month']: float(r['t']) for r in per_month}
    series = [{'x': mo, 'y': round(by_m.get(mo, 0.0), 2),
               'label': date(y, mo, 1).strftime('%b')} for mo in range(1, 13)]

    pie_rows = exp_qs.values('category__name').annotate(t=Sum('amount')).order_by('-t')
    pie = [{'label': r['category__name'], 'value': float(r['t'])} for r in pie_rows if r['t']]

    totals = _cat_totals(qs)
    hi = qs.filter(category__name='Income').order_by('-amount', '-date').first()
    cards = {
        'highest_income': {'amount': hi.amount if hi else Decimal('0.00'), 'when': hi.date if hi else None},
        'top_food': _top_item(qs, 'Food'),
        'top_transpo': _top_item(qs, 'Transpo'),
        'costly_consumable': _costliest(qs, 'Consumable'),
        'costly_ownership': _costliest(qs, 'Ownership'),
        'costly_misc': _costliest(qs, 'Miscellaneous'),
    }
    return {
        'kind': 'year',
        'year': y,
        'label': str(y),
        'series': series,
        'pie': pie,
        'totals': totals,
        'net': totals['Income'] - sum((v for k, v in totals.items() if k != 'Income'), Decimal('0.00')),
        'cards': cards,
    }


def list_rows(scope: str, period: str, sort: str = 'expense_desc') -> list[dict]:
    """Daily-in-month (scope=day) or monthly-in-year (scope=month) summary rows."""
    from tracker.models import Expense

    if sort not in SORTS:
        sort = 'expense_desc'
    if scope == 'month':
        y = int(period.split('-')[0])
        base = Expense.objects.filter(date__year=y)
        buckets: dict[str, dict] = {}
        for mo in range(1, 13):
            buckets[f'{y:04d}-{mo:02d}'] = {'key': f'{y:04d}-{mo:02d}', 'label': date(y, mo, 1).strftime('%b'),
                                            'income': Decimal('0.00'), 'expense': Decimal('0.00'),
                                            'cats': {c: Decimal('0.00') for c in EXPENSE_CATS}}
        agg = base.values('date__month', 'category__name').annotate(t=Sum('amount'))
        for r in agg:
            b = buckets[f"{y:04d}-{r['date__month']:02d}"]
            amt = r['t'] or Decimal('0.00')
            if r['category__name'] == 'Income':
                b['income'] += amt
            else:
                b['expense'] += amt
                if r['category__name'] in b['cats']:
                    b['cats'][r['category__name']] += amt
        rows = [b for b in buckets.values() if b['income'] or b['expense']]
    else:
        y, m, _ = map(int, period.split('-'))
        base = Expense.objects.filter(date__year=y, date__month=m)
        ndays = cal_module.monthrange(y, m)[1]
        buckets = {}
        for d in range(1, ndays + 1):
            k = f'{y:04d}-{m:02d}-{d:02d}'
            buckets[k] = {'key': k, 'label': str(d), 'income': Decimal('0.00'),
                          'expense': Decimal('0.00'), 'cats': {c: Decimal('0.00') for c in EXPENSE_CATS}}
        agg = base.values('date', 'category__name').annotate(t=Sum('amount'))
        for r in agg:
            b = buckets[r['date'].isoformat()]
            amt = r['t'] or Decimal('0.00')
            if r['category__name'] == 'Income':
                b['income'] += amt
            else:
                b['expense'] += amt
                if r['category__name'] in b['cats']:
                    b['cats'][r['category__name']] += amt
        rows = [b for b in buckets.values() if b['income'] or b['expense']]

    key = {'expense_desc': (-1, 'expense'), 'expense_asc': (1, 'expense'),
           'income_desc': (-1, 'income'), 'income_asc': (1, 'income')}[sort]
    reverse = key[0] == -1
    rows.sort(key=lambda r: (r[key[1]], r['key']), reverse=reverse)
    return rows


def insights_for(scope: str, period: str, sort: str = 'expense_desc') -> dict:
    ctx = month_context(period) if scope == 'day' else year_context(period)
    ctx['scope'] = scope
    ctx['period'] = period
    ctx['sort'] = sort if sort in SORTS else 'expense_desc'
    ctx['rows'] = list_rows(scope, period, ctx['sort'])
    return ctx

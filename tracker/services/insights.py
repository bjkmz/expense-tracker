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
  Top Food/Transpo = most frequent item name (COUNT) plus its peak child
  period (day/month/year) and that period's count;
  Most Costly X = single largest-amount record in that category.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.db.models import Count, Sum

from tracker.categories import CATEGORY_ORDER, EXPENSE_CATEGORIES as EXPENSE_CATS
from tracker.services.dates import month_range

SORTS = ('date_asc', 'date_desc', 'expense_desc', 'expense_asc', 'income_desc', 'income_asc')
SORT_DIMENSIONS = (('date', 'Date'), ('expense', 'Expense'), ('income', 'Income'))
SORT_DEFAULTS = {'date': 'date_asc', 'expense': 'expense_desc', 'income': 'income_desc'}


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


def _top_period_cards(qs, bucket_field: str, to_date) -> dict:
    """Most frequent item per category, then its peak child period."""
    cards = {}
    for key, cat in (('top_food', 'Food'), ('top_transpo', 'Transpo')):
        top = _top_item(qs, cat)
        if not top['count']:
            cards[key] = {**top, 'when': None}
            continue
        row = (
            qs.filter(category__name=cat, item=top['item'])
            .values(bucket_field)
            .annotate(n=Count('id'))
            .order_by('-n', bucket_field)
            .first()
        )
        cards[key] = {'item': top['item'], 'count': row['n'], 'when': to_date(row)}
    return cards


def _rollup(qs) -> dict:
    """Shared pie + category totals + net + insight cards for a scope queryset."""
    exp_qs = qs.exclude(category__name='Income')
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
    net = totals['Income'] - sum((v for k, v in totals.items() if k != 'Income'), Decimal('0.00'))
    return {'pie': pie, 'totals': totals, 'net': net, 'cards': cards}


def _top_year(qs, category_name: str):
    row = (
        qs.filter(category__name=category_name)
        .values('date__year').annotate(t=Sum('amount')).order_by('-t', 'date__year').first()
    )
    return row['date__year'] if row else None


def _year_cards(qs) -> dict:
    """Cards for the Yearly view: top year per metric, not a single day record."""
    hi_year = _top_year(qs, 'Income')
    hi_total = (
        qs.filter(category__name='Income', date__year=hi_year).aggregate(t=Sum('amount'))['t']
        if hi_year else None
    ) or Decimal('0.00')
    cards = {
        'highest_income': {'amount': hi_total, 'when': date(hi_year, 1, 1) if hi_year else None},
    }
    cards.update(_top_period_cards(
        qs, 'date__year', lambda r: date(r['date__year'], 1, 1)
    ))
    for key, cat in (
        ('costly_consumable', 'Consumable'),
        ('costly_ownership', 'Ownership'),
        ('costly_misc', 'Miscellaneous'),
    ):
        y = _top_year(qs, cat)
        rec = _costliest(qs.filter(date__year=y), cat) if y else None
        cards[key] = {
            'item': rec.item if rec else '–',
            'amount': rec.amount if rec else Decimal('0.00'),
            'date': date(y, 1, 1) if y else None,
        }
    return cards


def month_context(day_iso: str) -> dict:
    from tracker.models import Expense

    y, m, _ = map(int, day_iso.split('-'))
    first, last = month_range(y, m)
    qs = Expense.objects.filter(date__range=(first, last))
    exp_qs = qs.exclude(category__name='Income')

    # daily expense series (line)
    per_day = (
        exp_qs.values('date').annotate(t=Sum('amount')).order_by('date')
    )
    by_day = {r['date'].day: float(r['t']) for r in per_day}
    per_day_cat = qs.values('date', 'category__name').annotate(t=Sum('amount'))
    day_cats: dict[int, dict[str, float]] = {}
    for r in per_day_cat:
        day_cats.setdefault(r['date'].day, {})[r['category__name']] = float(r['t'])
    ndays = last.day
    series = [{'x': d, 'y': round(by_day.get(d, 0.0), 2),
               'cats': {c: round(day_cats.get(d, {}).get(c, 0.0), 2) for c in CATEGORY_ORDER}}
              for d in range(1, ndays + 1)]

    ctx = _rollup(qs)
    ctx['cards'].update(_top_period_cards(qs, 'date', lambda r: r['date']))
    ctx.update({'kind': 'month', 'year': y, 'month': m,
                'label': date(y, m, 1).strftime('%B %Y'), 'series': series})
    return ctx


def year_context(ym: str) -> dict:
    from tracker.models import Expense

    y = int(ym.split('-')[0])
    qs = Expense.objects.filter(date__year=y)
    exp_qs = qs.exclude(category__name='Income')

    per_month = exp_qs.values('date__month').annotate(t=Sum('amount')).order_by('date__month')
    by_m = {r['date__month']: float(r['t']) for r in per_month}
    per_month_cat = qs.values('date__month', 'category__name').annotate(t=Sum('amount'))
    month_cats: dict[int, dict[str, float]] = {}
    for r in per_month_cat:
        month_cats.setdefault(r['date__month'], {})[r['category__name']] = float(r['t'])
    series = [{'x': mo, 'y': round(by_m.get(mo, 0.0), 2),
               'label': date(y, mo, 1).strftime('%b'),
               'cats': {c: round(month_cats.get(mo, {}).get(c, 0.0), 2) for c in CATEGORY_ORDER}}
              for mo in range(1, 13)]

    ctx = _rollup(qs)
    ctx['cards'].update(_top_period_cards(
        qs, 'date__month', lambda r: date(y, r['date__month'], 1)
    ))
    ctx.update({'kind': 'year', 'year': y, 'label': str(y), 'series': series})
    return ctx


def all_context(granularity: str) -> dict:
    """All-data context: granularity 'yearly' (point per year) or 'monthly' (point per month)."""
    from tracker.models import Expense

    qs = Expense.objects.all()
    exp_qs = qs.exclude(category__name='Income')

    if granularity == 'yearly':
        years = sorted(set(qs.values_list('date__year', flat=True)))
        by = {r['date__year']: float(r['t'])
              for r in exp_qs.values('date__year').annotate(t=Sum('amount'))}
        cats: dict = {}
        for r in qs.values('date__year', 'category__name').annotate(t=Sum('amount')):
            cats.setdefault(r['date__year'], {})[r['category__name']] = float(r['t'])
        series = [{'x': y, 'y': round(by.get(y, 0.0), 2), 'label': str(y),
                   'cats': {c: round(cats.get(y, {}).get(c, 0.0), 2) for c in CATEGORY_ORDER}}
                  for y in years]
    else:
        spans = sorted(set(qs.values_list('date__year', 'date__month')))
        seq: list[tuple[int, int]] = []
        if spans:
            (y, m), (y1, m1) = spans[0], spans[-1]
            while (y, m) <= (y1, m1):
                seq.append((y, m))
                m, y = (1, y + 1) if m == 12 else (m + 1, y)
        by = {(r['date__year'], r['date__month']): float(r['t'])
              for r in exp_qs.values('date__year', 'date__month').annotate(t=Sum('amount'))}
        cats = {}
        for r in qs.values('date__year', 'date__month', 'category__name').annotate(t=Sum('amount')):
            cats.setdefault((r['date__year'], r['date__month']), {})[r['category__name']] = float(r['t'])
        series = [{'x': f'{y}-{m:02d}', 'y': round(by.get((y, m), 0.0), 2),
                   'label': date(y, m, 1).strftime('%b %Y'),
                   'cats': {c: round(cats.get((y, m), {}).get(c, 0.0), 2) for c in CATEGORY_ORDER}}
                  for y, m in seq]

    ctx = _rollup(qs)
    if granularity == 'yearly':
        ctx['cards'] = _year_cards(qs)
    ctx.update({'kind': granularity, 'label': 'All Data', 'series': series})
    return ctx


def list_rows(scope: str, period: str, sort: str = 'date_asc') -> list[dict]:
    """Daily-in-month (scope=day) or monthly-in-year (scope=month) summary rows."""
    from tracker.models import Expense

    if sort not in SORTS:
        sort = 'date_asc'
    if scope in ('yearly', 'overall'):
        years = sorted(set(Expense.objects.values_list('date__year', flat=True)))
        buckets = {}
        for y in years:
            buckets[str(y)] = {'key': str(y), 'label': str(y), 'income': Decimal('0.00'),
                               'expense': Decimal('0.00'), 'cats': {c: Decimal('0.00') for c in EXPENSE_CATS}}
        agg = Expense.objects.values('date__year', 'category__name').annotate(t=Sum('amount'))
        for r in agg:
            b = buckets[str(r['date__year'])]
            amt = r['t'] or Decimal('0.00')
            if r['category__name'] == 'Income':
                b['income'] += amt
            else:
                b['expense'] += amt
                if r['category__name'] in b['cats']:
                    b['cats'][r['category__name']] += amt
        rows = list(buckets.values())
    elif scope == 'month':
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
        rows = list(buckets.values())
    else:
        y, m, _ = map(int, period.split('-'))
        first, last = month_range(y, m)
        base = Expense.objects.filter(date__range=(first, last))
        ndays = last.day
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
        rows = list(buckets.values())

    if sort in ('date_asc', 'date_desc'):
        rows.sort(key=lambda r: r['key'], reverse=(sort == 'date_desc'))
        return rows
    key = {'expense_desc': (-1, 'expense'), 'expense_asc': (1, 'expense'),
           'income_desc': (-1, 'income'), 'income_asc': (1, 'income')}[sort]
    reverse = key[0] == -1
    rows.sort(key=lambda r: (r[key[1]], r['key']), reverse=reverse)
    return rows


def insights_for(scope: str, period: str, sort: str = 'date_asc') -> dict:
    if scope == 'day':
        ctx = month_context(period)
    elif scope == 'month':
        ctx = year_context(period)
    elif scope == 'yearly':
        ctx = all_context('yearly')
    else:
        scope = 'overall'
        ctx = all_context('monthly')
    ctx['scope'] = scope
    ctx['period'] = period
    ctx['sort'] = sort if sort in SORTS else 'date_asc'
    ctx['rows'] = list_rows(scope, period, ctx['sort'])
    if scope == 'day':
        ctx['rows_prefix'] = 'Daily rows in'
    elif scope == 'month':
        ctx['rows_prefix'] = 'Monthly rows in'
    else:
        ctx['rows_prefix'] = 'Yearly rows across'
    ctx['sort_label'], ctx['sort_options'] = sort_menu(ctx['sort'])
    ctx['card_date_format'] = (
        'F Y' if scope == 'month'
        else 'Y' if scope == 'yearly'
        else 'M d, Y' if scope == 'overall'
        else 'M d'
    )
    return ctx


def sort_menu(sort: str) -> tuple[str, list[dict]]:
    """Dropdown state: active dimension flips, others use their natural default."""
    if sort not in SORTS:
        sort = 'date_asc'
    dim, _, direction = sort.rpartition('_')
    names = dict(SORT_DIMENSIONS)
    options = []
    for d, name in SORT_DIMENSIONS:
        nxt = f'{d}_asc' if (d == dim and direction == 'desc') else (f'{d}_desc' if d == dim else SORT_DEFAULTS[d])
        options.append({'name': name, 'next': nxt,
                        'arrow': '↑' if nxt.endswith('_asc') else '↓',
                        'active': d == dim})
    return f"{names[dim]} {'↑' if direction == 'asc' else '↓'}", options


def period_caption(scope: str, period: str) -> tuple[str, str]:
    """Sort-bar caption without building the full insights context."""
    if scope in ('yearly', 'overall'):
        return 'Yearly rows across', 'All Data'
    if scope == 'month':
        return 'Monthly rows in', period.split('-')[0]
    y, m, _ = map(int, period.split('-'))
    return 'Daily rows in', date(y, m, 1).strftime('%B %Y')

"""Heatmap stats: ORM first, Pandas only for mean/median.

- Per-period visible totals (31 days / 12 months) always come from ORM SUMs.
- Global mean/median (all-time, expense-only, non-zero periods) are cached in
  settings.HEATMAP_STATS_PATH and recomputed only when global MAX(updated_at)
  moves. Pandas is imported lazily inside recompute only.
"""
from __future__ import annotations

import json
from decimal import Decimal

from django.conf import settings
from django.db.models import Max, Sum
from django.db.models.functions import TruncMonth


def _db_global_max_iso() -> str | None:
    from tracker.models import Expense

    m = Expense.objects.aggregate(m=Max('updated_at'))['m']
    return m.isoformat() if m else None


def _read_stats_cache() -> dict | None:
    try:
        return json.loads(settings.HEATMAP_STATS_PATH.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None


def get_heatmap_stats() -> dict:
    """Return {mean_daily, median_daily, mean_monthly, median_monthly, ...}.

    Fresh when cached source_max >= current db max. Recomputes otherwise.
    """
    db_max = _db_global_max_iso()
    cached = _read_stats_cache()
    if cached and db_max is not None and cached.get('source_max_updated_at', '') >= db_max:
        return cached
    if cached and db_max is None:
        return cached
    return recompute_heatmap_stats(db_max)


def recompute_heatmap_stats(db_max: str | None = None) -> dict:
    from tracker.models import Expense

    if db_max is None:
        db_max = _db_global_max_iso()

    daily_qs = (
        Expense.objects.exclude(category__name='Income')
        .values('date')
        .annotate(t=Sum('amount'))
        .order_by()
    )
    daily_vals = [float(r['t']) for r in daily_qs if r['t'] and float(r['t']) > 0]

    monthly_qs = (
        Expense.objects.exclude(category__name='Income')
        .annotate(m=TruncMonth('date'))
        .values('m')
        .annotate(t=Sum('amount'))
        .order_by()
    )
    monthly_vals = [float(r['t']) for r in monthly_qs if r['t'] and float(r['t']) > 0]

    if daily_vals:
        import pandas as pd  # lazy: only on recompute

        ds = pd.Series(daily_vals, dtype='float64')
        mean_daily, median_daily = float(ds.mean()), float(ds.median())
    else:
        mean_daily, median_daily = 0.0, 0.0

    if monthly_vals:
        import pandas as pd  # lazy

        ms = pd.Series(monthly_vals, dtype='float64')
        mean_monthly, median_monthly = float(ms.mean()), float(ms.median())
    else:
        mean_monthly, median_monthly = 0.0, 0.0

    stats = {
        'mean_daily': mean_daily,
        'median_daily': median_daily,
        'mean_monthly': mean_monthly,
        'median_monthly': median_monthly,
        'n_days': len(daily_vals),
        'n_months': len(monthly_vals),
        'source_max_updated_at': db_max,
    }
    try:
        settings.HEATMAP_STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
        settings.HEATMAP_STATS_PATH.write_text(json.dumps(stats), encoding='utf-8')
    except OSError:
        pass
    return stats


def compact_amount(v: Decimal | float | int | None) -> str:
    """Short display for calendar cells: strip .00, k/M for thousands, dash for empty."""
    if v is None:
        return '–'
    try:
        d = Decimal(str(v))
    except (ArithmeticError, ValueError):
        return '–'
    if d == 0:
        return '–'
    neg = d < 0
    a = abs(d)
    for threshold, suffix, divisor in ((Decimal(1000000), 'M', Decimal(1000000)), (Decimal(1000), 'k', Decimal(1000))):
        if a >= threshold:
            q = (a / divisor).quantize(Decimal('0.1'))
            s = format(q.normalize(), 'f').rstrip('0').rstrip('.')
            return f'-{s}{suffix}' if neg else f'{s}{suffix}'
    s = format(d.normalize(), 'f')
    if '.' in s:
        s = s.rstrip('0').rstrip('.')
    return s


def highlight_day(expense_total: Decimal | float | None, stats: dict, is_today: bool) -> str:
    if is_today:
        return 'today'
    e = float(expense_total or 0)
    mean_d, med_d = stats.get('mean_daily', 0) or 0, stats.get('median_daily', 0) or 0
    if mean_d > 0 and e > 5 * mean_d:
        return 'hot'
    if e > 0 and med_d > 0 and e < 0.8 * med_d:
        return 'cold'
    return ''


def highlight_month(expense_total: Decimal | float | None, stats: dict, is_this_month: bool) -> str:
    if is_this_month:
        return 'today'
    e = float(expense_total or 0)
    mean_m, med_m = stats.get('mean_monthly', 0) or 0, stats.get('median_monthly', 0) or 0
    if mean_m > 0 and e > 5 * mean_m:
        return 'hot'
    if e > 0 and med_m > 0 and e < 0.8 * med_m:
        return 'cold'
    return ''

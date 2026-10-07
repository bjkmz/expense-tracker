"""Plotly chart HTML with check-then-build disk cache.

- Gating query is a single indexed MAX(updated_at) over the chart's own
  month/year range (~1ms) vs Pandas+Plotly build (~50-200ms).
- Cached files: tmp/charts/<scope>_<period>_<line|pie>.html + .meta.json
- plotly.js loads once via CDN in base.html; fragments use include_plotlyjs=False,
  staticPlot, transparent backgrounds, flat 2D per outline.
"""
from __future__ import annotations

import calendar as cal_module
from datetime import date

from django.conf import settings
from django.db.models import Max

from tracker.services.cache import chart_paths, is_fresh, read_chart, write_chart

PIE_COLORS = {
    'Food': '#FCA5A5',
    'Transpo': '#93C5FD',
    'Consumable': '#86EFAC',
    'Ownership': '#C4B5FD',
    'Miscellaneous': '#FCD34D',
}
LINE_COLOR = '#60A5FA'


def _range_for(scope: str, period: str) -> tuple[date, date]:
    if scope == 'month':
        y = int(period.split('-')[0])
        return date(y, 1, 1), date(y, 12, 31)
    y, m, _ = map(int, period.split('-'))
    last = cal_module.monthrange(y, m)[1]
    return date(y, m, 1), date(y, m, last)


def scope_max_iso(scope: str, period: str) -> str | None:
    from tracker.models import Expense

    start, end = _range_for(scope, period)
    m = Expense.objects.filter(date__gte=start, date__lte=end).aggregate(m=Max('updated_at'))['m']
    return m.isoformat() if m else None


def get_chart_html(scope: str, period: str, kind: str = 'line') -> tuple[str, bool]:
    """Return (html, from_cache). Builds on miss."""
    if kind not in ('line', 'pie'):
        kind = 'line'
    html_path, meta_path = chart_paths(settings.CHART_CACHE_DIR, scope, period, kind)
    db_max = scope_max_iso(scope, period)
    if html_path.exists() and is_fresh(meta_path, db_max):
        try:
            return read_chart(html_path), True
        except OSError:
            pass
    html = build_chart_html(scope, period, kind)
    write_chart(html_path, meta_path, html, db_max)
    return html, False


def build_chart_html(scope: str, period: str, kind: str = 'line') -> str:
    from tracker.services.insights import month_context, year_context

    ctx = month_context(period) if scope == 'day' else year_context(period)
    if kind == 'pie':
        return _pie_html(ctx)
    return _line_html(ctx)


def _fig_to_div(fig) -> str:
    from plotly.offline import plot

    return plot(fig, output_type='div', include_plotlyjs=False,
                config={'staticPlot': True, 'displayModeBar': False})


def _line_html(ctx: dict) -> str:
    import plotly.graph_objects as go

    series = ctx.get('series', [])
    if ctx.get('kind') == 'year':
        x = [p['label'] for p in series]
        title = f"Monthly Expenses — {ctx['label']}"
    else:
        x = [p['x'] for p in series]
        title = f"Daily Expenses — {ctx['label']}"
    y = [p['y'] for p in series]
    if not any(y):
        return '<div class="p-6 text-center text-sm text-neutral-500">No expense data yet.</div>'
    fig = go.Figure(go.Scatter(x=x, y=y, mode='lines', line=dict(color=LINE_COLOR, width=2)))
    fig.update_layout(
        title=dict(text=title, font=dict(size=13)),
        margin=dict(l=40, r=10, t=40, b=30),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        xaxis=dict(showgrid=False), yaxis=dict(showgrid=True, gridcolor='#E5E7EB'),
        showlegend=False,
    )
    return _fig_to_div(fig)


def _pie_html(ctx: dict) -> str:
    import plotly.graph_objects as go

    pie = ctx.get('pie', [])
    if not pie:
        return '<div class="p-6 text-center text-sm text-neutral-500">No expense data yet.</div>'
    labels = [p['label'] for p in pie]
    values = [p['value'] for p in pie]
    colors = [PIE_COLORS.get(lb, '#D1D5DB') for lb in labels]
    title = f"Year Categories Division — {ctx['label']}" if ctx.get('kind') == 'year' else f"Month Categories Division — {ctx['label']}"
    fig = go.Figure(go.Pie(labels=labels, values=values, hole=0, marker=dict(colors=colors),
                           textinfo='label+percent', sort=False))
    fig.update_layout(
        title=dict(text=title, font=dict(size=13)),
        margin=dict(l=10, r=10, t=40, b=10),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        showlegend=False,
    )
    return _fig_to_div(fig)

import calendar as cal_module
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.db.models import DecimalField, Sum
from django.db.models import Case, When
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from tracker.services.heatmap import compact_amount, get_heatmap_stats, highlight_day, highlight_month
from tracker.services.records import day_panel_data, month_panel_data


def home(request):
    from tracker.models import Category

    today = timezone.localdate()
    return render(
        request,
        'home.html',
        {
            'today': today,
            'today_iso': today.isoformat(),
            'default_ym': today.strftime('%Y-%m'),
            'default_y': today.year,
            'categories': list(Category.objects.order_by('name')),
        },
    )


def calendar_day_stub(request):
    # Kept for backwards compat; P2 uses calendar_day.
    return calendar_day(request)


def _parse_ym(raw: str | None, today: date) -> tuple[int, int]:
    try:
        y_str, m_str = (raw or '').split('-')
        y, m = int(y_str), int(m_str)
        if 1 <= m <= 12 and 1900 <= y <= 2100:
            return y, m
    except (ValueError, AttributeError):
        pass
    return today.year, today.month


def calendar_day(request):
    today = timezone.localdate()
    y, m = _parse_ym(request.GET.get('ym'), today)
    ym = f'{y:04d}-{m:02d}'
    # prev/next via month arithmetic
    if m == 1:
        prev_ym = f'{y - 1:04d}-12'
    else:
        prev_ym = f'{y:04d}-{m - 1:02d}'
    if m == 12:
        next_ym = f'{y + 1:04d}-01'
    else:
        next_ym = f'{y:04d}-{m + 1:02d}'

    from tracker.models import Expense

    per_day = (
        Expense.objects.filter(date__year=y, date__month=m)
        .values('date')
        .annotate(
            income=Sum(Case(When(category__name='Income', then='amount'), output_field=DecimalField())),
            expense=Sum(
                Case(When(category__name='Income', then=None), default='amount', output_field=DecimalField())
            ),
        )
    )
    by_date = {r['date'].isoformat(): r for r in per_day}
    stats = get_heatmap_stats()
    first_weekday, num_days = cal_module.monthrange(y, m)

    cells = []
    # Sunday-start alignment: leading blanks so day 1 lands under correct weekday.
    leading = (first_weekday + 1) % 7
    for _ in range(leading):
        cells.append(None)
    for d in range(1, num_days + 1):
        d_iso = f'{y:04d}-{m:02d}-{d:02d}'
        r = by_date.get(d_iso, {})
        income, expense = r.get('income'), r.get('expense')
        cells.append(
            {
                'day': d,
                'iso': d_iso,
                'income': income,
                'expense': expense,
                'income_s': compact_amount(income),
                'expense_s': compact_amount(expense),
                'flag': highlight_day(expense, stats, is_today=(d_iso == today.isoformat())),
            }
        )
    # pad to full weeks (Sunday-start 7-col calendar grid)
    while len(cells) % 7:
        cells.append(None)

    ctx = {
        'ym': ym,
        'ym_label': date(y, m, 1).strftime('%B %Y'),
        'prev_ym': prev_ym,
        'next_ym': next_ym,
        'cells': cells,
    }
    if request.headers.get('HX-Request'):
        return render(request, 'partials/calendar_day.html', ctx)
    return render(request, 'partials/calendar_day.html', ctx)


def calendar_month(request):
    today = timezone.localdate()
    try:
        y = int(request.GET.get('y', today.year))
        assert 1900 <= y <= 2100
    except (ValueError, AssertionError, TypeError):
        y = today.year

    from tracker.models import Expense

    per_month = (
        Expense.objects.filter(date__year=y)
        .values('date__month')
        .annotate(
            income=Sum(Case(When(category__name='Income', then='amount'), output_field=DecimalField())),
            expense=Sum(
                Case(When(category__name='Income', then=None), default='amount', output_field=DecimalField())
            ),
        )
    )
    by_m = {r['date__month']: r for r in per_month}
    stats = get_heatmap_stats()
    this_ym = today.strftime('%Y-%m')

    cells = []
    for mo in range(1, 13):
        r = by_m.get(mo, {})
        income, expense = r.get('income'), r.get('expense')
        ym = f'{y:04d}-{mo:02d}'
        cells.append(
            {
                'month': mo,
                'name': date(y, mo, 1).strftime('%b').upper(),
                'ym': ym,
                'income': income,
                'expense': expense,
                'income_s': compact_amount(income),
                'expense_s': compact_amount(expense),
                'flag': highlight_month(expense, stats, is_this_month=(ym == this_ym)),
            }
        )

    ctx = {'y': y, 'prev_y': y - 1, 'next_y': y + 1, 'cells': cells}
    return render(request, 'partials/calendar_month.html', ctx)


def _parse_iso_day(raw: str | None, fallback: date) -> date:
    try:
        y, m, d = map(int, (raw or '').split('-'))
        return date(y, m, d)
    except (ValueError, AttributeError):
        return fallback


def _panel_for(scope: str, period: str, today: date, error: str = '') -> dict:
    """Build full panel context (summary + list + nav) for day or month scope."""
    if scope == 'month':
        y, m = _parse_ym(period if '-' in (period or '') and len(period) == 7 else None, today)
        # _parse_ym expects YYYY-MM; period here is YYYY-MM
        try:
            yy, mm = map(int, period.split('-'))
            y, m = yy, mm
            assert 1 <= m <= 12
        except (ValueError, AttributeError, AssertionError):
            pass
        data = month_panel_data(y, m)
        cur = date(y, m, 1)
        prev_ym = f'{(cur - timedelta(days=1)).strftime("%Y-%m")}'
        # next month: add 32 days then truncate
        nxt = (cur + timedelta(days=32)).replace(day=1)
        next_ym = nxt.strftime('%Y-%m')
        data.update({
            'head_label': cur.strftime('%B %Y'),
            'prev_url': f'/month/{prev_ym}/',
            'next_url': f'/month/{next_ym}/',
            'jump_value': f'{y:04d}-{m:02d}',
            'jump_type': 'month',
            'add_date_value': period if period != today.strftime('%Y-%m') else today.isoformat(),
            'show_date_input': True,
            'error': error,
        })
        return data
    day = _parse_iso_day(period, today)
    data = day_panel_data(day)
    data.update({
        'head_label': day.strftime('%B %d, %Y'),
        'prev_url': f'/day/{(day - timedelta(days=1)).isoformat()}/',
        'next_url': f'/day/{(day + timedelta(days=1)).isoformat()}/',
        'jump_value': day.isoformat(),
        'jump_type': 'date',
        'add_date_value': day.isoformat(),
        'show_date_input': False,
        'error': error,
    })
    return data


def _render_panel(request, scope: str, period: str, error: str = ''):
    today = timezone.localdate()
    ctx = _panel_for(scope, period, today, error=error)
    return render(request, 'partials/records_panel.html', ctx)


@require_GET
def records_panel_day(request):
    today = timezone.localdate()
    raw = request.GET.get('date') or today.isoformat()
    return _render_panel(request, 'day', _parse_iso_day(raw, today).isoformat())


@require_GET
def records_panel_month(request):
    today = timezone.localdate()
    raw = request.GET.get('ym') or today.strftime('%Y-%m')
    return _render_panel(request, 'month', raw)


def _clean_amount(raw) -> Decimal:
    try:
        v = Decimal(str(raw))
    except (InvalidOperation, TypeError):
        raise ValueError('Amount must be a number.')
    if v <= 0:
        raise ValueError('Amount must be above zero.')
    return v.quantize(Decimal('0.01'))


def _origin_scope_period(request) -> tuple[str, str]:
    today = timezone.localdate()
    scope = request.POST.get('scope') or request.GET.get('scope') or 'day'
    period = request.POST.get('period') or request.GET.get('period')
    if scope not in ('day', 'month'):
        scope = 'day'
    if not period:
        period = today.isoformat() if scope == 'day' else today.strftime('%Y-%m')
    return scope, period


@require_POST
def record_create(request):
    from django.http import HttpResponse

    from tracker.models import Category, Expense

    is_home_modal = request.POST.get('origin') == 'home-modal'
    is_hx = bool(request.headers.get('HX-Request'))
    scope, period = _origin_scope_period(request)
    item = (request.POST.get('item') or '').strip()
    cat_raw = (request.POST.get('category') or '').strip()
    date_raw = (request.POST.get('date') or '').strip() or period
    try:
        if not item:
            raise ValueError('Item name is required.')
        amount = _clean_amount(request.POST.get('amount'))
        try:
            day = date.fromisoformat(date_raw[:10])
        except ValueError:
            raise ValueError('Invalid date.')
        try:
            cat = Category.objects.get(pk=int(cat_raw))
        except (ValueError, Category.DoesNotExist):
            cat = Category.objects.filter(name__iexact=cat_raw).first()
            if not cat:
                raise ValueError('Pick a valid category.')
        Expense.objects.create(item=item, category=cat, amount=amount, date=day)
    except ValueError as e:
        if is_home_modal and is_hx:
            return HttpResponse(str(e), content_type='text/html')
        if is_hx:
            return _render_panel(request, scope, period, error=str(e))
        return HttpResponseBadRequest(str(e))
    from tracker.services.cache import invalidate_caches

    invalidate_caches()
    if is_home_modal and is_hx:
        return HttpResponse('', headers={'HX-Trigger': 'record-created'})
    if is_hx:
        return _render_panel(request, scope, period)
    return redirect(f'/day/{date_raw[:10]}/')


@require_POST
def record_update(request, pk):
    from tracker.models import Category, Expense

    scope, period = _origin_scope_period(request)
    exp = get_object_or_404(Expense, pk=pk)
    try:
        changed = False
        if 'item' in request.POST:
            item = request.POST.get('item', '').strip()
            if not item:
                raise ValueError('Item name is required.')
            exp.item = item
            changed = True
        if 'category' in request.POST and request.POST.get('category') != '':
            cat_raw = request.POST.get('category')
            try:
                exp.category = Category.objects.get(pk=int(cat_raw))
            except (ValueError, Category.DoesNotExist):
                raise ValueError('Pick a valid category.')
            changed = True
        if 'amount' in request.POST and request.POST.get('amount') != '':
            exp.amount = _clean_amount(request.POST.get('amount'))
            changed = True
        if changed:
            exp.save()
    except ValueError as e:
        if request.headers.get('HX-Request'):
            return _render_panel(request, scope, period, error=str(e))
        return HttpResponseBadRequest(str(e))
    if changed:
        from tracker.services.cache import invalidate_caches

        invalidate_caches()
    if request.headers.get('HX-Request'):
        return _render_panel(request, scope, period)
    return redirect(f'/day/{exp.date.isoformat()}/')


@require_POST
def record_move(request, pk):
    from tracker.models import Expense

    scope, period = _origin_scope_period(request)
    exp = get_object_or_404(Expense, pk=pk)
    try:
        new_date = date.fromisoformat((request.POST.get('new_date') or '').strip()[:10])
    except ValueError:
        err = 'Pick a valid new date.'
        if request.headers.get('HX-Request'):
            return _render_panel(request, scope, period, error=err)
        return HttpResponseBadRequest(err)
    exp.date = new_date
    exp.save()
    from tracker.services.cache import invalidate_caches

    invalidate_caches()
    if request.headers.get('HX-Request'):
        return _render_panel(request, scope, period)
    return redirect(f'/day/{new_date.isoformat()}/')


@require_POST
def record_delete(request, pk):
    from tracker.models import Expense

    scope, period = _origin_scope_period(request)
    exp = get_object_or_404(Expense, pk=pk)
    exp.delete()
    from tracker.services.cache import invalidate_caches

    invalidate_caches()
    if request.headers.get('HX-Request'):
        return _render_panel(request, scope, period)
    return redirect('/')


def _insights_ctx(scope: str, period: str, chart_type: str = 'line', sort: str = 'expense_desc') -> dict:
    from tracker.services.charts import get_chart_html
    from tracker.services.insights import insights_for

    if chart_type not in ('line', 'pie'):
        chart_type = 'line'
    ins = insights_for(scope, period, sort)
    chart_html, from_cache = get_chart_html(scope, period, chart_type)
    flipped = 'pie' if chart_type == 'line' else 'line'
    # tab links: day tab -> day page for same date (or first of month), month tab -> month page
    if scope == 'day':
        day_url = f'/day/{period}/'
        month_url = f'/month/{period[:7]}/'
    else:
        day_url = f'/day/{period}-01/'
        month_url = f'/month/{period}/'
    return {
        'ins_scope': scope,
        'ins_period': period,
        'ins': ins,
        'chart_type': chart_type,
        'chart_flipped': flipped,
        'chart_html': chart_html,
        'chart_cached': from_cache,
        'day_url': day_url,
        'month_url': month_url,
    }


@require_GET
def insights_chart(request):
    scope = request.GET.get('scope', 'day')
    period = request.GET.get('period', '')
    kind = request.GET.get('type', 'line')
    if scope not in ('day', 'month'):
        scope = 'day'
    if not period:
        today = timezone.localdate()
        period = today.isoformat() if scope == 'day' else today.strftime('%Y-%m')
    from tracker.services.charts import get_chart_html

    html, _ = get_chart_html(scope, period, kind)
    return render(request, 'partials/insights_chart.html', {'chart_html': html})


@require_GET
def insights_list(request):
    from tracker.services.insights import SORTS, list_rows

    scope = request.GET.get('scope', 'day')
    period = request.GET.get('period', '')
    sort = request.GET.get('sort', 'expense_desc')
    if scope not in ('day', 'month'):
        scope = 'day'
    if sort not in SORTS:
        sort = 'expense_desc'
    if not period:
        today = timezone.localdate()
        period = today.isoformat() if scope == 'day' else today.strftime('%Y-%m')
    rows = list_rows(scope, period, sort)
    return render(request, 'partials/insights_list.html', {'rows': rows, 'ins_scope': scope})


def day_detail(request, iso):
    today = timezone.localdate()
    day = _parse_iso_day(iso, today)
    ctx = _panel_for('day', day.isoformat(), today)
    chart_type = request.GET.get('chart', 'line')
    sort = request.GET.get('sort', 'expense_desc')
    ctx.update(_insights_ctx('day', day.isoformat(), chart_type, sort))
    ctx.update({
        'today': today,
        'default_ym': day.strftime('%Y-%m'),
        'default_y': day.year,
        'page_scope': 'day',
        'page_period': day.isoformat(),
    })
    return render(request, 'records_page.html', ctx)


def month_detail(request, ym):
    today = timezone.localdate()
    ctx = _panel_for('month', ym, today)
    try:
        yy, mm = map(int, ym.split('-'))
        cal_ym = f'{yy:04d}-{mm:02d}'
    except (ValueError, AttributeError):
        yy, mm = today.year, today.month
        cal_ym = today.strftime('%Y-%m')
    chart_type = request.GET.get('chart', 'line')
    sort = request.GET.get('sort', 'expense_desc')
    ctx.update(_insights_ctx('month', ym, chart_type, sort))
    ctx.update({
        'today': today,
        'default_ym': cal_ym,
        'default_y': yy,
        'page_scope': 'month',
        'page_period': ym,
    })
    return render(request, 'records_page.html', ctx)

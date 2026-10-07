from django.conf import settings
from django.core.management import call_command
from django.db import IntegrityError
from django.db.models import Max, Sum
from django.test import TestCase, override_settings

from tracker.models import Category, Expense


class CategorySeedTests(TestCase):
    def test_seed_migration_categories(self):
        names = set(Category.objects.values_list('name', flat=True))
        self.assertEqual(
            names, {'Income', 'Transpo', 'Food', 'Consumable', 'Ownership', 'Miscellaneous'}
        )

    def test_category_name_unique(self):
        with self.assertRaises(IntegrityError):
            Category.objects.create(name='Food')


class ExpenseModelTests(TestCase):
    def setUp(self):
        self.food = Category.objects.get(name='Food')
        self.income = Category.objects.get(name='Income')

    def test_create_and_max_updated_at_gate(self):
        # MAX(updated_at) gate used by chart/heatmap cache: no full scan needed
        e = Expense.objects.create(item='Rice', category=self.food, amount='55.50', date='2026-04-01')
        self.assertIsNotNone(e.updated_at)
        db_max = Expense.objects.aggregate(m=Max('updated_at'))['m']
        self.assertEqual(db_max, e.updated_at)

    def test_income_excluded_from_expense_sums(self):
        Expense.objects.create(item='Rice', category=self.food, amount='10.00', date='2026-04-01')
        Expense.objects.create(item='Bonus', category=self.income, amount='999.00', date='2026-04-01')
        total = Expense.objects.filter(date='2026-04-01').exclude(category__name='Income').aggregate(
            s=Sum('amount')
        )['s']
        self.assertEqual(float(total), 10.00)


class SeedDemoTests(TestCase):
    def test_seed_demo_anchors(self):
        call_command('seed_demo', '--clear')
        self.assertGreater(Expense.objects.count(), 800)
        self.assertEqual(Expense.objects.filter(item='Rice', date__year=2026, date__month=4).count(), 12)
        self.assertEqual(
            Expense.objects.filter(
                item='Jeepney Home-Office', date__year=2026, date__month=4
            ).count(),
            20,  # April has no baseline rows; Top loop only
        )
        # April 2026 must dominate: red month (>5x mean monthly expense)
        from collections import defaultdict

        monthly: dict[str, float] = defaultdict(float)
        for r in Expense.objects.exclude(category__name='Income').values('amount', 'date'):
            monthly[str(r['date'])[:7]] += float(r['amount'])
        vals = [v for v in monthly.values() if v > 0]
        mean_m = sum(vals) / len(vals)
        self.assertGreater(monthly['2026-04'], 5 * mean_m)


@override_settings(
    HEATMAP_STATS_PATH=settings.BASE_DIR / 'tmp' / 'test_heatmap_stats.json',
    CHART_CACHE_DIR=settings.BASE_DIR / 'tmp' / 'test_charts_cal',
)
class CalendarHeatmapTests(TestCase):
    def setUp(self):
        call_command('seed_demo', '--clear')

    def test_highlight_helpers(self):
        from tracker.services.heatmap import highlight_day, highlight_month

        stats = {'mean_daily': 100.0, 'median_daily': 100.0, 'mean_monthly': 3000.0, 'median_monthly': 3000.0}
        self.assertEqual(highlight_day(600, stats, False), 'hot')
        self.assertEqual(highlight_day(50, stats, False), 'cold')
        self.assertEqual(highlight_day(100, stats, False), '')
        self.assertEqual(highlight_day(9999, stats, True), 'today')
        self.assertEqual(highlight_month(20000, stats, False), 'hot')
        self.assertEqual(highlight_month(1000, stats, False), 'cold')
        self.assertEqual(highlight_month(9999, stats, True), 'today')

    def test_stats_cache_fresh(self):
        from tracker.services.heatmap import get_heatmap_stats

        s1 = get_heatmap_stats()
        s2 = get_heatmap_stats()
        self.assertEqual(s1, s2)
        self.assertGreater(s1['mean_daily'], 0)

    def test_day_partial_april_highlights(self):
        r = self.client.get('/partials/calendar/day/', {'ym': '2026-04'})
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('/day/2026-04-15/', body)  # spike day link
        self.assertIn('bg-red-300', body)  # Apr 15 hot
        self.assertIn('bg-blue-200', body)  # Apr 23/24/27/28 cold
        self.assertIn('?ym=2026-03', body)
        self.assertIn('?ym=2026-05', body)

    def test_day_partial_invalid_ym_falls_back(self):
        r = self.client.get('/partials/calendar/day/', {'ym': 'nope'})
        self.assertEqual(r.status_code, 200)

    def test_month_partial_2026_highlights(self):
        r = self.client.get('/partials/calendar/month/', {'y': '2026'})
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('/month/2026-04/', body)
        self.assertIn('bg-red-300', body)  # April hot month
        self.assertIn('?y=2025', body)
        self.assertIn('?y=2027', body)

    def test_detail_stubs(self):
        self.assertEqual(self.client.get('/day/2026-04-15/').status_code, 200)
        self.assertEqual(self.client.get('/month/2026-04/').status_code, 200)


@override_settings(
    HEATMAP_STATS_PATH=settings.BASE_DIR / 'tmp' / 'test_heatmap_stats.json',
    CHART_CACHE_DIR=settings.BASE_DIR / 'tmp' / 'test_charts_records',
)
class RecordsPanelTests(TestCase):
    def setUp(self):
        call_command('seed_demo', '--clear')
        self.food = Category.objects.get(name='Food')

    def _hx(self, **kw):
        kw.setdefault('HTTP_HX_REQUEST', 'true')
        return kw

    def test_day_page_renders_summary_and_nav(self):
        r = self.client.get('/day/2026-04-15/')
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('SUMMARY', body)
        self.assertIn('Cabinet', body)
        self.assertIn('/day/2026-04-14/', body)
        self.assertIn('/day/2026-04-16/', body)
        self.assertIn('type="date"', body)
        # per-category totals present, 0.00 default exists somewhere
        self.assertIn('Income:', body)

    def test_month_page_renders(self):
        r = self.client.get('/month/2026-04/')
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('April 2026', body)
        self.assertIn('SUMMARY', body)
        # jump pickers live in the calendar headers only, not the records head
        self.assertNotIn('type="month"', body)

    def test_calendar_partials_carry_icon_jump_pickers(self):
        day = self.client.get('/partials/calendar/day/', {'ym': '2026-04'}).content.decode()
        self.assertIn('type="date"', day)
        self.assertIn('jumpCalDay', day)
        month = self.client.get('/partials/calendar/month/', {'y': '2026'}).content.decode()
        self.assertIn('type="month"', month)
        self.assertIn('jumpCalMonth', month)

    def test_jump_targets_detail_pages(self):
        # jump navigates like a cell click: day page bundles records=date +
        # insights=month; month page bundles records=month + insights=year
        body = self.client.get('/day/2026-04-15/').content.decode()
        self.assertIn('April 15, 2026', body)
        self.assertIn('Daily rows in April 2026', body)
        body = self.client.get('/month/2026-04/').content.decode()
        self.assertIn('April 2026', body)
        self.assertIn('Monthly rows in 2026', body)

    def test_data_pages_use_fraction_columns_no_vw_overflow(self):
        # 25+25+50vw columns sum to 100vw which overflows by scrollbar width;
        # fractions of the flex parent fit exactly, root clips any remainder
        for url in ('/day/2026-04-15/', '/month/2026-04/'):
            body = self.client.get(url).content.decode()
            self.assertNotIn('w-[25vw]', body)
            self.assertNotIn('w-[50vw]', body)
            self.assertIn('lg:w-1/4', body)
            self.assertIn('lg:w-1/2', body)
            self.assertIn('overflow-x-clip', body)

    def test_records_column_runs_slate_to_bottom(self):
        # Middle column carries bg-slate-900 + flex-col and the panel claims
        # it via flex-1, so the dark field reaches page bottom on short lists
        for url in ('/day/2026-04-15/', '/month/2026-04/'):
            body = self.client.get(url).content.decode()
            self.assertIn('lg:w-1/4 bg-slate-900 flex flex-col', body)
            self.assertIn('flex flex-col flex-1 min-h-[60vh]', body)

    def test_insights_graph_is_sticky_half_viewport(self):
        for url in ('/day/2026-04-15/', '/month/2026-04/'):
            body = self.client.get(url).content.decode()
            self.assertIn('sticky top-1', body)
            self.assertIn('h-[50vh]', body)
            self.assertIn('insights-chart-box', body)
            self.assertIn('fitInsightCharts', body)

    def test_create_update_move_delete_roundtrip(self):
        # create
        r = self.client.post(
            '/records/',
            {'item': 'Test Bun', 'category': str(self.food.id), 'amount': '12.50',
             'date': '2026-04-01', 'scope': 'day', 'period': '2026-04-01'},
            **self._hx(),
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn('Test Bun', r.content.decode())
        e = Expense.objects.get(item='Test Bun')
        # update
        r = self.client.post(
            f'/records/{e.id}/',
            {'item': 'Test Bun 2', 'category': str(self.food.id), 'amount': '13.00',
             'scope': 'day', 'period': '2026-04-01'},
            **self._hx(),
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn('Test Bun 2', r.content.decode())
        # move
        r = self.client.post(
            f'/records/{e.id}/move/',
            {'new_date': '2026-04-02', 'scope': 'day', 'period': '2026-04-01'},
            **self._hx(),
        )
        self.assertEqual(r.status_code, 200)
        e.refresh_from_db()
        self.assertEqual(str(e.date), '2026-04-02')
        # delete
        r = self.client.post(
            f'/records/{e.id}/delete/',
            {'scope': 'day', 'period': '2026-04-02'},
            **self._hx(),
        )
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Expense.objects.filter(pk=e.id).exists())

    def test_create_validation_error_stays_in_panel(self):
        r = self.client.post(
            '/records/',
            {'item': '', 'category': str(self.food.id), 'amount': '5',
             'date': '2026-04-01', 'scope': 'day', 'period': '2026-04-01'},
            **self._hx(),
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn('Item name is required', r.content.decode())

    def test_create_bad_amount_rejected(self):
        r = self.client.post(
            '/records/',
            {'item': 'X', 'category': str(self.food.id), 'amount': '-3',
             'date': '2026-04-01', 'scope': 'day', 'period': '2026-04-01'},
            **self._hx(),
        )
        self.assertIn('above zero', r.content.decode())

    def test_panel_partials(self):
        self.assertEqual(self.client.get('/partials/records/day/', {'date': '2026-04-15'}).status_code, 200)
        self.assertEqual(self.client.get('/partials/records/month/', {'ym': '2026-04'}).status_code, 200)


@override_settings(
    HEATMAP_STATS_PATH=settings.BASE_DIR / 'tmp' / 'test_heatmap_stats.json',
    CHART_CACHE_DIR=settings.BASE_DIR / 'tmp' / 'test_charts_insights',
)
class InsightsPanelTests(TestCase):
    def setUp(self):
        call_command('seed_demo', '--clear')

    def test_month_cards_match_seed_anchors(self):
        from tracker.services.insights import insights_for

        ins = insights_for('day', '2026-04-15')
        self.assertEqual(ins['cards']['top_food'], {'item': 'Rice', 'count': 12})
        self.assertEqual(ins['cards']['top_transpo']['count'], 20)
        self.assertEqual(float(ins['cards']['highest_income']['amount']), 99999.99)
        self.assertEqual(str(ins['cards']['highest_income']['when']), '2026-04-03')
        self.assertIsNotNone(ins['cards']['costly_consumable'])
        self.assertIsNotNone(ins['cards']['costly_ownership'])
        self.assertIsNotNone(ins['cards']['costly_misc'])
        self.assertGreater(float(ins['totals']['Ownership']), 20000)

    def test_year_scope_month_labels(self):
        from tracker.services.insights import insights_for

        ins = insights_for('month', '2026-04')
        self.assertEqual(ins['kind'], 'year')
        self.assertEqual(len(ins['series']), 12)
        self.assertEqual(str(ins['cards']['highest_income']['when']), '2026-04-03')

    def test_list_sort_orders(self):
        from tracker.services.insights import list_rows

        desc = list_rows('day', '2026-04-15', 'expense_desc')
        asc = list_rows('day', '2026-04-15', 'expense_asc')
        self.assertGreaterEqual(desc[0]['expense'], desc[-1]['expense'])
        self.assertLessEqual(asc[0]['expense'], asc[-1]['expense'])
        self.assertEqual(desc[0]['label'], '15')  # spike day first
        inc_d = list_rows('day', '2026-04-15', 'income_desc')
        self.assertEqual(inc_d[0]['label'], '3')  # bonus day first

    def test_chart_cache_roundtrip_and_invalidation(self):
        import re

        from tracker.services.charts import get_chart_html

        norm = lambda h: re.sub(
            r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', 'UID', h
        )

        h1, c1 = get_chart_html('day', '2026-04-10', 'line')
        self.assertIn('plotly', h1.lower())
        h2, c2 = get_chart_html('day', '2026-04-10', 'line')
        self.assertTrue(c2)
        self.assertEqual(norm(h1), norm(h2))
        food = Category.objects.get(name='Food')
        e = Expense.objects.create(item='CacheBuster', category=food, amount='9.99', date='2026-04-10')
        h3, c3 = get_chart_html('day', '2026-04-10', 'line')
        self.assertFalse(c3)
        self.assertNotEqual(h1, h3)
        e.delete()
        from tracker.services.cache import invalidate_caches

        invalidate_caches()  # deletes retreat MAX; explicit clear is the documented path
        h4, c4 = get_chart_html('day', '2026-04-10', 'line')
        self.assertFalse(c4)
        self.assertEqual(norm(h1), norm(h4))

    def test_write_invalidates_charts(self):
        food = Category.objects.get(name='Food')
        self.client.get('/day/2026-04-10/')  # builds chart in test cache dir
        r = self.client.post(
            '/records/',
            {'item': 'Buster2', 'category': str(food.id), 'amount': '7.00',
             'date': '2026-04-10', 'scope': 'day', 'period': '2026-04-10'},
            HTTP_HX_REQUEST='true',
        )
        self.assertEqual(r.status_code, 200)
        from pathlib import Path

        leftovers = list((settings.BASE_DIR / 'tmp' / 'test_charts_insights').glob('*.html'))
        self.assertEqual(leftovers, [])

    def test_day_page_has_insights(self):
        r = self.client.get('/day/2026-04-15/')
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('insights-panel', body)
        self.assertIn('Highest Income', body)
        self.assertIn('99999.99', body)
        self.assertIn('Rice', body)
        self.assertIn('insights-chart', body)
        self.assertIn('insights-list', body)

    def test_month_page_has_year_insights(self):
        r = self.client.get('/month/2026-04/')
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('insights-panel', body)
        self.assertIn('Monthly Expenses', body)

    def test_chart_and_list_partials(self):
        pie = self.client.get('/partials/insights/chart/', {'scope': 'day', 'period': '2026-04-15', 'type': 'pie'})
        self.assertEqual(pie.status_code, 200)
        pie_body = pie.content.decode()
        self.assertIn('insights-chart-box', pie_body)
        self.assertNotIn('{#', pie_body)
        self.assertIn('type=line', pie_body)
        line = self.client.get('/partials/insights/chart/', {'scope': 'day', 'period': '2026-04-15', 'type': 'line'})
        line_body = line.content.decode()
        self.assertIn('type=pie', line_body)
        bogus = self.client.get('/partials/insights/chart/', {'scope': 'day', 'period': '2026-04-15', 'type': 'nope'})
        self.assertIn('type=pie', bogus.content.decode())
        r = self.client.get('/partials/insights/list/', {'scope': 'day', 'period': '2026-04-15', 'sort': 'income_desc'})
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        # highest-income day (3rd) before spike day (15th) when sorting by income desc
        self.assertLess(body.index('>3<'), body.index('>15<'))


@override_settings(
    HEATMAP_STATS_PATH=settings.BASE_DIR / 'tmp' / 'test_heatmap_stats.json',
    CHART_CACHE_DIR=settings.BASE_DIR / 'tmp' / 'test_charts_modal',
)
class HomeModalTests(TestCase):
    def setUp(self):
        call_command('seed_demo', '--clear')
        self.food = Category.objects.get(name='Food')

    def _hx(self, **kw):
        kw.setdefault('HTTP_HX_REQUEST', 'true')
        return kw

    def test_home_has_modal_with_today_and_categories(self):
        from django.utils import timezone

        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        today_iso = timezone.localdate().isoformat()
        self.assertIn('add-modal', body)
        self.assertIn('add-form', body)
        self.assertIn('home-toast', body)
        self.assertIn('showModal', body)
        self.assertIn(f'value="{today_iso}"', body)
        self.assertIn('record-created', body)  # refresh listener present
        for name in ('Food', 'Income', 'Transpo'):
            self.assertIn(name, body)

    def test_modal_hx_create_returns_trigger_and_row(self):
        from django.utils import timezone

        today_iso = timezone.localdate().isoformat()
        r = self.client.post(
            '/records/',
            {'item': 'Modal Bun', 'category': str(self.food.id), 'amount': '9.25',
             'date': today_iso, 'origin': 'home-modal'},
            **self._hx(),
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn('record-created', r.headers.get('HX-Trigger', ''))
        self.assertEqual(r.content.decode(), '')
        e = Expense.objects.get(item='Modal Bun')
        self.assertEqual(str(e.date), today_iso)

    def test_modal_hx_validation_error_stays_in_modal(self):
        r = self.client.post(
            '/records/',
            {'item': '', 'category': str(self.food.id), 'amount': '5',
             'date': '2026-04-01', 'origin': 'home-modal'},
            **self._hx(),
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn('Item name is required', r.content.decode())
        self.assertNotIn('record-created', r.headers.get('HX-Trigger', ''))

    def test_modal_hx_bad_amount(self):
        r = self.client.post(
            '/records/',
            {'item': 'X', 'category': str(self.food.id), 'amount': '-3',
             'date': '2026-04-01', 'origin': 'home-modal'},
            **self._hx(),
        )
        self.assertIn('above zero', r.content.decode())

    def test_modal_non_hx_falls_back_to_day_redirect(self):
        from django.utils import timezone

        today_iso = timezone.localdate().isoformat()
        r = self.client.post(
            '/records/',
            {'item': 'Plain Bun', 'category': str(self.food.id), 'amount': '4.00',
             'date': today_iso, 'origin': 'home-modal'},
        )
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r['Location'].endswith(f'/day/{today_iso}/'))

    def test_records_panel_create_unaffected_by_modal_branch(self):
        r = self.client.post(
            '/records/',
            {'item': 'Panel Bun', 'category': str(self.food.id), 'amount': '3.00',
             'date': '2026-04-01', 'scope': 'day', 'period': '2026-04-01'},
            **self._hx(),
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn('Panel Bun', r.content.decode())
        self.assertNotIn('record-created', r.headers.get('HX-Trigger', ''))

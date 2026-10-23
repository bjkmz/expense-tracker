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
    @classmethod
    def setUpTestData(cls):
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

    def test_calendar_partials_include_legend(self):
        for url, params in (
            ('/partials/calendar/day/', {'ym': '2026-04'}),
            ('/partials/calendar/month/', {'y': '2026'}),
        ):
            body = self.client.get(url, params).content.decode()
            for label in ('Current Day / Month', 'Spike: E&gt;5× avg', 'Low: E&lt;80% median'):
                self.assertIn(label, body)
            for swatch in ('bg-green-300/70', 'bg-red-300/70', 'bg-blue-200/70'):
                self.assertIn(swatch, body)

    def test_active_day_cell_is_marked(self):
        r = self.client.get(
            '/partials/calendar/day/',
            {'ym': '2026-04'},
            HTTP_HX_CURRENT_URL='http://testserver/day/2026-04-15/',
        )
        body = r.content.decode()
        self.assertEqual(r.headers['Cache-Control'], 'no-store')
        self.assertEqual(body.count('aria-current="true"'), 1)
        cell = body[body.index('href="/day/2026-04-15/"'):]
        cell = cell[:cell.index('>')]
        self.assertIn('cal-active', cell)

    def test_active_month_cell_is_marked(self):
        r = self.client.get(
            '/partials/calendar/month/',
            {'y': '2026'},
            HTTP_HX_CURRENT_URL='http://testserver/month/2026-04/',
        )
        body = r.content.decode()
        self.assertEqual(r.headers['Cache-Control'], 'no-store')
        self.assertEqual(body.count('aria-current="true"'), 1)
        cell = body[body.index('href="/month/2026-04/"'):]
        cell = cell[:cell.index('>')]
        self.assertIn('cal-active', cell)

    def test_month_tab_marks_month_containing_active_day(self):
        body = self.client.get(
            '/partials/calendar/month/',
            {'y': '2026'},
            HTTP_HX_CURRENT_URL='http://testserver/day/2026-04-15/',
        ).content.decode()
        self.assertEqual(body.count('aria-current="true"'), 1)
        self.assertIn('href="/month/2026-04/"', body)

    def test_home_calendar_has_no_active_cell(self):
        body = self.client.get(
            '/partials/calendar/day/',
            {'ym': '2026-04'},
            HTTP_HX_CURRENT_URL='http://testserver/',
        ).content.decode()
        self.assertNotIn('aria-current="true"', body)

    def test_detail_stubs(self):
        self.assertEqual(self.client.get('/day/2026-04-15/').status_code, 200)
        self.assertEqual(self.client.get('/month/2026-04/').status_code, 200)


@override_settings(
    HEATMAP_STATS_PATH=settings.BASE_DIR / 'tmp' / 'test_heatmap_stats.json',
    CHART_CACHE_DIR=settings.BASE_DIR / 'tmp' / 'test_charts_records',
)
class RecordsPanelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_demo', '--clear')
        cls.food = Category.objects.get(name='Food')

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

    def test_month_page_side_calendar_opens_month_tab(self):
        body = self.client.get('/month/2026-04/').content.decode()
        self.assertIn(
            'class="flex-1 border rounded py-1 text-sm cal-tab-active" '
            'onclick="setCalTab(this)" hx-get="/partials/calendar/month/?y=2026"',
            body,
        )

    def test_day_page_side_calendar_opens_day_tab(self):
        body = self.client.get('/day/2026-04-15/').content.decode()
        self.assertIn(
            'class="flex-1 border rounded py-1 text-sm cal-tab-active" '
            'onclick="setCalTab(this)" hx-get="/partials/calendar/day/?ym=2026-04"',
            body,
        )

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
            self.assertIn('text-xl font-bold', body)
            self.assertIn('banner banner-dim', body)

    def test_category_dropdown_follows_category_order(self):
        # Income first, then Food, Transpo, Consumable, Ownership, Miscellaneous
        want = ['Income', 'Food', 'Transpo', 'Consumable', 'Ownership', 'Miscellaneous']
        for url in ('/day/2026-04-15/', '/month/2026-04/'):
            body = self.client.get(url).content.decode()
            pos = [body.index(f'>{n}<') for n in want]
            self.assertEqual(pos, sorted(pos))
            self.assertRegex(body, r'<option[^>]*class="bg-slate-800 text-neutral-100"')

    def test_move_form_collapsed_behind_disclosure(self):
        # Row menu shows Move summary only; date picker + confirm spawn inside
        for url in ('/day/2026-04-15/', '/month/2026-04/'):
            body = self.client.get(url).content.decode()
            self.assertIn('title="Move to date">Move</summary>', body)
            self.assertIn('name="new_date"', body)
            self.assertIn('title="Confirm move"', body)
            self.assertIn('w-max min-w-20', body)
            self.assertNotIn('w-48', body)
            self.assertIn('absolute right-0 top-full', body)
            self.assertIn('grid-cols-[1fr_75px_60px_30px]', body)
            self.assertNotIn('1fr_110px_80px_36px', body)
        day_body = self.client.get('/day/2026-04-15/').content.decode()
        self.assertIn("#records-list details[open]", day_body)

    def test_month_rows_show_day_numbers_ascending(self):
        import re
        month_body = self.client.get('/month/2026-04/').content.decode()
        days = [int(n) for n in re.findall(r'record-day[^"]*">(\d+)<', month_body)]
        self.assertTrue(days)
        self.assertIn('record-day w-5 h-5 shrink-0 flex items-center justify-center', month_body)
        self.assertEqual(days, sorted(days))
        self.assertEqual(days[0], min(days))
        day_body = self.client.get('/day/2026-04-15/').content.decode()
        self.assertNotIn('record-day', day_body)

    def test_month_add_row_day_picker_locked_to_month(self):
        month_body = self.client.get('/month/2026-04/').content.decode()
        self.assertIn('grid-cols-[20px_1fr_75px_60px_30px]', month_body)
        self.assertNotIn('30px_1fr_75px_60px_30px', month_body)
        self.assertIn('min="2026-04-01"', month_body)
        self.assertIn('max="2026-04-30"', month_body)
        self.assertIn('setAddDay', month_body)
        self.assertIn('<span data-add-day', month_body)
        day_body = self.client.get('/day/2026-04-15/').content.decode()
        self.assertNotIn('<span data-add-day', day_body)
        self.assertNotIn('20px_1fr_75px_60px_30px', day_body)

    def test_insights_graph_is_sticky_half_viewport(self):
        for url in ('/day/2026-04-15/', '/month/2026-04/'):
            body = self.client.get(url).content.decode()
            self.assertIn('sticky top-1', body)
            self.assertIn('h-[50vh]', body)
            self.assertIn('insights-chart-box', body)
            self.assertIn('fitInsightCharts', body)

    def test_panels_have_independent_scroll_areas(self):
        # Page locks to viewport height on desktop; each column scrolls alone:
        # records rows scroll under fixed head/add-row, insights scroll under
        # the sticky chart card, calendar aside scrolls itself
        for url in ('/day/2026-04-15/', '/month/2026-04/'):
            body = self.client.get(url).content.decode()
            self.assertIn('lg:h-screen', body)
            self.assertIn('lg:overflow-hidden', body)
            self.assertIn('id="records-list" class="flex-1 min-h-0 lg:overflow-y-auto"', body)
            self.assertIn('lg:w-1/2 lg:h-screen lg:overflow-y-auto', body)

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
    @classmethod
    def setUpTestData(cls):
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

    def test_list_default_order_is_chronological(self):
        from tracker.services.insights import list_rows

        default = list_rows('day', '2026-04-15')
        keys = [r['key'] for r in default]
        self.assertEqual(keys, sorted(keys))
        desc = list_rows('day', '2026-04-15', 'date_desc')
        self.assertEqual([r['key'] for r in desc], sorted(keys, reverse=True))
        bogus = list_rows('day', '2026-04-15', 'nope')
        self.assertEqual([r['key'] for r in bogus], keys)
        mdef = list_rows('month', '2026-04')
        mkeys = [r['key'] for r in mdef]
        self.assertEqual(mkeys, sorted(mkeys))

    def test_sort_dropdown_flips_active_dimension(self):
        # Single sort control: active option flips, others use natural defaults
        body = self.client.get(
            '/partials/insights/list/?scope=day&period=2026-04-15&sort=date_asc').content.decode()
        self.assertIn('Sort: Date ↑', body)
        self.assertIn('sort=date_desc', body)  # reselecting Date flips
        self.assertIn('sort=expense_desc', body)
        self.assertIn('sort=income_desc', body)
        self.assertNotIn('>D↑<', body)
        self.assertNotIn('>E↓<', body)
        self.assertNotIn('>I↓<', body)
        exp = self.client.get(
            '/partials/insights/list/?scope=day&period=2026-04-15&sort=expense_desc').content.decode()
        self.assertIn('Sort: Expense ↓', exp)
        self.assertIn('sort=expense_asc', exp)  # reselecting Expense flips
        self.assertIn('sort=date_asc', exp)
        default = self.client.get('/day/2026-04-15/').content.decode()
        self.assertIn('Sort: Date ↑', default)
        self.assertIn('Daily rows in April 2026', default)
        self.assertIn('mt-12 flex items-center justify-end', body)  # breathing gap above rows bar

    def test_list_rows_keep_zero_value_periods(self):
        from decimal import Decimal

        from tracker.services.insights import list_rows

        days = list_rows('day', '2026-04-15')
        self.assertEqual(len(days), 30)  # full April run, empties included
        zero_days = [r for r in days if not r['income'] and not r['expense']]
        self.assertTrue(zero_days)
        self.assertEqual(zero_days[0]['income'], Decimal('0.00'))
        months = list_rows('month', '2026-04')
        self.assertEqual(len(months), 12)  # full Jan-Dec run

    def test_line_chart_marks_every_point_with_category_hover(self):
        from tracker.services.charts import build_chart_html
        from tracker.services.insights import CATEGORY_ORDER, month_context, year_context

        m = month_context('2026-04-15')
        self.assertEqual(len(m['series']), 30)  # every day depicted, zeros included
        for p in m['series']:
            self.assertEqual(set(p['cats']), set(CATEGORY_ORDER))
        yctx = year_context('2026-04')
        self.assertEqual(len(yctx['series']), 12)
        for p in yctx['series']:
            self.assertEqual(set(p['cats']), set(CATEGORY_ORDER))

        day = build_chart_html('day', '2026-04-15', 'line')
        self.assertIn('lines+markers', day)
        self.assertIn('customdata', day)
        for cat in CATEGORY_ORDER:
            self.assertIn(cat, day)
        self.assertIn('Total expense', day)
        self.assertIn('99999.99', day)  # Apr 3 Income bonus rides in hover payload
        year = build_chart_html('month', '2026-04', 'line')
        self.assertIn('lines+markers', year)
        self.assertIn('customdata', year)
        pie = build_chart_html('day', '2026-04-15', 'pie')
        self.assertNotIn('lines+markers', pie)
        self.assertNotIn('customdata', pie)

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

    def test_create_and_update_keep_chart_cache(self):
        from tracker.services.cache import chart_paths
        from tracker.services.charts import get_chart_html

        food = Category.objects.get(name='Food')
        html_path, _ = chart_paths(settings.CHART_CACHE_DIR, 'day', '2026-04-10', 'line')
        get_chart_html('day', '2026-04-10', 'line')
        self.assertTrue(html_path.exists())
        r = self.client.post(
            '/records/',
            {'item': 'CacheKeep', 'category': str(food.id), 'amount': '7.00',
             'date': '2026-04-10', 'scope': 'day', 'period': '2026-04-10'},
            HTTP_HX_REQUEST='true',
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(html_path.exists())
        e = Expense.objects.get(item='CacheKeep')
        r = self.client.post(
            f'/records/{e.id}/',
            {'item': 'CacheKeep 2', 'category': str(food.id), 'amount': '8.00',
             'scope': 'day', 'period': '2026-04-10'},
            HTTP_HX_REQUEST='true',
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(html_path.exists())

    def test_move_and_delete_invalidate_charts(self):
        from tracker.services.cache import chart_paths
        from tracker.services.charts import get_chart_html

        food = Category.objects.get(name='Food')
        e = Expense.objects.create(item='MoveBuster', category=food, amount='9.00', date='2026-04-10')
        old_path, _ = chart_paths(settings.CHART_CACHE_DIR, 'day', '2026-04-10', 'line')
        get_chart_html('day', '2026-04-10', 'line')
        self.assertTrue(old_path.exists())
        r = self.client.post(
            f'/records/{e.id}/move/',
            {'new_date': '2026-04-11', 'scope': 'day', 'period': '2026-04-10'},
            HTTP_HX_REQUEST='true',
        )
        self.assertEqual(r.status_code, 200)
        self.assertFalse(old_path.exists())
        new_path, _ = chart_paths(settings.CHART_CACHE_DIR, 'day', '2026-04-11', 'line')
        get_chart_html('day', '2026-04-11', 'line')
        self.assertTrue(new_path.exists())
        r = self.client.post(
            f'/records/{e.id}/delete/',
            {'scope': 'day', 'period': '2026-04-11'},
            HTTP_HX_REQUEST='true',
        )
        self.assertEqual(r.status_code, 200)
        self.assertFalse(new_path.exists())

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

    def test_chart_toggle_saves_kind_cookie(self):
        pie = self.client.get('/partials/insights/chart/', {'scope': 'day', 'period': '2026-04-15', 'type': 'pie'})
        self.assertEqual(pie.cookies['ins_chart'].value, 'pie')
        line = self.client.get('/partials/insights/chart/', {'scope': 'day', 'period': '2026-04-15', 'type': 'line'})
        self.assertEqual(line.cookies['ins_chart'].value, 'line')

    def test_detail_pages_use_saved_chart_kind(self):
        self.client.cookies['ins_chart'] = 'pie'
        for url in ('/day/2026-04-15/', '/month/2026-04/'):
            body = self.client.get(url).content.decode()
            self.assertNotIn('lines+markers', body)
            self.assertIn('type=line', body)

    def test_chart_query_param_overrides_saved_kind(self):
        self.client.cookies['ins_chart'] = 'pie'
        body = self.client.get('/day/2026-04-15/?chart=line').content.decode()
        self.assertIn('lines+markers', body)


@override_settings(
    HEATMAP_STATS_PATH=settings.BASE_DIR / 'tmp' / 'test_heatmap_stats.json',
    CHART_CACHE_DIR=settings.BASE_DIR / 'tmp' / 'test_charts_modal',
)
class HomeModalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_demo', '--clear')
        cls.food = Category.objects.get(name='Food')

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


@override_settings(
    HEATMAP_STATS_PATH=settings.BASE_DIR / 'tmp' / 'test_heatmap_stats.json',
    CHART_CACHE_DIR=settings.BASE_DIR / 'tmp' / 'test_charts_home',
)
class HomeInsightsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_demo', '--clear')

    def test_home_renders_insights_section_with_mode_buttons(self):
        from django.utils import timezone

        body = self.client.get('/').content.decode()
        self.assertIn('id="home-insights"', body)
        self.assertIn('>Yearly<', body)
        self.assertIn('>Overall<', body)
        month_label = timezone.localdate().strftime('%B %Y')
        self.assertIn(f'Daily rows in {month_label}', body)  # calendar-driven default
        self.assertIn('Sort: Date ↑', body)
        self.assertNotIn('sticky top-1', body)  # home panel scrolls, never sticks

    def test_records_page_panel_stays_sticky(self):
        body = self.client.get('/day/2026-04-15/').content.decode()
        self.assertIn('sticky top-1', body)

    def test_home_calendar_aside_is_pinned(self):
        # Desktop calendar stays in view while the home page scrolls.
        body = self.client.get('/').content.decode()
        self.assertIn('md:sticky md:top-0 md:h-screen md:overflow-y-auto', body)

    def test_home_toggle_flush_with_aside_edge(self):
        # Aside width and toggle offset share one reference (fractions, not vw),
        # so the tab's flat edge stays flush regardless of scrollbar width.
        body = self.client.get('/').content.decode()
        self.assertIn('md:w-1/4', body)
        self.assertIn('fixed right-3/4', body)
        self.assertIn("'right-3/4'", body)  # toggle JS re-adds the same class
        self.assertNotIn('w-[25vw]', body)
        self.assertNotIn('right-[75vw]', body)

    def test_home_uses_saved_chart_kind(self):
        self.client.cookies['ins_chart'] = 'pie'
        body = self.client.get('/').content.decode()
        self.assertNotIn('lines+markers', body)
        yearly = self.client.get('/partials/home/insights/', {'scope': 'yearly', 'period': 'all'})
        self.assertNotIn('lines+markers', yearly.content.decode())

    def test_home_insights_all_data_scopes(self):
        yearly = self.client.get('/partials/home/insights/', {'scope': 'yearly', 'period': 'all'})
        self.assertEqual(yearly.status_code, 200)
        ybody = yearly.content.decode()
        self.assertIn('data-scope="yearly"', ybody)
        self.assertIn('Yearly Expenses', ybody)
        self.assertIn('Yearly rows across All Data', ybody)
        self.assertIn('customdata', ybody)
        overall = self.client.get('/partials/home/insights/', {'scope': 'overall', 'period': 'all'})
        obody = overall.content.decode()
        self.assertIn('data-scope="overall"', obody)
        self.assertIn('Monthly Expenses', obody)
        self.assertIn('All Data', obody)
        self.assertIn('Yearly rows across All Data', obody)
        pie = self.client.get(
            '/partials/insights/chart/', {'scope': 'overall', 'period': 'all', 'type': 'pie'}
        )
        self.assertEqual(pie.status_code, 200)
        self.assertNotIn('lines+markers', pie.content.decode())

    def test_all_context_year_and_month_series(self):
        from django.utils import timezone

        from tracker.services.insights import SORTS, all_context, list_rows

        years = sorted(set(Expense.objects.values_list('date__year', flat=True)))
        yctx = all_context('yearly')
        self.assertEqual([p['label'] for p in yctx['series']], [str(y) for y in years])
        mctx = all_context('monthly')
        self.assertEqual(mctx['series'][0]['label'], 'May 2025')  # baseline start
        self.assertEqual(mctx['series'][-1]['label'], timezone.localdate().strftime('%b %Y'))
        rows = list_rows('yearly', 'all')
        self.assertEqual([r['label'] for r in rows], [str(y) for y in years])
        self.assertEqual(len(list_rows('overall', 'all')), len(years))
        self.assertIn('date_asc', SORTS)  # sort keys apply to yearly rows too
        desc = list_rows('yearly', 'all', 'income_desc')
        self.assertGreaterEqual(desc[0]['income'], desc[-1]['income'])

    def test_calendar_partials_emit_cal_period_trigger(self):
        import json

        day = self.client.get('/partials/calendar/day/', {'ym': '2026-04'})
        self.assertEqual(
            json.loads(day.headers['HX-Trigger']),
            {'cal-period': {'scope': 'day', 'period': '2026-04-01'}},
        )
        month = self.client.get('/partials/calendar/month/', {'y': 2026})
        self.assertEqual(
            json.loads(month.headers['HX-Trigger']),
            {'cal-period': {'scope': 'month', 'period': '2026-01'}},
        )

    def test_home_insights_trigger_is_isolated_leaf(self):
        body = self.client.get('/').content.decode()
        # The container must not carry event attributes, or descendants inherit
        # hx-vals and their own clicks send scope/period=undefined (issue: 500).
        wrapper = body[body.index('id="home-insights"'):]
        wrapper = wrapper[:wrapper.index('>')]
        self.assertNotIn('hx-vals', wrapper)
        self.assertNotIn('hx-get', wrapper)
        self.assertIn('hx-target="#home-insights"', body)
        # A `delay` trigger runs in setTimeout, where window.event is null, so
        # hx-vals' `event.detail` throws and the insights refresh is aborted.
        trigger = body[body.index('hx-trigger="cal-period'):]
        trigger = trigger[:trigger.index('"', trigger.index('"') + 1)]
        self.assertIn('from:body', trigger)
        self.assertNotIn('delay', trigger)

    def test_bad_period_falls_back_instead_of_500(self):
        for path, params in (
            ('/partials/insights/chart/', {'scope': 'yearly', 'period': 'undefined', 'type': 'line'}),
            ('/partials/insights/list/', {'scope': 'day', 'period': 'undefined'}),
            ('/partials/home/insights/', {'scope': 'month', 'period': 'undefined'}),
        ):
            r = self.client.get(path, params)
            self.assertEqual(r.status_code, 200, path)

    def test_home_mobile_calendar_loads_on_open(self):
        body = self.client.get('/').content.decode()
        self.assertIn('function openCalModal()', body)
        self.assertIn('onclick="openCalModal()"', body)
        mobile = body[body.index('id="calendar-m"'):]
        mobile = mobile[:mobile.index('>')]
        self.assertIn('hx-trigger="refresh"', mobile)
        self.assertNotIn('load', mobile)

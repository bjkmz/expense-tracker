"""Seed demo data matching reference sketches (April 2026 + baseline).

- Baseline May 2025 - Mar 2026 ~100/day expense -> stable mean/median over
  12 months so the April 2026 spike month can exceed 5x mean (red).
- April 2026 rich: Rice x12 (Top Food), Jeepney route x20 (Top Transpo),
  Highest Income 99999.99 Apr 03, Cabinet 3600 Apr 15 (red spike),
  Deodorant Apr 17, Electricity 2500 Apr 20, plus low days (~5.00) for blue.
- Current month gets a few rows so Home isn't empty (also a blue month demo).

Usage: python manage.py seed_demo [--clear]
"""
from __future__ import annotations

import random
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from tracker.models import Category, Expense

CATEGORIES = ['Income', 'Transpo', 'Food', 'Consumable', 'Ownership', 'Miscellaneous']


class Command(BaseCommand):
    help = 'Seed demo expenses for heatmap/insights testing.'

    def add_arguments(self, parser):
        parser.add_argument('--clear', action='store_true', help='Delete all expenses first.')

    @transaction.atomic
    def handle(self, *args, **options):
        for name in CATEGORIES:
            Category.objects.get_or_create(name=name)
        cats = {c.name: c for c in Category.objects.all()}

        if options['clear']:
            Expense.objects.all().delete()

        if Expense.objects.exists() and not options['clear']:
            self.stdout.write(self.style.WARNING('Expenses exist; use --clear to reseed.'))
            return

        rng = random.Random(42)
        rows: list[Expense] = []

        def add(item, cat, amount, day):
            rows.append(Expense(item=item, category=cats[cat], amount=Decimal(str(amount)), date=day))

        # Baseline May 2025 - Mar 2026: ~80-120/day across Food + Transpo
        day = date(2025, 5, 1)
        while day < date(2026, 4, 1):
            add('Rice meal', 'Food', round(rng.uniform(45, 70), 2), day)
            add('Jeepney Home-Office', 'Transpo', round(rng.uniform(25, 40), 2), day)
            if rng.random() < 0.3:
                add('Soap', 'Consumable', round(rng.uniform(30, 60), 2), day)
            if rng.random() < 0.15:
                add('Salary payout', 'Income', round(rng.uniform(800, 1500), 2), day)
            day += timedelta(days=1)

        # April 2026: Top Food Rice x12, Top Transpo route x20
        for i in range(12):
            add('Rice', 'Food', round(rng.uniform(50, 90), 2), date(2026, 4, 1 + (i % 28)))
        for i in range(20):
            add('Jeepney Home-Office', 'Transpo', round(rng.uniform(25, 40), 2), date(2026, 4, 1 + (i % 28)))
        # Sketch anchors
        add('April bonus', 'Income', '99999.99', date(2026, 4, 3))
        add('Cabinet', 'Ownership', '3600.00', date(2026, 4, 15))
        add('Deodorant', 'Consumable', '850.00', date(2026, 4, 17))
        add('Electricity', 'Miscellaneous', '2500.00', date(2026, 4, 20))
        # Spike extras on Apr 15 to guarantee red day AND red month
        # (>5x mean needs a long baseline: 11 baseline months dilute the mean)
        add('Cabinet delivery', 'Ownership', '20000.00', date(2026, 4, 15))
        add('Fixtures', 'Miscellaneous', '12000.00', date(2026, 4, 15))
        # Blue low days: tiny single expense on days with no Top-loop records
        for d in (23, 24, 27, 28):
            add('Water refill', 'Food', '5.00', date(2026, 4, d))
        # Regular April income
        add('Salary payout', 'Income', '12000.00', date(2026, 4, 30))

        # Current month: a few rows so initial Home view isn't empty
        today = date.today()
        for i in range(5):
            add('Rice meal', 'Food', round(rng.uniform(45, 70), 2), today - timedelta(days=i))
        add('Salary payout', 'Income', '12000.00', today)

        Expense.objects.bulk_create(rows)
        self.stdout.write(self.style.SUCCESS(f'Seeded {len(rows)} expenses.'))

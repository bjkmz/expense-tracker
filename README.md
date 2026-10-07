# Expense Tracker

Django + HTMX expense tracker (SQLite, Tailwind via CDN, Plotly.py + Pandas for
insights/heatmap). Single-user, no auth. Interface sketches and architecture notes
live in `reference/` (`outline.txt`, `1.png–7.png`).

## Prereqs

- Python 3.13 (`3.13.2` verified), `pip`
- Internet access on first page load (Tailwind, HTMX 1.9.12, and plotly.js 2.35.2
  load from CDN — versions pinned in `config/settings.py`)

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo
python manage.py runserver
```

Open `http://127.0.0.1:8000/`. To reseed demo data: `python manage.py seed_demo --clear`.
Pinned versions (`requirements.txt`): `Django==5.2.17`, `pandas==2.3.3`,
`plotly==6.5.2`, `numpy==2.1.3`.

Migrations `tracker/0001_initial` + `tracker/0002_seed_categories` create the
`Category`/`Expense` tables and the six categories (Income, Transpo, Food,
Consumable, Ownership, Miscellaneous). The seed script adds 872 demo rows with
April-2026 anchors (Rice x12, Jeepney x20, bonus 99999.99, Cabinet spike).

## Daily commands

| Task              | Command                            |
|-------------------|------------------------------------|
| Run dev server    | `python manage.py runserver`       |
| Run tests         | `python manage.py test tracker` (31 tests) |
| Reseed demo data  | `python manage.py seed_demo --clear` |
| Schema changes    | `python manage.py makemigrations` / `migrate` |
| Admin UI          | `python manage.py createsuperuser`, then `/admin/` |

## Using the app

- **Home (`/`)** — dark collapsible aside with Day/Month calendar heatmap tabs,
  `ADD RECORD` button opening a modal (item, category, amount; recorded as today,
  Cancel/Save). Saving closes the modal, shows a toast, and refreshes the
  calendar in place. Mobile uses a bottom bar with a full-screen calendar modal.
- **Calendar** — day cells show day no. + day income/expense; month cells show
  month + totals. Green = today/this month, red = expense over 5x the all-time
  average, blue = non-zero expense under 80% of the median. Click a cell to open
   `/day/<YYYY-MM-DD>/` or `/month/<YYYY-MM>/`. Calendar headers carry an
   icon-only jump picker (date picker on Day, month/year picker on Month) ahead
   of the label.
- **Records panel** — date head with chevrons around the label,
  SUMMARY (net + per-category totals, `0.00` if none), inline add row, rows with
  in-place editing, and a three-dot menu per row (Move to new date / Delete).
- **Insights panel** — Day/Month tabs, line/pie toggle, category totals, insight
  cards (Highest Income, Top Food/Transpo by record count, costliest
  Consumable/Ownership/Miscellaneous), and sortable daily/monthly rows
  (Expense and Income ascending/descending; Filter is a disabled placeholder).

## Project layout

```
config/            Django settings, root urls
tracker/           models, views, urls, admin, tests
  services/        heatmap.py, records.py, insights.py, charts.py, cache.py
  management/commands/seed_demo.py
templates/         base.html, home.html, records_page.html, partials/*
public/ + static/  static files (STATICFILES_DIRS)
tmp/               gitignored: charts/, cache/, heatmap_stats.json
reference/         outline.txt + interface sketches 1.png-7.png
```

## Caching rules (read before changing data code)

- ORM first; Pandas is used only for heatmap mean/median (lazy import inside the
  recompute path).
- Chart HTML (`tmp/charts/<scope>_<period>_<line|pie>.html` + `.meta.json`) is
  gated on a scoped `MAX(updated_at)` query — cheap check versus a full rebuild.
- Every write path calls `invalidate_caches()` (deletes retreat `MAX`, so gating
  alone would serve stale charts after a delete).
- Tests override cache paths to `tmp/test_*` so the dev cache stays clean.

## Troubleshooting

- `DisallowedHost: testserver` — dev hosts (`127.0.0.1`, `localhost`,
  `testserver`) are already in `ALLOWED_HOSTS`.
- Blank charts/styles offline — CDN assets (Tailwind/HTMX/plotly.js) need internet.
- Stale chart after manual DB edits — deletes/updates outside the views skip
  invalidation; clear with `Remove-Item tmp\charts\*`, `Remove-Item
  tmp\heatmap_stats.json` and reload.
- Venv activation blocked on Windows — `Set-ExecutionPolicy -Scope
  CurrentUser RemoteSigned`, then activate again.

## Out of scope (intentional)

Profile row placeholder (no accounts), blank home insights section per the
outline, non-functional Filter button, SQLite single-user store.

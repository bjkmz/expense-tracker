"""Disk-cache helpers for Plotly partials + heatmap stats (P0).

Policy (agreed):
- ORM first. Pandas only for mean/median over pre-aggregated series.
- Never load the whole Expense table. Gate every recompute on
  MAX(updated_at) (single indexed query) vs cached meta.
- plotly.js loads once via CDN; cached partials store HTML with
  include_plotlyjs=False.

Cache layout (settings.CHART_CACHE_DIR / HEATMAP_STATS_PATH):
  tmp/charts/<scope>_<period>_<line|pie>.html
  tmp/charts/<scope>_<period>_<line|pie>.meta.json
    {"source_max_updated_at": iso str | null, "built_at": iso str}
"""
from __future__ import annotations

import json
from datetime import datetime, timezone as dt_timezone
from pathlib import Path


def _iso_now() -> str:
    return datetime.now(dt_timezone.utc).isoformat()


def chart_paths(cache_dir: Path, scope: str, period: str, kind: str) -> tuple[Path, Path]:
    safe = f'{scope}_{period}_{kind}'.replace('/', '-')
    return cache_dir / f'{safe}.html', cache_dir / f'{safe}.meta.json'


def is_fresh(meta_path: Path, db_max_updated_at: str | None) -> bool:
    """True when cached chart was built from data at least as new as db_max.

    Both values are ISO strings; None (empty DB) is always fresh if file exists.
    String comparison works for ISO-8601 with matching offsets.
    """
    if db_max_updated_at is None:
        return True
    try:
        meta = json.loads(meta_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return False
    cached = meta.get('source_max_updated_at')
    return cached is not None and cached >= db_max_updated_at


def write_chart(html_path: Path, meta_path: Path, html: str, source_max: str | None) -> None:
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html, encoding='utf-8')
    meta_path.write_text(
        json.dumps({'source_max_updated_at': source_max, 'built_at': _iso_now()}),
        encoding='utf-8',
    )


def read_chart(html_path: Path) -> str:
    return html_path.read_text(encoding='utf-8')


def invalidate_caches() -> None:
    """Clear chart + heatmap disk caches after any write.

    Needed because deletes can retreat MAX(updated_at), making the
    meta>=db_max freshness check falsely pass. Writes are rare
    (single user) and rebuilds are gated, so full clear is cheapest
    correct option. Respects current settings (test overrides safe).
    """
    from django.conf import settings as dj_settings

    chart_dir: Path = dj_settings.CHART_CACHE_DIR
    for p in chart_dir.glob('*.html'):
        try:
            p.unlink()
        except OSError:
            pass
    for p in chart_dir.glob('*.meta.json'):
        try:
            p.unlink()
        except OSError:
            pass
    try:
        dj_settings.HEATMAP_STATS_PATH.unlink(missing_ok=True)
    except OSError:
        pass

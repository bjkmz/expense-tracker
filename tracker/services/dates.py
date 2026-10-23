from __future__ import annotations

import calendar
from datetime import date


def month_range(year: int, month: int) -> tuple[date, date]:
    """Inclusive first/last day of a month."""
    last = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)

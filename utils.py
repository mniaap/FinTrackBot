"""Utility helpers: currency formatting, date helpers, name normalisation."""
from __future__ import annotations

from datetime import datetime, timezone

from config import CURRENCY_SYMBOL


def fmt(amount: float) -> str:
    """Format an amount as Indian Rupees, e.g. ₹1,500.00"""
    if amount < 0:
        return f"-{CURRENCY_SYMBOL}{abs(amount):,.2f}"
    return f"{CURRENCY_SYMBOL}{amount:,.2f}"


def fmt_int(amount: float) -> str:
    """Format without decimals, e.g. ₹1,500"""
    if amount < 0:
        return f"-{CURRENCY_SYMBOL}{abs(int(amount)):,}"
    return f"{CURRENCY_SYMBOL}{int(amount):,}"


def normalise_name(name: str) -> str:
    """Lowercase, strip, collapse internal whitespace."""
    return " ".join(name.strip().lower().split())


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def current_month_str() -> str:
    """Return 'YYYY-MM' for the current month (UTC)."""
    return now_utc().strftime("%Y-%m")


def month_name_from_str(month_str: str) -> str:
    """Convert '2024-10' to 'October 2024'."""
    try:
        dt = datetime.strptime(month_str, "%Y-%m")
        return dt.strftime("%B %Y")
    except ValueError:
        return month_str


def progress_bar(pct: float, width: int = 10) -> str:
    """Return a text-based progress bar like ▓▓▓▓░░."""
    filled = int(round(pct / 100 * width))
    return "\u2593" * filled + "\u2591" * (width - filled)


def parse_period(text: str | None) -> tuple[str, str] | None:
    """Parse a natural-language period like 'this month', 'october', '2024-10'.

    Returns a tuple (start_sql, end_sql) of ISO datetime strings for SQLite,
    or None if unparseable.
    """
    if not text:
        return None

    text_lower = text.strip().lower()
    now = now_utc()

    if text_lower in ("today", "today's"):
        d = now.strftime("%Y-%m-%d")
        return (f"{d} 00:00:00", f"{d} 23:59:59")

    if text_lower in ("this month", "this month's", "current month"):
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=start.month + 1)
        return (start.isoformat(), end.isoformat())

    if text_lower in ("last month", "last month's"):
        if now.month == 1:
            start = now.replace(year=now.year - 1, month=12, day=1,
                                hour=0, minute=0, second=0, microsecond=0)
        else:
            start = now.replace(month=now.month - 1, day=1,
                                hour=0, minute=0, second=0, microsecond=0)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=start.month + 1)
        return (start.isoformat(), end.isoformat())

    # Try month name (e.g. "october", "oct")
    import calendar
    for idx, mname in enumerate(calendar.month_name[1:], start=1):
        if text_lower.startswith(mname.lower()):
            year = now.year
            # If the requested month is in the future relative to now, assume last year
            if idx > now.month:
                year -= 1
            start = now.replace(year=year, month=idx, day=1,
                                hour=0, minute=0, second=0, microsecond=0)
            if idx == 12:
                end = start.replace(year=year + 1, month=1)
            else:
                end = start.replace(month=idx + 1)
            return (start.isoformat(), end.isoformat())

    # Try YYYY-MM format
    try:
        dt = datetime.strptime(text_lower, "%Y-%m")
        start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=start.month + 1)
        return (start.isoformat(), end.isoformat())
    except ValueError:
        pass

    return None
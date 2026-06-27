"""Generate spending pie-chart images with matplotlib."""
from __future__ import annotations

import io
import logging
from datetime import datetime, timezone

from sqlalchemy import func as sa_func

import matplotlib
matplotlib.use("Agg")  # headless backend
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

from database import SessionLocal, PersonalExpense
from utils import parse_period, month_name_from_str, CURRENCY_SYMBOL, current_month_str

logger = logging.getLogger(__name__)

# Ensure we have a font that can render ₹ and common text
for fp in [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]:
    try:
        fm.fontManager.addfont(fp)
    except FileNotFoundError:
        pass

plt.rcParams["font.sans-serif"] = ["DejaVu Sans", "Liberation Sans"]
plt.rcParams["axes.unicode_minus"] = False


def _query_spending(user_id: int, period_text: str | None) -> dict[str, float]:
    """Return {category: total_amount} for the given user/period."""
    session = SessionLocal()
    try:
        if period_text:
            bounds = parse_period(period_text)
        else:
            bounds = parse_period("this month")

        q = session.query(
            PersonalExpense.category,
            sa_func.sum(PersonalExpense.amount),
        ).filter(PersonalExpense.user_id == user_id)

        if bounds:
            start, end = bounds
            q = q.filter(
                PersonalExpense.date >= start,
                PersonalExpense.date < end,
            )

        rows = q.group_by(PersonalExpense.category).all()
        return {row[0]: row[1] for row in rows if row[1] is not None}
    finally:
        session.close()


def generate_pie_chart(user_id: int, period_text: str | None = None) -> io.BytesIO | None:
    """Create a pie chart and return it as an in-memory PNG file-like object.

    Returns None if there is no data.
    """
    data = _query_spending(user_id, period_text)
    if not data:
        return None

    labels = list(data.keys())
    sizes = list(data.values())
    total = sum(sizes)

    # Build a readable title
    if period_text:
        period_name = month_name_from_str(
            period_text.replace("this month", current_month_str())
        )
    else:
        period_name = month_name_from_str(current_month_str())
    title = f"Spending \u2014 {period_name}"

    # Sort largest-first for better readability
    paired = sorted(zip(sizes, labels), reverse=True)
    sizes = [p[0] for p in paired]
    labels = [p[1] for p in paired]

    fig, ax = plt.subplots(figsize=(7, 5), constrained_layout=True)
    wedges, texts, autotexts = ax.pie(
        sizes,
        labels=None,
        autopct=lambda pct: f"{pct:.1f}%" if pct > 4 else "",
        startangle=140,
        colors=plt.cm.Set3.colors[: len(sizes)],
        pctdistance=0.75,
    )
    for t in autotexts:
        t.set_fontsize(9)

    # Legend with amounts
    legend_labels = [
        f"{lbl}: {CURRENCY_SYMBOL}{amt:,.0f} ({amt / total * 100:.1f}%)"
        for lbl, amt in zip(labels, sizes)
    ]
    ax.legend(
        wedges, legend_labels, title="Categories",
        loc="center left", bbox_to_anchor=(1, 0, 0.5, 1), fontsize=9,
    )

    ax.set_title(title, fontsize=14, fontweight="bold")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    buf.seek(0)
    return buf
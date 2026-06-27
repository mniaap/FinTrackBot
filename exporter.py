"""Export personal expenses & friend transactions to CSV."""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone

from database import SessionLocal, PersonalExpense, FriendTransaction
from utils import parse_period, fmt

logger = logging.getLogger(__name__)


def generate_csv(user_id: int, period_text: str | None = None) -> io.BytesIO:
    """Return a CSV file-like object containing all transactions."""
    session = SessionLocal()
    try:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["Type", "Date", "Category/Person", "Description",
                         "Amount", "Sub-type"])

        # Personal expenses
        q_exp = session.query(PersonalExpense).filter(
            PersonalExpense.user_id == user_id
        )
        if period_text:
            bounds = parse_period(period_text)
            if bounds:
                start, end = bounds
                q_exp = q_exp.filter(
                    PersonalExpense.date >= start,
                    PersonalExpense.date < end,
                )
        for row in q_exp.order_by(PersonalExpense.date.desc()).all():
            writer.writerow([
                "Expense",
                row.date.strftime("%Y-%m-%d %H:%M"),
                row.category,
                row.description or "",
                f"{row.amount:.2f}",
                "",
            ])

        # Friend transactions
        q_ft = session.query(FriendTransaction).filter(
            FriendTransaction.user_id == user_id
        )
        if period_text:
            bounds = parse_period(period_text)
            if bounds:
                start, end = bounds
                q_ft = q_ft.filter(
                    FriendTransaction.date >= start,
                    FriendTransaction.date < end,
                )
        for row in q_ft.order_by(FriendTransaction.date.desc()).all():
            writer.writerow([
                "Friend",
                row.date.strftime("%Y-%m-%d %H:%M"),
                row.friend_name,
                row.description or "",
                f"{row.amount:.2f}",
                row.type,
            ])

        # Return as bytes
        csv_bytes = io.BytesIO()
        csv_bytes.write(buf.getvalue().encode("utf-8-sig"))  # BOM for Excel
        csv_bytes.seek(0)
        return csv_bytes
    finally:
        session.close()
"""All Telegram bot command & message handlers."""
from __future__ import annotations

import logging
import tempfile
from datetime import datetime, timezone

from aiogram import Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from sqlalchemy import func as sa_func

from config import CURRENCY_SYMBOL, BUDGET_WARN_THRESHOLD, BUDGET_ALERT_THRESHOLD
from database import (
    SessionLocal,
    PersonalExpense,
    Friend,
    FriendTransaction,
    Budget,
)
from parser import parse_message
from utils import (
    fmt,
    fmt_int,
    normalise_name,
    now_utc,
    current_month_str,
    progress_bar,
    parse_period,
    month_name_from_str,
)
from charts import generate_pie_chart
from exporter import generate_csv

logger = logging.getLogger(__name__)
router = Router()


# ===================================================================
# Helpers
# ===================================================================

def _today_total(session, user_id: int) -> float:
    today = now_utc().strftime("%Y-%m-%d")
    result = (
        session.query(sa_func.sum(PersonalExpense.amount))
        .filter(
            PersonalExpense.user_id == user_id,
            PersonalExpense.date >= f"{today} 00:00:00",
            PersonalExpense.date <= f"{today} 23:59:59",
        )
        .scalar()
    )
    return result or 0.0


def _month_total(session, user_id: int) -> float:
    now = now_utc()
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if now.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    result = (
        session.query(sa_func.sum(PersonalExpense.amount))
        .filter(
            PersonalExpense.user_id == user_id,
            PersonalExpense.date >= start,
            PersonalExpense.date < end,
        )
        .scalar()
    )
    return result or 0.0


def _month_spent_by_category(session, user_id: int) -> dict[str, float]:
    now = now_utc()
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if now.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    rows = (
        session.query(
            PersonalExpense.category,
            sa_func.sum(PersonalExpense.amount),
        )
        .filter(
            PersonalExpense.user_id == user_id,
            PersonalExpense.date >= start,
            PersonalExpense.date < end,
        )
        .group_by(PersonalExpense.category)
        .all()
    )
    return {r[0]: r[1] for r in rows if r[1] is not None}


def _check_budget(session, user_id: int, category: str, amount: float) -> str | None:
    """Return a warning/alert string if a budget threshold is crossed, else None."""
    month = current_month_str()
    budget = (
        session.query(Budget)
        .filter(
            Budget.user_id == user_id,
            Budget.category == category,
            Budget.month == month,
        )
        .first()
    )
    if not budget:
        return None

    spent = _month_spent_by_category(session, user_id).get(category, 0.0)
    ratio = spent / budget.limit_amount if budget.limit_amount > 0 else 0

    if ratio >= BUDGET_ALERT_THRESHOLD:
        return (
            f"\U0001f6a8 You've exceeded your {category} budget! "
            f"Spent {fmt(spent)} of {fmt(budget.limit_amount)}."
        )
    if ratio >= BUDGET_WARN_THRESHOLD:
        return (
            f"\u26a0\ufe0f Heads up! You've spent {ratio * 100:.0f}% "
            f"({fmt(spent)}) of your {fmt(budget.limit_amount)} {category} budget this month."
        )
    return None


def _get_or_create_friend(session, user_id: int, name: str) -> Friend:
    name_norm = normalise_name(name)
    friend = (
        session.query(Friend)
        .filter(Friend.user_id == user_id, Friend.friend_name == name_norm)
        .first()
    )
    if not friend:
        friend = Friend(user_id=user_id, friend_name=name_norm, balance=0.0)
        session.add(friend)
        session.flush()
    return friend


# ===================================================================
# Slash command handlers
# ===================================================================

WELCOME = (
    "\U0001f4b0 <b>Welcome to FinTrackBot!</b>\n\n"
    "I'm your personal finance assistant. Just tell me what happened "
    "in plain English and I'll track it for you.\n\n"
    "<b>Quick examples:</b>\n"
    "• <code>spent 500 on groceries</code>\n"
    "• <code>gave Rahul 100 for college fees</code>\n"
    "• <code>Priya gave me 300 for concert</code>\n"
    "• <code>Rahul paid me back 50</code>\n"
    "• <code>how much does Rahul owe me?</code>\n\n"
    "Type /help to see all commands."
)

HELP_TEXT = (
    "\U0001f4cb <b>FinTrackBot — Command Reference</b>\n\n"
    "<b>Natural Language (just type!):</b>\n"
    "• <code>spent 500 on groceries</code> — Log expense\n"
    "• <code>gave Rahul 100 for college fees</code> — Lend money\n"
    "• <code>Priya gave me 300 for concert</code> — Borrow money\n"
    "• <code>Rahul paid me back 50</code> — Settle debt\n"
    "• <code>how much does Rahul owe me?</code> — Check balance\n"
    "• <code>set budget 3000 for food this month</code> — Set budget\n\n"
    "<b>Slash Commands:</b>\n"
    "/start — Welcome message\n"
    "/help — This help menu\n"
    "/owed — List who owes you\n"
    "/owes — List who you owe\n"
    "/summary — Today's & this month's total spend\n"
    "/chart — Spending pie chart\n"
    "/budgets — View all budgets\n"
    "/export — Download CSV of transactions"
)


@router.message(F.text == "/start")
async def cmd_start(message: Message):
    await message.answer(WELCOME, parse_mode="HTML")


@router.message(F.text == "/help")
async def cmd_help(message: Message):
    await message.answer(HELP_TEXT, parse_mode="HTML")


@router.message(F.text.startswith("/owed"))
async def cmd_owed(message: Message):
    """List everyone who owes the user money (positive balance)."""
    uid = message.from_user.id
    session = SessionLocal()
    try:
        friends = (
            session.query(Friend)
            .filter(Friend.user_id == uid, Friend.balance > 0)
            .all()
        )
        if not friends:
            await message.answer("\U0001f389 Nobody owes you money!")
            return
        lines = ["\U0001f4cb <b>People who owe you:</b>\n"]
        for f in sorted(friends, key=lambda x: -x.balance):
            lines.append(f"\u2022 <b>{f.friend_name.title()}</b>: {fmt(f.balance)}")
        await message.answer("\n".join(lines), parse_mode="HTML")
    finally:
        session.close()


@router.message(F.text.startswith("/owes"))
async def cmd_owes(message: Message):
    """List everyone the user owes money to (negative balance)."""
    uid = message.from_user.id
    session = SessionLocal()
    try:
        friends = (
            session.query(Friend)
            .filter(Friend.user_id == uid, Friend.balance < 0)
            .all()
        )
        if not friends:
            await message.answer("\U0001f389 You don't owe anyone!")
            return
        lines = ["\U0001f4cb <b>People you owe:</b>\n"]
        for f in sorted(friends, key=lambda x: x.balance):
            lines.append(f"\u2022 <b>{f.friend_name.title()}</b>: {fmt(abs(f.balance))}")
        await message.answer("\n".join(lines), parse_mode="HTML")
    finally:
        session.close()


@router.message(F.text.startswith("/summary"))
async def cmd_summary(message: Message):
    uid = message.from_user.id
    session = SessionLocal()
    try:
        today = _today_total(session, uid)
        month = _month_total(session, uid)
        text = (
            "\U0001f4ca <b>Spending Summary</b>\n\n"
            f"\U0001f4c5 Today: {fmt(today)}\n"
            f"\U0001f4c6 This month: {fmt(month)}"
        )
        await message.answer(text, parse_mode="HTML")
    finally:
        session.close()


@router.message(F.text.startswith("/chart"))
async def cmd_chart(message: Message):
    uid = message.from_user.id
    await message.bot.send_chat_action(message.chat.id, "upload_photo")

    period_text = message.text.replace("/chart", "").strip() or None
    buf = generate_pie_chart(uid, period_text)
    if buf is None:
        await message.answer(
            "\U0001f4ca No spending data found for this period. "
            "Log some expenses first!"
        )
        return

    buf.name = "spending_chart.png"
    await message.answer_photo(FSInputFile(buf))


@router.message(F.text.startswith("/budgets"))
async def cmd_budgets(message: Message):
    uid = message.from_user.id
    month = current_month_str()
    session = SessionLocal()
    try:
        budgets = (
            session.query(Budget)
            .filter(Budget.user_id == uid, Budget.month == month)
            .all()
        )
        if not budgets:
            await message.answer(
                "\U0001f4cb No budgets set for this month. "
                "Use: <code>set budget 3000 for food this month</code>",
                parse_mode="HTML",
            )
            return

        spent_map = _month_spent_by_category(session, uid)
        lines = [f"\U0001f4cb <b>Budgets — {month_name_from_str(month)}</b>\n"]
        for b in budgets:
            spent = spent_map.get(b.category, 0.0)
            pct = min((spent / b.limit_amount) * 100, 150) if b.limit_amount > 0 else 0
            bar = progress_bar(pct)
            status_emoji = "\U0001f7e2" if pct < 80 else ("\u26a0\ufe0f" if pct < 100 else "\U0001f534")
            lines.append(
                f"{status_emoji} <b>{b.category.title()}</b>: {bar} {pct:.0f}%\n"
                f"   {fmt(spent)} / {fmt(b.limit_amount)}"
            )
        await message.answer("\n".join(lines), parse_mode="HTML")
    finally:
        session.close()


@router.message(F.text.startswith("/export"))
async def cmd_export(message: Message):
    uid = message.from_user.id
    await message.bot.send_chat_action(message.chat.id, "upload_document")

    period_text = message.text.replace("/export", "").strip() or None
    csv_buf = generate_csv(uid, period_text)

    period_label = period_text or "all time"
    filename = f"fintrack_export_{normalise_name(period_label).replace(' ', '_')}.csv"

    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        tmp.write(csv_buf.getvalue())
        tmp_path = tmp.name

    try:
        await message.answer_document(
            FSInputFile(tmp_path, filename=filename),
            caption=f"\U0001f4e5 FinTrackBot export — {period_label}",
        )
    finally:
        import os
        os.unlink(tmp_path)


# ===================================================================
# Inline keyboard callbacks
# ===================================================================

@router.callback_query(F.data.startswith("settle_"))
async def cb_settle_full(callback: CallbackQuery):
    """Settle a friend's balance completely via inline button."""
    uid = callback.from_user.id
    friend_name = callback.data.replace("settle_", "")
    friend_name_norm = normalise_name(friend_name)

    session = SessionLocal()
    try:
        friend = (
            session.query(Friend)
            .filter(Friend.user_id == uid, Friend.friend_name == friend_name_norm)
            .first()
        )
        if not friend:
            await callback.answer("Friend not found.", show_alert=True)
            return

        old_balance = friend.balance
        friend.balance = 0.0

        # Log settle transaction
        tx = FriendTransaction(
            user_id=uid,
            friend_name=friend_name_norm,
            amount=abs(old_balance),
            description="Full settlement (via button)",
            type="settle",
        )
        session.add(tx)
        session.commit()

        await callback.message.edit_text(
            f"\U0001f4b0 Fully settled with <b>{friend_name_norm.title()}</b>!\n"
            f"Cleared {fmt(abs(old_balance))}.\n"
            f"Current balance: {fmt(0.0)}",
            parse_mode="HTML",
        )
        await callback.answer("Settled!")
    except Exception as e:
        session.rollback()
        logger.exception("Settle callback failed")
        await callback.answer("Something went wrong.", show_alert=True)
    finally:
        session.close()


@router.callback_query(F.data == "export_confirm_yes")
async def cb_export_confirm_yes(callback: CallbackQuery):
    """Confirmed export — delegate to /export logic."""
    await callback.message.delete_reply_markup()
    uid = callback.from_user.id
    await callback.bot.send_chat_action(callback.message.chat.id, "upload_document")
    csv_buf = generate_csv(uid, None)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        tmp.write(csv_buf.getvalue())
        tmp_path = tmp.name
    try:
        await callback.message.reply_document(
            FSInputFile(tmp_path, filename="fintrackbot_export.csv"),
            caption="\U0001f4e5 FinTrackBot export — all time",
        )
    finally:
        import os
        os.unlink(tmp_path)
    await callback.answer()


@router.callback_query(F.data == "export_confirm_no")
async def cb_export_confirm_no(callback: CallbackQuery):
    await callback.message.edit_text("\u274c Export cancelled.")
    await callback.answer()


# ===================================================================
# Natural language message handler (the core brain)
# ===================================================================

@router.message(F.text)
async def handle_text(message: Message):
    """Route free-text messages through the LLM parser."""
    uid = message.from_user.id
    text = message.text.strip()

    # Skip messages that look like accidental commands
    if text.startswith("/") and len(text.split()) == 1:
        await message.answer(
            "\U0001f914 Unknown command. Type /help to see what I can do."
        )
        return

    await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        parsed = await parse_message(text)
    except Exception:
        logger.exception("LLM call failed")
        await message.answer(
            "\u26a0\ufe0f I'm having trouble understanding right now. "
            "Please try again in a moment."
        )
        return

    ptype = parsed.get("type", "unknown")
    amount = parsed.get("amount")
    friend = parsed.get("friend")
    category = parsed.get("category")
    description = parsed.get("description")
    budget_amount = parsed.get("budget_amount")

    # ---- UNKNOWN ----
    if ptype == "unknown":
        await message.answer(
            "\U0001f914 I didn't quite catch that. Try something like:\n"
            "• <code>spent 200 on food</code>\n"
            "• <code>gave Rahul 100 for fees</code>\n"
            "• <code>how much does Rahul owe me?</code>",
            parse_mode="HTML",
        )
        return

    # ---- PERSONAL EXPENSE ----
    if ptype == "personal":
        if not amount or amount <= 0:
            await message.answer(
                "\U0001f914 How much did you spend? "
                "e.g. <code>spent 500 on groceries</code>",
                parse_mode="HTML",
            )
            return
        cat = (category or "misc").lower().strip()
        desc = description or cat

        session = SessionLocal()
        try:
            expense = PersonalExpense(
                user_id=uid, amount=amount, category=cat, description=desc,
            )
            session.add(expense)
            session.flush()  # ensure it's committed before budget check

            # Running totals
            today = _today_total(session, uid)
            month = _month_total(session, uid)

            # Budget check
            budget_msg = _check_budget(session, uid, cat, amount)

            session.commit()

            reply = (
                f"\U0001f44d Logged {fmt(amount)} for <b>{cat}</b>.\n"
                f"Total spent today: {fmt(today)}"
            )
            await message.answer(reply, parse_mode="HTML")

            if budget_msg:
                await message.answer(budget_msg)
        except Exception:
            session.rollback()
            logger.exception("Failed to log personal expense")
            await message.answer("\u26a0\ufe0f Failed to log expense. Please try again.")
        finally:
            session.close()
        return

    # ---- LEND ----
    if ptype == "lend":
        if not amount or amount <= 0:
            await message.answer(
                "\U0001f914 How much did you lend? "
                "e.g. <code>gave Rahul 100 for fees</code>",
                parse_mode="HTML",
            )
            return
        if not friend:
            await message.answer(
                "\U0001f914 Who did you lend to? "
                "e.g. <code>gave Rahul 100 for fees</code>",
                parse_mode="HTML",
            )
            return

        session = SessionLocal()
        try:
            f = _get_or_create_friend(session, uid, friend)
            f.balance += amount
            tx = FriendTransaction(
                user_id=uid,
                friend_name=f.friend_name,
                amount=amount,
                description=description or "lent",
                type="lend",
            )
            session.add(tx)
            session.commit()

            reply = (
                f"\U0001f4dd Logged {fmt(amount)} to <b>{f.friend_name.title()}</b>"
                f" for <b>{description or 'lent'}</b>.\n"
                f"{f.friend_name.title()} now owes you a total of {fmt(f.balance)}."
            )
            await message.answer(reply, parse_mode="HTML")
        except Exception:
            session.rollback()
            logger.exception("Failed to log lend")
            await message.answer("\u26a0\ufe0f Failed to record. Please try again.")
        finally:
            session.close()
        return

    # ---- BORROW ----
    if ptype == "borrow":
        if not amount or amount <= 0:
            await message.answer(
                "\U0001f914 How much did you borrow? "
                "e.g. <code>Priya gave me 300 for concert</code>",
                parse_mode="HTML",
            )
            return
        if not friend:
            await message.answer(
                "\U0001f914 Who did you borrow from? "
                "e.g. <code>Priya gave me 300 for concert</code>",
                parse_mode="HTML",
            )
            return

        session = SessionLocal()
        try:
            f = _get_or_create_friend(session, uid, friend)
            f.balance -= amount
            tx = FriendTransaction(
                user_id=uid,
                friend_name=f.friend_name,
                amount=amount,
                description=description or "borrowed",
                type="borrow",
            )
            session.add(tx)
            session.commit()

            if f.balance < 0:
                reply = (
                    f"\U0001f4dd Borrowed {fmt(amount)} from <b>{f.friend_name.title()}</b>"
                    f" for <b>{description or 'borrowed'}</b>.\n"
                    f"You owe {f.friend_name.title()} a total of {fmt(abs(f.balance))}."
                )
            else:
                reply = (
                    f"\U0001f4dd Borrowed {fmt(amount)} from <b>{f.friend_name.title()}</b>.\n"
                    f"Net balance: {f.friend_name.title()} owes you {fmt(f.balance)}."
                )
            await message.answer(reply, parse_mode="HTML")
        except Exception:
            session.rollback()
            logger.exception("Failed to log borrow")
            await message.answer("\u26a0\ufe0f Failed to record. Please try again.")
        finally:
            session.close()
        return

    # ---- SETTLE ----
    if ptype == "settle":
        if not amount or amount <= 0:
            await message.answer(
                "\U0001f914 How much was settled? "
                "e.g. <code>Rahul paid me back 50</code>",
                parse_mode="HTML",
            )
            return
        if not friend:
            await message.answer(
                "\U0001f914 Who settled with you? "
                "e.g. <code>Rahul paid me back 50</code>",
                parse_mode="HTML",
            )
            return

        session = SessionLocal()
        try:
            f = _get_or_create_friend(session, uid, friend)
            f.balance -= amount
            tx = FriendTransaction(
                user_id=uid,
                friend_name=f.friend_name,
                amount=amount,
                description=description or "settlement",
                type="settle",
            )
            session.add(tx)
            session.commit()

            if f.balance > 0:
                reply = (
                    f"\U0001f4b8 Settled {fmt(amount)} with <b>{f.friend_name.title()}</b>.\n"
                    f"{f.friend_name.title()} still owes you {fmt(f.balance)}."
                )
            elif f.balance < 0:
                reply = (
                    f"\U0001f4b8 Settled {fmt(amount)} with <b>{f.friend_name.title()}</b>.\n"
                    f"You now owe {f.friend_name.title()} {fmt(abs(f.balance))}."
                )
            else:
                reply = (
                    f"\U0001f4b8 Settled {fmt(amount)} with <b>{f.friend_name.title()}</b>.\n"
                    f"Balance is now cleared! \U0001f389"
                )
            await message.answer(reply, parse_mode="HTML")
        except Exception:
            session.rollback()
            logger.exception("Failed to log settle")
            await message.answer("\u26a0\ufe0f Failed to record. Please try again.")
        finally:
            session.close()
        return

    # ---- QUERY ----
    if ptype == "query":
        session = SessionLocal()
        try:
            if friend:
                friend_norm = normalise_name(friend)
                f = (
                    session.query(Friend)
                    .filter(Friend.user_id == uid, Friend.friend_name == friend_norm)
                    .first()
                )
                if not f:
                    await message.answer(
                        f"\U0001f50d No record found for <b>{friend_norm.title()}</b>.",
                        parse_mode="HTML",
                    )
                    return

                if f.balance > 0:
                    reply = (
                        f"\U0001f4b0 <b>{f.friend_name.title()}</b> owes you "
                        f"<b>{fmt(f.balance)}</b>."
                    )
                elif f.balance < 0:
                    reply = (
                        f"\U0001f4b0 You owe <b>{f.friend_name.title()}</b> "
                        f"<b>{fmt(abs(f.balance))}</b>."
                    )
                else:
                    reply = (
                        f"\u2705 You and <b>{f.friend_name.title()}</b> "
                        f"are all settled up!"
                    )

                # Add settle button if there's an outstanding balance
                keyboard = None
                if f.balance != 0:
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(
                            text="\U0001f4b0 Settle Completely",
                            callback_data=f"settle_{f.friend_name}",
                        )]
                    ])
                await message.answer(reply, parse_mode="HTML", reply_markup=keyboard)
            else:
                # Show all friend balances
                friends = (
                    session.query(Friend)
                    .filter(Friend.user_id == uid, Friend.balance != 0)
                    .all()
                )
                if not friends:
                    await message.answer(
                        "\U0001f389 No outstanding balances with anyone!"
                    )
                    return
                lines = ["\U0001f4cb <b>All Friend Balances:</b>\n"]
                for f in sorted(friends, key=lambda x: -x.balance):
                    if f.balance > 0:
                        lines.append(
                            f"\u2022 {f.friend_name.title()} owes you: {fmt(f.balance)}"
                        )
                    else:
                        lines.append(
                            f"\u2022 You owe {f.friend_name.title()}: {fmt(abs(f.balance))}"
                        )
                await message.answer("\n".join(lines), parse_mode="HTML")
        finally:
            session.close()
        return

    # ---- BUDGET ----
    if ptype == "budget":
        if not budget_amount or budget_amount <= 0:
            await message.answer(
                "\U0001f914 What's the budget amount? "
                "e.g. <code>set budget 3000 for food this month</code>",
                parse_mode="HTML",
            )
            return
        if not category:
            await message.answer(
                "\U0001f914 What category? "
                "e.g. <code>set budget 3000 for food this month</code>",
                parse_mode="HTML",
            )
            return

        cat = category.lower().strip()
        month = current_month_str()

        session = SessionLocal()
        try:
            existing = (
                session.query(Budget)
                .filter(
                    Budget.user_id == uid,
                    Budget.category == cat,
                    Budget.month == month,
                )
                .first()
            )
            if existing:
                existing.limit_amount = budget_amount
            else:
                session.add(Budget(
                    user_id=uid, category=cat,
                    limit_amount=budget_amount, month=month,
                ))
            session.commit()

            await message.answer(
                f"\U0001f4cb Budget set! <b>{cat.title()}</b>: "
                f"{fmt(budget_amount)} for {month_name_from_str(month)}.\n"
                f"Track progress with /budgets",
                parse_mode="HTML",
            )
        except Exception:
            session.rollback()
            logger.exception("Failed to set budget")
            await message.answer("\u26a0\ufe0f Failed to set budget. Please try again.")
        finally:
            session.close()
        return

    # Fallback
    await message.answer(
        "\U0001f914 I didn't quite catch that. Try: "
        "<code>spent 200 on food</code>",
        parse_mode="HTML",
    )
"""SQLAlchemy ORM models and database session management."""
from datetime import datetime, timezone
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    Float,
    Text,
    DateTime,
    select,
    func,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    scoped_session,
    sessionmaker,
    Mapped,
    mapped_column,
)

from config import DB_URL


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Table 1 — personal_expenses
# ---------------------------------------------------------------------------
class PersonalExpense(Base):
    __tablename__ = "personal_expenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    date: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


# ---------------------------------------------------------------------------
# Table 2 — friends
# ---------------------------------------------------------------------------
class Friend(Base):
    __tablename__ = "friends"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    friend_name: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    balance: Mapped[float] = mapped_column(Float, default=0.0)


# ---------------------------------------------------------------------------
# Table 3 — friend_transactions
# ---------------------------------------------------------------------------
class FriendTransaction(Base):
    __tablename__ = "friend_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    friend_name: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    type: Mapped[str] = mapped_column(Text, nullable=False)  # lend / borrow / settle
    date: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


# ---------------------------------------------------------------------------
# Table 4 — budgets
# ---------------------------------------------------------------------------
class Budget(Base):
    __tablename__ = "budgets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    limit_amount: Mapped[float] = mapped_column(Float, nullable=False)
    month: Mapped[str] = mapped_column(Text, nullable=False)  # "2024-10"


# ---------------------------------------------------------------------------
# Engine & session
# ---------------------------------------------------------------------------
engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
SessionLocal = scoped_session(sessionmaker(bind=engine))


def init_db() -> None:
    """Create all tables if they don't exist."""
    Base.metadata.create_all(bind=engine)


def get_session():
    """Return a new session (use in async with run_sync)."""
    return SessionLocal()
"""SQLite data layer for Spendly.

Raw sqlite3 (stdlib) only — no ORM. All SQL uses parameterized (?) placeholders.
"""

import calendar
import os
import sqlite3
from datetime import date, datetime

from werkzeug.security import generate_password_hash

# <project_root>/expense_tracker.db, independent of the caller's cwd.
DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "expense_tracker.db",
)

CATEGORIES = [
    "Food",
    "Transport",
    "Bills",
    "Health",
    "Entertainment",
    "Shopping",
    "Other",
]


def get_db():
    """Open a new SQLite connection with dict-like rows and FK enforcement."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create tables if they don't already exist. Safe to call repeatedly."""
    conn = get_db()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                category TEXT NOT NULL,
                date TEXT NOT NULL,
                description TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def create_user(name, email, password):
    """Insert a new user with a hashed password. Returns the new user's id.

    Raises sqlite3.IntegrityError if the email is already taken.
    """
    conn = get_db()
    try:
        password_hash = generate_password_hash(password)
        cursor = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            (name, email, password_hash),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_user_by_email(email):
    """Return the user row for email, or None if no match."""
    conn = get_db()
    try:
        return conn.execute(
            "SELECT * FROM users WHERE email = ?", (email,)
        ).fetchone()
    finally:
        conn.close()


def _format_member_since(created_at_text):
    """Format a SQLite 'YYYY-MM-DD HH:MM:SS' string as 'Month YYYY'."""
    dt = datetime.strptime(created_at_text.split(" ")[0], "%Y-%m-%d")
    return dt.strftime("%B %Y")


def get_user_by_id(user_id):
    """Return a dict with the user's name, email, initials, and formatted
    member-since date, or None if no such user exists."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id, name, email, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            return None
        initials = "".join(part[0].upper() for part in row["name"].split()[:2])
        return {
            "id": row["id"],
            "name": row["name"],
            "email": row["email"],
            "initials": initials,
            "created_at": _format_member_since(row["created_at"]),
        }
    finally:
        conn.close()


def get_summary_stats(user_id):
    """Return total spent, transaction count, and top category for a user.
    Returns zeros / '—' if the user has no expenses."""
    conn = get_db()
    try:
        total_row = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total, COUNT(*) AS n "
            "FROM expenses WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        top_row = conn.execute(
            "SELECT category, SUM(amount) AS cat_total FROM expenses "
            "WHERE user_id = ? GROUP BY category ORDER BY cat_total DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        return {
            "total_spent": round(total_row["total"], 2),
            "transaction_count": total_row["n"],
            "top_category": top_row["category"] if top_row else "—",
        }
    finally:
        conn.close()


def get_recent_transactions(user_id, limit=10):
    """Return the user's most recent expenses, newest first."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT date, description, category, amount FROM expenses "
            "WHERE user_id = ? ORDER BY date DESC, id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [
            {
                "date": r["date"],
                "description": r["description"],
                "category": r["category"],
                "amount": r["amount"],
            }
            for r in rows
        ]
    finally:
        conn.close()


def get_category_breakdown(user_id):
    """Return per-category totals as integer percentages of the user's
    overall spend, ordered by total descending. Percentages always sum to
    exactly 100 — the largest-spend category absorbs the rounding remainder.
    Returns [] if the user has no expenses."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT category, SUM(amount) AS total FROM expenses "
            "WHERE user_id = ? GROUP BY category ORDER BY total DESC",
            (user_id,),
        ).fetchall()
        if not rows:
            return []

        totals = [(r["category"], r["total"]) for r in rows]
        grand_total = sum(total for _, total in totals)

        floored = [(cat, int(total / grand_total * 100)) for cat, total in totals]
        remainder = 100 - sum(pct for _, pct in floored)

        largest_category = totals[0][0]
        return [
            {
                "category": cat,
                "pct": pct + remainder if cat == largest_category else pct,
            }
            for cat, pct in floored
        ]
    finally:
        conn.close()


def seed_db():
    """Insert one demo user + 8 sample expenses. No-op if users already has rows."""
    conn = get_db()
    try:
        row = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()
        if row["n"] > 0:
            return

        password_hash = generate_password_hash("demo123")
        cursor = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            ("Demo User", "demo@spendly.com", password_hash),
        )
        user_id = cursor.lastrowid

        # Build dates from today's year/month (clamped to the month's day count)
        # rather than date.today() - timedelta(...), which can roll into the
        # previous month when run early in a month and silently break the
        # "current month" requirement.
        today = date.today()
        year, month = today.year, today.month
        days_in_month = calendar.monthrange(year, month)[1]

        def month_day(day_number):
            return date(year, month, min(day_number, days_in_month)).strftime("%Y-%m-%d")

        sample_expenses = [
            (user_id, 12.50, "Food", month_day(1), "Lunch at cafe"),
            (user_id, 45.00, "Transport", month_day(4), "Monthly bus pass top-up"),
            (user_id, 89.99, "Bills", month_day(7), "Electricity bill"),
            (user_id, 25.00, "Health", month_day(10), "Pharmacy"),
            (user_id, 15.00, "Entertainment", month_day(13), "Movie ticket"),
            (user_id, 60.75, "Shopping", month_day(17), "New shoes"),
            (user_id, 10.00, "Other", month_day(21), "Miscellaneous"),
            (user_id, 32.20, "Food", month_day(25), "Groceries"),
        ]

        conn.executemany(
            """
            INSERT INTO expenses (user_id, amount, category, date, description)
            VALUES (?, ?, ?, ?, ?)
            """,
            sample_expenses,
        )
        conn.commit()
    finally:
        conn.close()

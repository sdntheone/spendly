"""SQLite data layer for Spendly.

Raw sqlite3 (stdlib) only — no ORM. All SQL uses parameterized (?) placeholders.
"""

import calendar
import os
import sqlite3
from datetime import date

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

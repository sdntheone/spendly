"""Tests for the /profile date-range filter (Step 6).

Spec: .claude/specs/06-date-filter-profile-page.md

These tests exercise behavior only (query params in, rendered page /
DB-backed stats out) — they do not assume anything about the internal
implementation beyond the documented function signatures in
database/db.py (get_summary_stats, get_recent_transactions,
get_category_breakdown all accept optional start_date/end_date kwargs).

DB isolation note: database/db.py's get_db() opens sqlite3.connect(DB_PATH)
against a fixed on-disk path computed at import time — there is no
app.config['DATABASE'] hook and ':memory:' would not survive across the
multiple independent connections each helper opens. Instead, each test
gets a fresh temp-file DB by monkeypatching database.db.DB_PATH before
calling init_db(), which keeps tests fully isolated and deterministic.
"""
import os

import pytest

import database.db as db
from app import app as flask_app


# ------------------------------------------------------------------ #
# Fixtures                                                             #
# ------------------------------------------------------------------ #

@pytest.fixture
def app(tmp_path, monkeypatch):
    """Flask app wired to a fresh, isolated sqlite file per test."""
    db_path = tmp_path / "test_expense_tracker.db"
    monkeypatch.setattr(db, "DB_PATH", str(db_path))

    flask_app.config.update({"TESTING": True, "SECRET_KEY": "test-secret"})

    db.init_db()
    yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def seeded_user(app):
    """A user with 8 hand-placed expenses spanning a known date range,
    independent of seed_db()'s "current month" convenience logic so
    range-filter math in tests is fully deterministic.

    Dates chosen in January 2024:
      2024-01-01  Food          12.50
      2024-01-04  Transport     45.00
      2024-01-07  Bills         89.99
      2024-01-10  Health        25.00
      2024-01-13  Entertainment 15.00
      2024-01-17  Shopping      60.75
      2024-01-21  Other         10.00
      2024-01-25  Food          32.20

    Total (all 8): 290.44
    """
    user_id = db.create_user("Test User", "testuser@example.com", "testpass123")

    expenses = [
        (user_id, 12.50, "Food", "2024-01-01", "Lunch at cafe"),
        (user_id, 45.00, "Transport", "2024-01-04", "Monthly bus pass top-up"),
        (user_id, 89.99, "Bills", "2024-01-07", "Electricity bill"),
        (user_id, 25.00, "Health", "2024-01-10", "Pharmacy"),
        (user_id, 15.00, "Entertainment", "2024-01-13", "Movie ticket"),
        (user_id, 60.75, "Shopping", "2024-01-17", "New shoes"),
        (user_id, 10.00, "Other", "2024-01-21", "Miscellaneous"),
        (user_id, 32.20, "Food", "2024-01-25", "Groceries"),
    ]
    conn = db.get_db()
    try:
        conn.executemany(
            "INSERT INTO expenses (user_id, amount, category, date, description) "
            "VALUES (?, ?, ?, ?, ?)",
            expenses,
        )
        conn.commit()
    finally:
        conn.close()

    return {"id": user_id, "email": "testuser@example.com", "password": "testpass123"}


@pytest.fixture
def auth_client(client, seeded_user):
    """A test client logged in as the seeded user."""
    response = client.post(
        "/login",
        data={"email": seeded_user["email"], "password": seeded_user["password"]},
        follow_redirects=False,
    )
    assert response.status_code == 302, "Login with seeded credentials should redirect"
    return client


# ------------------------------------------------------------------ #
# Auth guard                                                          #
# ------------------------------------------------------------------ #

class TestProfileAuthGuard:
    def test_profile_requires_login_redirects_to_login(self, client):
        response = client.get("/profile")
        assert response.status_code == 302, "Unauthenticated /profile should redirect"
        assert "/login" in response.headers["Location"], (
            "Unauthenticated /profile should redirect to /login"
        )

    def test_profile_with_filter_params_still_requires_login(self, client):
        response = client.get("/profile?start_date=2024-01-01&end_date=2024-01-10")
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]


# ------------------------------------------------------------------ #
# Unfiltered baseline                                                  #
# ------------------------------------------------------------------ #

class TestUnfilteredBaseline:
    def test_no_query_params_shows_all_time_data(self, auth_client):
        response = auth_client.get("/profile")
        assert response.status_code == 200
        body = response.data.decode()

        assert "290.44" in body, "All-time total spent should be 290.44"
        # 8 transactions total; each seeded description should appear.
        for desc in [
            "Lunch at cafe",
            "Monthly bus pass top-up",
            "Electricity bill",
            "Pharmacy",
            "Movie ticket",
            "New shoes",
            "Miscellaneous",
            "Groceries",
        ]:
            assert desc in body, f"Expected unfiltered transaction '{desc}' in page"

    def test_no_query_params_no_clear_filter_link(self, auth_client):
        response = auth_client.get("/profile")
        body = response.data.decode()
        assert "Clear filter" not in body, (
            "Clear filter link must not appear when no filter is active"
        )

    def test_no_query_params_date_inputs_empty(self, auth_client):
        response = auth_client.get("/profile")
        body = response.data.decode()
        assert 'id="start_date"' in body
        assert 'id="end_date"' in body

        import re
        start_match = re.search(
            r'id="start_date"[^>]*value="([^"]*)"', body
        ) or re.search(r'name="start_date"[^>]*value="([^"]*)"', body)
        end_match = re.search(
            r'id="end_date"[^>]*value="([^"]*)"', body
        ) or re.search(r'name="end_date"[^>]*value="([^"]*)"', body)

        assert start_match is not None, "Could not locate start_date input in rendered page"
        assert end_match is not None, "Could not locate end_date input in rendered page"
        assert start_match.group(1) == "", "start_date input should be empty when unfiltered"
        assert end_match.group(1) == "", "end_date input should be empty when unfiltered"


# ------------------------------------------------------------------ #
# Correct subset filtering                                            #
# ------------------------------------------------------------------ #

class TestSubsetFiltering:
    def test_filter_range_returns_correct_transaction_subset(self, auth_client):
        # Covers 2024-01-04 through 2024-01-13 inclusive: Transport, Bills, Health, Entertainment
        response = auth_client.get(
            "/profile?start_date=2024-01-04&end_date=2024-01-13"
        )
        assert response.status_code == 200
        body = response.data.decode()

        for desc in ["Monthly bus pass top-up", "Electricity bill", "Pharmacy", "Movie ticket"]:
            assert desc in body, f"Expected in-range transaction '{desc}' in filtered page"

        for desc in ["Lunch at cafe", "New shoes", "Miscellaneous", "Groceries"]:
            assert desc not in body, f"Out-of-range transaction '{desc}' should be excluded"

    def test_filter_range_summary_stats_recalculate(self, auth_client):
        # 2024-01-04 to 2024-01-13: 45.00 + 89.99 + 25.00 + 15.00 = 174.99, 4 transactions
        response = auth_client.get(
            "/profile?start_date=2024-01-04&end_date=2024-01-13"
        )
        body = response.data.decode()
        assert "174.99" in body, "Filtered total_spent should be 174.99"
        assert ">4<" in body, "Filtered transaction_count should be 4"

    def test_filter_range_top_category_recalculates(self, auth_client):
        # Bills (89.99) is the single largest expense in this range.
        response = auth_client.get(
            "/profile?start_date=2024-01-04&end_date=2024-01-13"
        )
        body = response.data.decode()
        assert "Bills" in body

    def test_filter_range_category_breakdown_sums_to_100(self, auth_client):
        response = auth_client.get(
            "/profile?start_date=2024-01-04&end_date=2024-01-13"
        )
        body = response.data.decode()
        # Pull all "width: NN%" occurrences from breakdown bars.
        import re
        pcts = [int(m) for m in re.findall(r"width:\s*(\d+)%", body)]
        assert pcts, "Expected at least one category breakdown bar"
        assert sum(pcts) == 100, f"Breakdown percentages should sum to 100, got {pcts}"

    def test_filter_single_day_range_inclusive(self, auth_client):
        # Single-day range where start_date == end_date should include that day's expense.
        response = auth_client.get(
            "/profile?start_date=2024-01-07&end_date=2024-01-07"
        )
        body = response.data.decode()
        assert "Electricity bill" in body, "Boundary date should be included (inclusive range)"
        assert "89.99" in body

    def test_filter_boundary_dates_are_inclusive(self, auth_client):
        # Range exactly matching first and last expense dates should include both endpoints.
        response = auth_client.get(
            "/profile?start_date=2024-01-01&end_date=2024-01-25"
        )
        body = response.data.decode()
        assert "Lunch at cafe" in body, "Range start boundary should be inclusive"
        assert "Groceries" in body, "Range end boundary should be inclusive"


# ------------------------------------------------------------------ #
# Invalid range fallback (start after end)                            #
# ------------------------------------------------------------------ #

class TestInvalidRangeFallback:
    def test_start_after_end_falls_back_to_all_time_data(self, auth_client):
        response = auth_client.get(
            "/profile?start_date=2024-01-20&end_date=2024-01-01"
        )
        assert response.status_code == 200, "Invalid range must not error"
        body = response.data.decode()
        assert "290.44" in body, "Should fall back to all-time total"
        for desc in ["Lunch at cafe", "Groceries"]:
            assert desc in body

    def test_start_after_end_no_clear_filter_link(self, auth_client):
        response = auth_client.get(
            "/profile?start_date=2024-01-20&end_date=2024-01-01"
        )
        body = response.data.decode()
        assert "Clear filter" not in body, (
            "Clear filter should not show when the range was rejected as invalid"
        )


# ------------------------------------------------------------------ #
# Malformed date fallback                                             #
# ------------------------------------------------------------------ #

class TestMalformedDateFallback:
    @pytest.mark.parametrize(
        "start_date,end_date",
        [
            ("not-a-date", "2024-01-10"),
            ("2024-01-01", "not-a-date"),
            ("2024-13-40", "2024-01-10"),
            ("2024/01/01", "2024/01/10"),
            ("", "2024-01-10"),
            ("2024-01-01", ""),
            ("<script>alert(1)</script>", "2024-01-10"),
            ("2024-01-01'; DROP TABLE expenses;--", "2024-01-10"),
        ],
    )
    def test_malformed_dates_fall_back_to_all_time_no_error(
        self, auth_client, start_date, end_date
    ):
        response = auth_client.get(
            f"/profile?start_date={start_date}&end_date={end_date}"
        )
        assert response.status_code == 200, (
            f"Malformed dates ({start_date!r}, {end_date!r}) must not raise an error page"
        )
        body = response.data.decode()
        assert "290.44" in body, "Should fall back to all-time total on malformed input"

    def test_malformed_dates_do_not_break_subsequent_queries(self, auth_client):
        # Sanity: a malformed filter followed by a valid request both work.
        bad = auth_client.get("/profile?start_date=garbage&end_date=garbage")
        assert bad.status_code == 200
        good = auth_client.get("/profile?start_date=2024-01-01&end_date=2024-01-04")
        assert good.status_code == 200
        assert "Lunch at cafe" in good.data.decode()


# ------------------------------------------------------------------ #
# Only one param supplied                                             #
# ------------------------------------------------------------------ #

class TestPartialParamsFallback:
    def test_only_start_date_falls_back_to_all_time(self, auth_client):
        response = auth_client.get("/profile?start_date=2024-01-01")
        assert response.status_code == 200
        body = response.data.decode()
        assert "290.44" in body

    def test_only_end_date_falls_back_to_all_time(self, auth_client):
        response = auth_client.get("/profile?end_date=2024-01-10")
        assert response.status_code == 200
        body = response.data.decode()
        assert "290.44" in body

    def test_only_start_date_no_clear_filter_link(self, auth_client):
        response = auth_client.get("/profile?start_date=2024-01-01")
        body = response.data.decode()
        assert "Clear filter" not in body


# ------------------------------------------------------------------ #
# Zero-match range                                                    #
# ------------------------------------------------------------------ #

class TestZeroMatchRange:
    def test_zero_match_range_shows_zero_total_and_no_errors(self, auth_client):
        # Valid range with no overlapping expenses (well outside January 2024).
        response = auth_client.get(
            "/profile?start_date=2024-06-01&end_date=2024-06-30"
        )
        assert response.status_code == 200, "Zero-match range must not error"
        body = response.data.decode()
        assert "0.00" in body, "Total spent should render as ₹0.00"

    def test_zero_match_range_transaction_count_is_zero(self, auth_client):
        response = auth_client.get(
            "/profile?start_date=2024-06-01&end_date=2024-06-30"
        )
        body = response.data.decode()
        assert ">0<" in body, "Transaction count should be 0"
        for desc in ["Lunch at cafe", "Groceries", "Electricity bill"]:
            assert desc not in body, "No expenses should appear for a zero-match range"

    def test_zero_match_range_empty_category_breakdown(self, auth_client):
        response = auth_client.get(
            "/profile?start_date=2024-06-01&end_date=2024-06-30"
        )
        body = response.data.decode()
        assert "breakdown-row" not in body, (
            "Category breakdown should render no rows for a zero-match range"
        )

    def test_zero_match_range_still_shows_clear_filter(self, auth_client):
        # A zero-match range is still a *valid* active filter (start <= end,
        # both well-formed) — Clear filter should be available to escape it.
        response = auth_client.get(
            "/profile?start_date=2024-06-01&end_date=2024-06-30"
        )
        body = response.data.decode()
        assert "Clear filter" in body, (
            "A valid (even if zero-match) filter should still show Clear filter"
        )


# ------------------------------------------------------------------ #
# Sticky form values                                                  #
# ------------------------------------------------------------------ #

class TestStickyFormValues:
    def test_valid_filter_values_retained_in_inputs(self, auth_client):
        response = auth_client.get(
            "/profile?start_date=2024-01-04&end_date=2024-01-13"
        )
        body = response.data.decode()
        assert 'value="2024-01-04"' in body, "start_date input should retain submitted value"
        assert 'value="2024-01-13"' in body, "end_date input should retain submitted value"

    def test_invalid_range_does_not_retain_values(self, auth_client):
        # Per spec, an invalid/rejected range falls back to unfiltered data;
        # the inputs should reflect that fallback (empty), not the rejected input.
        response = auth_client.get(
            "/profile?start_date=2024-01-20&end_date=2024-01-01"
        )
        body = response.data.decode()
        assert 'value="2024-01-20"' not in body
        assert 'value="2024-01-01"' not in body


# ------------------------------------------------------------------ #
# Clear filter link presence/absence                                  #
# ------------------------------------------------------------------ #

class TestClearFilterLink:
    def test_clear_filter_present_when_valid_filter_active(self, auth_client):
        response = auth_client.get(
            "/profile?start_date=2024-01-04&end_date=2024-01-13"
        )
        body = response.data.decode()
        assert "Clear filter" in body

    def test_clear_filter_link_points_to_plain_profile(self, auth_client):
        response = auth_client.get(
            "/profile?start_date=2024-01-04&end_date=2024-01-13"
        )
        body = response.data.decode()
        assert 'href="/profile"' in body, "Clear filter should link to unfiltered /profile"

    def test_clicking_clear_filter_returns_unfiltered_data(self, auth_client):
        auth_client.get("/profile?start_date=2024-01-04&end_date=2024-01-13")
        response = auth_client.get("/profile")
        body = response.data.decode()
        assert "290.44" in body
        assert "Clear filter" not in body

    def test_clear_filter_absent_when_no_filter(self, auth_client):
        response = auth_client.get("/profile")
        assert "Clear filter" not in response.data.decode()

    def test_clear_filter_absent_when_malformed_filter(self, auth_client):
        response = auth_client.get("/profile?start_date=bad&end_date=2024-01-10")
        assert "Clear filter" not in response.data.decode()

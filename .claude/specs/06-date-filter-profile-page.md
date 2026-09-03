# Spec: Date Filter For Profile Page

## Overview
Step 6 adds a date-range filter to the `/profile` page so a user can narrow
the recent transactions list and category breakdown down to a specific
window (e.g. "this month", "last 30 days", or a custom range) instead of
always seeing the unfiltered dataset. The summary stats, transaction list,
and category breakdown all currently query a user's full expense history
unconditionally (`database/db.py`); this step makes those queries
date-aware and adds the UI controls to drive them via query-string
parameters on `GET /profile`.

## Depends on
- Step 1: Database setup (`expenses` table with a `date` column)
- Step 2: Registration (users exist)
- Step 3: Login / Logout (`session["user_id"]` is set on login)
- Step 4: Profile page static UI (template structure already in place)
- Step 5: Backend Connection (`/profile` already renders live summary
  stats, recent transactions, and category breakdown from the database)

## Routes
- `GET /profile` — modified, not new — access level: logged-in
  - Accepts optional query-string params `start_date` and `end_date`
    (format `YYYY-MM-DD`)
  - When both are present and valid, summary stats, transactions, and
    category breakdown are filtered to that inclusive date range
  - When absent or invalid, behavior is unchanged (all-time data, same as
    Step 5)

If no new routes: N/A — `GET /profile` is extended in place.

## Database changes
No database changes. The `expenses.date` column (`TEXT`, `YYYY-MM-DD`)
already exists and is sufficient for range filtering with `?` placeholders
in a `BETWEEN` or `>=`/`<=` clause.

## Templates
- **Create:** None
- **Modify:** `templates/profile.html`
  - Add a date-range filter form (two date inputs + submit) above the
    "Recent transactions" panel, submitting via `GET` to `/profile` so the
    range persists in the URL and survives a refresh
  - Add a "Clear filter" link (plain `<a href="{{ url_for('profile') }}">`)
    shown only when a filter is active
  - Reflect the currently active range back into the date input values so
    the form doesn't reset on reload

## Files to change
- `app.py` — read `start_date`/`end_date` from `request.args` in the
  `profile()` view, validate them, and pass them through to the three
  data-fetching functions
- `database/db.py` — extend `get_summary_stats`, `get_recent_transactions`,
  and `get_category_breakdown` to accept optional `start_date`/`end_date`
  keyword arguments and append a parameterized date filter to each query
  when both are provided
- `templates/profile.html` — add the filter form and clear-filter link
- `static/css/profile.css` — style the new filter form using existing CSS
  variables

## Files to create
None.

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only — date bounds passed as `?` placeholders,
  never string-formatted into SQL
- Passwords hashed with werkzeug (unaffected by this step, carried over
  as a standing rule)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Invalid or malformed dates in `start_date`/`end_date` must be ignored
  (fall back to unfiltered, all-time data) rather than raising an error
- If only one of `start_date`/`end_date` is supplied, treat the filter as
  inactive and fall back to unfiltered data — don't guess the missing bound
- `start_date` must not be after `end_date`; if it is, ignore the filter
  and fall back to unfiltered data
- Filtering must be inclusive of both `start_date` and `end_date`
- No inline styles

## Definition of done
- [ ] Visiting `/profile` with no query params shows the same all-time
      data as before this change
- [ ] Submitting a date range that covers only some of the seed user's 8
      expenses shows the correct subset in the transaction list
- [ ] Summary stats (`total_spent`, `transaction_count`, `top_category`)
      recalculate correctly for the filtered range
- [ ] Category breakdown percentages recalculate for the filtered range
      and still sum to 100%
- [ ] The date inputs retain the submitted `start_date`/`end_date` values
      after the page reloads
- [ ] A "Clear filter" control is visible only when a filter is active,
      and clicking it returns to the unfiltered `/profile` view
- [ ] Submitting `start_date` after `end_date` shows unfiltered (all-time)
      data, not an error page
- [ ] Submitting a malformed date value shows unfiltered (all-time) data,
      not an error page
- [ ] Filtering to a range with zero matching expenses shows ₹0.00 total
      spent, 0 transactions, and an empty category breakdown — no errors

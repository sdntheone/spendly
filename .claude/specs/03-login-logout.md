# Spec: Login and Logout

## Overview
Implement user authentication so registered users can sign in and out of Spendly. This step upgrades the existing stub `GET /login` route into a fully functional form that validates credentials against the `users` table and establishes a Flask session. It also implements the `GET /logout` stub to clear that session. This is the entry point for all subsequent authenticated features (profile, expenses).

## Depends on
- Step 01 — Database setup (`users` table, `get_db()`)
- Step 02 — Registration (`create_user()`, users can already sign up with hashed passwords)

## Routes
- `GET /login` — render login form — public (already exists as stub, upgrade it)
- `POST /login` — validate credentials, start session, redirect to `/profile` — public
- `GET /logout` — clear session, redirect to `/login` — logged-in (currently a stub returning raw text)

## Database changes
No new tables or columns. The existing `users` table (id, name, email, password_hash, created_at) covers all requirements. Sessions are handled via Flask's signed cookie session (`flask.session`), not a DB-backed session table.

A new DB helper must be added to `database/db.py`:
- `get_user_by_email(email)` — returns the user row (including `password_hash`) for the given email, or `None` if no match. Parameterized query only.

## Templates
- **Modify**: `templates/login.html`
  - Change the form `action` from the hardcoded `/login` to `{{ url_for('login') }}` with `method="post"`
  - Add a block to display a flashed error message for invalid credentials (the template already has an `{% if error %}` block wired to a local `error` var — align this with the flash-message pattern used in `register.html` for consistency, or keep `error` if simpler; either way every internal link must use `url_for()`)
- **Modify**: `templates/base.html`
  - Nav currently always shows "Sign in" / "Get started" — no change required for this step since there's no session-aware nav yet; leave as-is unless trivial to guard behind `session.get('user_id')` (optional, not required for definition of done)

## Files to change
- `app.py` — upgrade `login()` to handle `GET` and `POST`; implement `logout()` to clear session and redirect
- `database/db.py` — add `get_user_by_email()` helper
- `templates/login.html` — wire up form action and confirm error display

## Files to create
None.

## New dependencies
No new dependencies. Uses `werkzeug.security.check_password_hash` (already available via existing `werkzeug` install) and Flask's built-in `session`, `flash`, `redirect`, `url_for`.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only — never use f-strings in SQL
- Passwords hashed with werkzeug — verify with `werkzeug.security.check_password_hash`, never compare plaintext
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Use `url_for()` for every internal link — never hardcode URLs
- On `POST /login` with an unknown email or wrong password, re-render the form with a generic error (e.g. "Invalid email or password") — never reveal which field was wrong
- On success, store `user_id` in `flask.session` and redirect to `url_for('profile')`
- `GET /logout` must clear the session (`session.clear()` or `session.pop('user_id', None)`) and redirect to `url_for('login')`
- Use `abort(405)` if an unsupported HTTP method reaches `/login`
- Do not implement route protection / login-required decorators for other stub routes (`/profile`, `/expenses/*`) in this step — that belongs to their own steps; `/profile` may remain a stub, login only needs to redirect there

## Definition of done
- [ ] `GET /login` renders the login form without errors
- [ ] Submitting valid credentials (matching a row in `users`) sets a session and redirects to `/profile`
- [ ] Submitting an unknown email re-renders the form with a generic invalid-credentials error, no session set
- [ ] Submitting a known email with the wrong password re-renders the form with the same generic error, no session set
- [ ] Visiting `/logout` after logging in clears the session and redirects to `/login`
- [ ] Visiting `/logout` when not logged in does not error — redirects to `/login` regardless
- [ ] No plaintext password comparison anywhere in the code — verifiable by inspecting `app.py` and `database/db.py`

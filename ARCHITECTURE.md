# Architecture

Spendwise is a server-rendered Flask application. The browser sends ordinary requests, Flask
returns finished HTML pages, and a SQLite file stores the data. A little JavaScript improves
the forms, but every page works without it and the server never trusts the browser to
validate anything.

## Project layout

```
spendwise/
├── app/
│   ├── __init__.py        # create_app() factory, environment and secret-key rules
│   ├── db.py              # SQLite connection handling (one connection per request)
│   ├── schema.sql         # the table definition and its constraints
│   ├── repository.py      # ALL SQL lives here
│   ├── services.py        # validation, money formatting, summary calculations
│   ├── routes.py          # URLs, CSRF, redirects, security headers, error pages
│   ├── templates/         # Jinja2 pages (base, dashboard, transactions, form, ...)
│   └── static/
│       ├── css/style.css  # all styling (light and dark schemes)
│       └── js/app.js      # optional form enhancements
├── tests/                 # pytest suite (369 tests)
├── docs/screenshots/      # images used by the README
├── requirements.txt       # Flask and pytest, pinned
└── pytest.ini
```

## Layers

Dependencies point one way: **routes → services → repository → database**. Nothing lower
knows about anything higher.

| Layer | File | Responsibility | Must not |
| --- | --- | --- | --- |
| Routes | `routes.py` | Read the request, call services and the repository, choose a template or redirect | Contain business rules or SQL |
| Services | `services.py` | Turn raw form text into clean values or friendly errors; format money; shape summaries | Know about Flask or HTTP |
| Repository | `repository.py` | Run SQL and return rows | Validate input |
| Database | `schema.sql`, `db.py` | Store data; refuse clearly invalid rows | |

Keeping `services.py` free of Flask means its logic can be tested with plain function calls.

## Request flow

Example: submitting the "Add transaction" form.

1. The browser sends `POST /transactions/new` with the form fields, a hidden `csrf_token` and
   a hidden `next` (where to return afterwards).
2. `_check_csrf` runs before every `POST`. It compares the submitted token with the one in
   the signed session cookie using a constant-time comparison. A mismatch returns **403**.
3. `new_transaction` calls `services.validate_transaction(request.form)`. This checks every
   field and collects *all* errors, not just the first.
4. **If there are errors**, the form is shown again with the user's input preserved, an error
   summary and per-field messages, with status **400**.
5. **If valid**, `repository.create_transaction` inserts the row inside a `with conn:` block,
   which commits on success and rolls back on any exception.
6. The route stores a flash message and redirects with **303 See Other** to the safe `next`
   address, so refreshing the page cannot resubmit the form (Post/Redirect/Get).
7. After every response, `_add_security_headers` adds the security headers.

Pages:

| URL | Methods | Purpose |
| --- | --- | --- |
| `/` | GET | Dashboard. Optional `?month=YYYY-MM` for the category breakdown |
| `/transactions` | GET | List with filters `type`, `category`, `date_from`, `date_to` |
| `/transactions/new` | GET, POST | Add form (optional `?type=income` or `expense`) |
| `/transactions/<id>/edit` | GET, POST | Edit form |
| `/transactions/<id>/delete` | GET, POST | GET shows a confirmation page and deletes nothing; POST deletes |

Unknown IDs, vanished rows and over-large IDs return a 404 page. Other HTTP errors (403, 405,
413) use the same error template, and an unexpected failure shows a generic page without
internal details.

## Database schema

One table, defined in `app/schema.sql`:

```sql
transactions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    type         TEXT    NOT NULL CHECK (type IN ('income', 'expense')),
    category     TEXT    NOT NULL CHECK (length(category) > 0),
    date         TEXT    NOT NULL CHECK (date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    description  TEXT    NOT NULL CHECK (length(description) > 0),
    created_at   TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
)
-- index on date
```

The `CHECK` constraints are a safety net. The services layer validates first and produces
friendly messages; the database independently refuses clearly invalid rows even if a bug lets
one through. The schema script uses `IF NOT EXISTS`, so running it on every start is safe.
There is no migration system.

## Validation (services layer)

| Field | Rules |
| --- | --- |
| Amount | Digits with an optional decimal point and at most two decimals; an optional leading `R` is accepted; greater than zero; at most 9 digits before the decimal point. Only ASCII digits `0-9` are accepted |
| Type | `income` or `expense` |
| Category | Must be on the list for the chosen type |
| Date | `YYYY-MM-DD`, a real calendar date (so `2026-02-30` is rejected), year 1900 to 2100 |
| Description | Required, at most 200 characters, no control characters or line breaks (surrounding whitespace is trimmed) |
| Filters | Every field optional; the same type/category/date rules; the end date must not be before the start date |

Validation errors are `ValidationError` messages written to be shown to users.

Categories are fixed lists in `services.py`. Income: Salary, Freelance, Gift, Other income.
Expense: Food, Transport, Rent, Utilities, Entertainment, Health, Other expense. The two
"Other" names differ so that every category name is unique, which keeps the category filter
unambiguous.

## Key design decisions

**Money is integer cents.** Floating-point numbers cannot represent most decimal amounts
exactly (0.1 + 0.2 is not 0.3), which is unacceptable for money. Text like `150.50` is read
digit by digit into `15050` (no `float`, no `Decimal` in application code), stored as an
integer, summed by SQLite as integers, and turned back into `R150.50` only for display.
Percentages in the category breakdown are whole tenths of a percent, rounded half-up with
integer arithmetic.

**Dates are ISO text.** `YYYY-MM-DD` sorts correctly as plain text, so date filters and
ordering need no conversion, and a month is just the first seven characters. Month links on
the dashboard use `month_bounds` to filter the list to exactly the first through last day.

**All SQL in one place, always parameterised.** Values are passed as `?` parameters. The only
SQL assembled from pieces is the filter `WHERE` clause, built from fixed fragments with the
values bound separately.

**One connection per request**, opened lazily and closed when the request ends.

**Application factory.** `create_app()` builds an app from settings, so tests can create
isolated apps with temporary databases.

**Fail-safe secret key.** An unset `SPENDWISE_ENV` means production. Production refuses to
start without a `SPENDWISE_SECRET_KEY` that is at least 32 characters and is not the
development fallback. The insecure fallback key can only be used when
`SPENDWISE_ENV=development` is set explicitly.

**Hand-written CSRF protection.** Each session gets a random token; every `POST` must send it
back. This is a small amount of code, but it is custom code (see limitations in the README).
The session cookie is also `SameSite=Lax`.

**Safe redirects.** After a form, the user returns to the page they came from (`next`). Only
`/` and `/transactions` (with a query string) are accepted. The address is rebuilt from its
path and query rather than echoed back, so it cannot point to another site. Anything else
falls back to the transaction list.

**Destructive actions use POST and a confirmation page.** A `GET` to the delete address only
shows the page.

**Response hardening.** Every response carries a Content-Security-Policy (own-origin
resources only; inline *styles* are allowed because the category bars set their width
inline; inline scripts are not), `X-Content-Type-Options: nosniff` and
`Referrer-Policy: same-origin`. Requests larger than 16 KiB are refused with a 413. Transaction
IDs in URLs are capped at the largest value SQLite can store.

**Progressive enhancement.** `app.js` focuses the error summary, pre-fills today's date and
narrows the category list to the chosen type. Without it the forms still work; the server
validates the type/category pairing regardless.

**Accessibility choices.** Labelled fields with associated hint and error text,
`aria-invalid` on fields with errors, an error summary that links to fields, semantic tables
with header scopes, visible focus styles and a colour scheme that follows the browser's
light/dark setting. These are design intentions; see the README for what has and has not
been tested.

## Testing

`python -m pytest` runs 369 tests in these files:

| File | What it checks |
| --- | --- |
| `test_services.py` | Parsing and validation edge cases (amounts, dates, leap years, unicode, control characters), money formatting and percentage rounding |
| `test_repository.py` | CRUD, filters (inclusive date bounds, exact category match, no SQL pattern matching), ordering, database constraints, rollback |
| `test_summaries_oracle.py` | Totals, monthly rows, month boundaries, category percentages and filters on seeded random data, compared with a separate plain-Python/Decimal calculation, including the values shown on the pages |
| `test_routes.py` | Every page and form: validation display, 404s, CSRF, safe redirects, filter preservation, security headers, error pages, oversized requests |
| `test_app_config.py` | Environment and secret-key rules, default database location, connection cleanup |

Page tests read the HTML through a small parser (`tests/html_helpers.py`) and assert on what
a page says rather than on exact markup. Tests use temporary databases and never touch
`instance/spendwise.sqlite`.

The tests cannot judge appearance. Layout was checked separately by looking at screenshots
from headless Chromium; no automated visual tests exist.

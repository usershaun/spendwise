-- Spendwise database schema.
-- Safe to run more than once: every statement uses IF NOT EXISTS.
--
-- The CHECK constraints are a safety net. The services layer validates all
-- input first, but the database refuses clearly invalid rows even if a bug
-- lets one through.

CREATE TABLE IF NOT EXISTS transactions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    -- Money is stored as whole cents (R12.50 -> 1250) to avoid floating-point errors.
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    type         TEXT    NOT NULL CHECK (type IN ('income', 'expense')),
    category     TEXT    NOT NULL CHECK (length(category) > 0),
    -- Dates are ISO 8601 text, 'YYYY-MM-DD'. This sorts correctly as plain text
    -- and makes the month simply the first 7 characters ('YYYY-MM').
    date         TEXT    NOT NULL
                 CHECK (date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    description  TEXT    NOT NULL CHECK (length(description) > 0),
    created_at   TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions (date);

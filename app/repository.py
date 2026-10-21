"""All SQL for Spendwise lives here.

Every function takes an open sqlite3 connection as its first argument and uses
`?` placeholders for values, never string formatting, so user input can never
change the meaning of a query. This module does no validation: the services
layer checks input before it gets here (the schema's CHECK constraints are the
last line of defence).

Writes use `with conn:`, which commits on success and rolls back if anything
raises, so a failed write never leaves half-saved data behind.

Note: parameters named `type` and `date` match the column names and the form
field names. They shadow Python built-in names only inside these small
functions, which do not use the built-ins.
"""

_INCOME_SUM = "COALESCE(SUM(CASE WHEN type = 'income' THEN amount_cents END), 0)"
_EXPENSE_SUM = "COALESCE(SUM(CASE WHEN type = 'expense' THEN amount_cents END), 0)"


def create_transaction(conn, *, amount_cents, type, category, date, description):
    """Insert a transaction and return its new id."""
    with conn:
        cursor = conn.execute(
            "INSERT INTO transactions (amount_cents, type, category, date, description) "
            "VALUES (?, ?, ?, ?, ?)",
            (amount_cents, type, category, date, description),
        )
    return cursor.lastrowid


def get_transaction(conn, transaction_id):
    """Return one transaction row, or None if it does not exist."""
    return conn.execute(
        "SELECT * FROM transactions WHERE id = ?", (transaction_id,)
    ).fetchone()


def update_transaction(
    conn, transaction_id, *, amount_cents, type, category, date, description
):
    """Replace a transaction's fields. Returns True if a row was updated."""
    with conn:
        cursor = conn.execute(
            "UPDATE transactions "
            "SET amount_cents = ?, type = ?, category = ?, date = ?, description = ? "
            "WHERE id = ?",
            (amount_cents, type, category, date, description, transaction_id),
        )
    return cursor.rowcount > 0


def delete_transaction(conn, transaction_id):
    """Delete a transaction. Returns True if a row was deleted."""
    with conn:
        cursor = conn.execute(
            "DELETE FROM transactions WHERE id = ?", (transaction_id,)
        )
    return cursor.rowcount > 0


def _build_where(type, category, date_from, date_to):
    """Build a WHERE clause from the filters that are set.

    Only fixed SQL fragments are joined together here; the actual values are
    always passed separately as bound parameters.
    """
    clauses = []
    params = []
    if type:
        clauses.append("type = ?")
        params.append(type)
    if category:
        clauses.append("category = ?")
        params.append(category)
    if date_from:
        clauses.append("date >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("date <= ?")
        params.append(date_to)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    return where, params


def list_transactions(conn, *, type=None, category=None, date_from=None, date_to=None):
    """Return matching transactions, newest first. Date bounds are inclusive."""
    where, params = _build_where(type, category, date_from, date_to)
    return conn.execute(
        f"SELECT * FROM transactions{where} ORDER BY date DESC, id DESC", params
    ).fetchall()


def get_totals(conn, *, type=None, category=None, date_from=None, date_to=None):
    """Return (income_cents, expense_cents) for the matching transactions."""
    where, params = _build_where(type, category, date_from, date_to)
    row = conn.execute(
        f"SELECT {_INCOME_SUM} AS income_cents, {_EXPENSE_SUM} AS expense_cents "
        f"FROM transactions{where}",
        params,
    ).fetchone()
    return row["income_cents"], row["expense_cents"]


def get_monthly_totals(conn):
    """Return one row per month that has data, newest month first.

    Each row has: month ('YYYY-MM'), income_cents, expense_cents.
    """
    return conn.execute(
        f"SELECT substr(date, 1, 7) AS month, "
        f"{_INCOME_SUM} AS income_cents, {_EXPENSE_SUM} AS expense_cents "
        f"FROM transactions GROUP BY month ORDER BY month DESC"
    ).fetchall()


def get_expense_totals_by_category(conn, month=None):
    """Return expense totals per category, largest first.

    If `month` ('YYYY-MM') is given, only that month is counted. Ties are
    broken alphabetically so the order is always the same.
    Each row has: category, total_cents.
    """
    sql = (
        "SELECT category, SUM(amount_cents) AS total_cents "
        "FROM transactions WHERE type = 'expense'"
    )
    params = []
    if month:
        sql += " AND substr(date, 1, 7) = ?"
        params.append(month)
    sql += " GROUP BY category ORDER BY total_cents DESC, category ASC"
    return conn.execute(sql, params).fetchall()

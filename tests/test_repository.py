import sqlite3

import pytest

from app import db, repository


# --- create / get ----------------------------------------------------------


def test_create_and_get_transaction(conn):
    new_id = repository.create_transaction(
        conn,
        amount_cents=12550,
        type="expense",
        category="Food",
        date="2026-03-05",
        description="Groceries",
    )

    row = repository.get_transaction(conn, new_id)

    assert row["id"] == new_id
    assert row["amount_cents"] == 12550
    assert row["type"] == "expense"
    assert row["category"] == "Food"
    assert row["date"] == "2026-03-05"
    assert row["description"] == "Groceries"


def test_get_missing_transaction_returns_none(conn):
    assert repository.get_transaction(conn, 999) is None


# --- update ----------------------------------------------------------------


def test_update_changes_all_fields(conn, add):
    tid = add()

    updated = repository.update_transaction(
        conn,
        tid,
        amount_cents=5000,
        type="income",
        category="Salary",
        date="2026-02-01",
        description="Bonus",
    )

    row = repository.get_transaction(conn, tid)
    assert updated is True
    assert (row["amount_cents"], row["type"], row["category"]) == (5000, "income", "Salary")
    assert (row["date"], row["description"]) == ("2026-02-01", "Bonus")


def test_update_missing_transaction_returns_false(conn):
    updated = repository.update_transaction(
        conn,
        999,
        amount_cents=100,
        type="expense",
        category="Food",
        date="2026-01-01",
        description="Nothing",
    )
    assert updated is False


def test_update_does_not_touch_other_rows(conn, add):
    first = add(description="first")
    second = add(description="second")

    repository.update_transaction(
        conn,
        first,
        amount_cents=1,
        type="expense",
        category="Food",
        date="2026-01-01",
        description="changed",
    )

    assert repository.get_transaction(conn, second)["description"] == "second"


# --- delete ----------------------------------------------------------------


def test_delete_removes_only_that_transaction(conn, add):
    keep = add(description="keep")
    remove = add(description="remove")

    assert repository.delete_transaction(conn, remove) is True

    assert repository.get_transaction(conn, remove) is None
    assert repository.get_transaction(conn, keep) is not None


def test_delete_missing_transaction_returns_false(conn):
    assert repository.delete_transaction(conn, 999) is False


# --- listing and filtering -------------------------------------------------


def test_list_empty_database_returns_empty_list(conn):
    assert repository.list_transactions(conn) == []


def test_list_orders_newest_date_first_then_newest_id(conn, add):
    old = add(date="2026-01-01")
    new_a = add(date="2026-03-01")
    new_b = add(date="2026-03-01")

    ids = [r["id"] for r in repository.list_transactions(conn)]

    assert ids == [new_b, new_a, old]


def test_filter_by_type(conn, add):
    add(type="income", category="Salary")
    add(type="expense")

    rows = repository.list_transactions(conn, type="income")

    assert [r["type"] for r in rows] == ["income"]


def test_filter_by_category(conn, add):
    add(category="Food")
    add(category="Rent")

    rows = repository.list_transactions(conn, category="Rent")

    assert [r["category"] for r in rows] == ["Rent"]


def test_filter_by_date_range_is_inclusive(conn, add):
    add(date="2026-01-31", description="before")
    add(date="2026-02-01", description="start")
    add(date="2026-02-15", description="middle")
    add(date="2026-02-28", description="end")
    add(date="2026-03-01", description="after")

    rows = repository.list_transactions(conn, date_from="2026-02-01", date_to="2026-02-28")

    assert sorted(r["description"] for r in rows) == ["end", "middle", "start"]


def test_filter_with_only_one_date_bound(conn, add):
    add(date="2026-01-01")
    add(date="2026-06-01")

    from_only = repository.list_transactions(conn, date_from="2026-03-01")
    to_only = repository.list_transactions(conn, date_to="2026-03-01")

    assert [r["date"] for r in from_only] == ["2026-06-01"]
    assert [r["date"] for r in to_only] == ["2026-01-01"]


def test_filters_combine_with_and(conn, add):
    add(type="expense", category="Food", date="2026-02-10", description="match")
    add(type="expense", category="Rent", date="2026-02-10", description="wrong category")
    add(type="income", category="Food", date="2026-02-10", description="wrong type")
    add(type="expense", category="Food", date="2026-05-10", description="wrong date")

    rows = repository.list_transactions(
        conn,
        type="expense",
        category="Food",
        date_from="2026-02-01",
        date_to="2026-02-28",
    )

    assert [r["description"] for r in rows] == ["match"]


def test_filter_with_no_matches_returns_empty_list(conn, add):
    add(category="Food")

    assert repository.list_transactions(conn, category="Health") == []


def test_hostile_filter_value_is_treated_as_plain_text(conn, add):
    add()

    rows = repository.list_transactions(conn, category="x'; DROP TABLE transactions; --")

    assert rows == []
    assert len(repository.list_transactions(conn)) == 1  # table still exists


# --- totals ----------------------------------------------------------------


def test_totals_on_empty_database_are_zero(conn):
    assert repository.get_totals(conn) == (0, 0)


def test_totals_sum_income_and_expenses_separately(conn, add):
    add(amount_cents=100000, type="income", category="Salary")
    add(amount_cents=2500, type="income", category="Other")
    add(amount_cents=1999, type="expense")
    add(amount_cents=1, type="expense")

    assert repository.get_totals(conn) == (102500, 2000)


def test_totals_respect_filters(conn, add):
    add(amount_cents=1000, type="expense", category="Food", date="2026-01-10")
    add(amount_cents=2000, type="expense", category="Rent", date="2026-01-10")
    add(amount_cents=5000, type="income", category="Salary", date="2026-02-10")

    assert repository.get_totals(conn, category="Food") == (0, 1000)
    assert repository.get_totals(conn, date_from="2026-02-01") == (5000, 0)


# --- monthly totals --------------------------------------------------------


def test_monthly_totals_empty_database(conn):
    assert repository.get_monthly_totals(conn) == []


def test_monthly_totals_group_by_month_newest_first(conn, add):
    add(amount_cents=300, type="expense", date="2025-12-31")
    add(amount_cents=700, type="income", category="Salary", date="2026-01-01")
    add(amount_cents=200, type="expense", date="2026-01-20")
    add(amount_cents=50, type="expense", date="2026-01-21")

    rows = repository.get_monthly_totals(conn)

    assert [(r["month"], r["income_cents"], r["expense_cents"]) for r in rows] == [
        ("2026-01", 700, 250),
        ("2025-12", 0, 300),
    ]


# --- expense totals by category -------------------------------------------


def test_category_totals_empty_database(conn):
    assert repository.get_expense_totals_by_category(conn) == []


def test_category_totals_count_only_expenses_largest_first(conn, add):
    add(amount_cents=1000, category="Food")
    add(amount_cents=500, category="Food")
    add(amount_cents=7000, category="Rent")
    add(amount_cents=999999, type="income", category="Salary")

    rows = repository.get_expense_totals_by_category(conn)

    assert [(r["category"], r["total_cents"]) for r in rows] == [
        ("Rent", 7000),
        ("Food", 1500),
    ]


def test_category_totals_ties_are_sorted_alphabetically(conn, add):
    add(amount_cents=500, category="Transport")
    add(amount_cents=500, category="Food")

    rows = repository.get_expense_totals_by_category(conn)

    assert [r["category"] for r in rows] == ["Food", "Transport"]


def test_category_totals_can_be_limited_to_one_month(conn, add):
    add(amount_cents=100, category="Food", date="2026-01-31")
    add(amount_cents=200, category="Food", date="2026-02-01")
    add(amount_cents=400, category="Rent", date="2026-02-28")
    add(amount_cents=800, category="Rent", date="2026-03-01")

    rows = repository.get_expense_totals_by_category(conn, month="2026-02")

    assert [(r["category"], r["total_cents"]) for r in rows] == [
        ("Rent", 400),
        ("Food", 200),
    ]


# --- persistence and schema safety net -------------------------------------


def test_data_persists_after_reopening_the_database_file(tmp_path):
    path = tmp_path / "persist.sqlite"
    first = db.connect(path)
    db.init_db(first)
    new_id = repository.create_transaction(
        first,
        amount_cents=4200,
        type="income",
        category="Salary",
        date="2026-04-01",
        description="Persisted",
    )
    first.close()

    second = db.connect(path)
    row = repository.get_transaction(second, new_id)
    second.close()

    assert row["description"] == "Persisted"
    assert row["amount_cents"] == 4200


def test_init_db_twice_keeps_existing_data(conn, add):
    add(description="survivor")

    db.init_db(conn)

    assert [r["description"] for r in repository.list_transactions(conn)] == ["survivor"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"amount_cents": 0},
        {"amount_cents": -100},
        {"type": "transfer"},
        {"category": ""},
        {"date": "15/01/2026"},
        {"description": ""},
    ],
)
def test_database_rejects_clearly_invalid_rows(conn, add, overrides):
    with pytest.raises(sqlite3.IntegrityError):
        add(**overrides)

    assert repository.list_transactions(conn) == []


def test_failed_write_is_rolled_back(conn, add):
    add(description="existing")

    with pytest.raises(sqlite3.IntegrityError):
        add(amount_cents=0)

    assert [r["description"] for r in repository.list_transactions(conn)] == ["existing"]

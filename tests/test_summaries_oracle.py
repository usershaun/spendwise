"""Check the app's numbers against a second, deliberately naive calculation.

Reproducible random data (fixed seeds) is loaded into the database. The expected
answers are worked out with plain Python and Decimal, NOT with the app's own SQL
or helpers, and then compared with what the app reports. If the SQL grouping, the
month boundaries, the rounding or the page rendering ever drift from the plain
arithmetic, these tests fail.
"""

import random
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

import pytest
from html_helpers import parse, stats, table_rows

from app import repository, services


def _last_day_of_month(day):
    first_of_next = date(day.year + (day.month == 12), day.month % 12 + 1, 1)
    return first_of_next - timedelta(days=1)


def load_random_transactions(conn, seed, count=200):
    """Insert reproducible random transactions; return them (with ids) as dicts."""
    rng = random.Random(seed)
    start = date(2024, 1, 1)
    span = (date(2026, 12, 31) - start).days
    loaded = []
    for number in range(count):
        kind = rng.choice(["income", "expense", "expense"])
        when = start + timedelta(days=rng.randint(0, span))
        if rng.random() < 0.25:  # month edges are where date bugs hide
            when = date(when.year, when.month, 1) if rng.random() < 0.5 else _last_day_of_month(when)
        categories = services.CATEGORIES_BY_TYPE[kind]
        row = {
            "amount_cents": rng.choice(
                [rng.randint(1, 99), rng.randint(100, 50_000), rng.randint(50_000, 2_500_000)]
            ),
            "type": kind,
            "category": rng.choice(categories),
            "date": when.isoformat(),
            "description": f"row {number}",
        }
        row["id"] = repository.create_transaction(conn, **row)
        loaded.append(row)
    return loaded


@pytest.fixture(params=[11, 2026, 90210], ids=lambda seed: f"seed{seed}")
def data(request, conn):
    return load_random_transactions(conn, request.param)


def rand(cents):
    """Independent money formatting (Decimal, not the app's helper)."""
    sign = "-" if cents < 0 else ""
    return f"{sign}R{Decimal(abs(cents)) / 100:,.2f}"


def totals_of(rows):
    income = sum(r["amount_cents"] for r in rows if r["type"] == "income")
    expense = sum(r["amount_cents"] for r in rows if r["type"] == "expense")
    return income, expense


def months_of(rows):
    """{(year, month): [rows]} using real date objects, not string slicing."""
    grouped = defaultdict(list)
    for row in rows:
        when = date.fromisoformat(row["date"])
        grouped[(when.year, when.month)].append(row)
    return grouped


# --- the service layer -----------------------------------------------------


def test_overall_totals_and_net_balance(conn, data):
    income, expense = totals_of(data)

    result = services.get_totals(conn)

    assert (result.income_cents, result.expense_cents) == (income, expense)
    assert result.net_cents == income - expense


def test_monthly_summary_matches_plain_grouping(conn, data):
    grouped = months_of(data)
    expected = [
        (f"{year:04d}-{month:02d}", *totals_of(grouped[(year, month)]))
        for (year, month) in sorted(grouped, reverse=True)
    ]

    actual = [
        (m.month, m.income_cents, m.expense_cents) for m in services.get_monthly_summary(conn)
    ]

    assert actual == expected
    income, expense = totals_of(data)
    assert sum(m[1] for m in actual) == income  # months add up to the overall totals
    assert sum(m[2] for m in actual) == expense


def test_month_link_bounds_select_exactly_that_months_transactions(conn, data):
    for (year, month), rows_in_month in months_of(data).items():
        label = f"{year:04d}-{month:02d}"
        first, last = services.month_bounds(label)
        income, expense = totals_of(rows_in_month)

        shown = repository.list_transactions(conn, date_from=first, date_to=last)
        totals = services.get_totals(conn, date_from=first, date_to=last)

        assert {r["id"] for r in shown} == {r["id"] for r in rows_in_month}, label
        assert (totals.income_cents, totals.expense_cents) == (income, expense), label


def test_category_breakdown_matches_plain_counting_and_rounding(conn, data):
    for (year, month), rows_in_month in months_of(data).items():
        label = f"{year:04d}-{month:02d}"
        spent = Counter()
        for row in rows_in_month:
            if row["type"] == "expense":
                spent[row["category"]] += row["amount_cents"]
        grand = sum(spent.values())

        breakdown = services.get_category_breakdown(conn, label)

        expected_order = sorted(spent.items(), key=lambda item: (-item[1], item[0]))
        assert [(s.category, s.total_cents) for s in breakdown.shares] == expected_order, label
        assert breakdown.total_cents == grand, label
        for share in breakdown.shares:
            tenths = (Decimal(share.total_cents) * 1000 / Decimal(grand)).quantize(
                Decimal(1), rounding=ROUND_HALF_UP
            )
            assert share.percent_tenths == int(tenths), (label, share.category)
        # Each share is rounded to 0.1%, so together they stay within that error of 100%.
        if breakdown.shares:
            assert abs(sum(s.percent_tenths for s in breakdown.shares) - 1000) <= len(breakdown.shares)


def test_random_filter_combinations_match_plain_filtering(conn, data):
    rng = random.Random(99)
    all_dates = sorted({r["date"] for r in data})
    for _ in range(40):
        kind = rng.choice([None, "income", "expense"])
        category = rng.choice([None, *services.CATEGORIES])
        first, last = sorted(rng.sample(all_dates, 2))
        use_from, use_to = rng.random() < 0.8, rng.random() < 0.8
        filters = {
            "type": kind,
            "category": category,
            "date_from": first if use_from else None,
            "date_to": last if use_to else None,
        }
        expected = [
            r
            for r in data
            if (kind is None or r["type"] == kind)
            and (category is None or r["category"] == category)
            and (not use_from or r["date"] >= first)
            and (not use_to or r["date"] <= last)
        ]
        expected.sort(key=lambda r: (r["date"], r["id"]), reverse=True)

        shown = repository.list_transactions(conn, **filters)
        totals = services.get_totals(conn, **filters)

        assert [r["id"] for r in shown] == [r["id"] for r in expected], filters
        assert (totals.income_cents, totals.expense_cents) == totals_of(expected), filters


# --- the same numbers as they appear on the pages ----------------------------


def test_dashboard_shows_the_independently_calculated_figures(client, data):
    income, expense = totals_of(data)

    page = parse(client.get("/").get_data(as_text=True))

    assert stats(page) == {
        "Total income": rand(income),
        "Total expenses": rand(expense),
        "Net balance": rand(income - expense),
    }
    section = page.find("section", aria_labelledby="monthly-heading")
    grouped = months_of(data)
    expected_rows = []
    for key in sorted(grouped, reverse=True):
        month_income, month_expense = totals_of(grouped[key])
        expected_rows.append(
            {
                "Month": date(key[0], key[1], 1).strftime("%B %Y"),
                "Income": rand(month_income),
                "Expenses": rand(month_expense),
                "Net": rand(month_income - month_expense),
            }
        )
    assert table_rows(section.find("table")) == expected_rows


def test_transaction_list_shows_every_row_newest_first_with_correct_amounts(client, data):
    expected = sorted(data, key=lambda r: (r["date"], r["id"]), reverse=True)

    page = parse(client.get("/transactions").get_data(as_text=True))

    shown = table_rows(page.find("table", cls="txn-table"))
    assert [r["Description"] for r in shown] == [r["description"] for r in expected]
    assert [r["Amount"] for r in shown] == [
        ("+" if r["type"] == "income" else "−") + rand(r["amount_cents"]) for r in expected
    ]
    assert [r["Type"] for r in shown] == [r["type"].capitalize() for r in expected]

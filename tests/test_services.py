import pytest

from app import services
from app.services import ValidationError


# --- amounts ---------------------------------------------------------------


@pytest.mark.parametrize(
    "text, cents",
    [
        ("150", 15000),
        ("150.5", 15050),
        ("150.50", 15050),
        ("0.10", 10),
        ("0.01", 1),
        ("1", 100),
        (" 12.30 ", 1230),
        ("R99.99", 9999),
        ("r5", 500),
        ("R 5", 500),
        ("007.5", 750),
        ("999999999.99", 99_999_999_999),
    ],
)
def test_valid_amounts_become_exact_integer_cents(text, cents):
    assert services.parse_amount_to_cents(text) == cents


def test_decimal_amounts_add_up_exactly():
    # With floats, 0.1 + 0.2 != 0.3. With integer cents it is exact.
    total = services.parse_amount_to_cents("0.1") + services.parse_amount_to_cents("0.2")
    assert total == services.parse_amount_to_cents("0.3")


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "   ",
        "abc",
        "0",
        "0.00",
        "-5",
        "-0.01",
        "1.234",
        "1,000",
        "1,5",
        "1e3",
        "NaN",
        "inf",
        ".5",
        "5.",
        "12.3.4",
        "1 000",
        "٣",  # Arabic-Indic digit three
        "1000000000",  # one digit too many
    ],
)
def test_invalid_amounts_are_rejected(text):
    with pytest.raises(ValidationError):
        services.parse_amount_to_cents(text)


def test_enormous_digit_strings_are_handled_without_crashing():
    # Python refuses int() on very long digit strings; we must never reach that.
    with pytest.raises(ValidationError, match="too large"):
        services.parse_amount_to_cents("9" * 5000)
    assert services.parse_amount_to_cents("0" * 5000 + "1") == 100


def test_amount_error_messages_are_specific():
    with pytest.raises(ValidationError, match="required"):
        services.parse_amount_to_cents("")
    with pytest.raises(ValidationError, match="greater than zero"):
        services.parse_amount_to_cents("0")
    with pytest.raises(ValidationError, match="greater than zero"):
        services.parse_amount_to_cents("-5")
    with pytest.raises(ValidationError, match="two decimal places"):
        services.parse_amount_to_cents("1.234")
    with pytest.raises(ValidationError, match="too large"):
        services.parse_amount_to_cents("1000000000")


# --- dates and months ------------------------------------------------------


@pytest.mark.parametrize("text", ["2026-02-28", "2024-02-29", "1900-01-01", "2100-12-31", " 2026-03-15 "])
def test_valid_dates_are_accepted(text):
    assert services.parse_date(text) == text.strip()


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "2026-02-30",
        "2025-02-29",  # not a leap year
        "2026-13-01",
        "2026-00-10",
        "26-01-01",
        "2026/01/01",
        "2026-1-1",
        "20260101",
        "15-01-2026",
        "1899-12-31",
        "2101-01-01",
        "٢٠٢٦-٠١-٠١",  # Arabic-Indic digits
    ],
)
def test_invalid_dates_are_rejected(text):
    with pytest.raises(ValidationError):
        services.parse_date(text)


@pytest.mark.parametrize("text", ["2026-01", "1999-12", "2026-12"])
def test_valid_months(text):
    assert services.parse_month(text) == text


@pytest.mark.parametrize("text", [None, "", "2026", "2026-13", "2026-00", "2026-1", "2026-01-01", "abcd-ef"])
def test_invalid_months(text):
    with pytest.raises(ValidationError):
        services.parse_month(text)


# --- type, category, description -------------------------------------------


@pytest.mark.parametrize("text, expected", [("income", "income"), ("Expense", "expense"), (" EXPENSE ", "expense")])
def test_valid_types(text, expected):
    assert services.parse_type(text) == expected


@pytest.mark.parametrize("text", [None, "", "transfer", "incomes"])
def test_invalid_types(text):
    with pytest.raises(ValidationError):
        services.parse_type(text)


@pytest.mark.parametrize("category", services.CATEGORIES)
def test_every_listed_category_is_accepted(category):
    assert services.parse_category(category) == category


@pytest.mark.parametrize("text", [None, "", "Gambling", "food", "Food; DROP TABLE"])
def test_invalid_categories(text):
    with pytest.raises(ValidationError):
        services.parse_category(text)


def test_description_is_trimmed():
    assert services.parse_description("  Lunch  ") == "Lunch"


def test_description_length_limit():
    assert services.parse_description("x" * 200) == "x" * 200
    with pytest.raises(ValidationError, match="200"):
        services.parse_description("x" * 201)


@pytest.mark.parametrize("text", [None, "", "    "])
def test_description_is_required(text):
    with pytest.raises(ValidationError, match="required"):
        services.parse_description(text)


# --- validate_transaction --------------------------------------------------


def valid_form(**overrides):
    form = {
        "amount": "250.75",
        "type": "expense",
        "category": "Food",
        "date": "2026-03-15",
        "description": "Groceries",
    }
    form.update(overrides)
    return form


def test_valid_transaction_form_produces_repository_values():
    result = services.validate_transaction(valid_form())

    assert result.ok
    assert result.errors == {}
    assert result.values == {
        "amount_cents": 25075,
        "type": "expense",
        "category": "Food",
        "date": "2026-03-15",
        "description": "Groceries",
    }


def test_all_errors_are_reported_together():
    result = services.validate_transaction(
        valid_form(amount="-1", type="nope", category="", date="2026-02-30", description="")
    )

    assert not result.ok
    assert set(result.errors) == {"amount", "type", "category", "date", "description"}


def test_only_the_bad_field_is_reported():
    result = services.validate_transaction(valid_form(amount="abc"))

    assert set(result.errors) == {"amount"}
    assert result.values["category"] == "Food"  # valid fields are still cleaned


def test_empty_form_reports_every_field_as_required():
    result = services.validate_transaction({})

    assert not result.ok
    assert set(result.errors) == {"amount", "type", "category", "date", "description"}


def test_unknown_form_fields_are_ignored():
    result = services.validate_transaction(valid_form(id="99", is_admin="true"))

    assert result.ok
    assert "id" not in result.values and "is_admin" not in result.values


# --- validate_filters ------------------------------------------------------


def test_blank_filters_mean_no_filtering():
    result = services.validate_filters({"type": "", "category": "", "date_from": "", "date_to": ""})

    assert result.ok
    assert result.values == {"type": None, "category": None, "date_from": None, "date_to": None}


def test_missing_filters_mean_no_filtering():
    result = services.validate_filters({})

    assert result.ok
    assert result.values == {"type": None, "category": None, "date_from": None, "date_to": None}


def test_valid_filters_are_cleaned():
    result = services.validate_filters(
        {"type": "Income", "category": "Salary", "date_from": "2026-01-01", "date_to": "2026-01-31"}
    )

    assert result.ok
    assert result.values == {
        "type": "income",
        "category": "Salary",
        "date_from": "2026-01-01",
        "date_to": "2026-01-31",
    }


def test_invalid_filter_values_are_errors_not_ignored():
    result = services.validate_filters({"type": "x", "category": "y", "date_from": "z"})

    assert set(result.errors) == {"type", "category", "date_from"}


def test_start_date_after_end_date_is_rejected():
    result = services.validate_filters({"date_from": "2026-02-01", "date_to": "2026-01-01"})

    assert not result.ok
    assert "date_to" in result.errors


def test_same_start_and_end_date_is_allowed():
    assert services.validate_filters({"date_from": "2026-02-01", "date_to": "2026-02-01"}).ok


def test_filter_values_can_be_passed_straight_to_the_repository(conn, add):
    add(type="expense", category="Food", date="2026-01-10")
    add(type="income", category="Salary", date="2026-01-10")
    result = services.validate_filters({"type": "expense"})

    totals = services.get_totals(conn, **result.values)

    assert (totals.income_cents, totals.expense_cents) == (0, 1000)


# --- formatting ------------------------------------------------------------


@pytest.mark.parametrize(
    "cents, expected",
    [
        (0, "R0.00"),
        (5, "R0.05"),
        (100, "R1.00"),
        (99999, "R999.99"),
        (123456, "R1,234.56"),
        (100000000, "R1,000,000.00"),
        (-250, "-R2.50"),
        (-123456, "-R1,234.56"),
    ],
)
def test_format_cents_as_rand(cents, expected):
    assert services.format_cents(cents) == expected


@pytest.mark.parametrize("cents, expected", [(5, "0.05"), (100, "1.00"), (123456, "1234.56")])
def test_cents_to_input(cents, expected):
    assert services.cents_to_input(cents) == expected


def test_amount_survives_a_round_trip_through_the_edit_form():
    for cents in (1, 10, 99, 100, 12345, 99_999_999_999):
        assert services.parse_amount_to_cents(services.cents_to_input(cents)) == cents


# --- totals ----------------------------------------------------------------


def test_totals_on_empty_database(conn):
    totals = services.get_totals(conn)

    assert (totals.income_cents, totals.expense_cents, totals.net_cents) == (0, 0, 0)


def test_totals_and_net_balance(conn, add):
    add(amount_cents=500000, type="income", category="Salary")
    add(amount_cents=120050, type="expense", category="Rent")
    add(amount_cents=3025, type="expense", category="Food")

    totals = services.get_totals(conn)

    assert totals.income_cents == 500000
    assert totals.expense_cents == 123075
    assert totals.net_cents == 376925


def test_net_balance_can_be_negative(conn, add):
    add(amount_cents=1000, type="income", category="Salary")
    add(amount_cents=4000, type="expense")

    assert services.get_totals(conn).net_cents == -3000


def test_totals_use_exact_cents_for_many_small_amounts(conn, add):
    for _ in range(10):
        add(amount_cents=10)  # ten times R0.10

    assert services.get_totals(conn).expense_cents == 100


# --- monthly summary -------------------------------------------------------


def test_monthly_summary_on_empty_database(conn):
    assert services.get_monthly_summary(conn) == []


def test_monthly_summary_rows_and_net(conn, add):
    add(amount_cents=10000, type="income", category="Salary", date="2026-02-01")
    add(amount_cents=2500, type="expense", date="2026-02-14")
    add(amount_cents=4000, type="expense", date="2026-01-31")

    summary = services.get_monthly_summary(conn)

    assert [(m.month, m.income_cents, m.expense_cents, m.net_cents) for m in summary] == [
        ("2026-02", 10000, 2500, 7500),
        ("2026-01", 0, 4000, -4000),
    ]


def test_months_do_not_leak_across_the_year_boundary(conn, add):
    add(amount_cents=100, date="2025-12-31")
    add(amount_cents=200, date="2026-01-01")

    summary = services.get_monthly_summary(conn)

    assert [(m.month, m.expense_cents) for m in summary] == [("2026-01", 200), ("2025-12", 100)]


def test_months_are_not_confused_by_a_matching_month_number(conn, add):
    add(amount_cents=100, date="2025-03-10")
    add(amount_cents=200, date="2026-03-10")

    assert len(services.get_monthly_summary(conn)) == 2


# --- category breakdown ----------------------------------------------------


def test_category_breakdown_on_empty_database(conn):
    breakdown = services.get_category_breakdown(conn)

    assert breakdown.total_cents == 0
    assert breakdown.shares == ()


def test_category_breakdown_when_month_has_only_income(conn, add):
    add(amount_cents=5000, type="income", category="Salary", date="2026-03-01")

    breakdown = services.get_category_breakdown(conn, "2026-03")

    assert breakdown.total_cents == 0
    assert breakdown.shares == ()


def test_category_breakdown_amounts_and_percentages(conn, add):
    add(amount_cents=3000, category="Food")
    add(amount_cents=7000, category="Rent")
    add(amount_cents=999999, type="income", category="Salary")  # ignored

    breakdown = services.get_category_breakdown(conn)

    assert breakdown.total_cents == 10000
    assert [(s.category, s.total_cents, s.percent_label) for s in breakdown.shares] == [
        ("Rent", 7000, "70.0%"),
        ("Food", 3000, "30.0%"),
    ]


def test_category_percentages_round_to_one_decimal_place(conn, add):
    for category in ("Food", "Rent", "Health"):
        add(amount_cents=100, category=category)

    shares = services.get_category_breakdown(conn).shares

    assert [s.percent_label for s in shares] == ["33.3%", "33.3%", "33.3%"]


def test_a_single_category_is_one_hundred_percent(conn, add):
    add(amount_cents=1, category="Food")

    assert services.get_category_breakdown(conn).shares[0].percent_label == "100.0%"


def test_category_breakdown_for_one_month(conn, add):
    add(amount_cents=100, category="Food", date="2026-01-31")
    add(amount_cents=300, category="Food", date="2026-02-01")
    add(amount_cents=100, category="Rent", date="2026-02-28")

    breakdown = services.get_category_breakdown(conn, "2026-02")

    assert breakdown.total_cents == 400
    assert [(s.category, s.percent_label) for s in breakdown.shares] == [
        ("Food", "75.0%"),
        ("Rent", "25.0%"),
    ]


def test_category_breakdown_rejects_an_invalid_month(conn):
    with pytest.raises(ValidationError):
        services.get_category_breakdown(conn, "2026-13")

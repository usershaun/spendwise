import html as html_lib
import re
from pathlib import Path

import pytest
from html_helpers import form_state, parse, stats, table_rows

from app import repository, services


def rows(conn):
    return repository.list_transactions(conn)


def parse_links(element):
    return {a.get("href"): a.text() for a in element.find_all("a")}


def monthly_rows(page):
    section = page.find("section", aria_labelledby="monthly-heading")
    return table_rows(section.find("table"))


def breakdown_items(page):
    section = page.find("section", aria_labelledby="breakdown-heading")
    return [
        {
            "category": li.find("a").text(),
            "summary": li.find("span").text(),
            "bar": li.find("div", cls="bar").find("span").get("style"),
        }
        for li in section.find_all("li")
    ]


# --- dashboard -------------------------------------------------------------


def test_dashboard_empty_state(client):
    response = client.get("/")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "R0.00" in html
    assert "No transactions yet" in html
    assert "Monthly summary" not in html


def test_dashboard_totals_come_from_the_database(client, add):
    add(amount_cents=500000, type="income", category="Salary", date="2026-03-01")
    add(amount_cents=123450, type="expense", category="Rent", date="2026-03-02")
    add(amount_cents=5, type="expense", category="Food", date="2026-03-03")

    page = parse(client.get("/").get_data(as_text=True))

    assert stats(page) == {
        "Total income": "R5,000.00",
        "Total expenses": "R1,234.55",
        "Net balance": "R3,765.45",
    }
    assert "stat-negative" not in page.find("div", cls="stat-net").classes


def test_dashboard_negative_net_balance_is_shown_and_flagged(client, add):
    add(amount_cents=1000, type="income", category="Salary", date="2026-03-01")
    add(amount_cents=5000, type="expense", category="Food", date="2026-03-02")

    page = parse(client.get("/").get_data(as_text=True))

    assert stats(page)["Net balance"] == "-R40.00"
    assert "stat-negative" in page.find("div", cls="stat-net").classes


def test_dashboard_monthly_table_lists_each_month(client, add):
    add(amount_cents=1000, type="income", category="Salary", date="2026-02-10")
    add(amount_cents=300, type="expense", category="Food", date="2026-03-10")
    add(amount_cents=5000, type="expense", category="Rent", date="2026-03-11")

    page = parse(client.get("/").get_data(as_text=True))

    assert monthly_rows(page) == [
        {"Month": "March 2026", "Income": "R0.00", "Expenses": "R53.00", "Net": "-R53.00"},
        {"Month": "February 2026", "Income": "R10.00", "Expenses": "R0.00", "Net": "R10.00"},
    ]


def test_each_monthly_summary_link_shows_exactly_that_months_transactions(client, add):
    # Month-end and month-start days, a leap day and a year boundary.
    for day in ("2024-02-29", "2024-03-01", "2025-12-31", "2026-01-01", "2026-02-28"):
        add(date=day, description=day)

    page = parse(client.get("/").get_data(as_text=True))
    section = page.find("section", aria_labelledby="monthly-heading")
    shown = {}
    for link in section.find_all("a"):
        listing = parse(client.get(link.get("href")).get_data(as_text=True))
        shown[link.text()] = [r["Date"] for r in table_rows(listing.find("table", cls="txn-table"))]

    assert shown == {
        "February 2024": ["2024-02-29"],
        "March 2024": ["2024-03-01"],
        "December 2025": ["2025-12-31"],
        "January 2026": ["2026-01-01"],
        "February 2026": ["2026-02-28"],
    }


def test_dashboard_defaults_to_latest_month_with_expenses(client, add):
    add(amount_cents=1000, type="expense", category="Food", date="2026-01-10")
    add(amount_cents=9000, type="income", category="Salary", date="2026-02-10")

    html = client.get("/").get_data(as_text=True)

    assert "Total expenses in January 2026" in html


def test_dashboard_month_picker_changes_the_breakdown(client, add):
    add(amount_cents=1000, type="expense", category="Food", date="2026-01-10")
    add(amount_cents=7000, type="expense", category="Rent", date="2026-02-10")

    january = parse(client.get("/?month=2026-01").get_data(as_text=True))
    february = parse(client.get("/?month=2026-02").get_data(as_text=True))

    assert [(i["category"], i["summary"]) for i in breakdown_items(january)] == [
        ("Food", "R10.00 · 100.0%")
    ]
    assert [(i["category"], i["summary"]) for i in breakdown_items(february)] == [
        ("Rent", "R70.00 · 100.0%")
    ]
    picker = january.find("form", cls="inline-form")
    assert form_state(picker) == {"month": "2026-01"}
    assert [o.get("value") for o in picker.find_all("option")] == ["2026-02", "2026-01"]


def test_dashboard_breakdown_shows_amounts_percentages_and_matching_bars(client, add):
    add(amount_cents=3000, type="expense", category="Food", date="2026-03-10")
    add(amount_cents=7000, type="expense", category="Rent", date="2026-03-10")

    page = parse(client.get("/?month=2026-03").get_data(as_text=True))

    assert breakdown_items(page) == [
        {"category": "Rent", "summary": "R70.00 · 70.0%", "bar": "width: 70.0%"},
        {"category": "Food", "summary": "R30.00 · 30.0%", "bar": "width: 30.0%"},
    ]


def test_dashboard_month_without_expenses_shows_empty_message(client, add):
    add(amount_cents=1000, type="expense", category="Food", date="2026-01-10")

    response = client.get("/?month=2026-05")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "No expenses recorded in May 2026" in html


def test_dashboard_invalid_month_returns_400_with_message(client, add):
    add(amount_cents=1000, type="expense", category="Food", date="2026-01-10")

    response = client.get("/?month=banana")
    html = response.get_data(as_text=True)

    assert response.status_code == 400
    assert "Enter the month as YYYY-MM" in html
    assert "Total expenses in January 2026" in html  # falls back to the latest month


def test_dashboard_shows_only_the_five_most_recent_transactions(client, add):
    for day in range(1, 8):
        add(date=f"2026-03-{day:02d}", description=f"item-{day}")

    html = client.get("/").get_data(as_text=True)
    recent = html.split("Recent transactions")[1]

    assert "item-7" in recent and "item-3" in recent
    assert "item-2" not in recent and "item-1<" not in recent


# --- transaction list and filters -----------------------------------------


def test_list_empty_state(client):
    response = client.get("/transactions")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "No transactions yet" in html
    assert "Add your first transaction" in html


def test_list_shows_transactions_newest_first_with_totals(client, add):
    add(amount_cents=1000, type="expense", date="2026-01-01", description="older")
    add(amount_cents=250000, type="income", category="Salary", date="2026-02-01", description="newer")

    page = parse(client.get("/transactions").get_data(as_text=True))

    rows = table_rows(page.find("table", cls="txn-table"))
    assert [(r["Description"], r["Type"], r["Amount"]) for r in rows] == [
        ("newer", "Income", "+R2,500.00"),
        ("older", "Expense", "−R10.00"),
    ]
    box = page.find("dl", cls="mini-stats")
    assert {d.find("dt").text(): d.find("dd").text() for d in box.find_all("div")} == {
        "Income": "R2,500.00",
        "Expenses": "R10.00",
        "Net": "R2,490.00",
    }
    assert page.find("h2", id="results-heading").text() == "2 transactions"


def test_list_escapes_html_in_descriptions(client, add):
    add(description="<script>alert('x')</script>")

    html = client.get("/transactions").get_data(as_text=True)

    assert "<script>alert" not in html
    assert "&lt;script&gt;alert" in html


def test_list_filter_by_type(client, add):
    add(type="income", category="Salary", description="pay-day")
    add(type="expense", description="shop-run")

    html = client.get("/transactions?type=income").get_data(as_text=True)

    assert "pay-day" in html and "shop-run" not in html
    assert "1 transaction match" in html


def test_list_filter_by_category(client, add):
    add(category="Food", description="lunch-item")
    add(category="Rent", description="rent-item")

    html = client.get("/transactions?category=Rent").get_data(as_text=True)

    assert "rent-item" in html and "lunch-item" not in html


def test_list_filter_by_date_range(client, add):
    add(date="2026-01-31", description="too-early")
    add(date="2026-02-15", description="in-range")
    add(date="2026-03-01", description="too-late")

    html = client.get("/transactions?date_from=2026-02-01&date_to=2026-02-28").get_data(as_text=True)

    assert "in-range" in html
    assert "too-early" not in html and "too-late" not in html


def test_list_filters_combine_and_form_keeps_selected_values(client, add):
    add(type="expense", category="Food", date="2026-02-10", description="match-me")
    add(type="expense", category="Rent", date="2026-02-10", description="other-cat")

    page = parse(
        client.get(
            "/transactions?type=expense&category=Food&date_from=2026-02-01&date_to=2026-02-28"
        ).get_data(as_text=True)
    )

    rows = table_rows(page.find("table", cls="txn-table"))
    assert [r["Description"] for r in rows] == ["match-me"]
    assert form_state(page.find("form", cls="filters")) == {
        "type": "expense",
        "category": "Food",
        "date_from": "2026-02-01",
        "date_to": "2026-02-28",
    }


def test_list_filter_with_no_matches_shows_empty_message(client, add):
    add(category="Food")

    response = client.get("/transactions?category=Health")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "No transactions match these filters" in html
    assert "Clear filters" in html


def test_list_invalid_filters_return_400_with_messages(client, add):
    add(description="should-not-appear")

    response = client.get("/transactions?type=nope&date_from=2026-02-30")
    html = response.get_data(as_text=True)

    assert response.status_code == 400
    assert "Type must be either income or expense." in html
    assert "does not exist on the calendar" in html
    assert "should-not-appear" not in html


def test_list_reversed_date_range_is_an_error(client):
    response = client.get("/transactions?date_from=2026-03-01&date_to=2026-02-01")

    assert response.status_code == 400
    assert "End date must be on or after the start date." in response.get_data(as_text=True)


def test_list_hostile_filter_text_is_harmless(client, add):
    add()

    response = client.get("/transactions?category=x'%3B DROP TABLE transactions%3B --")

    assert response.status_code == 400  # not on the category list
    assert client.get("/transactions").status_code == 200


def test_list_links_carry_all_active_filters_through_to_the_form(client, add):
    add(type="expense", category="Food", date="2026-02-10")
    filters = "type=expense&category=Food&date_from=2026-02-01&date_to=2026-02-28"

    page = client.get(f"/transactions?{filters}").get_data(as_text=True)
    edit_url = html_lib.unescape(re.search(r'href="([^"]*/edit\?[^"]*)"', page).group(1))
    form_page = client.get(edit_url).get_data(as_text=True)
    next_value = html_lib.unescape(re.search(r'name="next" value="([^"]*)"', form_page).group(1))

    # Every filter survives the round trip (none are cut off at the first "&").
    assert next_value == f"/transactions?{filters}"


# --- add -------------------------------------------------------------------


def test_new_form_fields_are_labelled_and_the_type_group_has_a_legend(client):
    page = parse(client.get("/transactions/new").get_data(as_text=True))
    form = page.find("form", cls="form")

    labels = {l.get("for"): l.text() for l in form.find_all("label") if l.get("for")}
    assert labels == {
        "amount": "Amount (R)",
        "category": "Category",
        "date": "Date",
        "description": "Description",
    }
    for radio in form.find_all("input", type="radio"):
        assert "label" in [a.tag for a in radio.ancestors()]  # label wraps the radio button
    assert form.find("fieldset").find("legend").text() == "Type"

    ids = {e.get("id") for e in page.iter() if e.get("id")}
    for element in page.iter():
        for target in element.get("aria-describedby", "").split():
            assert target in ids, f"aria-describedby points at missing id {target!r}"


def test_new_form_preselects_type_from_query(client):
    page = parse(client.get("/transactions/new?type=income").get_data(as_text=True))

    assert form_state(page.find("form", cls="form"))["type"] == "income"


def test_create_transaction_saves_to_the_database(client, conn, form):
    response = client.post("/transactions/new", data=form(amount="1234.56"))

    assert response.status_code == 303
    saved = rows(conn)
    assert len(saved) == 1
    assert saved[0]["amount_cents"] == 123456
    assert saved[0]["type"] == "expense"
    assert saved[0]["category"] == "Food"
    assert saved[0]["date"] == "2026-03-15"
    assert saved[0]["description"] == "Groceries"


def test_create_redirects_to_list_and_shows_confirmation(client, form):
    response = client.post("/transactions/new", data=form(), follow_redirects=True)
    html = response.get_data(as_text=True)

    assert response.request.path == "/transactions"
    assert "Transaction added." in html
    assert "Groceries" in html


def test_create_income_with_income_category(client, conn, form):
    client.post("/transactions/new", data=form(type="income", category="Salary", amount="100"))

    assert rows(conn)[0]["type"] == "income"


def test_flash_message_only_shows_once(client, form):
    client.post("/transactions/new", data=form(), follow_redirects=True)

    assert "Transaction added." not in client.get("/transactions").get_data(as_text=True)


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"amount": ""}, "Amount is required."),
        ({"amount": "-5"}, "Amount must be greater than zero."),
        ({"amount": "0"}, "Amount must be greater than zero."),
        ({"amount": "abc"}, "Enter a valid amount"),
        ({"amount": "1.234"}, "at most two decimal places"),
        ({"type": None}, "Type is required."),
        ({"type": "transfer"}, "Type must be either income or expense."),
        ({"category": ""}, "Category is required."),
        ({"category": "Gambling"}, "Choose an expense category from the list."),
        ({"category": "Salary"}, "Choose an expense category from the list."),
        ({"date": ""}, "Date is required."),
        ({"date": "2026-02-30"}, "does not exist on the calendar"),
        ({"description": ""}, "Description is required."),
        ({"description": "x" * 201}, "200 characters or fewer"),
    ],
)
def test_create_rejects_invalid_input_with_400_and_message(client, conn, form, overrides, message):
    response = client.post("/transactions/new", data=form(**overrides))

    assert response.status_code == 400
    assert message in response.get_data(as_text=True)
    assert rows(conn) == []


def test_invalid_create_keeps_what_the_user_typed(client, form):
    response = client.post(
        "/transactions/new",
        data=form(amount="abc", description="Keep this text", date="2026-03-20", type="income"),
    )

    state = form_state(parse(response.get_data(as_text=True)).find("form", cls="form"))

    assert state["amount"] == "abc"
    assert state["description"] == "Keep this text"
    assert state["date"] == "2026-03-20"
    assert state["type"] == "income"


def test_invalid_create_shows_an_error_summary_and_marks_fields_invalid(client, form):
    response = client.post("/transactions/new", data=form(amount="", description=""))
    page = parse(response.get_data(as_text=True))

    summary = page.find(id="error-summary")
    assert {a.get("href"): a.text() for a in summary.find_all("a")} == {
        "#amount": "Amount is required.",
        "#description": "Description is required.",
    }
    for field in ("amount", "description"):
        control = page.find(id=field)
        assert control.get("aria-invalid") == "true"
        assert f"error-{field}" in control.get("aria-describedby").split()
        assert page.find(id=f"error-{field}") is not None
    assert page.find(id="category").get("aria-invalid") is None  # valid fields are not flagged


def test_error_summary_links_always_point_at_real_fields(client, form):
    response = client.post("/transactions/new", data=form(type=None, category="", date="", amount=""))
    page = parse(response.get_data(as_text=True))

    ids = {e.get("id") for e in page.iter() if e.get("id")}
    links = parse_links(page.find(id="error-summary"))
    assert set(links) == {"#amount", "#type-income", "#category", "#date"}
    assert all(href[1:] in ids for href in links)


def test_income_category_on_expense_is_rejected_by_the_server(client, conn, form):
    response = client.post("/transactions/new", data=form(type="expense", category="Freelance"))

    assert response.status_code == 400
    assert rows(conn) == []


# --- edit ------------------------------------------------------------------


def test_edit_form_is_prefilled(client, add):
    tid = add(amount_cents=123456, type="income", category="Salary", date="2026-02-03", description="Pay")

    page = parse(client.get(f"/transactions/{tid}/edit").get_data(as_text=True))
    state = form_state(page.find("form", cls="form"))

    assert {k: state[k] for k in ("amount", "type", "category", "date", "description")} == {
        "amount": "1234.56",
        "type": "income",
        "category": "Salary",
        "date": "2026-02-03",
        "description": "Pay",
    }
    assert page.find("h1").text() == "Edit transaction"


def test_edit_updates_the_transaction(client, conn, add, form):
    tid = add(amount_cents=1000, description="before")

    response = client.post(
        f"/transactions/{tid}/edit",
        data=form(amount="99.99", type="income", category="Gift", date="2026-04-01", description="after"),
    )

    assert response.status_code == 303
    row = repository.get_transaction(conn, tid)
    assert (row["amount_cents"], row["type"], row["category"]) == (9999, "income", "Gift")
    assert (row["date"], row["description"]) == ("2026-04-01", "after")


def test_edit_shows_confirmation_after_redirect(client, add, form):
    tid = add()

    html = client.post(f"/transactions/{tid}/edit", data=form(), follow_redirects=True).get_data(as_text=True)

    assert "Transaction updated." in html


def test_edit_with_invalid_input_returns_400_and_changes_nothing(client, conn, add, form):
    tid = add(amount_cents=1000, description="original")

    response = client.post(f"/transactions/{tid}/edit", data=form(amount="-1"))

    assert response.status_code == 400
    assert "Amount must be greater than zero." in response.get_data(as_text=True)
    assert repository.get_transaction(conn, tid)["description"] == "original"


def test_edit_only_changes_the_chosen_transaction(client, conn, add, form):
    first = add(description="first")
    second = add(description="second")

    client.post(f"/transactions/{first}/edit", data=form(description="changed"))

    assert repository.get_transaction(conn, second)["description"] == "second"


def test_edit_missing_transaction_is_404_for_get_and_post(client, form):
    assert client.get("/transactions/999/edit").status_code == 404
    assert client.post("/transactions/999/edit", data=form()).status_code == 404


# --- delete ----------------------------------------------------------------


def test_delete_page_asks_for_confirmation_and_deletes_nothing(client, conn, add):
    tid = add(description="precious", amount_cents=4200)

    response = client.get(f"/transactions/{tid}/delete")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Delete this transaction?" in html
    assert "precious" in html and "R42.00" in html
    assert 'method="post"' in html
    assert repository.get_transaction(conn, tid) is not None


def test_delete_post_removes_only_that_transaction(client, conn, add, form):
    keep = add(description="keep")
    remove = add(description="remove")

    response = client.post(f"/transactions/{remove}/delete", data={"csrf_token": form()["csrf_token"]})

    assert response.status_code == 303
    assert repository.get_transaction(conn, remove) is None
    assert repository.get_transaction(conn, keep) is not None


def test_delete_shows_confirmation_after_redirect(client, add, form):
    tid = add()

    html = client.post(
        f"/transactions/{tid}/delete", data={"csrf_token": form()["csrf_token"]}, follow_redirects=True
    ).get_data(as_text=True)

    assert "Transaction deleted." in html


def test_delete_missing_transaction_is_404_for_get_and_post(client, form):
    assert client.get("/transactions/999/delete").status_code == 404
    assert client.post("/transactions/999/delete", data={"csrf_token": form()["csrf_token"]}).status_code == 404


def test_list_delete_links_go_to_the_confirmation_page_not_straight_to_deleting(client, add):
    tid = add(description="Weekly shop")

    page = parse(client.get("/transactions").get_data(as_text=True))

    table = page.find("table", cls="txn-table")
    link = next(a for a in table.find_all("a") if a.text() == "Delete")
    assert link.get("href").startswith(f"/transactions/{tid}/delete")
    assert "Weekly shop" in link.get("aria-label")  # screen readers know which row
    assert table.find_all("form") == []  # no one-click delete buttons in the list


# --- preserving filters (next) --------------------------------------------


def test_after_creating_the_user_returns_to_their_filtered_list(client, form):
    response = client.post(
        "/transactions/new",
        data=form(next="/transactions?type=expense&category=Food"),
    )

    assert response.headers["Location"] == "/transactions?type=expense&category=Food"


def test_after_editing_the_user_returns_to_their_filtered_list(client, add, form):
    tid = add()

    response = client.post(f"/transactions/{tid}/edit", data=form(next="/transactions?type=expense"))

    assert response.headers["Location"] == "/transactions?type=expense"


def test_after_deleting_the_user_returns_to_their_filtered_list(client, add, form):
    tid = add()

    response = client.post(
        f"/transactions/{tid}/delete",
        data={"csrf_token": form()["csrf_token"], "next": "/transactions?date_from=2026-01-01"},
    )

    assert response.headers["Location"] == "/transactions?date_from=2026-01-01"


def test_the_dashboard_is_an_allowed_place_to_return_to(client, form):
    response = client.post("/transactions/new", data=form(next="/?month=2026-03"))

    assert response.headers["Location"] == "/?month=2026-03"


def test_forms_carry_next_in_a_hidden_field_and_cancel_link(client, add):
    tid = add()

    page = parse(
        client.get(f"/transactions/{tid}/edit?next=/transactions%3Ftype%3Dexpense").get_data(
            as_text=True
        )
    )
    form = page.find("form", cls="form")

    assert form_state(form)["next"] == "/transactions?type=expense"
    cancel = next(a for a in form.find_all("a") if a.text() == "Cancel")
    assert cancel.get("href") == "/transactions?type=expense"


@pytest.mark.parametrize(
    "bad_next",
    [
        "https://evil.example/steal",
        "//evil.example",
        "http://localhost/transactions",
        "/\\evil.example",
        "javascript:alert(1)",
        "/admin",
        "/transactions/new",
        "/transactions\r\nSet-Cookie: x=y",
        " //evil.example",
        "/%2F%2Fevil.example",
        "////evil.example",
        "/transactions/../admin",
        "\t/transactions",
        "/static/css/style.css",
        "",
    ],
)
def test_unsafe_next_addresses_fall_back_to_the_list(client, form, bad_next):
    response = client.post("/transactions/new", data=form(next=bad_next))

    assert response.status_code == 303
    assert response.headers["Location"] == "/transactions"


# --- CSRF protection -------------------------------------------------------


def test_post_without_a_csrf_token_is_rejected_and_saves_nothing(app, conn, form):
    fresh_client = app.test_client()
    data = form()
    del data["csrf_token"]

    response = fresh_client.post("/transactions/new", data=data)

    assert response.status_code == 403
    assert rows(conn) == []


def test_post_with_a_wrong_csrf_token_is_rejected(client, conn, form):
    response = client.post("/transactions/new", data=form(csrf_token="wrong"))

    assert response.status_code == 403
    assert rows(conn) == []


def test_delete_without_a_csrf_token_is_rejected(client, conn, add):
    tid = add()

    response = client.post(f"/transactions/{tid}/delete", data={})

    assert response.status_code == 403
    assert repository.get_transaction(conn, tid) is not None


# --- errors and methods ----------------------------------------------------


def test_unknown_page_is_a_friendly_404(client):
    response = client.get("/nope")

    assert response.status_code == 404
    assert "Back to dashboard" in response.get_data(as_text=True)


def test_transaction_id_must_be_a_number(client):
    assert client.get("/transactions/abc/edit").status_code == 404


def test_wrong_method_is_a_405(client, form):
    assert client.post("/", data=form()).status_code == 405
    assert client.delete("/transactions/1/delete").status_code == 405


def test_get_never_changes_data(client, conn, add):
    tid = add()
    before = [dict(r) for r in rows(conn)]

    for url in ("/", "/transactions", "/transactions/new", f"/transactions/{tid}/edit", f"/transactions/{tid}/delete"):
        client.get(url)

    assert [dict(r) for r in rows(conn)] == before


# --- persistence and pages -------------------------------------------------


def test_created_data_survives_a_new_app_and_client(app, client, form, tmp_path):
    from app import create_app

    client.post("/transactions/new", data=form(description="persisted"))

    second_app = create_app(
        {"TESTING": True, "SECRET_KEY": "other", "DATABASE": str(tmp_path / "test.sqlite")}
    )
    html = second_app.test_client().get("/transactions").get_data(as_text=True)

    assert "persisted" in html


def test_pages_share_navigation_and_mark_the_current_page(client):
    page = parse(client.get("/transactions").get_data(as_text=True))

    current = [a.text() for a in page.find("nav").find_all("a") if a.get("aria-current") == "page"]
    assert current == ["Transactions"]
    assert page.find("html").get("lang") == "en"
    assert page.find("a", cls="skip-link").get("href") == "#main"
    assert page.find(id="main") is not None


def test_static_files_are_served(client):
    for url in ("/static/css/style.css", "/static/js/app.js"):
        with client.get(url) as response:
            assert response.status_code == 200


# --- hardening found during the Stage D review -----------------------------


@pytest.mark.parametrize("huge_id", [2**63, 10**20])
@pytest.mark.parametrize("action", ["edit", "delete"])
def test_ids_too_big_for_the_database_are_a_404_not_a_server_error(client, form, huge_id, action):
    url = f"/transactions/{huge_id}/{action}"

    assert client.get(url).status_code == 404
    assert client.post(url, data=form()).status_code == 404


@pytest.mark.parametrize("text", ["\x00", "ab\x00cd", "a\nb", "a\tb", "\x07", "a\u2028b"])
def test_control_characters_in_a_description_are_a_validation_error_not_a_crash(
    client, conn, form, text
):
    response = client.post("/transactions/new", data=form(description=text))

    assert response.status_code == 400
    assert "line breaks or control characters" in response.get_data(as_text=True)
    assert rows(conn) == []


def test_oversized_post_is_rejected_with_413_and_stores_nothing(client, conn, form):
    response = client.post("/transactions/new", data=form(description="x" * 20_000))

    assert response.status_code == 413
    assert "too large" in response.get_data(as_text=True)
    assert rows(conn) == []


@pytest.mark.parametrize("url", ["/", "/transactions/new", "/nope", "/static/css/style.css"])
def test_every_response_carries_the_security_headers(client, url):
    with client.get(url) as response:
        policy = response.headers["Content-Security-Policy"]
        directives = dict(part.strip().split(" ", 1) for part in policy.split(";"))

        assert directives["default-src"] == "'self'"
        assert directives["frame-ancestors"] == "'none'"
        assert directives["object-src"] == "'none'"
        # Inline styles are allowed (the bar widths); inline scripts never are.
        assert [name for name, value in directives.items() if "'unsafe-inline'" in value] == [
            "style-src"
        ]
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["Referrer-Policy"] == "same-origin"


def test_security_headers_are_also_sent_on_rejected_posts(client):
    response = client.post("/transactions/new", data={})  # no CSRF token -> 403

    assert response.status_code == 403
    assert "Content-Security-Policy" in response.headers


def test_templates_use_nothing_the_content_security_policy_would_block():
    # The CSP forbids inline scripts, inline event handlers and other websites'
    # files. Browsers are not available in this test suite, so check the source.
    templates = Path(__file__).parent.parent / "app" / "templates"
    for template in templates.glob("*.html"):
        source = template.read_text(encoding="utf-8")
        assert not re.search(r"<script(?![^>]*\bsrc=)", source), template.name
        assert not re.search(r"\son[a-z]+\s*=", source), template.name
        assert "javascript:" not in source, template.name
        assert "http://" not in source and "https://" not in source, template.name


def test_session_cookie_is_httponly_and_samesite_lax(app):
    response = app.test_client().get("/transactions/new")  # a new visitor gets a cookie

    cookie = response.headers["Set-Cookie"]
    assert cookie.startswith("session=")
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie


def test_a_405_response_lists_the_allowed_methods(client, form):
    response = client.post("/", data=form())

    assert response.status_code == 405
    assert "GET" in response.headers["Allow"]


def test_unexpected_errors_show_a_generic_page_without_internal_details(app, client, monkeypatch):
    def explode(*args, **kwargs):
        raise RuntimeError("secret internal detail /home/someone/spendwise.sqlite")

    monkeypatch.setattr(services, "get_totals", explode)
    app.config["PROPAGATE_EXCEPTIONS"] = False  # behave like production, not test mode

    response = client.get("/")
    body = response.get_data(as_text=True)

    assert response.status_code == 500
    assert "Something went wrong" in body
    assert "secret internal detail" not in body and "Traceback" not in body
    assert "Content-Security-Policy" in response.headers


def test_editing_a_transaction_that_vanishes_mid_request_is_a_404(client, add, form, monkeypatch):
    tid = add()
    monkeypatch.setattr(repository, "update_transaction", lambda *args, **kwargs: False)

    response = client.post(f"/transactions/{tid}/edit", data=form())

    assert response.status_code == 404
    assert "Transaction updated." not in client.get("/transactions").get_data(as_text=True)


def test_deleting_a_transaction_that_vanishes_mid_request_is_a_404(client, add, form, monkeypatch):
    tid = add()
    monkeypatch.setattr(repository, "delete_transaction", lambda *args, **kwargs: False)

    response = client.post(f"/transactions/{tid}/delete", data={"csrf_token": form()["csrf_token"]})

    assert response.status_code == 404
    assert "Transaction deleted." not in client.get("/transactions").get_data(as_text=True)


@pytest.mark.parametrize("page, rows_afterwards", [("new", 2), ("edit", 1), ("delete", 0)])
def test_every_form_page_includes_a_csrf_token_that_works(app, conn, add, page, rows_afterwards):
    tid = add(description="existing")
    urls = {
        "new": "/transactions/new",
        "edit": f"/transactions/{tid}/edit",
        "delete": f"/transactions/{tid}/delete",
    }
    visitor = app.test_client()  # a brand-new browser: no session, no token yet
    html = visitor.get(urls[page]).get_data(as_text=True)
    post_form = next(f for f in parse(html).find_all("form") if f.get("method") == "post")
    submission = form_state(post_form)  # exactly what the browser would send
    if page == "new":  # the add form starts blank, so fill it in like a person would
        submission.update(
            amount="12.50", type="expense", category="Food", date="2026-03-15", description="typed"
        )

    response = visitor.post(urls[page], data=submission)

    assert response.status_code == 303
    assert len(rows(conn)) == rows_afterwards


def test_dashboard_marks_only_negative_monthly_net_as_an_expense_colour(client, add):
    add(type="expense", category="Food", amount_cents=5000, date="2026-03-10")  # net -R50.00
    add(type="income", category="Salary", amount_cents=9000, date="2026-02-10")  # net +R90.00

    page = parse(client.get("/").get_data(as_text=True))
    table = page.find("section", aria_labelledby="monthly-heading").find("table")
    classes_by_month = {}
    for row in table.find("tbody").find_all("tr"):
        cells = [c for c in row.children if c.tag in ("td", "th")]
        classes_by_month[cells[0].text()] = cells[3].classes

    assert "amount-expense" in classes_by_month["March 2026"]
    assert "amount-expense" not in classes_by_month["February 2026"]

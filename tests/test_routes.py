import html as html_lib
import re

import pytest

from app import repository


def rows(conn):
    return repository.list_transactions(conn)


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

    html = client.get("/").get_data(as_text=True)

    assert "R5,000.00" in html  # income
    assert "R1,234.55" in html  # expenses
    assert "R3,765.45" in html  # net balance


def test_dashboard_totals_change_when_data_changes(client, add):
    add(amount_cents=100, type="income", category="Salary", date="2026-03-01")
    first = client.get("/").get_data(as_text=True)
    add(amount_cents=900, type="income", category="Salary", date="2026-03-02")
    second = client.get("/").get_data(as_text=True)

    assert "R1.00" in first and "R10.00" not in first
    assert "R10.00" in second


def test_dashboard_negative_net_balance_is_shown_and_flagged(client, add):
    add(amount_cents=1000, type="income", category="Salary", date="2026-03-01")
    add(amount_cents=5000, type="expense", category="Food", date="2026-03-02")

    html = client.get("/").get_data(as_text=True)

    assert "-R40.00" in html
    assert "stat-negative" in html


def test_dashboard_monthly_table_lists_each_month(client, add):
    add(amount_cents=1000, type="income", category="Salary", date="2026-02-10")
    add(amount_cents=300, type="expense", category="Food", date="2026-03-10")

    html = client.get("/").get_data(as_text=True)

    assert "February 2026" in html
    assert "March 2026" in html
    assert "date_from=2026-03-01" in html and "date_to=2026-03-31" in html


def test_dashboard_defaults_to_latest_month_with_expenses(client, add):
    add(amount_cents=1000, type="expense", category="Food", date="2026-01-10")
    add(amount_cents=9000, type="income", category="Salary", date="2026-02-10")

    html = client.get("/").get_data(as_text=True)

    assert "Total expenses in January 2026" in html


def test_dashboard_month_picker_changes_the_breakdown(client, add):
    add(amount_cents=1000, type="expense", category="Food", date="2026-01-10")
    add(amount_cents=7000, type="expense", category="Rent", date="2026-02-10")

    january = client.get("/?month=2026-01").get_data(as_text=True)
    february = client.get("/?month=2026-02").get_data(as_text=True)

    january_breakdown = january.split("Expenses by category")[1].split("Recent transactions")[0]
    february_breakdown = february.split("Expenses by category")[1].split("Recent transactions")[0]

    assert "Total expenses in January 2026" in january
    assert "100.0%" in january_breakdown
    assert "Rent" not in january_breakdown
    assert "Total expenses in February 2026" in february
    assert "Rent" in february_breakdown and "R70.00" in february_breakdown
    assert "Food" not in february_breakdown


def test_dashboard_breakdown_shows_percentages(client, add):
    add(amount_cents=3000, type="expense", category="Food", date="2026-03-10")
    add(amount_cents=7000, type="expense", category="Rent", date="2026-03-10")

    html = client.get("/?month=2026-03").get_data(as_text=True)

    assert "70.0%" in html and "30.0%" in html
    assert "width: 70.0%" in html


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

    html = client.get("/transactions").get_data(as_text=True)

    assert html.index("newer") < html.index("older")
    assert "2 transactions" in html
    assert "R2,500.00" in html and "R10.00" in html and "R2,490.00" in html


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

    html = client.get(
        "/transactions?type=expense&category=Food&date_from=2026-02-01&date_to=2026-02-28"
    ).get_data(as_text=True)

    assert "match-me" in html and "other-cat" not in html
    assert '<option value="expense" selected>' in html
    assert '<option value="Food" selected>' in html
    assert 'value="2026-02-01"' in html and 'value="2026-02-28"' in html


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


def test_new_form_renders_with_accessible_labels(client):
    response = client.get("/transactions/new")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    for field in ("amount", "category", "date", "description"):
        assert f'<label for="{field}">' in html
    assert "<legend>Type</legend>" in html
    assert 'name="csrf_token"' in html


def test_new_form_preselects_type_from_query(client):
    html = client.get("/transactions/new?type=income").get_data(as_text=True)

    assert 'id="type-income" name="type" value="income" required checked' in html


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
        data=form(amount="abc", description="Keep this text", date="2026-03-20"),
    )
    html = response.get_data(as_text=True)

    assert 'value="abc"' in html
    assert 'value="Keep this text"' in html
    assert 'value="2026-03-20"' in html


def test_invalid_create_shows_an_error_summary_and_marks_fields_invalid(client, form):
    response = client.post("/transactions/new", data=form(amount="", description=""))
    html = response.get_data(as_text=True)

    assert 'id="error-summary"' in html
    assert 'href="#amount"' in html and 'href="#description"' in html
    assert 'aria-invalid="true"' in html
    assert 'id="error-amount"' in html


def test_income_category_on_expense_is_rejected_by_the_server(client, conn, form):
    response = client.post("/transactions/new", data=form(type="expense", category="Freelance"))

    assert response.status_code == 400
    assert rows(conn) == []


# --- edit ------------------------------------------------------------------


def test_edit_form_is_prefilled(client, add):
    tid = add(amount_cents=123456, type="income", category="Salary", date="2026-02-03", description="Pay")

    html = client.get(f"/transactions/{tid}/edit").get_data(as_text=True)

    assert 'value="1234.56"' in html
    assert 'value="Pay"' in html
    assert 'value="2026-02-03"' in html
    assert 'value="income" required checked' in html
    assert '<option value="Salary" selected>' in html
    assert "Edit transaction" in html


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


def test_list_delete_links_go_to_the_confirmation_page_not_straight_to_deleting(client, conn, add):
    tid = add()

    html = client.get("/transactions").get_data(as_text=True)

    assert f'href="/transactions/{tid}/delete' in html
    assert "<form" not in html.split("<table")[1].split("</table>")[0]


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

    html = client.get(f"/transactions/{tid}/edit?next=/transactions%3Ftype%3Dexpense").get_data(as_text=True)

    assert '<input type="hidden" name="next" value="/transactions?type=expense">' in html
    assert 'href="/transactions?type=expense">Cancel' in html


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


def test_every_form_page_includes_a_csrf_token_that_works(app, conn, form):
    fresh_client = app.test_client()
    html = fresh_client.get("/transactions/new").get_data(as_text=True)
    token = html.split('name="csrf_token" value="')[1].split('"')[0]

    response = fresh_client.post("/transactions/new", data=form(csrf_token=token))

    assert response.status_code == 303
    assert len(rows(conn)) == 1


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
    html = client.get("/transactions").get_data(as_text=True)

    assert 'aria-current="page">Transactions' in html
    assert "Skip to main content" in html
    assert '<html lang="en">' in html


def test_static_files_are_served(client):
    assert client.get("/static/css/style.css").status_code == 200
    assert client.get("/static/js/app.js").status_code == 200

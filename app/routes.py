"""Web routes: they handle HTTP and nothing else.

Each route reads the request, calls the services/repository layers to do the
real work, and renders a template. Validation, money handling and summary
maths all live in `services`; SQL lives in `repository`.

Safety measures in this file:
- Anything that changes data is a POST. The "delete" link only opens a
  confirmation page; the data is deleted when that page's form is POSTed.
- Every POST must carry a CSRF token (see `_check_csrf`), so another website
  cannot make your browser submit a form to Spendwise on your behalf.
- The `next` address (where to go after saving) is checked so it can only
  point at Spendwise's own list or dashboard (see `_safe_next`).
"""

import hmac
import secrets
from urllib.parse import urlsplit

from flask import (
    Blueprint,
    abort,
    flash,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.exceptions import HTTPException

from app import repository, services
from app.db import get_db
from app.services import ValidationError

bp = Blueprint("main", __name__)

RECENT_LIMIT = 5

# SQLite integers are 64-bit, so a larger id cannot exist. Capping the URL
# converter turns absurd ids into an ordinary 404 instead of a database error.
_ID = "<int(max=9223372036854775807):transaction_id>"

# Only allow the page's own files; scripts and styles must come from this site.
# "unsafe-inline" is for styles only: the category bars set their width inline.
_CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "frame-ancestors 'none'",  # nobody may show these pages inside a frame
        "form-action 'self'",
        "base-uri 'self'",
        "object-src 'none'",
    ]
)

# Small display helpers made available inside templates.
bp.add_app_template_filter(services.format_cents, "rand")
bp.add_app_template_filter(services.format_month, "month_label")
bp.add_app_template_global(services.month_bounds, "month_bounds")


# --- CSRF protection -------------------------------------------------------


def _csrf_token():
    """Return this visitor's CSRF token, creating one on first use."""
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_hex(32)
        session["csrf_token"] = token
    return token


@bp.app_context_processor
def _template_context():
    return {
        "csrf_token": _csrf_token,
        "income_categories": services.INCOME_CATEGORIES,
        "expense_categories": services.EXPENSE_CATEGORIES,
    }


@bp.after_app_request
def _add_security_headers(response):
    response.headers["Content-Security-Policy"] = _CONTENT_SECURITY_POLICY
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


@bp.before_request
def _check_csrf():
    if request.method != "POST":
        return
    expected = session.get("csrf_token", "")
    sent = request.form.get("csrf_token", "")
    if not expected or not hmac.compare_digest(sent.encode(), expected.encode()):
        abort(403)


# --- helpers ---------------------------------------------------------------


def _current_url():
    """The address of the page being viewed, including its query string."""
    return request.full_path.rstrip("?")


def _safe_next(value):
    """Return `value` if it is a safe place to redirect to, else the list page.

    Only the transaction list and the dashboard are allowed, and only as
    relative addresses, so the `next` parameter can never send someone to
    another website.
    """
    default = url_for("main.transaction_list")
    # Obviously suspicious values are refused outright. The result below is also
    # rebuilt from just the path and query, so this is defence in depth.
    if not value or any(ord(char) < 32 for char in value) or "\\" in value:
        return default
    parts = urlsplit(value)
    if parts.scheme or parts.netloc or value.startswith("//"):
        return default
    if parts.path not in ("/", url_for("main.transaction_list")):
        return default
    return parts.path + (f"?{parts.query}" if parts.query else "")


def _get_or_404(conn, transaction_id):
    transaction = repository.get_transaction(conn, transaction_id)
    if transaction is None:
        abort(404)
    return transaction


def _render_form(mode, form, errors, next_url, transaction=None):
    status = 400 if errors else 200
    html = render_template(
        "form.html",
        mode=mode,
        form=form,
        errors=errors,
        next_url=next_url,
        transaction=transaction,
    )
    return html, status


# --- dashboard -------------------------------------------------------------


@bp.get("/")
def dashboard():
    conn = get_db()
    totals = services.get_totals(conn)
    monthly = services.get_monthly_summary(conn)
    available_months = [summary.month for summary in monthly]

    status = 200
    month_error = None
    selected = None
    requested = request.args.get("month", "").strip()
    if requested:
        try:
            selected = services.parse_month(requested)
        except ValidationError as error:
            month_error = str(error)
            status = 400
    if selected is None:
        selected = services.default_breakdown_month(monthly)

    # Make sure the month being shown is also one of the picker's choices.
    month_options = list(available_months)
    if selected and selected not in month_options:
        month_options = sorted(month_options + [selected], reverse=True)

    html = render_template(
        "dashboard.html",
        totals=totals,
        monthly=monthly,
        breakdown=services.get_category_breakdown(conn, selected),
        selected_month=selected,
        month_options=month_options,
        month_error=month_error,
        recent=repository.list_transactions(conn, limit=RECENT_LIMIT),
        next_url=_current_url(),
    )
    return html, status


# --- transaction list and filters -----------------------------------------


@bp.get("/transactions")
def transaction_list():
    conn = get_db()
    result = services.validate_filters(request.args)

    status = 200
    rows = []
    totals = None
    if result.ok:
        rows = repository.list_transactions(conn, **result.values)
        totals = services.get_totals(conn, **result.values)
    else:
        status = 400

    html = render_template(
        "transactions.html",
        rows=rows,
        totals=totals,
        form=request.args,
        errors=result.errors,
        filters_active=any(result.values.values()),
        has_any_transactions=bool(repository.list_transactions(conn, limit=1)),
        next_url=_current_url(),
    )
    return html, status


# --- add, edit, delete -----------------------------------------------------


@bp.route("/transactions/new", methods=["GET", "POST"])
def new_transaction():
    next_url = _safe_next(request.values.get("next"))

    if request.method == "POST":
        result = services.validate_transaction(request.form)
        if result.ok:
            repository.create_transaction(get_db(), **result.values)
            flash("Transaction added.", "success")
            return redirect(next_url, code=303)
        return _render_form("new", request.form, result.errors, next_url)

    form = {"type": request.args.get("type", "")}
    return _render_form("new", form, {}, next_url)


@bp.route(f"/transactions/{_ID}/edit", methods=["GET", "POST"])
def edit_transaction(transaction_id):
    conn = get_db()
    transaction = _get_or_404(conn, transaction_id)
    next_url = _safe_next(request.values.get("next"))

    if request.method == "POST":
        result = services.validate_transaction(request.form)
        if result.ok:
            if not repository.update_transaction(conn, transaction_id, **result.values):
                abort(404)  # it was deleted while the form was open
            flash("Transaction updated.", "success")
            return redirect(next_url, code=303)
        return _render_form("edit", request.form, result.errors, next_url, transaction)

    form = {
        "amount": services.cents_to_input(transaction["amount_cents"]),
        "type": transaction["type"],
        "category": transaction["category"],
        "date": transaction["date"],
        "description": transaction["description"],
    }
    return _render_form("edit", form, {}, next_url, transaction)


@bp.route(f"/transactions/{_ID}/delete", methods=["GET", "POST"])
def delete_transaction(transaction_id):
    conn = get_db()
    transaction = _get_or_404(conn, transaction_id)
    next_url = _safe_next(request.values.get("next"))

    if request.method == "POST":
        if not repository.delete_transaction(conn, transaction_id):
            abort(404)
        flash("Transaction deleted.", "success")
        return redirect(next_url, code=303)

    # GET only shows the confirmation page. Nothing is deleted here.
    return render_template(
        "confirm_delete.html", transaction=transaction, next_url=next_url
    )


# --- error pages -----------------------------------------------------------

_ERROR_MESSAGES = {
    403: "That form could not be verified. Go back, reload the page and try again.",
    404: "We couldn't find that page or transaction. It may have been deleted.",
    405: "That action isn't available at this address.",
    413: "That request was too large to be a transaction form.",
}


@bp.app_errorhandler(HTTPException)
def _handle_http_error(error):
    message = _ERROR_MESSAGES.get(error.code, "Something went wrong with that request.")
    response = make_response(
        render_template("error.html", code=error.code, name=error.name, message=message),
        error.code,
    )
    # Keep any headers the status requires, such as "Allow" on a 405.
    for name, value in error.get_headers():
        if name.lower() != "content-type":
            response.headers[name] = value
    return response

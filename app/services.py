"""Business logic: input validation, money handling and summaries.

Nothing here knows about Flask or HTTP. The validation functions turn raw form
text into clean values (or friendly error messages), and the summary functions
ask the repository for numbers and shape them for the pages.

Money rule: amounts are never floats. Text like "150.50" is converted to the
integer 15050 (cents) by reading the digits directly, and all arithmetic after
that is whole-number arithmetic.
"""

import calendar
import re
from dataclasses import dataclass, field
from datetime import date as _date

from app import repository

TRANSACTION_TYPES = ("income", "expense")

# Income and expenses have their own category lists. The two "Other" entries
# have different names so every category name is unique, which keeps the
# category filter unambiguous.
INCOME_CATEGORIES = ("Salary", "Freelance", "Gift", "Other income")
EXPENSE_CATEGORIES = (
    "Food",
    "Transport",
    "Rent",
    "Utilities",
    "Entertainment",
    "Health",
    "Other expense",
)
CATEGORIES_BY_TYPE = {"income": INCOME_CATEGORIES, "expense": EXPENSE_CATEGORIES}
CATEGORIES = INCOME_CATEGORIES + EXPENSE_CATEGORIES

MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

MAX_DESCRIPTION_LENGTH = 200
MAX_AMOUNT_DIGITS = 9  # up to R999,999,999.99
MIN_YEAR = 1900
MAX_YEAR = 2100

# [0-9] is used instead of \d because \d also matches digits from other
# alphabets (e.g. Arabic-Indic numerals), which we do not want to accept.
_AMOUNT_RE = re.compile(r"^([0-9]+)(?:\.([0-9]+))?$")
_DATE_RE = re.compile(r"^([0-9]{4})-([0-9]{2})-([0-9]{2})$")
_MONTH_RE = re.compile(r"^([0-9]{4})-([0-9]{2})$")


class ValidationError(ValueError):
    """Raised by the parse_* functions. The message is safe to show to users."""


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of validating a whole form.

    `values` holds the cleaned values for fields that were valid. `errors` maps
    a form field name to a message. Always check `ok` before using `values`.
    """

    values: dict = field(default_factory=dict)
    errors: dict = field(default_factory=dict)

    @property
    def ok(self):
        return not self.errors


def _clean(raw):
    """Turn a missing value into '' and strip surrounding whitespace."""
    return "" if raw is None else str(raw).strip()


# --- parsing single fields -------------------------------------------------


def parse_amount_to_cents(raw):
    """Convert text like '150', '150.5' or 'R150.50' to integer cents."""
    text = _clean(raw)
    if not text:
        raise ValidationError("Amount is required.")
    if text[0] in "Rr":
        text = text[1:].strip()
    if text.startswith("-"):
        raise ValidationError("Amount must be greater than zero.")

    match = _AMOUNT_RE.match(text)
    if not match:
        raise ValidationError(
            "Enter a valid amount such as 150 or 150.50 (digits and a decimal point only)."
        )
    rands, decimals = match.group(1), match.group(2) or ""
    if len(decimals) > 2:
        raise ValidationError("Amount can have at most two decimal places.")
    # Drop leading zeros and check the length BEFORE converting: Python refuses
    # to convert extremely long digit strings to int, and we must never get there.
    rands = rands.lstrip("0") or "0"
    if len(rands) > MAX_AMOUNT_DIGITS:
        raise ValidationError("Amount is too large.")

    cents = int(rands) * 100 + int((decimals + "00")[:2])
    if cents <= 0:
        raise ValidationError("Amount must be greater than zero.")
    return cents


def parse_type(raw):
    text = _clean(raw).lower()
    if not text:
        raise ValidationError("Type is required.")
    if text not in TRANSACTION_TYPES:
        raise ValidationError("Type must be either income or expense.")
    return text


def parse_category(raw, transaction_type=None):
    """Check the category is on the list.

    If `transaction_type` is 'income' or 'expense', the category must belong to
    that type's list; otherwise any listed category is accepted (used by filters).
    """
    text = _clean(raw)
    if not text:
        raise ValidationError("Category is required.")
    if transaction_type in CATEGORIES_BY_TYPE:
        if text not in CATEGORIES_BY_TYPE[transaction_type]:
            raise ValidationError(f"Choose an {transaction_type} category from the list.")
    elif text not in CATEGORIES:
        raise ValidationError("Choose a category from the list.")
    return text


def parse_date(raw):
    """Accept only real calendar dates written as YYYY-MM-DD."""
    text = _clean(raw)
    if not text:
        raise ValidationError("Date is required.")
    match = _DATE_RE.match(text)
    if not match:
        raise ValidationError("Enter the date as YYYY-MM-DD, for example 2026-03-15.")
    year, month, day = (int(part) for part in match.groups())
    try:
        _date(year, month, day)
    except ValueError:
        raise ValidationError("That date does not exist on the calendar.") from None
    if not MIN_YEAR <= year <= MAX_YEAR:
        raise ValidationError(f"Year must be between {MIN_YEAR} and {MAX_YEAR}.")
    return text


def parse_month(raw):
    """Accept a month written as YYYY-MM."""
    text = _clean(raw)
    match = _MONTH_RE.match(text)
    if not match:
        raise ValidationError("Enter the month as YYYY-MM, for example 2026-03.")
    year, month = (int(part) for part in match.groups())
    if not 1 <= month <= 12 or not MIN_YEAR <= year <= MAX_YEAR:
        raise ValidationError("That month is not valid.")
    return text


def parse_description(raw):
    text = _clean(raw)
    if not text:
        raise ValidationError("Description is required.")
    if len(text) > MAX_DESCRIPTION_LENGTH:
        raise ValidationError(
            f"Description must be {MAX_DESCRIPTION_LENGTH} characters or fewer."
        )
    return text


# --- validating whole forms ------------------------------------------------


def _run(parsers, data):
    """Apply (field_name, output_key, parser) triples; collect every error."""
    values, errors = {}, {}
    for field_name, key, parser in parsers:
        try:
            values[key] = parser(data.get(field_name))
        except ValidationError as error:
            errors[field_name] = str(error)
    return values, errors


def validate_transaction(data):
    """Validate the add/edit form.

    `data` is anything with a `.get()` (a dict, or Flask's request.form).
    On success `values` has the keys the repository expects:
    amount_cents, type, category, date, description.
    """
    values, errors = _run(
        [
            ("amount", "amount_cents", parse_amount_to_cents),
            ("type", "type", parse_type),
        ],
        data,
    )

    # The category must match the type, so it is checked after the type
    # (if the type itself was invalid, any listed category is accepted).
    try:
        values["category"] = parse_category(data.get("category"), values.get("type"))
    except ValidationError as error:
        errors["category"] = str(error)

    more_values, more_errors = _run(
        [
            ("date", "date", parse_date),
            ("description", "description", parse_description),
        ],
        data,
    )
    values.update(more_values)
    errors.update(more_errors)
    return ValidationResult(values, errors)


def _optional(parser):
    """Wrap a parser so a blank value means 'no filter' (None)."""

    def wrapper(raw):
        return parser(raw) if _clean(raw) else None

    return wrapper


def validate_filters(data):
    """Validate the filter form. Blank fields mean 'do not filter on this'.

    On success `values` has the keys type, category, date_from and date_to
    (None when unset), ready to pass to the repository as keyword arguments.
    """
    values, errors = _run(
        [
            ("type", "type", _optional(parse_type)),
            ("category", "category", _optional(parse_category)),
            ("date_from", "date_from", _optional(parse_date)),
            ("date_to", "date_to", _optional(parse_date)),
        ],
        data,
    )
    start, end = values.get("date_from"), values.get("date_to")
    if start and end and start > end:  # ISO dates compare correctly as text
        errors["date_to"] = "End date must be on or after the start date."
    return ValidationResult(values, errors)


# --- formatting money ------------------------------------------------------


def format_cents(cents):
    """Format cents as South African rand for display: 123456 -> 'R1,234.56'."""
    sign = "-" if cents < 0 else ""
    rands, remainder = divmod(abs(cents), 100)
    return f"{sign}R{rands:,}.{remainder:02d}"


def cents_to_input(cents):
    """Format cents for a form field: 123456 -> '1234.56' (no symbol or commas)."""
    rands, remainder = divmod(cents, 100)
    return f"{rands}.{remainder:02d}"


def format_month(month):
    """'2026-03' -> 'March 2026'. Raises ValidationError for an invalid month."""
    month = parse_month(month)
    return f"{MONTH_NAMES[int(month[5:7]) - 1]} {month[:4]}"


def month_bounds(month):
    """'2026-02' -> ('2026-02-01', '2026-02-28'): first and last day of the month."""
    month = parse_month(month)
    last_day = calendar.monthrange(int(month[:4]), int(month[5:7]))[1]
    return f"{month}-01", f"{month}-{last_day:02d}"


# --- summaries -------------------------------------------------------------


@dataclass(frozen=True)
class Totals:
    income_cents: int
    expense_cents: int

    @property
    def net_cents(self):
        return self.income_cents - self.expense_cents


@dataclass(frozen=True)
class MonthSummary:
    month: str  # 'YYYY-MM'
    income_cents: int
    expense_cents: int

    @property
    def net_cents(self):
        return self.income_cents - self.expense_cents


@dataclass(frozen=True)
class CategoryShare:
    category: str
    total_cents: int
    percent_tenths: int  # 1 decimal place as an integer: 333 means 33.3%

    @property
    def percent_label(self):
        return f"{self.percent_tenths // 10}.{self.percent_tenths % 10}%"


@dataclass(frozen=True)
class CategoryBreakdown:
    total_cents: int
    shares: tuple


def get_totals(conn, **filters):
    """Income, expenses and net balance. Optional filters as in the repository."""
    income, expense = repository.get_totals(conn, **filters)
    return Totals(income, expense)


def get_monthly_summary(conn):
    """One MonthSummary per month that has transactions, newest first."""
    return [
        MonthSummary(row["month"], row["income_cents"], row["expense_cents"])
        for row in repository.get_monthly_totals(conn)
    ]


def default_breakdown_month(summaries):
    """Pick the month the category breakdown should show first.

    That is the most recent month that actually has expenses (a month with only
    income would give an empty breakdown). Returns None if there is no data.
    `summaries` is the newest-first list from get_monthly_summary.
    """
    for summary in summaries:
        if summary.expense_cents > 0:
            return summary.month
    return summaries[0].month if summaries else None


def get_category_breakdown(conn, month=None):
    """Expenses grouped by category, with each category's share of the total.

    Pass `month` as 'YYYY-MM' to look at a single month. Raises ValidationError
    if the month is not valid.
    """
    if month is not None:
        month = parse_month(month)
    rows = repository.get_expense_totals_by_category(conn, month)
    grand_total = sum(row["total_cents"] for row in rows)

    shares = []
    for row in rows:
        # Whole-number arithmetic, rounded half up: (part * 1000 / total) to 1 d.p.
        tenths = (row["total_cents"] * 1000 + grand_total // 2) // grand_total
        shares.append(CategoryShare(row["category"], row["total_cents"], tenths))
    return CategoryBreakdown(grand_total, tuple(shares))

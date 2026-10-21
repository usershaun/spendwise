import pytest

from app import db, repository


@pytest.fixture
def conn(tmp_path):
    """A connection to a fresh, empty database in a temporary folder.

    pytest deletes tmp_path afterwards, so tests never touch real data.
    """
    connection = db.connect(tmp_path / "test.sqlite")
    db.init_db(connection)
    yield connection
    connection.close()


@pytest.fixture
def add(conn):
    """Return a helper that inserts a transaction, with sensible defaults."""

    def _add(
        amount_cents=1000,
        type="expense",
        category="Food",
        date="2026-01-15",
        description="Test transaction",
    ):
        return repository.create_transaction(
            conn,
            amount_cents=amount_cents,
            type=type,
            category=category,
            date=date,
            description=description,
        )

    return _add


@pytest.fixture
def app(conn, tmp_path):
    """A Flask app using the same temporary database file as the `conn` fixture."""
    from app import create_app

    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret-key",
            "DATABASE": str(tmp_path / "test.sqlite"),
        }
    )


TEST_CSRF_TOKEN = "test-csrf-token"


@pytest.fixture
def client(app):
    """A browser-like client that already holds a valid CSRF token."""
    test_client = app.test_client()
    with test_client.session_transaction() as session:
        session["csrf_token"] = TEST_CSRF_TOKEN
    return test_client


@pytest.fixture
def form():
    """Build form data for POST requests, including the CSRF token."""

    def _form(**overrides):
        data = {
            "csrf_token": TEST_CSRF_TOKEN,
            "amount": "250.75",
            "type": "expense",
            "category": "Food",
            "date": "2026-03-15",
            "description": "Groceries",
        }
        data.update(overrides)
        return {key: value for key, value in data.items() if value is not None}

    return _form

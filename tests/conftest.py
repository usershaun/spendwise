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

"""Database connection handling.

`connect` and `init_db` are plain sqlite3 helpers that know nothing about Flask,
so tests and scripts can use them directly. `get_db`, `close_db` and `init_app`
are the small Flask glue that gives each web request its own connection.
"""

import sqlite3
from pathlib import Path

from flask import current_app, g

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(database_path):
    """Open a SQLite connection whose rows can be read by column name."""
    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn):
    """Create the tables if they do not exist yet. Safe to call repeatedly."""
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


def get_db():
    """Return this request's connection, opening it on first use."""
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(exception=None):
    """Close the request's connection (registered as a teardown handler)."""
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_app(app):
    """Wire the database into a Flask app and make sure the tables exist."""
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db(get_db())

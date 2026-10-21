"""Spendwise: a small personal expense tracker.

`create_app` is the Flask "application factory": calling it builds a fresh app.
Tests call it with their own settings; `flask --app app run` calls it with none.

Environment variables
---------------------
SPENDWISE_ENV         "production" (the default) or "development".
SPENDWISE_SECRET_KEY  Required in production. Used to sign sessions and flash
                      messages. Generate one with:
                      python -c "import secrets; print(secrets.token_hex(32))"
"""

import os
from pathlib import Path

from flask import Flask

from app import db

DEV_FALLBACK_SECRET_KEY = "dev-only-insecure-key-never-use-in-production"
MIN_SECRET_KEY_LENGTH = 32
ENVIRONMENTS = ("production", "development")


def resolve_environment(environ=None):
    """Return 'production' or 'development'. Unset means production (the safe choice)."""
    environ = os.environ if environ is None else environ
    value = (environ.get("SPENDWISE_ENV") or "").strip().lower() or "production"
    if value not in ENVIRONMENTS:
        raise RuntimeError(
            f"SPENDWISE_ENV must be one of {', '.join(ENVIRONMENTS)} (got {value!r})."
        )
    return value


def resolve_secret_key(environ=None):
    """Decide which secret key to use, refusing to start insecurely.

    - development: use SPENDWISE_SECRET_KEY if set, else a fixed insecure key
      that is fine on your own machine.
    - production: SPENDWISE_SECRET_KEY must be set, long enough, and must not
      be the development fallback. Otherwise we raise instead of running with
      a guessable key.
    """
    environ = os.environ if environ is None else environ
    environment = resolve_environment(environ)
    key = (environ.get("SPENDWISE_SECRET_KEY") or "").strip()

    if environment == "development":
        return key or DEV_FALLBACK_SECRET_KEY

    if not key:
        raise RuntimeError(
            "SPENDWISE_SECRET_KEY is not set. In production it is required. "
            'Generate one with: python -c "import secrets; print(secrets.token_hex(32))" '
            "or set SPENDWISE_ENV=development for local use."
        )
    if key == DEV_FALLBACK_SECRET_KEY:
        raise RuntimeError("SPENDWISE_SECRET_KEY must not be the development fallback key.")
    if len(key) < MIN_SECRET_KEY_LENGTH:
        raise RuntimeError(
            f"SPENDWISE_SECRET_KEY is too short (minimum {MIN_SECRET_KEY_LENGTH} characters)."
        )
    return key


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        DATABASE=os.path.join(app.instance_path, "spendwise.sqlite"),
    )
    if test_config is not None:
        app.config.from_mapping(test_config)

    # Tests may supply their own SECRET_KEY; otherwise it comes from the
    # environment and the app refuses to start if production has no valid key.
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = resolve_secret_key()

    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    db.init_app(app)
    return app

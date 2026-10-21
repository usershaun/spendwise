import pytest

import app as app_module
from app import create_app, db

GOOD_KEY = "a" * 40


# --- environment -----------------------------------------------------------


def test_unset_environment_means_production():
    assert app_module.resolve_environment({}) == "production"


def test_blank_environment_means_production():
    assert app_module.resolve_environment({"SPENDWISE_ENV": "  "}) == "production"


def test_environment_is_case_insensitive():
    assert app_module.resolve_environment({"SPENDWISE_ENV": "Development"}) == "development"


def test_unknown_environment_is_refused():
    with pytest.raises(RuntimeError, match="SPENDWISE_ENV"):
        app_module.resolve_environment({"SPENDWISE_ENV": "prod"})


# --- secret key ------------------------------------------------------------


def test_production_without_a_key_refuses_to_start():
    with pytest.raises(RuntimeError, match="SPENDWISE_SECRET_KEY is not set"):
        app_module.resolve_secret_key({})


def test_production_with_blank_key_refuses_to_start():
    with pytest.raises(RuntimeError, match="not set"):
        app_module.resolve_secret_key({"SPENDWISE_ENV": "production", "SPENDWISE_SECRET_KEY": "   "})


def test_production_with_short_key_refuses_to_start():
    with pytest.raises(RuntimeError, match="too short"):
        app_module.resolve_secret_key({"SPENDWISE_SECRET_KEY": "short"})


def test_production_refuses_the_development_fallback_key():
    with pytest.raises(RuntimeError, match="development fallback"):
        app_module.resolve_secret_key(
            {"SPENDWISE_SECRET_KEY": app_module.DEV_FALLBACK_SECRET_KEY}
        )


def test_production_with_a_good_key_uses_it():
    assert app_module.resolve_secret_key({"SPENDWISE_SECRET_KEY": GOOD_KEY}) == GOOD_KEY


def test_development_without_a_key_uses_the_fallback():
    key = app_module.resolve_secret_key({"SPENDWISE_ENV": "development"})

    assert key == app_module.DEV_FALLBACK_SECRET_KEY


def test_development_with_a_key_prefers_it():
    key = app_module.resolve_secret_key(
        {"SPENDWISE_ENV": "development", "SPENDWISE_SECRET_KEY": "my-own-key"}
    )

    assert key == "my-own-key"


# --- create_app ------------------------------------------------------------


def test_create_app_in_production_without_a_key_fails(monkeypatch, tmp_path):
    monkeypatch.delenv("SPENDWISE_ENV", raising=False)
    monkeypatch.delenv("SPENDWISE_SECRET_KEY", raising=False)

    with pytest.raises(RuntimeError, match="SPENDWISE_SECRET_KEY"):
        create_app({"DATABASE": str(tmp_path / "x.sqlite")})


def test_create_app_reads_the_key_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.delenv("SPENDWISE_ENV", raising=False)
    monkeypatch.setenv("SPENDWISE_SECRET_KEY", GOOD_KEY)

    app = create_app({"DATABASE": str(tmp_path / "x.sqlite")})

    assert app.config["SECRET_KEY"] == GOOD_KEY


def test_create_app_uses_test_config_and_skips_the_environment(monkeypatch, tmp_path):
    monkeypatch.delenv("SPENDWISE_ENV", raising=False)
    monkeypatch.delenv("SPENDWISE_SECRET_KEY", raising=False)

    app = create_app({"TESTING": True, "SECRET_KEY": "test", "DATABASE": str(tmp_path / "t.sqlite")})

    assert app.config["TESTING"] is True
    assert app.config["SECRET_KEY"] == "test"


def test_create_app_creates_the_database_and_table(tmp_path):
    path = tmp_path / "nested" / "folder" / "app.sqlite"

    create_app({"SECRET_KEY": "test", "DATABASE": str(path)})

    assert path.exists()
    conn = db.connect(path)
    tables = [r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    conn.close()
    assert "transactions" in tables


def test_get_db_returns_one_connection_per_context_and_closes_it(tmp_path):
    app = create_app({"SECRET_KEY": "test", "DATABASE": str(tmp_path / "t.sqlite")})

    with app.app_context():
        first = db.get_db()
        assert db.get_db() is first
        first.execute("SELECT 1")

    with pytest.raises(Exception, match="closed database"):
        first.execute("SELECT 1")


def test_test_app_does_not_touch_the_real_instance_database(tmp_path):
    app = create_app({"SECRET_KEY": "test", "DATABASE": str(tmp_path / "t.sqlite")})

    assert str(tmp_path) in app.config["DATABASE"]
    assert "instance" not in app.config["DATABASE"]

from verialign.proxy.config import is_async_database, SQLITE_DEFAULT, get_settings
from verialign.storage.store_factory import create_trace_store
from verialign.storage.trace_store import TraceStore
from verialign.storage.async_trace_store import AsyncTraceStore


class TestIsAsyncDatabase:
    def test_sqlite_is_not_async(self):
        assert is_async_database("sqlite:///./test.db") is False

    def test_sqlite_default_is_not_async(self):
        assert is_async_database(SQLITE_DEFAULT) is False

    def test_postgres_is_async(self):
        assert is_async_database("postgresql+asyncpg://user:pass@host/db") is True

    def test_postgresql_is_async(self):
        assert is_async_database("postgresql://user:pass@host/db") is True

    def test_mysql_is_async(self):
        assert is_async_database("mysql+aiomysql://user:pass@host/db") is True

    def test_asyncpg_is_async(self):
        assert is_async_database("asyncpg://user:pass@host/db") is True

    def test_empty_string_is_not_async(self):
        assert is_async_database("") is False

    def test_case_insensitive(self):
        assert is_async_database("PostgreSQL+asyncpg://user:pass@host/db") is True


class TestCreateTraceStore:
    def test_sqlite_returns_sync_store(self):
        store = create_trace_store("sqlite:///./test.db")
        assert isinstance(store, TraceStore)
        assert not isinstance(store, AsyncTraceStore)

    def test_default_returns_sync_store(self):
        store = create_trace_store()
        assert isinstance(store, TraceStore)

    def test_postgres_returns_async_store(self):
        store = create_trace_store(
            "postgresql+asyncpg://user:pass@localhost:5432/verialign"
        )
        assert isinstance(store, AsyncTraceStore)

    def test_mysql_returns_async_store(self):
        store = create_trace_store(
            "mysql+aiomysql://user:pass@localhost:3306/verialign"
        )
        assert isinstance(store, AsyncTraceStore)

    def test_redact_passed_to_sync_store(self):
        store = create_trace_store(db_path="./test.db", redact=False)
        assert store.redact is False

    def test_redact_defaults_to_true(self):
        store = create_trace_store()
        assert store.redact is True

    def test_db_path_ignored_for_async(self):
        store = create_trace_store(
            "postgresql+asyncpg://u:p@h/db", db_path="./ignored.db"
        )
        assert isinstance(store, AsyncTraceStore)
        assert store.database_url == "postgresql+asyncpg://u:p@h/db"


class TestConfigSwitching:
    def test_default_is_sqlite_url(self):
        settings = get_settings()
        assert settings.database_url == SQLITE_DEFAULT

    def test_database_url_overrides_db_path(self, monkeypatch):
        monkeypatch.setenv("VERIALIGN_DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
        get_settings.cache_clear()
        settings = get_settings()
        assert is_async_database(settings.database_url) is True
        get_settings.cache_clear()

    def test_mixed_settings_async_url_wins(self, monkeypatch):
        monkeypatch.setenv("VERIALIGN_DB_PATH", "./custom.sqlite3")
        monkeypatch.setenv("VERIALIGN_DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
        get_settings.cache_clear()
        settings = get_settings()
        store = create_trace_store(settings.database_url, settings.db_path)
        assert isinstance(store, AsyncTraceStore)
        get_settings.cache_clear()

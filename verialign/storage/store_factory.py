"""Factory to create the appropriate trace store for the configured database."""

from verialign.proxy.config import is_async_database, SQLITE_DEFAULT
from verialign.storage.trace_store import TraceStore
from verialign.storage.async_trace_store import AsyncTraceStore


def create_trace_store(
    database_url: str = SQLITE_DEFAULT,
    db_path: str = "./verialign.sqlite3",
    redact: bool = True,
) -> AsyncTraceStore | TraceStore:
    if is_async_database(database_url):
        return AsyncTraceStore(database_url, redact=redact)
    return TraceStore(db_path, redact=redact)

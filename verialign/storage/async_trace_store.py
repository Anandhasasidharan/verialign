"""Async trace store for Postgres via SQLAlchemy async."""

import json
from datetime import datetime, timezone

from sqlalchemy import text

from verialign.verification.models import VerificationResult
from verialign.storage.trace_store import redact_sensitive_data
from verialign.storage.models import Base


class AsyncTraceStore:
    def __init__(self, database_url: str, redact: bool = True) -> None:
        self.database_url = database_url
        self.redact = redact
        self._engine = None
        self._session_factory = None

    def _get_engine(self):
        if self._engine is None:
            from sqlalchemy.ext.asyncio import create_async_engine

            self._engine = create_async_engine(
                self.database_url, pool_size=10, max_overflow=20
            )
        return self._engine

    def _get_session_factory(self):
        if self._session_factory is None:
            from sqlalchemy.ext.asyncio import async_sessionmaker

            self._session_factory = async_sessionmaker(
                self._get_engine(), expire_on_commit=False
            )
        return self._session_factory

    async def initialize(self) -> None:
        engine = self._get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def write_trace(
        self,
        request_payload: dict,
        response_payload: dict,
        verification: VerificationResult,
    ) -> None:
        request_to_store = (
            redact_sensitive_data(request_payload) if self.redact else request_payload
        )
        response_to_store = (
            redact_sensitive_data(response_payload) if self.redact else response_payload
        )

        session_factory = self._get_session_factory()
        async with session_factory() as session:
            from verialign.storage.models import Trace

            trace = Trace(
                created_at=datetime.now(timezone.utc),
                model=str(request_payload.get("model", "")),
                request_json=request_to_store,
                response_json=response_to_store,
                verification_json=verification.to_dict(),
            )
            session.add(trace)
            await session.commit()

    async def list_recent(self, limit: int = 25) -> list[dict]:
        bounded_limit = min(max(limit, 1), 100)
        session_factory = self._get_session_factory()
        async with session_factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT id, created_at, model, request_json, response_json, verification_json
                    FROM traces
                    ORDER BY id DESC
                    LIMIT :limit
                    """
                ),
                {"limit": bounded_limit},
            )
            rows = result.all()

        traces: list[dict] = []
        for row in rows:
            request_data = (
                json.loads(row.request_json)
                if isinstance(row.request_json, str)
                else row.request_json
            )
            response_data = (
                json.loads(row.response_json)
                if isinstance(row.response_json, str)
                else row.response_json
            )
            verification_data = (
                json.loads(row.verification_json)
                if isinstance(row.verification_json, str)
                else row.verification_json
            )
            traces.append(
                {
                    "id": row.id,
                    "created_at": row.created_at.isoformat()
                    if hasattr(row.created_at, "isoformat")
                    else str(row.created_at),
                    "model": row.model,
                    "request": request_data,
                    "response": response_data,
                    "verification": verification_data,
                    "summary": verification_data.get("summary", {}),
                }
            )
        return traces

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()

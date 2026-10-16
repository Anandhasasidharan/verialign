"""Alembic migrations shipped inside the package.

Installed users do not need a checkout or an ``alembic.ini`` — ``verialign migrate``
builds an Alembic config pointing at this directory and runs ``upgrade head``.
"""

from __future__ import annotations

from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent


def build_alembic_config(database_url: str | None = None):  # noqa: ANN201 - alembic type
    """Return an Alembic config bound to the packaged migrations."""
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    if database_url:
        config.set_main_option("sqlalchemy.url", database_url)
    return config


def run_migrations(database_url: str | None = None, revision: str = "head") -> None:
    """Run ``alembic upgrade <revision>`` against ``database_url``.

    Raises:
        RuntimeError: if the ``alembic`` package (``verialign[migrate]``) is missing.
    """
    try:
        from alembic import command
    except ImportError as exc:  # pragma: no cover - exercised via the CLI
        msg = "alembic is required for migrations; install with: pip install 'verialign[migrate]'"
        raise RuntimeError(msg) from exc

    command.upgrade(build_alembic_config(database_url), revision)


__all__ = ["MIGRATIONS_DIR", "build_alembic_config", "run_migrations"]

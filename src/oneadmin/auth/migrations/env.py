"""Alembic environment for OneAdmin's own tables. Driven by ``oneadmin.auth.migrate``.

The caller passes an open *sync* connection in ``config.attributes["connection"]`` (obtained
from the app's async engine via ``run_sync``), so the environment never builds its own engine
or reads a URL.
"""

from __future__ import annotations

from typing import Any

from alembic import context

from oneadmin.alembic import is_oneadmin_object
from oneadmin.auth.tables import VERSION_TABLE, metadata


def _only_oneadmin_tables(
    obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any
) -> bool:
    """Autogenerate (for OneAdmin developers) must only ever see OneAdmin's own tables."""
    return type_ != "table" or is_oneadmin_object(name, type_)


connection = context.config.attributes["connection"]
context.configure(
    connection=connection,
    target_metadata=metadata,
    version_table=VERSION_TABLE,
    include_object=_only_oneadmin_tables,
    compare_type=True,
)
with context.begin_transaction():
    context.run_migrations()

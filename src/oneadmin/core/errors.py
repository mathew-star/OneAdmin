"""Typed errors.

There are three families:
- ``ConfigurationError``: a developer mistake (bad ``ModelAdmin`` option), raised at
  registration or startup and never at request time.
- ``QueryError``: a bad client-supplied list parameter. The API layer maps it to HTTP 400.
- ``WriteError``: a refused create/update/delete/action (validation, scope, permission,
  concurrency, constraint). The API layer maps each ``code`` to a status.

Every error carries ``code``, ``message`` and ``param``. Messages are safe to show to the
client: they never echo raw SQL or internal details.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class OneAdminError(Exception):
    """Base class for all OneAdmin errors."""


class ConfigurationError(OneAdminError):
    """Invalid admin configuration. The message says exactly what to change."""


class QueryError(OneAdminError):
    """A client-supplied list parameter (sort, filter, search, cursor) is invalid."""

    code: str = "invalid_query"

    def __init__(self, message: str, *, param: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.param = param


class InvalidSort(QueryError):
    code = "invalid_sort"


class InvalidFilter(QueryError):
    code = "invalid_filter"


class InvalidSearch(QueryError):
    code = "invalid_search"


class InvalidCursor(QueryError):
    code = "invalid_cursor"


# ---- write path (ADR-0018) ----------------------------------------------------------------
class WriteError(OneAdminError):
    """A write was refused. ``code`` is stable and machine-readable; the API maps it to a status."""

    code: str = "write_failed"

    def __init__(self, message: str, *, param: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.param = param


class ValidationError(WriteError):
    """Field-level input errors. Raise it from ``ModelAdmin.clean`` for your own rules::

        raise ValidationError({"end_date": "must be after the start date"})

    A plain string is a non-field error.
    """

    code = "validation_failed"

    def __init__(self, errors: Mapping[str, str] | str) -> None:
        self.errors: dict[str, str] = {"": errors} if isinstance(errors, str) else dict(errors)
        first_field, first_message = next(iter(self.errors.items()), ("", "invalid input"))
        message = (
            first_message if len(self.errors) == 1 else f"{len(self.errors)} fields are invalid"
        )
        super().__init__(message, param=first_field or None)


class NotFound(WriteError):
    """The row doesn't exist, or is outside the caller's scope (indistinguishable on purpose)."""

    code = "not_found"


class PermissionDenied(WriteError):
    code = "forbidden"


class OutOfScope(PermissionDenied):
    """The write would leave the row outside the caller's own scope (e.g. another tenant)."""

    code = "out_of_scope"


class PreconditionRequired(WriteError):
    """``If-Match`` with the row's ``version`` is required for this change."""

    code = "precondition_required"


class Conflict(WriteError):
    """The row changed since the client read it. ``current`` is the row as it is now."""

    code = "conflict"

    def __init__(self, message: str, *, current: Any = None) -> None:
        super().__init__(message)
        self.current = current


class IntegrityConflict(WriteError):
    """A database constraint (unique, foreign key, check) rejected the change."""

    code = "integrity_error"


class UnknownAction(WriteError):
    code = "unknown_action"

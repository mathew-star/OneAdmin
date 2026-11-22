"""Typing helpers that span SQLAlchemy 2.0 and 2.1.

SQLAlchemy 2.1 made ``Select`` variadic (PEP 646): ``Select[int, str]``. ``AnySelect`` now
means a *one-column* select, so it would reject users' multi-column statements.
``AnySelect`` is "a select of any shape" on 2.1. On 2.0, ``Unpack`` inside ``Select[...]``
degrades to ``Any`` under mypy, which is acceptable: we type-check against 2.1 in CI and run
the tests against both (see OPEN_QUESTIONS.md).
"""

from __future__ import annotations

from typing import Any, TypeAlias

from sqlalchemy import Select

AnySelect: TypeAlias = "Select[*tuple[Any, ...]]"

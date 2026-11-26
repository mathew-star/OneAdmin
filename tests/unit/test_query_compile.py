"""Compile-level tests for sort parsing, cursors, keyset predicates, filters and search."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import DBAPIError
from sqlalchemy.sql.elements import ColumnElement

from oneadmin.core.errors import (
    ConfigurationError,
    InvalidCursor,
    InvalidFilter,
    InvalidSearch,
    InvalidSort,
)
from oneadmin.core.meta import introspect
from oneadmin.core.query.counting import _is_timeout
from oneadmin.core.query.cursor import Cursor, CursorCodec
from oneadmin.core.query.filters import parse_filters, to_sql
from oneadmin.core.query.keyset import keyset_segments, pagination_mode
from oneadmin.core.query.search import compile_search_fields, search_clause
from oneadmin.core.query.sorting import parse_sort, validate_default_sort
from tests.models import Item, Pair

ITEM = introspect(Item)
ALL = ITEM.fields.keys()
CODEC = CursorCodec("x" * 32)


def sql(expr: ColumnElement[Any], dialect: Any = None) -> str:
    return str(
        expr.compile(
            dialect=dialect or postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


# ----------------------------------------------------------------------------- sorting


def test_sort_completed_with_pk_inheriting_last_direction() -> None:
    spec = parse_sort(ITEM, "-grp", allowed=ALL)
    assert [k.token() for k in spec.keys] == ["-grp", "-id"]
    assert spec.uniform


def test_sort_default_and_explicit_pk() -> None:
    assert [k.token() for k in parse_sort(ITEM, None, allowed=ALL).keys] == ["id"]
    assert [k.token() for k in parse_sort(ITEM, "", allowed=ALL, default=["-id"]).keys] == ["-id"]
    assert [k.token() for k in parse_sort(ITEM, "-id,grp", allowed=ALL).keys] == ["-id", "grp"]


def test_composite_pk_completion() -> None:
    meta = introspect(Pair)
    spec = parse_sort(meta, "-v", allowed=meta.fields.keys())
    assert [k.token() for k in spec.keys] == ["-v", "-a", "-b"]


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        ("nope", "cannot sort by 'nope'"),
        ("grp,grp", "duplicate"),
        ("a,b,c,d,e", "at most"),
        ("name; DROP TABLE x", "cannot sort by"),
        ("--grp", "cannot sort by '-grp'"),
    ],
)
def test_sort_rejects(spec: str, message: str) -> None:
    with pytest.raises(InvalidSort, match=message):
        parse_sort(ITEM, spec, allowed=ALL)


def test_sort_allow_list_is_enforced() -> None:
    with pytest.raises(InvalidSort):
        parse_sort(ITEM, "amount", allowed={"grp"})


def test_default_ordering_validated_at_startup() -> None:
    with pytest.raises(ConfigurationError, match=r"Item.ordering: cannot sort by 'missing'"):
        validate_default_sort(ITEM, ["missing"])


def test_signature_changes_with_sort() -> None:
    a = parse_sort(ITEM, "grp", allowed=ALL).signature
    b = parse_sort(ITEM, "-grp", allowed=ALL).signature
    assert a != b


# ----------------------------------------------------------------------------- cursors


def test_cursor_roundtrip_and_tamper() -> None:
    spec = parse_sort(ITEM, "-grp", allowed=ALL)
    token = CODEC.encode(spec, Cursor("after", (5, 99)))
    assert CODEC.decode(spec, token) == Cursor("after", (5, 99))
    body, _, sig = token.partition(".")
    with pytest.raises(InvalidCursor, match="signature"):
        CODEC.decode(spec, body + "." + sig[::-1])
    with pytest.raises(InvalidCursor, match="signature"):
        CursorCodec("y" * 32).decode(spec, token)


def test_cursor_bound_to_sort() -> None:
    a = parse_sort(ITEM, "-grp", allowed=ALL)
    b = parse_sort(ITEM, "grp", allowed=ALL)
    with pytest.raises(InvalidCursor, match="different sort"):
        CODEC.decode(b, CODEC.encode(a, Cursor("after", (5, 99))))


@pytest.mark.parametrize("token", ["", "abc", "a.b", "x" * 5000, "!!!.???"])
def test_cursor_garbage(token: str) -> None:
    spec = parse_sort(ITEM, None, allowed=ALL)
    with pytest.raises(InvalidCursor):
        CODEC.decode(spec, token)


def test_short_secret_rejected() -> None:
    with pytest.raises(ValueError, match="16 bytes"):
        CursorCodec("short")


# ----------------------------------------------------------------------------- keyset


def test_uniform_non_null_uses_row_value_on_pg() -> None:
    spec = parse_sort(ITEM, "grp", allowed=ALL)
    [seg] = keyset_segments(spec, (3, 10), dialect="postgresql")
    assert sql(seg) == "(qe_item.grp, qe_item.id) > (3, 10)"


def test_mixed_direction_uses_bounded_form_never_bare_or() -> None:
    spec = parse_sort(ITEM, "-grp,id", allowed=ALL)
    [seg] = keyset_segments(spec, (3, 10), dialect="postgresql")
    assert sql(seg) == "qe_item.grp <= 3 AND (qe_item.grp < 3 OR qe_item.id > 10)"


def test_unknown_dialect_uses_bounded_form() -> None:
    spec = parse_sort(ITEM, "grp", allowed=ALL)
    [seg] = keyset_segments(spec, (3, 10), dialect="mysql")
    assert sql(seg) == "qe_item.grp >= 3 AND (qe_item.grp > 3 OR qe_item.id > 10)"


def test_three_keys_nest() -> None:
    spec = parse_sort(ITEM, "grp,-amount,id", allowed=ALL)
    [seg] = keyset_segments(spec, (1, 2, 3), dialect="postgresql")
    assert sql(seg) == (
        "qe_item.grp >= 1 AND (qe_item.grp > 1 OR qe_item.amount <= 2 AND "
        "(qe_item.amount < 2 OR qe_item.id > 3))"
    )


def test_nullable_leading_key_segments() -> None:
    asc = parse_sort(ITEM, "seen_at", allowed=ALL)  # NULLS LAST
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    segs = keyset_segments(asc, (ts, 5), dialect="postgresql")
    assert [sql(s) for s in segs] == [
        "(qe_item.seen_at, qe_item.id) > ('2026-01-01 00:00:00+00:00', 5)",
        "qe_item.seen_at IS NULL",
    ]
    segs = keyset_segments(asc, (None, 5), dialect="postgresql")
    assert [sql(s) for s in segs] == ["qe_item.seen_at IS NULL AND qe_item.id > 5"]

    desc = parse_sort(ITEM, "-seen_at", allowed=ALL)  # NULLS FIRST
    segs = keyset_segments(desc, (None, 5), dialect="postgresql")
    assert [sql(s) for s in segs] == [
        "qe_item.seen_at IS NULL AND qe_item.id < 5",
        "qe_item.seen_at IS NOT NULL",
    ]
    segs = keyset_segments(desc, (ts, 5), dialect="postgresql")
    assert len(segs) == 1


def test_nullable_non_leading_key_falls_back_to_offset() -> None:
    spec = parse_sort(ITEM, "grp,seen_at", allowed=ALL)
    assert pagination_mode(spec) == "offset"
    with pytest.raises(ValueError, match="offset"):
        keyset_segments(spec, (1, None, 2), dialect="postgresql")


def test_order_by_emits_nulls_only_for_nullable() -> None:
    spec = parse_sort(ITEM, "-seen_at", allowed=ALL)
    stmt = select(Item.id).order_by(*spec.order_by())
    compiled = str(stmt.compile(dialect=postgresql.dialect()))
    assert "ORDER BY qe_item.seen_at DESC NULLS FIRST, qe_item.id DESC" in compiled
    assert "NULLS" in str(stmt.compile(dialect=sqlite.dialect()))


# ----------------------------------------------------------------------------- filters


def test_filters_compile() -> None:
    clauses = parse_filters(
        ITEM,
        [
            ("f.grp__gte", "2"),
            ("f.color__in", "red,blue"),
            ("f.seen_at__isnull", "true"),
            ("f.name__icontains", "50%_off"),
            ("f.note__contains", "x"),
            ("page", "ignored"),
        ],
        allowed=ALL,
    )
    out = [sql(to_sql(c)) for c in clauses]
    assert out[0] == "qe_item.grp >= 2"
    assert out[1] == "qe_item.color IN ('RED', 'BLUE')"
    assert out[2] == "qe_item.seen_at IS NULL"
    assert out[3] == "qe_item.name ILIKE '%%' || '50/%%/_off' || '%%' ESCAPE '/'"


def test_ne_on_nullable_keeps_nulls() -> None:
    [c] = parse_filters(ITEM, [("f.slug__ne", "x")], allowed=ALL)
    assert sql(to_sql(c)) == "qe_item.slug != 'x' OR qe_item.slug IS NULL"


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("f.secret", "1", "cannot filter by 'secret'"),
        ("f.grp__regex", ".*", "operator 'regex'"),
        ("f.grp__gte", "1 OR 1=1", "integer"),
        ("f.grp__isnull", "true", "not nullable"),
        ("f.grp__in", ",".join(["1"] * 101), "1 to 100"),
        ("f.grp__in", "", "1 to 100"),
        ("f.name__icontains", "", "empty"),
        ("f.amount__lt", "1e999999", "out of range"),
        ("f.amount__lt", "123456789", "NUMERIC\\(10,2\\)"),
        ("f.seen_at__gt", "yesterday", "seen_at"),
    ],
)
def test_filter_rejects(key: str, value: str, message: str) -> None:
    with pytest.raises(InvalidFilter, match=message):
        parse_filters(ITEM, [(key, value)], allowed=ALL)


def test_filter_allow_list() -> None:
    with pytest.raises(InvalidFilter):
        parse_filters(ITEM, [("f.amount", "1")], allowed={"grp"})


def test_too_many_filters() -> None:
    with pytest.raises(InvalidFilter, match="at most 20"):
        parse_filters(ITEM, [("f.grp", "1")] * 21, allowed=ALL)


# ----------------------------------------------------------------------------- search


def test_search_terms_and_modes() -> None:
    fields = compile_search_fields(ITEM, ["name", "^note", "=id"])
    clause = search_clause(fields, "ab 42")
    assert clause is not None
    out = sql(clause)
    assert "qe_item.name ILIKE '%%' || 'ab' || '%%'" in out
    assert "qe_item.note ILIKE 'ab' || '%%'" in out
    assert "qe_item.id = 42" in out
    assert "qe_item.id = 'ab'" not in out, "non-integer word skips the exact id field"


def test_search_limits_and_config() -> None:
    fields = compile_search_fields(ITEM, ["name"])
    assert search_clause(fields, "   ") is None
    with pytest.raises(InvalidSearch):
        search_clause(fields, "a " * 9)
    with pytest.raises(InvalidSearch):
        search_clause(fields, "a" * 201)
    with pytest.raises(ConfigurationError, match="Use '=grp'"):
        compile_search_fields(ITEM, ["grp"])
def test_only_statement_timeouts_are_count_timeouts() -> None:
    canceled = DBAPIError("SELECT 1", {}, Exception("canceling statement due to user request"))
    timed_out = DBAPIError("SELECT 1", {}, Exception("canceling statement due to statement timeout"))
    assert not _is_timeout(canceled)
    assert _is_timeout(timed_out)

"""Opaque, signed pagination cursors.

Token format: ``base64url(json) "." base64url(hmac_sha256(key, json))``.

Cursors are signed so clients cannot craft arbitrary predicate values, and so a cursor
cannot be replayed under a different sort. The values are typed through ``FieldMeta`` on
decode and always bound as parameters, never interpolated. Signing is defense in depth, not
the SQL-injection barrier.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any, Literal

from oneadmin.core.coerce import from_json, to_json
from oneadmin.core.errors import InvalidCursor
from oneadmin.core.query.sorting import SortSpec

MAX_TOKEN_LENGTH = 2_048
Direction = Literal["after", "before"]


@dataclass(frozen=True, slots=True)
class Cursor:
    direction: Direction
    values: tuple[Any, ...] | None = None
    """Sort-key values of the boundary row (keyset mode)."""
    offset: int | None = None
    """Row offset (offset mode)."""


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


class CursorCodec:
    """Encodes and decodes cursors for one ``AdminSite`` (its own key, so no global state)."""

    def __init__(self, secret: str | bytes) -> None:
        key = secret.encode() if isinstance(secret, str) else secret
        if len(key) < 16:
            raise ValueError("cursor signing secret must be at least 16 bytes")
        # Domain-separate from other uses of the site secret.
        self._key = hmac.new(key, b"oneadmin.cursor.v1", hashlib.sha256).digest()

    def _sign(self, body: bytes) -> str:
        return _b64(hmac.new(self._key, body, hashlib.sha256).digest())

    def encode(self, sort: SortSpec, cursor: Cursor) -> str:
        payload: dict[str, Any] = {"d": cursor.direction, "s": sort.signature}
        if cursor.values is not None:
            payload["v"] = [
                to_json(v, k.field) for k, v in zip(sort.keys, cursor.values, strict=True)
            ]
        if cursor.offset is not None:
            payload["o"] = cursor.offset
        body = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()
        return f"{_b64(body)}.{self._sign(body)}"

    def decode(self, sort: SortSpec, token: str) -> Cursor:
        if len(token) > MAX_TOKEN_LENGTH:
            raise InvalidCursor("cursor is too long", param="cursor")
        body_b64, sep, sig = token.partition(".")
        if not sep:
            raise InvalidCursor("malformed cursor", param="cursor")
        try:
            body = _unb64(body_b64)
        except (binascii.Error, ValueError):
            raise InvalidCursor("malformed cursor", param="cursor") from None
        if not hmac.compare_digest(self._sign(body), sig):
            raise InvalidCursor("cursor signature mismatch", param="cursor")
        try:
            payload = json.loads(body)
        except ValueError:
            raise InvalidCursor("malformed cursor", param="cursor") from None
        if not isinstance(payload, dict) or payload.get("d") not in ("after", "before"):
            raise InvalidCursor("malformed cursor", param="cursor")
        if payload.get("s") != sort.signature:
            raise InvalidCursor(
                "cursor was created for a different sort order; restart from the first page",
                param="cursor",
            )
        values: tuple[Any, ...] | None = None
        if "v" in payload:
            raw = payload["v"]
            if not isinstance(raw, list) or len(raw) != len(sort.keys):
                raise InvalidCursor("malformed cursor", param="cursor")
            try:
                values = tuple(from_json(k.field, v) for k, v in zip(sort.keys, raw, strict=True))
            except (ValueError, TypeError, KeyError):
                raise InvalidCursor("malformed cursor", param="cursor") from None
        offset = payload.get("o")
        if offset is not None and (not isinstance(offset, int) or offset < 0):
            raise InvalidCursor("malformed cursor", param="cursor")
        if (values is None) == (offset is None):
            raise InvalidCursor("malformed cursor", param="cursor")
        return Cursor(direction=payload["d"], values=values, offset=offset)

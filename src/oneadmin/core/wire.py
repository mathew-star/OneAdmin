"""Conversion of database values to JSON-safe wire values, and primary-key encoding.

Wire rules (part of the API contract, ADR-0008):
- ``Decimal`` → string (no float rounding of money).
- Integers outside ±(2^53 - 1) → string (JavaScript numbers lose precision beyond that).
- datetimes/dates/times → ISO 8601; ``timedelta`` → total seconds (number).
- ``UUID`` → string; ``Enum`` → its value if JSON-safe, else its name.
- ``bytes`` → ``None`` (binary is never sent in v1).
- JSON columns pass through.
"""

from __future__ import annotations

import base64
import binascii
import enum
import json
from typing import Any

from oneadmin.core.coerce import from_json, parse_text, to_json
from oneadmin.core.fields import JS_SAFE_INT, to_wire
from oneadmin.core.meta import ModelMeta

__all__ = ["JS_SAFE_INT", "decode_pk", "encode_pk", "to_wire"]


def encode_pk(meta: ModelMeta, values: tuple[Any, ...]) -> str:
    if len(meta.pk) == 1:
        v = values[0]
        return v.name if isinstance(v, enum.Enum) else str(meta.pk[0].field_type.to_wire(v))
    body = json.dumps(
        [to_json(v, f) for f, v in zip(meta.pk, values, strict=True)], separators=(",", ":")
    ).encode()
    return base64.urlsafe_b64encode(body).rstrip(b"=").decode()


def decode_pk(meta: ModelMeta, raw: str) -> tuple[Any, ...]:
    """Parse a wire PK. Raises ``ValueError`` if it is malformed (callers answer 404)."""
    if len(raw) > 1_000:
        raise ValueError("primary key too long")
    if len(meta.pk) == 1:
        return (parse_text(meta.pk[0], raw),)
    try:
        data = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    except (binascii.Error, ValueError) as exc:
        raise ValueError("malformed primary key") from exc
    if not isinstance(data, list) or len(data) != len(meta.pk):
        raise ValueError("malformed primary key")
    return tuple(from_json(f, v) for f, v in zip(meta.pk, data, strict=True))

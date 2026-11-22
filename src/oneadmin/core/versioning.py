"""Row versions for optimistic concurrency (ADR-0018).

A version is ``HMAC(site key, slug + canonical JSON of the row's visible field values)``,
truncated to 128 bits. It is computed the same way from a read (wire values) and from a
loaded ORM instance, so ``PATCH``/``DELETE`` can check ``If-Match`` against the row as the
client saw it. Any change to a visible field changes the version.

It is keyed rather than a plain hash so tokens are opaque: nothing about the row can be
learnt or tested offline from a version.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from typing import Any

from oneadmin.core.model_admin import CompiledAdmin
from oneadmin.core.wire import to_wire


class RowVersioner:
    def __init__(self, secret_key: str) -> None:
        self._key = hmac.new(secret_key.encode(), b"oneadmin.row-version.v1", "sha256").digest()

    def of_values(self, c: CompiledAdmin, values: Mapping[str, Any]) -> str:
        """Version of a row given its wire values (as returned by the read API)."""
        body = json.dumps(
            [c.slug, [[f.name, values.get(f.name)] for f in c.detail_fields]],
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hmac.new(self._key, body.encode(), hashlib.sha256).hexdigest()[:32]

    def of_instance(self, c: CompiledAdmin, obj: Any) -> str:
        """Version of a loaded ORM instance (all visible attributes must be loaded)."""
        return self.of_values(c, {f.name: to_wire(getattr(obj, f.name)) for f in c.detail_fields})

    @staticmethod
    def matches(expected: str, provided: str) -> bool:
        return hmac.compare_digest(expected.encode(), provided.encode())

"""Password hashing and policy.

Hashing uses argon2id with ``argon2-cffi``'s default parameters (t=3, m=64 MiB, p=4: about
65 ms per hash, measured on 2026-11-06). That is too slow for the event loop, and each
in-flight hash allocates 64 MiB, so:

* hashing runs in a worker thread (``anyio.to_thread``), and
* concurrency is capped per ``PasswordHasher`` instance (threat model D3). Excess calls
  queue instead of exhausting memory.
"""

from __future__ import annotations

import anyio
import anyio.to_thread
from argon2 import PasswordHasher as _Argon2
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from oneadmin.core.errors import OneAdminError

MIN_LENGTH = 12
MAX_LENGTH = 1024


class WeakPassword(OneAdminError):
    """The password does not satisfy the policy. The message is safe to show the user."""


def validate_password(password: str, *, email: str | None = None) -> None:
    """Raise ``WeakPassword`` if ``password`` is unacceptable.

    The policy follows NIST SP 800-63B: a minimum length, no composition rules. It also
    rejects passwords equal to (or contained in) the email address.
    """
    if len(password) < MIN_LENGTH:
        raise WeakPassword(f"Password must be at least {MIN_LENGTH} characters long.")
    if len(password) > MAX_LENGTH:
        raise WeakPassword(f"Password must be at most {MAX_LENGTH} characters long.")
    if not password.strip():
        raise WeakPassword("Password cannot be only whitespace.")
    if email and password.casefold() in email.casefold():
        raise WeakPassword("Password must not be part of the email address.")


class PasswordHasher:
    """Async, concurrency-limited argon2id hashing. One instance per ``AdminSite``."""

    def __init__(self, *, max_concurrency: int = 4) -> None:
        self._argon2 = _Argon2()
        self._limiter = anyio.CapacityLimiter(max_concurrency)
        # Verifying against this when the user doesn't exist costs the same time as a real
        # verification, so response timing does not reveal which emails have accounts.
        self._dummy_hash = self._argon2.hash("oneadmin-dummy-password-for-timing")

    async def hash(self, password: str) -> str:
        return await anyio.to_thread.run_sync(self._argon2.hash, password, limiter=self._limiter)

    async def verify(self, password_hash: str | None, password: str) -> bool:
        """Constant-ish-time check. ``password_hash=None`` means "no such user"."""
        target = password_hash if password_hash is not None else self._dummy_hash
        ok = await anyio.to_thread.run_sync(self._verify, target, password, limiter=self._limiter)
        return ok and password_hash is not None

    def needs_rehash(self, password_hash: str) -> bool:
        """True when the stored hash uses older parameters; rehash it after a good login."""
        return self._argon2.check_needs_rehash(password_hash)

    def _verify(self, password_hash: str, password: str) -> bool:
        try:
            return self._argon2.verify(password_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

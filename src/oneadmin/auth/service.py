"""Built-in admin accounts: users, login, sessions and rate limiting (ADR-0005, ADR-0016).

This module is framework-neutral (no FastAPI/Starlette). The HTTP layer
(``oneadmin.api.auth_routes``) handles cookies and headers; the CLI calls the same methods.

Each public method is one unit of work: it opens a session from the site's
``session_factory``, does its work and commits. Auth state therefore never rides along in
(or is rolled back with) a request's data transaction.

Security properties, each with a test in ``tests/security/``:

* Session tokens are 256-bit random values. The database stores only their SHA-256, so a
  leaked database yields no usable sessions.
* Sessions expire after ``idle_timeout`` of inactivity and, regardless of activity, after
  ``absolute_timeout``.
* Login always creates a new session (no fixation). Changing a password revokes every
  session of that user.
* Unknown email, wrong password and inactive account are indistinguishable, including in
  timing (the dummy hash in ``PasswordHasher``).
* Failed logins are rate limited per email and per client IP, in the database, so the limit
  holds across workers.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import re
import secrets
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar

from sqlalchemy import case, delete, func, insert, select, update
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from oneadmin.auth import tables as t
from oneadmin.auth.backend import AdminIdentity
from oneadmin.auth.passwords import PasswordHasher, validate_password
from oneadmin.auth.permissions import validate_codename
from oneadmin.core.errors import OneAdminError

T = TypeVar("T")
Clock = Callable[[], datetime]

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# --------------------------------------------------------------------------- errors
class AuthError(OneAdminError):
    """Base class for authentication errors."""


class AdminNotMigrated(AuthError):
    """OneAdmin's tables don't exist yet. Fix: run ``oneadmin migrate``."""

    def __init__(self) -> None:
        super().__init__("OneAdmin's tables are missing. Run `oneadmin migrate` first.")


class InvalidCredentials(AuthError):
    """Wrong email/password, or an inactive account (deliberately indistinguishable)."""


class RateLimited(AuthError):
    def __init__(self, retry_after: int) -> None:
        super().__init__(f"Too many failed logins. Try again in {retry_after} seconds.")
        self.retry_after = retry_after


class UserExists(AuthError):
    """An admin user with this email already exists."""


class UserNotFound(AuthError):
    """No admin user has this email."""


class InvalidEmail(AuthError):
    """The email address is malformed."""


# --------------------------------------------------------------------------- settings
@dataclass(frozen=True, slots=True)
class AuthSettings:
    idle_timeout: timedelta = timedelta(hours=2)
    absolute_timeout: timedelta = timedelta(hours=12)
    failure_window: timedelta = timedelta(minutes=15)
    max_failures_per_email: int = 5
    max_failures_per_ip: int = 20
    touch_interval: timedelta = timedelta(seconds=60)
    """``last_seen_at`` is written at most this often, not on every request."""
    max_hash_concurrency: int = 4


@dataclass(frozen=True, slots=True)
class LoginResult:
    token: str
    """The raw session token, for the cookie. It is not stored anywhere server-side."""
    identity: AdminIdentity
    csrf_token: str


def normalize_email(email: str) -> str:
    """Trim and lower-case. Raises ``InvalidEmail`` if it doesn't look like an address."""
    value = email.strip().lower()
    if len(value) > 254 or not _EMAIL.match(value):
        raise InvalidEmail(f"{email!r} is not a valid email address.")
    return value


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


class AuthService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        secret_key: str,
        settings: AuthSettings | None = None,
        *,
        clock: Clock = _now,
    ) -> None:
        self.settings = settings or AuthSettings()
        self._session_factory = session_factory
        self._csrf_key = hmac.new(secret_key.encode(), b"oneadmin.csrf.v1", "sha256").digest()
        self._hasher = PasswordHasher(max_concurrency=self.settings.max_hash_concurrency)
        self._clock = clock

    # ---- users ---------------------------------------------------------------------------
    async def create_user(
        self, email: str, password: str, *, is_superuser: bool = False
    ) -> AdminIdentity:
        """Create an admin user. Raises ``InvalidEmail``, ``WeakPassword`` or ``UserExists``."""
        email = normalize_email(email)
        validate_password(password, email=email)
        password_hash = await self._hasher.hash(password)
        now = self._clock()

        async def work(s: AsyncSession) -> AdminIdentity:
            try:
                user_id = (
                    await s.execute(
                        insert(t.user)
                        .values(
                            email=email,
                            password_hash=password_hash,
                            is_superuser=is_superuser,
                            is_active=True,
                            created_at=now,
                            password_changed_at=now,
                        )
                        .returning(t.user.c.id)
                    )
                ).scalar_one()
            except IntegrityError:
                raise UserExists(f"An admin user with email {email!r} already exists.") from None
            return AdminIdentity(id=str(user_id), email=email, is_superuser=is_superuser)

        return await self._transaction(work)

    async def set_password(self, email: str, password: str) -> None:
        """Change a password and revoke all of that user's sessions."""
        email = normalize_email(email)
        validate_password(password, email=email)
        password_hash = await self._hasher.hash(password)

        async def work(s: AsyncSession) -> None:
            user_id = (
                await s.execute(select(t.user.c.id).where(t.user.c.email == email))
            ).scalar_one_or_none()
            if user_id is None:
                raise UserNotFound(f"No admin user with email {email!r}.")
            await s.execute(
                update(t.user)
                .where(t.user.c.id == user_id)
                .values(password_hash=password_hash, password_changed_at=self._clock())
            )
            await s.execute(delete(t.session).where(t.session.c.user_id == user_id))

        await self._transaction(work)

    # ---- permissions (ADR-0019) ----------------------------------------------------------
    async def grant(self, email: str, codenames: Iterable[str]) -> list[str]:
        """Grant permission codenames to a user. Returns the ones that were newly added."""
        wanted = sorted({validate_codename(c) for c in codenames})

        async def work(s: AsyncSession) -> list[str]:
            user_id = await self._user_id(s, email)
            existing = set(
                (
                    await s.execute(select(t.grant.c.codename).where(t.grant.c.user_id == user_id))
                ).scalars()
            )
            added = [c for c in wanted if c not in existing]
            if added:
                await s.execute(
                    insert(t.grant), [{"user_id": user_id, "codename": c} for c in added]
                )
            return added

        return await self._transaction(work)

    async def revoke(self, email: str, codenames: Iterable[str]) -> int:
        """Revoke permission codenames. Returns how many grants were removed."""
        targets = {validate_codename(c) for c in codenames}

        async def work(s: AsyncSession) -> int:
            user_id = await self._user_id(s, email)
            result = await s.execute(
                delete(t.grant).where(t.grant.c.user_id == user_id, t.grant.c.codename.in_(targets))
            )
            return int(getattr(result, "rowcount", 0) or 0)

        return await self._transaction(work)

    async def permissions_of(self, email: str) -> tuple[bool, list[str]]:
        """``(is_superuser, granted codenames)`` of a user."""

        async def work(s: AsyncSession) -> tuple[bool, list[str]]:
            user_id = await self._user_id(s, email)
            is_superuser = (
                await s.execute(select(t.user.c.is_superuser).where(t.user.c.id == user_id))
            ).scalar_one()
            codes = await s.execute(
                select(t.grant.c.codename)
                .where(t.grant.c.user_id == user_id)
                .order_by(t.grant.c.codename)
            )
            return bool(is_superuser), list(codes.scalars())

        return await self._transaction(work)

    async def _user_id(self, s: AsyncSession, email: str) -> int:
        email = normalize_email(email)
        user_id = (
            await s.execute(select(t.user.c.id).where(t.user.c.email == email))
        ).scalar_one_or_none()
        if user_id is None:
            raise UserNotFound(f"No admin user with email {email!r}.")
        return int(user_id)

    async def count_users(self) -> int:
        """All admin users, active or not (first-run setup is offered only at zero)."""

        async def work(s: AsyncSession) -> int:
            return int((await s.execute(select(func.count()).select_from(t.user))).scalar_one())

        return await self._transaction(work)

    async def count_superusers(self) -> int:
        async def work(s: AsyncSession) -> int:
            stmt = select(func.count()).where(t.user.c.is_superuser, t.user.c.is_active)
            return int((await s.execute(stmt.select_from(t.user))).scalar_one())

        return await self._transaction(work)

    # ---- login / logout ------------------------------------------------------------------
    async def login(
        self, email: str, password: str, *, ip: str | None = None, user_agent: str | None = None
    ) -> LoginResult:
        """Verify credentials and open a new session.

        Raises ``RateLimited`` (checked before any password work) or ``InvalidCredentials``.
        """
        try:
            email = normalize_email(email)
        except InvalidEmail:
            if ip:
                await self._transaction(lambda s: self._check_rate_limit(s, None, ip))
            await self._hasher.verify(None, password)  # same cost as a real attempt
            if ip:
                await self._transaction(
                    lambda s: self._record_attempts(s, [f"ip:{ip}"], success=False)
                )
            raise InvalidCredentials("Invalid email or password.") from None
        keys = [f"email:{email}"] + ([f"ip:{ip}"] if ip else [])
        await self._transaction(lambda s: self._check_rate_limit(s, email, ip))

        async def verify_and_open(s: AsyncSession) -> LoginResult | None:
            # Keep this row lock until the session is inserted. A concurrent password
            # change then either happens first (the old password fails) or waits and
            # revokes the newly created session in its own transaction.
            row = await _first(
                s,
                select(
                    t.user.c.id, t.user.c.password_hash, t.user.c.is_superuser, t.user.c.is_active
                )
                .where(t.user.c.email == email)
                .with_for_update(),
            )
            valid = await self._hasher.verify(row.password_hash if row else None, password)
            if row is None or not valid or not row.is_active:
                await self._record_attempts(s, keys, success=False)
                return None
            token = secrets.token_urlsafe(32)
            now = self._clock()
            new_hash = (
                await self._hasher.hash(password)
                if self._hasher.needs_rehash(row.password_hash)
                else None
            )
            await s.execute(
                insert(t.session).values(
                    token_hash=hash_token(token),
                    user_id=row.id,
                    created_at=now,
                    last_seen_at=now,
                    expires_at=now + self.settings.absolute_timeout,
                    ip=ip,
                    user_agent=(user_agent or "")[:255] or None,
                )
            )
            values: dict[str, Any] = {"last_login_at": now}
            if new_hash is not None:
                values["password_hash"] = new_hash
            await s.execute(update(t.user).where(t.user.c.id == row.id).values(**values))
            await self._record_attempts(s, keys, success=True)
            # Housekeeping: drop this user's expired sessions on each login.
            await s.execute(
                delete(t.session).where(t.session.c.user_id == row.id, t.session.c.expires_at < now)
            )
            identity = AdminIdentity(id=str(row.id), email=email, is_superuser=row.is_superuser)
            return LoginResult(token, identity, self.csrf_token(token))

        result = await self._transaction(verify_and_open)
        if result is None:
            raise InvalidCredentials("Invalid email or password.")
        return result

    async def logout(self, token: str) -> None:
        await self._transaction(
            lambda s: s.execute(
                delete(t.session).where(t.session.c.token_hash == hash_token(token))
            )
        )

    # ---- sessions ------------------------------------------------------------------------
    async def resolve(self, token: str | None) -> AdminIdentity | None:
        """The identity behind a cookie token, or ``None`` if missing/expired/revoked."""
        if not token or len(token) > 128:
            return None
        token_hash = hash_token(token)
        now = self._clock()
        settings = self.settings

        async def work(s: AsyncSession) -> AdminIdentity | None:
            row = await _first(
                s,
                select(
                    t.session.c.last_seen_at,
                    t.session.c.expires_at,
                    t.user.c.id,
                    t.user.c.email,
                    t.user.c.is_superuser,
                    t.user.c.is_active,
                )
                .join(t.user, t.user.c.id == t.session.c.user_id)
                .where(t.session.c.token_hash == token_hash),
            )
            if row is None:
                return None
            expired = row.expires_at <= now or row.last_seen_at + settings.idle_timeout <= now
            if expired or not row.is_active:
                await s.execute(delete(t.session).where(t.session.c.token_hash == token_hash))
                return None
            if now - row.last_seen_at >= settings.touch_interval:
                await s.execute(
                    update(t.session)
                    .where(t.session.c.token_hash == token_hash)
                    .values(last_seen_at=now)
                )
            permissions: frozenset[str] = frozenset()
            if not row.is_superuser:  # superusers hold everything; skip the query
                codes = await s.execute(
                    select(t.grant.c.codename).where(t.grant.c.user_id == row.id)
                )
                permissions = frozenset(codes.scalars())
            return AdminIdentity(
                id=str(row.id),
                email=row.email,
                is_superuser=row.is_superuser,
                permissions=permissions,
            )

        return await self._transaction(work)

    # ---- CSRF ----------------------------------------------------------------------------
    def csrf_token(self, session_token: str) -> str:
        """Per-session CSRF token, derived (not stored): HMAC(site key, session hash)."""
        return hmac.new(self._csrf_key, hash_token(session_token).encode(), "sha256").hexdigest()

    def check_csrf(self, session_token: str, provided: str | None) -> bool:
        return provided is not None and hmac.compare_digest(
            self.csrf_token(session_token), provided
        )

    # ---- internals -----------------------------------------------------------------------
    async def _check_rate_limit(self, s: AsyncSession, email: str | None, ip: str | None) -> None:
        """Raise ``RateLimited`` if this email or IP has too many recent failures.

        A successful login resets the *email* counter, so a legitimate user isn't locked out
        by their own earlier typos. The *IP* counter never resets on success; otherwise an
        attacker could log into their own account between guesses to reset it.
        The check-then-act is not atomic: concurrent attempts can overshoot a limit by the
        number of in-flight requests, which is acceptable for a throttle.
        """
        settings = self.settings
        since = self._clock() - settings.failure_window
        attempt = t.login_attempt.c
        checks = [(f"email:{email}", settings.max_failures_per_email, True)] if email else []
        if ip:
            checks.append((f"ip:{ip}", settings.max_failures_per_ip, False))
        for key, limit, reset_on_success in checks:
            window_start: Any = since
            if reset_on_success:
                last_success = (
                    select(func.max(attempt.at))
                    .where(attempt.key == key, attempt.success)
                    .scalar_subquery()
                )
                # max(since, last_success) without GREATEST(), which SQLite lacks
                window_start = case((last_success > since, last_success), else_=since)
            count, oldest = (
                await s.execute(
                    select(func.count(), func.min(attempt.at)).where(
                        attempt.key == key, ~attempt.success, attempt.at > window_start
                    )
                )
            ).one()
            if count >= limit:
                retry_after = oldest + settings.failure_window - self._clock()
                raise RateLimited(max(1, math.ceil(retry_after.total_seconds())))

    async def _record_attempts(self, s: AsyncSession, keys: list[str], *, success: bool) -> None:
        now = self._clock()
        await s.execute(
            insert(t.login_attempt), [{"key": k, "at": now, "success": success} for k in keys]
        )
        # Keep the table small: attempts older than a day are no longer useful.
        await s.execute(
            delete(t.login_attempt).where(t.login_attempt.c.at < now - timedelta(days=1))
        )

    async def _transaction(self, work: Callable[[AsyncSession], Awaitable[T]]) -> T:
        try:
            async with self._session_factory() as s, s.begin():
                return await work(s)
        except (ProgrammingError, OperationalError) as exc:
            if is_missing_table(exc):
                raise AdminNotMigrated() from exc
            raise


async def _first(s: AsyncSession, stmt: Any) -> Any:
    return (await s.execute(stmt)).first()


def is_missing_table(exc: Exception) -> bool:
    """Whether a database error means one of OneAdmin's tables doesn't exist (not migrated)."""
    text = str(exc).lower()
    mentions_ours = t.PREFIX in text
    missing = "does not exist" in text or "no such table" in text or "doesn't exist" in text
    return mentions_ours and missing

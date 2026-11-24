import asyncio
from collections import deque
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import math
import re
import secrets
import threading
import time
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_db
from app.models import User

_PBKDF2_SCHEME = "pbkdf2_sha256"
_PBKDF2_ITERATIONS = 120_000
_WA_JID_SUFFIX_RE = re.compile(r"(?::\d+)?@(?:c\.us|s\.whatsapp\.net)$", re.IGNORECASE)
_BEARER_SCHEME = HTTPBearer(auto_error=False)
ALLOWED_JWT_ALGORITHMS = frozenset({"HS256", "HS384", "HS512"})
LOGIN_MAX_FAILURES = 15
LOGIN_LOCKOUT_SECONDS = 300.0
PIN_MAX_FAILURES = 5
PIN_LOCKOUT_SECONDS = 300.0


class AttemptRateLimiter:
    """Thread-safe in-memory sliding-window failure tracker with lockout."""

    def __init__(self, max_failures: int, window_seconds: float) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._failures: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        cutoff = now - self.window_seconds
        bucket = self._failures.get(key)
        if bucket is None:
            if len(self._failures) > 10_000:
                stale_keys = [
                    k for k, dq in self._failures.items() if not dq or dq[-1] <= cutoff
                ]
                for stale in stale_keys:
                    self._failures.pop(stale, None)
            bucket = deque()
            self._failures[key] = bucket
            return bucket
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if not bucket:
            self._failures.pop(key, None)
            bucket = deque()
            self._failures[key] = bucket
        return bucket

    def check_allowed(self, key: str) -> tuple[bool, int]:
        """Return `(allowed, retry_after_seconds)` for the given rate-limit key."""
        now = time.monotonic()
        with self._lock:
            bucket = self._failures.get(key)
            if not bucket:
                return True, 0
            cutoff = now - self.window_seconds
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if not bucket:
                self._failures.pop(key, None)
                return True, 0
            if len(bucket) >= self.max_failures:
                retry_after = max(1, int(math.ceil(bucket[0] + self.window_seconds - now)))
                return False, retry_after
            return True, 0

    def record_failure(self, key: str) -> int:
        """Record a failed attempt and return the active failure count inside the window."""
        now = time.monotonic()
        with self._lock:
            bucket = self._prune(key, now)
            bucket.append(now)
            return len(bucket)

    def reset(self, key: str) -> None:
        """Clear failure history after successful authentication."""
        with self._lock:
            self._failures.pop(key, None)


def get_login_rate_limiter(request: Request) -> AttemptRateLimiter:
    """FastAPI dependency returning the app-scoped login failure rate limiter."""
    limiter = getattr(request.app.state, "login_rate_limiter", None)
    if limiter is None:
        limiter = AttemptRateLimiter(
            max_failures=LOGIN_MAX_FAILURES,
            window_seconds=LOGIN_LOCKOUT_SECONDS,
        )
        request.app.state.login_rate_limiter = limiter
    return limiter


def get_pin_rate_limiter(request: Request) -> AttemptRateLimiter:
    """FastAPI dependency returning the app-scoped kiosk PIN failure rate limiter."""
    limiter = getattr(request.app.state, "pin_rate_limiter", None)
    if limiter is None:
        limiter = AttemptRateLimiter(
            max_failures=PIN_MAX_FAILURES,
            window_seconds=PIN_LOCKOUT_SECONDS,
        )
        request.app.state.pin_rate_limiter = limiter
    return limiter


def _validate_jwt_algorithm(algorithm: str) -> str:
    alg = algorithm.strip()
    if alg not in ALLOWED_JWT_ALGORITHMS:
        raise ValueError(
            f"Algoritma JWT tidak diizinkan: {algorithm}. Gunakan salah satu dari {sorted(ALLOWED_JWT_ALGORITHMS)}."
        )
    return alg


def hash_secret(plain: str) -> str:
    """Hash a password or PIN using PBKDF2-HMAC-SHA256 with a random 16-byte salt."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        plain.encode("utf-8"),
        salt,
        _PBKDF2_ITERATIONS,
    )
    return f"{_PBKDF2_SCHEME}${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_secret(plain: str, hashed: str) -> bool:
    """Verify a plaintext password or PIN against a stored PBKDF2-HMAC-SHA256 hash."""
    try:
        scheme, iter_str, salt_hex, expected_hex = hashed.split("$", 3)
        if scheme != _PBKDF2_SCHEME:
            return False
        iterations = int(iter_str)
        if iterations <= 0:
            return False
        salt = bytes.fromhex(salt_hex)
    except (ValueError, TypeError):
        return False

    computed = hashlib.pbkdf2_hmac(
        "sha256",
        plain.encode("utf-8"),
        salt,
        iterations,
    ).hex()
    return hmac.compare_digest(computed, expected_hex)


async def hash_secret_async(plain: str) -> str:
    """Run PBKDF2 hashing off the asyncio event loop."""
    return await asyncio.to_thread(hash_secret, plain)


async def verify_secret_async(plain: str, hashed: str) -> bool:
    """Run PBKDF2 verification off the asyncio event loop."""
    return await asyncio.to_thread(verify_secret, plain, hashed)


def create_access_token(
    user_id: str,
    role: str,
    settings: Settings | None = None,
) -> str:
    """Create a signed JWT access token for a user."""
    cfg = settings or get_settings()
    algorithm = _validate_jwt_algorithm(cfg.jwt_algorithm)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=cfg.access_token_expire_minutes)
    payload = {
        "sub": user_id,
        "role": role,
        "iat": now,
        "exp": expires_at,
    }
    return jwt.encode(payload, cfg.jwt_secret, algorithm=algorithm)


def decode_access_token(
    token: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Decode and verify a JWT access token requiring `exp`, `sub`, and `iat`."""
    cfg = settings or get_settings()
    algorithm = _validate_jwt_algorithm(cfg.jwt_algorithm)
    return jwt.decode(
        token,
        cfg.jwt_secret,
        algorithms=[algorithm],
        options={"require": ["exp", "sub", "iat"]},
    )


def normalize_wa_phone(raw: str) -> str:
    """Normalize Indonesian WhatsApp numbers or JIDs into canonical `628...` digits."""
    if not isinstance(raw, str):
        raise ValueError("Nomor WhatsApp tidak valid.")

    cleaned = _WA_JID_SUFFIX_RE.sub("", raw.strip())
    if not cleaned or re.search(r"[a-zA-Z]", cleaned):
        raise ValueError("Nomor WhatsApp tidak valid.")

    digits = re.sub(r"\D", "", cleaned)
    if digits.startswith("0062"):
        digits = "62" + digits[4:]
    elif digits.startswith("620"):
        digits = "62" + digits[3:]
    elif digits.startswith("0"):
        digits = "62" + digits[1:]
    elif digits.startswith("8"):
        digits = "62" + digits

    if not digits.startswith("628") or not (10 <= len(digits) <= 15):
        raise ValueError(
            "Nomor WhatsApp tidak valid. Gunakan format nomor Indonesia (contoh: 081234567890)."
        )

    return digits


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_BEARER_SCHEME),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    """FastAPI dependency returning the authenticated user from a Bearer JWT."""
    auth_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Autentikasi diperlukan. Silakan login kembali.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not credentials.credentials
    ):
        raise auth_error

    try:
        payload = decode_access_token(credentials.credentials, settings=settings)
    except (jwt.PyJWTError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesi Anda telah berakhir atau token tidak valid. Silakan login kembali.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user_id = payload.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise auth_error

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise auth_error
    return user


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """FastAPI dependency restricting access to admin users."""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak. Hanya admin yang dapat mengakses fitur ini.",
        )
    return current_user


async def require_teacher(current_user: User = Depends(get_current_user)) -> User:
    """FastAPI dependency restricting access to teacher users."""
    if current_user.role != "teacher":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak. Hanya guru yang dapat mengakses fitur ini.",
        )
    return current_user


async def require_staff(current_user: User = Depends(get_current_user)) -> User:
    """FastAPI dependency allowing authenticated admin or teacher staff."""
    if current_user.role not in {"admin", "teacher"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak. Hanya admin atau guru yang dapat mengakses fitur ini.",
        )
    return current_user

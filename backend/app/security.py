from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import re
import secrets
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_db
from app.models import User

_PBKDF2_SCHEME = "pbkdf2_sha256"
_PBKDF2_ITERATIONS = 120_000
_WA_JID_SUFFIX_RE = re.compile(r"@(?:c\.us|s\.whatsapp\.net)$", re.IGNORECASE)
_BEARER_SCHEME = HTTPBearer(auto_error=False)


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


def create_access_token(
    user_id: str,
    role: str,
    settings: Settings | None = None,
) -> str:
    """Create a signed JWT access token for a user."""
    cfg = settings or get_settings()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=cfg.access_token_expire_minutes)
    payload = {
        "sub": user_id,
        "role": role,
        "iat": now,
        "exp": expires_at,
    }
    return jwt.encode(payload, cfg.jwt_secret, algorithm=cfg.jwt_algorithm)


def decode_access_token(
    token: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Decode and verify a JWT access token."""
    cfg = settings or get_settings()
    return jwt.decode(token, cfg.jwt_secret, algorithms=[cfg.jwt_algorithm])


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
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesi Anda telah berakhir atau token tidak valid. Silakan login kembali.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user_id = payload.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise auth_error

    user = await db.get(User, user_id)
    if user is None:
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

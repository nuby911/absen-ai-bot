from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_db
from app.models import User
from app.schemas import (
    KioskPinUpdateRequest,
    KioskPinUpdateResponse,
    LoginRequest,
    LoginResponse,
    UserResponse,
    VerifyPinRequest,
    VerifyPinResponse,
)
from app.security import (
    AttemptRateLimiter,
    create_access_token,
    get_current_user,
    get_login_rate_limiter,
    get_pin_rate_limiter,
    hash_secret_async,
    require_teacher,
    verify_secret_async,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _raise_rate_limited(retry_after: int, action_label: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=f"Terlalu banyak percobaan {action_label} gagal. Coba lagi dalam {retry_after} detik.",
        headers={"Retry-After": str(retry_after)},
    )


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    login_limiter: AttemptRateLimiter = Depends(get_login_rate_limiter),
) -> LoginResponse:
    """Authenticate an admin or teacher by email or NIP and return a JWT."""
    identifier = payload.identifier.strip()
    rate_key = identifier.lower()
    allowed, retry_after = login_limiter.check_allowed(rate_key)
    if not allowed:
        _raise_rate_limited(retry_after, "login")

    if "@" in identifier:
        user = await db.scalar(
            select(User).where(func.lower(User.email) == identifier.lower()).limit(1)
        )
        if user is None:
            user = await db.scalar(select(User).where(User.nip == identifier).limit(1))
    else:
        user = await db.scalar(select(User).where(User.nip == identifier).limit(1))
        if user is None:
            user = await db.scalar(
                select(User).where(func.lower(User.email) == identifier.lower()).limit(1)
            )

    if (
        user is None
        or not user.is_active
        or not (await verify_secret_async(payload.password, user.password_hash))
    ):
        login_limiter.record_failure(rate_key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email/NIP atau kata sandi salah.",
        )

    login_limiter.reset(rate_key)
    token = create_access_token(user.id, user.role, settings=settings)
    return LoginResponse(
        access_token=token,
        token_type="bearer",
        user=UserResponse.from_user(user),
    )


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)) -> UserResponse:
    """Return the currently authenticated user's profile."""
    return UserResponse.from_user(current_user)


@router.put("/kiosk-pin", response_model=KioskPinUpdateResponse)
async def update_kiosk_pin(
    payload: KioskPinUpdateRequest,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
    pin_limiter: AttemptRateLimiter = Depends(get_pin_rate_limiter),
) -> KioskPinUpdateResponse:
    """Set or update the authenticated teacher's kiosk lock PIN."""
    if current_user.kiosk_pin_hash:
        allowed, retry_after = pin_limiter.check_allowed(current_user.id)
        if not allowed:
            _raise_rate_limited(retry_after, "verifikasi PIN Kiosk")

        valid_current = bool(
            payload.current_pin
            and await verify_secret_async(payload.current_pin, current_user.kiosk_pin_hash)
        )
        if not valid_current:
            pin_limiter.record_failure(current_user.id)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="PIN Kiosk lama wajib diisi dan harus sesuai.",
            )
        pin_limiter.reset(current_user.id)

    current_user.kiosk_pin_hash = await hash_secret_async(payload.pin)
    await db.commit()
    await db.refresh(current_user)
    return KioskPinUpdateResponse(
        message="PIN Kiosk berhasil disimpan.",
        has_kiosk_pin=True,
    )


@router.post("/verify-pin", response_model=VerifyPinResponse)
async def verify_kiosk_pin(
    payload: VerifyPinRequest,
    current_user: User = Depends(require_teacher),
    pin_limiter: AttemptRateLimiter = Depends(get_pin_rate_limiter),
) -> VerifyPinResponse:
    """Verify a submitted PIN against the authenticated teacher's stored kiosk PIN."""
    has_kiosk_pin = bool(current_user.kiosk_pin_hash)
    if not has_kiosk_pin:
        return VerifyPinResponse(valid=False, has_kiosk_pin=False)

    allowed, retry_after = pin_limiter.check_allowed(current_user.id)
    if not allowed:
        _raise_rate_limited(retry_after, "verifikasi PIN Kiosk")

    assert current_user.kiosk_pin_hash is not None
    valid = await verify_secret_async(payload.pin, current_user.kiosk_pin_hash)
    if valid:
        pin_limiter.reset(current_user.id)
    else:
        pin_limiter.record_failure(current_user.id)
    return VerifyPinResponse(valid=valid, has_kiosk_pin=True)

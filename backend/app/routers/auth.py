from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, or_, select
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
    create_access_token,
    get_current_user,
    hash_secret,
    require_teacher,
    verify_secret,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LoginResponse:
    """Authenticate an admin or teacher by email or NIP and return a JWT."""
    identifier = payload.identifier
    stmt = select(User).where(
        or_(
            func.lower(User.email) == identifier.lower(),
            User.nip == identifier,
        )
    )
    user = (await db.execute(stmt)).scalar_one_or_none()
    if user is None or not verify_secret(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email/NIP atau kata sandi salah.",
        )

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
) -> KioskPinUpdateResponse:
    """Set or update the authenticated teacher's kiosk lock PIN."""
    current_user.kiosk_pin_hash = hash_secret(payload.pin)
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
) -> VerifyPinResponse:
    """Verify a submitted PIN against the authenticated teacher's stored kiosk PIN."""
    valid = bool(
        current_user.kiosk_pin_hash
        and verify_secret(payload.pin, current_user.kiosk_pin_hash)
    )
    return VerifyPinResponse(valid=valid)

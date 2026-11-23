import re

from pydantic import BaseModel, Field, field_validator

from app.models import User


class LoginRequest(BaseModel):
    """Credentials payload accepting either email or NIP as identifier."""

    identifier: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)

    @field_validator("identifier")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Email atau NIP wajib diisi.")
        return stripped


class UserResponse(BaseModel):
    """Public profile representation of an authenticated staff user."""

    id: str
    name: str
    email: str
    role: str
    nip: str | None
    has_kiosk_pin: bool

    @classmethod
    def from_user(cls, user: User) -> "UserResponse":
        return cls(
            id=user.id,
            name=user.name,
            email=user.email,
            role=user.role,
            nip=user.nip,
            has_kiosk_pin=bool(user.kiosk_pin_hash),
        )


class LoginResponse(BaseModel):
    """Bearer access token response alongside authenticated user metadata."""

    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class KioskPinUpdateRequest(BaseModel):
    """Payload for setting or updating a teacher's 4–6 digit numeric kiosk PIN."""

    pin: str

    @field_validator("pin")
    @classmethod
    def validate_pin(cls, value: str) -> str:
        if not re.fullmatch(r"\d{4,6}", value):
            raise ValueError("PIN Kiosk harus terdiri dari 4 hingga 6 digit angka.")
        return value


class KioskPinUpdateResponse(BaseModel):
    """Confirmation returned after updating the kiosk PIN."""

    message: str
    has_kiosk_pin: bool = True


class VerifyPinRequest(BaseModel):
    """Payload for verifying a teacher's kiosk PIN."""

    pin: str = Field(..., min_length=1)


class VerifyPinResponse(BaseModel):
    """Result of kiosk PIN verification."""

    valid: bool

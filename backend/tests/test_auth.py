from datetime import datetime, timedelta, timezone

from fastapi import Depends
import httpx
import jwt
import pytest

from app.config import Settings
from app.main import create_app
from app.models import User
from app.security import (
    create_access_token,
    decode_access_token,
    normalize_wa_phone,
    require_admin,
)


def test_normalize_wa_phone_variants() -> None:
    assert normalize_wa_phone("0812-7900-1234") == "6281279001234"
    assert normalize_wa_phone("+62 812 7900 1234") == "6281279001234"
    assert normalize_wa_phone("6281279001234@c.us") == "6281279001234"
    assert normalize_wa_phone("6281279001234@s.whatsapp.net") == "6281279001234"
    assert normalize_wa_phone("6281279001234:12@s.whatsapp.net") == "6281279001234"
    assert normalize_wa_phone("81279001234") == "6281279001234"
    assert normalize_wa_phone("(0812) 7900 1234") == "6281279001234"

    for invalid in ("", "   ", "abc", "123", "0812", "628123456789012345"):
        with pytest.raises(ValueError):
            normalize_wa_phone(invalid)


async def test_login_by_email_and_nip_and_wrong_password(
    client,
    seeded_teacher: User,
) -> None:
    email_res = await client.post(
        "/api/v1/auth/login",
        json={"identifier": seeded_teacher.email, "password": "guru123"},
    )
    assert email_res.status_code == 200
    email_data = email_res.json()
    assert email_data["token_type"] == "bearer"
    assert isinstance(email_data["access_token"], str) and email_data["access_token"]
    assert email_data["user"] == {
        "id": seeded_teacher.id,
        "name": seeded_teacher.name,
        "email": seeded_teacher.email,
        "role": "teacher",
        "nip": seeded_teacher.nip,
        "has_kiosk_pin": False,
    }

    nip_res = await client.post(
        "/api/v1/auth/login",
        json={"identifier": seeded_teacher.nip, "password": "guru123"},
    )
    assert nip_res.status_code == 200
    assert nip_res.json()["user"]["id"] == seeded_teacher.id

    wrong_res = await client.post(
        "/api/v1/auth/login",
        json={"identifier": seeded_teacher.email, "password": "salah-password"},
    )
    assert wrong_res.status_code == 401
    assert "salah" in wrong_res.json()["detail"].lower()

    unknown_res = await client.post(
        "/api/v1/auth/login",
        json={"identifier": "tidakada@sekolah.sch.id", "password": "guru123"},
    )
    assert unknown_res.status_code == 401


async def test_kiosk_pin_validation_and_verification(
    client,
    teacher_headers: dict[str, str],
) -> None:
    initial_verify = await client.post(
        "/api/v1/auth/verify-pin",
        headers=teacher_headers,
        json={"pin": "1234"},
    )
    assert initial_verify.status_code == 200
    assert initial_verify.json() == {"valid": False, "has_kiosk_pin": False}

    for invalid_pin in ("12", "1234567", "12ab", ""):
        res = await client.put(
            "/api/v1/auth/kiosk-pin",
            headers=teacher_headers,
            json={"pin": invalid_pin},
        )
        assert res.status_code == 422

    # First-time setup does NOT require current_pin
    set_res = await client.put(
        "/api/v1/auth/kiosk-pin",
        headers=teacher_headers,
        json={"pin": "1234"},
    )
    assert set_res.status_code == 200
    assert set_res.json()["has_kiosk_pin"] is True
    assert "message" in set_res.json()

    me_res = await client.get("/api/v1/auth/me", headers=teacher_headers)
    assert me_res.status_code == 200
    assert me_res.json()["has_kiosk_pin"] is True

    valid_res = await client.post(
        "/api/v1/auth/verify-pin",
        headers=teacher_headers,
        json={"pin": "1234"},
    )
    assert valid_res.status_code == 200
    assert valid_res.json() == {"valid": True, "has_kiosk_pin": True}

    invalid_res = await client.post(
        "/api/v1/auth/verify-pin",
        headers=teacher_headers,
        json={"pin": "9999"},
    )
    assert invalid_res.status_code == 200
    assert invalid_res.json() == {"valid": False, "has_kiosk_pin": True}

    # Updating an already-set PIN requires valid current_pin
    missing_cur = await client.put(
        "/api/v1/auth/kiosk-pin",
        headers=teacher_headers,
        json={"pin": "5678"},
    )
    assert missing_cur.status_code == 403

    wrong_cur = await client.put(
        "/api/v1/auth/kiosk-pin",
        headers=teacher_headers,
        json={"pin": "5678", "current_pin": "0000"},
    )
    assert wrong_cur.status_code == 403

    ok_update = await client.put(
        "/api/v1/auth/kiosk-pin",
        headers=teacher_headers,
        json={"pin": "5678", "current_pin": "1234"},
    )
    assert ok_update.status_code == 200
    assert ok_update.json()["has_kiosk_pin"] is True

    new_verify = await client.post(
        "/api/v1/auth/verify-pin",
        headers=teacher_headers,
        json={"pin": "5678"},
    )
    assert new_verify.status_code == 200
    assert new_verify.json() == {"valid": True, "has_kiosk_pin": True}


async def test_pin_and_login_rate_limiting_and_jwt_hardening(
    client,
    seeded_teacher: User,
    teacher_headers: dict[str, str],
    test_settings: Settings,
) -> None:
    # 1. Configure PIN then exceed 5 failed PIN checks -> 429 lockout
    assert (
        await client.put(
            "/api/v1/auth/kiosk-pin",
            headers=teacher_headers,
            json={"pin": "4321"},
        )
    ).status_code == 200

    for _ in range(5):
        res = await client.post(
            "/api/v1/auth/verify-pin",
            headers=teacher_headers,
            json={"pin": "0000"},
        )
        assert res.status_code == 200
        assert res.json() == {"valid": False, "has_kiosk_pin": True}

    locked_pin = await client.post(
        "/api/v1/auth/verify-pin",
        headers=teacher_headers,
        json={"pin": "4321"},
    )
    assert locked_pin.status_code == 429
    assert int(locked_pin.headers["retry-after"]) >= 1

    # 2. Exceed 15 failed logins -> 429 lockout
    for _ in range(15):
        bad_login = await client.post(
            "/api/v1/auth/login",
            json={"identifier": seeded_teacher.email, "password": "wrong-password"},
        )
        assert bad_login.status_code == 401

    locked_login = await client.post(
        "/api/v1/auth/login",
        json={"identifier": seeded_teacher.email, "password": "guru123"},
    )
    assert locked_login.status_code == 429
    assert int(locked_login.headers["retry-after"]) >= 1

    # 3. JWT hardening: disallow unsupported algorithm and require exp/sub/iat
    bad_alg_settings = test_settings.model_copy(update={"jwt_algorithm": "none"})
    with pytest.raises(ValueError):
        create_access_token(seeded_teacher.id, "teacher", settings=bad_alg_settings)

    token_missing_iat = jwt.encode(
        {
            "sub": seeded_teacher.id,
            "role": "teacher",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
        },
        test_settings.jwt_secret,
        algorithm="HS256",
    )
    with pytest.raises(jwt.MissingRequiredClaimError):
        decode_access_token(token_missing_iat, settings=test_settings)


async def test_security_headers_and_custom_cors_origins(tmp_path) -> None:
    custom_settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        jwt_secret="custom-strong-secret-for-headers-test-2026",
        cors_allow_origins="https://admin.sekolah.sch.id, http://localhost:3001",
        upload_dir=str(tmp_path / "uploads"),
    )
    app = create_app(settings=custom_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as local_client:
        res = await local_client.get(
            "/health",
            headers={"Origin": "https://admin.sekolah.sch.id"},
        )
        assert res.status_code == 200
        assert res.headers.get("x-content-type-options") == "nosniff"
        assert res.headers.get("x-frame-options") == "DENY"
        assert res.headers.get("referrer-policy") == "strict-origin-when-cross-origin"
        assert res.headers.get("access-control-allow-origin") == "https://admin.sekolah.sch.id"


async def test_rbac_guards(
    client,
    seeded_admin: User,
    seeded_teacher: User,
    admin_headers: dict[str, str],
    teacher_headers: dict[str, str],
) -> None:
    unauth_res = await client.get("/api/v1/auth/me")
    assert unauth_res.status_code == 401

    bad_token_res = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer token-palsu"},
    )
    assert bad_token_res.status_code == 401

    teacher_me = await client.get("/api/v1/auth/me", headers=teacher_headers)
    assert teacher_me.status_code == 200
    assert teacher_me.json()["id"] == seeded_teacher.id

    admin_kiosk_res = await client.put(
        "/api/v1/auth/kiosk-pin",
        headers=admin_headers,
        json={"pin": "1234"},
    )
    assert admin_kiosk_res.status_code == 403

    fastapi_app = client._transport.app  # type: ignore[attr-defined]

    @fastapi_app.get("/api/v1/_test-admin-only")
    async def _admin_only_probe(
        current_admin: User = Depends(require_admin),
    ) -> dict[str, str]:
        return {"id": current_admin.id}

    teacher_forbidden = await client.get(
        "/api/v1/_test-admin-only",
        headers=teacher_headers,
    )
    assert teacher_forbidden.status_code == 403

    admin_ok = await client.get(
        "/api/v1/_test-admin-only",
        headers=admin_headers,
    )
    assert admin_ok.status_code == 200
    assert admin_ok.json() == {"id": seeded_admin.id}


async def test_health_endpoint(client) -> None:
    res = await client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}

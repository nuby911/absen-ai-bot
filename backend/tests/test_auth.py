import pytest
from fastapi import Depends

from app.models import User
from app.security import normalize_wa_phone, require_admin


def test_normalize_wa_phone_variants() -> None:
    assert normalize_wa_phone("0812-7900-1234") == "6281279001234"
    assert normalize_wa_phone("+62 812 7900 1234") == "6281279001234"
    assert normalize_wa_phone("6281279001234@c.us") == "6281279001234"
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
    assert initial_verify.json() == {"valid": False}

    for invalid_pin in ("12", "1234567", "12ab", ""):
        res = await client.put(
            "/api/v1/auth/kiosk-pin",
            headers=teacher_headers,
            json={"pin": invalid_pin},
        )
        assert res.status_code == 422

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
    assert valid_res.json() == {"valid": True}

    invalid_res = await client.post(
        "/api/v1/auth/verify-pin",
        headers=teacher_headers,
        json={"pin": "9999"},
    )
    assert invalid_res.status_code == 200
    assert invalid_res.json() == {"valid": False}


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

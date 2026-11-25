import pytest
from fastapi.testclient import TestClient
from myapp.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LOAN_DB_PATH", str(tmp_path / "loans.sqlite3"))
    monkeypatch.setenv("LOAN_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("LOAN_ADMIN_PASSWORD", "a-very-long-admin-password")
    with TestClient(app) as test_client:
        yield test_client


def sign_in(client, username, password):
    response = client.post("/api/login", json={"username": username, "password": password})
    assert response.status_code == 200


def create_staff(client, username, password, role):
    response = client.post(
        "/api/staff",
        json={"username": username, "password": password, "role": role},
    )
    assert response.status_code == 201


def test_homepage_and_static_assets_are_available(client):
    homepage = client.get("/")
    assert homepage.status_code == 200
    assert "Start an application" in homepage.text
    assert client.get("/static/app.js").status_code == 200


def test_customer_can_apply_and_track_without_signing_in(client):
    response = client.post(
        "/api/applications",
        json={
            "applicant_name": "Avery Customer",
            "email": "avery@example.com",
            "amount": 12500,
            "purpose": "Replace essential home heating equipment",
        },
    )
    assert response.status_code == 201
    application = response.json()
    assert application["status"] == "coordinator_review"

    tracking = client.get(f"/api/track/{application['tracking_code']}")
    assert tracking.status_code == 200
    assert tracking.json()["applicant_name"] == "Avery Customer"
    assert client.get("/api/applications").status_code == 401
    assert client.get("/api/track/not-a-valid-code").status_code == 404


def test_application_moves_through_role_specific_approval_stages(client):
    sign_in(client, "admin", "a-very-long-admin-password")
    staff = [
        ("coordinator", "coordinator-password-1", "coordinator", "forward", "level_1_review"),
        ("level1", "level-one-password-1", "approver_level_1", "approve", "level_2_review"),
        ("level2", "level-two-password-1", "approver_level_2", "approve", "finance_pending"),
        ("finance", "finance-password-123", "finance", "disburse", "funded"),
    ]
    for username, password, role, _, _ in staff:
        create_staff(client, username, password, role)

    application = client.post(
        "/api/applications",
        json={
            "applicant_name": "Jordan Applicant",
            "email": "jordan@example.com",
            "amount": 8000,
            "purpose": "Cover costs for a professional certification course",
        },
    ).json()

    for username, password, _, action, expected_status in staff:
        client.post("/api/logout")
        sign_in(client, username, password)
        response = client.post(
            f"/api/applications/{application['application_id']}/actions",
            json={"action": action},
        )
        assert response.status_code == 200
        assert response.json()["status"] == expected_status

    assert len(response.json()["events"]) == 5


def test_rejection_requires_a_reason_and_admin_cannot_approve(client):
    sign_in(client, "admin", "a-very-long-admin-password")
    create_staff(client, "reviewer", "reviewer-password-123", "approver_level_1")
    application = client.post(
        "/api/applications",
        json={
            "applicant_name": "Sam Applicant",
            "email": "sam@example.com",
            "amount": 1000,
            "purpose": "Purchase tools needed to start a small business",
        },
    ).json()
    rejected = client.post(
        f"/api/applications/{application['application_id']}/actions",
        json={"action": "reject", "note": "The requested income evidence is missing."},
    )
    assert rejected.status_code == 403

    client.post("/api/logout")
    sign_in(client, "reviewer", "reviewer-password-123")
    wrong_stage = client.post(
        f"/api/applications/{application['application_id']}/actions",
        json={"action": "approve"},
    )
    assert wrong_stage.status_code == 409
    assert client.post(
        f"/api/applications/{application['application_id']}/actions",
        json={"action": "reject"},
    ).status_code == 422

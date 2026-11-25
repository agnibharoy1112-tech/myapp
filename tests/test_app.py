import pytest
from fastapi.testclient import TestClient

from myapp.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LOAN_DB_PATH", str(tmp_path / "loans.sqlite3"))
    monkeypatch.setenv("LOAN_UPLOAD_DIR", str(tmp_path / "documents"))
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


def submit_application(client, name="Avery Customer", email="avery@example.com"):
    return client.post(
        "/api/applications",
        json={
            "applicant_name": name,
            "email": email,
            "amount": 12500,
            "loan_type": "Personal Loan",
            "purpose": "Replace essential home heating equipment",
        },
    )


def test_homepage_and_static_assets_are_available(client):
    homepage = client.get("/")
    assert homepage.status_code == 200
    assert "Start an application" in homepage.text
    assert client.get("/static/app.js").status_code == 200


def test_customer_can_apply_and_track_without_signing_in(client):
    response = submit_application(client)
    assert response.status_code == 201
    application = response.json()
    assert application["status"] == "coordinator_review"

    tracking = client.get(f"/api/track/{application['tracking_code']}")
    assert tracking.status_code == 200
    assert tracking.json()["applicant_name"] == "Avery Customer"
    assert client.get("/api/applications").status_code == 401
    assert client.get("/api/track/not-a-valid-code").status_code == 404
    invalid_type = client.post(
        "/api/applications",
        json={
            "applicant_name": "Avery Customer",
            "email": "avery@example.com",
            "amount": 12500,
            "loan_type": "Unlisted product",
            "purpose": "Replace essential home heating equipment",
        },
    )
    assert invalid_type.status_code == 422


def test_applicant_can_upload_multiple_documents_and_staff_downloads_them(client):
    application = submit_application(client, "Case Applicant", "case@example.com").json()
    upload = client.post(
        f"/api/track/{application['tracking_code']}/documents",
        files=[
            ("files", ("income.pdf", b"proof of income", "application/pdf")),
            ("files", ("license.png", b"photo id", "image/png")),
        ],
    )
    assert upload.status_code == 201
    assert len(upload.json()["documents"]) == 2
    document_id = upload.json()["documents"][0]["id"]
    assert client.get(f"/api/documents/{document_id}").status_code == 401

    sign_in(client, "admin", "a-very-long-admin-password")
    response = client.get(f"/api/documents/{document_id}")
    assert response.status_code == 200
    assert response.content == b"proof of income"

    case = client.get("/api/applications").json()[0]
    assert len(case["documents"]) == 2
    assert case["events"][-1]["action"] == "documents_uploaded"


def test_admin_case_edits_record_each_changed_field(client):
    sign_in(client, "admin", "a-very-long-admin-password")
    application = submit_application(client, "Taylor Applicant", "taylor@example.com").json()
    response = client.patch(
        f"/api/applications/{application['application_id']}",
        json={
            "amount": 5400,
            "loan_type": "Home Equity Loan / HELOC",
            "reason": "Corrected the requested amount and loan product after review.",
        },
    )
    assert response.status_code == 200
    assert response.json()["amount"] == 5400
    assert {change["field_name"] for change in response.json()["field_changes"]} == {
        "amount",
        "loan_type",
    }
    assert all(change["old_value"] != change["new_value"] for change in response.json()["field_changes"])
    assert client.patch(
        f"/api/applications/{application['application_id']}",
        json={"amount": 5600},
    ).status_code == 422


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
    application = submit_application(client, "Jordan Applicant", "jordan@example.com").json()

    for username, password, _, action, expected_status in staff:
        client.post("/api/logout")
        sign_in(client, username, password)
        payload = {"action": action}
        if action == "approve":
            payload.update(
                reason_code="affordability_confirmed",
                note="Income and repayment checks meet the affordability guidance.",
            )
        response = client.post(
            f"/api/applications/{application['application_id']}/actions",
            json=payload,
        )
        assert response.status_code == 200
        assert response.json()["status"] == expected_status

    assert len(response.json()["events"]) == 5


def test_approval_and_rejection_require_reason_and_explanation(client):
    sign_in(client, "admin", "a-very-long-admin-password")
    create_staff(client, "coordinator", "coordinator-password-1", "coordinator")
    create_staff(client, "reviewer", "reviewer-password-123", "approver_level_1")
    application = submit_application(client, "Sam Applicant", "sam@example.com").json()
    case_url = f"/api/applications/{application['application_id']}/actions"

    assert client.post(case_url, json={"action": "reject"}).status_code == 403
    client.post("/api/logout")
    sign_in(client, "reviewer", "reviewer-password-123")
    wrong_stage = client.post(
        case_url,
        json={
            "action": "approve",
            "reason_code": "affordability_confirmed",
            "note": "The application is affordable based on submitted evidence.",
        },
    )
    assert wrong_stage.status_code == 409

    client.post("/api/logout")
    sign_in(client, "coordinator", "coordinator-password-1")
    assert client.post(case_url, json={"action": "forward"}).status_code == 200
    client.post("/api/logout")
    sign_in(client, "reviewer", "reviewer-password-123")

    assert client.post(case_url, json={"action": "approve"}).status_code == 422
    assert client.post(
        case_url,
        json={"action": "reject", "reason_code": "eligibility_not_met", "note": "No."},
    ).status_code == 422
    rejected = client.post(
        case_url,
        json={
            "action": "reject",
            "reason_code": "eligibility_not_met",
            "note": "The applicant does not meet the minimum eligibility requirements.",
        },
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["events"][-1]["reason_code"] == "eligibility_not_met"

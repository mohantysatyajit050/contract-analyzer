import io

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_check():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_analyze_rejects_empty_file():
    empty_file = io.BytesIO(b"")
    response = client.post(
        "/api/analyze",
        files={"file": ("empty.txt", empty_file, "text/plain")},
        data={"company_name": "", "user_question": ""},
    )
    assert response.status_code == 400


def test_analyze_and_review_happy_path():
    contract_text = (
        "1. Payment terms.\n\nPayment is due within 30 days of invoice.\n\n"
        "2. Termination.\n\nEither party may terminate this agreement at its sole discretion."
    )
    file_obj = io.BytesIO(contract_text.encode("utf-8"))

    analyze_response = client.post(
        "/api/analyze",
        files={"file": ("sample.txt", file_obj, "text/plain")},
        data={"company_name": "Acme Supplies", "user_question": "check termination clauses"},
    )
    assert analyze_response.status_code == 200
    body = analyze_response.json()
    assert body["review_status"] in ("pending", "rejected")
    session_id = body["session_id"]

    if body["review_status"] == "pending":
        review_response = client.post(
            "/api/review",
            json={"session_id": session_id, "decision": "approve", "notes": None},
        )
        assert review_response.status_code == 200
        assert review_response.json()["review_status"] == "approved"


def test_review_rejects_unknown_session():
    response = client.post(
        "/api/review",
        json={"session_id": "does_not_exist", "decision": "approve", "notes": None},
    )
    assert response.status_code == 404


def test_review_rejects_invalid_decision():
    contract_text = "1. A clause.\n\nSome contract text."
    file_obj = io.BytesIO(contract_text.encode("utf-8"))
    analyze_response = client.post(
        "/api/analyze",
        files={"file": ("sample.txt", file_obj, "text/plain")},
        data={"company_name": "", "user_question": ""},
    )
    session_id = analyze_response.json()["session_id"]

    response = client.post(
        "/api/review",
        json={"session_id": session_id, "decision": "maybe", "notes": None},
    )
    assert response.status_code == 400
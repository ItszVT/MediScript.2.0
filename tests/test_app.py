"""
Integration tests for the full app. OCR is mocked (we test OUR code, not
OCR.space's network service). Each test uses an isolated temp SQLite DB.
"""
import os
import tempfile

import numpy as np
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    # isolated DB per test: a fresh engine bound to a temp SQLite file, wired in
    # via FastAPI dependency_overrides (keeps the models' Base intact).
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setenv("SECRET_KEY", "test-secret")

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.core.database import Base, get_db
    import app.models  # noqa: F401  (register all tables on Base)

    test_engine = create_engine(f"sqlite:///{tmp.name}",
                                connect_args={"check_same_thread": False})
    TestingSession = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=test_engine)

    def _override_get_db():
        s = TestingSession()
        try:
            yield s
        finally:
            s.close()

    # mock OCR: return deterministic text so we exercise matching + persistence
    from app.services import extraction

    class _Line:
        def __init__(self, text, box=(10, 20, 100, 18)):
            self.text, self.confidence, self.box = text, 88.0, box

    class _Ocr:
        ok = True
        text = "Augmentin 625\nPantoprazole 40\nParacetamol 500"
        mean_confidence = 88.0
        lines = [_Line("Augmentin 625", (10, 20, 120, 18)),
                 _Line("Pantoprazole 40", (10, 44, 120, 18)),
                 _Line("Paracetamol 500", (10, 68, 120, 18))]
        error = None

    class _Engine:
        def read_image(self, *a, **k): return _Ocr()
        def read_region(self, *a, **k): return _Ocr()

    monkeypatch.setattr(extraction, "get_engine", lambda: _Engine())
    monkeypatch.setattr(extraction, "_decode",
                        lambda b: np.zeros((10, 10, 3), np.uint8))

    from app.main import create_app
    from app.core.database import get_db as real_get_db
    app = create_app()
    app.dependency_overrides[real_get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    os.unlink(tmp.name)


def _register(client, email, role="user", pharmacy=""):
    return client.post("/api/auth/register", json={
        "email": email, "password": "secret123", "full_name": "Test",
        "role": role, "pharmacy_name": pharmacy})


# ------------------------------- auth -------------------------------------
def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_register_login_logout(client):
    r = _register(client, "u1@test.com")
    assert r.status_code == 200 and r.json()["redirect"] == "/app"
    # duplicate
    assert _register(client, "u1@test.com").status_code == 409
    # bad login
    assert client.post("/api/auth/login", json={
        "email": "u1@test.com", "password": "wrong"}).status_code == 401
    # good login
    assert client.post("/api/auth/login", json={
        "email": "u1@test.com", "password": "secret123"}).status_code == 200


def test_chemist_role_and_guard(client):
    _register(client, "c1@test.com", role="chemist", pharmacy="City Care")
    assert client.get("/api/chemist/inventory").status_code == 200
    # a plain user may not touch chemist endpoints
    client.post("/api/auth/logout")
    _register(client, "u2@test.com")
    assert client.get("/api/chemist/inventory").status_code == 403


# ------------------------------- user flow --------------------------------
def test_user_upload_and_persistence(client):
    _register(client, "u3@test.com")
    r = client.post("/api/user/upload",
                    files={"file": ("rx.png", b"fakebytes", "image/png")})
    assert r.status_code == 200
    data = r.json()
    names = [m["name"] for m in data["matches"]]
    assert any("Augmentin" in n for n in names)
    assert any("Pantoprazole" in n for n in names)
    assert data["raw_text"]
    # persisted analytics reflect the scan
    a = client.get("/api/user/analytics").json()
    assert a["prescriptions_scanned"] == 1
    assert a["medicines_detected"] >= 2


def test_search_and_vote_persist(client):
    _register(client, "u4@test.com")
    s = client.get("/api/user/search", params={"q": "Metformin"}).json()
    assert s["results"] and s["results"][0]["name"]
    client.post("/api/user/vote", json={
        "context": "search", "predicted": "Metformin", "verdict": "yes"})
    a = client.get("/api/user/analytics").json()
    assert a["accuracy"]["total"] == 1 and a["accuracy"]["yes"] == 1


# ------------------------------- chemist flow -----------------------------
def test_inventory_add_check_and_demand(client):
    _register(client, "c2@test.com", role="chemist", pharmacy="Care")
    # add stock
    client.post("/api/chemist/inventory", data={
        "name": "Paracetamol", "quantity": "50", "reorder_level": "10"})
    inv = client.get("/api/chemist/inventory").json()
    assert inv["stats"]["total_items"] == 1

    # confirm a stocked medicine -> in_stock
    r = client.post("/api/chemist/confirm",
                    json={"medicine": "Paracetamol", "context": "upload"}).json()
    assert r["stock"]["status"] == "in_stock"

    # confirm an un-stocked medicine -> restock filed
    r2 = client.post("/api/chemist/confirm",
                     json={"medicine": "Insulin", "context": "upload"}).json()
    assert r2["stock"]["status"] == "not_stocked"
    pending = client.get("/api/chemist/restock").json()["pending"]
    assert any(p["medicine"] == "Insulin" for p in pending)

    # business analytics persisted
    an = client.get("/api/chemist/analytics").json()
    assert an["stock"]["total_checks"] >= 2
    assert an["accuracy"]["total"] >= 2


def test_csv_import_and_clear_demo(client):
    _register(client, "c3@test.com", role="chemist", pharmacy="Care")
    csv = b"medicine,quantity,rack_location\nAspirin,30,A1\nIbuprofen,20,A2\n"
    r = client.post("/api/chemist/inventory/import",
                    files={"file": ("stock.csv", csv, "text/csv")}).json()
    assert r["imported"] == 2
    assert client.get("/api/chemist/inventory").json()["stats"]["total_items"] == 2


# ------------------------------- account settings -------------------------
def test_update_profile_and_password(client):
    _register(client, "c4@test.com", role="chemist", pharmacy="Old Name")
    # update pharmacy name + contact name
    r = client.post("/api/account/profile",
                    json={"full_name": "Jane P", "pharmacy_name": "New Pharmacy"}).json()
    assert r["pharmacy_name"] == "New Pharmacy" and r["full_name"] == "Jane P"
    assert client.get("/api/account/me").json()["pharmacy_name"] == "New Pharmacy"

    # wrong current password rejected
    bad = client.post("/api/account/password",
                      json={"current_password": "nope", "new_password": "brandnew1"})
    assert bad.status_code == 400
    # correct current password accepted, and new password works to log in
    ok = client.post("/api/account/password",
                     json={"current_password": "secret123", "new_password": "brandnew1"})
    assert ok.status_code == 200
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login",
                       json={"email": "c4@test.com", "password": "brandnew1"}).status_code == 200


# ------------------------------- guest demo -------------------------------
def test_guest_one_free_upload_then_gate(client):
    # no auth needed
    s = client.get("/api/guest/status").json()
    assert s["uploads_left"] == 1 and s["searches_left"] == 1
    # first upload works and is not persisted as a user prescription
    r1 = client.post("/api/guest/upload",
                     files={"file": ("rx.png", b"x", "image/png")}).json()
    assert r1.get("limit_reached") is False
    assert any("Augmentin" in m["name"] for m in r1["matches"])
    # second upload is gated
    r2 = client.post("/api/guest/upload",
                     files={"file": ("rx.png", b"x", "image/png")}).json()
    assert r2.get("limit_reached") is True and "account" in r2["message"].lower()


def test_guest_one_free_search_then_gate(client):
    s1 = client.get("/api/guest/search", params={"q": "Metformin"}).json()
    assert s1.get("limit_reached") is False and s1["results"]
    s2 = client.get("/api/guest/search", params={"q": "Paracetamol"}).json()
    assert s2.get("limit_reached") is True


def test_demo_page_public(client):
    # demo page renders without auth
    assert client.get("/demo?role=chemist").status_code == 200


def test_region_first_flow(client):
    _register(client, "reg@test.com")
    # prepare stores the image, opens a prescription, returns dimensions
    p = client.post("/api/user/prepare-image",
                    files={"file": ("rx.png", b"x", "image/png")}).json()
    assert p["image_id"] and p["prescription_id"] and p["image_width"] > 0
    # reading a boxed region returns an honest classified verdict
    v = client.post("/api/user/manual-region",
                    json={"x1": 0.1, "y1": 0.1, "x2": 0.9, "y2": 0.5,
                          "image_id": p["image_id"],
                          "prescription_id": p["prescription_id"]}).json()
    assert v["status"] in ("ok", "unsure")
    assert v["best"]["name"]
    # the scan + detection now show in analytics
    a = client.get("/api/user/analytics").json()
    assert a["prescriptions_scanned"] >= 1
    assert a["medicines_detected"] >= 1
    assert "confidence_distribution" in a


def test_region_expired_image(client):
    _register(client, "reg2@test.com")
    r = client.post("/api/user/manual-region",
                    json={"x1": 0, "y1": 0, "x2": 1, "y2": 1,
                          "image_id": "does-not-exist"})
    assert r.status_code == 404


from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.security_middleware import (
    SecurityHeadersMiddleware,
    LoginRateLimitMiddleware,
)


def create_test_app():
    app = FastAPI()

    app.add_middleware(SecurityHeadersMiddleware)

    app.add_middleware(
        LoginRateLimitMiddleware,
        max_attempts=5,
        window_seconds=60,
    )

    @app.get("/dashboard")
    def dashboard():
        return {"message": "Dashboard"}

    @app.post("/login")
    def login():
        return {"message": "Login submitted"}

    return app


def test_security_headers():
    client = TestClient(create_test_app())

    response = client.get("/dashboard")

    assert response.status_code == 200

    assert (
        response.headers["X-Content-Type-Options"]
        == "nosniff"
    )

    assert (
        response.headers["X-Frame-Options"]
        == "DENY"
    )

    assert "Content-Security-Policy" in response.headers


def test_dashboard_cache_disabled():
    client = TestClient(create_test_app())

    response = client.get("/dashboard")

    assert response.headers["Cache-Control"] == "no-store"


def test_login_rate_limit():
    client = TestClient(create_test_app())

    for _ in range(5):
        response = client.post("/login")
        assert response.status_code == 200

    response = client.post("/login")

    assert response.status_code == 429
    assert "Retry-After" in response.headers


def test_other_routes_not_rate_limited():
    client = TestClient(create_test_app())

    for _ in range(10):
        response = client.get("/dashboard")
        assert response.status_code == 200

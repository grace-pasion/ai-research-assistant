from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.security_headers import security_headers_middleware


def make_test_app() -> FastAPI:
    app = FastAPI()
    app.middleware("http")(security_headers_middleware)

    @app.get("/api/private")
    def private_response():
        return {"ok": True}

    return app


def test_api_responses_include_security_headers_and_are_not_cached():
    response = TestClient(make_test_app(), base_url="https://testserver").get("/api/private")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert response.headers["Permissions-Policy"] == "camera=(), microphone=(), geolocation=()"
    assert response.headers["Strict-Transport-Security"] == "max-age=31536000"
    assert response.headers["Cache-Control"] == "no-store"

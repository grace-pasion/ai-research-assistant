import pytest
from pydantic import ValidationError

from app.schemas import RegisterRequest


def test_registration_requires_a_long_non_common_password():
    for password in ("short", "password123!", "aaaaaaaaaaaa"):
        with pytest.raises(ValidationError):
            RegisterRequest(
                email="researcher@example.com",
                name="Researcher",
                password=password,
            )


def test_registration_accepts_a_long_passphrase():
    request = RegisterRequest(
        email="researcher@example.com",
        name="Researcher",
        password="a good research passphrase",
    )

    assert request.password == "a good research passphrase"

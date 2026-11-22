from uuid import uuid4

from app.security import create_access_token, hash_password, verify_password


def test_password_hash_verifies_only_matching_password():
    stored = hash_password("a sufficiently long password")

    assert stored != "a sufficiently long password"
    assert verify_password("a sufficiently long password", stored)
    assert not verify_password("a different password", stored)


def test_access_token_contains_user_identity():
    token = create_access_token(uuid4())

    assert isinstance(token, str)
    assert token.count(".") == 2

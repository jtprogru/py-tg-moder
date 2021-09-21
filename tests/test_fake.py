__test_data = {
    "username": "admin",
    "is_active": True,
    "is_verified": True
}


def test_username():
    assert __test_data["username"] is "admin"


def test_is_active():
    assert __test_data["is_active"] is True


def test_is_verified():
    assert __test_data["is_verified"] is True

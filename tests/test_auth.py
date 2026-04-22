class TestRegister:
    def test_register_success(self, client):
        resp = client.post("/api/auth/register", json={
            "username": "newuser",
            "password": "newpass123",
            "invite_code": "huiming",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["username"] == "newuser"
        assert "id" in data

    def test_register_wrong_invite_code(self, client):
        resp = client.post("/api/auth/register", json={
            "username": "newuser",
            "password": "newpass123",
            "invite_code": "wrong_code",
        })
        assert resp.status_code == 403

    def test_register_duplicate_username(self, client, registered_user):
        resp = client.post("/api/auth/register", json={
            "username": "testuser",
            "password": "testpass123",
            "invite_code": "huiming",
        })
        assert resp.status_code == 400


class TestLogin:
    def test_login_success(self, client, registered_user):
        resp = client.post("/api/auth/login", json={"username": "testuser", "password": "testpass123"})
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    def test_login_wrong_password(self, client, registered_user):
        resp = client.post("/api/auth/login", json={"username": "testuser", "password": "wrongpass"})
        assert resp.status_code == 401

    def test_login_nonexistent_user(self, client):
        resp = client.post("/api/auth/login", json={"username": "nouser", "password": "anypass"})
        assert resp.status_code == 401


class TestMe:
    def test_get_me_success(self, client, auth_headers):
        resp = client.get("/api/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["username"] == "testuser"

    def test_get_me_no_token(self, client):
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401

    def test_get_me_invalid_token(self, client):
        resp = client.get("/api/auth/me", headers={"Authorization": "Bearer invalidtoken"})
        assert resp.status_code == 401

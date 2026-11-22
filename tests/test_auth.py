"""认证、禁用 401 与权限矩阵（骨架）。"""

from __future__ import annotations

from tests.conftest import add_member, auth_header, make_kb, make_user


def test_login_success(client, db):
    make_user(db, "alice", "secret123", role="admin")
    resp = client.post("/api/auth/login", json={"username": "alice", "password": "secret123"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["token"]
    assert body["user"]["username"] == "alice"
    assert body["user"]["role"] == "admin"


def test_login_wrong_password(client, db):
    make_user(db, "alice", "secret123")
    resp = client.post("/api/auth/login", json={"username": "alice", "password": "wrong"})
    assert resp.status_code == 401


def test_login_unknown_user(client):
    resp = client.post("/api/auth/login", json={"username": "ghost", "password": "x"})
    assert resp.status_code == 401


def test_login_disabled_user(client, db):
    make_user(db, "bob", "secret123", status=0)
    resp = client.post("/api/auth/login", json={"username": "bob", "password": "secret123"})
    assert resp.status_code == 401


def test_me_requires_token(client):
    assert client.get("/api/auth/me").status_code == 401


def test_me_ok(client, db):
    user = make_user(db, "alice")
    resp = client.get("/api/auth/me", headers=auth_header(user))
    assert resp.status_code == 200
    assert resp.json()["username"] == "alice"


def test_disabled_user_existing_token_401(client, db):
    """禁用用户（status=0）存量 JWT 立即 401。"""
    user = make_user(db, "alice")
    headers = auth_header(user)
    assert client.get("/api/auth/me", headers=headers).status_code == 200
    user.status = 0
    db.commit()
    assert client.get("/api/auth/me", headers=headers).status_code == 401


# ---------- 权限矩阵骨架 ----------


def test_non_admin_cannot_manage_users(client, db):
    user = make_user(db, "alice")
    resp = client.get("/api/users", headers=auth_header(user))
    assert resp.status_code == 403


def test_admin_can_list_users(client, db):
    admin = make_user(db, "root", role="admin")
    make_user(db, "alice")
    resp = client.get("/api/users", headers=auth_header(admin))
    assert resp.status_code == 200
    assert resp.json()["total"] == 2


def test_non_admin_cannot_create_kb(client, db):
    user = make_user(db, "alice")
    resp = client.post(
        "/api/knowledge-bases", json={"name": "x"}, headers=auth_header(user)
    )
    assert resp.status_code == 403


def test_user_sees_only_member_kbs(client, db):
    admin = make_user(db, "root", role="admin")
    alice = make_user(db, "alice")
    kb = make_kb(db, "库A", created_by=admin.id)
    make_kb(db, "库B", created_by=admin.id)

    resp = client.get("/api/knowledge-bases", headers=auth_header(alice))
    assert resp.status_code == 200
    assert resp.json() == []

    add_member(db, kb.id, alice.id)
    resp = client.get("/api/knowledge-bases", headers=auth_header(alice))
    assert [k["id"] for k in resp.json()] == [kb.id]

    resp = client.get("/api/knowledge-bases", headers=auth_header(admin))
    assert len(resp.json()) == 2


def test_non_member_get_kb_members_403(client, db):
    """后端强校验：非成员访问成员接口 403，不依赖前端隐藏。"""
    admin = make_user(db, "root", role="admin")
    alice = make_user(db, "alice")
    kb = make_kb(db, "库A", created_by=admin.id)
    resp = client.get(
        f"/api/knowledge-bases/{kb.id}/members", headers=auth_header(alice)
    )
    assert resp.status_code == 403
    resp = client.get(
        f"/api/knowledge-bases/{kb.id}/members", headers=auth_header(admin)
    )
    assert resp.status_code == 200


def test_non_member_cannot_upload(client, db):
    admin = make_user(db, "root", role="admin")
    alice = make_user(db, "alice")
    kb = make_kb(db, "库A", created_by=admin.id)
    resp = client.post(
        f"/api/knowledge-bases/{kb.id}/documents",
        files={"file": ("a.txt", b"hello", "text/plain")},
        headers=auth_header(alice),
    )
    assert resp.status_code == 403


def test_member_can_upload(client, db):
    admin = make_user(db, "root", role="admin")
    alice = make_user(db, "alice")
    kb = make_kb(db, "库A", created_by=admin.id)
    add_member(db, kb.id, alice.id)
    resp = client.post(
        f"/api/knowledge-bases/{kb.id}/documents",
        files={"file": ("a.txt", b"hello", "text/plain")},
        headers=auth_header(alice),
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "pending"

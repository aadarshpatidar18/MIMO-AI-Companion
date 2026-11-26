"""Device identity: hashed tokens, pairing codes, scopes, revocation, the auth gate."""
import sqlite3

import pytest

from backend.core.security import hash_token, new_token, parse_bearer, scopes_for_kind
from backend.core.security.pairing import PairingCodes, SlidingWindowLimiter
from backend.core.security.store import SecurityStore
from backend.tests.conftest import seed_device


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def make_service(tmp_path, clock=None):
    from backend.core.security import SecurityService
    store = SecurityStore(tmp_path / "security.db", clock=clock or Clock())
    return SecurityService(store, codes=PairingCodes(clock=clock or Clock()))


# ---------------------------------------------------------------- tokens in the DB
def test_raw_token_is_never_stored(tmp_path):
    service = make_service(tmp_path)
    result = service.enroll(service.issue_code(), "phone", "android")
    token = result["token"]

    rows = sqlite3.connect(tmp_path / "security.db").execute("SELECT * FROM device_tokens").fetchall()
    blob = repr(rows)
    assert token not in blob                      # plaintext absent
    assert hash_token(token) in blob              # only the hash
    assert token.startswith("mimo_") and len(token) > 40


def test_hash_is_stable_and_tokens_are_unique():
    a, b = new_token(), new_token()
    assert a != b and hash_token(a) != hash_token(b)
    assert len(hash_token(a)) == 64


@pytest.mark.parametrize("header,expected", [
    (None, False),
    ("", False),
    ("Bearer", False),
    ("Token mimo_abc", False),
    ("Bearer short", False),          # no prefix
    ("Bearer mimo_abc", True),
])
def test_parse_bearer(header, expected):
    assert (parse_bearer(header) is not None) is expected


# ---------------------------------------------------------------- pairing
def test_code_is_single_use(tmp_path):
    service = make_service(tmp_path)
    code = service.issue_code()
    service.enroll(code, "phone", "android")
    with pytest.raises(ValueError, match="invalid or has expired"):
        service.enroll(code, "other", "android")


def test_code_expires(tmp_path):
    clock = Clock()
    service = make_service(tmp_path, clock)
    code = service.issue_code()
    clock.advance(601)
    with pytest.raises(ValueError):
        service.enroll(code, "phone", "android")


def test_code_burns_after_repeated_wrong_guesses(tmp_path):
    codes = PairingCodes(max_attempts=3, clock=Clock())
    good = codes.issue()
    for _ in range(4):
        assert codes.redeem("WRONGCODE") is False
    assert codes.redeem(good) is False          # the live code was burned too


def test_new_code_invalidates_the_previous_one(tmp_path):
    service = make_service(tmp_path)
    first = service.issue_code()
    second = service.issue_code()
    with pytest.raises(ValueError):
        service.enroll(first, "phone", "android")
    service.enroll(second, "phone", "android")


def test_pairing_attempts_are_rate_limited(tmp_path):
    service = make_service(tmp_path)
    for _ in range(10):
        with pytest.raises(ValueError):
            service.enroll("BADCODE1", "x", "android", client_key="1.2.3.4")
    with pytest.raises(ValueError, match="too many attempts"):
        service.enroll("BADCODE2", "x", "android", client_key="1.2.3.4")


def test_unknown_device_kind_is_refused(tmp_path):
    service = make_service(tmp_path)
    with pytest.raises(ValueError, match="kind must be"):
        service.enroll(service.issue_code(), "x", "toaster")


# ---------------------------------------------------------------- scopes and revocation
def test_scopes_follow_the_device_kind():
    phone, pc = scopes_for_kind("android"), scopes_for_kind("windows")
    assert "chat:write" in phone and "device:manage" not in phone
    assert "device:manage" in pc
    assert pc > phone


def test_revoked_device_cannot_authenticate(tmp_path):
    service = make_service(tmp_path)
    result = service.enroll(service.issue_code(), "phone", "android")
    token, device_id = result["token"], result["device"]["id"]
    assert service.authenticate(token)["id"] == device_id
    assert service.revoke(device_id) is True
    assert service.authenticate(token) is None
    assert service.revoke(device_id) is False       # already revoked


def test_rotation_invalidates_the_old_token_only_for_that_device(tmp_path):
    service = make_service(tmp_path)
    a = service.enroll(service.issue_code(), "phone", "android")
    b = service.enroll(service.issue_code(), "pc", "windows")
    new = service.rotate(service.store.get_device(a["device"]["id"]), a["token"])["token"]
    assert service.authenticate(a["token"]) is None
    assert service.authenticate(new) is not None
    assert service.authenticate(b["token"]) is not None


def test_rotate_refuses_a_token_that_is_not_live(tmp_path):
    service = make_service(tmp_path)
    a = service.enroll(service.issue_code(), "phone", "android")
    device = service.store.get_device(a["device"]["id"])
    service.revoke(a["device"]["id"])
    with pytest.raises(ValueError):
        service.rotate(device, a["token"])


def test_security_events_are_recorded(tmp_path):
    service = make_service(tmp_path)
    service.enroll(service.issue_code(), "phone", "android")
    with pytest.raises(ValueError):
        service.enroll("BADCODE1", "x", "android")
    kinds = [e["kind"] for e in service.store.list_events()]
    assert "device_enrolled" in kinds and "pair_failed" in kinds


def test_limiter_allows_up_to_the_limit_then_refuses():
    clock = Clock()
    limiter = SlidingWindowLimiter(limit=3, window_s=10, clock=clock)
    assert [limiter.allow("k") for _ in range(3)] == [True, True, True]
    assert limiter.allow("k") is False
    clock.advance(11)
    assert limiter.allow("k") is True


# ---------------------------------------------------------------- HTTP surface
def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_pairing_over_http_yields_a_working_token(app_env):
    client, *_ = app_env
    pc_id, pc_token = seed_device("windows")
    code = client.post("/auth/pair/code", headers=auth(pc_token)).json()["code"]

    r = client.post("/auth/pair", json={"code": code, "name": "Pixel", "kind": "android"})
    assert r.status_code == 200
    token = r.json()["token"]
    assert r.json()["device"]["kind"] == "android"

    me = client.get("/auth/me", headers=auth(token)).json()
    assert me["name"] == "Pixel" and "chat:write" in me["scopes"]
    assert client.get("/auth/me", headers=auth("mimo_nope")).status_code == 401


def test_pairing_code_requires_a_local_or_trusted_caller(app_env):
    client, *_ = app_env
    assert client.post("/auth/pair/code").status_code == 401       # TestClient is not loopback
    android_id, android_token = seed_device("android")
    assert client.post("/auth/pair/code", headers=auth(android_token)).status_code == 403


def test_device_list_and_revoke_respect_scopes(app_env):
    client, *_ = app_env
    pc_id, pc_token = seed_device("windows")
    phone_id, phone_token = seed_device("android")

    listing = client.get("/devices", headers=auth(phone_token))
    assert listing.status_code == 200 and listing.json()["count"] == 2

    assert client.delete(f"/devices/{pc_id}", headers=auth(phone_token)).status_code == 403
    assert client.delete(f"/devices/{pc_id}", headers=auth(pc_token)).status_code == 409  # self
    assert client.delete(f"/devices/{phone_id}", headers=auth(pc_token)).status_code == 200
    assert client.get("/auth/me", headers=auth(phone_token)).status_code == 401

    assert client.get("/devices").status_code == 401
    events = client.get("/security/events", headers=auth(pc_token)).json()["events"]
    assert any(e["kind"] == "device_revoked" for e in events)


def test_rename_device(app_env):
    client, *_ = app_env
    pc_id, pc_token = seed_device("windows")
    r = client.patch(f"/devices/{pc_id}", json={"name": "Aadarsh-PC"}, headers=auth(pc_token))
    assert r.status_code == 200 and r.json()["device"]["name"] == "Aadarsh-PC"


def test_auth_gate_closes_everything_but_health_and_pairing(app_env):
    client, *_ = app_env
    pc_id, pc_token = seed_device("windows")

    client.put("/security/settings", json={"require_auth": True}, headers=auth(pc_token))
    assert client.get("/auth/status").json()["require_auth"] is True

    assert client.get("/health").status_code == 200
    assert client.get("/auth/status").status_code == 200
    assert client.get("/memory").status_code == 401
    assert client.post("/chat", json={"message": "hi"}).status_code == 401
    assert client.get("/agent/tools").status_code == 401

    # A live token opens the same routes.
    assert client.get("/memory", headers=auth(pc_token)).status_code == 200
    assert client.get("/agent/tools", headers=auth(pc_token)).status_code == 200

    events = client.get("/security/events", headers=auth(pc_token)).json()["events"]
    assert sum(1 for e in events if e["kind"] == "auth_rejected") == 3

    client.put("/security/settings", json={"require_auth": False}, headers=auth(pc_token))
    assert client.post("/chat", json={"message": "hi"}).status_code == 200


def test_revocation_takes_effect_on_the_next_request(app_env):
    client, *_ = app_env
    pc_id, pc_token = seed_device("windows")
    phone_id, phone_token = seed_device("android")
    client.put("/security/settings", json={"require_auth": True}, headers=auth(pc_token))

    assert client.get("/memory", headers=auth(phone_token)).status_code == 200
    client.delete(f"/devices/{phone_id}", headers=auth(pc_token))
    assert client.get("/memory", headers=auth(phone_token)).status_code == 401

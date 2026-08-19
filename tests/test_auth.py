"""
ARTHA Terminal — auth core: password hashing, key encryption, sessions, and the
default-deny bearer gate.

These are the tests that have to fail loudly if the security core regresses:

- a password verifies against its own stored scrypt parameters, and a wrong one
  does not;
- a tampered ciphertext RAISES instead of decrypting to something plausible —
  a bit-flipped broker token that came back as garbage would be sent to Upstox;
- an expired session is rejected;
- the database stores only the SHA-256 of a session token, and lookup happens by
  that hash;
- and every route that is not on the three-path allowlist answers 401 without a
  token, including a route invented inside the test — which is the property that
  keeps this true for routes nobody has written yet.
"""

import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Route, WebSocketRoute
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from cryptography.fernet import InvalidToken

import services.auth as auth
from db import get_connection, init_database


@pytest.fixture
def db(tmp_path, monkeypatch):
    """A throwaway database with the real schema, wired into config.db_path.

    services.auth reads config.db_path through get_connection() on every call,
    so this redirects the whole module without touching the live database.
    """
    from config import config
    path = tmp_path / "auth.db"
    init_database(path)
    monkeypatch.setattr(config, "db_path", path)
    return path


@pytest.fixture
def user(db):
    uid = auth.create_user("Trader@Example.com", "correct horse battery staple")
    assert uid is not None
    return uid


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------
def test_scrypt_round_trip_and_wrong_password():
    encoded, salt = auth.hash_password("correct horse battery staple")

    assert encoded.startswith("scrypt$")
    assert auth.verify_password("correct horse battery staple", encoded, salt) is True
    assert auth.verify_password("Correct horse battery staple", encoded, salt) is False
    assert auth.verify_password("", encoded, salt) is False


def test_hash_carries_its_cost_parameters_and_a_unique_salt():
    """Parameters travel with the hash, so raising them later cannot lock an
    existing user out — their row still verifies with the old cost."""
    e1, s1 = auth.hash_password("correct horse battery staple")
    e2, s2 = auth.hash_password("correct horse battery staple")

    algo, n, r, p, _ = e1.split("$")
    assert (algo, int(n), int(r), int(p)) == ("scrypt", auth.SCRYPT_N, auth.SCRYPT_R, auth.SCRYPT_P)
    # Same password, different salt -> different hash. No rainbow table, and
    # two users with the same password are not visibly the same.
    assert s1 != s2 and e1 != e2

    # A hash written with weaker parameters still verifies.
    old = f"scrypt$1024$8$1${auth._scrypt('pw', bytes.fromhex(s1), 1024, 8, 1).hex()}"
    assert auth.verify_password("pw", old, s1) is True


def test_verify_password_never_raises_on_a_broken_row():
    assert auth.verify_password("pw", "not-a-hash", "zz") is False
    assert auth.verify_password("pw", "bcrypt$1$2$3$ff", "ff") is False


def test_password_hash_and_salt_never_leave_get_user(user, db):
    profile = auth.get_user(user)
    assert set(profile) == {"id", "email", "created_at", "last_login_at"}


# ---------------------------------------------------------------------------
# API key encryption
# ---------------------------------------------------------------------------
def test_encrypt_decrypt_round_trip():
    secret = "sk-or-v1-abcdef0123456789"
    blob = auth.encrypt_key(secret)

    assert secret not in blob
    assert auth.decrypt_key(blob) == secret


def test_tampered_ciphertext_raises_rather_than_returning_garbage():
    blob = auth.encrypt_key("upstox-live-token")
    # Flip one character of the base64 payload.
    idx = len(blob) // 2
    tampered = blob[:idx] + ("A" if blob[idx] != "A" else "B") + blob[idx + 1:]

    with pytest.raises(InvalidToken):
        auth.decrypt_key(tampered)


def test_key_stored_encrypted_and_a_bad_row_resolves_to_none(user, db, monkeypatch):
    auth.save_key(user, "GROQ_API_KEY", "gsk-plaintext-value")
    with get_connection() as conn:
        row = conn.execute(
            "SELECT ciphertext FROM user_api_keys WHERE user_id=? AND provider=?",
            (user, "GROQ_API_KEY")).fetchone()
    assert "gsk-plaintext-value" not in row["ciphertext"]
    assert auth.user_key("GROQ_API_KEY", user) == "gsk-plaintext-value"

    # An undecryptable row (wrong ARTHA_SECRET_KEY) must not break the request;
    # it falls through to the .env value.
    with get_connection() as conn:
        conn.execute("UPDATE user_api_keys SET ciphertext='garbage' WHERE user_id=?", (user,))
    monkeypatch.setenv("GROQ_API_KEY", "from-dotenv")
    assert auth.user_key("GROQ_API_KEY", user) is None
    assert auth.resolve_key("GROQ_API_KEY", user) == "from-dotenv"


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------
def test_only_the_token_hash_is_stored_and_lookup_uses_it(user, db):
    import hashlib
    token, _ = auth.create_session(user)

    with get_connection() as conn:
        rows = conn.execute("SELECT token_hash FROM sessions").fetchall()
    stored = [r["token_hash"] for r in rows]

    # A database dump must not yield a usable session.
    assert token not in stored
    assert stored == [hashlib.sha256(token.encode()).hexdigest()]
    assert auth.session_user(token) == user
    assert auth.session_user(token + "x") is None
    assert auth.session_user(None) is None


def test_expired_session_is_rejected_and_removed(user, db):
    token, _ = auth.create_session(user)
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with get_connection() as conn:
        conn.execute("UPDATE sessions SET expires_at=? WHERE user_id=?", (past, user))

    assert auth.session_user(token) is None
    with get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) c FROM sessions").fetchone()["c"] == 0


def test_remember_me_picks_the_long_ttl(user, db):
    _, short = auth.create_session(user, remember=False)
    _, long_ = auth.create_session(user, remember=True)
    now = datetime.now(timezone.utc)

    assert abs((datetime.fromisoformat(short) - now) - auth.SESSION_TTL) < timedelta(minutes=1)
    assert abs((datetime.fromisoformat(long_) - now) - auth.SESSION_TTL_REMEMBER) < timedelta(minutes=1)


def test_logout_deletes_the_session(user, db):
    token, _ = auth.create_session(user)
    auth.delete_session(token)
    assert auth.session_user(token) is None


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
def test_duplicate_email_is_refused_case_insensitively(user, db):
    assert auth.create_user("trader@example.com", "another long password") is None
    assert auth.create_user("TRADER@EXAMPLE.COM", "another long password") is None


def test_short_password_and_bad_email_are_refused(db):
    assert auth.create_user("someone@example.com", "short") is None
    assert auth.create_user("not-an-email", "a long enough password") is None
    assert auth.create_user("someone@example.com", "x" * 5000) is None


def test_authenticate_accepts_the_right_password_only(user, db):
    assert auth.authenticate("trader@example.com", "correct horse battery staple") == user
    assert auth.authenticate("trader@example.com", "wrong password entirely") is None
    assert auth.authenticate("nobody@example.com", "correct horse battery staple") is None


# ---------------------------------------------------------------------------
# Per-user key resolution (config reads this live)
# ---------------------------------------------------------------------------
def test_resolver_prefers_the_user_key_then_env_then_none(user, db, monkeypatch):
    monkeypatch.setenv("SERPAPI_KEY", "env-fallback")
    assert auth.resolve_key("SERPAPI_KEY", user) == "env-fallback"

    auth.save_key(user, "SERPAPI_KEY", "user-key")
    assert auth.resolve_key("SERPAPI_KEY", user) == "user-key"   # no restart

    auth.delete_key(user, "SERPAPI_KEY")
    assert auth.resolve_key("SERPAPI_KEY", user) == "env-fallback"

    monkeypatch.delenv("SERPAPI_KEY")
    assert auth.resolve_key("SERPAPI_KEY", user) is None


def test_config_reads_the_signed_in_users_key_live(user, db, monkeypatch):
    from config import config
    monkeypatch.setattr(config.search, "serpapi_key", "dotenv-value")
    assert config.search.serpapi_key == "dotenv-value"       # no user in context

    auth.save_key(user, "SERPAPI_KEY", "this-users-key")
    ctx = auth.current_user_id.set(user)
    try:
        assert config.search.serpapi_key == "this-users-key"
        auth.delete_key(user, "SERPAPI_KEY")
        assert config.search.serpapi_key == "dotenv-value"   # falls back
    finally:
        auth.current_user_id.reset(ctx)


def test_no_user_in_context_means_env_only(db, monkeypatch):
    """Ingestion and the scheduler run with no signed-in user at all."""
    monkeypatch.setenv("FINNHUB_API_KEY", "scheduler-key")
    assert auth.current_user_id.get() is None
    assert auth.resolve_key("FINNHUB_API_KEY") == "scheduler-key"


# ---------------------------------------------------------------------------
# The bearer gate
# ---------------------------------------------------------------------------
async def _secret(req):
    return JSONResponse({"ok": True, "user_id": req.state.user_id})


async def _ws_secret(ws):
    await ws.accept()
    await ws.close()


def _gated_app():
    from api.server import BearerAuthMiddleware
    return Starlette(routes=[Route("/api/brand-new-route", _secret),
                              WebSocketRoute("/ws/brand-new-route", _ws_secret)],
                     middleware=[Middleware(BearerAuthMiddleware)])


def test_a_route_nobody_exempted_requires_auth(user, db):
    """Default-deny. This route did not exist when the middleware was written,
    which is exactly the case that must not need anyone to remember anything."""
    client = TestClient(_gated_app())

    r = client.get("/api/brand-new-route")
    assert r.status_code == 401
    assert r.json() == {"ok": False, "error": "authentication required"}
    assert r.headers["www-authenticate"] == "Bearer"


def test_garbage_and_malformed_tokens_are_rejected(user, db):
    client = TestClient(_gated_app())
    token, _ = auth.create_session(user)

    for header in ("", "Bearer", "Bearer ", "Basic " + token, token, "Bearer nope"):
        assert client.get("/api/brand-new-route",
                          headers={"Authorization": header}).status_code == 401

    r = client.get("/api/brand-new-route", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200 and r.json()["user_id"] == user


def test_a_valid_token_attaches_the_user_and_logout_revokes_it(user, db):
    client = TestClient(_gated_app())
    token, _ = auth.create_session(user)
    hdr = {"Authorization": f"Bearer {token}"}

    assert client.get("/api/brand-new-route", headers=hdr).json()["user_id"] == user
    auth.delete_session(token)
    assert client.get("/api/brand-new-route", headers=hdr).status_code == 401


def test_every_registered_route_except_the_allowlist_needs_a_token(db):
    """The whole route table, enumerated — not a spot check.

    Nothing is mocked and no handler runs: the gate answers before routing, so
    a 401 here also proves no service, database read or upstream call happens
    for an unauthenticated caller.
    """
    from api.server import app, routes, PUBLIC_PATHS

    client = TestClient(app)   # not a context manager: no lifespan, no ingestion
    checked = 0
    for route in routes:
        if isinstance(route, WebSocketRoute):
            with pytest.raises((WebSocketDisconnect, Exception)):
                with client.websocket_connect(route.path):
                    pass
            checked += 1
            continue
        path = re.sub(r"\{[^}]+\}", "X", route.path)
        methods = route.methods or {"GET"}
        method = next(m for m in ("GET", "POST", "DELETE", "PUT", "PATCH") if m in methods)
        r = client.request(method, path)
        # The gate's own 401 carries this exact error. A public route may still
        # answer 401 for its own reasons (an empty login body is bad
        # credentials), so match the body, not just the status.
        gated = r.status_code == 401 and (r.json() or {}).get("error") == "authentication required"
        if route.path in PUBLIC_PATHS:
            assert not gated, f"{route.path} is on the allowlist but the gate rejected it"
        else:
            assert gated, f"{method} {route.path} answered {r.status_code} {r.text[:80]}, not the gate's 401"
        checked += 1

    assert checked == len(routes) and checked > 40


def test_websocket_auths_off_the_session_cookie(user, db):
    """/ws is reached directly by the browser, not through a Next.js proxy, so
    there is no Authorization header — the WebSocket API cannot set one. The
    session cookie the browser attaches automatically is the only credential
    it can offer."""
    token, _ = auth.create_session(user)
    client = TestClient(_gated_app())

    with pytest.raises((WebSocketDisconnect, Exception)):
        with client.websocket_connect("/ws/brand-new-route"):
            pass  # no cookie, no header -> still rejected

    with client.websocket_connect("/ws/brand-new-route", cookies={"artha_session": token}):
        pass  # cookie alone is enough


def test_the_allowlist_is_exactly_these_six_paths():
    """A new public path is a security decision, not a refactor. If this
    fails, someone widened the hole — read the diff before updating it.

    Six: /api/openapi.json and /api/docs — API documentation is meant to be
    readable before anyone holds a token, and neither touches user data (the
    spec describes route SHAPES, generated from the route table itself; the
    UI is static HTML). /api/auth/test-key — the registration wizard verifies
    a key against its real provider BEFORE an account exists to own it; the
    route stores nothing, so the worst an unauthenticated caller achieves is
    testing a key they already hold. /api/auth/keys, which actually STORES a
    credential, deliberately stays off this list."""
    from api.server import PUBLIC_PATHS
    assert PUBLIC_PATHS == frozenset({
        "/api/health", "/api/auth/register", "/api/auth/login",
        "/api/openapi.json", "/api/docs", "/api/auth/test-key",
    })


def test_register_login_me_logout_round_trip(db):
    from api.server import app

    client = TestClient(app)
    email, password = "roundtrip@example.com", "a sufficiently long password"

    assert client.post("/api/auth/register",
                       json={"email": email, "password": password}).status_code == 201
    # Duplicate: generic message, nothing about the email existing.
    dup = client.post("/api/auth/register", json={"email": email, "password": password})
    assert dup.status_code == 400 and "exist" not in dup.text and email not in dup.text
    # Too short.
    assert client.post("/api/auth/register",
                       json={"email": "b@example.com", "password": "short"}).status_code == 400

    login = client.post("/api/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200
    token = login.json()["token"]
    hdr = {"Authorization": f"Bearer {token}"}

    me = client.get("/api/auth/me", headers=hdr)
    assert me.status_code == 200 and me.json()["user"]["email"] == email
    assert "password" not in me.text and "salt" not in me.text

    assert client.post("/api/auth/logout", headers=hdr).status_code == 200
    assert client.get("/api/auth/me", headers=hdr).status_code == 401

    assert client.post("/api/auth/login",
                       json={"email": email, "password": "wrong password here"}).status_code == 401


def test_login_remember_flag_controls_the_ttl(db):
    from api.server import app

    client = TestClient(app)
    email, password = "ttl@example.com", "a sufficiently long password"
    client.post("/api/auth/register", json={"email": email, "password": password})
    now = datetime.now(timezone.utc)

    short = client.post("/api/auth/login",
                        json={"email": email, "password": password, "remember": False}).json()
    long_ = client.post("/api/auth/login",
                        json={"email": email, "password": password, "remember": True}).json()

    assert abs((datetime.fromisoformat(short["expires_at"]) - now)
               - timedelta(hours=12)) < timedelta(minutes=1)
    assert abs((datetime.fromisoformat(long_["expires_at"]) - now)
               - timedelta(days=30)) < timedelta(minutes=1)
    # The token itself must never appear in a response field other than `token`.
    assert short["token"] != long_["token"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))

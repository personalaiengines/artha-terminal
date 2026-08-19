"""
ARTHA Terminal — authentication, session and per-user credential storage.

Everything security-critical for the portal lives here so there is exactly one
place to audit:

- **Passwords**: `hashlib.scrypt` (memory-hard, stdlib), per-user 16-byte random
  salt, and the COST PARAMETERS ARE STORED WITH THE HASH (`scrypt$n$r$p$hex`).
  Raising the cost later therefore re-hashes nobody out of their account — an
  old row still verifies against the parameters it was written with.
- **Sessions**: `secrets.token_urlsafe(32)`. Only the SHA-256 of the token is
  stored, so a database dump yields no usable session. Comparison is
  `hmac.compare_digest`, never `==`.
- **API keys**: Fernet (AES-128-CBC + HMAC), keyed off `ARTHA_SECRET_KEY`.
  Authenticated encryption matters here: these are live broker credentials, and
  a tampered ciphertext must raise rather than decrypt to something plausible.

Nothing in this module logs, prints or puts into an exception message a
password, a raw token or a decrypted key. Failures are reported as booleans and
`None`s; the provider NAME (e.g. "GROQ_API_KEY") is the most that ever reaches a
log line.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import re
import secrets
import sqlite3
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet, InvalidToken

from db import get_connection

log = logging.getLogger("services.auth")

# ---------------------------------------------------------------------------
# Master key — required, never generated
# ---------------------------------------------------------------------------
# Auto-generating this would be the worst kind of convenience: the container
# would come up fine, encrypt a user's Upstox and AI keys with an ephemeral
# key, and the next restart would make every one of them permanently
# undecryptable with no error at all. Refusing to start is the loud failure.
_SECRET = (os.getenv("ARTHA_SECRET_KEY") or "").strip()
_MIN_SECRET_LEN = 16

if len(_SECRET) < _MIN_SECRET_LEN:
    raise RuntimeError(
        "ARTHA_SECRET_KEY is not set (or is shorter than "
        f"{_MIN_SECRET_LEN} characters).\n"
        "It encrypts every stored API key. ARTHA will not invent one: a "
        "generated key would be lost on the next restart and every saved "
        "credential would become permanently undecryptable.\n"
        "Generate one and add it to your .env:\n"
        '    python -c "import secrets; print(secrets.token_urlsafe(48))"\n'
        "    ARTHA_SECRET_KEY=<paste the value here>"
    )

# Fernet needs a 32-byte urlsafe-base64 key; ARTHA_SECRET_KEY is free-form text.
# SHA-256 over a domain-separated label so the same secret could key something
# else later without the two sharing key material.
_FERNET = Fernet(base64.urlsafe_b64encode(
    hashlib.sha256(b"artha:user_api_keys:v1:" + _SECRET.encode()).digest()))


def encrypt_key(plaintext: str) -> str:
    """Ciphertext for storage. Fernet is authenticated — see `decrypt_key`."""
    return _FERNET.encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_key(ciphertext: str) -> str:
    """Plaintext, or raise `cryptography.fernet.InvalidToken`.

    Raising on a tampered or wrong-key ciphertext is the point of using an
    authenticated cipher: a bit-flipped broker token that decrypted to garbage
    would be sent to Upstox as if it were real.
    """
    return _FERNET.decrypt(ciphertext.encode("ascii")).decode("utf-8")


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------
# Cost parameters. Raise them freely: every stored hash carries the parameters
# it was created with, so old rows keep verifying.
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1
_DKLEN = 32

MIN_PASSWORD_LENGTH = 12
# scrypt's cost is paid by this process, so an unbounded password is a free DoS
# on the login route. No human types 1024 characters.
MAX_PASSWORD_LENGTH = 1024

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
MAX_EMAIL_LENGTH = 254


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    # maxmem is derived from the parameters rather than fixed, so raising N/R
    # later does not start failing with "memory limit exceeded".
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p,
                          dklen=_DKLEN, maxmem=128 * n * r * 2 + (1 << 20))


def hash_password(password: str) -> tuple[str, str]:
    """-> (encoded_hash, salt_hex). `encoded_hash` is `scrypt$n$r$p$<hex>`."""
    salt = secrets.token_bytes(16)
    dk = _scrypt(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${dk.hex()}", salt.hex()


def verify_password(password: str, encoded: str, salt_hex: str) -> bool:
    """Constant-time check against a stored hash, using ITS parameters.

    Returns False for a malformed row rather than raising: an exception here
    would travel up into a log line carrying the caller's arguments.
    """
    try:
        algo, n, r, p, dk_hex = encoded.split("$")
        if algo != "scrypt":
            return False
        dk = _scrypt(password, bytes.fromhex(salt_hex), int(n), int(r), int(p))
    except Exception:
        return False
    return hmac.compare_digest(dk.hex(), dk_hex)


# A throwaway hash with the live parameters, computed once at import. Login for
# an unknown email verifies against THIS, so the endpoint costs the same whether
# the email exists or not and cannot be used to enumerate accounts.
_DUMMY_HASH, _DUMMY_SALT = hash_password(secrets.token_urlsafe(16))


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def create_user(email: str, password: str) -> int | None:
    """New user id, or None if the email is taken or the input is unusable.

    A single None for both cases is deliberate — the register route must not
    tell an anonymous caller which emails are already registered.
    """
    email = normalize_email(email)
    if not EMAIL_RE.match(email) or len(email) > MAX_EMAIL_LENGTH:
        return None
    if not (MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH):
        return None
    encoded, salt = hash_password(password)
    try:
        with get_connection() as conn:
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, salt, created_at) VALUES (?,?,?,?)",
                (email, encoded, salt, _now().isoformat()))
            return cur.lastrowid
    except sqlite3.IntegrityError:
        return None


def authenticate(email: str, password: str) -> int | None:
    """User id on a correct email+password, else None.

    Runs the same scrypt work for an unknown email as for a known one (against
    `_DUMMY_HASH`), so response time does not reveal which emails exist.
    """
    email = normalize_email(email)
    if len(password) > MAX_PASSWORD_LENGTH:
        return None
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, password_hash, salt FROM users WHERE email = ?", (email,)).fetchone()
    if row is None:
        verify_password(password, _DUMMY_HASH, _DUMMY_SALT)
        return None
    if not verify_password(password, row["password_hash"], row["salt"]):
        return None
    with get_connection() as conn:
        conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?",
                     (_now().isoformat(), row["id"]))
    return row["id"]


def get_user(user_id: int) -> dict | None:
    """Public profile fields only — never the hash or the salt."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, email, created_at, last_login_at FROM users WHERE id = ?",
            (user_id,)).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------
# "Remember me" is exactly this: which of the two TTLs the row gets.
SESSION_TTL = timedelta(hours=12)
SESSION_TTL_REMEMBER = timedelta(days=30)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(user_id: int, remember: bool = False,
                   user_agent: str | None = None) -> tuple[str, str]:
    """-> (raw_token, expires_at_iso). The raw token is returned to the caller
    ONCE and never stored — only its SHA-256 goes to the database."""
    token = secrets.token_urlsafe(32)
    expires = _now() + (SESSION_TTL_REMEMBER if remember else SESSION_TTL)
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at, user_agent) "
            "VALUES (?,?,?,?,?)",
            (_token_hash(token), user_id, _now().isoformat(), expires.isoformat(),
             (user_agent or "")[:200] or None))
    return token, expires.isoformat()


def session_user(token: str | None) -> int | None:
    """User id for a live session token, else None (unknown or expired).

    Expiry is compared in Python, not SQL: SQLite's `datetime('now')` format
    ('2026-08-09 10:00:00') does not string-compare correctly against the
    timezone-aware ISO values written above, and a wrong comparison here would
    silently accept expired sessions.
    """
    if not token:
        return None
    digest = _token_hash(token)
    with get_connection() as conn:
        row = conn.execute(
            "SELECT token_hash, user_id, expires_at FROM sessions WHERE token_hash = ?",
            (digest,)).fetchone()
    if row is None or not hmac.compare_digest(row["token_hash"], digest):
        return None
    try:
        if datetime.fromisoformat(row["expires_at"]) <= _now():
            delete_session(token)
            return None
    except ValueError:
        return None
    return row["user_id"]


def delete_session(token: str | None) -> None:
    if not token:
        return
    with get_connection() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))


def list_sessions(user_id: int, current_token: str | None = None) -> list[dict]:
    """Every live session for this user — the device list Settings shows.

    Never returns the token or its hash: `token_hash` is what a stolen row
    would need to impersonate a session, so it has no reason to leave this
    module. `current` marks which row the caller is looking at right now, so
    the UI can label it and refuse to let it be revoked from the list (that is
    what the sign-out button is for).
    """
    current_hash = _token_hash(current_token) if current_token else None
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT token_hash, created_at, expires_at, user_agent FROM sessions "
            "WHERE user_id = ? ORDER BY created_at DESC", (user_id,)).fetchall()
    return [
        {"created_at": r["created_at"], "expires_at": r["expires_at"],
         "user_agent": r["user_agent"],
         "current": current_hash is not None and hmac.compare_digest(r["token_hash"], current_hash)}
        for r in rows
    ]


def delete_other_sessions(user_id: int, keep_token: str | None) -> int:
    """Revoke every session for this user except the one making the request.
    Returns the count revoked. `keep_token` absent means keep nothing."""
    keep_hash = _token_hash(keep_token) if keep_token else None
    with get_connection() as conn:
        if keep_hash:
            cur = conn.execute(
                "DELETE FROM sessions WHERE user_id = ? AND token_hash != ?",
                (user_id, keep_hash))
        else:
            cur = conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        return cur.rowcount


# ---------------------------------------------------------------------------
# Per-user API keys
# ---------------------------------------------------------------------------
# The `provider` column IS the environment variable name ("GROQ_API_KEY",
# "UPSTOX_ANALYTICS_TOKEN"). One vocabulary for the stored key and its .env
# fallback means no mapping table to drift out of sync.
current_user_id: ContextVar[int | None] = ContextVar("artha_user_id", default=None)


def save_key(user_id: int, provider: str, value: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO user_api_keys (user_id, provider, ciphertext, updated_at) "
            "VALUES (?,?,?,?) ON CONFLICT(user_id, provider) DO UPDATE SET "
            "ciphertext = excluded.ciphertext, updated_at = excluded.updated_at",
            (user_id, provider, encrypt_key(value), _now().isoformat()))


def delete_key(user_id: int, provider: str) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM user_api_keys WHERE user_id = ? AND provider = ?",
                     (user_id, provider))


def user_key(provider: str, user_id: int | None = None) -> str | None:
    """This user's stored value for `provider`, or None.

    Read on every access with no caching, which is what "a key saved in Settings
    works on the next request, no restart" requires.
    ponytail: one indexed SQLite row read per credential access. Add a per-user
    dict invalidated by save_key/delete_key if a profiler ever shows it.
    """
    uid = user_id if user_id is not None else current_user_id.get()
    if uid is None:
        return None
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT ciphertext FROM user_api_keys WHERE user_id = ? AND provider = ?",
                (uid, provider)).fetchone()
    except sqlite3.Error:
        # Missing table on a not-yet-migrated database: fall back to .env rather
        # than failing every request that reads a credential.
        return None
    if row is None:
        return None
    try:
        return decrypt_key(row["ciphertext"]) or None
    except InvalidToken:
        # Provider name only — never the ciphertext, never a partial plaintext.
        log.error("stored credential %r for user %s could not be decrypted "
                  "(ARTHA_SECRET_KEY changed?)", provider, uid)
        return None


def resolve_key(provider: str, user_id: int | None = None) -> str | None:
    """The credential to use right now: user's stored key -> .env -> None.

    The .env fallback is required, not laziness: ingestion and the scheduler run
    with no signed-in user at all.
    """
    return user_key(provider, user_id) or os.getenv(provider) or None


def list_key_providers(user_id: int) -> list[str]:
    """Which providers this user has stored. Names only — values never leave."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT provider FROM user_api_keys WHERE user_id = ? ORDER BY provider",
            (user_id,)).fetchall()
    return [r["provider"] for r in rows]

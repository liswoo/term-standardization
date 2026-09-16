"""Password hashing + session helpers for real login/signup/roles. Stdlib-only
(no new pip dependency) - PBKDF2-HMAC-SHA256, consistent with this project's
existing use of raw hashlib.sha256 elsewhere (db.py's catalog_fingerprint).
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from starlette.responses import JSONResponse
from . import db

PBKDF2_ITERATIONS = 390_000  # OWASP 2023 minimum recommendation for PBKDF2-SHA256
SESSION_COOKIE_NAME = "session_token"
SESSION_TTL = timedelta(days=7)

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"{PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"

def verify_password(password: str, stored: str) -> bool:
    try:
        iterations_str, salt_hex, hash_hex = stored.split("$")
        salt, expected = bytes.fromhex(salt_hex), bytes.fromhex(hash_hex)
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations_str))
    except (ValueError, AttributeError):
        return False
    return secrets.compare_digest(candidate, expected)

def create_session(user_id) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + SESSION_TTL
    with db.connect() as conn:
        conn.execute("INSERT INTO sessions(token,user_id,expires_at) VALUES(%s,%s,%s)", (token, user_id, expires_at))
    return token

def delete_session(token) -> None:
    with db.connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token=%s", (token,))

def get_session_user(request):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    with db.connect() as conn:
        return conn.execute("""SELECT u.id,u.username,u.display_name,u.team,u.role,u.status
            FROM sessions s JOIN users u ON u.id=s.user_id
            WHERE s.token=%s AND s.expires_at>now()""", (token,)).fetchone()

def require_auth(request):
    """Returns (user, None) on success, or (None, JSONResponse) to return immediately."""
    user = get_session_user(request)
    if not user:
        return None, JSONResponse({"ok": False, "error": "AUTH_REQUIRED"}, status_code=401)
    if user["status"] != "ACTIVE":
        return None, JSONResponse({"ok": False, "error": "ACCOUNT_NOT_ACTIVE"}, status_code=403)
    return user, None

def require_admin(request):
    user, error = require_auth(request)
    if error:
        return None, error
    if user["role"] != "ADMIN":
        return None, JSONResponse({"ok": False, "error": "ADMIN_REQUIRED"}, status_code=403)
    return user, None

def active_admin_count(conn, excluding=None) -> int:
    """How many ACTIVE ADMIN users exist, optionally excluding one user_id - used
    to refuse an action that would leave the system with zero usable admins."""
    if excluding:
        row = conn.execute("SELECT count(*) AS n FROM users WHERE role='ADMIN' AND status='ACTIVE' AND id<>%s",
            (excluding,)).fetchone()
    else:
        row = conn.execute("SELECT count(*) AS n FROM users WHERE role='ADMIN' AND status='ACTIVE'").fetchone()
    return row["n"]

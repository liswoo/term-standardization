"""Local-only admin HTTP routes: the Settings-screen LLM provider switch, plus
real login/signup/session/role auth (term_service/auth.py). Plain REST
endpoints on the same server.py process (port 8100), proxied by Caddy at
/admin/* so the browser can call them same-origin (cookies included
automatically - no per-call Authorization header needed on this frontend).

/admin/auth/signup and /admin/auth/login are necessarily unauthenticated
(that's the point of them) - every other route below requires require_auth
or require_admin from term_service/auth.py.
"""
import asyncio
import subprocess
import sys
import uuid
from pathlib import Path
import psycopg
from starlette.requests import Request
from starlette.responses import JSONResponse
from .tools import mcp
from . import db
from .credentials import active_provider, set_active_provider, llm_configured
from .auth import (hash_password, verify_password, create_session, delete_session,
    require_auth, require_admin, active_admin_count, SESSION_COOKIE_NAME, SESSION_TTL)

ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable  # this same .venv's interpreter

def _redeploy_chatflow():
    """Rebuild/import/publish the Dify chatflow so its intent/reply nodes pick
    up whatever provider build_chatflow.py's active_provider() reads at import
    time. Mirrors CLAUDE.md's mandatory 3-step deploy - skipping a step would
    silently redeploy a stale draft (see CLAUDE.md's own warning about that)."""
    steps = (["build_chatflow.py"], ["dify_admin.py", "import", "dify-chatflow.yaml"],
        ["scripts/publish_chatflow.py"])
    for args in steps:
        result = subprocess.run([PYTHON, *args], cwd=ROOT, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise RuntimeError(f"{args[0]} failed: {result.stderr[-2000:]}")

@mcp.custom_route("/admin/llm-status", methods=["GET"])
async def llm_status(request: Request) -> JSONResponse:
    _, error = require_auth(request)  # any logged-in user - provider name/bool isn't sensitive
    if error: return error
    return JSONResponse({"provider": active_provider(), "configured": llm_configured()})

@mcp.custom_route("/admin/llm-provider", methods=["POST"])
async def switch_llm_provider(request: Request) -> JSONResponse:
    _, error = require_admin(request)  # mutating config change - ADMIN only
    if error: return error
    body = await request.json()
    provider = body.get("provider")
    if provider not in ("openai", "local"):
        return JSONResponse({"ok": False, "error": "provider must be 'openai' or 'local'"}, status_code=400)
    set_active_provider(provider)
    try:
        # Rebuilding/publishing the Dify app is a docker exec + HTTP round trip
        # taking several seconds - run off the event loop so it doesn't block
        # other requests to this server while it's in flight.
        await asyncio.to_thread(_redeploy_chatflow)
    except Exception as error:
        return JSONResponse({"ok": False, "provider": active_provider(), "error": str(error)}, status_code=502)
    return JSONResponse({"ok": True, "provider": active_provider(), "configured": llm_configured()})

# ── 로그인 / 회원가입 / 세션 ──────────────────────────────────────

@mcp.custom_route("/admin/auth/signup", methods=["POST"])
async def auth_signup(request: Request) -> JSONResponse:
    body = await request.json()
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    display_name = (body.get("display_name") or "").strip()
    team = (body.get("team") or "").strip()
    if not username or not password or not display_name:
        return JSONResponse({"ok": False, "error": "MISSING_FIELDS"}, status_code=400)
    if len(password) < 8:
        return JSONResponse({"ok": False, "error": "PASSWORD_TOO_SHORT"}, status_code=400)
    try:
        with db.connect() as conn:
            conn.execute("""INSERT INTO users(id,username,password_hash,display_name,team,role,status)
                VALUES(%s,%s,%s,%s,%s,'MEMBER','PENDING_APPROVAL')""",
                (str(uuid.uuid4()), username, hash_password(password), display_name, team))
    except psycopg.errors.UniqueViolation:
        return JSONResponse({"ok": False, "error": "USERNAME_TAKEN"}, status_code=409)
    return JSONResponse({"ok": True, "status": "PENDING_APPROVAL"})

@mcp.custom_route("/admin/auth/login", methods=["POST"])
async def auth_login(request: Request) -> JSONResponse:
    body = await request.json()
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    with db.connect() as conn:
        user = conn.execute("SELECT * FROM users WHERE username=%s", (username,)).fetchone()
    if not user or not verify_password(password, user["password_hash"]):
        return JSONResponse({"ok": False, "error": "INVALID_CREDENTIALS"}, status_code=401)
    if user["status"] != "ACTIVE":
        return JSONResponse({"ok": False, "error": "ACCOUNT_NOT_ACTIVE", "status": user["status"]}, status_code=403)
    token = create_session(user["id"])
    response = JSONResponse({"ok": True, "user": {
        "username": user["username"], "display_name": user["display_name"],
        "team": user["team"], "role": user["role"]}})
    response.set_cookie(SESSION_COOKIE_NAME, token, httponly=True, samesite="lax",
        max_age=int(SESSION_TTL.total_seconds()), path="/")
    return response

@mcp.custom_route("/admin/auth/logout", methods=["POST"])
async def auth_logout(request: Request) -> JSONResponse:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        delete_session(token)
    response = JSONResponse({"ok": True})
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return response

@mcp.custom_route("/admin/auth/me", methods=["GET"])
async def auth_me(request: Request) -> JSONResponse:
    user, error = require_auth(request)
    if error:
        return JSONResponse({"ok": False, "error": "NOT_LOGGED_IN"}, status_code=401)
    return JSONResponse({"ok": True, "user": {
        "username": user["username"], "display_name": user["display_name"],
        "team": user["team"], "role": user["role"]}})

@mcp.custom_route("/admin/auth/change-password", methods=["POST"])
async def auth_change_password(request: Request) -> JSONResponse:
    user, error = require_auth(request)
    if error: return error
    body = await request.json()
    current_password = body.get("current_password") or ""
    new_password = body.get("new_password") or ""
    with db.connect() as conn:
        row = conn.execute("SELECT password_hash FROM users WHERE id=%s", (user["id"],)).fetchone()
    if not verify_password(current_password, row["password_hash"]):
        return JSONResponse({"ok": False, "error": "CURRENT_PASSWORD_INCORRECT"}, status_code=401)
    if len(new_password) < 8:
        return JSONResponse({"ok": False, "error": "PASSWORD_TOO_SHORT"}, status_code=400)
    current_token = request.cookies.get(SESSION_COOKIE_NAME)
    with db.connect() as conn:
        conn.execute("UPDATE users SET password_hash=%s,updated_at=now() WHERE id=%s",
            (hash_password(new_password), user["id"]))
        # Log out every other session on a password change (a stolen/shared old
        # session shouldn't survive it) - keep only the one making this request.
        conn.execute("DELETE FROM sessions WHERE user_id=%s AND token<>%s", (user["id"], current_token))
    return JSONResponse({"ok": True})

# ── 회원 관리 (ADMIN 전용) ────────────────────────────────────────

@mcp.custom_route("/admin/auth/members", methods=["GET"])
async def auth_members(request: Request) -> JSONResponse:
    _, error = require_admin(request)
    if error: return error
    with db.connect() as conn:
        rows = conn.execute("""SELECT id,username,display_name,team,role,status,created_at
            FROM users ORDER BY
            CASE status WHEN 'PENDING_APPROVAL' THEN 0 WHEN 'ACTIVE' THEN 1 WHEN 'SUSPENDED' THEN 2 ELSE 3 END,
            created_at""").fetchall()
    for r in rows:
        r["id"] = str(r["id"]); r["created_at"] = r["created_at"].isoformat()
    return JSONResponse({"ok": True, "users": rows})

@mcp.custom_route("/admin/auth/approve-user", methods=["POST"])
async def auth_approve_user(request: Request) -> JSONResponse:
    _, error = require_admin(request)
    if error: return error
    body = await request.json()
    with db.connect() as conn:
        row = conn.execute("""UPDATE users SET status='ACTIVE',updated_at=now()
            WHERE id=%s AND status IN ('PENDING_APPROVAL','REJECTED') RETURNING id""",
            (body.get("user_id"),)).fetchone()
    if not row:
        return JSONResponse({"ok": False, "error": "USER_NOT_FOUND_OR_NOT_ELIGIBLE"}, status_code=404)
    return JSONResponse({"ok": True})

@mcp.custom_route("/admin/auth/reject-user", methods=["POST"])
async def auth_reject_user(request: Request) -> JSONResponse:
    _, error = require_admin(request)
    if error: return error
    body = await request.json()
    with db.connect() as conn:
        row = conn.execute("""UPDATE users SET status='REJECTED',updated_at=now()
            WHERE id=%s AND status='PENDING_APPROVAL' RETURNING id""", (body.get("user_id"),)).fetchone()
    if not row:
        return JSONResponse({"ok": False, "error": "USER_NOT_FOUND_OR_NOT_PENDING"}, status_code=404)
    return JSONResponse({"ok": True})

@mcp.custom_route("/admin/auth/suspend-user", methods=["POST"])
async def auth_suspend_user(request: Request) -> JSONResponse:
    _, error = require_admin(request)
    if error: return error
    body = await request.json()
    user_id = body.get("user_id")
    with db.connect() as conn:
        target = conn.execute("SELECT role,status FROM users WHERE id=%s", (user_id,)).fetchone()
        if not target or target["status"] != "ACTIVE":
            return JSONResponse({"ok": False, "error": "USER_NOT_FOUND_OR_NOT_ACTIVE"}, status_code=404)
        if target["role"] == "ADMIN" and active_admin_count(conn, excluding=user_id) == 0:
            return JSONResponse({"ok": False, "error": "LAST_ADMIN_CANNOT_BE_SUSPENDED"}, status_code=409)
        conn.execute("UPDATE users SET status='SUSPENDED',updated_at=now() WHERE id=%s", (user_id,))
    return JSONResponse({"ok": True})

@mcp.custom_route("/admin/auth/reactivate-user", methods=["POST"])
async def auth_reactivate_user(request: Request) -> JSONResponse:
    _, error = require_admin(request)
    if error: return error
    body = await request.json()
    with db.connect() as conn:
        row = conn.execute("""UPDATE users SET status='ACTIVE',updated_at=now()
            WHERE id=%s AND status='SUSPENDED' RETURNING id""", (body.get("user_id"),)).fetchone()
    if not row:
        return JSONResponse({"ok": False, "error": "USER_NOT_FOUND_OR_NOT_SUSPENDED"}, status_code=404)
    return JSONResponse({"ok": True})

@mcp.custom_route("/admin/auth/set-role", methods=["POST"])
async def auth_set_role(request: Request) -> JSONResponse:
    _, error = require_admin(request)
    if error: return error
    body = await request.json()
    user_id, role = body.get("user_id"), body.get("role")
    if role not in ("ADMIN", "MEMBER"):
        return JSONResponse({"ok": False, "error": "INVALID_ROLE"}, status_code=400)
    with db.connect() as conn:
        target = conn.execute("SELECT role,status FROM users WHERE id=%s", (user_id,)).fetchone()
        if not target or target["status"] != "ACTIVE":
            return JSONResponse({"ok": False, "error": "USER_NOT_FOUND_OR_NOT_ACTIVE"}, status_code=404)
        if target["role"] == "ADMIN" and role == "MEMBER" and active_admin_count(conn, excluding=user_id) == 0:
            return JSONResponse({"ok": False, "error": "LAST_ADMIN_CANNOT_BE_DEMOTED"}, status_code=409)
        conn.execute("UPDATE users SET role=%s,updated_at=now() WHERE id=%s", (role, user_id))
    return JSONResponse({"ok": True})

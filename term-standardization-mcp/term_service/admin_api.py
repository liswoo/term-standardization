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

# ── 도메인 신청 (버튼 기반 직접 폼, 챗봇 아님) ────────────────────────────
# registration.py/word_registration.py의 prepare()/submit() 2단계를 그대로
# 쓰지만, 대화 여러 턴에 걸쳐 딴 데 갔다 올 사용자가 없는 단일 폼 제출이라
# 한 요청 안에서 이어서 호출한다(domain_registration.py 자체는 그 두 함수를
# 그대로 유지 - 나중에 정말 다단계가 필요해지면 이 라우트만 바꾸면 됨).
_DOMAIN_REQUEST_ERROR_STATUS = {
    "CODE_ALREADY_EXISTS": 409, "PENDING_REQUEST_ALREADY_EXISTS": 409,
    "CATALOG_CHANGED_RETRY": 409, "CATALOG_CHANGED_REVALIDATE": 409,
    "DOMAIN_CODE_ALREADY_EXISTS": 409,
}

@mcp.custom_route("/admin/domain-requests", methods=["POST"])
async def create_domain_request(request: Request) -> JSONResponse:
    from pydantic import ValidationError
    from . import domain_registration
    from .schemas import DomainRequestInput
    user, error = require_auth(request)
    if error: return error
    body = await request.json()
    try:
        payload = DomainRequestInput(**{**body, "requester": user["username"], "conversation_id": "direct-form"})
    except ValidationError as exc:
        return JSONResponse({"ok": False, "error": "INVALID_FIELDS", "detail": exc.errors()}, status_code=400)
    prep = domain_registration.prepare(payload)
    if not prep["ready"]:
        # domain_registration.py uses "code" as its failure-identifier key (matching
        # registration.py/word_registration.py's convention), but every other route in
        # this file uses "error" for the frontend's submitAuthForm()/AUTH_ERROR_LABELS
        # lookup - translate here rather than making the frontend understand two keys.
        return JSONResponse({"ok": False, "error": prep["code"], **prep},
            status_code=_DOMAIN_REQUEST_ERROR_STATUS.get(prep["code"], 400))
    result = domain_registration.submit(prep["confirmation_id"], user["username"], "direct-form", confirmed=True)
    if not result["created"]:
        return JSONResponse({"ok": False, "error": result.get("code"), **result},
            status_code=_DOMAIN_REQUEST_ERROR_STATUS.get(result.get("code"), 409))
    return JSONResponse({"ok": True, **result})

@mcp.custom_route("/admin/domain-requests", methods=["GET"])
async def list_own_domain_requests(request: Request) -> JSONResponse:
    user, error = require_auth(request)
    if error: return error
    with db.connect() as conn:
        rows = conn.execute("""SELECT id::text AS request_id,code,domain_group,data_type,status,created_at
            FROM domain_requests WHERE requester=%s ORDER BY created_at DESC""", (user["username"],)).fetchall()
    for r in rows: r["created_at"] = r["created_at"].isoformat()
    return JSONResponse({"ok": True, "requests": rows})

@mcp.custom_route("/admin/domain-requests/options", methods=["GET"])
async def domain_request_options(request: Request) -> JSONResponse:
    _, error = require_auth(request)
    if error: return error
    with db.connect() as conn:
        groups = [r["domain_group"] for r in conn.execute(
            "SELECT DISTINCT domain_group FROM domains WHERE domain_group<>'' ORDER BY domain_group").fetchall()]
        types = [r["data_type"] for r in conn.execute(
            "SELECT DISTINCT data_type FROM domains WHERE data_type IS NOT NULL AND data_type<>'' ORDER BY data_type").fetchall()]
    return JSONResponse({"ok": True, "domain_groups": groups, "data_types": types})

@mcp.custom_route("/admin/mock-tables", methods=["GET"])
async def list_mock_tables(request: Request) -> JSONResponse:
    _, error = require_auth(request)
    if error: return error
    from .mock_operations import ALLOWLISTED_MOCKOPS_TABLES
    return JSONResponse({"ok": True, "tables": ALLOWLISTED_MOCKOPS_TABLES})

@mcp.custom_route("/admin/domains/{code}/sample-data", methods=["GET"])
async def domain_sample_data(request: Request) -> JSONResponse:
    _, error = require_auth(request)
    if error: return error
    from .mock_operations import sample_data_for_domain
    return JSONResponse({"ok": True, "results": sample_data_for_domain(request.path_params["code"])})
    return JSONResponse({"ok": True})

# 허용값/표현형식/저장형식처럼 "도메인이 결정하는" 값은 용어 신청 폼에 직접 입력받지
# 않고(2026-09-18), 도메인 선택 시 이 라우트로 조회해서 참고용으로 보여준다. 챗봇의
# 등록완료 카드도 같은 라우트로 도메인 상세를 가져와 붙인다(registration.submit()이
# 반환하는 domain은 코드뿐이라 별도 조회가 필요).
@mcp.custom_route("/admin/domains/{code}", methods=["GET"])
async def get_domain_detail(request: Request) -> JSONResponse:
    _, error = require_auth(request)
    if error: return error
    with db.connect() as conn:
        row = conn.execute("""SELECT code,description,domain_group,domain_classification,data_type,
            data_length,decimal_length,storage_format,display_format,unit,valid_values,status
            FROM domains WHERE code=%s""", (request.path_params["code"],)).fetchone()
    if not row:
        return JSONResponse({"ok": False, "error": "DOMAIN_NOT_FOUND"}, status_code=404)
    return JSONResponse({"ok": True, "domain": row})

# ── 용어/단어 신청 (표준 데이터 조회 화면의 "용어 신청"/"단어 신청" 탭, 간편 입력) ──
# 도메인 신청과 같은 이유로 prepare()+submit()을 한 요청 안에서 이어서 호출한다.
# 단어는 word_registration.py를 그대로 씀(exact-match만 확인하므로 도메인과 동급으로
# 간단함). 용어는 quick_registration.prepare_term()이 단어 gap 체크만 얹어서
# registration.py의 prepare()/submit()을 그대로 위임 - 임베딩+LLM 의미비교는 챗봇
# 경로와 동일하게 실행되므로 응답이 도메인/단어보다 느릴 수 있다(수 초).
_TERM_QUICK_ERROR_STATUS = {
    "GUIDELINE_VIOLATION": 422, "EXACT_MATCH": 409, "SYNONYM_CONFLICT": 409,
    "SAME_MEANING": 409, "WORD_GAP_REQUIRES_REGISTRATION": 422,
    "CATALOG_CHANGED_RETRY": 409, "CATALOG_CHANGED_REVALIDATE": 409,
    "PENDING_REQUEST_ALREADY_EXISTS": 409,
}

@mcp.custom_route("/admin/term-requests", methods=["POST"])
async def create_term_request(request: Request) -> JSONResponse:
    from pydantic import ValidationError
    from . import quick_registration, registration
    from .schemas import RegistrationInput
    user, error = require_auth(request)
    if error: return error
    body = await request.json()
    english_abbr = (body.pop("english_abbr", "") or "").strip()[:20]
    try:
        payload = RegistrationInput(**{**body, "requester": user["username"], "conversation_id": "direct-form"})
    except ValidationError as exc:
        return JSONResponse({"ok": False, "error": "INVALID_FIELDS", "detail": exc.errors()}, status_code=400)
    prep = quick_registration.prepare_term(payload)
    if not prep["ready"]:
        return JSONResponse({"ok": False, "error": prep.get("code"), **prep},
            status_code=_TERM_QUICK_ERROR_STATUS.get(prep.get("code"), 400))
    result = registration.submit(prep["confirmation_id"], user["username"], "direct-form",
        confirmed=True, english_abbr=english_abbr)
    if not result["created"]:
        return JSONResponse({"ok": False, "error": result.get("code"), **result},
            status_code=_TERM_QUICK_ERROR_STATUS.get(result.get("code"), 409))
    return JSONResponse({"ok": True, **result})

_WORD_QUICK_ERROR_STATUS = {
    "EXACT_MATCH": 409, "ABBREVIATION_ALREADY_USED": 409,
    "CATALOG_CHANGED_RETRY": 409, "CATALOG_CHANGED_REVALIDATE": 409,
    "PENDING_REQUEST_ALREADY_EXISTS": 409,
}

@mcp.custom_route("/admin/word-requests", methods=["POST"])
async def create_word_request(request: Request) -> JSONResponse:
    from pydantic import ValidationError
    from . import word_registration
    from .schemas import WordRegistrationInput
    user, error = require_auth(request)
    if error: return error
    body = await request.json()
    try:
        payload = WordRegistrationInput(**{**body, "requester": user["username"], "conversation_id": "direct-form"})
    except ValidationError as exc:
        return JSONResponse({"ok": False, "error": "INVALID_FIELDS", "detail": exc.errors()}, status_code=400)
    prep = word_registration.prepare(payload)
    if not prep["ready"]:
        return JSONResponse({"ok": False, "error": prep.get("code"), **prep},
            status_code=_WORD_QUICK_ERROR_STATUS.get(prep.get("code"), 400))
    result = word_registration.submit(prep["confirmation_id"], user["username"], "direct-form", confirmed=True)
    if not result["created"]:
        return JSONResponse({"ok": False, "error": result.get("code"), **result},
            status_code=_WORD_QUICK_ERROR_STATUS.get(result.get("code"), 409))
    return JSONResponse({"ok": True, **result})

# ── 표준 데이터 조회 (용어/단어/도메인 통합 화면) ──────────────────────────
@mcp.custom_route("/admin/standard-data", methods=["GET"])
async def list_standard_data_catalog(request: Request) -> JSONResponse:
    _, error = require_auth(request)
    if error: return error
    from . import unified_catalog
    qp = request.query_params
    kinds = [k for k in qp.get("kinds", "").split(",") if k]
    try:
        limit = int(qp.get("limit", "50"))
        offset = int(qp.get("offset", "0"))
    except ValueError:
        return JSONResponse({"ok": False, "error": "INVALID_FIELDS"}, status_code=400)
    result = unified_catalog.list_standard_data(kinds, qp.get("q", ""), qp.get("status", ""), limit, offset)
    for r in result["items"]:
        if r.get("created_at"):
            r["created_at"] = r["created_at"].isoformat()
    return JSONResponse({"ok": True, **result})

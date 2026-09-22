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
import httpx
import psycopg
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from .tools import mcp
from . import db
from .config import DIFY_API_BASE_URL
from .credentials import active_provider, set_active_provider, llm_configured, dify_chat_key, dify_list_terms_key
from .auth import (hash_password, verify_password, create_session, delete_session,
    require_auth, require_admin, active_admin_count, SESSION_COOKIE_NAME, SESSION_TTL)

ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable  # this same .venv's interpreter

def _validation_detail(exc):
    """INVALID_FIELDS 응답용 pydantic 오류 목록 - JSON으로 안전하게 직렬화되는 loc/msg/type만.

    exc.errors()를 그대로 실으면 field_validator가 던진 ValueError가 ctx에 **객체로** 들어 있어
    (예: 동의어 100자 초과) JSONResponse가 TypeError를 내고 400이어야 할 응답이 500이 된다
    (2026-09-22 실측). input(사용자가 보낸 원문)도 같이 빼서 최대 4000자짜리 정의를 응답에
    되돌려 싣지 않는다 - 클라이언트가 쓰는 건 loc뿐이다.
    """
    return exc.errors(include_url=False, include_context=False, include_input=False)

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
        return JSONResponse({"ok": False, "error": "INVALID_FIELDS", "detail": _validation_detail(exc)}, status_code=400)
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

# 도메인 신청 간편 입력에 챗봇 신규도메인 서브플로우 수준의 AI 추천을 붙임(2026-09-22) - "설명"
# 칸을 domain_suggestion.suggest_domain()의 definition 자리에 그대로 넘긴다. 이 모듈은 원래
# "용어의 정의를 보고 그 용어에 필요한 도메인 스펙을 짓는" 용도(신규 도메인 챗봇 서브플로우)라
# term_name이 필수 인자인데, 도메인 신청 폼엔 "용어"가 없다 - 사용자가 이미 적어둔 도메인명(코드)이나
# 도메인그룹을 term_name 자리에 힌트로 대신 넘긴다(실제로는 프롬프트 문맥과 가이드라인 검색 쿼리에만
# 쓰이므로 완전히 대체 가능 - domain_suggestion.py의 term_name 사용처 참고). 결과의 code/domain_group/
# data_type/data_length/decimal_length/display_format/valid_values만 프론트가 빈 칸에 채워 넣고,
# description은 사용자가 이미 쓴 트리거 텍스트 그 자체이므로 AI가 다시 쓴 문장으로 덮어쓰지 않는다.
@mcp.custom_route("/admin/domain-requests/suggest", methods=["GET"])
async def suggest_domain_route(request: Request) -> JSONResponse:
    import json
    from .domain_suggestion import suggest_domain
    _, error = require_auth(request)
    if error: return error
    description = (request.query_params.get("description") or "").strip()
    if not description:
        return JSONResponse({"ok": False, "error": "DESCRIPTION_REQUIRED"}, status_code=400)
    name_hint = (request.query_params.get("code") or request.query_params.get("domain_group") or "").strip()
    raw_history = request.query_params.get("clarification_history")
    clarification_history = None
    if raw_history:
        try:
            clarification_history = json.loads(raw_history)
        except (json.JSONDecodeError, TypeError):
            return JSONResponse({"ok": False, "error": "INVALID_CLARIFICATION_HISTORY"}, status_code=400)
    result = suggest_domain(name_hint, description, clarification_history=clarification_history)
    return JSONResponse({"ok": True, **result.model_dump()})

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

# 간편 입력 폼에 챗봇과 같은 즉각 반응을 주기 위한 3개 읽기전용 라우트(2026-09-21) -
# 실제 제출 없이 이름/정의/도메인/약어를 미리 점검·추천만 한다. 아래 셋 다 기존 로직을
# 그대로 재사용(새 판단 로직을 만들지 않음): check-name은 validate_name()+search()로
# 챗봇의 confirm_term이 정의를 묻기 *전에* 하는 것과 정확히 같은 검사만 수행 - registration.
# prepare()는 여기서 쓰지 않는다(LLM 기반 SAME_MEANING 비교까지 돌리면 blur 한 번에 수 초가
# 걸리고, registration_preparations에 부작용 있는 행까지 남긴다 - 그 깊은 판단은 여전히
# 최종 제출 시점에만 실행됨, 지금과 동일). "이미 있다/없다"는 여기서 답하지만 "의미가 같다"는
# 여전히 제출 시점의 몫.
# 용어 신청 폼 맨 위에 "사용하고자 하는 용어는 어떤 개념인가요?"를 먼저 받는 입력(2026-09-22) -
# 단, 단어/도메인과 달리 이 설명으로 AI가 용어명을 짓지는 않는다(사용자 결정 - "표준용어는
# 표준단어의 조합"이어야 하므로 이름은 항상 사용자가 직접 입력). 이 라우트의 역할은 딱 둘:
# (1) 여기서 - 이름을 정하기도 전에 의미상 겹치는 기존 용어가 있는지 미리 경고(참고용, 제출을
# 막지 않음). check-name과 달리 validate_name()을 거치지 않는다 - 이 입력은 애초에 이름이
# 아니라 자유 서술문이라 명명 규칙(마지막 형태소 명사형 등)에 맞을 이유가 없음. search()의
# term 인자는 최소 1자 제약만 있고 형식 검증이 없어 자유 서술문을 그대로 넘겨도 안전 - 의미
# 기반 임베딩 검색(semantic_matches)이 실제 신호이고, exact/synonym/lexical은 문장을 이름처럼
# 취급하니 사실상 항상 빈 값. (2) checkTermName()이 통과한 뒤 정의 추천(suggest-definition)을
# 부를 때, 프론트가 이 설명을 clarification_history의 첫 답으로 얹어 넘긴다(별도 백엔드 변경
# 없음 - suggest_definition()이 이미 받는 파라미터 재사용).
@mcp.custom_route("/admin/term-requests/check-concept", methods=["GET"])
async def check_term_concept(request: Request) -> JSONResponse:
    from .search import search
    _, error = require_auth(request)
    if error: return error
    description = (request.query_params.get("description") or "").strip()
    if not description:
        return JSONResponse({"ok": True, "matches": []})
    result = search(description, limit=5)
    matches = [{"name": c.name, "definition": c.definition, "domain": c.domain, "similarity": c.similarity}
        for c in result.semantic_matches]
    return JSONResponse({"ok": True, "matches": matches})

@mcp.custom_route("/admin/term-requests/check-name", methods=["GET"])
async def check_term_name(request: Request) -> JSONResponse:
    from . import quick_registration, registration
    from .search import validate_name, search
    _, error = require_auth(request)
    if error: return error
    term_name = (request.query_params.get("term_name") or "").strip()
    if not term_name:
        return JSONResponse({"ok": True, "status": "empty"})
    validation = validate_name(term_name)
    if not validation.valid:
        reason = validation.violations[0].reason if validation.violations else "형식이 올바르지 않습니다."
        return JSONResponse({"ok": True, "status": "invalid", "message": reason,
            "suggestions": validation.suggestions})
    pending = registration.find_pending(term_name)
    if pending:
        return JSONResponse({"ok": True, "status": "pending",
            "message": "이미 검토 대기 중인 동일한 이름의 신청이 있습니다.", "matched": pending})
    result = search(term_name)
    if result.match_type == "EXACT_MATCH" and result.exact_matches:
        match = result.exact_matches[0]
        return JSONResponse({"ok": True, "status": "exact_match",
            "message": f"이미 등록된 표준용어입니다(도메인 {match.domain}).", "matched": match.model_dump()})
    if result.match_type == "SYNONYM_MATCH" and result.synonym_matches:
        match = result.synonym_matches[0]
        return JSONResponse({"ok": True, "status": "synonym_match",
            "message": f"이미 등록된 표준용어 '{match.name}'의 동의어입니다.", "matched": match.model_dump()})
    # 마지막 관문: 표준단어 사전으로 완전분해되는가. 제출(quick_registration.prepare_term)이 하는
    # 검사와 같은 함수를 쓴다 - 여기서 빠지면 "사용 가능"(초록)이라고 답한 뒤 제출에서야 "단어부터
    # 등록하라"로 거절되고, 그 사이 정의/도메인/약어 추천(LLM)까지 등록 못 할 이름에 대해 돈다.
    # 순서는 챗봇 confirm_term과 같다(정확일치/대기중복/형식 다음이 단어 갭). LLM 없음.
    gaps = quick_registration.find_word_gaps(term_name)
    if gaps is not None:
        return JSONResponse({"ok": True, "status": "word_gap", "gaps": gaps,
            "message": quick_registration.word_gap_message(gaps)})
    return JSONResponse({"ok": True, "status": "available", "message": "사용 가능한 이름입니다."})

@mcp.custom_route("/admin/term-requests/suggest-definition", methods=["GET"])
async def suggest_term_definition_route(request: Request) -> JSONResponse:
    import json
    from .definition_suggestion import suggest_definition
    _, error = require_auth(request)
    if error: return error
    term_name = (request.query_params.get("term_name") or "").strip()
    if not term_name:
        return JSONResponse({"ok": False, "error": "TERM_NAME_REQUIRED"}, status_code=400)
    # 모호함 해소 라운드(클릭한 후보 라벨을 그대로 정의로 쓰면 안 됨 - 그 라벨은 "어떤
    # 의미인지" 답일 뿐, 완성된 정의 문장이 아니다. 챗봇의 set_definition과 동일하게
    # clarification_history로 다시 넣어 실제 정의 문장을 받는다).
    raw_history = request.query_params.get("clarification_history")
    clarification_history = None
    if raw_history:
        try:
            clarification_history = json.loads(raw_history)
        except (json.JSONDecodeError, TypeError):
            return JSONResponse({"ok": False, "error": "INVALID_CLARIFICATION_HISTORY"}, status_code=400)
    result = suggest_definition(term_name, clarification_history=clarification_history)
    return JSONResponse({"ok": True, **result.model_dump()})

# 도메인 추천(용어 이름+정의로 비교군을 찾아 domain_usage())과 영문약어 추천을 한 번에 묶음 -
# 같은 시점(이름+정의 둘 다 준비된 시점)에 함께 필요해서 왕복을 줄인다.
@mcp.custom_route("/admin/term-requests/suggest-followups", methods=["GET"])
async def suggest_term_followups(request: Request) -> JSONResponse:
    from .search import search, domain_usage
    from .abbreviation import suggest_abbreviation
    _, error = require_auth(request)
    if error: return error
    term_name = (request.query_params.get("term_name") or "").strip()
    definition = (request.query_params.get("definition") or "").strip()
    if not term_name or not definition:
        return JSONResponse({"ok": False, "error": "TERM_NAME_AND_DEFINITION_REQUIRED"}, status_code=400)
    result = search(term_name, definition, limit=30)
    domains = domain_usage(term_name, [c.term_id for c in result.candidates][:30])
    abbreviation = suggest_abbreviation(term_name)
    return JSONResponse({"ok": True, "domain": domains, "abbreviation": abbreviation.model_dump()})

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
        return JSONResponse({"ok": False, "error": "INVALID_FIELDS", "detail": _validation_detail(exc)}, status_code=400)
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

# "도메인분류"는 자유 입력 칸이지만 실제 정부 표준 사전에 이미 쓰이고 있는 값(수/금액/율/비용 등,
# 3,281건 중 545건에 값이 있음 - 나머지는 빈 문자열)이 있어서, 아무 선택지 없이 빈 텍스트 칸만
# 보여주면 사용자가 뭘 적어야 할지 알 수 없다는 지적(2026-09-22)에 따라 실제 값 목록을 돌려준다 -
# domain-requests/options의 dr-domain-group-options와 같은 패턴(자유 입력은 그대로 유지 - 강제
# 선택형 <select>가 아니라 <datalist>).
@mcp.custom_route("/admin/word-requests/options", methods=["GET"])
async def word_request_options(request: Request) -> JSONResponse:
    _, error = require_auth(request)
    if error: return error
    with db.connect() as conn:
        classifications = [r["domain_classification"] for r in conn.execute(
            "SELECT DISTINCT domain_classification FROM standard_words WHERE status='ACTIVE' AND domain_classification<>'' ORDER BY domain_classification").fetchall()]
    return JSONResponse({"ok": True, "domain_classifications": classifications})

# 단어 신청 간편 입력에 챗봇 수준의 AI 추천을 붙임(2026-09-22) - 단, "단어 등록은 이름이 아니라
# 의미가 입력"(위 CLAUDE.md 원칙, word_suggestion.py 참고)이라 용어 신청과 달리 사용자가 입력하는
# 이름을 그대로 검사하는 라우트가 아니다. "이 개념을 이렇게 씁니다"라는 의미 설명 하나를 받아
# word_suggestion.suggest_word()에 그대로 넘기면, 기존 단어와 겹치는지(existing_word_match)·의미가
# 모호한지(ambiguous)·아니면 새 이름/정의/영문약어/형식단어 초안까지 한 번의 호출로 전부 나온다 -
# 용어 신청처럼 이름 확인/정의 추천/후속 추천을 별도 라우트 3개로 쪼갤 필요가 없다(트리거 시점이
# "의미 설명 칸을 벗어날 때" 하나뿐이라서). fixed_name은 용어 등록 도중 자동 분기된 단어 서브플로우
# 전용(conversation.py)이라 여기서는 항상 빈 문자열 - 간편 입력은 독립 진입이라 고정할 표기가 없음.
@mcp.custom_route("/admin/word-requests/suggest", methods=["GET"])
async def suggest_word_route(request: Request) -> JSONResponse:
    import json
    from .word_suggestion import suggest_word
    _, error = require_auth(request)
    if error: return error
    usage_description = (request.query_params.get("usage_description") or "").strip()
    if not usage_description:
        return JSONResponse({"ok": False, "error": "USAGE_DESCRIPTION_REQUIRED"}, status_code=400)
    raw_history = request.query_params.get("clarification_history")
    clarification_history = None
    if raw_history:
        try:
            clarification_history = json.loads(raw_history)
        except (json.JSONDecodeError, TypeError):
            return JSONResponse({"ok": False, "error": "INVALID_CLARIFICATION_HISTORY"}, status_code=400)
    result = suggest_word(usage_description, clarification_history=clarification_history)
    return JSONResponse({"ok": True, **result.model_dump()})

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
        return JSONResponse({"ok": False, "error": "INVALID_FIELDS", "detail": _validation_detail(exc)}, status_code=400)
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

# ── Dify 프록시 (2026-09-22) ────────────────────────────────────────────
# 이전엔 app.js가 DIFY_CHAT_KEY/LIST_TERMS_KEY를 직접 들고 Dify를 호출했다 -
# 두 키 다 실제 비밀값이라 그 페이지를 여는 누구든(레포 공개 여부와 무관하게)
# devtools로 바로 읽을 수 있었다. 이제 프론트는 세션 쿠키로만 이 두 라우트를
# 부르고, 실제 Dify 키는 서버(.runtime/*.txt, 배포 스크립트가 씀)만 안다.
# user는 클라이언트가 보낸 값을 절대 신뢰하지 않고 세션의 실제 사용자명으로
# 강제한다 - 예전엔 아무 user 값이나 보내 다른 사람인 척 대화를 남길 수 있었다.
@mcp.custom_route("/admin/chat", methods=["POST"])
async def chat_proxy(request: Request):
    user, error = require_auth(request)
    if error: return error
    key = dify_chat_key()
    if not key:
        return JSONResponse({"ok": False, "error": "CHATFLOW_NOT_DEPLOYED"}, status_code=503)
    body = await request.json()
    query = (body.get("query") or "").strip()
    if not query:
        return JSONResponse({"ok": False, "error": "QUERY_REQUIRED"}, status_code=400)
    upstream_body = {"query": query, "inputs": {}, "response_mode": "streaming", "user": user["username"]}
    conversation_id = (body.get("conversation_id") or "").strip()
    if conversation_id:
        upstream_body["conversation_id"] = conversation_id

    # 스트리밍 그대로 중계 - 여기서 파싱/버퍼링하지 않는다. 프론트의 SSE 파서
    # (streamChatMessage)가 각 청크를 실시간으로 소비해 "답변 작성 중..." 타이핑
    # 효과와 노드별 진행 표시를 하므로, 여기서 한 번에 모아 보내면 그 효과가 죽는다.
    client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0))
    upstream_req = client.build_request("POST", f"{DIFY_API_BASE_URL}/v1/chat-messages",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, json=upstream_body)
    try:
        upstream = await client.send(upstream_req, stream=True)
    except httpx.HTTPError as exc:
        await client.aclose()
        return JSONResponse({"ok": False, "error": "UPSTREAM_UNREACHABLE", "detail": str(exc)}, status_code=502)
    if upstream.status_code != 200:
        detail = (await upstream.aread())[:2000].decode("utf-8", "replace")
        await upstream.aclose()
        await client.aclose()
        return JSONResponse({"ok": False, "error": "UPSTREAM_ERROR", "detail": detail}, status_code=upstream.status_code)

    async def relay():
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()
    return StreamingResponse(relay(), media_type=upstream.headers.get("content-type", "text/event-stream"))

@mcp.custom_route("/admin/list-terms", methods=["POST"])
async def list_terms_proxy(request: Request) -> JSONResponse:
    user, error = require_auth(request)
    if error: return error
    key = dify_list_terms_key()
    if not key:
        return JSONResponse({"ok": False, "error": "LIST_TERMS_WORKFLOW_NOT_DEPLOYED"}, status_code=503)
    body = await request.json()
    inputs = body.get("inputs") or {}
    upstream_body = {"inputs": inputs, "response_mode": "blocking", "user": user["username"]}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            upstream = await client.post(f"{DIFY_API_BASE_URL}/v1/workflows/run",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, json=upstream_body)
    except httpx.HTTPError as exc:
        return JSONResponse({"ok": False, "error": "UPSTREAM_UNREACHABLE", "detail": str(exc)}, status_code=502)
    return JSONResponse(upstream.json(), status_code=upstream.status_code)

"""표준 데이터 조회 통합 화면: standard_terms/standard_words/domains 각각과 그
자신의 대기/반려 신청 큐를 kind로 태그해 하나의 정렬/검색/페이지 피드로 합친다 -
list_terms()/list_standard_words()가 이미 하던 타입별 승인+대기 병합을 세 타입에
걸쳐 한 번에 하는 것뿐이다. 읽기 전용이며 admin_api.py의 GET /admin/standard-data로
노출된다(순수 조회 화면이라 Dify 워크플로 입력도 MCP @tool도 아님 - domain-request
라우트들과 같은 전례).

TERM 행의 valid_values/display_format은 자기 자신의 값(정부 원본에 드물게 있던
용어별 오버라이드 - approve/import_standard_catalog로만 채워짐, 신청 경로로는
절대 채워지지 않음)이 있으면 그걸, 없으면 소속 도메인의 값을 그대로 보여준다
(COALESCE) - "허용값/표현형식은 도메인이 결정한다"는 원칙(2026-09-18)에 따라
신규 신청 용어는 항상 도메인 값을 물려받는다. storage_format/data_type/
data_length/decimal_length/unit은 용어 자체엔 저장하지 않고 항상 도메인에서
그대로 가져온다(저장형식은 실측상 도메인과 100% 일치, 나머지는 원래도 도메인
고유 속성).
"""
from . import db

ALL_KINDS = ("TERM", "WORD", "DOMAIN")
PENDING_STATUSES = ("PENDING_REVIEW", "WAITING_FOR_WORD_APPROVAL", "WAITING_FOR_DOMAIN_APPROVAL", "REJECTED")

def list_standard_data(kinds: list[str], q: str = "", status: str = "", limit: int = 50, offset: int = 0) -> dict:
    """`kinds`는 TERM/WORD/DOMAIN 중 임의 조합(빈 값/알 수 없는 값은 셋 다). `q`는
    각 브랜치의 이름/내용(+대기 행은 requester)에 대한 ILIKE OR 검색. `status`는
    ""(승인+대기 전부), "APPROVED", 또는 PENDING_STATUSES 중 하나."""
    kinds = [k for k in (kinds or []) if k in ALL_KINDS] or list(ALL_KINDS)
    limit = min(max(limit, 1), 200)
    offset = max(offset, 0)
    like = f"%{q.strip()}%" if q.strip() else None
    status = (status or "").strip().upper()
    show_approved = status in ("", "APPROVED")
    pending_statuses = [status] if status in PENDING_STATUSES else (list(PENDING_STATUSES) if status == "" else [])

    branches: list[str] = []
    params: list = []

    def add(sql: str, p: list):
        branches.append(sql)
        params.extend(p)

    if "TERM" in kinds and show_approved:
        where, p = ["t.status='ACTIVE'"], []
        if like:
            where.append("(t.name ILIKE %s OR t.definition ILIKE %s)")
            p += [like, like]
        add(f"""SELECT 'TERM' AS kind, t.id::text AS id, t.name AS logical_name, NULL::text AS physical_name,
            t.definition AS content, t.domain, NULL::text AS requester, 'APPROVED' AS status, t.created_at,
            false AS is_personal_info, COALESCE(t.valid_values,d.valid_values) AS valid_values,
            COALESCE(t.display_format,d.display_format) AS display_format,
            t.administrative_code_name, t.competent_agency,
            d.storage_format, d.data_type, d.data_length, d.decimal_length, d.unit
            FROM standard_terms t LEFT JOIN domains d ON d.code=t.domain WHERE {' AND '.join(where)}""", p)
    if "TERM" in kinds and pending_statuses:
        where, p = ["t.status=ANY(%s)"], [pending_statuses]
        if like:
            where.append("(t.term_name ILIKE %s OR t.definition ILIKE %s OR t.requester ILIKE %s)")
            p += [like] * 3
        add(f"""SELECT 'TERM' AS kind, t.id::text AS id, t.term_name AS logical_name, NULL::text AS physical_name,
            t.definition AS content, t.domain, t.requester, t.status, t.created_at, false AS is_personal_info,
            d.valid_values, d.display_format, NULL::text AS administrative_code_name, NULL::text AS competent_agency,
            d.storage_format, d.data_type, d.data_length, d.decimal_length, d.unit
            FROM registration_requests t LEFT JOIN domains d ON d.code=t.domain WHERE {' AND '.join(where)}""", p)

    if "WORD" in kinds and show_approved:
        where, p = ["status='ACTIVE'"], []
        if like:
            where.append("(name ILIKE %s OR definition ILIKE %s)")
            p += [like, like]
        add(f"""SELECT 'WORD' AS kind, id::text AS id, name AS logical_name, english_abbr AS physical_name,
            definition AS content, NULL::text AS domain, NULL::text AS requester, 'APPROVED' AS status,
            updated_at AS created_at, false AS is_personal_info,
            NULL::text AS valid_values, NULL::text AS display_format,
            NULL::text AS administrative_code_name, NULL::text AS competent_agency,
            NULL::text AS storage_format, NULL::text AS data_type, NULL::int AS data_length,
            NULL::int AS decimal_length, NULL::text AS unit
            FROM standard_words WHERE {' AND '.join(where)}""", p)
    if "WORD" in kinds and pending_statuses:
        where, p = ["status=ANY(%s)"], [pending_statuses]
        if like:
            where.append("(word_name ILIKE %s OR definition ILIKE %s OR requester ILIKE %s)")
            p += [like] * 3
        add(f"""SELECT 'WORD' AS kind, id::text AS id, word_name AS logical_name, english_abbr AS physical_name,
            definition AS content, NULL::text AS domain, requester, status, created_at, false AS is_personal_info,
            NULL::text AS valid_values, NULL::text AS display_format,
            NULL::text AS administrative_code_name, NULL::text AS competent_agency,
            NULL::text AS storage_format, NULL::text AS data_type, NULL::int AS data_length,
            NULL::int AS decimal_length, NULL::text AS unit
            FROM word_registration_requests WHERE {' AND '.join(where)}""", p)

    if "DOMAIN" in kinds and show_approved:
        where, p = ["status='ACTIVE'"], []
        if like:
            where.append("(code ILIKE %s OR description ILIKE %s)")
            p += [like, like]
        add(f"""SELECT 'DOMAIN' AS kind, code AS id, code AS logical_name, physical_name,
            description AS content, NULL::text AS domain, NULL::text AS requester, 'APPROVED' AS status,
            created_at, is_personal_info, valid_values, display_format,
            NULL::text AS administrative_code_name, NULL::text AS competent_agency,
            storage_format, data_type, data_length, decimal_length, unit
            FROM domains WHERE {' AND '.join(where)}""", p)
    if "DOMAIN" in kinds and pending_statuses:
        where, p = ["status=ANY(%s)"], [pending_statuses]
        if like:
            where.append("(code ILIKE %s OR description ILIKE %s OR requester ILIKE %s)")
            p += [like] * 3
        add(f"""SELECT 'DOMAIN' AS kind, id::text AS id, code AS logical_name, physical_name,
            description AS content, NULL::text AS domain, requester, status, created_at, is_personal_info,
            valid_values, display_format, NULL::text AS administrative_code_name, NULL::text AS competent_agency,
            NULL::text AS storage_format, data_type, data_length, decimal_length, NULL::text AS unit
            FROM domain_requests WHERE {' AND '.join(where)}""", p)

    if not branches:
        return {"items": [], "count": 0, "total_count": 0, "limit": limit, "offset": offset}

    union_sql = " UNION ALL ".join(branches)
    with db.connect() as conn:
        total = conn.execute(f"SELECT count(*) AS count FROM ({union_sql}) t", params).fetchone()["count"]
        items = conn.execute(
            f"SELECT * FROM ({union_sql}) t ORDER BY created_at DESC NULLS LAST LIMIT %s OFFSET %s",
            params + [limit, offset]).fetchall()
    return {"items": items, "count": len(items), "total_count": total, "limit": limit, "offset": offset}

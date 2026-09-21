"""Governance for new domain (도메인) applications - a direct-form, non-chatbot
counterpart to registration.py/word_registration.py. Same two-step prepare()/
submit() confirmation shape (mirrored for consistency and because admin_api.py
still calls both in sequence within one HTTP request - see its docstring),
but simpler than the other two: no embeddings, no semantic duplicate/synonym
comparison. A domain is a data-type specification (도메인그룹/데이터유형/길이/
개인정보여부 등), not a natural-language concept, so the only real conflict to
guard against is two requests claiming the same domain code.

There is still no admin UI (matching the existing term/word gap) - approve()
below is the CLI-only entry point (manage.py approve-domain) a human reviewer
invokes once they've read a PENDING_REVIEW request.
"""
from datetime import datetime, timedelta, timezone
import uuid
import psycopg
from psycopg.types.json import Jsonb
from . import db
from .schemas import DomainRequestInput

def prepare(payload: DomainRequestInput):
    with db.connect() as conn:
        before = db.domain_catalog_fingerprint(conn)
        exists = conn.execute("SELECT code,description FROM domains WHERE code=%s", (payload.code,)).fetchone()
    if exists:
        return {"ready": False, "code": "CODE_ALREADY_EXISTS", "existing_domain": exists}
    with db.connect() as conn:
        pending = conn.execute("SELECT id FROM domain_requests WHERE code=%s AND status='PENDING_REVIEW'",
            (payload.code,)).fetchone()
    if pending:
        return {"ready": False, "code": "PENDING_REQUEST_ALREADY_EXISTS"}
    assessment = {"warnings": []}
    prep_id = str(uuid.uuid4())
    expires = datetime.now(timezone.utc) + timedelta(minutes=30)
    with db.connect() as conn:
        if db.domain_catalog_fingerprint(conn) != before:
            return {"ready": False, "code": "CATALOG_CHANGED_RETRY"}
        conn.execute("""UPDATE domain_preparations SET status='CANCELLED'
            WHERE requester=%s AND conversation_id=%s AND status='AWAITING_CONFIRMATION'""",
            (payload.requester, payload.conversation_id))
        conn.execute("""INSERT INTO domain_preparations
            (id,payload,assessment,requester,conversation_id,catalog_fingerprint,expires_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s)""",
            (prep_id, Jsonb(payload.model_dump()), Jsonb(assessment), payload.requester,
             payload.conversation_id, before, expires))
    return {"ready": True, "confirmation_id": prep_id, "expires_at": expires.isoformat(),
        "payload": payload.model_dump(), "assessment": assessment,
        "requires_final_confirmation": True, "resulting_status": "PENDING_REVIEW"}

def submit(confirmation_id, requester, conversation_id, confirmed):
    uuid.UUID(confirmation_id)
    if confirmed is not True:
        return {"created": False, "code": "EXPLICIT_CONFIRMATION_REQUIRED"}
    with db.connect() as conn:
        prep = conn.execute("SELECT * FROM domain_preparations WHERE id=%s FOR UPDATE", (confirmation_id,)).fetchone()
        if not prep or prep["requester"] != requester or prep["conversation_id"] != conversation_id:
            return {"created": False, "code": "CONFIRMATION_NOT_FOUND"}
        previous = conn.execute("SELECT id::text AS request_id,status,created_at FROM domain_requests WHERE preparation_id=%s",
            (confirmation_id,)).fetchone()
        if previous:
            previous["created_at"] = previous["created_at"].isoformat()
            return {"created": False, "idempotent_replay": True, **previous}
        if prep["status"] != "AWAITING_CONFIRMATION" or prep["expires_at"] < datetime.now(timezone.utc):
            return {"created": False, "code": "CONFIRMATION_EXPIRED_OR_CANCELLED"}
        conn.execute("LOCK TABLE domains IN SHARE MODE")
        if db.domain_catalog_fingerprint(conn) != prep["catalog_fingerprint"]:
            return {"created": False, "code": "CATALOG_CHANGED_REVALIDATE"}
        p = prep["payload"]
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,3))", (p["code"],))
        exists = conn.execute("SELECT code FROM domains WHERE code=%s", (p["code"],)).fetchone()
        if exists:
            return {"created": False, "code": "CODE_ALREADY_EXISTS"}
        pending = conn.execute("SELECT id FROM domain_requests WHERE code=%s AND status='PENDING_REVIEW'",
            (p["code"],)).fetchone()
        if pending:
            return {"created": False, "code": "PENDING_REQUEST_ALREADY_EXISTS"}
        row = conn.execute("""INSERT INTO domain_requests
            (id,preparation_id,code,domain_group,physical_name,data_type,data_length,decimal_length,
             min_value,max_value,display_format,source_classification,valid_values,default_value,
             description,is_personal_info,personal_info_type,protection_level,is_encrypted,
             encryption_method,mapping_table,mapping_column,request_reason,requester,conversation_id,assessment)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id::text AS request_id,status,created_at""",
            (str(uuid.uuid4()), confirmation_id, p["code"], p["domain_group"], p["physical_name"], p["data_type"],
             p["data_length"], p["decimal_length"], p["min_value"], p["max_value"], p["display_format"],
             p["source_classification"], p["valid_values"], p["default_value"], p["description"],
             p["is_personal_info"], p["personal_info_type"], p["protection_level"], p["is_encrypted"],
             p["encryption_method"], p["mapping_table"], p["mapping_column"], p["request_reason"],
             requester, conversation_id, Jsonb(prep["assessment"]))).fetchone()
        conn.execute("UPDATE domain_preparations SET status='SUBMITTED' WHERE id=%s", (confirmation_id,))
    row["created_at"] = row["created_at"].isoformat()
    return {"created": True, **row, "code": p["code"], "domain_group": p["domain_group"]}

def cancel(requester, conversation_id):
    with db.connect() as conn:
        rows = conn.execute("""UPDATE domain_preparations SET status='CANCELLED'
            WHERE requester=%s AND conversation_id=%s AND status='AWAITING_CONFIRMATION' RETURNING id""",
            (requester, conversation_id)).fetchall()
    return {"cancelled_confirmations": len(rows)}

def approve(request_id):
    """Promote a PENDING_REVIEW domain request into the live domains catalog.

    Also promotes any term registration that was waiting on this domain
    (WAITING_FOR_DOMAIN_APPROVAL, set by registration.submit() when a term's chosen
    domain didn't exist yet - see conversation.py's domain-request sub-flow) to
    PENDING_REVIEW. The NOT EXISTS guard is defensive, not load-bearing today:
    registration.submit()'s word-wins tie-break means a WAITING_FOR_DOMAIN_APPROVAL
    row never has an unresolved word dependency in practice, but checking costs
    nothing and protects against that tie-break ever changing - see
    word_registration.approve()'s symmetric comment.
    """
    with db.connect() as conn:
        req = conn.execute("SELECT * FROM domain_requests WHERE id=%s", (request_id,)).fetchone()
        if not req:
            return {"approved": False, "code": "REQUEST_NOT_FOUND"}
        if req["status"] != "PENDING_REVIEW":
            return {"approved": False, "code": "NOT_PENDING_REVIEW", "status": req["status"]}
        try:
            conn.execute("""INSERT INTO domains(code,description,source,status,domain_group,physical_name,
                data_type,data_length,decimal_length,display_format,min_value,max_value,source_classification,
                valid_values,default_value,is_personal_info,personal_info_type,protection_level,
                is_encrypted,encryption_method)
                VALUES(%s,%s,%s,'ACTIVE',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (req["code"], req["description"], "DIRECT_FORM_APPROVED", req["domain_group"], req["physical_name"],
                 req["data_type"], req["data_length"], req["decimal_length"], req["display_format"],
                 req["min_value"], req["max_value"], req["source_classification"], req["valid_values"],
                 req["default_value"], req["is_personal_info"], req["personal_info_type"],
                 req["protection_level"], req["is_encrypted"], req["encryption_method"]))
        except psycopg.errors.UniqueViolation:
            # A domain with this code slipped in between submit() and approve() (e.g.
            # import-standard-catalog ran, or another request for the same code was
            # approved first) - the partial unique index on domain_requests only
            # guards concurrent PENDING rows, not this later gap.
            return {"approved": False, "code": "DOMAIN_CODE_ALREADY_EXISTS"}
        if req["mapping_table"] and req["mapping_column"]:
            conn.execute("""INSERT INTO domain_data_mappings(id,domain_code,table_name,column_name)
                VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (str(uuid.uuid4()), req["code"], req["mapping_table"], req["mapping_column"]))
        conn.execute("UPDATE domain_requests SET status='APPROVED' WHERE id=%s", (request_id,))
        promoted = conn.execute("""UPDATE registration_requests SET status='PENDING_REVIEW'
            WHERE status='WAITING_FOR_DOMAIN_APPROVAL' AND depends_on_domain_request_id=%s
              AND NOT EXISTS (
                  SELECT 1 FROM registration_request_word_dependencies d
                  JOIN word_registration_requests w ON w.id=d.word_request_id
                  WHERE d.registration_request_id=registration_requests.id AND w.status<>'APPROVED')
            RETURNING id::text AS request_id, term_name""", (request_id,)).fetchall()
    return {"approved": True, "code": req["code"], "promoted_terms": [dict(r) for r in promoted]}

def reject(request_id):
    with db.connect() as conn:
        row = conn.execute("""UPDATE domain_requests SET status='REJECTED'
            WHERE id=%s AND status='PENDING_REVIEW' RETURNING id::text AS request_id,code""",
            (request_id,)).fetchone()
    if not row:
        return {"rejected": False, "code": "REQUEST_NOT_FOUND_OR_NOT_PENDING"}
    return {"rejected": True, **row}

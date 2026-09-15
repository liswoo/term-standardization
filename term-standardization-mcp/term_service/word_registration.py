"""Governance for new 표준단어(standard word) requests - mirrors registration.py's
prepare()/submit() two-step confirmation exactly, but for word_registration_requests
instead of registration_requests. Kept as a separate table/module rather than folding
into the term one, matching this schema's existing separation of standard_words from
standard_terms: a word and a term have different shapes (no domain, but is_format_word/
domain_classification) and different lifecycles (a word can be reused across many
future terms, so its own review queue shouldn't be entangled with any one term's).

There is still no admin UI (see CLAUDE.md's known gaps) - approve() below is the
minimal entry point a human reviewer invokes (via manage.py) once they've actually
read and accepted a PENDING_REVIEW request. A word is otherwise usable for search/
comparison purposes at PENDING_REVIEW (never treated as an approved standard).
"""
from datetime import datetime, timedelta, timezone
import uuid
from psycopg.types.json import Jsonb
from . import db
from .config import EMBEDDING_MODEL
from .embeddings import embed
from .naming import key
from .schemas import WordRegistrationInput

def prepare(payload: WordRegistrationInput):
    with db.connect() as conn:
        before = db.word_catalog_fingerprint(conn)
        exact = conn.execute("SELECT id::text,name,english_abbr FROM standard_words WHERE normalized_name=%s AND status='ACTIVE'",
            (key(payload.word_name),)).fetchone()
    if exact:
        # Defense in depth: suggest_word() already checks this via search_words(), but
        # a race (two users proposing the same word concurrently) or a manually-typed
        # override must still be caught here before creating a duplicate.
        return {"ready": False, "code": "EXACT_MATCH", "recommended_action": "USE_EXISTING", "existing_word": exact}
    abbr_conflict = None
    with db.connect() as conn:
        abbr_conflict = conn.execute("""SELECT 1 FROM standard_words WHERE english_abbr=%s AND status='ACTIVE'
            UNION SELECT 1 FROM word_registration_requests WHERE english_abbr=%s AND status<>'REJECTED'""",
            (payload.english_abbr, payload.english_abbr)).fetchone()
    if abbr_conflict:
        return {"ready": False, "code": "ABBREVIATION_ALREADY_USED"}
    assessment = {"warnings": []}
    prep_id = str(uuid.uuid4())
    expires = datetime.now(timezone.utc) + timedelta(minutes=30)
    with db.connect() as conn:
        if db.word_catalog_fingerprint(conn) != before:
            return {"ready": False, "code": "CATALOG_CHANGED_RETRY"}
        conn.execute("""UPDATE word_registration_preparations SET status='CANCELLED'
            WHERE requester=%s AND conversation_id=%s AND status='AWAITING_CONFIRMATION'""",
            (payload.requester, payload.conversation_id))
        conn.execute("""INSERT INTO word_registration_preparations
            (id,payload,assessment,requester,conversation_id,catalog_fingerprint,expires_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s)""",
            (prep_id, Jsonb(payload.model_dump()), Jsonb(assessment), payload.requester, payload.conversation_id, before, expires))
    return {"ready": True, "confirmation_id": prep_id, "expires_at": expires.isoformat(),
        "payload": payload.model_dump(), "assessment": assessment, "requires_final_confirmation": True,
        "resulting_status": "PENDING_REVIEW"}

def submit(confirmation_id, requester, conversation_id, confirmed):
    uuid.UUID(confirmation_id)
    if confirmed is not True:
        return {"created": False, "code": "EXPLICIT_CONFIRMATION_REQUIRED"}
    with db.connect() as conn:
        prep = conn.execute("SELECT * FROM word_registration_preparations WHERE id=%s FOR UPDATE", (confirmation_id,)).fetchone()
        if not prep or prep["requester"] != requester or prep["conversation_id"] != conversation_id:
            return {"created": False, "code": "CONFIRMATION_NOT_FOUND"}
        previous = conn.execute("SELECT id::text AS request_id,status,created_at FROM word_registration_requests WHERE preparation_id=%s",
            (confirmation_id,)).fetchone()
        if previous:
            previous["created_at"] = previous["created_at"].isoformat()
            return {"created": False, "idempotent_replay": True, **previous}
        if prep["status"] != "AWAITING_CONFIRMATION" or prep["expires_at"] < datetime.now(timezone.utc):
            return {"created": False, "code": "CONFIRMATION_EXPIRED_OR_CANCELLED"}
        conn.execute("LOCK TABLE standard_words IN SHARE MODE")
        if db.word_catalog_fingerprint(conn) != prep["catalog_fingerprint"]:
            return {"created": False, "code": "CATALOG_CHANGED_REVALIDATE"}
        p = prep["payload"]
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,2))", (key(p["word_name"]),))
        pending = conn.execute("SELECT id FROM word_registration_requests WHERE normalized_name=%s AND status='PENDING_REVIEW'",
            (key(p["word_name"]),)).fetchone()
        if pending:
            return {"created": False, "code": "PENDING_REQUEST_ALREADY_EXISTS"}
        row = conn.execute("""INSERT INTO word_registration_requests
            (id,preparation_id,word_name,normalized_name,definition,english_abbr,is_format_word,
            domain_classification,requester,conversation_id,assessment)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id::text AS request_id,status,created_at""",
            (str(uuid.uuid4()), confirmation_id, p["word_name"], key(p["word_name"]), p["definition"],
             p["english_abbr"], p["is_format_word"], p["domain_classification"], requester, conversation_id,
             Jsonb(prep["assessment"]))).fetchone()
        conn.execute("UPDATE word_registration_preparations SET status='SUBMITTED' WHERE id=%s", (confirmation_id,))
    row["created_at"] = row["created_at"].isoformat()
    return {"created": True, "is_official_standard": False, **row, "word_name": p["word_name"],
        "definition": p["definition"], "english_abbr": p["english_abbr"]}

def cancel(requester, conversation_id):
    with db.connect() as conn:
        rows = conn.execute("""UPDATE word_registration_preparations SET status='CANCELLED'
            WHERE requester=%s AND conversation_id=%s AND status='AWAITING_CONFIRMATION' RETURNING id""",
            (requester, conversation_id)).fetchall()
    return {"cancelled_confirmations": len(rows)}

def approve(word_request_id):
    """Promote a PENDING_REVIEW word request into the live standard_words catalog.

    Also promotes any term registration that was waiting on this exact word
    (WAITING_FOR_WORD_APPROVAL, set by registration.submit() when a term's required
    word didn't exist yet - see conversation.py's confirm_term/set_word_abbreviation)
    to PENDING_REVIEW, since the dependency is now satisfied.
    """
    with db.connect() as conn:
        req = conn.execute("SELECT * FROM word_registration_requests WHERE id=%s", (word_request_id,)).fetchone()
        if not req:
            return {"approved": False, "code": "REQUEST_NOT_FOUND"}
        if req["status"] != "PENDING_REVIEW":
            return {"approved": False, "code": "NOT_PENDING_REVIEW", "status": req["status"]}
        vector = embed(req["word_name"] + " : " + req["definition"]) if req["definition"] else embed(req["word_name"])
        conn.execute("""INSERT INTO standard_words(id,name,normalized_name,english_abbr,definition,
            is_format_word,domain_classification,source,embedding,embedding_model,status)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'ACTIVE')""",
            (str(uuid.uuid4()), req["word_name"], req["normalized_name"], req["english_abbr"], req["definition"],
             req["is_format_word"], req["domain_classification"], "CHATBOT_APPROVED", vector, EMBEDDING_MODEL))
        conn.execute("UPDATE word_registration_requests SET status='APPROVED' WHERE id=%s", (word_request_id,))
        promoted = conn.execute("""UPDATE registration_requests SET status='PENDING_REVIEW'
            WHERE depends_on_word_request_id=%s AND status='WAITING_FOR_WORD_APPROVAL'
            RETURNING id::text AS request_id, term_name""", (word_request_id,)).fetchall()
    return {"approved": True, "word_name": req["word_name"],
        "promoted_terms": [dict(r) for r in promoted]}

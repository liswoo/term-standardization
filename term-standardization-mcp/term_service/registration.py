from datetime import datetime, timedelta, timezone
import uuid
from psycopg.types.json import Jsonb
from . import db
from .naming import key
from .schemas import RegistrationInput
from .search import search, validate_name
from .comparison import compare

def prepare(payload: RegistrationInput):
    validation=validate_name(payload.term_name)
    if not validation.valid:
        return {"ready":False,"code":"GUIDELINE_VIOLATION","validation":validation.model_dump()}
    before = None
    with db.connect() as conn:
        before=db.catalog_fingerprint(conn)
        known_domain=bool(conn.execute("SELECT code FROM domains WHERE code=%s",(payload.domain,)).fetchone())
    result=search(payload.term_name,payload.definition,limit=30)
    if result.exact_matches:
        return {"ready":False,"code":"EXACT_MATCH","recommended_action":"USE_EXISTING","search":result.model_dump()}
    # Supplied synonyms cannot silently claim an existing standard name or alias.
    alias_conflicts=[]
    with db.connect() as conn:
        for synonym in payload.synonyms:
            alias_conflicts.extend(conn.execute("SELECT id::text,name FROM standard_terms WHERE normalized_name=%s OR %s=ANY(normalized_synonyms)",
                (key(synonym),key(synonym))).fetchall())
    if alias_conflicts:
        return {"ready":False,"code":"SYNONYM_CONFLICT","candidates":alias_conflicts}
    comparisons=[compare(payload.term_name,payload.definition,c.term_id).model_dump() for c in result.candidates]
    if any(c["relation"]=="SAME_MEANING" for c in comparisons):
        return {"ready":False,"code":"SAME_MEANING","recommended_action":"USE_EXISTING","comparisons":comparisons}
    warnings=list(result.warnings)
    if not known_domain:
        warnings.append("UNREGISTERED_DOMAIN_REQUIRES_REVIEW")
    if result.synonym_matches:
        warnings.append("SYNONYM_MATCH_REQUIRES_REVIEW")
    if any(c["relation"]=="UNCERTAIN" for c in comparisons):
        warnings.append("UNCERTAIN_DEFINITION_REQUIRES_REVIEW")
    if len(result.candidates)>=30:
        warnings.append("CANDIDATE_LIMIT_REQUIRES_REVIEW")
    assessment={"search":result.model_dump(),"comparisons":comparisons,"warnings":warnings,
        "recommended_action":"REVIEW_REQUIRED" if warnings else "CREATE_NEW","domain_known":known_domain}
    prep_id=str(uuid.uuid4())
    expires=datetime.now(timezone.utc)+timedelta(minutes=30)
    with db.connect() as conn:
        if db.catalog_fingerprint(conn)!=before:
            return {"ready":False,"code":"CATALOG_CHANGED_RETRY"}
        # Supersede prior confirmations in this conversation; edits invalidate the old payload.
        conn.execute("UPDATE registration_preparations SET status='CANCELLED' WHERE requester=%s AND conversation_id=%s AND status='AWAITING_CONFIRMATION'",
            (payload.requester,payload.conversation_id))
        conn.execute("""INSERT INTO registration_preparations
            (id,payload,assessment,requester,conversation_id,catalog_fingerprint,expires_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s)""",
            (prep_id,Jsonb(payload.model_dump()),Jsonb(assessment),payload.requester,payload.conversation_id,before,expires))
    return {"ready":True,"confirmation_id":prep_id,"expires_at":expires.isoformat(),"payload":payload.model_dump(),
        "assessment":assessment,"requires_final_confirmation":True,"resulting_status":"PENDING_REVIEW"}

def submit(confirmation_id, requester, conversation_id, confirmed):
    uuid.UUID(confirmation_id)
    if confirmed is not True:
        return {"created":False,"code":"EXPLICIT_CONFIRMATION_REQUIRED"}
    with db.connect() as conn:
        prep=conn.execute("SELECT * FROM registration_preparations WHERE id=%s FOR UPDATE",(confirmation_id,)).fetchone()
        if not prep or prep["requester"]!=requester or prep["conversation_id"]!=conversation_id:
            return {"created":False,"code":"CONFIRMATION_NOT_FOUND"}
        previous=conn.execute("SELECT id::text AS request_id,status,created_at FROM registration_requests WHERE preparation_id=%s",(confirmation_id,)).fetchone()
        if previous:
            previous["created_at"]=previous["created_at"].isoformat()
            return {"created":False,"idempotent_replay":True,**previous}
        if prep["status"]!="AWAITING_CONFIRMATION" or prep["expires_at"]<datetime.now(timezone.utc):
            return {"created":False,"code":"CONFIRMATION_EXPIRED_OR_CANCELLED"}
        # Catalog shared lock closes the check/insert race against administrative imports.
        conn.execute("LOCK TABLE standard_terms, domains IN SHARE MODE")
        if db.catalog_fingerprint(conn)!=prep["catalog_fingerprint"]:
            return {"created":False,"code":"CATALOG_CHANGED_REVALIDATE"}
        p=prep["payload"]
        # Serialize pending requests for the same normalized name.
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",(key(p["term_name"]),))
        pending=conn.execute("SELECT id FROM registration_requests WHERE normalized_name=%s AND status='PENDING_REVIEW'",(key(p["term_name"]),)).fetchone()
        if pending:
            return {"created":False,"code":"PENDING_REQUEST_ALREADY_EXISTS"}
        row=conn.execute("""INSERT INTO registration_requests
            (id,preparation_id,term_name,normalized_name,definition,domain,synonyms,requester,conversation_id,assessment)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id::text AS request_id,status,created_at""",
            (str(uuid.uuid4()),confirmation_id,p["term_name"],key(p["term_name"]),p["definition"],p["domain"],
             p["synonyms"],requester,conversation_id,Jsonb(prep["assessment"]))).fetchone()
        conn.execute("UPDATE registration_preparations SET status='SUBMITTED' WHERE id=%s",(confirmation_id,))
    row["created_at"]=row["created_at"].isoformat()
    return {"created":True,"is_official_standard":False,**row,"term_name":p["term_name"],"definition":p["definition"],"domain":p["domain"]}

def cancel(requester,conversation_id):
    with db.connect() as conn:
        rows=conn.execute("UPDATE registration_preparations SET status='CANCELLED' WHERE requester=%s AND conversation_id=%s AND status='AWAITING_CONFIRMATION' RETURNING id",
            (requester,conversation_id)).fetchall()
    return {"cancelled_confirmations":len(rows)}

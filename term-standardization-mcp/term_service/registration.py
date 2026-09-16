from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import uuid
from psycopg.types.json import Jsonb
from . import db
from .config import EMBEDDING_MODEL, LOCAL_COMPARE_CANDIDATE_CAP
from .credentials import active_provider
from .embeddings import embed
from .naming import key, morphology
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
    # Each compare() call is one LLM round-trip; result.candidates can hold up to
    # 30 (see search.py's limit=30 above). Run sequentially and a single confirmation
    # takes tens of seconds once a real catalog actually produces that many candidates
    # (a handful of synthetic terms never did) - each call opens its own DB connection
    # (db.connect() has no shared pool/state), so they're safe to fan out concurrently.
    # With OpenAI's backend this genuinely runs the 8 threads in parallel (~3-4s total,
    # see CLAUDE.md). ThreadPoolExecutor cannot do the same trick against a single local
    # GPU serving one Ollama process - the "parallel" calls just queue up and run close
    # to sequentially, and comparing all 30 candidates can take minutes and blow past
    # Dify's 5-minute MCP tool timeout with no error surfaced to the user (see CLAUDE.md's
    # "로컬 모델(Ollama) 테스트" section for how this was diagnosed).
    #
    # TEST-ONLY QUALITY TRADEOFF, local provider only: compare only the top
    # LOCAL_COMPARE_CANDIDATE_CAP candidates (result.candidates is already ordered
    # exact > synonym > semantic > lexical, most-relevant-first within each group -
    # see search.py) instead of all of them. This exists purely so local testing
    # finishes in reasonable time; it is NOT a quality improvement and must never
    # apply to the OpenAI path - a real duplicate sitting outside the kept slice
    # becomes a false negative (SAME_MEANING silently missed). Do not raise the
    # default cap to "fix" speed without re-reading why it exists; the actual fix
    # is fewer LLM calls per confirmation (batch the candidates into one call) or
    # faster local throughput (better hardware/quantization), not a bigger cap.
    to_compare=result.candidates
    local_cap_applied=False
    if active_provider()=="local" and len(to_compare)>LOCAL_COMPARE_CANDIDATE_CAP:
        to_compare=to_compare[:LOCAL_COMPARE_CANDIDATE_CAP]
        local_cap_applied=True
    with ThreadPoolExecutor(max_workers=8) as executor:
        comparisons=[c.model_dump() for c in executor.map(
            lambda candidate: compare(payload.term_name,payload.definition,candidate.term_id), to_compare)]
    if any(c["relation"]=="SAME_MEANING" for c in comparisons):
        # Unlike EXACT_MATCH above, this block used to omit `search`, so the matched
        # existing term's name/definition/domain never reached rendering - only an
        # opaque existing_term_id in `comparisons`.
        return {"ready":False,"code":"SAME_MEANING","recommended_action":"USE_EXISTING",
            "comparisons":comparisons,"search":result.model_dump()}
    warnings=list(result.warnings)
    if local_cap_applied:
        # Data-level paper trail for the tradeoff above: this specific preparation's
        # duplicate check did not cover all of result.candidates, so it must read as
        # weaker evidence than a normal (OpenAI) REVIEW_REQUIRED/CREATE_NEW - never
        # silently promote this to an approved standard term without a human re-check
        # against the full candidate list.
        warnings.append("LOCAL_TEST_COMPARISON_CAPPED")
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

def submit(confirmation_id, requester, conversation_id, confirmed, english_abbr="", depends_on_word_request_ids=None):
    uuid.UUID(confirmation_id)
    if confirmed is not True:
        return {"created":False,"code":"EXPLICIT_CONFIRMATION_REQUIRED"}
    dependency_ids=depends_on_word_request_ids or []
    with db.connect() as conn:
        prep=conn.execute("SELECT * FROM registration_preparations WHERE id=%s FOR UPDATE",(confirmation_id,)).fetchone()
        if not prep or prep["requester"]!=requester or prep["conversation_id"]!=conversation_id:
            return {"created":False,"code":"CONFIRMATION_NOT_FOUND"}
        previous=conn.execute("SELECT id::text AS request_id,status,created_at,english_abbr FROM registration_requests WHERE preparation_id=%s",(confirmation_id,)).fetchone()
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
        pending=conn.execute("SELECT id FROM registration_requests WHERE normalized_name=%s AND status IN ('PENDING_REVIEW','WAITING_FOR_WORD_APPROVAL')",(key(p["term_name"]),)).fetchone()
        if pending:
            return {"created":False,"code":"PENDING_REQUEST_ALREADY_EXISTS"}
        # A term whose required word(s) were just submitted (not reused - see conversation.py's
        # set_word_abbreviation/confirm_word) depends on every one of them being approved
        # first: the term isn't ready for review on its own merits yet, so it must not sit
        # in the same PENDING_REVIEW queue as one that is. A term can now depend on several
        # words at once (see naming.py's split_into_nouns - a multi-noun gap registered as
        # separate words), tracked in registration_request_word_dependencies rather than a
        # single FK column so word_registration.approve() can require ALL of them approved.
        initial_status="WAITING_FOR_WORD_APPROVAL" if dependency_ids else "PENDING_REVIEW"
        row=conn.execute("""INSERT INTO registration_requests
            (id,preparation_id,term_name,normalized_name,definition,domain,synonyms,english_abbr,requester,conversation_id,assessment,status)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id::text AS request_id,status,created_at,english_abbr""",
            (str(uuid.uuid4()),confirmation_id,p["term_name"],key(p["term_name"]),p["definition"],p["domain"],
             p["synonyms"],english_abbr or None,requester,conversation_id,Jsonb(prep["assessment"]),
             initial_status)).fetchone()
        for word_request_id in dependency_ids:
            conn.execute("""INSERT INTO registration_request_word_dependencies(registration_request_id,word_request_id)
                VALUES(%s,%s)""",(row["request_id"],word_request_id))
        conn.execute("UPDATE registration_preparations SET status='SUBMITTED' WHERE id=%s",(confirmation_id,))
    row["created_at"]=row["created_at"].isoformat()
    return {"created":True,"is_official_standard":False,**row,"term_name":p["term_name"],"definition":p["definition"],"domain":p["domain"]}

def approve(request_id):
    """Promote a PENDING_REVIEW term request into the live standard_terms catalog.

    There is no admin UI yet (see CLAUDE.md's known gaps) - this is the minimal
    entry point a human reviewer invokes (via manage.py) once they've actually
    read and accepted the request. WAITING_FOR_WORD_APPROVAL requests are refused
    here on purpose: approving the term before its dependency word is real would
    publish a term whose abbreviation composition points at a word that doesn't
    exist yet.
    """
    with db.connect() as conn:
        req=conn.execute("SELECT * FROM registration_requests WHERE id=%s",(request_id,)).fetchone()
        if not req:
            return {"approved":False,"code":"REQUEST_NOT_FOUND"}
        if req["status"]!="PENDING_REVIEW":
            return {"approved":False,"code":"NOT_PENDING_REVIEW","status":req["status"]}
        nouns=[m["form"] for m in morphology(req["term_name"])["morphemes"] if m["tag"].startswith("N")]
        vector=embed(req["term_name"]+" : "+req["definition"])
        conn.execute("""INSERT INTO standard_terms(id,name,normalized_name,definition,domain,synonyms,
            normalized_synonyms,noun_tokens,source,embedding,embedding_model,english_abbr,status)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'ACTIVE')""",
            (str(uuid.uuid4()),req["term_name"],req["normalized_name"],req["definition"],req["domain"],
             req["synonyms"],[key(s) for s in req["synonyms"]],nouns,"CHATBOT_APPROVED",vector,EMBEDDING_MODEL,
             req["english_abbr"]))
        conn.execute("UPDATE registration_requests SET status='APPROVED' WHERE id=%s",(request_id,))
    return {"approved":True,"term_name":req["term_name"]}

def find_pending(term_name):
    """The most recent still-pending request for this exact normalized name, if any.

    confirm_term uses this to short-circuit a re-registration of a term that is
    already awaiting review, before the user re-walks the whole domain/definition/
    abbreviation flow only to hit PENDING_REQUEST_ALREADY_EXISTS at the very end.
    """
    with db.connect() as conn:
        row=conn.execute("""SELECT id::text AS request_id,term_name,definition,domain,english_abbr,status,created_at
            FROM registration_requests WHERE normalized_name=%s AND status IN ('PENDING_REVIEW','WAITING_FOR_WORD_APPROVAL')
            ORDER BY created_at DESC LIMIT 1""",(key(term_name),)).fetchone()
    if row:
        row["created_at"]=row["created_at"].isoformat()
    return row

def cancel(requester,conversation_id):
    with db.connect() as conn:
        rows=conn.execute("UPDATE registration_preparations SET status='CANCELLED' WHERE requester=%s AND conversation_id=%s AND status='AWAITING_CONFIRMATION' RETURNING id",
            (requester,conversation_id)).fetchall()
    return {"cancelled_confirmations":len(rows)}

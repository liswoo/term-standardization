"""MCP contracts. Chat wording and intent interpretation live in Dify."""
from functools import wraps
from typing import Any
import logging
import uuid
from mcp.server.mcpserver import MCPServer
from . import db, registration, word_registration
from .abbreviation import suggest_abbreviation, validate_abbreviation, validate_word_abbreviation
from .guideline import check_guideline
from .naming import morphology
from .schemas import RegistrationInput, WordRegistrationInput
from .search import search, relational, vector_search, validate_name, get_term, domain_usage, search_words
from .comparison import compare
from .word_suggestion import suggest_word

log=logging.getLogger(__name__)
mcp=MCPServer(name="term-standardization",instructions="Structured Korean terminology validation, catalog search and pending review requests. Never treat pending requests as approved standards.")

def tool(fn):
    fn.__annotations__["return"] = dict[str, Any]
    @wraps(fn)
    def safe(*args,**kwargs):
        try:
            result=fn(*args,**kwargs)
            return result.model_dump(mode="json") if hasattr(result,"model_dump") else result
        except ValueError as exc:
            return {"ok":False,"error":{"code":"INVALID_INPUT","type":type(exc).__name__}}
        except Exception as exc:
            log.error("tool=%s exception=%s",fn.__name__,type(exc).__name__)
            return {"ok":False,"error":{"code":"DEPENDENCY_UNAVAILABLE","type":type(exc).__name__},"retryable":True}
    return mcp.tool(structured_output=True)(safe)

@tool
def analyze_morphology(text: str) -> dict:
    """Analyze Korean text using Kiwi. Returns morpheme forms, POS tags and positions."""
    return morphology(text)

@tool
def validate_term_name(term: str) -> dict:
    """Validate Korean noun naming rules. Returns valid, violations and evidence-based suggestions."""
    return validate_name(term)

@tool
def search_standard_terms(term: str, definition: str = "", limit: int = 10) -> dict:
    """Search approved catalog by normalized name, synonyms, morphological tokens and pgvector similarity. Empty/unavailable catalog is UNDETERMINED."""
    return search(term,definition,limit)

@tool
def search_similar_terms_vector(query: str, top_k: int = 5) -> dict:
    """Compatibility tool: local multilingual embeddings plus pgvector cosine search."""
    return {"query":query,"results":vector_search(query,limit=top_k),"source":"pgvector"}

@tool
def search_similar_terms_rdb(query: str) -> dict:
    """Compatibility tool: PostgreSQL exact/synonym/trigram/morphological token retrieval."""
    groups=relational(query)
    return {"query":query,"results":[r for rows in groups.values() for r in rows],**groups,"source":"postgresql"}

@tool
def get_standard_term(term_id: str) -> dict:
    """Read a catalog entry for questions about prior candidate definitions."""
    return get_term(term_id)

@tool
def analyze_domain_usage(candidate_term: str, similar_term_ids: list[str] | None = None) -> dict:
    """Compute domain counts from real deduplicated catalog records. No evidence means no recommendation."""
    return domain_usage(candidate_term,similar_term_ids or [])

@tool
def list_data_domains() -> dict:
    """List actual domain metadata; never generate fake domains."""
    with db.connect() as conn:
        return {"domains":conn.execute("SELECT code,description,source FROM domains WHERE status='ACTIVE' ORDER BY code").fetchall()}

@tool
def list_terms(limit: int = 50, offset: int = 0, q: str = "") -> dict:
    """Page through approved catalog terms plus non-rejected registration requests, most
    recent first. `q` filters by name/definition substring (case-insensitive) - with a
    real government-scale catalog (13,000+ terms), unfiltered offset paging alone is not
    a usable way to find anything. `total_count` is the ACTIVE catalog count matching `q`
    (registration requests are few enough to always return in full, unpaginated)."""
    limit=min(max(limit,1),200)
    offset=max(offset,0)
    like=f"%{q.strip()}%" if q.strip() else None
    with db.connect() as conn:
        if like:
            total=conn.execute(
                "SELECT count(*) AS count FROM standard_terms WHERE status='ACTIVE' AND (name ILIKE %s OR definition ILIKE %s)",
                (like,like)).fetchone()["count"]
            approved=conn.execute(
                "SELECT id::text AS id, name AS term_name, definition, domain, synonyms, english_abbr, 'APPROVED' AS status, created_at "
                "FROM standard_terms WHERE status='ACTIVE' AND (name ILIKE %s OR definition ILIKE %s) "
                "ORDER BY created_at DESC LIMIT %s OFFSET %s",(like,like,limit,offset)).fetchall()
            pending=conn.execute(
                "SELECT id::text AS id, term_name, definition, domain, synonyms, english_abbr, status, created_at "
                "FROM registration_requests WHERE status!='REJECTED' AND (term_name ILIKE %s OR definition ILIKE %s) "
                "ORDER BY created_at DESC LIMIT %s",(like,like,limit)).fetchall()
        else:
            total=conn.execute("SELECT count(*) AS count FROM standard_terms WHERE status='ACTIVE'").fetchone()["count"]
            approved=conn.execute(
                "SELECT id::text AS id, name AS term_name, definition, domain, synonyms, english_abbr, 'APPROVED' AS status, created_at "
                "FROM standard_terms WHERE status='ACTIVE' ORDER BY created_at DESC LIMIT %s OFFSET %s",(limit,offset)).fetchall()
            pending=conn.execute(
                "SELECT id::text AS id, term_name, definition, domain, synonyms, english_abbr, status, created_at "
                "FROM registration_requests WHERE status!='REJECTED' ORDER BY created_at DESC LIMIT %s",(limit,)).fetchall()
        descriptions={r["code"]:r["description"] for r in conn.execute("SELECT code,description FROM domains").fetchall()}
    combined=approved+pending
    for r in combined:
        r["domain_description"]=descriptions.get(r["domain"])
    combined.sort(key=lambda r:r["created_at"],reverse=True)
    return {"terms":combined,"count":len(combined),"total_count":total,"limit":limit,"offset":offset}

@tool
def list_standard_words(limit: int = 50, offset: int = 0, q: str = "") -> dict:
    """Page through the 표준단어(standard word) dictionary that standard_terms are
    composed from, most recently updated first. `q` filters by name/definition substring."""
    limit=min(max(limit,1),200)
    offset=max(offset,0)
    like=f"%{q.strip()}%" if q.strip() else None
    fields="name,english_abbr,english_name,definition,is_format_word,domain_classification,synonyms,status,updated_at"
    with db.connect() as conn:
        if like:
            total=conn.execute(
                "SELECT count(*) AS count FROM standard_words WHERE status='ACTIVE' AND (name ILIKE %s OR definition ILIKE %s)",
                (like,like)).fetchone()["count"]
            rows=conn.execute(f"""SELECT {fields} FROM standard_words
                WHERE status='ACTIVE' AND (name ILIKE %s OR definition ILIKE %s)
                ORDER BY updated_at DESC LIMIT %s OFFSET %s""",(like,like,limit,offset)).fetchall()
        else:
            total=conn.execute("SELECT count(*) AS count FROM standard_words WHERE status='ACTIVE'").fetchone()["count"]
            rows=conn.execute(f"""SELECT {fields} FROM standard_words
                WHERE status='ACTIVE' ORDER BY updated_at DESC LIMIT %s OFFSET %s""",(limit,offset)).fetchall()
    return {"words":rows,"count":len(rows),"total_count":total,"limit":limit,"offset":offset}

@tool
def search_standard_words_semantic(meaning_query: str, limit: int = 10) -> dict:
    """Meaning-first search over the 표준단어(standard word) dictionary: given a
    free-text description of a concept/use case (not a word name), find existing
    words whose own name+definition is semantically close (pgvector cosine).
    This is the entry point for "is there already an official word for what I mean" -
    different from decomposing a term name into exact known words."""
    return {"query":meaning_query,"results":search_words(meaning_query,limit=limit)}

@tool
def suggest_standard_word(usage_description: str, clarification_hint: str = "") -> dict:
    """Given a description of how a concept/word is being used (not a name the user
    already picked), judge whether an existing standard word already covers it
    (existing_word_match) or propose a brand-new one (name/english_abbr/definition).
    Ambiguous descriptions get a clarifying question instead of a guess; answer it by
    calling again with clarification_hint set to the chosen option label."""
    return suggest_word(usage_description,clarification_hint)

@tool
def prepare_word_registration(word_name: str, definition: str, english_abbr: str, requester: str,
                              conversation_id: str, is_format_word: bool = False,
                              domain_classification: str = "") -> dict:
    """Revalidate for duplicates/abbreviation collisions; save a 30-minute immutable
    confirmation payload for a new standard word. Show it to the user before submitting."""
    return word_registration.prepare(WordRegistrationInput(word_name=word_name,definition=definition,
        english_abbr=english_abbr,is_format_word=is_format_word,domain_classification=domain_classification,
        requester=requester,conversation_id=conversation_id))

@tool
def create_word_registration_request(confirmation_id: str, requester: str, conversation_id: str,
                                     confirmed: bool = False) -> dict:
    """Submit the displayed word payload only after explicit user confirmation.
    Produces PENDING_REVIEW, never an official standard. Repeated confirmation is idempotent."""
    return word_registration.submit(confirmation_id,requester,conversation_id,confirmed)

@tool
def get_word_registration_request(request_id: str, requester: str) -> dict:
    """Read a word request owned by the trusted Dify requester identity."""
    uuid.UUID(request_id)
    with db.connect() as conn:
        result=conn.execute("""SELECT id::text AS request_id,word_name,definition,english_abbr,status,created_at
            FROM word_registration_requests WHERE id=%s AND requester=%s""",(request_id,requester)).fetchone()
    return result or {"ok":False,"error":{"code":"REQUEST_NOT_FOUND"}}

@tool
def validate_standard_word_abbreviation(abbreviation: str) -> dict:
    """Check format and word-dictionary-wide uniqueness of a user-provided English
    abbreviation for a new standard word (separate namespace from term abbreviations)."""
    value,error=validate_word_abbreviation(abbreviation)
    return {"valid":error is None,"normalized":value,"error_code":error}

@tool
def compare_term_definition(new_term: str, new_definition: str, existing_term_id: str) -> dict:
    """Compare definitions against a real catalog term; return semantic relation/evidence. LLM failure returns UNCERTAIN."""
    return compare(new_term,new_definition,existing_term_id)

@tool
def prepare_term_registration(term_name: str, definition: str, domain: str, requester: str,
                              conversation_id: str, synonyms: list[str] | None = None) -> dict:
    """Revalidate and compare candidates; save a 30-minute immutable confirmation payload.
    requester/conversation_id must come from Dify system variables, not user-provided identity.
    Show payload and assessment to the user; do not submit on the same turn.
    """
    return registration.prepare(RegistrationInput(term_name=term_name,definition=definition,domain=domain,
        requester=requester,conversation_id=conversation_id,synonyms=synonyms or []))

@tool
def create_term_registration_request(confirmation_id: str, requester: str, conversation_id: str,
                                     confirmed: bool = False, english_abbr: str = "") -> dict:
    """Submit the displayed payload only after explicit user confirmation on a subsequent turn.
    Produces PENDING_REVIEW, never an official standard. Repeated confirmation is idempotent.
    """
    return registration.submit(confirmation_id,requester,conversation_id,confirmed,english_abbr)

@tool
def check_term_guideline(term_name: str) -> dict:
    """RAG check of a candidate term name against the vectorized standard_guide.md.
    Catches word-choice rules (e.g. no standalone generic nouns) that validate_term_name
    cannot express. Returns the retrieved guideline excerpts as evidence alongside the verdict.
    """
    return check_guideline(term_name)

@tool
def suggest_english_abbreviation(term_name: str) -> dict:
    """Recommend an English abbreviation for a Korean standard term, grounded in
    standard_guide.md's abbreviation rules (RAG) plus every abbreviation already
    assigned in the catalog, for consistency. The user confirms or overrides it."""
    return suggest_abbreviation(term_name)

@tool
def validate_english_abbreviation(abbreviation: str) -> dict:
    """Check format (uppercase/digits/underscore, <=20 chars) and catalog-wide uniqueness
    of a user-provided English abbreviation."""
    value,error=validate_abbreviation(abbreviation)
    return {"valid":error is None,"normalized":value,"error_code":error}

@tool
def cancel_term_registration(requester: str, conversation_id: str) -> dict:
    """Invalidate unsubmitted confirmations on cancel/restart/edit."""
    return registration.cancel(requester,conversation_id)

@tool
def get_registration_request(request_id: str, requester: str) -> dict:
    """Read a request owned by the trusted Dify requester identity."""
    uuid.UUID(request_id)
    with db.connect() as conn:
        result=conn.execute("SELECT id::text AS request_id,term_name,definition,domain,status,created_at FROM registration_requests WHERE id=%s AND requester=%s",(request_id,requester)).fetchone()
    return result or {"ok":False,"error":{"code":"REQUEST_NOT_FOUND"}}

@tool
def register_term(standard_name: str, definition: str, synonyms: list[str] | None = None) -> dict:
    """Legacy safety wrapper. Use prepare_term_registration then create_term_registration_request."""
    return {"created":False,"code":"CONFIRMATION_FLOW_REQUIRED",
        "next_tools":["prepare_term_registration","create_term_registration_request"]}

@tool
def terminology_health() -> dict:
    """Report configuration and real catalog counts without exposing secrets."""
    from .credentials import api_key
    from .config import EMBEDDING_MODEL, LLM_MODEL
    with db.connect() as conn:
        count=conn.execute("SELECT count(*) AS count FROM standard_terms WHERE status='ACTIVE'").fetchone()["count"]
        domains=conn.execute("SELECT count(*) AS count FROM domains WHERE status='ACTIVE'").fetchone()["count"]
    return {"ok":True,"catalog_count":count,"domain_count":domains,"embedding_model":EMBEDDING_MODEL,
        "definition_model":LLM_MODEL,"definition_model_configured":bool(api_key()),
        "catalog_ready":bool(count),"warning":None if count else "REFERENCE_DATA_IMPORT_REQUIRED"}

@tool
def get_conversation_state(conversation_id: str, requester: str) -> dict:
    """Read persisted workflow state. Supply Dify system conversation/user identifiers."""
    from .conversation import get_state
    return get_state(conversation_id,requester)

@tool
def apply_conversation_action(conversation_id: str, requester: str, expected_revision: int,
                              intent: str, value: str = "", confirmed: bool = False) -> dict:
    """Execute one Dify-interpreted action. Never classify a help/query/edit as set_definition.
    One action per user turn. Final confirmation must be a later turn than preparation.
    Allowed intents: propose_term,confirm_term,set_domain,set_definition,set_abbreviation,
    confirm_registration,show_candidates,edit_term,edit_domain,edit_definition,cancel,restart,help,unknown,
    propose_word,confirm_word,set_word_abbreviation (the last three drive the standard-word
    request sub-flow, entered standalone or automatically when a term name doesn't fully
    decompose into known standard_words).
    """
    from .conversation import apply
    return apply(conversation_id,requester,expected_revision,{"intent":intent,"value":value,"confirmed":confirmed})

@tool
def apply_dify_turn(conversation_id: str, requester: str, action_json: str) -> dict:
    """Execute ONE classified action per Dify chat turn. action_json fields:
    intent, value, confirmed (boolean), expected_revision (integer).
    Identity comes exclusively from Dify system variables. JSON is data, not code.
    """
    import json
    from .conversation import apply, ConversationAction
    if len(action_json)>12000:
        raise ValueError("Action too large")
    parsed=json.loads(action_json)
    revision=parsed.pop("expected_revision")
    if type(revision) is not int or revision<0 or type(parsed.get("confirmed",False)) is not bool:
        raise ValueError("Invalid revision/confirmation type")
    action=ConversationAction.model_validate(parsed)
    return apply(conversation_id,requester,revision,action.model_dump())

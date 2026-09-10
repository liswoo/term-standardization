"""MCP contracts. Chat wording and intent interpretation live in Dify."""
from functools import wraps
from typing import Any
import logging
import uuid
from mcp.server.mcpserver import MCPServer
from . import db, registration
from .abbreviation import suggest_abbreviation, validate_abbreviation
from .guideline import check_guideline
from .naming import morphology
from .schemas import RegistrationInput
from .search import search, relational, vector_search, validate_name, get_term, domain_usage
from .comparison import compare

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
        return {"domains":conn.execute("SELECT code,description,source FROM domains ORDER BY code").fetchall()}

@tool
def list_terms(limit: int = 100) -> dict:
    """List approved catalog terms plus non-rejected registration requests, most recent first, for dashboard display."""
    limit=min(max(limit,1),200)
    with db.connect() as conn:
        approved=conn.execute(
            "SELECT id::text AS id, name AS term_name, definition, domain, synonyms, english_abbr, 'APPROVED' AS status, created_at "
            "FROM standard_terms ORDER BY created_at DESC LIMIT %s",(limit,)).fetchall()
        pending=conn.execute(
            "SELECT id::text AS id, term_name, definition, domain, synonyms, english_abbr, status, created_at "
            "FROM registration_requests WHERE status!='REJECTED' ORDER BY created_at DESC LIMIT %s",(limit,)).fetchall()
        descriptions={r["code"]:r["description"] for r in conn.execute("SELECT code,description FROM domains").fetchall()}
    combined=approved+pending
    for r in combined:
        r["domain_description"]=descriptions.get(r["domain"])
    combined.sort(key=lambda r:r["created_at"],reverse=True)
    return {"terms":combined[:limit],"count":len(combined[:limit])}

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
        count=conn.execute("SELECT count(*) AS count FROM standard_terms").fetchone()["count"]
        domains=conn.execute("SELECT count(*) AS count FROM domains").fetchone()["count"]
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
    confirm_registration,show_candidates,edit_term,edit_domain,edit_definition,cancel,restart,help,unknown.
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

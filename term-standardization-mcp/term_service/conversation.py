"""Deterministic transition executor. Dify supplies the interpreted intent and renders replies.
User messages are never implicitly stored as definitions. Trusted identities must be injected by Dify.
"""
from typing import Literal
from pydantic import Field
from psycopg.types.json import Jsonb
from . import db, registration
from .naming import strip_trailing_particle
from .schemas import Schema, RegistrationInput
from .search import validate_name, search, domain_usage

class ConversationAction(Schema):
    intent: Literal["propose_term","confirm_term","set_domain","set_definition","confirm_registration",
                    "show_candidates","edit_term","edit_domain","edit_definition","cancel","restart","help","unknown"]
    value: str = Field(default="",max_length=4000)
    confirmed: bool = False

def db_domain_codes():
    with db.connect() as conn:
        return conn.execute("SELECT code FROM domains").fetchall()

def get_state(conversation_id,requester):
    with db.connect() as conn:
        row=conn.execute("SELECT state,revision FROM conversation_state WHERE conversation_id=%s AND requester=%s",
            (conversation_id,requester)).fetchone()
    return row or {"state":{"stage":"awaiting_term_direct"},"revision":0}

def transition(state, action, requester, conversation_id):
    s=dict(state)
    stage=s.get("stage","awaiting_term_direct")
    a=ConversationAction.model_validate(action)
    if a.intent in {"help","unknown","show_candidates"}:
        extra={"domains":s["domains"]} if stage=="awaiting_domain_choice" and "domains" in s else {}
        return s,{"next_action":a.intent,"stage":stage,"candidates":s.get("search",{}).get("candidates",[]),**extra}
    if a.intent in {"cancel","restart"}:
        registration.cancel(requester,conversation_id)
        return {"stage":"awaiting_term_direct"},{"next_action":a.intent}
    if a.intent in {"propose_term","edit_term"}:
        if not a.value.strip() or len(a.value)>200:
            return s,{"error":"TERM_REQUIRED"}
        # A trailing case particle (e.g. "값을") is part of the request sentence, never
        # the term itself; drop it here so the user isn't asked to confirm-then-correct
        # something they never actually proposed.
        term_name=strip_trailing_particle(a.value.strip())
        if not term_name:
            return s,{"error":"TERM_REQUIRED"}
        registration.cancel(requester,conversation_id)
        return {"stage":"awaiting_term_confirm","term_name":term_name},{"next_action":"CONFIRM_EXTRACTED_TERM"}
    if a.intent=="confirm_term":
        if stage!="awaiting_term_confirm":
            return s,{"error":"UNEXPECTED_INTENT"}
        if not a.confirmed:
            return {"stage":"awaiting_term_direct"},{"next_action":"INPUT_TERM"}
        valid=validate_name(s["term_name"])
        s["validation"]=valid.model_dump()
        if not valid.valid:
            s["stage"]="awaiting_guideline_choice"
            return s,{"next_action":"CHOOSE_CORRECTION"}
        result=search(s["term_name"])
        s["search"]=result.model_dump()
        if result.match_type=="EXACT_MATCH":
            s["stage"]="existing_term_found"
            return s,{"next_action":"USE_EXISTING"}
        s["domains"]=domain_usage(s["term_name"],[c.term_id for c in result.candidates])
        s["stage"]="awaiting_domain_choice"
        return s,{"next_action":"CHOOSE_DOMAIN","prefer_existing":result.match_type=="SYNONYM_MATCH"}
    if a.intent=="edit_domain":
        if "term_name" not in s or "search" not in s:
            return s,{"error":"CONFIRM_TERM_FIRST"}
        registration.cancel(requester,conversation_id)
        for name in ["domain","definition","preparation"]:
            s.pop(name,None)
        s["stage"]="awaiting_domain_choice"
        return s,{"next_action":"CHOOSE_DOMAIN"}
    if a.intent=="set_domain":
        if stage!="awaiting_domain_choice" or not a.value.strip() or len(a.value)>100:
            return s,{"error":"UNEXPECTED_OR_INVALID_DOMAIN"}
        value=a.value.strip()
        # A domain must be an actual catalog code (recommended or any known domain),
        # never free text the intent parser mistook for a selection (e.g. "제공해줘").
        known={d["code"] for d in s.get("domains",{}).get("known_domains",[])} or {r["code"] for r in db_domain_codes()}
        if value not in known:
            return s,{"error":"UNRECOGNIZED_DOMAIN","known_domains":sorted(known)}
        s["domain"]=value
        s["stage"]="awaiting_definition"
        return s,{"next_action":"INPUT_DEFINITION"}
    if a.intent=="edit_definition":
        if not s.get("domain"):
            return s,{"error":"CHOOSE_DOMAIN_FIRST"}
        registration.cancel(requester,conversation_id)
        s.pop("preparation",None)
        s.pop("definition",None)
        s["stage"]="awaiting_definition"
        return s,{"next_action":"INPUT_DEFINITION"}
    if a.intent=="set_definition":
        if stage!="awaiting_definition":
            return s,{"error":"UNEXPECTED_INTENT"}
        p=RegistrationInput(term_name=s["term_name"],definition=a.value,domain=s["domain"],
            requester=requester,conversation_id=conversation_id)
        prepared=registration.prepare(p)
        s["definition"]=p.definition
        s["preparation"]=prepared
        s["stage"]="awaiting_confirm" if prepared.get("ready") else "definition_blocked"
        return s,{"next_action":"FINAL_CONFIRMATION" if prepared.get("ready") else "EXPLAIN_BLOCK"}
    if a.intent=="confirm_registration":
        if stage!="awaiting_confirm" or not s.get("preparation",{}).get("ready"):
            return s,{"error":"FINAL_CONFIRMATION_NOT_READY"}
        if not a.confirmed:
            registration.cancel(requester,conversation_id)
            s["stage"]="cancelled"
            return s,{"next_action":"CANCELLED"}
        result=registration.submit(s["preparation"]["confirmation_id"],requester,conversation_id,True)
        s["registration"]=result
        # A failed submit() must not leave the conversation parked in
        # awaiting_confirm: preparation.ready is still true, so a repeated
        # "네, 등록해주세요" would replay the same confirmation_id and hit the
        # exact same failure (e.g. PENDING_REQUEST_ALREADY_EXISTS) forever.
        s["stage"]="submitted" if result.get("request_id") else "registration_failed"
        return s,{"next_action":"SHOW_REGISTRATION_RESULT"}
    return s,{"error":"UNEXPECTED_INTENT"}

def apply(conversation_id,requester,expected_revision,action):
    if not conversation_id or not requester or max(len(conversation_id),len(requester))>200:
        raise ValueError("Invalid conversation identity")
    with db.connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,1))",(conversation_id+"/"+requester,))
        row=conn.execute("SELECT state,revision FROM conversation_state WHERE conversation_id=%s AND requester=%s",
            (conversation_id,requester)).fetchone()
        revision=row["revision"] if row else 0
        state=row["state"] if row else {"stage":"awaiting_term_direct"}
        if revision!=expected_revision:
            return {"applied":False,"code":"STALE_REVISION","revision":revision,"state":state}
        new_state,result=transition(state,action,requester,conversation_id)
        conn.execute("""INSERT INTO conversation_state(conversation_id,requester,revision,state) VALUES(%s,%s,%s,%s)
            ON CONFLICT(conversation_id,requester) DO UPDATE SET revision=excluded.revision,state=excluded.state,updated_at=now()""",
            (conversation_id,requester,revision+1,Jsonb(new_state)))
    return {"applied":True,"revision":revision+1,"state":new_state,**result}

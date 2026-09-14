"""Deterministic transition executor. Dify supplies the interpreted intent and renders replies.
User messages are never implicitly stored as definitions. Trusted identities must be injected by Dify.
"""
from typing import Literal
from pydantic import Field
from psycopg.types.json import Jsonb
from . import db, registration, word_registration
from .abbreviation import suggest_abbreviation, validate_abbreviation, validate_word_abbreviation
from .definition_suggestion import suggest_definition
from .guideline import check_guideline
from .naming import strip_trailing_particle, segment_words
from .schemas import Schema, RegistrationInput, WordRegistrationInput
from .search import validate_name, search, domain_usage
from .word_suggestion import suggest_word

class ConversationAction(Schema):
    intent: Literal["propose_term","confirm_term","set_domain","set_definition","set_abbreviation","confirm_registration",
                    "show_candidates","edit_term","edit_domain","edit_definition","cancel","restart","help","unknown",
                    "propose_word","confirm_word","set_word_abbreviation"]
    value: str = Field(default="",max_length=4000)
    confirmed: bool = False

def db_domain_codes():
    with db.connect() as conn:
        return conn.execute("SELECT code FROM domains WHERE status='ACTIVE'").fetchall()

def _word_lookup():
    with db.connect() as conn:
        rows=conn.execute("SELECT normalized_name,name,english_abbr FROM standard_words WHERE status='ACTIVE'").fetchall()
    return {r["normalized_name"]:r for r in rows}

def _resume_or_finish_word_flow(s, result_stage):
    """A word request can start two ways: standalone, or embedded inside a term
    registration whose name didn't fully decompose into known standard_words
    (see confirm_term below). resume_term marks the latter - once the word
    question is resolved (reused an existing word, or a new one was submitted
    for review), jump back to exactly where the term flow paused instead of
    making the user re-state the term."""
    resume=s.pop("resume_term",None)
    for name in ["word_usage_description","word_suggestion","word_registration_payload"]:
        s.pop(name,None)
    if resume:
        s["definition_suggestion"]=suggest_definition(resume["term_name"]).model_dump()
        s["stage"]="awaiting_definition"
        return s,{"next_action":"INPUT_DEFINITION","resumed_from_word_request":True}
    s["stage"]=result_stage
    return s,{"next_action":"SHOW_WORD_RESULT"}

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
            # Stale from a previous, different candidate term this turn is replacing;
            # leaving it would let render show an old guideline reason for a mechanical
            # violation on a brand new term.
            s.pop("guideline_check",None)
            s["stage"]="awaiting_guideline_choice"
            return s,{"next_action":"CHOOSE_CORRECTION"}
        # Mechanical validate() only checks syntax (length/character-set/noun-ending);
        # it cannot express a word-choice rule like "no standalone generic nouns" from
        # standard_guide.md section 2-1. This RAG check catches exactly that gap.
        guideline=check_guideline(s["term_name"])
        s["guideline_check"]=guideline.model_dump()
        if not guideline.compliant:
            s["stage"]="awaiting_guideline_choice"
            return s,{"next_action":"CHOOSE_CORRECTION"}
        result=search(s["term_name"])
        s["search"]=result.model_dump()
        # A registered synonym IS the same concept as its primary term by
        # definition (same definition/domain, just an alternate label) - there
        # is no such thing as a legitimately different "new" term sharing that
        # exact name, so this blocks immediately just like EXACT_MATCH instead
        # of sending the user through the whole domain/definition/abbreviation
        # flow only to (hopefully) get caught later by compare().
        if result.match_type in ("EXACT_MATCH","SYNONYM_MATCH"):
            s["stage"]="existing_term_found"
            return s,{"next_action":"USE_EXISTING"}
        # A term already awaiting review must not be silently re-collected through
        # definition/domain/abbreviation only to fail at the final submit() step
        # (PENDING_REQUEST_ALREADY_EXISTS) - catch it here, right after confirming
        # the name, same as EXACT_MATCH does for already-approved terms.
        pending=registration.find_pending(s["term_name"])
        if pending:
            s["pending_request"]=pending
            s["stage"]="pending_request_found"
            return s,{"next_action":"PENDING_REQUEST_FOUND"}
        # A standard term is supposed to be a pure concatenation of standard words
        # (e.g. "지사"+"분류"+"코드" -> "지사분류코드") - if the name doesn't fully
        # decompose into known standard_words, some part of it names a concept with
        # no official word yet. Silently letting suggest_abbreviation() invent an
        # abbreviation for that part later means a new word gets coined with no
        # governance at all. Catch it here instead and route into the word-request
        # sub-flow first; confirm_word/set_word_abbreviation resume back to
        # suggest_definition() below once the word question is resolved.
        # Only applies once a word dictionary actually exists - an empty one (a
        # fresh install, or a synthetic scenario catalog with no words at all)
        # means "cannot check", not "everything is a gap", same as how an empty
        # standard_terms corpus never fails EXACT_MATCH/semantic search.
        word_lookup=_word_lookup()
        if word_lookup:
            matched,full_match=segment_words(s["term_name"],word_lookup)
            if not full_match:
                s["resume_term"]={"term_name":s["term_name"]}
                s["stage"]="awaiting_word_meaning"
                return s,{"next_action":"REQUEST_NEW_WORD","matched_words":[w["name"] for w in matched]}
        # Definition comes before domain (see set_definition below): the domain
        # step's own comparison-group evidence is far stronger once a definition
        # exists to search with, not just the bare name. Writing a definition
        # from scratch is also real friction, so propose one (or ask a clarifying
        # question first, if the name is genuinely ambiguous) here too.
        s["definition_suggestion"]=suggest_definition(s["term_name"]).model_dump()
        s["stage"]="awaiting_definition"
        return s,{"next_action":"INPUT_DEFINITION"}
    if a.intent=="edit_definition":
        if "term_name" not in s:
            return s,{"error":"CONFIRM_TERM_FIRST"}
        registration.cancel(requester,conversation_id)
        # Domain evidence was built from the OLD definition's search results, so
        # editing the definition invalidates it too - back to square one on both.
        for name in ["domain","domains","preparation","definition","abbreviation_suggestion","english_abbr"]:
            s.pop(name,None)
        s["definition_suggestion"]=suggest_definition(s["term_name"]).model_dump()
        s["stage"]="awaiting_definition"
        return s,{"next_action":"INPUT_DEFINITION"}
    if a.intent=="set_definition":
        if stage!="awaiting_definition":
            return s,{"error":"UNEXPECTED_INTENT"}
        suggestion=s.get("definition_suggestion") or {}
        if suggestion.get("ambiguous") and a.value in suggestion.get("options",[]):
            # This is an answer to the clarifying question, not a final definition -
            # re-propose with that hint instead of registering the option label
            # itself as the term's definition.
            s["definition_suggestion"]=suggest_definition(s["term_name"],clarification_hint=a.value).model_dump()
            return s,{"next_action":"INPUT_DEFINITION"}
        # Full shape/length validation (RegistrationInput) happens once at
        # set_domain below, where term_name/definition/domain are all finally
        # known together - domain isn't chosen yet at this point.
        s["definition"]=a.value
        # Now that a definition exists, search with it (not just the bare name)
        # for real domain-recommendation evidence - see the comment on confirm_term.
        result=search(s["term_name"],a.value,limit=30)
        s["search"]=result.model_dump()
        # search() merges up to `limit` matches from EACH of 4 independent groups
        # (exact/synonym/semantic/lexical), so combined candidates can exceed 30
        # even though each group individually respects the limit - domain_usage()
        # hard-caps at 30 comparison IDs (a real catalog easily produces more than
        # that once every group actually has candidates, unlike the old handful of
        # synthetic terms). Truncate here, keeping search()'s own priority order
        # (exact > synonym > semantic > lexical) intact.
        s["domains"]=domain_usage(s["term_name"],[c.term_id for c in result.candidates][:30])
        s["stage"]="awaiting_domain_choice"
        return s,{"next_action":"CHOOSE_DOMAIN"}
    if a.intent=="edit_domain":
        if "term_name" not in s or not s.get("definition"):
            return s,{"error":"SET_DEFINITION_FIRST"}
        registration.cancel(requester,conversation_id)
        for name in ["domain","preparation","abbreviation_suggestion","english_abbr"]:
            s.pop(name,None)
        result=search(s["term_name"],s["definition"],limit=30)
        s["search"]=result.model_dump()
        s["domains"]=domain_usage(s["term_name"],[c.term_id for c in result.candidates][:30])
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
        p=RegistrationInput(term_name=s["term_name"],definition=s["definition"],domain=value,
            requester=requester,conversation_id=conversation_id)
        prepared=registration.prepare(p)
        s["preparation"]=prepared
        if not prepared.get("ready"):
            s["stage"]="definition_blocked"
            return s,{"next_action":"EXPLAIN_BLOCK"}
        # A Korean term and its English abbreviation are registered as one set; recommend
        # one now so the user isn't left to invent a compliant abbreviation unaided.
        s["abbreviation_suggestion"]=suggest_abbreviation(s["term_name"]).model_dump()
        s.pop("english_abbr",None)
        s["stage"]="awaiting_abbreviation"
        return s,{"next_action":"CONFIRM_ABBREVIATION"}
    if a.intent=="set_abbreviation":
        if stage!="awaiting_abbreviation":
            return s,{"error":"UNEXPECTED_INTENT"}
        value,error=validate_abbreviation(a.value)
        if error:
            return s,{"error":error}
        s["english_abbr"]=value
        s["stage"]="awaiting_confirm"
        return s,{"next_action":"FINAL_CONFIRMATION"}
    if a.intent=="confirm_registration":
        if stage!="awaiting_confirm" or not s.get("preparation",{}).get("ready") or not s.get("english_abbr"):
            return s,{"error":"FINAL_CONFIRMATION_NOT_READY"}
        if not a.confirmed:
            registration.cancel(requester,conversation_id)
            s["stage"]="cancelled"
            return s,{"next_action":"CANCELLED"}
        result=registration.submit(s["preparation"]["confirmation_id"],requester,conversation_id,True,
            english_abbr=s["english_abbr"])
        s["registration"]=result
        # A failed submit() must not leave the conversation parked in
        # awaiting_confirm: preparation.ready is still true, so a repeated
        # "네, 등록해주세요" would replay the same confirmation_id and hit the
        # exact same failure (e.g. PENDING_REQUEST_ALREADY_EXISTS) forever.
        s["stage"]="submitted" if result.get("request_id") else "registration_failed"
        return s,{"next_action":"SHOW_REGISTRATION_RESULT"}
    if a.intent=="propose_word":
        # Fires from ANY stage - a standalone "이런 개념을 단어로 추천해줘" request,
        # or the first/subsequent description at the embedded awaiting_word_meaning
        # stage confirm_term routed into above. Never touches term_name/resume_term,
        # so an embedded word request keeps its place in the paused term flow.
        value=a.value.strip()
        if not value:
            return s,{"error":"WORD_MEANING_REQUIRED"}
        prior=s.get("word_suggestion") or {}
        if prior.get("ambiguous") and value in prior.get("options",[]):
            # Answer to a clarifying question, not a fresh description.
            suggestion=suggest_word(s["word_usage_description"],clarification_hint=value).model_dump()
        else:
            s["word_usage_description"]=value
            suggestion=suggest_word(value).model_dump()
        s["word_suggestion"]=suggestion
        s["stage"]="awaiting_word_confirm"
        return s,{"next_action":"CONFIRM_WORD"}
    if a.intent=="confirm_word":
        if stage!="awaiting_word_confirm":
            return s,{"error":"UNEXPECTED_INTENT"}
        if not a.confirmed:
            s["stage"]="awaiting_word_meaning"
            return s,{"next_action":"INPUT_WORD_MEANING"}
        suggestion=s.get("word_suggestion") or {}
        if suggestion.get("existing_word_match"):
            # Nothing to register - the meaning is already covered by an existing
            # word. Record which one resolved this so the result can name it.
            s["resolved_word"]={"name":suggestion["existing_word_match"],"reused":True}
            return _resume_or_finish_word_flow(s,"word_reused")
        if not (suggestion.get("name") and suggestion.get("english_abbr") and suggestion.get("definition")):
            return s,{"error":"WORD_SUGGESTION_NOT_READY"}
        s["word_registration_payload"]={"word_name":suggestion["name"],"definition":suggestion["definition"],
            "english_abbr":suggestion["english_abbr"],"is_format_word":suggestion.get("is_format_word",False)}
        s["stage"]="awaiting_word_abbreviation"
        return s,{"next_action":"CONFIRM_WORD_ABBREVIATION"}
    if a.intent=="set_word_abbreviation":
        if stage!="awaiting_word_abbreviation":
            return s,{"error":"UNEXPECTED_INTENT"}
        value,error=validate_word_abbreviation(a.value)
        if error:
            return s,{"error":error}
        payload=s.get("word_registration_payload") or {}
        p=WordRegistrationInput(word_name=payload["word_name"],definition=payload["definition"],
            english_abbr=value,is_format_word=payload.get("is_format_word",False),
            requester=requester,conversation_id=conversation_id)
        prepared=word_registration.prepare(p)
        if not prepared.get("ready"):
            s["word_prepare_error"]=prepared
            s["stage"]="word_request_blocked"
            return s,{"next_action":"EXPLAIN_WORD_BLOCK"}
        result=word_registration.submit(prepared["confirmation_id"],requester,conversation_id,True)
        s["word_registration"]=result
        return _resume_or_finish_word_flow(s,"word_submitted" if result.get("request_id") else "word_registration_failed")
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

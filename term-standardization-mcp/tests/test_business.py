import os
import uuid
from concurrent.futures import ThreadPoolExecutor
import pytest
from term_service import db, registration, conversation
from term_service.config import ROOT
from term_service.naming import validate, morphology, strip_trailing_particle
from term_service.search import search, domain_usage, validate_name
from term_service.schemas import AbbreviationResult, DefinitionSuggestionResult, RegistrationInput
from term_service.comparison import compare
from manage import import_guideline

def insert_guideline_chunk(section,content):
    from term_service.config import EMBEDDING_MODEL
    from term_service.embeddings import embed
    vector=embed(section+" : "+content)
    with db.connect() as conn:
        conn.execute("""INSERT INTO guideline_chunks(id,section,content,embedding,embedding_model,source)
            VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(section) DO UPDATE SET content=excluded.content""",
            (str(uuid.uuid4()),section,content,vector,EMBEDDING_MODEL,"TEST_FIXTURE_NOT_PRODUCTION"))

@pytest.mark.parametrize("name",["일일권장칼로리","체질량지수(BMI)","나이","국가"])
def test_valid_names(name):
    assert validate(name).valid

@pytest.mark.parametrize("name",["BMI","123","!!","가","가"*21,"용어를","등록해주세요"])
def test_invalid_names(name):
    assert not validate(name).valid

def test_real_morphology():
    assert len(morphology("일일권장칼로리")["morphemes"])>=3

@pytest.mark.parametrize("raw,expected",[
    ("식사만족도점수를","식사만족도점수"),
    ("값을","값"),
    ("용어는","용어"),
    ("일일권장칼로리","일일권장칼로리"),  # no trailing particle: unchanged
    ("BMI","BMI"),
])
def test_strip_trailing_particle(raw,expected):
    assert strip_trailing_particle(raw)==expected

def test_propose_term_stores_particle_free_name():
    # Regression for the bug where CLASSIFY's extracted value kept a trailing
    # particle (e.g. "식사만족도점수를"), forcing the user to confirm a name they
    # never actually proposed before validate_name() caught it downstream.
    def apply(revision,intent,value="",confirmed=False):
        return conversation.apply("particle-conv","user",revision,{"intent":intent,"value":value,"confirmed":confirmed})
    result=apply(0,"propose_term","값을")
    assert result["state"]["term_name"]=="값"
    assert result["state"]["stage"]=="awaiting_term_confirm"
    result=apply(1,"edit_term","식사만족도점수를")
    assert result["state"]["term_name"]=="식사만족도점수"

def test_search_empty_is_not_new():
    result=search("일일권장칼로리")
    assert result.match_type=="UNDETERMINED"
    assert "EMPTY_REFERENCE_CATALOG" in result.warnings
    assert domain_usage("일일권장칼로리",[])["recommended_domain"] is None

def test_actual_rdb_and_vector(catalog):
    assert search("일일섭취칼로리").match_type=="EXACT_MATCH"
    assert search("하루섭취열량").match_type=="SYNONYM_MATCH"
    result=search("일일권장칼로리")
    assert result.semantic_matches
    assert all(c.similarity is not None for c in result.semantic_matches)
    assert "체질량지수" in validate_name("BMI").suggestions
    assert search("' OR 1=1 --").exact_matches==[]

def test_distribution_uses_real_deduplicated_rows(catalog):
    ids=list(catalog.values())
    result=domain_usage("칼로리",ids+[ids[0]])
    assert result["sample_size"]==4
    assert result["distribution"][0]["ratio"]==0.75
    assert result["recommended_domain"]=="수N7"

def test_vector_failure_is_not_new(catalog,monkeypatch):
    import term_service.search as module
    def fail(*args,**kwargs):
        raise RuntimeError("unavailable")
    monkeypatch.setattr(module,"vector_search",fail)
    result=module.search("다른개념")
    assert not result.search_complete
    assert result.match_type=="UNDETERMINED"

def test_definition_identical_and_failure(catalog,monkeypatch):
    existing_id=catalog["일일섭취칼로리"]
    assert compare("섭취열량","한 사람이 하루 동안 음식으로 실제 섭취한 에너지의 총량",existing_id).relation=="SAME_MEANING"
    import term_service.comparison as module
    monkeypatch.setattr(module,"api_key",lambda:None)
    assert compare("권장칼로리","하루 권장 기준 에너지량",existing_id).relation=="UNCERTAIN"

def payload(name="일일권장칼로리",who="test-user",conv="test-conversation"):
    return RegistrationInput(term_name=name,definition="한 사람이 하루에 권장받는 에너지의 기준량",
        domain="수N7",requester=who,conversation_id=conv)

def test_confirm_and_idempotency():
    prepared=registration.prepare(payload())
    assert prepared["ready"]
    ident=prepared["confirmation_id"]
    assert not registration.submit(ident,"test-user","test-conversation",False)["created"]
    assert not registration.submit(ident,"wrong-user","test-conversation",True)["created"]
    result=registration.submit(ident,"test-user","test-conversation",True)
    assert result["status"]=="PENDING_REVIEW"
    assert not result["is_official_standard"]
    assert registration.submit(ident,"test-user","test-conversation",True)["idempotent_replay"]
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM standard_terms").fetchone()["n"]==0

def test_edit_invalidates_confirmation():
    first=registration.prepare(payload())
    second=registration.prepare(payload("권장에너지"))
    assert second["ready"]
    assert registration.submit(first["confirmation_id"],"test-user","test-conversation",True)["code"]=="CONFIRMATION_EXPIRED_OR_CANCELLED"

def test_concurrent_duplicate_requests():
    one=registration.prepare(payload(conv="first"))
    two=registration.prepare(payload(conv="second"))
    with ThreadPoolExecutor(2) as pool:
        futures=[pool.submit(registration.submit,p["confirmation_id"],"test-user",c,True) for p,c in [(one,"first"),(two,"second")]]
        results=[f.result() for f in futures]
    assert sum(r["created"] for r in results)==1

def test_catalog_change_invalidates_confirmation():
    prepared=registration.prepare(payload())
    with db.connect() as conn:
        conn.execute("INSERT INTO domains(code,source) VALUES('신규도메인','TEST')")
    assert registration.submit(prepared["confirmation_id"],"test-user","test-conversation",True)["code"]=="CATALOG_CHANGED_REVALIDATE"

def test_exact_registration_blocked(catalog):
    assert registration.prepare(payload("일일섭취칼로리"))["code"]=="EXACT_MATCH"

def test_same_meaning_blocked_carries_matched_term(catalog):
    # Regression: SAME_MEANING used to omit `search`, so the matched existing
    # term's own name/definition/domain never reached rendering - only an opaque
    # existing_term_id in `comparisons`, unlike the EXACT_MATCH branch above.
    duplicate=RegistrationInput(term_name="섭취열량",definition="한 사람이 하루 동안 음식으로 실제 섭취한 에너지의 총량",
        domain="수N7",requester="test-user",conversation_id="test-conversation")
    prepared=registration.prepare(duplicate)
    assert prepared["code"]=="SAME_MEANING"
    assert any(c["relation"]=="SAME_MEANING" for c in prepared["comparisons"])
    matched_id=next(c["existing_term_id"] for c in prepared["comparisons"] if c["relation"]=="SAME_MEANING")
    candidate_ids={c["term_id"] for c in prepared["search"]["candidates"]}
    assert matched_id in candidate_ids

def test_multiturn_help_does_not_become_definition(monkeypatch):
    # Abbreviation suggestion calls the real LLM; stub it so this stays a free,
    # deterministic test like the rest of the suite (see suggest_abbreviation's
    # own unavailable-path test below for the paid-call boundary).
    monkeypatch.setattr(conversation,"suggest_abbreviation",
        lambda term_name: AbbreviationResult(abbreviation="TEST_ABBR",rationale="테스트 고정값",method="test_stub"))
    with db.connect() as conn:
        conn.execute("INSERT INTO domains(code,description,source) VALUES('수N7','테스트 숫자 도메인','TEST')")
    def apply(revision,intent,value="",confirmed=False):
        return conversation.apply("conversation","user",revision,{"intent":intent,"value":value,"confirmed":confirmed})
    assert apply(0,"propose_term","일일권장칼로리")["state"]["stage"]=="awaiting_term_confirm"
    assert apply(1,"confirm_term",confirmed=True)["state"]["stage"]=="awaiting_domain_choice"
    assert apply(2,"set_domain","수N7")["state"]["stage"]=="awaiting_definition"
    result=apply(3,"show_candidates","잠깐, 기존 용어 정의 다시 보여줘")
    assert "definition" not in result["state"]
    result=apply(4,"set_definition","하루에 섭취하도록 권장하는 에너지 기준량")
    assert result["state"]["stage"]=="awaiting_abbreviation"
    assert result["state"]["abbreviation_suggestion"]["abbreviation"]=="TEST_ABBR"
    assert apply(5,"help")["state"]["stage"]=="awaiting_abbreviation"
    result=apply(6,"set_abbreviation","test_abbr")
    assert result["state"]["stage"]=="awaiting_confirm"
    assert result["state"]["english_abbr"]=="TEST_ABBR"
    assert apply(7,"help")["state"]["stage"]=="awaiting_confirm"
    assert apply(8,"confirm_registration",confirmed=True)["state"]["stage"]=="submitted"
    assert not apply(8,"confirm_registration",confirmed=True)["applied"]

def test_confirm_term_detects_already_pending_request(monkeypatch):
    # Regression: re-registering a term that is already PENDING_REVIEW used to
    # sail straight through confirm_term into a brand-new domain/definition/
    # abbreviation flow, only failing at the very last step (submit()'s
    # PENDING_REQUEST_ALREADY_EXISTS) - after the user redid the whole
    # conversation. confirm_term must catch this immediately, like EXACT_MATCH.
    monkeypatch.setattr(conversation,"suggest_abbreviation",
        lambda term_name: AbbreviationResult(abbreviation="TEST_ABBR",rationale="테스트 고정값",method="test_stub"))
    with db.connect() as conn:
        conn.execute("INSERT INTO domains(code,description,source) VALUES('수N7','테스트 숫자 도메인','TEST')")
    def apply(conv,revision,intent,value="",confirmed=False):
        return conversation.apply(conv,"user",revision,{"intent":intent,"value":value,"confirmed":confirmed})
    apply("first",0,"propose_term","일일운동시간")
    apply("first",1,"confirm_term",confirmed=True)
    apply("first",2,"set_domain","수N7")
    apply("first",3,"set_definition","하루 동안 실시한 신체 활동의 누적 시간")
    apply("first",4,"set_abbreviation","TEST_ABBR")
    result=apply("first",5,"confirm_registration",confirmed=True)
    assert result["state"]["stage"]=="submitted"

    apply("second",0,"propose_term","일일운동시간")
    result=apply("second",1,"confirm_term",confirmed=True)
    assert result["state"]["stage"]=="pending_request_found"
    assert result["state"]["pending_request"]["term_name"]=="일일운동시간"
    assert result["state"]["pending_request"]["english_abbr"]=="TEST_ABBR"
    # A different, brand new term must still register normally afterwards.
    result=apply("second",2,"propose_term","일일계단오름횟수")
    assert result["state"]["stage"]=="awaiting_term_confirm"

def test_check_guideline_no_index_is_compliant():
    from term_service.guideline import check_guideline
    result=check_guideline("정보")
    assert result.compliant
    assert result.method=="no_guideline_indexed"

def test_check_guideline_unavailable_when_no_api_key(monkeypatch):
    import term_service.guideline as module
    insert_guideline_chunk("2-1. 용어 전체 길이 기준","최소 길이는 공백 제외 2자 이상이어야 한다.")
    monkeypatch.setattr(module,"api_key",lambda:None)
    result=module.check_guideline("정보")
    assert result.compliant  # fails open, matching compare()'s UNCERTAIN-not-blocking philosophy
    assert result.method=="unavailable"
    assert result.error_code=="LLM_NOT_CONFIGURED"
    assert result.evidence  # retrieval itself is local (fastembed) and still ran

def test_validate_abbreviation_format():
    from term_service.abbreviation import validate_abbreviation
    value,error=validate_abbreviation("daily_rec_cal")
    assert value=="DAILY_REC_CAL" and error is None
    value,error=validate_abbreviation("가나다")
    assert value is None and error=="INVALID_ABBREVIATION_FORMAT"
    value,error=validate_abbreviation("D")
    assert value is None and error=="INVALID_ABBREVIATION_FORMAT"

def test_validate_abbreviation_uniqueness(catalog):
    from term_service.abbreviation import validate_abbreviation
    with db.connect() as conn:
        conn.execute("UPDATE standard_terms SET english_abbr='BMI' WHERE name='체질량지수'")
    value,error=validate_abbreviation("bmi")
    assert value is None and error=="ABBREVIATION_ALREADY_USED"

def test_suggest_abbreviation_unavailable_when_no_api_key(monkeypatch):
    import term_service.abbreviation as module
    monkeypatch.setattr(module,"api_key",lambda:None)
    result=module.suggest_abbreviation("일일권장열량")
    assert result.abbreviation==""
    assert result.method=="unavailable"
    assert result.error_code=="LLM_NOT_CONFIGURED"

def test_suggest_definition_unavailable_when_no_api_key(monkeypatch):
    import term_service.definition_suggestion as module
    monkeypatch.setattr(module,"api_key",lambda:None)
    result=module.suggest_definition("일일권장열량","수N7")
    assert result.definition==""
    assert not result.ambiguous
    assert result.method=="unavailable"
    assert result.error_code=="LLM_NOT_CONFIGURED"

def test_definition_clarification_round_trip(monkeypatch):
    # set_domain triggers a first suggest_definition call; if it comes back
    # ambiguous, picking one of its options must trigger a SECOND call (with
    # that pick as clarification_hint) rather than registering the short
    # option label itself as the term's definition. A stub with a call
    # counter stands in for the real (paid) LLM call, same pattern as
    # test_multiturn_help_does_not_become_definition's abbreviation stub.
    calls=[]
    def fake_suggest_definition(term_name,domain,clarification_hint=""):
        calls.append(clarification_hint)
        if not clarification_hint:
            return DefinitionSuggestionResult(ambiguous=True,question="실제 소모량인가요, 목표량인가요?",
                options=["실제 소모량 기준","목표로 설정한 소모량 기준"],method="test_stub")
        return DefinitionSuggestionResult(ambiguous=False,
            definition=f"{clarification_hint}으로 계산한 하루 소모 에너지량",rationale="테스트 고정값",method="test_stub")
    monkeypatch.setattr(conversation,"suggest_definition",fake_suggest_definition)
    monkeypatch.setattr(conversation,"suggest_abbreviation",
        lambda term_name: AbbreviationResult(abbreviation="TEST_ABBR",rationale="테스트 고정값",method="test_stub"))
    with db.connect() as conn:
        conn.execute("INSERT INTO domains(code,description,source) VALUES('수N7','테스트 숫자 도메인','TEST')")
    def apply(revision,intent,value="",confirmed=False):
        return conversation.apply("definition-conv","user",revision,{"intent":intent,"value":value,"confirmed":confirmed})
    apply(0,"propose_term","일일소모열량계산값")
    apply(1,"confirm_term",confirmed=True)
    result=apply(2,"set_domain","수N7")
    assert result["state"]["stage"]=="awaiting_definition"
    assert result["state"]["definition_suggestion"]["ambiguous"]
    assert len(calls)==1 and calls[0]==""
    # Picking one of the offered options must re-propose, not register the
    # option label as the definition.
    result=apply(3,"set_definition","실제 소모량 기준")
    assert result["state"]["stage"]=="awaiting_definition"
    assert not result["state"]["definition_suggestion"]["ambiguous"]
    assert "definition" not in result["state"]
    assert len(calls)==2 and calls[1]=="실제 소모량 기준"
    # Accepting the resulting confident suggestion (or typing anything else
    # that isn't one of the prior options) must proceed to registration.
    result=apply(4,"set_definition",result["state"]["definition_suggestion"]["definition"])
    assert result["state"]["stage"]=="awaiting_abbreviation"
    assert result["state"]["definition"]==calls[1]+"으로 계산한 하루 소모 에너지량"

def test_definition_suggestion_own_text_bypasses_suggestion(monkeypatch):
    # The user must always be able to just type their own definition, whether
    # or not a suggestion/question was ever offered.
    monkeypatch.setattr(conversation,"suggest_definition",
        lambda term_name,domain,clarification_hint="": DefinitionSuggestionResult(
            ambiguous=True,question="q",options=["A","B"],method="test_stub"))
    monkeypatch.setattr(conversation,"suggest_abbreviation",
        lambda term_name: AbbreviationResult(abbreviation="TEST_ABBR2",rationale="",method="test_stub"))
    with db.connect() as conn:
        conn.execute("INSERT INTO domains(code,description,source) VALUES('수N7','테스트 숫자 도메인','TEST') ON CONFLICT DO NOTHING")
    def apply(revision,intent,value="",confirmed=False):
        return conversation.apply("definition-conv-2","user",revision,{"intent":intent,"value":value,"confirmed":confirmed})
    apply(0,"propose_term","야간간식섭취열량")
    apply(1,"confirm_term",confirmed=True)
    apply(2,"set_domain","수N7")
    result=apply(3,"set_definition","늦은 밤에 추가로 섭취한 간식의 열량 총합")
    assert result["state"]["stage"]=="awaiting_abbreviation"
    assert result["state"]["definition"]=="늦은 밤에 추가로 섭취한 간식의 열량 총합"

@pytest.mark.skipif(os.getenv("RUN_LLM_TESTS")!="1",reason="Explicit low-volume paid API smoke test")
def test_real_guideline_blocks_generic_word():
    insert_guideline_chunk("2. 표준용어 작성 규칙",
        "지나치게 포괄적이거나 그 자체로 의미가 성립하지 않는 단어는 단독으로 표준용어가 될 수 없다. "
        "예: 값, 정보, 데이터, 항목, 구분, 내용, 사항 - 이런 단어는 반드시 앞에 대상을 특정하는 표준단어가 붙어야 한다.")
    with db.connect() as conn:
        conn.execute("INSERT INTO domains(code,description,source) VALUES('수N7','테스트 숫자 도메인','TEST')")
    def apply(revision,intent,value="",confirmed=False):
        return conversation.apply("guideline-conv","user",revision,{"intent":intent,"value":value,"confirmed":confirmed})
    apply(0,"propose_term","정보")
    result=apply(1,"confirm_term",confirmed=True)
    assert result["state"]["stage"]=="awaiting_guideline_choice"
    assert result["state"]["guideline_check"]["compliant"] is False

@pytest.mark.skipif(os.getenv("RUN_LLM_TESTS")!="1",reason="Explicit low-volume paid API smoke test")
def test_real_guideline_does_not_misjudge_noun_ending_as_particle():
    # Regression: the guideline LLM twice misjudged a term ending in a plain
    # noun ("일일운동시간", "수면만족도점수") as ending in a grammatical particle -
    # a rule the excerpt states verbatim and mechanical validate_name() already
    # enforces correctly - because the mechanical-rule text and the RAG-only
    # word-choice rule used to live in the same retrieved chunk. Uses the real
    # standard_guide.md (not a synthetic fixture chunk), since this specifically
    # tests that document's section split plus the SYSTEM prompt guardrail.
    from term_service.guideline import check_guideline
    import_guideline(ROOT/"data/standard_guide.md")
    for term in ["일일운동시간","수면만족도점수","체질량지수"]:
        result=check_guideline(term)
        assert result.compliant, f"{term} wrongly blocked: {result.reason}"

@pytest.mark.skipif(os.getenv("RUN_LLM_TESTS")!="1",reason="Explicit low-volume paid API smoke test")
def test_real_abbreviation_suggestion_reaches_confirm(catalog):
    with db.connect() as conn:
        conn.execute("INSERT INTO domains(code,description,source) VALUES('수N7','테스트 숫자 도메인','TEST') ON CONFLICT DO NOTHING")
    def apply(revision,intent,value="",confirmed=False):
        return conversation.apply("abbr-conv","user",revision,{"intent":intent,"value":value,"confirmed":confirmed})
    apply(0,"propose_term","일일평균걸음수")
    apply(1,"confirm_term",confirmed=True)
    apply(2,"set_domain","수N7")
    result=apply(3,"set_definition","하루 동안 걸은 평균 걸음 수")
    assert result["state"]["stage"]=="awaiting_abbreviation"
    assert result["state"]["abbreviation_suggestion"]["abbreviation"]
    result=apply(4,"set_abbreviation","DAILY_AVG_STEP")
    assert result["state"]["stage"]=="awaiting_confirm"
    assert result["state"]["english_abbr"]=="DAILY_AVG_STEP"

@pytest.mark.skipif(os.getenv("RUN_LLM_TESTS")!="1",reason="Explicit low-volume paid API smoke test")
def test_real_llm_definition_comparison(catalog):
    same=compare("하루권장칼로리","건강한 생활을 유지하기 위해 개인에게 권장하는 하루 에너지 섭취 기준량",catalog["일일권장열량"])
    different=compare("일일권장칼로리","건강 유지를 위해 하루에 섭취하도록 권장되는 에너지 기준량",catalog["일일섭취칼로리"])
    assert same.method=="structured_llm"
    assert same.relation in {"SAME_MEANING","UNCERTAIN"}
    assert different.method=="structured_llm"
    assert different.relation in {"RELATED_BUT_DISTINCT","UNCERTAIN"}
    print("LLM evidence:",same.model_dump(),different.model_dump())

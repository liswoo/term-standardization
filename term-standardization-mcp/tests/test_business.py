import os
import uuid
from concurrent.futures import ThreadPoolExecutor
import pytest
from term_service import db, registration, word_registration, conversation, auth
from term_service.config import ROOT
from term_service.naming import validate, morphology, strip_trailing_particle
from term_service.search import search, domain_usage, validate_name
from term_service.schemas import AbbreviationResult, DefinitionSuggestionResult, RegistrationInput
from term_service.comparison import compare
from term_service.word_suggestion import suggest_word
from term_service.tools import list_terms, list_standard_words
from term_service import domain_registration, mock_operations
from term_service.schemas import DomainRequestInput
from manage import import_guideline, create_admin, seed_mockops

def insert_guideline_chunk(section,content):
    from term_service.config import EMBEDDING_MODEL
    from term_service.embeddings import embed
    vector=embed(section+" : "+content)
    with db.connect() as conn:
        conn.execute("""INSERT INTO guideline_chunks(id,section,content,embedding,embedding_model,source)
            VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(section) DO UPDATE SET content=excluded.content""",
            (str(uuid.uuid4()),section,content,vector,EMBEDDING_MODEL,"TEST_FIXTURE_NOT_PRODUCTION"))

def insert_standard_word(name,english_abbr,definition=""):
    from term_service.config import EMBEDDING_MODEL
    from term_service.embeddings import embed
    from term_service.naming import key
    vector=embed(name+" : "+definition) if definition else embed(name)
    with db.connect() as conn:
        conn.execute("""INSERT INTO standard_words(id,name,normalized_name,english_abbr,definition,status,source,embedding,embedding_model)
            VALUES(%s,%s,%s,%s,%s,'ACTIVE','TEST_FIXTURE_NOT_PRODUCTION',%s,%s)
            ON CONFLICT(normalized_name) DO UPDATE SET english_abbr=excluded.english_abbr,definition=excluded.definition,
            embedding=excluded.embedding,embedding_model=excluded.embedding_model""",
            (str(uuid.uuid4()),name,key(name),english_abbr,definition,vector,EMBEDDING_MODEL))

def insert_pending_term(term_name,definition="테스트 정의",domain="수N7",requester="tester",status="PENDING_REVIEW"):
    from term_service.naming import key
    from psycopg.types.json import Jsonb
    with db.connect() as conn:
        prep_id=str(uuid.uuid4())
        conn.execute("""INSERT INTO registration_preparations(id,payload,assessment,requester,conversation_id,catalog_fingerprint,expires_at)
            VALUES(%s,%s,%s,%s,%s,%s,now()+interval '30 minutes')""",
            (prep_id,Jsonb({}),Jsonb({}),requester,"test-conv","TEST_FIXTURE_NOT_PRODUCTION"))
        conn.execute("""INSERT INTO registration_requests
            (id,preparation_id,term_name,normalized_name,definition,domain,synonyms,requester,conversation_id,assessment,status)
            VALUES(%s,%s,%s,%s,%s,%s,'{}',%s,%s,%s,%s)""",
            (str(uuid.uuid4()),prep_id,term_name,key(term_name),definition,domain,requester,"test-conv",Jsonb({}),status))

def insert_pending_word(word_name,definition="테스트 정의",requester="tester",status="PENDING_REVIEW"):
    from term_service.naming import key
    from psycopg.types.json import Jsonb
    with db.connect() as conn:
        prep_id=str(uuid.uuid4())
        conn.execute("""INSERT INTO word_registration_preparations(id,payload,assessment,requester,conversation_id,catalog_fingerprint,expires_at)
            VALUES(%s,%s,%s,%s,%s,%s,now()+interval '30 minutes')""",
            (prep_id,Jsonb({}),Jsonb({}),requester,"test-conv","TEST_FIXTURE_NOT_PRODUCTION"))
        conn.execute("""INSERT INTO word_registration_requests
            (id,preparation_id,word_name,normalized_name,definition,english_abbr,requester,conversation_id,assessment,status)
            VALUES(%s,%s,%s,%s,%s,'',%s,%s,%s,%s)""",
            (str(uuid.uuid4()),prep_id,word_name,key(word_name),definition,requester,"test-conv",Jsonb({}),status))

def insert_pending_domain_request(code,domain_group="테스트그룹",data_type="문자",requester="tester",status="PENDING_REVIEW",
                                   mapping_table=None,mapping_column=None):
    from psycopg.types.json import Jsonb
    with db.connect() as conn:
        prep_id=str(uuid.uuid4())
        conn.execute("""INSERT INTO domain_preparations(id,payload,assessment,requester,conversation_id,catalog_fingerprint,expires_at)
            VALUES(%s,%s,%s,%s,%s,%s,now()+interval '30 minutes')""",
            (prep_id,Jsonb({}),Jsonb({}),requester,"direct-form","TEST_FIXTURE_NOT_PRODUCTION"))
        conn.execute("""INSERT INTO domain_requests
            (id,preparation_id,code,domain_group,data_type,mapping_table,mapping_column,requester,conversation_id,assessment,status,is_personal_info)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (str(uuid.uuid4()),prep_id,code,domain_group,data_type,mapping_table,mapping_column,requester,"direct-form",
             Jsonb({}),status,bool(mapping_table)))

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
    monkeypatch.setattr(module,"llm_configured",lambda:False)
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

def test_confirm_term_blocks_exact_and_synonym_names(catalog):
    # A registered synonym IS the same concept as its primary term (same
    # definition/domain, just an alternate label) - confirm_term must block it
    # immediately just like EXACT_MATCH, instead of sending the user through
    # the whole domain/definition/abbreviation flow only to maybe get caught
    # later by compare(). "하루섭취열량" is a synonym of "일일섭취칼로리" in
    # the catalog fixture.
    def apply(conv,revision,intent,value="",confirmed=False):
        return conversation.apply(conv,"user",revision,{"intent":intent,"value":value,"confirmed":confirmed})
    apply("exact-conv",0,"propose_term","일일섭취칼로리")
    result=apply("exact-conv",1,"confirm_term",confirmed=True)
    assert result["state"]["stage"]=="existing_term_found"
    assert result["state"]["search"]["match_type"]=="EXACT_MATCH"

    apply("syn-conv",0,"propose_term","하루섭취열량")
    result=apply("syn-conv",1,"confirm_term",confirmed=True)
    assert result["state"]["stage"]=="existing_term_found"
    assert result["state"]["search"]["match_type"]=="SYNONYM_MATCH"

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
    # Abbreviation/definition suggestions call the real LLM; stub them so this
    # stays a free, deterministic test like the rest of the suite (see their
    # own unavailable-path tests below for the paid-call boundary).
    monkeypatch.setattr(conversation,"suggest_abbreviation",
        lambda term_name,extra_words=None: AbbreviationResult(abbreviation="TEST_ABBR",rationale="테스트 고정값",method="test_stub"))
    monkeypatch.setattr(conversation,"suggest_definition",
        lambda term_name,clarification_history=None: DefinitionSuggestionResult(ambiguous=False,definition="",rationale="",method="test_stub"))
    with db.connect() as conn:
        conn.execute("INSERT INTO domains(code,description,source) VALUES('수N7','테스트 숫자 도메인','TEST')")
    def apply(revision,intent,value="",confirmed=False):
        return conversation.apply("conversation","user",revision,{"intent":intent,"value":value,"confirmed":confirmed})
    assert apply(0,"propose_term","일일권장칼로리")["state"]["stage"]=="awaiting_term_confirm"
    # Definition now comes before domain: the domain step's own comparison-group
    # evidence is much stronger once a definition exists to search with.
    assert apply(1,"confirm_term",confirmed=True)["state"]["stage"]=="awaiting_definition"
    result=apply(2,"show_candidates","잠깐, 기존 용어 정의 다시 보여줘")
    assert "definition" not in result["state"]
    result=apply(3,"set_definition","하루에 섭취하도록 권장하는 에너지 기준량")
    assert result["state"]["stage"]=="awaiting_domain_choice"
    result=apply(4,"set_domain","수N7")
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
    # sail straight through confirm_term into a brand-new definition/domain/
    # abbreviation flow, only failing at the very last step (submit()'s
    # PENDING_REQUEST_ALREADY_EXISTS) - after the user redid the whole
    # conversation. confirm_term must catch this immediately, like EXACT_MATCH.
    monkeypatch.setattr(conversation,"suggest_abbreviation",
        lambda term_name,extra_words=None: AbbreviationResult(abbreviation="TEST_ABBR",rationale="테스트 고정값",method="test_stub"))
    monkeypatch.setattr(conversation,"suggest_definition",
        lambda term_name,clarification_history=None: DefinitionSuggestionResult(ambiguous=False,definition="",rationale="",method="test_stub"))
    with db.connect() as conn:
        conn.execute("INSERT INTO domains(code,description,source) VALUES('수N7','테스트 숫자 도메인','TEST')")
    def apply(conv,revision,intent,value="",confirmed=False):
        return conversation.apply(conv,"user",revision,{"intent":intent,"value":value,"confirmed":confirmed})
    apply("first",0,"propose_term","일일운동시간")
    apply("first",1,"confirm_term",confirmed=True)
    apply("first",2,"set_definition","하루 동안 실시한 신체 활동의 누적 시간")
    apply("first",3,"set_domain","수N7")
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
    monkeypatch.setattr(module,"llm_configured",lambda:False)
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
    monkeypatch.setattr(module,"llm_configured",lambda:False)
    result=module.suggest_abbreviation("일일권장열량")
    assert result.abbreviation==""
    assert result.method=="unavailable"
    assert result.error_code=="LLM_NOT_CONFIGURED"

def test_suggest_definition_unavailable_when_no_api_key(monkeypatch):
    import term_service.definition_suggestion as module
    monkeypatch.setattr(module,"llm_configured",lambda:False)
    result=module.suggest_definition("일일권장열량")
    assert result.definition==""
    assert not result.ambiguous
    assert result.method=="unavailable"
    assert result.error_code=="LLM_NOT_CONFIGURED"

def test_suggest_domain_unavailable_when_no_api_key(monkeypatch):
    import term_service.domain_suggestion as module
    monkeypatch.setattr(module,"llm_configured",lambda:False)
    result=module.suggest_domain("결제수단코드","결제수단을 구분하는 코드")
    assert result.code==""
    assert result.existing_domain_match==""
    assert not result.ambiguous
    assert result.method=="unavailable"
    assert result.error_code=="LLM_NOT_CONFIGURED"

@pytest.mark.skipif(os.getenv("RUN_LLM_TESTS")!="1",reason="Explicit low-volume paid API smoke test")
def test_real_suggest_domain_drafts_enumerated_code_list():
    from term_service.domain_suggestion import suggest_domain
    with db.connect() as conn:
        conn.execute("INSERT INTO domains(code,description,source,data_type) VALUES('수N7','테스트 숫자 도메인','TEST','숫자') ON CONFLICT DO NOTHING")
    result=suggest_domain("결제수단코드","신용카드, 계좌이체, 간편결제, 포인트 중 하나로 결제 방법을 구분하는 코드")
    assert result.existing_domain_match==""
    assert result.code
    for value in ["신용카드","계좌이체","간편결제","포인트"]:
        assert value in result.valid_values
    assert result.rationale
    assert result.method=="structured_llm_rag"

@pytest.mark.skipif(os.getenv("RUN_LLM_TESTS")!="1",reason="Explicit low-volume paid API smoke test")
def test_real_suggest_domain_correction_never_matches_existing_domain():
    # Regression for a real live incident: correcting an already-drafted spec with a short
    # fragment ("길이를 12로 해줘") re-triggered the existing-domain safety net, which matched
    # a completely unrelated existing domain (a driver's license number domain) purely
    # because it happened to share that length - silently discarding the user's own draft
    # and skipping straight past confirmation. allow_existing_match=False must guarantee an
    # empty existing_domain_match even when a same-length decoy domain is sitting right there.
    from term_service.domain_suggestion import suggest_domain
    with db.connect() as conn:
        conn.execute("""INSERT INTO domains(code,description,source,data_type,data_length)
            VALUES('운전면허번호C12','테스트용 운전면허번호','TEST','CHAR',12) ON CONFLICT DO NOTHING""")
    history=[{"question":"기관등록코드의 길이나 형식은 어떻게 되나요?","answer":"고정된 길이 코드"},
        {"question":"이 도메인 스펙이 맞습니까?","answer":"길이를 12로 해줘."}]
    result=suggest_domain("기관등록코드","특정 기관이나 단체의 공식 등록을 나타내는 기호 체계",
        clarification_history=history,allow_existing_match=False)
    assert result.existing_domain_match==""
    assert result.code
    assert result.data_length==12
    assert result.method=="structured_llm_rag"

@pytest.mark.skipif(os.getenv("RUN_LLM_TESTS")!="1",reason="Explicit low-volume paid API smoke test")
def test_real_suggest_domain_correction_only_changes_requested_field():
    # Regression for a real live report: asking to change only the length also changed the
    # domain's code and domain_group (a real screenshot showed "한강수질C20"/도메인그룹 "수질"
    # drift to "수질등급_VARCHAR"/"환경" after asking only "길이를 10으로 변경하고싶어") - the
    # redraft had nothing but loose clarification_history prose to anchor to, so it
    # regenerated the whole spec from scratch instead of editing it. current_draft must pin
    # every field the correction doesn't mention.
    from term_service.domain_suggestion import suggest_domain
    current_draft={"code":"한강수질C20","domain_group":"수질","data_type":"VARCHAR","data_length":20,
        "decimal_length":None,"display_format":"","valid_values":"","description":"한강의 수질을 나타내는 등급을 표현하기 위한 도메인입니다."}
    history=[{"question":"수질 등급의 표현 방식이 무엇인가요?","answer":"명칭으로 표현"},
        {"question":"이 도메인 스펙이 맞습니까?","answer":"길이를 10으로 변경하고싶어."}]
    result=suggest_domain("한강수질등급","한강의 수질을 나타내는 등급",
        clarification_history=history,allow_existing_match=False,current_draft=current_draft)
    assert result.existing_domain_match==""
    assert result.code==current_draft["code"]
    assert result.domain_group==current_draft["domain_group"]
    assert result.data_type==current_draft["data_type"]
    assert result.description==current_draft["description"]
    assert result.data_length==10
    assert result.method=="structured_llm_rag"

@pytest.mark.skipif(os.getenv("RUN_LLM_TESTS")!="1",reason="Explicit low-volume paid API smoke test")
def test_real_suggest_domain_correction_adds_valid_value():
    # Same current_draft mechanism as the length-only test above, but for a list-shaped
    # field: adding one more allowed value must leave code/domain_group/data_type/data_length
    # untouched and must not silently drop the two values already there.
    from term_service.domain_suggestion import suggest_domain
    current_draft={"code":"결제수단_코드","domain_group":"코드","data_type":"CHAR","data_length":10,
        "decimal_length":None,"display_format":"","valid_values":"신용카드, 계좌이체",
        "description":"결제 방법을 구분하는 코드입니다."}
    history=[{"question":"이 도메인 스펙이 맞습니까?","answer":"카카오페이도 허용값에 추가해줘."}]
    result=suggest_domain("결제수단코드","결제 방법을 구분하는 코드",
        clarification_history=history,allow_existing_match=False,current_draft=current_draft)
    assert result.existing_domain_match==""
    assert result.code==current_draft["code"]
    assert result.domain_group==current_draft["domain_group"]
    assert result.data_type==current_draft["data_type"]
    assert result.data_length==current_draft["data_length"]
    for value in ["신용카드","계좌이체","카카오페이"]:
        assert value in result.valid_values
    assert result.method=="structured_llm_rag"

@pytest.mark.skipif(os.getenv("RUN_LLM_TESTS")!="1",reason="Explicit low-volume paid API smoke test")
def test_real_suggest_domain_correction_renames_domain_group():
    # A correction targeting a text-identity field (domain_group), not a number or a list -
    # everything else, including the unrelated code, must stay exactly as drafted.
    from term_service.domain_suggestion import suggest_domain
    current_draft={"code":"한강수질C20","domain_group":"수질","data_type":"VARCHAR","data_length":20,
        "decimal_length":None,"display_format":"","valid_values":"",
        "description":"한강의 수질을 나타내는 등급을 표현하기 위한 도메인입니다."}
    history=[{"question":"이 도메인 스펙이 맞습니까?","answer":"도메인그룹을 '환경'으로 바꿔줘."}]
    result=suggest_domain("한강수질등급","한강의 수질을 나타내는 등급",
        clarification_history=history,allow_existing_match=False,current_draft=current_draft)
    assert result.existing_domain_match==""
    assert result.code==current_draft["code"]
    assert result.domain_group=="환경"
    assert result.data_type==current_draft["data_type"]
    assert result.data_length==current_draft["data_length"]
    assert result.description==current_draft["description"]
    assert result.method=="structured_llm_rag"

def test_definition_clarification_round_trip(monkeypatch):
    # confirm_term triggers a first suggest_definition call; if it comes back
    # ambiguous, picking one of its options must trigger a SECOND call (with the
    # full clarification_history, not just the latest answer - see
    # suggest_definition()'s own comment for why) rather than registering the
    # short option label itself as the term's definition. Once a confident
    # definition is accepted, THAT (not the bare name) is what search()/
    # domain_usage() use for domain-recommendation evidence. A stub with a call
    # log stands in for the real (paid) LLM call, same pattern as
    # test_multiturn_help_does_not_become_definition's abbreviation stub.
    calls=[]
    def fake_suggest_definition(term_name,clarification_history=None):
        calls.append(clarification_history or [])
        if not clarification_history:
            return DefinitionSuggestionResult(ambiguous=True,question="실제 소모량인가요, 목표량인가요?",
                options=["실제 소모량 기준","목표로 설정한 소모량 기준"],method="test_stub")
        answer=clarification_history[-1]["answer"]
        return DefinitionSuggestionResult(ambiguous=False,
            definition=f"{answer}으로 계산한 하루 소모 에너지량",rationale="테스트 고정값",method="test_stub")
    monkeypatch.setattr(conversation,"suggest_definition",fake_suggest_definition)
    monkeypatch.setattr(conversation,"suggest_abbreviation",
        lambda term_name,extra_words=None: AbbreviationResult(abbreviation="TEST_ABBR",rationale="테스트 고정값",method="test_stub"))
    with db.connect() as conn:
        conn.execute("INSERT INTO domains(code,description,source) VALUES('수N7','테스트 숫자 도메인','TEST')")
    def apply(revision,intent,value="",confirmed=False):
        return conversation.apply("definition-conv","user",revision,{"intent":intent,"value":value,"confirmed":confirmed})
    apply(0,"propose_term","일일소모열량계산값")
    result=apply(1,"confirm_term",confirmed=True)
    assert result["state"]["stage"]=="awaiting_definition"
    assert result["state"]["definition_suggestion"]["ambiguous"]
    assert len(calls)==1 and calls[0]==[]
    # Picking one of the offered options must re-propose, not register the
    # option label as the definition.
    result=apply(2,"set_definition","실제 소모량 기준")
    assert result["state"]["stage"]=="awaiting_definition"
    assert not result["state"]["definition_suggestion"]["ambiguous"]
    assert "definition" not in result["state"]
    assert len(calls)==2 and calls[1]==[{"question":"실제 소모량인가요, 목표량인가요?","answer":"실제 소모량 기준"}]
    assert result["state"]["definition_clarification_history"]==calls[1]
    # Accepting the resulting confident suggestion moves on to domain choice,
    # now backed by search(term_name, definition) evidence, not just the name.
    result=apply(3,"set_definition",result["state"]["definition_suggestion"]["definition"])
    assert result["state"]["stage"]=="awaiting_domain_choice"
    assert result["state"]["definition"]=="실제 소모량 기준으로 계산한 하루 소모 에너지량"
    result=apply(4,"set_domain","수N7")
    assert result["state"]["stage"]=="awaiting_abbreviation"

def test_definition_suggestion_own_text_bypasses_suggestion(monkeypatch):
    # The user must always be able to just type their own definition, whether
    # or not a suggestion/question was ever offered.
    monkeypatch.setattr(conversation,"suggest_definition",
        lambda term_name,clarification_history=None: DefinitionSuggestionResult(
            ambiguous=True,question="q",options=["A","B"],method="test_stub"))
    monkeypatch.setattr(conversation,"suggest_abbreviation",
        lambda term_name,extra_words=None: AbbreviationResult(abbreviation="TEST_ABBR2",rationale="",method="test_stub"))
    with db.connect() as conn:
        conn.execute("INSERT INTO domains(code,description,source) VALUES('수N7','테스트 숫자 도메인','TEST') ON CONFLICT DO NOTHING")
    def apply(revision,intent,value="",confirmed=False):
        return conversation.apply("definition-conv-2","user",revision,{"intent":intent,"value":value,"confirmed":confirmed})
    apply(0,"propose_term","야간간식섭취열량")
    apply(1,"confirm_term",confirmed=True)
    result=apply(2,"set_definition","늦은 밤에 추가로 섭취한 간식의 열량 총합")
    assert result["state"]["stage"]=="awaiting_domain_choice"
    assert result["state"]["definition"]=="늦은 밤에 추가로 섭취한 간식의 열량 총합"
    result=apply(3,"set_domain","수N7")
    assert result["state"]["stage"]=="awaiting_abbreviation"

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
    result=apply(2,"set_definition","하루 동안 걸은 평균 걸음 수")
    assert result["state"]["stage"]=="awaiting_domain_choice"
    result=apply(3,"set_domain","수N7")
    assert result["state"]["stage"]=="awaiting_abbreviation"
    assert result["state"]["abbreviation_suggestion"]["abbreviation"]
    result=apply(4,"set_abbreviation","DAILY_AVG_STEP")
    assert result["state"]["stage"]=="awaiting_confirm"
    assert result["state"]["english_abbr"]=="DAILY_AVG_STEP"

def test_confirm_term_routes_to_word_request_when_decomposition_fails():
    # A term fully covered by known standard_words must behave exactly as before
    # (straight to awaiting_definition) - the new word-gap check must never fire
    # when it has nothing to report.
    insert_standard_word("일일","DAILY")
    insert_standard_word("칼로리","CAL")
    def apply(revision,intent,value="",confirmed=False):
        return conversation.apply("word-gap-conv","user",revision,{"intent":intent,"value":value,"confirmed":confirmed})
    apply(0,"propose_term","일일칼로리")
    result=apply(1,"confirm_term",confirmed=True)
    assert result["state"]["stage"]=="awaiting_definition"

    # A name with a portion the dictionary doesn't cover ("보행량") must route into
    # the word-request sub-flow instead of silently proceeding, with enough state
    # saved (resume_term) to pick the term registration back up afterward.
    apply(2,"propose_term","일일보행량")
    result=apply(3,"confirm_term",confirmed=True)
    assert result["state"]["stage"]=="awaiting_word_meaning"
    assert result["state"]["resume_term"]["term_name"]=="일일보행량"

@pytest.mark.skipif(os.getenv("RUN_LLM_TESTS")!="1",reason="Explicit low-volume paid API smoke test")
def test_real_word_request_flow_resumes_term_registration():
    insert_standard_word("등기","RG","국가 기관이 법정 절차에 따라 등기부에 부동산이나 동산 등에 대한 권리관계를 기록하는 행위")
    def apply(revision,intent,value="",confirmed=False):
        return conversation.apply("word-flow-conv","user",revision,{"intent":intent,"value":value,"confirmed":confirmed})
    apply(0,"propose_term","등기증명서")  # "증명서" isn't in this tiny test dictionary
    result=apply(1,"confirm_term",confirmed=True)
    assert result["state"]["stage"]=="awaiting_word_meaning"
    rev=2
    result=apply(rev,"propose_word","등기 내용을 증명하기 위해 발급하는 문서")
    assert result["state"]["stage"]=="awaiting_word_confirm"
    suggestion=result["state"]["word_suggestion"]
    if suggestion.get("ambiguous"):
        rev+=1
        result=apply(rev,"propose_word",suggestion["options"][0])
        suggestion=result["state"]["word_suggestion"]
    rev+=1
    result=apply(rev,"confirm_word",confirmed=True)
    if result["state"]["stage"]=="awaiting_word_abbreviation":
        rev+=1
        abbr=result["state"]["word_registration_payload"]["english_abbr"]
        result=apply(rev,"set_word_abbreviation",abbr)
    # Whether it reused an existing word or registered a brand-new one, the paused
    # term registration must resume right where it left off.
    assert result["state"]["stage"]=="awaiting_definition"
    assert "resume_term" not in result["state"]
    assert result["state"]["definition_suggestion"]

@pytest.mark.skipif(os.getenv("RUN_LLM_TESTS")!="1",reason="Explicit low-volume paid API smoke test")
def test_fixed_name_forbids_reuse_even_of_a_near_perfect_synonym():
    # Regression for a real user report: registering "소리동굴" (both "소리" and "동굴"
    # missing) got offered a "reuse" of the existing word "음성" for "소리" - but 음성
    # (a human voice) and 소리 (sound in general) are not actually interchangeable, and
    # silently substituting 음성 would also silently change the term's own spelling out
    # from under the requester ("소리동굴" registered as if it meant "음성동굴"). The
    # user's decision: when filling a gap inside a term's own decomposition, never
    # substitute a differently-named word, no matter how close a "synonym" it looks -
    # always coin a new word using the term's own literal wording. fixed_name is the
    # deterministic (code-level, not just prose) enforcement of that - this test grounds
    # it against the real LLM so an even more obviously-synonymous existing word (here
    # "소리" itself, registered verbatim) still can't be reused when fixed_name is set.
    insert_standard_word("소리","SOUN","공기의 진동으로 전달되는 청각 자극")
    result = suggest_word("동굴에서 울리는 소리를 뜻함", fixed_name="소리")
    assert result.existing_word_match==""
    assert result.name=="소리"
    assert result.method=="structured_llm_rag"

def test_term_waits_for_new_word_approval_and_reuses_its_abbreviation(monkeypatch):
    # Regression for a real user report: registering "일일보행량" (일일=known word,
    # 보행량=missing) routed into the word sub-flow, submitted a brand-new word
    # "보행량"/WALKCNT for review, then - after resuming - the TERM's own abbreviation
    # suggestion had no idea that word existed (it isn't in standard_words yet, only
    # word_registration_requests) and invented a totally unrelated one via the LLM
    # fallback, producing two different English names for one concept. Also: the term
    # must not sit in the same ready-to-review queue as a term whose dependency is
    # already a real standard - it must wait for the word to be approved first.
    insert_standard_word("일일","DAILY")
    with db.connect() as conn:
        conn.execute("INSERT INTO domains(code,description,source) VALUES('수N7','테스트 숫자 도메인','TEST') ON CONFLICT DO NOTHING")
    monkeypatch.setattr(conversation,"suggest_word",
        lambda usage_description,clarification_history=None,fixed_name="": type("R",(),{"model_dump":lambda self: {
            "existing_word_match":"","match_reason":"","ambiguous":False,"question":"","options":[],
            "name":fixed_name or "보행량","english_abbr":"WALKCNT","is_format_word":False,
            "definition":"하루 동안 걸은 걸음 수","rationale":"","method":"test_stub"}})())
    monkeypatch.setattr(conversation,"suggest_definition",
        lambda term_name,clarification_history=None: DefinitionSuggestionResult(
            ambiguous=False,definition="하루 동안 걸은 걸음 수를 합산한 값",rationale="",method="test_stub"))
    def apply(revision,intent,value="",confirmed=False):
        return conversation.apply("word-approval-conv","user",revision,{"intent":intent,"value":value,"confirmed":confirmed})
    apply(0,"propose_term","일일보행량")
    result=apply(1,"confirm_term",confirmed=True)
    assert result["state"]["stage"]=="awaiting_word_meaning"
    result=apply(2,"propose_word","하루 동안 걸은 걸음 수를 세는 개념")
    assert result["state"]["stage"]=="awaiting_word_confirm"
    result=apply(3,"confirm_word",confirmed=True)
    assert result["state"]["stage"]=="awaiting_word_abbreviation"
    result=apply(4,"set_word_abbreviation","WALKCNT")
    # Resumed straight back into the paused term flow, carrying the new word forward.
    assert result["state"]["stage"]=="awaiting_definition"
    word_request_id=result["state"]["term_pending_words"][0]["request_id"]
    assert result["state"]["term_pending_words"][0]["english_abbr"]=="WALKCNT"
    result=apply(5,"set_definition",result["state"]["definition_suggestion"]["definition"])
    assert result["state"]["stage"]=="awaiting_domain_choice"
    result=apply(6,"set_domain","수N7")
    assert result["state"]["stage"]=="awaiting_abbreviation"
    # The whole point: composed from the real word abbreviation, not LLM-invented.
    assert result["state"]["abbreviation_suggestion"]["abbreviation"]=="DAILY_WALKCNT"
    assert result["state"]["abbreviation_suggestion"]["method"]=="deterministic_word_dictionary"
    result=apply(7,"set_abbreviation","DAILY_WALKCNT")
    assert result["state"]["stage"]=="awaiting_confirm"
    result=apply(8,"confirm_registration",confirmed=True)
    assert result["state"]["stage"]=="submitted"
    term_request_id=result["state"]["registration"]["request_id"]
    # Not ready for review yet - it depends on a word that isn't a real standard yet.
    assert result["state"]["registration"]["status"]=="WAITING_FOR_WORD_APPROVAL"
    assert registration.approve(term_request_id)["code"]=="NOT_PENDING_REVIEW"

    approval=word_registration.approve(word_request_id)
    assert approval["approved"]
    assert term_request_id in [p["request_id"] for p in approval["promoted_terms"]]
    with db.connect() as conn:
        row=conn.execute("SELECT status FROM registration_requests WHERE id=%s",(term_request_id,)).fetchone()
    assert row["status"]=="PENDING_REVIEW"

    final=registration.approve(term_request_id)
    assert final["approved"]
    with db.connect() as conn:
        term_row=conn.execute("SELECT english_abbr,status FROM standard_terms WHERE name='일일보행량'").fetchone()
        word_row=conn.execute("SELECT english_abbr,status FROM standard_words WHERE name='보행량'").fetchone()
    assert term_row["english_abbr"]=="DAILY_WALKCNT" and term_row["status"]=="ACTIVE"
    assert word_row["english_abbr"]=="WALKCNT" and word_row["status"]=="ACTIVE"

def test_term_waits_for_new_domain_approval_via_chat_and_reuses_it(monkeypatch):
    # End-to-end version of registration.py's test_term_waiting_on_new_domain_released_
    # once_domain_approved, but driven through conversation.py's actual state machine
    # (request_new_domain -> confirm_domain_spec -> set_domain_pii) instead of calling
    # registration.submit()/domain_registration.approve() directly - this is the part
    # that was still untested: the chat wiring itself, not just the backend plumbing.
    monkeypatch.setattr(conversation,"suggest_domain",
        lambda term_name,definition,clarification_history=None: type("R",(),{"model_dump":lambda self:{
            "existing_domain_match":"","match_reason":"","ambiguous":False,"question":"","options":[],
            "code":"결제수단_코드","domain_group":"코드","data_type":"CHAR","data_length":1,"decimal_length":None,
            "display_format":"","valid_values":"신용카드,계좌이체","description":"결제 방법을 구분하는 코드",
            "rationale":"정의의 '결제 방법을 구분' 표현에서 도출","method":"test_stub"}})())
    monkeypatch.setattr(conversation,"suggest_definition",
        lambda term_name,clarification_history=None: DefinitionSuggestionResult(
            ambiguous=False,definition="신용카드 또는 계좌이체 등 결제 방법을 구분하는 코드",rationale="",method="test_stub"))
    monkeypatch.setattr(conversation,"suggest_abbreviation",
        lambda term_name,extra_words=None: AbbreviationResult(abbreviation="PAYMTHD_CD",rationale="",method="test_stub"))
    def apply(revision,intent,value="",confirmed=False):
        return conversation.apply("domain-approval-conv","user",revision,{"intent":intent,"value":value,"confirmed":confirmed})
    apply(0,"propose_term","결제수단코드")
    result=apply(1,"confirm_term",confirmed=True)
    assert result["state"]["stage"]=="awaiting_definition"
    result=apply(2,"set_definition",result["state"]["definition_suggestion"]["definition"])
    assert result["state"]["stage"]=="awaiting_domain_choice"
    # The user rejects every recommended/known domain (none exist in this clean test DB
    # anyway) - no extra description needed, suggest_domain() drafts from context alone.
    result=apply(3,"request_new_domain")
    assert result["state"]["stage"]=="awaiting_domain_spec_confirm"
    assert result["state"]["domain_suggestion"]["code"]=="결제수단_코드"
    result=apply(4,"confirm_domain_spec",confirmed=True)
    assert result["state"]["stage"]=="awaiting_domain_pii_choice"
    result=apply(5,"set_domain_pii",confirmed=False)
    assert result["state"]["stage"]=="awaiting_abbreviation"
    assert result["state"]["domain"]=="결제수단_코드"
    domain_request_id=result["state"]["pending_domain_request"]["request_id"]
    result=apply(6,"set_abbreviation","PAYMTHD_CD")
    assert result["state"]["stage"]=="awaiting_confirm"
    result=apply(7,"confirm_registration",confirmed=True)
    assert result["state"]["stage"]=="submitted"
    term_request_id=result["state"]["registration"]["request_id"]
    # Not ready for review yet - it depends on a domain that isn't a real standard yet.
    assert result["state"]["registration"]["status"]=="WAITING_FOR_DOMAIN_APPROVAL"
    assert registration.approve(term_request_id)["code"]=="NOT_PENDING_REVIEW"

    approval=domain_registration.approve(domain_request_id)
    assert approval["approved"]
    assert term_request_id in [p["request_id"] for p in approval["promoted_terms"]]
    with db.connect() as conn:
        row=conn.execute("SELECT status,domain FROM registration_requests WHERE id=%s",(term_request_id,)).fetchone()
    assert row["status"]=="PENDING_REVIEW"
    assert row["domain"]=="결제수단_코드"

    final=registration.approve(term_request_id)
    assert final["approved"]
    with db.connect() as conn:
        term_row=conn.execute("SELECT english_abbr,status,domain FROM standard_terms WHERE name='결제수단코드'").fetchone()
    assert term_row["english_abbr"]=="PAYMTHD_CD" and term_row["status"]=="ACTIVE" and term_row["domain"]=="결제수단_코드"

def test_domain_spec_existing_match_skips_straight_to_abbreviation(monkeypatch):
    # domain_suggestion.py's safety net: even after the user rejects every domain
    # awaiting_domain_choice offered, the model can still find that an existing domain
    # actually fits once it reads the definition directly - this must proceed with that
    # domain immediately (no new domain_requests row, no PII question), not repeat a
    # spec-drafting round for something that already exists.
    with db.connect() as conn:
        conn.execute("INSERT INTO domains(code,description,source) VALUES('코드C2','테스트 코드 도메인','TEST')")
    monkeypatch.setattr(conversation,"suggest_domain",
        lambda term_name,definition,clarification_history=None: type("R",(),{"model_dump":lambda self:{
            "existing_domain_match":"코드C2","match_reason":"이미 있는 코드 도메인이 정의에 부합",
            "ambiguous":False,"question":"","options":[],"code":"","domain_group":"","data_type":"",
            "data_length":None,"decimal_length":None,"display_format":"","valid_values":"","description":"",
            "rationale":"","method":"test_stub"}})())
    monkeypatch.setattr(conversation,"suggest_definition",
        lambda term_name,clarification_history=None: DefinitionSuggestionResult(
            ambiguous=False,definition="테스트용 정의",rationale="",method="test_stub"))
    def apply(revision,intent,value="",confirmed=False):
        return conversation.apply("domain-match-conv","user",revision,{"intent":intent,"value":value,"confirmed":confirmed})
    apply(0,"propose_term","환불사유코드")
    result=apply(1,"confirm_term",confirmed=True)
    result=apply(2,"set_definition",result["state"]["definition_suggestion"]["definition"])
    assert result["state"]["stage"]=="awaiting_domain_choice"
    result=apply(3,"request_new_domain")
    assert result["state"]["stage"]=="awaiting_abbreviation"
    assert result["state"]["domain"]=="코드C2"
    assert "pending_domain_request" not in result["state"]
    with db.connect() as conn:
        count=conn.execute("SELECT count(*) AS n FROM domain_requests").fetchone()["n"]
    assert count==0

def test_term_can_split_its_missing_part_into_several_new_words(monkeypatch):
    # A real user report: registering "소리동굴" found NEITHER "소리" NOR "동굴" in the
    # word dictionary, so confirm_term's old behavior forced the whole gap into ONE new
    # atomic word ("소리동굴" itself) with no way to instead register "소리" and "동굴" as
    # their own separate standard words and compose the term from them - a design fork
    # that had never actually been decided. This is the new decision point
    # (awaiting_word_split_choice) and the multi-word registration path it unlocks: each
    # split noun goes through the normal word sub-flow in turn, and the term must wait
    # for ALL of them (not just the first) to be approved before it's ready for review.
    with db.connect() as conn:
        conn.execute("INSERT INTO domains(code,description,source) VALUES('수N7','테스트 숫자 도메인','TEST') ON CONFLICT DO NOTHING")
    # The word-decomposition check only runs once a word dictionary actually exists (an
    # empty one means "cannot check", not "everything is a gap" - see confirm_term) - an
    # unrelated word is enough to make that true without affecting "소리"/"동굴" themselves.
    insert_standard_word("등기","RG","국가 기관이 법정 절차에 따라 등기부에 기록하는 행위")
    word_stubs={
        "소리":{"existing_word_match":"","match_reason":"","ambiguous":False,"question":"","options":[],
            "name":"소리","english_abbr":"SORI","is_format_word":False,
            "definition":"공기의 진동으로 전달되는 청각 자극","rationale":"","method":"test_stub"},
        "동굴":{"existing_word_match":"","match_reason":"","ambiguous":False,"question":"","options":[],
            "name":"동굴","english_abbr":"CAVE","is_format_word":False,
            "definition":"땅속이나 암석 속에 자연적으로 생긴 깊은 굴","rationale":"","method":"test_stub"},
    }
    monkeypatch.setattr(conversation,"suggest_word",
        lambda usage_description,clarification_history=None,fixed_name="": type("R",(),{
            "model_dump":lambda self,_d=word_stubs[usage_description]: _d})())
    monkeypatch.setattr(conversation,"suggest_definition",
        lambda term_name,clarification_history=None: DefinitionSuggestionResult(
            ambiguous=False,definition="소리가 나는 관광용 동굴",rationale="",method="test_stub"))
    def apply(revision,intent,value="",confirmed=False):
        return conversation.apply("word-split-conv","user",revision,{"intent":intent,"value":value,"confirmed":confirmed})
    apply(0,"propose_term","소리동굴")
    result=apply(1,"confirm_term",confirmed=True)
    assert result["state"]["stage"]=="awaiting_word_split_choice"
    assert result["state"]["word_split_candidates"]["split_names"]==["소리","동굴"]
    result=apply(2,"set_word_split_choice",confirmed=True)
    assert result["state"]["stage"]=="awaiting_word_confirm"
    assert result["state"]["word_suggestion"]["name"]=="소리"
    assert result["state"]["resume_term"]["pending_word_names"]==["동굴"]
    result=apply(3,"confirm_word",confirmed=True)
    assert result["state"]["stage"]=="awaiting_word_abbreviation"
    result=apply(4,"set_word_abbreviation","SORI")
    # First word done, but a second one is still missing - stays in the word sub-flow
    # instead of resuming the term, and now proposes "동굴" specifically (not re-asking
    # the user to describe anything - the split already named it).
    assert result["state"]["stage"]=="awaiting_word_confirm"
    assert result["state"]["word_suggestion"]["name"]=="동굴"
    assert result["state"]["resume_term"]["pending_word_names"]==[]
    result=apply(5,"confirm_word",confirmed=True)
    assert result["state"]["stage"]=="awaiting_word_abbreviation"
    result=apply(6,"set_word_abbreviation","CAVE")
    # Both words done - now the term flow actually resumes.
    assert result["state"]["stage"]=="awaiting_definition"
    assert "resume_term" not in result["state"]
    pending=result["state"]["term_pending_words"]
    assert {w["name"] for w in pending}=={"소리","동굴"}
    result=apply(7,"set_definition",result["state"]["definition_suggestion"]["definition"])
    assert result["state"]["stage"]=="awaiting_domain_choice"
    result=apply(8,"set_domain","수N7")
    assert result["state"]["stage"]=="awaiting_abbreviation"
    # Composed deterministically from BOTH new words' abbreviations, not invented by the LLM.
    assert result["state"]["abbreviation_suggestion"]["abbreviation"]=="SORI_CAVE"
    assert result["state"]["abbreviation_suggestion"]["method"]=="deterministic_word_dictionary"
    result=apply(9,"set_abbreviation","SORI_CAVE")
    assert result["state"]["stage"]=="awaiting_confirm"
    result=apply(10,"confirm_registration",confirmed=True)
    assert result["state"]["stage"]=="submitted"
    term_request_id=result["state"]["registration"]["request_id"]
    assert result["state"]["registration"]["status"]=="WAITING_FOR_WORD_APPROVAL"
    assert registration.approve(term_request_id)["code"]=="NOT_PENDING_REVIEW"
    word_ids={w["name"]:w["request_id"] for w in pending}

    # Approving only ONE of the two dependency words must NOT release the term yet.
    first_approval=word_registration.approve(word_ids["소리"])
    assert first_approval["approved"]
    assert first_approval["promoted_terms"]==[]
    with db.connect() as conn:
        row=conn.execute("SELECT status FROM registration_requests WHERE id=%s",(term_request_id,)).fetchone()
    assert row["status"]=="WAITING_FOR_WORD_APPROVAL"

    # Approving the SECOND (last remaining) dependency finally releases it.
    second_approval=word_registration.approve(word_ids["동굴"])
    assert second_approval["approved"]
    assert term_request_id in [p["request_id"] for p in second_approval["promoted_terms"]]
    with db.connect() as conn:
        row=conn.execute("SELECT status FROM registration_requests WHERE id=%s",(term_request_id,)).fetchone()
    assert row["status"]=="PENDING_REVIEW"

    final=registration.approve(term_request_id)
    assert final["approved"]
    with db.connect() as conn:
        term_row=conn.execute("SELECT english_abbr,status FROM standard_terms WHERE name='소리동굴'").fetchone()
        word_rows={r["name"]:r for r in conn.execute(
            "SELECT name,english_abbr,status FROM standard_words WHERE name IN ('소리','동굴')").fetchall()}
    assert term_row["english_abbr"]=="SORI_CAVE" and term_row["status"]=="ACTIVE"
    assert word_rows["소리"]["english_abbr"]=="SORI" and word_rows["소리"]["status"]=="ACTIVE"
    assert word_rows["동굴"]["english_abbr"]=="CAVE" and word_rows["동굴"]["status"]=="ACTIVE"

def test_hash_password_roundtrip():
    stored=auth.hash_password("correct horse battery staple")
    assert auth.verify_password("correct horse battery staple",stored)
    assert not auth.verify_password("wrong password",stored)

def test_hash_password_unique_salts():
    assert auth.hash_password("same-password")!=auth.hash_password("same-password")

def test_create_admin_cli_bootstraps_active_admin():
    result=create_admin("root-admin","hunter2-hunter2","관리자","거버넌스팀")
    assert result=={"created":True,"username":"root-admin","role":"ADMIN"}
    with db.connect() as conn:
        row=conn.execute("SELECT role,status,password_hash FROM users WHERE username='root-admin'").fetchone()
    assert row["role"]=="ADMIN" and row["status"]=="ACTIVE"
    assert auth.verify_password("hunter2-hunter2",row["password_hash"])
    assert create_admin("root-admin","different","다른이름")=={"created":False,"error":"USERNAME_TAKEN"}

@pytest.fixture
def api_client():
    from starlette.testclient import TestClient
    from term_service import admin_api  # noqa: F401 - registers /admin/auth/* routes on `mcp`
    from term_service.tools import mcp
    return TestClient(mcp.streamable_http_app())

def test_signup_then_login_pending(api_client):
    signup=api_client.post("/admin/auth/signup",json={
        "username":"new-member","password":"password123","display_name":"신규회원","team":"운영팀"})
    assert signup.status_code==200 and signup.json()=={"ok":True,"status":"PENDING_APPROVAL"}
    login=api_client.post("/admin/auth/login",json={"username":"new-member","password":"password123"})
    assert login.status_code==403
    assert login.json()=={"ok":False,"error":"ACCOUNT_NOT_ACTIVE","status":"PENDING_APPROVAL"}

def test_duplicate_username_signup_conflict(api_client):
    payload={"username":"dup-user","password":"password123","display_name":"중복"}
    assert api_client.post("/admin/auth/signup",json=payload).status_code==200
    second=api_client.post("/admin/auth/signup",json=payload)
    assert second.status_code==409 and second.json()["error"]=="USERNAME_TAKEN"

def _create_active_admin(username="admin1",password="adminpass123",display_name="관리자"):
    create_admin(username,password,display_name)

def test_admin_approve_then_login_succeeds(api_client):
    _create_active_admin()
    assert api_client.post("/admin/auth/login",json={"username":"admin1","password":"adminpass123"}).status_code==200
    api_client.post("/admin/auth/signup",json={
        "username":"approved-user","password":"memberpass123","display_name":"멤버"})
    members=api_client.get("/admin/auth/members").json()["users"]
    user_id=next(u["id"] for u in members if u["username"]=="approved-user")
    approve=api_client.post("/admin/auth/approve-user",json={"user_id":user_id})
    assert approve.status_code==200 and approve.json()["ok"]
    from starlette.testclient import TestClient
    from term_service.tools import mcp
    fresh_client=TestClient(mcp.streamable_http_app())
    login=fresh_client.post("/admin/auth/login",json={"username":"approved-user","password":"memberpass123"})
    assert login.status_code==200
    assert "session_token" in login.cookies

def test_login_wrong_password_rejected(api_client):
    _create_active_admin()
    resp=api_client.post("/admin/auth/login",json={"username":"admin1","password":"wrong-password"})
    assert resp.status_code==401 and resp.json()["error"]=="INVALID_CREDENTIALS"

def test_reject_user(api_client):
    _create_active_admin()
    api_client.post("/admin/auth/login",json={"username":"admin1","password":"adminpass123"})
    api_client.post("/admin/auth/signup",json={
        "username":"to-reject","password":"memberpass123","display_name":"반려대상"})
    members=api_client.get("/admin/auth/members").json()["users"]
    user_id=next(u["id"] for u in members if u["username"]=="to-reject")
    reject=api_client.post("/admin/auth/reject-user",json={"user_id":user_id})
    assert reject.status_code==200
    login=api_client.post("/admin/auth/login",json={"username":"to-reject","password":"memberpass123"})
    assert login.status_code==403 and login.json()["status"]=="REJECTED"

def test_role_gating_member_forbidden(api_client):
    _create_active_admin()
    api_client.post("/admin/auth/login",json={"username":"admin1","password":"adminpass123"})
    api_client.post("/admin/auth/signup",json={
        "username":"plain-member","password":"memberpass123","display_name":"일반회원"})
    members=api_client.get("/admin/auth/members").json()["users"]
    user_id=next(u["id"] for u in members if u["username"]=="plain-member")
    api_client.post("/admin/auth/approve-user",json={"user_id":user_id})
    from starlette.testclient import TestClient
    from term_service.tools import mcp
    member_client=TestClient(mcp.streamable_http_app())
    member_client.post("/admin/auth/login",json={"username":"plain-member","password":"memberpass123"})
    resp=member_client.get("/admin/auth/members")
    assert resp.status_code==403 and resp.json()["error"]=="ADMIN_REQUIRED"

def test_logout_clears_session(api_client):
    _create_active_admin()
    api_client.post("/admin/auth/login",json={"username":"admin1","password":"adminpass123"})
    assert api_client.get("/admin/auth/me").status_code==200
    api_client.post("/admin/auth/logout")
    assert api_client.get("/admin/auth/me").status_code==401

def test_session_expiry(api_client):
    _create_active_admin()
    with db.connect() as conn:
        user_id=conn.execute("SELECT id FROM users WHERE username='admin1'").fetchone()["id"]
    token=auth.create_session(user_id)
    with db.connect() as conn:
        conn.execute("UPDATE sessions SET expires_at=now()-interval '1 day' WHERE token=%s",(token,))
    api_client.cookies.set("session_token",token)
    resp=api_client.get("/admin/auth/me")
    assert resp.status_code==401

def test_suspend_and_reactivate_user(api_client):
    _create_active_admin()
    _create_active_admin("admin2","adminpass456","관리자2")
    api_client.post("/admin/auth/login",json={"username":"admin1","password":"adminpass123"})
    members=api_client.get("/admin/auth/members").json()["users"]
    target_id=next(u["id"] for u in members if u["username"]=="admin2")
    suspend=api_client.post("/admin/auth/suspend-user",json={"user_id":target_id})
    assert suspend.status_code==200
    login_suspended=api_client.post("/admin/auth/login",json={"username":"admin2","password":"adminpass456"})
    assert login_suspended.status_code==403 and login_suspended.json()["status"]=="SUSPENDED"
    reactivate=api_client.post("/admin/auth/reactivate-user",json={"user_id":target_id})
    assert reactivate.status_code==200
    login_ok=api_client.post("/admin/auth/login",json={"username":"admin2","password":"adminpass456"})
    assert login_ok.status_code==200

def test_last_admin_cannot_be_suspended(api_client):
    _create_active_admin()
    api_client.post("/admin/auth/login",json={"username":"admin1","password":"adminpass123"})
    members=api_client.get("/admin/auth/members").json()["users"]
    self_id=next(u["id"] for u in members if u["username"]=="admin1")
    resp=api_client.post("/admin/auth/suspend-user",json={"user_id":self_id})
    assert resp.status_code==409 and resp.json()["error"]=="LAST_ADMIN_CANNOT_BE_SUSPENDED"

def test_last_admin_cannot_be_demoted(api_client):
    _create_active_admin()
    api_client.post("/admin/auth/login",json={"username":"admin1","password":"adminpass123"})
    members=api_client.get("/admin/auth/members").json()["users"]
    self_id=next(u["id"] for u in members if u["username"]=="admin1")
    resp=api_client.post("/admin/auth/set-role",json={"user_id":self_id,"role":"MEMBER"})
    assert resp.status_code==409 and resp.json()["error"]=="LAST_ADMIN_CANNOT_BE_DEMOTED"

def test_set_role_promotes_member_to_admin(api_client):
    _create_active_admin()
    api_client.post("/admin/auth/login",json={"username":"admin1","password":"adminpass123"})
    api_client.post("/admin/auth/signup",json={
        "username":"future-admin","password":"memberpass123","display_name":"승격예정"})
    members=api_client.get("/admin/auth/members").json()["users"]
    target_id=next(u["id"] for u in members if u["username"]=="future-admin")
    api_client.post("/admin/auth/approve-user",json={"user_id":target_id})
    promote=api_client.post("/admin/auth/set-role",json={"user_id":target_id,"role":"ADMIN"})
    assert promote.status_code==200
    with db.connect() as conn:
        role=conn.execute("SELECT role FROM users WHERE id=%s",(target_id,)).fetchone()["role"]
    assert role=="ADMIN"
    # Now that two admins exist, demoting the original one must succeed (no longer "last").
    self_id=next(u["id"] for u in members if u["username"]=="admin1")
    demote=api_client.post("/admin/auth/set-role",json={"user_id":self_id,"role":"MEMBER"})
    assert demote.status_code==200

def test_change_password_then_old_password_rejected(api_client):
    _create_active_admin()
    api_client.post("/admin/auth/login",json={"username":"admin1","password":"adminpass123"})
    change=api_client.post("/admin/auth/change-password",
        json={"current_password":"adminpass123","new_password":"newpass456"})
    assert change.status_code==200 and change.json()["ok"]
    from starlette.testclient import TestClient
    from term_service.tools import mcp
    fresh_client=TestClient(mcp.streamable_http_app())
    assert fresh_client.post("/admin/auth/login",
        json={"username":"admin1","password":"adminpass123"}).status_code==401
    assert fresh_client.post("/admin/auth/login",
        json={"username":"admin1","password":"newpass456"}).status_code==200

def test_change_password_wrong_current_rejected(api_client):
    _create_active_admin()
    api_client.post("/admin/auth/login",json={"username":"admin1","password":"adminpass123"})
    resp=api_client.post("/admin/auth/change-password",
        json={"current_password":"wrong-password","new_password":"newpass456"})
    assert resp.status_code==401 and resp.json()["error"]=="CURRENT_PASSWORD_INCORRECT"

def test_change_password_revokes_other_sessions(api_client):
    _create_active_admin()
    api_client.post("/admin/auth/login",json={"username":"admin1","password":"adminpass123"})
    from starlette.testclient import TestClient
    from term_service.tools import mcp
    other_device=TestClient(mcp.streamable_http_app())
    other_device.post("/admin/auth/login",json={"username":"admin1","password":"adminpass123"})
    assert other_device.get("/admin/auth/me").status_code==200
    api_client.post("/admin/auth/change-password",
        json={"current_password":"adminpass123","new_password":"newpass456"})
    assert other_device.get("/admin/auth/me").status_code==401
    assert api_client.get("/admin/auth/me").status_code==200

def test_list_terms_query_matches_requester_too():
    insert_pending_term("신규약속어",requester="김철수")
    result=list_terms(q="김철수")
    assert any(t["term_name"]=="신규약속어" for t in result["terms"])

def test_list_terms_query_still_matches_name_and_definition():
    insert_pending_term("신규약속어",definition="특별한 정의문",requester="박영희")
    by_name=list_terms(q="신규약속어")
    assert any(t["term_name"]=="신규약속어" for t in by_name["terms"])
    by_def=list_terms(q="특별한 정의문")
    assert any(t["term_name"]=="신규약속어" for t in by_def["terms"])

def test_list_terms_query_does_not_hide_approved_rows(catalog):
    # Regression: a requester filter used to force show_approved=False, which
    # meant merging requester-search into `q` would have silently hidden the
    # whole approved catalog whenever the search box had any text in it.
    result=list_terms(q="일일섭취칼로리")
    assert any(t["term_name"]=="일일섭취칼로리" and t["status"]=="APPROVED" for t in result["terms"])

def test_list_standard_words_query_matches_requester_too():
    insert_pending_word("신규단어",requester="이민수")
    result=list_standard_words(q="이민수")
    assert any(w["name"]=="신규단어" for w in result["words"])

# ── 도메인 신청 (버튼 기반 직접 입력 폼) ──────────────────────────────

def _domain_payload(code,**overrides):
    fields=dict(code=code,domain_group="테스트그룹",physical_name="",data_type="문자",data_length=None,
        decimal_length=None,min_value="",max_value="",display_format="",source_classification="",
        valid_values="",default_value="",description="",is_personal_info=False,personal_info_type="",
        protection_level="",is_encrypted=False,encryption_method="",mapping_table="",mapping_column="",
        request_reason="",requester="tester",conversation_id="direct-form")
    fields.update(overrides)
    return DomainRequestInput(**fields)

def test_domain_prepare_rejects_existing_live_code(catalog):
    result=domain_registration.prepare(_domain_payload("수N7"))
    assert result=={"ready":False,"code":"CODE_ALREADY_EXISTS","existing_domain":{"code":"수N7","description":"테스트 숫자 도메인"}}

def test_domain_prepare_rejects_pending_duplicate():
    insert_pending_domain_request("신규도메인1")
    result=domain_registration.prepare(_domain_payload("신규도메인1"))
    assert result=={"ready":False,"code":"PENDING_REQUEST_ALREADY_EXISTS"}

def test_domain_submit_creates_pending_review():
    prep=domain_registration.prepare(_domain_payload("신규도메인2"))
    assert prep["ready"]
    result=domain_registration.submit(prep["confirmation_id"],"tester","direct-form",confirmed=True)
    assert result["created"] and result["status"]=="PENDING_REVIEW" and result["code"]=="신규도메인2"

def test_domain_submit_idempotent_replay():
    prep=domain_registration.prepare(_domain_payload("신규도메인3"))
    first=domain_registration.submit(prep["confirmation_id"],"tester","direct-form",confirmed=True)
    second=domain_registration.submit(prep["confirmation_id"],"tester","direct-form",confirmed=True)
    assert second=={"created":False,"idempotent_replay":True,"request_id":first["request_id"],
        "status":"PENDING_REVIEW","created_at":second["created_at"]}

def test_approve_domain_promotes_full_field_set():
    insert_pending_domain_request("신규도메인4",mapping_table="mockops_customers",mapping_column="resident_number")
    with db.connect() as conn:
        request_id=conn.execute("SELECT id::text AS id FROM domain_requests WHERE code='신규도메인4'").fetchone()["id"]
    result=domain_registration.approve(request_id)
    assert result=={"approved":True,"code":"신규도메인4","promoted_terms":[]}
    with db.connect() as conn:
        row=conn.execute("SELECT domain_group,is_personal_info,status FROM domains WHERE code='신규도메인4'").fetchone()
        mapping=conn.execute("SELECT table_name,column_name FROM domain_data_mappings WHERE domain_code='신규도메인4'").fetchone()
    assert row=={"domain_group":"테스트그룹","is_personal_info":True,"status":"ACTIVE"}
    assert mapping=={"table_name":"mockops_customers","column_name":"resident_number"}

def test_term_waiting_on_new_domain_released_once_domain_approved():
    insert_pending_domain_request("신규도메인6")
    with db.connect() as conn:
        domain_request_id=conn.execute("SELECT id::text AS id FROM domain_requests WHERE code='신규도메인6'").fetchone()["id"]
    prepared=registration.prepare(RegistrationInput(term_name="도메인대기용어",definition="새 도메인 승인을 기다리는 테스트용 용어",
        domain="신규도메인6",requester="test-user",conversation_id="test-conversation"))
    assert prepared["ready"]
    result=registration.submit(prepared["confirmation_id"],"test-user","test-conversation",True,
        depends_on_domain_request_id=domain_request_id)
    term_request_id=result["request_id"]
    assert result["status"]=="WAITING_FOR_DOMAIN_APPROVAL"
    # Not actually ready for review yet, same as the word-dependency case.
    assert registration.approve(term_request_id)["code"]=="NOT_PENDING_REVIEW"
    approval=domain_registration.approve(domain_request_id)
    assert approval["approved"]
    assert term_request_id in [p["request_id"] for p in approval["promoted_terms"]]
    with db.connect() as conn:
        row=conn.execute("SELECT status FROM registration_requests WHERE id=%s",(term_request_id,)).fetchone()
    assert row["status"]=="PENDING_REVIEW"

def test_approve_domain_refuses_non_pending():
    insert_pending_domain_request("신규도메인5",status="APPROVED")
    with db.connect() as conn:
        request_id=conn.execute("SELECT id::text AS id FROM domain_requests WHERE code='신규도메인5'").fetchone()["id"]
    assert domain_registration.approve(request_id)=={"approved":False,"code":"NOT_PENDING_REVIEW","status":"APPROVED"}

def test_reject_domain():
    insert_pending_domain_request("신규도메인6")
    with db.connect() as conn:
        request_id=conn.execute("SELECT id::text AS id FROM domain_requests WHERE code='신규도메인6'").fetchone()["id"]
    assert domain_registration.reject(request_id)=={"rejected":True,"request_id":request_id,"code":"신규도메인6"}
    assert domain_registration.reject(request_id)=={"rejected":False,"code":"REQUEST_NOT_FOUND_OR_NOT_PENDING"}

def test_sample_rows_rejects_unlisted_table_or_column():
    assert mock_operations.sample_rows("pg_user","usename")=={"ok":False,"error":"UNKNOWN_TABLE_OR_COLUMN"}
    assert mock_operations.sample_rows("mockops_customers","id")=={"ok":False,"error":"UNKNOWN_TABLE_OR_COLUMN"}

def test_sample_rows_returns_seeded_synthetic_data():
    seed_mockops()
    result=mock_operations.sample_rows("mockops_customers","resident_number",limit=3)
    assert result["ok"] and len(result["sample"])==3

def test_domain_request_requires_auth(api_client):
    resp=api_client.post("/admin/domain-requests",json={"code":"신규도메인7"})
    assert resp.status_code==401

def test_domain_request_success_then_visible_in_own_list(api_client):
    _create_active_admin()
    api_client.post("/admin/auth/login",json={"username":"admin1","password":"adminpass123"})
    resp=api_client.post("/admin/domain-requests",json={
        "code":"신규도메인8","domain_group":"금액","data_type":"NUMBER"})
    assert resp.status_code==200 and resp.json()["status"]=="PENDING_REVIEW"
    listing=api_client.get("/admin/domain-requests")
    assert any(r["code"]=="신규도메인8" for r in listing.json()["requests"])

def test_domain_request_duplicate_code_rejected_via_api(api_client):
    _create_active_admin()
    api_client.post("/admin/auth/login",json={"username":"admin1","password":"adminpass123"})
    payload={"code":"신규도메인9","domain_group":"금액","data_type":"NUMBER"}
    assert api_client.post("/admin/domain-requests",json=payload).status_code==200
    second=api_client.post("/admin/domain-requests",json=payload)
    assert second.status_code==409 and second.json()["code"]=="PENDING_REQUEST_ALREADY_EXISTS"

def test_domain_request_list_scoped_to_owner(api_client):
    from starlette.testclient import TestClient
    from term_service.tools import mcp
    _create_active_admin("admin-a","adminpass123","관리자A")
    _create_active_admin("admin-b","adminpass123","관리자B")
    api_client.post("/admin/auth/login",json={"username":"admin-a","password":"adminpass123"})
    api_client.post("/admin/domain-requests",json={"code":"신규도메인10","domain_group":"금액","data_type":"NUMBER"})
    other=TestClient(mcp.streamable_http_app())
    other.post("/admin/auth/login",json={"username":"admin-b","password":"adminpass123"})
    other.post("/admin/domain-requests",json={"code":"신규도메인11","domain_group":"금액","data_type":"NUMBER"})
    listing_a=api_client.get("/admin/domain-requests").json()["requests"]
    assert any(r["code"]=="신규도메인10" for r in listing_a)
    assert not any(r["code"]=="신규도메인11" for r in listing_a)

def test_domain_request_invalid_fields_rejected(api_client):
    _create_active_admin()
    api_client.post("/admin/auth/login",json={"username":"admin1","password":"adminpass123"})
    resp=api_client.post("/admin/domain-requests",json={"domain_group":"금액"})
    assert resp.status_code==400 and resp.json()["error"]=="INVALID_FIELDS"

def test_term_request_requires_auth(api_client):
    resp=api_client.post("/admin/term-requests",json={"term_name":"신규용어","definition":"테스트","domain":"수N7"})
    assert resp.status_code==401

def test_term_request_word_gap_rejected_without_calling_llm(api_client):
    # word_lookup only knows "일일" - "일일측정계기" has a real gap ("측정계기"), so
    # this must be rejected by quick_registration's own segment_words check before
    # registration.prepare() (and its paid LLM comparison calls) ever runs.
    insert_standard_word("일일","DAILY")
    _create_active_admin()
    api_client.post("/admin/auth/login",json={"username":"admin1","password":"adminpass123"})
    resp=api_client.post("/admin/term-requests",json={"term_name":"일일측정계기","definition":"테스트 정의입니다","domain":"수N7"})
    assert resp.status_code==422
    body=resp.json()
    assert body["error"]=="WORD_GAP_REQUIRES_REGISTRATION" and body["gaps"]

def test_term_request_overlong_synonym_returns_400_not_500(api_client):
    # 회귀: RegistrationInput의 synonyms field_validator가 던지는 ValueError가 pydantic errors()의
    # ctx에 객체로 실려, INVALID_FIELDS 응답을 JSON으로 만들 때 TypeError -> 500이 되던 문제.
    _create_active_admin()
    api_client.post("/admin/auth/login",json={"username":"admin1","password":"adminpass123"})
    resp=api_client.post("/admin/term-requests",json={"term_name":"신규용어","definition":"테스트 정의입니다",
        "domain":"수N7","synonyms":["가"*101]})
    assert resp.status_code==400
    body=resp.json()
    assert body["error"]=="INVALID_FIELDS"
    assert any(d["loc"][0]=="synonyms" for d in body["detail"])

def test_invalid_fields_detail_is_json_safe_and_does_not_echo_input():
    # 응답에 사용자가 보낸 원문(input)을 되돌려 싣지 않는다 - 정의는 최대 4000자라 불필요하게 크고,
    # 클라이언트가 쓰는 건 loc/msg뿐이다.
    from pydantic import ValidationError
    from term_service.admin_api import _validation_detail
    from term_service.schemas import RegistrationInput
    import json
    try:
        RegistrationInput(term_name="가나다",definition="충분히 긴 정의입니다",domain="d",requester="x",
            conversation_id="c",synonyms=["가"*101])
    except ValidationError as exc:
        detail=_validation_detail(exc)
    json.dumps(detail)
    assert detail and all({"loc","msg","type"}<=set(d) for d in detail)
    assert not any("input" in d or "ctx" in d for d in detail)

def test_term_request_invalid_fields_rejected(api_client):
    _create_active_admin()
    api_client.post("/admin/auth/login",json={"username":"admin1","password":"adminpass123"})
    resp=api_client.post("/admin/term-requests",json={"definition":"테스트"})
    assert resp.status_code==400 and resp.json()["error"]=="INVALID_FIELDS"

def test_check_term_name_requires_auth(api_client):
    resp=api_client.get("/admin/term-requests/check-name",params={"term_name":"아무이름"})
    assert resp.status_code==401

def test_check_term_name_available_for_new_name(api_client):
    _create_active_admin()
    api_client.post("/admin/auth/login",json={"username":"admin1","password":"adminpass123"})
    resp=api_client.get("/admin/term-requests/check-name",params={"term_name":"전혀새로운용어명"})
    assert resp.status_code==200
    body=resp.json()
    assert body["ok"] and body["status"]=="available"

def test_check_term_name_exact_match(api_client,catalog):
    _create_active_admin()
    api_client.post("/admin/auth/login",json={"username":"admin1","password":"adminpass123"})
    resp=api_client.get("/admin/term-requests/check-name",params={"term_name":"일일섭취칼로리"})
    body=resp.json()
    assert body["status"]=="exact_match"
    assert body["matched"]["name"]=="일일섭취칼로리"

def test_check_term_name_invalid_mechanical(api_client):
    _create_active_admin()
    api_client.post("/admin/auth/login",json={"username":"admin1","password":"adminpass123"})
    resp=api_client.get("/admin/term-requests/check-name",params={"term_name":"값"})
    body=resp.json()
    assert body["status"]=="invalid" and body["message"]

def test_check_term_name_pending(api_client):
    _create_active_admin()
    api_client.post("/admin/auth/login",json={"username":"admin1","password":"adminpass123"})
    with db.connect() as conn:
        conn.execute("INSERT INTO domains(code,description,source) VALUES('수N7','테스트 숫자 도메인','TEST') ON CONFLICT DO NOTHING")
    prepared=registration.prepare(RegistrationInput(term_name="검토대기용어신청",
        definition="전혀 다른 개념을 가리키는 완전히 독립적인 정의 문장입니다",domain="수N7",
        requester="test-user",conversation_id="test-conversation"))
    registration.submit(prepared["confirmation_id"],"test-user","test-conversation",True)
    resp=api_client.get("/admin/term-requests/check-name",params={"term_name":"검토대기용어신청"})
    assert resp.json()["status"]=="pending"

def test_check_term_name_word_gap_is_not_reported_as_available(api_client):
    # 회귀: 사전에 없는 단어가 섞인 이름("가드레일"처럼)을 check-name이 "사용 가능"(초록)이라고
    # 답하고 제출에서야 WORD_GAP_REQUIRES_REGISTRATION으로 거절되던 불일치. 두 경로가 같은
    # 판정을 해야 한다 - 그렇지 않으면 이후 정의/도메인/약어 추천도 등록 못 할 이름에 대해 돈다.
    insert_standard_word("일일","DAILY")
    _create_active_admin()
    api_client.post("/admin/auth/login",json={"username":"admin1","password":"adminpass123"})
    resp=api_client.get("/admin/term-requests/check-name",params={"term_name":"일일측정계기"})
    body=resp.json()
    assert body["status"]=="word_gap"
    assert body["gaps"] and "측정계기" in "".join(body["gaps"])
    assert "단어 신청" in body["message"]

def test_check_term_name_fully_decomposable_name_stays_available(api_client):
    insert_standard_word("일일","DAILY")
    insert_standard_word("측정","MSR")
    _create_active_admin()
    api_client.post("/admin/auth/login",json={"username":"admin1","password":"adminpass123"})
    resp=api_client.get("/admin/term-requests/check-name",params={"term_name":"일일측정"})
    assert resp.json()["status"]=="available"

def test_check_name_verdict_agrees_with_submit_word_gap_check(api_client):
    # check-name이 available이라고 한 이름은 제출 쪽 표준단어 검사(prepare_term)에서도 갭으로
    # 걸리면 안 되고, word_gap이라고 한 이름은 제출에서도 같은 갭으로 걸려야 한다.
    from term_service import quick_registration
    insert_standard_word("일일","DAILY")
    insert_standard_word("측정","MSR")
    _create_active_admin()
    api_client.post("/admin/auth/login",json={"username":"admin1","password":"adminpass123"})
    for name in ["일일측정","일일측정계기","가드레일","측정일일"]:
        status=api_client.get("/admin/term-requests/check-name",params={"term_name":name}).json()["status"]
        has_gap=quick_registration.find_word_gaps(name) is not None
        assert (status=="word_gap")==has_gap,(name,status,has_gap)

def test_suggest_definition_route_requires_auth(api_client):
    resp=api_client.get("/admin/term-requests/suggest-definition",params={"term_name":"아무이름"})
    assert resp.status_code==401

def test_suggest_definition_route_rejects_invalid_clarification_history(api_client):
    _create_active_admin()
    api_client.post("/admin/auth/login",json={"username":"admin1","password":"adminpass123"})
    resp=api_client.get("/admin/term-requests/suggest-definition",
        params={"term_name":"아무이름","clarification_history":"이건 JSON이 아님"})
    assert resp.status_code==400 and resp.json()["error"]=="INVALID_CLARIFICATION_HISTORY"

def test_suggest_definition_route_passes_clarification_history_through(api_client,monkeypatch):
    # A real live bug: clicking an ambiguous option's label used to be written straight into
    # the definition field verbatim, instead of being fed back for an actual definition
    # sentence (mirrors conversation.py's set_definition, which never treats an option pick
    # as the final definition either). This checks the route wiring carries the history
    # through to suggest_definition() rather than re-verifying suggest_definition() itself
    # (already covered elsewhere).
    # admin_api.py's route does a LOCAL import (`from .definition_suggestion import
    # suggest_definition` inside the function body, re-resolved on every call) rather than a
    # module-level one, so the source module's attribute must be patched, not admin_api's.
    import json
    import term_service.definition_suggestion as definition_suggestion_module
    captured={}
    def fake_suggest_definition(term_name,clarification_history=None):
        captured["term_name"]=term_name
        captured["clarification_history"]=clarification_history
        return DefinitionSuggestionResult(ambiguous=False,definition="반영된 정의",rationale="",method="test_stub")
    monkeypatch.setattr(definition_suggestion_module,"suggest_definition",fake_suggest_definition)
    _create_active_admin()
    api_client.post("/admin/auth/login",json={"username":"admin1","password":"adminpass123"})
    history=[{"question":"의미는 어떤 것인가요?","answer":"변경 이후에 할당된 주소 코드"}]
    resp=api_client.get("/admin/term-requests/suggest-definition",
        params={"term_name":"변경주소코드","clarification_history":json.dumps(history,ensure_ascii=False)})
    assert resp.status_code==200
    body=resp.json()
    assert body["definition"]=="반영된 정의"

def test_suggest_followups_route_requires_params(api_client):
    _create_active_admin()
    api_client.post("/admin/auth/login",json={"username":"admin1","password":"adminpass123"})
    resp=api_client.get("/admin/term-requests/suggest-followups",params={"term_name":"이름만있음"})
    assert resp.status_code==400 and resp.json()["error"]=="TERM_NAME_AND_DEFINITION_REQUIRED"

def test_word_request_requires_auth(api_client):
    resp=api_client.post("/admin/word-requests",json={"word_name":"새단어","definition":"테스트","english_abbr":"NEW"})
    assert resp.status_code==401

def test_word_request_success_then_same_abbr_rejected(api_client):
    _create_active_admin()
    api_client.post("/admin/auth/login",json={"username":"admin1","password":"adminpass123"})
    payload={"word_name":"새표준단어","definition":"테스트 정의입니다","english_abbr":"NEWSTD"}
    first=api_client.post("/admin/word-requests",json=payload)
    assert first.status_code==200 and first.json()["status"]=="PENDING_REVIEW"
    second=api_client.post("/admin/word-requests",json=payload)
    assert second.status_code==409 and second.json()["error"]=="ABBREVIATION_ALREADY_USED"

def test_word_request_same_name_different_abbr_rejected_as_pending_duplicate(api_client):
    _create_active_admin()
    api_client.post("/admin/auth/login",json={"username":"admin1","password":"adminpass123"})
    api_client.post("/admin/word-requests",json={"word_name":"새표준단어2","definition":"테스트 정의입니다","english_abbr":"AAA"})
    second=api_client.post("/admin/word-requests",json={"word_name":"새표준단어2","definition":"테스트 정의입니다","english_abbr":"BBB"})
    assert second.status_code==409 and second.json()["error"]=="PENDING_REQUEST_ALREADY_EXISTS"

def test_word_request_exact_match_against_live_catalog_rejected(api_client):
    insert_standard_word("이미있는단어","EXIST")
    _create_active_admin()
    api_client.post("/admin/auth/login",json={"username":"admin1","password":"adminpass123"})
    resp=api_client.post("/admin/word-requests",json={"word_name":"이미있는단어","definition":"테스트 정의입니다","english_abbr":"DUP"})
    assert resp.status_code==409 and resp.json()["error"]=="EXACT_MATCH"

def test_word_request_invalid_fields_rejected(api_client):
    _create_active_admin()
    api_client.post("/admin/auth/login",json={"username":"admin1","password":"adminpass123"})
    resp=api_client.post("/admin/word-requests",json={"definition":"테스트"})
    assert resp.status_code==400 and resp.json()["error"]=="INVALID_FIELDS"

@pytest.mark.skipif(os.getenv("RUN_LLM_TESTS")!="1",reason="Explicit low-volume paid API smoke test")
def test_real_llm_definition_comparison(catalog):
    same=compare("하루권장칼로리","건강한 생활을 유지하기 위해 개인에게 권장하는 하루 에너지 섭취 기준량",catalog["일일권장열량"])
    different=compare("일일권장칼로리","건강 유지를 위해 하루에 섭취하도록 권장되는 에너지 기준량",catalog["일일섭취칼로리"])
    assert same.method=="structured_llm"
    assert same.relation in {"SAME_MEANING","UNCERTAIN"}
    assert different.method=="structured_llm"
    assert different.relation in {"RELATED_BUT_DISTINCT","UNCERTAIN"}
    print("LLM evidence:",same.model_dump(),different.model_dump())

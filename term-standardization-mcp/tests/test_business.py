import os
from concurrent.futures import ThreadPoolExecutor
import pytest
from term_service import db, registration, conversation
from term_service.naming import validate, morphology
from term_service.search import search, domain_usage, validate_name
from term_service.schemas import RegistrationInput
from term_service.comparison import compare

@pytest.mark.parametrize("name",["일일권장칼로리","체질량지수(BMI)","나이","국가"])
def test_valid_names(name):
    assert validate(name).valid

@pytest.mark.parametrize("name",["BMI","123","!!","가","가"*21,"용어를","등록해주세요"])
def test_invalid_names(name):
    assert not validate(name).valid

def test_real_morphology():
    assert len(morphology("일일권장칼로리")["morphemes"])>=3

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

def test_multiturn_help_does_not_become_definition():
    with db.connect() as conn:
        conn.execute("INSERT INTO domains(code,description,source) VALUES('수N7','테스트 숫자 도메인','TEST')")
    def apply(revision,intent,value="",confirmed=False):
        return conversation.apply("conversation","user",revision,{"intent":intent,"value":value,"confirmed":confirmed})
    assert apply(0,"propose_term","일일권장칼로리")["state"]["stage"]=="awaiting_term_confirm"
    assert apply(1,"confirm_term",confirmed=True)["state"]["stage"]=="awaiting_domain_choice"
    assert apply(2,"set_domain","수N7")["state"]["stage"]=="awaiting_definition"
    result=apply(3,"show_candidates","잠깐, 기존 용어 정의 다시 보여줘")
    assert "definition" not in result["state"]
    assert apply(4,"set_definition","하루에 섭취하도록 권장하는 에너지 기준량")["state"]["stage"]=="awaiting_confirm"
    assert apply(5,"help")["state"]["stage"]=="awaiting_confirm"
    assert apply(6,"confirm_registration",confirmed=True)["state"]["stage"]=="submitted"
    assert not apply(6,"confirm_registration",confirmed=True)["applied"]

@pytest.mark.skipif(os.getenv("RUN_LLM_TESTS")!="1",reason="Explicit low-volume paid API smoke test")
def test_real_llm_definition_comparison(catalog):
    same=compare("하루권장칼로리","건강한 생활을 유지하기 위해 개인에게 권장하는 하루 에너지 섭취 기준량",catalog["일일권장열량"])
    different=compare("일일권장칼로리","건강 유지를 위해 하루에 섭취하도록 권장되는 에너지 기준량",catalog["일일섭취칼로리"])
    assert same.method=="structured_llm"
    assert same.relation in {"SAME_MEANING","UNCERTAIN"}
    assert different.method=="structured_llm"
    assert different.relation in {"RELATED_BUT_DISTINCT","UNCERTAIN"}
    print("LLM evidence:",same.model_dump(),different.model_dump())

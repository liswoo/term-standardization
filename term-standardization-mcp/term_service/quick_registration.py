"""직접입력 폼(챗봇 대화 없이)으로 용어를 신청하는 경로 - "표준 데이터 조회" 화면의
"용어 신청" 탭 전용. registration.py의 prepare()/submit()을 그대로 재사용하므로
임베딩 기반 의미비교·가이드라인 준수 검사는 챗봇 경로와 완전히 동일하게 실행된다
(단순 존재확인만 하는 domain_registration.py와 다른 지점).

한 가지만 챗봇과 달리 이 경로에서 직접 재현한다: conversation.py의 confirm_term이
registration.prepare()를 부르기 *전에* 하는 표준단어 완전분해 체크(단어 gap 탐지).
등록되지 않은 단어를 포함한 용어명은 챗봇의 단어등록 서브플로우(단어 하나씩 등록 후
재개) 없이는 이 1회성 폼에서 처리할 수 없으므로, 그 경우 등록을 진행하지 않고
어떤 부분이 비표준단어인지 알려서 "단어 신청" 탭을 먼저 쓰도록 안내한다.
"""
from . import db, registration
from .naming import segment_words, unmatched_spans
from .schemas import RegistrationInput

def _word_lookup():
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT normalized_name,name,english_abbr FROM standard_words WHERE status='ACTIVE'").fetchall()
    return {r["normalized_name"]: r for r in rows}

def prepare_term(payload: RegistrationInput):
    word_lookup = _word_lookup()
    if word_lookup:
        _, full_match = segment_words(payload.term_name, word_lookup)
        if not full_match:
            gaps = unmatched_spans(payload.term_name, word_lookup)
            return {"ready": False, "code": "WORD_GAP_REQUIRES_REGISTRATION", "gaps": gaps}
    return registration.prepare(payload)

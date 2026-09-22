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

def find_word_gaps(term_name: str):
    """용어명이 표준단어 사전으로 완전분해되는지 - 안 되면 사전에 없는 부분(gap) 목록, 되면 None.

    제출(prepare_term)과 입력 중 이름 확인(admin_api의 check-name)이 **같은 함수**를 써서 같은
    판정을 하게 한다. check-name이 이 검사를 빠지고 "사용 가능"이라고 답했다가 제출에서야
    거절되던 불일치(2026-09-22, "가드레일")가 있었다 - 이 판정을 바꾸면 두 경로가 함께 바뀐다.
    사전이 비어 있으면(새 설치/시나리오 카탈로그) "검사 불가"이지 "전부 gap"이 아니므로 None.
    DB 조회 1회 + 문자열 처리뿐이라 LLM/임베딩 호출이 없다(입력 중 반복 호출해도 안전).
    """
    word_lookup = _word_lookup()
    if not word_lookup:
        return None
    _, full_match = segment_words(term_name, word_lookup)
    if full_match:
        return None
    # unmatched_spans는 형태소 경계를 지키는 더 엄격한 스캔이라 비어서 나올 수도 있다 -
    # 그래도 완전분해 실패라는 판정은 유효하므로 이름 전체를 gap으로 보고한다.
    return unmatched_spans(term_name, word_lookup) or [term_name]

def word_gap_message(gaps: list[str]) -> str:
    return f'다음 부분이 아직 표준단어로 등록되지 않았습니다: {", ".join(gaps)}. "단어 신청" 탭에서 먼저 등록해주세요.'

def prepare_term(payload: RegistrationInput):
    gaps = find_word_gaps(payload.term_name)
    if gaps is not None:
        return {"ready": False, "code": "WORD_GAP_REQUIRES_REGISTRATION", "gaps": gaps,
                "message": word_gap_message(gaps)}
    return registration.prepare(payload)

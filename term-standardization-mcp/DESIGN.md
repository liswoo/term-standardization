# 구현 설계 및 계약

> **더 상세하고 최신인 버전은 [../docs/reference.html](../docs/reference.html)입니다** — 이 파일은 아래 내용이 작성된 시점(22개 도구) 기준이라 지금(29개)과 어긋나 있습니다. 새로 확인할 땐 그쪽을 보세요. 왜 이렇게 만들었는지, 반복해서 발견된 패턴, 미해결 이슈는 저장소 루트의 [../CLAUDE.md](../CLAUDE.md)를 먼저 보세요.

## 기존 구조 활용

`server.py`의 MCPServer와 decorator 등록 체계를 유지했습니다. 이전 네 Tool은 호환 이름을 유지하되 `register_term`은 즉시 저장하지 않고 CONFIRMATION_FLOW_REQUIRED를 반환합니다. 원래 Dify workflow의 무확인 등록을 방지합니다.

## 모듈

| 모듈 | 책임 |
|---|---|
| naming.py | Kiwi 형태소 분석, 명명 규칙(길이/문자종류/조사), `strip_trailing_particle`(결정론적 조사 제거) |
| search.py / embeddings.py | 정규화 RDB 검색(trigram+명사토큰), 로컬 임베딩(multilingual-e5-small)+pgvector 코사인 검색, 후보 병합·중복제거 |
| guideline.py | `standard_guide.md`를 벡터화한 `guideline_chunks` 기반 RAG 준수 검사. 형태소 규칙은 코드가, 의미 판단(포괄적 단어 등)만 이 모듈이 담당 |
| abbreviation.py | 영문 약어 추천(RAG+기존 약어 일관성)과 형식/고유성 검증 |
| definition_suggestion.py | 정의 초안 제안. 이름이 진짜 애매하면(카탈로그 내 이미 갈라진 개념과 겹칠 때) 추측 대신 확인 질문+후보를 먼저 냄 |
| comparison.py | 기존 용어와의 정의 비교(SAME_MEANING/RELATED_BUT_DISTINCT/UNCERTAIN), 콘텐츠 기반 캐시 |
| registration.py | 검증 스냅샷(`prepare`), 최종 확인(`submit`), 멱등 승인 대기 저장, 검토 대기 중복 조회(`find_pending`) |
| conversation.py | Dify가 해석한 의도의 상태 전이(`transition`)와 revision 충돌 검출(`apply`). 단계 순서는 CLAUDE.md 참고 |
| tools.py / schemas.py | MCP 등록(22개 도구), 입력 검증, 구조화 결과 |
| db.py / schema.sql | 별도 DB 연결, 마이그레이션, 카탈로그 변경 감지(`catalog_fingerprint`) |

## MCP 도구 계약 (22개, `term_service/tools.py`)

| Tool | 입력 | 결과 |
|---|---|---|
| analyze_morphology | text | 형태소·품사·위치 |
| validate_term_name | term | valid, violations, suggestions, morphemes |
| search_standard_terms | term, definition?, limit | match_type, exact/synonym/semantic/lexical_matches, candidates, warnings |
| search_similar_terms_vector | query, top_k? | pgvector 코사인 검색만 노출하는 호환용 도구 |
| search_similar_terms_rdb | query | trigram/명사토큰 검색만 노출하는 호환용 도구 |
| get_standard_term | term_id | 이름·정의·도메인·동의어·영문약어·출처 |
| analyze_domain_usage | candidate_term, similar_term_ids | recommended_domain, distribution, evidence, sample_size (증거 없으면 추천 안 냄) |
| list_data_domains | 없음 | 도메인 코드·설명·출처 |
| list_terms | limit? | 승인된 용어 + 반려 아닌 신청건 병합, 대시보드용 |
| compare_term_definition | new_term, new_definition, existing_term_id | relation, confidence, reason, differences, recommended_action |
| prepare_term_registration | term_name, definition, domain, requester, conversation_id, synonyms? | ready, confirmation_id, payload, assessment, expires_at |
| create_term_registration_request | confirmation_id, requester, conversation_id, confirmed, english_abbr? | created, request_id, status, created_at |
| check_term_guideline | term_name | RAG 준수 검사 결과 + 근거 발췌 |
| suggest_english_abbreviation | term_name | 추천 약어 + 근거 |
| validate_english_abbreviation | abbreviation | 형식·고유성 검증 결과 |
| cancel_term_registration | requester, conversation_id | 미제출 확인건 무효화 |
| get_registration_request | request_id, requester | 소유자 본인의 신청 조회 |
| register_term | standard_name, definition, synonyms? | 레거시 안전 래퍼(CONFIRMATION_FLOW_REQUIRED) |
| terminology_health | 없음 | 설정·카탈로그 카운트 상태 |
| get_conversation_state | conversation_id, requester | state, revision |
| apply_conversation_action | conversation_id, requester, expected_revision, intent, value?, confirmed? | 개별 필드로 액션 전달하는 버전 |
| apply_dify_turn | conversation_id, requester, action_json | applied, state, revision, next_action 또는 error |

`action_json`은 intent/value/confirmed/expected_revision의 JSON입니다. revision은 정수, confirmed는 진위값이어야 합니다. Dify Tool 결과는 `json` 출력을 참조합니다(구조화 MCP 응답에서는 `text`가 비어있음).

**`registration_requests.status`에 `APPROVED`/`REJECTED`가 스키마상 정의되어 있지만, 그 상태로 전이시키는 도구가 없습니다** — 관리자 승인 플로우는 아직 구현되지 않았습니다(CLAUDE.md "다음 작업 후보" 1번).

## 판정 기준

EXACT_MATCH는 NFC·공백제거·casefold 후 일치, SYNONYM_MATCH는 동일하게 정규화한 등록된 동의어와의 일치입니다. `conversation.py`의 `confirm_term`은 이 둘을 **동일하게 즉시 차단**합니다(동의어는 원본 용어와 의미가 같으므로). 검색 장애/빈 카탈로그는 UNDETERMINED로 NEW_TERM과 구분합니다.

비교는 정의의 정규화 일치를 먼저 판정하고, 그 외는 실제 LLM(`compare()`)에 보냅니다. UNCERTAIN은 별개 개념이라 단정하지 않습니다. 정의 비교 LLM이 반환하는 confidence는 자기평가이며 보정된 확률이 아닙니다.

## Dify 지식

MCP 자체 pgvector(`standard_terms`, `guideline_chunks`)와 Dify 자체 지식베이스(Weaviate, `sync_dify_knowledge.py`가 업로드)는 완전히 별개의 인덱스입니다. 전자는 업무 판정 기준, 후자는 `show_candidates`/`help` 의도일 때만 노출되는 보조 참고 자료입니다. 통합 단일 인덱스화는 하지 않았습니다(의도적 — CLAUDE.md 참고).

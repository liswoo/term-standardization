# 구현 설계 및 계약

## 기존 구조 활용

`server.py`의 MCPServer와 decorator 등록 체계를 유지했습니다. 기존 파일은 `backups/server.skeleton.py`에 보관했습니다. 이전 네 Tool은 호환 이름을 유지하되 `register_term`은 즉시 저장하지 않고 CONFIRMATION_FLOW_REQUIRED를 반환합니다. 원래 Dify workflow의 무확인 등록을 방지합니다.

## 모듈

| 모듈 | 책임 |
|---|---|
| naming.py | Kiwi 형태소 분석, 명명 규칙, 실제 약어 사전 기반 수정 후보 |
| search.py / embeddings.py | 정규화 RDB 검색, 실제 로컬 임베딩/pgvector, 후보 병합 |
| comparison.py | 실제 정의 조회 및 구조화 LLM 비교, 콘텐츠 기반 캐시 |
| registration.py | 검증 스냅샷, 최종 확인, 멱등 승인 대기 저장 |
| conversation.py | Dify가 해석한 의도의 상태 전이와 revision 충돌 검출 |
| tools.py / schemas.py | MCP 등록, 입력 검증, 구조화 결과 |
| db.py / schema.sql | 별도 DB 연결, 마이그레이션, 카탈로그 변경 감지 |

## 주요 Tool 계약

| Tool | 입력 | 결과 |
|---|---|---|
| analyze_morphology | term | 실제 형태소·품사 |
| validate_term_name | term | valid, violations, suggestions, morphemes |
| search_standard_terms | term, definition?, limit | match_type, exact/synonym/semantic/lexical_matches, candidates, warnings |
| get_standard_term | term_id | 실제 이름·정의·도메인·동의어·출처 |
| analyze_domain_usage | candidate_term, similar_term_ids | recommended_domain, distribution, evidence, sample_size |
| list_data_domains | 없음 | 실제 도메인 코드·설명·출처 |
| compare_term_definition | new_term, new_definition, existing_term_id | relation, confidence, reason, differences, recommended_action |
| prepare_term_registration | term_name, definition, domain, requester, conversation_id, synonyms? | ready, confirmation_id, payload, assessment, expires_at |
| create_term_registration_request | confirmation_id, requester, conversation_id, confirmed | created, request_id, status, created_at |
| get_conversation_state | conversation_id, requester | state, revision |
| apply_dify_turn | conversation_id, requester, action_json | applied, state, revision, next_action 또는 error |

`action_json`は intent/value/confirmed/expected_revision の JSON。revisionは整数、confirmedは真偽値が必要です。DifyのTool結果は `json` 出力を参照します（構造化MCP応答では `text` が空になるため）。

EXACT_MATCHはNFC・空白除去・casefold後の一致、SYNONYM_MATCHは同様に正規化した登録済み同義語との一致です。「事実上同義」は未登録の文字列類似だけで確定せずベクトル候補の定義比較に送ります。検索障害/空カタログはUNDETERMINEDとしてNEW_TERMと区別します。

比較は同一定義の正規化一致を先に判定し、それ以外を実際のLLMに送ります。UNCERTAINは別概念と断定しません。定義比較のLLMが返すconfidenceは自己評価であり校正済み確率ではありません。

## Dify 知識

独立した新規知識を作り、12文書を高品質インデックス化しました。Chatflowに実際の知識検索ノードを追加しました。MCPのローカルベクトル検索とDifyの知識検索は別インデックスです。前者は業務判定、後者は会話の補助情報として利用します。統合による単一インデックス化は未実装です。

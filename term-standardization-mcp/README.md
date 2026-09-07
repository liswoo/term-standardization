# 용어표준화 MCP

기존 Python MCPServer 스켈레톤과 `@mcp.tool()` 등록 방식을 유지하면서 실제 조회·검증·저장 로직을 추가했습니다. 서버는 Python 프로세스(8100), 용어 DB는 별도 PostgreSQL/pgvector 컨테이너(55432)입니다. Dify 이미지를 다시 빌드할 필요는 없습니다.

## 현재 구성

- Dify 앱: **용어표준화-대화형(시나리오)**. 기존 **용어표준화-테스트**는 보존했습니다.
- Dify 지식: **용어표준화-시나리오데이터(가상)**, 문서 12건. 기존 다른 지식은 수정하지 않았습니다.
- 원본 데이터: `data/scenario_catalog.json`, 가상 용어 12건 및 도메인 4건. 공식 표준 데이터가 아닙니다.
- RDB: 정규화 이름/동의어 일치, PostgreSQL trigram 및 Kiwi 명사 토큰 검색.
- 벡터: 로컬 multilingual-e5-small 임베딩(384차원) + pgvector cosine 검색. 임베딩 자체는 외부 API 비용이 없습니다.
- 정의 비교: Dify에 등록한 OpenAI 자격증명을 Windows DPAPI로 보호하여 gpt-4o-mini 구조화 응답을 호출합니다. 실패하거나 낮은 신뢰도이면 UNCERTAIN입니다.
- Dify 지식 검색은 text-embedding-3-small을 사용합니다. Dify의 의도 해석/설명 생성과 이 임베딩, 정의 비교에는 OpenAI API 사용료가 발생합니다.

## 실행 및 수정

PowerShell에서 이 프로젝트 폴더로 이동한 후:

```powershell
./start.ps1
# Python 코드 수정 후
./start.ps1 -Restart
.venv/Scripts/python manage.py health
```

Docker Desktop이 실행되어 있어야 합니다. DB 볼륨은 유지됩니다. MCP는 별도 Python 프로세스이므로 Windows 재부팅 후 `start.ps1` 실행이 필요합니다. Dify 연결 주소는 `http://host.docker.internal:8100/mcp`입니다. 이 주소를 외부 공개 터널로 직접 노출할 필요는 없습니다.

```powershell
# 의존성 설치 / DB 초기화
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python manage.py init-db
# 카탈로그 임포트 (동일 정규화 이름이면 갱신)
.venv/Scripts/python manage.py import-catalog data/scenario_catalog.json
# 새 MCP Tool 추가 후 Dify 공급자 도구 목록 갱신
.venv/Scripts/python dify_admin.py refresh
# Dify Chatflow 수정·반영 (저장된 앱 ID로 갱신)
.venv/Scripts/python build_chatflow.py
.venv/Scripts/python dify_admin.py import dify-chatflow.yaml
.venv/Scripts/python scripts/publish_chatflow.py
```

`.env`는 DB 설정, `.runtime/model-credential.dpapi`는 현재 Windows 사용자에 묶인 API 키입니다. API 키 변경 시 `link_dify_provider.py`를 다시 실행합니다. `.env`, `.runtime`, `backups`는 버전 관리에서 제외됩니다. Dify 관리 스크립트는 현재 설치본의 내부 서비스 API를 사용하므로 Dify 업그레이드 때 호환성 점검이 필요합니다.

## 역할 및 데이터 일관성

Dify는 의도 분류 → MCP 상태 전이 → 지식 검색 → 설명 생성을 수행합니다. MCP는 의도를 재해석하지 않고 검증·검색·등록 규칙을 적용합니다. 대화 상태는 MCP DB에 conversation_id/requester/revision으로 저장하여 재시작 후에도 이어집니다. 조회/도움말/취소/수정은 정의 입력과 구분됩니다.

정확한 중복·동의어 판정, 도메인 빈도 집계, 승인 대기 저장의 기준은 **MCP RDB**입니다. Dify 지식은 검색·설명용 보조 저장소입니다. RAG 검색만으로 정확한 중복 방지와 트랜잭션 저장을 대체하지 않습니다.

현재 `sync_dify_knowledge.py`는 시나리오 카탈로그의 문서를 최초 생성하고 같은 제목의 기존 문서는 건너뜁니다. **자동 양방향 동기화나 기존 문서 수정 반영은 구현하지 않았습니다.** 향후 실데이터로 전환할 때 가상 데이터 분리/교체와 RDB·지식의 갱신 정책을 함께 정해야 합니다. 승인 대기 요청은 지식/정식 용어에 자동 추가하지 않습니다.

## 등록 흐름과 제한

용어 추출 확인 → 명명 검증 → 검색 → 도메인 선택 → 정의 입력/비교 → 최종 확인 → PENDING_REVIEW 저장 순서입니다. EXACT_MATCH 및 SAME_MEANING은 차단합니다. UNCERTAIN, 미등록 도메인, 검색 장애 등은 검토 사유를 기록합니다. 별도 담당자 승인 화면/정식 승격 기능은 이번 구현 범위에 포함하지 않았습니다.

등록 전 준비 Tool이 30분 유효한 스냅샷을 생성합니다. 수정/취소/카탈로그 변경 시 재확인해야 합니다. 제출은 사용자·대화 소유권, 명시적 확인, 중복 요청을 검사합니다. Dify 시스템 변수의 사용자 ID/대화 ID를 사용하며 LLM이 사용자 신원을 만들지 않도록 구성했습니다. MCP 엔드포인트는 신뢰하는 Dify 전용 호출을 전제로 합니다.

유사도 임계값 0.85와 LLM 신뢰도는 실데이터로 보정할 필요가 있습니다. 도메인 confidence는 검색 비교군의 관측 사용 비율이며 적합성 확률이 아닙니다. LLM 설명은 변동될 수 있지만 저장/차단 규칙은 MCP가 적용합니다.

## 검증

```powershell
.venv/Scripts/python -m pytest -q
# 선택: 실제 OpenAI 호출 테스트 (소액 API 사용)
$env:RUN_LLM_TESTS='1'
.venv/Scripts/python -m pytest -q -k real_llm
# 게시된 Chatflow 실제 HTTP 대화 테스트
.venv/Scripts/python scripts/chat_http.py '일일권장칼로리를 신규 용어로 등록해줘'
```

테스트는 분리된 `terms_test` DB를 사용합니다. `chat_http.py`는 실제 시나리오 앱/운영 용어 DB를 사용하므로 최종 확인하면 테스트 승인 대기 요청이 남습니다. `test_dify_turn.py`도 동일한 HTTP 검증으로 연결됩니다.

Tool 입력 스키마는 MCP tools/list로 제공되며 주요 업무 응답 스키마는 `schemas.json`, 설계 설명은 `DESIGN.md`에 있습니다.
